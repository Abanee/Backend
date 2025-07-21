from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import uuid

from .models import EmailVerificationToken, PasswordResetToken
from .serializers import (
    UserRegistrationSerializer, UserLoginSerializer, UserProfileSerializer,
    UserProfileDetailSerializer, PasswordChangeSerializer, 
    PasswordResetSerializer, PasswordResetConfirmSerializer
)
from .tasks import send_verification_email, send_password_reset_email

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """User registration endpoint"""

    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Create email verification token
        token = EmailVerificationToken.objects.create(user=user)

        # Send verification email (async task)
        send_verification_email.delay(user.id, str(token.token))

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        return Response({
            'message': 'User registered successfully. Please check your email for verification.',
            'user': UserProfileSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)


class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom login view with additional user data"""

    def post(self, request, *args, **kwargs):
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        refresh = RefreshToken.for_user(user)

        return Response({
            'message': 'Login successful',
            'user': UserProfileSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        })


class ProfileView(generics.RetrieveUpdateAPIView):
    """User profile view"""

    serializer_class = UserProfileDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(generics.UpdateAPIView):
    """Change password view"""

    serializer_class = PasswordChangeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = self.get_object()
        user.set_password(serializer.validated_data['new_password'])
        user.save()

        return Response({'message': 'Password changed successfully'})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def verify_email(request):
    """Email verification endpoint"""

    token = request.data.get('token')
    if not token:
        return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        verification_token = EmailVerificationToken.objects.get(
            token=token, is_used=False
        )

        # Check if token is not expired (valid for 24 hours)
        if verification_token.created_at < timezone.now() - timedelta(hours=24):
            return Response({'error': 'Token has expired'}, status=status.HTTP_400_BAD_REQUEST)

        # Mark user as verified
        user = verification_token.user
        user.is_email_verified = True
        user.save()

        # Mark token as used
        verification_token.is_used = True
        verification_token.save()

        return Response({'message': 'Email verified successfully'})

    except EmailVerificationToken.DoesNotExist:
        return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def request_password_reset(request):
    """Request password reset endpoint"""

    serializer = PasswordResetSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    email = serializer.validated_data['email']
    user = User.objects.get(email=email)

    # Create password reset token
    token = PasswordResetToken.objects.create(
        user=user,
        expires_at=timezone.now() + timedelta(hours=1)
    )

    # Send password reset email (async task)
    send_password_reset_email.delay(user.id, str(token.token))

    return Response({'message': 'Password reset email sent'})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def confirm_password_reset(request):
    """Confirm password reset endpoint"""

    serializer = PasswordResetConfirmSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    token = serializer.validated_data['token']
    new_password = serializer.validated_data['new_password']

    try:
        reset_token = PasswordResetToken.objects.get(
            token=token, is_used=False
        )

        # Check if token is not expired
        if reset_token.expires_at < timezone.now():
            return Response({'error': 'Token has expired'}, status=status.HTTP_400_BAD_REQUEST)

        # Reset password
        user = reset_token.user
        user.set_password(new_password)
        user.save()

        # Mark token as used
        reset_token.is_used = True
        reset_token.save()

        return Response({'message': 'Password reset successfully'})

    except PasswordResetToken.DoesNotExist:
        return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    """Logout view - blacklist refresh token"""

    try:
        refresh_token = request.data.get('refresh')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        return Response({'message': 'Logged out successfully'})
    except Exception as e:
        return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)
