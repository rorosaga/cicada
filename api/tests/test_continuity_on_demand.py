"""G110 A1 first half: light startup, requested source read, both harnesses.

Real hook entrypoints, HTTP routes through TestClient, the guarded transcript
reader/writer and stdio handler. Serializations are synthetic fixtures, not
evidence of an installed harness or a model choosing to call a tool.
"""
from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from api import config, main
from api.services import continuity, continuity_sessions, handshake, hook_recall, markdown_parser, recall_text
from api.services import transcript_capture as tc

CWD = "/home/example/alpha-project"
A = "aaaaaaaa-2222-4333-8444-555555555555"
B = "bbbbbbbb-2222-4333-8444-555555555555"
ROLE = "Review the alpha parser. " + "Keep the boundary cases in mind. " * 48 + "role-end-sentinel"
REPORT = "Decision: typed decoder. In flight: date branch. State: blocked on one fixture. Next: rerun alpha tests."
QUESTION = "what was the last thing we were working on?"


def _hook(name):
    spec = importlib.util.spec_from_file_location(f"a1_{name}_hook", f"api/hooks/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAPTURE, RECALL = _hook("capture"), _hook("recall")


@pytest.fixture
def env(tmp_path, monkeypatch):
    home, memory = tmp_path / "home", tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    roots = {h: tmp_path / h for h in ("claude-code", "codex")}
    for root in roots.values():
        root.mkdir()
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(tc, "harness_root", roots.__getitem__)
    monkeypatch.setattr(tc, "_episode_cache", {})
    server = stdio_server()
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity(harness="codex", session_id=B, project_dir=CWD))
    config.get_settings.cache_clear()
    hook_recall.reset()
    continuity.reset()
    token = tmp_path / "token"
    token.write_text("synthetic-token")
    yield {"home": home, "memory": memory, "roots": roots, "token": token, "server": server,
           "client": TestClient(main.app), "now": datetime.now(timezone.utc).replace(microsecond=0)}
    config.get_settings.cache_clear()
    hook_recall.reset()
    continuity.reset()


