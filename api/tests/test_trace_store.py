"""G218 — activity traces' store: sealed at rest, the policy re-applied, retention, pause, forget and wipe.

Synthetic apps, titles and sites only (``com.example.*``, ``alpha-project``); never a real title."""
from __future__ import annotations

import json
import os
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api.services import trace_keys, trace_policy, trace_seal, trace_store
from api.services.trace_store import TraceStore

NOW = datetime(2026, 10, 23, 15, 20, tzinfo=timezone.utc)
CHROME = "com.google.Chrome"
EDITOR = "com.example.Editor"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def store(tmp_path) -> TraceStore:
    s = TraceStore(root=tmp_path / "home" / "traces", keys=trace_keys.FileKeyProvider(tmp_path / "home" / "traces.key"))
    s.turn_on(trace_store.CONSENT_VERSION, now=NOW - timedelta(hours=1))
    return s


def _span(sid: str, start: datetime, minutes: float = 5, *, bundle=EDITOR, app="Editor", title=None, url=None,
          **extra) -> dict:
    row = {"id": sid, "start": start.isoformat(), "end": (start + timedelta(minutes=minutes)).isoformat(),
           "bundle_id": bundle, "app": app}
    if title is not None:
        row["title"] = title
    if url is not None:
        row["url"] = url
    row.update(extra)
    return row


def _jpeg(size: int = 64) -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\0" * size


# --- sealed at rest ------------------------------------------------------------------------------------------------


def test_a_sealed_record_opens_only_with_its_key_and_its_place():
    key, other = os.urandom(32), os.urandom(32)
    blob = trace_seal.seal(key, b"alpha-project notes", "timeline/2026-10-23")
    assert trace_seal.open_sealed(key, blob, "timeline/2026-10-23") == b"alpha-project notes"
    with pytest.raises(trace_seal.Tampered):
        trace_seal.open_sealed(other, blob, "timeline/2026-10-23")
    with pytest.raises(trace_seal.Tampered):
        trace_seal.open_sealed(key, blob, "timeline/2026-10-22")      # moved to another day
    flipped = bytearray(blob)
    flipped[-1] ^= 1
    with pytest.raises(trace_seal.Tampered):
        trace_seal.open_sealed(key, bytes(flipped), "timeline/2026-10-23")


def test_nothing_on_disk_holds_a_title_an_address_or_recognized_text_in_the_clear(store):
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=30), title="alpha-project plan")], now=NOW)
    store.update({"browsers": ["chrome"]})
    store.add_spans([_span("span-0002", NOW - timedelta(minutes=20), bundle=CHROME, app="Chrome",
                           title="A video", url="https://www.youtube.com/watch?v=aaaaaaaaaaa&t=30")], now=NOW)
    store.add_frame({"id": "frame-0001", "at": (NOW - timedelta(minutes=10)).isoformat(), "bundle_id": EDITOR,
                     "app": "Editor", "width": 640, "height": 400}, _jpeg(), "bob-example invoice", now=NOW)
    raw = b"".join(p.read_bytes() for p in store.root.rglob("*") if p.is_file())
    for secret in (b"alpha-project", b"youtube", b"bob-example", b"Editor", EDITOR.encode()):
        assert secret not in raw
    # …and it reads back through the key.
    day = store.timeline(NOW.date())
    assert [s["title"] for s in day["spans"]] == ["alpha-project plan", "A video"]
    assert day["spans"][1]["url"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa"   # the query's content key only
    assert store.frame("frame-0001")[1] == _jpeg()


def test_a_tampered_line_is_skipped_and_counted_never_guessed(store):
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=30), title="one"),
                     _span("span-0002", NOW - timedelta(minutes=20), title="two")], now=NOW)
    path = store.root / "timeline" / f"{NOW.date().isoformat()}.log"
    lines = path.read_text().splitlines()
    lines[0] = lines[0][:-6] + ("AAAAAA" if not lines[0].endswith("AAAAAA") else "BBBBBB")
    path.write_text("\n".join(lines) + "\n")
    store._ids.clear()
    day = store.timeline(NOW.date())
    assert [s["title"] for s in day["spans"]] == ["two"] and day["unreadable"] == 1


