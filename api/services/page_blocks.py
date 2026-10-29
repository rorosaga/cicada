"""What a page holds, as blocks a layout and an agent can both read (vision item 5, 2026-10-28).

The owner, 2026-10-28: a page should be rendered by what it holds — a map for a place, the look of a design, the
sources, the history with the contributor's picture and Sleep as a tag, what is ongoing — "and in the same way we
expose in a nice understanding way all information, same for the agents". The layout waits on a design decision; the
data does not. This module is the data: ``build`` returns which blocks a page has (``order``) and each one's data,
computed from what the record already holds every time the page is read.

Rails it keeps:

* **Derived on read, never stored, never fetched.** No block makes a network call or a model call; a place's
  coordinates are the ones the page itself stores (never geocoded here), a source's preview is the icon route the card
  already reads, a look's screenshot the route the Looks page already serves.
* **The card open is a hot path.** Every input is what ``GET /entities/{id}`` already read (the page, its history, its
  relevance) or a stat-cached index (the looks, by ``design_refs.stamp``). Blame stays lazy: it is never a block.
* **One function per door.** ``GET /entities/{id}`` serves ``build``; ``cicada_recall_detail(include=…)`` words the
  same dict (``mcp_tools``), so the app and an agent can never see two different pages.

``card_etag`` is the ETag of ``GET /entities/{id}``: every input the card reads, as cheap stamps.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import date
from pathlib import Path

from api.services import bank_index, design_refs, page_citations

#: The wire's version; it rides the card's ETag, so a new shape revalidates every held card.
SHAPE = "blocks-2"
#: Every block, in the order a page reads them — the redesign proposal's page order (2026-10-28 §0/§1): why it matters,
#: where to check, the type block (a map from stored coordinates, a look), what is ongoing, the article's citations
#: (ruling 48 (16), ``page_citations``: its markers, References and belief sentences), then who changed it.
KINDS = ("relevance", "sources", "coordinates", "looks", "ongoing", "citations", "history")
MAX_ONGOING = 8
MAX_SOURCES = 12
MAX_LOOKS = 6
MAX_CONTRIBUTORS = 6
_OPEN = {"happened": ("ongoing", "happening"), "milestone": ("planned", "milestone")}


# ---- ongoing -------------------------------------------------------------------------------------------------------


def _day(raw) -> str:
    text = str(raw or "")[:10]
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" else ""


def ongoing(claims: list) -> list[dict]:
    """The page's open events (G141): a happening still ongoing, a milestone still planned — each event's head only
    (a superseded state is history, a withdrawal record is never an event). Newest first."""
    from api.services.claims import is_event, is_persons_words, is_record

    out = []
    for c in claims or []:
        if not is_event(c) or c.superseded_by or is_record(c) or getattr(c, "recovered_by", None):
            continue
        want, kind = _OPEN[c.predicate]
        if str(c.status or "") != want:
            continue
        out.append({"claimId": c.id, "kind": kind, "status": want, "text": str(c.text or "").strip(),
                    "since": _day(c.valid_from) or _day(c.recorded_at), "target": _day(getattr(c, "target", None)),
                    "verbatim": bool(is_persons_words(c))})
    out.sort(key=lambda r: (r["since"], r["claimId"]), reverse=True)
    return out


# ---- place ---------------------------------------------------------------------------------------------------------


def _coordinate(value, bound: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and -bound <= number <= bound else None


def coordinates(fm: dict, label: str = "") -> dict | None:
    """Coordinates the page stores at its top level (``lat``/``lon``, or ``latitude``/``longitude``) — the keys the
    app's map already prefers over geocoding. A value out of range or not a number is no place. ``label``: the page's
    name, the pin's caption."""
    lat = _coordinate(fm.get("lat", fm.get("latitude")), 90.0)
    lon = _coordinate(fm.get("lon", fm.get("longitude")), 180.0)
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon, "label": label, "source": "page"}


# ---- looks ---------------------------------------------------------------------------------------------------------

_LOOKS: dict[str, tuple[str, dict[str, list[dict]]]] = {}
_LOOKS_LOCK = threading.Lock()


def _look(ref) -> dict:
    return {"id": ref.id, "title": ref.title or "", "site": ref.site, "day": ref.day,
            "palette": [str(c["hex"]) for c in ref.palette if isinstance(c, dict) and c.get("hex")][:8],
            "fonts": design_refs.fonts(ref)[:4],
            "image": f"/design/{ref.id}/image" if ref.image_path else None}


