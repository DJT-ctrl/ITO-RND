"""Unit tests for pydantic-ai Gemini model / provider normalization (issue #1)."""

import pytest

from config.settings import pydantic_ai_gemini_model, validate_agent_model


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "google:gemini-2.5-flash-lite"),
        ("gemini-2.5-flash-lite", "google:gemini-2.5-flash-lite"),
        ("google:gemini-2.5-flash", "google:gemini-2.5-flash"),
        ("google-gla:gemini-2.5-flash-lite", "google:gemini-2.5-flash-lite"),
        ("GOOGLE-GLA:gemini-2.0-flash", "google:gemini-2.0-flash"),
        ("  gemini-2.5-flash-lite  ", "google:gemini-2.5-flash-lite"),
    ],
)
def test_pydantic_ai_gemini_model_normalizes_to_google_prefix(raw, expected, monkeypatch):
    if raw is None:
        monkeypatch.setattr("config.settings.AGENT_GEMINI_MODEL", "gemini-2.5-flash-lite")
        assert pydantic_ai_gemini_model() == expected
    else:
        assert pydantic_ai_gemini_model(raw) == expected


def test_pydantic_ai_gemini_model_rejects_empty_id():
    with pytest.raises(ValueError, match="empty"):
        pydantic_ai_gemini_model("google:")


def test_pydantic_ai_gemini_model_never_returns_google_gla():
    """Regression: fallback to google-gla caused Unknown provider on pydantic-ai 2.x."""
    assert not pydantic_ai_gemini_model("google-gla:gemini-2.5-flash").startswith("google-gla:")


def test_validate_agent_model_wraps_infer_failure(monkeypatch):
    def _boom(_model_id: str):
        raise RuntimeError("Unknown provider: google-gla")

    monkeypatch.setattr(
        "pydantic_ai.models.infer_model",
        _boom,
        raising=False,
    )
    # Patch via the module path validate_agent_model imports from.
    import pydantic_ai.models as pai_models

    monkeypatch.setattr(pai_models, "infer_model", _boom)

    with pytest.raises(ValueError, match="Invalid pydantic-ai agent model"):
        validate_agent_model("gemini-2.5-flash-lite")


def test_api_import_does_not_build_agents():
    """Importing api.main must leave agent globals unset (lazy init)."""
    import importlib

    import api.main as api_main

    importlib.reload(api_main)

    assert api_main.predictor_agent is None
    assert api_main.diagnostic_agents is None
    assert api_main._eval_model is None
    # Health must still work without agents.
    from fastapi.testclient import TestClient

    client = TestClient(api_main.app)
    assert client.get("/health").json() == {"status": "ok"}
