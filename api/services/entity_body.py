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

from api.services import fact_policy, summary_policy

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
    """Top-level bullet items, including their indented continuations."""
    lines: list[str] = []
    indent = 0
    for raw in (content or "").splitlines():
        stripped = raw.strip()
        depth = len(raw) - len(raw.lstrip())
        if lines and depth > indent:
            lines[-1] += '\n' + raw
        elif stripped.startswith(("- ", "* ")):
            indent = depth
            lines.append(stripped[2:].strip())
        elif lines and not stripped:
            lines[-1] += '\n'
    lines = [line.rstrip() for line in lines]
    return lines


def has_human_prose(frontmatter: dict, sections: dict[str, str]) -> bool:
    return bool(frontmatter.get('human_edited')) or any(
        title and title not in CANONICAL_SECTIONS for title in sections)


def retain_orientation(sections: dict[str, str], text: str, *, names=()) -> int:
    """Keep what a displaced orientation says that the page does not, as Key Facts.

    An orientation that lost the Summary (an incoming one beside a usable
    Summary, a replaced or overlong one) is split into sentences; a sentence the
    Summary or a Key Fact already restates (`fact_policy.restates`) is dropped,
    every other one becomes a Key Fact, so its words survive once. Re-introducing
    the thing is what a Summary is for, once; History is a timeline, not a drawer
    for orientations (the "Undated background" bullets this replaced repeated Key
    Facts word for word). Never assigns a date. Returns the sentences added."""
    text = (text or '').strip()
    if not text:
        return 0
    kept = _summary_sentences(sections.get('Summary', '')) + _bullet_lines(sections.get('Key Facts', ''))
    keys = {_normalize_fact(k) for k in kept}
    fresh = []
    for paragraph in re.split(r'\n\s*\n', text):
        for sentence in fact_policy.sentences(paragraph):
            if _normalize_fact(sentence) in keys or _said(sentence, kept, names):
                continue
            fresh.append(sentence)
            kept.append(sentence)
            keys.add(_normalize_fact(sentence))
    if fresh:
        sections['Key Facts'] = _merge_facts(sections.get('Key Facts', ''), fresh)
    return len(fresh)


def _said(sentence: str, kept: list[str], names=()) -> bool:
    """A displaced orientation sentence the page already says, word for word, in one item
    (`fact_policy.restates`). Anything less is kept: a duplicate is cheaper than a lost fact."""
    return fact_policy.covered(sentence, kept)


def adds_orientation(body: str, text: str, *, names=()) -> bool:
    """True when ``text`` (an incoming summary) has a sentence the page's Summary and
    Key Facts do not already say (:func:`_said`) — used to decide whether a re-read
    of a conversation still needs a model's merge (`conflict_resolver`)."""
    from api.services.claims import strip_claims_block

    sections = parse_sections(strip_claims_block(body or ''))
    kept = _summary_sentences(sections.get('Summary', '')) + _bullet_lines(sections.get('Key Facts', ''))
    keys = {_normalize_fact(k) for k in kept}
    return any(_normalize_fact(sentence) not in keys and not _said(sentence, kept, names)
               for sentence in _summary_sentences(text))


def _summary_sentences(summary: str) -> list[str]:
    return [s for p in re.split(r'\n\s*\n', summary or '') for s in fact_policy.sentences(p)]


def lead(text: str, *, names=()) -> tuple[str, str]:
    """``(summary, rest)``: the orientation a machine Summary keeps, and what it moves out.

    Whole sentences of the first paragraph, in order, while they fit the
    600-character budget (`summary_policy`), skipping a sentence an earlier kept
    one restates and every second (re-)introduction of the thing ("X is a CI
    platform. … X is a CI/CD automation platform."): several conversations'
    orientations glued together keep the first. Never clips a sentence;
    ``summary`` is empty when the first sentence alone is over budget. ``rest``
    is every sentence not kept and every later paragraph, for
    :func:`retain_orientation`."""
    text = (text or '').strip()
    if not text:
        return '', ''
    paragraphs = [p for p in re.split(r'\n\s*\n', text) if p.strip()]
    kept: list[str] = []
    rest: list[str] = []
    introduced, full = False, False
    for sentence in fact_policy.sentences(paragraphs[0]):
        intro = fact_policy.introduces(sentence, names)
        if (full or (intro and introduced) or fact_policy.covered(sentence, kept)
                or _normalize_fact(sentence) in {_normalize_fact(k) for k in kept}):
            rest.append(sentence)
            continue
        if len(' '.join(kept + [sentence])) > summary_policy.MAX_CHARS:
            full = True  # the Summary is a prefix: nothing after an over-budget sentence
            rest.append(sentence)
            continue
        kept.append(sentence)
        introduced = introduced or intro
    remainder = '\n\n'.join(part for part in [' '.join(rest)] + paragraphs[1:] if part.strip())
    return ' '.join(kept), remainder


