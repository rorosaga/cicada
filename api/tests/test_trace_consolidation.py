"""G218 traces redesign (2026-10-28): "Learn from my day" as one switch with its preview, "What you watch and read" on
any site, project time attributed only through the person's own projects, "Remove from memory" with Undo, and the
page's days managed one item at a time. Synthetic apps, hosts, titles and ids only; no model, no network."""
from __future__ import annotations

import json
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import (bank_index, history_index, markdown_parser, trace_keys, trace_memory, trace_seal,
                          trace_store)
from api.services.claims import Claim, Evidence, parse_claims, write_claims

CHROME = "com.google.Chrome"
EDITOR = "com.example.Editor"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def midday(monkeypatch):
    """One clock for the whole test, pinned at today's noon UTC: the store reads ``trace_store._now``, promotion and
    the routes read ``datetime.now``. On the wall clock these tests failed in the first quarter hour after midnight —
    yesterday's spans are not a finished day until the forget window past midnight has gone (``PROMOTE_HOLD``). A
    test that needs another instant re-pins with ``frozen``."""
    moment = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)

    class Noon(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.astimezone().replace(tzinfo=None)

    monkeypatch.setattr(trace_store, "_now", lambda: moment)
    monkeypatch.setattr(trace_memory, "datetime", Noon)
    return moment


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada-home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


@pytest.fixture
def store(tmp_path):
    s = trace_store.TraceStore(root=tmp_path / "t", keys=trace_keys.FileKeyProvider(tmp_path / "k"))
    s.turn_on(trace_store.CONSENT_VERSION, displayed_version=2, now=_now() - timedelta(days=3))
    s.update({"browsers": ["chrome"]})
    return s


def _now() -> datetime:
    return trace_store._now().replace(microsecond=0)   # the pinned clock (`midday`, or `frozen`)


def _span(sid, start: datetime, minutes=5.0, **extra):
    return {"id": sid, "start": start.isoformat(), "end": (start + timedelta(minutes=minutes)).isoformat(),
            "bundle_id": extra.pop("bundle_id", CHROME), "app": extra.pop("app", "Chrome"), **extra}


def _yesterday_at(hour: int) -> datetime:
    return (_now() - timedelta(days=1)).replace(hour=hour, minute=0, second=0)


def _make_mine(memory: Path, eid: str, **fm):
    page = memory / "entities" / f"{eid}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "mine": {"via": "app", "day": "2026-10-01", "by": "user"}, **fm},
                          parsed.body)
    bank_index.invalidate(memory)


def _episodes(memory: Path, prefix: str) -> dict[str, markdown_parser.ParsedFile]:
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        sid = str(parsed.frontmatter.get("source_id") or "")
        if sid.startswith(prefix):
            out[sid] = parsed
    return out


# --- one switch, its aliases and its migration ---------------------------------------------------------------------


def test_learn_from_my_day_is_one_switch_off_by_default_and_the_old_keys_read_it(store):
    values = store.settings()
    assert values["learn_from_day"] is False and values["watch_and_read"] is True
    assert values["daily_summary"] is False and values["learn_from_summary"] is False   # Hyrum: still readable
    assert values["youtube_to_watch_history"] is True
    on = store.update({"learn_from_day": True})
    assert on["daily_summary"] is True and on["learn_from_summary"] is True
    assert store.update({"daily_summary": False})["learn_from_day"] is False      # the old parent still turns it off
    assert store.update({"learn_from_summary": True})["learn_from_day"] is True   # the old child turns it on
    assert store.update({"youtube_to_watch_history": False})["watch_and_read"] is False


@pytest.mark.parametrize("old, learn", [({"daily_summary": True, "learn_from_summary": True}, True),
                                        ({"daily_summary": True, "learn_from_summary": False}, False),
                                        ({}, False)])
