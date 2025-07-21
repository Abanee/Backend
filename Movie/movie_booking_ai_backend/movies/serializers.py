from rest_framework import serializers
from .models import Movie, Cinema, Screen, Seat, Showtime, Genre, Language, MovieReview


class GenreSerializer(serializers.ModelSerializer):
    """Serializer for Genre model"""

    class Meta:
        model = Genre
        fields = ['id', 'name', 'description']


class LanguageSerializer(serializers.ModelSerializer):
    """Serializer for Language model"""

    class Meta:
        model = Language
        fields = ['id', 'name', 'code']


class MovieListSerializer(serializers.ModelSerializer):
    """Serializer for Movie list view"""

    genres = GenreSerializer(many=True, read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)
    duration_formatted = serializers.ReadOnlyField()

    class Meta:
        model = Movie
        fields = ['id', 'title', 'description', 'duration', 'duration_formatted',
                 'release_date', 'rating', 'status', 'poster', 'director', 
                 'imdb_rating', 'genres', 'languages']


class MovieDetailSerializer(serializers.ModelSerializer):
    """Serializer for Movie detail view"""

    genres = GenreSerializer(many=True, read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)
    duration_formatted = serializers.ReadOnlyField()
    reviews_count = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = ['id', 'title', 'description', 'duration', 'duration_formatted',
                 'release_date', 'rating', 'status', 'poster', 'trailer_url',
                 'director', 'cast', 'imdb_rating', 'genres', 'languages',
                 'reviews_count', 'average_rating', 'created_at']

    def get_reviews_count(self, obj):
        return obj.reviews.filter(is_approved=True).count()

    def get_average_rating(self, obj):
        reviews = obj.reviews.filter(is_approved=True)
        if reviews.exists():
            return round(reviews.aggregate(avg=models.Avg('rating'))['avg'], 1)
        return None


class SeatSerializer(serializers.ModelSerializer):
    """Serializer for Seat model"""

    seat_identifier = serializers.ReadOnlyField()

    class Meta:
        model = Seat
        fields = ['id', 'row', 'number', 'seat_identifier', 'seat_type', 
                 'base_price', 'is_available', 'is_blocked']


class ScreenSerializer(serializers.ModelSerializer):
    """Serializer for Screen model"""

    class Meta:
        model = Screen
        fields = ['id', 'name', 'screen_type', 'total_seats', 'rows', 'seats_per_row']


class CinemaSerializer(serializers.ModelSerializer):
    """Serializer for Cinema model"""

    screens = ScreenSerializer(many=True, read_only=True)

    class Meta:
        model = Cinema
        fields = ['id', 'name', 'address', 'city', 'state', 'pincode', 
                 'phone', 'amenities', 'screens']


class CinemaListSerializer(serializers.ModelSerializer):
    """Serializer for Cinema list view"""

    screens_count = serializers.SerializerMethodField()

    class Meta:
        model = Cinema
        fields = ['id', 'name', 'address', 'city', 'state', 'pincode', 
                 'phone', 'amenities', 'screens_count']

    def get_screens_count(self, obj):
        return obj.screens.filter(is_active=True).count()


class ShowtimeSerializer(serializers.ModelSerializer):
    """Serializer for Showtime model"""

    movie = MovieListSerializer(read_only=True)
    screen = ScreenSerializer(read_only=True)
    cinema = serializers.SerializerMethodField()
    available_seats_count = serializers.ReadOnlyField()

    class Meta:
        model = Showtime
        fields = ['id', 'movie', 'screen', 'cinema', 'show_date', 'show_time',
                 'base_price', 'premium_price', 'recliner_price', 
                 'is_housefull', 'available_seats_count']

    def get_cinema(self, obj):
        return {
            'id': obj.screen.cinema.id,
            'name': obj.screen.cinema.name,
            'address': obj.screen.cinema.address,
            'city': obj.screen.cinema.city,
        }


class ShowtimeDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for Showtime with seat map"""

    movie = MovieListSerializer(read_only=True)
    screen = ScreenSerializer(read_only=True)
    cinema = serializers.SerializerMethodField()
    seats = serializers.SerializerMethodField()
    available_seats_count = serializers.ReadOnlyField()

    class Meta:
        model = Showtime
        fields = ['id', 'movie', 'screen', 'cinema', 'show_date', 'show_time',
                 'base_price', 'premium_price', 'recliner_price', 
                 'is_housefull', 'available_seats_count', 'seats']

    def get_cinema(self, obj):
        return CinemaSerializer(obj.screen.cinema).data

    def get_seats(self, obj):
        """Get seat map with booking status"""
        from bookings.models import Booking

        # Get all seats for this screen
        seats = obj.screen.seats.all().order_by('row', 'number')

        # Get booked seats for this showtime
        booked_seats = Booking.objects.filter(
            showtime=obj,
            status__in=['confirmed', 'pending']
        ).values_list('seats__id', flat=True)

        # Serialize seats with booking status
        seat_data = []
        for seat in seats:
            seat_info = SeatSerializer(seat).data
            seat_info['is_booked'] = seat.id in booked_seats
            seat_info['price'] = float(obj.get_price_for_seat(seat))
            seat_data.append(seat_info)

        return seat_data


class MovieReviewSerializer(serializers.ModelSerializer):
    """Serializer for Movie Review"""

    user = serializers.SerializerMethodField()

    class Meta:
        model = MovieReview
        fields = ['id', 'rating', 'title', 'review', 'user', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_user(self, obj):
        return {
            'id': obj.user.id,
            'username': obj.user.username,
            'full_name': obj.user.full_name,
        }


class MovieReviewCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating Movie Review"""

    class Meta:
        model = MovieReview
        fields = ['rating', 'title', 'review']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        validated_data['movie'] = self.context['movie']
        return super().create(validated_data)
