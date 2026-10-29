"""G228: T3 Code is a host, not a harness. Its threads are captured by the harness it drives (Claude Code, Codex,
Cursor) through Cicada's existing hooks — one episode per harness session — with ``host: t3code`` as a label the hook
reads from its own launch chain (parent pid and exec path only); what T3 Code itself writes into a turn (a handoff's
replay, its instructions) is never kept as the person's words — and only under that host, on its full fixed shape.
Synthetic fixtures shaped from T3 Code's source (commit 3748c5c2); unverified against a running T3 Code."""
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


# --- the hook names the host from its own launch chain: exec paths only ---------------------------------------


@pytest.mark.parametrize("exe,expected", [
    (APP_EXE, "t3code"),                                           # the desktop app's server: Electron as Node
    ("/Applications/T3 Code.app/Contents/MacOS/T3 Code", "t3code"),
    ("/home/example/.local/bin/t3", "t3code"),                     # `t3`, `t3 service`, the Linux app's <root>/t3
    ("/usr/local/bin/node", None),                                 # `npx t3` / npm-global: undetected by decision
    ("/opt/homebrew/bin/bun", None),
    (CLAUDE_EXE, None),
    ("/bin/zsh", None),
    ("/usr/local/bin/t3code", None),
    ("/Applications/Other.app/Contents/MacOS/t3helper", None),
    (None, None),
])
def test_host_of_matches_only_t3_codes_own_exec_paths(exe, expected):
    assert host_identity.host_of(exe) == expected


def _chain(*exes):
    """pid → (ppid, exe), pids 100, 101, … each the parent of the one before."""
    table = {100 + i: (101 + i, exe) for i, exe in enumerate(exes)}
    return table.__getitem__


def test_detect_walks_up_hook_shell_harness_to_the_server():
    assert host_identity.detect({}, start=100, read=_chain("/bin/sh", CLAUDE_EXE, APP_EXE, "/sbin/launchd")) \
        == "t3code"


def test_detect_is_none_for_a_terminal_session_a_long_chain_or_a_reader_that_fails():
    terminal = _chain("/bin/sh", CLAUDE_EXE, "/bin/zsh", "/usr/bin/login")
    assert host_identity.detect({}, start=100, read=terminal, depth=4) is None
    deep = _chain(*["/bin/sh"] * 12, APP_EXE)
    assert host_identity.detect({}, start=100, read=deep) is None, "only MAX_DEPTH ancestors are read"

    def boom(pid):
        raise OSError("gone")

    assert host_identity.detect({}, start=100, read=boom) is None
    assert host_identity.detect({}, start=1, read=terminal) is None


def test_a_detached_child_takes_its_parents_answer_and_only_a_known_one():
    assert host_identity.detect({host_identity.ENV: "t3code"}, start=100, read=_chain()) == "t3code"
    terminal = _chain("/bin/zsh", "/usr/bin/login")
    assert host_identity.detect({host_identity.ENV: "someapp"}, start=100, read=terminal, depth=2) is None


def test_the_hooks_list_is_the_backends():
    assert tuple(host_identity.HOSTS) == agent_catalog.HOSTS
    assert all(agent_catalog.way(h) is not None for h in agent_catalog.HOSTS)


def test_no_other_process_arguments_or_environment_are_ever_read(monkeypatch):
    """Blocker 1 of #543's review: the launch chain is parent pid and exec path only. On macOS the only libproc calls
    are ``proc_pidinfo`` and ``proc_pidpath`` (never ``sysctl``/``KERN_PROCARGS2``); on Linux the only files are
    ``/proc/<pid>/stat`` and the ``exe`` link (never ``cmdline`` or ``environ``) — and detection still works."""
    text = Path(host_identity.__file__).read_text()
    code = text.split('"""', 2)[2]                      # past the module docstring, which names what is never read
    source = "\n".join(line.split("#", 1)[0] for line in code.splitlines())
    for banned in ("KERN_PROCARGS2", "sysctl(", "/cmdline", "/environ", "subprocess"):
        assert banned not in source, banned
    if sys.platform == "darwin":
        ctypes, lib = host_identity._mac_libproc()
        used = []

        class OnlyChain:
            def __getattr__(self, name):
                if name not in ("proc_pidinfo", "proc_pidpath"):
                    raise AssertionError(f"libproc.{name} called")
                used.append(name)
                return getattr(lib, name)

        monkeypatch.setattr(host_identity, "_libproc", (ctypes, OnlyChain()))
        ppid, exe = host_identity._mac(__import__("os").getpid())
        assert ppid and exe and set(used) == {"proc_pidinfo", "proc_pidpath"}
        assert host_identity.detect({}) is None   # the walk runs to its end through the guarded reader
    elif sys.platform.startswith("linux"):
        import builtins

        real_open = builtins.open
        opened = []

        def guarded(path, *a, **k):
            opened.append(str(path))
            assert not str(path).endswith(("/cmdline", "/environ")), path
            return real_open(path, *a, **k)

        monkeypatch.setattr(builtins, "open", guarded)
        assert host_identity._linux(__import__("os").getpid())[0]
        assert all(p.endswith("/stat") for p in opened)
    # Exec paths alone still find T3 Code.
    assert host_identity.detect({}, start=100, read=_chain(CLAUDE_EXE, "/home/example/.local/bin/t3")) == "t3code"


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


