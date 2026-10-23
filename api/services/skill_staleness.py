"""W6 (G148, G112; 2026-10-23): a Stage 4 skill whose summary rests on a belief that has since closed is stale.

Stage 4 writes a skill's prose once, at its birth (``skill_grounding``: a re-detection is evidence, never new text), so
"For fernpost, Teo reviews the <tool> pull requests" outlives the day the project dropped the tool. The handshake's
*How to work with me* is those summaries' first sentences, so an agent arriving after the switch was told the old
stack as a working agreement.

A summary **cites** a claim when the claim joins two pages the skill draws on (its ``related``, the ``draws on``
edges) and the summary names the claim's object by its page's name or an alias. The summary's **day** is the newest
conversation its section provenance cites — the day its words were true. The skill is **stale** when a cited claim
that was open on that day (``valid_from`` on or before it) closed after it. Nothing here calls a model or writes a page: the cursor builder (``state_dictionary``) leaves
a stale skill out of *How to work with me* on the next rebuild, which Sleep's tail runs every night. The page itself
is unchanged; a later Stage 4 that grounds the pattern again keeps it, as before.

When unsure, a skill is kept: no provenance, no dated conversation, a claim closed with no date, or an event
(``happened``/``milestone``, born closed) or a withdrawal record — none of those makes a summary stale.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable

from api.services import section_provenance
from api.services.claims import Claim, is_event, is_record, parse_claims

_EP_DAY = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_")
_MIN_NAME = 3


def summary_day(frontmatter: dict, body: str) -> str | None:
    """The newest day among the conversations the ``## Summary``'s provenance cites, or ``None``. An episode id
    carries the conversation's local day (ruling 34), the same day a claim's ``valid_to`` is dated in."""
    try:
        rows = section_provenance.matched(frontmatter or {}, body or "").get("summary") or {}
    except Exception:   # noqa: BLE001 - unreadable provenance: no day, so the skill is kept
        return None
    days = [m.group(1) for _guard, evs in rows.values() for ev in evs
            if (m := _EP_DAY.match(str(getattr(ev, "episode", "") or "")))]
    return max(days) if days else None


def _summary_text(body: str) -> str:
    from api.services.claims import strip_claims_block
    from api.services.entity_body import parse_sections

    try:
        return str(parse_sections(strip_claims_block(body or "")).get("Summary") or "")
    except Exception:   # noqa: BLE001
        return ""


def _names(text: str, spellings: Iterable[str]) -> bool:
    low = text.lower()
    for raw in spellings:
        word = " ".join(str(raw or "").split()).lower()
        if len(word) >= _MIN_NAME and re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", low):
            return True
    return False


def closed_since(frontmatter: dict, body: str, page: Callable[[str], tuple[list[str], str] | None]) -> list[Claim]:
    """The claims a skill's summary cites that closed after the summary's day (see the module docstring).

    ``page(id)`` answers a page's spellings (name, then aliases) and its body, or ``None`` for no such page."""
    day = summary_day(frontmatter, body)
    related = [str(r) for r in (frontmatter or {}).get("related") or [] if r]
    if not day or len(related) < 2:
        return []
    text = _summary_text(body)
    if not text:
        return []
    members = set(related)
    stale: list[Claim] = []
    for sid in related:
        found = page(sid)
        if found is None:
            continue
        for c in parse_claims(found[1]):
            if c.subject != sid or c.object not in members or c.object == sid:
                continue
            if is_event(c) or is_record(c) or not c.valid_to or str(c.valid_to)[:10] <= day:
                continue
            if not c.valid_from or str(c.valid_from)[:10] > day:
                continue   # not yet believed when the summary was written: a later record, never what it rests on
            target = page(c.object)
            if target is not None and _names(text, target[0]):
                stale.append(c)
    return stale
