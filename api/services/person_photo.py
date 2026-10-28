"""G159 amendment (owner 2026-10-09) — a person's photo from a public profile, never from a guess.

Until this ruling a `person` page could get a picture only from the person's own upload or a Contacts photo, and no
outside service was ever asked about a person. The owner now allows two public avatar services for people — and only
from an identifier **already on that person's page or the person's own record**:

- **an email address the person gave for the page** — today that is only the owner's own page: the `email` the person
  typed in Settings (`owner_identity.load_owner`, `~/.cicada/owner.json`, never a bank file), used only on the page
  marked `owner: true`. The bank holds no one else's address: Contacts posts which facts a card holds, never the
  values (G154 R-SR8), and a model's claim is not an identifier. The address is trimmed, lowercased and SHA-256'd in
  memory; only the hash is ever sent, and neither the address nor the hash is logged or stored (the cache key is a
  hash of the hash);
- **a GitHub profile link among the page's `sources:`** — `https://github.com/<username>`, exactly one path segment,
  that somebody gave as the person's OWN account (:func:`is_own_account`: the person's or one they took, or an
  identified agent's, with no fact attached or a profile predicate — never a link Stage 5.56 attached from a claim's
  cited words, never Cicada's own writers); best-ranked first (`fact_sources.rank`).

- **an X, Instagram or LinkedIn profile link among the page's `sources:`** (owner 2026-10-09, the one exception to the ToS rail's
  "never through someone else's service") — `https://x.com/<handle>` (or twitter.com) and
  `https://www.linkedin.com/in/<slug>`, profile URLs only, never a post or a company page — asked of the unavatar.io
  avatar proxy, which is handed the handle. Behind its OWN gate, `CICADA_ALLOW_PERSON_PHOTO_PROXY` — **on by default
  since ruling 36 D5** (owner 2026-10-22; off from 2026-10-09) — because each lookup tells a third party whom the person
  knows, `off` still closes it, and with it off such a link is no identifier at all. Instagram joined the rung with D5
  (`https://www.instagram.com/<handle>`, profile URLs only). A LinkedIn
  link the person's own connections export put on a page it matched confidently counts as given (owner 2026-10-17,
  :func:`is_own_account`); an alias-only match waits for the person to take it. At most
  :data:`PROXY_DAILY_BUDGET` lookups a UTC day across the install (the proxy's anonymous allowance), counted in
  `$CICADA_HOME/pictures/proxy_budget.json`, outside every bank; over budget is a transient miss, asked again the
  next day.
- **a public figure's encyclopedia portrait** (owner 2026-10-28, C; ruling 44's public test) — only for a page the full
  public test called public: it passed the local test (a full name, no acquaintance on the record, no personal channel,
  a public cue) AND matched exactly ONE human on Wikidata with an encyclopedia article, the item kept in ruling 44's
  memo outside every bank (`web_context.public_items`). The item's image (P18) is asked of Wikidata by that item and
  the file of Wikimedia Commons by its own name — never the person's name again. The local test is run once more just
  before the ask (err private: an acquaintance since, and nothing is asked); a page that fails it later leaves the memo
  on Sleep's next verdict, and its portrait with it.

Never a name, an alias, a domain or a username guessed from either.

**The ladder** (the owner's model, adapted): the person's own choice → the Contacts photo → the email's public photo
(asked with ``d=404``, so a "no photo" answer is a 404, never a default image cached as a photo) → the GitHub avatar →
the encyclopedia portrait (no proxy budget, and it tells no one anything the public test did not already ask) → the X photo → the Instagram photo → the LinkedIn photo (each with ``fallback=false``, unavatar's documented "404 on a miss") → the monogram. `entity_picture.resolve` holds the precedence; this module answers its `profile` rung's availability
(read-only, from the cache index) and does the one fetch, on demand, when the app asks `GET /entities/{id}/photo`.

**The fetch** — fixed URL shapes, `https` only, every hop (redirects followed by hand, at most 3) checked against
the providers' own hosts AND `net_guard`; 4 s a request (all its hops) and 10 s for the whole ladder, ≤ 512 KB read
and then stopped, a fresh client with no cookies
and no credentials; kept only as a PNG or a JPEG of 16–1024 px by its own bytes (an SVG, whatever its header says, a
GIF, an HTML page are refused). Two gates, both on by default: `CICADA_ALLOW_LOGO_FETCH` (every picture fetch) and
`CICADA_ALLOW_PERSON_PHOTO_FETCH` (people only). Nothing here runs from Sleep; a later warm-up would also sit behind
`CICADA_ALLOW_CONNECTOR_FETCH`.

**The cache** — `$CICADA_HOME/pictures/<bank>/people/<id>.<png|jpg>` beside the Contacts photos, outside every bank,
indexed by `meta.json` (`{key, fetched_at, miss, transient, ext, sha}`). A photo is fetched ONCE per person and
identifier set: a hit is kept until the identifier changes or goes, a miss is retried after 30 days, a failed
connection after a day. The person's upload always wins, and "Use initials" (kept in the bank) removes it for good.
A demo bank asks nobody and never offers the owner's email (its owner page is synthetic, made for screenshots).
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote, urljoin, urlparse

from loguru import logger

from api.services import logo_service, markdown_parser, net_guard
from api.services.logo_service import FetchResult

GATE_ENV = "CICADA_ALLOW_PERSON_PHOTO_FETCH"
PROXY_GATE_ENV = "CICADA_ALLOW_PERSON_PHOTO_PROXY"
#: The proxy's anonymous allowance (its docs: 25 requests a day per IP address), shared by every bank on this Mac.
PROXY_DAILY_BUDGET = 25
BUDGET_FILENAME = "proxy_budget.json"
PEOPLE_DIR = "people"
META_FILENAME = "meta.json"
LOCK_FILENAME = "meta.lock"
MISS_TTL = timedelta(days=30)
TRANSIENT_TTL = timedelta(days=1)
MAX_BYTES = logo_service.MAX_BYTES
TIMEOUT_SECONDS = logo_service.TIMEOUT_SECONDS
MAX_REDIRECTS = 3
#: One deadline for the whole ladder (up to four providers), on top of each request's own 4 s.
LADDER_SECONDS = 10.0
SIZE = 256
EXTS = ("png", "jpg")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg"}

GRAVATAR = "gravatar"
GITHUB = "github"
X = "x"
LINKEDIN = "linkedin"
INSTAGRAM = "instagram"
#: A public figure's encyclopedia portrait: the value is the Wikidata item, never a name (owner 2026-10-28, C).
WIKIDATA = "wikidata"
PROXIED = frozenset({X, INSTAGRAM, LINKEDIN})
_URLS = {
    GRAVATAR: "https://gravatar.com/avatar/{value}?s=" + str(SIZE) + "&d=404",
    GITHUB: "https://github.com/{value}.png?size=" + str(SIZE),
    X: "https://unavatar.io/x/{value}?fallback=false",
    LINKEDIN: "https://unavatar.io/linkedin/user:{value}?fallback=false",
    INSTAGRAM: "https://unavatar.io/instagram/{value}?fallback=false",
    # Commons' own redirect to a SIZE-px raster of the file (an SVG or a TIFF is drawn to PNG/JPEG by Commons itself).
    WIKIDATA: "https://commons.wikimedia.org/wiki/Special:FilePath/{value}?width=" + str(SIZE),
}
_QID_RE = re.compile(r"Q[1-9][0-9]{0,11}")
#: A Commons file name as P18 holds it: no path, no scheme, an image extension Commons renders as a raster thumbnail.
_COMMONS_FILE_RE = re.compile(r"[^/\\#?<>\[\]{}|\x00-\x1f]{1,236}\.(?:jpe?g|png|gif|tiff?|webp|svg)", re.IGNORECASE)
_WIKIMEDIA_HOSTS = frozenset({"commons.wikimedia.org", "upload.wikimedia.org"})
_X_HANDLE_RE = re.compile(r"[A-Za-z0-9_]{1,15}")
_X_RESERVED = frozenset({
    "home", "explore", "notifications", "messages", "i", "settings", "search", "intent", "share", "hashtag", "compose",
    "login", "logout", "signup", "tos", "privacy", "about", "jobs", "download", "following", "followers", "lists",
    "bookmarks", "communities", "premium", "account",
})
_INSTAGRAM_RE = re.compile(r"[A-Za-z0-9._]{1,30}")
#: First path segments of instagram.com that are pages of the site, not an account.
_INSTAGRAM_RESERVED = frozenset({
    "p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct", "about", "developer", "legal", "privacy",
    "terms", "web", "challenge", "emails", "session", "help", "press", "api", "static",
})
_LINKEDIN_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,99}")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_USERNAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
#: First path segments of github.com that are pages of the site, not a person's profile.
_GITHUB_RESERVED = frozenset({
    "about", "apps", "collections", "contact", "customer-stories", "enterprise", "events", "explore", "features",
    "home", "issues", "join", "login", "logout", "marketplace", "new", "notifications", "organizations", "orgs",
    "pricing", "pulls", "readme", "search", "security", "settings", "site", "sponsors", "team", "topics", "trending",
    "users", "codespaces", "copilot", "dashboard", "discussions", "github", "resources", "solutions", "signup",
})

Fetcher = Callable[[str], Awaitable[FetchResult]]


@dataclass(frozen=True)
class Candidate:
    """One identifier to ask with: `gravatar` carries the address's SHA-256 (never the address), `github` a username."""

    provider: str
    value: str


