import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from decimal import Decimal


class Genre(models.Model):
    """Movie genres"""

    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'genres'
        ordering = ['name']

    def __str__(self):
        return self.name


class Language(models.Model):
    """Movie languages"""

    name = models.CharField(max_length=50, unique=True)
    code = models.CharField(max_length=5, unique=True)  # ISO language code

    class Meta:
        db_table = 'languages'
        ordering = ['name']

    def __str__(self):
        return self.name


class Movie(models.Model):
    """Movie model"""

    RATING_CHOICES = [
        ('U', 'Universal'),
        ('UA', 'Universal Adult'),
        ('A', 'Adults Only'),
        ('S', 'Special'),
    ]

    STATUS_CHOICES = [
        ('coming_soon', 'Coming Soon'),
        ('now_showing', 'Now Showing'),
        ('ended', 'Ended'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    duration = models.PositiveIntegerField(help_text="Duration in minutes")
    release_date = models.DateField()
    rating = models.CharField(max_length=2, choices=RATING_CHOICES)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='coming_soon')

    # Media
    poster = models.ImageField(upload_to='movie_posters/', blank=True, null=True)
    trailer_url = models.URLField(blank=True, null=True)

    # Relationships
    genres = models.ManyToManyField(Genre, related_name='movies')
    languages = models.ManyToManyField(Language, related_name='movies')

    # Metadata
    director = models.CharField(max_length=200)
    cast = models.JSONField(default=list, help_text="List of main cast members")
    imdb_rating = models.DecimalField(max_digits=3, decimal_places=1, 
                                     validators=[MinValueValidator(0), MaxValueValidator(10)],
                                     blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'movies'
        ordering = ['-release_date', 'title']
        indexes = [
            models.Index(fields=['status', 'release_date']),
            models.Index(fields=['title']),
        ]

    def __str__(self):
        return self.title

    @property
    def duration_formatted(self):
        """Return duration in hours and minutes format"""
        hours = self.duration // 60
        minutes = self.duration % 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"


class Cinema(models.Model):
    """Cinema/Theater model"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)
    phone = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)

    # Location
    latitude = models.DecimalField(max_digits=10, decimal_places=8, blank=True, null=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, blank=True, null=True)

    # Amenities
    amenities = models.JSONField(default=list, help_text="List of amenities")

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'cinemas'
        ordering = ['name']
        indexes = [
            models.Index(fields=['city', 'is_active']),
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.name} - {self.city}"


class Screen(models.Model):
    """Cinema screen model"""

    SCREEN_TYPES = [
        ('2d', '2D'),
        ('3d', '3D'),
        ('imax', 'IMAX'),
        ('4dx', '4DX'),
        ('dolby', 'Dolby Atmos'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cinema = models.ForeignKey(Cinema, on_delete=models.CASCADE, related_name='screens')
    name = models.CharField(max_length=100)
    screen_type = models.CharField(max_length=10, choices=SCREEN_TYPES, default='2d')
    total_seats = models.PositiveIntegerField()

    # Seat configuration
    rows = models.PositiveIntegerField()
    seats_per_row = models.PositiveIntegerField()

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'screens'
        ordering = ['cinema', 'name']
        unique_together = ['cinema', 'name']

    def __str__(self):
        return f"{self.cinema.name} - {self.name}"


class Seat(models.Model):
    """Individual seat model"""

    SEAT_TYPES = [
        ('regular', 'Regular'),
        ('premium', 'Premium'),
        ('recliner', 'Recliner'),
        ('couple', 'Couple Seat'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name='seats')
    row = models.CharField(max_length=5)
    number = models.PositiveIntegerField()
    seat_type = models.CharField(max_length=10, choices=SEAT_TYPES, default='regular')

    # Pricing
    base_price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('100.00'))

    # Status
    is_available = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)  # For maintenance

    class Meta:
        db_table = 'seats'
        ordering = ['row', 'number']
        unique_together = ['screen', 'row', 'number']
        indexes = [
            models.Index(fields=['screen', 'is_available']),
        ]

    def __str__(self):
        return f"{self.screen} - {self.row}{self.number}"

    @property
    def seat_identifier(self):
        return f"{self.row}{self.number}"


class Showtime(models.Model):
    """Movie showtime model"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='showtimes')
    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name='showtimes')

    # Timing
    show_date = models.DateField()
    show_time = models.TimeField()

    # Pricing
    base_price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('150.00'))
    premium_price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('200.00'))
    recliner_price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('300.00'))

    # Status
    is_active = models.BooleanField(default=True)
    is_housefull = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'showtimes'
        ordering = ['show_date', 'show_time']
        unique_together = ['screen', 'show_date', 'show_time']
        indexes = [
            models.Index(fields=['movie', 'show_date', 'is_active']),
            models.Index(fields=['screen', 'show_date']),
        ]

    def __str__(self):
        return f"{self.movie.title} - {self.show_date} {self.show_time}"

    def get_price_for_seat(self, seat):
        """Get price for a specific seat based on seat type"""
        if seat.seat_type == 'recliner':
            return self.recliner_price
        elif seat.seat_type == 'premium':
            return self.premium_price
        else:
            return self.base_price

    @property
    def available_seats_count(self):
        """Get count of available seats for this showtime"""
        from bookings.models import Booking
        booked_seats = Booking.objects.filter(
            showtime=self,
            status__in=['confirmed', 'pending']
        ).values_list('seats', flat=True)

        return self.screen.seats.filter(
            is_available=True,
            is_blocked=False
        ).exclude(id__in=booked_seats).count()


class MovieReview(models.Model):
    """Movie review model"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey('authentication.User', on_delete=models.CASCADE, related_name='movie_reviews')

    # Review content
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=200, blank=True)
    review = models.TextField()

    # Status
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'movie_reviews'
        ordering = ['-created_at']
        unique_together = ['movie', 'user']

    def __str__(self):
        return f"{self.movie.title} - {self.user.email} ({self.rating}/5)"
