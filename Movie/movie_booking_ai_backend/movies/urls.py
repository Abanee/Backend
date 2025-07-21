from django.urls import path
from . import views

urlpatterns = [
    # Genre and Language endpoints
    path('genres/', views.GenreListView.as_view(), name='genre_list'),
    path('languages/', views.LanguageListView.as_view(), name='language_list'),

    # Movie endpoints
    path('', views.MovieListView.as_view(), name='movie_list'),
    path('<uuid:pk>/', views.MovieDetailView.as_view(), name='movie_detail'),
    path('<uuid:movie_id>/showtimes/', views.movie_showtimes, name='movie_showtimes'),
    path('<uuid:movie_id>/reviews/', views.MovieReviewListView.as_view(), name='movie_reviews'),
    path('<uuid:movie_id>/reviews/create/', views.MovieReviewCreateView.as_view(), name='movie_review_create'),

    # Cinema endpoints
    path('cinemas/', views.CinemaListView.as_view(), name='cinema_list'),
    path('cinemas/<uuid:pk>/', views.CinemaDetailView.as_view(), name='cinema_detail'),
    path('cinemas/<uuid:cinema_id>/showtimes/', views.cinema_showtimes, name='cinema_showtimes'),

    # Showtime endpoints
    path('showtimes/', views.ShowtimeListView.as_view(), name='showtime_list'),
    path('showtimes/<uuid:pk>/', views.ShowtimeDetailView.as_view(), name='showtime_detail'),

    # Special endpoints
    path('trending/', views.trending_movies, name='trending_movies'),
    path('upcoming/', views.upcoming_movies, name='upcoming_movies'),
]
