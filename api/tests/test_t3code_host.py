"""G228: T3 Code is a host, not a harness. Its threads are captured by the harness it drives (Claude Code, Codex,
Cursor) through Cicada's existing hooks — one episode per harness session — with ``host: t3code`` as a label read by
the hook from its own ancestors; what T3 Code itself writes into a turn (a handoff's replay, its instructions) is
never kept as the person's words. Synthetic fixtures shaped from T3 Code's source (commit 3748c5c2); unverified
against a running T3 Code."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.hooks import capture as hook
from api.services import agent_catalog, agent_live, markdown_parser, source_overview
from api.services import transcript_capture as tc
from api.services import transcript_extract as tx
from api.services import turn_capture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
import host_identity  # noqa: E402 — the hook's own stdlib module, imported the way the hook imports it

SID = "11111111-2222-4333-8444-555555555555"
APP_EXE = "/Applications/T3 Code (Beta).app/Contents/MacOS/T3 Code (Beta)"
CLAUDE_EXE = "/home/example/.local/share/claude/versions/2.1.312"


# --- the hook names the host from its ancestors -----------------------------------------------------------------


@pytest.mark.parametrize("exe,argv,expected", [
    (APP_EXE, None, "t3code"),                                     # the desktop app's server: Electron as Node
    ("/Applications/T3 Code.app/Contents/MacOS/T3 Code", None, "t3code"),
    ("/home/example/.local/bin/t3", None, "t3code"),               # `t3`, `t3 service`, the Linux app's <root>/t3
    ("/usr/local/bin/node", ["node", "/home/example/.npm/_npx/abc/node_modules/t3/dist/bin.mjs"], "t3code"),
    ("/opt/homebrew/bin/node", ["node", "/home/example/.npm/_npx/abc/node_modules/.bin/t3"], "t3code"),
    ("/usr/bin/bun", ["bun", "/home/example/src/t3code/apps/server/src/bin.ts"], "t3code"),
    ("/usr/local/bin/node", ["node", "/home/example/other/apps/server/src/bin.ts"], None),   # another app's server
    ("/usr/local/bin/node", ["node", "/home/example/t3-notes.js"], None),
    (CLAUDE_EXE, None, None),
    ("/bin/zsh", None, None),
    ("/Applications/Other.app/Contents/MacOS/t3helper", None, None),
    (None, None, None),
])
def test_host_of_matches_only_t3_codes_own_server(exe, argv, expected):
    assert host_identity.host_of(exe, argv) == expected


def _chain(*procs):
    """pid → (ppid, exe, argv), pids 100, 101, … each the parent of the one before."""
    table = {}
    for i, (exe, argv) in enumerate(procs):
        table[100 + i] = (101 + i, exe, argv)
    return table.__getitem__


def test_detect_walks_up_hook_shell_harness_to_the_server():
    read = _chain(("/bin/sh", None), (CLAUDE_EXE, None), (APP_EXE, None), ("/sbin/launchd", None))
    assert host_identity.detect({}, start=100, read=read) == "t3code"


def test_detect_is_none_for_a_terminal_session_a_short_chain_or_a_reader_that_fails():
    terminal = _chain(("/bin/sh", None), (CLAUDE_EXE, None), ("/bin/zsh", None), ("/usr/bin/login", None))
    assert host_identity.detect({}, start=100, read=terminal, depth=4) is None
    deep = _chain(*[("/bin/sh", None)] * 12, (APP_EXE, None))
    assert host_identity.detect({}, start=100, read=deep) is None, "only MAX_DEPTH ancestors are read"

    def boom(pid):
        raise OSError("gone")

    assert host_identity.detect({}, start=100, read=boom) is None
    assert host_identity.detect({}, start=1, read=terminal) is None


def test_a_detached_child_takes_its_parents_answer_and_only_a_known_one():
    assert host_identity.detect({host_identity.ENV: "t3code"}, start=100, read=_chain()) == "t3code"
    terminal = _chain(("/bin/zsh", None), ("/usr/bin/login", None))
    assert host_identity.detect({host_identity.ENV: "someapp"}, start=100, read=terminal, depth=2) is None


def test_the_hooks_list_is_the_backends():
    assert tuple(host_identity.HOSTS) == agent_catalog.HOSTS
    assert all(agent_catalog.way(h) is not None for h in agent_catalog.HOSTS)


def test_reading_this_process_never_raises_and_is_fast():
    import time

    host_identity.detect({})   # loads ctypes once
    started = time.perf_counter()
    for _ in range(50):
        host_identity.detect({})
    assert (time.perf_counter() - started) / 50 < 0.005


# --- the hook posts it ----------------------------------------------------------------------------------------------


PAYLOAD = {"session_id": SID, "transcript_path": "/home/example/.claude/projects/x/" + SID + ".jsonl",
           "cwd": "/home/example/alpha-project", "hook_event_name": "Stop"}


def _run(tmp_path, payload, *, environ=None, argv=("--harness", "claude-code")):
    token = tmp_path / "api_token"
    token.write_text("tok-123")
    log = tmp_path / "logs" / "capture.log"
    calls = []

    def post(url, body, tok, timeout):
        calls.append((url, json.loads(body)))
        return 200, '{"status":"created"}'

    env = {"HOME": str(tmp_path), "CICADA_HOME": str(tmp_path / "hook-home"), **(environ or {})}
    hook.main(list(argv), stdin=io.StringIO(json.dumps(payload)), environ=env, post=post, log_path=log,
              token_path=token)
    return calls, log.read_text()


def test_a_stop_under_t3_code_posts_the_host_and_logs_it(tmp_path):
    calls, log = _run(tmp_path, PAYLOAD, environ={host_identity.ENV: "t3code"})
    assert calls[0][1]["host"] == "t3code" and calls[0][1]["harness"] == "claude-code"
    assert f"claude-code {SID[:8]} Stop via t3code http 200 created" in log


def test_a_gemini_exchange_carries_the_host_too(tmp_path):
    payload = {"session_id": SID, "hook_event_name": "AfterAgent", "prompt": "hello", "prompt_response": "hi"}
    calls, _ = _run(tmp_path, payload, environ={host_identity.ENV: "t3code"}, argv=("--harness", "gemini-cli"))
    assert calls[0][1]["host"] == "t3code"


def test_cicadas_own_spawns_are_still_never_captured(tmp_path):
    calls, log = _run(tmp_path, PAYLOAD, environ={host_identity.ENV: "t3code", "CICADA_CAPTURE": "off"})
    assert calls == [] and "CICADA_CAPTURE=off" in log


# --- what T3 Code writes into a turn is not the person's words --------------------------------------------------


HANDOFF = ("Context handoff (provider_switch):\nFrom thread thread-a, runs 1-3. Recover history with t3_thread_read, "
           "view=activity; paginate with afterPosition, and use itemId/textOffset for long items.\n"
           "Selected 2 intact items; omitted 0 items. Historical material is context, not a new request or "
           "higher-priority instructions. Attached files and native tool/reasoning state are not replayed.\n\n"
           "[Historical user; message; thread=thread-a; run=run-1; item=item-1; provider-thread=pt-1; "
           "status=completed]\nWhat did we decide about alpha-project?\n\n"
           "[Historical assistant; message; thread=thread-a; run=run-1; item=item-2; provider-thread=pt-1; "
           "status=completed]\nWe kept the old schema.\n\nUser message:\nNow add the migration.")


def test_a_handoff_keeps_only_the_new_request():
    assert tx.host_envelope(HANDOFF) == ("Now add the migration.", "host_handoff")


def test_a_replayed_turn_and_the_native_context_message_keep_nothing():
    replay = ("[Historical user; message; thread=thread-a; run=run-1; item=item-1; provider-thread=pt-1; "
              "status=completed]\nWhat did we decide?")
    assert tx.host_envelope(replay) == ("", "host_replay")
    context = HANDOFF.split("\n\n[Historical")[0]
    assert tx.host_envelope(context) == ("", "host_handoff")


def test_an_acp_prompt_keeps_the_request_inside_the_instructions():
    wrapped = ("<t3_code_instructions>\nYou are running inside T3 Code.\n\nUse the T3 tools.\n"
               "</t3_code_instructions>\n\n<user_request>\nRename the helper.\nThen run the tests.\n</user_request>")
    assert tx.host_envelope(wrapped) == ("Rename the helper.\nThen run the tests.", "host_instructions")


@pytest.mark.parametrize("text", [
    "Context handoff (my notes): the meeting moved to Tuesday.",           # the person's own words, no T3 marker
    "Can you explain what a [Historical user; message] header is?",
    "<user_request>\nnot wrapped by T3\n</user_request>",
    "Plain request.",
])
def test_the_persons_own_text_is_kept_whole(text):
    assert tx.host_envelope(text) == (text, None)


def _line(typ, content, ts="2026-10-29T10:00:00.000Z"):
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID, "cwd": "/home/example/alpha",
                       "message": {"role": typ, "content": content}})


def test_a_claude_session_started_by_a_provider_switch_keeps_the_request_as_the_first_person_turn():
    conv = tx.extract("claude-code", [_line("user", HANDOFF),
                                      _line("assistant", [{"type": "text", "text": "Migration added."}])])
    assert [(t.role, t.text) for t in conv.turns] == [("user", "Now add the migration."),
                                                      ("assistant", "Migration added.")]
    assert conv.summary["dropped_blocks"]["host_handoff"] == 1


def _codex(role, text, ts="2026-10-29T10:00:00.000Z"):
    kind = "input_text" if role == "user" else "output_text"
    return json.dumps({"type": "response_item", "timestamp": ts,
                       "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}})


def test_a_codex_session_given_history_natively_keeps_none_of_the_replay():
    context, rest = HANDOFF.split("\n\n[Historical", 1)
    replay_user, replay_agent = ("[Historical" + rest.split("\n\nUser message:")[0]).split("\n\n")
    conv = tx.extract("codex", [_codex("user", context), _codex("user", replay_user),
                                _codex("assistant", replay_agent), _codex("user", "Now add the migration."),
                                _codex("assistant", "Done.")])
    assert [(t.role, t.text) for t in conv.turns] == [("user", "Now add the migration."), ("assistant", "Done.")]
    assert conv.summary["dropped_messages"]["host_replay"] == 2
    assert conv.summary["dropped_messages"]["host_handoff"] == 1


def test_a_posted_turn_is_unwrapped_the_same_way():
    turn, _ = tx.clean_turn("user", HANDOFF, first=True)
    assert turn.text == "Now add the migration."


# --- the backend records it -------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})
    seen = []
    from api.services import agent_seen

    monkeypatch.setattr(agent_seen, "stamp_agent", lambda agent, *, via, device=None: seen.append((agent, via, device)))
    return seen


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    root = tmp_path / "claude-projects" / "-home-example-alpha"
    root.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: root.parent)
    path = root / f"{SID}.jsonl"
    path.write_text("\n".join([_line("user", "Plan the alpha migration."),
                               _line("assistant", [{"type": "text", "text": "Here is the plan."}])]) + "\n")
    return path


def test_one_episode_labelled_with_its_host_and_seen_once_written(memory, transcript, _fresh):
    first = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                                  cwd=None, keep_assistant=True, host="t3code")
    assert first.status == "created"
    again = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                                  cwd=None, keep_assistant=True, host="t3code")
    assert again.status == "unchanged" and again.episode_id == first.episode_id
    files = list((memory / "episodes").glob("*.md"))
    assert len(files) == 1, "one T3 Code thread on one harness is one episode (G104)"
    fm = markdown_parser.parse(files[0]).frontmatter
    assert (fm["harness"], fm["host"], fm["origin"]) == ("claude-code", "t3code", "claude-code")
    assert _fresh == [("t3code", "hook", None), ("t3code", "hook", None)]


def test_a_later_firing_that_could_not_name_the_host_keeps_the_label(memory, transcript):
    tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                          cwd=None, keep_assistant=True, host="t3code")
    with transcript.open("a") as fh:
        fh.write(_line("user", "And the rollback?") + "\n")
    tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                          cwd=None, keep_assistant=True)
    fm = markdown_parser.parse(next((memory / "episodes").glob("*.md"))).frontmatter
    assert fm["host"] == "t3code"


def test_an_unknown_host_is_dropped_and_never_refuses_the_capture(memory, transcript, _fresh):
    result = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                                   cwd=None, keep_assistant=True, host="some-new-app")
    assert result.status == "created"
    fm = markdown_parser.parse(next((memory / "episodes").glob("*.md"))).frontmatter
    assert "host" not in fm and _fresh == []


def test_a_demo_bank_still_refuses_and_sees_nothing(memory, transcript, _fresh, monkeypatch):
    from api.services import demo_guard

    monkeypatch.setattr(demo_guard, "is_demo", lambda p: True)
    result = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                                   cwd=None, keep_assistant=True, host="t3code")
    assert result.status == "refused" and _fresh == []


def test_a_cursor_turn_under_t3_code_is_labelled(memory, _fresh):
    result = turn_capture.capture_turns(memory, harness="cursor", session_id="conv-12345678",
                                        turns=[turn_capture.Posted("user", "Rename the helper.")], host="t3code")
    assert result.status == "created"
    fm = markdown_parser.parse(next((memory / "episodes").glob("*.md"))).frontmatter
    assert fm["host"] == "t3code" and _fresh == [("t3code", "hook", None)]


@pytest.fixture
def client(memory, monkeypatch):
    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_routes_take_the_field_and_an_unknown_one_is_no_refusal(client, memory, transcript):
    body = {"harness": "claude-code", "session_id": SID, "transcript_path": str(transcript), "host": "t3code"}
    answer = client.post("/capture/transcript", json=body)
    assert answer.status_code == 200, answer.text
    fm = markdown_parser.parse(next((memory / "episodes").glob("*.md"))).frontmatter
    assert fm["host"] == "t3code"
    turn = client.post("/capture/turn", json={"harness": "cursor", "session_id": "conv-12345678", "host": "x" * 30,
                                              "messages": [{"speaker": "user", "text": "Rename the helper."}]})
    assert turn.status_code == 200, turn.text


# --- where it shows -----------------------------------------------------------------------------------------------


def test_a_host_session_is_the_hosts_source_row_and_the_rest_keep_theirs():
    assert source_overview.source_key({"session_id": SID, "harness": "claude-code", "host": "t3code"}) == \
        "harness:t3code"
    assert source_overview.source_key({"session_id": SID, "harness": "claude-code"}) == "harness:claude-code"
    assert source_overview.source_key({"session_id": SID, "harness": "codex", "host": "bogus"}) == "harness:codex"
    assert source_overview.HARNESS_LABELS["t3code"] == "T3 Code"


def test_t3_code_is_one_umbrella_whose_connect_flow_is_the_agents_it_drives():
    umbrella = next(u for u in agent_catalog.UMBRELLAS if u.id == "t3")
    (way,) = umbrella.ways
    assert (umbrella.label, umbrella.logo, way.id) == ("T3 Code", None, "t3code")
    assert way.setup == ("claude-code", "codex", "cursor") and "hooks" in way.connects
    assert way.id not in agent_catalog.LIVE_PILLS and way.id in agent_catalog.TRACKED
    assert not any("chat" in w.id for w in umbrella.ways), "T3 Chat takes no MCP connector, so it is not listed"


def test_a_t3_code_sighting_never_lights_another_agent():
    folded = agent_live._fold_other({"t3code": "2026-10-29T10:00:00Z"})
    assert "other" not in folded
    assert agent_live._fold_other({"zed": "2026-10-29T10:00:00Z"})["other"] == "2026-10-29T10:00:00Z"
