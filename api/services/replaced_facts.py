"""A replaced fact leaves Key Facts and stays in History (owner 2026-11-07: "yes").

A stated value (``value-of-<attribute>``, a literal; ``claims.is_value_claim``) is one at a time: a later value closes the
earlier one (``claim_reconciler``). The claim keeps the old value with its dates, but the page's Key Facts went on
saying it — Key Facts only ever grew (``entity_body._merge_facts``) — so a page read "version 0.3.1" and "version
0.6.0" side by side. Here, in the same write that closes the claim, a Key Facts bullet that says the replaced value and
not the replacing one moves to History with the old claim's dates, whole, so no word of it is lost.

Narrow on purpose, no model and no word lists: only a *value* claim (the one kind whose value Stage 1 states in Key Facts
too), a whole-word match of the old value after ``fact_policy.normalized`` folding, never a bullet that also says the new
value, never a page a person wrote or edited (``entity_body.has_human_prose``). A bullet that is not about a replaced value
stays. Pure string logic over a page body and its claims before and after; the callers (``claim_pipeline``,
``agentic_write``) already write the page.
"""
from __future__ import annotations

import re

from api.services import claims as claims_mod
from api.services import entity_body, fact_policy

#: A value shorter than this (after folding) is too common to tie a sentence to ("a", "3").
MIN_VALUE_CHARS = 2


def _says(bullet: str, value: str) -> bool:
    folded = fact_policy.normalized(value)
    if len(folded) < MIN_VALUE_CHARS:
        return False
    return re.search(r"(?<!\w)" + re.escape(folded) + r"(?!\w)", fact_policy.normalized(bullet)) is not None


def newly_replaced(before, after) -> list[tuple[object, object]]:
    """``(old, new)`` for each value claim in ``after`` that a later value closed in this change and ``before`` did not
    hold closed."""
    had = {c.id: c for c in before or ()}
    by_id = {c.id: c for c in after or ()}
    out = []
    for c in after or ():
        if not claims_mod.is_value_claim(c) or not c.superseded_by:
            continue
        old = had.get(c.id)
        if old is not None and old.superseded_by:
            continue
        new = by_id.get(c.superseded_by)
        if (new is None or not claims_mod.is_value_claim(new)
                or fact_policy.normalized(new.object) == fact_policy.normalized(c.object)):
            continue
        out.append((c, new))
    return out


def retire(frontmatter: dict, body: str, before, after) -> str:
    """``body`` with the Key Facts bullets that state a value this change replaced moved into History, or ``body``
    itself when nothing qualifies. ``before`` and ``after`` are the page's claims around the change."""
    pairs = newly_replaced(before, after)
    if not pairs or "## Key Facts" not in (body or ""):
        return body
    sections = entity_body.parse_sections(claims_mod.strip_claims_block(body))
    if entity_body.has_human_prose(frontmatter or {}, sections):
        return body
    facts = entity_body._bullet_lines(sections.get("Key Facts", ""))
    moved: list[dict] = []
    for old, new in pairs:
        start, end = str(old.valid_from or "")[:10], str(old.valid_to or "")[:10]
        for bullet in list(facts):
            if _says(bullet, old.object) and not _says(bullet, new.object):
                facts.remove(bullet)
                tail = f" (until {end})" if start and end else f" (replaced {end})" if end else ""
                moved.append({"date": start, "event": f"{bullet.strip()}{tail}"})
    if not moved:
        return body
    if facts:
        sections["Key Facts"] = entity_body._bullets_block(facts)
    else:
        sections.pop("Key Facts", None)
    sections["History"] = entity_body._merge_history_bullets(sections.get("History", ""), moved)
    return claims_mod.write_claims(entity_body.render_sections(sections), after)
