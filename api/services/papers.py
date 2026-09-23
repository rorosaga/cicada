"""Papers in a watched folder, parsed with no LLM (G133 · R-F3 · G121).

A folder's reference list — ``- [Title](https://arxiv.org/abs/<id>) — why``
bullets under H2 sections — is the cheapest possible input for a paper page:
every entry already has a title, a canonical id and a one-line reason in the
person's (or their agent's) words. So this module never asks a model:

* **Pages.** A paper is a ``media`` page with ``media.kind: paper`` (the G2
  closure: no new entity type) and a ``paper:`` block, evergreen, keyed by the
  normalised arXiv id or the lowercased DOI. Both canonical URLs sit in
  ``url_index.json`` — the second as an ``alias_of`` entry — so a DOI link and
  an arXiv link never fork one paper, and a paper already saved some other way
  is upgraded in place, never duplicated (R-LS14).
* **Why it matters to you** (G121, anchored on the owner). Personal-tier
  claims, each with a G118 span into the folder file's episode:
  ``saved-because`` (the bullet's annotation), ``cited-in`` (the folder's
  project), ``about`` (the section's concept, when one exists by name —
  R-LS16). Whose words they are follows the file's authorship (R-F2): the
  person's own (``user_stated``, observer = owner) or an agent's sweep
  (``agent_reflected``, observer ``agent``, ``assistant`` spans).
* **World tier** comes later and separately: ``paper_metadata`` stores the
  abstract as a dated cache (R-LS19).

Claims are written by :func:`apply_claims`, not ``agentic_write.write_claim``
(R-LS15): a references file re-parses hundreds of papers per save, and one parse
+ one write per page — deterministic ids, this file's spans replaced rather
than appended, claims the file no longer supports closed with ``valid_to``
(never deleted) — is what keeps a watched folder cheap and its history honest.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from api.services import (
    bank_index,
    decay_policy,
    episode_ids,
    episode_staging,
    evidence,
    folder_source,
    markdown_parser,
    media_ingestor,
)
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims
from api.services.id_utils import sanitize_id

KIND = "paper"
ORIGIN = folder_source.ORIGIN
CITATIONS_FILENAME = "folder_citations.json"
WHY_PREDICATES = ("saved-because", "cited-in", "about")
_CONCEPT_TYPES = frozenset({"concept", "tool", "skill", "project"})
_CONFIDENCE = {
    "user": {"saved-because": 0.9, "cited-in": 0.8, "about": 0.6},
    "agent": {"saved-because": 0.6, "cited-in": 0.5, "about": 0.4},
}

_NEW_ID = r"\d{4}\.\d{4,5}"
_OLD_ID = r"[a-z][a-z.\-]*/\d{7}"
_ID = rf"(?P<id>{_NEW_ID}|{_OLD_ID})(?:v\d+)?"
ARXIV_URL_RE = re.compile(rf"https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf|html)/{_ID}(?:\.pdf)?", re.IGNORECASE)
ARXIV_TAG_RE = re.compile(rf"\barxiv:\s?{_ID}", re.IGNORECASE)
_DOI = r"(?P<doi>10\.\d{4,9}/[^\s\"'<>\]]+)"
DOI_URL_RE = re.compile(rf"https?://(?:dx\.)?doi\.org/{_DOI}", re.IGNORECASE)
DOI_TAG_RE = re.compile(rf"\bdoi:\s?{_DOI}", re.IGNORECASE)
BULLET_RE = re.compile(
    r"^[ \t]*[-*+][ \t]+\[(?P<title>[^\]\n]+)\]\((?P<url>[^)\s]+)\)[ \t]*"
    r"(?:(?:—|–|--|-|:)[ \t]*(?P<note>\S.*?))?[ \t]*$")
H2_RE = re.compile(r"^##[ \t]+(?P<h>.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(`{3}|~{3})")
# arXiv mints DOIs of the form 10.48550/arXiv.<id>; those ARE the arXiv paper.
_ARXIV_DOI_PREFIX = "10.48550/arxiv."
_TRAILING = ".,;:)]}>'\""


def normalise_arxiv(raw: str) -> str:
    return re.sub(r"v\d+$", "", (raw or "").strip().lower())


def normalise_doi(raw: str) -> str:
    return (raw or "").strip().rstrip(_TRAILING).lower()


@dataclass(frozen=True)
class PaperKey:
    arxiv_id: str | None = None
    doi: str | None = None

    @property
    def abs_url(self) -> str | None:
        return f"https://arxiv.org/abs/{self.arxiv_id}" if self.arxiv_id else None

    @property
    def doi_url(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None

    @property
    def canonical_url(self) -> str:
        return self.abs_url or self.doi_url or ""

    @property
    def entity_id(self) -> str:
        """Id-based, so identity never depends on which title arrived first (R-LS14)."""
        if self.arxiv_id:
            return "media-arxiv-" + re.sub(r"[^a-z0-9]+", "-", self.arxiv_id).strip("-")
        return "media-doi-" + hashlib.sha1((self.doi or "").encode()).hexdigest()[:10]


def key_for_doi(raw: str) -> PaperKey:
    doi = normalise_doi(raw)
    if doi.startswith(_ARXIV_DOI_PREFIX):
        return PaperKey(arxiv_id=normalise_arxiv(doi[len(_ARXIV_DOI_PREFIX):]))
    return PaperKey(doi=doi)


def key_from_url(url: str) -> PaperKey | None:
    m = ARXIV_URL_RE.search(url or "")
    if m:
        return PaperKey(arxiv_id=normalise_arxiv(m.group("id")))
    m = DOI_URL_RE.search(url or "")
    if m:
        return key_for_doi(m.group("doi"))
    return None


def never_scraped(url: str) -> bool:
    """A paper link, or any arxiv.org page: no page or PDF fetch, ever.

    L final review (finding 4): the rail says arxiv.org pages and PDFs are never
    fetched (spec R-F3, "never scrape arxiv.org"), but only pages ``is_paper``
    had already marked were skipped — an arXiv or DOI link arriving as an
    ordinary bookmark, a ``cicada_save_url`` or a Telegram save was still
    OpenGraph-fetched at save time and again by the enrichment backfill, back to
    back across a bookmark import, ignoring arXiv's crawl-delay. Details for a
    paper come only from ``paper_metadata``'s two APIs. Shared by
    ``media_ingestor.enrich`` and ``link_enrichment._excluded_media`` so the save
    path and the Sleep-time passes cannot disagree."""
    if key_from_url(url) is not None:
        return True
    host = (urlparse(url or "").hostname or "").lower()
    return host == "arxiv.org" or host.endswith(".arxiv.org")


@dataclass
class Citation:
    key: PaperKey
    kind: str  # "bullet" | "mention"
    line_start: int
    line_end: int
    quote: str  # the words a cited-in span points at
    title: str | None = None
    note: str | None = None
    section: str | None = None
    heading_start: int | None = None
    heading_end: int | None = None


def parse(text: str) -> list[Citation]:
    """Every paper a document cites, with offsets into ``text`` — which is the
    stored episode body, so the offsets are evidence offsets. Reference bullets
    carry a title and the annotation; any other arXiv/DOI URL or ``arXiv:`` /
    ``doi:`` tag is a bare mention. Code fences are skipped."""
    out: list[Citation] = []
    section: str | None = None
    h_start = h_end = None
    in_fence = False
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        start, end = offset, offset + len(line)
        offset += len(raw)
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = H2_RE.match(line)
        if h:
            section = h.group("h").strip()
            h_start, h_end = start + h.start("h"), start + h.end("h")
            continue
        b = BULLET_RE.match(line)
        if b:
            key = key_from_url(b.group("url"))
            if key is not None:
                title = b.group("title").strip()
                out.append(Citation(key=key, kind="bullet", line_start=start, line_end=end, quote=title,
                                    title=title, note=(b.group("note") or "").strip() or None,
                                    section=section, heading_start=h_start, heading_end=h_end))
                continue
        seen: set[PaperKey] = set()
        for rx, is_doi in ((ARXIV_URL_RE, False), (ARXIV_TAG_RE, False), (DOI_URL_RE, True), (DOI_TAG_RE, True)):
            for m in rx.finditer(line):
                key = key_for_doi(m.group("doi")) if is_doi else PaperKey(arxiv_id=normalise_arxiv(m.group("id")))
                if key in seen:
                    continue
                seen.add(key)
                out.append(Citation(key=key, kind="mention", line_start=start, line_end=end,
                                    quote=line.strip()[: evidence.MAX_QUOTE_CHARS], section=section,
                                    heading_start=h_start, heading_end=h_end))
    return out


def count_papers(texts: list[str]) -> int:
    return len({c.key for t in texts for c in parse(t)})


def is_paper(fm: dict) -> bool:
    media = fm.get("media") if isinstance(fm, dict) else None
    return isinstance(media, dict) and media.get("kind") == KIND


def page_path(memory_path: Path, entity_id: str) -> Path:
    return Path(memory_path) / "entities" / f"{entity_id}.md"


# --- Pages ------------------------------------------------------------------


def _known_papers(idx: dict) -> dict[PaperKey, str]:
    """PaperKey -> media entity id for every saved URL that names a paper — a
    bookmark of ``arxiv.org/pdf/<id>v2`` included (R-LS14)."""
    out: dict[PaperKey, str] = {}
    for entry in idx.values():
        if not isinstance(entry, dict):
            continue
        key = key_from_url(str(entry.get("url") or ""))
        eid = str(entry.get("media_entity_id") or "")
        if key and eid:
            out.setdefault(key, eid)
    return out


def index_aliases(idx: dict, key: PaperKey, entity_id: str, *, title: str | None,
                  episode_id: str | None = None) -> bool:
    """Both canonical URLs into ``url_index.json`` (R-LS14). The first entry the
    page owns is its Feed row; every other is ``alias_of`` that row, so a DOI
    link and an arXiv link to one paper dedup against each other and still
    render as ONE row."""
    primary = next((h for h, e in idx.items() if isinstance(e, dict)
                    and e.get("media_entity_id") == entity_id and not e.get("alias_of")), None)
    changed = False
    for url in (key.abs_url, key.doi_url):
        if not url:
            continue
        h = media_ingestor.url_hash(url)
        if h in idx:
            continue
        if primary is None:
            idx[h] = {"media_entity_id": entity_id, "episode_id": episode_id or "", "url": url,
                      "title": title or "", "media_type": "url", "kind": KIND, "thumbnail": None,
                      "saved_at": episode_ids.utc_now_iso(), "origin": ORIGIN}
            primary = h
        else:
            idx[h] = {"media_entity_id": entity_id, "url": url, "alias_of": primary, "kind": KIND}
        changed = True
    return changed


def _placeholder(key: PaperKey) -> str:
    return f"arXiv {key.arxiv_id}" if key.arxiv_id else f"DOI {key.doi}"


def _upgrade(path: Path, key: PaperKey, section: str | None, episode_id: str) -> bool:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    before = json.dumps(fm, sort_keys=True, default=str)
    fm["media"] = {**(fm.get("media") or {}), "kind": KIND}
    paper = dict(fm.get("paper") or {})
    if key.arxiv_id and not paper.get("arxiv_id"):
        paper["arxiv_id"] = key.arxiv_id
    if key.doi and not paper.get("doi"):
        paper["doi"] = key.doi
    sections = list(paper.get("sections") or [])
    if section and section not in sections:
        sections.append(section)
    paper["sections"] = sections
    paper.setdefault("title_from", "page")
    fm["paper"] = paper
    fm["tags"] = sorted(set(fm.get("tags") or []) | {KIND} | ({sanitize_id(section)} if section else set()))
    episodes = list(fm.get("source_episodes") or [])
    if episode_id not in episodes:
        episodes.append(episode_id)
    fm["source_episodes"] = episodes
    # A paper page is the arXiv/Crossref APIs' to describe, never a scrape (R-LS19).
    fm["enrichment_attempted"] = True
    if json.dumps(fm, sort_keys=True, default=str) == before:
        return False
    markdown_parser.write(path, fm, parsed.body)
    return True


def ensure_page(memory_path: Path, key: PaperKey, *, title: str | None, section: str | None,
                episode_id: str, idx: dict, known: dict, today: str) -> tuple[str, bool, bool, bool]:
    """``(entity_id, created, page_changed, index_changed)``."""
    entity_id = known.get(key)
    if entity_id is None and page_path(memory_path, key.entity_id).exists():
        entity_id = key.entity_id
    if entity_id is not None and page_path(memory_path, entity_id).exists():
        changed = _upgrade(page_path(memory_path, entity_id), key, section, episode_id)
        return entity_id, False, changed, index_aliases(idx, key, entity_id, title=None, episode_id=episode_id)
    entity_id = key.entity_id
    name = (title or "").strip() or _placeholder(key)
    fm = {
        "name": name, "type": "media", "status": "active", "confidence": 0.8,
        "created": today, "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("media", source="media")),
        "source_episodes": [episode_id],
        "tags": sorted({KIND} | ({sanitize_id(section)} if section else set())),
        "related": [], "version": 1, "origin": ORIGIN,
        "enrichment_attempted": True,
        "media": {"url": key.canonical_url, "media_type": "url", "kind": KIND,
                  "site": "arxiv.org" if key.arxiv_id else "doi.org", "channel": None, "thumbnail": None,
                  "saved_at": episode_ids.utc_now_iso(), "url_hash": media_ingestor.url_hash(key.canonical_url)},
        "paper": {"arxiv_id": key.arxiv_id, "doi": key.doi, "title": None, "authors": [],
                  "published": None, "updated": None, "primary_category": None, "journal_ref": None,
                  "venue": None, "sections": [section] if section else [],
                  "title_from": "bullet" if title else "placeholder"},
        "sources": [{"ref": u, "kind": "url", "added_by": "cicada", "added_at": today}
                    for u in (key.abs_url, key.doi_url) if u],
    }
    path = page_path(memory_path, entity_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, fm, f"## Summary\nSaved paper — {name}.")
    index_aliases(idx, key, entity_id, title=name, episode_id=episode_id)
    return entity_id, True, True, True


# --- Claims (R-LS15) --------------------------------------------------------


def claim_id(*parts: str) -> str:
    return "clm_paper_" + hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:10]


def desired_claims(*, entity_id: str, citations: list[Citation], episode_id: str, text: str,
                   authorship: str, owner: str, folder_id: str, project_id: str | None,
                   project_name: str | None, concept_for, today: str, valid_from: str) -> list[Claim]:
    """What ``episode_id`` says about this paper now, as claims."""
    who = "user" if authorship == "user" else "agent"
    observer = owner if who == "user" else "agent"
    trust = "user_stated" if who == "user" else "agent_reflected"
    kind = "user" if who == "user" else "assistant"
    out: dict[str, Claim] = {}

    def claim(predicate: str, obj: str, *, literal: bool, context: str, text_: str, quote: str,
              window: tuple[int, int]) -> None:
        cid = claim_id(entity_id, predicate, obj, observer, context)
        if cid in out:
            return
        out[cid] = Claim(
            id=cid, text=text_, subject=entity_id, predicate=predicate, object=obj,
            object_kind="literal" if literal else "node", observer=observer, context=context,
            epistemic="explicit", source_trust=trust, confidence=_CONFIDENCE[who][predicate],
            valid_from=valid_from, recorded_at=today, source_episodes=[episode_id],
            authored_by="user" if who == "user" else None, origin=ORIGIN,
            evidence=[evidence.verify(None, episode_id, quote, text=text, window=window, kind_override=kind)],
        )

    for c in citations:
        if c.note:
            section = sanitize_id(c.section) if c.section else "top"
            claim("saved-because", c.note, literal=True, context=f"folder:{folder_id}:{section}",
                  text_=c.note, quote=c.note, window=(c.line_start, c.line_end))
        if project_id:
            claim("cited-in", project_id, literal=False, context="general",
                  text_=f"Cited in {project_name or project_id}.", quote=c.quote,
                  window=(c.line_start, c.line_end))
        concept = concept_for(c.section) if c.section else None
        if concept and c.heading_start is not None:
            claim("about", concept, literal=False, context="general", text_=f"Filed under {c.section}.",
                  quote=c.section, window=(c.heading_start, c.heading_end))
    return list(out.values())


def apply_claims(page: Path, episode_id: str, desired: list[Claim], today: str) -> bool:
    """Make this page's folder claims from ``episode_id`` equal ``desired``.

    A wanted claim that exists gets THIS episode's span replaced (not appended —
    ``claim_reconciler._reinforce`` would stack a stale span per edit) and is
    reopened if it had been closed. A folder claim this episode supported and no
    longer does loses this episode's span; if that was its last span it is
    closed with ``valid_to`` (and ``superseded_by`` its successor in the same
    predicate + context, e.g. an edited annotation). Nothing is deleted."""
    if not page.exists():
        return False
    parsed = markdown_parser.parse(page)
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError as exc:
        logger.error(f"corrupt claims block on {page.name}, paper claims skipped: {exc}")
        return False
    by_id = {c.id: c for c in claims}
    wanted = {c.id for c in desired}
    for new in desired:
        old = by_id.get(new.id)
        if old is None:
            claims.append(new)
            by_id[new.id] = new
            continue
        old.evidence = [e for e in old.evidence if e.episode != episode_id] + list(new.evidence)
        if episode_id not in old.source_episodes:
            old.source_episodes.append(episode_id)
        if old.valid_to:
            old.valid_to = None
            old.superseded_by = None
    for c in claims:
        if c.origin != ORIGIN or c.valid_to or c.id in wanted:
            continue
        if not any(e.episode == episode_id for e in c.evidence):
            continue
        others = [e for e in c.evidence if e.episode != episode_id]
        if others:
            c.evidence = others
            continue
        c.valid_to = today
        c.superseded_by = next((d.id for d in desired
                                if d.predicate == c.predicate and d.context == c.context), None)
    new_body = write_claims(parsed.body, claims)
    if new_body == parsed.body:
        return False
    markdown_parser.write(page, parsed.frontmatter, new_body)
    return True


# --- Removals (R-LS20) ------------------------------------------------------


def propose_removals(memory_path: Path, entity_ids: list[str], folder: dict) -> list[str]:
    """One G129-shaped ``removal`` item per paper the folder created that no file
    cites any more. A paper saved some other way first (``origin`` is not
    ``folder``) is never proposed; a pending item is never duplicated."""
    from api.services import inbox_generator, inbox_service

    inbox_dir = Path(memory_path) / "inbox"
    label = str(folder.get("label") or "a folder")
    written: list[str] = []
    next_num: int | None = None
    for eid in entity_ids:
        path = page_path(memory_path, eid)
        if not path.exists():
            continue
        fm = markdown_parser.parse(path).frontmatter
        if fm.get("origin") != ORIGIN or not is_paper(fm):
            continue
        if str(fm.get("status") or "active") in ("archived", "dropped"):
            continue
        if inbox_generator.find_open(Path(memory_path), "removal", eid) is not None:
            continue
        inbox_dir.mkdir(parents=True, exist_ok=True)
        if next_num is None:
            next_num = inbox_service.next_inbox_num(inbox_dir)
        item_id = f"inbox-{next_num:03d}"
        next_num += 1
        name = str(fm.get("name") or eid)
        markdown_parser.write(inbox_dir / f"{item_id}.md", {
            "kind": "removal", "required_input": "choice", "status": "pending", "priority": 0.4,
            "entity_id": eid, "entity_name": name, "title": f"Still keep {name}?",
            "created_date": date.today().isoformat(),
            "question": f"It isn't cited anywhere in {label} any more.",
            # keep first — QuestionSelection's no-recommendation fallback highlights index 0.
            "options": [{"key": "keep", "label": "Keep"}, {"key": "remove", "label": "Remove"}],
            "allow_other": False, "allow_defer": True,
            # `browser` is the key `inbox_context.cause_for` reads for a removal's
            # "Removed from <where>" excerpt (G129 slice 2); here it names the folder.
            "channel": folder_source.channel_id(folder["id"]), "browser": label,
            "url": str((fm.get("media") or {}).get("url") or ""), "synced_at": episode_ids.utc_now_iso(),
            "hint": None, "trigger": "sync/folder_removal",
        }, f"{name} is no longer cited in {label}.")
        written.append(f"inbox/{item_id}.md")
    return written


# --- Reconcile --------------------------------------------------------------


def _citations_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / CITATIONS_FILENAME


def load_citations(memory_path: Path) -> dict[str, list[str]]:
    """``source_id -> [paper entity ids]`` — the previous set a re-parse diffs
    against (the ``bookmark_seen.json`` pattern, G129)."""
    try:
        data = json.loads(_citations_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): [str(x) for x in v] for k, v in data.items() if isinstance(v, list)} if isinstance(data, dict) else {}


def save_citations(memory_path: Path, cites: dict[str, list[str]]) -> None:
    path = _citations_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cites, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _owner(memory_path: Path) -> str:
    from api.config import get_settings
    from api.services import owner_identity

    return owner_identity.resolve_observer(memory_path, get_settings())


def _name_of(memory_path: Path, entity_id: str | None) -> str | None:
    if not entity_id or not page_path(memory_path, entity_id).exists():
        return None
    return str(markdown_parser.parse(page_path(memory_path, entity_id)).frontmatter.get("name") or entity_id)


def _concept_matcher(memory_path: Path):
    """Section heading -> an existing concept/tool/skill/project id, by the
    zero-LLM half of Stage 2's matcher (R-LS16)."""
    from api.services import entity_resolver

    pool = [{"id": f.stem, "frontmatter": f.frontmatter} for f in bank_index.files(Path(memory_path), "entities")
            if (f.frontmatter or {}).get("type") in _CONCEPT_TYPES]
    by_name = entity_resolver.existing_by_name(pool)
    cache: dict[str, str | None] = {}

    def match(section: str | None) -> str | None:
        key = (section or "").strip()
        if not key:
            return None
        if key not in cache:
            hit = entity_resolver._find_direct_candidate_match({"name": key}, by_name, {})
            cache[key] = hit["candidate"]["id"] if hit else None
        return cache[key]

    return match


