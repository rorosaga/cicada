"""One episode-id rule and one clock for every capture writer (G114).

Every Awake writer — the conversation importer, the MCP ``cicada_save_episode``
tool, the media/URL ingestor, the Telegram webhook, the calendar and notes
syncs — mints an ``ep_<YYYY-MM-DD>_<NNN>`` id and stamps a ``timestamp``. Until
this module each carried its own copy of both rules, and the copies disagreed:

- **Id.** Four writers did max-suffix+1 (collision-free); the importer counted
  files per date and added one, which collides — and silently OVERWRITES — the
  moment a same-day episode has been deleted or the sequence has a gap (a
  ``_003`` beside no ``_001``/``_002`` gets clobbered on the second write).
  Ruling R1: the id is ``1 + max(existing suffixes for that date)``, always.
- **Timestamp.** Three writers stamped ``datetime.now().isoformat() + "Z"`` —
  naive LOCAL time falsely labelled UTC, off by the machine's offset — while
  the two newest emitted a real aware-UTC ``+00:00`` stamp. Ruling R2: every
  stamp is what ``datetime.now(timezone.utc).isoformat()`` yields. Existing
  files are NOT migrated; readers already accept both shapes, and
  :func:`timestamp_sort_key` lets a queue order legacy naive-local stamps
  correctly against new UTC ones.

Pure filesystem + ``datetime``; no bank state, no LLM, importable from the MCP
server (which only has ``api.services`` on its path) as freely as from a router.

Audit 2026-10-02 (K01, A01) adds the cross-process half: :func:`create_episode`
never replaces a file, so two processes that mint the same id both land, and
:func:`episode_lock` is the one per-bank critical section for a dedup check or a
read-modify-write of an existing episode, Sleep's retirement included.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from api.services import markdown_parser

# Anchored so the stem `ep_2026-09-01_001` matches and `ep_2026-09-01_x`,
# `sleep_2026-09-01_001` or a stem with its `.md` still attached do not. The
# suffix is `\d+`, not `\d{3}`: zero-padding is a formatting choice on write,
# and a bank that has minted its thousandth same-day episode (`_1000`) must
# keep counting rather than restart at `_001` and overwrite.
EPISODE_ID_RE: re.Pattern[str] = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_(\d+)$")


def parse_episode_id(stem: str) -> tuple[str, int] | None:
    """``"ep_2026-09-01_005"`` → ``("2026-09-01", 5)``; anything else → ``None``."""
    m = EPISODE_ID_RE.match(stem)
    if m is None:
        return None
    return m.group(1), int(m.group(2))


def max_suffix_by_date(episodes_dir: Path) -> dict[str, int]:
    """Highest existing suffix per date, from ONE ``glob("ep_*.md")``.

    Tolerant of junk: a file whose stem doesn't parse (``ep_2026-09-01_x.md``,
    a stray ``README.md``) is skipped, never raised on — a hand-edited bank
    must not stop every writer from minting ids. A missing directory is an
    empty bank, not an error, so a writer can seed before its first
    ``mkdir``. This is what the importer seeds its per-batch counter from
    (R1) instead of counting files.
    """
    result: dict[str, int] = {}
    if not episodes_dir.is_dir():
        return result
    for filepath in episodes_dir.glob("ep_*.md"):
        parsed = parse_episode_id(filepath.stem)
        if parsed is None:
            continue
        ep_date, num = parsed
        if num > result.get(ep_date, 0):
            result[ep_date] = num
    return result


def next_episode_id(episodes_dir: Path, ep_date: str) -> str:
    """Next ``ep_<ep_date>_NNN`` = 1 + max existing suffix for that date (R1).

    Max-based, never count-based: a count collides after any deletion or gap
    and — because every writer calls ``markdown_parser.write`` unconditionally
    — a collision is a silent overwrite of a real episode. Zero-padded to
    three digits for the common case; a fourth digit simply appears when a
    day runs past 999, and :data:`EPISODE_ID_RE` reads it back fine.
    """
    max_num = 0
    if episodes_dir.is_dir():
        for filepath in episodes_dir.glob(f"ep_{ep_date}_*.md"):
            parsed = parse_episode_id(filepath.stem)
            if parsed is not None and parsed[0] == ep_date:
                max_num = max(max_num, parsed[1])
    return f"ep_{ep_date}_{max_num + 1:03d}"


#: How many times :func:`create_episode` re-mints after losing a race before it
#: gives up — each loss means another writer created a file, so this is never
#: reached in practice.
CREATE_ATTEMPTS = 64


def create_episode(episodes_dir: Path, frontmatter: dict, body: str) -> str:
    """Write a NEW episode under ``frontmatter["id"]``, never replacing a file (K01).

    ``next_episode_id`` scans, then the writer writes: two processes (an MCP
    stdio server and the backend, or two MCP servers) that scan together mint
    the same id, and ``markdown_parser.write`` used to replace the first
    episode with the second. Here the create fails instead, the id is minted
    again — the other writer's file now moves the max — and ``frontmatter["id"]``
    is updated in place. Returns the id actually written.

    G181 phase 3: when a per-device token signed the request this runs in (``device_context``), the episode records
    ``device: <id>`` unless its writer already set one.

    Ruling 39 (owner 2026-10-24, "both dates recorded for everything"): every new episode records ``received_at``,
    when Cicada received it (:func:`stamp_received`), beside ``timestamp``, the item's own date."""
    episode_id = str(frontmatter["id"])
    parsed = parse_episode_id(episode_id)
    # G181 phase 3: a new episode written while serving a device's request says which device it came from.
    from api.services import device_context

    device_context.stamp(frontmatter)
    stamp_received(frontmatter)
    if parsed is None:
        raise ValueError(f"not an episode id: {episode_id!r}")
    for _ in range(CREATE_ATTEMPTS):
        try:
            markdown_parser.write_new(episodes_dir / f"{episode_id}.md", frontmatter, body)
            return episode_id
        except FileExistsError:
            episode_id = next_episode_id(episodes_dir, parsed[0])
            frontmatter["id"] = episode_id
    raise FileExistsError(f"no free episode id for {parsed[0]} after {CREATE_ATTEMPTS} attempts")


