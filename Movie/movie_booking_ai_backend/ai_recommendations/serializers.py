from rest_framework import serializers
from .models import (
    UserPreference, MovieInteraction, RecommendationRequest, 
    RecommendationFeedback, ChatbotConversation
)
from movies.serializers import MovieListSerializer


class UserPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for user preferences"""

    class Meta:
        model = UserPreference
        fields = [
            'genre_weight', 'rating_weight', 'popularity_weight', 
            'recency_weight', 'similar_users_weight',
            'preferred_show_times', 'preferred_cinema_types', 'booking_frequency',
            'enable_collaborative_filtering', 'enable_content_based', 'enable_hybrid_recommendations'
        ]

    def validate(self, attrs):
        """Validate that weights sum to reasonable values"""
        weights = [
            attrs.get('genre_weight', 0.3),
            attrs.get('rating_weight', 0.2),
            attrs.get('popularity_weight', 0.2),
            attrs.get('recency_weight', 0.1),
            attrs.get('similar_users_weight', 0.2)
        ]

        total_weight = sum(weights)
        if not (0.8 <= total_weight <= 1.2):  # Allow some tolerance
            raise serializers.ValidationError(
                f"Total weight sum ({total_weight}) should be close to 1.0"
            )

        return attrs


class MovieInteractionSerializer(serializers.ModelSerializer):
    """Serializer for movie interactions"""

    class Meta:
        model = MovieInteraction
        fields = [
            'movie', 'interaction_type', 'interaction_strength',
            'session_id', 'device_type', 'location', 'metadata'
        ]
        read_only_fields = ['created_at']


class RecommendationRequestSerializer(serializers.Serializer):
    """Serializer for recommendation requests"""

    RECOMMENDATION_TYPES = [
        ('personalized', 'Personalized Recommendations'),
        ('collaborative', 'Collaborative Filtering'),
        ('content_based', 'Content-Based Filtering'),
        ('trending', 'Trending Movies'),
        ('similar', 'Similar Movies'),
        ('genre_based', 'Genre-Based Recommendations'),
    ]

    recommendation_type = serializers.ChoiceField(choices=RECOMMENDATION_TYPES, default='personalized')
    count = serializers.IntegerField(min_value=1, max_value=50, default=10)
    genre = serializers.CharField(required=False, allow_blank=True)
    movie_id = serializers.UUIDField(required=False, allow_null=True)  # For similar movie recommendations
    city = serializers.CharField(required=False, allow_blank=True)
    include_watched = serializers.BooleanField(default=False)


class MovieRecommendationSerializer(serializers.Serializer):
    """Serializer for movie recommendations response"""

    movie = MovieListSerializer()
    score = serializers.FloatField()
    reason = serializers.CharField(max_length=200)
    algorithm = serializers.CharField(max_length=50)


class RecommendationResponseSerializer(serializers.Serializer):
    """Serializer for recommendation API response"""

    recommendations = MovieRecommendationSerializer(many=True)
    total_count = serializers.IntegerField()
    request_id = serializers.UUIDField()
    algorithm_used = serializers.CharField(max_length=50)
    response_time_ms = serializers.IntegerField()
    user_preferences_used = serializers.BooleanField()


class RecommendationFeedbackSerializer(serializers.ModelSerializer):
    """Serializer for recommendation feedback"""

    class Meta:
        model = RecommendationFeedback
        fields = [
            'recommendation_request', 'movie', 'feedback_type', 
            'feedback_score', 'recommendation_position'
        ]
        read_only_fields = ['created_at']


class ChatMessageSerializer(serializers.Serializer):
    """Serializer for chatbot messages"""

    MESSAGE_TYPES = [
        ('user', 'User Message'),
        ('bot', 'Bot Response'),
        ('system', 'System Message'),
    ]

    type = serializers.ChoiceField(choices=MESSAGE_TYPES)
    content = serializers.CharField(max_length=1000)
    timestamp = serializers.DateTimeField(read_only=True)
    metadata = serializers.JSONField(default=dict, required=False)


class ChatbotRequestSerializer(serializers.Serializer):
    """Serializer for chatbot requests"""

    message = serializers.CharField(max_length=1000)
    session_id = serializers.CharField(max_length=100, required=False)
    context = serializers.JSONField(default=dict, required=False)


class ChatbotResponseSerializer(serializers.Serializer):
    """Serializer for chatbot responses"""

    response = serializers.CharField()
    session_id = serializers.CharField()
    intent = serializers.CharField(required=False)
    recommended_movies = MovieListSerializer(many=True, required=False)
    context = serializers.JSONField(default=dict)
    confidence = serializers.FloatField(required=False)


class ChatbotConversationSerializer(serializers.ModelSerializer):
    """Serializer for chatbot conversations"""

    messages = ChatMessageSerializer(many=True, read_only=True)
    recommended_movies = MovieListSerializer(many=True, read_only=True)

    class Meta:
        model = ChatbotConversation
        fields = [
            'id', 'session_id', 'messages', 'current_intent', 
            'recommended_movies', 'is_active', 'satisfaction_score',
            'started_at', 'last_activity_at', 'ended_at'
        ]
        read_only_fields = ['id', 'started_at']


class UserInteractionHistorySerializer(serializers.Serializer):
    """Serializer for user interaction history"""

    movie = MovieListSerializer()
    interactions = serializers.SerializerMethodField()
    last_interaction = serializers.DateTimeField()
    total_interactions = serializers.IntegerField()

    def get_interactions(self, obj):
        """Get interaction breakdown"""
        return obj.get('interaction_breakdown', {})
