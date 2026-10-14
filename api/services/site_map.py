"""The site map an explore visit leaves behind (G166 slice 2, owner 2026-10-14 evening) — the ONE reader and writer.

"Maybe a sitemap of sorts can live in memory also for whatever website already got scraped."

One markdown file per explored site, **in the bank beside the site's captures**: ``<bank>/captures/_sites/<site>.md``
(``site`` is ``reading_hosts.site_of``: the registrable-ish name, so every saved page of one site shares one map). It
records the pages the person's agents found and visited there — each page's URL, title, kind, when it was first and last
seen, and the capture ids that hold its pictures — plus robots.txt as last read and one line per visit.

**Why in the bank.** It is memory, not a cache: what existed on a site on a given day cannot be fetched again, and the
capture ids it names are bank paths, so a map outside the bank would point at nothing once the bank is handed over. It
is small (a few KB), committed with the capture it came from under the agent's own author, and legible as it is — YAML
frontmatter for a program, a table for a person or an agent. ``_sites`` starts with an underscore, so it can never be a
saved page's own capture folder (an entity id never does).

**Append-only over visits.** A visit adds pages and adds a visit line; it never removes a page or a visit, never moves
a ``first_seen``, and only ever moves a ``last_seen`` forward. A page a later visit no longer finds keeps its row (and its
``last_seen`` says when it was last there), so a later visit knows what existed before. Git keeps every version.

A page found behind a sign-in or a block keeps that outcome, and the next plan never opens it again (the ToS rail: a
block is never retried). Pages that sign in, check out or manage an account are never listed.

Callers pass the ACTIVE bank, hold the write admission through their commit and refuse a demo bank; nothing here
commits. The URLs kept are page addresses with no query and no fragment (``explore_plan.clean_page_url``).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from api.services import episode_scrub, explore_plan, markdown_parser

DIR = ("captures", "_sites")
SHAPE = "sitemap-1"
#: A map lists at most this many pages; past it, newly found pages are counted (``unlisted``), never listed.
MAX_PAGES = 300
TITLE_CHARS = 160
LABEL_CHARS = 80
SITE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
_KIND_ORDER = ("home", *explore_plan.PAGE_KINDS, "other")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel_path(site: str) -> str | None:
    site = str(site or "").strip().lower()
    if not SITE_RE.match(site) or ".." in site:
        return None
    return f"{'/'.join(DIR)}/{site}.md"


def path_for(memory_path, site: str) -> Path | None:
    rel = rel_path(site)
    return Path(memory_path) / rel if rel else None


def _line(text, cap: int, bank: str) -> str:
    cleaned, n = episode_scrub.scrub(" ".join(str(text or "").split()))
    episode_scrub.record("site_map", n, bank=bank)
    return cleaned[:cap].rstrip()


# --------------------------------------------------------------------------- reading


def read(memory_path, site: str) -> dict | None:
    """The site's map as stored (frontmatter), or None when the site was never explored."""
    path = path_for(memory_path, site)
    if path is None or not path.is_file():
        return None
    try:
        fm = dict(markdown_parser.parse(path).frontmatter or {})
    except Exception as exc:  # noqa: BLE001 — a hand-broken map reads as none; the next visit starts a fresh one
        logger.debug(f"site_map: unreadable {path.name}: {type(exc).__name__}")
        return None
    fm["pages"] = [p for p in fm.get("pages") or [] if isinstance(p, dict) and isinstance(p.get("url"), str)]
    fm["visits"] = [v for v in fm.get("visits") or [] if isinstance(v, dict)]
    return fm


def known_by_kind(smap: dict | None) -> dict[str, str]:
    """``{kind: url}``: for each page kind, the page a previous visit opened most recently — so a re-visit opens the
    same pricing page and the two captures compare. Walled pages and the landing page are left out."""
    out: dict[str, tuple[str, str]] = {}
    for page in (smap or {}).get("pages") or []:
        kind, url = str(page.get("kind") or ""), str(page.get("url") or "")
        if kind in ("home", "other", "account") or not page.get("captures") or page.get("outcome") in _WALLS:
            continue
        when = str(page.get("last_visited") or "")
        if kind not in out or when > out[kind][0]:
            out[kind] = (when, url)
    return {k: v[1] for k, v in out.items()}


_WALLS = ("needs_login", "blocked")


def walled_urls(smap: dict | None) -> list[str]:
    return [str(p["url"]) for p in (smap or {}).get("pages") or [] if p.get("outcome") in _WALLS]