def test_a_line_moved_to_another_days_file_fails_its_check(store):
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=30), title="one")], now=NOW)
    today = store.root / "timeline" / f"{NOW.date().isoformat()}.log"
    yesterday = store.root / "timeline" / f"{(NOW.date() - timedelta(days=1)).isoformat()}.log"
    yesterday.write_text(today.read_text())
    assert store.timeline(NOW.date() - timedelta(days=1)) | {} == {
        "day": yesterday.stem, "spans": [], "frames": [], "unreadable": 1}


def test_the_key_file_is_0600_outside_the_store_and_a_widened_key_is_refused(store, tmp_path):
    key_path = tmp_path / "home" / "traces.key"
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert store.root not in key_path.parents
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    os.chmod(key_path, 0o644)
    with pytest.raises(trace_keys.KeyRefused):
        trace_keys.FileKeyProvider(key_path).load()
    fresh = TraceStore(root=store.root, keys=trace_keys.FileKeyProvider(key_path))
    assert fresh.settings()["enabled"] is False     # a key that may have been read records nothing
    assert fresh.sweep(now=NOW).get("key_refused") is True
    assert any(store.root.rglob("*.enc"))           # …and deletes nothing on its own initiative


def test_a_key_is_never_replaced_silently(tmp_path):
    provider = trace_keys.FileKeyProvider(tmp_path / "k")
    provider.create()
    with pytest.raises(FileExistsError):
        provider.create()


# --- consent, off, pause -------------------------------------------------------------------------------------------


def test_off_by_default_and_on_only_with_the_current_consent(tmp_path):
    s = TraceStore(root=tmp_path / "traces", keys=trace_keys.FileKeyProvider(tmp_path / "traces.key"))
    assert s.settings()["enabled"] is False and not (tmp_path / "traces.key").exists()
    with pytest.raises(trace_store.TracesOff):
        s.add_spans([_span("span-0001", NOW - timedelta(minutes=5))], now=NOW)
    with pytest.raises(trace_store.PayloadError):
        s.turn_on(0)
    assert s.turn_on(trace_store.CONSENT_VERSION)["enabled"] is True


def test_turned_off_nothing_is_written(store):
    store.turn_off()
    with pytest.raises(trace_store.TracesOff):
        store.add_spans([_span("span-0001", NOW - timedelta(minutes=5))], now=NOW)
    with pytest.raises(trace_store.TracesOff):
        store.add_frame({"id": "frame-0001", "at": NOW.isoformat(), "bundle_id": EDITOR, "width": 10, "height": 10},
                        _jpeg(), now=NOW)


def test_paused_nothing_from_the_pause_on_is_kept_not_even_a_title(store):
    store.pause(trace_store.UNTIL_RESUMED, now=NOW - timedelta(minutes=10))
    result = store.add_spans([
        _span("span-0001", NOW - timedelta(minutes=14), minutes=8, title="before"),   # ends inside the pause
        _span("span-0002", NOW - timedelta(minutes=5), title="during"),
    ], now=NOW)
    assert (result.kept, result.paused) == (1, 1)
    [kept] = store.timeline(NOW.date())["spans"]
    assert kept["title"] == "before" and kept["end"] == "2026-10-23T15:10:00Z"   # cut at the pause
    with pytest.raises(trace_store.TracesOff):
        store.add_frame({"id": "frame-0001", "at": (NOW - timedelta(minutes=1)).isoformat(), "bundle_id": EDITOR,
                         "width": 10, "height": 10}, _jpeg(), now=NOW)
    store.pause(None, now=NOW)
    assert store.add_spans([_span("span-0003", NOW - timedelta(minutes=3))], now=NOW + timedelta(minutes=3)).kept == 1


