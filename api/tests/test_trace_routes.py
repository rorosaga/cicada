"""G218 — activity traces through the backend: This Mac only, YouTube views into the watch history, the counted day
summary behind its switch, no model and no network anywhere on the path.

Synthetic apps, titles and video ids only."""
from __future__ import annotations

import ast
import base64
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import (bank_index, demo_guard, device_tokens, episode_time, history_index, markdown_parser,
                          trace_memory, trace_store, watch_history)

ROOT = Path(__file__).resolve().parents[2]
CHROME = "com.google.Chrome"
VID = "aaaaaaaaaaa"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada-home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    c = TestClient(main.app)
    yield c, memory
    config.get_settings.cache_clear()


def _on(c, *, browsers=("chrome",), **settings):
    assert c.post("/sources/traces/on", json={"consent_version": trace_store.CONSENT_VERSION}).status_code == 200
    r = c.put("/sources/traces/settings", json={"browsers": list(browsers), **settings})
    assert r.status_code == 200, r.text
    return r.json()


def _span(sid, start: datetime, minutes=5.0, **extra):
    return {"id": sid, "start": start.isoformat(), "end": (start + timedelta(minutes=minutes)).isoformat(),
            "bundle_id": extra.pop("bundle_id", CHROME), "app": extra.pop("app", "Chrome"), **extra}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _watch_days(memory: Path) -> dict[str, markdown_parser.ParsedFile]:
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        sid = str(parsed.frontmatter.get("source_id") or "")
        if sid.startswith(("watch-history:", "traces-day:")):
            out[sid] = parsed
    return out


def _head(memory: Path) -> str:
    return subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%s%n%b"], capture_output=True, text=True,
                          check=True).stdout


def test_traces_are_off_by_default_and_a_sync_while_off_is_refused(client):
    c, _ = client
    body = c.get("/sources/traces/settings").json()
    assert body["settings"]["enabled"] is False and body["consent_version"] == trace_store.CONSENT_VERSION
    assert "com.1password.1password" in body["policy"]["never_apps"]
    assert c.post("/sources/traces/sync", json={"spans": [_span("span-0001", _now() - timedelta(minutes=9))]}
                  ).status_code == 409
    assert c.post("/sources/traces/on", json={"consent_version": 0}).status_code == 422


def test_a_youtube_view_from_traces_lands_in_the_watch_history_with_its_dwell(client):
    c, memory = client
    _on(c)
    start = _now() - timedelta(minutes=30)
    url = f"https://www.youtube.com/watch?v={VID}&t=42"
    r = c.post("/sources/traces/sync", json={"spans": [
        _span("span-0001", start, minutes=6, title="Bridge design, part one - YouTube", url=url),
        _span("span-0002", start + timedelta(minutes=6), minutes=2, bundle_id="com.example.Editor", app="Editor"),
        _span("span-0003", start + timedelta(minutes=8), minutes=4, title="Bridge design, part one - YouTube",
              url=url),
        _span("span-0004", start + timedelta(minutes=12), minutes=0.2, title="A click", url=
              "https://www.youtube.com/watch?v=bbbbbbbbbbb"),   # under MIN_WATCH: a click, not a watch
    ]})
    assert r.status_code == 200, r.text
    assert r.json()["kept"] == 4 and r.json()["promoted_files"] >= 1
    day = _watch_days(memory)[f"watch-history:youtube:{start.date().isoformat()}"]
    [row] = day.frontmatter["watched"]
    assert row["url"] == f"https://www.youtube.com/watch?v={VID}" and row["via"] == ["traces"]
    assert row["dwell_s"] == 600 and row["title"] == "Bridge design, part one"
    assert "10 min on screen" in day.body
    assert day.frontmatter["processed_by"] == history_index.INDEXED_BY       # index-only, like every watched day
    assert "capture/traces" in _head(memory)
    # Ask's existing engine-free lookup answers the time-of-day question from it.
    lines = watch_history.lookup(memory, "what was the bridge design video I watched")
    clock = start.astimezone().strftime("%H:%M")
    assert any("Bridge design, part one" in line and clock in line for line in lines), lines
    # The owner's own question: a time of day, no title, no "watch" verb — the day's watches, nearest first.
    asked = watch_history.lookup(memory, f"what was that video at {clock}", today=start.astimezone().date())
    assert asked[0].startswith(f"Watched on {start.astimezone().date().isoformat()}") and f"nearest to {clock}" in asked[0]
    assert "Bridge design, part one" in asked[1] and "not near" not in asked[1]


