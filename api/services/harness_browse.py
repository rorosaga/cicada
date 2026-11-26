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
  own host. The session never makes an address.
* **A bounded number of opens** per question (:data:`MAX_OPENS`) and a few sessions per run (:data:`PER_RUN`).
* **Only when the person's own browser is already reachable** (:func:`daemon_ready`): the helper never starts a browser, so with no
  daemon the compartment is skipped, in words, and the question is worked without it. What would make it dependable is the app
  starting the browser session; that is the next slice.

Nothing a private session read is ever put in this session's brief and nothing this session read is put in another's; what it
returns goes only to Cicada's code as evidence items, checked like every other (`harness_agent.verify`, `harness_questions`).
"""
from __future__ import annotations

import json
import os
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
#: Sites whose profile pages tell the person viewed that someone looked: their links are never followed (a search page is read, a
#: profile only when the page already tracks it as a source).
NO_FOLLOW = ("linkedin",)
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


def connected_sites() -> dict[str, tuple[str, ...]]:
    """``{site: its domains}`` for the sites the person connected for reading with their own browser: ``agent_sites``, the saved lists
    (``x-likes`` is X), the YouTube and Substack lists. Empty when the master switch is off, when they turned off the use of their
    signed-in session, and for a site they said never to explore, a private workspace or a vendor's own host (`reading_hosts.classify`)."""
    if not reading_settings.agent_enabled() or not reading_settings.explore_signed_in():
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


def given_for(memory_path: Path, page_ids: tuple[str, ...], names: list[str], sites: dict[str, tuple[str, ...]], *,
              limit: int = MAX_GIVEN) -> list[Given]:
    """The addresses the session may open first: a tracked source on a connected site, then each connected site's own search page for
    the question's own name (the first name given: the page's title). At most ``limit``; never an address built from anything a
    session read."""
    domains = [d for ds in sites.values() for d in ds]
    out: list[Given] = []
    for url in tracked_urls(memory_path, page_ids):
        if read_browser.on_domain(read_browser._host(url), domains) and not read_browser.action_reason(url):
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
               max_opens: int = MAX_OPENS, loopback_for_test: bool = False) -> dict:
    """What the helper is granted for one question: written by this code only, read by the helper only. ``loopback_for_test`` is for
    Cicada's own tests and battery (pages on localhost); nothing a setting or a request says reaches it."""
    return {"v": 1, "domains": sorted({d for ds in sites.values() for d in ds}), "given": [{"url": g.url, "origin": g.origin} for g in given],
            "max_opens": max_opens, "no_follow": sorted({d for s in NO_FOLLOW for d in sites.get(s, ())}),
            "harness": harness, "loopback_for_test": bool(loopback_for_test)}


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


def daemon_ready(harness_env: dict | None = None, harness: str = "") -> tuple[bool, str]:
    """``(ready, why not)``: is the person's own browser-harness daemon already running and answering? Never starts one."""
    path = harness or harness_path()
    if not path:
        return False, "the browser harness is not installed"
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
            return False, "the browser did not answer in time"
    line = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    return (True, "") if line[0] == "ready" else (False, line[0].removeprefix("unavailable: ") or "no browser answered")


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
