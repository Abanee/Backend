from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import Booking, Transaction, BookingHistory, Refund, CancellationPolicy
from movies.models import Showtime, Seat
from movies.serializers import ShowtimeSerializer, SeatSerializer


class SeatSelectionSerializer(serializers.Serializer):
    """Serializer for seat selection"""

    seat_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=10,
        help_text="List of seat IDs to book"
    )
    special_requests = serializers.CharField(max_length=500, required=False, allow_blank=True)


class BookingCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating bookings"""

    seat_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        min_length=1,
        max_length=10
    )

    class Meta:
        model = Booking
        fields = ['seat_ids', 'special_requests']

    def validate_seat_ids(self, value):
        """Validate seat availability"""
        showtime_id = self.context['showtime_id']
        showtime = Showtime.objects.get(id=showtime_id)

        # Check if seats exist and belong to the showtime's screen
        seats = Seat.objects.filter(
            id__in=value,
            screen=showtime.screen
        )

        if seats.count() != len(value):
            raise serializers.ValidationError("Some seats do not exist or don't belong to this screen")

        # Check seat availability
        unavailable_seats = seats.filter(
            models.Q(is_available=False) | 
            models.Q(is_blocked=True) |
            models.Q(bookings__showtime=showtime, bookings__status__in=['confirmed', 'pending'])
        )

        if unavailable_seats.exists():
            unavailable_list = [f"{seat.row}{seat.number}" for seat in unavailable_seats]
            raise serializers.ValidationError(
                f"These seats are not available: {', '.join(unavailable_list)}"
            )

        return value

    @transaction.atomic
    def create(self, validated_data):
        """Create booking with seat lock"""
        seat_ids = validated_data.pop('seat_ids')
        showtime_id = self.context['showtime_id']
        user = self.context['request'].user

        showtime = Showtime.objects.select_for_update().get(id=showtime_id)
        seats = Seat.objects.select_for_update().filter(
            id__in=seat_ids,
            screen=showtime.screen,
            is_available=True,
            is_blocked=False
        )

        # Double-check availability with lock
        if seats.count() != len(seat_ids):
            raise serializers.ValidationError("Some seats are no longer available")

        # Calculate pricing
        subtotal = sum(showtime.get_price_for_seat(seat) for seat in seats)
        tax_amount = round(subtotal * Decimal('0.18'), 2)  # 18% GST
        convenience_fee = Decimal('20.00')
        total_amount = subtotal + tax_amount + convenience_fee

        # Create booking
        booking = Booking.objects.create(
            user=user,
            showtime=showtime,
            subtotal=subtotal,
            tax_amount=tax_amount,
            convenience_fee=convenience_fee,
            total_amount=total_amount,
            expires_at=timezone.now() + timedelta(minutes=15),  # 15 min to complete payment
            **validated_data
        )

        # Add seats to booking
        booking.seats.set(seats)

        # Update seat availability (temporary lock)
        seats.update(is_available=False)

        return booking


class BookingSerializer(serializers.ModelSerializer):
    """Serializer for booking list/detail view"""

    showtime = ShowtimeSerializer(read_only=True)
    seats = SeatSerializer(many=True, read_only=True)
    seat_numbers = serializers.ReadOnlyField()
    seat_count = serializers.ReadOnlyField()

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_reference', 'showtime', 'seats', 'seat_numbers', 'seat_count',
            'subtotal', 'tax_amount', 'convenience_fee', 'total_amount',
            'status', 'booked_at', 'expires_at', 'confirmed_at', 'special_requests'
        ]
        read_only_fields = ['id', 'booking_reference', 'booked_at']


class BookingDetailSerializer(BookingSerializer):
    """Detailed serializer for booking with transaction history"""

    transactions = serializers.SerializerMethodField()
    refunds = serializers.SerializerMethodField()
    cancellation_allowed = serializers.SerializerMethodField()

    class Meta(BookingSerializer.Meta):
        fields = BookingSerializer.Meta.fields + ['transactions', 'refunds', 'cancellation_allowed']

    def get_transactions(self, obj):
        return TransactionSerializer(obj.transactions.all(), many=True).data

    def get_refunds(self, obj):
        return RefundSerializer(obj.refunds.all(), many=True).data

    def get_cancellation_allowed(self, obj):
        """Check if booking can be cancelled"""
        if obj.status not in ['confirmed', 'pending']:
            return False

        # Calculate hours before show
        show_datetime = timezone.make_aware(
            timezone.datetime.combine(obj.showtime.show_date, obj.showtime.show_time)
        )
        hours_before = (show_datetime - timezone.now()).total_seconds() / 3600

        policy = CancellationPolicy.get_applicable_policy(hours_before)
        return policy and policy.is_refundable


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for transaction model"""

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'gateway', 'gateway_transaction_id',
            'amount', 'currency', 'status', 'initiated_at', 'completed_at',
            'failure_reason'
        ]
        read_only_fields = ['id', 'transaction_id', 'initiated_at']


class PaymentInitiateSerializer(serializers.Serializer):
    """Serializer for payment initiation"""

    gateway = serializers.ChoiceField(choices=Transaction.GATEWAY_CHOICES)
    return_url = serializers.URLField(required=False)
    cancel_url = serializers.URLField(required=False)


class PaymentConfirmSerializer(serializers.Serializer):
    """Serializer for payment confirmation"""

    transaction_id = serializers.CharField()
    gateway_transaction_id = serializers.CharField()
    gateway_response = serializers.JSONField()


class BookingCancelSerializer(serializers.Serializer):
    """Serializer for booking cancellation"""

    reason = serializers.CharField(max_length=500)

    def validate(self, attrs):
        booking = self.context['booking']

        # Check if booking can be cancelled
        if booking.status not in ['confirmed', 'pending']:
            raise serializers.ValidationError("This booking cannot be cancelled")

        # Check cancellation policy
        show_datetime = timezone.make_aware(
            timezone.datetime.combine(booking.showtime.show_date, booking.showtime.show_time)
        )
        hours_before = (show_datetime - timezone.now()).total_seconds() / 3600

        policy = CancellationPolicy.get_applicable_policy(hours_before)
        if not policy or not policy.is_refundable:
            raise serializers.ValidationError("Cancellation not allowed at this time")

        attrs['policy'] = policy
        return attrs


class RefundSerializer(serializers.ModelSerializer):
    """Serializer for refund model"""

    class Meta:
        model = Refund
        fields = [
            'id', 'refund_id', 'amount', 'refund_amount', 'cancellation_fee',
            'status', 'reason', 'initiated_at', 'processed_at'
        ]
        read_only_fields = ['id', 'refund_id', 'initiated_at']


class BookingHistorySerializer(serializers.ModelSerializer):
    """Serializer for booking history"""

    changed_by_email = serializers.SerializerMethodField()

    class Meta:
        model = BookingHistory
        fields = [
            'id', 'previous_status', 'new_status', 'changed_by_email',
            'reason', 'changed_at'
        ]

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else 'System'
