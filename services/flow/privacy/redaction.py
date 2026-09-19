"""Conservative local text redaction for semantic metadata."""

from __future__ import annotations

import re

PATTERNS = (
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL_REDACTED]"),
    (re.compile(r"\b(?:sk|pk|api|token|secret)[_-]?[A-Za-z0-9_-]{16,}\b", re.I), "[TOKEN_REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----", re.S), "[PRIVATE_KEY_REDACTED]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[CARD_REDACTED]"),
)


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    for pattern, replacement in PATTERNS:
        value = pattern.sub(replacement, value)
    return value
