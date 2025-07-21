import django_filters
from django.db import models
from .models import Movie, Showtime


class MovieFilter(django_filters.FilterSet):
    """Filter for Movie model"""

    genre = django_filters.CharFilter(field_name='genres__name', lookup_expr='icontains')
    language = django_filters.CharFilter(field_name='languages__name', lookup_expr='icontains')
    rating = django_filters.CharFilter()
    status = django_filters.ChoiceFilter(choices=Movie.STATUS_CHOICES)
    release_date_from = django_filters.DateFilter(field_name='release_date', lookup_expr='gte')
    release_date_to = django_filters.DateFilter(field_name='release_date', lookup_expr='lte')
    imdb_rating_min = django_filters.NumberFilter(field_name='imdb_rating', lookup_expr='gte')
    imdb_rating_max = django_filters.NumberFilter(field_name='imdb_rating', lookup_expr='lte')

    class Meta:
        model = Movie
        fields = {
            'title': ['icontains'],
            'director': ['icontains'],
            'duration': ['gte', 'lte'],
        }


class ShowtimeFilter(django_filters.FilterSet):
    """Filter for Showtime model"""

    movie = django_filters.UUIDFilter(field_name='movie__id')
    cinema = django_filters.UUIDFilter(field_name='screen__cinema__id')
    city = django_filters.CharFilter(field_name='screen__cinema__city', lookup_expr='icontains')
    show_date = django_filters.DateFilter()
    show_date_from = django_filters.DateFilter(field_name='show_date', lookup_expr='gte')
    show_date_to = django_filters.DateFilter(field_name='show_date', lookup_expr='lte')
    screen_type = django_filters.CharFilter(field_name='screen__screen_type')

    class Meta:
        model = Showtime
        fields = {
            'base_price': ['gte', 'lte'],
            'show_time': ['gte', 'lte'],
        }