def test_a_settings_file_from_before_migrates_without_widening_a_model_read(store, old, learn):
    """Only both old switches on (a model already read the summary) migrate to on; an index-only summary never widens
    into a model read nobody chose."""
    key = store.keys.load()
    stored = {k: v for k, v in trace_store.DEFAULTS.items() if k not in ("learn_from_day", "watch_and_read")}
    stored.update(enabled=True, consent_version=1, youtube_to_watch_history=False, **old)
    (store.root / "settings.enc").write_bytes(trace_seal.seal(key, json.dumps(stored).encode(), "settings"))
    values = store.settings()
    assert values["learn_from_day"] is learn and values["watch_and_read"] is False


def test_agreeing_to_the_newer_sheet_while_paused_keeps_the_pause(store):
    store.pause(trace_store.UNTIL_RESUMED)
    values = store.turn_on(trace_store.CONSENT_VERSION, displayed_version=2)
    assert values["paused_until"] == trace_store.UNTIL_RESUMED
    assert values["consent_version"] == trace_store.ALL_SCREENS_CONSENT
    with pytest.raises(trace_store.PayloadError):
        store.turn_on(1)   # a sheet the person did not see is refused


def test_the_recorded_sheet_is_the_one_the_app_displayed(tmp_path):
    """Review of #508, must-fix 6: an app from before 2026-10-28 echoes the served version but showed sheet 1."""
    s = trace_store.TraceStore(root=tmp_path / "t", keys=trace_keys.FileKeyProvider(tmp_path / "k"))
    assert s.turn_on(trace_store.CONSENT_VERSION)["consent_version"] == 1          # an old app: no displayed version
    assert s.turn_on(trace_store.CONSENT_VERSION, displayed_version=2)["consent_version"] == 2
    with pytest.raises(trace_store.PayloadError):
        s.turn_on(trace_store.CONSENT_VERSION, displayed_version=trace_store.CONSENT_VERSION + 1)   # unknown sheet
    with pytest.raises(trace_store.PayloadError):
        s.turn_on(trace_store.CONSENT_VERSION, displayed_version=0)


def test_the_store_refuses_a_whole_screen_frame_under_sheet_one(tmp_path):
    """Review of #508, must-fix 5: policy parity — the store holds the rail too, not only the app."""
    s = trace_store.TraceStore(root=tmp_path / "t", keys=trace_keys.FileKeyProvider(tmp_path / "k"))
    s.turn_on(trace_store.CONSENT_VERSION)   # sheet 1
    at = _now() - timedelta(minutes=5)
    with pytest.raises(trace_store.TracesOff):
        _frame(s, "frame-0001", at, display=1, displays=2)
    assert _frame(s, "frame-0002", at) == "frame-0002"   # the front window, as sheet 1 says
    s.turn_on(trace_store.CONSENT_VERSION, displayed_version=2)
    assert _frame(s, "frame-0003", at, display=1, displays=2) == "frame-0003"


def test_an_upgrade_with_the_youtube_switch_on_says_once_that_it_now_covers_every_site(store):
    key = store.keys.load()
    stored = {k: v for k, v in trace_store.DEFAULTS.items()
              if k not in ("learn_from_day", "watch_and_read", "reading_notice")}
    stored.update(enabled=True, consent_version=1, youtube_to_watch_history=True)
    (store.root / "settings.enc").write_bytes(trace_seal.seal(key, json.dumps(stored).encode(), "settings"))
    assert store.settings()["reading_notice"] is True
    assert store.update({"reading_notice": False})["reading_notice"] is False
    assert store.settings()["reading_notice"] is False                  # once
    with pytest.raises(trace_store.PayloadError):
        store.update({"reading_notice": True})                          # only the person clears it
    off = {**stored, "youtube_to_watch_history": False}
    (store.root / "settings.enc").write_bytes(trace_seal.seal(key, json.dumps(off).encode(), "settings"))
    assert store.settings()["reading_notice"] is False                  # nothing changed for them


# --- what you watch and read, on any site --------------------------------------------------------------------------


