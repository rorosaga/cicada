"""One scrub for every episode writer (R-N3 · R3 P3 · extends G114).

Until this module the secret scrub ran in exactly one place —
``transcript_extract._Builder._add`` (G105 R6) — so a key pasted into a chat
export, a passcode in a calendar invite, or a one-time code dictated into a
note-taker reached the bank verbatim through every OTHER writer. G114 made
"one rule for every writer" the house shape for ids and clocks; this is the
same move for the one thing that must never be stored.

Two families, applied in order:

* **Secrets** — the G105 R6 rules, moved here verbatim from
  ``transcript_extract`` (API keys, bearer tokens, vendor prefixes, JWTs, PEM
  blocks, ``key=value`` credentials, long hex/base64 runs).
  ``transcript_extract.scrub_secrets`` is now :func:`scrub`, so the Stop-hook
  path and every other writer cannot drift apart.
* **One-time codes** (R-LS5) — a 4–8 digit number joined to a code keyword by
  a short connector (``is``/``was``, ``:``, ``=``, ``#``, ``-`` or plain
  whitespace), in either order: "code: 482913", "482913 is your verification
  code". Only the digits are replaced, so the sentence still says a code was
  sent. The connector grammar replaces R3's "within ~24 characters" window on
  purpose: a raw window also ate years in ordinary prose ("wrote code in 2019").

Pure and engine-free. :func:`record` adds one ``capture`` ledger row when
something was replaced — a writer enum and a count, never what was replaced
(the transcript path records its own count in ``transcript_capture._record``).
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"

#: The writer enums a ``capture`` row may carry — ids and enums only (R-LS6).
WRITERS = frozenset({
    "import", "folder", "wispr-flow", "telegram", "media", "apple-notes",
    "calendar", "mcp", "demo",
    "backlog",  # G150 R-B10: a backlog item's title, description and notes
    "tab-groups",  # G160 (round 4): a Chrome tab group's name and its tabs' titles and links
})

# Secret shapes (G105 R6), moved verbatim from transcript_extract. Ordered
# longest-context first so a PEM block is taken whole before its base64 body
# is chewed up piecemeal. The hex and base64 runs are deliberately long
# (32 / 64) so a short git SHA or an ordinary word survives; a base64
# candidate with three or more ``/`` is a path, not a token, and is kept.
_SECRET_RES: tuple[re.Pattern[str], ...] = tuple(re.compile(p, f) for p, f in (
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    (r"\bsk-[A-Za-z0-9_-]{16,}", 0),
    (r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}", 0),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", 0),
    (r"\bxox[abopr]s?-[A-Za-z0-9-]{10,}", 0),
    (r"\bAKIA[0-9A-Z]{16}\b", 0),
    (r"\bAIza[0-9A-Za-z_-]{30,}", 0),
    (r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", 0),
    (r"\bbearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    (r"\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password|passwd|token)\b\s*[=:]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    (r"\b[0-9a-fA-F]{32,}\b", 0),
))
_BASE64_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{64,}={0,2}(?![A-Za-z0-9+/])")

_OTP_KEYWORD = (
    r"(?:one[- ]time\s+(?:pass)?code|verification\s+code|security\s+code|login\s+code"
    r"|sign[- ]in\s+code|auth(?:entication)?\s+code|confirmation\s+code"
    r"|2fa(?:\s+code)?|otp|passcode|pin|code)"
)
_OTP_FORWARD_RE = re.compile(
    rf"\b{_OTP_KEYWORD}(?:\s+(?:is|was))?\s*[:=#-]?\s*(?P<digits>\d{{4,8}})\b", re.IGNORECASE)
_OTP_REVERSE_RE = re.compile(
    rf"\b(?P<digits>\d{{4,8}})\s+is\s+(?:your|the)\s+(?:[A-Za-z]+\s+){{0,2}}{_OTP_KEYWORD}\b",
    re.IGNORECASE)


def _scrub_base64(m: re.Match[str]) -> str:
    return m.group(0) if m.group(0).count("/") >= 3 else REDACTED


def _redact_digits(m: re.Match[str]) -> str:
    start, end = m.span("digits")
    whole, base = m.group(0), m.start()
    return whole[: start - base] + REDACTED + whole[end - base:]


def scrub(text: str) -> tuple[str, int]:
    """Redact secrets, then one-time codes. Returns ``(text, replacements)`` —
    a count for the ledger, never what was replaced."""
    text = text or ""
    count = 0
    for rx in _SECRET_RES:
        text, n = rx.subn(REDACTED, text)
        count += n
    # The base64 pass keeps path-like runs (three or more ``/``), so count
    # only the matches that were actually replaced — ``subn`` would count
    # every match, kept or not.
    count += sum(1 for m in _BASE64_RUN_RE.finditer(text) if m.group(0).count("/") < 3)
    text = _BASE64_RUN_RE.sub(_scrub_base64, text)
    for rx in (_OTP_FORWARD_RE, _OTP_REVERSE_RE):
        text, n = rx.subn(_redact_digits, text)
        count += n
    return text, count


def record(writer: str, count: int, *, bank: str | None = None) -> None:
    """One ``capture`` ledger row for a write that replaced something. Never
    raises: the ledger must not fail a capture (``telemetry.record`` already
    swallows its own I/O errors; the import guard covers a stripped install)."""
    if count <= 0:
        return
    try:
        from api.services import telemetry

        telemetry.record(telemetry.UsageEvent(
            kind="capture", stage="capture", bank=bank, billing="free", invocations=0,
            refs={"writer": writer if writer in WRITERS else "other", "status": "scrubbed",
                  "scrubbed": int(count)},
        ))
    except Exception:  # noqa: BLE001
        pass


def scrub_body(text: str, *, writer: str, bank: str | None = None) -> str:
    """:func:`scrub` + :func:`record`, for a writer that holds one body."""
    cleaned, n = scrub(text)
    record(writer, n, bank=bank)
    return cleaned
