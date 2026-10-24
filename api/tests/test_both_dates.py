"""Ruling 39 (owner 2026-10-24): "have both dates recorded for everything when available."

Every new episode keeps ``timestamp`` as the item's own date (published, created, sent, saved, happened) where its
source gives one, and records ``received_at`` — when Cicada received it — through the one door every new episode goes
through (``episode_ids.create_episode``; the stager writes it in ``write_new``). A feed item is dated by when it was
published and is no time signal (``episode_time.is_feed_item``): its back catalogue is no burst of activity, and an
old article neither starts a page's clock years ago nor charges anything. Existing episodes are never renamed and a
missing ``received_at`` reads as unknown. Synthetic values only.
"""
from __future__ import annotations

import ast
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.config import Settings
from api.services import (bank_index, calendar_registry, channel_items, decay_policy, episode_ids, episode_staging,
                          episode_time, markdown_parser, media_ingestor, provenance, source_dates)
from api.services.media_ingestor import MediaMeta

API = Path(__file__).resolve().parents[1]


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "synthetic-bank"
    for sub in ("episodes", "entities", "sources", "inbox"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    return memory


def _fm(path: Path) -> dict:
    return markdown_parser.parse(path).frontmatter


def _received(fm: dict) -> datetime:
    value = datetime.fromisoformat(str(fm[episode_ids.RECEIVED_KEY]))
    assert value.tzinfo is not None, "received_at is aware UTC"
    return value


# --------------------------------------------------------------------------- the one door


def test_create_episode_records_received_at_beside_timestamp_and_keeps_turns_last(tmp_path):
    episodes = _bank(tmp_path) / "episodes"
    fm = {"id": "ep_2024-03-02_001", "timestamp": "2024-03-02T09:00:00+00:00", "source": "note",
          "turns": [{"offset": 0, "ts": "2024-03-02T09:00:00+00:00", "speaker": "user"}]}
    before = datetime.now(timezone.utc)
    eid = episode_ids.create_episode(episodes, fm, "user: a synthetic note")
    stored = _fm(episodes / f"{eid}.md")
    keys = list(stored)
    assert keys.index(episode_ids.RECEIVED_KEY) == keys.index("timestamp") + 1
    assert keys[-1] == "turns"
    assert _received(stored) >= before
    assert str(stored["timestamp"]) == "2024-03-02T09:00:00+00:00"      # the item's own date is untouched


def test_a_writer_s_own_received_at_wins(tmp_path):
    episodes = _bank(tmp_path) / "episodes"
    fm = {"id": "ep_2024-03-02_001", "timestamp": "2024-03-02T09:00:00+00:00",
          "received_at": "2024-03-02T09:05:00+00:00"}
    eid = episode_ids.create_episode(episodes, fm, "user: hello")
    assert str(_fm(episodes / f"{eid}.md")["received_at"]) == "2024-03-02T09:05:00+00:00"


# --------------------------------------------------------------------------- every writer is covered


_MINTS = ("next_episode_id", "max_suffix_by_date")
_DOORS = ("create_episode", "stamp_received", "stage", "write_new")


def _calls(node: ast.AST) -> set[str]:
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def _writes_markdown(node: ast.AST) -> bool:
    return any(isinstance(s, ast.Call) and isinstance(s.func, ast.Attribute) and s.func.attr in ("write", "write_new")
               and isinstance(s.func.value, ast.Name) and s.func.value.id == "markdown_parser" for s in ast.walk(node))


def test_every_writer_that_mints_an_episode_records_received_at():
    """Fails when a writer creates an episode without ``received_at``: a module that mints an episode id must create
    the file through ``create_episode`` (which stamps it) or the stager, and a function that mints an id and writes the
    file itself (the demo generators) must call ``stamp_received`` before it does (or create through
    ``create_episode`` and write only to update, as the Stop hook's writer does)."""
    minting, bare = [], []
    # All of `api/` (scripts, the CLI, connectors, services, routers) and the MCP server; never the tests or a venv.
    sources = [p for root in (API, API.parent / "mcp") for p in sorted(root.rglob("*.py"))
               if not {".venv", "tests", "__pycache__"} & set(p.relative_to(root).parts)]
    for path in sources:
        if path == API / "services" / "episode_ids.py":
            continue
        name = path.relative_to(API.parent).as_posix()
        tree = ast.parse(path.read_text())
        calls = _calls(tree)
        if not calls & set(_MINTS):
            continue
        minting.append(name)
        if not calls & set(_DOORS):
            bare.append(name)
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls(fn) & set(_MINTS) \
                    and _writes_markdown(fn) and not _calls(fn) & {"stamp_received", "create_episode"}:
                bare.append(f"{name}:{fn.name}")
    # The scan sees the writers.
    assert "api/services/episode_staging.py" in minting and "api/services/media_ingestor.py" in minting
    assert bare == []


def test_every_episode_the_demo_writes_has_both_dates(tmp_path):
    """The demo runs the real writers (the stager, the watch record, the media save) beside its own direct ones: every
    episode it leaves has an item date and a receipt, and the receipt is pinned to the demo's clock (deterministic)."""
    from _demo_scenario import build

    bank = build(tmp_path, index=False, showcase=True)
    episodes = sorted((bank / "episodes").glob("*.md"))
    assert episodes
    missing = [p.name for p in episodes if not (_fm(p).get("timestamp") and _fm(p).get(episode_ids.RECEIVED_KEY))]
    assert missing == []


def test_the_stager_writes_both_dates_and_never_changes_the_receipt(tmp_path):
    episodes = _bank(tmp_path) / "episodes"
    draft = episode_staging.EpisodeDraft(title="Synthetic", source_id="synthetic:1", source="note",
                                         timestamp="2023-05-01T08:00:00+00:00", original_date="2023-05-01",
                                         body="A synthetic note body.")
    result = episode_staging.stage([draft], episodes)
    (eid,) = result.touched.values()
    path = episodes / f"{eid}.md"
    first = _fm(path)
    assert eid.startswith("ep_2023-05-01_") and str(first["timestamp"]) == "2023-05-01T08:00:00+00:00"
    receipt = first["received_at"]
    assert _received(first).date() >= date.today() - timedelta(days=1)

    # An edit in place, a re-date and a tombstone keep the same file, id and receipt.
    bank_index.invalidate()
    edited = episode_staging.EpisodeDraft(title="Synthetic", source_id="synthetic:1", source="note",
                                          timestamp="2023-05-02T08:00:00+00:00", body="An edited body.", redate=True)
    episode_staging.stage([edited], episodes)
    bank_index.invalidate()
    episode_staging.stage([], episodes, deleted_source_ids=["synthetic:1"])
    after = _fm(path)
    assert sorted(p.name for p in episodes.glob("*.md")) == [path.name]
    assert after["received_at"] == receipt
    assert str(after["redated_from"]).startswith("2023-05-01") and after.get("source_deleted_at")


def test_an_existing_episode_is_never_renamed_or_given_a_guessed_receipt(tmp_path):
    episodes = _bank(tmp_path) / "episodes"
    legacy = {"id": "ep_2025-01-10_001", "timestamp": "2025-01-10T10:00:00+00:00", "source": "note",
              "title": "Old", "processed": True, "content_hash": episode_staging.content_hash("Old body."),
              "source_id": "synthetic:legacy", "source_updated_at": None}
    markdown_parser.write(episodes / "ep_2025-01-10_001.md", legacy, "Old body.")
    bank_index.invalidate()
    draft = episode_staging.EpisodeDraft(title="Old", source_id="synthetic:legacy", source="note",
                                         timestamp="2025-01-10T10:00:00+00:00", body="Old body, edited.")
    result = episode_staging.stage([draft], episodes)
    assert result.touched == {"synthetic:legacy": "ep_2025-01-10_001"}
    assert [p.name for p in episodes.glob("*.md")] == ["ep_2025-01-10_001.md"]
    fm = _fm(episodes / "ep_2025-01-10_001.md")
    assert episode_ids.RECEIVED_KEY not in fm                          # unknown, never guessed
    assert episode_time.received_shown(fm) is None


def test_a_calendar_subscription_event_has_both_dates(tmp_path):
    memory = _bank(tmp_path)
    start = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0)
    ics = ("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:synthetic-1@example.com\n"
           f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}\nSUMMARY:Synthetic standup\nEND:VEVENT\nEND:VCALENDAR\n")
    created, _ = calendar_registry.ingest_ics(ics, memory, "https://example.com/cal.ics", commit=False)
    assert created == 1
    (path,) = (memory / "episodes").glob("*.md")
    fm = _fm(path)
    assert datetime.fromisoformat(str(fm["timestamp"])) == start          # the event's own start, as before
    assert _received(fm) > start


