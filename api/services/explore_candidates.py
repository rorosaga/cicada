"""Which saved sites an agent may explore (G166 exploring, design §1.2), and what the Explore sheet counts.

The candidates are the bank's **saved links** — pages already made by a save, a bookmark sync or an import, joined
through ``sources/url_index.json`` — minus, deterministically and with no fetch:

* what ``reading_hosts.classify`` never offers an agent: secrets and side effects, local hosts, AI apps' own pages,
  videos (the video queue owns them), papers, redirectors;
* **private workspaces** (docs, drive, notion, figma, slack…): the person's own documents, not sites;
* pages retired as junk, archived or dropped;
* the **walled families** (LinkedIn, X, Facebook, Instagram, TikTok, Reddit) unless the person turned that site on in
  Reading the web — the one place a walled read is allowed;
* sites the person marked **Never explore** (``reading_settings.never_explore``).

Exploring creates no page. The person's reason for a save (G191 ``saved_why`` on the link's episode, when that slice
has landed) steers the depth (D4: capture by default, deeper only where the why asks).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from api.services import bank_index, media_ingestor, reading_hosts, reading_settings, source_overview, video_state

#: Why a saved link is not offered, as the sheet counts it.
EXCLUSIONS = ("private", "secret", "local", "ai_app", "video", "paper", "redirector", "not_web", "walled", "never",
              "hidden")
_CLASS_REASON = {
    reading_hosts.CLASS_SIDE_EFFECT: "secret", reading_hosts.CLASS_LOCAL: "local",
    reading_hosts.CLASS_VENDOR: "ai_app", reading_hosts.CLASS_VIDEO: "video", reading_hosts.CLASS_PAPER: "paper",
    reading_hosts.CLASS_NEVER: "redirector", reading_hosts.CLASS_BAD: "not_web",
}
#: G191's answer keys → the depth they ask for (design §2.5). The deepest one asked wins.
WHY_DEPTH = {"design": "look", "product": "product", "technique": "read", "read_later": "capture", "someday": "capture"}
#: Typical wall time per site with one agent (design §6.1, capture depth), and the default number of agents.
SECONDS_PER_SITE = 35
DEFAULT_AGENTS = 4


@dataclass(frozen=True)
class SavedSite:
    key: str
    entity_id: str
    url: str
    title: str
    site: str
    origin: str | None = None
    folder: str | None = None
    saved_at: str | None = None
    why: dict | None = field(default=None, compare=False)
    excluded: str | None = None

    @property
    def depth(self) -> str:
        return depth_for(self.why)


def depth_for(why: dict | None) -> str:
    """D4: ``capture`` unless the person's reason asks for more — the look for "the design", the product's pages
    for "the product" or a project, the matching section for "a technique" — read from the reason ids and, since
    slice 2, the person's own words about the save (``explore_plan``; the claim adds their conversations)."""
    from api.services import explore_plan

    return explore_plan.depth_of(why)


def _why(fm: dict) -> dict | None:
    """G191's answer on the link's episode, read through the one optional field. G191 (branch feat/ask-why, not
    merged when this was written) stores it as the episode's ``saved_why`` frontmatter ``{reasons, project, text, at}``
    beside a ``## Why it was saved`` section, and serves it as ``GET /sources`` → ``items[].savedWhy``. ``reasons``
    are the stable ids ``design``, ``product``, ``technique``, ``read_later``; ``project`` is a project page id and
    ``text`` the person's words, separate fields. None when the field is absent, nobody was asked, or they dismissed
    the panel — the depth is then ``capture`` (D4)."""
    raw = fm.get("saved_why")
    if not isinstance(raw, dict):
        return None
    reasons = [str(r) for r in raw.get("reasons") or [] if isinstance(r, str) and r in WHY_DEPTH]
    out: dict = {"reasons": reasons}
    for name in ("project", "text", "at"):
        if isinstance(raw.get(name), str) and raw[name].strip():
            out[name] = raw[name].strip()
    return out if (reasons or out.get("project") or out.get("text")) else None


def excluded_reason(url: str, *, never: dict | None = None) -> str | None:
    """Why ``url`` is never offered for exploring, or None. Pure string work plus the person's settings."""
    verdict = reading_hosts.classify(url)
    if not verdict.ok:
        if verdict.cls == reading_hosts.CLASS_SIDE_EFFECT and reading_hosts.is_private_workspace(url):
            return "private"
        return _CLASS_REASON.get(verdict.cls, "not_web")
    site = verdict.site
    if site in (never if never is not None else reading_settings.never_explore()):
        return "never"
    if verdict.walled and not reading_settings.site_allowed(site):
        return "walled"
    return None