def _replay_aliases(memory_path: Path, ops: list[tuple[PaperKey, str, str | None, str]]) -> bool:
    """This run's ``index_aliases`` calls, replayed onto a FRESH ``url_index.json``
    load and saved at once — ``paper_metadata._replay_index``'s shape (T4 review
    finding 1). The working copy ``reconcile`` held across its page loop was
    loaded before it; saving THAT dropped any row a bookmark, Telegram or
    ``cicada_save_url`` save added meanwhile (L final review, finding 3)."""
    if not ops:
        return False
    idx = media_ingestor.load_url_index(memory_path)
    changed = False
    for key, entity_id, title, episode_id in ops:
        changed |= index_aliases(idx, key, entity_id, title=title, episode_id=episode_id)
    if changed:
        media_ingestor.save_url_index(memory_path, idx)
    return changed


def reconcile(memory_path: Path, folder: dict, *, touched: dict[str, str], tombstoned: dict[str, str],
              renamed=()) -> dict:
    """Re-parse the episodes a sync touched and bring paper pages, claims and
    removal proposals in line. Idempotent: running it twice changes nothing.

    Held under ``folder_source._LOCK`` (re-entrant) end to end. L final review,
    finding 3: this runs in the threadpool after ``folder_source.sync`` released
    that lock, and it load→mutate→saves the whole of ``folder_citations.json`` —
    two folders syncing at once (two FSEvents streams, a watched folder inside
    another) each saved their own stale copy, and the lost row made the next
    edit's ``previous`` empty, so claims the file no longer supports never
    closed and no removal was proposed."""
    with folder_source._LOCK:
        return _reconcile_locked(Path(memory_path), folder, touched=touched, tombstoned=tombstoned,
                                 renamed=renamed)


