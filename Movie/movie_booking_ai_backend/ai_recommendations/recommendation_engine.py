"""
Movie recommendation engine with multiple algorithms
"""
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import TruncatedSVD
from django.db.models import Count, Avg, Q
from django.utils import timezone
from datetime import timedelta
import logging
import openai
from django.conf import settings

from .models import UserPreference, MovieInteraction, RecommendationCache
from movies.models import Movie, Genre
from bookings.models import Booking

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """Main recommendation engine class"""

    def __init__(self, user=None):
        self.user = user
        self.last_algorithm = None

    def get_personalized_recommendations(self, count=10, city=None, include_watched=False):
        """Get personalized recommendations using hybrid approach"""

        if not self.user:
            return self.get_trending_recommendations(count=count, city=city)

        # Try to get cached recommendations first
        cache_key = f"personalized_{self.user.id}_{count}_{city}_{include_watched}"
        cached = self._get_cached_recommendations(cache_key)
        if cached:
            self.last_algorithm = 'cached_hybrid'
            return cached

        try:
            # Get user preferences
            user_prefs = getattr(self.user, 'ai_preferences', None)

            if not user_prefs:
                # No preferences, use trending + content-based
                recommendations = self._combine_recommendations([
                    (self.get_trending_recommendations(count=count//2, city=city), 0.6),
                    (self.get_content_based_recommendations(count=count//2, include_watched=include_watched), 0.4)
                ], count)
                self.last_algorithm = 'trending_content_hybrid'
            else:
                # Use preference weights for hybrid approach
                recommendations_sources = []

                if user_prefs.enable_collaborative_filtering:
                    collab_recs = self.get_collaborative_recommendations(
                        count=count, include_watched=include_watched
                    )
                    recommendations_sources.append((collab_recs, user_prefs.similar_users_weight))

                if user_prefs.enable_content_based:
                    content_recs = self.get_content_based_recommendations(
                        count=count, include_watched=include_watched
                    )
                    recommendations_sources.append((content_recs, user_prefs.rating_weight + user_prefs.genre_weight))

                # Add trending with recency and popularity weights
                trending_recs = self.get_trending_recommendations(count=count, city=city)
                trending_weight = user_prefs.popularity_weight + user_prefs.recency_weight
                recommendations_sources.append((trending_recs, trending_weight))

                if recommendations_sources:
                    recommendations = self._combine_recommendations(recommendations_sources, count)
                    self.last_algorithm = 'hybrid_weighted'
                else:
                    # Fallback to trending
                    recommendations = self.get_trending_recommendations(count=count, city=city)
                    self.last_algorithm = 'trending_fallback'

            # Cache the results
            self._cache_recommendations(cache_key, recommendations, hours=2)
            return recommendations

        except Exception as e:
            logger.error(f"Personalized recommendations failed: {str(e)}")
            # Fallback to trending recommendations
            recommendations = self.get_trending_recommendations(count=count, city=city)
            self.last_algorithm = 'trending_error_fallback'
            return recommendations

    def get_collaborative_recommendations(self, count=10, include_watched=False):
        """Collaborative filtering recommendations"""

        try:
            if not self.user:
                return self.get_trending_recommendations(count=count)

            # Find users with similar preferences/bookings
            user_interactions = MovieInteraction.objects.filter(user=self.user).values_list('movie_id', flat=True)
            if not user_interactions:
                return self.get_trending_recommendations(count=count)

            # Find users who interacted with similar movies
            similar_users = MovieInteraction.objects.filter(
                movie_id__in=user_interactions
            ).exclude(user=self.user).values('user_id').annotate(
                common_movies=Count('movie_id')
            ).filter(common_movies__gte=2).order_by('-common_movies')[:50]

            if not similar_users:
                return self.get_content_based_recommendations(count=count, include_watched=include_watched)

            similar_user_ids = [user['user_id'] for user in similar_users]

            # Get movies liked by similar users that current user hasn't interacted with
            excluded_movies = set(user_interactions)
            if not include_watched:
                # Also exclude movies user has bookings for
                booked_movies = Booking.objects.filter(
                    user=self.user, status='confirmed'
                ).values_list('showtime__movie_id', flat=True)
                excluded_movies.update(booked_movies)

            recommended_movies = MovieInteraction.objects.filter(
                user_id__in=similar_user_ids,
                interaction_type__in=['like', 'book', 'review']
            ).exclude(
                movie_id__in=excluded_movies
            ).values('movie_id').annotate(
                score=Count('id') + Avg('interaction_strength')
            ).order_by('-score')[:count]

            recommendations = []
            for movie_data in recommended_movies:
                try:
                    movie = Movie.objects.get(id=movie_data['movie_id'])
                    recommendations.append({
                        'movie': movie,
                        'score': float(movie_data['score']),
                        'reason': 'Users with similar taste also liked this movie',
                        'algorithm': 'collaborative_filtering'
                    })
                except Movie.DoesNotExist:
                    continue

            self.last_algorithm = 'collaborative_filtering'
            return recommendations[:count]

        except Exception as e:
            logger.error(f"Collaborative filtering failed: {str(e)}")
            return self.get_trending_recommendations(count=count)

    def get_content_based_recommendations(self, count=10, genre=None, include_watched=False):
        """Content-based filtering recommendations"""

        try:
            # Get user's preferred genres from interactions or preferences
            preferred_genres = []

            if self.user:
                # Get genres from user interactions
                user_genre_interactions = MovieInteraction.objects.filter(
                    user=self.user,
                    interaction_type__in=['like', 'book', 'review']
                ).values('movie__genres__name').annotate(
                    count=Count('id')
                ).order_by('-count')[:5]

                preferred_genres = [item['movie__genres__name'] for item in user_genre_interactions if item['movie__genres__name']]

                # Add user's preferred genres from profile
                if hasattr(self.user, 'ai_preferences'):
                    user_prefs = getattr(self.user, 'preferred_genres', [])
                    preferred_genres.extend(user_prefs)

            if genre:
                preferred_genres = [genre]

            # Build query for content-based recommendations
            query = Q(status='now_showing')

            if preferred_genres:
                query &= Q(genres__name__in=preferred_genres)

            # Exclude watched movies if requested
            if self.user and not include_watched:
                watched_movies = MovieInteraction.objects.filter(
                    user=self.user
                ).values_list('movie_id', flat=True)
                if watched_movies:
                    query &= ~Q(id__in=watched_movies)

                # Also exclude booked movies
                booked_movies = Booking.objects.filter(
                    user=self.user, status='confirmed'
                ).values_list('showtime__movie_id', flat=True)
                if booked_movies:
                    query &= ~Q(id__in=booked_movies)

            # Get movies and calculate content similarity
            movies = Movie.objects.filter(query).select_related().prefetch_related('genres')[:100]

            if not movies:
                return self.get_trending_recommendations(count=count)

            recommendations = []
            for movie in movies[:count]:
                # Calculate content score based on genre match, rating, and recency
                genre_score = 0
                if preferred_genres:
                    movie_genres = [g.name for g in movie.genres.all()]
                    genre_matches = len(set(preferred_genres) & set(movie_genres))
                    genre_score = genre_matches / len(preferred_genres) if preferred_genres else 0

                rating_score = float(movie.imdb_rating or 7.0) / 10.0

                # Recency score (newer movies get higher score)
                days_since_release = (timezone.now().date() - movie.release_date).days
                recency_score = max(0, 1 - (days_since_release / 365))  # Decays over a year

                # Combined score
                final_score = (genre_score * 0.4 + rating_score * 0.4 + recency_score * 0.2)

                reason = f"Based on your interest in {', '.join(preferred_genres[:2]) if preferred_genres else 'popular movies'}"

                recommendations.append({
                    'movie': movie,
                    'score': final_score,
                    'reason': reason,
                    'algorithm': 'content_based'
                })

            # Sort by score
            recommendations.sort(key=lambda x: x['score'], reverse=True)

            self.last_algorithm = 'content_based'
            return recommendations[:count]

        except Exception as e:
            logger.error(f"Content-based recommendations failed: {str(e)}")
            return self.get_trending_recommendations(count=count)

    def get_trending_recommendations(self, count=10, city=None):
        """Get trending movies based on bookings and ratings"""

        try:
            # Get movies with recent bookings (last 7 days)
            recent_date = timezone.now().date() - timedelta(days=7)

            query = Q(status='now_showing')

            if city:
                query &= Q(showtimes__screen__cinema__city__icontains=city)

            trending_movies = Movie.objects.filter(query).filter(
                showtimes__show_date__gte=recent_date
            ).annotate(
                booking_count=Count('showtimes__bookings', filter=Q(showtimes__bookings__status='confirmed')),
                avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))
            ).exclude(booking_count=0).order_by('-booking_count', '-avg_rating')[:count * 2]

            if not trending_movies:
                # Fallback to highly rated recent movies
                trending_movies = Movie.objects.filter(
                    status='now_showing',
                    release_date__gte=timezone.now().date() - timedelta(days=90)
                ).order_by('-imdb_rating', '-release_date')[:count]

            recommendations = []
            for movie in trending_movies[:count]:
                booking_count = getattr(movie, 'booking_count', 0)
                avg_rating = getattr(movie, 'avg_rating', movie.imdb_rating or 7.0)

                # Calculate trending score
                score = (booking_count * 0.6) + (float(avg_rating) / 10 * 0.4)

                recommendations.append({
                    'movie': movie,
                    'score': score,
                    'reason': f"Trending movie with {booking_count} recent bookings",
                    'algorithm': 'trending'
                })

            self.last_algorithm = 'trending'
            return recommendations

        except Exception as e:
            logger.error(f"Trending recommendations failed: {str(e)}")
            # Ultimate fallback - recent movies by rating
            return self._get_fallback_recommendations(count)

    def get_similar_movie_recommendations(self, movie, count=10, include_watched=False):
        """Get movies similar to a specific movie"""

        try:
            # Find movies with similar genres
            movie_genres = list(movie.genres.all())

            similar_movies = Movie.objects.filter(
                genres__in=movie_genres,
                status='now_showing'
            ).exclude(id=movie.id).annotate(
                genre_match_count=Count('genres', filter=Q(genres__in=movie_genres))
            ).order_by('-genre_match_count', '-imdb_rating')[:count * 2]

            if self.user and not include_watched:
                # Exclude watched movies
                watched_movies = MovieInteraction.objects.filter(
                    user=self.user
                ).values_list('movie_id', flat=True)
                if watched_movies:
                    similar_movies = similar_movies.exclude(id__in=watched_movies)

            recommendations = []
            for similar_movie in similar_movies[:count]:
                genre_match = getattr(similar_movie, 'genre_match_count', 0)
                score = (genre_match / len(movie_genres)) * 0.7 + (float(similar_movie.imdb_rating or 7.0) / 10) * 0.3

                shared_genres = [g.name for g in similar_movie.genres.all() if g in movie_genres]
                reason = f"Similar to {movie.title} - shares genres: {', '.join(shared_genres[:2])}"

                recommendations.append({
                    'movie': similar_movie,
                    'score': score,
                    'reason': reason,
                    'algorithm': 'similar_movies'
                })

            self.last_algorithm = 'similar_movies'
            return recommendations

        except Exception as e:
            logger.error(f"Similar movie recommendations failed: {str(e)}")
            return self.get_trending_recommendations(count=count)

    def get_genre_based_recommendations(self, genre, count=10, city=None, include_watched=False):
        """Get recommendations for a specific genre"""

        try:
            query = Q(genres__name__icontains=genre, status='now_showing')

            if city:
                query &= Q(showtimes__screen__cinema__city__icontains=city)

            if self.user and not include_watched:
                watched_movies = MovieInteraction.objects.filter(
                    user=self.user
                ).values_list('movie_id', flat=True)
                if watched_movies:
                    query &= ~Q(id__in=watched_movies)

            genre_movies = Movie.objects.filter(query).annotate(
                booking_count=Count('showtimes__bookings', filter=Q(showtimes__bookings__status='confirmed')),
                avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))
            ).order_by('-imdb_rating', '-booking_count')[:count]

            recommendations = []
            for movie in genre_movies:
                rating_score = float(movie.imdb_rating or 7.0) / 10
                booking_score = min(getattr(movie, 'booking_count', 0) / 100, 1.0)  # Normalize bookings
                score = rating_score * 0.7 + booking_score * 0.3

                recommendations.append({
                    'movie': movie,
                    'score': score,
                    'reason': f"Popular {genre} movie",
                    'algorithm': 'genre_based'
                })

            self.last_algorithm = 'genre_based'
            return recommendations

        except Exception as e:
            logger.error(f"Genre-based recommendations failed: {str(e)}")
            return self.get_trending_recommendations(count=count)

    def get_ai_powered_recommendations(self, user_query, count=10):
        """Get AI-powered recommendations using OpenAI"""

        if not settings.OPENAI_API_KEY:
            logger.warning("OpenAI API key not configured")
            return self.get_personalized_recommendations(count=count)

        try:
            # Get available movies
            movies = Movie.objects.filter(status='now_showing').values(
                'id', 'title', 'description', 'genres__name', 'director', 'imdb_rating'
            )[:50]  # Limit for API efficiency

            movie_context = "\n".join([
                f"{movie['title']} ({movie['director']}) - {movie['genres__name']} - Rating: {movie['imdb_rating']}"
                for movie in movies
            ])

            user_preferences = ""
            if self.user and hasattr(self.user, 'ai_preferences'):
                prefs = self.user.ai_preferences
                user_preferences = f"User prefers genres: {', '.join(self.user.preferred_genres)}"

            prompt = f"""
            Based on the user query: "{user_query}"
            {user_preferences}

            Available movies:
            {movie_context}

            Recommend {count} movies that best match the user's request. 
            Return only the movie titles, one per line.
            """

            openai.api_key = settings.OPENAI_API_KEY
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500
            )

            recommended_titles = response.choices[0].message.content.strip().split('\n')

            recommendations = []
            for title in recommended_titles[:count]:
                try:
                    movie = Movie.objects.filter(title__icontains=title.strip()).first()
                    if movie:
                        recommendations.append({
                            'movie': movie,
                            'score': 0.9,  # High confidence for AI recommendations
                            'reason': f'AI recommendation based on: "{user_query}"',
                            'algorithm': 'openai_gpt'
                        })
                except:
                    continue

            self.last_algorithm = 'openai_gpt'
            return recommendations

        except Exception as e:
            logger.error(f"AI-powered recommendations failed: {str(e)}")
            return self.get_personalized_recommendations(count=count)

    def _combine_recommendations(self, sources, count):
        """Combine recommendations from multiple sources"""

        combined_scores = {}

        for recommendations, weight in sources:
            for rec in recommendations:
                movie_id = rec['movie'].id
                weighted_score = rec['score'] * weight

                if movie_id in combined_scores:
                    combined_scores[movie_id]['score'] += weighted_score
                    combined_scores[movie_id]['algorithms'].append(rec['algorithm'])
                else:
                    combined_scores[movie_id] = {
                        'movie': rec['movie'],
                        'score': weighted_score,
                        'reason': rec['reason'],
                        'algorithms': [rec['algorithm']]
                    }

        # Convert to list and sort
        combined_recommendations = []
        for movie_id, data in combined_scores.items():
            data['algorithm'] = '+'.join(data['algorithms'])
            combined_recommendations.append(data)

        combined_recommendations.sort(key=lambda x: x['score'], reverse=True)
        return combined_recommendations[:count]

    def _get_cached_recommendations(self, cache_key):
        """Get cached recommendations if available"""
        try:
            cache_obj = RecommendationCache.objects.get(
                cache_key=cache_key,
                expires_at__gt=timezone.now()
            )
            cache_obj.hit_count += 1
            cache_obj.save()
            return cache_obj.cached_data
        except RecommendationCache.DoesNotExist:
            return None

    def _cache_recommendations(self, cache_key, recommendations, hours=1):
        """Cache recommendations"""
        try:
            cache_data = []
            for rec in recommendations:
                cache_data.append({
                    'movie_id': str(rec['movie'].id),
                    'score': rec['score'],
                    'reason': rec['reason'],
                    'algorithm': rec['algorithm']
                })

            RecommendationCache.objects.update_or_create(
                cache_key=cache_key,
                defaults={
                    'user': self.user,
                    'recommendation_type': self.last_algorithm or 'hybrid',
                    'cached_data': cache_data,
                    'expires_at': timezone.now() + timedelta(hours=hours)
                }
            )
        except Exception as e:
            logger.error(f"Failed to cache recommendations: {str(e)}")

    def _get_fallback_recommendations(self, count):
        """Ultimate fallback recommendations"""
        try:
            movies = Movie.objects.filter(
                status='now_showing'
            ).order_by('-imdb_rating', '-release_date')[:count]

            recommendations = []
            for movie in movies:
                recommendations.append({
                    'movie': movie,
                    'score': float(movie.imdb_rating or 7.0) / 10,
                    'reason': 'Highly rated movie',
                    'algorithm': 'fallback'
                })

            return recommendations
        except:
            return []

    def get_last_algorithm_used(self):
        """Get the last algorithm used"""
        return self.last_algorithm or 'unknown'
