from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import logging

from .models import Booking, Transaction, BookingHistory, Refund, CancellationPolicy
from .serializers import (
    BookingCreateSerializer, BookingSerializer, BookingDetailSerializer,
    TransactionSerializer, PaymentInitiateSerializer, PaymentConfirmSerializer,
    BookingCancelSerializer, RefundSerializer, BookingHistorySerializer
)
from movies.models import Showtime, Seat
from .utils.payment import PaymentGatewayFactory
from .tasks import send_booking_confirmation, send_cancellation_confirmation

logger = logging.getLogger(__name__)


class CreateBookingView(generics.CreateAPIView):
    """Create a new booking"""

    serializer_class = BookingCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['showtime_id'] = self.kwargs['showtime_id']
        return context

    def create(self, request, *args, **kwargs):
        showtime = get_object_or_404(Showtime, id=self.kwargs['showtime_id'])

        # Check if showtime is active and not in the past
        if not showtime.is_active:
            return Response(
                {'error': 'This showtime is not available for booking'},
                status=status.HTTP_400_BAD_REQUEST
            )

        show_datetime = timezone.make_aware(
            timezone.datetime.combine(showtime.show_date, showtime.show_time)
        )
        if show_datetime <= timezone.now():
            return Response(
                {'error': 'Cannot book seats for past showtimes'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create booking
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()

        # Log booking creation
        BookingHistory.objects.create(
            booking=booking,
            previous_status='',
            new_status='pending',
            changed_by=request.user,
            reason='Booking created'
        )

        return Response({
            'message': 'Booking created successfully',
            'booking': BookingDetailSerializer(booking).data
        }, status=status.HTTP_201_CREATED)


class UserBookingsView(generics.ListAPIView):
    """List user's bookings"""

    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ['-booked_at']

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user).select_related(
            'showtime__movie', 'showtime__screen__cinema'
        ).prefetch_related('seats')


class BookingDetailView(generics.RetrieveAPIView):
    """Booking detail view"""

    serializer_class = BookingDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user).select_related(
            'showtime__movie', 'showtime__screen__cinema'
        ).prefetch_related('seats', 'transactions', 'refunds')


