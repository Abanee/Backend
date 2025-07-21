"""
URL configuration for movie_booking_ai project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('authentication.urls')),
    path('api/movies/', include('movies.urls')),
    path('api/bookings/', include('bookings.urls')),
    path('api/recommendations/', include('ai_recommendations.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Admin site customization
admin.site.site_header = "Movie Booking AI Admin"
admin.site.site_title = "Movie Booking AI"
admin.site.index_title = "Welcome to Movie Booking AI Administration"