def looks(memory_path: Path, entity_id: str) -> list[dict]:
    """The looks attached to the page, newest first — from one index of the bank's looks, rebuilt only when a look
    file changes (``design_refs.stamp``, a stat walk), so a card open never parses every look."""
    key = str(memory_path)
    stamp = design_refs.stamp(memory_path)
    with _LOOKS_LOCK:
        hit = _LOOKS.get(key)
    if hit is None or hit[0] != stamp:
        by_page: dict[str, list[dict]] = {}
        for ref in design_refs.list_refs(memory_path):
            if ref.entity:
                by_page.setdefault(ref.entity, []).append(_look(ref))
        hit = (stamp, by_page)
        with _LOOKS_LOCK:
            _LOOKS[key] = hit
    return list(hit[1].get(entity_id, []))


# ---- sources -------------------------------------------------------------------------------------------------------


def icon_site(source: dict, page_type: str) -> str | None:
    """The site key ``GET /entities/{id}/sources/icon/{site}`` serves for one source, or None when that route would
    404 — a trusted URL source on a page that is neither a person nor a media page (G159)."""
    from api.services import fact_sources, reading_hosts

    if str(source.get("kind") or "") != "url" or page_type in ("person", "media") or not fact_sources.trusted(source):
        return None
    site = reading_hosts.site_of(str(source.get("ref") or ""))
    return site if site and reading_hosts.valid_site_key(site) and reading_hosts.icon_host(site) else None


#: A source's state in one word, the redesign proposal's words (2026-10-28 §0) plus the two it leaves implicit.
SOURCE_STATES = ("proposed", "dead", "changed", "stale", "checked", "unchecked", "unconfirmed")


def source_state(source: dict, today: date) -> str:
    """One of :data:`SOURCE_STATES`: ``proposed`` (an agent's find waiting for the person), ``dead`` (two failed visits a
    week apart), ``changed`` (Cicada saw the page change and could not read the fact), ``stale`` (a re-check is due:
    its cadence passed, a retry, or the person asked), ``checked`` (re-checked within its cadence, or confirmed by
    Cicada's own read), ``unchecked`` (trusted, never re-checked — or nothing to visit), else ``unconfirmed``. Read from
    ``source_refresh``'s own rules (ruling 26), never a second copy of them."""
    from api.services import fact_sources, source_refresh

    if fact_sources.is_proposed(source):
        return "proposed"
    if not fact_sources.trusted(source):
        return "unconfirmed"
    if source_refresh.tracked(source) and source_refresh.dead(source):
        return "dead"
    due = source_refresh.due_reason(source, today)
    if due == "changed":
        return "changed"
    if due in ("cadence", "retry", "asked"):
        return "stale"
    if source.get("verified") or source_refresh.state(source).get("at"):
        return "checked"
    return "unchecked"


def sources(fm: dict, page_type: str, today: date) -> dict | None:
    """The page's "where to check" entries (at most :data:`MAX_SOURCES`), each with its state in one word, its site,
    the day it was last checked or confirmed, and the icon route's site key — the stored icon, never a fetch."""
    from api.services import fact_sources, reading_hosts, source_proposals, source_refresh

    rows = fact_sources.as_sources(fm.get("sources"))
    if not rows:
        return None
    items = []
    for s in rows[:MAX_SOURCES]:
        link_kind, label = source_proposals.link_kind(s)
        ref = str(s.get("ref") or "")
        stamps = [d.get("at") for d in (source_refresh.state(s), s.get("verified"), s.get("checked"))
                  if isinstance(d, dict) and d.get("at")]
        items.append({"ref": ref, "kind": str(s.get("kind") or "note"), "label": label,
                      "linkKind": link_kind, "state": source_state(s, today),
                      "site": reading_hosts.site_of(ref) or None if str(s.get("kind") or "") == "url" else None,
                      "checkedAt": max(str(x) for x in stamps)[:10] if stamps else None,
                      "addedBy": str(s.get("added_by") or "user"), "iconSite": icon_site(s, page_type)})
    return {"total": len(rows), "proposed": sum(1 for s in rows if fact_sources.is_proposed(s)),
            "tracked": sum(1 for s in rows if source_refresh.tracked(s)), "items": items}


# ---- history -------------------------------------------------------------------------------------------------------