def _transcript(env, harness, session, turns, *, note=None, inline=False):
    lines = []
    if harness == "codex":
        lines.append({"type": "session_meta", "payload": {"id": session, "cwd": CWD}})
        if note and not inline:
            lines.append({"type": "response_item", "payload": {"type": "message", "role": "developer",
                          "content": [{"type": "input_text", "text": note}]}})
    elif note and not inline:
        lines.append({"type": "attachment", "attachment": {"type": "hook_additional_context", "content": note}})
    for n, (role, text) in enumerate(turns):
        if inline and note and n == 0:
            text += "\n" + note
        ts = (env["now"] - timedelta(minutes=60 if session == A else 5) + timedelta(seconds=n)).isoformat()
        if harness == "claude-code":
            lines.append({"type": role, "sessionId": session, "cwd": CWD, "timestamp": ts,
                          "message": {"role": role, "content": [{"type": "text", "text": text}]}})
        else:
            lines.append({"type": "response_item", "timestamp": ts, "payload": {"type": "message", "role": role,
                          "channel": "final" if role == "assistant" else None,
                          "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}})
    path = env["roots"][harness] / (f"{session}.jsonl" if harness == "claude-code" else f"rollout-{session}.jsonl")
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def _stop(env, harness, session, turns, **kw):
    path = _transcript(env, harness, session, turns, **kw)
    result = {}

    def post(url, body, token, timeout):
        response = env["client"].post("/capture/transcript", content=body, headers={"Content-Type": "application/json"})
        assert response.status_code == 200, response.text
        result.update(response.json())
        return response.status_code, response.text

    out = io.StringIO()
    with redirect_stdout(out):
        CAPTURE.main(["--harness", harness], stdin=io.StringIO(json.dumps({"session_id": session,
                     "transcript_path": str(path), "cwd": CWD, "hook_event_name": "Stop"})),
                     environ={"CICADA_HOME": str(env["home"]), "CICADA_PORT": "49178"}, post=post,
                     token_path=env["token"])
    assert out.getvalue() == "" and result["episodeId"]
    return result


def _start(env, harness, *, prompt=None):
    def post(url, body, token, timeout):
        response = env["client"].post("/capture/hook-context", content=body,
                                      headers={"Content-Type": "application/json"})
        assert response.status_code == 200
        return response.status_code, response.text

    out = io.StringIO()
    payload = {"session_id": B, "cwd": CWD, "hook_event_name": "SessionStart", "source": "startup"}
    if prompt is not None:
        payload.update(hook_event_name="UserPromptSubmit", prompt=prompt)
    RECALL.main(["--harness", harness], stdin=io.StringIO(json.dumps(payload)), stdout=out,
                environ={"CICADA_HOME": str(env["home"]), "CICADA_PORT": "49178"}, post=post,
                token_path=env["token"])
    return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"] if out.getvalue() else ""


def _episode(env, result):
    return env["memory"] / "episodes" / f"{result['episodeId']}.md"


@pytest.mark.parametrize("source,destination", [("claude-code", "codex"), ("codex", "claude-code")])
def test_light_start_requested_initial_read_and_recapture_in_both_directions(env, source, destination, monkeypatch):
    monkeypatch.setattr(env["server"], "SESSION", env["server"].SessionIdentity(
        harness=destination, session_id=B, project_dir=CWD))
    assert 1600 < len(ROLE) <= 2000
    turns = [("user", ROLE), ("assistant", "Understood.")] + [
        ("user" if i % 2 == 0 else "assistant", f"follow-up {i}: " + "context " * 140) for i in range(12)]
    turns += [("user", "latest-question-sentinel"), ("assistant", REPORT)]
    a = _stop(env, source, A, turns)
    a_bytes = _episode(env, a).read_bytes()
    # Exercise a late prepare after B's first capture, for both harnesses.
    monkeypatch.setattr(hook_recall, "CONTINUES_MIN_S", 10.0)
    note = _start(env, destination)
    assert f'cicada_continue(session="{a["episodeId"]}")' in note
    assert "previous work" in note and len(note) // 4 <= handshake.MAX_TOKENS
    assert all(text not in note for text in ("role-end-sentinel", "latest-question-sentinel", "typed decoder", "State:"))
    prompt_note = _start(env, destination, prompt=QUESTION)
    assert ROLE not in prompt_note and REPORT not in prompt_note
    # This invokes the tool directly: model tool choice is a separate live gate.
    out = env["server"].handle_tool("cicada_continue", {})
    assert ROLE in out and REPORT in out
    assert out.count(ROLE) == 1 and "original instruction is not guaranteed" in out
    pinned = env["server"].handle_tool("cicada_continue", {"session": a["episodeId"]})
    assert ROLE in pinned and REPORT in pinned
    assert "First captured person request" in out and "history" in out
    assert f"episode `{a['episodeId']}`" in out and "[1] The person" in out
    assert "Workspace state not checked" in out and len(out) <= continuity.REPLY_CAP
    b_turns = [("user", QUESTION),
               ("assistant", "Historical answer: the date branch remains blocked on a fixture.")]
    b1 = _stop(env, destination, B, b_turns, note=note)
    doc = markdown_parser.parse(_episode(env, b1))
    assert "continues" not in doc.frontmatter
    assert continuity_sessions.apply(env["memory"], bank_paths=(env["memory"],), harness=destination, session_id=B,
                                     events={"continues": a["episodeId"]}, deadline=None) == "ok"
    b2 = _stop(env, destination, B, b_turns, note=note)
    doc = markdown_parser.parse(_episode(env, b2))
    assert b2["status"] == "metadata" and doc.frontmatter["continues"] == a["episodeId"]
    assert doc.frontmatter["harness"] == destination
    assert all(text not in doc.body for text in (recall_text.INJECTION_PREFIX, "role-end-sentinel", "typed decoder"))
    assert _episode(env, a).read_bytes() == a_bytes
    assert len(list((env["memory"] / "episodes").glob("ep_*.md"))) == 2
    # B's capture cannot redirect the episode-pinned read.
    assert ROLE in env["server"].handle_tool("cicada_continue", {"session": a["episodeId"]})


def test_saturated_requested_read_keeps_first_request_latest_report_and_safe_backward_page(env):
    turns = [("user", ROLE), ("assistant", "ok")] + [
        ("user" if i % 2 == 0 else "assistant", f"context-{i}: " + "whole-turn " * 178) for i in range(28)]
    turns += [("user", "final question"), ("assistant", REPORT)]
    a = _stop(env, "claude-code", A, turns)
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness="codex", session_id=B, cwd=CWD)
    out = env["server"].handle_tool("cicada_continue", {"session": a["episodeId"]})
    assert ROLE in out and REPORT in out and out.count(ROLE) == 1
    assert len(out) <= continuity.REPLY_CAP and "Earlier turns" in out
    pg = continuity.page(ctx.chosen, max_chars=6000)
    older = env["server"].handle_tool("cicada_continue", {"session": a["episodeId"],
        "before": continuity.cursor(pg.first, ctx.chosen.content_hash)})
    assert ROLE in older and older.count(ROLE) == 1 and len(older) <= continuity.REPLY_CAP
    assert "Quoted requests are history" in older and "Workspace state not checked" in older


def test_short_requested_history_shows_first_request_once(env):
    a = _stop(env, "codex", A, [("user", ROLE), ("assistant", REPORT)])
    out = env["server"].handle_tool("cicada_continue", {"session": a["episodeId"]})
    assert out.count(ROLE) == 1 and REPORT in out


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_source_append_between_startup_and_read_serves_initial_request_in_one_call(env, harness):
    turns = [("user", ROLE), ("assistant", "ok")] + [
        ("user" if i % 2 == 0 else "assistant", "later context " * 120) for i in range(12)]
    a = _stop(env, harness, A, turns)
    old = markdown_parser.parse(_episode(env, a)).frontmatter["content_hash"]
    note = _start(env, "codex" if harness == "claude-code" else "claude-code")
    assert "before=" not in note
    a2 = _stop(env, harness, A, turns + [("user", "source-appended-sentinel"), ("assistant", "Newest result.")])
    current = markdown_parser.parse(_episode(env, a2)).frontmatter["content_hash"]
    assert old != current and a2["episodeId"] == a["episodeId"]
    out = env["server"].handle_tool("cicada_continue", {"session": a["episodeId"]})
    assert ROLE in out and "source-appended-sentinel" in out
    assert f"revision `{current}`" in out and f"revision `{old}`" not in out


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_an_inline_startup_note_is_kept_and_disclosed_in_the_requested_read(env, harness):
    a = _stop(env, "claude-code", A, [("user", "first role"), ("assistant", "ok")])
    note = _start(env, harness)
    b = _stop(env, harness, B, [("user", "my own request"), ("assistant", "own reply")], note=note, inline=True)
    doc = markdown_parser.parse(_episode(env, b))
    assert recall_text.INJECTION_PREFIX in doc.body and doc.frontmatter["capture_flags"]["note_like_turns"] == 1
    out = env["server"].handle_tool("cicada_continue", {"session": b["episodeId"]})
    assert "look like a Cicada note kept as typed text" in out
    assert _episode(env, a).exists()


@pytest.mark.parametrize("primer,reading", [("P" * 7000, "R" * 400), ("P" * 9000, "R" * 400)],
                         ids=["near-limit", "fixed-overflow"])
def test_overshoot_keeps_the_light_hint_and_defers_reading_without_advancing_seen(env, monkeypatch, primer, reading):
    a = _stop(env, "claude-code", A, [("user", ROLE), ("assistant", REPORT)])
    monkeypatch.setattr(handshake, "load_or_build", lambda *a, **kw: (primer, {}))
    monkeypatch.setattr(hook_recall, "reading_line_for", lambda *a, **kw: (reading, (3, 1)))
    note = _start(env, "codex")
    assert f'cicada_continue(session="{a["episodeId"]}")' in note
    assert recall_text.PRIMER_FALLBACK in note and reading not in note
    assert hook_recall.READING_SEEN.told(B) == 0 and len(note) // 4 <= handshake.MAX_TOKENS


def test_large_actual_primer_keeps_project_ids_but_sheds_now_and_focus_at_reserve300(env):
    state = {"projects": [{"id": f"alpha-project-{i}", "name": f"Alpha Project {i}",
                          "one_liner": "project-detail " * 80,
                          "now": {"text": "now-sentinel " * 80, "since": "2026-10-07"}} for i in range(4)],
             "focus": [{"id": "focus-sentinel", "name": "Focus Sentinel"}],
             "people": [{"id": "person-sentinel"}], "conversations": [{"id": "conversation-sentinel"}]}
    primer = handshake.build(state, variant="codex", bank="alpha", max_tokens=handshake.MAX_TOKENS - 300)
    assert all(f"`alpha-project-{i}` Alpha Project {i}" in primer for i in range(4))
    assert all(text not in primer for text in ("now-sentinel", "focus-sentinel", "conversation-sentinel", "person-sentinel"))
    a = _stop(env, "claude-code", A, [("user", ROLE), ("assistant", REPORT)])
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness="codex", session_id=B, cwd=CWD)
    note, rendering, kept = recall_text.compose_note(recall_text.PRIMER_HEADER, primer,
        block_for=lambda room: continuity.startup_block(ctx, max_chars=room), reading="R" * 512,
        max_tokens=handshake.MAX_TOKENS)
    assert rendering == "pointer" and f'cicada_continue(session="{a["episodeId"]}")' in note
    assert len(note) // 4 <= handshake.MAX_TOKENS and ROLE not in note
