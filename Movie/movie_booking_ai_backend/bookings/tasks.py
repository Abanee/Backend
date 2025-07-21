"""
Celery tasks for booking-related background processing
"""
from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from datetime import timedelta
import logging

from .models import Booking, Transaction, Refund, BookingNotification
from .utils.payment import PaymentGatewayFactory

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_booking_confirmation(self, booking_id):
    """Send booking confirmation email"""

    try:
        booking = Booking.objects.select_related(
            'user', 'showtime__movie', 'showtime__screen__cinema'
        ).prefetch_related('seats').get(id=booking_id)

        context = {
            'booking': booking,
            'user': booking.user,
            'movie': booking.showtime.movie,
            'showtime': booking.showtime,
            'cinema': booking.showtime.screen.cinema,
            'seats': booking.seats.all().order_by('row', 'number'),
            'site_name': 'Movie Booking AI',
        }

        # Render email templates
        subject = f'Booking Confirmed - {booking.booking_reference}'
        html_content = render_to_string('emails/booking_confirmation.html', context)
        text_content = render_to_string('emails/booking_confirmation.txt', context)

        # Send email
        send_mail(
            subject=subject,
            message=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[booking.user.email],
            html_message=html_content,
            fail_silently=False,
        )

        # Create notification record
        BookingNotification.objects.create(
            booking=booking,
            notification_type='booking_confirmed',
            channel='email',
            recipient=booking.user.email,
            subject=subject,
            message=text_content,
            status='sent',
            scheduled_at=timezone.now(),
            sent_at=timezone.now(),
        )

        logger.info(f"Booking confirmation sent for {booking.booking_reference}")
        return f"Confirmation email sent for booking {booking.booking_reference}"

    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found")
        return f"Booking {booking_id} not found"
    except Exception as exc:
        logger.error(f"Failed to send booking confirmation for {booking_id}: {str(exc)}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def send_cancellation_confirmation(self, booking_id):
    """Send booking cancellation confirmation email"""

    try:
        booking = Booking.objects.select_related(
            'user', 'showtime__movie', 'showtime__screen__cinema'
        ).get(id=booking_id)

        context = {
            'booking': booking,
            'user': booking.user,
            'movie': booking.showtime.movie,
            'showtime': booking.showtime,
            'cinema': booking.showtime.screen.cinema,
            'site_name': 'Movie Booking AI',
        }

        # Render email templates
        subject = f'Booking Cancelled - {booking.booking_reference}'
        html_content = render_to_string('emails/booking_cancellation.html', context)
        text_content = render_to_string('emails/booking_cancellation.txt', context)

        # Send email
        send_mail(
            subject=subject,
            message=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[booking.user.email],
            html_message=html_content,
            fail_silently=False,
        )

        # Create notification record
        BookingNotification.objects.create(
            booking=booking,
            notification_type='booking_cancelled',
            channel='email',
            recipient=booking.user.email,
            subject=subject,
            message=text_content,
            status='sent',
            scheduled_at=timezone.now(),
            sent_at=timezone.now(),
        )

        logger.info(f"Cancellation confirmation sent for {booking.booking_reference}")
        return f"Cancellation email sent for booking {booking.booking_reference}"

    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found")
        return f"Booking {booking_id} not found"
    except Exception as exc:
        logger.error(f"Failed to send cancellation confirmation for {booking_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def process_refund(self, refund_id):
    """Process refund through payment gateway"""

    try:
        refund = Refund.objects.select_related('booking', 'transaction').get(id=refund_id)

        if refund.status != 'initiated':
            logger.warning(f"Refund {refund.refund_id} is not in initiated status")
            return f"Refund {refund.refund_id} is not in initiated status"

        # Update status to processing
        refund.status = 'processing'
        refund.save()

        # Initiate refund with payment gateway
        gateway = PaymentGatewayFactory.get_gateway(refund.transaction.gateway)
        gateway_response = gateway.initiate_refund(refund.transaction, refund.refund_amount)

        # Update refund record
        refund.gateway_refund_id = gateway_response['refund_id']
        refund.gateway_response = gateway_response
        refund.status = 'completed' if gateway_response['status'] == 'processed' else 'processing'
        refund.processed_at = timezone.now()
        refund.save()

        # Send refund confirmation email
        send_refund_confirmation.delay(refund.id)

        logger.info(f"Refund processed for {refund.refund_id}")
        return f"Refund processed for {refund.refund_id}"

    except Refund.DoesNotExist:
        logger.error(f"Refund {refund_id} not found")
        return f"Refund {refund_id} not found"
    except Exception as exc:
        # Update refund status to failed
        try:
            refund = Refund.objects.get(id=refund_id)
            refund.status = 'failed'
            refund.save()
        except:
            pass

        logger.error(f"Failed to process refund {refund_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=300 * (2 ** self.request.retries))  # 5 min initial delay


@shared_task
def send_refund_confirmation(refund_id):
    """Send refund confirmation email"""

    try:
        refund = Refund.objects.select_related(
            'booking__user', 'booking__showtime__movie'
        ).get(id=refund_id)

        context = {
            'refund': refund,
            'booking': refund.booking,
            'user': refund.booking.user,
            'site_name': 'Movie Booking AI',
        }

        subject = f'Refund Processed - {refund.refund_id}'
        html_content = render_to_string('emails/refund_confirmation.html', context)
        text_content = render_to_string('emails/refund_confirmation.txt', context)

        send_mail(
            subject=subject,
            message=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[refund.booking.user.email],
            html_message=html_content,
        )

        logger.info(f"Refund confirmation sent for {refund.refund_id}")

    except Exception as e:
        logger.error(f"Failed to send refund confirmation for {refund_id}: {str(e)}")


@shared_task
def expire_pending_bookings():
    """Expire pending bookings that have passed their expiry time"""

    try:
        expired_bookings = Booking.objects.filter(
            status='pending',
            expires_at__lt=timezone.now()
        ).select_related('showtime')

        count = 0
        for booking in expired_bookings:
            # Update booking status
            booking.status = 'expired'
            booking.save()

            # Release seats
            booking.seats.update(is_available=True)

            # Create history record
            from .models import BookingHistory
            BookingHistory.objects.create(
                booking=booking,
                previous_status='pending',
                new_status='expired',
                reason='Booking expired due to timeout'
            )

            count += 1

        logger.info(f"Expired {count} pending bookings")
        return f"Expired {count} bookings"

    except Exception as e:
        logger.error(f"Failed to expire bookings: {str(e)}")
        return f"Error: {str(e)}"


@shared_task
def send_show_reminders():
    """Send show reminders 4 hours before showtime"""

    try:
        # Get bookings with shows starting in 4 hours
        reminder_time = timezone.now() + timedelta(hours=4)

        bookings = Booking.objects.filter(
            status='confirmed',
            showtime__show_date=reminder_time.date(),
            showtime__show_time__gte=reminder_time.time(),
            showtime__show_time__lt=(reminder_time + timedelta(minutes=30)).time()
        ).select_related(
            'user', 'showtime__movie', 'showtime__screen__cinema'
        ).prefetch_related('seats')

        count = 0
        for booking in bookings:
            # Check if reminder already sent
            if BookingNotification.objects.filter(
                booking=booking,
                notification_type='show_reminder',
                status='sent'
            ).exists():
                continue

            context = {
                'booking': booking,
                'user': booking.user,
                'movie': booking.showtime.movie,
                'showtime': booking.showtime,
                'cinema': booking.showtime.screen.cinema,
                'seats': booking.seats.all().order_by('row', 'number'),
                'site_name': 'Movie Booking AI',
            }

            subject = f'Show Reminder - {booking.showtime.movie.title}'
            html_content = render_to_string('emails/show_reminder.html', context)
            text_content = render_to_string('emails/show_reminder.txt', context)

            send_mail(
                subject=subject,
                message=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[booking.user.email],
                html_message=html_content,
            )

            # Create notification record
            BookingNotification.objects.create(
                booking=booking,
                notification_type='show_reminder',
                channel='email',
                recipient=booking.user.email,
                subject=subject,
                message=text_content,
                status='sent',
                scheduled_at=timezone.now(),
                sent_at=timezone.now(),
            )

            count += 1

        logger.info(f"Sent {count} show reminders")
        return f"Sent {count} show reminders"

    except Exception as e:
        logger.error(f"Failed to send show reminders: {str(e)}")
        return f"Error: {str(e)}"


@shared_task
def cleanup_expired_tokens():
    """Clean up expired booking-related tokens and notifications"""

    try:
        # Clean up old notifications (older than 30 days)
        old_notifications = BookingNotification.objects.filter(
            scheduled_at__lt=timezone.now() - timedelta(days=30)
        )
        deleted_count = old_notifications.delete()[0]

        logger.info(f"Cleaned up {deleted_count} old notifications")
        return f"Cleaned up {deleted_count} old notifications"

    except Exception as e:
        logger.error(f"Failed to cleanup expired tokens: {str(e)}")
        return f"Error: {str(e)}"
