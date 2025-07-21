from django.urls import path
from . import views

urlpatterns = [
    # Booking creation
    path('create/<uuid:showtime_id>/', views.CreateBookingView.as_view(), name='create_booking'),

    # User bookings
    path('my-bookings/', views.UserBookingsView.as_view(), name='user_bookings'),
    path('<uuid:pk>/', views.BookingDetailView.as_view(), name='booking_detail'),
    path('<uuid:booking_id>/history/', views.BookingHistoryView.as_view(), name='booking_history'),

    # Payment endpoints
    path('<uuid:booking_id>/payment/initiate/', views.InitiatePaymentView.as_view(), name='initiate_payment'),
    path('<uuid:booking_id>/payment/confirm/', views.ConfirmPaymentView.as_view(), name='confirm_payment'),

    # Booking management
    path('<uuid:booking_id>/cancel/', views.CancelBookingView.as_view(), name='cancel_booking'),
    path('<uuid:booking_id>/extend-timer/', views.extend_booking_timer, name='extend_booking_timer'),

    # Webhook
    path('webhook/payment/', views.payment_webhook, name='payment_webhook'),
]
