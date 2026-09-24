"""Chrome's open tab groups — the backend half (round 4; G160's first slice; decisions addendum 3).

A named, coloured group of open tabs is what the person is working on right now — more current than a bookmark, and
still an intentional act: they made the group. The APP reads Chrome's `Sessions/` file (SNSS commands 25 and 27 plus
each member tab's current page), only after the person turned on this channel's own switch, and posts the projection
here; the backend never opens `~/Library` (the Awake rail). Incognito windows are never in those files, and page
contents are never read — a group's title, its colour, and its tabs' titles and links, nothing else (R-SR6).

Each group is ONE snapshot episode through the G20 stager, keyed
`tab-group:<browser>:<profile>:<identity>` (R-SR4): Chrome's saved guid when the group is saved, else a hash of its
folded title and colour, else (an unnamed group) its session token. A changed title, colour or tab list rewrites the
episode in place and re-queues it; a group no longer open is tombstoned — only for the browser and profile the
request named — and un-tombstoned if it comes back (R-SR5). `collapsed` never reaches the body, so folding a group
never re-queues it. Everything is scrubbed before it is hashed (R-N3), the frontmatter title too.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from api.services import episode_scrub, episode_staging, text_fold

#: The browsers whose session files the app reads (R-SR3). Brave, Comet and Dia likely share Chrome's session code
#: and Vivaldi's stacks are its own — each waits for G160's check on a real install.
BROWSERS: dict[str, str] = {"chrome": "Chrome"}
#: `components/tab_groups/tab_group_color.h` — the app maps the enum to these words.
COLORS = ("grey", "blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange")
SOURCE_PREFIX = "tab-group:"
SCRUB_WRITER = "tab-groups"
MAX_GROUPS = 200
MAX_TABS = 100
MAX_TABS_PER_REQUEST = 5000
TITLE_CAP = 300
URL_CAP = 2000
#: Chrome's profile directory names — never a path (a profile is joined into nothing, but the id must stay an id).
PROFILE_RE = re.compile(r"^(Default|Profile \d{1,3})$")


class PayloadError(ValueError):
    """A request the backend cannot trust — answered 422, nothing staged."""


def channel_id(browser: str) -> str:
    return f"{browser}-tab-groups"


def origin_for(browser: str) -> str:
    return f"{browser}-tab-group"


def _clip(value, cap: int = TITLE_CAP) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def _url(value) -> str | None:
    """A web page only: scheme, host, path and query — a query is often the page itself (`watch?v=`), and the scrub
    redacts a token in one; the fragment goes (R-SR6)."""
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))[:URL_CAP]


def _color(value) -> str:
    word = str(value or "").strip().lower()
    return word if word in COLORS else "grey"


def identity(group: dict) -> str:
    """R-SR4 — what makes "the same group" across a restart."""
    guid = str(group.get("saved_guid") or group.get("savedGuid") or "").strip()
    if guid:
        return "saved:" + guid[:64]
    title = " ".join(text_fold.words(group.get("title")))
    if title:
        digest = hashlib.sha256(f"{title}|{_color(group.get('color'))}".encode("utf-8")).hexdigest()[:12]
        return "named:" + digest
    return "token:" + str(group.get("key") or "")[:32]


def body_for(title: str, color: str, browser: str, tabs: list[tuple[str, str]], total: int) -> str:
    lines = [f"# Tab group: {title or 'Unnamed group'}", "",
             f"**Browser:** {BROWSERS[browser]}", f"**Colour:** {color}", f"**Open tabs:** {total}", ""]
    lines += [f"- {name or url} — {url}" for name, url in tabs]
    if total > len(tabs):
        lines.append(f"- …and {total - len(tabs)} more tabs")
    return "\n".join(lines)


def sync(memory_path: Path, payload: dict, *, bank: str | None = None) -> dict:
    """Stage one snapshot of a browser profile's open groups. `payload` is the request with snake_case keys. Returns
    the counts, the number of groups and tabs kept (for the channel row), and the bank-relative paths to commit."""
    browser = str(payload.get("browser") or "").strip().lower()
    if browser not in BROWSERS:
        raise PayloadError(f"tab groups are read from {', '.join(BROWSERS)} only")
    profile = str(payload.get("profile") or "Default").strip()
    if not PROFILE_RE.match(profile):
        raise PayloadError("profile must be Chrome's own profile folder name")
    prefix = f"{SOURCE_PREFIX}{browser}:{profile}:"
    drafts: list[episode_staging.EpisodeDraft] = []
    posted: set[str] = set()
    scrubbed = tabs_total = 0
    for group in (payload.get("groups") or [])[:MAX_GROUPS]:
        tabs = [(_clip(t.get("title")), url) for t in (group.get("tabs") or [])
                if (url := _url(t.get("url")))]
        if not tabs:
            continue   # a group of chrome:// pages says nothing about the person's work
        sid = prefix + identity(group)
        if sid in posted:
            sid = f"{sid}#{str(group.get('key') or '')[:8]}"
        title = _clip(group.get("title"))
        color = _color(group.get("color"))
        heading, n = episode_scrub.scrub(f"Tab group: {title or 'Unnamed group'}")
        scrubbed += n
        drafts.append(episode_staging.EpisodeDraft(
            title=heading, source_id=sid, source="tab-group", origin=origin_for(browser),
            body=body_for(title, color, browser, tabs[:MAX_TABS], total=len(tabs)),
            extra={"browser": browser, "profile": profile, "tab_group_color": color},
            writer=SCRUB_WRITER))
        posted.add(sid)
        tabs_total += len(tabs)
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    with episode_staging.STAGE_LOCK:
        index, _ = episode_staging.scan(episodes_dir)
        gone = sorted(sid for sid, entry in index.items()
                      if sid.startswith(prefix) and sid not in posted and not entry.fm.get("source_deleted_at"))
        result = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=gone, bank=bank)
    episode_scrub.record(SCRUB_WRITER, scrubbed, bank=bank)
    return {"created": result.created, "updated": result.updated, "unchanged": result.skipped,
            "tombstoned": result.tombstoned, "groups": len(drafts), "tabs": tabs_total, "paths": list(result.paths)}
