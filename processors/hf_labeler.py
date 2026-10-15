"""Hugging Face quality labels for one post.

This is the categorising section from the local Ito data pipeline: spam,
hook strength, clarity, tone quality, claim credibility, financial
compliance, originality, and length/format.

It does not call Gemini and does not read Gemini fields. Zero-shot scores
use ``valhalla/distilbart-mnli-12-3`` only when a classifier is passed in.
Spam heuristics and length/format always run from the text alone.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from processors.schemas import (
    HuggingFaceDimension,
    HuggingFaceLabelSection,
    HuggingFaceLengthFormat,
    HuggingFaceSpam,
)

HF_MODEL_ID = "valhalla/distilbart-mnli-12-3"
_SCORE_THRESHOLD = 0.50
_MIN_MODEL_CHARS = 5

ZeroShotClassifier = Callable[[str, list[str]], dict[str, Any]]

_POSITIVE = {
    "hook_strength": "strong, compelling, curiosity-inducing hook",
    "clarity": "clear, well-structured, easy to understand",
    "tone_of_voice": "constructive, professional, authentic, engaging tone",
    "claim_credibility": "realistic, grounded, credible, genuine claim with authentic experience or evidence",
    "financial_compliance": "compliant financial information, educational market insights, or safe corporate financial disclosure",
    "originality": "original thought leadership, fresh industry perspective, or unique authentic case study",
}
_NEGATIVE = {
    "hook_strength": "weak, bland, or generic opening",
    "clarity": "confusing, rambling, convoluted, hard to follow",
    "tone_of_voice": "arrogant, abrasive, preachy, or robotic tone",
    "claim_credibility": "overstated, exaggerated, hyperbolic claim with inflated promises, hype, or guarantees",
    "financial_compliance": "risky financial promotion, unregistered investment solicitation, promises of high returns, or speculative hype",
    "originality": "cliche linkedin tropes, recycled generic platitudes, or engagement bait opening",
}
_HIGH_CATEGORY = {
    "hook_strength": "Strong Hook",
    "clarity": "Clear Post",
    "tone_of_voice": "Good Tone",
    "claim_credibility": "Genuine Claim",
    "financial_compliance": "Compliant Promotion",
    "originality": "Original Post",
}
_LOW_CATEGORY = {
    "hook_strength": "Weak Hook",
    "clarity": "Confusing Post",
    "tone_of_voice": "Bad Tone",
    "claim_credibility": "Overstated Claim",
    "financial_compliance": "Risky Financial Promotion",
    "originality": "Cliché / Trope",
}

_RE_WEAK_HOOK_PREFIX = re.compile(
    r"^(?:i'm (?:excited|thrilled|pleased|honored|happy) to (?:announce|share)|excited to share|today i want to talk about|hope (?:everyone|you all) (?:is|are) doing well|just wanted to share)",
    re.IGNORECASE,
)
_RE_CURIOSITY = re.compile(r"\b\d+(?:\.\d+)?%?|\$\d+\b")
_RE_WHATSAPP = re.compile(
    r"(?:wa\.me/|api\.whatsapp\.com|\b(?:chat|message|contact|reach)\b.*(?:via|on)\s+whatsapp|\bwhatsapp\s*:\s*\+?\d{8,15})",
    re.IGNORECASE | re.DOTALL,
)
_RE_TELEGRAM = re.compile(
    r"(?:t\.me/|telegram\.me/|\b(?:join|message|contact)\b.*(?:my|our)?\s*telegram)",
    re.IGNORECASE | re.DOTALL,
)
_RE_FINANCIAL_SCAM = re.compile(
    r"(?:guaranteed\s+(?:profit|return|income)s?|earn\s+\$?\d+[\d,]*\s+(?:daily|weekly|per\s+day)|forex\s+signals?|binary\s+options?|crypto\s+recovery|100%\s+passive\s+income|dm\s+to\s+invest|bitcoin\s+mining\s+profit)",
    re.IGNORECASE,
)
_RE_AIRDROP_WALLET = re.compile(
    r"(?:claim\s+(?:free\s+)?airdrop|connect\s+(?:your\s+)?wallet|seed\s+phrase|private\s+key\s+giveaway)",
    re.IGNORECASE,
)
_RE_ENGAGEMENT_BAIT = re.compile(
    r"(?:comment\s+['\"“]?(?:yes|interested|send|ready)['\"”]?(?:\s+below)?\s+to|drop\s+your\s+email\s+below|type\s+['\"“]?(?:yes|send|info)['\"”]?\s+in\s+the\s+comments)",
    re.IGNORECASE,
)
_RE_HASHTAG = re.compile(r"#\w+")
_RE_BULLETS = re.compile(r"(?:^\s*[-•*▪►✓✔→]\s+)", re.MULTILINE)
_RE_NUMBERED_STEPS = re.compile(r"(?:^\s*(?:step\s*\d+|\d+[\.\)])\s+)", re.MULTILINE | re.IGNORECASE)
_RE_URL = re.compile(r"https?://\S+")
_RE_EMOJI = re.compile(r"[\U00010000-\U0010ffff]", re.UNICODE)
_RE_EXCESSIVE_PUNCT = re.compile(r"(?:!{3,}|\?{3,})")
_RE_CAPS_WORDS = re.compile(r"\b[A-Z]{3,}\b")
_CAPS_ALLOW = {
    "CEO", "CFO", "CTO", "USA", "API", "KYC", "ROI", "B2B", "SaaS", "EOR",
    "SEBI", "RBI", "CFIT", "OBE", "AMD", "TFN", "DSCR",
}
_RE_GUARANTEE_HYPE = re.compile(
    r"\b(?:guaranteed (?:results?|returns?|profit|success|growth|revenue)|100% (?:guaranteed|proven|risk[- ]free|safe|success)|foolproof (?:system|blueprint|strategy)|can't lose|fail[- ]proof|surefire (?:way|method)|guarantee you will)\b",
    re.IGNORECASE,
)
_RE_UNREALISTIC_TIMEFRAME = re.compile(
    r"\b(?:(?:in|within) (?:24 hours|3 days|7 days|one week|overnight|30 days) (?:i (?:made|generated|earned|scaled)|to (?:make|generate|earn|scale) \$\d+)|(?:from|scale to) \$(?:10k|50k|100k|1m) in \d+ (?:days|weeks|months) with (?:no|zero) (?:experience|effort|money))\b",
    re.IGNORECASE,
)
_RE_SECRET_BLUEPRINT = re.compile(
    r"\b(?:secret (?:formula|blueprint|hack|loophole|sauce|trick)|nobody is talking about this|what 99% of people (?:don't know|get wrong)|the algorithm doesn't want you to see|break the algorithm|steal this (?:framework|system|prompt))\b",
    re.IGNORECASE,
)
_RE_SENSATIONALIST = re.compile(
    r"\b(?:will change your life forever|revolutionary miracle|mind[- ]blowing results?|infinite money glitch|pure goldmine|insane results?)\b",
    re.IGNORECASE,
)
_RE_VULNERABILITY = re.compile(
    r"\b(?:mistakes? we made|what failed|lessons? learned|it depends|trade[- ]offs?|honest truth|wasn't easy|took us \d+ years?|not a magic bullet|failed at|rough patch|the reality is|transparently|truth be told)\b",
    re.IGNORECASE,
)
_RE_METHODOLOGY = re.compile(
    r"\b(?:sample size|cohort of|data shows?|methodology|a/b test(?:ed|ing)?|surveyed \d+|measured over \d+ months?|case study:?|key takeaways?|our benchmark|control group)\b",
    re.IGNORECASE,
)
_RE_PROMISED_RETURNS = re.compile(
    r"\b(?:guaranteed (?:returns?|profit|yield|roi)|(?:double|triple) your money|100% (?:safe|risk[- ]free) (?:returns?|investment)|earn \$\d+ (?:daily|weekly|hourly)|passive income guaranteed|zero risk investment)\b",
    re.IGNORECASE,
)
_RE_UNREGISTERED = re.compile(
    r"\b(?:dm me to invest|message me for signals|join my (?:vip|telegram|crypto|forex) (?:group|channel)|free crypto signals?|presale (?:whitelist|allocation)|send \$\d+ to get|guaranteed airdrop)\b",
    re.IGNORECASE,
)
_RE_PUMP = re.compile(
    r"\b(?:100x (?:gem|potential|coin)|to the moon|next (?:bitcoin|ethereum|solana)|buy before it explodes|insane pump|fomo is real)\b",
    re.IGNORECASE,
)
_RE_DISCLAIMERS = re.compile(
    r"\b(?:not financial advice|nfa|for educational purposes only|past performance is no guarantee|do your own research|dyor|capital at risk|terms and conditions apply|regulated by (?:sec|finra|fca|sebi|rbi)|member sipc)\b",
    re.IGNORECASE,
)
_RE_CLICHES = re.compile(
    r"\b(?:agree\?|thoughts\?|let that sink in|unpopular opinion(?:\s*but)?|read that again|hard pill to swallow|most people will scroll past|here's what nobody tells you|comment (?:below|interested|yes)|drop a comment|what did i miss\?|save this for later|follow me for more)\b",
    re.IGNORECASE,
)
_RE_PLATITUDES = re.compile(
    r"\b(?:leadership is not about|success is not final|hustle in silence|winners never quit|comfort zone is where dreams go to die|hire character train skill|people don't leave companies they leave managers)\b",
    re.IGNORECASE,
)


def load_zero_shot_classifier() -> ZeroShotClassifier:
    """Load the local zero-shot model. Call this only when Hugging Face scoring is requested."""
    import torch
    from transformers import pipeline

    if torch.backends.mps.is_available():
        device: str | int = "mps"
    elif torch.cuda.is_available():
        device = 0
    else:
        device = -1
    classifier = pipeline(
        "zero-shot-classification",
        model=HF_MODEL_ID,
        device=device,
    )

    def classify(text: str, candidate_labels: list[str]) -> dict[str, Any]:
        return classifier(text, candidate_labels)

    return classify


def label_text(
    text: str,
    classifier: Optional[ZeroShotClassifier] = None,
) -> dict[str, Any]:
    """Score one post. ``classifier`` fills the model dimensions; heuristics always run."""
    content = text or ""
    model_ran = classifier is not None
    section = HuggingFaceLabelSection(
        model=HF_MODEL_ID,
        model_ran=model_ran,
        spam=_spam(content),
        hook_strength=_hook(content, classifier),
        clarity=_clarity(content, classifier),
        tone_of_voice=_tone(content, classifier),
        claim_credibility=_claims(content, classifier),
        financial_compliance=_compliance(content, classifier),
        originality=_originality(content, classifier),
        length_and_format=_length_format(content),
    )
    return section.model_dump()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def _category(dimension: str, score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score >= _SCORE_THRESHOLD:
        return _HIGH_CATEGORY[dimension]
    return _LOW_CATEGORY[dimension]


def _model_probability(
    text: str,
    dimension: str,
    classifier: Optional[ZeroShotClassifier],
    *,
    excerpt: Optional[str] = None,
) -> Optional[float]:
    if classifier is None:
        return None
    sample = (excerpt if excerpt is not None else text)[:500]
    if len(sample.strip()) < _MIN_MODEL_CHARS:
        return 0.0
    result = classifier(sample, [_POSITIVE[dimension], _NEGATIVE[dimension]])
    labels = list(result["labels"])
    scores = list(result["scores"])
    return float(scores[labels.index(_POSITIVE[dimension])])


def _dimension(dimension: str, score: Optional[float], detail: dict[str, Any]) -> HuggingFaceDimension:
    return HuggingFaceDimension(
        score=None if score is None else _clamp(score),
        category=_category(dimension, None if score is None else _clamp(score)),
        detail=detail,
    )


def extract_hook(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    hook = lines[0]
    if len(hook) < 60 and len(lines) > 1:
        hook += " " + lines[1]
    return hook[:200]


def _hook(text: str, classifier: Optional[ZeroShotClassifier]) -> HuggingFaceDimension:
    hook = extract_hook(text)
    score = _model_probability(text, "hook_strength", classifier, excerpt=hook)
    if score is not None:
        if _RE_WEAK_HOOK_PREFIX.match(hook):
            score -= 0.35
        if "?" in hook or _RE_CURIOSITY.search(hook):
            score += 0.15
    return _dimension("hook_strength", score, {"extracted_hook": hook})


def _clarity(text: str, classifier: Optional[ZeroShotClassifier]) -> HuggingFaceDimension:
    words = text.split()
    total_words = len(words)
    sentences = [part.strip() for part in re.split(r"[.!?\n]+", text) if len(part.strip().split()) >= 2]
    avg_sentence_len = total_words / max(len(sentences), 1)
    has_linebreaks = "\n" in text
    score = _model_probability(text, "clarity", classifier)
    if score is not None:
        if avg_sentence_len > 35:
            score -= 0.15
        if total_words > 120 and not has_linebreaks:
            score -= 0.20
        if 8 <= avg_sentence_len <= 22 and has_linebreaks:
            score += 0.10
    return _dimension(
        "clarity",
        score,
        {"word_count": total_words, "avg_sentence_length": round(avg_sentence_len, 1)},
    )


def _tone(text: str, classifier: Optional[ZeroShotClassifier]) -> HuggingFaceDimension:
    punct_matches = len(_RE_EXCESSIVE_PUNCT.findall(text))
    caps_matches = len([word for word in _RE_CAPS_WORDS.findall(text) if word not in _CAPS_ALLOW])
    score = _model_probability(text, "tone_of_voice", classifier)
    if score is not None:
        if punct_matches >= 1:
            score -= 0.08
        if caps_matches >= 3:
            score -= 0.12
    return _dimension(
        "tone_of_voice",
        score,
        {"aggressive_punct_count": punct_matches, "caps_words_count": caps_matches},
    )


def _claims(text: str, classifier: Optional[ZeroShotClassifier]) -> HuggingFaceDimension:
    hype_count = (
        len(_RE_GUARANTEE_HYPE.findall(text))
        + len(_RE_UNREALISTIC_TIMEFRAME.findall(text))
        + len(_RE_SECRET_BLUEPRINT.findall(text))
        + len(_RE_SENSATIONALIST.findall(text))
    )
    credibility_count = len(_RE_VULNERABILITY.findall(text)) + len(_RE_METHODOLOGY.findall(text))
    score = _model_probability(text, "claim_credibility", classifier)
    if score is not None:
        if hype_count >= 1:
            score -= 0.15 * min(hype_count, 3)
        if credibility_count >= 1:
            score += 0.10 * min(credibility_count, 2)
    return _dimension(
        "claim_credibility",
        score,
        {"hype_flags_count": hype_count, "credibility_signals_count": credibility_count},
    )


def _compliance(text: str, classifier: Optional[ZeroShotClassifier]) -> HuggingFaceDimension:
    risk_count = (
        len(_RE_PROMISED_RETURNS.findall(text))
        + len(_RE_UNREGISTERED.findall(text))
        + len(_RE_PUMP.findall(text))
    )
    disclaimer_count = len(_RE_DISCLAIMERS.findall(text))
    score = _model_probability(text, "financial_compliance", classifier)
    if score is not None:
        if risk_count >= 1:
            score -= 0.20 * min(risk_count, 3)
        if disclaimer_count >= 1:
            score += 0.10 * min(disclaimer_count, 2)
    return _dimension(
        "financial_compliance",
        score,
        {"risk_flags_count": risk_count, "disclaimers_count": disclaimer_count},
    )


def _originality(text: str, classifier: Optional[ZeroShotClassifier]) -> HuggingFaceDimension:
    cliche_count = len(_RE_CLICHES.findall(text)) + len(_RE_PLATITUDES.findall(text))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    short_lines = [line for line in lines if len(line.split()) < 15]
    is_broetry = len(lines) >= 6 and (len(short_lines) / max(len(lines), 1)) >= 0.75
    score = _model_probability(text, "originality", classifier)
    if score is not None:
        if cliche_count >= 1:
            score -= 0.15 * min(cliche_count, 3)
        if is_broetry:
            score -= 0.12
    return _dimension(
        "originality",
        score,
        {"cliche_count": cliche_count, "is_broetry": is_broetry},
    )


def _spam(text: str) -> HuggingFaceSpam:
    score = 0.0
    reasons: list[str] = []
    if not text:
        return HuggingFaceSpam(score=0.0, category="Clean", reasons=reasons)

    if _RE_WHATSAPP.search(text):
        score += 0.65
        reasons.append("WHATSAPP_REDIRECT_LINK")
    if _RE_TELEGRAM.search(text):
        score += 0.55
        reasons.append("TELEGRAM_CHANNEL_REDIRECT")
    if _RE_FINANCIAL_SCAM.search(text):
        score += 0.70
        reasons.append("FINANCIAL_FRAUD_PROMISE")
    if _RE_AIRDROP_WALLET.search(text):
        score += 0.80
        reasons.append("CRYPTO_AIRDROP_WALLET_SCAM")
    if _RE_ENGAGEMENT_BAIT.search(text):
        score += 0.30
        reasons.append("COMMENT_ENGAGEMENT_BAIT")

    non_ascii_count = sum(1 for char in text if ord(char) > 127)
    emoji_ratio = non_ascii_count / max(len(text), 1)
    if non_ascii_count >= 15 or emoji_ratio > 0.22:
        score += 0.25
        reasons.append(f"EXCESSIVE_EMOJI_SYMBOLS ({non_ascii_count} symbols, {emoji_ratio * 100:.1f}%)")

    if len(text) > 40:
        caps_ratio = sum(1 for char in text if char.isupper()) / len(text)
        if caps_ratio > 0.65:
            score += 0.35
            reasons.append(f"EXCESSIVE_ALL_CAPS ({caps_ratio * 100:.1f}%)")

    hashtags = _RE_HASHTAG.findall(text)
    if len(hashtags) >= 20:
        score += 0.25
        reasons.append(f"HASHTAG_STUFFING ({len(hashtags)} tags)")

    final_score = _clamp(score)
    return HuggingFaceSpam(
        score=final_score,
        category="Spam" if final_score >= _SCORE_THRESHOLD else "Clean",
        reasons=reasons,
    )


def _length_format(text: str) -> HuggingFaceLengthFormat:
    words = text.split()
    word_count = len(words)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if word_count < 50:
        length_tier = "Micro (<50 words)"
    elif word_count <= 150:
        length_tier = "Short (50-150 words)"
    elif word_count <= 300:
        length_tier = "Medium (151-300 words)"
    else:
        length_tier = "Long Form (>300 words)"

    bullet_matches = len(_RE_BULLETS.findall(text))
    numbered_matches = len(_RE_NUMBERED_STEPS.findall(text))
    if bullet_matches >= 3:
        primary_format = "Bulleted List / Checklist"
    elif numbered_matches >= 3:
        primary_format = "Framework / Step Guide"
    elif text.strip().endswith("?") or (lines and lines[-1].endswith("?")):
        primary_format = "Q&A / Discussion Prompt"
    elif word_count > 150 and len(lines) >= 5:
        primary_format = "Story / Narrative Essay"
    elif word_count < 60:
        primary_format = "Short Announcement / Update"
    else:
        primary_format = "Standard Article / Insight"

    return HuggingFaceLengthFormat(
        length_tier=length_tier,
        primary_format=primary_format,
        line_count=len(lines),
        has_bullets=bullet_matches >= 2,
        has_numbered_steps=numbered_matches >= 2,
        has_emojis=bool(_RE_EMOJI.search(text)),
        has_links=bool(_RE_URL.search(text)),
    )