def all_maps(memory_path) -> list[dict]:
    root = Path(memory_path).joinpath(*DIR)
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.md")):
        if (smap := read(memory_path, path.stem)) is not None:
            out.append(smap)
    return out


# --------------------------------------------------------------------------- the merge (pure)


def merge(existing: dict | None, *, site: str, visit: dict, bank: str = "") -> dict:
    """``existing`` plus one visit — append-only (see the module doc). ``visit``::

        {at, capture, entity, landing: {url, title, kind?, outcome?, dhash?, thumb?},
         pages: [{url, title, kind, outcome, dhash?, thumb?}],          # opened in this visit
         found: [{url, label}],                                          # links the site showed
         robots: {status, sha256} | None, robots_parser: RobotFileParser | None}
    """
    at = str(visit.get("at") or _iso(datetime.now(timezone.utc)))
    smap = {"shape": SHAPE, "site": site, "first_seen": at, "last_seen": at, "pages": [], "visits": []}
    if existing:
        smap.update({k: v for k, v in existing.items() if k not in ("path",)})
        smap["pages"] = [dict(p) for p in existing.get("pages") or []]
        smap["visits"] = [dict(v) for v in existing.get("visits") or []]
        smap["shape"], smap["site"] = SHAPE, site
        smap["first_seen"] = min(str(existing.get("first_seen") or at), at)
        smap["last_seen"] = max(str(existing.get("last_seen") or at), at)
    by_url = {p["url"]: p for p in smap["pages"]}
    unlisted = int(smap.get("unlisted") or 0)
    parser = visit.get("robots_parser")
    capture = str(visit.get("capture") or "")

    def touch(url: str, *, title: str | None, label: str | None, kind: str | None, visited: dict | None) -> None:
        nonlocal unlisted
        clean = explore_plan.clean_page_url(url)
        if clean is None or explore_plan.host_of(clean) == "":
            return
        kind = kind or explore_plan.page_kind(clean, label)
        if kind == "account":
            return
        page = by_url.get(clean)
        if page is None:
            if len(by_url) >= MAX_PAGES:
                unlisted += 1
                return
            page = {"url": clean, "kind": kind, "first_seen": at, "last_seen": at}
            by_url[clean] = page
            smap["pages"].append(page)
        else:
            page["first_seen"] = min(str(page.get("first_seen") or at), at)
            page["last_seen"] = max(str(page.get("last_seen") or at), at)
            if page.get("kind") in (None, "", "other") and kind not in ("other",):
                page["kind"] = kind
        words = _line(title, TITLE_CHARS, bank) if title else ""
        if words:
            page["title"] = words
        elif label and not page.get("title"):
            page["label"] = _line(label, LABEL_CHARS, bank)
        if parser is not None and visited is None:
            page["robots"] = "allowed" if explore_plan.allowed(parser, clean) else "disallowed"
        if visited is not None:
            page["last_visited"] = max(str(page.get("last_visited") or at), at)
            if capture and capture not in (page.get("captures") or []):
                page["captures"] = [*(page.get("captures") or []), capture]
            outcome = str(visited.get("outcome") or "captured")
            page["outcome"] = outcome
            for name in ("dhash", "thumb"):
                if visited.get(name):
                    page[name] = visited[name]
            if outcome in _WALLS:
                page.pop("thumb", None)

    landing = visit.get("landing") or {}
    if landing.get("url"):
        touch(landing["url"], title=landing.get("title"), label=None, kind=landing.get("kind") or "home",
              visited=landing)
    for page in visit.get("pages") or []:
        if isinstance(page, dict) and page.get("url"):
            touch(page["url"], title=page.get("title"), label=None, kind=page.get("kind"), visited=page)
    for link in visit.get("found") or []:
        if isinstance(link, dict) and link.get("url"):
            touch(link["url"], title=None, label=link.get("label"), kind=None, visited=None)
    if unlisted:
        smap["unlisted"] = unlisted
    robots = visit.get("robots")
    if isinstance(robots, dict) and robots.get("status") is not None:
        smap["robots"] = {"status": robots.get("status"), "read_at": at,
                          **({"sha256": robots["sha256"]} if robots.get("sha256") else {})}
    opened = [p for p in visit.get("pages") or [] if isinstance(p, dict) and p.get("url")]
    line = {"at": at, "capture": capture, "entity": str(visit.get("entity") or ""),
            "pages": 1 + len(opened), "found": len(visit.get("found") or [])}
    if visit.get("depth"):
        line["depth"] = str(visit["depth"])
    if not any(v.get("capture") == capture and v.get("at") == at for v in smap["visits"]):
        smap["visits"].append(line)
    smap["pages"].sort(key=lambda p: (_KIND_ORDER.index(p["kind"]) if p.get("kind") in _KIND_ORDER
                                      else len(_KIND_ORDER), str(p.get("first_seen") or ""), p["url"]))
    return smap