# --- identifiers ------------------------------------------------------------------------------------------------


def gravatar_hash(raw) -> str | None:
    """SHA-256 of the trimmed, lowercased address — what the service keys a photo by. None for anything that is not
    one plausible address."""
    if not isinstance(raw, str):
        return None
    email = raw.strip().lower()
    if not email or len(email) > 254 or _EMAIL_RE.fullmatch(email) is None:
        return None
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def github_username(ref) -> str | None:
    """The username of a GitHub *profile* URL (`https://github.com/<username>`, a trailing slash, query or fragment
    allowed) — None for a repository, a site page, another host, or anything that is not a URL."""
    if not isinstance(ref, str) or "://" not in ref:
        return None
    try:
        parsed = urlparse(ref.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or host not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 1:
        return None
    name = parts[0]
    if name.lower() in _GITHUB_RESERVED or _USERNAME_RE.fullmatch(name) is None:
        return None
    return name


def _profile_parts(ref, hosts: tuple[str, ...]) -> list[str] | None:
    """The path segments of an http(s) URL on one of ``hosts``; None for anything else."""
    if not isinstance(ref, str) or "://" not in ref:
        return None
    try:
        parsed = urlparse(ref.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or host not in hosts:
        return None
    return [p for p in parsed.path.split("/") if p]


def x_handle(ref) -> str | None:
    """The handle of an X profile URL (`https://x.com/<handle>`, twitter.com too) — None for a post, a site page,
    another host, or anything that is not a URL."""
    parts = _profile_parts(ref, ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"))
    if not parts or len(parts) != 1:
        return None
    name = parts[0]
    if name.lower() in _X_RESERVED or _X_HANDLE_RE.fullmatch(name) is None:
        return None
    return name


def linkedin_slug(ref) -> str | None:
    """The slug of a LinkedIn member profile (`https://www.linkedin.com/in/<slug>`) — None for a company page, a post,
    a profile's sub-page, or anything else."""
    parts = _profile_parts(ref, ("linkedin.com", "www.linkedin.com"))
    if not parts or len(parts) != 2 or parts[0] != "in" or _LINKEDIN_SLUG_RE.fullmatch(parts[1]) is None:
        return None
    return parts[1]


def instagram_handle(ref) -> str | None:
    """The handle of an Instagram profile URL (`https://www.instagram.com/<handle>`) — None for a post, a reel, a site
    page, another host, or anything else (ruling 36 D5, 2026-10-22)."""
    parts = _profile_parts(ref, ("instagram.com", "www.instagram.com"))
    if not parts or len(parts) != 1:
        return None
    name = parts[0]
    if name.lower() in _INSTAGRAM_RESERVED or _INSTAGRAM_RE.fullmatch(name) is None or name.strip(".") != name:
        return None
    return name


_PARSERS = {GITHUB: github_username, X: x_handle, INSTAGRAM: instagram_handle, LINKEDIN: linkedin_slug}


#: The predicates that say "this link is the person's own account" — the only ones a profile link may carry (none at all
#: also counts). None of them is a `world` or `artifact` predicate, so a link Stage 5.56 attaches from a claim's cited
#: words (always under that claim's own predicate) can never qualify; a test pins that.
PROFILE_PREDICATES = frozenset({"profile", "identity", "account", "handle", "social", "github", "x", "twitter",
                                "linkedin", "instagram", "scholar", "orcid"})
#: The person may also file their own profile link as their `website`.
_PERSON_PREDICATES = PROFILE_PREDICATES | {"website"}
#: Machine writers that never speak for the person's identity: Cicada's own syncs and an unidentified proposal.
_NOT_AN_AGENT = frozenset({"cicada", "agent"})


def is_own_account(source: dict) -> bool:
    """Review B2 — a link counts as the person's OWN account only when somebody said so: the person added or took it
    (`fact_sources.trusted`) with no fact attached or a profile predicate (a person's `works-at` link to an org is the
    org's), or an identified agent added it with no fact attached or a profile predicate. Never Cicada's own writers,
    never an unidentified proposal, never an "Only I know" note — with one exception (owner 2026-10-17): the profile
    link the person's own LinkedIn connections put on a page they matched confidently (`linkedin_people`: the page's
    own name or a link the person or an identified agent listed as their account — never an alias-only guess, which waits for the person to take
    it). "If it's because I'm connected", it is that person's account."""
    from api.services import fact_sources, linkedin_people

    predicate = str(source.get("predicate") or "").strip().lower()
    if fact_sources.is_proposed(source):
        return False   # ruling 36 D5: inferred from the record, not yet taken by the person — never a face
    if fact_sources.trusted(source):
        return not predicate or predicate in _PERSON_PREDICATES
    who = str(source.get("added_by") or "").strip().lower()
    if (who == linkedin_people.AUTHOR and predicate == linkedin_people.SOURCE_PREDICATE
            and source.get(linkedin_people.MATCH_KEY) in linkedin_people.CONFIDENT_MATCHES):
        return True
    if not who or who in _NOT_AN_AGENT:
        return False
    return not predicate or predicate in PROFILE_PREDICATES


def _matcher(provider: str):
    parse = _PARSERS[provider]

    def serves(source: dict, _predicate) -> bool:
        kind = str(source.get("kind") or "url").strip().lower()
        return kind == "url" and parse(source.get("ref")) is not None and is_own_account(source)

    return serves


def candidates(fm: dict, *, owner: dict | None = None, proxy: bool | None = None,
               public: str | None = None) -> list[Candidate]:
    """The identifiers a `person` page offers, in the order they are asked: the owner's email (only on the page marked
    `owner: true`), then the best-ranked GitHub profile link among its sources, then the public figure's Wikidata item
    (``public``: the item ruling 44's full public test matched, :func:`public_item` — never on the owner's page), then
    the X, Instagram and LinkedIn links — those only while the proxy gate is on (``proxy``, default
    :func:`proxy_allowed`), so turning it on changes the identifier set and re-asks. Nothing derived from a name.
    `owner` is `owner.json`'s content; read only on the owner's page."""
    fm = fm or {}
    if str(fm.get("type") or "").strip().lower() != "person":
        return []
    out: list[Candidate] = []
    if fm.get("owner") is True:
        if owner is None:
            from api.services import owner_identity

            owner = owner_identity.load_owner()
        digest = gravatar_hash((owner or {}).get("email"))
        if digest:
            out.append(Candidate(GRAVATAR, digest))
    from api.services import fact_sources

    providers = [GITHUB, WIKIDATA] + ([X, INSTAGRAM, LINKEDIN] if (proxy_allowed() if proxy is None else proxy) else [])
    for provider in providers:
        if provider == WIKIDATA:
            if public and fm.get("owner") is not True and _QID_RE.fullmatch(str(public)):
                out.append(Candidate(WIKIDATA, str(public)))
            continue
        for source in fact_sources.rank(fm.get("sources"), None, match=_matcher(provider)):
            out.append(Candidate(provider, _PARSERS[provider](source["ref"])))
            break
    return out


def public_item(memory_path, entity_id: str, fm: dict) -> str | None:
    """The Wikidata item of a person ruling 44's full public test called a public figure (`web_context.public_items`,
    the memo outside every bank), else None — never for the owner's page, a demo bank or a page that is not a person.
    No network."""
    from api.services import demo_guard, web_context

    if str((fm or {}).get("type") or "").strip().lower() != "person" or (fm or {}).get("owner") is True:
        return None
    item = web_context.public_items(Path(memory_path)).get(entity_id)   # one stat when nothing is public
    return None if item is None or demo_guard.is_demo(Path(memory_path)) else item


def identity_key(cands: list[Candidate]) -> str | None:
    """What the cache entry is filed under: a hash of the identifiers, so a changed or removed one re-resolves and the
    index never holds the email's hash itself."""
    if not cands:
        return None
    text = "\n".join(f"{c.provider}:{c.value.lower()}" for c in cands)
    return hashlib.sha256(("cicada-person-photo\n" + text).encode("utf-8")).hexdigest()[:16]


def provider_url(cand: Candidate) -> str:
    """The one URL a candidate is asked at. A Wikidata candidate's value is the Commons FILE name by then
    (:func:`_portrait_file`), never the item or a person's name."""
    if cand.provider == WIKIDATA:
        return _URLS[WIKIDATA].format(value=quote(cand.value.replace(" ", "_"), safe=""))
    return _URLS[cand.provider].format(value=cand.value)


WikidataGet = Callable[[dict], Awaitable[dict | None]]


async def _portrait_file(item: str, get: WikidataGet) -> tuple[str | None, bool]:
    """``(Commons file name, transient)`` of the item's image (P18), asked of Wikidata by item alone on ruling 44's
    rail (`org_sites.wikidata_get`: 4 s, ≤ 512 KB, no cookies, `net_guard`, a block never retried). A failed request
    is transient; an item with no image, or a value that is not one plain image file name, is a plain miss."""
    from api.services import org_sites

    if not _QID_RE.fullmatch(item or ""):
        return None, False
    try:
        data = await get({"action": "wbgetclaims", "entity": item, "property": "P18"})
    except Exception as exc:  # noqa: BLE001 — a failed lookup is no answer
        logger.debug(f"portrait lookup failed: {type(exc).__name__}")
        return None, True
    if data is None or "claims" not in data:
        return None, True
    for name in org_sites._claim_values(data, "P18"):
        if isinstance(name, str) and _COMMONS_FILE_RE.fullmatch(name.strip()):
            return name.strip(), False
    return None, False


# --- gates and the fetch ----------------------------------------------------------------------------------------


def fetch_allowed() -> bool:
    """Both gates: the logo gate covers every picture fetch, this one people only. On by default (the owner allowed
    it, 2026-10-09); the test suite turns both off."""
    own = os.environ.get(GATE_ENV, "on").strip().lower() not in {"off", "0", "false"}
    return own and logo_service.fetch_allowed()


def proxy_allowed() -> bool:
    """The X/Instagram/LinkedIn proxy: its own gate, ON by default since ruling 36 D5 (owner 2026-10-22: "photo gate
    ON"; it was off from 2026-10-09) — ``off`` still turns it off — and never past the other two."""
    own = os.environ.get(PROXY_GATE_ENV, "on").strip().lower() not in {"off", "0", "false"}
    return own and fetch_allowed()


def budget_path() -> Path:
    """The install-wide proxy budget, outside every bank: ``$CICADA_HOME/pictures/proxy_budget.json``."""
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(raw).expanduser() / "pictures" / BUDGET_FILENAME


def _take_budget_sync() -> bool:
    """Spend one proxy lookup from today's (UTC) allowance; False when it is spent. Under a file lock, so two
    processes (the server and the CLI) share one count."""
    path = budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    with open(path.with_name(BUDGET_FILENAME + ".lock"), "a+") as handle:
        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        used = int(data.get("count") or 0) if isinstance(data, dict) and data.get("day") == today else 0
        if used >= PROXY_DAILY_BUDGET:
            return False
        tmp = path.with_name(f"{BUDGET_FILENAME}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"day": today, "count": used + 1}) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return True


def _provider_host(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    return (host == "gravatar.com" or host.endswith(".gravatar.com") or host == "github.com"
            or host == "avatars.githubusercontent.com" or host == "unavatar.io" or host in _WIKIMEDIA_HOSTS)


def _user_agent(url: str) -> str:
    """Wikimedia's User-Agent policy asks for a contact (the project's own page, never a person's identifier)."""
    from api.services import org_sites

    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""
    return org_sites.USER_AGENT if host in _WIKIMEDIA_HOSTS else logo_service.USER_AGENT


async def _http_get(url: str) -> FetchResult:
    """The default transport: one hop, no redirects followed (the caller re-checks each), a fresh client (no cookies,
    no credentials), the body streamed and cut one byte past the bound."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
        async with client.stream("GET", url, headers={"User-Agent": _user_agent(url),
                                                      "Accept": "image/png,image/jpeg"}) as resp:
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    break
            return FetchResult(status=resp.status_code, body=bytes(body[:MAX_BYTES + 1]),
                               content_type=resp.headers.get("content-type", ""),
                               location=resp.headers.get("location"))


async def _get(url: str, fetcher: Fetcher, *, timeout: float = TIMEOUT_SECONDS,
               spend=None) -> tuple[FetchResult | None, bool]:
    """One logical GET within the rail, every hop inside ``timeout`` (≤ 4 s, less when the ladder's deadline is near).
    Returns ``(result, transient)``: ``transient`` is True when the connection failed, time ran out or ``spend`` (the
    proxy's daily budget) said no — worth a sooner retry; a refusal or a long redirect chain is a plain miss. ``spend``
    is asked once, only after the first hop passed the host and `net_guard` checks, so a request that could never go
    costs nothing. Never logs a URL — the email's hash is in it."""
    current = url
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout)
    for hop in range(MAX_REDIRECTS + 1):
        if not _provider_host(current) or not await net_guard.is_fetchable_url_async(current):
            return None, False
        if hop == 0 and spend is not None and not await spend():
            return None, True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None, True
        try:
            result = await asyncio.wait_for(fetcher(current), timeout=remaining)
        except Exception as exc:  # noqa: BLE001 — a dead host never raises into the caller
            logger.debug(f"person photo fetch failed: {type(exc).__name__}")
            return None, True
        if result.status in (301, 302, 303, 307, 308) and result.location:
            current = urljoin(current, result.location)
            continue
        return result, False
    return None, False


def accept(result: FetchResult | None) -> tuple[bytes, str] | None:
    """A PNG or a JPEG by its own bytes, ≤ 512 KB, 16–1024 px a side — else None (an SVG whatever its header, a GIF,
    a page, a tracking pixel)."""
    from api.services import entity_picture

    if result is None or result.status != 200 or not result.body or len(result.body) > MAX_BYTES:
        return None
    if "svg" in (result.content_type or "").lower() or logo_service.looks_like_svg(result.body):
        return None
    ext = entity_picture.sniff(result.body)
    size = entity_picture.dimensions(result.body) if ext else None
    if ext not in EXTS or size is None:
        return None
    if min(size) < entity_picture.MIN_SIDE or max(size) > entity_picture.MAX_SIDE:
        return None
    return result.body, ext


# --- the cache --------------------------------------------------------------------------------------------------


def _root(bank: str) -> Path:
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(raw).expanduser() / "pictures" / (bank or "default") / PEOPLE_DIR


def meta_path(bank: str) -> Path:
    """The index, without creating anything (a read must not conjure a folder — `logo_service.meta_path`'s rule)."""
    return _root(bank) / META_FILENAME


def photo_path(bank: str, entity_id: str, ext: str) -> Path | None:
    """The stored photo's path, derived from the id; None for an ext it never stores or an id that leaves the folder."""
    if ext not in EXTS:
        return None
    base = _root(bank).resolve()
    path = (base / f"{entity_id}.{ext}").resolve()
    return path if path.parent == base else None


def read_meta(bank: str) -> dict:
    try:
        data = json.loads(meta_path(bank).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_meta(bank: str, meta: dict) -> None:
    path = meta_path(bank)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def _flock(bank: str):
    directory = _root(bank)
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / LOCK_FILENAME, "a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _record_sync(bank: str, entity_id: str, entry: dict | None) -> None:
    """Read-modify-write one entry (None removes it) under the cross-process lock."""
    with _flock(bank):
        meta = read_meta(bank)
        if entry is None:
            meta.pop(entity_id, None)
        else:
            meta[entity_id] = entry
        write_meta(bank, meta)


def _drop_files(bank: str, entity_id: str, *, keep: str | None = None) -> None:
    for ext in EXTS:
        path = photo_path(bank, entity_id, ext)
        if ext != keep and path is not None:
            path.unlink(missing_ok=True)


def _fetched_at(entry: dict) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str((entry or {}).get("fetched_at")))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _miss_due(entry: dict) -> datetime | None:
    """When a miss may be asked again; None for a hit (kept until its identifier changes)."""
    if not (entry or {}).get("miss"):
        return None
    fetched = _fetched_at(entry)
    if fetched is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return fetched + (TRANSIENT_TTL if entry.get("transient") else MISS_TTL)


def _fresh_miss(entry: dict, now: datetime | None = None) -> bool:
    due = _miss_due(entry)
    return due is not None and (now or datetime.now(timezone.utc)) < due


def _hit_file(bank: str, entity_id: str, entry: dict) -> Path | None:
    if not entry or entry.get("miss"):
        return None
    path = photo_path(bank, entity_id, str(entry.get("ext") or ""))
    return path if path is not None and path.is_file() else None


def available(entity_id: str, fm: dict, meta: dict, *, owner: dict | None = None,
              bank: str | None = None, public: str | None = None) -> tuple[bool, str | None, str | None]:
    """The `profile` rung's inputs for `/graph` and the card: ``(offered, sha, key)``. Offered while the page has an
    identifier and is not known to miss under it; ``sha`` once a photo for THIS identifier is stored (checked on disk
    when ``bank`` is given); ``key`` the identifiers' hash, which names the URL until a copy is stored (review B1: a
    changed identifier is a new URL, so the app's disk cache can never pin a stale photo). ``public`` is the page's
    :func:`public_item`. No network, ever."""
    key = identity_key(candidates(fm, owner=owner, public=public))
    if key is None:
        return False, None, None
    entry = (meta or {}).get(entity_id)
    if not isinstance(entry, dict) or entry.get("key") != key:
        return True, None, key
    if entry.get("miss"):
        return (not _fresh_miss(entry)), None, key
    sha = entry.get("sha") if isinstance(entry.get("sha"), str) else None
    if bank is not None and _hit_file(bank, entity_id, entry) is None:
        return True, None, key
    return True, sha, key


_STAMPS: dict[str, tuple[float, int, float | None]] = {}


def stamp(bank: str) -> str:
    """The cache's version stamp for `/sync/version`: ``<meta.json mtime>:<misses past their window>``. A miss aging
    out writes nothing, yet it turns the rung back on for `/graph`; the count moves on exactly that."""
    try:
        mtime = meta_path(bank).stat().st_mtime
    except OSError:
        mtime = 0.0
    cached = _STAMPS.get(bank)
    if cached is None or cached[0] != mtime or (cached[2] is not None and time.time() >= cached[2]):
        now = datetime.now(timezone.utc)
        expired, soonest = 0, None
        for entry in read_meta(bank).values():
            due = _miss_due(entry) if isinstance(entry, dict) else None
            if due is None:
                continue
            if due <= now:
                expired += 1
            elif soonest is None or due.timestamp() < soonest:
                soonest = due.timestamp()
        _STAMPS[bank] = cached = (mtime, expired, soonest)
    return f"{mtime:.6f}:{cached[1]}"


# --- on demand --------------------------------------------------------------------------------------------------


async def ensure_photo(memory_path, entity_id: str, *, fetcher: Fetcher | None = None,
                       wikidata: WikidataGet | None = None, still_public=None) -> Path | None:
    """Resolve → cache → (once) fetch → store. Only for a `person` page whose picture would be this rung: the person's
    own choice or a Contacts photo means nothing is asked. Returns the stored file, or None. ``wikidata`` (default
    `org_sites.wikidata_get`) and ``still_public`` (default :func:`_still_public`) are for tests."""
    from api.services import demo_guard

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        return None   # a demo is synthetic: nothing about it is asked of the network
    bank = logo_service.bank_name(memory_path)
    async with logo_service._lock(f"person:{bank}/{entity_id}"):
        return await _ensure_locked(memory_path, bank, entity_id, fetcher or _http_get, wikidata=wikidata,
                                    still_public=still_public or _still_public)


def _still_public(memory_path: Path, entity_id: str) -> bool:
    """Ruling 44's local test, run again just before a portrait is asked (err private): the memo's match can be weeks
    old, and an acquaintance on the record since makes the page private. No network."""
    from api.services import web_context, web_settle

    try:
        page = web_context.load_page(memory_path, entity_id)
        if page is None:
            return False
        return web_context.local_verdict(memory_path, page, web_settle.bank_facts(memory_path)).public is None
    except Exception as exc:  # noqa: BLE001 — a test that cannot run says private
        logger.debug(f"public test failed: {type(exc).__name__}")
        return False


async def _ensure_locked(memory_path: Path, bank: str, entity_id: str, fetcher: Fetcher, *,
                         wikidata: WikidataGet | None = None, still_public=_still_public) -> Path | None:
    from api.services import entity_picture

    page = memory_path / "entities" / f"{entity_id}.md"
    if not page.is_file():
        return None
    try:
        fm = markdown_parser.parse(page).frontmatter or {}
    except Exception:  # noqa: BLE001 — an unreadable page asks nobody
        return None
    inputs = entity_picture.with_chat(memory_path, entity_id, entity_picture.inputs_for(fm))
    # Every rung above this one outranks it: the person's choice, a Contacts photo, the photo their chat shares.
    if inputs.type != "person" or inputs.choice is not None or inputs.contacts_sha is not None \
            or inputs.messages_sha is not None:
        return None
    cands = candidates(fm, public=public_item(memory_path, entity_id, fm))
    key = identity_key(cands)
    entry = read_meta(bank).get(entity_id)
    if key is None:
        # The identifier went (a link removed): so does the photo it drew.
        if entry is not None:
            _drop_files(bank, entity_id)
            await asyncio.to_thread(_record_sync, bank, entity_id, None)
        return None
    if isinstance(entry, dict) and entry.get("key") == key:
        hit = _hit_file(bank, entity_id, entry)
        if hit is not None:
            return hit
        if _fresh_miss(entry):
            return None
    if not fetch_allowed():
        return None   # never asked is not a miss
    transient = False
    found: tuple[bytes, str] | None = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + LADDER_SECONDS

    async def spend() -> bool:
        return await asyncio.to_thread(_take_budget_sync)

    for cand in cands:
        remaining = deadline - loop.time()
        if remaining <= 0:
            transient = True   # out of time: asked again soon, never a cached miss
            break
        if cand.provider == WIKIDATA:
            # Owner 2026-10-28 (C): the local public test once more (err private), then the item's image by item
            # alone, then that file from Commons by its own name — the person's name is never sent again.
            if not await asyncio.to_thread(still_public, memory_path, entity_id):
                continue
            if wikidata is None:
                from api.services import org_sites

                wikidata = org_sites.wikidata_get
            try:
                name, failed = await asyncio.wait_for(_portrait_file(cand.value, wikidata),
                                                      timeout=max(0.1, deadline - loop.time()))
            except asyncio.TimeoutError:
                name, failed = None, True
            transient = transient or failed
            if name is None:
                continue
            cand = Candidate(WIKIDATA, name)
            remaining = deadline - loop.time()
            if remaining <= 0:
                transient = True
                break
        # Over today's proxy allowance is transient too: asked again tomorrow.
        result, failed = await _get(provider_url(cand), fetcher, timeout=min(TIMEOUT_SECONDS, remaining),
                                    spend=spend if cand.provider in PROXIED else None)
        transient = transient or failed
        found = accept(result)
        if found is not None:
            break
    now = datetime.now(timezone.utc).isoformat()
    if found is None:
        _drop_files(bank, entity_id)
        await asyncio.to_thread(_record_sync, bank, entity_id, {
            "key": key, "fetched_at": now, "miss": True, "transient": transient, "ext": None, "sha": None})
        return None
    data, ext = found
    path = photo_path(bank, entity_id, ext)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    _drop_files(bank, entity_id, keep=ext)
    await asyncio.to_thread(_record_sync, bank, entity_id, {
        "key": key, "fetched_at": now, "miss": False, "transient": False, "ext": ext,
        "sha": entity_picture.sha12(data)})
    return path
