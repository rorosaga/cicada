"""Tracked sources keep facts current: dated re-checks, dead sites, and the newest evidence wins (G61).

Owner ruling 2026-10-14 (TODO ruling 26), amending the G61 rail "a check never settles, reorders or changes a
belief": a source the person added, or one Cicada's own read confirmed (``fact_sources.trusted``), is **re-checked** on a
cadence (``DEFAULT_EVERY_DAYS``, a per-source ``recheck_days``) or when the person asks, and what the page says now is
**a new dated fact** — the page and the capture date as its evidence, the old fact's validity closed (bi-temporal,
nothing deleted). An inbox *check* (``check_record``, the S3 shadow) is unchanged: it still settles nothing.

**The newest evidence wins, even over the person's own words** (owner amendment, same evening: "it can override
something I said if it has evidence, there is no problem with that"). One rule, :func:`fold`, for every writer:

* a re-check captured AFTER the day a belief was last said supersedes it; the belief stays as history (closed);
* a belief said AFTER the capture stands, and the reading writes nothing on the page (its episode keeps it);
* only a clash with no clear order — the same day, or a belief with no date — becomes ONE inbox question with both
  sides and their dates (``kind: divergence``, the existing two-claim answer path);
* a predicate the vocabulary marks multi-valued (``works-at``) gains a value beside the others, and a value ends only
  on the source's own evidence that it ended (``ended``), under the same dating rule.

Nothing changes silently: the new belief's text says what changed, from where and when ("role updated 2026-11-03 from
example.com: …, was …"), the commit is one manifest line per file (``cicada_timeline``), and git reverts it.

**Dead sites.** "Gone" needs two failed visits at least :data:`DEAD_GAP_DAYS` apart, each one of :data:`MISSES`
(not found, gone, parked, moved). A dead source is marked with the dates (``refresh.dead``) and its last good capture
(``refresh.good`` / ``refresh.episode``) is kept. A good visit clears the strikes.

**Who checks** (:func:`checker`): a public page is read by Cicada's own fetcher on the Sleep tail (:func:`run_tail`,
behind ``CICADA_ALLOW_CONNECTOR_FETCH``, on the link rail's one transport: 4 s, ≤ 512 KB, no cookies, a block never
retried). That read is deterministic — no model: it states only what the page says in machine-readable form
(schema.org JSON-LD: ``jobTitle``, ``worksFor``, ``homeLocation``…, :data:`FIELDS`), and a page whose words changed
with no such field is marked ``changed`` and handed to the person's agent. A login-walled source (LinkedIn and the
like, ``reading_hosts.is_walled`` / ``fact_sources.is_refused_host``) is NEVER fetched by the backend: only the
person's own agent reads it, through this module's small lease queue (:func:`claim`, the explore queue's rules: one
live lease per site, 15 minutes, a wall pauses the site a week), in the signed-in session only while the person's
Reading-the-web switches allow it (:func:`agent_refusal`). Ruling 4: nothing scheduled uses a plan — "due" checks are
only LISTED (:func:`due`, :func:`agent_due`); the agent works them when the person asks, or when the hook's one line
leads them to ask.

State lives on the source entry itself (``sources:`` frontmatter), under ``refresh``::

    refresh: {at, outcome, good, episode, hash, changed, asked, tries, blocked, misses: [{at, outcome}], dead: {...}}

and the person's cadence under ``recheck_days``. Every write is a page's frontmatter (plus its claims fence, a
``source-refresh`` episode and, rarely, one inbox item), committed by the caller.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import bank_index, episode_ids, episode_scrub, fact_sources, git_service, markdown_parser, \
    page_lock, reading_hosts

ORIGIN = "source-refresh"          # a re-check's claims (`origin`) and its episodes (`source`)
TRIGGER = "sleep/source-refresh"
ROUTE_TRIGGER = "user/companion_app"
AUTHOR = fact_sources.CICADA
STATE_KEY = "refresh"
EVERY_KEY = "recheck_days"

DEFAULT_EVERY_DAYS = 30
MIN_EVERY_DAYS = 7
MAX_EVERY_DAYS = 365
DEAD_GAP_DAYS = 7
MAX_TRIES = 3
TAIL_BUDGET = 20
MAX_VALUE_CHARS = 120
MAX_QUOTES = 3
MAX_QUOTE_CHARS = 240
MAX_SUMMARY_CHARS = 500
MAX_ENDED = 5
#: How old a capture an agent may record (it is what the page says NOW) and how far ahead of this clock it may be.
CAPTURE_MAX_AGE = timedelta(days=2)
CAPTURE_SKEW = timedelta(minutes=10)

CICADA = "cicada"
AGENT = "agent"

#: The failed visits that count toward "gone" (design §3, D6): a 404/410, a name or connection failure, a parked
#: domain, a landing on another site.
MISSES = ("not_found", "gone", "parked", "moved")
#: What an agent records: ``read`` (what the page says now), or one of the misses.
RECORD_OUTCOMES = ("read",) + MISSES
#: What an agent hands back instead: a wall pauses the whole site; nothing is retried with different headers.
RELEASE_CODES = ("needs_login", "blocked", "failed", "skipped")
PAUSING = ("needs_login", "blocked")

LEASE_MINUTES = 15
PAUSE_DAYS = 7
CLAIM_MAX = 5

#: A predicate the source re-checks -> the schema.org fields that state it. Closed and small on purpose: Cicada's own
#: read states only what a page says about itself in machine-readable form; anything else is the person's agent's.
FIELDS: dict[str, tuple[str, ...]] = {
    "role": ("jobTitle",), "job-title": ("jobTitle",), "title": ("jobTitle",), "has-role": ("jobTitle",),
    "position": ("jobTitle",),
    "works-at": ("worksFor",), "employed-by": ("worksFor",),
    "lives-in": ("homeLocation", "address"), "based-in": ("homeLocation", "address", "location"),
    "located-in": ("address", "location"),
    "studied-at": ("alumniOf",), "alumni-of": ("alumniOf",),
}

#: Parking services and "for sale" titles (design §3: a short, closed list).
PARKING_HOSTS = frozenset({
    "sedoparking.com", "parkingcrew.net", "bodis.com", "dan.com", "afternic.com", "hugedomains.com", "sav.com",
    "parklogic.com", "above.com", "undeveloped.com", "domainmarket.com",
})
_PARKED_TITLE = re.compile(
    r"\b(domain (name )?(is )?for sale|buy this domain|this domain (name )?(is|may be) for sale|domain parked|"
    r"parked domain|parked free)\b", re.IGNORECASE)
_LD_JSON = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
                      re.IGNORECASE | re.DOTALL)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


# ---- the source's own state -----------------------------------------------------------------------------------------


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def every_days(source: dict) -> int:
    """The source's cadence in days: the person's ``recheck_days``, clamped, else :data:`DEFAULT_EVERY_DAYS`."""
    try:
        days = int(source.get(EVERY_KEY))
    except (TypeError, ValueError):
        return DEFAULT_EVERY_DAYS
    return max(MIN_EVERY_DAYS, min(MAX_EVERY_DAYS, days))


def state(source: dict) -> dict:
    raw = source.get(STATE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def dead(source: dict) -> dict | None:
    d = state(source).get("dead")
    return dict(d) if isinstance(d, dict) else None


def _url_ref(source: dict) -> str | None:
    ref = str(source.get("ref") or "").strip()
    kind = str(source.get("kind") or fact_sources.infer_kind(ref))
    if kind != fact_sources.KIND_URL or not ref.lower().startswith(("http://", "https://")):
        return None
    return ref


def walled(ref: str) -> bool:
    """A page Cicada never reads on its own: a walled family, a refused host, or a login/consent page."""
    from api.services.link_enrichment import classify_page

    return reading_hosts.is_walled(ref) or fact_sources.is_refused_host(ref) or classify_page("", ref) is not None


def checker(source: dict) -> str | None:
    """Who re-checks this source now: ``cicada`` (a public page, Cicada's own fetcher), ``agent`` (a login-walled
    page, a page whose read was blocked, or a public page Cicada saw change with no machine-readable fact), or None
    (a path, a repo, an app, a note — nothing to visit)."""
    ref = _url_ref(source)
    if ref is None:
        return None
    st = state(source)
    if walled(ref) or fact_sources.effective_access(source) == fact_sources.ACCESS_SIGNED_IN or st.get("blocked"):
        return AGENT
    return AGENT if st.get("changed") else CICADA


def tracked(source: dict) -> bool:
    """Re-checked at all: the person's own, one they took, or one Cicada's own read confirmed — never an "Only I
    know" note, never an agent's unconfirmed proposal."""
    return fact_sources.trusted(source) and not source.get("only_me") and checker(source) is not None