def test_a_page_read_on_any_site_joins_its_days_reading_record_index_only(tmp_path, store):
    memory = _bank(tmp_path)
    start = _now() - timedelta(hours=3)
    store.add_spans([
        _span("span-0001", start, minutes=4, url="https://docs.example/guide?utm_source=x", title="Guide"),
        _span("span-0002", start + timedelta(minutes=5), minutes=0.2, url="https://news.example/flicked"),
        _span("span-0003", start + timedelta(minutes=6), minutes=3, url="https://www.youtube.com/watch?v=aaaaaaaaaaa"),
        _span("span-0004", start + timedelta(minutes=10), minutes=5, url="https://meet.google.com/abc-defg-hij"),
    ], now=_now())
    paths = trace_memory.promote(memory, store, store.settings(), now=_now())
    day = trace_store.local_day(start).isoformat()
    reading = _episodes(memory, "reading-history:")[f"reading-history:{day}"]
    assert "docs.example" in reading.body and "Guide" in reading.body and "utm_source" not in reading.body
    assert "news.example" not in reading.body                       # 12 s is a skim, not a read
    assert "youtube" not in reading.body and "meet.google" not in reading.body   # a watch and a call are not reads
    assert _episodes(memory, "watch-history:youtube:")                 # the video joined the watch history
    assert reading.frontmatter["processed_by"] == history_index.INDEXED_BY
    assert not history_index.waits_for_model(reading.frontmatter)     # never read by a model (ruling 30)
    assert all(p.startswith("episodes/") for p in paths)
    # Idempotent: the same day again writes nothing.
    assert trace_memory.write_reading(memory, store, {trace_store.local_day(start)}, until=_now()) == []


def test_with_the_switch_off_nothing_watched_or_read_reaches_the_bank(tmp_path, store):
    memory = _bank(tmp_path)
    store.update({"watch_and_read": False})
    start = _now() - timedelta(hours=3)
    store.add_spans([_span("span-0001", start, minutes=4, url="https://docs.example/guide"),
                     _span("span-0002", start + timedelta(minutes=5), minutes=3,
                           url="https://www.youtube.com/watch?v=aaaaaaaaaaa")], now=_now())
    assert trace_memory.promote(memory, store, store.settings(), now=_now()) == []


# --- attribution and the digest -------------------------------------------------------------------------------------


def test_project_time_is_attributed_only_through_the_persons_own_projects(tmp_path):
    memory = _bank(tmp_path)
    # alpha-project declares a repository (~/src/alpha-project) but is not the person's yet: no attribution.
    span_title = {"id": "s1", "start": "2026-10-27T10:00:00Z", "end": "2026-10-27T11:00:00Z", "bundle_id": EDITOR,
                  "app": "Editor", "title": "main.py — alpha-project"}
    assert trace_memory.attribute(span_title, trace_memory.owned_projects(memory)) is None
    _make_mine(memory, "alpha-project",
               sources=[{"ref": "https://docs.example/alpha", "kind": "url", "added_by": "user"},
                        {"ref": "https://tracker.example/x", "kind": "url", "added_by": "agent", "proposed": True}])
    projects = trace_memory.owned_projects(memory)
    assert [p.id for p in projects] == ["alpha-project"]
    assert trace_memory.attribute(span_title, projects) == "alpha-project"                 # its folder, as a word
    code = {**span_title, "title": "", "url": "https://github.com/someone/alpha-project/pull/3", "host": "github.com"}
    assert trace_memory.attribute(code, projects) == "alpha-project"                       # its repository
    tied = {**span_title, "title": "", "url": "https://docs.example/alpha/page", "host": "docs.example"}
    assert trace_memory.attribute(tied, projects) == "alpha-project"                       # an address tied by hand
    proposed = {**span_title, "title": "", "url": "https://tracker.example/x", "host": "tracker.example"}
    assert trace_memory.attribute(proposed, projects) is None                              # a proposal never ties
    near = {**span_title, "title": "alpha-projects-archive notes"}
    assert trace_memory.attribute(near, projects) is None                                  # a whole word only


def test_two_projects_matching_equally_leave_the_time_unattributed(tmp_path):
    memory = _bank(tmp_path)
    _make_mine(memory, "alpha-project")
    _make_mine(memory, "beta-project", paths=[{"path": "~/work/alpha-project", "device": "mac"}])
    span = {"id": "s1", "start": "2026-10-27T10:00:00Z", "end": "2026-10-27T11:00:00Z", "bundle_id": EDITOR,
            "app": "Editor", "title": "alpha-project"}
    assert trace_memory.attribute(span, trace_memory.owned_projects(memory)) is None


