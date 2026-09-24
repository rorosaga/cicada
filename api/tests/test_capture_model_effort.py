"""Round 4 D1 / C1 (G49 lifted for harness writes): the capture path keeps each
agent turn's model id and reasoning effort — two keys, nothing else of the line —
in the episode's `turns` sidecar, outside `content_hash`. Synthetic transcripts
only: the real key names, placeholder content; no real transcript is read."""
from __future__ import annotations

import io
import json

import pytest

from api.hooks import capture as hook
from api.services import episode_staging, markdown_parser, transcript_capture as tc, transcript_extract as tx

SID = "66666666-7777-4888-8999-aaaaaaaaaaaa"
CSID = "77777777-8888-4999-8aaa-bbbbbbbbbbbb"
SENTINEL = "SENTINEL-never-read"


def _user(text, ts="2026-09-24T10:00:00.000Z"):
    return json.dumps({"type": "user", "uuid": "u", "timestamp": ts, "sessionId": SID,
                       "cwd": "/home/example/alpha-project", "message": {"role": "user", "content": text}})


def _asst(text, *, model=None, effort=None, ts="2026-09-24T10:00:05.000Z", blocks=None, **top):
    msg = {"role": "assistant", "content": blocks or [{"type": "text", "text": text}], "usage": {"note": SENTINEL}}
    if model is not None:
        msg["model"] = model
    line = {"type": "assistant", "uuid": "a", "timestamp": ts, "sessionId": SID,
            "cwd": "/home/example/alpha-project", "message": msg, **top}
    if effort is not None:
        line["effort"] = effort
    return json.dumps(line)


def _cx(typ, payload, ts="2026-09-24T10:00:00.000Z"):
    return json.dumps({"timestamp": ts, "type": typ, "payload": payload})


def _cx_msg(role, text, ts="2026-09-24T10:00:01.000Z"):
    kind = "input_text" if role == "user" else "output_text"
    return _cx("response_item", {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}, ts)


# --- the extractor -------------------------------------------------------------


def test_a_claude_reply_carries_its_model_and_effort_and_a_person_never_does():
    person, reply = tx.extract_claude_code([
        _user("Which index does alpha-project use?"),
        _asst("sqlite-vec.", model="claude-opus-5-5", effort="XHIGH"),
    ]).turns
    assert (person.model, person.effort) == (None, None)
    assert (reply.model, reply.effort) == ("claude-opus-5-5", "xhigh")  # lower-cased (R4B-2)


def test_the_final_replys_line_decides_not_narration_before_a_tool():
    conv = tx.extract_claude_code([
        _user("Check alpha-project."),
        _asst("Let me look.", model="claude-haiku-5", effort="low"),
        _asst("", blocks=[{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}],
              model="claude-haiku-5", effort="low"),
        json.dumps({"type": "user", "uuid": "r", "timestamp": "2026-09-24T10:00:06.000Z", "sessionId": SID,
                    "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                             "content": "ok"}]}}),
        _asst("All good.", model="claude-opus-5-5", effort="high"),
    ])
    assert (conv.turns[-1].model, conv.turns[-1].effort) == ("claude-opus-5-5", "high")


def test_an_unknown_effort_and_a_synthetic_model_are_dropped_never_guessed():
    reply = tx.extract_claude_code([_user("Q"), _asst("A", model="<synthetic>", effort="turbo")]).turns[-1]
    assert (reply.model, reply.effort) == (None, None)


def test_nothing_else_of_an_agent_line_is_read():
    conv = tx.extract_claude_code([
        _user("Q"),
        _asst("", blocks=[{"type": "thinking", "thinking": SENTINEL}], model="claude-opus-5-5"),
        _asst("A", model="claude-opus-5-5", effort="high", reasoning={"text": SENTINEL}),
    ])
    assert SENTINEL not in repr(conv)


def test_codex_turn_context_names_the_model_for_the_turns_that_follow():
    conv = tx.extract_codex([
        _cx("session_meta", {"id": CSID, "cwd": "/home/example/alpha-project"}),
        _cx("turn_context", {"cwd": "/home/example/alpha-project", "model": "gpt-5.5-codex", "effort": "high",
                             "user_instructions": SENTINEL, "summary": "auto"}),
        _cx_msg("user", "Plan alpha-project"),
        _cx("response_item", {"type": "reasoning", "summary": [{"type": "summary_text", "text": SENTINEL}]}),
        _cx_msg("assistant", "Plan drafted."),
        _cx("turn_context", {"model": "gpt-5.5-codex-mini", "effort": "LOW"}),
        _cx_msg("user", "Shorter please"),
        _cx_msg("assistant", "Done."),
    ])
    assert [(t.role, t.model, t.effort) for t in conv.turns] == [
        ("user", None, None), ("assistant", "gpt-5.5-codex", "high"),
        ("user", None, None), ("assistant", "gpt-5.5-codex-mini", "low")]
    assert SENTINEL not in repr(conv)
    assert conv.summary["dropped_messages"]["other_type"] == 2  # turn_context still counts as before


# --- the writer ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_episode_cache(monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    folder = tmp_path / "claude-projects" / "-home-example-alpha-project"
    folder.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: folder.parent)
    return folder / f"{SID}.jsonl"


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


def _capture(memory, transcript, lines, *, effort=None):
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                              cwd="/home/example/alpha-project", keep_assistant=True, effort=effort)
    assert r.status in ("created", "updated"), r
    parsed = markdown_parser.parse(memory / "episodes" / f"{r.episode_id}.md")
    return dict(parsed.frontmatter), parsed.body