def _reconcile_locked(memory_path: Path, folder: dict, *, touched: dict[str, str], tombstoned: dict[str, str],
                      renamed=()) -> dict:
    today = date.today().isoformat()
    cites = load_citations(memory_path)
    cites_before = {k: list(v) for k, v in cites.items()}
    for old, new in renamed:
        if old in cites:
            cites[new] = cites.pop(old)
    idx = media_ingestor.load_url_index(memory_path)
    known = _known_papers(idx)
    owner = _owner(memory_path)
    concept_for = _concept_matcher(memory_path)
    project_id = str(folder.get("project_id") or "") or None
    project_name = _name_of(memory_path, project_id)
    report = {"papers_found": 0, "papers_created": 0, "claims_changed": 0, "removals_proposed": 0}
    paths: set[str] = set()
    # `idx` is a working copy — what this run's own pages already claimed; the
    # file is written only by `_replay_aliases`, from these recorded calls.
    alias_ops: list[tuple[PaperKey, str, str | None, str]] = []
    revisit: set[str] = set()
    for sid, ep_id in touched.items():
        text, fm = evidence.source_document(memory_path, ep_id)
        if text is None:
            continue
        by_page: dict[str, list[Citation]] = {}
        for c in parse(text):
            eid, created, page_changed, index_changed = ensure_page(
                memory_path, c.key, title=c.title, section=c.section, episode_id=ep_id,
                idx=idx, known=known, today=today)
            known.setdefault(c.key, eid)
            if index_changed:
                # `ensure_page` names a NEW page's Feed row after it; an existing one keeps its title.
                title = ((c.title or "").strip() or _placeholder(c.key)) if created else None
                alias_ops.append((c.key, eid, title, ep_id))
            report["papers_created"] += int(created)
            if page_changed:
                paths.add(f"entities/{eid}.md")
            by_page.setdefault(eid, []).append(c)
        previous = set(cites.get(sid, []))
        authorship = str(fm.get("authorship") or "user")
        valid_from = str(fm.get("timestamp") or "")[:10] or today
        for eid in sorted(previous | set(by_page)):
            desired = desired_claims(
                entity_id=eid, citations=by_page.get(eid, []), episode_id=ep_id, text=text,
                authorship=authorship, owner=owner, folder_id=folder["id"], project_id=project_id,
                project_name=project_name, concept_for=concept_for, today=today, valid_from=valid_from)
            if apply_claims(page_path(memory_path, eid), ep_id, desired, today):
                report["claims_changed"] += 1
                paths.add(f"entities/{eid}.md")
        cites[sid] = sorted(by_page)
        revisit |= previous - set(by_page)
        report["papers_found"] += len(by_page)
    for sid, ep_id in tombstoned.items():
        previous = set(cites.pop(sid, []))
        for eid in sorted(previous):
            if apply_claims(page_path(memory_path, eid), ep_id, [], today):
                report["claims_changed"] += 1
                paths.add(f"entities/{eid}.md")
        revisit |= previous
    cited_now = {eid for ids in cites.values() for eid in ids}
    written = propose_removals(memory_path, sorted(revisit - cited_now), folder)
    report["removals_proposed"] = len(written)
    paths.update(written)
    if _replay_aliases(memory_path, alias_ops):
        paths.add("sources/url_index.json")
    # Written only when it moved, so a sync that changed nothing leaves no path
    # to commit (the Task 2 no-churn rule the route keeps).
    if cites != cites_before:
        save_citations(memory_path, cites)
        paths.add(f"sources/{CITATIONS_FILENAME}")
    report["paths"] = sorted(paths)
    return report