def test_the_preview_is_exactly_the_digest_sleep_reads(client):
    c, memory = client
    _make_mine(memory, "alpha-project")
    assert c.post("/sources/traces/on", json={"consent_version": trace_store.CONSENT_VERSION}).status_code == 200
    c.put("/sources/traces/settings", json={"browsers": ["chrome"]})
    at = _yesterday_at(10)
    spans = [_span("span-0001", at, minutes=50, bundle_id=EDITOR, app="Editor", title="alpha-project — notes"),
             _span("span-0002", at + timedelta(minutes=50), minutes=30, bundle_id="us.zoom.xos", app="Zoom"),
             _span("span-0003", at + timedelta(minutes=80), minutes=20, url="https://docs.example/a", title="A"),
             _span("span-0004", at + timedelta(minutes=100), minutes=15, bundle_id="com.example.Mail", app="Mail")]
    trace_store.store().add_spans(spans, now=_now())
    preview = c.get("/sources/traces/preview").json()
    counts = preview["counts"]
    assert counts["projects"][0]["id"] == "alpha-project" and counts["projects"][0]["seconds"] == 3000
    assert counts["calls"]["count"] == 1 and counts["reading"]["pages"] == 1
    assert counts["else"]["apps"] == ["Mail"]
    assert "Alpha Project — 50 min (Editor)" in preview["text"]
    # Turned on, the digest written is the preview, word for word.
    c.put("/sources/traces/settings", json={"learn_from_day": True})
    c.post("/sources/traces/sync", json={"spans": []})
    digest = _episodes(memory, "traces-day:")[f"traces-day:{at.date().isoformat()}"]
    assert digest.body.strip() == preview["text"].strip()


# --- what traces added, Remove from memory, Undo --------------------------------------------------------------------


def _claims_through_the_writers(memory: Path, digest: str, other: str) -> None:
    """Review of #508, B2: built by the real writers — a done happening is born closed (``valid_to = valid_from``)."""
    from api.services import agentic_write, progress

    yesterday = (_now() - timedelta(days=1)).date()
    r = progress.record_happening(memory, subject="alpha-project", text="Worked on the draft", status="done",
                                  source_episode=digest, day=yesterday, date_basis="episode", observer="agent",
                                  origin="sleep", authored_by="claude-haiku-test")
    assert r["action"] == "written", r
    for predicate, obj, episode in [("habit", "morning writing", digest), ("uses", "the editor", digest),
                                    ("uses", "the editor", other)]:
        w = agentic_write.write_claim(memory, "bob-example", predicate, obj, observer="agent", object_kind="literal",
                                      source_episode=episode, origin="sleep", authored_by="claude-haiku-test")
        assert w.get("action") in ("written", "reinforced", "created", "updated"), w


def _commit_all(memory: Path) -> None:
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "fixture"], check=True, capture_output=True)


def _claims(memory: Path, eid: str) -> list:
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)


