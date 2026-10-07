"""G118 item links: compact scalars in frontmatter, exact identity on read.

No I/O, engine, indexes, claim IDs or stored quotes. The server owns item
parsing and Unicode code-point ranges. Normalization is lookup only; an exact
text guard is mandatory. Unsupported schemas fail closed and survive writes.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace

from api.services import entity_body, evidence
from api.services.claims import Evidence, FENCE_UNREADABLE, fence_state

FIELD = 'section_provenance'
INPUTS = '_section_inputs'  # transient, never serialized into a page
TITLES = {'summary': 'Summary', 'key_facts': 'Key Facts', 'history': 'History',
          'links': 'Links', 'open_questions': 'Open Questions'}
_CODES = {'user': 'u', 'assistant': 'a', 'page': 'p', 'reasoning': 'r', 'speaker': 's', 'media': 'm'}
_KINDS = {v: k for k, v in _CODES.items()}
_HASH = re.compile(r'[0-9a-f]{12}')
_DOC = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}')
_ROW = re.compile(r'(s\d+):(-?\d+):(-?\d+):([uaprsm])')
_HEADING = re.compile(r'^##\s+(.+?)\s*$')
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
_BULLET = re.compile(r'^[-*+]\s+')


@dataclass(frozen=True)
class Item:
    key: str
    text_hash: str
    text: str
    ranges: tuple[tuple[int, int], ...]
    ambiguous: bool = False


def _item(text: str, ranges: tuple) -> Item:
    return Item(evidence.body_hash(entity_body._normalize_fact(text)), evidence.body_hash(text), text, ranges)


def _fragments(body: str) -> tuple[dict, str | None]:
    """Raw section fragments plus the actual last heading, ignoring fences."""
    fragments: dict[str, list[list[tuple[int, str, bool]]]] = {}
    title = None
    lines = None
    fence = None
    claims = False
    offset = 0
    for raw in (body or '').splitlines(keepends=True):
        line = raw.rstrip('\r\n')
        marker = _FENCE.match(line)
        was_fenced = fence is not None
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
                if claims:
                    claims = False
                    lines = None
                    offset += len(raw)
                    continue
        elif marker:
            fence = marker[1]
            claims = marker[2].strip() == 'claims'
        if claims:
            offset += len(raw)
            continue
        heading = _HEADING.match(line) if not was_fenced and not marker else None
        if heading:
            title = next((k for k, t in TITLES.items() if t == heading[1]), None)
            lines = None
        elif title:
            if lines is None:
                lines = []
                fragments.setdefault(title, []).append(lines)
            lines.append((offset, raw, was_fenced or marker is not None))
        offset += len(raw)

    return fragments, title


def scan(body: str) -> dict[str, list[Item]]:
    """Canonical sections, duplicate headings accumulated; fences are not headings.

    Summary is one item. A top-level bullet and its indented continuation
    form one item. Claims never enter fingerprints; offsets index RAW body.
    """
    fragments, _ = _fragments(body)

    result = {}
    for key, chunks in fragments.items():
        items = []
        if key == 'summary':
            texts, ranges = [], []
            for chunk in chunks:
                raw = ''.join(row[1] for row in chunk)
                text = raw.strip()
                if text:
                    start = chunk[0][0] + len(raw) - len(raw.lstrip())
                    texts.append(text)
                    ranges.append((start, start + len(text)))
            if texts:
                items.append(_item('\n'.join(texts), tuple(ranges)))
        else:
            for chunk in chunks:
                current = []
                def finish():
                    if current:
                        first = current[0]
                        raw = ''.join(row[1] for row in current)
                        prefix = _BULLET.match(first[1]).end()
                        text = raw[prefix:].rstrip()
                        if text:
                            start = first[0] + prefix
                            items.append(_item(text, ((start, start + len(text)),)))
                        current.clear()
                for row in chunk:
                    if not row[2] and _BULLET.match(row[1]):
                        finish()
                        current.append(row)
                    elif current and (row[1].startswith((' ', '\t')) or not row[1].strip()):
                        current.append(row)
                    else:
                        finish()
                finish()
        counts = Counter(item.key for item in items)
        result[key] = [replace(item, ambiguous=counts[item.key] > 1) for item in items]
    return result


def unavailable_section(body: str) -> str | None:
    if fence_state(body) != FENCE_UNREADABLE:
        return None
    opening = re.search(r'^```claims[ \t]*\r?$', body, re.MULTILINE)
    return _fragments(body[:opening.start()])[1] if opening else None


def decode(raw) -> dict | None:
    """Decode schema 1, rejecting malformed coordinates, unsafe IDs and kinds.

    Scalars use `guard s0:start:end:kind ...`; source scalars use `id hash`.
    Unknown top-level fields are allowed and preserved by refresh.
    """
    if not isinstance(raw, dict) or type(raw.get('v')) is not int or raw['v'] != 1:
        return None
    try:
        sources = {}
        for key, value in raw['sources'].items():
            if not re.fullmatch(r's\d+', key) or not isinstance(value, str):
                return None
            doc, hash_ = value.split()
            if not _DOC.fullmatch(doc) or not _HASH.fullmatch(hash_):
                return None
            sources[key] = (doc, hash_)
        result = {}
        for section, items in raw['sections'].items():
            if section not in TITLES or not isinstance(items, dict):
                return None
            result[section] = {}
            for key, value in items.items():
                if not isinstance(key, str) or not _HASH.fullmatch(key) or not isinstance(value, str):
                    return None
                guard, *tokens = value.split()
                if not _HASH.fullmatch(guard) or not tokens:
                    return None
                rows = []
                for token in tokens:
                    row = _ROW.fullmatch(token)
                    if not row or row[1] not in sources:
                        return None
                    start, end, kind = int(row[2]), int(row[3]), _KINDS[row[4]]
                    if not ((kind == 'reasoning' and start == end == -1) or
                            (kind != 'reasoning' and 0 <= start < end)):
                        return None
                    doc, hash_ = sources[row[1]]
                    ev = Evidence(episode=doc, hash=hash_, start=start, end=end, kind=kind)
                    if ev not in rows:
                        rows.append(ev)
                result[section][key] = (guard, rows)
        return result
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def encode(records: dict) -> dict:
    sources, source_keys, sections = {}, {}, {}
    for section, items in records.items():
        stored = {}
        for key, (guard, evs) in items.items():
            tokens = []
            for ev in evs:
                pair = (ev.episode, ev.hash)
                if pair not in source_keys:
                    skey = f's{len(sources)}'
                    source_keys[pair] = skey
                    sources[skey] = f'{ev.episode} {ev.hash}'
                token = f'{source_keys[pair]}:{ev.start}:{ev.end}:{_CODES[ev.kind]}'
                if token not in tokens:
                    tokens.append(token)
            if tokens:
                stored[key] = ' '.join([guard, *tokens])
        if stored:
            sections[section] = stored
    return {'v': 1, 'sources': sources, 'sections': sections}


def matched(frontmatter: dict, body: str) -> dict:
    records = decode(frontmatter.get(FIELD)) or {}
    unavailable = unavailable_section(body)
    return {section: {item.key: records[section][item.key] for item in items
                      if not item.ambiguous and item.key in records.get(section, {})
                      and records[section][item.key][0] == item.text_hash}
            for section, items in scan(body).items() if section in records and section != unavailable}


def attach(entity: dict, episode_id: str, body: str) -> None:
    """Stage 1a-i: link each existing output item to its source, no prompt/call.

    Do not trust model-supplied private fields. Reasoning records inference,
    never an exact quotation, even when the prose resembles the conversation.
    """
    records = []
    ev = evidence.reasoning(episode_id, hash=evidence.body_hash(body)).to_dict()
    for field in ('summary', 'description', 'key_facts'):
        values = entity.get(field) or []
        if field != 'key_facts':
            values = [values]
        for value in values:
            if isinstance(value, str) and value.strip():
                records.append({'field': field, 'text': value.strip(), 'evidence': [dict(ev)]})
    entity[INPUTS] = records


def merge_selected(base: dict, incoming: dict, *, incoming_description: bool) -> list[dict]:
    """Follow current Stage-2 fields; never union facts it actually discards."""
    return [record for record in base.get(INPUTS, []) if record['field'] != 'description'] + [
        record for record in (incoming if incoming_description else base).get(INPUTS, [])
        if record['field'] == 'description']


def refresh(frontmatter: dict, original_body: str, body: str, entity: dict, *, synthesized: bool = False) -> None:
    """Filter links by exact CURRENT old items plus selected incoming text.

    Never repair an unmatched guard. No raw record survives a writer just
    because the resulting text happens to match an obsolete pre-edit value.
    """
    raw = frontmatter.get(FIELD)
    if raw is not None and decode(raw) is None:
        return  # preserve unknown/malformed metadata without recertification
    old = matched(frontmatter, original_body)
    incoming = {}
    selected_summary = 'description' if synthesized else ('summary' if entity.get('summary') else 'description')
    for record in entity.get(INPUTS, []) or []:
        field = record['field']
        section = 'summary' if field == selected_summary else ('key_facts' if field == 'key_facts' and not synthesized else None)
        if not section:
            continue
        text = record['text']
        item = _item(text, ())
        entry = incoming.setdefault(section, {}).setdefault(item.key, (item.text_hash, []))
        if entry[0] == item.text_hash:
            for ev in record['evidence']:
                value = Evidence(**ev)
                if value not in entry[1]:
                    entry[1].append(value)
    records = {}
    unavailable = unavailable_section(body)
    for section, items in scan(body).items():
        if section == unavailable:
            continue
        for item in items:
            if item.ambiguous:
                continue
            evs = []
            for candidates in (old, incoming):
                value = candidates.get(section, {}).get(item.key)
                if value and value[0] == item.text_hash:
                    evs.extend(ev for ev in value[1] if ev not in evs)
            if evs:
                records.setdefault(section, {})[item.key] = (item.text_hash, evs)
    if records or raw is not None:
        extras = {k: v for k, v in (raw or {}).items() if k not in ('v', 'sources', 'sections')}
        frontmatter[FIELD] = {**extras, **encode(records)}
