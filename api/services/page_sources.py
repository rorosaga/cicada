"""Where a page's knowledge comes from, and how fresh it is — one read for the entity card (owner 2026-10-14, G61).

Three kinds of origin already live in three places; this module only reads them together:

* **Sources** (G61 ``sources:``) — where to look a fact up. Each comes back with the current beliefs it backs: the
  page's own claims of the source's predicate (a ``website`` entry backs the page's ``website`` claims and, as the
  official-site role, the page as a whole; an entry with no predicate backs the page as a whole).
* **Links** — the page's ``## Links`` lines that are not sources, each with the conversation that named it when the
  page's section-provenance record (G118 sections) says which.
* **Conversations** — grouped exactly as ``/provenance`` groups them (``provenance.conversation_groups``) and tallied by
  app: how many, the beliefs and the page's passages each app's conversations back, the newest time said.

Rails: engine-free and network-free (a site's icon is the card's own ask of the page's icon route, never this module's);
writes nothing; a source check never settles, reorders or changes a belief — this is a view of what is stored. Bounded
for an owner-sized page: at most :data:`MAX_FACTS` beliefs per source and :data:`MAX_LINKS` links travel, with honest
totals, so the card never reads the claims list to draw the section.
"""

from __future__ import annotations

import re
from pathlib import Path

from api.models.schemas import (
    EvidenceModel,
    OverviewApp,
    OverviewConversations,
    OverviewLink,
    OverviewLinkOrigin,
    OverviewSource,
    SourceFact,
    SourcesOverview,
    SourceUpdate,
)
from api.services import (
    episode_ids,
    evidence,
    fact_sources,
    link_views,
    markdown_parser,
    provenance,
    reading_hosts,
    section_provenance,
)
from api.services.claims import is_current, is_event, is_record, parse_claims

#: The beliefs one source row lists; ``factCount`` says how many it backs in all.
MAX_FACTS = 4
#: The ``## Links`` lines served; ``linksTotal`` says how many the page has.
MAX_LINKS = 12
#: Bumped when the payload changes for the same files (the route's ETag ``extra``).
SHAPE = "page-sources-2"

# A titled link (`[T](url "bookmark")`, `link_views`) keeps its title; a bare URL is group 3.
_LINK = re.compile(r"\[([^\]]*)\]" + link_views.LINK_TAIL + r"|(https?://[^\s<>\")\]]+)")
_NOTE_LEAD = re.compile(r"^[\s\-–—:·|]+")