def test_a_time_of_day_question_ranks_that_days_watches_by_distance(tmp_path):
    from datetime import date

    from api.services.watch_history import Watch, asked_moment, record

    memory = _bank(tmp_path)
    day = date(2026, 10, 21)
    record(memory, [Watch("youtube", "https://www.youtube.com/watch?v=aaaaaaaaaaa", day,
                          datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc), "Morning talk", door="traces"),
                    Watch("youtube", "https://www.youtube.com/watch?v=bbbbbbbbbbb", day,
                          datetime(2026, 10, 21, 15, 18, tzinfo=timezone.utc), "Afternoon talk", door="traces")])
    today = date(2026, 10, 22)
    assert asked_moment("what was that video at 3:20 pm yesterday", today) == (day, 15 * 60 + 20)
    assert asked_moment("what did I watch on Wednesday", today) == (day, None)
    assert asked_moment("what did I watch since 2026-10-01", today) is not None   # a range: lookup's own guard
    lines = watch_history.lookup(memory, "what was that video at 15:20 yesterday", today=today)
    assert "Afternoon talk" in lines[1] and "Morning talk" in lines[2] and "not near" in lines[2]
    assert watch_history.lookup(memory, "what did I watch on 2026-10-20", today=today) == [
        "No watched video is recorded on 2026-10-20 (Tuesday)."]
    assert not watch_history.is_about_watching("which video call app do we use")   # a bare "video" still is not


def test_with_the_switch_off_youtube_views_stay_in_traces(client):
    c, memory = client
    _on(c, youtube_to_watch_history=False)
    c.post("/sources/traces/sync", json={"spans": [
        _span("span-0001", _now() - timedelta(minutes=20), url=f"https://www.youtube.com/watch?v={VID}")]})
    assert _watch_days(memory) == {}


def test_a_demo_bank_receives_nothing_but_the_trace_is_kept_outside_it(client):
    c, memory = client
    demo_guard.write_manifest(memory)
    _on(c)
    start = _now() - timedelta(minutes=20)
    r = c.post("/sources/traces/sync", json={"spans": [
        _span("span-0001", start, url=f"https://www.youtube.com/watch?v={VID}")]})
    assert r.status_code == 200 and r.json()["kept"] == 1 and r.json()["promoted_files"] == 0
    assert _watch_days(memory) == {}


def test_the_day_summary_is_counted_index_only_and_never_a_mention(client):
    c, memory = client
    _on(c, daily_summary=True)
    yesterday = (_now() - timedelta(days=1, minutes=20)).replace(hour=10, minute=0, second=0)
    c.post("/sources/traces/sync", json={"spans": [
        _span("span-0001", yesterday, minutes=40, bundle_id="com.example.Editor", app="Editor",
              title="alpha-project plan"),
        _span("span-0002", yesterday + timedelta(minutes=40), minutes=20, url="https://docs.example/a",
              title="Reference")]})
    summary = _watch_days(memory)[f"traces-day:{yesterday.date().isoformat()}"]
    assert "Editor — 40 min" in summary.body and "docs.example — 20 min" in summary.body
    assert "alpha-project plan" in summary.body          # behind the switch, a title the store kept
    assert history_index.kind(summary.frontmatter) == "traces"
    assert summary.frontmatter["processed_by"] == history_index.INDEXED_BY
    assert not history_index.waits_for_model(summary.frontmatter)
    assert not episode_time.counts_as_activity(summary.frontmatter)
    assert summary.frontmatter["evidence_kind"] == "assistant"   # never the person's own words


def test_learn_from_traces_queues_the_summary_for_sleep_and_nothing_else(client):
    c, memory = client
    _on(c, daily_summary=True, learn_from_summary=True)
    yesterday = (_now() - timedelta(days=1, minutes=20)).replace(hour=10, minute=0, second=0)
    c.post("/sources/traces/sync", json={"spans": [
        _span("span-0001", yesterday, minutes=40, bundle_id="com.example.Editor", app="Editor")]})
    summary = _watch_days(memory)[f"traces-day:{yesterday.date().isoformat()}"]
    assert history_index.kind(summary.frontmatter) is None and history_index.waits_for_model(summary.frontmatter)


def test_without_the_summary_switch_nothing_but_youtube_reaches_the_bank(client):
    c, memory = client
    _on(c)
    yesterday = _now() - timedelta(days=1, minutes=20)
    c.post("/sources/traces/sync", json={"spans": [
        _span("span-0001", yesterday, minutes=40, bundle_id="com.example.Editor", app="Editor", title="alpha")]})
    assert _watch_days(memory) == {}
    tracked = subprocess.run(["git", "-C", str(memory), "ls-files"], capture_output=True, text=True).stdout
    assert "trace" not in tracked


