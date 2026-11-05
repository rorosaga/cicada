"""Linear — the issues the person created or holds, and the discussion on them, read through a sign-in (ROR-115).

The connector is built on ``tier2`` (a normal capture path: ``episode_staging``, scrub, one writer, a tombstone for
nothing it cannot see, no model at capture) and ``linear_mcp`` (the browser sign-in and the read-only MCP session).
Nothing is asked for or pasted. Nothing is ever written to Linear: the session can call ``whoami``, ``list_issues``
and ``list_comments`` and nothing else (``linear_mcp.ALLOWED_TOOLS``), on Linear's ``/mcp/readonly`` endpoint.

**What is read.** The issues the person *created* and the issues *assigned to* them (two ``list_issues`` filters,
``"me"``), newest edit first, each with its description and its comments (``list_comments``), one episode per issue
keyed ``linear:<issue id>``. Every issue edited in the last :data:`REREAD_DAYS` days is read again each sync, because
Linear's listing filters on the issue's own edit time and a new comment need not move it; an unchanged thread is a
hash skip in the stager. A comment on an issue that has been quiet for longer than that is picked up when the issue
itself next changes (said in ``network.md``). An issue archived or deleted in Linear is not detected: it is kept as
it was (a listing that omits archived issues says nothing about them). The first walk is capped per sync and carries on
from Linear's own cursor.

**Whose words — decided by the API's own fields, and never in the person's favour on a guess.** An issue's text or a
comment is stored as a turn of the thread. :func:`attribute` decides each turn's marker:

* ``assistant`` when the record says an agent wrote it — a comment with ``onBehalfOf`` set, a bot/app/agent author, a
  ``botActor`` or ``externalUser`` — or when the text carries a mark agents leave (an "Agent notes" fold, a
  "Generated with" line, a ``Co-Authored-By`` / ``Claude-Session`` trailer);
* ``assistant`` too when it was written under the **signed-in account** and nothing above marks it an agent's: an agent
  working through the person's own sign-in posts under the person's own user with no flag Linear's read API exposes, so
  a comment under their account is *not provably the person's typing*. It is kept as written under their account
  (``assistant``, never ``user``), and the Sources row says so;
* ``speaker:<label>`` when another user wrote it — the same rule as a meeting (someone else, never the person; an agent
  of theirs is their account's, indistinguishable the same way);
* ``assistant`` when the author cannot be read at all.

No Linear text is ever a ``user:`` turn. No ``*_by_other`` flag or ``evidence_kind`` rides the episode: the markers on
the turns are the record, so a thread of several people keeps each person apart. Only ids are compared to find the
signed-in account; a name is the fallback only when an id is absent, and a miss there reads as another person, never as
the person.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import episode_ids, episode_staging, evidence
from api.services.connectors import base, linear_mcp, tier2
from api.services.id_utils import sanitize_id

CHANNEL_ID = "linear-api"
LABEL = "Linear"
LOGIN_MODE = "credentials"
CHANNEL_NOUN = "issue"
TIER = tier2.TIER
ORIGIN = "linear-api"
SOURCE_PREFIX = "linear:"
SCRUB_WRITER = "linear"
TOKEN_ENV = linear_mcp.TOKEN_ENV
#: No field: Linear is connected by signing in, never by a pasted key (owner 2026-11-05).
FIELDS: tuple[dict, ...] = ()
SECRET_NAMES: tuple[str, ...] = linear_mcp.SECRET_NAMES
#: Only the read-only endpoint is ever a request's target (`tier2.Client` refuses any other URL).
API_BASE = linear_mcp.MCP_URL
TOKEN_HELP = None
READS = "Read-only. Signs in as you: the issues you created or hold, and their comments."
REFUSED_WORDS = "Linear signed Cicada out. Connect Linear again in Sources → Linear."
#: Said on the Sources row when anything came in under the person's own account.
ACCOUNT_WORDS = ("Linear does not say who typed a comment under your account, so those are kept as written under it, "
                 "not as your own words.")

ISSUE_FIELDS = ["id", "uuid", "title", "description", "createdAt", "updatedAt", "createdBy", "createdById",
                "status", "team"]
PAGE_SIZE = 25
MAX_ISSUES_PER_SYNC = 100
MAX_COMMENT_PAGES = 4
REREAD_DAYS = 7
TITLE_CAP = 200
TURN_CAP = 12000
_FILTERS = ({"creator": "me"}, {"assignee": "me"})
_BOT_KEYS = ("isBot", "bot", "app", "isApp", "isAgent", "agent", "botActor")
_BOT_TYPES = frozenset({"app", "bot", "agent", "integration", "application"})
#: What an agent leaves in text it writes. Used only to demote: a match never makes anything the person's.
_AGENT_MARK = re.compile(r"(?im)^\s*\+\+\+\s*agent notes\b|generated with \[?claude|co-authored-by:|claude-session:"
                         r"|^\s*🤖")

app_available = linear_mcp.app_available
authorize_url = linear_mcp.authorize_url
exchange_code = linear_mcp.exchange_code
how = linear_mcp.how
needs_reconnect = linear_mcp.needs_reconnect
revoke = linear_mcp.revoke
prepare = linear_mcp.prepare


def _self():
    return sys.modules[__name__]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}


def is_connected() -> bool:
    return tier2.is_connected(_self()) and not linear_mcp.needs_reconnect()


def credential_fields() -> list[dict]:
    return []


def forget() -> None:
    tier2.forget(_self())


async def check(client: tier2.Client) -> None:
    raise tier2.Refused("Linear connects by signing in; there is no token to paste.", kind="sign-in")


async def sync(memory_path: Path, *, http_fn=None, allow_fetch=None, scheduled: bool = False) -> dict:
    return await tier2.run(_self(), memory_path, http_fn=http_fn, allow_fetch=allow_fetch, scheduled=scheduled)


# --- whose words ---------------------------------------------------------------------------------------------------


def _actor(value) -> dict:
    """``{id, name, bot}`` from whatever shape Linear gives an author: an object, a bare name, or nothing."""
    if isinstance(value, str):
        return {"id": "", "name": value.strip(), "bot": False}
    if not isinstance(value, dict):
        return {"id": "", "name": "", "bot": False}
    bot = any(bool(value.get(k)) for k in _BOT_KEYS) or str(value.get("type") or "").lower() in _BOT_TYPES
    return {"id": str(value.get("id") or "").strip(), "name": str(value.get("name") or value.get("displayName")
                                                                    or "").strip(), "bot": bot}


def me_of(data: dict) -> dict:
    """The signed-in account from ``whoami`` (an id and a name; either may be absent)."""
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    return _actor(user)


def label_of(name: str) -> str:
    slug = sanitize_id(name or "") if name else ""
    return slug[:64] if slug and slug != "unnamed" else "linear-user"   # a longer label is no speaker marker at all


def attribute(author, *, me: dict, text: str = "", on_behalf_of=None, bot_actor=None, external_user=None) -> tuple[str, str]:
    """(turn marker, why) for one piece of Linear text. Never ``user``: nothing Linear's read API exposes proves a
    person, rather than an agent signed in as them, typed it."""
    who = _actor(author)
    if on_behalf_of or bot_actor or external_user or who["bot"]:
        return "assistant", "agent"
    if _AGENT_MARK.search(text or ""):
        return "assistant", "agent-mark"
    if not who["id"] and not who["name"]:
        return "assistant", "unknown"
    if who["id"] and me.get("id"):
        mine = who["id"] == me["id"]
    else:
        mine = bool(who["name"] and me.get("name") and who["name"].casefold() == me["name"].casefold())
    if mine:
        return "assistant", "account"
    return f"speaker:{label_of(who['name'])}", "other"


# --- reading -------------------------------------------------------------------------------------------------------


def _rows(data: dict, *keys: str) -> list[dict]:
    for key in (*keys, "results", "items"):
        if isinstance(data.get(key), list):
            return [r for r in data[key] if isinstance(r, dict)]
    return []


def _when(value) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else None


def _clip(text, cap: int) -> str:
    value = str(text or "").strip()
    return value if len(value) <= cap else value[: cap - 1].rstrip() + "…"


def _key(row: dict) -> str:
    raw = str(row.get("uuid") or row.get("id") or "").strip()
    return sanitize_id(raw) if raw else ""


def _since(high_water, reread: str) -> str | None:
    """The listing's lower bound: the last complete sync's newest edit, or the re-read window if that is earlier."""
    if not high_water:
        return None
    a, b = _when(high_water), _when(reread)
    return high_water if a is not None and b is not None and a < b else reread


async def _page(session, since: str | None, which: int, cursor: str | None) -> tuple[list[dict], str | None]:
    """One page of one ``list_issues`` filter, newest edit first: (rows, the next cursor or None when it was the last)."""
    args = {**_FILTERS[which], "orderBy": "updatedAt", "limit": PAGE_SIZE, "fields": ISSUE_FIELDS}
    if since:
        args["updatedAt"] = since
    if cursor:
        args["cursor"] = cursor
    try:
        data = await session.call("list_issues", args)
    except (tier2.Refused, linear_mcp.WriteToolRefused):
        raise
    except base.ConnectorError:
        if not cursor:
            raise
        return await _page(session, since, which, None)      # a cursor Linear no longer takes: start again
    nxt = data.get("cursor") if data.get("hasNextPage") else None
    return _rows(data, "issues"), (nxt if isinstance(nxt, str) and nxt else None)


async def _comments(session, issue_id: str) -> list[dict]:
    out: list[dict] = []
    cursor = None
    for _ in range(MAX_COMMENT_PAGES):
        args = {"issueId": issue_id, "orderBy": "createdAt", "limit": 250}
        if cursor:
            args["cursor"] = cursor
        data = await session.call("list_comments", args)
        out.extend(_rows(data, "comments"))
        nxt = data.get("cursor") if data.get("hasNextPage") else None
        cursor = nxt if isinstance(nxt, str) and nxt else None
        if not cursor:
            break
    return sorted(out, key=lambda c: str(c.get("createdAt") or ""))


def draft_for(issue: dict, comments: list[dict], me: dict) -> tuple[episode_staging.EpisodeDraft | None, bool]:
    """One issue's thread as an episode, and whether any turn was written under the person's own account."""
    key = _key(issue)
    created = str(issue.get("createdAt") or "")
    turns: list[episode_staging.Turn] = []
    account = False

    def add(text: str, marker: str, why: str, ts: str | None) -> None:
        nonlocal account
        account = account or why == "account"
        # A pasted "User: I can't log in" must never open a turn of the person's (the attachment rule).
        turns.append(episode_staging.Turn(text=evidence.quote_markers(_clip(text, TURN_CAP)), speaker=marker, ts=ts or None))

    desc = str(issue.get("description") or "").strip()
    if desc:
        author = issue.get("createdBy")
        if not isinstance(author, dict):
            author = {"id": issue.get("createdById"), "name": author}
        marker, why = attribute(author, me=me, text=desc)
        add(desc, marker, why, created)
    for c in comments:
        body = str(c.get("body") or "").strip()
        if not body:
            continue
        if c.get("quotedText"):
            body = f'On "{_clip(c["quotedText"], 200)}": {body}'
        marker, why = attribute(c.get("author"), me=me, text=body, on_behalf_of=c.get("onBehalfOf"),
                                bot_actor=c.get("botActor"), external_user=c.get("externalUser"))
        add(body, marker, why, str(c.get("createdAt") or "") or None)
    if not key or not turns:
        return None, False
    when = _when(created) or _when(issue.get("updatedAt"))
    draft = episode_staging.EpisodeDraft(
        title=_clip(" ".join(str(issue.get("title") or "Untitled").split()), TITLE_CAP),
        source_id=SOURCE_PREFIX + key, source_updated_at=str(issue.get("updatedAt") or "") or None,
        timestamp=episode_staging.normalise_timestamp(created) if when else None,
        original_date=episode_ids.id_day(when.astimezone(timezone.utc)) if when else None,
        source=ORIGIN, origin=ORIGIN, turns=turns, writer=SCRUB_WRITER,
        extra={"source": ORIGIN, "linear_issue": key})
    draft.redate = False
    return draft, account


async def fetch(client: tier2.Client, cursor: dict, memory_path: Path) -> tier2.Batch:
    """Both filters, a page at a time, each issue's thread read as its page comes. A sync that reaches its budget stops
    *before* the next page and keeps that page's own cursor, so nothing is skipped and the cursor holds only Linear's
    opaque page marker and times (a repeated page is a hash skip downstream). An issue whose comments could not be read
    is never staged without them, which would read as their removal; the mark holds instead, so it is listed again."""
    session = linear_mcp.Session(client)
    me = me_of(await session.call("whoami", {}))
    reread = (datetime.now(timezone.utc) - timedelta(days=REREAD_DAYS)).isoformat()
    high_water = cursor.get("high_water")
    walk = dict(cursor.get("walk") or {})       # {"since", "cursors": [str|None, str|None], "done": [bool, bool]}
    since = walk["since"] if walk else _since(high_water, reread)
    cursors = list(walk.get("cursors") or [None, None])
    done = list(walk.get("done") or [False, False])
    newest = high_water or ""
    batch = tier2.Batch()
    unreadable = 0
    listed = 0                                  # every issue costs a read, whether or not it has words to keep
    stopped = False
    account = False
    for which in (0, 1):
        while not done[which] and not stopped:
            if listed + PAGE_SIZE > MAX_ISSUES_PER_SYNC and listed:
                break                           # the budget: this page waits for the next sync
            try:
                rows, nxt = await _page(session, since, which, cursors[which])
            except linear_mcp.RequestLimit:
                stopped = True
                break
            for row in rows:
                newest = max(newest, str(row.get("updatedAt") or ""))
                rid = str(row.get("uuid") or row.get("id") or "")
                if not rid:
                    continue
                try:
                    comments = await _comments(session, rid)
                except (tier2.Refused, linear_mcp.WriteToolRefused):
                    raise
                except linear_mcp.RequestLimit:
                    stopped = True
                    break
                except base.ConnectorError:
                    unreadable += 1
                    continue
                draft, own = draft_for(row, comments, me)
                if draft is None:
                    continue
                account = account or own
                batch.drafts.append(draft)
                batch.replaced.append(draft.source_id)
                batch.seen += 1
            if stopped:
                break                           # this page again next sync; what it already read is a hash skip
            listed += len(rows)
            cursors[which], done[which] = nxt, nxt is None
    finished = all(done)
    failed = bool(walk.get("failed")) or unreadable > 0
    # The mark moves only once both listings are whole and every issue in them was read, to the newest edit seen.
    batch.cursor = {"high_water": (newest or high_water) if finished and not failed else high_water}
    if not finished:
        batch.cursor["walk"] = {"since": since, "cursors": cursors, "done": done, "failed": failed}
    words = []
    if not finished:
        words.append(f"Reading your Linear issues: {batch.seen} this time; the next sync carries on.")
    elif not batch.seen and not high_water:
        words.append("Linear listed no issues you created or hold.")
    if account:
        words.append(ACCOUNT_WORDS)
    if unreadable:
        words.append(f"{unreadable} issue(s) could not be read; the next sync tries again.")
    batch.words = " ".join(words) or None
    return batch


__all__ = ["CHANNEL_ID", "LABEL", "ORIGIN", "attribute", "draft_for", "fetch", "sync"]
