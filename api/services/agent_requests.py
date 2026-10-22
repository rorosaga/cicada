"""Agent requests (G205): an agent asks the person for something only they can do — today, to sign in to a site in
their own browser so the agent can read a page — as one Inbox kind, ``agent_request``, and a Mac notification.

**Where:** ``$CICADA_HOME/agent_requests/<bank>.json``, machine-wide and never in a bank, beside the reading asks it
grows from (``reading_asks``' precedent: a login wall is stored and shown at once, with no bank write, no commit and no
Sleep gate). Two kinds of process write it (the backend and each stdio MCP server), so every write is
read-modify-write under an ``fcntl.flock`` and lands by temp file plus ``os.replace``. Its mtime folds into the
``inbox`` sync component, so the app's Inbox refreshes over SSE the moment a request lands.

**A row** is ``{id, kind, agent, site, reason, created_at, url_hash?}``: ``agent`` is a catalog way id
(``agent_catalog``; its name and logo are joined at read), ``site`` a display host, ``reason`` the agent's own short
words (scrubbed, at most :data:`MAX_REASON` characters) or Cicada's fixed sentence. No URL, no page title, no episode
text. One open request per (agent, kind, site, reason) — asking again refreshes nothing and adds nothing.

**Rules (G205 constraints):** a request never settles, reorders or changes a belief; it is never asked in a
conversation (``mcp_tools.APP_ONLY_INBOX_KINDS``: ``cicada_check_nudges`` never lists it and an agent cannot resolve
it); it never asks the agent to sign in — the agent is told to stop and move on; it resolves only on the person's tap:
``done`` (I signed in — the site's ``needs_login`` pause lifts, as the Reading settings' "try again" does) or
``dismiss``. Rows expire after :data:`EXPIRES_AFTER_DAYS` (in memory at read; persisted only inside a write).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import agent_catalog, episode_scrub
from api.services.auth import cicada_home

KIND = "agent_request"
KINDS = ("sign_in",)
MAX_REASON = 160
MAX_ROWS = 100
EXPIRES_AFTER_DAYS = 14
ID_RE = re.compile(r"^req-[a-f0-9]{8}$")
_SITE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$")
ACTIONS = ("done", "dismiss")


def _path(memory_path: Path) -> Path:
    from api.services import reading_asks

    return cicada_home() / "agent_requests" / f"{reading_asks.bank_slug(memory_path)}.json"


def mtime(memory_path: Path) -> float | None:
    """The file's mtime, or ``None`` when there has never been a request in this bank (so a bank with none keeps the
    inbox ETag it had before G205)."""
    try:
        return _path(memory_path).stat().st_mtime
    except OSError:
        return None


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _alive(row: dict, now: datetime) -> bool:
    try:
        made = datetime.fromisoformat(str(row.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return now - made < timedelta(days=EXPIRES_AFTER_DAYS)


def _read(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("requests") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict) and ID_RE.match(str(r.get("id") or ""))] if isinstance(rows, list) else []


@contextmanager
def _locked(memory_path: Path):
    path = _path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.parent / f".{path.name}.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield path
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _write(path: Path, rows: list[dict]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".requests-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"v": 1, "requests": rows[-MAX_ROWS:]}, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def clean_reason(reason) -> str | None:
    text = " ".join(str(reason or "").split())
    if not text:
        return None
    text = episode_scrub.scrub(text)[0]
    return text[:MAX_REASON].rstrip()


def clean_site(site) -> str | None:
    host = str(site or "").strip().lower().removeprefix("www.")
    return host if _SITE_RE.match(host) else None


def ask(memory_path: Path, *, agent: str | None, site: str, reason: str | None = None, kind: str = "sign_in",
        url_hash: str | None = None, now: datetime | None = None) -> dict | None:
    """File one request (or find the open one it repeats). ``None`` when the site is not a host or the kind unknown —
    the caller's own answer to the agent stands either way. Never raises on a full or unreadable file."""
    if kind not in KINDS:
        return None
    host = clean_site(site)
    if host is None:
        return None
    agent = agent if agent and agent_catalog.way(agent) else agent_catalog.OTHER
    words = clean_reason(reason)
    moment = _now(now)
    with _locked(memory_path) as path:
        rows = [r for r in _read(path) if _alive(r, moment)]
        for row in rows:
            if (row.get("agent"), row.get("kind"), row.get("site"), row.get("reason")) == (agent, kind, host, words):
                return row
        row = {"id": f"req-{secrets.token_hex(4)}", "kind": kind, "agent": agent, "site": host, "reason": words,
               "created_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if url_hash and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", url_hash):
            row["url_hash"] = url_hash
        rows.append(row)
        _write(path, rows)
        return row


