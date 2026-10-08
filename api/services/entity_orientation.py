"""Bounded orientation generation; section detail is composed without the model.

Context limits restrict what the model sees, never what the writer retains.
Shared by opt-in Sleep synthesis and the read-only repair candidate tool.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date

from api.services import claims, entity_body, summary_policy

PROMPT_VERSION = 1
MAX_CONTEXT_CHARS = 24000


def context(body: str, *, name: str, entity_type: str, fields: dict,
            today: str, source_dates: list[str], sources: list[dict] | None = None) -> dict:
    claims.raw_claim_entries(body)  # fail closed on unterminated/repeated fences
    sections = entity_body.parse_sections(claims.strip_claims_block(body))
    # Never expose closed/withdrawal claims as present beliefs. Prose itself may
    # contain obsolete statements: the prompt explicitly labels it unverified.
    current = [asdict(c) for c in claims.parse_claims(body, strict=True)
               if claims.is_current(c, now=date.fromisoformat(today)) and not claims.is_record(c)]
    return dict(name=name, type=entity_type, today=today, source_dates=source_dates,
                existing_sections=sections, incoming=fields, current_claims=current,
                sources=sources or [])


def prompt(data: dict, *, repair: bool = False) -> str:
    instructions = """SECTION-AWARE ORIENTATION
Return JSON {"summary": "..."}. Write one paragraph, 1-3 complete sentences,
at most 600 characters. Describe the entity and its evidenced role for the owner;
if its present role is unknown, say so. No source narration, markdown or relative
time words (currently, now, recently, soon). Use only the supplied evidence.
Existing prose is unverified background, not proof of a current belief.
Only current_claims are structurally current; even an open claim about a plan or
state of mind is dated. Material said more than 90 days before today names its
month and year. Plans and intentions always name when they were stated.
Keep absolute dates; an earlier import never overrides a later dated state.
A page's last-mentioned date does not date every fact. Multiple source dates do
not prove which date belongs to an incoming sentence. With no item-level date,
describe dated background cautiously or state that present status is unknown.
Do not regenerate facts, history, links or questions; they are retained by code.
"""
    if repair:
        instructions += """For repair also return "dated_edits": [{"id": "...", "text": "...",
"source_id": "..."}]. Edit only the provided existing item ids, using its same
facts and a date explicitly grounded in that named source. The text must be
exactly "YYYY-MM-DD: " followed by the original item text, which must occur
verbatim in that source. Skip already dated or multiline items. No deletions or new
items. Do not change Summary using unsupported conclusions. An empty edit list
is allowed. Items with no adequate source remain untouched.
"""
    return instructions + "\nINPUT:\n" + json.dumps(data, ensure_ascii=False, sort_keys=True)


def valid_summary(text) -> bool:
    return (isinstance(text, str) and summary_policy.usable(text)
            and bool(re.search(r'[.!?]["\u201d\u2019\']?$', text.strip()))
            and not re.search(r'```|^\s*[#*-]|\[\[|\b(?:currently|now|recently|soon)\b', text, re.I))


def compose(existing_body: str, fields: dict, summary: str) -> str:
    """Replace only Summary, retaining the complete deterministic merge."""
    prose = claims.strip_claims_block(existing_body)
    sections = entity_body.upgrade_legacy_to_v2(prose, str(fields.get('type', 'concept')))
    original = dict(sections)
    sections = entity_body.merge_sections_fallback(sections, fields)
    old = sections.get('Summary', '')
    if old.strip() != summary.strip():
        entity_body._background(sections, old)
    sections['Summary'] = summary.strip()
    # Canonical sections can still contain free prose from legacy writers.
    # Preserve it and append only new items during an orientation-only rewrite.
    for title in ('Key Facts', 'History', 'Links', 'Open Questions'):
        text = original.get(title, '')
        if any(line.strip() and not line[:1].isspace() and not line.startswith(('- ', '* '))
               for line in text.splitlines()):
            seen = {entity_body._normalize_fact(i) for i in entity_body._bullet_lines(text)}
            additions = [i for i in entity_body._bullet_lines(sections.get(title, ''))
                         if entity_body._normalize_fact(i) not in seen]
            sections[title] = text + ('\n' + entity_body._bullets_block(additions) if additions else '')
    return claims.preserve_claims_blocks(existing_body, entity_body.render_sections(sections))


def bounded_prompt(data: dict, *, repair: bool = False) -> str | None:
    # No silent clipping, which could remove the latest dated evidence. Large
    # inputs use the deterministic fallback (repair records a deferral).
    result = prompt(data, repair=repair)
    return result if len(result) <= MAX_CONTEXT_CHARS else None
