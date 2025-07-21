from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import Booking, Transaction, BookingHistory, Refund, CancellationPolicy, BookingNotification


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    """Admin for Booking model"""

    list_display = ['booking_reference', 'user_email', 'movie_title', 'show_datetime',
                   'seat_count', 'total_amount', 'status', 'booked_at']
    list_filter = ['status', 'booked_at', 'showtime__show_date', 'showtime__movie']
    search_fields = ['booking_reference', 'user__email', 'showtime__movie__title']
    readonly_fields = ['id', 'booking_reference', 'booked_at', 'seat_numbers']
    date_hierarchy = 'booked_at'
    ordering = ['-booked_at']

    fieldsets = (
        ('Booking Information', {
            'fields': ('id', 'booking_reference', 'user', 'showtime', 'status')
        }),
        ('Seats', {
            'fields': ('seat_numbers', 'special_requests')
        }),
        ('Pricing', {
            'fields': ('subtotal', 'tax_amount', 'convenience_fee', 'total_amount')
        }),
        ('Timestamps', {
            'fields': ('booked_at', 'expires_at', 'confirmed_at', 'cancelled_at')
        }),
        ('Metadata', {
            'fields': ('booking_source',),
            'classes': ('collapse',)
        }),
    )

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'
    user_email.admin_order_field = 'user__email'

    def movie_title(self, obj):
        return obj.showtime.movie.title
    movie_title.short_description = 'Movie'
    movie_title.admin_order_field = 'showtime__movie__title'

    def show_datetime(self, obj):
        return f"{obj.showtime.show_date} {obj.showtime.show_time}"
    show_datetime.short_description = 'Show Date/Time'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'showtime__movie', 'showtime__screen__cinema'
        ).prefetch_related('seats')

    actions = ['mark_confirmed', 'mark_cancelled']

    def mark_confirmed(self, request, queryset):
        updated = queryset.filter(status='pending').update(
            status='confirmed',
            confirmed_at=timezone.now()
        )
        self.message_user(request, f'{updated} bookings marked as confirmed.')
    mark_confirmed.short_description = 'Mark selected bookings as confirmed'

    def mark_cancelled(self, request, queryset):
        updated = queryset.filter(status__in=['pending', 'confirmed']).update(
            status='cancelled',
            cancelled_at=timezone.now()
        )
        self.message_user(request, f'{updated} bookings marked as cancelled.')
    mark_cancelled.short_description = 'Mark selected bookings as cancelled'


class TransactionInline(admin.TabularInline):
    """Inline admin for Transaction model"""

    model = Transaction
    extra = 0
    readonly_fields = ['transaction_id', 'initiated_at', 'completed_at']
    fields = ['transaction_id', 'gateway', 'gateway_transaction_id', 'amount', 'status']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Admin for Transaction model"""

    list_display = ['transaction_id', 'booking_reference', 'gateway', 'amount', 'status', 'initiated_at']
    list_filter = ['status', 'gateway', 'initiated_at']
    search_fields = ['transaction_id', 'gateway_transaction_id', 'booking__booking_reference']
    readonly_fields = ['id', 'transaction_id', 'initiated_at', 'completed_at']
    ordering = ['-initiated_at']

    fieldsets = (
        ('Transaction Information', {
            'fields': ('id', 'transaction_id', 'booking', 'gateway')
        }),
        ('Gateway Details', {
            'fields': ('gateway_transaction_id', 'reference_id')
        }),
        ('Amount', {
            'fields': ('amount', 'currency')
        }),
        ('Status', {
            'fields': ('status', 'failure_reason')
        }),
        ('Timestamps', {
            'fields': ('initiated_at', 'completed_at')
        }),
        ('Gateway Response', {
            'fields': ('gateway_response',),
            'classes': ('collapse',)
        }),
    )

    def booking_reference(self, obj):
        return obj.booking.booking_reference
    booking_reference.short_description = 'Booking'
    booking_reference.admin_order_field = 'booking__booking_reference'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('booking')


@admin.register(BookingHistory)
class BookingHistoryAdmin(admin.ModelAdmin):
    """Admin for BookingHistory model"""

    list_display = ['booking_reference', 'previous_status', 'new_status', 'changed_by_email', 'changed_at']
    list_filter = ['previous_status', 'new_status', 'changed_at']
    search_fields = ['booking__booking_reference', 'reason']
    readonly_fields = ['id', 'changed_at']
    ordering = ['-changed_at']

    def booking_reference(self, obj):
        return obj.booking.booking_reference
    booking_reference.short_description = 'Booking'

    def changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else 'System'
    changed_by_email.short_description = 'Changed By'


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    """Admin for Refund model"""

    list_display = ['refund_id', 'booking_reference', 'amount', 'refund_amount', 'status', 'initiated_at']
    list_filter = ['status', 'initiated_at']
    search_fields = ['refund_id', 'booking__booking_reference']
    readonly_fields = ['id', 'refund_id', 'initiated_at', 'processed_at']
    ordering = ['-initiated_at']

    fieldsets = (
        ('Refund Information', {
            'fields': ('id', 'refund_id', 'booking', 'transaction')
        }),
        ('Amount Details', {
            'fields': ('amount', 'refund_amount', 'cancellation_fee')
        }),
        ('Status', {
            'fields': ('status', 'reason')
        }),
        ('Timestamps', {
            'fields': ('initiated_at', 'processed_at')
        }),
        ('Gateway Details', {
            'fields': ('gateway_refund_id', 'gateway_response'),
            'classes': ('collapse',)
        }),
    )

    def booking_reference(self, obj):
        return obj.booking.booking_reference
    booking_reference.short_description = 'Booking'


@admin.register(CancellationPolicy)
class CancellationPolicyAdmin(admin.ModelAdmin):
    """Admin for CancellationPolicy model"""

    list_display = ['name', 'hours_before_show', 'cancellation_fee_percentage', 'is_refundable', 'is_active']
    list_filter = ['is_refundable', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['hours_before_show']

    fieldsets = (
        ('Policy Information', {
            'fields': ('name', 'description')
        }),
        ('Rules', {
            'fields': ('hours_before_show', 'cancellation_fee_percentage', 'is_refundable')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )


@admin.register(BookingNotification)
class BookingNotificationAdmin(admin.ModelAdmin):
    """Admin for BookingNotification model"""

    list_display = ['booking_reference', 'notification_type', 'channel', 'recipient', 'status', 'scheduled_at']
    list_filter = ['notification_type', 'channel', 'status', 'scheduled_at']
    search_fields = ['booking__booking_reference', 'recipient', 'subject']
    readonly_fields = ['id', 'sent_at']
    ordering = ['-scheduled_at']

    def booking_reference(self, obj):
        return obj.booking.booking_reference
    booking_reference.short_description = 'Booking'

    actions = ['mark_as_sent', 'retry_failed_notifications']

    def mark_as_sent(self, request, queryset):
        updated = queryset.update(status='sent', sent_at=timezone.now())
        self.message_user(request, f'{updated} notifications marked as sent.')
    mark_as_sent.short_description = 'Mark selected notifications as sent'

    def retry_failed_notifications(self, request, queryset):
        failed_notifications = queryset.filter(status='failed')
        for notification in failed_notifications:
            notification.status = 'pending'
            notification.attempts = 0
            notification.error_message = ''
            notification.save()
        self.message_user(request, f'{failed_notifications.count()} notifications queued for retry.')
    retry_failed_notifications.short_description = 'Retry failed notifications'