def open_requests(memory_path: Path, *, now: datetime | None = None) -> list[dict]:
    moment = _now(now)
    return [r for r in _read(_path(memory_path)) if _alive(r, moment)]


def get(memory_path: Path, request_id: str) -> dict | None:
    return next((r for r in open_requests(memory_path) if r.get("id") == request_id), None)


def is_request_id(item_id: str) -> bool:
    return bool(ID_RE.match(item_id or ""))


def _agent_label(agent: str) -> str:
    way = agent_catalog.way(agent)
    return way.label if way is not None and agent != agent_catalog.OTHER else "An agent"


def notification(row: dict) -> dict:
    """What the app posts as a Mac notification: ids and the agent's own words, never episode text (G205)."""
    who = _agent_label(str(row.get("agent") or ""))
    reason = row.get("reason")
    body = f"{who} is asking you to sign in to {row['site']}" + (f", {reason}" if reason else "") + "."
    return {"id": row["id"], "title": f"{who} needs you to sign in", "body": body,
            "openUrl": f"https://{row['site']}"}


def wire(row: dict) -> dict:
    agent = str(row.get("agent") or agent_catalog.OTHER)
    umbrella = agent_catalog.umbrella_of(agent)
    return {"kind": row.get("kind"), "agent": agent, "agentName": _agent_label(agent),
            "umbrella": umbrella.id if umbrella is not None else None,
            "logo": umbrella.logo if umbrella is not None else None,
            "site": row.get("site"), "reason": row.get("reason"), "createdAt": row.get("created_at"),
            "notification": notification(row)}


def as_inbox_item(row: dict) -> dict:
    """The ``InboxItem`` fields for one request. Priority 1.0: requests sit above questions (G205)."""
    info = wire(row)
    note = info["notification"]
    return {"id": row["id"], "kind": KIND, "required_input": "choice", "status": "pending", "priority": 1.0,
            "title": note["title"], "body": note["body"], "question": note["body"],
            "options": [{"key": "done", "label": "I signed in"}, {"key": "dismiss", "label": "Not now"}],
            "created_date": str(row.get("created_at") or "")[:10], "allow_other": False, "allow_defer": False,
            "request": info}


def resolve(memory_path: Path, request_id: str, action: str) -> dict | None:
    """The person's tap. ``done`` lifts the site's sign-in pause so the agent tries again; ``dismiss`` only closes
    the request. ``None`` when there is no such open request. Never a bank write."""
    if action not in ACTIONS:
        raise ValueError(f"An agent request takes optionKey 'done' or 'dismiss' — got {action!r}.")
    with _locked(memory_path) as path:
        rows = _read(path)
        row = next((r for r in rows if r.get("id") == request_id), None)
        if row is None:
            return None
        _write(path, [r for r in rows if r.get("id") != request_id])
    if action == "done" and row.get("kind") == "sign_in":
        try:
            from api.services import reading_hosts, reading_queue

            reading_queue.resume_site(memory_path, reading_hosts.site_of(row["site"]))
        except Exception:  # noqa: BLE001 — the request is closed either way; a pause also ages out on its own
            pass
    return {"status": "resolved", "id": request_id, "action": action}
