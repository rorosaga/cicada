"""Capture-everywhere: hook-posted turns (Cursor, Gemini CLI) become ONE episode per
session through the same writer as the Stop hook. Synthetic banks and payloads only;
no installed Cursor or Gemini CLI was run, so the payload shapes are the documented
ones (Cursor docs/hooks v1, Gemini CLI hooks reference), checked 2026-10-14."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_registry, demo_guard, evidence, markdown_parser, telemetry
from api.services import transcript_capture as tc
from api.services import turn_capture as turns
from api.services.transcript_extract import FIRST_USER_CAP_CHARS, SESSION_CAP_CHARS, TURN_CAP_CHARS

SID = "cursor-conv-0001-alpha"
P = turns.Posted


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})
    path = tmp_path / "bank"
    (path / "episodes").mkdir(parents=True)
    return path


@pytest.fixture(autouse=True)
def _fresh_settings():
    yield
    config.get_settings.cache_clear()


def _words(n: int) -> str:
    """Prose of exactly ``n`` characters — a long run of one letter reads as a token and is scrubbed."""
    return ("plain words about the alpha-project plan " * (n // 40 + 1))[:n]


def _cursor(bank: Path, speaker: str, text: str, gen: str, **kw):
    return turns.capture_turns(bank, harness="cursor", session_id=kw.pop("sid", SID), turns=[P(speaker, text)],
                               turn_id=gen, model=kw.pop("model", None), cwd="/synthetic/alpha-project",
                               hook_event="beforeSubmitPrompt" if speaker == "user" else "afterAgentResponse", **kw)


def _episodes(bank: Path) -> list[Path]:
    return sorted((bank / "episodes").glob("ep_*.md"))


def _one(bank: Path):
    (path,) = _episodes(bank)
    return path, markdown_parser.parse(path)


def test_a_multi_turn_cursor_conversation_is_one_episode(bank):
    statuses = [_cursor(bank, "user", "Should alpha-project ship on Friday?", "gen-1").status,
                _cursor(bank, "assistant", "Yes, if the migration lands first.", "gen-1", model="claude-example-5").status,
                _cursor(bank, "user", "And bob-example's review?", "gen-2").status,
                _cursor(bank, "assistant", "It is the last blocker.", "gen-2").status]
    assert statuses == ["created", "updated", "updated", "updated"]
    path, ep = _one(bank)
    assert ep.body == ("user: Should alpha-project ship on Friday?\nassistant: Yes, if the migration lands first.\n"
                       "user: And bob-example's review?\nassistant: It is the last blocker.")
    fm = ep.frontmatter
    assert (fm["harness"], fm["source"], fm["capture_kind"], fm["session_id"]) == ("cursor", "cursor", "transcript", SID)
    assert fm["title"] == "Should alpha-project ship on Friday?" and fm["processed"] is False
    assert fm["project_dir"] == "/synthetic/alpha-project"
    assert [e["speaker"] for e in fm["turns"]] == ["user", "assistant", "user", "assistant"]
    assert fm["turns"][1]["model"] == "claude-example-5"
    assert [e.get("id") for e in fm[turns.STATE_KEY]] == ["gen-1", "gen-1", "gen-2", "gen-2"]
    assert list(fm)[-1] == "turns"  # the sidecar stays the last key (R-PB4)
    assert fm["turn_count"] == 4 and len(fm["tail_turns"]) == 4
    assert evidence.turn_stamps(fm)  # the Reader's one reader of turn times reads it


def test_a_refire_is_idempotent_and_writes_nothing(bank):
    _cursor(bank, "user", "Plan the alpha-project launch", "gen-1")
    _cursor(bank, "assistant", "Three steps.", "gen-1")
    path, _ = _one(bank)
    before = path.read_bytes()
    assert _cursor(bank, "assistant", "Three steps.", "gen-1").status == "unchanged"
    assert _cursor(bank, "user", "Plan the alpha-project launch", "gen-1").status == "unchanged"
    assert path.read_bytes() == before and len(_episodes(bank)) == 1


def test_a_later_reply_for_the_same_run_replaces_the_earlier_one(bank):
    _cursor(bank, "user", "Draft the note", "gen-1")
    _cursor(bank, "assistant", "Let me look at the files first.", "gen-1")
    assert _cursor(bank, "assistant", "Here is the draft.", "gen-1").status == "updated"
    _, ep = _one(bank)
    assert ep.body == "user: Draft the note\nassistant: Here is the draft."


def test_a_reply_lands_after_its_own_prompt_when_a_follow_up_was_queued(bank):
    _cursor(bank, "user", "First question", "gen-1")
    _cursor(bank, "user", "Queued follow-up", "gen-2")
    _cursor(bank, "assistant", "Answer to the first", "gen-1")
    _, ep = _one(bank)
    assert ep.body == "user: First question\nassistant: Answer to the first\nuser: Queued follow-up"


def test_turns_are_cleaned_like_a_transcript_turn(bank):
    secret = "sk-ant-api03-" + "A" * 40
    _cursor(bank, "user", _words(FIRST_USER_CAP_CHARS + 500), "gen-1")
    _cursor(bank, "assistant", f"Use this:\n```python\nprint('{secret}')\n```\nThen {secret} again. " + _words(5000), "gen-1")
    _cursor(bank, "user", _words(5000), "gen-2")
    path, ep = _one(bank)
    first, reply, later = ep.frontmatter[turns.STATE_KEY]
    assert secret not in path.read_text() and "[code omitted]" in ep.body
    assert reply["offset"] - first["offset"] == len("user: ") + FIRST_USER_CAP_CHARS + 1
    assert len(ep.body) - later["offset"] == len("user: ") + TURN_CAP_CHARS
    assert "reply_gap" in reply and ep.frontmatter["reply_gaps"]
    assert ep.frontmatter["capture_flags"]["first_request_clipped"] is True


def test_replies_are_dropped_when_the_owner_keeps_only_their_own_turns(bank):
    _cursor(bank, "user", "Only my words", "gen-1", keep_assistant=False)
    assert _cursor(bank, "assistant", "Not kept", "gen-1", keep_assistant=False).status == "unchanged"
    assert _one(bank)[1].body == "user: Only my words"


def test_the_session_cap_keeps_the_head_and_slides_the_tail(bank):
    n = (SESSION_CAP_CHARS // TURN_CAP_CHARS) * 2 + 12
    head = None
    for i in range(n):
        _cursor(bank, "user" if i % 2 == 0 else "assistant", f"{i:04d} " + _words(TURN_CAP_CHARS - 10), f"gen-{i // 2}")
        fm = _one(bank)[1].frontmatter
        if head is None and "capture_gap" in fm:
            head = _one(bank)[1].body[:fm["capture_gap"]["offset"]]
    _, ep = _one(bank)
    gap = ep.frontmatter["capture_gap"]
    assert gap["dropped_turns"] > 0 and evidence.is_gap_line(ep.body[gap["offset"]:].split("\n", 1)[0])
    assert head and ep.body[:gap["offset"]] == head  # the head never moved once the gap formed (gate B2)
    assert f"{n - 1:04d} " in ep.body  # the latest turn is always kept
    kept = len(ep.frontmatter[turns.STATE_KEY])
    assert kept + gap["dropped_turns"] == n
    assert sum(len(line) for line in ep.body.split("\n")) <= SESSION_CAP_CHARS + 2 * kept + 200
    # A re-fire of the latest turn after the gap formed is still a no-op.
    assert _cursor(bank, "user" if (n - 1) % 2 == 0 else "assistant", f"{n - 1:04d} " + _words(TURN_CAP_CHARS - 10),
                   f"gen-{(n - 1) // 2}").status == "unchanged"


def test_an_episode_that_no_longer_matches_its_turn_index_is_never_rewritten(bank):
    _cursor(bank, "user", "Hello there", "gen-1")
    path, ep = _one(bank)
    markdown_parser.write(path, ep.frontmatter, "A note added above.\n" + ep.body)
    before = path.read_bytes()
    result = _cursor(bank, "assistant", "Hi", "gen-1")
    assert (result.status, result.reason) == ("refused", "state_mismatch")
    assert path.read_bytes() == before


@pytest.mark.parametrize("poison", [
    lambda fm: fm["hook_turns"][0].__setitem__("offset", float("inf")),
    lambda fm: fm["hook_turns"][0].__setitem__("offset", "0"),
    lambda fm: fm["hook_turns"][1].__setitem__("reply_gap", {"offset": 3}),
    lambda fm: fm["hook_turns"][1].__setitem__("reply_gap", "gap"),
    lambda fm: fm["hook_turns"][0].pop("offset"),
    lambda fm: fm["hook_turns"].__setitem__(0, "not an entry"),
    lambda fm: fm.__setitem__("capture_gap", {"offset": float("inf"), "dropped_turns": 1}),
    lambda fm: fm.__setitem__("capture_gap", ["not", "a", "gap"]),
    lambda fm: fm["hook_turns"][0].__setitem__("id", {"nested": True}),
])
def test_a_hand_poisoned_turn_index_is_a_refusal_not_a_500(bank, poison):
    _cursor(bank, "user", "Hello there", "gen-1")
    _cursor(bank, "assistant", "Hi", "gen-1")
    path, ep = _one(bank)
    fm = dict(ep.frontmatter)
    fm["hook_turns"] = [dict(e) for e in fm["hook_turns"]]
    poison(fm)
    markdown_parser.write(path, fm, ep.body)
    before = path.read_bytes()
    result = _cursor(bank, "user", "Next", "gen-2")
    assert (result.status, result.reason) == ("refused", "state_mismatch")
    assert path.read_bytes() == before


@pytest.mark.parametrize("kw,reason", [({"harness": "claude-code"}, "bad_harness"),
                                       ({"session_id": "bad id"}, "bad_session_id"),
                                       ({"turn_id": "bad\nid"}, "bad_turn_id")])
def test_bad_identity_is_refused_unwritten(bank, kw, reason):
    args = {"harness": "cursor", "session_id": SID, "turns": [P("user", "hi")], "turn_id": "gen-1", **kw}
    result = turns.capture_turns(bank, **args)
    assert (result.status, result.reason) == ("refused", reason) and _episodes(bank) == []


def test_the_service_refuses_a_demo_bank(tmp_path):
    demo = tmp_path / "demo"
    bank_registry.scaffold_bank(demo, git_init=False)
    demo_guard.write_manifest(demo)
    result = turns.capture_turns(demo, harness="cursor", session_id=SID, turns=[P("user", "hi")], turn_id="gen-1")
    assert (result.status, result.reason) == ("refused", "demo_bank")
    assert list((demo / "episodes").glob("ep_*.md")) == []


# --- Gemini CLI: one whole exchange per AfterAgent -------------------------------------


def _gemini(bank: Path, prompt: str, reply: str, retry: bool = False):
    return turns.capture_turns(bank, harness="gemini-cli", session_id="gemini-session-0001",
                               turns=[P("user", prompt), P("assistant", reply)], retry=retry, hook_event="AfterAgent")


def test_gemini_exchanges_append_refire_and_retry(bank):
    assert _gemini(bank, "Summarise alpha-project", "It ships Friday.").status == "created"
    assert _gemini(bank, "Summarise alpha-project", "It ships Friday.").status == "unchanged"
    assert _gemini(bank, "continue", "More detail.").status == "updated"
    assert _gemini(bank, "continue", "Even more detail.").status == "updated"   # a repeated prompt is a new turn
    assert _gemini(bank, "continue", "A retried answer.", retry=True).status == "updated"
    _, ep = _one(bank)
    assert ep.body == ("user: Summarise alpha-project\nassistant: It ships Friday.\nuser: continue\n"
                       "assistant: More detail.\nuser: continue\nassistant: A retried answer.")
    assert ep.frontmatter["harness"] == "gemini-cli" and ep.frontmatter["title"] == "Summarise alpha-project"


# --- the route ---------------------------------------------------------------------------


def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def _body(text="Should alpha-project ship?", speaker="user", gen="gen-1"):
    return {"harness": "cursor", "session_id": SID, "messages": [{"speaker": speaker, "text": text}],
            "turn_id": gen, "hook_event": "beforeSubmitPrompt"}


def test_the_route_writes_into_the_active_bank(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})
    root = tmp_path / "root"
    root.mkdir()
    client = _client(root, monkeypatch)
    r = client.post("/capture/turn", json=_body())
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["bank"], r.json()["redirectedFrom"]) == ("created", "default", None)
    assert len(list((root / "episodes").glob("ep_*.md"))) == 1
    r = client.post("/capture/turn", json={**_body(), "harness": "claude-code"})
    assert r.status_code == 422


def test_the_route_saves_into_the_real_bank_left_last_while_the_demo_is_open(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})
    root = tmp_path / "root"
    root.mkdir()
    bank_registry.create_bank(root, "work")
    slug = bank_registry.create_bank(root, "demo")
    demo = bank_registry.bank_dir(root, slug)
    demo_guard.write_manifest(demo)
    bank_registry.activate_bank(root, "work")
    bank_registry.activate_bank(root, "demo")
    r = _client(root, monkeypatch).post("/capture/turn", json=_body())
    assert r.status_code == 200, r.text
    assert (r.json()["bank"], r.json()["redirectedFrom"]) == ("work", "demo")
    assert list((demo / "episodes").glob("ep_*.md")) == []


def test_with_only_the_demo_bank_the_route_answers_409_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    root = tmp_path / "root"
    root.mkdir()
    bank_registry.create_bank(root, "work")
    slug = bank_registry.create_bank(root, "demo")
    demo = bank_registry.bank_dir(root, slug)
    demo_guard.write_manifest(demo)
    reg = bank_registry.load_registry(root)
    reg["active"] = "demo"   # two real banks and no stamp: never guess
    bank_registry.save_registry(root, reg)
    r = _client(root, monkeypatch).post("/capture/turn", json=_body())
    assert r.status_code == 409 and r.json()["detail"] == demo_guard.HOOK_REFUSAL
    for path in (root, bank_registry.bank_dir(root, "work"), demo):
        assert list((path / "episodes").glob("ep_*.md")) == []
    (ev,) = [e for e in telemetry.read_events() if e.kind == "capture"]
    assert ev.refs["status"] == "refused" and ev.refs["reason"] == "demo_bank"


def test_an_oversized_turn_is_refused_by_the_route(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    r = _client(root, monkeypatch).post("/capture/turn", json=_body(text="x" * (turns.TEXT_MAX_CHARS + 1)))
    assert r.status_code == 422
    assert list((root / "episodes").glob("ep_*.md")) == []
