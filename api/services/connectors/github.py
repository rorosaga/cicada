"""GitHub — the person's own repositories and the ones they starred (ruling 47 tier 2, G230).

The browser sees a repository page now and then; GitHub's REST API holds the person's whole list — every repository
they own and every one they starred, with when. **The person connects with a code** (owner 2026-11-03: "cant we just
do oauth? like a connect?"): GitHub's device flow for Cicada's own read-only GitHub App (``github_auth``) — no token to
make, no secret, no server of Cicada's. A token the person makes themselves (fine-grained, read-only "Metadata",
"Contents" and "Starring") is the fallback behind "Use a token instead", for a build whose app is not registered yet.
Only ``GET`` requests to ``api.github.com``; Cicada never writes to GitHub. Off until the person connects, said in
words (:data:`READS`), forgotten by Disconnect.

What a sync brings in, one item per repository, keyed by GitHub's own numeric id (a rename or a transfer keeps it):

* **A repository the person owns** — ``github:owned:<id>``, staged through ``episode_staging`` (scrubbed, hashed, an
  edit rewrites in place, a repository gone from the list is tombstoned and kept), indexed and never read by a model
  (``history_index.LIST_ORIGINS``, ruling 30's posture) — **and a page** (owner 2026-11-03: "there shouldn't be added
  manually, always sync and make their initial markdowns, and develop them if needed"): a ``media`` page
  (``media.kind: repository``, ``github.owned: true``) whose first markdown is its name, link, description, language,
  topics and a summary from its README (``github_repos.apply_owned``). A repository page is not a project page: a
  project lists its repositories (``github_repos.link``), by the hook's D2a origin hash or the person's act.
* **A repository the person starred** — a save, like a bookmark: one ``media`` page (``media.kind: repository``) and
  one index-only save episode through ``media_ingestor``'s own write path, dated when it was starred
  (``github_repos.apply_stars``). A later sync updates the page's GitHub block in place; a repository no longer starred
  is marked so on its page and kept — nothing is deleted.

**Requests** (:func:`fetch`): ``/user`` (the account's own login, to tell its own repositories apart),
``/user/installations`` (signed in with the app: whether it is installed on the person's account, which is what lets
it see their repositories), then ``/user/repos?affiliation=owner`` and ``/user/starred`` 50 at a time, at most
``MAX_PAGES`` pages each, and ``/repos/{owner}/{name}/readme`` once for each of their own repositories whose page is
about to be made (its first summary). Nothing a request sends names anyone: only the person's own account endpoints
and the repository's own path. GitHub allows 5,000 requests an hour with a token; a 429 (or a 403 that says the limit
was reached) is answered in words and the next sync starts over. The transport (:func:`guarded_transport`) is
``api.github.com`` only, through ``net_guard``'s address rule, no redirects, no cookies, 4 s and 512 KB a response (the
ToS rail's numbers).

A starred repository's README is never read during a sync: it is asked for one repository at a time, when the person
opens its page (``github_repos.ensure_readme``), and kept outside every bank.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from api.services import episode_ids, episode_scrub, episode_staging
from api.services.connectors import github_auth, tier2

CHANNEL_ID = "github"
LABEL = "GitHub"
LOGIN_MODE = "credentials"
CHANNEL_NOUN = "repo"
TIER = tier2.TIER
ORIGIN_OWNED = "github-owned"
ORIGIN_STARRED = "github-starred"
OWNED_PREFIX = "github:owned:"
SCRUB_WRITER = "github"
TOKEN_ENV = github_auth.TOKEN_ENV
#: The fallback: a token the person pastes (behind "Use a token instead").
FIELDS: tuple[dict, ...] = ({"name": TOKEN_ENV, "label": "GitHub token", "secret": True},)
#: The token, its refresh token, when it lapses and how it was made — every one forgotten by Disconnect.
SECRET_NAMES: tuple[str, ...] = github_auth.SECRET_NAMES
API_BASE = "https://api.github.com/"
API_HOST = "api.github.com"
WEB_HOSTS = frozenset({"github.com", "www.github.com"})
TOKEN_HELP = "github.com/settings/personal-access-tokens"
#: One short line (owner 2026-11-03: "this text is extremely unnecessary in all pages that have it, remove it"); the
#: panel adds where the token comes from while it is not connected, so neither says it twice.
READS = "Read-only: your repositories, each with its README, and the ones you starred."
#: GitHub's rate limits (the primary hourly one, or a secondary one for too many requests at once). A sync reads both
#: lists whole each time, so a sync a limit stopped saved nothing and the next one starts again from the top.
RATE_WORDS = ("GitHub asked Cicada to slow down, so nothing was saved this time; the next sync reads your repositories "
              "again from the start.")
REFUSED_WORDS = "GitHub refused Cicada's access. Connect GitHub again in Sources → GitHub."
#: Signed in with the app, not installed on the person's account: their own repositories are out of its reach.
NOT_INSTALLED_WORDS = ("Your stars came in. To bring in your own repositories, install Cicada on your GitHub account "
                       "(Sources → GitHub → Install on GitHub).")
def not_shared_words(n: int) -> str:
    """Installed on selected repositories only: the ones left out, said — their records and pages are kept."""
    if n == 1:
        return ("One of your repositories isn't shared with Cicada on GitHub, so it was not read; its page stays. Add "
                "it to Cicada's installation on GitHub to read it again.")
    return (f"{n} of your repositories aren't shared with Cicada on GitHub, so they were not read; their pages stay. "
            "Add them to Cicada's installation on GitHub to read them again.")


#: How many README reads run at once in a sync (a first sync of many repositories).
README_CONCURRENCY = 4

#: Rows a list request asks for. GitHub allows 100, but a real 100-repository page measured 633,641 bytes (a starred
#: row ~6.1 KB with every URL template GitHub sends), past the ToS rail's 512 KB a response: 50 a page stays under it
#: with room (≈ 310 KB). 60 pages keep the same 3,000 items a list may hold.
PER_PAGE = 50
MAX_PAGES = 60
TIMEOUT_SECONDS = 4.0
MAX_BYTES = 512 * 1024
TEXT_CAP = 2000
#: GitHub's own shape for an owner login and a repository name (``owner/name``).
_LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
_NAME = r"[A-Za-z0-9._-]{1,100}"
FULL_NAME_RE = re.compile(rf"(?P<owner>{_LOGIN})/(?P<name>{_NAME})")
_RESERVED_OWNERS = frozenset({
    "settings", "orgs", "organizations", "marketplace", "explore", "topics", "collections", "trending", "sponsors",
    "features", "about", "pricing", "login", "logout", "join", "notifications", "pulls", "issues", "search", "apps",
    "users", "enterprise", "codespaces", "new", "site", "security", "readme", "stars", "watching", "dashboard",
})


def auth_headers(token: str) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "Cicada"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _self():
    import sys

    return sys.modules[__name__]


def is_connected() -> bool:
    return tier2.is_connected(_self())


def credential_fields() -> list[dict]:
    return tier2.credential_fields(_self())


def forget() -> None:
    """Disconnect: the token, the cursors, and the READMEs read with it (a private repository's words were the
    token's to read). The pages and episodes in memory stay — they are the person's, to keep or remove."""
    from api.services import github_repos

    github_auth.cancel()
    tier2.forget(_self())
    github_repos.forget_readmes()


def on_token_saved() -> None:
    """The person pasted a token (Settings, or `cicada connector connect github`): the code sign-in it replaces is
    forgotten — its refresh token, its expiry, its "signed in by code" mark and its install state — so a later renewal
    never puts the old sign-in's token back over the pasted one."""
    github_auth.forget_sign_in()


async def prepare() -> None:
    """Before a sync's first request (``tier2.run``): a signed-in token about to lapse is renewed."""
    await github_auth.fresh_token()


async def check(client: tier2.Client) -> None:
    """The person's Save: ``GET /user`` answers 200 for a token GitHub accepts."""
    body = await client.get("user")
    if not isinstance(body, dict) or not body.get("login"):
        raise tier2.Refused(REFUSED_WORDS, kind="sign-in")


async def sync(memory_path: Path, *, http_fn=None, allow_fetch=None, scheduled: bool = False) -> dict:
    return await tier2.run(_self(), memory_path, http_fn=http_fn, allow_fetch=allow_fetch, scheduled=scheduled)


# --- the transport ---------------------------------------------------------------------------------------------------


async def guarded_transport(method: str, url: str, *, headers: dict, params: dict | None = None,
                            json: dict | None = None) -> tier2.Response:
    """``api.github.com`` only, every request through ``net_guard``'s address rule, no redirect followed, no cookie
    kept, 4 s, at most 512 KB read (a longer answer is a refusal in words, never a partial read)."""
    import httpx

    from api.services import net_guard

    host = (urlparse(url).hostname or "").lower()
    if urlparse(url).scheme != "https" or host != API_HOST:
        raise tier2.base.ConnectorError("GitHub: a request off its own host was refused")
    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_SECONDS, transport=HTTPX_TRANSPORT,
                                 trust_env=False,
                                 event_hooks={"request": [net_guard.httpx_request_guard]}) as client:
        async with client.stream(method, url, headers=headers, params=params, json=json) as resp:
            chunks, size = [], 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise tier2.Refused("GitHub sent more than Cicada reads in one answer.", kind="other")
                chunks.append(chunk)
            raw = b"".join(chunks)
            status, response_headers = resp.status_code, {k.lower(): v for k, v in resp.headers.items()}
    body = None
    if raw:
        import json as _json

        try:
            body = _json.loads(raw)
        except ValueError:
            body = None
    return tier2.Response(_rate_status(status, body, response_headers), body, response_headers)


