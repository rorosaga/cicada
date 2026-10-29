"""An agent's saved note is the agent's words, never the person's (ruling 50, owner 2026-10-29).

`cicada_save_episode` (stdio, the remote connector, an agent's shell running `cicada save`) writes a note with no turn
marker. Before ruling 50, R4's default read every unmarked line as the person's: the note's paragraphs were exchanges
"in the person's own words" (promotion), its spans `user` evidence, and agent notes minted event pages. Now
`authorship.of` derives `evidence.AGENT_KIND` from the note's own record, every reader passes it as `override`, and
the person's own located words in a captured conversation stay theirs (G118).
"""
from __future__ import annotations

from types import SimpleNamespace

from api.services import (authorship, entity_extractor, episode_actor, evidence, inbox_tend, markdown_parser,
                          promotion)

NOTE_ID = "ep_2026-10-01_002"
SESSION_ID = "ep_2026-10-01_001"
SID = "sess-alpha"
NOTE = """The person registered for alpha-event.

They chose alpha-event over beta-event.

alpha-event is in alpha-city.

They will travel to alpha-event by train.

user: I signed up for alpha-event"""
MEETING = """speaker:bob-example: alpha-project ships Friday
video [1:05]: alpha-project in the demo
attachment [notes.txt]:
> alpha-project plan"""
NOTE_FM = {"id": NOTE_ID, "source": "mcp", "origin": "mcp", "session_id": SID, "harness": "claude-code"}
SESSION = "user: I signed up for alpha-event today\nassistant: Noted."
SESSION_FM = {"id": SESSION_ID, "source": "claude-code", "origin": "claude-code", "session_id": SID,
              "harness": "claude-code", "capture_kind": "transcript"}
EVENT = {"name": "alpha-event", "type": "event"}


def _bank(tmp_path, *episodes):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    for eid, fm, body in episodes:
        markdown_parser.write(memory / "episodes" / f"{eid}.md", fm, body)
    return memory


# ---------- whose words, from the record ----------

def test_an_agent_save_is_known_by_its_door_never_by_a_line():
    for door in ("mcp", "mcp-remote"):
        assert authorship.of({"source": door, "origin": "mcp"}) == evidence.AGENT_KIND, door
        assert authorship.agent_saved({"source": door})
    # The command line: an agent's shell names its harness or session; the person's own terminal names neither.
    assert authorship.of({"source": "cli", "origin": "mcp", "harness": "codex"}) == evidence.AGENT_KIND
    assert authorship.of({"source": "cli", "origin": "mcp", "session_id": SID}) == evidence.AGENT_KIND
    assert authorship.of({"source": "cli", "origin": "mcp"}) is None
    assert authorship.of({"source": "cli", "origin": "mcp", "harness": "unknown"}) is None
    # A hook-captured session, a chat export, the person's app note: the markers decide, as before.
    assert authorship.of(SESSION_FM) is None
    assert authorship.of({"source": "claude-export", "origin": "claude-export"}) is None
    assert authorship.of({"source": "companion_app", "origin": "progress"}) is None
    # A declared kind always wins; another tool-door writer (a watch, a read) is a saved item by its own record.
    assert authorship.of({**NOTE_FM, "evidence_kind": "user"}) == "user"
    assert authorship.of({"source": "video-watch", "origin": "mcp", "url": "https://example.com/v",
                          "media_entity_id": "media-v"}) == evidence.SAVE_KIND


def test_every_span_the_person_would_have_is_the_agents():
    ov = authorship.of(NOTE_FM)
    kind = lambda quote, text=NOTE: evidence.verify(None, NOTE_ID, quote, text=text, kind_override=ov).kind  # noqa: E731
    assert kind("The person registered for alpha-event") == "assistant"
    assert kind("alpha-event is in alpha-city") == "assistant"
    assert kind("I signed up for alpha-event") == "assistant"        # a `user:` line the agent wrote is still its own
    # Nobody else's words become the agent's: a meeting's speaker, a video, a quoted document keep their kind.
    assert kind("alpha-project ships Friday", MEETING) == "speaker"
    assert kind("alpha-project in the demo", MEETING) == "media"
    assert kind("alpha-project plan", MEETING) == "page"
    # Without the record's word the old reading holds.
    assert evidence.verify(None, NOTE_ID, "alpha-event is in alpha-city", text=NOTE).kind == "user"


def test_turns_agree_with_the_span_kind_at_every_offset():
    ov = evidence.AGENT_KIND
    for text in (NOTE, MEETING):
        for t in evidence.turns(text, override=ov):
            for at in range(t.start, t.end):
                assert evidence.kind_for(NOTE_ID, text, at, ov) == t.role, (text[:20], at)
    assert {t.role for t in evidence.turns(NOTE, override=ov)} == {"assistant"}


# ---------- promotion ----------