def history(entries: list, truncated: bool) -> dict | None:
    """Who changed the page, for pictures: each contributor (a model id or ``user``) with their change count and last
    day, most changes first, and how many changes Sleep made — Sleep is a tag on a row, the contributor its face."""
    if not entries:
        return None
    by: dict[str, dict] = {}
    sleep = 0
    for e in entries:
        get = (lambda k, d=None: e.get(k, d)) if isinstance(e, dict) else (lambda k, d=None: getattr(e, k, d))
        author = str(get("author") or "unknown")
        row = by.setdefault(author, {"author": author, "kind": get("author_kind") or "unknown",
                                     "provider": get("author_provider"), "changes": 0, "last": ""})
        row["changes"] += 1
        row["last"] = max(row["last"], str(get("date") or ""))
        sleep += 1 if get("via") == "sleep" else 0
    ranked = sorted(by.values(), key=lambda r: (-r["changes"], r["author"]))[:MAX_CONTRIBUTORS]
    days = [str((e.get("date") if isinstance(e, dict) else e.date) or "") for e in entries]
    return {"changes": len(entries), "truncated": bool(truncated), "bySleep": sleep, "lastChange": max(days),
            "contributors": ranked}


# ---- the blocks ----------------------------------------------------------------------------------------------------


def build(memory_path: Path, entity_id: str, *, fm: dict, claims: list, relevance: dict | None,
          history_entries: list | None = None, history_truncated: bool = False, today: date | None = None,
          body: str | None = None) -> dict:
    """The page's blocks. ``order`` lists the blocks present, in :data:`KINDS` order; an absent block's key is null or
    an empty list. Never raises for one bad block: that block is left out. ``body``: the page's raw body (claims fence
    included), which the citations are numbered from; ``None`` leaves them out."""
    today = today or date.today()
    page_type = str(fm.get("type") or "concept").strip().lower()
    out: dict = {"shape": SHAPE, "order": [], "relevance": relevance, "ongoing": [], "ongoingTotal": 0,
                 "coordinates": None, "looks": [], "sources": None, "citations": None, "history": None}
    try:
        open_events = ongoing(claims)
        out["ongoing"], out["ongoingTotal"] = open_events[:MAX_ONGOING], len(open_events)
    except Exception:  # noqa: BLE001 — a derived block never fails a page read
        pass
    out["coordinates"] = coordinates(fm, str(fm.get("name") or entity_id))
    try:
        out["looks"] = looks(memory_path, entity_id)[:MAX_LOOKS]
    except Exception:  # noqa: BLE001
        pass
    try:
        out["sources"] = sources(fm, page_type, today)
    except Exception:  # noqa: BLE001
        pass
    if body is not None:
        try:
            out["citations"] = page_citations.block(memory_path, entity_id, fm=fm, body=body, claims=claims)
        except Exception:  # noqa: BLE001
            pass
    out["history"] = history(history_entries or [], history_truncated)
    present = {"relevance": bool(relevance) and relevance.get("tense") != "self", "ongoing": bool(out["ongoing"]),
               "coordinates": out["coordinates"] is not None, "looks": bool(out["looks"]), "sources": out["sources"] is not None,
               "citations": out["citations"] is not None, "history": out["history"] is not None}
    out["order"] = [k for k in KINDS if present[k]]
    return out


# ---- the card's ETag -----------------------------------------------------------------------------------------------


def _stat(path: Path) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return "-"
    return f"{st.st_mtime_ns}.{st.st_size}"


def _dir(path: Path) -> str:
    """A directory's own stamp: its mtime moves whenever an entry is created, removed or renamed — which every bank
    write is (atomic: a temp file renamed into place), and so is git restoring a file. No listing, no per-file stat."""
    try:
        return str(os.stat(path).st_mtime_ns)
    except OSError:
        return "-"


def _known_owner(mp: Path) -> str:
    """The owner page's id as the relevance index last read it, without a directory scan; the scan only when it was
    never read. A new owner is a page write, which moves the ``entities`` stamp anyway."""
    from api.services import page_relevance

    hit = page_relevance._names_cache.get(str(mp))
    return (hit[2] if hit is not None else page_relevance._owner_id(mp)) or ""