def _rate_status(status: int, body, headers: dict) -> int:
    """GitHub answers a rate limit with 403 as often as 429: the primary limit with ``x-ratelimit-remaining: 0``, a
    secondary one with ``retry-after`` or a message that says so. Either is a rate limit (429), never a refused token."""
    if status != 403:
        return status
    message = str((body or {}).get("message") or "").lower() if isinstance(body, dict) else ""
    if headers.get("x-ratelimit-remaining") == "0" or headers.get("retry-after") or "rate limit" in message:
        return 429
    return status


TRANSPORT = guarded_transport
#: httpx's own transport under `guarded_transport`: None is the network. The suite puts an `httpx.MockTransport` here
#: so a realistic answer goes through the real size cap and status mapping.
HTTPX_TRANSPORT = None


def client(token: str | None = None, transport=None) -> tier2.Client:
    """A request client for one job: the person's token when connected (else none — a public repository's record
    and README are readable without one), the guarded transport unless a test hands its own."""
    value = tier2.token(_self()) if token is None else token
    return tier2.Client(_self(), value, transport)


# --- URLs -----------------------------------------------------------------------------------------------------------


def parse_repo(value: str) -> str | None:
    """``owner/name`` from a repository URL the person pasted (``https://github.com/o/r``, a deeper page of it,
    ``.git``, ``git@github.com:o/r.git``) or a bare ``owner/name``. ``None`` for anything else (a profile, another
    host, a reserved GitHub path). Pure."""
    text = str(value or "").strip()
    if not text or len(text) > 400 or any(ch.isspace() for ch in text):
        return None
    if text.startswith("git@github.com:"):
        path = text.split(":", 1)[1]
    elif "://" in text:
        try:
            parsed = urlparse(text)
        except ValueError:
            return None
        if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in WEB_HOSTS \
                or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        path = parsed.path
    elif text.lower().startswith(("github.com/", "www.github.com/")):
        path = text.split("/", 1)[1]
    else:
        path = text
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, name = parts[0], parts[1].removesuffix(".git")
    full = f"{owner}/{name}"
    if not FULL_NAME_RE.fullmatch(full) or owner.lower() in _RESERVED_OWNERS or name in (".", ".."):
        return None
    return full


