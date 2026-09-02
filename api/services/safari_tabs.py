"""Safari iCloud tabs → saved-for-later media items (2026-09-02 brief, extends G30).

The bytes of ``~/Library/Containers/com.apple.Safari/Data/Library/Safari/
CloudTabs.db`` arrive from the companion app (R1: the app reads ``~/Library``
because it is the bundle the user grants Full Disk Access to; the launchd
backend has none and must never try). This module never opens a path under
the user's home — it only ever parses bytes it was handed. There is
deliberately no ``sync_from_local_files`` twin here: a missing-FDA failure
must surface exactly once, in the app, with the fix — not a second time as
a silent empty sync from the backend.

Parsing (R2): the bytes are written to a private temp dir and opened with
stdlib ``sqlite3`` through a read-only URI. Safari keeps the store in WAL
mode, so a bare copy of the main file can be missing whatever still sits in
``CloudTabs.db-wal``; when the caller supplies the sidecar it is written
beside the copy and SQLite replays it. Without a sidecar the copy is opened
``immutable=1`` — nothing can change under us and no ``-shm`` is needed.

Each tab becomes a ``RawItem`` with ``origin="safari-tab"`` (also in ``tags``,
same double-stamp as ``bookmark_sync._tag_origin`` — ``tags`` alone is not a
provenance signal), ``folder`` = the device's display name (so the Feed can
group "everything open on the phone"), and ``added`` from a Core Data
timestamp column when the schema has one. Non-http(s), loopback, ``.local``
and RFC-1918 URLs are dropped: a tab pointing at a dev server is not a save.

Ingest rides ``media_ingestor.ingest_batch`` in ``MAX_BATCH`` slices exactly
like ``connectors/base._run_sync_locked`` (final-review H3 there: a single
``items[:MAX_BATCH]`` call silently drops the tail). Dedup is the existing
``url_index.json`` hash check inside ``ingest_batch`` — a tab that is already
a bookmark entity is reported ``skipped``, never re-created (R3). No LLM, no
network call of its own: ``ingest_batch``'s pre-existing best-effort
enrichment is left exactly as it is.
"""

from __future__ import annotations

import ipaddress
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from loguru import logger

from api.services import media_ingestor, saved_at, sync_state
from api.services.media_ingestor import MAX_BATCH, RawItem

ORIGIN = "safari-tab"
CHANNEL_ID = "safari-tabs"
UNKNOWN_DEVICE = "Unknown device"

# Columns a CloudTabs.db has carried across macOS versions for "when was this
# tab last touched", in preference order. Probed with PRAGMA table_info at
# parse time — the schema is Apple's, not ours, so nothing here is assumed.
_TIMESTAMP_COLUMNS = ("last_viewed_time", "date_modified", "last_modified", "creation_date")

IngestFn = Callable[..., Awaitable[tuple[int, int]]]


class SafariTabsError(ValueError):
    """The bytes are not a CloudTabs.db (not SQLite, or missing its tables)."""


@dataclass
class TabsSnapshot:
    """What one CloudTabs.db contains, already filtered to importable tabs."""

    items: list[RawItem]
    devices: list[dict]  # [{"name": str, "count": int}], count desc then name
    skipped: int  # in-batch duplicates + unimportable URLs
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)


