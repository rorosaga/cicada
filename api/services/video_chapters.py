"""Chapters from a video's own description text (G140 Q-R12, R5 §5.6) — fields only.

YouTube's rule for chapters is "formatted timestamps (for example, 00:00) in
the description text", and Vimeo and Loom descriptions follow the same habit.
So a chapter list is PARSED, deterministically, from text a provider already
returned — never fetched, never inferred, never a model. A list counts only
when it looks like one: at least two lines that each OPEN with a timestamp,
the first at 0:00, strictly increasing. Anything else — a lone "at 3:15 we…"
sentence — is prose and yields nothing: absent beats a guess (R17).

``seconds``/``stamp`` are the one reading of a video time in the backend, so
a watch record's excerpt times (``watch_record``) and a description's
chapter times can never parse differently.
"""
from __future__ import annotations

import re

MAX_CHAPTERS = 50
TITLE_LIMIT = 120
# A line that OPENS with a time: an optional bullet, an optional bracket round
# the time, then an optional separator before the title. A time anywhere else
# on the line ("at 3:15 we…") never matches — that is prose, not a chapter.
_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?[(\[]?(?P<t>(?:\d{1,2}:)?\d{1,2}:\d{2})[)\]]?\s*(?:[-–—:|]\s*)?(?P<title>\S.*?)\s*$"
)



def opens_with_stamp(line: str) -> bool:
    """True when ``line`` OPENS with a timestamp the way a chapter row does.

    The one reading of "this line is a chapter stamp" outside ``parse`` —
    link enrichment drops such lines before a description becomes a
    ``describes`` claim (G140 final review), and it must not disagree with
    the parser about which lines those are.
    """
    return bool(_LINE.match(line or ""))

def seconds(raw) -> int | None:
    """``m:ss`` / ``h:mm:ss`` / whole seconds (int or digits) → seconds;
    ``None`` when unreadable. Minutes and seconds after the first field must
    be < 60."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    nums = [int(p) for p in parts]
    if any(n >= 60 for n in nums[1:]):
        return None
    total = 0
    for n in nums:
        total = total * 60 + n
    return total


def stamp(total: int) -> str:
    """Seconds → ``m:ss`` or ``h:mm:ss`` — the form a player shows."""
    hours, rest = divmod(max(0, int(total)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def parse(description: str | None) -> list[dict]:
    """``[{"t": seconds, "title": str}]`` from a description, or ``[]``.

    A time that goes backwards voids the whole list rather than truncating it:
    a list that reorders is not a chapter list, and a half-list would present a
    guess as the provider's own structure (R17). At most ``MAX_CHAPTERS`` rows,
    titles cut at ``TITLE_LIMIT``.
    """
    out: list[dict] = []
    for line in (description or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        t = seconds(m.group("t"))
        title = m.group("title").strip()[:TITLE_LIMIT]
        if t is None or not title:
            continue
        if out and t <= out[-1]["t"]:
            return []
        out.append({"t": t, "title": title})
        if len(out) >= MAX_CHAPTERS:
            break
    if len(out) < 2 or out[0]["t"] != 0:
        return []
    return out