def test_a_timed_pause_ends_by_itself(store):
    store.pause((NOW + timedelta(hours=1)).isoformat(), now=NOW)
    assert store.status(now=NOW + timedelta(minutes=30))["paused"] is True
    assert store.status(now=NOW + timedelta(hours=2))["paused"] is False


# --- exclusions ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bundle", ["com.1password.1password", "com.apple.Passwords", "com.bitwarden.desktop",
                                    "com.apple.loginwindow", "com.rorosaga.cicada", "com.rorosaga.cicada.verify-1"])
def test_password_managers_the_lock_screen_and_cicada_itself_are_never_recorded(store, bundle):
    result = store.add_spans([_span("span-0001", NOW - timedelta(minutes=5), bundle=bundle, title="vault")], now=NOW)
    assert (result.kept, result.excluded) == (0, 1)
    assert store.timeline(NOW.date())["spans"] == []


def test_an_excluded_app_records_nothing_not_even_its_name(store):
    store.update({"excluded_apps": ["com.example.Bank"]})
    result = store.add_spans([_span("span-0001", NOW - timedelta(minutes=5), bundle="com.example.Bank",
                                    app="Bank", title="balance")], now=NOW)
    assert (result.kept, result.excluded) == (0, 1)
    raw = b"".join(p.read_bytes() for p in store.root.rglob("*.log"))
    assert raw == b""
    with pytest.raises(trace_store.TracesOff):
        store.add_frame({"id": "frame-0001", "at": NOW.isoformat(), "bundle_id": "com.example.Bank", "width": 10,
                         "height": 10}, _jpeg(), now=NOW)


def test_an_excluded_site_or_a_private_window_drops_the_whole_moment(store):
    store.update({"browsers": ["chrome"], "excluded_sites": ["https://www.bank.example/login"]})
    assert store.settings()["excluded_sites"] == ["bank.example"]
    result = store.add_spans([
        _span("span-0001", NOW - timedelta(minutes=30), bundle=CHROME, title="Account", url="https://my.bank.example/a"),
        _span("span-0002", NOW - timedelta(minutes=20), bundle=CHROME, title="Secret", url="https://x.example/",
              private=True),
        _span("span-0003", NOW - timedelta(minutes=10), bundle=CHROME, title="Docs", url="https://docs.example/a?k=1"),
    ], now=NOW)
    assert (result.kept, result.excluded) == (1, 2)
    [kept] = store.timeline(NOW.date())["spans"]
    assert kept["url"] == "https://docs.example/a" and kept["host"] == "docs.example"


def test_chat_and_mail_keep_the_app_and_times_never_the_title_unless_turned_on(store):
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=30), bundle="com.apple.MobileSMS", app="Messages",
                           title="bob-example")], now=NOW)
    assert "title" not in store.timeline(NOW.date())["spans"][0]
    with pytest.raises(trace_store.TracesOff):   # nor its screen
        store.add_frame({"id": "frame-0001", "at": NOW.isoformat(), "bundle_id": "com.apple.MobileSMS",
                         "width": 10, "height": 10}, _jpeg(), now=NOW)
    store.update({"title_apps": ["com.apple.MobileSMS"]})
    store.add_spans([_span("span-0002", NOW - timedelta(minutes=10), bundle="com.apple.MobileSMS", app="Messages",
                           title="alpha-project group")], now=NOW)
    assert store.timeline(NOW.date())["spans"][1]["title"] == "alpha-project group"


def test_a_browser_keeps_no_address_unless_allowed_and_no_title_without_a_verified_tab(store):
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=30), bundle=CHROME, title="Something",
                           url="https://docs.example/a"),
                     _span("span-0002", NOW - timedelta(minutes=20), bundle="com.apple.Safari", title="Private?",
                           url="https://docs.example/b")], now=NOW)
    spans = store.timeline(NOW.date())["spans"]
    assert all("url" not in s and "title" not in s for s in spans)
    with pytest.raises(trace_store.TracesOff):
        store.add_frame({"id": "frame-0001", "at": NOW.isoformat(), "bundle_id": "com.apple.Safari", "width": 10,
                         "height": 10}, _jpeg(), now=NOW)


