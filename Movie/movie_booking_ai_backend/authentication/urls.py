from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    # Authentication endpoints
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.CustomTokenObtainPairView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Profile endpoints
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change_password'),

    # Email verification
    path('verify-email/', views.verify_email, name='verify_email'),

    # Password reset
    path('password-reset/', views.request_password_reset, name='password_reset'),
    path('password-reset-confirm/', views.confirm_password_reset, name='password_reset_confirm'),
]
