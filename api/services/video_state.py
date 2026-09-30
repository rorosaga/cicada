"""What Cicada honestly knows about each saved video (G162, spec §4.2).

Pure and engine-free: it reads the url index and the bank's frontmatter cache
(``bank_index``), never a page body, never the network. Nothing here is stored;
``GET /videos/state`` derives it per request.

**State is about the event, not the belief (R-VU1).** A video is *read* when a
``video-watch`` episode with a stated basis exists for it. Each such episode
contributes facts to a set, and the state is the union over the video's
episodes (a later record adds; nothing un-reads a video):

    ``watch_basis``            contributes
    transcript                 T
    frames                     F
    both                       T, F
    absent / unrecognised      U

    none                     S is empty
    transcript               T in S, F not (a U beside it changes nothing)
    watched                  F in S, T not (a U beside it changes nothing)
    watched_and_transcript   T and F in S
    recorded                 S == {U}: a record whose method was never stated

The basis is the agent's own word (R-VU2), so the app says "an agent recorded
that it watched", never "Cicada watched": Cicada sees no frames and reads no
captions. A record with no basis is its own state, never ``watched``.

Two documented divergences from the belief layer's rule ("a ``describes`` claim
with a ``media`` span"): a withdrawn claim does not un-watch the video, and a
record with a summary but no valid excerpt still counts (it has no ``media``
span).

**Identity is the url-index key (R-VU8).** Entity ids collide across same-titled
videos; ``media_ingestor.url_hash`` never does. Episodes are matched to a video
by the hash of their ``url``, and only the ``source: video-watch`` ones count —
a saved-media episode carries the same ``url`` and ``media_entity_id``.

**The set of videos is the Feed's set** (P10): the Python twin of the app's
``FeedKind.of(...) == .video`` (pinned by ``api/tests/fixtures/video_kind.json``)
over the same ``url_index`` entries ``GET /sources`` walks, with the same skip
rules, so the strip that says "8 not read yet" never disagrees with the tab.

No host table (P3): any saved item the Feed shows as a video can be queued,
whatever its site. Nothing here reads ``reading_hosts`` or ``agent_hosts``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from api.services import bank_index, media_ingestor, source_overview, video_urls

#: The tag folded into both provenance ETags and the video routes' ETags, so a
#: running app's in-memory caches do not 304 stale after a backend restart.
VIDEO_SHAPE = "video-1"

BASES = ("transcript", "frames", "both")
#: Which path a record took. ``video_link`` (a model reading the link) replaces
#: the spec's first draft of this value, which named a provider (P7).
ENGINES = ("captions", "video_link", "local_frames", "speech_to_text", "browser", "other")
#: Engines whose wording is a model's reading, not captions. ``other`` and an
#: absent engine read approximate too: "we were not told" is the honest reading.
APPROXIMATE_ENGINES = frozenset({"video_link", "other"})
STATES = ("none", "transcript", "watched", "watched_and_transcript", "recorded")
WATCH_SOURCE = "video-watch"

T, F, U = "T", "F", "U"


def clean_basis(raw) -> str | None:
    value = str(raw or "").strip().lower()
    return value if value in BASES else None


def clean_engine(raw) -> str | None:
    value = str(raw or "").strip().lower()
    return value if value in ENGINES else None


def basis_facts(fm: dict) -> frozenset[str]:
    """The facts one watch episode contributes (the table above)."""
    basis = clean_basis((fm or {}).get("watch_basis"))
    if basis == "transcript":
        return frozenset({T})
    if basis == "frames":
        return frozenset({F})
    if basis == "both":
        return frozenset({T, F})
    return frozenset({U})


def basis_from_facts(facts) -> str | None:
    """The stated basis a set of T/F facts spells, or ``None`` (only U/empty)."""
    has_t, has_f = T in facts, F in facts
    if has_t and has_f:
        return "both"
    if has_t:
        return "transcript"
    if has_f:
        return "frames"
    return None


def derive(facts) -> str:
    """The video's state from the union of its episodes' facts."""
    facts = frozenset(facts)
    if not facts:
        return "none"
    has_t, has_f = T in facts, F in facts
    if has_t and has_f:
        return "watched_and_transcript"
    if has_t:
        return "transcript"
    if has_f:
        return "watched"
    return "recorded"


def fidelity(engine) -> str:
    """``approximate`` for a model's reading of the link, ``other`` and an
    absent or unknown engine (so every legacy record); else ``verbatim``."""
    value = clean_engine(engine)
    return "approximate" if value is None or value in APPROXIMATE_ENGINES else "verbatim"


def is_video_page(media_type, url, kind) -> bool:
    """The Feed's rule (``FeedKind.of``): a paper is never a video; a page is a
    video when its type says so or its link resolves to a video provider."""
    if kind == "paper":
        return False
    if str(media_type or "") in ("youtube", "video"):
        return True
    return video_urls.resolve(str(url or "")) is not None


@dataclass(frozen=True)
class SavedVideo:
    key: str
    entity_id: str
    url: str
    title: str
    channel: str | None
    duration_s: int | None
    media_type: str


def saved_videos(memory_path: Path) -> dict[str, SavedVideo]:
    """Every saved video page, keyed by its url-index key, in index order.

    The same entries and skip rules as ``GET /sources``: an ``alias_of`` row is
    skipped, and so is a page that is archived, dropped or ``junk`` — a page
    with no readable frontmatter is kept (the route defaults it to active)."""
    memory_path = Path(memory_path)
    index = media_ingestor.load_url_index(memory_path)
    if not index:
        return {}
    pages = {f.stem: f.frontmatter or {} for f in bank_index.files(memory_path, "entities")}
    out: dict[str, SavedVideo] = {}
    for raw_key, entry in index.items():
        if not isinstance(entry, dict) or entry.get("alias_of"):
            continue
        url = str(entry.get("url") or "")
        entity_id = str(entry.get("media_entity_id") or "")
        fm = pages.get(entity_id) or {}
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        kind = media.get("kind") if isinstance(media.get("kind"), str) and media.get("kind") else None
        if str(fm.get("status", "active")) in source_overview.HIDDEN_STATUSES:
            continue
        if str(fm.get("enrichment_status") or "") == "junk":
            continue
        media_type = str(entry.get("media_type") or "url")
        if not is_video_page(media_type, url, kind):
            continue
        key = str(raw_key) if _is_key(raw_key) else media_ingestor.url_hash(url)
        channel = media.get("channel") if isinstance(media.get("channel"), str) and media.get("channel") else None
        duration = media.get("duration_s")
        duration_s = duration if isinstance(duration, int) and not isinstance(duration, bool) and duration > 0 else None
        out[key] = SavedVideo(key=key, entity_id=entity_id, url=url, title=str(entry.get("title") or ""),
                              channel=channel, duration_s=duration_s, media_type=media_type)
    return out


def _is_key(value) -> bool:
    text = str(value or "")
    return len(text) == 12 and all(c in "0123456789abcdef" for c in text)


@dataclass(frozen=True)
class Record:
    """One watch episode, reduced to what the state needs."""

    episode_id: str
    timestamp: str
    facts: frozenset[str]
    engine: str | None
    harness: str | None
    processed: bool
    processed_by: str | None


def watch_records(memory_path: Path) -> dict[str, list[Record]]:
    """Watch episodes grouped by the url-index key of their link, oldest first.
    One pass over ``bank_index``'s cached frontmatter; no body is read."""
    grouped: dict[str, list[Record]] = {}
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        if fm.get("source") != WATCH_SOURCE:
            continue
        url = str(fm.get("url") or "").strip()
        if not url:
            continue  # an episode with no link counts for nothing
        grouped.setdefault(media_ingestor.url_hash(url), []).append(Record(
            episode_id=f.stem, timestamp=str(fm.get("timestamp") or ""), facts=basis_facts(fm),
            engine=clean_engine(fm.get("watch_engine")),
            harness=(str(fm.get("harness") or "").strip() or None),
            processed=bool(fm.get("processed")),
            processed_by=(str(fm.get("processed_by") or "").strip() or None),
        ))
    for records in grouped.values():
        records.sort(key=lambda r: (r.timestamp, r.episode_id))
    return grouped