def test_titles_off_keeps_no_title_and_every_title_is_scrubbed(store):
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=30),
                           title="deploy key sk-ant-api03-" + "a" * 40)], now=NOW)
    assert "sk-ant" not in store.timeline(NOW.date())["spans"][0]["title"]
    store.update({"titles": False})
    store.add_spans([_span("span-0002", NOW - timedelta(minutes=10), title="alpha-project")], now=NOW)
    assert "title" not in store.timeline(NOW.date())["spans"][1]


def test_a_url_keeps_scheme_host_and_path_and_only_content_keys_of_the_query():
    assert trace_policy.clean_url("https://www.youtube.com/watch?v=aaaaaaaaaaa&list=x&t=3#c") == (
        "https://www.youtube.com/watch?v=aaaaaaaaaaa", "www.youtube.com")
    assert trace_policy.clean_url("https://example.com/reset?token=secret")[0] == "https://example.com/reset"
    assert trace_policy.clean_url("chrome://settings") is None and trace_policy.clean_url("file:///x") is None


def test_a_resent_span_is_kept_once_and_a_bad_row_is_refused(store):
    rows = [_span("span-0001", NOW - timedelta(minutes=30))]
    assert store.add_spans(rows, now=NOW).kept == 1
    assert store.add_spans(rows, now=NOW).duplicate == 1
    bad = [{"id": "x", "start": "now"}, _span("span-0002", NOW + timedelta(hours=1)),
           {**_span("span-0003", NOW - timedelta(minutes=5)), "start": "2026-10-23T15:00:00"}]   # naive time
    assert store.add_spans(bad, now=NOW).invalid == 3


# --- retention, forget, wipe ---------------------------------------------------------------------------------------


def test_retention_keeps_30_days_of_timeline_and_7_of_screenshots(store):
    for age in (0, 6, 7, 29, 30, 31):
        at = NOW - timedelta(days=age)
        store.add_spans([_span(f"span-age-{age:03d}", at - timedelta(minutes=10))], now=at)
        if age <= 7:
            store.add_frame({"id": f"frame-age-{age:03d}", "at": (at - timedelta(minutes=1)).isoformat(),
                             "bundle_id": EDITOR, "width": 10, "height": 10}, _jpeg(), now=at)
    store.sweep(now=NOW)
    kept_days = {(NOW.date() - timedelta(days=a)).isoformat() for a in (0, 6, 7, 29)}
    assert set(store.days()) == kept_days
    assert {p.stem for p in (store.root / "frames").glob("*.log")} == {
        (NOW.date() - timedelta(days=a)).isoformat() for a in (0, 6)}
    assert {p.name for p in (store.root / "shots").iterdir()} == {
        (NOW.date() - timedelta(days=a)).isoformat() for a in (0, 6)}


def test_the_person_may_shorten_retention_never_lengthen_it(store):
    store.update({"timeline_days": 3, "shot_days": 1})
    for age in (0, 2, 3):
        at = NOW - timedelta(days=age)
        store.add_spans([_span(f"span-age-{age:03d}", at - timedelta(minutes=10))], now=at)
    store.sweep(now=NOW)
    assert len(store.days()) == 2
    with pytest.raises(trace_store.PayloadError):
        store.update({"timeline_days": 31})
    with pytest.raises(trace_store.PayloadError):
        store.update({"shot_days": 8})


def test_the_sweep_creates_nothing_when_traces_were_never_on(tmp_path):
    s = TraceStore(root=tmp_path / "traces", keys=trace_keys.FileKeyProvider(tmp_path / "traces.key"))
    s.sweep(now=NOW)
    assert not (tmp_path / "traces").exists()