def test_another_device_can_neither_read_nor_send_traces(client, monkeypatch):
    c, _ = client
    _on(c)
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    _, token = device_tokens.store().create("laptop-example")
    headers = {"Authorization": f"Bearer {token}"}
    for method, path, body in [("GET", "/sources/traces/settings", None), ("GET", "/sources/traces/days", None),
                               ("POST", "/sources/traces/sync", {"spans": []}),
                               ("POST", "/sources/traces/search", {"query": "x"}),
                               ("GET", "/sources/traces/timeline?day=2026-10-23", None),
                               ("GET", "/sources/traces/frames/frame-0001", None),
                               ("POST", "/sources/traces/wipe", {"confirm": True})]:
        r = c.request(method, path, json=body, headers=headers)
        assert r.status_code == 403, (path, r.status_code)


def test_screenshots_round_trip_and_search_is_a_post(client):
    c, _ = client
    _on(c)
    at = _now() - timedelta(minutes=2)
    image = b"\xff\xd8\xff\xe0" + b"\0" * 100
    r = c.post("/sources/traces/frames", json={
        "id": "frame-0001", "at": at.isoformat(), "bundle_id": "com.example.Editor", "app": "Editor",
        "width": 640, "height": 400, "image": base64.b64encode(image).decode(), "text": "alpha-project error 42"})
    assert r.status_code == 200, r.text
    got = c.get("/sources/traces/frames/frame-0001")
    assert got.content == image and got.headers["cache-control"] == "no-store"
    assert c.get("/sources/traces/frames/frame-0001/text").json()["text"] == "alpha-project error 42"
    assert c.post("/sources/traces/search", json={"query": "error 42"}).json()["hits"][0]["id"] == "frame-0001"
    assert c.get("/sources/traces/search?query=x").status_code == 405


def test_wipe_needs_a_confirmation_then_everything_is_gone(client, tmp_path):
    c, _ = client
    _on(c)
    assert c.post("/sources/traces/wipe", json={}).status_code == 422
    body = c.post("/sources/traces/wipe", json={"confirm": True}).json()
    assert body["settings"]["enabled"] is False
    assert not (tmp_path / "cicada-home" / "traces").exists()
    assert not (tmp_path / "cicada-home" / "traces.key").exists()


# --- no network, no model, no ledger -------------------------------------------------------------------------------

TRACE_MODULES = ["api/services/trace_store.py", "api/services/trace_keys.py", "api/services/trace_seal.py",
                 "api/services/trace_policy.py", "api/services/trace_memory.py", "api/routers/traces.py"]
#: Modules that reach the network, run a model or write the telemetry ledger (``urllib.parse`` is parsing, allowed).
NETWORK = {"urllib.request", "http.client", "http.server", "httpx", "requests", "socket", "ssl", "aiohttp",
           "websockets", "litellm", "subprocess", "asyncio.subprocess"}
CICADA_SERVICES = {"net_guard", "telemetry", "llm_engine", "agent_engine", "codex_engine", "embed_worker", "providers",
                   "engine_select", "link_enrichment", "source_check"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod)
            names.update(f"{mod}.{a.name}" if mod else a.name for a in node.names)
            names.update(a.name for a in node.names)
    return names


@pytest.mark.parametrize("rel", TRACE_MODULES)
def test_the_traces_path_imports_no_network_no_model_and_no_ledger(rel):
    names = _imports(ROOT / rel)
    bad = {n for n in names if n in NETWORK or n.split(".")[0] in NETWORK}
    bad |= {n for n in names if n.split(".")[-1] in CICADA_SERVICES}
    assert not bad, (rel, sorted(bad))


def test_no_agent_door_reads_the_traces_store():
    """No MCP tool, no Ask, no remote listener, no /v1 reads traces in v1 (G218): only routers/traces.py and the
    promotion do, and the store is imported by nothing else.

    The scan reads the repository's own tracked Python sources under ``api/`` and ``mcp/`` (the MCP server) — never a
    virtualenv, ``__pycache__`` or anything else a checkout happens to hold (CI keeps its venv at ``api/.venv``)."""
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "api", "mcp"], capture_output=True,
                            check=True).stdout.decode("utf-8").split("\0")
    sources = [ROOT / rel for rel in listed if rel.endswith(".py")]
    assert any(p.name == "mcp_tools.py" for p in sources) and any(p.parent.name == "remote" for p in sources)
    readers = set()
    for path in sources:
        if "tests" in path.parts or path.name.startswith("trace_") or path.name == "traces.py" or not path.is_file():
            continue
        if {"trace_store", "trace_memory", "trace_keys", "trace_seal"} & {n.split(".")[-1] for n in _imports(path)}:
            readers.add(path.relative_to(ROOT).as_posix())
    assert readers == {"api/main.py"}, readers   # main.py: the router include and the retention sweep only