def reparse_folder(memory_path: Path, folder: dict, *, tombstoned: dict[str, str] | None = None) -> dict:
    """Every live episode of the folder — the deferred path (R-LS17).

    The syncs that landed while a cycle ran are gone by the time this runs, and
    with them their ``StageResult``: a file deleted or renamed mid-cycle would
    leave its ``folder_citations.json`` row pointing at a dead source id, so its
    claims never closed and no removal was ever asked. So the stale rows are
    read back from the episode index itself — a tombstoned source is a
    deletion, a source id a live episode lists in ``previous_source_ids`` is a
    rename (Task 3 review).

    The scan and the reconcile share one hold of ``folder_source._LOCK`` so a
    sync cannot stage between them (L final review, finding 3)."""
    with folder_source._LOCK:
        return _reparse_folder_locked(Path(memory_path), folder, tombstoned=tombstoned)


def _reparse_folder_locked(memory_path: Path, folder: dict, *, tombstoned: dict[str, str] | None) -> dict:
    index, _ = episode_staging.scan(memory_path / "episodes")
    mine = {sid: e for sid, e in index.items() if e.fm.get("folder_id") == folder["id"]}
    touched = {sid: e.id for sid, e in mine.items() if not e.fm.get("source_deleted_at")}
    renamed_to = {str(prev): sid for sid in touched
                  for prev in (mine[sid].fm.get("previous_source_ids") or []) if prev}
    dead = dict(tombstoned or {})
    renamed: list[tuple[str, str]] = []
    prefix = folder_source.channel_id(folder["id"]) + ":"
    for sid in load_citations(memory_path):
        if not sid.startswith(prefix) or sid in touched or sid in dead:
            continue
        if sid in renamed_to:
            renamed.append((sid, renamed_to[sid]))
        elif sid in mine:
            dead[sid] = mine[sid].id
    return reconcile(memory_path, folder, touched=touched, tombstoned=dead, renamed=renamed)


