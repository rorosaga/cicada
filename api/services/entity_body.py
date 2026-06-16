"""Entity body v2 — the section grammar (parse / render / compose / merge).

Single source of truth for the ordered, section-aware entity body layout
(``layout_version: 2``). Extractor, conflict_resolver, the routers, the
backfill script, and LEANN all share this implementation.

A v2 body is a sequence of H2 sections in a fixed canonical order. Any
section may be absent (rendered + parsed as empty). No prose lives above the
first H2 — a v1 flat body's leading paragraph is lifted into ``## Summary``.

    ## Summary        ## Key Facts        ## History
    ## Related        ## Links            ## Open Questions

All functions are pure string logic — no LLM, no I/O — so they are safe to
call on every read and in tight loops.
"""

from __future__ import annotations

import re

CANONICAL_SECTIONS = [
    "Summary",
    "Key Facts",
    "History",
    "Related",
    "Links",
    "Open Questions",
]

# H2 heading matcher. Captures the trimmed title after "## ".
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_URL_IN_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")


def parse_sections(body: str) -> dict[str, str]:
    """Split a markdown body into ``{section_title: section_markdown}``.

    Lines before the first H2 are returned under a synthetic ``""`` key
    (legacy lead prose). Section bodies are stripped of surrounding
    whitespace. Works on both v1 (flat prose + optional ``## History``) and
    v2 bodies.
    """
    body = (body or "").strip()
    if not body:
        return {}

    matches = list(_H2.finditer(body))
    sections: dict[str, str] = {}

    if not matches:
        # Pure flat body — all prose, no headings.
        sections[""] = body
        return sections

    lead = body[: matches[0].start()].strip()
    if lead:
        sections[""] = lead

    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        # Later duplicate headings of the same title accumulate (defensive).
        if title in sections and sections[title]:
            sections[title] = (sections[title] + "\n" + content).strip()
        else:
            sections[title] = content
    return sections


def render_sections(sections: dict[str, str]) -> str:
    """Serialize a section dict to canonical-order markdown, dropping empties.

    Any non-canonical keys (other than the synthetic ``""`` lead key, which
    is folded into Summary if Summary is empty) are appended after the
    canonical sections so no content is silently lost.
    """
    sections = dict(sections or {})
    lead = (sections.pop("", "") or "").strip()
    if lead and not (sections.get("Summary") or "").strip():
        sections["Summary"] = lead
    elif lead:
        # Both exist — preserve lead by prepending to Summary.
        sections["Summary"] = (lead + "\n\n" + sections["Summary"]).strip()

    blocks: list[str] = []
    for title in CANONICAL_SECTIONS:
        content = (sections.get(title, "") or "").strip()
        if content:
            blocks.append(f"## {title}\n{content}")

    # Preserve any unexpected extra sections.
    for title, content in sections.items():
        if title in CANONICAL_SECTIONS:
            continue
        content = (content or "").strip()
        if content:
            blocks.append(f"## {title}\n{content}")

    return "\n\n".join(blocks).strip()


def _bullet_lines(content: str) -> list[str]:
    """Return the bullet lines (``- ...``) of a section body, text only."""
    lines: list[str] = []
    for raw in (content or "").splitlines():
        stripped = raw.strip()
        if stripped.startswith("- "):
            lines.append(stripped[2:].strip())
        elif stripped.startswith("* "):
            lines.append(stripped[2:].strip())
    return lines


def _normalize_fact(text: str) -> str:
    """Normalized key for dedup: lowercased, wikilink-unwrapped, despaced."""
    text = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", text or "")
    text = re.sub(r"[`*_]", "", text)
    return " ".join(text.lower().split())


def _bullets_block(items: list[str]) -> str:
    return "\n".join(f"- {it}" for it in items if it.strip())


