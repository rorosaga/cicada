"""G124 — one row per memory source (harness / browser / social / feed /
messaging / import), computed from episode frontmatter, `source_episodes`
credits and `GET /sources/channels` state. Hermetic: a throwaway bank under
tmp_path; the real memory/ is never read. No network, no LLM."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_registry, source_overview, sync_state

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
UUID_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def _episode(memory, episode_id, *, timestamp, origin=None, session_id=None,
             source_id=None, harness=None, title="Untitled"):
    d = memory / "episodes"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {episode_id}", f"timestamp: '{timestamp}'", f"title: {title}",
             "processed: true"]
    for key, value in (("origin", origin), ("session_id", session_id),
                       ("source_id", source_id), ("harness", harness)):
        if value is not None:
            lines.append(f"{key}: {value}")
    lines += ["---", "", "body"]
    (d / f"{episode_id}.md").write_text("\n".join(lines), encoding="utf-8")


def _entity(memory, entity_id, source_episodes):
    d = memory / "entities"
    d.mkdir(parents=True, exist_ok=True)
    eps = "\n".join(f"- {e}" for e in source_episodes) if source_episodes else "[]"
    (d / f"{entity_id}.md").write_text(
        f"---\nid: {entity_id}\ntype: concept\nstatus: active\nconfidence: 0.8\n"
        f"source_episodes:\n{eps}\n---\n\n# {entity_id}\n", encoding="utf-8")


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    # two Claude Code sessions, one Cursor session, one legacy mcp episode (no session)
    _episode(memory, "ep_2026-08-01_001", timestamp="2026-08-01T09:00:00+00:00",
             origin="mcp", session_id=UUID_A, harness="claude-code")
    _episode(memory, "ep_2026-08-01_002", timestamp="2026-08-01T10:00:00+00:00",
             origin="mcp", session_id=UUID_A, harness="claude-code")
    _episode(memory, "ep_2026-08-02_001", timestamp="2026-08-02T09:00:00+00:00",
             origin="mcp", session_id=UUID_B, harness="cursor")
    _episode(memory, "ep_2026-07-01_001", timestamp="2026-07-01T09:00:00+00:00", origin="mcp")
    # one imported Claude thread, two Safari bookmarks, one telegram capture
    _episode(memory, "ep_2026-08-03_001", timestamp="2026-08-03T09:00:00+00:00",
             origin="claude-export", source_id="thread-1")
    _episode(memory, "ep_2026-08-04_001", timestamp="2026-08-04T09:00:00+00:00", origin="safari-bookmark")
    _episode(memory, "ep_2026-08-04_002", timestamp="2026-08-04T10:00:00+00:00", origin="safari-bookmark")
    _episode(memory, "ep_2026-08-05_001", timestamp="2026-08-05T09:00:00+00:00", origin="telegram")
    # an origin the catalog does not know
    _episode(memory, "ep_2026-08-06_001", timestamp="2026-08-06T09:00:00+00:00", origin="mystery-app")
    _entity(memory, "alpha-project", ["ep_2026-08-01_001", "ep_2026-08-04_001"])
    _entity(memory, "bob-example", ["ep_2026-08-01_002"])
    _entity(memory, "gamma-tool", ["ep_2026-07-01_001"])
    sync_state.record_sync(memory, "safari-bookmarks", count=42, at="2026-08-04T10:05:00Z")
    bank_index.invalidate()
    return memory


def _rows(memory, telegram_enabled=False):
    channels = channel_registry.build_channels(memory, telegram_enabled=telegram_enabled)
    return {r["id"]: r for r in source_overview.build_overview(memory, channels=channels)}


def test_source_key_routes_mcp_and_session_episodes_to_a_harness_row():
    assert source_overview.source_key({"origin": "mcp", "session_id": UUID_A, "harness": "claude-code"}) == "harness:claude-code"
    assert source_overview.source_key({"origin": "mcp"}) == "harness:unknown", "R4: legacy mcp episodes still belong to a harness row"
    assert source_overview.source_key({"session_id": UUID_A, "harness": "cursor"}) == "harness:cursor"
    assert source_overview.source_key({"origin": "safari-bookmark"}) == "safari-bookmarks"
    assert source_overview.source_key({"origin": "claude-export", "source_id": "t"}) == "chat-export:claude"
    assert source_overview.source_key({"origin": "gemini-export", "source_id": "t"}) == "chat-export:gemini", "conversations.py:599 writes it"
    assert source_overview.source_key({"origin": "tiktok-history"}) == "tiktok"
    assert source_overview.source_key({"origin": "mystery-app"}) == "origin:mystery-app"
    assert source_overview.source_key({}) == "origin:unknown"


def test_harness_rows_count_conversations_episodes_and_entities(bank):
    rows = _rows(bank)
    cc = rows["harness:claude-code"]
    assert cc["kind"] == "harness" and cc["label"] == "Claude Code" and cc["mark"] == "claude-code"
    assert cc["conversations"] == 1 and cc["episodes"] == 2 and cc["entities"] == 2
    assert cc["harness"] == "claude-code" and cc["connected"] is True
    assert cc["last_activity_at"] == "2026-08-01T10:00:00+00:00"
    cursor = rows["harness:cursor"]
    assert cursor["conversations"] == 1 and cursor["episodes"] == 1 and cursor["entities"] == 0
    legacy = rows["harness:unknown"]
    assert legacy["conversations"] == 0 and legacy["episodes"] == 1 and legacy["entities"] == 1
    assert legacy["harness"] == "unknown", "the filter value the app sends back to /conversations/recent"


def test_catalog_rows_join_channel_state(bank):
    rows = _rows(bank)
    safari = rows["safari-bookmarks"]
    assert safari["kind"] == "browser" and safari["channel_id"] == "safari-bookmarks"
    assert safari["episodes"] == 2 and safari["entities"] == 1
    assert safari["items"] == 42 and safari["connected"] is True and safari["actions"] == ["sync"]
    assert safari["last_activity_at"] == "2026-08-04T10:05:00Z", "channel last_sync is newer than the last episode"
    assert safari["origins"] == ["safari-bookmark"]
    claude_export = rows["chat-export:claude"]
    assert claude_export["kind"] == "harness" and claude_export["conversations"] == 1
    assert claude_export["mark"] == "claude-export"


def test_telegram_row_follows_the_env_flag(bank):
    assert _rows(bank, telegram_enabled=False)["telegram"]["connected"] is False
    assert _rows(bank, telegram_enabled=True)["telegram"]["connected"] is True
    assert _rows(bank)["telegram"]["episodes"] == 1, "shown even when not connected — it has episodes (R2)"


def test_unknown_origin_gets_an_open_family_row_and_empty_catalog_rows_are_hidden(bank):
    rows = _rows(bank)
    mystery = rows["origin:mystery-app"]
    assert mystery["kind"] == "import" and mystery["label"] == "mystery-app" and mystery["episodes"] == 1
    assert "pinterest" not in rows and "rss" not in rows, "R2: no evidence, no card"
    assert "files" not in rows, "an empty url index is no evidence either (R1: files has no origins of its own)"


def _media_page(memory, entity_id, *, origin=None):
    origin_line = f"origin: {origin}\n" if origin else ""
    (memory / "entities" / f"{entity_id}.md").write_text(
        f"---\nid: {entity_id}\ntype: media\nstatus: active\nconfidence: 0.9\n{origin_line}"
        f"source_episodes: []\nrelated: []\nmedia:\n  url: https://example.com/{entity_id}\n---\n\n# {entity_id}\n",
        encoding="utf-8")


def test_files_row_counts_nil_origin_media_pages_not_the_url_index(bank):
    """Final review M1: the Files & links page lists the Feed items whose page
    carries no `origin:`, so its card must count exactly those — not
    `len(url_index)`, which is every item `ingest_batch` ever wrote. Three
    imported bookmarks + one pasted link: the card says 1, not 4."""
    from api.services import media_ingestor
    index = {}
    for i, origin in enumerate(("safari-bookmark", "safari-bookmark", "chrome-bookmark", None)):
        entity_id = f"media-{i}"
        _media_page(bank, entity_id, origin=origin)
        index[f"h{i}"] = {"media_entity_id": entity_id, "episode_id": "ep_x", "url": f"https://example.com/{i}",
                          "title": entity_id, "media_type": "url", "thumbnail": None,
                          "saved_at": "2026-08-04T10:00:00+00:00"}
    media_ingestor.save_url_index(bank, index)
    bank_index.invalidate()
    rows = _rows(bank)
    assert rows["files"]["items"] == 1 and rows["files"]["connected"] is True
    channels = {c["id"]: c for c in channel_registry.build_channels(bank, telegram_enabled=False)}
    assert channels["files"]["count"] == 4, "the channel row keeps counting the whole index — only the card changed"
    assert rows["safari-bookmarks"]["items"] == 42, "an origin-bearing row still reads its channel's count"
    # only imported pages -> no nil-origin evidence -> no Files & links card (R2)
    (bank / "entities" / "media-3.md").unlink()
    bank_index.invalidate()
    assert "files" not in _rows(bank)


def test_rows_are_ordered_by_kind_then_recency(bank):
    ordered = source_overview.build_overview(
        bank, channels=channel_registry.build_channels(bank, telegram_enabled=False))
    kinds = [r["kind"] for r in ordered]
    assert kinds == sorted(kinds, key=source_overview.KIND_ORDER.index)
    harness_rows = [r for r in ordered if r["kind"] == "harness"]
    assert harness_rows[0]["id"] == "chat-export:claude", "newest activity first within a kind"


def test_empty_bank_yields_no_rows(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    bank_index.invalidate()
    channels = channel_registry.build_channels(memory, telegram_enabled=False)
    assert source_overview.build_overview(memory, channels=channels) == []


# --- the route --------------------------------------------------------------


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_HOME", str(bank.parent / "home"))
    monkeypatch.delenv("CICADA_TELEGRAM_BOT_TOKEN", raising=False)
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_overview_route_is_camel_case_and_etagged(client, bank):
    first = client.get("/sources/overview")
    assert first.status_code == 200, first.text
    body = first.json()
    ids = {r["id"] for r in body["sources"]}
    assert {"harness:claude-code", "safari-bookmarks", "chat-export:claude"} <= ids
    row = next(r for r in body["sources"] if r["id"] == "safari-bookmarks")
    assert {"lastActivityAt", "channelId", "lastError", "conversations", "entities", "items"} <= set(row)
    etag = first.headers["etag"]
    assert client.get("/sources/overview", headers={"If-None-Match": etag}).status_code == 304
    # a new episode moves the `episodes` component -> the etag must move too
    _episode(bank, "ep_2026-08-07_001", timestamp="2026-08-07T09:00:00+00:00", origin="safari-bookmark")
    bank_index.invalidate()
    again = client.get("/sources/overview", headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.headers["etag"] != etag


def test_sources_items_carry_origin_and_folder(client, bank):
    """R6 — the per-source page filters the existing Feed items by origin and
    groups them by folder, so both must ride `GET /sources`."""
    from api.services import media_ingestor
    media_ingestor.save_url_index(bank, {
        "h1": {"media_entity_id": "media-alpha", "episode_id": "ep_x", "url": "https://example.com/a",
               "title": "A", "media_type": "url", "thumbnail": None, "saved_at": "2026-08-04T10:00:00+00:00"},
    })
    (bank / "entities" / "media-alpha.md").write_text(
        "---\nid: media-alpha\ntype: media\nstatus: active\nconfidence: 0.9\norigin: safari-bookmark\n"
        "folder: Favorites/Papers\nsource_episodes: []\nrelated: []\nmedia:\n  url: https://example.com/a\n---\n\n# A\n",
        encoding="utf-8")
    bank_index.invalidate()
    items = client.get("/sources").json()["items"]
    row = next(i for i in items if i["mediaEntityId"] == "media-alpha")
    assert row["origin"] == "safari-bookmark" and row["folder"] == "Favorites/Papers"


def test_saved_links_and_feeds_now_credit_their_own_rows(bank):
    """G124 follow-up. Both rows used to carry no origins at all: the cards
    showed a count and nothing else, because no episode on disk pointed at
    them. With `saved-link` and `rss` stamped at the writers, the same joins
    every other row uses start working for these two."""
    _episode(bank, "ep_2026-08-07_001", timestamp="2026-08-07T09:00:00+00:00", origin="saved-link")
    _episode(bank, "ep_2026-08-07_002", timestamp="2026-08-07T10:00:00+00:00", origin="rss")
    _entity(bank, "delta-concept", ["ep_2026-08-07_001"])
    _entity(bank, "epsilon-concept", ["ep_2026-08-07_002"])
    _media_page(bank, "media-saved", origin="saved-link")
    bank_index.invalidate()

    rows = _rows(bank)
    assert rows["files"]["episodes"] == 1
    assert rows["files"]["entities"] == 1
    assert rows["files"]["last_activity_at"] == "2026-08-07T09:00:00+00:00"
    assert rows["rss"]["episodes"] == 1
    assert rows["rss"]["entities"] == 1
    assert rows["rss"]["last_activity_at"] == "2026-08-07T10:00:00+00:00"
    # Neither leaks into the open `origin:<id>` family any more.
    assert "origin:saved-link" not in rows and "origin:rss" not in rows


def test_the_files_card_counts_stamped_and_pre_stamp_saves_together(bank):
    """A bank spans the change: links saved before the writers stamped an
    origin carry none, links saved after carry `saved-link`, and they are the
    same card and the same page. Counting only one of the two would make the
    card disagree with its own list — the M1 bug, inverted."""
    _media_page(bank, "media-legacy", origin=None)
    _media_page(bank, "media-new", origin="saved-link")
    _media_page(bank, "media-bookmark", origin="safari-bookmark")
    bank_index.invalidate()

    assert _rows(bank)["files"]["items"] == 2


# --- activity (R-A16, the Memory-sources sparkline) -------------------------


def test_activity_buckets_captures_by_day_inside_the_window(bank):
    """R-A16 — one sparse ISO-day histogram per source, computed in the loop
    `build_overview` already runs. Absolute date keys, never a rolling array:
    a 304'd payload must render a day SHORT, never a day SHIFTED.

    `today=2026-08-10` puts the fixture's window start at 2026-07-12, so the
    two Aug 4 Safari bookmarks land in one bucket and the Jul 1 episode is
    dropped — inclusion and the bound in one assertion.
    """
    from datetime import date
    rows = {r["id"]: r for r in source_overview.build_overview(
        bank, channels=[], today=date(2026, 8, 10))}
    assert rows["safari-bookmarks"]["activity"] == {"2026-08-04": 2}
    assert rows["harness:unknown"]["activity"] == {}      # the Jul 1 legacy mcp episode
    # A silent day has NO key — the series is sparse on the wire and densified
    # client-side, so a gap can never be read as a zero the backend asserted.
    assert "2026-08-05" not in rows["safari-bookmarks"]["activity"]


def test_activity_reads_a_naive_stamp_as_local_then_converts_to_utc():
    """The trap the design panel named: banks hold naive-local stamps
    (pre-G114) beside aware ones, so `raw[:10]` calls a local day a UTC day
    and is off by one, invisibly, for a subset of rows."""
    import os
    import time

    from api.services import source_overview as mod
    os.environ["TZ"] = "Pacific/Auckland"
    time.tzset()                                             # UTC+12/+13
    try:
        assert mod._activity_day("2026-09-02T09:00:00") == "2026-09-01"
        assert mod._activity_day("2026-09-02T09:00:00+00:00") == "2026-09-02"
        assert mod._activity_day("2026-09-02T09:00:00Z") == "2026-09-02"
        assert mod._activity_day("") is None
        assert mod._activity_day("not-a-date") is None
    finally:
        os.environ.pop("TZ", None)
        time.tzset()


def test_overview_etag_recipe_is_unchanged_by_the_activity_field(client, bank):
    """ETag ship-together (R-A16): `activity` is computed from episodes, which
    the recipe already covers and `VersionVector.mapping` already routes to
    `.sourcesOverview` — so the recipe must NOT move, and no client mapping
    change is owed. Pinned behaviourally, not by grepping the source.

    (The connector tag is built from `ADAPTERS`, so read it off the response
    rather than retyping it: the point of this test is that adding `activity`
    changed nothing about the recipe's INPUTS, which the recomputation below
    proves by reproducing the same value from the same four arguments.)
    """
    from api.routers.sources import ADAPTERS
    from api.services import sync_service
    r = client.get("/sources/overview")
    assert r.status_code == 200
    assert "activity" in r.json()["sources"][0]
    tag = ",".join(f"{k}:{a.is_connected()}" for k, a in sorted(ADAPTERS.items()))
    expected = sync_service.etag_for(
        bank, "sources", "episodes", "entities",
        extra=f"overview|telegram:False|connectors:{tag}",
    )
    assert r.headers["etag"] == expected
    assert client.get("/sources/overview", headers={"If-None-Match": expected}).status_code == 304