def reconcile_pending(memory_path: Path) -> dict:
    """The Sleep tail's deterministic half: re-parse folders a running cycle
    deferred. Returns ``{"folders": n, "paths": [...]}``.

    Under ``folder_source._LOCK`` like ``reconcile`` (L final review, finding 3):
    the flag read and its clear must not straddle a sync that sets it again."""
    paths: set[str] = set()
    done = 0
    with folder_source._LOCK:
        for folder in folder_source.list_folders(memory_path):
            if not folder.get("papers_pending"):
                continue
            report = reparse_folder(memory_path, folder)
            folder_source.set_flags(memory_path, folder["id"], papers_pending=False)
            paths.update(report["paths"])
            done += 1
    if done:
        paths.add(f"sources/{folder_source.FOLDERS_FILENAME}")
    return {"folders": done, "paths": sorted(paths)}


# --- The card (read path, engine-free) --------------------------------------

_DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_WHY_ORDER = {p: i for i, p in enumerate(WHY_PREDICATES)}


def _heading_above(text: str, start: int) -> str | None:
    heading = None
    for m in _HEADING_RE.finditer(text):
        if m.start() > start:
            break
        heading = m.group(1).strip()
    return heading


def _snippet(text: str, start: int, end: int, pad: int = 120) -> tuple[str, int, int]:
    """±``pad`` characters around a span, cut on word boundaries, newlines shown
    as spaces (same length, so the highlight offsets stay exact)."""
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    if lo > 0:
        space = text.find(" ", lo, start)
        lo = space + 1 if space != -1 else lo
    if hi < len(text):
        space = text.rfind(" ", end, hi)
        hi = space if space != -1 else hi
    prefix, suffix = ("…" if lo > 0 else ""), ("…" if hi < len(text) else "")
    first = len(prefix) + (start - lo)
    return prefix + text[lo:hi].replace("\n", " ") + suffix, first, first + (end - start)