def due_reason(source: dict, today: date) -> str | None:
    """Why this source is due now — ``asked`` (the person asked), ``changed`` (Cicada saw the page change and could not
    read the fact), ``never`` (never re-checked), ``retry`` (a failed read, tried again the next day up to
    :data:`MAX_TRIES`), ``cadence`` — or None. A dead source is due only when the person asks."""
    if not tracked(source):
        return None
    st = state(source)
    if st.get("asked"):
        return "asked"
    if st.get("dead"):
        return None
    if st.get("changed"):
        return "changed"
    at = _day(st.get("at"))
    if at is None:
        return "never"
    if st.get("outcome") == "failed" and int(st.get("tries") or 0) < MAX_TRIES and (today - at).days >= 1:
        return "retry"
    if (today - at).days >= every_days(source):
        return "cadence"
    return None


def key_of(entity_id: str, ref: str, predicate: str | None) -> str:
    return hashlib.sha256(f"{entity_id}\x00{ref}\x00{(predicate or '').lower()}".encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Due:
    entity_id: str
    name: str
    ref: str
    predicate: str
    site: str
    checker: str
    reason: str
    last: str | None
    every: int
    dead_since: str | None = None

    @property
    def key(self) -> str:
        return key_of(self.entity_id, self.ref, self.predicate)

    def to_dict(self) -> dict:
        return {"entityId": self.entity_id, "name": self.name, "ref": self.ref, "predicate": self.predicate or None,
                "site": self.site, "checker": self.checker, "reason": self.reason, "lastChecked": self.last,
                "everyDays": self.every, "deadSince": self.dead_since}


_REASON_ORDER = {"asked": 0, "changed": 1, "never": 2, "retry": 3, "cadence": 4}


def due(memory_path: Path, *, today: date | None = None, warm_only: bool = False) -> list[Due] | None:
    """Every tracked source due a re-check, the person's asks first, then the longest unchecked. Engine-free and
    network-free: a frontmatter scan through ``bank_index`` — no spend. ``warm_only`` answers None on a cold cache
    (the hook's budget)."""
    memory_path = Path(memory_path)
    if warm_only and not bank_index.is_warm(memory_path, "entities"):
        return None
    today = today or date.today()
    out: list[Due] = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("status") or "") == "dropped":
            continue
        for source in fact_sources.as_sources(fm.get("sources")):
            reason = due_reason(source, today)
            if reason is None:
                continue
            ref = str(source.get("ref") or "")
            out.append(Due(entity_id=f.stem, name=str(fm.get("name") or f.stem), ref=ref,
                           predicate=str(source.get("predicate") or ""), site=reading_hosts.site_of(ref),
                           checker=checker(source) or CICADA, reason=reason, last=state(source).get("at"),
                           every=every_days(source), dead_since=(dead(source) or {}).get("since")))
    out.sort(key=lambda d: (_REASON_ORDER.get(d.reason, 9), d.last or "", d.entity_id, d.ref))
    return out


def tracked_count(memory_path: Path) -> dict:
    """``{tracked, dead}`` over the bank (for the due summary)."""
    tracked_n = dead_n = 0
    for f in bank_index.files(Path(memory_path), "entities"):
        for source in fact_sources.as_sources((f.frontmatter or {}).get("sources")):
            if tracked(source):
                tracked_n += 1
                dead_n += 1 if state(source).get("dead") else 0
    return {"tracked": tracked_n, "dead": dead_n}


