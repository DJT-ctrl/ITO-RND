"""Unit tests for T7.9 + T7.10 visual diagnostics (opt-in multimodal)."""

import asyncio
from unittest.mock import MagicMock, patch

from pydantic_ai.models.test import TestModel

from agents.schemas import EvaluationDeps
from agents.visual_diagnostics import (
    VisualDiagnosticOutput,
    build_visual_agent,
    build_visual_system_prompt,
    build_visual_user_prompt,
    fetch_image_from_url,
    prepare_visual_image,
    resolve_use_visual_diagnostics,
)
from config.settings import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="test",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="",
        visual_diagnostics_enabled=False,
    )
    base.update(overrides)
    return Settings(**base)


def test_resolve_use_visual_diagnostics_off_by_default():
    settings = _settings(visual_diagnostics_enabled=False)
    assert resolve_use_visual_diagnostics(settings) is False


def test_resolve_use_visual_diagnostics_honors_settings_and_override():
    settings = _settings(visual_diagnostics_enabled=True)
    assert resolve_use_visual_diagnostics(settings) is True
    assert resolve_use_visual_diagnostics(settings, use_visual_diagnostics=False) is False
    settings_off = _settings(visual_diagnostics_enabled=False)
    assert resolve_use_visual_diagnostics(settings_off, use_visual_diagnostics=True) is True


def test_prepare_visual_image_rejects_oversized_upload():
    huge = b"x" * (5 * 1024 * 1024 + 1)
    data, media, url, warnings = prepare_visual_image(
        image_bytes=huge, image_media_type="image/png"
    )
    assert data is None
    assert media is None
    assert any("exceeds" in w for w in warnings)


def test_prepare_visual_image_accepts_png_upload():
    data, media, url, warnings = prepare_visual_image(
        image_bytes=b"\x89PNG\r\n\x1a\nfake",
        image_media_type="image/png",
    )
    assert data is not None
    assert media == "image/png"
    assert warnings == []


def test_prepare_visual_image_rejects_bad_url_scheme():
    data, media, url, warnings = prepare_visual_image(image_url="ftp://example.com/a.png")
    assert data is None
    assert any("http" in w for w in warnings)


@patch("agents.visual_diagnostics.urlopen")
def test_fetch_image_from_url_success(mock_urlopen):
    body = b"jpeg-bytes"
    resp = MagicMock()
    resp.headers = {"Content-Type": "image/jpeg"}
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    mock_urlopen.return_value = resp

    data, media, warnings = fetch_image_from_url("https://cdn.example.com/shot.jpg")
    assert data == body
    assert media == "image/jpeg"
    assert warnings == []


@patch("agents.visual_diagnostics.urlopen")
def test_fetch_image_from_url_degrades_on_error(mock_urlopen):
    mock_urlopen.side_effect = TimeoutError("slow")
    data, media, warnings = fetch_image_from_url("https://cdn.example.com/shot.jpg")
    assert data is None
    assert media is None
    assert any("failed to fetch" in w for w in warnings)


def test_build_visual_prompts_include_draft_and_image_part():
    deps = EvaluationDeps(
        draft_content="Launch day — see the carousel.",
        image_bytes=b"fakepng",
        image_media_type="image/png",
    )
    system = build_visual_system_prompt(deps)
    user = build_visual_user_prompt(deps)

    assert "Visual Diagnostics" in system or "hierarchy" in system.lower()
    assert "Launch day" in system
    assert isinstance(user, list)
    assert any(hasattr(p, "data") for p in user)


def test_visual_agent_returns_structured_output_with_test_model():
    deps = EvaluationDeps(
        draft_content="Launch day — see the carousel.",
        image_bytes=b"fakepng",
        image_media_type="image/png",
    )
    agent = build_visual_agent(TestModel())
    result = asyncio.run(agent.run(build_visual_user_prompt(deps), deps=deps))
    assert isinstance(result.output, VisualDiagnosticOutput)
    assert 0 <= result.output.score <= 10
    assert 0 <= result.output.copy_alignment_score <= 10
