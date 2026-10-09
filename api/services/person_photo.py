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
  that the person or an agent attached (best-ranked first, `fact_sources.rank`; an "Only I know" note never counts).

Never a name, an alias, a domain or a username guessed from either. Never X/Twitter or LinkedIn, and never a
third-party proxy that is handed the identifier: the request goes to the service itself, and only to its own hosts.

**The ladder** (the owner's model, adapted): the person's own choice → the Contacts photo → the email's public photo
(asked with ``d=404``, so a "no photo" answer is a 404, never a default image cached as a photo) → the GitHub avatar →
the monogram. `entity_picture.resolve` holds the precedence; this module answers its `profile` rung's availability
(read-only, from the cache index) and does the one fetch, on demand, when the app asks `GET /entities/{id}/photo`.

**The fetch** — two fixed URL shapes, `https` only, every hop (redirects followed by hand, at most 3) checked against
the providers' own hosts AND `net_guard`; 4 s in all, ≤ 512 KB read and then stopped, a fresh client with no cookies
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
from urllib.parse import urljoin, urlparse

from loguru import logger

from api.services import logo_service, markdown_parser, net_guard
from api.services.logo_service import FetchResult

GATE_ENV = "CICADA_ALLOW_PERSON_PHOTO_FETCH"
PEOPLE_DIR = "people"
META_FILENAME = "meta.json"
LOCK_FILENAME = "meta.lock"
MISS_TTL = timedelta(days=30)
TRANSIENT_TTL = timedelta(days=1)
MAX_BYTES = logo_service.MAX_BYTES
TIMEOUT_SECONDS = logo_service.TIMEOUT_SECONDS
MAX_REDIRECTS = 3
SIZE = 256
EXTS = ("png", "jpg")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg"}

GRAVATAR = "gravatar"
GITHUB = "github"
_URLS = {
    GRAVATAR: "https://gravatar.com/avatar/{value}?s=" + str(SIZE) + "&d=404",
    GITHUB: "https://github.com/{value}.png?size=" + str(SIZE),
}
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


def _github_source(source: dict, _predicate) -> bool:
    kind = str(source.get("kind") or "url").strip().lower()
    return kind == "url" and github_username(source.get("ref")) is not None


def candidates(fm: dict, *, owner: dict | None = None) -> list[Candidate]:
    """The identifiers a `person` page offers, in the order they are asked: the owner's email (only on the page marked
    `owner: true`), then the best-ranked GitHub profile link among its sources. Nothing derived from a name. `owner`
    is `owner.json`'s content; read only when the page is the owner's."""
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

    for source in fact_sources.rank(fm.get("sources"), None, match=_github_source):
        out.append(Candidate(GITHUB, github_username(source["ref"])))
        break
    return out


def identity_key(cands: list[Candidate]) -> str | None:
    """What the cache entry is filed under: a hash of the identifiers, so a changed or removed one re-resolves and the
    index never holds the email's hash itself."""
    if not cands:
        return None
    text = "\n".join(f"{c.provider}:{c.value.lower()}" for c in cands)
    return hashlib.sha256(("cicada-person-photo\n" + text).encode("utf-8")).hexdigest()[:16]


def provider_url(cand: Candidate) -> str:
    return _URLS[cand.provider].format(value=cand.value)


# --- gates and the fetch ----------------------------------------------------------------------------------------


def fetch_allowed() -> bool:
    """Both gates: the logo gate covers every picture fetch, this one people only. On by default (the owner allowed
    it, 2026-10-09); the test suite turns both off."""
    own = os.environ.get(GATE_ENV, "on").strip().lower() not in {"off", "0", "false"}
    return own and logo_service.fetch_allowed()


def _provider_host(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    return (host == "gravatar.com" or host.endswith(".gravatar.com") or host == "github.com"
            or host == "avatars.githubusercontent.com")


async def _http_get(url: str) -> FetchResult:
    """The default transport: one hop, no redirects followed (the caller re-checks each), a fresh client (no cookies,
    no credentials), the body streamed and cut one byte past the bound."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
        async with client.stream("GET", url, headers={"User-Agent": logo_service.USER_AGENT,
                                                      "Accept": "image/png,image/jpeg"}) as resp:
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    break
            return FetchResult(status=resp.status_code, body=bytes(body[:MAX_BYTES + 1]),
                               content_type=resp.headers.get("content-type", ""),
                               location=resp.headers.get("location"))


async def _get(url: str, fetcher: Fetcher) -> tuple[FetchResult | None, bool]:
    """One logical GET within the rail. Returns ``(result, transient)``: ``transient`` is True only when the
    connection failed or timed out (worth a sooner retry); a refusal or a long redirect chain is a plain miss. Never
    logs a URL — the email's hash is in it."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not _provider_host(current) or not await net_guard.is_fetchable_url_async(current):
            return None, False
        try:
            result = await asyncio.wait_for(fetcher(current), timeout=TIMEOUT_SECONDS)
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
              bank: str | None = None) -> tuple[bool, str | None]:
    """The `profile` rung's inputs for `/graph` and the card: ``(offered, sha)``. Offered while the page has an
    identifier and is not known to miss under it; ``sha`` once a photo for THIS identifier is stored (checked on disk
    when ``bank`` is given). No network, ever."""
    key = identity_key(candidates(fm, owner=owner))
    if key is None:
        return False, None
    entry = (meta or {}).get(entity_id)
    if not isinstance(entry, dict) or entry.get("key") != key:
        return True, None
    if entry.get("miss"):
        return (not _fresh_miss(entry)), None
    sha = entry.get("sha") if isinstance(entry.get("sha"), str) else None
    if bank is not None and _hit_file(bank, entity_id, entry) is None:
        return True, None
    return True, sha


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


async def ensure_photo(memory_path, entity_id: str, *, fetcher: Fetcher | None = None) -> Path | None:
    """Resolve → cache → (once) fetch → store. Only for a `person` page whose picture would be this rung: the person's
    own choice or a Contacts photo means nothing is asked. Returns the stored file, or None."""
    from api.services import demo_guard

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        return None   # a demo is synthetic: nothing about it is asked of the network
    bank = logo_service.bank_name(memory_path)
    async with logo_service._lock(f"person:{bank}/{entity_id}"):
        return await _ensure_locked(memory_path, bank, entity_id, fetcher or _http_get)


async def _ensure_locked(memory_path: Path, bank: str, entity_id: str, fetcher: Fetcher) -> Path | None:
    from api.services import entity_picture

    page = memory_path / "entities" / f"{entity_id}.md"
    if not page.is_file():
        return None
    try:
        fm = markdown_parser.parse(page).frontmatter or {}
    except Exception:  # noqa: BLE001 — an unreadable page asks nobody
        return None
    inputs = entity_picture.inputs_for(fm)
    if inputs.type != "person" or inputs.choice is not None or inputs.contacts_sha is not None:
        return None
    cands = candidates(fm)
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
    for cand in cands:
        result, failed = await _get(provider_url(cand), fetcher)
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
