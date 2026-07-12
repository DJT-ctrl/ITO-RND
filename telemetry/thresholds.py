"""Threshold evaluation for evaluation-cycle telemetry warnings."""

from __future__ import annotations

from config.settings import Settings
from telemetry.schemas import RunMetadata, StepTelemetry, TelemetryWarning


def evaluate_thresholds(metadata: RunMetadata, settings: Settings) -> list[TelemetryWarning]:
    warnings: list[TelemetryWarning] = []

    if metadata.total_cost_usd > settings.eval_cost_warning_usd:
        warnings.append(
            TelemetryWarning(
                code="cost_threshold",
                message=(
                    f"Evaluation cost ${metadata.total_cost_usd:.4f} exceeds "
                    f"warning threshold ${settings.eval_cost_warning_usd:.2f}"
                ),
                threshold=settings.eval_cost_warning_usd,
                actual=metadata.total_cost_usd,
            )
        )

    if metadata.total_latency_ms > settings.eval_latency_warning_ms:
        warnings.append(
            TelemetryWarning(
                code="latency_threshold",
                message=(
                    f"Total latency {metadata.total_latency_ms / 1000:.1f}s exceeds "
                    f"warning threshold {settings.eval_latency_warning_ms / 1000:.1f}s"
                ),
                threshold=float(settings.eval_latency_warning_ms),
                actual=metadata.total_latency_ms,
            )
        )

    for step in metadata.steps:
        if step.latency_ms > settings.eval_step_latency_warning_ms:
            warnings.append(
                TelemetryWarning(
                    code="step_latency_threshold",
                    message=(
                        f"Step '{step.label}' took {step.latency_ms / 1000:.1f}s "
                        f"(threshold {settings.eval_step_latency_warning_ms / 1000:.1f}s)"
                    ),
                    threshold=float(settings.eval_step_latency_warning_ms),
                    actual=step.latency_ms,
                )
            )

    return warnings


def steps_for_stage(steps: list[StepTelemetry], stage: str) -> list[StepTelemetry]:
    return [s for s in steps if s.stage == stage]


def stage_summary(steps: list[StepTelemetry], stage: str) -> tuple[float, float]:
    """Return (total_latency_ms, total_cost_usd) for a stage."""
    stage_steps = steps_for_stage(steps, stage)
    if not stage_steps:
        return 0.0, 0.0
    latency = max(s.latency_ms for s in stage_steps)
    cost = sum(s.cost_usd for s in stage_steps)
    return latency, cost
