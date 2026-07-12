"""Async instrumentation helpers for evaluation agents and timed steps."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, TypeVar

from telemetry.collector import RunMetadataCollector
from telemetry.schemas import StepCallType, StepStage

T = TypeVar("T")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _extract_usage(result: Any) -> Any:
    usage_fn = getattr(result, "usage", None)
    if callable(usage_fn):
        return usage_fn()
    return None


async def run_agent_step(
    collector: Optional[RunMetadataCollector],
    *,
    step_id: str,
    label: str,
    stage: StepStage,
    agent: Any,
    prompt: str,
    deps: Any,
    model: Optional[str] = None,
) -> Any:
    """Run a PydanticAI agent (or duck-typed stub) and record telemetry."""
    started_at = _utc_now()
    t0 = time.perf_counter()
    try:
        result = await agent.run(prompt, deps=deps)
        latency_ms = _elapsed_ms(t0)
        if collector is not None:
            usage = _extract_usage(result)
            if usage is not None:
                collector.record_llm_usage(
                    step_id=step_id,
                    label=label,
                    stage=stage,
                    model=model,
                    usage=usage,
                    latency_ms=latency_ms,
                    started_at=started_at,
                    ended_at=_utc_now(),
                )
            else:
                collector.record_step(
                    step_id=step_id,
                    label=label,
                    stage=stage,
                    call_type="llm",
                    latency_ms=latency_ms,
                    started_at=started_at,
                    ended_at=_utc_now(),
                    model=model,
                )
        return result
    except Exception as exc:
        latency_ms = _elapsed_ms(t0)
        if collector is not None:
            collector.record_step(
                step_id=step_id,
                label=label,
                stage=stage,
                call_type="llm",
                latency_ms=latency_ms,
                started_at=started_at,
                ended_at=_utc_now(),
                status="error",
                model=model,
                error=str(exc),
            )
        raise


async def run_timed_step(
    collector: Optional[RunMetadataCollector],
    *,
    step_id: str,
    label: str,
    stage: StepStage,
    call_type: StepCallType,
    coro: Awaitable[T],
    model: Optional[str] = None,
) -> T:
    """Await a coroutine and record wall-clock latency."""
    started_at = _utc_now()
    t0 = time.perf_counter()
    try:
        result = await coro
        latency_ms = _elapsed_ms(t0)
        if collector is not None:
            collector.record_step(
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
        if collector is not None:
            collector.record_step(
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


def run_timed_sync(
    collector: Optional[RunMetadataCollector],
    *,
    step_id: str,
    label: str,
    stage: StepStage,
    call_type: StepCallType,
    fn: Callable[[], T],
    model: Optional[str] = None,
) -> T:
    """Run a blocking callable (often via asyncio.to_thread) with telemetry."""
    if collector is None:
        return fn()
    return collector.record_timed(
        step_id=step_id,
        label=label,
        stage=stage,
        call_type=call_type,
        fn=fn,
        model=model,
    )


async def run_timed_thread(
    collector: Optional[RunMetadataCollector],
    *,
    step_id: str,
    label: str,
    stage: StepStage,
    call_type: StepCallType,
    fn: Callable[[], T],
    model: Optional[str] = None,
) -> T:
    return await asyncio.to_thread(
        run_timed_sync,
        collector,
        step_id=step_id,
        label=label,
        stage=stage,
        call_type=call_type,
        fn=fn,
        model=model,
    )
