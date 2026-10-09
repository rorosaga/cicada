"""Bounded orientation generation; section detail is composed without the model.

Context limits restrict what the model sees, never what the writer retains.
Shared by opt-in Sleep synthesis and the read-only repair candidate tool.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date

from api.services import claims, entity_body, fact_policy, summary_policy

PROMPT_VERSION = 2
MAX_CONTEXT_CHARS = 24000


def orientation_sentences(body: str, fields: dict) -> list[str]:
    """The sentences of the page's Summary, then of the incoming summary, once each:
    what the new Summary replaces. Each one the model does not mark covered is
    kept as a Key Fact (:func:`compose`)."""
    sections = entity_body.parse_sections(claims.strip_claims_block(body))
    incoming = str(fields.get('summary') or fields.get('description') or '')
    out, seen = [], set()
    for text in (sections.get('Summary', ''), incoming):
        for sentence in entity_body._summary_sentences(text):
            key = entity_body._normalize_fact(sentence)
            if key and key not in seen:
                seen.add(key)
                out.append(sentence)
    return out


def context(body: str, *, name: str, entity_type: str, fields: dict,
            today: str, source_dates: list[str], sources: list[dict] | None = None,
            orientation: bool = False) -> dict:
    claims.raw_claim_entries(body)  # fail closed on unterminated/repeated fences
    sections = entity_body.parse_sections(claims.strip_claims_block(body))
    # Never expose closed/withdrawal claims as present beliefs. Prose itself may
    # contain obsolete statements: the prompt explicitly labels it unverified.
    current = [asdict(c) for c in claims.parse_claims(body, strict=True)
               if claims.is_current(c, now=date.fromisoformat(today)) and not claims.is_record(c)]
    data = dict(name=name, type=entity_type, today=today, source_dates=source_dates,
                existing_sections=sections, incoming=fields, current_claims=current,
                sources=sources or [])
    if orientation:  # Sleep's update: what the new Summary replaces, to mark covered
        data['orientation_sentences'] = orientation_sentences(body, fields)
    return data


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
    if 'orientation_sentences' in data:
        instructions += """Also return "restated": the 0-based indexes of incoming.key_facts, and "covered": the
0-based indexes of orientation_sentences, that say nothing beyond your summary or an
item already in existing_sections' Key Facts (the same fact in other words). Every
other one is kept as a Key Fact. Never list one that adds a detail, a name, a number,
a date or a change. Empty lists are fine.
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


def _confirmed(candidates: list[str], indexes, summary: str, existing_body: str, name: str) -> set[int]:
    """The listed indexes whose item shares two words (beyond the thing's own name)
    with one sentence of the Summary or one Key Fact, and adds no number, tense or
    status word or negation that item lacks (`fact_policy.compatible`) — a check
    that a claim of sameness is about something on the page, never a licence to
    drop text."""
    if not isinstance(indexes, list) or not candidates:
        return set()
    sections = entity_body.parse_sections(claims.strip_claims_block(existing_body))
    on_page = (entity_body._summary_sentences(summary) + entity_body._summary_sentences(sections.get('Summary', ''))
               + entity_body._bullet_lines(sections.get('Key Facts', '')))
    name_words = fact_policy._profile(name)[0]
    out = set()
    for index in indexes:
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(candidates):
            continue
        words = fact_policy._profile(candidates[index])[0] - name_words
        # One page item that shares two words beyond the name and adds back nothing the candidate says
        # (no number, tense/status word or negation the item lacks): otherwise the candidate stays.
        if any(len(words & fact_policy._profile(item)[0]) >= 2 and fact_policy.compatible(candidates[index], item)
               for item in on_page):
            out.add(index)
    return out


def restated_facts(fields: dict, restated, summary: str, existing_body: str) -> set[int]:
    """Incoming fact indexes the model said only restate the page (:func:`_confirmed`).
    Only incoming facts: nothing already on the page is removed this way."""
    facts = [str(f) for f in (fields.get('key_facts') or [])]
    return _confirmed(facts, restated, summary, existing_body, str(fields.get('name') or ''))


def covered_sentences(existing_body: str, fields: dict, covered, summary: str) -> set[str]:
    """Normalized orientation sentences (:func:`orientation_sentences`) the model said the
    new Summary or the Key Facts already say (:func:`_confirmed`)."""
    sentences = orientation_sentences(existing_body, fields)
    chosen = _confirmed(sentences, covered, summary, existing_body, str(fields.get('name') or ''))
    return {entity_body._normalize_fact(sentences[i]) for i in chosen}


def compose(existing_body: str, fields: dict, summary: str, *, restated=(), covered=()) -> str:
    """Replace only Summary, retaining the complete deterministic merge.

    ``restated``: incoming fact indexes to leave out (:func:`restated_facts`);
    ``covered``: normalized replaced-orientation sentences not to keep as Key
    Facts (:func:`covered_sentences`). Every other sentence of the replaced and
    the incoming orientation is kept (`entity_body.retain_orientation`)."""
    prose = claims.strip_claims_block(existing_body)
    sections = entity_body.upgrade_legacy_to_v2(prose, str(fields.get('type', 'concept')))
    original = dict(sections)
    old = sections.pop('Summary', '')
    if restated:
        fields = {**fields, 'key_facts': [f for i, f in enumerate(fields.get('key_facts') or []) if i not in restated]}
    # Compose against the actual replacement, so neither the interim old
    # Summary nor the incoming one suppresses a fact we ultimately retain.
    sections = entity_body.merge_sections_fallback(sections, {**fields, 'summary': summary.strip()})
    selected_key = entity_body._normalize_fact(summary)
    incoming = str(fields.get('summary') or fields.get('description') or '').strip()
    for text in (old, incoming):
        if text and entity_body._normalize_fact(text) != selected_key:
            kept = [sentence for sentence in entity_body._summary_sentences(text)
                    if entity_body._normalize_fact(sentence) not in covered]
            entity_body.retain_orientation(sections, ' '.join(kept), names=[str(fields.get('name') or '')])
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