def state_of(records: list[Record]) -> str:
    facts: set[str] = set()
    for r in records:
        facts |= r.facts
    return derive(facts)


def newer_than(record: Record, since: str | None) -> bool:
    """Is this record's time at or after ``since``? Compared as instants, not strings: a
    record stamped `+00:00` and a request stamped `Z` are one format apart. A record with no
    readable time is never newer than a floor."""
    if not since:
        return True
    floor, stamp = _parse(since), _parse(record.timestamp)
    return floor is None or (stamp is not None and stamp >= floor)


def satisfies(records: list[Record], want: str, *, since: str | None) -> bool:
    """Does a record newer than ``since`` satisfy a queue request (§4.3, session
    ignored)? A transcript record closes a transcript request; frames or both
    close either; a record whose method was never stated satisfies nothing here
    — it closes an entry only for the leaseholder, at record time."""
    for r in records:
        if not newer_than(r, since):
            continue
        if F in r.facts or (T in r.facts and want == "transcript"):
            return True
    return False


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _item(video: SavedVideo, records: list[Record], row: dict | None) -> dict:
    """One item of ``/videos/state``. Title, channel, thumbnail, duration and site
    are not repeated: the app joins by ``mediaEntityId|url`` to the row it holds."""
    item: dict = {"key": video.key, "mediaEntityId": video.entity_id, "url": video.url,
                  "state": state_of(records)}
    if records:
        facts: set[str] = set()
        for r in records:
            facts |= r.facts
        newest = records[-1]
        basis = basis_from_facts(facts)
        if basis:
            item["basis"] = basis
        if newest.engine:
            item["engine"] = newest.engine
        item["fidelity"] = fidelity(newest.engine)
        item["episodeId"] = newest.episode_id
        stamp = _parse(newest.timestamp)
        if stamp is not None:
            item["recordedAt"] = _iso(stamp)
        if newest.harness:
            item["recordedBy"] = newest.harness
        # Read by Sleep only when Sleep says so; an agent that flipped
        # `processed` itself is unknowable, so the key is absent (R-VU9).
        if not newest.processed:
            item["readBySleep"] = False
        elif newest.processed_by == "sleep":
            item["readBySleep"] = True
    if row is not None:
        item["want"] = row["want"]
        item["queueState"] = row["state"]
        if row.get("claimed_by") and row["state"] == "claimed":
            item["claimedBy"] = row["claimed_by"]
        if row.get("attempts"):
            item["attempts"] = int(row["attempts"])
        if row.get("batch"):
            item["batch"] = row["batch"]
        failed = row.get("failed")
        if row["state"] == "failed" and isinstance(failed, dict):
            item["failedCode"] = failed.get("code") or "failed"
            if failed.get("reason"):
                item["failedReason"] = failed["reason"]
    return item


