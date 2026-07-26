"""Unit tests for T7.5 deterministic clarity / cognitive-load metrics."""

from agents.clarity_metrics import (
    compute_clarity_metrics,
    count_syllables,
    format_clarity_context_section,
    jargon_density_percent,
)
from agents.diagnostics import build_clarity_prompt, build_diagnostic_prompt
from agents.schemas import EvaluationDeps


def test_count_syllables_basic():
    assert count_syllables("cat") == 1
    assert count_syllables("hiring") >= 2
    assert count_syllables("operationalize") >= 4


def test_jargon_density_flags_lexicon_and_long_words():
    words = ["we", "will", "leverage", "synergy", "to", "ship", "faster"]
    pct = jargon_density_percent(words)
    assert pct > 0


def test_compute_clarity_metrics_scannable_short_post():
    draft = "We hired two engineers.\n\nResults shipped in two weeks."
    metrics = compute_clarity_metrics(draft)

    assert metrics["word_count"] > 0
    assert metrics["wall_of_text"] is False
    assert metrics["deterministic_score"] >= 6.0
    checks = {s["check"]: s["status"] for s in metrics["signals"]}
    assert "flesch_kincaid_grade" in checks
    assert "jargon_density_percent" in checks
    assert "wall_of_text" in checks
    assert "mobile_scan" in checks


def test_compute_clarity_metrics_flags_wall_of_text():
    draft = " ".join(["This is a dense LinkedIn paragraph with no breaks."] * 20)
    metrics = compute_clarity_metrics(draft)

    assert metrics["wall_of_text"] is True
    assert metrics["max_paragraph_words"] >= 80
    wall = next(s for s in metrics["signals"] if s["check"] == "wall_of_text")
    assert wall["status"] == "fail"


def test_compute_clarity_metrics_sheet_fields_present():
    draft = (
        "Today we operationalize scalable synergies across the ecosystem. "
        "Stakeholders should leverage our transformative paradigm."
    )
    metrics = compute_clarity_metrics(draft)

    assert "flesch_kincaid_grade" in metrics
    assert "jargon_density_percent" in metrics
    assert metrics["jargon_density_percent"] > 8


def test_format_clarity_context_section_includes_metrics():
    metrics = compute_clarity_metrics(
        "Short clear post.\n\nSecond paragraph with a point."
    )
    section = format_clarity_context_section(metrics)

    assert "Flesch–Kincaid grade" in section
    assert "Jargon density" in section
    assert "deterministic clarity score" in section
    assert "mobile" in section.lower()


def test_format_clarity_context_section_empty_on_none():
    assert format_clarity_context_section(None) == ""
    assert format_clarity_context_section({}) == ""


def test_build_clarity_prompt_includes_metrics_when_present():
    draft = "Hiring backend engineers today.\n\nApply below."
    metrics = compute_clarity_metrics(draft)
    deps = EvaluationDeps(draft_content=draft, clarity_context=metrics)

    prompt = build_clarity_prompt(deps)

    assert "deterministic clarity" in prompt.lower()
    assert "Hiring backend engineers today." in prompt
    assert prompt != build_diagnostic_prompt("clarity", deps)


def test_build_clarity_prompt_falls_back_without_context():
    deps = EvaluationDeps(draft_content="Hiring backend engineers today.")
    assert build_clarity_prompt(deps) == build_diagnostic_prompt("clarity", deps)