def _is_importable(url: str) -> bool:
    """http(s) to a public host only — a tab on a dev server, a LAN box or a
    bookmarklet is not something the user "saved"."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "0.0.0.0"} or host.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a DNS name, not a literal address


def _timestamp_column(conn: sqlite3.Connection) -> str | None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(cloud_tabs)")}
    return next((c for c in _TIMESTAMP_COLUMNS if c in cols), None)


def load_tabs(db: bytes, wal: bytes | None = None) -> TabsSnapshot:
    """Parse CloudTabs.db bytes (plus an optional ``-wal`` sidecar) into a snapshot.

    Raises :class:`SafariTabsError` when the bytes are not SQLite or lack the
    two Safari tables — the router maps that to a 422 so the app can say
    "that isn't a CloudTabs.db" rather than "sync failed".
    """
    tmp = Path(tempfile.mkdtemp(prefix="cicada-cloudtabs-"))
    try:
        db_path = tmp / "CloudTabs.db"
        db_path.write_bytes(db)
        if wal:
            (tmp / "CloudTabs.db-wal").write_bytes(wal)
        uri = f"file:{db_path}?mode=ro" + ("" if wal else "&immutable=1")
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as e:
            raise SafariTabsError(f"Not a SQLite database: {e}") from e
        try:
            try:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            except sqlite3.DatabaseError as e:
                raise SafariTabsError(f"Not a SQLite database: {e}") from e
            if not {"cloud_tabs", "cloud_tab_devices"} <= tables:
                raise SafariTabsError("Not a Safari CloudTabs.db (missing cloud_tabs / cloud_tab_devices)")
            ts_col = _timestamp_column(conn)
            ts_select = f", t.{ts_col}" if ts_col else ", NULL"
            rows = conn.execute(
                "SELECT d.device_name, t.title, t.url" + ts_select +
                " FROM cloud_tabs t LEFT JOIN cloud_tab_devices d ON d.device_uuid = t.device_uuid"
            ).fetchall()
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Rows arrive in SQLite's scan order and nothing downstream depends on it:
    # `position` is an opaque BLOB in Safari's schema, so there is no honest
    # ORDER BY — the device picker sorts by count, the Feed by its own dates.
    # Only `device_name`, `title`, `url` and the probed timestamp column are
    # named: the fewer Apple columns the SQL mentions, the fewer schema
    # versions can break the parse.
    seen: set[str] = set()
    items: list[RawItem] = []
    counts: dict[str, int] = {}
    skipped = 0
    for device_name, title, url, stamp in rows:
        device = (device_name or "").strip() or UNKNOWN_DEVICE
        if not isinstance(url, str) or not _is_importable(url):
            skipped += 1
            continue
        h = media_ingestor.url_hash(url)
        if h in seen:
            skipped += 1
            continue
        seen.add(h)
        items.append(RawItem(
            url=url,
            title=(title or "").strip() or None,
            tags=[ORIGIN],
            origin=ORIGIN,
            folder=device,
            added=saved_at.from_cocoa_seconds(stamp) if ts_col else None,
        ))
        counts[device] = counts.get(device, 0) + 1

    devices = [{"name": n, "count": counts[n]} for n in sorted(counts, key=lambda n: (-counts[n], n))]
    return TabsSnapshot(items=items, devices=devices, skipped=skipped)


def select(snapshot: TabsSnapshot, devices: list[str] | None) -> list[RawItem]:
    """The tabs to import: every tab, or only those on the named devices (exact name match)."""
    if not devices:
        return list(snapshot.items)
    wanted = set(devices)
    return [i for i in snapshot.items if i.folder in wanted]


async def sync_tabs(
    memory_path: Path,
    db: bytes,
    *,
    wal: bytes | None = None,
    devices: list[str] | None = None,
    ingest_fn: IngestFn | None = None,
) -> dict[str, Any]:
    """Parse, filter, ingest in ``MAX_BATCH`` slices, and stamp ``sync_state``.

    A failure inside ingest is recorded on the channel (``record_error``) so
    ``GET /sources/channels`` says "Last sync failed · …" instead of a stale
    success, and then re-raised — the app just asked for this sync and must
    see the error, unlike a connector's unattended poll.
    """
    fn: IngestFn = ingest_fn or media_ingestor.ingest_batch
    memory_path = Path(memory_path)
    snapshot = load_tabs(db, wal)
    items = select(snapshot, devices)
    selected = set(devices) if devices else {d["name"] for d in snapshot.devices}

    created = skipped = 0
    try:
        for start in range(0, len(items), MAX_BATCH):
            chunk = items[start:start + MAX_BATCH]
            c, d = await fn(chunk, memory_path, from_bookmark_file=True)
            created += c
            skipped += d
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        logger.warning(f"{CHANNEL_ID} sync failed: {message}")
        sync_state.record_error(memory_path, CHANNEL_ID, message)
        raise

    sync_state.record_sync(
        memory_path, CHANNEL_ID, count=len(items),
        extra={"devices": [d["name"] for d in snapshot.devices if d["name"] in selected]},
    )
    return {
        "new": created,
        "skipped": skipped,
        "seen": len(items),
        "devices": [{**d, "selected": d["name"] in selected} for d in snapshot.devices],
    }