def _opt(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _same_url(a: str, b: str) -> bool:
    return a.strip().rstrip("/").lower() == b.strip().rstrip("/").lower()


def _site(url: str) -> str | None:
    try:
        site = reading_hosts.site_of(url)
    except Exception:
        return None
    return site or None


def _parse_link(text: str) -> tuple[str, str, str | None] | None:
    """``(url, title, note)`` from one ``## Links`` item — ``[Title](url) — note`` or a bare URL; ``None`` when the
    line holds no web link."""
    m = _LINK.search(text or "")
    if not m:
        return None
    title = (m.group(1) or "").strip()
    # A link's own URL is whole (a balanced ``)`` is part of it); only a bare URL sheds the sentence's punctuation.
    url = m.group(2) or link_views.trim_bare(m.group(3) or "")
    rest = (text[m.end():] or "").strip()
    note = _NOTE_LEAD.sub("", rest).strip() or None
    return url, title, note


def _page_name(memory_path: Path, entity_id: str) -> str | None:
    try:
        name = markdown_parser.parse(Path(memory_path) / "entities" / f"{entity_id}.md").frontmatter.get("name")
    except Exception:
        return None
    return _opt(name)


def _scope(source: dict) -> str:
    predicate = str(source.get("predicate") or "").strip().lower()
    if not predicate:
        return "page"
    return "site" if predicate == fact_sources.WEBSITE else "fact"


def _checked_at(source: dict) -> str | None:
    stamps = [str(block.get("at")) for key in ("verified", "checked", "refresh")
              if isinstance(block := source.get(key), dict) and block.get("at")]
    return max(stamps, key=episode_ids.timestamp_sort_key) if stamps else None


def _recency(claim) -> str:
    return str(claim.recorded_at or claim.valid_from or "")


#: The re-check updates the card lists (G61, ruling 26).
MAX_UPDATES = 8


def _updates(memory_path: Path, claims: list) -> list[SourceUpdate]:
    """What tracked sources changed on this page, newest first — read from the claims a re-check wrote (``origin:
    source-refresh``) and the beliefs each closed; the site from the re-check's own episode."""
    from api.services import bank_index, source_refresh

    by_successor = {c.superseded_by: c for c in claims if c.superseded_by}
    rows = []
    for c in claims:
        if (c.origin or "") != source_refresh.ORIGIN:
            continue
        site = None
        for ep in c.source_episodes[:1]:
            f = bank_index.file(Path(memory_path), "episodes", f"{ep}.md")
            site = str(((f.frontmatter if f else {}) or {}).get("checked_host") or "") or None
        ended = source_refresh.is_ending(c)
        was = by_successor.get(c.id)
        rows.append(SourceUpdate(claim_id=c.id, predicate=c.predicate, value=c.object,
                                 was=was.object if was is not None else None, at=c.valid_from, site=site,
                                 current=is_current(c), ended=ended))
    rows.sort(key=lambda r: (r.at or "", r.claim_id), reverse=True)
    return rows[:MAX_UPDATES]


def overview(memory_path: Path, page: Path) -> SourcesOverview:
    """The card's "Where this comes from" for ``page`` (an existing entity file). Pure read; never raises on a page
    hand-edited into invalid YAML — it reads as an empty page, as ``/provenance`` does."""
    memory_path = Path(memory_path)
    entity_id = page.stem
    try:
        parsed = markdown_parser.parse(page)
    except Exception:
        parsed = markdown_parser.ParsedMarkdown()
    fm = parsed.frontmatter or {}
    body = parsed.body or ""
    all_claims = parse_claims(body)
    current = [c for c in all_claims if is_current(c)]
    # What a source can refresh: current beliefs. A withdrawal record is bookkeeping and a happening or milestone is
    # dated history (G141), neither a fact a source checks — both still count as what a conversation fed the page.
    beliefs = [c for c in current if not is_record(c) and not is_event(c)]
    belief_ids = {c.id for c in beliefs}

    # Beliefs by predicate, newest first — what a source of that predicate backs.
    by_predicate: dict[str, list] = {}
    for claim in beliefs:
        key = (claim.predicate or "").strip().lower()
        if key:
            by_predicate.setdefault(key, []).append(claim)
    for claims in by_predicate.values():
        claims.sort(key=_recency, reverse=True)

    # `## Links`, with the conversation each line's section-provenance record names.
    items = section_provenance.scan(body)
    try:
        matched = section_provenance.matched(fm, body)
    except Exception:
        matched = {}
    link_rows: list[tuple[str, str, str | None, list]] = []
    for item in items.get("links", []):
        parsed_link = _parse_link(item.text)
        if parsed_link is None:
            continue
        url, title, note = parsed_link
        evs = [] if item.ambiguous else matched.get("links", {}).get(item.key, ("", []))[1]
        link_rows.append((url, title, note, evs))

    raw_sources = fact_sources.as_sources(fm.get("sources"))
    sources: list[OverviewSource] = []
    backed: set[str] = set()
    for s in raw_sources:
        row = dict(s)
        row["entity"] = fact_sources.linked_entity(memory_path, s, self_id=entity_id)
        row["effective_access"] = fact_sources.effective_access(s)
        row["trusted"] = fact_sources.trusted(s)
        ref = str(s.get("ref") or "")
        is_url = str(s.get("kind") or fact_sources.infer_kind(ref)) == fact_sources.KIND_URL
        predicate = str(s.get("predicate") or "").strip().lower()
        facts = by_predicate.get(predicate, []) if predicate else []
        backed.update(c.id for c in facts)
        title = next((t for u, t, _, _ in link_rows if t and is_url and _same_url(u, ref)), None)
        if title is None and is_url and row["entity"]:
            # The page this source is linked to is the saved copy of it: its name is the title read when it was
            # saved — already in the bank, nothing is fetched.
            title = _page_name(memory_path, row["entity"])
        known = set(OverviewSource.model_fields)
        sources.append(OverviewSource(
            **{k: v for k, v in row.items() if k in known},
            site=_site(ref) if is_url else None,
            title=title,
            scope=_scope(s),
            facts=[SourceFact(claim_id=c.id, text=c.text, predicate=c.predicate, context=c.context or "general")
                   for c in facts[:MAX_FACTS]],
            fact_count=len(facts),
        ))

    docs = provenance._Episodes(memory_path)

    def origin_of(evs) -> OverviewLinkOrigin | None:
        ev = next((e for e in evs if evidence.is_episode_id(e.episode)), None)
        if ev is None:
            return None
        indexed = docs.meta(ev.episode)
        efm = indexed.frontmatter if indexed is not None else {}
        return OverviewLinkOrigin(
            episode=ev.episode, title=str(efm.get("title") or ""),
            harness=_opt(efm.get("harness")), origin=_opt(efm.get("origin")) or _opt(efm.get("source")),
            said=provenance._said(str(efm.get("timestamp") or ""), ev.episode),
            available=indexed is not None, evidence=EvidenceModel(**ev.to_dict()))

    source_urls = [str(s.get("ref") or "") for s in raw_sources]
    links_all = [r for r in link_rows if not any(_same_url(r[0], ref) for ref in source_urls)]
    links = [OverviewLink(url=url, title=title, site=_site(url), note=note, came_from=origin_of(evs))
             for url, title, note, evs in links_all[:MAX_LINKS]]

    # Conversations, grouped as `/provenance` groups them, tallied by app.
    cited = {c.id: provenance.cited_episodes(c) for c in current}
    fed_by = [str(e) for e in (fm.get("source_episodes") or []) if evidence.is_episode_id(str(e))]
    ordered = list(dict.fromkeys(fed_by + sorted({e for eps in cited.values() for e in eps})))
    # Inverted once, episode -> what it backs, so the tally is O(beliefs + episodes + passages), never
    # conversations x beliefs (an owner-sized page: ~6k beliefs over ~3k conversations, review B1).
    beliefs_by_episode: dict[str, set[str]] = {}
    for cid, eps in cited.items():
        if cid in belief_ids:
            for ep in eps:
                beliefs_by_episode.setdefault(ep, set()).add(cid)
    passages_by_episode: dict[str, set[tuple[str, str]]] = {}
    for section, records in matched.items():
        if section == "links":
            continue
        for key, (_, evs) in records.items():
            for e in evs:
                if evidence.is_episode_id(e.episode):
                    passages_by_episode.setdefault(e.episode, set()).add((section, key))

    apps: dict[str, dict] = {}
    first_said = last_said = None
    groups = provenance.conversation_groups(docs, ordered)
    for group in groups:
        members = {e[1] for e in group["episodes"]}
        efms = [e[2] for e in group["episodes"]]
        last = group["episodes"][-1][2]
        harness = next((h for f in efms if (h := _opt(f.get("harness")))), None)
        origin = _opt(last.get("origin")) or _opt(last.get("source"))
        app = apps.setdefault(harness or origin or "", {
            "harness": harness, "origin": origin, "source": _opt(last.get("source")),
            "conversations": 0, "facts": set(), "passages": set(), "last_said": None})
        app["conversations"] += 1
        for ep in members:
            app["facts"].update(beliefs_by_episode.get(ep, ()))
            app["passages"].update(passages_by_episode.get(ep, ()))
        if group["said"]:
            first, newest = group["said"]
            if app["last_said"] is None or episode_ids.timestamp_sort_key(newest) > \
                    episode_ids.timestamp_sort_key(app["last_said"]):
                app["last_said"] = newest
            if first_said is None or episode_ids.timestamp_sort_key(first) < episode_ids.timestamp_sort_key(first_said):
                first_said = first
            if last_said is None or episode_ids.timestamp_sort_key(newest) > episode_ids.timestamp_sort_key(last_said):
                last_said = newest
    app_rows = [OverviewApp(harness=a["harness"], origin=a["origin"], source=a["source"],
                            conversations=a["conversations"], facts=len(a["facts"]), passages=len(a["passages"]),
                            last_said=a["last_said"]) for a in apps.values()]
    # Most conversations first; between equals, the app said in most recently (an undated one last).
    app_rows.sort(key=lambda a: episode_ids.timestamp_sort_key(a.last_said), reverse=True)
    app_rows.sort(key=lambda a: -a.conversations)

    checked = [stamp for s in raw_sources if (stamp := _checked_at(s))]
    return SourcesOverview(
        entity_id=entity_id,
        entity_type=str(fm.get("type") or ""),
        sources=sources,
        links=links,
        links_total=len(links_all),
        conversations=OverviewConversations(total=len(groups), first_said=first_said, last_said=last_said,
                                            apps=app_rows),
        facts_total=len(beliefs),
        facts_with_source=len(backed),
        last_checked=max(checked, key=episode_ids.timestamp_sort_key) if checked else None,
        updates=_updates(memory_path, all_claims),
    )