class InitiatePaymentView(generics.CreateAPIView):
    """Initiate payment for a booking"""

    serializer_class = PaymentInitiateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        booking = get_object_or_404(
            Booking,
            id=self.kwargs['booking_id'],
            user=request.user
        )

        # Validate booking status
        if booking.status != 'pending':
            return Response(
                {'error': 'Payment can only be made for pending bookings'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if booking has expired
        if booking.expires_at <= timezone.now():
            booking.status = 'expired'
            booking.save()

            # Release seats
            booking.seats.update(is_available=True)

            return Response(
                {'error': 'Booking has expired'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        gateway_name = serializer.validated_data['gateway']

        try:
            # Create transaction record
            transaction_obj = Transaction.objects.create(
                booking=booking,
                gateway=gateway_name,
                amount=booking.total_amount,
                currency='INR'
            )

            # Initialize payment gateway
            payment_gateway = PaymentGatewayFactory.get_gateway(gateway_name)

            # Create payment order
            payment_data = payment_gateway.create_order(
                transaction_obj,
                return_url=serializer.validated_data.get('return_url'),
                cancel_url=serializer.validated_data.get('cancel_url')
            )

            # Update transaction with gateway response
            transaction_obj.reference_id = payment_data.get('order_id')
            transaction_obj.gateway_response = payment_data
            transaction_obj.save()

            return Response({
                'transaction': TransactionSerializer(transaction_obj).data,
                'payment_data': payment_data
            })

        except Exception as e:
            logger.error(f"Payment initiation failed for booking {booking.id}: {str(e)}")
            return Response(
                {'error': 'Payment initiation failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ConfirmPaymentView(generics.UpdateAPIView):
    """Confirm payment after gateway callback"""

    serializer_class = PaymentConfirmSerializer
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        booking = get_object_or_404(
            Booking,
            id=self.kwargs['booking_id'],
            user=request.user
        )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        transaction_id = serializer.validated_data['transaction_id']
        gateway_transaction_id = serializer.validated_data['gateway_transaction_id']
        gateway_response = serializer.validated_data['gateway_response']

        try:
            transaction_obj = Transaction.objects.get(
                transaction_id=transaction_id,
                booking=booking
            )

            # Verify payment with gateway
            payment_gateway = PaymentGatewayFactory.get_gateway(transaction_obj.gateway)
            is_valid = payment_gateway.verify_payment(
                gateway_transaction_id,
                gateway_response
            )

            if is_valid:
                # Payment successful
                transaction_obj.status = 'success'
                transaction_obj.gateway_transaction_id = gateway_transaction_id
                transaction_obj.completed_at = timezone.now()
                transaction_obj.gateway_response = gateway_response
                transaction_obj.save()

                # Update booking status
                booking.status = 'confirmed'
                booking.confirmed_at = timezone.now()
                booking.save()

                # Log status change
                BookingHistory.objects.create(
                    booking=booking,
                    previous_status='pending',
                    new_status='confirmed',
                    changed_by=request.user,
                    reason='Payment completed successfully'
                )

                # Send confirmation email (async)
                send_booking_confirmation.delay(booking.id)

                return Response({
                    'message': 'Payment confirmed successfully',
                    'booking': BookingDetailSerializer(booking).data
                })
            else:
                # Payment failed
                transaction_obj.status = 'failed'
                transaction_obj.failure_reason = 'Payment verification failed'
                transaction_obj.gateway_response = gateway_response
                transaction_obj.save()

                return Response(
                    {'error': 'Payment verification failed'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Transaction.DoesNotExist:
            return Response(
                {'error': 'Invalid transaction'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Payment confirmation failed for booking {booking.id}: {str(e)}")
            return Response(
                {'error': 'Payment confirmation failed. Please contact support.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CancelBookingView(generics.UpdateAPIView):
    """Cancel a booking and initiate refund"""

    serializer_class = BookingCancelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return get_object_or_404(
            Booking,
            id=self.kwargs['booking_id'],
            user=self.request.user
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['booking'] = self.get_object()
        return context

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        booking = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        policy = serializer.validated_data['policy']
        reason = serializer.validated_data['reason']

        try:
            # Calculate refund amount
            cancellation_fee_amount = (booking.total_amount * policy.cancellation_fee_percentage) / 100
            refund_amount = booking.total_amount - cancellation_fee_amount

            # Update booking status
            previous_status = booking.status
            booking.status = 'cancelled'
            booking.cancelled_at = timezone.now()
            booking.save()

            # Release seats
            booking.seats.update(is_available=True)

            # Log status change
            BookingHistory.objects.create(
                booking=booking,
                previous_status=previous_status,
                new_status='cancelled',
                changed_by=request.user,
                reason=reason
            )

            # Create refund record if booking was paid
            if booking.status == 'confirmed':
                successful_transaction = booking.transactions.filter(status='success').first()
                if successful_transaction:
                    refund = Refund.objects.create(
                        booking=booking,
                        transaction=successful_transaction,
                        amount=booking.total_amount,
                        refund_amount=refund_amount,
                        cancellation_fee=cancellation_fee_amount,
                        reason=reason
                    )

                    # Initiate refund with payment gateway (async)
                    from .tasks import process_refund
                    process_refund.delay(refund.id)

            # Send cancellation confirmation (async)
            send_cancellation_confirmation.delay(booking.id)

            return Response({
                'message': 'Booking cancelled successfully',
                'booking': BookingDetailSerializer(booking).data,
                'refund_amount': float(refund_amount) if refund_amount else 0,
                'cancellation_fee': float(cancellation_fee_amount)
            })

        except Exception as e:
            logger.error(f"Booking cancellation failed for booking {booking.id}: {str(e)}")
            return Response(
                {'error': 'Cancellation failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def payment_webhook(request):
    """Handle payment gateway webhooks"""

    gateway = request.GET.get('gateway', 'razorpay')

    try:
        payment_gateway = PaymentGatewayFactory.get_gateway(gateway)
        result = payment_gateway.handle_webhook(request.data, request.META)

        if result.get('success'):
            transaction_id = result.get('transaction_id')
            transaction_obj = Transaction.objects.get(transaction_id=transaction_id)
            booking = transaction_obj.booking

            # Update transaction status based on webhook
            if result.get('status') == 'success':
                transaction_obj.status = 'success'
                transaction_obj.completed_at = timezone.now()
                booking.status = 'confirmed'
                booking.confirmed_at = timezone.now()

                # Send confirmation email
                send_booking_confirmation.delay(booking.id)

            elif result.get('status') == 'failed':
                transaction_obj.status = 'failed'
                transaction_obj.failure_reason = result.get('failure_reason', 'Payment failed')

                # Release seats if payment failed
                booking.seats.update(is_available=True)

            transaction_obj.gateway_response = request.data
            transaction_obj.save()
            booking.save()

        return Response({'status': 'success'})

    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}")
        return Response({'status': 'error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BookingHistoryView(generics.ListAPIView):
    """View booking history/status changes"""

    serializer_class = BookingHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        booking_id = self.kwargs['booking_id']
        booking = get_object_or_404(Booking, id=booking_id, user=self.request.user)
        return booking.history.all().order_by('-changed_at')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def extend_booking_timer(request, booking_id):
    """Extend booking expiry timer (one-time extension)"""

    booking = get_object_or_404(
        Booking,
        id=booking_id,
        user=request.user,
        status='pending'
    )

    # Check if already extended
    if hasattr(booking, '_timer_extended'):
        return Response(
            {'error': 'Booking timer can only be extended once'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check if booking is close to expiry (within 2 minutes)
    time_remaining = (booking.expires_at - timezone.now()).total_seconds()
    if time_remaining > 120:  # More than 2 minutes remaining
        return Response(
            {'error': 'Timer extension only available when booking is about to expire'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Extend by 10 minutes
    booking.expires_at = timezone.now() + timedelta(minutes=10)
    booking._timer_extended = True
    booking.save()

    return Response({
        'message': 'Booking timer extended successfully',
        'new_expires_at': booking.expires_at
    })
