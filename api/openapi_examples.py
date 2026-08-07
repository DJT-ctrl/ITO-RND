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
            "niche": "B2B SaaS",
            "hook_type": "story",
            "linkedin_url": "https://www.linkedin.com/posts/example-101",
            "engagement_anomaly_flag": False,
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
    "cluster_coaching": {
        "status": "ready",
        "summary": "Lead with the operational outcome before the hiring announcement.",
        "evidence": {
            "cluster_id": "saas_b2b_short_prose_micro",
            "cluster_label": "saas_b2b: short prose posts (micro followers)",
            "sample_count": 18,
            "validated_feedback_count": 3,
            "confidence": "cluster_validated",
            "age_bucket": None,
            "summary": "Approved lessons in this cluster favor specific reader-facing openings.",
        },
        "primary_action": {
            "priority": "high",
            "title": "Lead with the customer outcome",
            "draft_anchor": "Excited to announce",
            "diagnosis": "The opening expresses enthusiasm but does not give the reader a concrete reason to continue before the company announcement.",
            "edit_instruction": "Replace the opening with the operational outcome this hire will help create, then introduce the role in the next sentence.",
            "example_replacement": "We are cutting customer setup time in half. That is why we hired a backend engineer to scale the workflow.",
            "expected_effect": "A specific outcome creates immediate reader relevance without promising a performance result.",
            "evidence_refs": ["neighbor:post-101", "feedback:prediction-101"],
        },
        "supporting_actions": [],
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
    "cross_references": {
        "status": "ready",
        "selection_method": "global_semantic_performance_v1",
        "baseline_percentile": 81.0,
        "baseline_method": "audience_adjusted_weighted_neighbors",
        "candidates_evaluated": 30,
        "eligible_candidates": 2,
        "references": [
            {
                "post": {
                    **SIMILAR_POSTS_RESPONSE_EXAMPLE["results"][0],
                    "post_id": "post-224",
                    "content": "Three lessons from hiring our first platform engineer.",
                    "engagement_percentile": 94.0,
                    "audience_adjusted_percentile": 91.0,
                    "cosine_distance": 0.07,
                },
                "comparison_metric": "audience_adjusted_percentile",
                "effective_percentile": 91.0,
                "percentile_uplift": 10.0,
                "selection_score": 34.8,
                "selection_reasons": [
                    "Semantic match is within the 0.25 distance threshold (0.070).",
                    "Its audience adjusted percentile is 91.0, 10.0 points above the draft baseline.",
                ],
                "observed_strengths": ["Specific outcome-led opening"],
                "suggested_adaptation": "Lead with the team outcome before the hiring announcement.",
            }
        ],
        "overall_feedback": ["Make the opening concrete without copying the reference wording."],
        "caveats": [
            "Historical performance is observational; these examples do not prove that a wording choice caused engagement."
        ],
    },
    "errors": [],
    "run_metadata": None,
    "query_embedding": None,
    "embedding_model_version": "models/gemini-embedding-001",
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
