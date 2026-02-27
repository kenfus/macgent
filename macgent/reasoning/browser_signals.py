"""Signal detection helpers for browser reliability and anti-bot/captcha handling."""

from __future__ import annotations

import re

# Keep patterns explicit so tests can validate behavior easily.
CAPTCHA_PATTERNS = [
    r"\bcaptcha\b",
    r"i\s*am\s*not\s*a\s*robot",
    r"not\s*a\s*robot",
    r"verify\s+you\s+are\s+human",
    r"verify\s+that\s+you\s+are\s+human",
    r"checkbox\s+challenge",
    r"puzzle\s+challenge",
    r"select\s+all\s+images",
    r"security\s+check",
]

ANTI_BOT_PATTERNS = [
    r"access\s+denied",
    r"unusual\s+traffic",
    r"cloudflare",
    r"datadome",
    r"challenge\s+page",
    r"temporarily\s+blocked",
    r"blocked\s+request",
    r"please\s+enable\s+javascript",
]


def _collect_matches(text: str, patterns: list[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            matches.append(pattern)
    return matches


def detect_browser_blockers(page_text: str = "", screen_description: str = "") -> dict[str, object]:
    """Return normalized blocker signals from page text and vision description."""
    combined = "\n".join(part for part in (page_text, screen_description) if part)
    captcha = _collect_matches(combined, CAPTCHA_PATTERNS)
    anti_bot = _collect_matches(combined, ANTI_BOT_PATTERNS)
    return {
        "is_captcha": bool(captcha),
        "is_antibot": bool(anti_bot),
        "captcha_signals": captcha,
        "antibot_signals": anti_bot,
    }
