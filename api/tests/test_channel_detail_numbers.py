"""R-S5 — no channel's `detail` carries a formatted number any more.

`_plural` baked `f"{n:,}"` into every state line, and the app printed it
verbatim (`ChannelSourceView.swift:83`, `ConnectedChannelRow.swift:123`), so a
server-side `en_US` grouping sat beside the app's own locale grouping in one
window (critique B1). The count now rides `count`/`count_noun`/`count_is_delta`
and the client composes the line (`ChannelDetailLine.text`) — which is also the
only way the number can follow the READER's locale, since the server has no
idea what it is.

Hermetic: every test builds its own `tmp_path` bank, no network, no LLM. This
file is self-contained on purpose — `test_source_channels.py`'s `client`
fixture yields a `(client, path)` tuple and there is no shared `bank` fixture,
so a new file inherits neither.
"""

from __future__ import annotations

import json
import re

from api.services import bank_index, channel_registry
from api.services.connectors import ADAPTERS


def _channels(memory_path, *, telegram_enabled: bool = True, **kwargs) -> dict:
    bank_index.invalidate()  # a warm index would serve the previous test's bank
    return {c["id"]: c for c in channel_registry.build_channels(
        memory_path, telegram_enabled=telegram_enabled, **kwargs)}


def _busy_bank(tmp_path):
    """A bank with something in EVERY counted branch, so the sweeps below are
    not vacuous: both subscription registries, every local-file sync, both chat
    exports, a Telegram capture, the saved-URL index, and a connector run."""
    from api.services import calendar_registry, feed_registry, sync_state

    feed_registry.subscribe_feed(tmp_path, "https://example.com/feed.xml")
    calendar_registry.subscribe_calendar(tmp_path, "https://example.com/cal.ics")
    sync_state.record_sync(tmp_path, "bookmarks", count=1035, at="2026-08-29T10:00:00Z")
    sync_state.record_sync(tmp_path, "safari-tabs", count=12, at="2026-08-29T11:00:00Z")
    sync_state.record_sync(tmp_path, "notes", count=18, at="2026-08-29T12:00:00Z")
    sync_state.record_sync(tmp_path, "pinterest", count=7, at="2026-08-30T10:00:00Z")

    episodes = tmp_path / "episodes"
    episodes.mkdir(parents=True, exist_ok=True)
    for i, origin in enumerate(("claude-export", "chatgpt-export", "telegram")):
        (episodes / f"ep_2026-08-0{i + 1}_001.md").write_text(
            f"---\nid: ep_2026-08-0{i + 1}_001\norigin: {origin}\n"
            f"timestamp: '2026-08-0{i + 1}T09:00:00Z'\n---\nx\n",
            encoding="utf-8")

    sources = tmp_path / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "url_index.json").write_text(
        json.dumps({"h1": {"url": "https://a.example"}, "h2": {"url": "https://b.example"}}),
        encoding="utf-8")
    return tmp_path


def _detail_without_price_note(ch: dict) -> str:
    """X's ``PRICE_NOTE`` ("~$0.001/read · pay-per-use", `x.py:79`) is a PRICE,
    not a count, and it legitimately contains a decimal — strip it first or the
    grouping regex below flags the one string this rule was never about. (It
    reaches Settings → Integrations, not the Sources page; the 2026-09-03 G124
    ruling is about the app's own surfaces, and this change adds no new one.)"""
    detail = ch.get("detail") or ""
    for adapter in ADAPTERS.values():
        note = getattr(adapter, "PRICE_NOTE", None)
        if note and note in detail:
            detail = detail.replace(note, "").strip(" ·")
    return detail


def test_no_channel_detail_contains_a_grouped_or_leading_number(tmp_path):
    channels = _channels(_busy_bank(tmp_path), connectors_connected={"pinterest": True})
    for cid, ch in channels.items():
        detail = _detail_without_price_note(ch)
        assert not re.search(r"\d[.,]\d{3}", detail), f"{cid}: {detail!r}"
        assert not re.match(r"^\+?\d", detail), f"{cid} still leads with a count: {detail!r}"


