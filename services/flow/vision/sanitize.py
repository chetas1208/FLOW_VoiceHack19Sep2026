"""Screen text is untrusted evidence. Everything that came from pixels passes through here.

The perception model only ever *describes*; downstream code (recommendations, voice, delegated
task proposals) must never treat visible text as an instruction. ``sanitize_screen_text`` bounds the
text, strips control characters, redacts secrets and replaces anything that reads like an
instruction to an assistant with a fixed placeholder.
"""

from __future__ import annotations

import re

from ..privacy.redaction import redact_text

SUSPICIOUS_PLACEHOLDER = "[screen text containing instructions omitted]"

_INJECTION = re.compile(
    r"""(
        \b(ignore|disregard|forget|override)\b[^.\n]{0,50}\b(previous|prior|above|earlier|all|any|your|these)\b[^.\n]{0,30}\b(instruction|prompt|rule|direction|context)s?\b
      | \b(system|developer)\s+(prompt|message|instruction)s?\b
      | \b(you\s+(must|should|shall|will|are\s+now|have\s+to)|please)\b[^.\n]{0,40}\b(run|execute|delete|remove|send|upload|download|install|type|click|reveal|exfiltrate|ignore|approve|disable)\b
      | \b(run|execute|paste|type)\b[^.\n]{0,25}(`|\$\(|\brm\s|\bsudo\b|\bcurl\b|\bwget\b|\bbash\b|\bsh\s|\bpowershell\b)
      | \brm\s+-[a-z]*[rf][a-z]*\b
      | \bsudo\s+\S+
      | \b(curl|wget)\b[^|\n]*\|\s*(ba|z)?sh\b
      | <\s*\|?\s*(im_start|im_end|system|assistant)\b
      | \bassistant\s*:\s
      | \bact\s+as\s+(an?\s+)?(assistant|admin|root|system)\b
      | \bnew\s+instructions?\b
    )""",
    re.I | re.X,
)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


def looks_like_instruction(text: str | None) -> bool:
    return bool(text and _INJECTION.search(text))


def sanitize_screen_text(text: str | None, limit: int = 160) -> tuple[str, bool]:
    """Return ``(clean_text, suspicious)``. ``clean_text`` is safe to store, speak or quote."""
    if not text:
        return "", False
    value = _CONTROL.sub(" ", str(text))
    value = re.sub(r"\s+", " ", value).strip()
    suspicious = looks_like_instruction(value)
    if suspicious:
        return SUSPICIOUS_PLACEHOLDER, True
    value = redact_text(value) or ""
    if len(value) > limit:
        value = value[: max(0, limit - 1)].rstrip() + "…"
    return value, False


def normalize_signature(text: str | None) -> frozenset[str]:
    """Order-free token signature of a description/error, stable across line numbers, paths and ids."""
    if not text:
        return frozenset()
    value = text.casefold()
    value = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{8,}\b|\b\d+(\.\d+)*\b", " ", value)
    value = re.sub(r"[/\\][\w./\\-]+", " ", value)
    return frozenset(token for token in re.findall(r"[a-z][a-z_]{2,}", value) if token not in _STOP)


_STOP = frozenset("the and for with that this from are was were has have had not but into than then its line file".split())


def signature_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