#: Ruling 39 (owner 2026-10-24): the frontmatter key of when Cicada received an episode — aware UTC, written once
#: when the episode file is created (:func:`create_episode`) and never changed after: an edit in place, a re-date
#: (``redated_from``), a relay upgrade or a tombstone keeps it. ``timestamp`` stays the item's own date (published,
#: created, sent, saved, happened) where its source gives one; for a live capture the two are the same moment. An
#: episode written before the ruling has none, and a missing one reads as unknown — never guessed from the id, the
#: file's mtime or ``redated_from``.
RECEIVED_KEY = "received_at"


def stamp_received(frontmatter: dict, *, now: str | None = None) -> dict:
    """Set ``received_at`` on a NEW episode's frontmatter (a writer's own value wins), placed right after
    ``timestamp`` (else right after ``id``) so an episode's two dates read together. Every other key keeps its order,
    so the per-turn sidecar stays the last key (R-PB4). Mutates and returns ``frontmatter`` (:func:`create_episode`
    updates the caller's dict in place)."""
    if frontmatter.get(RECEIVED_KEY):
        return frontmatter
    value = now or utc_now_iso()
    items = [(k, v) for k, v in frontmatter.items() if k != RECEIVED_KEY]
    anchor = "timestamp" if any(k == "timestamp" for k, _ in items) else "id"
    frontmatter.clear()
    for key, val in items:
        frontmatter[key] = val
        if key == anchor:
            frontmatter[RECEIVED_KEY] = value
    frontmatter.setdefault(RECEIVED_KEY, value)
    return frontmatter


# --- The one critical section (audit K01 / A01) ----------------------------------

_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_HELD: dict[str, tuple[int, int]] = {}  # key -> (depth, fd), touched only by the RLock's owner


@contextmanager
def episode_lock(episodes_dir: Path) -> Iterator[None]:
    """Exclusive, cross-process, re-entrant lock on one bank's episodes.

    An ``flock`` on the episodes directory's own descriptor: every process
    that opens the directory contends for it, and nothing is created inside
    the bank for git to see. A per-directory ``RLock`` in front makes it
    re-entrant within a thread and orders threads of one process. Hold it for
    one short operation only — a dedup check plus its create, or one
    read-modify-write of an existing episode — never for a whole import or a
    Sleep stage. ``flock`` waits without a timeout, and the Stop hook's request
    has a 3 s budget, so every holder must stay short. Lock order is always a
    writer's own process lock first, this one second."""
    with dir_lock(episodes_dir):
        yield


