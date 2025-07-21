from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.auth import get_user_model
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task
def send_verification_email(user_id, token):
    """Send email verification email"""

    try:
        user = User.objects.get(id=user_id)

        subject = 'Verify your email address'
        message = render_to_string('emails/email_verification.txt', {
            'user': user,
            'token': token,
            'site_name': 'Movie Booking AI',
        })
        html_message = render_to_string('emails/email_verification.html', {
            'user': user,
            'token': token,
            'site_name': 'Movie Booking AI',
        })

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f"Verification email sent to {user.email}")
        return True

    except User.DoesNotExist:
        logger.error(f"User with id {user_id} does not exist")
        return False
    except Exception as e:
        logger.error(f"Error sending verification email: {str(e)}")
        return False


@shared_task
def send_password_reset_email(user_id, token):
    """Send password reset email"""

    try:
        user = User.objects.get(id=user_id)

        subject = 'Reset your password'
        message = render_to_string('emails/password_reset.txt', {
            'user': user,
            'token': token,
            'site_name': 'Movie Booking AI',
        })
        html_message = render_to_string('emails/password_reset.html', {
            'user': user,
            'token': token,
            'site_name': 'Movie Booking AI',
        })

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f"Password reset email sent to {user.email}")
        return True

    except User.DoesNotExist:
        logger.error(f"User with id {user_id} does not exist")
        return False
    except Exception as e:
        logger.error(f"Error sending password reset email: {str(e)}")
        return False


@shared_task
def send_booking_confirmation_email(user_id, booking_id):
    """Send booking confirmation email"""

    try:
        user = User.objects.get(id=user_id)

        # Import here to avoid circular imports
        from bookings.models import Booking
        booking = Booking.objects.get(id=booking_id)

        subject = 'Booking Confirmation'
        message = render_to_string('emails/booking_confirmation.txt', {
            'user': user,
            'booking': booking,
            'site_name': 'Movie Booking AI',
        })
        html_message = render_to_string('emails/booking_confirmation.html', {
            'user': user,
            'booking': booking,
            'site_name': 'Movie Booking AI',
        })

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f"Booking confirmation email sent to {user.email}")
        return True

    except (User.DoesNotExist, Booking.DoesNotExist) as e:
        logger.error(f"User or booking does not exist: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error sending booking confirmation email: {str(e)}")
        return False