def test_remove_from_memory_takes_back_only_what_traces_alone_said_in_one_commit_and_undo_restores_it(client):
    c, memory = client
    assert c.post("/sources/traces/on", json={"consent_version": trace_store.CONSENT_VERSION}).status_code == 200
    c.put("/sources/traces/settings", json={"learn_from_day": True})
    at = _yesterday_at(9)
    trace_store.store().add_spans([_span("span-0001", at, minutes=40, bundle_id=EDITOR, app="Editor")], now=_now())
    c.post("/sources/traces/sync", json={"spans": []})
    digest = next(iter(_episodes(memory, "traces-day:").values())).frontmatter["id"]
    _claims_through_the_writers(memory, digest, "ep_2026-09-01_001")
    _commit_all(memory)
    bank_index.invalidate(memory)
    happening = next(cl for cl in _claims(memory, "alpha-project") if cl.predicate == "happened")
    born = happening.valid_to
    assert born is not None, "a done happening is born closed — the case the first fixture missed"
    added = c.get("/sources/traces/added").json()
    assert (added["beliefs"], added["progress"]) == (1, 1) and added["since"] == at.date().isoformat()
    head = subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    r = c.post("/sources/traces/remove-from-memory")
    assert r.status_code == 200 and r.json()["removed"] == 2
    log = subprocess.run(["git", "-C", str(memory), "log", "--format=%s", f"{head.strip()}..HEAD"],
                         capture_output=True, text=True).stdout.strip().splitlines()
    assert len(log) == 1 and "Removed from memory" in log[0]                                # ONE commit
    happening = next(cl for cl in _claims(memory, "alpha-project") if cl.predicate == "happened")
    assert happening.superseded_by and happening.valid_to == born                           # taken back, dates kept
    bob = {cl.predicate: cl for cl in _claims(memory, "bob-example") if cl.predicate != "retracts"}
    assert bob["habit"].superseded_by and bob["habit"].valid_to                              # closed, kept as history
    assert bob["uses"].valid_to is None and not bob["uses"].superseded_by                   # another conversation says it
    assert c.get("/sources/traces/added").json()["beliefs"] == 0
    rid = r.json()["removal_id"]
    assert [x["id"] for x in c.get("/sources/traces/added").json()["removals"]] == [rid]
    u = c.post("/sources/traces/remove-from-memory/undo", json={"removal_id": rid})
    assert u.status_code == 200 and u.json()["restored"] == 2
    happening = next(cl for cl in _claims(memory, "alpha-project") if cl.predicate == "happened")
    assert happening.valid_to == born and not happening.superseded_by                        # exactly as it was
    habit = next(cl for cl in _claims(memory, "bob-example") if cl.predicate == "habit")
    assert habit.valid_to is None and not habit.superseded_by
    assert not [cl for e in ("alpha-project", "bob-example") for cl in _claims(memory, e) if cl.predicate == "retracts"]
    assert c.post("/sources/traces/remove-from-memory/undo", json={"removal_id": rid}).status_code == 404


def test_remove_after_a_wipe_is_refused_and_changes_nothing(client):
    """Review of #508, B3: with no key, the undo record cannot be kept, so nothing is removed."""
    c, memory = client
    assert c.post("/sources/traces/on", json={"consent_version": trace_store.CONSENT_VERSION}).status_code == 200
    c.put("/sources/traces/settings", json={"learn_from_day": True})
    trace_store.store().add_spans([_span("span-0001", _yesterday_at(9), minutes=40, bundle_id=EDITOR, app="Editor")],
                                  now=_now())
    c.post("/sources/traces/sync", json={"spans": []})
    digest = next(iter(_episodes(memory, "traces-day:").values())).frontmatter["id"]
    _claims_through_the_writers(memory, digest, "ep_2026-09-01_001")
    _commit_all(memory)
    bank_index.invalidate(memory)
    assert c.post("/sources/traces/wipe", json={"confirm": True}).status_code == 200
    before = (memory / "entities" / "bob-example.md").read_bytes()
    r = c.post("/sources/traces/remove-from-memory")
    assert r.status_code == 409 and "could not be undone" in r.json()["detail"]
    assert (memory / "entities" / "bob-example.md").read_bytes() == before


# --- managing traces by day ------------------------------------------------------------------------------------------


def _frame(store, fid, at, *, span_id="", display=0, displays=0):
    meta = {"id": fid, "at": at.isoformat(), "bundle_id": EDITOR, "app": "Editor", "width": 640, "height": 400,
            "span_id": span_id, "display": display, "displays": displays}
    return store.add_frame(meta, b"\xff\xd8\xff\xe0" + b"\0" * 64, "words on screen", now=_now())


def test_a_day_card_counts_the_day_names_its_cover_and_the_screens_connected(store):
    at = _now() - timedelta(hours=2)
    store.add_spans([_span("span-0001", at, minutes=30, bundle_id=EDITOR, app="Editor"),
                     _span("span-0002", at + timedelta(minutes=30), minutes=5, url="https://docs.example/a")],
                    now=_now())
    _frame(store, "frame-0001", at + timedelta(minutes=1), span_id="span-0001", display=2, displays=2)
    _frame(store, "frame-0002", at + timedelta(minutes=1), span_id="span-0001", display=1, displays=2)
    _frame(store, "frame-0003", at + timedelta(minutes=31), span_id="span-0002")
    card = store.day_cards()[0]
    assert card["day"] == trace_store.local_day(at).isoformat()
    assert (card["spans"], card["frames"], card["apps"], card["sites"]) == (2, 3, 2, 1)
    assert card["screens"] == 2 and card["seconds"] == 35 * 60
    assert card["cover"] == "frame-0002"     # the longest span's, the main screen's
    assert store.timeline(trace_store.local_day(at))["screens"] == 2