def build(memory_path: Path, rows: list[dict], batch: dict | None, *, next_change_at: str | None = None,
          saved: dict[str, SavedVideo] | None = None, records: dict[str, list[Record]] | None = None) -> dict:
    """``{items, queue, [nextChangeAt], shape}`` — the body of ``GET /videos/state``.

    ``rows`` are the queue's live rows (already settled by ``video_queue``); a
    row whose key is not a saved video is ignored here — a hidden or removed
    page drops out of every count (the orphan rule)."""
    videos = saved if saved is not None else saved_videos(memory_path)
    records = records if records is not None else watch_records(memory_path)
    by_key = {r["key"]: r for r in rows if r["key"] in videos}
    items = [_item(v, records.get(k, []), by_key.get(k)) for k, v in videos.items()]
    body = {"items": items, "queue": summary_from(items, batch), "shape": VIDEO_SHAPE}
    if next_change_at:
        body["nextChangeAt"] = next_change_at
    return body


def summary_from(items: list[dict], batch: dict | None) -> dict:
    """The one function both ``/videos/state.queue`` and ``/videos/summary`` come
    from (N-6), so they cannot disagree. ``unread`` is state ``none`` with no
    queue entry; ``read`` is everything else with none; the picker's Queued tab
    is ``queued + claimed + failed``; the three tabs sum to ``total``."""
    out = {"total": len(items), "unread": 0, "queued": 0, "claimed": 0, "failed": 0, "read": 0}
    for item in items:
        queue_state = item.get("queueState")
        if queue_state in ("queued", "claimed", "failed"):
            out[queue_state] += 1
        elif item["state"] == "none":
            out["unread"] += 1
        else:
            out["read"] += 1
    if batch:
        out["batch"] = batch
    return out