def bound_summary(sections: dict[str, str], *, previous: str = '', name: str = '',
                  entity_type: str = '', names=()) -> dict[str, str]:
    """Bound machine prose: one orientation in Summary, what it displaces kept as Key Facts.

    The Summary keeps its leading whole sentences that fit the budget, once each
    (:func:`lead`); the rest goes through :func:`retain_orientation`. With no
    sentence to keep: a usable ``previous`` Summary, else the identity fallback.
    Human Summaries never come here (callers check)."""
    sections = dict(sections)
    names = [n for n in (name, *names) if n]
    lead_text = sections.pop('', '').strip()
    candidate = sections.get('Summary', '').strip()
    candidate = '\n\n'.join(part for part in (lead_text, candidate) if part)
    if not candidate:
        return sections
    kept, rest = lead(candidate, names=names)
    if not kept:
        sections['Summary'] = previous if summary_policy.usable(previous) else summary_policy.fallback(
            name=name, entity_type=entity_type)
        rest = candidate
    elif kept == ' '.join(candidate.split()) and summary_policy.usable(candidate):
        sections['Summary'] = candidate  # nothing moved: keep the exact text (and its G118 guard)
        rest = ''
    else:
        sections['Summary'] = kept
    retain_orientation(sections, rest, names=names)
    return sections


def _normalize_fact(text: str) -> str:
    """Normalized key for dedup: lowercased, wikilink-unwrapped, despaced."""
    text = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", text or "")
    text = re.sub(r"[`*_]", "", text)
    return " ".join(text.lower().split())


def _bullets_block(items: list[str]) -> str:
    # A carried orientation can have several lines/paragraphs. Indent fresh
    # continuation lines so the next union/read treats the complete text as
    # one item. Existing indentation is stable across repeated merges.
    blocks = []
    for item in items:
        if not item.strip():
            continue
        lines = item.split('\n')
        lines[1:] = [line if not line or line[:1].isspace() else '  ' + line for line in lines[1:]]
        blocks.append('- ' + '\n'.join(lines))
    return '\n'.join(blocks)


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
    """Existing fact bullets unchanged, then every new fact nothing else restates.

    Exact (normalized) duplicates are skipped as always; a new fact an existing
    one restates, or a more specific new one restates, is folded away
    (`fact_policy.union`). An existing bullet is never removed or reworded."""
    items = _bullet_lines(existing)
    seen = {_normalize_fact(it) for it in items}
    fresh: list[str] = []
    for fact in new_facts or []:
        fact = str(fact).strip()
        key = _normalize_fact(fact)
        if not fact or key in seen:
            continue
        seen.add(key)
        fresh.append(fact)
    items, _ = fact_policy.union(items, fresh)
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
    *, name: str = '', entity_type: str = '',
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

    if summary:
        # A fact the Summary already says is not repeated under it ("Do NOT re-narrate the summary").
        said = _summary_sentences(summary)
        facts = [item for item in _bullet_lines(sections.get('Key Facts', ''))
                 if _normalize_fact(item) != _normalize_fact(summary) and not fact_policy.covered(item, said)]
        if facts:
            sections['Key Facts'] = _bullets_block(facts)
        else:
            sections.pop('Key Facts', None)
        sections = bound_summary(sections, name=name, entity_type=entity_type)
    return render_sections(sections)