# --- what T3 Code writes into a turn is not the person's words (under its host, on its full shape) --------------


T3 = "t3code"
SELECTED = ("Selected 2 intact items; omitted 0 items. Historical material is context, not a new request or "
            "higher-priority instructions. Attached files and native tool/reasoning state are not replayed.")
CONTEXT = ("Context handoff (provider_switch):\nFrom thread thread-a, runs 1-3. Recover history with t3_thread_read, "
           "view=activity; paginate with afterPosition, and use itemId/textOffset for long items.\n" + SELECTED)
REPLAY_USER = ("[Historical user; message; thread=thread-a; run=run-1; item=item-1; provider-thread=pt-1; "
               "status=completed]\nWhat did we decide about alpha-project?")
REPLAY_AGENT = ("[Historical assistant; message; thread=thread-a; run=run-1; item=item-2; provider-thread=pt-1; "
                "status=completed]\nWe kept the old schema.")
HANDOFF = CONTEXT + "\n\n" + REPLAY_USER + "\n\n" + REPLAY_AGENT + "\n\nUser message:\nNow add the migration."
#: The two strings #543's review reproduced as dropped whole in a plain Claude Code session.
REVIEW_REPROS = ("Context handoff (G228): I want the t3_thread_read marker handled. Please review.",
                 "[Historical user; …] is the header I keep seeing — what does it mean?")


def test_a_full_handoff_under_t3_code_keeps_only_the_new_request():
    assert tx.host_envelope(HANDOFF, T3) == ("Now add the migration.", "host_handoff")


def test_nothing_is_unwrapped_without_the_t3_code_host():
    for text in (HANDOFF, REPLAY_USER, CONTEXT, *REVIEW_REPROS):
        assert tx.host_envelope(text) == (text, None)
        assert tx.host_envelope(text, "some-other-app") == (text, None)


@pytest.mark.parametrize("text", [
    *REVIEW_REPROS,
    HANDOFF.replace(SELECTED, "Selected some items."),                       # the fixed sentence is missing
    HANDOFF.replace("\n\nUser message:\n", "\n\n"),                          # no split line
    CONTEXT + "\n\nUser message:\nNow add the migration.",                   # no historical block
    HANDOFF.replace("t3_thread_read", "the thread reader"),                  # no T3 marker in the header
    "Context handoff (my notes): the meeting moved to Tuesday.",
    "<user_request>\nnot wrapped by T3\n</user_request>",
    "Plain request.",
])
def test_under_t3_code_anything_short_of_the_full_shape_is_kept_whole(text):
    assert tx.host_envelope(text, T3) == (text, None)


def test_a_request_that_itself_holds_the_split_line_keeps_its_head():
    request = "Now add the migration.\n\nUser message:\nand quote it like that"
    assert tx.host_envelope(CONTEXT + "\n\n" + REPLAY_USER + "\n\nUser message:\n" + request, T3) == \
        (request, "host_handoff")


def test_a_replayed_turn_and_the_native_context_message_keep_nothing_under_t3_code():
    assert tx.host_envelope(REPLAY_USER, T3) == ("", "host_replay")
    assert tx.host_envelope(CONTEXT, T3) == ("", "host_handoff")


def test_an_acp_prompt_keeps_the_request_inside_the_instructions():
    wrapped = ("<t3_code_instructions>\nYou are running inside T3 Code.\n\nUse the T3 tools.\n"
               "</t3_code_instructions>\n\n<user_request>\nRename the helper.\nThen run the tests.\n</user_request>")
    assert tx.host_envelope(wrapped, T3) == ("Rename the helper.\nThen run the tests.", "host_instructions")
    assert tx.host_envelope(wrapped) == (wrapped, None)


def _line(typ, content, ts="2026-10-29T10:00:00.000Z"):
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID, "cwd": "/home/example/alpha",
                       "message": {"role": typ, "content": content}})


