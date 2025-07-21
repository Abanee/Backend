from rest_framework import generics, filters, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db.models import Q, Avg
from datetime import date, timedelta

from .models import Movie, Cinema, Screen, Showtime, Genre, Language, MovieReview
from .serializers import (
    MovieListSerializer, MovieDetailSerializer, CinemaSerializer, CinemaListSerializer,
    ShowtimeSerializer, ShowtimeDetailSerializer, GenreSerializer, LanguageSerializer,
    MovieReviewSerializer, MovieReviewCreateSerializer
)
from .filters import MovieFilter, ShowtimeFilter


class GenreListView(generics.ListAPIView):
    """List all genres"""

    queryset = Genre.objects.all()
    serializer_class = GenreSerializer
    permission_classes = [AllowAny]


class LanguageListView(generics.ListAPIView):
    """List all languages"""

    queryset = Language.objects.all()
    serializer_class = LanguageSerializer
    permission_classes = [AllowAny]


class MovieListView(generics.ListAPIView):
    """List movies with filtering and search"""

    queryset = Movie.objects.filter(status__in=['now_showing', 'coming_soon'])
    serializer_class = MovieListSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = MovieFilter
    search_fields = ['title', 'director', 'cast']
    ordering_fields = ['release_date', 'title', 'imdb_rating']
    ordering = ['-release_date']


class MovieDetailView(generics.RetrieveAPIView):
    """Movie detail view"""

    queryset = Movie.objects.all()
    serializer_class = MovieDetailSerializer
    permission_classes = [AllowAny]


class CinemaListView(generics.ListAPIView):
    """List cinemas by city"""

    queryset = Cinema.objects.filter(is_active=True)
    serializer_class = CinemaListSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['city', 'state']
    search_fields = ['name', 'city', 'address']
    ordering = ['name']


class CinemaDetailView(generics.RetrieveAPIView):
    """Cinema detail view with screens"""

    queryset = Cinema.objects.filter(is_active=True)
    serializer_class = CinemaSerializer
    permission_classes = [AllowAny]


class ShowtimeListView(generics.ListAPIView):
    """List showtimes with filtering"""

    queryset = Showtime.objects.filter(is_active=True).select_related('movie', 'screen__cinema')
    serializer_class = ShowtimeSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_class = ShowtimeFilter
    ordering = ['show_date', 'show_time']

    def get_queryset(self):
        """Filter showtimes from today onwards"""
        return super().get_queryset().filter(show_date__gte=date.today())


class ShowtimeDetailView(generics.RetrieveAPIView):
    """Showtime detail view with seat map"""

    queryset = Showtime.objects.filter(is_active=True).select_related('movie', 'screen__cinema')
    serializer_class = ShowtimeDetailSerializer
    permission_classes = [AllowAny]


@api_view(['GET'])
@permission_classes([AllowAny])
def movie_showtimes(request, movie_id):
    """Get all showtimes for a specific movie"""

    movie = get_object_or_404(Movie, id=movie_id)
    city = request.query_params.get('city')
    show_date = request.query_params.get('date', date.today())

    queryset = Showtime.objects.filter(
        movie=movie,
        is_active=True,
        show_date=show_date
    ).select_related('screen__cinema')

    if city:
        queryset = queryset.filter(screen__cinema__city__icontains=city)

    serializer = ShowtimeSerializer(queryset, many=True)
    return Response({
        'movie': MovieListSerializer(movie).data,
        'showtimes': serializer.data,
        'date': show_date,
        'city': city
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def cinema_showtimes(request, cinema_id):
    """Get all showtimes for a specific cinema"""

    cinema = get_object_or_404(Cinema, id=cinema_id)
    show_date = request.query_params.get('date', date.today())

    queryset = Showtime.objects.filter(
        screen__cinema=cinema,
        is_active=True,
        show_date=show_date
    ).select_related('movie', 'screen')

    serializer = ShowtimeSerializer(queryset, many=True)
    return Response({
        'cinema': CinemaSerializer(cinema).data,
        'showtimes': serializer.data,
        'date': show_date
    })


class MovieReviewListView(generics.ListAPIView):
    """List reviews for a movie"""

    serializer_class = MovieReviewSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        movie_id = self.kwargs['movie_id']
        return MovieReview.objects.filter(
            movie_id=movie_id,
            is_approved=True
        ).order_by('-created_at')


class MovieReviewCreateView(generics.CreateAPIView):
    """Create a review for a movie"""

    serializer_class = MovieReviewCreateSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        movie_id = self.kwargs['movie_id']
        context['movie'] = get_object_or_404(Movie, id=movie_id)
        return context

    def create(self, request, *args, **kwargs):
        movie_id = self.kwargs['movie_id']
        movie = get_object_or_404(Movie, id=movie_id)

        # Check if user already reviewed this movie
        if MovieReview.objects.filter(movie=movie, user=request.user).exists():
            return Response(
                {'error': 'You have already reviewed this movie'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().create(request, *args, **kwargs)


@api_view(['GET'])
@permission_classes([AllowAny])
def trending_movies(request):
    """Get trending movies based on bookings and ratings"""

    # Get movies with bookings in the last 7 days
    recent_date = date.today() - timedelta(days=7)

    trending_movies = Movie.objects.filter(
        status='now_showing',
        showtimes__show_date__gte=recent_date
    ).annotate(
        avg_rating=Avg('reviews__rating')
    ).distinct().order_by('-avg_rating', '-release_date')[:10]

    serializer = MovieListSerializer(trending_movies, many=True)
    return Response({'trending_movies': serializer.data})


@api_view(['GET'])
@permission_classes([AllowAny])
def upcoming_movies(request):
    """Get upcoming movies"""

    upcoming = Movie.objects.filter(
        status='coming_soon',
        release_date__gte=date.today()
    ).order_by('release_date')[:10]

    serializer = MovieListSerializer(upcoming, many=True)
    return Response({'upcoming_movies': serializer.data})