def test_an_agent_note_is_no_exchange_in_the_persons_words():
    plain = NOTE.split("\n\nuser:")[0]   # four paragraphs, no marker: R4 read each as an exchange of the person's
    for text in (NOTE, plain):
        units = promotion.exchanges(text, override=authorship.of(NOTE_FM))
        count, named = promotion.measure(EVENT, units)
        assert named is False and not promotion.substantive({"mention_exchanges": count, "named_by_person": named})
    # The same words typed by the person in their own terminal are theirs, as before.
    own = promotion.exchanges(plain, override=authorship.of({"source": "cli", "origin": "mcp"}))
    count, named = promotion.measure(EVENT, own)
    assert named is True and count > promotion.MIN_EXCHANGES


def test_an_agents_notes_are_one_conversation_with_their_session(tmp_path):
    memory = _bank(tmp_path, (SESSION_ID, SESSION_FM, SESSION), (NOTE_ID, NOTE_FM, NOTE),
                   ("ep_2026-10-01_003", {**NOTE_FM, "id": "ep_2026-10-01_003"}, "another note on alpha-event"),
                   ("ep_2026-10-01_004", {"id": "ep_2026-10-01_004", "source": "mcp", "origin": "mcp"}, "no session"))
    assert promotion.conversation_keys([NOTE_ID, "ep_2026-10-01_003"], memory) == {f"session:{SID}"}
    assert promotion.conversation_keys([SESSION_ID, NOTE_ID], memory) == {f"session:{SID}"}
    assert promotion.conversation_keys(["ep_2026-10-01_004"], memory) == set()


# ---------- the person's own words (ruling 29's settle, the ask gate) ----------

def test_the_persons_words_are_found_only_where_they_said_them(tmp_path):
    memory = _bank(tmp_path, (SESSION_ID, SESSION_FM, SESSION), (NOTE_ID, NOTE_FM, NOTE))
    assert inbox_tend.persons_span(memory, NOTE_ID, "I signed up for alpha-event") is None
    assert inbox_tend.person_turns({**NOTE_FM, "content": NOTE}) == []
    # G118: a quote of the person located in the captured conversation still points at their own `user` span.
    span = inbox_tend.persons_span(memory, SESSION_ID, "I signed up for alpha-event")
    assert span is not None and span.kind == "user"
    evs = evidence.verify_many(memory, [{"episode": SESSION_ID, "quote": "I signed up for alpha-event"},
                                        {"episode": NOTE_ID, "quote": "I signed up for alpha-event"}])
    assert sorted(e.kind for e in evs) == ["assistant", "user"]


# ---------- Stage 1: the speaker model and the observer ----------

def test_stage_one_is_told_whose_note_it_is_and_gives_the_agent_its_claims():
    episode = {**NOTE_FM, "content": NOTE}
    assert entity_extractor.assistant_observer(episode) == "external:claude-code"
    note = entity_extractor.agent_save_note(episode)
    assert note and "Claude Code" in note and "never the person's own words" in note
    remote = {"source": "mcp-remote", "origin": "mcp", "harness": "claude-ai"}
    assert entity_extractor.assistant_observer(remote) == "external:claude-ai"
    assert "an AI agent" in entity_extractor.agent_save_note({"source": "mcp", "origin": "mcp"})
    # A captured session and the person's own CLI note get no such note.
    assert entity_extractor.agent_save_note(SESSION_FM) is None
    assert entity_extractor.agent_save_note({"source": "cli", "origin": "mcp"}) is None
    rel = {"evidence": [evidence.verify(None, NOTE_ID, "alpha-event is in alpha-city", text=NOTE,
                                        kind_override=authorship.of(NOTE_FM)).to_dict()]}
    assert entity_extractor._observer_for(rel, entity_extractor.assistant_observer(episode), [], NOTE) \
        == "external:claude-code"
    assert not promotion.person_said({**rel, "observer": "external:claude-code"})


def test_ask_names_the_note_by_its_agent_and_the_persons_cli_note_as_theirs():
    assert episode_actor.actor(NOTE_FM, ids=False) == "an agent's saved note from a Claude Code session"
    assert episode_actor.actor({"source": "mcp", "origin": "mcp"}) == "an agent's saved note"
    assert episode_actor.actor({"source": "cli", "origin": "mcp"}) is None


# ---------- the command line stamps the shell's harness ----------

def test_a_cli_save_from_an_agents_shell_names_its_harness(monkeypatch, tmp_path):
    from api import cli, cli_app

    boot = SimpleNamespace(pin=SimpleNamespace(path=tmp_path), backend_url="http://127.0.0.1:1", caller_cwd=None)
    none = SimpleNamespace(session_id=None, harness=None, project_dir=None)
    monkeypatch.setattr(cli, "_identity", lambda: none)
    monkeypatch.setattr(cli, "_backend_headers", lambda: {})
    monkeypatch.setattr(cli_app, "agent_shell", lambda environ=None: "codex")
    ctx = cli._tool_context(boot)
    assert ctx.session_frontmatter() == {"harness": "codex"}
    assert authorship.agent_saved({"source": "cli", **ctx.session_frontmatter()})
    monkeypatch.setattr(cli_app, "agent_shell", lambda environ=None: None)
    ctx = cli._tool_context(boot)
    assert ctx.session_frontmatter() == {}
    assert not authorship.agent_saved({"source": "cli", **ctx.session_frontmatter()})