def card_etag(memory_path: Path, entity_id: str, *, extra: str = "") -> str:
    """``GET /entities/{id}``'s ETag: every input the card reads, as stamps — a handful of ``stat`` calls, never a
    parse and never a directory listing (a listing of ``entities/`` and ``episodes/`` is ~20 ms each on an owner-scale
    bank; the whole ETag is under a millisecond). This page and its claims ledger, and the owner page and its ledger
    (the relations its relevance reads), stat'ed directly; the ``entities``, ``episodes`` and looks directories by their
    own mtime (any page, conversation or look written, added or removed — the names a relevance line uses, the
    conversations decay and relevance count); the bank's git head (its history and every committed file, the decay
    tuning among them); the logo and people-photo caches outside the bank (the picture); the day (bands, a source's
    due date, an event's tense) and :data:`SHAPE`. ``extra``: the caller's own varying state.

    What it cannot see: a hand edit made in place (not renamed) to ANOTHER page or a conversation, which a running
    card never reads more than a name or a kind from — the next real write, commit or day moves it."""
    from api.services import logo_service, messages_photos, person_photo, sync_service

    mp = Path(memory_path)
    entities = mp / "entities"
    owner = _known_owner(mp)
    bank = logo_service.bank_name(mp)
    parts = {
        "entities": _dir(entities),
        "episodes": _dir(mp / "episodes"),
        "pageFile": _stat(entities / f"{entity_id}.md"),
        "ledger": _stat(entities / f"{entity_id}.claims.jsonl"),
        "owner": f"{owner}:{_stat(entities / f'{owner}.md')}:{_stat(entities / f'{owner}.claims.jsonl')}"
                 if owner else "-",
        "design": _dir(mp / design_refs.DESIGN_DIR),
        "git": sync_service.git_head(mp),
        "logos": sync_service._logos_component(mp),
        "photos": f"{person_photo.stamp(bank)}:{messages_photos.stamp(mp)}",
        "day": date.today().isoformat(),
        "page": f"{mp}|{entity_id}|{SHAPE}|{extra}",
    }
    return '"' + hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16] + '"'


# ---- the same blocks for an agent (cicada_recall_detail include=…) -------------------------------------------------

#: What ``include`` may name: every block, or ``blocks`` for all of them. ``history`` is the one block a remote
#: connection is never offered: no remote scope covers a page's per-commit history (``REMOTE_INCLUDE``).
INCLUDE = ("blocks", *KINDS)
REMOTE_INCLUDE = tuple(k for k in INCLUDE if k != "history")


def wanted(include, *, remote: bool) -> tuple[str, ...]:
    """The block kinds an ``include`` argument asks for, in page order; ``blocks`` is all of them."""
    if isinstance(include, str):
        include = [include]
    asked = {str(k).strip().lower() for k in (include or []) if str(k).strip()}
    allowed = REMOTE_INCLUDE if remote else INCLUDE
    return tuple(k for k in KINDS if k in allowed and ("blocks" in asked or k in asked))


def for_page(memory_path: Path, entity_id: str, kinds: tuple[str, ...]) -> dict:
    """``build`` for one page outside the card's route: one parse, and the page's git history only when ``history`` is
    asked (it is the one block that runs git). Never raises: an unreadable page is an empty set of blocks."""
    from api.services import markdown_parser, page_relevance
    from api.services.claims import parse_claims

    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    try:
        parsed = markdown_parser.parse(path, ledger=False)
        claims = parse_claims(parsed.body or "")
    except Exception:  # noqa: BLE001
        return {"shape": SHAPE, "order": []}
    with bank_index.shared_scans():   # the relevance line's two listings of `entities/` become one
        relevance = page_relevance.for_page(memory_path, entity_id, fm=parsed.frontmatter, body=parsed.body,
                                            claims=claims).to_dict()
    entries, truncated = [], False
    if "history" in kinds:
        import asyncio

        from api.services import git_service

        try:
            entries, truncated = asyncio.run(git_service.entity_history(entity_id, Path(memory_path)))
        except Exception:  # noqa: BLE001 — a history git cannot read is no history block
            entries, truncated = [], False
    return build(memory_path, entity_id, fm=parsed.frontmatter, claims=claims, relevance=relevance,
                 history_entries=entries, history_truncated=truncated,
                 body=(parsed.body or "") if "citations" in kinds else None)


#: What an ongoing item in the person's own words reads as for a caller that may not see their words.
OWN_WORDS = "(in the person's own words)"