def test_forget_the_last_15_minutes_drops_every_span_reaching_into_them_and_their_screenshots(store):
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=40), minutes=10, title="kept"),
                     _span("span-0002", NOW - timedelta(minutes=20), minutes=10, title="reaches in"),
                     _span("span-0003", NOW - timedelta(minutes=5), minutes=4, title="inside")], now=NOW)
    store.add_frame({"id": "frame-0001", "at": (NOW - timedelta(minutes=30)).isoformat(), "bundle_id": EDITOR,
                     "width": 10, "height": 10}, _jpeg(), now=NOW)
    store.add_frame({"id": "frame-0002", "at": (NOW - timedelta(minutes=2)).isoformat(), "bundle_id": EDITOR,
                     "width": 10, "height": 10}, _jpeg(), "alpha-project", now=NOW)
    assert store.forget(15, now=NOW) == {"spans": 2, "frames": 1}
    assert [s["title"] for s in store.timeline(NOW.date())["spans"]] == ["kept"]
    assert store.frame("frame-0002") is None and store.frame("frame-0001") is not None
    assert not list(store.root.rglob("frame-0002*"))
    assert store.search("alpha-project") == []


def test_wipe_deletes_every_trace_and_the_key_and_turns_traces_off(store, tmp_path):
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=30), title="alpha-project")], now=NOW)
    store.add_frame({"id": "frame-0001", "at": NOW.isoformat(), "bundle_id": EDITOR, "width": 10, "height": 10},
                    _jpeg(), now=NOW)
    copy = (store.root / "timeline" / f"{NOW.date().isoformat()}.log").read_bytes()
    store.wipe()
    assert not store.root.exists() and not (tmp_path / "home" / "traces.key").exists()
    assert store.settings()["enabled"] is False
    # Crypto-shredding: a copy taken before the wipe opens with no key there is.
    again = TraceStore(root=store.root, keys=trace_keys.FileKeyProvider(tmp_path / "home" / "traces.key"))
    again.turn_on(trace_store.CONSENT_VERSION)
    key = again.keys.load()
    with pytest.raises(trace_seal.Tampered):
        trace_seal.open_line(key, copy.decode().splitlines()[0], f"timeline/{NOW.date().isoformat()}")


def test_search_reads_titles_sites_and_recognized_text_without_writing_an_index(store):
    store.update({"browsers": ["chrome"]})
    store.add_spans([_span("span-0001", NOW - timedelta(minutes=30), bundle=CHROME, title="Bridge design",
                           url="https://www.youtube.com/watch?v=aaaaaaaaaaa")], now=NOW)
    store.add_frame({"id": "frame-0001", "at": (NOW - timedelta(minutes=10)).isoformat(), "bundle_id": EDITOR,
                     "width": 10, "height": 10}, _jpeg(), "Error: alpha-project build failed", now=NOW)
    before = sorted(p.name for p in store.root.rglob("*"))
    assert [h["kind"] for h in store.search("bridge")] == ["span"]
    assert store.search("build failed")[0]["snippet"].startswith("Error: alpha-project")
    assert sorted(p.name for p in store.root.rglob("*")) == before


def test_a_screenshot_must_be_a_small_jpeg_or_png(store):
    meta = {"id": "frame-0001", "at": NOW.isoformat(), "bundle_id": EDITOR, "width": 10, "height": 10}
    with pytest.raises(trace_store.PayloadError):
        store.add_frame(meta, b"GIF89a" + b"\0" * 10, now=NOW)
    with pytest.raises(trace_store.PayloadError):
        store.add_frame({**meta, "width": 5000}, _jpeg(), now=NOW)
    with pytest.raises(trace_store.PayloadError):
        store.add_frame(meta, _jpeg(trace_store.MAX_SHOT_BYTES), now=NOW)


def test_settings_on_disk_are_sealed_and_a_tampered_settings_file_reads_as_off(store):
    path = store.root / "settings.enc"
    assert b"enabled" not in path.read_bytes()
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(bytes(data))
    assert store.settings()["enabled"] is False
    assert json.dumps(trace_store.DEFAULTS)   # defaults stay serialisable
