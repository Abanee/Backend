from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Count, Avg, Q
from datetime import timedelta
import time
import logging

from .models import (
    UserPreference, MovieInteraction, RecommendationRequest,
    RecommendationFeedback, ChatbotConversation, RecommendationCache
)
from .serializers import (
    UserPreferenceSerializer, MovieInteractionSerializer, RecommendationRequestSerializer,
    RecommendationResponseSerializer, RecommendationFeedbackSerializer,
    ChatbotRequestSerializer, ChatbotResponseSerializer, ChatbotConversationSerializer,
    UserInteractionHistorySerializer
)
from .recommendation_engine import RecommendationEngine
from .chatbot import MovieChatbot
from movies.models import Movie
from movies.serializers import MovieListSerializer

logger = logging.getLogger(__name__)


class UserPreferenceView(generics.RetrieveUpdateCreateAPIView):
    """User preference management"""

    serializer_class = UserPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        user_pref, created = UserPreference.objects.get_or_create(user=self.request.user)
        return user_pref


class GetRecommendationsView(generics.GenericAPIView):
    """Get movie recommendations"""

    serializer_class = RecommendationRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start_time = time.time()

        try:
            # Get recommendation parameters
            recommendation_type = serializer.validated_data['recommendation_type']
            count = serializer.validated_data['count']
            genre = serializer.validated_data.get('genre')
            movie_id = serializer.validated_data.get('movie_id')
            city = serializer.validated_data.get('city')
            include_watched = serializer.validated_data['include_watched']

            # Create recommendation request record
            recommendation_request = RecommendationRequest.objects.create(
                user=request.user,
                recommendation_type=recommendation_type,
                request_params=serializer.validated_data,
                session_id=request.session.session_key or '',
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                ip_address=request.META.get('REMOTE_ADDR'),
            )

            # Initialize recommendation engine
            engine = RecommendationEngine(user=request.user)

            # Get recommendations based on type
            if recommendation_type == 'personalized':
                recommendations = engine.get_personalized_recommendations(
                    count=count, city=city, include_watched=include_watched
                )
            elif recommendation_type == 'collaborative':
                recommendations = engine.get_collaborative_recommendations(
                    count=count, include_watched=include_watched
                )
            elif recommendation_type == 'content_based':
                recommendations = engine.get_content_based_recommendations(
                    count=count, genre=genre, include_watched=include_watched
                )
            elif recommendation_type == 'trending':
                recommendations = engine.get_trending_recommendations(count=count, city=city)
            elif recommendation_type == 'similar':
                if not movie_id:
                    return Response(
                        {'error': 'movie_id is required for similar movie recommendations'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                movie = get_object_or_404(Movie, id=movie_id)
                recommendations = engine.get_similar_movie_recommendations(
                    movie=movie, count=count, include_watched=include_watched
                )
            elif recommendation_type == 'genre_based':
                if not genre:
                    return Response(
                        {'error': 'genre is required for genre-based recommendations'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                recommendations = engine.get_genre_based_recommendations(
                    genre=genre, count=count, city=city, include_watched=include_watched
                )
            else:
                return Response(
                    {'error': 'Invalid recommendation type'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            end_time = time.time()
            response_time_ms = int((end_time - start_time) * 1000)

            # Update recommendation request
            recommendation_request.recommended_movies = [
                {'movie_id': str(rec['movie'].id), 'score': rec['score']} 
                for rec in recommendations
            ]
            recommendation_request.response_time_ms = response_time_ms
            recommendation_request.algorithm_used = engine.get_last_algorithm_used()
            recommendation_request.save()

            # Prepare response
            response_data = {
                'recommendations': recommendations,
                'total_count': len(recommendations),
                'request_id': recommendation_request.id,
                'algorithm_used': engine.get_last_algorithm_used(),
                'response_time_ms': response_time_ms,
                'user_preferences_used': hasattr(request.user, 'ai_preferences'),
            }

            response_serializer = RecommendationResponseSerializer(response_data)
            return Response(response_serializer.data)

        except Exception as e:
            logger.error(f"Recommendation generation failed: {str(e)}")
            return Response(
                {'error': 'Failed to generate recommendations. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TrackInteractionView(generics.CreateAPIView):
    """Track user interactions with movies"""

    serializer_class = MovieInteractionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(
            user=self.request.user,
            session_id=self.request.session.session_key or '',
            device_type=self.get_device_type()
        )

    def get_device_type(self):
        """Detect device type from user agent"""
        user_agent = self.request.META.get('HTTP_USER_AGENT', '').lower()
        if 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent:
            return 'mobile'
        elif 'tablet' in user_agent or 'ipad' in user_agent:
            return 'tablet'
        else:
            return 'web'


class SubmitFeedbackView(generics.CreateAPIView):
    """Submit feedback on recommendations"""

    serializer_class = RecommendationFeedbackSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ChatbotView(generics.GenericAPIView):
    """Chatbot for movie recommendations"""

    serializer_class = ChatbotRequestSerializer
    permission_classes = [permissions.AllowAny]  # Allow anonymous users

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message = serializer.validated_data['message']
        session_id = serializer.validated_data.get('session_id', request.session.session_key or '')
        context = serializer.validated_data.get('context', {})

        try:
            # Initialize chatbot
            chatbot = MovieChatbot(user=request.user if request.user.is_authenticated else None)

            # Get or create conversation
            conversation, created = ChatbotConversation.objects.get_or_create(
                session_id=session_id,
                user=request.user if request.user.is_authenticated else None,
                is_active=True,
                defaults={'context': context}
            )

            # Process message and get response
            response_data = chatbot.process_message(
                message=message,
                conversation=conversation,
                context=context
            )

            response_serializer = ChatbotResponseSerializer(response_data)
            return Response(response_serializer.data)

        except Exception as e:
            logger.error(f"Chatbot processing failed: {str(e)}")
            return Response({
                'response': "I'm sorry, I'm having trouble understanding. Could you please try again?",
                'session_id': session_id,
                'context': context
            })


class UserInteractionHistoryView(generics.ListAPIView):
    """Get user's movie interaction history"""

    serializer_class = UserInteractionHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # This is a placeholder - actual implementation would aggregate interactions
        return []

    def list(self, request, *args, **kwargs):
        # Get user interactions grouped by movie
        interactions = MovieInteraction.objects.filter(
            user=request.user
        ).select_related('movie').values(
            'movie'
        ).annotate(
            total_interactions=Count('id'),
            last_interaction=models.Max('created_at')
        ).order_by('-last_interaction')[:50]

        # Get interaction breakdown for each movie
        result = []
        for interaction in interactions:
            movie = Movie.objects.get(id=interaction['movie'])
            interaction_breakdown = MovieInteraction.objects.filter(
                user=request.user, movie=movie
            ).values('interaction_type').annotate(count=Count('id'))

            result.append({
                'movie': movie,
                'interaction_breakdown': {item['interaction_type']: item['count'] for item in interaction_breakdown},
                'last_interaction': interaction['last_interaction'],
                'total_interactions': interaction['total_interactions']
            })

        serializer = self.get_serializer(result, many=True)
        return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_user_recommendations_summary(request):
    """Get summary of user's recommendation history"""

    # Get recommendation statistics
    total_requests = RecommendationRequest.objects.filter(user=request.user).count()

    recent_requests = RecommendationRequest.objects.filter(
        user=request.user,
        requested_at__gte=timezone.now() - timedelta(days=30)
    ).values('recommendation_type').annotate(count=Count('id'))

    # Get feedback statistics
    feedback_stats = RecommendationFeedback.objects.filter(user=request.user).values(
        'feedback_type'
    ).annotate(count=Count('id'))

    # Get most interacted genres
    top_genres = MovieInteraction.objects.filter(user=request.user).values(
        'movie__genres__name'
    ).annotate(count=Count('id')).order_by('-count')[:5]

    return Response({
        'total_recommendation_requests': total_requests,
        'recent_requests_by_type': {item['recommendation_type']: item['count'] for item in recent_requests},
        'feedback_distribution': {item['feedback_type']: item['count'] for item in feedback_stats},
        'top_genres': [{'genre': item['movie__genres__name'], 'count': item['count']} for item in top_genres],
        'has_preferences': hasattr(request.user, 'ai_preferences'),
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def clear_user_data(request):
    """Clear user's AI recommendation data"""

    data_type = request.data.get('data_type', 'all')

    if data_type in ['all', 'interactions']:
        MovieInteraction.objects.filter(user=request.user).delete()

    if data_type in ['all', 'feedback']:
        RecommendationFeedback.objects.filter(user=request.user).delete()

    if data_type in ['all', 'preferences']:
        if hasattr(request.user, 'ai_preferences'):
            request.user.ai_preferences.delete()

    if data_type in ['all', 'cache']:
        RecommendationCache.objects.filter(user=request.user).delete()

    if data_type in ['all', 'conversations']:
        ChatbotConversation.objects.filter(user=request.user).delete()

    return Response({
        'message': f'Successfully cleared {data_type} data',
        'data_type': data_type
    })