def test_a_counted_channel_ships_a_singular_noun_and_a_delta_flag(tmp_path):
    channels = _channels(_busy_bank(tmp_path), connectors_connected={"pinterest": True})
    # A running total: the noun is singular, the flag is false.
    chrome = channels["chrome-bookmarks"]
    assert chrome["count"] == 1035
    assert chrome["count_noun"] == "bookmark"
    assert chrome["count_is_delta"] is False
    assert "1,035" not in (chrome["detail"] or "")
    assert chrome["detail"] == "synced 2026-08-29"
    # "items pulled THIS run" (`_connector_channel:150-153`) — the flag is what
    # keeps the client from printing it as a total.
    pin = channels["pinterest"]
    assert pin["count"] == 7
    assert pin["count_noun"] == "pin"
    assert pin["count_is_delta"] is True
    assert pin["detail"] == "synced 2026-08-30"


def test_a_failed_or_skipped_poll_ships_no_noun_so_no_count_can_be_composed(tmp_path):
    """"0 pins · Last sync failed" must be unrepresentable, not merely
    unlikely — a branch with nothing to count ships no noun."""
    from api.services import sync_state

    sync_state.record_error(tmp_path, "pinterest", "HTTPStatusError: 401")
    ch = _channels(tmp_path, connectors_connected={"pinterest": True})["pinterest"]
    assert ch["count_noun"] is None
    assert ch["count_is_delta"] is False
    assert ch["detail"].startswith("Last sync failed")

    sync_state.record_skip(tmp_path, "reddit", "connector fetch disabled")
    skipped = _channels(tmp_path, connectors_connected={"reddit": True})["reddit"]
    assert skipped["count_noun"] is None
    assert skipped["detail"].startswith("Last sync skipped")

    # And an untouched channel with no state at all.
    assert _channels(tmp_path)["calendar"]["count_noun"] is None


# The nouns every branch of `build_channels` can ship, plus the adapters'
# `CHANNEL_NOUN`s. Named here so a new counted branch either appears in this
# set or fails the sweep loudly, rather than reaching the client as
# "calendarys".
_EXPECTED_NOUNS = {
    "conversation", "bookmark", "tab", "note", "feed", "calendar", "capture",
    "saved item", "pin",
}


def _pluralises_by_adding_s(noun: str) -> bool:
    """English's regular plural: `+ "s"`. A head word ending in a sibilant
    (`s x z ch sh`) takes `-es`, and one ending in a consonant + `y` takes
    `-ies` — either would print wrong through the client's `+ "s"`."""
    head = noun.split()[-1]
    if head.endswith(("s", "x", "z", "ch", "sh")):
        return False
    if head.endswith("y") and len(head) > 1 and head[-2] not in "aeiou":
        return False
    return True


def test_every_shipped_noun_pluralises_by_adding_s(tmp_path):
    """R-S16 — the client pluralises with `+ "s"`; an irregular noun here would
    silently print "calendarys". Adapters supply `CHANNEL_NOUN` too, so this
    sweeps `ADAPTERS` (`pin`, `saved item`, `bookmark`) as well as the literals
    in `build_channels` (`conversation`, `bookmark`, `tab`, `note`, `feed`,
    `calendar`, `capture`, `saved item`) — all regular today, and this is what
    keeps that true."""
    connected = {cid: True for cid in ADAPTERS}
    channels = _channels(_busy_bank(tmp_path), connectors_connected=connected)
    shipped = {ch["count_noun"] for ch in channels.values() if ch["count_noun"]}
    shipped |= {adapter.CHANNEL_NOUN for adapter in ADAPTERS.values()}

    assert _EXPECTED_NOUNS <= shipped, f"a counted branch stopped shipping its noun: {shipped}"
    for noun in sorted(shipped):
        assert noun == noun.lower(), f"{noun!r} is not the bare singular the client pluralises"
        assert _pluralises_by_adding_s(noun), (
            f"{noun!r} does not pluralise with + 's' — the client would print "
            f"{noun + 's'!r}")