def test_deleting_a_span_takes_its_screenshots_and_a_whole_day_goes_at_once(client):
    c, _ = client
    assert c.post("/sources/traces/on", json={"consent_version": trace_store.CONSENT_VERSION}).status_code == 200
    s = trace_store.store()
    at = _now() - timedelta(hours=2)
    s.add_spans([_span("span-0001", at, minutes=10, bundle_id=EDITOR, app="Editor"),
                 _span("span-0002", at + timedelta(minutes=10), minutes=10, bundle_id=EDITOR, app="Editor")],
                now=_now())
    _frame(s, "frame-0001", at + timedelta(minutes=1), span_id="span-0001")
    _frame(s, "frame-0002", at + timedelta(minutes=11), span_id="span-0002")
    day = trace_store.local_day(at).isoformat()
    r = c.post("/sources/traces/delete", json={"day": day, "spans": ["span-0001"]})
    assert r.json() == {"spans": 1, "frames": 1}
    timeline = c.get(f"/sources/traces/timeline?day={day}").json()
    assert [x["id"] for x in timeline["spans"]] == ["span-0002"] and [f["id"] for f in timeline["frames"]] == ["frame-0002"]
    assert not (s.root / "shots" / day / "frame-0001.enc").exists()
    assert c.post("/sources/traces/delete", json={"day": day}).status_code == 422   # say what
    assert c.post("/sources/traces/delete", json={"day": day, "all": True}).json() == {"spans": 1, "frames": 1}
    assert c.get("/sources/traces/day-cards").json()["days"] == []
    assert not (s.root / "shots" / day).exists()


def test_deleting_a_span_across_midnight_takes_its_next_day_screenshots(store):
    """Review of #508: a span is filed under the day it started; its screenshots after midnight under the next."""
    midnight = datetime.combine(_now().date(), datetime.min.time(), tzinfo=timezone.utc)
    start = midnight - timedelta(minutes=20)
    store.add_spans([_span("span-0001", start, minutes=40, bundle_id=EDITOR, app="Editor"),
                     _span("span-0002", midnight + timedelta(minutes=30), minutes=10, bundle_id=EDITOR, app="Editor")],
                    now=_now())
    _frame(store, "frame-0001", start + timedelta(minutes=5), span_id="span-0001")
    _frame(store, "frame-0002", midnight + timedelta(minutes=10), span_id="span-0001")
    _frame(store, "frame-0003", midnight + timedelta(minutes=12))          # no span id, inside its time range
    _frame(store, "frame-0004", midnight + timedelta(minutes=35), span_id="span-0002")
    gone = store.delete(trace_store.local_day(start), spans=["span-0001"])
    assert gone == {"spans": 1, "frames": 3}
    left = store.timeline(trace_store.local_day(midnight))
    assert [f["id"] for f in left["frames"]] == ["frame-0004"] and [x["id"] for x in left["spans"]] == ["span-0002"]
    assert not (store.root / "shots" / midnight.date().isoformat() / "frame-0002.enc").exists()


def test_a_frame_keeps_which_screen_it_shows_only_when_it_makes_sense(store):
    at = _now() - timedelta(minutes=5)
    _frame(store, "frame-0001", at, display=2, displays=3)
    _frame(store, "frame-0002", at, display=4, displays=3)    # nonsense: kept, without screen numbers
    rows = {f["id"]: f for f in store.timeline(trace_store.local_day(at))["frames"]}
    assert (rows["frame-0001"]["display"], rows["frame-0001"]["displays"]) == (2, 3)
    assert "display" not in rows["frame-0002"]