def detail(memory_path: Path, entity_id: str) -> dict | None:
    """The paper card's two tiers (G121), resolved at read: every open personal
    claim's span as a snippet with the file, the heading above it and the
    file's date — then the world-tier ``describes`` context. ``None`` for an
    id that is not a paper page (or not a bare id at all)."""
    if not _DOC_ID_RE.match(entity_id or ""):
        return None
    path = page_path(memory_path, entity_id)
    if not path.exists():
        return None
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter or {}
    if not is_paper(fm):
        return None
    paper = fm.get("paper") or {}
    claims = parse_claims(parsed.body)
    docs: dict[str, tuple[str | None, dict]] = {}
    names: dict[str, str] = {}
    why: list[dict] = []
    open_why = sorted((c for c in claims if c.predicate in WHY_PREDICATES and not c.valid_to),
                      key=lambda c: (_WHY_ORDER[c.predicate], c.id))
    for c in open_why:
        for ev in c.evidence:
            if ev.kind == "reasoning" or ev.start < 0:
                continue
            if ev.episode not in docs:
                docs[ev.episode] = evidence.source_document(memory_path, ev.episode)
            text, efm = docs[ev.episode]
            if text is None or ev.end > len(text):
                continue
            snippet, first, last = _snippet(text, ev.start, ev.end)
            target = None
            if c.object_kind == "node":
                names.setdefault(c.object, _name_of(memory_path, c.object) or c.object)
                target = names[c.object]
            why.append({
                "predicate": c.predicate, "text": c.object if c.object_kind == "literal" else None,
                "target": target, "snippet": snippet, "highlight_start": first, "highlight_end": last,
                "file": efm.get("relpath"), "heading": _heading_above(text, ev.start),
                "edited": str(efm.get("source_updated_at") or efm.get("timestamp") or "")[:10] or None,
                "kind": ev.kind, "episode": ev.episode, "start": ev.start, "end": ev.end,
                "stale": bool(ev.hash) and ev.hash != evidence.body_hash(text),
            })
    describes = next((c for c in claims if c.predicate == "describes" and c.source_trust == "external"
                      and not c.valid_to), None)
    return {
        "entity_id": entity_id,
        "title": str(paper.get("title") or fm.get("name") or entity_id),
        "authors": [str(a) for a in paper.get("authors") or []],
        "venue": paper.get("venue") or paper.get("journal_ref"),
        "published": paper.get("published"),
        "arxiv_id": paper.get("arxiv_id"),
        "doi": paper.get("doi"),
        "abs_url": f"https://arxiv.org/abs/{paper['arxiv_id']}" if paper.get("arxiv_id") else None,
        "doi_url": f"https://doi.org/{paper['doi']}" if paper.get("doi") else None,
        "sections": [str(s) for s in paper.get("sections") or []],
        "why": why,
        "agent_only": bool(why) and not any(w["kind"] == "user" for w in why),
        "context": describes.object if describes else None,
        "context_source": paper.get("metadata_source") if describes else None,
        "context_as_of": describes.recorded_at if describes else None,
        # L final review (finding 6): the card's empty state names what really
        # happened — a lookup that failed (and waits `RETRY_DAYS`) is not
        # "arriving with the next sync".
        "metadata_status": paper.get("metadata_status") if not describes else None,
    }
