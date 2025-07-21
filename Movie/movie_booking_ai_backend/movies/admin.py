from django.contrib import admin
from django.utils.html import format_html
from .models import Movie, Cinema, Screen, Seat, Showtime, Genre, Language, MovieReview


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    """Admin for Genre model"""

    list_display = ['name', 'description', 'created_at']
    search_fields = ['name']
    ordering = ['name']


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    """Admin for Language model"""

    list_display = ['name', 'code']
    search_fields = ['name', 'code']
    ordering = ['name']


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    """Admin for Movie model"""

    list_display = ['title', 'director', 'release_date', 'rating', 'status', 'imdb_rating']
    list_filter = ['status', 'rating', 'release_date', 'genres']
    search_fields = ['title', 'director', 'cast']
    filter_horizontal = ['genres', 'languages']
    date_hierarchy = 'release_date'
    ordering = ['-release_date', 'title']

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'duration', 'release_date', 'rating', 'status')
        }),
        ('Media', {
            'fields': ('poster', 'trailer_url')
        }),
        ('Details', {
            'fields': ('director', 'cast', 'imdb_rating')
        }),
        ('Categories', {
            'fields': ('genres', 'languages')
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('genres', 'languages')


class ScreenInline(admin.TabularInline):
    """Inline admin for Screen model"""

    model = Screen
    extra = 0
    fields = ['name', 'screen_type', 'total_seats', 'rows', 'seats_per_row', 'is_active']


@admin.register(Cinema)
class CinemaAdmin(admin.ModelAdmin):
    """Admin for Cinema model"""

    list_display = ['name', 'city', 'state', 'pincode', 'is_active', 'screens_count']
    list_filter = ['city', 'state', 'is_active']
    search_fields = ['name', 'city', 'address']
    inlines = [ScreenInline]
    ordering = ['name']

    def screens_count(self, obj):
        return obj.screens.count()
    screens_count.short_description = 'Screens'


@admin.register(Screen)
class ScreenAdmin(admin.ModelAdmin):
    """Admin for Screen model"""

    list_display = ['name', 'cinema', 'screen_type', 'total_seats', 'is_active']
    list_filter = ['screen_type', 'is_active', 'cinema__city']
    search_fields = ['name', 'cinema__name']
    ordering = ['cinema', 'name']


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    """Admin for Seat model"""

    list_display = ['seat_identifier', 'screen', 'seat_type', 'base_price', 'is_available', 'is_blocked']
    list_filter = ['seat_type', 'is_available', 'is_blocked', 'screen__cinema__city']
    search_fields = ['screen__name', 'screen__cinema__name', 'row', 'number']
    ordering = ['screen', 'row', 'number']

    def seat_identifier(self, obj):
        return f"{obj.row}{obj.number}"
    seat_identifier.short_description = 'Seat'


@admin.register(Showtime)
class ShowtimeAdmin(admin.ModelAdmin):
    """Admin for Showtime model"""

    list_display = ['movie', 'screen_info', 'show_date', 'show_time', 
                   'base_price', 'is_active', 'is_housefull']
    list_filter = ['show_date', 'is_active', 'is_housefull', 'screen__cinema__city']
    search_fields = ['movie__title', 'screen__name', 'screen__cinema__name']
    date_hierarchy = 'show_date'
    ordering = ['-show_date', 'show_time']

    fieldsets = (
        ('Show Information', {
            'fields': ('movie', 'screen', 'show_date', 'show_time')
        }),
        ('Pricing', {
            'fields': ('base_price', 'premium_price', 'recliner_price')
        }),
        ('Status', {
            'fields': ('is_active', 'is_housefull')
        }),
    )

    def screen_info(self, obj):
        return f"{obj.screen.cinema.name} - {obj.screen.name}"
    screen_info.short_description = 'Screen'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('movie', 'screen__cinema')


@admin.register(MovieReview)
class MovieReviewAdmin(admin.ModelAdmin):
    """Admin for MovieReview model"""

    list_display = ['movie', 'user_email', 'rating', 'is_approved', 'created_at']
    list_filter = ['rating', 'is_approved', 'created_at']
    search_fields = ['movie__title', 'user__email', 'title']
    ordering = ['-created_at']

    fieldsets = (
        ('Review Information', {
            'fields': ('movie', 'user', 'rating', 'title', 'review')
        }),
        ('Moderation', {
            'fields': ('is_approved',)
        }),
    )

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('movie', 'user')

    actions = ['approve_reviews', 'reject_reviews']

    def approve_reviews(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f'{updated} reviews approved.')
    approve_reviews.short_description = 'Approve selected reviews'

    def reject_reviews(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f'{updated} reviews rejected.')
    reject_reviews.short_description = 'Reject selected reviews'