def test_a_claude_session_started_by_a_provider_switch_keeps_the_request_as_the_first_person_turn():
    lines = [_line("user", HANDOFF), _line("assistant", [{"type": "text", "text": "Migration added."}])]
    conv = tx.extract("claude-code", lines, host=T3)
    assert [(t.role, t.text) for t in conv.turns] == [("user", "Now add the migration."),
                                                      ("assistant", "Migration added.")]
    assert conv.summary["dropped_blocks"]["host_handoff"] == 1
    plain = tx.extract("claude-code", lines)
    assert plain.turns[0].text.startswith("Context handoff (provider_switch)"), "no host: kept whole"


def _codex(role, text, ts="2026-10-29T10:00:00.000Z"):
    kind = "input_text" if role == "user" else "output_text"
    return json.dumps({"type": "response_item", "timestamp": ts,
                       "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}})


def test_a_codex_session_given_history_natively_keeps_none_of_the_replay_under_t3_code():
    conv = tx.extract("codex", [_codex("user", CONTEXT), _codex("user", REPLAY_USER),
                                _codex("assistant", REPLAY_AGENT), _codex("user", "Now add the migration."),
                                _codex("assistant", "Done.")], host=T3)
    assert [(t.role, t.text) for t in conv.turns] == [("user", "Now add the migration."), ("assistant", "Done.")]
    assert conv.summary["dropped_messages"]["host_replay"] == 2
    assert conv.summary["dropped_messages"]["host_handoff"] == 1


def test_a_posted_turn_is_unwrapped_only_under_the_host():
    assert tx.clean_turn("user", HANDOFF, first=True, host=T3)[0].text == "Now add the migration."
    assert tx.clean_turn("user", REVIEW_REPROS[0], first=True)[0].text == REVIEW_REPROS[0]


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
    assert (umbrella.label, umbrella.logo, umbrella.tier, way.id) == ("T3 Code", "t3", 1, "t3code")
    assert way.setup == ("claude-code", "codex", "cursor") and "hooks" in way.connects
    assert way.id not in agent_catalog.LIVE_PILLS and way.id in agent_catalog.TRACKED
    assert not any("chat" in w.id for w in umbrella.ways), "T3 Chat takes no MCP connector, so it is not listed"


def test_a_t3_code_sighting_never_lights_another_agent():
    folded = agent_live._fold_other({"t3code": "2026-10-29T10:00:00Z"})
    assert "other" not in folded
    assert agent_live._fold_other({"zed": "2026-10-29T10:00:00Z"})["other"] == "2026-10-29T10:00:00Z"


# --- the strip follows the capture's host on every route --------------------------------------------------------


def _first_person_turn(memory) -> str:
    body = markdown_parser.parse(next((memory / "episodes").glob("*.md"))).body
    return body.split("assistant:")[0]


def test_a_plain_session_keeps_a_handoff_shaped_message_whole(memory, transcript):
    transcript.write_text("\n".join([_line("user", HANDOFF),
                                     _line("assistant", [{"type": "text", "text": "Done."}])]) + "\n")
    tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                          cwd=None, keep_assistant=True)
    assert "Context handoff (provider_switch)" in _first_person_turn(memory)


def test_a_t3_session_strips_it_and_a_later_hostless_firing_follows_the_episodes_host(memory, transcript):
    tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                          cwd=None, keep_assistant=True, host="t3code")
    with transcript.open("a") as fh:
        fh.write(_line("user", HANDOFF) + "\n")
    tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                          cwd=None, keep_assistant=True)   # this firing could not read its launch chain
    body = markdown_parser.parse(next((memory / "episodes").glob("*.md"))).body
    assert "Now add the migration." in body and "Historical" not in body and "Context handoff" not in body


def test_stored_host_reads_only_the_frontmatter_head(tmp_path):
    ep = tmp_path / "ep.md"
    ep.write_text("---\nid: ep_1\nhost: t3code\nturns:\n- a: 1\n---\nuser: host: t3code\n")
    assert tc.stored_host(ep) == "t3code"
    ep.write_text("---\nid: ep_1\nturns:\n- host: t3code\n---\nuser: hi\n")
    assert tc.stored_host(ep) is None
    assert tc.stored_host(None) is None and tc.stored_host(tmp_path / "missing.md") is None


def test_a_cursor_turn_is_unwrapped_only_under_the_host(memory):
    turn_capture.capture_turns(memory, harness="cursor", session_id="conv-aaaaaaaa",
                               turns=[turn_capture.Posted("user", HANDOFF)])
    turn_capture.capture_turns(memory, harness="cursor", session_id="conv-bbbbbbbb",
                               turns=[turn_capture.Posted("user", HANDOFF)], host="t3code")
    bodies = {markdown_parser.parse(p).frontmatter["session_id"]: markdown_parser.parse(p).body
              for p in (memory / "episodes").glob("*.md")}
    assert "Context handoff" in bodies["conv-aaaaaaaa"]
    assert "Context handoff" not in bodies["conv-bbbbbbbb"] and "Now add the migration." in bodies["conv-bbbbbbbb"]
