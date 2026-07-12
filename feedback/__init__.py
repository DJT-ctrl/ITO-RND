"""Feedback loop: calibration, structured lessons, and predict-time learning.

Phase A: passive calibration.
Phase B: template feedback records.
Phase C: deterministic cluster routing.
Phase D (next): feedback injection at predict time.
See planning/validation-feedback-loop/.
"""

from feedback.calibration import apply_calibration, compute_mean_delta
from feedback.generate import generate_template_feedback, generate_template_feedback_from_record
from feedback.routing import assign_cluster_id
from feedback.schemas import (
    CalibrationResult,
    CalibrationStats,
    FeedbackPayload,
    FeedbackRecord,
)

__all__ = [
    "CalibrationResult",
    "CalibrationStats",
    "FeedbackPayload",
    "FeedbackRecord",
    "apply_calibration",
    "assign_cluster_id",
    "compute_mean_delta",
    "generate_template_feedback",
    "generate_template_feedback_from_record",
]