# ---- the person's agent: consent and the lease queue ----------------------------------------------------------------


@dataclass(frozen=True)
class Consent:
    """The person's Reading-the-web switches, read ONCE per listing (``reading.json`` is read on every call)."""

    enabled: bool
    allowed: frozenset[str]
    never: frozenset[str]
    signed_in: bool

    @classmethod
    def load(cls) -> "Consent":
        from api.services import reading_settings

        return cls(reading_settings.agent_enabled(), frozenset(reading_settings.allowed_sites()),
                   frozenset(reading_settings.never_explore()), reading_settings.explore_signed_in())


def agent_refusal(due_item: Due, consent: Consent | None = None) -> str | None:
    """Why the person's agent may not check this source now, in words — None when it may. The same switches that
    govern exploring (owner ruling 25, D2/D3): agent reading on and acknowledged, the site turned on in Reading the web,
    not marked Never explore, and — for a login-walled page — the signed-in session allowed."""
    consent = consent or Consent.load()
    if not consent.enabled:
        return "agent reading is off (Settings, Reading the web)"
    if due_item.site in consent.never:
        return f"the person marked {due_item.site} Never explore"
    if due_item.site not in consent.allowed:
        return f"{due_item.site} is not turned on in Reading the web"
    if walled(due_item.ref) and not consent.signed_in:
        return "the person turned off using their signed-in browser session"
    return None


def agent_due(memory_path: Path, *, today: date | None = None, warm_only: bool = False,
              now: datetime | None = None) -> list[Due] | None:
    """The due sources the person's own agent may check now: due, worked by the agent, allowed by the person's
    switches, on a site not paused by a wall. Nothing is leased here."""
    consent = Consent.load()
    if not consent.enabled or not consent.allowed:
        return [] if not warm_only or bank_index.is_warm(Path(memory_path), "entities") else None
    items = due(memory_path, today=today, warm_only=warm_only)
    if items is None:
        return None
    paused = paused_sites(memory_path, now=now)
    return [d for d in items if d.checker == AGENT and d.site not in paused and agent_refusal(d, consent) is None]


