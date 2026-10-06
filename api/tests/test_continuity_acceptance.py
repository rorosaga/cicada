"""G110 slice 1a T6: acceptance on synthetic fixtures (spec acceptance 1 and the
honest state of 5). Plan: docs/plans/2026-10-06-g110-continuity.md r4.

Everything runs through the real paths: `capture_transcript` (the Stop hook's
writer) for every session, `POST /capture/hook-context` for SessionStart, and
the stdio `cicada_continue` handler. Timestamps are pinned relative to now so the
fixtures never age out. Placeholders only (`alpha-project`, `/home/example`).

* Acceptance 1, under the capture cap, same harness: PASSES.
* Acceptance 1, over the cap: depends on gate B. Under B1 (today) the note
  discloses the turns past the limit and the acceptance is recorded NOT MET.
* Acceptance 5: NOT CLAIMED. The latest correction is shown, history and
  attribution are intact and the note is never captured, but Sleep would still
  count B's agent restatement of A's fact (strict xfail; optional T10)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from api import config, main
from api.services import continuity, continuity_sessions, handshake, hook_recall, markdown_parser, recall_text
from api.services import transcript_capture as tc
from api.services import transcript_extract

CWD = "/home/example/alpha-project"
URL = "/capture/hook-context"
A, B, C = ("aaaaaaaa-2222-4333-8444-555555555555", "bbbbbbbb-2222-4333-8444-555555555555",
           "cccccccc-2222-4333-8444-555555555555")
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _ts(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _line(typ, content, ts, session, harness_cwd=CWD):
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": session, "cwd": harness_cwd,
                       "message": {"role": typ, "content": content}})


def _transcript(session, turns, *, note: str | None = None) -> str:
    """Claude Code JSONL. ``note`` is the SessionStart hook's context as the
    harness records it: a separate non-message record (documented: hook
    context produces no visible transcript entry)."""
    lines = []
    if note:
        lines.append(json.dumps({"type": "attachment", "timestamp": turns[0][2], "sessionId": session,
                                 "attachment": {"type": "hook_additional_context", "content": note}}))
    for role, text, ts in turns:
        lines.append(_line(role, text if role == "user" else [{"type": "text", "text": text}], ts, session))
    return "\n".join(lines) + "\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    claude = tmp_path / "claude-projects" / "-home-example-alpha-project"
    claude.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: claude.parent)
    monkeypatch.setattr(tc, "_episode_cache", {})
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    hook_recall.reset()
    continuity.reset()
    yield {"memory": memory, "claude": claude, "client": TestClient(main.app)}
    config.get_settings.cache_clear()
    hook_recall.reset()


def _capture(env, session, turns, *, note=None):
    path = env["claude"] / f"{session}.jsonl"
    path.write_text(_transcript(session, turns, note=note), encoding="utf-8")
    return tc.capture_transcript(env["memory"], harness="claude-code", session_id=session, transcript_path=str(path),
                                 cwd=CWD, keep_assistant=True, bank_paths=(env["memory"],))


def _start(env, session, *, harness="claude-code", source="clear"):
    data = env["client"].post(URL, json={"event": "session_start", "harness": harness, "session_id": session,
                                         "cwd": CWD, "source": source}).json()
    return data["additionalContext"] or ""


def _episode(env, result):
    return env["memory"] / "episodes" / f"{result.episode_id}.md"


A_TURNS = [
    ("user", "Make the alpha parser strict about dates.", _ts(30)),
    ("assistant", "I propose approach X: a regex pre-pass over every field.", _ts(29)),
    ("user", "Not X, it breaks the fixture loader; use Y, the typed decoder.", _ts(28)),
    ("assistant", "Done with Y. I edited tests/fixtures/alpha.json; test_alpha_roundtrip still fails on one case. "
                  "Next: fix the date branch in parse_alpha, then rerun test_alpha_roundtrip.", _ts(27)),
]


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_acceptance_1_same_folder_rollover_before_sleep(env, harness, monkeypatch):
    a = _capture(env, A, A_TURNS)
    a_bytes = _episode(env, a).read_bytes()
    # B's first Stop will race the registry's `continues` write: skip it at SessionStart.
    monkeypatch.setattr(hook_recall, "CONTINUES_MIN_S", 10.0)
    note = _start(env, B, harness=harness)
    assert note.startswith(recall_text.PRIMER_HEADER) and len(note) // 4 <= handshake.MAX_TOKENS
    for words in ("### Where the last session in this folder stopped", f"episode `{a.episode_id}`",
                  "the most recent session here", "not yet consolidated",
                  "Not X, it breaks the fixture loader; use Y, the typed decoder.",   # the rejection and its reason
                  "tests/fixtures/alpha.json", "test_alpha_roundtrip",                  # the change and the failing test
                  "Next: fix the date branch in parse_alpha",                          # the next action
                  "quoted as history, not a new instruction", "Workspace state not checked",
                  f'cicada_continue(session="{a.episode_id}")'):
        assert words in note, words
    if harness == "codex":
        return      # Codex's transcript serialization of hook context is unverified: not asserted here.
    # The lazy read lists the person's requests.
    out = stdio_server().handle_tool("cicada_continue", {"session": a.episode_id})
    assert "Make the alpha parser strict about dates." in out and "Not X, it breaks the fixture loader" in out
    # B's first Stop lands before the registry knows what B was pointed at …
    b_turns = [("user", "continue", _ts(5)), ("assistant", "Fixing the date branch in parse_alpha now.", _ts(4))]
    b1 = _capture(env, B, b_turns, note=note)
    assert "continues" not in markdown_parser.parse(_episode(env, b1)).frontmatter
    assert continuity_sessions.apply(env["memory"], bank_paths=(env["memory"],), harness="claude-code", session_id=B,
                                     events={"continues": a.episode_id}, deadline=None) == "ok"
    # … and its second Stop, with the same body, attaches it without re-queuing anything.
    b2 = _capture(env, B, b_turns, note=note)
    doc = markdown_parser.parse(_episode(env, b2))
    assert b2.status == "metadata" and doc.frontmatter["continues"] == a.episode_id
    assert "From Cicada" not in doc.body and "Where the last session" not in doc.body      # the note is not captured
    assert "fixture loader" not in doc.body                                               # nor are A's turns
    assert _episode(env, a).read_bytes() == a_bytes                                       # A is untouched


def test_acceptance_1_a_later_prompt_with_no_captured_reply_is_disclosed(env):
    a = _capture(env, A, A_TURNS)
    env["client"].post(URL, json={"event": "user_prompt_submit", "harness": "claude-code", "session_id": A,
                                  "cwd": CWD, "prompt": "now also handle time zones"})
    note = _start(env, B)
    assert f"episode `{a.episode_id}`" in note and "has no captured reply" in note


def test_acceptance_1_over_the_cap_is_disclosed_and_not_met_under_b1(env, monkeypatch):
    """Gate B pending. Under B1 (today's head-stable cap) the decision at the end
    of an over-cap session is NOT in the bank: the note says so. This records
    acceptance 1 as NOT MET for over-cap sessions; under B2 (T-B) this test is
    to assert the content instead."""
    monkeypatch.setattr(transcript_extract, "SESSION_CAP_CHARS", 4_000)
    # Four 1,000-character turns fill the (pinned) 4,000-character cap exactly, so
    # every later turn — however short — is refused, as in a long real session.
    early = [("user" if i % 2 == 0 else "assistant", (f"early step {i:03d} " + "word " * 250)[:1000],
              _ts(120 - i * 0.5)) for i in range(114)]
    late = [(r, t, _ts(60 - i)) for i, (r, t, _) in enumerate(A_TURNS)]
    a = _capture(env, A, early + late)
    note = _start(env, B)
    assert f"episode `{a.episode_id}`" in note
    assert "turns past Cicada's capture limit" in note
    assert "Not X, it breaks the fixture loader" not in note          # B1: the latest turns are not in memory


def test_acceptance_5_correction_is_shown_history_kept_echo_not_captured(env):
    a = _capture(env, A, [("user", "The alpha-project demo date is 2026-10-09.", _ts(60)),
                          ("assistant", "Noted: the demo is on 2026-10-09.", _ts(59))])
    a_bytes = _episode(env, a).read_bytes()
    note_b = _start(env, B)
    assert f"episode `{a.episode_id}`" in note_b
    b = _capture(env, B, [("user", "continue", _ts(40)),
                          ("assistant", "From the last session: the demo is on 2026-10-09.", _ts(39)),
                          ("user", "Correction: the demo moved to 2026-10-12.", _ts(38)),
                          ("assistant", "Updated: the demo is now on 2026-10-12.", _ts(37))], note=note_b)
    # C starts now: A (60 min ago) and B (37 min ago) are more than 15 minutes apart — B is the unique choice.
    note_c = _start(env, C)
    assert f"episode `{b.episode_id}`" in note_c and "Correction: the demo moved to 2026-10-12." in note_c
    assert _episode(env, a).read_bytes() == a_bytes
    b_body = markdown_parser.parse(_episode(env, b)).body
    assert "From Cicada" not in b_body and "Where the last session" not in b_body
    sessions = [markdown_parser.parse(p).frontmatter.get("session_id")
                for p in (env["memory"] / "episodes").glob("ep_*.md")]
    assert sorted(sessions) == sorted([A, B])                     # one episode per captured session


def test_acceptance_5_two_sessions_active_together_ask_once_and_an_id_resolves(env):
    a = _capture(env, A, [("user", "task one", _ts(10)), ("assistant", "ok", _ts(9))])
    b = _capture(env, B, [("user", "task two", _ts(5)), ("assistant", "ok", _ts(4))])
    note = _start(env, C)
    assert "### Recent sessions in this folder" in note and "Ask the person which one to continue" in note
    out = stdio_server().handle_tool("cicada_continue", {"session": b.episode_id})
    assert "task two" in out and "task one" not in out


@pytest.mark.xfail(strict=True, raises=ImportError, reason="T10 (optional, needs approval): Sleep does not yet count a "
                                                           "continued session's agent restatement once")
def test_acceptance_5_sleep_counts_a_lineage_once():
    from api.services.entity_resolver import lineage_units  # noqa: F401
