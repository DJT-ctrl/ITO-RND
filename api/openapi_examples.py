"""OpenAPI request/response examples for the v1 public API contract."""

from api.schemas import API_PATH_VERSION

HEALTH_OK_EXAMPLE = {"status": "ok", "api_version": API_PATH_VERSION}

SIMILAR_POSTS_REQUEST_EXAMPLE = {
    "content": "Excited to share what we learned shipping our first AI feature.",
    "limit": 5,
}

SIMILAR_POSTS_RESPONSE_EXAMPLE = {
    "query_content": "Excited to share what we learned shipping our first AI feature.",
    "results": [
        {
            "post_id": "post-101",
            "content": "Three lessons from our AI launch week…",
            "likes": 120,
            "comments": 18,
            "shares": 4,
            "total_engagement": 142,
            "engagement_percentile": 82.5,
            "engagement_zscore": 1.1,
            "cosine_distance": 0.08,
            "follower_count": 4200,
            "engagement_rate": 0.034,
            "audience_adjusted_percentile": 79.0,
            "hashtag_count": 2,
            "word_count": 186,
            "topic": "product launch",
            "hook_type": "story",
        }
    ],
}

EVALUATE_REQUEST_EXAMPLE = {
    "content": "Excited to announce our new backend engineering hire!",
    "variant_strategy": "dimension",
    "reembed_variant_neighbors": False,
    "user_id": "user-42",
    "use_voice_profile": True,
}

EVALUATE_RESPONSE_EXAMPLE = {
    "draft_content": "Excited to announce our new backend engineering hire!",
    "similar_posts": SIMILAR_POSTS_RESPONSE_EXAMPLE["results"],
    "voice_profile": {
        "dominant_hook_type": "announcement",
        "dominant_tone": "professional",
        "dominant_writing_style": "concise",
        "avg_word_count": 142.0,
        "avg_hashtag_count": 1.5,
        "cta_usage_ratio": 0.4,
        "sample_size": 8,
    },
    "predictor_result": {
        "predicted_engagement_percentile": 81.0,
        "predicted_total_engagement": 42,
        "predicted_likes": 30,
        "predicted_comments": 8,
        "predicted_shares": 4,
        "reasoning": "Neighbors with similar hiring announcements scored in the 75–85 percentile band.",
    },
    "diagnostics": {
        "seo": {
            "score": 7.5,
            "flaws": ["Missing industry keywords in the first line"],
            "advantages": ["Clear role signal"],
            "improvements": ["Add stack or team context in the hook"],
        },
        "clarity": {
            "score": 8.0,
            "flaws": [],
            "advantages": ["Single clear announcement"],
            "improvements": ["Optional one-line benefit for the reader"],
        },
        "tone": {
            "score": 7.0,
            "flaws": ["Slightly generic enthusiasm"],
            "advantages": ["Professional and approachable"],
            "improvements": ["Name the team or mission tie-in"],
        },
    },
    "variants": [
        {
            "variant_text": "We just welcomed a backend engineer to help scale our API platform.",
            "rationale": "Leads with outcome and team context.",
            "strategy_label": "seo-focused",
            "predicted_engagement_percentile": 84.0,
            "predicted_total_engagement": 48,
        }
    ],
    "errors": [],
    "run_metadata": None,
    "query_embedding": None,
    "embedding_model_version": "text-embedding-004",
}

VALIDATION_ERROR_EXAMPLE = {
    "detail": [
        {
            "loc": ["body", "content"],
            "msg": "String should have at least 1 character",
            "type": "string_too_short",
        }
    ]
}

API_ERROR_EXAMPLE = {
    "code": "EMBED_FAILED",
    "message": "Failed to embed query text.",
    "retryable": True,
    "details": {"provider": "google"},
}
