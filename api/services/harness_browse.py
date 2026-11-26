"""The third compartment of Cicada's own agent: reading through the person's signed-in browser (ruling 84; G209).

The two compartments of the first slice never hold a browser, because a session that could open the person's mail or social
site AND fetch any address could be told, by text on any page it read, to send what it saw to whoever wrote that text. This
compartment has its **own session** that holds exactly one tool, ``Bash``, limited by a permission rule to one launcher that runs
:mod:`api.harness_tools.read_browser`; no search, no fetch, no file tool, no conversation copy. Its limits are in the helper's code
and in what the session holds, never in the prompt alone; this module is the code side that decides what the helper is *granted*:

* **Only sites the person connected** (:func:`connected_sites`): the sites they let an agent read with their own browser, the
  saved lists they asked an agent to keep current, resolved to domains here, behind the master switch and the "use my signed-in
  session" switch, minus a site they said never to explore, a private workspace and a vendor.
* **Only addresses that are given, never built** (:func:`given_for`): a source the page already tracks (ruling 54a: a page's Where
  to check is where a private person is learned about) on a connected site, and the connected site's own search page for the
  question's own name, built here from a per-site template. The helper adds the links of a page this run opened, on that page's
  own host, **only when the decoded path matches the site's allow pattern** (:data:`PROFILES`: a public profile or about page of an
  account; a site with no entry, and a site where viewing tells the person viewed, follows none). The session never makes an address.
* **No request leaves the site, and a page is read, never loaded** (the helper's browser-side interception, `read_browser`): the one document
  asked for is read and parsed for text, title and links and its request aborted; every other request of any kind is failed before it is
  sent, so nothing the site sent loads, renders or runs in the tab. The grant carries each connected site's domains and nothing else.
* **A bounded number of opens** per question (:data:`MAX_OPENS`) and a few sessions per run (:data:`PER_RUN`).
* **Only when the person's own browser is already reachable** (:func:`daemon_ready`): the helper never starts a browser, so with no
  daemon the compartment is skipped, in words, and the question is worked without it. What would make it dependable is the app
  starting the browser session; that is the next slice.

**What remains** (`mcp.md`, "What remains, said plainly"): which page is opened still carries up to log2(:data:`harness_browse.MAX_LINKS`) bits a followed
open (:data:`MAX_FOLLOWED` a question, :data:`PER_RUN` sessions a run: 10.3 bits a run at most), through per-account view data the site shows
the account's owner; a page built by its own script reads as what it declares about itself (title, description), not as its feed. Nothing the
session read ever reaches an address.

Nothing a private session read is ever put in this session's brief and nothing this session read is put in another's; what it
returns goes only to Cicada's code as evidence items, checked like every other (`harness_agent.verify`, `harness_questions`).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from api.harness_tools import read_browser
from api.services import reading_hosts, reading_settings

#: Opens a question may make in the person's browser, counting every attempt, and the sessions of this kind a run starts.
MAX_OPENS = 6
PER_RUN = 2
MAX_GIVEN = 6
#: A site's own search page for a name, one per site that has a stable one. The name is the question's own and is percent-encoded
#: here. A site with none (Instagram's search is not an address) is reached only through a source the page tracks.
SEARCH = {
    "x": "https://x.com/search?q={q}&f=user",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={q}",
    "reddit": "https://www.reddit.com/search/?q={q}&type=sr%2Cuser",
    "tiktok": "https://www.tiktok.com/search/user?q={q}",
    "pinterest": "https://www.pinterest.com/search/users/?q={q}",
    "substack": "https://substack.com/search/{q}",
    "goodreads": "https://www.goodreads.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
}
@dataclass(frozen=True)
class Profile:
    """What this compartment is FOR on one site: answering "who or what is this account or organisation" from its public profile or about
    page. ``patterns`` are regular expressions over the decoded path (no query, nothing encoded: `read_browser.follow_reason`); a path
    that fully matches one is a profile or about page of an account. **A pattern that carries the account's name in its address names that
    segment** ``(?P<name>...)`` (the handle or the slug): a link of an opened page is followed only through such a pattern, only when the
    question's own name is in that segment (folded) and never because of the link's text, which the page writes; a pattern with no name in
    it (a numeric id: ``/artist/<id>``) is a profile a tracked source may be, **never one a page's link may lead to**, unless ``host_named``
    says the name is the host's first label (an organisation's own subdomain). A first segment (or a name) in ``reserved`` is a feature of
    the site that looks like an account name: the second layer under the patterns, one list per site, which is longer than anything it
    ought to need. ``params`` are the only query keys a tracked source of this site may carry (none: a source with a query is not given).
    ``viewer_visible`` marks a site where merely viewing a profile or a story tells the person viewed (or counts toward a list they see):
    **nothing there is followed, and a profile opens only as an address the person's own page already tracks as a source**.
    ``client_rendered`` marks a site whose page is built by its own script: the page is read here with no script (by its text
    and by what it declares about itself, its title and description), so what is read there is the declared preview, not the rendered feed.
    The person's own private areas
    (messages, chat, bookmarks, lists, an assistant, history, feeds, notifications, settings, stories, explore, home, search) are refused by
    the helper's second layer whatever the table says; this compartment never reads the person's lists (ruling 30; saves are another reader's)."""
    patterns: tuple[str, ...]
    reserved: tuple[str, ...] = ()
    viewer_visible: bool = False
    host_named: bool = False
    client_rendered: bool = False
    params: tuple[str, ...] = ()


#: The person's own areas and the features of a site that look like an account name, in the first path segment, for every site: a layer under
#: each site's own list (a site lists more below).
_COMMON_RESERVED = (
    "home", "explore", "search", "notifications", "notification", "messages", "message", "messaging", "chat", "chats", "inbox", "dm", "dms",
    "direct", "conversations", "conversation", "settings", "setting", "preferences", "prefs", "account", "accounts", "bookmarks", "bookmark",
    "saved", "lists", "list", "likes", "history", "library", "feed", "feeds", "stories", "story", "reels", "following", "followers", "friends",
    "assistant", "assistants", "grok", "ai", "copilot", "bot", "compose", "create", "new", "submit", "upload", "drafts", "activity", "login",
    "logout", "signin", "signup", "register", "oauth", "intent", "share", "help", "support", "about", "tos", "privacy", "legal", "ads", "business",
    "premium", "jobs", "communities", "i", "me", "my", "mynetwork", "watchlater", "playlist", "playlists", "subscriptions", "purchases",
    "wallet", "billing", "admin", "api", "static", "download", "downloads", "flow", "hashtag", "topics", "trending", "foryou", "live", "shop",
    "watch", "videos", "marketplace", "groups", "events", "gaming", "pages", "pin", "ideas", "today", "verified", "rules")
_X_RESERVED = _COMMON_RESERVED + ("lists", "i", "who_to_follow", "connect_people", "display", "creators", "subscriptions", "monetization",
                                  "safety", "directory", "media_studio", "tweet", "status", "analytics", "topics", "moments")
_REDDIT_RESERVED = _COMMON_RESERVED + ("all", "popular", "friends", "mod", "random", "randnsfw", "prefs", "wiki", "coins",
                                       "avatar", "settings", "chat", "message", "submit", "saved", "upvoted", "downvoted", "hidden", "submitted",
                                       "overview", "comments", "gilded")
_PINTEREST_RESERVED = _COMMON_RESERVED + ("news_hub", "_", "pin-builder", "idea-pin-builder", "homefeed", "resource", "offsite", "boards",
                                          "following", "shopping", "settings", "business")
_SUBSTACK_RESERVED = tuple(w for w in _COMMON_RESERVED if w != "about") + ("sign-in", "subscribe", "dashboard", "publish", "notes", "chat", "inbox", "settings", "activity")
_YOUTUBE_RESERVED = _COMMON_RESERVED + ("feed", "playlist", "results", "shorts", "reporthistory", "account", "premium", "gaming", "live")
_GOODREADS_RESERVED = _COMMON_RESERVED + ("user", "review", "shelf", "friend", "quotes", "book", "group", "notifications", "message", "friends")
_META_RESERVED = _COMMON_RESERVED + ("policies", "recover", "dialog", "adsmanager", "fundraisers", "memories", "reel", "profile.php", "tv", "p",
                                     "accounts", "legal", "stories", "reels", "explore", "direct")
#: Per-site allow patterns, beside the per-site search templates. A site with no entry follows no link at all. Marked **viewer_visible**
#: and why: LinkedIn (a profile view is shown to the viewed person and counts toward their "who viewed"), Instagram and Facebook (a
#: story view is listed to the person whose story it is, and a profile open can start one), TikTok (profile views are a list its
#: owner may see). **No link is followed where the address carries no name** (Spotify's `/artist/<id>`, YouTube's `/channel/UC...`, a
#: Goodreads author with no slug): such a profile is read only as a source the page already tracks. ``client_rendered`` is what each
#: site is known to be (its body built by script, so a no-script read shows its declared title and description); it is a note, not
#: measured live: the live sites are never opened here.
PROFILES: dict[str, Profile] = {
    "x": Profile((r"/(?P<name>[A-Za-z0-9_]{1,15})",), _X_RESERVED, client_rendered=True),
    "reddit": Profile((r"/(?:user|u)/(?P<name>[A-Za-z0-9_-]{3,20})", r"/r/(?P<name>[A-Za-z0-9_]{2,21})"), _REDDIT_RESERVED, client_rendered=True),
    "pinterest": Profile((r"/(?P<name>[a-z0-9_]{3,30})",), _PINTEREST_RESERVED, client_rendered=True),
    "substack": Profile((r"/@(?P<name>[A-Za-z0-9_.-]{2,40})", r"/about"), _SUBSTACK_RESERVED, host_named=True),
    "youtube": Profile((r"/@(?P<name>[A-Za-z0-9_.-]{3,30})(?:/about)?", r"/channel/UC[A-Za-z0-9_-]{22}(?:/about)?"), _YOUTUBE_RESERVED, client_rendered=True),
    "goodreads": Profile((r"/author/show/\d{1,12}(?:\.(?P<name>[A-Za-z0-9_-]{1,60}))?",), _GOODREADS_RESERVED),
    "spotify": Profile((r"/artist/[A-Za-z0-9]{22}",), _COMMON_RESERVED, client_rendered=True),
    "linkedin": Profile((r"/in/(?P<name>[A-Za-z0-9-]{3,100})", r"/company/(?P<name>[A-Za-z0-9-]{2,100})(?:/about)?"), _COMMON_RESERVED + ("feed", "mynetwork"),
                        viewer_visible=True, client_rendered=True),
    "instagram": Profile((r"/(?P<name>[A-Za-z0-9._]{1,30})",), _META_RESERVED, viewer_visible=True, client_rendered=True),
    "facebook": Profile((r"/(?P<name>[A-Za-z0-9.]{5,50})",), _META_RESERVED, viewer_visible=True, client_rendered=True),
    "tiktok": Profile((r"/@(?P<name>[A-Za-z0-9_.]{2,24})",), _COMMON_RESERVED, viewer_visible=True, client_rendered=True),
}
#: A site where viewing tells the person viewed: kept as the names of such sites (the same set, derived).
NO_FOLLOW = tuple(sorted(k for k, v in PROFILES.items() if v.viewer_visible))
#: The shapes a tracked source of a site with an entry may take besides its profile patterns: none. A source that is not a profile or about
#: page of an account (a post, a feed, a list) is not given: the person's page tracks it for another reader.
MAX_FOLLOWED = 2

#: A site key's domains when it is not a walled family (those are `reading_hosts.WALLED_DOMAINS`).
EXTRA_DOMAINS = {"youtube": ("youtube.com",), "substack": ("substack.com",), "spotify": ("spotify.com",),
                 "goodreads": ("goodreads.com",), "pinterest": ("pinterest.com",)}
#: What a grant file may carry for the harness: where its daemon and config are. Nothing else is copied from a caller.
HARNESS_ENV_KEYS = ("BH_HOME", "BH_RUNTIME_DIR", "BH_TMP_DIR", "BU_NAME", "BU_CDP_URL", "BH_RUNTIME_DIR_SHARED")


@dataclass(frozen=True)
class Given:
    url: str
    origin: str          # "source" (a page's tracked source) | "search" (a site's own search page for the question's name)


# --------------------------------------------------------------------------- which sites


def site_domains(site: str) -> tuple[str, ...]:
    return reading_hosts.WALLED_DOMAINS.get(site) or EXTRA_DOMAINS.get(site) or (site,)


def signed_in_switch() -> bool:
    """This device's switch for this compartment alone (``CICADA_HARNESS_SIGNED_IN``, beside the agent's own ``CICADA_HARNESS_AGENT``;
    on by default, ruling 84), **read fresh** every time it is asked: a person who turns it off stops the next session, the agent's
    other compartments untouched. A settings file that cannot be read counts as off."""
    try:
        from api import config

        return bool(config.Settings().harness_signed_in)
    except Exception:  # noqa: BLE001 - an unreadable setting is never "on"
        return False


def connected_sites() -> dict[str, tuple[str, ...]]:
    """``{site: its domains}`` for the sites the person connected for reading with their own browser: ``agent_sites``, the saved lists
    (``x-likes`` is X), the YouTube and Substack lists. Empty when the master switch is off, when they turned off the use of their
    signed-in session, and for a site they said never to explore, a private workspace or a vendor's own host (`reading_hosts.classify`)."""
    if not signed_in_switch() or not reading_settings.agent_enabled() or not reading_settings.explore_signed_in():
        return {}
    keys = set(reading_settings.allowed_sites())
    keys |= {k.split("-")[0] for k in reading_settings.saved_lists()}
    if reading_settings.youtube_lists():
        keys.add("youtube")
    if reading_settings.substack_lists():
        keys.add("substack")
    never = set(reading_settings.never_explore())
    out: dict[str, tuple[str, ...]] = {}
    for site in sorted(keys - never):
        domains = tuple(d for d in site_domains(site) if reading_hosts.classify(f"https://{d}/").ok)
        if domains:
            out[site] = domains
    return out


# --------------------------------------------------------------------------- which addresses


def on_connected(url: str, domains) -> bool:
    """Is ``url`` an address on one of the connected sites' domains (a dot boundary, never a substring)?"""
    return read_browser.on_domain(read_browser._host(url), list(domains))


def search_url(site: str, name: str) -> str:
    template = SEARCH.get(site)
    q = " ".join(str(name or "").split())[:80]
    return template.format(q=urllib.parse.quote(q, safe="")) if template and q else ""


def tracked_urls(memory_path: Path, page_ids: tuple[str, ...]) -> list[str]:
    """The addresses the pages already track as where to check (the person's own, one they took, one Cicada's read confirmed):
    never a proposal nobody took, an "only I know" note, a dead source or one from the person's LinkedIn connections list."""
    from api.services import bank_index, fact_sources, linkedin_people, source_refresh

    out: list[str] = []
    for page_id in page_ids:
        entry = bank_index.file(Path(memory_path), "entities", f"{page_id}.md")
        for source in fact_sources.as_sources((entry.frontmatter or {}).get("sources") if entry else None):
            ref = str(source.get("ref") or "").strip()
            if (not ref.startswith(("http://", "https://")) or fact_sources.is_proposed(source) or linkedin_people.from_connections(source)
                    or not source_refresh.tracked(source) or source_refresh.dead(source)):
                continue
            if ref not in out:
                out.append(ref)
    return out


def site_key_of(host: str) -> str:
    """The table's key for a host (``x`` for ``x.com``), or ``""``."""
    for key in PROFILES:
        if read_browser.on_domain(host, list(site_domains(key))):
            return key
    return ""


def source_reason(url: str) -> str:
    """Why a tracked source is not given to the session (``""`` when it is): not an address the person's own browser should open for
    this compartment. Never an action or a private area (the helper's second layer, decoded), and on a site with an entry in
    :data:`PROFILES` only a public profile or about page of an account (the same patterns a followed link must match, the first segment and
    the name segment not a feature of the site): a post, a feed, a list or an address of the person's own areas is another reader's, not
    this one's. **A source with a query string is not given** unless the site's entry names the parameter (``Profile.params``)."""
    if read_browser.action_reason(url):
        return "an action or a private area"
    key = site_key_of(read_browser._host(url))
    if not key:
        return ""
    parts = urllib.parse.urlsplit(url)
    profile = PROFILES[key]
    if parts.query or "?" in url:
        keys = {k.lower() for k, _v in urllib.parse.parse_qsl(read_browser.decoded(parts.query), keep_blank_values=True)}
        if not keys or not keys <= {p.lower() for p in profile.params}:
            return "a query string the site's profile address does not use"
    path = read_browser.decoded(parts.path).rstrip("/") or "/"
    reserved = {r.lower() for r in profile.reserved}
    if path.split("/")[1:2] and path.split("/")[1].lower() in reserved:
        return "a feature of the site, not an account"
    match = next((m for m in (re.fullmatch(p, path, re.I | re.A) for p in profile.patterns) if m), None)
    if match is None:
        return "not a profile or about page"
    if "name" in match.groupdict() and (match.group("name") or "").lower() in reserved:
        return "a feature of the site, not an account"
    return ""


def given_for(memory_path: Path, page_ids: tuple[str, ...], names: list[str], sites: dict[str, tuple[str, ...]], *,
              limit: int = MAX_GIVEN) -> list[Given]:
    """The addresses the session may open first: a tracked source on a connected site (that is a public profile or about page, never a
    private area), then each connected site's own search page for the question's own name (the first name given: the page's title).
    At most ``limit``; never an address built from anything a session read."""
    domains = [d for ds in sites.values() for d in ds]
    out: list[Given] = []
    for url in tracked_urls(memory_path, page_ids):
        if read_browser.on_domain(read_browser._host(url), domains) and not source_reason(url):
            out.append(Given(url, "source"))
    name = next((n for n in names if " ".join(str(n or "").split())), "")
    for site in sites:
        url = search_url(site, name)
        if url:
            out.append(Given(url, "search"))
    return out[:limit]


# --------------------------------------------------------------------------- the grant, the launcher, the daemon


def harness_path() -> str:
    """The browser harness's own program, resolved here (a launchd backend's PATH is short): the PATH's, else where it installs."""
    found = shutil.which("browser-harness")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "browser-harness", Path("/opt/homebrew/bin/browser-harness"),
                      Path("/usr/local/bin/browser-harness")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


def grant_dict(sites: dict[str, tuple[str, ...]], given: list[Given], *, harness: str = "", harness_env: dict | None = None,
               max_opens: int = MAX_OPENS, loopback_for_test: bool = False, names: list[str] | None = None, timeout_s: float | None = None) -> dict:
    """What the helper is granted for one question: written by this code only, read by the helper only. ``loopback_for_test`` (and the
    shorter ``timeout_s`` it alone honours) is for Cicada's own tests and battery (pages on localhost); nothing a setting or a request
    says reaches it. ``sites`` lists each connected site's domains; ``follow`` carries, for each connected site
    whose entry in :data:`PROFILES` allows following, the patterns a followed link's decoded path must match (a site with no entry, or
    one where viewing tells the person viewed, has none: nothing is followed); ``names`` are what the question is about."""
    per_site = []
    follow = []
    for site, domains in sites.items():
        entry = PROFILES.get(site)
        per_site.append({"site": site, "domains": sorted(domains)})
        followable = [p for p in entry.patterns if "(?P<name>" in p or entry.host_named] if entry is not None else []
        if entry is not None and not entry.viewer_visible and followable:         # no name in the address, nothing to follow to
            follow.append({"domains": sorted(domains), "patterns": followable, "reserved": list(entry.reserved), "host_named": entry.host_named})
    return {"v": 3, "domains": sorted({d for ds in sites.values() for d in ds}), "sites": per_site, "follow": follow,
            "given": [{"url": g.url, "origin": g.origin} for g in given], "max_opens": max_opens, "max_followed": MAX_FOLLOWED,
            "names": [" ".join(str(n).split())[:80] for n in (names or []) if str(n).strip()][:3],
            "harness": harness, "loopback_for_test": bool(loopback_for_test),
            **({"timeout_s": float(timeout_s)} if timeout_s else {})}


def launcher_text(grant_path: str, state_path: str, harness_env: dict | None = None) -> str:
    """The one program the session may run: a shell script that sets the grant and the state paths (so no caller's environment can) and
    runs the helper under the interpreter that runs Cicada. The permission rule names this file."""
    env = {k: v for k, v in (harness_env or {}).items() if k in HARNESS_ENV_KEYS and isinstance(v, str)}
    lines = ["#!/bin/sh", f"export CICADA_BROWSE_GRANT={shlex.quote(grant_path)}", f"export CICADA_BROWSE_STATE={shlex.quote(state_path)}"]
    lines += [f"export {k}={shlex.quote(v)}" for k, v in env.items()]
    lines.append(f"exec {shlex.quote(sys.executable)} {shlex.quote(str(Path(read_browser.__file__).resolve()))} \"$@\"")
    return "\n".join(lines) + "\n"


@dataclass
class Setup:
    """One session's browser files, in the session's own private folder: a launcher, a grant (read-only to the session's tools: it holds
    no file tool), the state the helper keeps."""
    launcher: str
    grant: str
    state: str
    harness_env: dict


def write_setup(base: Path, grant: dict, harness_env: dict | None = None) -> Setup:
    """Write the launcher (0700), the grant (0600) and an empty state into ``base`` (made by `harness_files.make_scratch`)."""
    grant_path, state_path, launcher = base / "browse-grant.json", base / "browse-state.json", base / "rb"
    grant_path.write_text(json.dumps(grant), encoding="utf-8")
    os.chmod(grant_path, 0o600)
    state_path.write_text("{}", encoding="utf-8")
    os.chmod(state_path, 0o600)
    launcher.write_text(launcher_text(str(grant_path), str(state_path), harness_env), encoding="utf-8")
    os.chmod(launcher, 0o700)
    return Setup(str(launcher), str(grant_path), str(state_path), dict(harness_env or {}))


def daemon_probe(harness_env: dict | None = None, harness: str = "") -> tuple[bool, str, str]:
    """``(ready, why not, the daemon's name)``: is the person's own browser-harness daemon already running and answering, and under
    which name (``BU_NAME``, ``default`` when unset)? Never starts one. The name goes in the audit: on a machine where other agents run
    a daemon of the default name may be attached to a scratch or test browser, which this cannot tell apart; it only says which answered."""
    path = harness or harness_path()
    if not path:
        return False, "the browser harness is not installed", ""
    with tempfile.TemporaryDirectory(prefix="cicada-browse-probe-") as tmp:
        grant_file = Path(tmp) / "grant.json"
        grant_file.write_text(json.dumps({"harness": path}), encoding="utf-8")
        env = dict(os.environ)
        env.update({k: v for k, v in (harness_env or {}).items() if k in HARNESS_ENV_KEYS})
        env[read_browser.GRANT_ENV] = str(grant_file)
        try:
            proc = subprocess.run([sys.executable, str(Path(read_browser.__file__).resolve()), "status"], capture_output=True, text=True,
                                  timeout=25.0, env=env)
        except (OSError, subprocess.TimeoutExpired):
            return False, "the browser did not answer in time", ""
    lines = (proc.stdout or "").strip().splitlines() or [""]
    name = next((ln.removeprefix("daemon: ").strip()[:40] for ln in lines if ln.startswith("daemon: ")), "")
    return (True, "", name or "default") if lines[0] == "ready" else (False, lines[0].removeprefix("unavailable: ") or "no browser answered", "")


def daemon_ready(harness_env: dict | None = None, harness: str = "") -> tuple[bool, str]:
    """``(ready, why not)`` of :func:`daemon_probe`."""
    ready, why, _name = daemon_probe(harness_env, harness)
    return ready, why


def close_tabs(setup: Setup) -> None:
    """Close every tab this session's helper opened (never one it did not). Called when the session ends, whatever way; the reaper does
    the same for a backend that died."""
    env = dict(os.environ)
    env.update({k: v for k, v in setup.harness_env.items() if k in HARNESS_ENV_KEYS})
    env[read_browser.GRANT_ENV], env[read_browser.STATE_ENV] = setup.grant, setup.state
    try:
        subprocess.run([sys.executable, str(Path(read_browser.__file__).resolve()), "close"], capture_output=True, text=True,
                       timeout=45.0, env=env)
    except (OSError, subprocess.TimeoutExpired):
        pass


def opened_addresses(state_path: str) -> list[dict]:
    """The helper's own record of what it opened, in order: ``[{url, host, how}]`` (``how``: source, search or followed)."""
    try:
        data = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [o for o in data.get("opens", []) if isinstance(o, dict)] if isinstance(data, dict) else []