@contextmanager
def dir_lock(directory: Path) -> Iterator[None]:
    """The mechanism behind :func:`episode_lock` and ``page_lock.page_lock``:
    an exclusive, cross-process, re-entrant ``flock`` on a directory's own
    descriptor, with a per-directory ``RLock`` in front. Each directory is its
    own lock (keyed by its resolved path)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    key = os.path.realpath(directory)
    with _THREAD_LOCKS_GUARD:
        rlock = _THREAD_LOCKS.setdefault(key, threading.RLock())
    with rlock:
        depth, fd = _HELD.get(key, (0, -1))
        if depth == 0:
            fd = os.open(key, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except BaseException:
                os.close(fd)
                raise
        _HELD[key] = (depth + 1, fd)
        try:
            yield
        finally:
            depth, fd = _HELD[key]
            if depth == 1:
                del _HELD[key]
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
            else:
                _HELD[key] = (depth - 1, fd)


def dir_lock_held(directory: Path) -> bool:
    """Does THIS process hold :func:`dir_lock` on ``directory``? (a test seam)"""
    return _HELD.get(os.path.realpath(directory), (0, -1))[0] > 0


def body_revision(body: str) -> str:
    """The revision of an episode's text, for retiring only what Sleep read (A01).

    Content-derived, so a legacy episode with no ``content_hash`` needs no
    migration, and frontmatter-only edits (a title, a turn stamp) never count
    as new content."""
    return hashlib.sha256(body.encode("utf-8", errors="surrogatepass")).hexdigest()


# --- The one clock (R2) --------------------------------------------------------


def utc_now_iso() -> str:
    """Now, as aware-UTC ISO-8601 with an explicit ``+00:00`` (R2).

    The one shape every new episode ``timestamp`` takes. ``+00:00`` rather than
    ``Z`` because that is what ``datetime.isoformat()`` emits natively — no
    string surgery on either side, and Python 3.11's ``fromisoformat`` reads
    both, so a reader never has to know which writer produced the file.
    """
    return datetime.now(timezone.utc).isoformat()


#: The widest UTC offset a zone has (UTC+14 / UTC-12, with room), in minutes: a posted offset outside it is ignored.
MAX_UTC_OFFSET_MINUTES = 14 * 60


def id_day(stamp: str | datetime | None = None, *, utc_offset_minutes: int | None = None) -> str:
    """The day an episode id carries (ruling 34, 2026-10-22): the conversation's first moment as a calendar day in
    the person's zone — this machine's, or the UTC offset a client posted with the turns (G181: a server elsewhere
    mints the id, and its own zone is not the person's) — never the UTC day.

    ``stamp`` is the conversation's first moment, ISO-8601 (``Z`` or an offset; a naive one is this machine's local
    time, as every legacy writer meant it) or a ``datetime``; absent or unreadable, now. An id once minted is never
    renamed: this decides only new ids."""
    moment: datetime | None = stamp if isinstance(stamp, datetime) else None
    if moment is None and stamp:
        try:
            moment = datetime.fromisoformat(str(stamp).strip().replace("Z", "+00:00"))
        except ValueError:
            moment = None
    if moment is None:
        moment = datetime.now(timezone.utc)
    try:
        if isinstance(utc_offset_minutes, int) and not isinstance(utc_offset_minutes, bool) \
                and abs(utc_offset_minutes) <= MAX_UTC_OFFSET_MINUTES:
            return moment.astimezone(timezone(timedelta(minutes=utc_offset_minutes))).date().isoformat()
        return moment.astimezone().date().isoformat()
    except (ValueError, OverflowError, OSError):
        return moment.date().isoformat()


def local_day(raw) -> date | None:
    """The day a stored stamp was said, as the person counts days (ruling 34, 2026-10-22) — the one reading rule
    beside :func:`id_day`'s minting rule. Any stored shape: a naive legacy stamp (this machine's local time, as its
    writer meant it), ``Z``, ``+00:00``, a YAML ``datetime``, or a bare ``YYYY-MM-DD`` (already a day, kept as it is),
    in this machine's zone. Never the first ten characters of a UTC stamp: words said at 00:27 in Madrid are stored
    on the previous UTC day. ``None`` when unreadable — nothing is guessed."""
    if isinstance(raw, datetime):
        moment = raw
    elif isinstance(raw, date):
        return raw
    else:
        text = str(raw or "").strip()
        if len(text) == 10:
            try:
                return date.fromisoformat(text)
            except ValueError:
                return None
        key = timestamp_sort_key(text or None)
        if not key:
            return None
        try:
            moment = datetime.fromisoformat(key)
        except ValueError:
            return None
    try:
        return moment.astimezone().date()
    except (ValueError, OverflowError, OSError):
        return None


def zone_offset_minutes(zone_name, at: datetime | None = None) -> int | None:
    """A client's IANA zone name (``Europe/Madrid``) as its UTC offset in minutes at ``at`` (now by default), east
    positive — what :func:`id_day` takes. ``None`` for anything that is not a known zone, or an offset outside
    :data:`MAX_UTC_OFFSET_MINUTES`: a hint, never a reason to fail a capture."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    name = zone_name.strip() if isinstance(zone_name, str) else ""
    if not name or len(name) > 64:
        return None
    try:
        offset = (at or datetime.now(timezone.utc)).astimezone(ZoneInfo(name)).utcoffset()
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    if offset is None:
        return None
    minutes = int(offset.total_seconds() // 60)
    return minutes if abs(minutes) <= MAX_UTC_OFFSET_MINUTES else None


def utc_now_seconds() -> str:
    """Now as `YYYY-MM-DDTHH:MM:SSZ` — the shape of a claim's `recorded_ts`
    (round 4 C2). Seconds on purpose: it is compared with a turn's time floored
    to the second (`turn_authorship`), and a sub-second stamp would claim a
    precision the join does not use."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc_iso(value: datetime | int | float) -> str:
    """Normalise an epoch or a ``datetime`` to the R2 shape.

    - epoch seconds (``int``/``float``) → ``fromtimestamp(value, timezone.utc)``.
      Never ``fromtimestamp(value)`` alone — that lands in local time, which is
      exactly the bug the ``+ "Z"`` idiom used to bake into imports.
    - a naive ``datetime`` is ASSUMED UTC (the only honest choice for a value
      that arrived without a zone from an export or an API).
    - an aware ``datetime`` is converted with ``astimezone``.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            dt = value.replace(tzinfo=timezone.utc)
        else:
            dt = value.astimezone(timezone.utc)
    else:
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
    return dt.isoformat()


def timestamp_sort_key(raw: str | None) -> str:
    """A normalised UTC ISO key for ORDERING episode timestamps of any shape.

    Banks hold three shapes side by side and always will (R2 forbids a
    migration): legacy naive local (``2026-09-01T10:00:00``), ``Z``-suffixed
    (``…T08:00:00Z``), and the new ``+00:00``. Lexical order across those is
    wrong by the machine's UTC offset, so the Sleep queue sorts on this key
    instead. A NAIVE input is read as LOCAL time — the same reading
    ``sleep_debt._parse_episode_timestamp`` gives it, because that is what
    the writers that produced it meant — and converted to UTC. Anything
    unparseable (``None``, garbage, a non-string) sorts first as ``""`` rather
    than raising: one bad file must not hide the whole queue. That promise
    covers the CONVERSION too, not just the parse — a naive stamp at either
    end of the calendar (``0001-01-01T00:00:00``, ``9999-12-31T23:59:59``)
    parses fine but ``astimezone()`` then walks it out of range and raises
    ``ValueError``/``OverflowError`` (and the platform ``localtime`` behind it
    can raise ``OSError``), which aborted the Sleep cycle and 500'd
    ``GET /sleep/episodes`` for one absurd file.
    """
    if not raw or not isinstance(raw, str):
        return ""
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()  # naive → local-aware, matching sleep_debt's reading
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return ""