def repo_url(full_name: str) -> str:
    return f"https://github.com/{full_name}"


# --- reading -------------------------------------------------------------------------------------------------------


async def _pages(client: tier2.Client, path: str, **params) -> tuple[list, bool]:
    """Every page of a list endpoint, at most ``MAX_PAGES``: (rows, finished)."""
    rows: list = []
    for page in range(1, MAX_PAGES + 1):
        body = await client.get(path, per_page=PER_PAGE, page=page, **params)
        batch = [r for r in (body or []) if isinstance(r, dict)] if isinstance(body, list) else []
        rows.extend(batch)
        if len(batch) < PER_PAGE:
            return rows, True
    return rows, False


async def read_starred(client: tier2.Client) -> tuple[list[dict], bool]:
    """``[{starred_at, repo}]``, newest star first. The star media type is asked per request."""
    rows: list = []
    for page in range(1, MAX_PAGES + 1):
        body = await client.request("GET", "user/starred", params={"per_page": PER_PAGE, "page": page},
                                    headers={"Accept": "application/vnd.github.star+json"})
        batch = [r for r in (body or []) if isinstance(r, dict)] if isinstance(body, list) else []
        rows.extend(batch)
        if len(batch) < PER_PAGE:
            return [_star(r) for r in rows if _star(r)], True
    return [_star(r) for r in rows if _star(r)], False


def _star(row: dict) -> dict | None:
    """A starred row as ``{starred_at, repo}``; the plain media type (no timestamp) is a bare repository."""
    if isinstance(row.get("repo"), dict):
        return {"starred_at": row.get("starred_at"), "repo": row["repo"]}
    if row.get("full_name"):
        return {"starred_at": None, "repo": row}
    return None


async def read_repo(client: tier2.Client, full_name: str) -> dict:
    return await client.get(f"repos/{full_name}") or {}


async def read_readme(client: tier2.Client, full_name: str) -> dict | None:
    """The repository's README record (``content`` base64), or ``None`` when it has none (404)."""
    try:
        body = await client.get(f"repos/{full_name}/readme")
    except tier2.base.ConnectorError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise
    return body if isinstance(body, dict) else None