def for_caller(blocks: dict, kinds: tuple[str, ...], *, verbatim: bool) -> dict:
    """The blocks one agent call may carry — as its words AND as structured data (``/v1`` returns ``data`` as it is,
    review of #505): only the kinds asked for (an absent one null or empty, ``order`` narrowed), and, for a caller
    without ``sources`` (``verbatim=False``), every ongoing item worded in the person's own sentence masked. A copy:
    the input is never changed."""
    out = {"shape": blocks.get("shape", SHAPE), "order": [k for k in blocks.get("order") or [] if k in kinds]}
    empty = {"relevance": None, "sources": None, "coordinates": None, "looks": [], "ongoing": [], "citations": None,
             "history": None}
    for kind in KINDS:
        out[kind] = blocks.get(kind, empty[kind]) if kind in kinds else empty[kind]
    out["ongoingTotal"] = blocks.get("ongoingTotal", 0) if "ongoing" in kinds else 0
    if not verbatim:
        out["ongoing"] = [dict(item, text=OWN_WORDS) if item.get("verbatim") else dict(item)
                          for item in out["ongoing"]]
    out["citations"] = page_citations.for_caller(out["citations"], verbatim=verbatim)
    return out


def words(blocks: dict, kinds: tuple[str, ...], *, verbatim: bool = True) -> str:
    """The blocks as compact text for an agent, in page order, one heading line each; a kind asked for that the page
    does not have says so in one line. ``verbatim=False`` (a remote connection without ``sources``): an ongoing item
    worded in the person's own sentence is named, never quoted."""
    present = set(blocks.get("order") or [])
    lines = ["## Page blocks"]
    for kind in kinds:
        if kind not in present:
            lines.append(f"- {kind}: none on this page")
        elif kind == "relevance":
            lines.append(f"- relevance ({blocks['relevance'].get('tense')}): {blocks['relevance'].get('line')}")
        elif kind == "sources":
            s = blocks["sources"]
            lines.append(f"- sources: {s['total']} ({s.get('proposed', 0)} proposed, {s.get('tracked', 0)} tracked)")
            for row in s["items"]:
                when = f", checked {row['checkedAt']}" if row.get("checkedAt") else ""
                lines.append(f"  - {row['state']}: {row['ref']} ({row.get('linkKind') or row['kind']}, "
                             f"added by {row.get('addedBy') or 'user'}{when})")
        elif kind == "coordinates":
            c = blocks["coordinates"]
            lines.append(f"- coordinates: {c['lat']}, {c['lon']} (stored on the page)")
        elif kind == "looks":
            lines.append(f"- looks: {len(blocks['looks'])}")
            for look in blocks["looks"]:
                bits = [b for b in (look.get("site"), look.get("day")) if b]
                colours, faces = " ".join(look.get("palette") or []), ", ".join(look.get("fonts") or [])
                lines.append(f"  - {look['id']}" + (f" ({' · '.join(bits)})" if bits else "")
                             + (f"; colours {colours}" if colours else "") + (f"; type {faces}" if faces else ""))
        elif kind == "ongoing":
            lines.append(f"- ongoing: {blocks.get('ongoingTotal', len(blocks['ongoing']))}")
            for item in blocks["ongoing"]:
                text = item["text"] if verbatim or not item.get("verbatim") else OWN_WORDS
                when = (f", planned for {item['target']}" if item.get("target")
                        else f", since {item['since']}" if item.get("since") else "")
                lines.append(f"  - {item['kind']} {item['status']}{when}: {text} [{item['claimId']}]")
        elif kind == "citations":
            c = page_citations.for_caller(blocks["citations"], verbatim=verbatim)
            lines.append(f"- citations: {c['total']} sources ({c.get('conversations', 0)} conversations, "
                         f"{c.get('web', 0)} looked up, {c.get('pages', 0)} pages), {c.get('markersTotal', 0)} "
                         "cited lines; each source is a reference [n] in the article")
            for ref in c.get("refs") or []:
                lines.append(f"  - {page_citations.ref_words(ref)}")
            if c.get("beliefs"):
                total = c.get("beliefsTotal")
                lines.append(f"  - as sentences ({len(c['beliefs'])} of "
                             f"{total if total is not None else 'more'} beliefs):")
                for belief in c["beliefs"]:
                    lines.append(f"    - {page_citations.belief_words(belief)}")
        elif kind == "history":
            h = blocks["history"]
            lines.append(f"- history: {h['changes']} changes{' (more not shown)' if h.get('truncated') else ''}, "
                         f"{h.get('bySleep', 0)} by Sleep, last {h.get('lastChange') or 'unknown'}")
            for c in h["contributors"]:
                lines.append(f"  - {c['author']} ({c.get('kind') or 'unknown'}): {c['changes']} "
                             f"change{'' if c['changes'] == 1 else 's'}, last {c['last']}")
    return "\n".join(lines)


