"""Route PydanticAI agent spans to self-hosted Langfuse.

PydanticAI emits OpenTelemetry spans (model, token usage, latency, prompt and
response payloads) that Langfuse ingests over OTLP. Instrumentation is opt-in:
it activates only when a Langfuse public + secret key pair is configured, and
is a silent no-op otherwise so agents run unchanged without it.
"""

from __future__ import annotations

import logging

from config.settings import Settings

logger = logging.getLogger(__name__)

_configured = False


def configure_observability(settings: Settings) -> bool:
    """Route PydanticAI agent spans to self-hosted Langfuse.

    Returns True if instrumentation was activated, False if it was skipped
    (keys not set) or unavailable (package missing / client init failed).
    Safe to call more than once — only the first successful call takes effect.
    """
    global _configured
    if _configured:
        return True

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return False

    try:
        from langfuse import Langfuse
        from pydantic_ai import Agent
    except ImportError:
        logger.warning(
            "LANGFUSE_* keys are set but the 'langfuse' package is not "
            "installed; agent tracing is disabled."
        )
        return False

    try:
        # Sets up the OpenTelemetry batch exporter. It does not require the
        # Langfuse server to be reachable now — spans buffer and flush once it
        # is up, so the API never blocks on (or crashes over) trace-engine
        # startup ordering.
        Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception as exc:
        logger.warning(
            "Could not initialise Langfuse client for %s (%s); agent tracing "
            "is disabled.",
            settings.langfuse_host,
            exc,
        )
        return False

    Agent.instrument_all()
    _configured = True
    logger.info("Langfuse trace engine active (%s).", settings.langfuse_host)
    return True