async def fetch(client: tier2.Client, cursor: dict, memory_path: Path) -> tier2.Batch:
    from api.services import github_repos

    me = await client.get("user") or {}
    login = str(me.get("login") or "")
    installation = await github_auth.check_installation(client, login)
    owned, owned_done = await _pages(client, "user/repos", affiliation="owner", sort="full_name")
    starred, starred_done = await read_starred(client)
    records = [github_repos.Repo.from_api(r) for r in owned]
    records = [r for r in records if r is not None]
    drafts = [_owned_draft(r) for r in records]
    stars = [(rec, s.get("starred_at")) for s in starred if (rec := github_repos.Repo.from_api(s["repo"]))]
    # A first summary for each page about to be made — never for a page that exists or one the person removed.
    readmes = await _readmes(client, github_repos.pages_to_make(memory_path, records))
    words = [f"GitHub's list was longer than {PER_PAGE * MAX_PAGES} items; the first ones came in."] \
        if not (owned_done and starred_done) else []
    installed = bool(installation.get("installed"))
    if not installed:
        words.append(NOT_INSTALLED_WORDS)
    # Installed on some repositories only: one left out of the selection is out of the app's sight, not deleted.
    selected = installation.get("selection") == "selected"
    if installed and selected and owned_done:
        seen_ids = {r.id for r in records}
        hidden = [r for r in github_repos.owned(memory_path) if r.get("id") not in seen_ids]
        if hidden:
            words.append(not_shared_words(len(hidden)))
    batch = tier2.Batch(
        drafts=drafts,
        # The owned list was read whole: a repository gone from it is tombstoned (kept), never silently dropped. A list
        # cut short at MAX_PAGES replaces nothing, and neither does one the app could not wholly see (not installed, or
        # installed on selected repositories: nothing was deleted on GitHub).
        replaced=[OWNED_PREFIX.rstrip(":")] if owned_done and installed and not selected else [],
        seen=len(records) + len(stars),
        cursor={"login_hash": github_repos.login_key(login)} if login else {},
        words=" ".join(words) or None,
    )

    def after(path: Path) -> dict:
        mine = github_repos.apply_owned(path, records, readmes=readmes)
        theirs = github_repos.apply_stars(path, stars, login=login, complete=starred_done)
        out = {"paths": list(dict.fromkeys([*mine["paths"], *theirs["paths"]])),
               "created": mine["created"] + theirs["created"], "updated": mine["updated"] + theirs["updated"],
               "live": theirs["live"]}
        said = " ".join(w for w in (mine.get("words"), theirs.get("words")) if w)
        if said:
            out["words"] = said
        # After the sync's own commit: the D2a links, Cicada's inference, committed under its own author.
        out["then"] = github_repos.link_by_origin
        return out

    batch.after = after
    return batch


async def _readmes(client: tier2.Client, repos: list) -> dict[int, str]:
    """``{repository id: README markdown}`` for ``repos``, :data:`README_CONCURRENCY` at a time; a repository with no
    README, or one whose read failed, is absent — its page is made without a summary. A refusal (the token, a rate
    limit) stops the sync in words like any other request."""
    from api.services import github_repos

    gate = asyncio.Semaphore(README_CONCURRENCY)
    out: dict[int, str] = {}

    async def one(repo) -> None:
        async with gate:
            try:
                record = await read_readme(client, repo.full_name)
            except tier2.Refused:
                raise
            except Exception as exc:  # noqa: BLE001 — one README never stops the rest; the class only
                logger.info(f"github: a README was not read ({type(exc).__name__})")
                return
        text = github_repos.decode_readme(record) if record else None
        if text:
            out[repo.id] = text

    await asyncio.gather(*(one(r) for r in repos))
    return out


def _owned_draft(repo) -> episode_staging.EpisodeDraft:
    lines = [f"# {repo.full_name}", ""]
    if repo.description:
        lines += [repo.description[:TEXT_CAP], ""]
    lines.append(f"**Repository:** [{repo.full_name}]({repo.url})")
    if repo.language:
        lines.append(f"**Language:** {repo.language}")
    if repo.topics:
        lines.append("**Topics:** " + ", ".join(repo.topics))
    lines.append(f"**Visibility:** {'private' if repo.private else 'public'}"
                 + (" · archived" if repo.archived else "") + (" · a fork" if repo.fork else ""))
    title, _ = episode_scrub.scrub(repo.full_name)
    created = _when(repo.created_at)
    return episode_staging.EpisodeDraft(
        title=title, source_id=f"{OWNED_PREFIX}{repo.id}", source_updated_at=repo.updated_at or repo.pushed_at,
        timestamp=created.isoformat() if created else None,
        original_date=episode_ids.id_day(created) if created else None,
        source="github", origin=ORIGIN_OWNED, body="\n".join(lines).strip(),
        extra={"github": repo.block("owned"), "url": repo.url},
        queue_for_sleep=False, processed_by="index", writer=SCRUB_WRITER)


def _when(value) -> datetime | None:
    if not value:
        return None
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.astimezone(timezone.utc) if at.tzinfo else None