def saved_sites(memory_path: Path, *, include_excluded: bool = False) -> dict[str, SavedSite]:
    """Every saved link, keyed by its url-index key, in index order; excluded ones only when asked (each with why)."""
    memory_path = Path(memory_path)
    index = media_ingestor.load_url_index(memory_path)
    if not index:
        return {}
    pages = {f.stem: f.frontmatter or {} for f in bank_index.files(memory_path, "entities")}
    episodes = {f.stem: f.frontmatter or {} for f in bank_index.files(memory_path, "episodes")}
    never = reading_settings.never_explore()
    out: dict[str, SavedSite] = {}
    for raw_key, entry in index.items():
        if not isinstance(entry, dict) or entry.get("alias_of"):
            continue
        url = str(entry.get("url") or "")
        entity_id = str(entry.get("media_entity_id") or "")
        if not url or not entity_id:
            continue
        fm = pages.get(entity_id) or {}
        reason = None
        if str(fm.get("status", "active")) in source_overview.HIDDEN_STATUSES or \
                str(fm.get("enrichment_status") or "") == "junk":
            reason = "hidden"
        else:
            media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
            kind = media.get("kind") if isinstance(media.get("kind"), str) else None
            if video_state.is_video_page(entry.get("media_type"), url, kind):
                reason = "video"
            elif kind == "paper":
                reason = "paper"
            else:
                reason = excluded_reason(url, never=never)
        if reason is not None and not include_excluded:
            continue
        ep = episodes.get(str(entry.get("episode_id") or "")) or {}
        key = str(raw_key) if len(str(raw_key)) == 12 else media_ingestor.url_hash(url)
        out[key] = SavedSite(
            key=key, entity_id=entity_id, url=url, title=str(entry.get("title") or ""),
            site=reading_hosts.site_of(url), origin=str(ep.get("origin") or "") or None,
            folder=str(ep.get("folder") or "") or None,
            # The browser's own instant when G191's sync recorded one (``added_at``), else the save day.
            saved_at=str(ep.get("added_at") or entry.get("content_saved_at") or ep.get("saved_at") or "") or None,
            why=_why(ep), excluded=reason)
    return out


def explored_entities(memory_path: Path) -> set[str]:
    """Pages that have at least one capture record (``captures/<entity-id>/`` holds a file). ``captures/_sites``
    holds the site maps (``site_map``), never a page's captures: an entity id never starts with an underscore."""
    from api.services import site_captures

    root = Path(memory_path) / "captures"
    try:
        return {d.name for d in root.iterdir() if d.is_dir() and site_captures.ENTITY_RE.match(d.name)
                and any(d.glob("*.md"))}
    except OSError:
        return set()


def origin_label(origin: str | None) -> str:
    from api.services import bookmark_sync

    if not origin:
        return "Saved links"
    return bookmark_sync._BROWSER_LABEL.get(origin, origin)


def select(memory_path: Path, selection: dict | None) -> list[SavedSite]:
    """The sites a selection names, eligible ones only. ``selection``: ``scope`` = ``all`` | ``never_explored``,
    optional ``origins`` (browser origins, e.g. ``chrome-bookmark``), optional ``keys``."""
    selection = selection if isinstance(selection, dict) else {}
    sites = list(saved_sites(memory_path).values())
    origins = {str(o) for o in selection.get("origins") or [] if isinstance(o, str)}
    keys = {str(k) for k in selection.get("keys") or [] if isinstance(k, str)}
    if origins:
        sites = [s for s in sites if (s.origin or "saved") in origins]
    if keys:
        sites = [s for s in sites if s.key in keys]
    if str(selection.get("scope") or "all") == "never_explored":
        done = explored_entities(memory_path)
        sites = [s for s in sites if s.entity_id not in done]
    return sites


def estimate(count: int, depths: list[str] | None = None) -> dict:
    """The sheet's size, never a price (ruling 12): Light / Medium / Heavy plus minutes at the default four agents."""
    extra = sum(12 if d == "look" else 25 if d in ("product", "read") else 0 for d in depths or [])
    seconds = count * SECONDS_PER_SITE + extra
    minutes = math.ceil(seconds / DEFAULT_AGENTS / 60) if count else 0
    size = "light" if count <= 50 else "medium" if count <= 300 else "heavy"
    return {"size": size, "minutes": minutes, "agents": DEFAULT_AGENTS}


def overview(memory_path: Path) -> dict:
    """What the Explore sheet shows: eligible counts by browser, never explored, what is left out and why, and the
    run's size."""
    every = saved_sites(memory_path, include_excluded=True)
    eligible = [s for s in every.values() if s.excluded is None]
    done = explored_entities(memory_path)
    by_origin: dict[str, int] = {}
    for s in eligible:
        by_origin[s.origin or "saved"] = by_origin.get(s.origin or "saved", 0) + 1
    excluded: dict[str, int] = {}
    for s in every.values():
        if s.excluded is not None:
            excluded[s.excluded] = excluded.get(s.excluded, 0) + 1
    never = [s for s in eligible if s.entity_id not in done]
    return {
        "eligible": len(eligible), "neverExplored": len(never),
        "origins": [{"origin": o, "label": origin_label(None if o == "saved" else o), "count": n}
                    for o, n in sorted(by_origin.items(), key=lambda kv: (-kv[1], kv[0]))],
        "excluded": dict(sorted(excluded.items())),
        "estimate": estimate(len(eligible), [s.depth for s in eligible]),
        "estimateNeverExplored": estimate(len(never), [s.depth for s in never]),
    }
