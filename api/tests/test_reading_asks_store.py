"""G166 (spec §8.4) — the reading-ask store: machine-wide, outside every bank, no
URL in it, 7-day expiry applied in memory, two writers, "Ask again" resets."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from api.services import media_ingestor, reading_asks, sync_service

H = media_ingestor.url_hash("https://blog.bob-example.org/post/1")
H2 = media_ingestor.url_hash("https://blog.bob-example.org/post/2")
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    return tmp_path / "memory"


def test_the_file_lives_outside_the_bank_and_holds_no_url(memory, tmp_path):
    reading_asks.ask(memory, H, host="blog.bob-example.org", host_class="public", now=T0)
    path = reading_asks.path_for(memory)
    assert path == tmp_path / "home" / "reading_asks" / "memory.json"
    assert not memory.exists(), "nothing is written into the bank"
    text = path.read_text()
    assert "http" not in text and "bob-example.org/post" not in text
    row = json.loads(text)["asks"][0]
    assert set(row) == {"url_hash", "host", "host_class", "asked_at", "state"}
    assert row["state"] == "waiting" and row["asked_at"] == "2026-09-29T12:00:00Z"


def test_a_read_never_creates_the_file_or_the_directory(memory, tmp_path):
    assert reading_asks.all_rows(memory) == [] and reading_asks.get(memory, H) is None
    assert reading_asks.waiting(memory) == [] and reading_asks.counts(memory)["waiting"] == 0
    assert not (tmp_path / "home" / "reading_asks").exists()


def test_a_bad_bank_name_is_refused_not_pathed(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    with pytest.raises(ValueError):
        reading_asks.path_for(tmp_path / "..%2Fx y")
    assert reading_asks.mtime(tmp_path / "..%2Fx y") == 0.0


def test_asking_again_resets_the_state_and_forgets_the_outcome(memory):
    reading_asks.ask(memory, H, host="blog.bob-example.org", host_class="public", now=T0)
    reading_asks.record_outcome(memory, H, "needs_login", via="a browser skill", harness="claude-code",
                                note="It asked me to sign in.", now=T0 + timedelta(minutes=1))
    row = reading_asks.get(memory, H, now=T0 + timedelta(minutes=2))
    assert (row["state"], row["via"], row["harness"], row["note"]) == (
        "needs_login", "a browser skill", "claude-code", "It asked me to sign in.")
    assert row["asked_at"] == "2026-09-29T12:00:00Z" and row["outcome_at"] == "2026-09-29T12:01:00Z"
    again = reading_asks.ask(memory, H, host="blog.bob-example.org", host_class="public",
                             now=T0 + timedelta(minutes=5))
    assert again["state"] == "waiting" and not {"outcome_at", "via", "harness", "note"} & set(again)
    assert len(reading_asks.all_rows(memory, now=T0 + timedelta(minutes=6))) == 1


def test_an_outcome_for_a_link_nobody_asked_about_writes_nothing(memory):
    assert reading_asks.record_outcome(memory, H, "blocked", host="blog.bob-example.org", now=T0) is None
    assert reading_asks.all_rows(memory, now=T0) == [] and not reading_asks.path_for(memory).exists()
    reading_asks.ask(memory, H, host="blog.bob-example.org", host_class="public", now=T0)
    with pytest.raises(ValueError):
        reading_asks.record_outcome(memory, H, "waiting")
    with pytest.raises(ValueError):
        reading_asks.record_outcome(memory, H, "made-up")


def test_via_and_note_are_plain_short_and_scrubbed(memory):
    secret = "sk-" + "Z" * 24
    reading_asks.ask(memory, H, host="h", host_class="public", now=T0)
    row = reading_asks.record_outcome(
        memory, H, "failed", via="<b>Chrome</b>\nharness " + "x" * 80, note=f"see {secret} " + "n" * 400, now=T0)
    assert "<" not in row["via"] and "\n" not in row["via"] and len(row["via"]) <= reading_asks.MAX_VIA_CHARS
    assert secret not in row["note"] and len(row["note"]) <= reading_asks.MAX_NOTE_CHARS


def test_rows_expire_after_seven_days_in_memory_and_persist_only_on_a_write(memory):
    reading_asks.ask(memory, H, host="h", host_class="public", now=T0)
    reading_asks.ask(memory, H2, host="h", host_class="public", now=T0 + timedelta(days=6))
    later = T0 + timedelta(days=8)
    before = reading_asks.path_for(memory).stat().st_mtime_ns
    assert [r["url_hash"] for r in reading_asks.all_rows(memory, now=later)] == [H2]
    assert reading_asks.path_for(memory).stat().st_mtime_ns == before, "a read never writes"
    assert len(json.loads(reading_asks.path_for(memory).read_text())["asks"]) == 2
    reading_asks.ask(memory, H, host="h", host_class="public", now=later)
    assert {r["url_hash"] for r in json.loads(reading_asks.path_for(memory).read_text())["asks"]} == {H, H2}
    reading_asks.drop(memory, H2, now=later + timedelta(days=8))
    assert json.loads(reading_asks.path_for(memory).read_text())["asks"] == [], "a write prunes"


def test_an_outcome_keeps_the_row_alive_from_its_own_time(memory):
    reading_asks.ask(memory, H, host="h", host_class="public", now=T0)
    reading_asks.record_outcome(memory, H, "needs_login", now=T0 + timedelta(days=6))
    assert reading_asks.get(memory, H, now=T0 + timedelta(days=9)) is not None


def test_waiting_is_oldest_first_and_drop_reports(memory):
    reading_asks.ask(memory, H2, host="h", host_class="public", now=T0 + timedelta(minutes=1))
    reading_asks.ask(memory, H, host="h", host_class="public", now=T0)
    assert [r["url_hash"] for r in reading_asks.waiting(memory, now=T0 + timedelta(minutes=2))] == [H, H2]
    assert reading_asks.drop(memory, H, now=T0 + timedelta(minutes=2)) is True
    assert reading_asks.drop(memory, H, now=T0 + timedelta(minutes=2)) is False


def test_two_writers_do_not_lose_each_others_rows(memory):
    hashes = [media_ingestor.url_hash(f"https://blog.bob-example.org/p/{i}") for i in range(24)]
    errors: list[BaseException] = []

    def write(chunk):
        try:
            for h in chunk:
                reading_asks.ask(memory, h, host="h", host_class="public", now=T0)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(hashes[i::3],)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert {r["url_hash"] for r in reading_asks.all_rows(memory, now=T0)} == set(hashes)


def test_a_torn_or_foreign_file_reads_as_no_asks(memory):
    path = reading_asks.path_for(memory)
    path.parent.mkdir(parents=True)
    path.write_text('{"v":1,"asks":[{"url_hash":"nothex","state":"waiting"},"junk",{"url_hash":"%s","state":"nope"}]}' % H)
    assert reading_asks.all_rows(memory) == []
    path.write_text("{oops")
    assert reading_asks.all_rows(memory) == []


def test_the_reading_component_moves_on_an_ask_an_outcome_and_a_settings_change(memory, tmp_path):
    (memory / "entities").mkdir(parents=True)
    a = sync_service.components(memory)["reading"]
    reading_asks.ask(memory, H, host="h", host_class="public", now=T0)
    b = sync_service.components(memory)["reading"]
    assert b != a
    reading_asks.record_outcome(memory, H, "needs_login", now=T0)
    import os
    os.utime(reading_asks.path_for(memory), ns=(0, reading_asks.path_for(memory).stat().st_mtime_ns + 5_000_000))
    c = sync_service.components(memory)["reading"]
    assert c != b
    from api.services import reading_settings

    reading_settings.update(agent_hosts=["x"])
    assert sync_service.components(memory)["reading"] != c
    # and only that component moved for a store write: the bank's own are untouched
    before = sync_service.components(memory)
    reading_asks.ask(memory, media_ingestor.url_hash("https://blog.bob-example.org/z"), host="h",
                     host_class="public", now=T0)
    after = sync_service.components(memory)
    assert {k for k in before if before[k] != after[k]} == {"reading"}