# --------------------------------------------------------------------------- feeds


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Synthetic Feed</title><link>https://feed.example.com</link>
  <item><title>Old article</title><link>https://feed.example.com/old</link>
    <pubDate>Mon, 01 May 2023 08:30:00 +0200</pubDate><description>Published long ago.</description></item>
  <item><title>Undated article</title><link>https://feed.example.com/undated</link></item>
</channel></rss>
"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Synthetic Atom</title>
  <entry><title>Atom entry</title><link href="https://atom.example.com/a"/>
    <published>2022-11-05T12:00:00Z</published><updated>2023-01-01T00:00:00Z</updated></entry>
  <entry><title>Updated only</title><link href="https://atom.example.com/b"/><updated>2021-02-03T04:05:06Z</updated></entry>
</feed>
"""


def test_parse_rss_reads_each_entry_s_own_published_date():
    old, undated = media_ingestor.parse_rss(FEED)
    assert old.published_at == "2023-05-01T06:30:00+00:00" and undated.published_at is None
    assert old.note is None and old.preview == "Published long ago."   # the publisher's words, never the person's
    a, b = media_ingestor.parse_rss(ATOM)
    assert a.published_at == "2022-11-05T12:00:00+00:00" and b.published_at == "2021-02-03T04:05:06+00:00"
    future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    assert media_ingestor._feed_published(future) is None and media_ingestor._feed_published("soon") is None


def _offline(monkeypatch):
    async def fake_enrich(url, client, from_bookmark_file=False):
        return MediaMeta(title=media_ingestor._fallback_title(url), description="",
                         site=media_ingestor._site_of(url), media_type=media_ingestor._classify(url, False))
    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)


def test_a_feed_item_is_dated_when_published_and_records_when_it_came_in(tmp_path, monkeypatch):
    _offline(monkeypatch)
    memory = _bank(tmp_path)
    before = datetime.now(timezone.utc)
    created, _ = asyncio.run(media_ingestor.ingest_feed(FEED, memory, commit=False))
    assert created == 2
    by_title = {_fm(p)["title"]: (p, _fm(p)) for p in (memory / "episodes").glob("*.md")}
    path, old = by_title["Old article"]
    assert path.name.startswith("ep_2023-05-01_")                        # its own day (ruling 34: the local day)
    assert str(old["timestamp"]) == "2023-05-01T06:30:00+00:00" == str(old["published_at"])
    assert _received(old) >= before and old["origin"] == "rss"
    body = markdown_parser.parse(path).body
    assert "## User note" not in body                                    # the feed's text is not the person's
    assert f"**Saved:** {datetime.now().strftime('%Y-%m-%d')}" in body  # it came in today, never "saved" in 2023
    _, undated = by_title["Undated article"]
    assert "published_at" not in undated                                 # no date given: received is all there is
    assert _received(undated) >= before
    index = json.loads((memory / "sources" / "url_index.json").read_text())
    assert sorted(e.get("published_at") or "" for e in index.values()) == ["", "2023-05-01T06:30:00+00:00"]

    # A re-poll writes nothing new and renames nothing.
    names = sorted(p.name for p in (memory / "episodes").glob("*.md"))
    created, duplicates = asyncio.run(media_ingestor.ingest_feed(FEED, memory, commit=False))
    assert (created, duplicates) == (0, 2)
    assert sorted(p.name for p in (memory / "episodes").glob("*.md")) == names


def test_a_feed_item_is_no_time_signal_whichever_date_it_carries(tmp_path):
    memory = _bank(tmp_path)
    eps = memory / "episodes"
    rows = {
        "ep_2023-05-01_001": {"source": "article", "origin": "rss", "published_at": "2023-05-01T06:30:00+00:00"},
        "ep_2026-10-20_001": {"source": "url", "origin": "rss"},                 # a poll-dated item from before
        "ep_2026-10-20_002": {"source": "url", "published_at": "2024-01-01T00:00:00+00:00"},   # an uploaded feed file
        "ep_2026-10-20_003": {"source": "url", "origin": "chrome-bookmark"},     # a save stays a signal
        "ep_2026-10-20_004": {"source": "claude-code", "origin": "claude-code"},
    }
    for eid, extra in rows.items():
        markdown_parser.write(eps / f"{eid}.md", {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00", **extra},
                              "body")
    bank_index.invalidate()
    feeds = {"ep_2023-05-01_001", "ep_2026-10-20_001", "ep_2026-10-20_002"}
    assert episode_time.untimed_ids(memory) == frozenset(feeds)
    episode_time._MEMO.clear()
    assert episode_time.untimed_among(memory, list(rows)) == frozenset(feeds)
    with patch.object(episode_time, "_sources", lambda _paths: None):   # awk unavailable: the line reader agrees
        episode_time._MEMO.clear()
        assert episode_time.untimed_among(memory, list(rows)) == frozenset(feeds)
    # What decay reads: no mention week, no last-said day and no conversation from a feed item.
    refs = list(rows)
    assert decay_policy.latest_said(refs, untimed=feeds) == "2026-10-20"
    assert decay_policy.conversations(refs, untimed=feeds) == 2
    assert decay_policy.mention_weeks(["ep_2023-05-01_001"], untimed=feeds) == 0
    assert decay_policy.latest_said(["ep_2023-05-01_001"], untimed=feeds) is None


# --------------------------------------------------------------------------- Sleep: a back catalogue charges nothing


from api.services import conflict_resolver as cr, entity_extractor as ex, entity_resolver as er, providers  # noqa: E402

TODAY = date(2026, 10, 24)
CYCLE_NOW = datetime(2026, 10, 24, 3, 0)
FEED_EP = "ep_2019-05-01_001"
OLD_FEED = {"id": FEED_EP, "timestamp": "2019-05-01T08:00:00+00:00", "origin": "rss", "source": "article",
            "published_at": "2019-05-01T08:00:00+00:00",
            "content": "# Gamma Engine\n\nGamma Engine is a synthetic rocket engine.\n"}


class _CycleDay(date):
    @classmethod
    def today(cls):
        return cls(CYCLE_NOW.year, CYCLE_NOW.month, CYCLE_NOW.day)


def _extract(episodes):
    seen: list[str] = []

    async def fake(**kw):
        seen.append(kw["messages"][1]["content"])
        reply = {"entities": [{"name": "Gamma Engine", "type": "concept", "confidence": 0.7,
                               "summary": "Gamma Engine is a rocket engine.",
                               "key_facts": ["Gamma Engine is a rocket engine."]}], "relationships": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))])

    async def no_sleep(*_a, **_k):
        return None

    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake), patch.object(ex.asyncio, "sleep", no_sleep):
        out = asyncio.run(ex.extract([dict(e) for e in episodes], Settings(_env_file=None), today=TODAY))
    return out, seen


def test_stage_one_reads_a_feed_item_as_published_and_not_a_mention():
    out, seen = _extract([OLD_FEED])
    (entity,) = [r for r in out if r][0]["entities"]
    assert entity["untimed"] is True and entity["source_episode"] == FEED_EP
    assert entity["source_episode_timestamp"] is None
    (msg,) = seen
    assert msg.startswith(source_dates.DATE_NOTE_PREFIX)
    assert "published 2019-05-01" in msg and "not the person's words" in msg and "as of May 2019" in msg
    assert "assistant's summary" not in msg


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)

    async def no_model(*a, **k):
        raise AssertionError("no model call expected")
    monkeypatch.setattr(er, "_llm_judge_same_entity", no_model)
    return root


def _settings(bank):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=1)


def _existing(bank):
    out = []
    for f in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(f)
        out.append({"id": f.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    return out


def _cycle(bank, episodes, *, decay):
    real = Settings(_env_file=None, llm_mode="byok", litellm_model="synthetic-model")
    resolved = []
    if episodes:
        out, _ = _extract(episodes)
        resolved = asyncio.run(er.resolve([r for r in out if r], _existing(bank), _settings(bank)))["changes"]

    async def no_synthesis(**_k):
        return None
    with patch.object(cr, "_synthesize_entity_update", no_synthesis), patch.object(cr, "date", _CycleDay):
        changes = asyncio.run(cr.resolve_and_prune(resolved, _existing(bank), real, decay=decay, now=CYCLE_NOW))
        cr.apply_changes(changes, bank)
    bank_index.invalidate()
    return resolved


def test_a_page_from_an_old_feed_item_starts_its_clock_the_day_it_came_in_and_is_charged_nothing(bank):
    markdown_parser.write(bank / "episodes" / f"{FEED_EP}.md",
                          {k: v for k, v in OLD_FEED.items() if k != "content"}, OLD_FEED["content"])
    bank_index.invalidate()
    (change,) = _cycle(bank, [OLD_FEED], decay=False)
    assert change["untimed"] is True
    fm = _fm(bank / "entities" / "gamma-engine.md")
    assert "last_referenced" not in fm                                   # never a mention, years ago or today
    assert str(fm["decayed_through"]) == "2026-10-24"                    # the clock starts the day it came in
    confidence, status = fm["confidence"], fm["status"]
    _cycle(bank, [], decay=True)                                         # that night's decay pass
    after = _fm(bank / "entities" / "gamma-engine.md")
    assert after["confidence"] == confidence and after["status"] == status == "active"


def test_an_old_feed_item_never_revives_a_fading_page(bank):
    _entity_fm = {"name": "Gamma Engine", "type": "concept", "status": "decaying", "confidence": 0.3,
                  "created": "2025-01-01", "last_referenced": "2025-01-01", "decayed_through": "2026-10-01",
                  "source_episodes": ["ep_2025-01-01_001"]}
    markdown_parser.write(bank / "entities" / "gamma-engine.md", _entity_fm, "## Summary\nA synthetic page.\n")
    markdown_parser.write(bank / "episodes" / f"{FEED_EP}.md",
                          {k: v for k, v in OLD_FEED.items() if k != "content"}, OLD_FEED["content"])
    bank_index.invalidate()
    (change,) = _cycle(bank, [OLD_FEED], decay=False)
    assert change["action"] == "update" and change["untimed"] is True
    fm = _fm(bank / "entities" / "gamma-engine.md")
    assert str(fm["last_referenced"]) == "2025-01-01" and str(fm["decayed_through"]) == "2026-10-01"
    assert fm["status"] == "decaying" and fm["confidence"] == 0.3
    assert FEED_EP in fm["source_episodes"]                              # the fact's source is kept


# --------------------------------------------------------------------------- surfaces: the second date only when it differs


def test_the_received_date_is_shown_only_when_it_is_days_after_the_item_s_own():
    now = datetime.now(timezone.utc)
    late = {"id": "ep_2023-05-01_001", "timestamp": "2023-05-01T08:00:00+00:00", "received_at": now.isoformat()}
    assert episode_time.received_shown(late) == now.isoformat()
    same = {"id": "ep_x", "timestamp": now.isoformat(), "received_at": (now + timedelta(hours=20)).isoformat()}
    assert episode_time.received_shown(same) is None
    assert episode_time.received_shown({"timestamp": "2023-05-01T08:00:00+00:00"}) is None   # unknown
    assert episode_time.received_shown({"id": "ep_2023-05-01_001", "received_at": now.isoformat()}) == now.isoformat()
    assert episode_time.received_after("2023-05-01", "not a date") is None


def test_the_reader_and_what_came_in_carry_the_received_day(tmp_path):
    memory = _bank(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old = {"id": "ep_2023-05-01_001", "timestamp": "2023-05-01T08:00:00+00:00", "received_at": now.isoformat(),
           "source": "calendar", "origin": "calendar", "title": "Old event", "event_start": "2023-05-01T08:00:00+00:00"}
    live = {"id": "ep_2026-10-24_001", "timestamp": now.isoformat(), "received_at": now.isoformat(),
            "source": "calendar", "origin": "calendar", "title": "Today", "event_start": now.isoformat()}
    for fm in (old, live):
        markdown_parser.write(memory / "episodes" / f"{fm['id']}.md", fm, "# event")
    bank_index.invalidate()
    assert provenance.episode_document(memory, "ep_2023-05-01_001").received_at == now.isoformat()
    assert provenance.episode_document(memory, "ep_2026-10-24_001").received_at is None
    rows = {r["id"]: r for r in channel_items.items(memory, "calendar")["items"]}
    assert rows["ep_2023-05-01_001"]["day"] == "2023-05-01"
    assert rows["ep_2023-05-01_001"]["received"] == now.date().isoformat()
    assert "received" not in rows["ep_2026-10-24_001"]


def test_recall_says_when_an_old_item_came_in(tmp_path):
    from api.services import mcp_tools

    memory = _bank(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    markdown_parser.write(memory / "episodes" / "ep_2023-05-01_001.md",
                          {"id": "ep_2023-05-01_001", "timestamp": "2023-05-01T08:00:00+00:00",
                           "received_at": now.isoformat(), "processed": False}, "x")
    markdown_parser.write(memory / "episodes" / "ep_2023-05-02_001.md",
                          {"id": "ep_2023-05-02_001", "timestamp": "2023-05-02T08:00:00+00:00",
                           "received_at": now.isoformat(), "processed": True}, "x")
    markdown_parser.write(memory / "episodes" / "ep_2023-05-03_001.md",
                          {"id": "ep_2023-05-03_001", "timestamp": "2023-05-03T08:00:00+00:00",
                           "processed": True}, "x")
    bank_index.invalidate()
    day = episode_ids.local_day(now.isoformat()).isoformat()
    assert mcp_tools._unread_label(memory, "ep_2023-05-01_001") == f" (2023-05-01, added {day}, not yet read by Sleep)"
    assert mcp_tools._unread_label(memory, "ep_2023-05-02_001") == f" (added {day})"
    assert mcp_tools._unread_label(memory, "ep_2023-05-03_001") == ""
