import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator

User = get_user_model()


class UserPreference(models.Model):
    """User preferences for personalized recommendations"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='ai_preferences')

    # Preference weights (0.0 to 1.0)
    genre_weight = models.FloatField(default=0.3, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    rating_weight = models.FloatField(default=0.2, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    popularity_weight = models.FloatField(default=0.2, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    recency_weight = models.FloatField(default=0.1, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    similar_users_weight = models.FloatField(default=0.2, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])

    # User behavior tracking
    preferred_show_times = models.JSONField(default=list, help_text="Preferred time slots")
    preferred_cinema_types = models.JSONField(default=list, help_text="Preferred cinema types")
    booking_frequency = models.CharField(max_length=20, default='medium', choices=[
        ('low', 'Low (< 1 per month)'),
        ('medium', 'Medium (1-4 per month)'),
        ('high', 'High (> 4 per month)'),
    ])

    # ML model preferences
    enable_collaborative_filtering = models.BooleanField(default=True)
    enable_content_based = models.BooleanField(default=True)
    enable_hybrid_recommendations = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_preferences'

    def __str__(self):
        return f"Preferences for {self.user.email}"


class MovieInteraction(models.Model):
    """Track user interactions with movies for ML training"""

    INTERACTION_TYPES = [
        ('view', 'Movie View'),
        ('like', 'Movie Like'),
        ('dislike', 'Movie Dislike'),
        ('book', 'Movie Booking'),
        ('search', 'Movie Search'),
        ('trailer_view', 'Trailer View'),
        ('review', 'Movie Review'),
        ('share', 'Movie Share'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='movie_interactions')
    movie = models.ForeignKey('movies.Movie', on_delete=models.CASCADE, related_name='user_interactions')

    # Interaction details
    interaction_type = models.CharField(max_length=20, choices=INTERACTION_TYPES)
    interaction_strength = models.FloatField(
        default=1.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(5.0)],
        help_text="Interaction strength (0.0 to 5.0)"
    )

    # Context
    session_id = models.CharField(max_length=100, blank=True)
    device_type = models.CharField(max_length=20, default='web')
    location = models.CharField(max_length=100, blank=True)

    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'movie_interactions'
        indexes = [
            models.Index(fields=['user', 'movie']),
            models.Index(fields=['interaction_type', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.interaction_type} - {self.movie.title}"


class RecommendationRequest(models.Model):
    """Track recommendation requests for analytics and caching"""

    RECOMMENDATION_TYPES = [
        ('personalized', 'Personalized Recommendations'),
        ('collaborative', 'Collaborative Filtering'),
        ('content_based', 'Content-Based Filtering'),
        ('trending', 'Trending Movies'),
        ('similar', 'Similar Movies'),
        ('genre_based', 'Genre-Based Recommendations'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recommendation_requests', null=True, blank=True)

    # Request details
    recommendation_type = models.CharField(max_length=20, choices=RECOMMENDATION_TYPES)
    request_params = models.JSONField(default=dict)

    # Response details
    recommended_movies = models.JSONField(default=list)  # List of movie IDs with scores
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    algorithm_used = models.CharField(max_length=50, blank=True)

    # Context
    session_id = models.CharField(max_length=100, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    # Timestamps
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recommendation_requests'
        indexes = [
            models.Index(fields=['user', 'recommendation_type']),
            models.Index(fields=['requested_at']),
        ]

    def __str__(self):
        user_email = self.user.email if self.user else 'Anonymous'
        return f"{user_email} - {self.recommendation_type}"


class RecommendationFeedback(models.Model):
    """User feedback on recommendations for model improvement"""

    FEEDBACK_TYPES = [
        ('click', 'Clicked on Recommendation'),
        ('book', 'Booked Recommended Movie'),
        ('dismiss', 'Dismissed Recommendation'),
        ('like', 'Liked Recommendation'),
        ('dislike', 'Disliked Recommendation'),
        ('not_interested', 'Not Interested'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recommendation_feedback')
    recommendation_request = models.ForeignKey(RecommendationRequest, on_delete=models.CASCADE, related_name='feedback')
    movie = models.ForeignKey('movies.Movie', on_delete=models.CASCADE, related_name='recommendation_feedback')

    # Feedback details
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPES)
    feedback_score = models.FloatField(
        validators=[MinValueValidator(-1.0), MaxValueValidator(1.0)],
        help_text="Feedback score (-1.0 to 1.0)"
    )

    # Additional context
    recommendation_position = models.PositiveIntegerField(help_text="Position in recommendation list")
    time_to_feedback_seconds = models.PositiveIntegerField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recommendation_feedback'
        unique_together = ['user', 'recommendation_request', 'movie']

    def __str__(self):
        return f"{self.user.email} - {self.feedback_type} - {self.movie.title}"


class MLModel(models.Model):
    """Track ML models used for recommendations"""

    MODEL_TYPES = [
        ('collaborative_filtering', 'Collaborative Filtering'),
        ('content_based', 'Content-Based Filtering'),
        ('matrix_factorization', 'Matrix Factorization'),
        ('deep_learning', 'Deep Learning Model'),
        ('ensemble', 'Ensemble Model'),
        ('openai_api', 'OpenAI API'),
    ]

    STATUS_CHOICES = [
        ('training', 'Training'),
        ('active', 'Active'),
        ('deprecated', 'Deprecated'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    model_type = models.CharField(max_length=30, choices=MODEL_TYPES)
    version = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='training')

    # Model metrics
    accuracy_score = models.FloatField(null=True, blank=True)
    precision_score = models.FloatField(null=True, blank=True)
    recall_score = models.FloatField(null=True, blank=True)
    f1_score = models.FloatField(null=True, blank=True)

    # Model configuration
    hyperparameters = models.JSONField(default=dict)
    training_data_size = models.PositiveIntegerField(null=True, blank=True)

    # File paths (for locally stored models)
    model_file_path = models.CharField(max_length=500, blank=True)
    feature_columns = models.JSONField(default=list)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    trained_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ml_models'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} v{self.version} ({self.model_type})"


class RecommendationCache(models.Model):
    """Cache recommendations for performance"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recommendation_cache', null=True, blank=True)

    # Cache key and data
    cache_key = models.CharField(max_length=255, unique=True)
    recommendation_type = models.CharField(max_length=50)
    cached_data = models.JSONField()

    # Cache metadata
    hit_count = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'recommendation_cache'
        indexes = [
            models.Index(fields=['cache_key']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"Cache: {self.recommendation_type} - {self.cache_key}"

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at


class ChatbotConversation(models.Model):
    """Track chatbot conversations for movie recommendations"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chatbot_conversations', null=True, blank=True)
    session_id = models.CharField(max_length=100)

    # Conversation details
    messages = models.JSONField(default=list)  # List of message objects
    current_intent = models.CharField(max_length=100, blank=True)
    context = models.JSONField(default=dict)  # Conversation context

    # Recommendations given
    recommended_movies = models.ManyToManyField('movies.Movie', blank=True, related_name='chatbot_recommendations')

    # Status
    is_active = models.BooleanField(default=True)
    satisfaction_score = models.FloatField(null=True, blank=True, validators=[MinValueValidator(1.0), MaxValueValidator(5.0)])

    # Timestamps
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'chatbot_conversations'
        indexes = [
            models.Index(fields=['user', 'started_at']),
            models.Index(fields=['session_id']),
        ]

    def __str__(self):
        user_email = self.user.email if self.user else 'Anonymous'
        return f"Conversation: {user_email} - {self.started_at}"
