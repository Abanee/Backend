import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from django.contrib.auth import get_user_model

User = get_user_model()


class Booking(models.Model):
    """Main booking model"""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    showtime = models.ForeignKey('movies.Showtime', on_delete=models.CASCADE, related_name='bookings')

    # Booking details
    booking_reference = models.CharField(max_length=20, unique=True)
    seats = models.ManyToManyField('movies.Seat', related_name='bookings')

    # Pricing
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    convenience_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('20.00'))
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Booking status and timestamps
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    booked_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    # Metadata
    booking_source = models.CharField(max_length=20, default='web')  # web, mobile, api
    special_requests = models.TextField(blank=True)

    class Meta:
        db_table = 'bookings'
        ordering = ['-booked_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['showtime', 'status']),
            models.Index(fields=['booking_reference']),
        ]

    def __str__(self):
        return f"{self.booking_reference} - {self.user.email}"

    @property
    def seat_count(self):
        return self.seats.count()

    @property
    def seat_numbers(self):
        return ', '.join([f"{seat.row}{seat.number}" for seat in self.seats.all().order_by('row', 'number')])

    def save(self, *args, **kwargs):
        if not self.booking_reference:
            self.booking_reference = self.generate_booking_reference()
        super().save(*args, **kwargs)

    def generate_booking_reference(self):
        """Generate unique booking reference"""
        import random
        import string

        while True:
            ref = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            ref = f"MB{ref}"
            if not Booking.objects.filter(booking_reference=ref).exists():
                return ref


class Transaction(models.Model):
    """Payment transaction model"""

    GATEWAY_CHOICES = [
        ('razorpay', 'Razorpay'),
        ('stripe', 'Stripe'),
        ('paytm', 'Paytm'),
        ('phonepe', 'PhonePe'),
        ('gpay', 'Google Pay'),
    ]

    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='transactions')

    # Transaction details
    transaction_id = models.CharField(max_length=100, unique=True)
    gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES)
    gateway_transaction_id = models.CharField(max_length=255, blank=True)
    reference_id = models.CharField(max_length=255, blank=True)  # Gateway order ID

    # Amount details
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')

    # Status and timestamps
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='initiated')
    initiated_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    # Gateway response
    gateway_response = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'transactions'
        ordering = ['-initiated_at']
        indexes = [
            models.Index(fields=['booking', 'status']),
            models.Index(fields=['transaction_id']),
            models.Index(fields=['gateway_transaction_id']),
        ]

    def __str__(self):
        return f"{self.transaction_id} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = self.generate_transaction_id()
        super().save(*args, **kwargs)

    def generate_transaction_id(self):
        """Generate unique transaction ID"""
        import random
        import string

        while True:
            ref = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
            ref = f"TXN{ref}"
            if not Transaction.objects.filter(transaction_id=ref).exists():
                return ref


class BookingHistory(models.Model):
    """Booking status history for tracking"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='history')

    # Status change details
    previous_status = models.CharField(max_length=15)
    new_status = models.CharField(max_length=15)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField(blank=True)

    # Timestamp
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'booking_history'
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.booking.booking_reference} - {self.previous_status} → {self.new_status}"


class Refund(models.Model):
    """Refund model for cancelled bookings"""

    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='refunds')
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='refunds')

    # Refund details
    refund_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2)  # After deductions
    cancellation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Status and timestamps
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='initiated')
    reason = models.TextField()
    initiated_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    # Gateway details
    gateway_refund_id = models.CharField(max_length=255, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'refunds'
        ordering = ['-initiated_at']

    def __str__(self):
        return f"{self.refund_id} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.refund_id:
            self.refund_id = self.generate_refund_id()
        super().save(*args, **kwargs)

    def generate_refund_id(self):
        """Generate unique refund ID"""
        import random
        import string

        while True:
            ref = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
            ref = f"REF{ref}"
            if not Refund.objects.filter(refund_id=ref).exists():
                return ref


class CancellationPolicy(models.Model):
    """Cancellation policy for different scenarios"""

    name = models.CharField(max_length=100)
    description = models.TextField()

    # Time-based cancellation rules
    hours_before_show = models.PositiveIntegerField()
    cancellation_fee_percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    is_refundable = models.BooleanField(default=True)

    # Applicability
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'cancellation_policies'
        ordering = ['hours_before_show']

    def __str__(self):
        return self.name

    @classmethod
    def get_applicable_policy(cls, hours_before_show):
        """Get the applicable cancellation policy"""
        return cls.objects.filter(
            hours_before_show__lte=hours_before_show,
            is_active=True
        ).order_by('-hours_before_show').first()


class BookingNotification(models.Model):
    """Notification model for booking updates"""

    NOTIFICATION_TYPES = [
        ('booking_confirmed', 'Booking Confirmed'),
        ('payment_success', 'Payment Success'),
        ('booking_cancelled', 'Booking Cancelled'),
        ('refund_initiated', 'Refund Initiated'),
        ('show_reminder', 'Show Reminder'),
    ]

    CHANNELS = [
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('push', 'Push Notification'),
        ('whatsapp', 'WhatsApp'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='notifications')

    # Notification details
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    channel = models.CharField(max_length=15, choices=CHANNELS)
    recipient = models.CharField(max_length=255)  # email, phone number, etc.

    # Content
    subject = models.CharField(max_length=200)
    message = models.TextField()

    # Status and timestamps
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    scheduled_at = models.DateTimeField()
    sent_at = models.DateTimeField(blank=True, null=True)

    # Metadata
    attempts = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = 'booking_notifications'
        ordering = ['-scheduled_at']
        indexes = [
            models.Index(fields=['booking', 'notification_type']),
            models.Index(fields=['status', 'scheduled_at']),
        ]

    def __str__(self):
        return f"{self.booking.booking_reference} - {self.notification_type}"