def merge_sections_fallback(existing: dict[str, str], new_fields: dict, *,
                            human_edited: bool = False) -> dict[str, str]:
    """Non-LLM section-aware merge used when synthesis is unavailable.

    Union Key Facts / Links / Open Questions (a new fact something on the page
    already restates is folded away, `fact_policy`), append+dedupe History, keep
    the existing usable Summary. A distinct orientation is never concatenated:
    what it says that the page does not becomes Key Facts
    (:func:`retain_orientation`). Human Summary is exempt and exact.

    ``new_fields`` keys (all optional): ``summary``, ``key_facts``,
    ``history_entries``, ``links``, ``open_questions``.
    """
    merged = dict(existing or {})

    new_summary = str(new_fields.get("summary", "") or "").strip()
    old_summary = merged.get('Summary', '')
    names = [str(new_fields.get('name') or '')]
    if not human_edited:
        if summary_policy.usable(old_summary):
            merged['Summary'] = old_summary
        elif summary_policy.usable(new_summary):
            merged['Summary'] = new_summary
        elif old_summary or new_summary:
            merged['Summary'] = (lead(old_summary, names=names)[0] or lead(new_summary, names=names)[0]
                                 or summary_policy.fallback(name=names[0], entity_type=str(new_fields.get('type') or '')))
    new_facts = list(new_fields.get("key_facts", []) or [])
    # A displaced orientation's sentences join the incoming facts, so one union
    # keeps whichever spelling is the more specific (`retain_orientation`'s rule).
    for text, at_end in ((old_summary, False), (new_summary, True)):
        if text and _normalize_fact(text) != _normalize_fact(merged.get('Summary', '')):
            displaced = [sentence for paragraph in re.split(r'\n\s*\n', text)
                         for sentence in fact_policy.sentences(paragraph)]
            new_facts = new_facts + displaced if at_end else displaced + new_facts
    # Existing prose (including human facts) remains untouched. Only suppress
    # an incoming fact the retained orientation already says; an exact copy's
    # source row can follow the Summary through the writer's selected-input mapping.
    said = _summary_sentences(merged.get('Summary', ''))
    new_facts = [item for item in new_facts
                 if _normalize_fact(str(item)) != _normalize_fact(merged.get('Summary', ''))
                 and not fact_policy.covered(str(item), said)]
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


def adopt_rewrite(original: dict[str, str], rewritten: dict[str, str]) -> dict[str, str]:
    """What a whole-body rewrite (legacy synthesis) may change: the Summary, and
    History lines it adds that no line already says. Every other section stays
    as ``original`` had it, item for item, so a fact the rewrite left out or
    rephrased is neither lost nor doubled; the extraction's own items are merged
    after (:func:`merge_sections_fallback`)."""
    merged = dict(original)
    merged.pop('', None)
    summary = '\n\n'.join(part for part in ((rewritten.get('') or '').strip(),
                                              (rewritten.get('Summary') or '').strip()) if part)
    if summary:
        merged['Summary'] = summary
    lines = _bullet_lines(merged.get('History', ''))
    for line in _bullet_lines(rewritten.get('History', '')):
        if _normalize_fact(line) not in {_normalize_fact(x) for x in lines} and not fact_policy.covered(line, lines):
            lines.append(line)
    if lines:
        merged['History'] = _bullets_block(sorted(lines, key=_history_sort_key))
    return merged


def merge_sections_human_safe(
    existing: dict[str, str], new_fields: dict, *, human_edited: bool
) -> dict[str, str]:
    """Section-aware merge that NEVER rewrites or removes human prose (rule 3c).

    On an agent-only page (``human_edited=False``) this is the normal
    :func:`merge_sections_fallback` (union Key Facts / Links / Open Questions,
    bounded Summary, dedupe History).

    On a **human-edited** page (``human_edited=True`` — the frontmatter carries
    ``human_edited: true``, or the page has non-canonical hand-added headings) the
    merge is **additive only**: every existing section (canonical or not) is
    preserved, with Summary exact. What an incoming orientation adds becomes Key
    Facts; it may never replace or extend the person's Summary.
    This is the prose-level mirror of the Stage-3 ``COEXIST_FLAG`` rule (an agent
    may not regenerate-away human prose any more than it may close a human claim).
    """
    if not human_edited:
        return merge_sections_fallback(existing, new_fields)

    existing = dict(existing or {})
    # Snapshot every human-authored (non-canonical) section so the additive merge
    # below cannot touch it.
    human_sections = {
        title: content
        for title, content in existing.items()
        if title not in CANONICAL_SECTIONS and title != ""
    }

    merged = merge_sections_fallback(existing, new_fields, human_edited=True)

    # Re-assert the human sections verbatim — they are never rewritten.
    for title, content in human_sections.items():
        merged[title] = content
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


# Priority order for recall summaries: fact-bearing sections first. Summary +
# Key Facts are ALWAYS included in full (they hold the answer); the rest fill
# the remaining budget in this order.
_RECALL_PRIORITY = ["Summary", "Key Facts", "History", "Links", "Related", "Open Questions"]


