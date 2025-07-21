"""
Payment gateway utilities for different payment providers
"""
import hashlib
import hmac
import razorpay
import stripe
from django.conf import settings
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class PaymentGatewayInterface:
    """Base interface for payment gateways"""

    def create_order(self, transaction, return_url=None, cancel_url=None):
        """Create payment order"""
        raise NotImplementedError

    def verify_payment(self, gateway_transaction_id, gateway_response):
        """Verify payment status"""
        raise NotImplementedError

    def handle_webhook(self, payload, headers):
        """Handle webhook from payment gateway"""
        raise NotImplementedError

    def initiate_refund(self, transaction, refund_amount):
        """Initiate refund"""
        raise NotImplementedError


class RazorpayGateway(PaymentGatewayInterface):
    """Razorpay payment gateway implementation"""

    def __init__(self):
        self.client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )

    def create_order(self, transaction, return_url=None, cancel_url=None):
        """Create Razorpay order"""
        try:
            order_data = {
                'amount': int(transaction.amount * 100),  # Amount in paise
                'currency': transaction.currency,
                'receipt': transaction.transaction_id,
                'notes': {
                    'booking_id': str(transaction.booking.id),
                    'user_email': transaction.booking.user.email,
                }
            }

            order = self.client.order.create(order_data)

            return {
                'order_id': order['id'],
                'key_id': settings.RAZORPAY_KEY_ID,
                'amount': transaction.amount,
                'currency': transaction.currency,
                'name': 'Movie Booking AI',
                'description': f'Booking for {transaction.booking.showtime.movie.title}',
                'prefill': {
                    'name': transaction.booking.user.get_full_name(),
                    'email': transaction.booking.user.email,
                    'contact': transaction.booking.user.phone_number or '',
                },
                'notes': order_data['notes'],
                'theme': {
                    'color': '#3399cc'
                }
            }

        except Exception as e:
            logger.error(f"Razorpay order creation failed: {str(e)}")
            raise

    def verify_payment(self, gateway_transaction_id, gateway_response):
        """Verify Razorpay payment"""
        try:
            order_id = gateway_response.get('razorpay_order_id')
            payment_id = gateway_response.get('razorpay_payment_id')
            signature = gateway_response.get('razorpay_signature')

            # Verify signature
            generated_signature = hmac.new(
                settings.RAZORPAY_KEY_SECRET.encode('utf-8'),
                f"{order_id}|{payment_id}".encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            if hmac.compare_digest(signature, generated_signature):
                # Fetch payment details from Razorpay
                payment = self.client.payment.fetch(payment_id)
                return payment['status'] == 'captured'

            return False

        except Exception as e:
            logger.error(f"Razorpay payment verification failed: {str(e)}")
            return False

    def handle_webhook(self, payload, headers):
        """Handle Razorpay webhook"""
        try:
            # Verify webhook signature
            signature = headers.get('X-Razorpay-Signature', '')
            expected_signature = hmac.new(
                settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
                payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                logger.warning("Invalid Razorpay webhook signature")
                return {'success': False, 'error': 'Invalid signature'}

            import json
            data = json.loads(payload)
            event = data.get('event')
            payment_entity = data.get('payload', {}).get('payment', {}).get('entity', {})

            if event == 'payment.captured':
                return {
                    'success': True,
                    'status': 'success',
                    'transaction_id': payment_entity.get('notes', {}).get('transaction_id'),
                    'gateway_transaction_id': payment_entity.get('id'),
                }
            elif event == 'payment.failed':
                return {
                    'success': True,
                    'status': 'failed',
                    'transaction_id': payment_entity.get('notes', {}).get('transaction_id'),
                    'failure_reason': payment_entity.get('error_description', 'Payment failed'),
                }

            return {'success': False, 'error': 'Unhandled event'}

        except Exception as e:
            logger.error(f"Razorpay webhook processing failed: {str(e)}")
            return {'success': False, 'error': str(e)}

    def initiate_refund(self, transaction, refund_amount):
        """Initiate Razorpay refund"""
        try:
            refund_data = {
                'amount': int(refund_amount * 100),  # Amount in paise
                'speed': 'normal',
                'notes': {
                    'booking_id': str(transaction.booking.id),
                    'reason': 'Booking cancellation',
                }
            }

            refund = self.client.payment.refund(
                transaction.gateway_transaction_id,
                refund_data
            )

            return {
                'refund_id': refund['id'],
                'status': refund['status'],
                'amount': Decimal(refund['amount']) / 100,
            }

        except Exception as e:
            logger.error(f"Razorpay refund initiation failed: {str(e)}")
            raise


class StripeGateway(PaymentGatewayInterface):
    """Stripe payment gateway implementation"""

    def __init__(self):
        stripe.api_key = settings.STRIPE_SECRET_KEY

    def create_order(self, transaction, return_url=None, cancel_url=None):
        """Create Stripe payment intent"""
        try:
            intent = stripe.PaymentIntent.create(
                amount=int(transaction.amount * 100),  # Amount in cents
                currency=transaction.currency.lower(),
                automatic_payment_methods={'enabled': True},
                metadata={
                    'transaction_id': transaction.transaction_id,
                    'booking_id': str(transaction.booking.id),
                    'user_email': transaction.booking.user.email,
                },
                description=f'Booking for {transaction.booking.showtime.movie.title}',
            )

            return {
                'client_secret': intent.client_secret,
                'payment_intent_id': intent.id,
                'publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
                'amount': transaction.amount,
                'currency': transaction.currency,
            }

        except Exception as e:
            logger.error(f"Stripe payment intent creation failed: {str(e)}")
            raise

    def verify_payment(self, gateway_transaction_id, gateway_response):
        """Verify Stripe payment"""
        try:
            intent = stripe.PaymentIntent.retrieve(gateway_transaction_id)
            return intent.status == 'succeeded'

        except Exception as e:
            logger.error(f"Stripe payment verification failed: {str(e)}")
            return False

    def handle_webhook(self, payload, headers):
        """Handle Stripe webhook"""
        try:
            sig_header = headers.get('stripe-signature')
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )

            if event['type'] == 'payment_intent.succeeded':
                intent = event['data']['object']
                return {
                    'success': True,
                    'status': 'success',
                    'transaction_id': intent['metadata'].get('transaction_id'),
                    'gateway_transaction_id': intent['id'],
                }
            elif event['type'] == 'payment_intent.payment_failed':
                intent = event['data']['object']
                return {
                    'success': True,
                    'status': 'failed',
                    'transaction_id': intent['metadata'].get('transaction_id'),
                    'failure_reason': intent.get('last_payment_error', {}).get('message', 'Payment failed'),
                }

            return {'success': False, 'error': 'Unhandled event'}

        except Exception as e:
            logger.error(f"Stripe webhook processing failed: {str(e)}")
            return {'success': False, 'error': str(e)}

    def initiate_refund(self, transaction, refund_amount):
        """Initiate Stripe refund"""
        try:
            refund = stripe.Refund.create(
                payment_intent=transaction.gateway_transaction_id,
                amount=int(refund_amount * 100),  # Amount in cents
                metadata={
                    'booking_id': str(transaction.booking.id),
                    'reason': 'Booking cancellation',
                }
            )

            return {
                'refund_id': refund['id'],
                'status': refund['status'],
                'amount': Decimal(refund['amount']) / 100,
            }

        except Exception as e:
            logger.error(f"Stripe refund initiation failed: {str(e)}")
            raise


class PaymentGatewayFactory:
    """Factory class for payment gateways"""

    _gateways = {
        'razorpay': RazorpayGateway,
        'stripe': StripeGateway,
    }

    @classmethod
    def get_gateway(cls, gateway_name):
        """Get payment gateway instance"""
        if gateway_name not in cls._gateways:
            raise ValueError(f"Unsupported payment gateway: {gateway_name}")

        return cls._gateways[gateway_name]()

    @classmethod
    def get_available_gateways(cls):
        """Get list of available payment gateways"""
        return list(cls._gateways.keys())
