"""The quick review's context (owner 2026-10-19): enough on a decay or fold card to decide without opening the page.

The app's review goes one kind at a time — "Fading pages · 49", then one card at a time with the same answers in the
same place. A decay card needs when the page was last said and in how many conversations; a fold card needs the two
predicate names and what the page is. Both are derived here at read from the subject page through the inbox's own
read cache (:class:`inbox_context.InboxContext`): engine-free, never stored, never a hidden card (a failure leaves the
field out). Answers still go through ``POST /inbox/{id}/resolve`` — this module writes nothing.
"""

from __future__ import annotations

import re

from api.models.schemas import InboxFold, InboxSubject
from api.services import decay_policy
from api.services.inbox_generator import fold_claims

#: The kinds whose card carries a ``subject`` block.
SUBJECT_KINDS = frozenset({"decay", "normalization"})

#: A summary or an example sentence longer than this is cut on a word boundary.
CLIP_CHARS = 200

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def clip(text: str | None, limit: int = CLIP_CHARS) -> str | None:
    """The first sentence of ``text``, whitespace collapsed, cut on a word at ``limit`` with an ellipsis."""
    line = " ".join(str(text or "").split())
    if not line:
        return None
    line = _SENTENCE_END.split(line, maxsplit=1)[0]
    if len(line) <= limit:
        return line
    cut = line[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return (cut or line[: limit - 1]) + "…"


def _page_summary(page) -> str | None:
    """The page's lead: its frontmatter ``summary`` when a writer kept one, else its ``## Summary`` section."""
    fm = page.frontmatter or {}
    if str(fm.get("summary") or "").strip():
        return clip(fm.get("summary"))
    try:
        from api.services import entity_body
        from api.services.claims import strip_claims_block

        return clip(entity_body.parse_sections(strip_claims_block(page.body())).get("Summary"))
    except Exception:  # noqa: BLE001 — a page with no lead simply has none to show
        return None


def subject_for(entity_id: str, context) -> InboxSubject | None:
    """What the page is and how often it was said. ``None`` when the subject has no page."""
    page = context.entity(entity_id)
    if page is None:
        return None
    refs = (page.frontmatter or {}).get("source_episodes")
    untimed = context.untimed()
    return InboxSubject(
        summary=_page_summary(page),
        conversations=decay_policy.conversations(refs, untimed=untimed),
        last_said=decay_policy.latest_said(refs, untimed=untimed),
    )


def _words(predicate: str) -> str:
    return " ".join(str(predicate or "").replace("-", " ").replace("_", " ").split())


def fold_for(fm: dict, context) -> InboxFold | None:
    """The fold in words. ``fm`` is the item as served (its ``entity_id``/``claim_id`` already the live anchor's).
    ``None`` for a legacy item that never recorded the pair — the card then shows its question alone."""
    raw = _words(fm.get("raw_predicate"))
    canonical = _words(fm.get("canonical_predicate"))
    if not raw or not canonical:
        return None
    covered = fold_claims(fm)
    entity_id = str(fm.get("entity_id", "") or "")
    claim_id = str(fm.get("claim_id", "") or "")
    claim = next((c for c in context.claims(entity_id) if c.id == claim_id), None) if claim_id else None
    return InboxFold(
        raw=raw,
        canonical=canonical,
        claims=len(covered),
        pages=len({e for e, _ in covered}),
        example=clip(claim.text) if claim is not None else None,
    )