def queue_path(memory_path: Path) -> Path:
    """The lease file for a bank, outside every bank (the explore queue's slug rule). Never creates anything."""
    from api.services import video_queue
    from api.services.auth import cicada_home

    return cicada_home() / "refresh_queue" / f"{video_queue.bank_slug(memory_path)}.json"


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _ts(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


@contextmanager
def _locked(memory_path: Path):
    target = queue_path(memory_path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(target.with_name(target.name + ".lock"), "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield target
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read(target: Path) -> dict:
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    leases = data.get("leases") if isinstance(data.get("leases"), dict) else {}
    paused = data.get("paused") if isinstance(data.get("paused"), dict) else {}
    return {"leases": {k: v for k, v in leases.items() if isinstance(v, dict)},
            "paused": {k: str(v) for k, v in paused.items() if isinstance(k, str)}}


def _write(target: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".refresh-queue-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"v": 1, **data}, indent=1, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _settle(data: dict, now: datetime) -> dict:
    data["leases"] = {k: v for k, v in data["leases"].items()
                      if (_parse_ts(v.get("until")) or now) > now}
    data["paused"] = {s: u for s, u in data["paused"].items() if (_parse_ts(u) or now) > now}
    return data


def paused_sites(memory_path: Path, *, now: datetime | None = None) -> set[str]:
    try:
        target = queue_path(memory_path)
    except Exception:
        return set()
    if not target.exists():
        return set()
    return set(_settle(_read(target), _now(now))["paused"])


def claim(memory_path: Path, *, session: str | None, harness: str | None, limit: int = 1,
          today: date | None = None, now: datetime | None = None) -> list[tuple[Due, str]]:
    """Lease up to ``limit`` due sources to this session: one live lease per site across every agent, never a site
    paused by a wall. Returns ``[(due, lease_token)]``; a source this session already holds comes back with its token."""
    moment = _now(now)
    limit = max(1, min(CLAIM_MAX, int(limit or 1)))
    items = agent_due(memory_path, today=today, now=moment) or []
    out: list[tuple[Due, str]] = []
    with _locked(memory_path) as target:
        data = _settle(_read(target), moment)
        held_sites = {v.get("site") for v in data["leases"].values() if v.get("session") != session}
        mine = {k: v for k, v in data["leases"].items() if v.get("session") == session}
        for d in items:
            if len(out) >= limit:
                break
            if d.key in mine:
                mine[d.key]["until"] = _ts(moment + timedelta(minutes=LEASE_MINUTES))
                out.append((d, str(mine[d.key]["token"])))
                continue
            if d.site in held_sites or d.site in {x.site for x, _ in out}:
                continue
            token = secrets.token_hex(16)
            data["leases"][d.key] = {"token": token, "session": session or "", "harness": harness or "",
                                     "site": d.site, "entity": d.entity_id,
                                     "claimed_at": _ts(moment), "until": _ts(moment + timedelta(minutes=LEASE_MINUTES))}
            out.append((d, token))
        _write(target, data)
    return out


def lease_ok(memory_path: Path, key: str, token: str, *, now: datetime | None = None) -> bool:
    try:
        target = queue_path(memory_path)
    except Exception:
        return False
    if not target.exists():
        return False
    held = _settle(_read(target), _now(now))["leases"].get(key)
    return bool(held) and secrets.compare_digest(str(held.get("token") or ""), str(token or ""))


def complete(memory_path: Path, key: str, *, now: datetime | None = None) -> None:
    with _locked(memory_path) as target:
        data = _settle(_read(target), _now(now))
        if data["leases"].pop(key, None) is not None:
            _write(target, data)


def release(memory_path: Path, key: str, token: str, code: str, *, now: datetime | None = None) -> str | None:
    """Hand a leased source back. A wall (``needs_login``, ``blocked``) pauses its whole site for :data:`PAUSE_DAYS`
    days — never retried with different headers or another agent. Returns the site, or None when not leased."""
    moment = _now(now)
    with _locked(memory_path) as target:
        data = _settle(_read(target), moment)
        held = data["leases"].get(key)
        if not held or not secrets.compare_digest(str(held.get("token") or ""), str(token or "")):
            return None
        data["leases"].pop(key, None)
        site = str(held.get("site") or "")
        if code in PAUSING and site:
            data["paused"][site] = _ts(moment + timedelta(days=PAUSE_DAYS))
        _write(target, data)
    return site


# ---- reading a public page on Cicada's own rail ---------------------------------------------------------------------


@dataclass
class Observation:
    """What one visit found. ``outcome``: ``read`` | a :data:`MISSES` value | ``blocked`` | ``failed``."""

    outcome: str
    values: list[str] = field(default_factory=list)
    ended: list[dict] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    captured_on: date | None = None
    text_hash: str | None = None
    summary: str = ""


StreamFn = Callable[[str], Awaitable[tuple[str, str, str]]]


def _ld_nodes(html: str) -> list[dict]:
    nodes: list[dict] = []

    def walk(value):
        if isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, dict):
            nodes.append(value)
            for key in ("@graph", "mainEntity"):
                if key in value:
                    walk(value[key])

    for raw in _LD_JSON.findall(html or "")[:20]:
        try:
            walk(json.loads(raw.strip()))
        except ValueError:
            continue
    return nodes[:200]


def _field_values(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key in ("name", "addressLocality", "jobTitle"):
            if isinstance(value.get(key), str):
                return [value[key]]
        return []
    if isinstance(value, list):
        return [v for item in value[:8] for v in _field_values(item)]
    return []


def _norm(text) -> str:
    return " ".join(str(text or "").casefold().split())


def _about(node: dict, names: list[str]) -> bool:
    label = _norm(node.get("name"))
    if not label:
        return True
    return any(n and (n == label or n in label) for n in (_norm(x) for x in names))


def structured_facts(html: str, predicate: str, names: list[str]) -> tuple[list[str], list[str]]:
    """``(values, quote lines)`` the page states for ``predicate`` in schema.org JSON-LD, about the page named
    ``names`` (a node naming someone else is skipped). Pure; no model."""
    keys = FIELDS.get((predicate or "").strip().lower())
    if not keys:
        return [], []
    values: list[str] = []
    quotes: list[str] = []
    for node in _ld_nodes(html):
        if not _about(node, names):
            continue
        for key in keys:
            for value in _field_values(node.get(key)):
                value = " ".join(value.split())[:MAX_VALUE_CHARS]
                if value and value not in values:
                    values.append(value)
                    quotes.append(f"{key}: {value}")
        if values:
            break
    return values, quotes[:MAX_QUOTES]


def text_hash(html: str) -> str:
    """A hash of the page's words with numbers masked, so a footer year or a counter is not a change."""
    from api.services.link_enrichment import _extract_visible_text

    text = re.sub(r"\d", "0", _norm(_extract_visible_text(html or "", 20000)))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def classify(ref: str, status: str, html: str, final_url: str) -> str:
    """The visit's outcome from what the one transport returned — deterministic (design §3's table)."""
    if status == "ok":
        final_site = reading_hosts.site_of(final_url) if final_url else ""
        found = _TITLE.search(html or "")
        title = " ".join(found.group(1).split()) if found else ""
        if final_site in PARKING_HOSTS or any(final_site.endswith("." + p) for p in PARKING_HOSTS) \
                or _PARKED_TITLE.search(title or ""):
            return "parked"
        if final_site and final_site != reading_hosts.site_of(ref):
            return "moved"
        return "read"
    if status == "blocked":
        return "blocked"
    if status in ("failed:http_404", "failed:http_410"):
        return "not_found"
    if status == "failed:ConnectError":
        return "gone"
    return "failed"


async def observe(ref: str, predicate: str, names: list[str], *, stream_fn: StreamFn | None = None,
                  today: date | None = None) -> Observation:
    """Read ONE public page on Cicada's own rail and say what it found. A walled host is refused before any request.
    Never raises."""
    today = today or date.today()
    if walled(ref):
        return Observation("blocked", captured_on=today)
    if stream_fn is None:
        from api.services.link_enrichment import _stream_html as stream_fn   # the ONE transport (4 s, 512 KB)
    try:
        status, html, final = await stream_fn(ref)
    except Exception as exc:  # noqa: BLE001 — never raises
        logger.warning(f"source refresh fetch failed ({type(exc).__name__})")
        return Observation("failed", captured_on=today)
    outcome = classify(ref, status, html, final)
    if outcome != "read":
        return Observation(outcome, captured_on=today)
    values, quotes = structured_facts(html, predicate, names)
    return Observation("read", values=values, quotes=quotes, captured_on=today, text_hash=text_hash(html))


# ---- the fold: the newest evidence wins -----------------------------------------------------------------------------


def said_on(claim, untimed=frozenset()) -> str | None:
    """The day a belief was last said, or None when nothing dates it. A re-check's own belief is dated by its capture;
    a belief from conversations by the latest dated one (a memory export entry says nothing about when); a live write
    with no conversation (the app, an agent) by the day it was written."""
    from api.services import decay_policy
    from api.services.claim_reconciler import _said_refs

    if (claim.origin or "") == ORIGIN:
        return str(claim.valid_from or "")[:10] or None
    refs = _said_refs(claim)
    if refs:
        return decay_policy.latest_said(refs, untimed=untimed)
    return str(claim.recorded_at or "")[:10] or None


def _same(memory_path: Path, obj: str, value: str) -> bool:
    from api.services.id_utils import sanitize_id

    if _norm(obj) == _norm(value):
        return True
    a, b = sanitize_id(str(obj or "")), sanitize_id(str(value or ""))
    return bool(a) and a == b


def _object_for(memory_path: Path, value: str) -> tuple[str, str]:
    """``(object, object_kind)``: an existing page's id when the value names one exactly, else the words."""
    from api.services.id_utils import resolve_entity_file, sanitize_id

    try:
        page = resolve_entity_file(Path(memory_path), sanitize_id(value) or value)
    except Exception:
        page = None
    return (page.stem, "node") if page is not None else (value, "literal")


@dataclass
class Fold:
    added: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    confirmed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    asked: list[tuple[object, object]] = field(default_factory=list)   # (existing claim, the source's claim)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.closed)


def is_ending(claim) -> bool:
    """A re-check's record that a value ENDED (born closed), not a value it read as current."""
    return (claim.origin or "") == ORIGIN and claim.id.rsplit("_", 1)[-1].startswith("end")


def _words(predicate: str) -> str:
    return (predicate or "fact").replace("-", " ")


def fold(memory_path: Path, claims: list, *, entity_id: str, name: str, predicate: str, values: list[str],
         ended: list[dict], captured: str, evidence: list, episode_id: str | None, host: str, observer: str,
         author: str, session_id: str | None, today: str, recorded_ts: str | None = None,
         untimed=frozenset()) -> Fold:
    """Fold one dated reading into a page's claims IN PLACE (the caller writes them). The rule is the module's: the
    newest evidence wins; a later statement stands; no clear order asks once. Pure over the list — no I/O but the
    vocabulary's cardinality and an exact page lookup for a value that names one."""
    from api.services import predicates
    from api.services.claims import Claim, is_event, is_record

    out = Fold()
    multi = predicates.cardinality(memory_path, predicate) == "multi"

    def current():
        return [c for c in claims if c.valid_to is None and c.subject == entity_id and c.predicate == predicate
                and not is_event(c) and not is_record(c)]

    def make(value: str, text: str, *, closed: bool = False) -> Claim:
        obj, kind = _object_for(memory_path, value)
        digest = hashlib.sha1(f"{entity_id}\x00{predicate}\x00{obj}\x00{captured}\x00{host}\x00{closed}".encode(
            "utf-8")).hexdigest()[:8]
        return Claim(
            id=f"clm_{entity_id}_{predicate or 'fact'}_{'end' if closed else 'src'}{digest}", text=text,
            subject=entity_id, predicate=predicate, object=obj, object_kind=kind, observer=observer,
            epistemic="explicit", source_trust="external", confidence=0.8, valid_from=captured,
            valid_to=captured if closed else None, recorded_at=today,
            source_episodes=[episode_id] if episode_id else [], authored_by=author, origin=ORIGIN,
            session_id=session_id, session_ids=[session_id] if session_id else [], evidence=list(evidence),
            recorded_ts=recorded_ts)

    def order(c) -> str:
        said = said_on(c, untimed)
        if said is None or said == captured:
            return "clash"
        return "older" if captured > said else "newer"

    for value in (values if multi else values[:1]):
        if not value:
            continue
        cur = current()
        same = [c for c in cur if _same(memory_path, c.object, value)]
        if same:
            out.confirmed += [c.id for c in same]
            continue
        if multi:
            new = make(value, f"{name}: {_words(predicate)} read {captured} from {host}: {value}")
            if all(c.id != new.id for c in claims):
                claims.append(new)
                out.added.append(new.id)
            continue
        verdicts = [(c, order(c)) for c in cur]
        if any(v == "newer" for _, v in verdicts):
            out.kept += [c.id for c, v in verdicts if v == "newer"]
            continue
        older = [c for c, v in verdicts if v == "older"]
        was = f", was {older[0].object}" if older else ""
        verb = "updated" if older else "read"
        new = make(value, f"{name}: {_words(predicate)} {verb} {captured} from {host}: {value}{was}")
        if any(c.id == new.id for c in claims):
            continue
        claims.append(new)
        out.added.append(new.id)
        for c in older:
            c.valid_to = max(captured, str(c.valid_from or captured)[:10])
            c.superseded_by = new.id
            new.supersedes = c.id
            out.closed.append(c.id)
        for c, v in verdicts:
            if v == "clash":
                out.asked.append((c, new))

    for row in ended[:MAX_ENDED]:
        value = str(row.get("value") or "").strip()[:MAX_VALUE_CHARS]
        if not value:
            continue
        on = _day(row.get("on"))
        on_s = min(on.isoformat(), captured) if on else captured
        for c in [c for c in current() if _same(memory_path, c.object, value)]:
            v = order(c)
            if v == "newer":
                out.kept.append(c.id)
            elif v == "older":
                c.valid_to = max(on_s, str(c.valid_from or on_s)[:10])
                out.closed.append(c.id)
            else:
                record = make(value, f"{name}: {_words(predicate)} {value} ended, per {host} read {captured}",
                              closed=True)
                if all(x.id != record.id for x in claims):
                    claims.append(record)
                out.asked.append((c, record))
    return out


# ---- writing one visit ----------------------------------------------------------------------------------------------


@dataclass
class Applied:
    action: str
    entity_id: str
    paths: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    episode_id: str | None = None
    fold: Fold | None = None
    item: str | None = None
    message: str = ""


def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def clean_quotes(raw) -> list[str]:
    kept: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        quote = item.get("quote") if isinstance(item, dict) else item if isinstance(item, str) else None
        text = _one_line(quote).lstrip("> ").strip()[:MAX_QUOTE_CHARS].rstrip()
        if text and len(kept) < MAX_QUOTES:
            kept.append(episode_scrub.scrub(text)[0])
    return kept


def clean_ended(raw) -> list[dict]:
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"value": item}
        if not isinstance(item, dict):
            continue
        value = episode_scrub.scrub(_one_line(item.get("value"))[:MAX_VALUE_CHARS])[0]
        if value:
            out.append({"value": value, **({"on": _iso(_day(item.get("on")))} if _day(item.get("on")) else {})})
    return out[:MAX_ENDED]


def _write_episode(memory_path: Path, *, entity_id: str, name: str, ref: str, predicate: str, host: str,
                   label: str, captured: str, quotes: list[str], summary: str, checker_kind: str,
                   session_frontmatter: dict | None, via: str | None) -> str:
    """One ``source-refresh`` episode: the reader's summary as theirs, then ``attachment [host]:`` and the page's own
    words as quote lines (``evidence`` reads them as ``page``-kind spans: what the page said, never the person).
    Processed from birth (Sleep never re-reads it) and untimed (``episode_time``: a re-check is not a mention)."""
    summary = episode_scrub.scrub(_one_line(summary))[0][:MAX_SUMMARY_CHARS] or \
        f"Re-checked {host} for {_words(predicate)} on {captured}."
    head = f"attachment [{host}]: as {label} read it on {captured}"
    body = "\n".join([f"assistant: {summary}", "", head, *[f"> {q}" for q in quotes]])
    content_hash = hashlib.sha256(f"{entity_id}\x00{ref}\x00{captured}\x00{body}".encode("utf-8")).hexdigest()[:12]
    existing = next((f.stem for f in bank_index.files(memory_path, "episodes")
                     if (f.frontmatter or {}).get("content_hash") == content_hash
                     and (f.frontmatter or {}).get("source") == ORIGIN), None)
    if existing:
        return existing
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    episode_id = episode_ids.next_episode_id(episodes_dir, captured)
    frontmatter = {
        "id": episode_id, "timestamp": episode_ids.utc_now_iso(), "source": ORIGIN,
        "origin": "mcp" if checker_kind != CICADA else CICADA,
        "title": f"Re-check: {name} ({_words(predicate)})"[:120], "processed": True,
        "processed_by": CICADA if checker_kind == CICADA else "agent", "content_hash": content_hash,
        "checked_ref": ref, "checked_host": host, "entity_id": entity_id, "captured_at": captured,
        "checker_kind": checker_kind,
        **({"predicate": predicate} if predicate else {}),
        **({"via": _one_line(via)[:80]} if via else {}),
        **(session_frontmatter or {}),
    }
    return episode_ids.create_episode(episodes_dir, frontmatter, body)


def _open_question(memory_path: Path, entity_id: str, predicate: str) -> Path | None:
    inbox = memory_path / "inbox"
    if not inbox.exists():
        return None
    for path in sorted(inbox.glob("inbox-*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:
            continue
        if (fm.get("trigger") == TRIGGER and str(fm.get("status") or "pending") == "pending"
                and fm.get("entity_id") == entity_id and str(fm.get("predicate") or "") == predicate):
            return path
    return None


def _ask(memory_path: Path, *, entity_id: str, name: str, predicate: str, existing, new, host: str,
         captured: str, episode_id: str | None, untimed) -> str | None:
    """One inbox question for a clash with no clear order — both sides and their dates. ``kind: divergence``, so the
    existing two-claim answer applies (keep / update / both). At most one open per (page, fact)."""
    from api.services import inbox_service

    if _open_question(memory_path, entity_id, predicate) is not None:
        return None
    said = said_on(existing, untimed)
    when = f"said {said}" if said else "with no date"
    ending = new.valid_to is not None
    inbox = memory_path / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"inbox-{inbox_service.next_inbox_num(inbox):03d}.md"
    reading = f"says {existing.object} ended" if ending else f"says '{new.object}'"
    body = (f"Memory holds {name}'s {_words(predicate)} as '{existing.object}' ({when}). {host} {reading}, read on "
            f"{captured}. Neither is clearly newer, so nothing was changed.")
    markdown_parser.write(path, {
        "kind": "divergence", "required_input": "choice", "status": "pending", "priority": 0.6,
        "entity_id": entity_id, "entity_name": name,
        "title": f"{host} says something different about {name}",
        "created_date": date.today().isoformat(),
        "options": [f"Keep {existing.object} ({when})",
                    (f"It ended ({host}, {captured})" if ending else f"Update to {new.object} ({host}, {captured})"),
                    "Both true — different context"],
        "predicate": predicate, "question": f"Which is current for {name}'s {_words(predicate)}?",
        "allow_other": False, "allow_defer": True, "claim_id": new.id, "existing_claim_id": existing.id,
        "source_episode": episode_id, "trigger": TRIGGER,
    }, body)
    return f"inbox/{path.name}"


def _find_entry(fm: dict, ref: str, predicate: str | None) -> dict | None:
    for s in fm.get("sources") or []:
        if isinstance(s, dict) and str(s.get("ref") or "").strip() == ref.strip() \
                and fact_sources.same_predicate(s.get("predicate"), predicate):
            return s
    return None


def apply(memory_path: Path, *, entity_id: str, ref: str, predicate: str | None, obs: Observation,
          checker_kind: str, label: str, author: str, trigger: str, session_id: str | None = None,
          session_frontmatter: dict | None = None, via: str | None = None, recorded_ts: str | None = None,
          today: date | None = None) -> Applied:
    """Write one visit onto the page: the source's state (good, a strike, dead, blocked, failed), and for a read that
    states the fact, a ``source-refresh`` episode, the folded claims and — for a clash with no clear order — one
    question. The CALLER holds the bank's page lock (and write admission, for an agent) and commits ``paths``."""
    from api.services import episode_time, evidence as evidence_mod
    from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

    memory_path = Path(memory_path)
    today = today or date.today()
    rel = f"entities/{entity_id}.md"
    page = memory_path / rel
    if not page.exists():
        return Applied("error", entity_id, message="no such page")
    parsed = markdown_parser.parse(page)
    fm, body = parsed.frontmatter, parsed.body
    entry = _find_entry(fm, ref, predicate)
    if entry is None:
        return Applied("error", entity_id, message="that source is not on the page")
    predicate = str(entry.get("predicate") or predicate or "")
    st = state(entry)
    captured = (obs.captured_on or today).isoformat()
    host = reading_hosts.display_host(reading_hosts.host_of(ref)) or "the page"
    name = str(fm.get("name") or entity_id)
    result = Applied(obs.outcome, entity_id)
    line = f"{rel}: updated (source: n/a, trigger: {trigger})"

    st.pop("asked", None)
    if obs.outcome in MISSES:
        misses = [m for m in st.get("misses") or [] if isinstance(m, dict) and _day(m.get("at"))]
        misses.append({"at": captured, "outcome": obs.outcome})
        first = min(_day(m["at"]) for m in misses)
        st["misses"] = [min(misses, key=lambda m: m["at"]), misses[-1]] if len(misses) > 1 else misses
        st.update(at=captured, outcome=obs.outcome)
        if (date.fromisoformat(captured) - first).days >= DEAD_GAP_DAYS:
            st["dead"] = {"since": first.isoformat(), "at": captured, "outcome": obs.outcome}
            result.action = "dead"
        else:
            result.action = "miss"
    elif obs.outcome == "blocked":
        st.update(at=captured, outcome="blocked", blocked=captured)
        result.action = "blocked"
    elif obs.outcome == "failed":
        st.update(at=captured, outcome="failed", tries=int(st.get("tries") or 0) + 1)
        result.action = "failed"
    else:
        for key in ("misses", "dead", "blocked", "tries", "changed"):
            st.pop(key, None)
        previous_hash = st.get("hash")
        st.update(at=captured, outcome="read", good=captured)
        if obs.text_hash:
            st["hash"] = obs.text_hash
        result.action = "checked"
        if obs.values or obs.ended:
            episode_id = _write_episode(
                memory_path, entity_id=entity_id, name=name, ref=ref, predicate=predicate, host=host, label=label,
                captured=captured, quotes=obs.quotes, summary=obs.summary, checker_kind=checker_kind,
                session_frontmatter=session_frontmatter, via=via)
            result.episode_id = episode_id
            ep_rel = f"episodes/{episode_id}.md"
            result.created.append(ep_rel)
            result.paths.append(ep_rel)
            result.lines.append(f"{ep_rel}: created (trigger: {trigger})")
            st["episode"] = episode_id
            spans = [evidence_mod.verify(memory_path, episode_id, q) for q in obs.quotes[:1]] or \
                [evidence_mod.verify(memory_path, episode_id, "")]
            try:
                claims = parse_claims(body, strict=True)
            except MalformedClaimsBlockError:
                return Applied("error", entity_id, message="the page's claims block will not parse")
            untimed = episode_time.untimed_ids(memory_path)
            folded = fold(memory_path, claims, entity_id=entity_id, name=name, predicate=predicate,
                          values=obs.values, ended=obs.ended, captured=captured, evidence=spans,
                          episode_id=episode_id, host=host, observer=CICADA if checker_kind == CICADA else AGENT,
                          author=author, session_id=session_id, today=today.isoformat(), recorded_ts=recorded_ts,
                          untimed=untimed)
            result.fold = folded
            if folded.added or folded.closed or folded.asked:
                body = write_claims(body, claims)
            for existing, new in folded.asked[:1]:
                item = _ask(memory_path, entity_id=entity_id, name=name, predicate=predicate, existing=existing,
                            new=new, host=host, captured=captured, episode_id=episode_id, untimed=untimed)
                if item:
                    result.item = item
                    result.created.append(item)
                    result.paths.append(item)
                    result.lines.append(f"{item}: created (source: {episode_id}, trigger: {trigger})")
            if folded.changed:
                line = f"{rel}: updated (source: {episode_id}, trigger: {trigger})"
            result.action = ("asked" if folded.asked else "updated" if folded.closed else
                             "added" if folded.added else "kept" if folded.kept else "confirmed")
        elif previous_hash and obs.text_hash and previous_hash != obs.text_hash and checker_kind == CICADA \
                and predicate and not fact_sources.same_predicate(predicate, fact_sources.WEBSITE):
            # The words changed and the page states no machine-readable fact: the person's agent reads it. An official
            # site's words change all the time and say nothing about a fact; its re-check is liveness only.
            st["changed"] = captured
            result.action = "changed"
    entry[STATE_KEY] = st
    markdown_parser.write(page, fm, body)
    result.paths.insert(0, rel)
    result.lines.insert(0, line)
    bank_index.invalidate(memory_path)
    return result


def describe(applied: Applied, *, host: str) -> str:
    """One sentence on what a visit changed, for an agent's reply or a log line's caller."""
    f = applied.fold
    if applied.action == "error":
        return f"Not recorded: {applied.message}."
    if applied.action == "dead":
        return f"{host} failed twice a week apart: the source is marked dead; its last good capture is kept."
    if applied.action == "miss":
        return f"{host} could not be reached properly; one more failed visit a week from now marks it dead."
    if applied.action in ("blocked", "failed"):
        return f"{host} could not be read ({applied.action}); nothing about the facts changed."
    if applied.action == "changed":
        return f"{host} changed; the person's agent will read it."
    if f is None:
        return f"{host} re-checked: nothing to compare (no fact read)."
    parts = []
    if f.added:
        parts.append(f"new dated belief {', '.join(f.added)}")
    if f.closed:
        parts.append(f"closed as history {', '.join(f.closed)}")
    if f.confirmed:
        parts.append("the page still says what memory holds")
    if f.kept:
        parts.append("a statement dated after this capture stands")
    if applied.item:
        parts.append(f"same-day or undated clash: one question ({applied.item})")
    return f"{host} re-checked: " + ("; ".join(parts) or "nothing changed") + "."


# ---- the Sleep tail and the person's "check now" --------------------------------------------------------------------


@dataclass
class Report:
    paths: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def add(self, applied: Applied) -> None:
        self.bump(applied.action)
        for p in applied.paths:
            if p not in self.paths:
                self.paths.append(p)
        self.created += [c for c in applied.created if c not in self.created]
        self.lines += [ln for ln in applied.lines if ln not in self.lines]


def _names(memory_path: Path, entity_id: str) -> list[str]:
    f = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
    fm = (f.frontmatter if f else {}) or {}
    return [str(fm.get("name") or entity_id)] + [a for a in (fm.get("aliases") or []) if isinstance(a, str)]


def asked_item(memory_path: Path, entity_id: str, ref: str, predicate: str | None) -> Due | None:
    """The one source the person asked to re-check now, as a due item — whatever its cadence says (a dead one
    included). None when it is not on the page or not tracked."""
    f = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
    fm = (f.frontmatter if f else {}) or {}
    entry = _find_entry(fm, ref, predicate)
    if entry is None or not tracked(entry):
        return None
    ref = str(entry.get("ref") or "")
    return Due(entity_id=entity_id, name=str(fm.get("name") or entity_id), ref=ref,
               predicate=str(entry.get("predicate") or ""), site=reading_hosts.site_of(ref),
               checker=checker(entry) or CICADA, reason="asked", last=state(entry).get("at"),
               every=every_days(entry), dead_since=(dead(entry) or {}).get("since"))


async def observe_due(memory_path: Path, *, budget: int = TAIL_BUDGET, skip: frozenset[str] = frozenset(),
                      stream_fn: StreamFn | None = None, today: date | None = None, report: Report | None = None,
                      only: Due | None = None) -> list[tuple[Due, Observation]]:
    """The network half: read the due PUBLIC sources on Cicada's own rail — at most ``budget`` fetches, one per site
    per run, never a walled host (refused before any request), nothing written. ``only`` (from :func:`asked_item`)
    reads that one source now, whatever its cadence."""
    import asyncio

    memory_path = Path(memory_path)
    today = today or date.today()
    report = report if report is not None else Report()
    items = [only] if only is not None else (await asyncio.to_thread(due, memory_path, today=today) or [])
    seen: set[str] = set()
    planned: list[tuple[Due, Observation]] = []
    for d in items:
        if d.checker != CICADA or f"entities/{d.entity_id}.md" in skip:
            continue
        if walled(d.ref):
            report.bump("walled")
            continue
        if len(planned) >= budget or d.site in seen:
            report.bump("deferred")
            continue
        seen.add(d.site)
        report.bump("fetched")
        names = await asyncio.to_thread(_names, memory_path, d.entity_id)
        planned.append((d, await observe(d.ref, d.predicate, names, stream_fn=stream_fn, today=today)))
    return planned


def write_observed(memory_path: Path, planned: list[tuple[Due, Observation]], *, trigger: str = TRIGGER,
                   today: date | None = None, report: Report | None = None) -> Report:
    """The write half (synchronous, a worker thread): each page under the bank's page lock — never held across a
    fetch. The caller commits ``report.paths`` or restores them."""
    memory_path = Path(memory_path)
    report = report if report is not None else Report()
    for d, obs in planned:
        with page_lock.page_lock(memory_path):
            report.add(apply(memory_path, entity_id=d.entity_id, ref=d.ref, predicate=d.predicate, obs=obs,
                             checker_kind=CICADA, label="Cicada", author=AUTHOR, trigger=trigger, today=today))
    return report


async def run_tail(memory_path: Path, *, budget: int = TAIL_BUDGET, skip: frozenset[str] = frozenset(),
                   stream_fn: StreamFn | None = None, today: date | None = None, report: Report | None = None,
                   trigger: str = TRIGGER) -> Report:
    """The Sleep tail's step: :func:`observe_due`, then :func:`write_observed`. The caller gates it
    (``CICADA_ALLOW_CONNECTOR_FETCH``) and commits ``report.paths`` (``commit_message``) or restores them
    (``restore``)."""
    import asyncio

    report = report if report is not None else Report()
    planned = await observe_due(memory_path, budget=budget, skip=skip, stream_fn=stream_fn, today=today, report=report)
    return await asyncio.to_thread(write_observed, memory_path, planned, trigger=trigger, today=today, report=report)


def mark_asked(memory_path: Path, entity_id: str, ref: str, predicate: str | None, *,
               today: date | None = None) -> bool:
    """The person asked to re-check a source: it is listed first until it is checked (and a dead one comes back)."""
    page = Path(memory_path) / "entities" / f"{entity_id}.md"
    with page_lock.page_lock(memory_path):
        parsed = markdown_parser.parse(page)
        entry = _find_entry(parsed.frontmatter, ref, predicate)
        if entry is None:
            return False
        st = state(entry)
        st["asked"] = (today or date.today()).isoformat()
        entry[STATE_KEY] = st
        markdown_parser.write(page, parsed.frontmatter, parsed.body)
    bank_index.invalidate(Path(memory_path))
    return True


def set_every(memory_path: Path, entity_id: str, ref: str, predicate: str | None, days: int | None) -> bool:
    """The person's cadence for one source (``None`` = the default)."""
    page = Path(memory_path) / "entities" / f"{entity_id}.md"
    with page_lock.page_lock(memory_path):
        parsed = markdown_parser.parse(page)
        entry = _find_entry(parsed.frontmatter, ref, predicate)
        if entry is None:
            return False
        if days is None:
            entry.pop(EVERY_KEY, None)
        else:
            entry[EVERY_KEY] = max(MIN_EVERY_DAYS, min(MAX_EVERY_DAYS, int(days)))
        markdown_parser.write(page, parsed.frontmatter, parsed.body)
    bank_index.invalidate(Path(memory_path))
    return True


def commit_message(report: Report, today: date, trigger: str = TRIGGER) -> str:
    """``Source refresh <date>``, ``Cicada-Author: cicada``, no engine trailer (no model ran). Paths and claim-free
    manifest lines only."""
    lines = report.lines or [f"{p}: updated (source: n/a, trigger: {trigger})" for p in report.paths]
    return git_service.build_commit_message(f"Source refresh {today.isoformat()}", lines, authors=[AUTHOR])


def restore(memory_path: Path, report: Report) -> None:
    """Undo a run whose commit failed: new files are removed, changed pages come back from HEAD — so the next
    ``git add -A`` writer never sweeps them under the wrong author (the G85 smear)."""
    memory_path = Path(memory_path)
    for rel in report.created:
        (memory_path / rel).unlink(missing_ok=True)
    changed = [p for p in report.paths if p not in report.created]
    if changed and (memory_path / ".git").exists():
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", *changed)
        except git_service.GitError as exc:
            logger.warning(f"source-refresh restore failed: {type(exc).__name__}")
    bank_index.invalidate(memory_path)
