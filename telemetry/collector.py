"""RunMetadataCollector — records per-step telemetry during an evaluation cycle."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from config.settings import Settings
from telemetry.pricing import cost_from_embedding_tokens, cost_from_llm_usage, cost_from_tokens
from telemetry.schemas import RunMetadata, StepStage, StepTelemetry, StepCallType, StepStatus
from telemetry.thresholds import evaluate_thresholds


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class RunMetadataCollector:
    """Accumulates step telemetry for one evaluation cycle."""

    def __init__(
        self,
        *,
        settings: Settings,
        user_id: Optional[str] = None,
        agent_model: Optional[str] = None,
        variant_strategy: Optional[str] = None,
        reembed_variant_neighbors: bool = False,
        seo_mode: Optional[str] = None,
        neighbor_limit: int = 10,
    ) -> None:
        self._settings = settings
        self._run_id = str(uuid4())
        self._started_at = _utc_now()
        self._cycle_started = time.perf_counter()
        self._user_id = user_id
        self._agent_model = agent_model
        self._variant_strategy = variant_strategy
        self._reembed_variant_neighbors = reembed_variant_neighbors
        self._seo_mode = seo_mode
        self._neighbor_limit = neighbor_limit
        self._steps: list[StepTelemetry] = []

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def steps(self) -> list[StepTelemetry]:
        return list(self._steps)

    def record_step(
        self,
        *,
        step_id: str,
        label: str,
        stage: StepStage,
        call_type: StepCallType,
        latency_ms: float,
        started_at: datetime,
        ended_at: datetime,
        status: StepStatus = "ok",
        model: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        error: Optional[str] = None,
    ) -> StepTelemetry:
        step = StepTelemetry(
            step_id=step_id,
            label=label,
            stage=stage,
            call_type=call_type,
            model=model,
            status=status,
            latency_ms=round(latency_ms, 2),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost_usd, 8),
            error=error,
            started_at=started_at,
            ended_at=ended_at,
        )
        self._steps.append(step)
        return step

    def record_llm_usage(
        self,
        *,
        step_id: str,
        label: str,
        stage: StepStage,
        model: Optional[str],
        usage: Any,
        latency_ms: float,
        started_at: datetime,
        ended_at: datetime,
        status: StepStatus = "ok",
        error: Optional[str] = None,
    ) -> StepTelemetry:
        input_tokens, output_tokens, cost_usd = cost_from_llm_usage(model, usage)
        return self.record_step(
            step_id=step_id,
            label=label,
            stage=stage,
            call_type="llm",
            latency_ms=latency_ms,
            started_at=started_at,
            ended_at=ended_at,
            status=status,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            error=error,
        )

    def record_embedding(
        self,
        *,
        step_id: str,
        label: str,
        stage: StepStage,
        prompt_tokens: int,
        latency_ms: float,
        started_at: datetime,
        ended_at: datetime,
        model: str = "gemini-embedding-001",
        status: StepStatus = "ok",
        error: Optional[str] = None,
    ) -> StepTelemetry:
        cost_usd = cost_from_embedding_tokens(model, prompt_tokens)
        return self.record_step(
            step_id=step_id,
            label=label,
            stage=stage,
            call_type="embedding",
            latency_ms=latency_ms,
            started_at=started_at,
            ended_at=ended_at,
            status=status,
            model=model,
            input_tokens=prompt_tokens,
            output_tokens=0,
            cost_usd=cost_usd,
            error=error,
        )

    def record_timed(
        self,
        *,
        step_id: str,
        label: str,
        stage: StepStage,
        call_type: StepCallType,
        fn: Callable[[], Any],
        model: Optional[str] = None,
    ) -> Any:
        """Run a synchronous callable and record wall-clock latency."""
        started_at = _utc_now()
        t0 = time.perf_counter()
        try:
            result = fn()
            latency_ms = _elapsed_ms(t0)
            self.record_step(
                step_id=step_id,
                label=label,
                stage=stage,
                call_type=call_type,
                latency_ms=latency_ms,
                started_at=started_at,
                ended_at=_utc_now(),
                model=model,
            )
            return result
        except Exception as exc:
            latency_ms = _elapsed_ms(t0)
            self.record_step(
                step_id=step_id,
                label=label,
                stage=stage,
                call_type=call_type,
                latency_ms=latency_ms,
                started_at=started_at,
                ended_at=_utc_now(),
                status="error",
                model=model,
                error=str(exc),
            )
            raise

    def finalize(self) -> RunMetadata:
        ended_at = _utc_now()
        total_latency_ms = _elapsed_ms(self._cycle_started)
        total_cost = sum(s.cost_usd for s in self._steps)
        total_input = sum(s.input_tokens for s in self._steps)
        total_output = sum(s.output_tokens for s in self._steps)

        metadata = RunMetadata(
            run_id=self._run_id,
            user_id=self._user_id,
            started_at=self._started_at,
            ended_at=ended_at,
            total_latency_ms=total_latency_ms,
            total_cost_usd=round(total_cost, 8),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            agent_model=self._agent_model,
            variant_strategy=self._variant_strategy,
            reembed_variant_neighbors=self._reembed_variant_neighbors,
            neighbor_limit=self._neighbor_limit,
            seo_mode=self._seo_mode,
            steps=self._steps,
        )
        metadata.warnings = evaluate_thresholds(metadata, self._settings)
        return metadata

    def format_snippet(self, *, stage: Optional[StepStage] = None, since_index: int = 0) -> str:
        """Short latency + cost string for live dashboard status labels."""
        relevant = self._steps[since_index:]
        if stage is not None:
            relevant = [s for s in relevant if s.stage == stage]
        if not relevant:
            return ""
        latency = max(s.latency_ms for s in relevant)
        cost = sum(s.cost_usd for s in relevant)
        return f" · {latency / 1000:.1f}s · ${cost:.4f}"