def body(smap: dict) -> str:
    """The map as an agent or a person reads it: what it is, a table of pages, the visits."""
    site = smap.get("site") or "this site"
    pages = smap.get("pages") or []
    parts = [f"# Site map: {site}", "",
             f"Pages the person's agents found on {site} while exploring their saved pages. Append-only: a page stays "
             "listed after a later visit stops finding it, and its last-seen date says when it was last there.", ""]
    if smap.get("robots"):
        parts += [f"robots.txt read {str(smap['robots'].get('read_at') or '')[:10]} "
                  f"(status {smap['robots'].get('status')}).", ""]
    parts += ["| Page | Kind | First seen | Last seen | Captures |", "|---|---|---|---|---|"]
    for p in pages:
        name = (p.get("title") or p.get("label") or p["url"]).replace("|", "/")
        caps = ", ".join(p.get("captures") or []) or ("not opened" + (" (robots.txt)" if p.get("robots") ==
                                                                         "disallowed" else ""))
        if p.get("outcome") in _WALLS:
            caps += f" · {p['outcome'].replace('_', ' ')}"
        parts.append(f"| [{name}](<{p['url']}>) | {p.get('kind')} | {str(p.get('first_seen'))[:10]} | "
                     f"{str(p.get('last_seen'))[:10]} | {caps} |")
    if smap.get("unlisted"):
        parts += ["", f"…and {smap['unlisted']} more pages found but not listed (the map keeps {MAX_PAGES})."]
    parts += ["", "## Visits", ""]
    for v in smap.get("visits") or []:
        parts.append(f"- {v.get('at')} · capture {v.get('capture')} of `{v.get('entity')}` · {v.get('pages')} "
                     f"page(s) opened, {v.get('found')} link(s) found")
    return "\n".join(parts).rstrip() + "\n"


# --------------------------------------------------------------------------- writing


def update(memory_path, site: str, visit: dict) -> str | None:
    """Merge one visit into the site's map and write it atomically. Returns the memory-relative path to commit, or
    None when the site name is not one a map can be kept under (nothing written)."""
    path = path_for(memory_path, site)
    if path is None:
        return None
    merged = merge(read(memory_path, site), site=site, visit=visit, bank=Path(memory_path).name)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, merged, body(merged))
    return rel_path(site)


def wire(smap: dict | None) -> dict | None:
    """The map as the API serves it (camelCase)."""
    if not smap:
        return None
    return {
        "site": smap.get("site"), "firstSeen": smap.get("first_seen"), "lastSeen": smap.get("last_seen"),
        "robots": smap.get("robots"), "unlisted": int(smap.get("unlisted") or 0), "shape": SHAPE,
        "pages": [{"url": p.get("url"), "title": p.get("title") or p.get("label"), "kind": p.get("kind"),
                   "firstSeen": p.get("first_seen"), "lastSeen": p.get("last_seen"),
                   "lastVisited": p.get("last_visited"), "captures": list(p.get("captures") or []),
                   "outcome": p.get("outcome"), "robots": p.get("robots")} for p in smap.get("pages") or []],
        "visits": [{"at": v.get("at"), "capture": v.get("capture"), "entityId": v.get("entity"),
                    "pages": v.get("pages"), "found": v.get("found"), "depth": v.get("depth")}
                   for v in smap.get("visits") or []],
    }


def summary_lines(smap: dict | None, limit: int = 12) -> list[str]:
    """A few lines for an agent about to explore the site again: what was there before, and what never to open."""
    if not smap:
        return []
    pages = smap.get("pages") or []
    visited = [p for p in pages if p.get("captures")]
    lines = [f"Known from earlier visits to {smap.get('site')}: {len(pages)} page(s), {len(visited)} opened, "
             f"last {str(smap.get('last_seen') or '')[:10]} (read the whole map with cicada_site_map)."]
    for p in visited[:limit]:
        lines.append(f"   {p.get('kind')}: {p['url']} (last opened {str(p.get('last_visited') or '')[:10]}"
                     + (f", {p['outcome'].replace('_', ' ')} — never open it again" if p.get("outcome") in _WALLS
                        else "") + ")")
    return lines
