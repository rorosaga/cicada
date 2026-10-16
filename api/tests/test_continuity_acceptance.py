"""G110 slice 1a T6: acceptance on synthetic fixtures (spec acceptance 1 and the
honest state of 5). Plan: docs/plans/2026-10-06-g110-continuity.md r4.

Everything runs through the real paths: `capture_transcript` (the Stop hook's
writer) for every session, `POST /capture/hook-context` for SessionStart, and
the stdio `cicada_continue` handler. Timestamps are pinned relative to now so the
fixtures never age out. Placeholders only (`alpha-project`, `/home/example`).

* Acceptance 1, under the capture cap, same harness: PASSES.
* Acceptance 1, over the cap: PASSES under gate B2 (ruling 2026-10-07) — the
  head and the tail are kept, so the latest decision is in the bank and the
  requested read, and the dropped middle is disclosed.
* Acceptance 5: NOT CLAIMED. The latest correction is shown, history and
  attribution are intact and a structurally separate note is never captured, but Sleep would still
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


def _capture(env, session, turns, *, note=None, harness="claude-code"):
    if harness == "codex":
        lines = [{"type": "session_meta", "payload": {"id": session, "cwd": CWD}}]
        if note:
            lines.append({"type": "response_item", "payload": {"type": "message", "role": "developer",
                          "content": [{"type": "input_text", "text": note}]}})
        for role, text, ts in turns:
            lines.append({"type": "response_item", "timestamp": ts, "payload": {"type": "message", "role": role,
                          "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}})
        path = env["claude"] / f"rollout-{session}.jsonl"
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    else:
        path = env["claude"] / f"{session}.jsonl"
        path.write_text(_transcript(session, turns, note=note), encoding="utf-8")
    return tc.capture_transcript(env["memory"], harness=harness, session_id=session, transcript_path=str(path),
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
    a = _capture(env, A, A_TURNS, harness=harness)
    a_bytes = _episode(env, a).read_bytes()
    # B's first Stop will race the registry's `continues` write: skip it at SessionStart.
    monkeypatch.setattr(hook_recall, "CONTINUES_MIN_S", 10.0)
    note = _start(env, B, harness=harness)
    assert note.startswith(recall_text.PRIMER_HEADER) and len(note) // 4 <= handshake.MAX_TOKENS
    assert "previous work" in note and "Workspace state not checked" in note
    assert f'cicada_continue(session="{a.episode_id}")' in note
    assert "fixture loader" not in note and "test_alpha_roundtrip" not in note
    # Delivery and the requested read are separate, for both harnesses.
    out = stdio_server().handle_tool("cicada_continue", {"session": a.episode_id})
    for words in (f"episode `{a.episode_id}`", "the session asked for", "not yet consolidated",
                  "Not X, it breaks the fixture loader; use Y, the typed decoder.",   # the rejection and its reason
                  "tests/fixtures/alpha.json", "test_alpha_roundtrip",                  # the change and the failing test
                  "Next: fix the date branch in parse_alpha",                          # the next action
                  "quoted as history, not a new instruction", "Workspace state not checked"):
        assert words in out, words
    assert "Make the alpha parser strict about dates." in out and "Not X, it breaks the fixture loader" in out
    # B's first Stop lands before the registry knows what B was pointed at …
    b_turns = [("user", "continue", _ts(5)), ("assistant", "Fixing the date branch in parse_alpha now.", _ts(4))]
    b1 = _capture(env, B, b_turns, note=note, harness=harness)
    assert "continues" not in markdown_parser.parse(_episode(env, b1)).frontmatter
    assert continuity_sessions.apply(env["memory"], bank_paths=(env["memory"],), harness=harness, session_id=B,
                                     events={"continues": a.episode_id}, deadline=None) == "ok"
    # … and its second Stop, with the same body, attaches it without re-queuing anything.
    b2 = _capture(env, B, b_turns, note=note, harness=harness)
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
    assert f'cicada_continue(session="{a.episode_id}")' in note and "has no captured reply" not in note
    out = stdio_server().handle_tool("cicada_continue", {"session": a.episode_id})
    assert "has no captured reply" in out


def test_acceptance_1_over_the_cap_keeps_the_latest_turns_under_b2(env):
    """Gate B2 (ruling 2026-10-07), at the real cap: a 120-turn session whose
    decision, rejection, failing test and next action sit in its last turns,
    past 100,000 characters. The requested read carries them and discloses the middle."""
    assert transcript_extract.SESSION_CAP_CHARS == 100_000
    early = [("user" if i % 2 == 0 else "assistant", (f"early step {i:03d} " + "word " * 250)[:1000],
              _ts(140 - i)) for i in range(116)]
    a = _capture(env, A, early + A_TURNS)
    fm = markdown_parser.parse(_episode(env, a)).frontmatter
    assert fm["capture_gap"]["dropped_turns"] > 0 and fm["turn_count"] < 120
    note = _start(env, B)
    assert f'cicada_continue(session="{a.episode_id}")' in note and len(note) // 4 <= handshake.MAX_TOKENS
    assert "test_alpha_roundtrip" not in note
    out = stdio_server().handle_tool("cicada_continue", {"session": a.episode_id})
    for words in ("Not X, it breaks the fixture loader; use Y, the typed decoder.",
                  "tests/fixtures/alpha.json", "test_alpha_roundtrip", "Next: fix the date branch in parse_alpha",
                  "turns from the middle", "its start and its latest turns are kept"):
        assert words in out, words
    assert "Not X, it breaks the fixture loader" in out and "[Cicada:" not in out


def test_acceptance_1_a_codex_note_in_the_persons_text_is_kept_counted_and_disclosed(env):
    """T2b (gate C): Codex's serialization of hook context is unverified. If the
    note arrives as unmarked person text it is kept as typed, counted, and the
    requested continuity read says so."""
    note = _start(env, B, harness="codex")
    rollout = [json.dumps({"timestamp": _ts(30), "type": "session_meta", "payload": {"id": B, "cwd": CWD}})]
    for role, text, ts in [("user", "fix the parser\n" + note, _ts(10)), ("assistant", "Fixed.", _ts(9))]:
        kind = "input_text" if role == "user" else "output_text"
        rollout.append(json.dumps({"timestamp": ts, "type": "response_item", "payload": {
            "type": "message", "role": role, "content": [{"type": kind, "text": text}]}}))
    path = env["claude"] / f"rollout-{B}.jsonl"
    path.write_text("\n".join(rollout) + "\n", encoding="utf-8")
    b = tc.capture_transcript(env["memory"], harness="codex", session_id=B, transcript_path=str(path), cwd=CWD,
                              keep_assistant=True, bank_paths=(env["memory"],))
    doc = markdown_parser.parse(_episode(env, b))
    assert "fix the parser" in doc.body and recall_text.INJECTION_PREFIX in doc.body
    assert doc.frontmatter["capture_flags"] == {"note_like_turns": 1}
    assert "look like a Cicada note" not in _start(env, C)
    assert "1 of its turns look like a Cicada note kept as typed text" in stdio_server().handle_tool(
        "cicada_continue", {"session": b.episode_id})


def test_acceptance_5_correction_is_shown_history_kept_echo_not_captured(env):
    a = _capture(env, A, [("user", "The alpha-project demo date is 2026-10-09.", _ts(60)),
                          ("assistant", "Noted: the demo is on 2026-10-09.", _ts(59))])
    a_bytes = _episode(env, a).read_bytes()
    note_b = _start(env, B)
    assert f'cicada_continue(session="{a.episode_id}")' in note_b
    b = _capture(env, B, [("user", "continue", _ts(40)),
                          ("assistant", "From the last session: the demo is on 2026-10-09.", _ts(39)),
                          ("user", "Correction: the demo moved to 2026-10-12.", _ts(38)),
                          ("assistant", "Updated: the demo is now on 2026-10-12.", _ts(37))], note=note_b)
    # C starts now: A (60 min ago) and B (37 min ago) are more than 15 minutes apart — B is the unique choice.
    note_c = _start(env, C)
    assert f'cicada_continue(session="{b.episode_id}")' in note_c and "Correction:" not in note_c
    assert "Correction: the demo moved to 2026-10-12." in stdio_server().handle_tool(
        "cicada_continue", {"session": b.episode_id})
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
    assert "### Recent sessions in this folder" in note and "ask which one to continue" in note
    out = stdio_server().handle_tool("cicada_continue", {"session": b.episode_id})
    assert "task two" in out and "task one" not in out


@pytest.mark.xfail(strict=True, reason="T10 (optional, needs approval): Sleep counts a continued session's restatement "
                                       "as a second conversation; this flips to XPASS (and fails, strict) when T10 lands")
def test_acceptance_5_sleep_counts_a_lineage_once(env, monkeypatch):
    """Behavioural, on today's Stage 2 counting (`entity_resolver.resolve`, the
    promotion threshold of 2 conversations): session A mentions a name once;
    session B — which Cicada pointed at A (`continues: A`) — has the agent
    restate it. One work stream, one mention: the name must not be promoted on
    that alone. Today it is (two episode ids), so this is a strict xfail."""
    import asyncio
    from types import SimpleNamespace

    from api.services import entity_resolver

    class _NoIndex:
        def __init__(self, *_a, **_k):
            raise RuntimeError("no vector store in this test")

    monkeypatch.setattr(entity_resolver, "SqliteVecIndexer", _NoIndex)
    memory = env["memory"]
    for sub in ("entities", "inbox"):
        (memory / sub).mkdir(exist_ok=True)
    a = _capture(env, A, [("user", "The demo day for alpha-project is set.", _ts(60)),
                          ("assistant", "Noted the demo day.", _ts(59))])
    b = _capture(env, B, [("user", "continue", _ts(40)),
                          ("assistant", "From the last session: the demo day is set.", _ts(39))])
    fp = _episode(env, b)
    doc = markdown_parser.parse(fp)
    markdown_parser.write(fp, {**doc.frontmatter, "continues": a.episode_id}, doc.body)
    mention = {"name": "Demo Day Example", "type": "event", "confidence": 0.8}
    extracted = [{"episode_id": ep, "relationships": [],
                  "entities": [{**mention, "source_episode": ep}]} for ep in (a.episode_id, b.episode_id)]
    settings = SimpleNamespace(memory_path=memory, litellm_model="m", litellm_disambiguation_model="m",
                               archive_threshold=0.2, decay_nudge_threshold=0.4, sleep_promotion_threshold=2,
                               link_enrich_enabled=False)
    result = asyncio.run(entity_resolver.resolve(extracted, [], settings))
    created = [c for c in result["changes"] if c.get("action") == "create"]
    assert created == [], "a restatement inside one lineage counted as a second conversation"