def summarize_for_recall(body: str, *, max_chars: int = 3200) -> str:
    """Section-aware truncation that always preserves Summary + Key Facts.

    Byte-offset truncation can cut Key Facts (where specific figures live). This
    keeps Summary + Key Facts whole, then appends further canonical sections in
    priority order until the char budget is reached.
    """
    from api.services.claims import strip_claims_block
    sections = parse_sections(strip_claims_block(body))
    lead = sections.get("", "").strip()
    chosen: list[str] = []
    used = 0
    # Always-include tier, whole:
    for title in ("Summary", "Key Facts"):
        content = sections.get(title, "").strip()
        if content:
            block = f"## {title}\n{content}"
            chosen.append(block)
            used += len(block)
    # Fill remaining budget:
    for title in _RECALL_PRIORITY:
        if title in ("Summary", "Key Facts"):
            continue
        content = sections.get(title, "").strip()
        if not content:
            continue
        block = f"## {title}\n{content}"
        if used + len(block) > max_chars and chosen:
            break
        chosen.append(block)
        used += len(block)
    if not chosen:  # legacy flat body (no H2s)
        return (lead or body).strip()[:max_chars]
    return "\n\n".join(chosen)


_TERMINAL = (".", "!", "?", "…")


def summary_line(text: str, *, predicate: str = "") -> str:
    """One claim's text as a Summary sentence — deterministic, no LLM (F1 R-FX9).

    ``agentic_write`` used to open every page it created with ``<name> —
    created via agentic write.``; the owner's pages then showed nothing but that
    line and, under it, the claims fence as raw YAML. The claim being written is
    the only thing Cicada knows about a new page, so it becomes the first line:
    whitespace collapsed, a hyphenated predicate slug read as words when it
    appears as a whole token (``depends-on`` → ``depends on``; the mechanical
    fallback text is ``<subject> <predicate> <object>``), the first letter
    capitalised only when the first word is all lowercase (``iOS`` stays), and a
    period added when the text has no terminal punctuation."""
    line = " ".join((text or "").split())
    if not line:
        return ""
    if predicate and "-" in predicate:
        line = re.sub(rf"(?<![\w-]){re.escape(predicate)}(?![\w-])",
                      predicate.replace("-", " "), line, count=1)
    first = line.split(" ", 1)[0]
    if first[:1].islower() and first == first.lower():
        line = line[:1].upper() + line[1:]
    if not line.endswith(_TERMINAL):
        line += "."
    return line


def summary_from_claims(claims, *, limit: int = 3, max_chars: int = 240) -> str:
    """The first ``limit`` open claims as sentences, in page order, deduplicated,
    capped at ``max_chars`` on a word boundary (F1 R-FX10). Closed and superseded
    claims are not current beliefs, so they never write the Summary. Empty when
    nothing is open. Duck-typed on ``text`` / ``predicate`` / ``valid_to`` /
    ``superseded_by`` so this module keeps importing nothing from ``claims`` at
    module level."""
    sentences: list[str] = []
    seen: set[str] = set()
    for claim in claims or []:
        if getattr(claim, "valid_to", None) or getattr(claim, "superseded_by", None):
            continue
        if getattr(claim, "predicate", "") in ("happened", "milestone"):
            # G141: an open thread or plan is progress, not what the page IS —
            # a Summary never reads "Bob is connecting…".
            continue
        line = summary_line(getattr(claim, "text", ""), predicate=getattr(claim, "predicate", ""))
        if not line or line.lower() in seen:
            continue
        seen.add(line.lower())
        sentences.append(line)
        if len(sentences) == limit:
            break
    out = " ".join(sentences)
    if len(out) <= max_chars:
        return out
    return out[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def sections_to_fields(sections: dict) -> dict:
    """Convert a ``{title: markdown}`` sections dict into the STRUCTURED
    ``new_fields`` shape that :func:`merge_sections_fallback` /
    :func:`merge_sections_human_safe` consume (``summary`` str + ``key_facts`` /
    ``history_entries`` / ``links`` / ``open_questions`` bullet lists). Bullets
    are the ``- `` lines of each list section; non-canonical sections are ignored
    here (callers preserve those separately). Passing a raw sections dict to the
    merge helpers merges nothing — this adapter is the bridge.
    """
    def _bullets(s: str) -> list[str]:
        return [ln.strip()[2:].strip()
                for ln in (s or "").splitlines() if ln.strip().startswith("- ")]

    def _history_dicts(s: str) -> list[dict]:
        out = []
        for ln in (s or "").splitlines():
            ln = ln.strip()
            if not ln.startswith("- "):
                continue
            item = ln[2:].strip()
            if ": " in item:
                date, _, event = item.partition(": ")
                out.append({"date": date.strip(), "event": event.strip()})
            else:
                out.append({"date": "", "event": item})
        return out

    return {
        "summary": (sections.get("Summary", "") or "").strip(),
        "key_facts": _bullets(sections.get("Key Facts", "")),
        "history_entries": _history_dicts(sections.get("History", "")),
        "links": _bullets(sections.get("Links", "")),
        "open_questions": _bullets(sections.get("Open Questions", "")),
    }
