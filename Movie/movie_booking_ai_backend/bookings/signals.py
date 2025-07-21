"""
Django signals for booking-related automation
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Booking, Transaction, BookingHistory


@receiver(pre_save, sender=Booking)
def track_booking_status_change(sender, instance, **kwargs):
    """Track booking status changes"""

    if instance.pk:  # Only for existing bookings
        try:
            old_instance = Booking.objects.get(pk=instance.pk)
            if old_instance.status != instance.status:
                # Status changed, create history record after save
                instance._status_changed = True
                instance._old_status = old_instance.status
        except Booking.DoesNotExist:
            pass


@receiver(post_save, sender=Booking)
def create_booking_history(sender, instance, created, **kwargs):
    """Create booking history record when status changes"""

    if created:
        # New booking created
        BookingHistory.objects.create(
            booking=instance,
            previous_status='',
            new_status=instance.status,
            reason='Booking created'
        )
    elif hasattr(instance, '_status_changed') and instance._status_changed:
        # Status changed
        BookingHistory.objects.create(
            booking=instance,
            previous_status=instance._old_status,
            new_status=instance.status,
            reason=f'Status changed from {instance._old_status} to {instance.status}'
        )

        # Clean up the temporary attributes
        delattr(instance, '_status_changed')
        delattr(instance, '_old_status')


@receiver(post_save, sender=Booking)
def handle_booking_confirmation(sender, instance, **kwargs):
    """Handle actions when booking is confirmed"""

    if instance.status == 'confirmed' and not instance.confirmed_at:
        # Booking just got confirmed
        instance.confirmed_at = timezone.now()
        instance.save(update_fields=['confirmed_at'])

        # Schedule show reminder (4 hours before show)
        from .tasks import send_show_reminders
        show_datetime = timezone.make_aware(
            timezone.datetime.combine(instance.showtime.show_date, instance.showtime.show_time)
        )
        reminder_time = show_datetime - timezone.timedelta(hours=4)

        if reminder_time > timezone.now():
            send_show_reminders.apply_async(eta=reminder_time)


@receiver(post_save, sender=Booking)
def handle_booking_cancellation(sender, instance, **kwargs):
    """Handle actions when booking is cancelled"""

    if instance.status == 'cancelled':
        # Release seats when booking is cancelled
        instance.seats.update(is_available=True)

        if not instance.cancelled_at:
            instance.cancelled_at = timezone.now()
            instance.save(update_fields=['cancelled_at'])


@receiver(post_save, sender=Transaction)
def handle_successful_payment(sender, instance, created, **kwargs):
    """Handle successful payment"""

    if instance.status == 'success' and instance.booking.status == 'pending':
        # Payment successful, confirm booking
        booking = instance.booking
        booking.status = 'confirmed'
        booking.confirmed_at = timezone.now()
        booking.save()

        # Send confirmation email (async)
        from .tasks import send_booking_confirmation
        send_booking_confirmation.delay(booking.id)


@receiver(post_save, sender=Transaction)
def handle_failed_payment(sender, instance, **kwargs):
    """Handle failed payment"""

    if instance.status == 'failed':
        booking = instance.booking

        # If no successful transactions exist, release seats
        if not booking.transactions.filter(status='success').exists():
            booking.seats.update(is_available=True)

            # Optionally extend booking timer for retry
            if booking.expires_at > timezone.now():
                booking.expires_at = timezone.now() + timezone.timedelta(minutes=15)
                booking.save()