def test_the_traces_body_limits_are_bounded():
    from api.services import request_limits

    assert request_limits.BODY_LIMITS["/sources/traces/sync"] <= 4 * 1024 * 1024
    assert request_limits.BODY_LIMITS["/sources/traces/frames"] <= 4 * 1024 * 1024


def test_a_youtube_span_shorter_than_a_watch_is_not_promoted(tmp_path):
    s = trace_store.TraceStore(root=tmp_path / "t", keys=trace_store.trace_keys.FileKeyProvider(tmp_path / "k"))
    s.turn_on(trace_store.CONSENT_VERSION)
    s.update({"browsers": ["chrome"]})
    start = _now() - timedelta(minutes=5)
    result = s.add_spans([_span("span-0001", start, minutes=0.25, url=f"https://youtu.be/{VID}")])
    assert trace_memory.youtube_watches(s, result.pages) == []


# --- review of #456, B1: nothing forget can reach is ever in the bank or git ---------------------------------------


def _log(memory: Path) -> str:
    return subprocess.run(["git", "-C", str(memory), "log", "--format=%H"], capture_output=True, text=True).stdout


def test_a_watch_forgotten_within_15_minutes_never_reaches_the_bank_or_git(client):
    c, memory = client
    _on(c)
    before = _log(memory)
    start = _now() - timedelta(minutes=8)
    r = c.post("/sources/traces/sync", json={"spans": [
        _span("span-0001", start, minutes=6, title="Bridge design - YouTube",
              url=f"https://www.youtube.com/watch?v={VID}")]})
    assert r.json()["kept"] == 1 and r.json()["promoted_files"] == 0    # held: younger than the forget window
    assert c.post("/sources/traces/forget", json={"minutes": 15}).json()["spans"] == 1
    c.post("/sources/traces/sync", json={"spans": []})
    assert _watch_days(memory) == {}
    assert _log(memory) == before
    grep = subprocess.run(["git", "-C", str(memory), "grep", "-l", VID], capture_output=True, text=True).stdout
    assert grep == ""


def test_a_watch_is_promoted_once_it_is_older_than_the_forget_window(tmp_path):
    memory = _bank(tmp_path)
    s = trace_store.TraceStore(root=tmp_path / "t", keys=trace_store.trace_keys.FileKeyProvider(tmp_path / "k"))
    now = _now()
    s.turn_on(trace_store.CONSENT_VERSION, now=now - timedelta(hours=1))
    s.update({"browsers": ["chrome"]})
    s.add_spans([_span("span-0001", now - timedelta(minutes=10), minutes=6,
                       url=f"https://www.youtube.com/watch?v={VID}")], now=now)
    assert trace_memory.promote(memory, s, s.settings(), now=now) == []
    later = now + trace_store.PROMOTE_HOLD
    assert trace_memory.promote(memory, s, s.settings(), now=later)
    assert _watch_days(memory)
    assert trace_memory.promote(memory, s, s.settings(), now=later + timedelta(minutes=1)) == []   # once


def test_yesterdays_summary_waits_until_its_last_moments_are_past_the_forget_window(tmp_path):
    memory = _bank(tmp_path)
    s = trace_store.TraceStore(root=tmp_path / "t", keys=trace_store.trace_keys.FileKeyProvider(tmp_path / "k"))
    midnight = datetime.combine(_now().date(), datetime.min.time(), tzinfo=timezone.utc)
    s.turn_on(trace_store.CONSENT_VERSION, now=midnight - timedelta(hours=2))
    s.update({"daily_summary": True})
    s.add_spans([_span("span-0001", midnight - timedelta(minutes=50), minutes=45, bundle_id="com.example.Editor",
                       app="Editor")], now=midnight - timedelta(minutes=1))
    assert trace_memory.promote(memory, s, s.settings(), now=midnight + timedelta(minutes=5)) == []
    assert trace_memory.promote(memory, s, s.settings(), now=midnight + timedelta(minutes=20))