def _history_sort_key(line: str):
    """History entries sort chronologically; undated entries sort last."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", line.strip())
    if m:
        return (0, m.group(1), line)
    return (1, "", line)


def _merge_history_bullets(existing: str, new_entries: list[dict]) -> str:
    """Merge dated history bullets, dedupe exact lines, sort chronologically."""
    lines = _bullet_lines(existing)
    seen = {_normalize_fact(line) for line in lines}
    for entry in new_entries or []:
        event_date = str(entry.get("date", "")).strip()
        event = str(entry.get("event", "")).strip()
        if not event:
            continue
        line = f"{event_date}: {event}" if event_date else event
        key = _normalize_fact(line)
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    lines = sorted(lines, key=_history_sort_key)
    return _bullets_block(lines)


def _merge_facts(existing: str, new_facts: list[str]) -> str:
    """Union of fact bullets, deduped by normalized text."""
    items = _bullet_lines(existing)
    seen = {_normalize_fact(it) for it in items}
    for fact in new_facts or []:
        fact = str(fact).strip()
        if not fact:
            continue
        key = _normalize_fact(fact)
        if key in seen:
            continue
        seen.add(key)
        items.append(fact)
    return _bullets_block(items)


def _link_url(line: str) -> str:
    m = _URL_IN_LINK.search(line)
    return m.group(1).strip() if m else _normalize_fact(line)


def _link_bullet(link: dict) -> str:
    url = str(link.get("url", "")).strip()
    if not url:
        return ""
    title = str(link.get("title", "")).strip() or url
    note = str(link.get("note", "")).strip()
    bullet = f"[{title}]({url})"
    if note:
        bullet += f" — {note}"
    return bullet


def _merge_links(existing: str, new_links: list[dict]) -> str:
    """Union of link bullets, deduped by URL."""
    items = _bullet_lines(existing)
    seen = {_link_url(it) for it in items}
    for link in new_links or []:
        bullet = _link_bullet(link)
        if not bullet:
            continue
        url = _link_url(bullet)
        if url in seen:
            continue
        seen.add(url)
        items.append(bullet)
    return _bullets_block(items)


def _merge_open_questions(existing: str, new_questions: list[str]) -> str:
    """Union of open-question bullets, deduped by normalized text."""
    items = _bullet_lines(existing)
    seen = {_normalize_fact(it) for it in items}
    for q in new_questions or []:
        q = str(q).strip()
        if not q:
            continue
        key = _normalize_fact(q)
        if key in seen:
            continue
        seen.add(key)
        items.append(q)
    return _bullets_block(items)


def compose_body_v2(
    summary: str,
    key_facts: list[str],
    history_entries: list[dict],
    related: list[tuple[str, str]],
    links: list[dict],
    open_questions: list[str],
) -> str:
    """Build a fresh v2 body from extracted fields (Stage-1 create path)."""
    sections: dict[str, str] = {}
    summary = (summary or "").strip()
    if summary:
        sections["Summary"] = summary

    facts = _merge_facts("", key_facts or [])
    if facts:
        sections["Key Facts"] = facts

    history = _merge_history_bullets("", history_entries or [])
    if history:
        sections["History"] = history

    related_block = _related_bullets(related or [])
    if related_block:
        sections["Related"] = related_block

    link_block = _merge_links("", links or [])
    if link_block:
        sections["Links"] = link_block

    oq = _merge_open_questions("", open_questions or [])
    if oq:
        sections["Open Questions"] = oq

    return render_sections(sections)


def merge_sections_fallback(existing: dict[str, str], new_fields: dict) -> dict[str, str]:
    """Non-LLM section-aware merge used when synthesis is unavailable.

    Union Key Facts / Links / Open Questions, append+dedupe History, keep the
    existing Summary if no new summary is supplied (else integrate by
    appending a sentence rather than replacing). Never raw-appends a blob.

    ``new_fields`` keys (all optional): ``summary``, ``key_facts``,
    ``history_entries``, ``links``, ``open_questions``.
    """
    merged = dict(existing or {})

    new_summary = str(new_fields.get("summary", "") or "").strip()
    if new_summary:
        old_summary = (merged.get("Summary", "") or "").strip()
        if not old_summary:
            merged["Summary"] = new_summary
        elif _normalize_fact(new_summary) not in _normalize_fact(old_summary):
            # Append as a follow-on sentence — no raw paragraph stacking.
            merged["Summary"] = (old_summary.rstrip() + " " + new_summary).strip()

    new_facts = list(new_fields.get("key_facts", []) or [])
    if new_facts or merged.get("Key Facts"):
        facts = _merge_facts(merged.get("Key Facts", ""), new_facts)
        if facts:
            merged["Key Facts"] = facts

    new_history = list(new_fields.get("history_entries", []) or [])
    if new_history or merged.get("History"):
        history = _merge_history_bullets(merged.get("History", ""), new_history)
        if history:
            merged["History"] = history

    new_links = list(new_fields.get("links", []) or [])
    if new_links or merged.get("Links"):
        link_block = _merge_links(merged.get("Links", ""), new_links)
        if link_block:
            merged["Links"] = link_block

    new_oq = list(new_fields.get("open_questions", []) or [])
    if new_oq or merged.get("Open Questions"):
        oq = _merge_open_questions(merged.get("Open Questions", ""), new_oq)
        if oq:
            merged["Open Questions"] = oq

    return merged


def upgrade_legacy_to_v2(body: str, entity_type: str) -> dict[str, str]:
    """Lift a v1 flat body into a v2 section dict (pure string transform).

    Leading prose -> Summary, an existing ``## History`` is preserved, any
    other recognized H2 sections are kept under their canonical key. No LLM.
    Used by lazy migration and the structural backfill.
    """
    parsed = parse_sections(body)
    sections: dict[str, str] = {}

    lead = (parsed.get("", "") or "").strip()
    summary = (parsed.get("Summary", "") or "").strip()
    if summary and lead:
        sections["Summary"] = (lead + "\n\n" + summary).strip()
    elif summary:
        sections["Summary"] = summary
    elif lead:
        sections["Summary"] = lead

    for title, content in parsed.items():
        if title in ("", "Summary"):
            continue
        content = (content or "").strip()
        if not content:
            continue
        if title in CANONICAL_SECTIONS:
            sections[title] = content
        else:
            # Non-canonical heading from a hand-edited page — fold into Key
            # Facts as bullets so nothing is lost and traversal still works.
            existing_kf = sections.get("Key Facts", "")
            sections["Key Facts"] = (existing_kf + f"\n- {title}: {content}").strip()
    return sections


def _related_bullets(related: list[tuple[str, str]]) -> str:
    """Render ``[[Name]] — verb phrase`` bullets, deduped by display name."""
    items: list[str] = []
    seen: set[str] = set()
    for entry in related or []:
        if isinstance(entry, (tuple, list)) and len(entry) >= 1:
            name = str(entry[0]).strip()
            verb = str(entry[1]).strip() if len(entry) >= 2 else ""
        else:
            name = str(entry).strip()
            verb = ""
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        bullet = f"[[{name}]]"
        if verb:
            bullet += f" — {verb}"
        items.append(bullet)
    return _bullets_block(items)


def render_related(related_slugs: list[str], edges: list[dict], id_to_name: dict) -> str:
    """Build the ``## Related`` bullet block from the related slug list +
    ``graph_edges.yaml`` labels.

    ``edges`` is the raw ``graph_edges.yaml`` edge list (``{source, target,
    label}`` dicts) filtered to this entity, ``id_to_name`` maps entity id ->
    display name. Wikilinks stay in sync with structured edges. The verb
    phrase comes from the edge label when available; ``related`` slugs without
    an edge still produce a plain wikilink.
    """
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Edge-derived bullets first (they carry a verb phrase).
    for edge in edges or []:
        target_id = str(edge.get("target", "")).strip()
        label = str(edge.get("label", "")).strip()
        if not target_id or target_id in seen:
            continue
        name = str(id_to_name.get(target_id, target_id.replace("-", " ").title()))
        seen.add(target_id)
        pairs.append((name, label))

    # related slugs without an edge — plain wikilink.
    for slug in related_slugs or []:
        slug = str(slug).strip()
        if not slug:
            continue
        # related entries may be slugs or display names.
        if slug in id_to_name:
            name = str(id_to_name[slug])
            key = slug
        else:
            name = slug
            key = slug.lower().replace(" ", "-")
        if key in seen or name.lower() in {n.lower() for n, _ in pairs}:
            continue
        seen.add(key)
        pairs.append((name, ""))

    return _related_bullets(pairs)