def test_agent_entries_carry_them_in_contract_order_outside_the_hash(memory, transcript):
    fm, body = _capture(memory, transcript, [_user("Q1"), _asst("A1", model="claude-opus-5-5", effort="xhigh")])
    person, reply = fm["turns"]
    assert tuple(person) == episode_staging.TURN_STAMP_REQUIRED
    assert tuple(reply) == episode_staging.TURN_STAMP_KEYS
    assert (reply["model"], reply["effort"]) == ("claude-opus-5-5", "xhigh")
    assert fm["content_hash"] == episode_staging.content_hash(body)  # the body alone (C1)


def test_the_hooks_effort_fills_the_last_reply_only_when_the_transcript_is_silent(memory, transcript):
    fm, _ = _capture(memory, transcript, [_user("Q1"), _asst("A1", model="claude-opus-5-5")], effort="max")
    assert fm["turns"][-1]["effort"] == "max"


def test_the_transcripts_own_effort_wins(memory, transcript):
    fm, _ = _capture(memory, transcript, [_user("Q1"), _asst("A1", effort="high")], effort="low")
    assert fm["turns"][-1]["effort"] == "high"


def test_a_hook_effort_with_no_reply_in_the_body_lands_nowhere(memory, transcript):
    fm, _ = _capture(memory, transcript, [_user("Q1"), _asst("A1", model="claude-opus-5-5"),
                                          _user("Q2", ts="2026-09-24T10:01:00.000Z")], effort="max")
    assert all("effort" not in e for e in fm["turns"])


def test_a_later_stop_keeps_what_the_hook_said_about_an_earlier_reply(memory, transcript):
    _capture(memory, transcript, [_user("Q1"), _asst("A1", model="claude-opus-5-5")], effort="max")
    fm, _ = _capture(memory, transcript, [
        _user("Q1"), _asst("A1", model="claude-opus-5-5"),
        _user("Q2", ts="2026-09-24T10:02:00.000Z"),
        _asst("A2", model="claude-opus-5-5", ts="2026-09-24T10:02:05.000Z")])
    assert [e.get("effort") for e in fm["turns"]] == [None, "max", None, None]


# --- the hook and the route -------------------------------------------------------


def _hook_body(tmp_path, payload):
    token = tmp_path / "api_token"
    token.write_text("tok")
    calls = []

    def post(url, body, tok, timeout):
        calls.append(json.loads(body))
        return 200, '{"status":"updated"}'

    assert hook.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ={}, post=post,
                     log_path=tmp_path / "capture.log", token_path=token) == 0
    return calls[0]


def test_the_hook_forwards_effort_level_and_nothing_else_new(tmp_path):
    base = {"session_id": SID, "transcript_path": f"/home/example/.claude/projects/x/{SID}.jsonl",
            "cwd": "/home/example/alpha-project", "hook_event_name": "Stop"}
    body = _hook_body(tmp_path, {**base, "effort": {"level": "xhigh"}, "model": {"id": SENTINEL}})
    assert body["effort"] == "xhigh" and SENTINEL not in json.dumps(body)
    assert "effort" not in _hook_body(tmp_path, base)


def test_the_route_passes_the_hooks_effort_through(memory, transcript, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        transcript.write_text("\n".join([_user("Q1"), _asst("A1", model="claude-opus-5-5")]) + "\n",
                              encoding="utf-8")
        client = TestClient(main.app)
        req = {"harness": "claude-code", "session_id": SID, "transcript_path": str(transcript)}
        r = client.post("/capture/transcript", json={**req, "effort": "medium"})
        assert r.status_code == 200, r.text
        fm = markdown_parser.parse(memory / "episodes" / f"{r.json()['episodeId']}.md").frontmatter
        assert fm["turns"][-1]["effort"] == "medium"
        assert client.post("/capture/transcript", json={**req, "effort": "x" * 40}).status_code == 422
    finally:
        config.get_settings.cache_clear()
