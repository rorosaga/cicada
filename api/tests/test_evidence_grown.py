"""G118 slice 2 (A7) — a span in a conversation that CONTINUED is `grown`, not `stale`.

Slice 1 compared a span's stored hash with the whole current text, so every
span in a Stop-hook episode read `stale` the moment the session took another
turn (the hook rewrites the session's ONE episode in place with appended
turns — G104/G105), and every span in a G20-grown chat export did the same.
`evidence.span_status` tries the turn-boundary prefixes before giving up:
exact, never fuzzy, one pass. Fixtures are synthetic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import conversations as conv
from api.services import bank_index, evidence, inbox_service, markdown_parser
from api.services import transcript_capture as tc
from api.services.claims import Claim, Evidence, write_claims

BODY = (
    "user: Should alpha-project move to sqlite-vec?\n"
    "assistant: Yes — bob-example agreed last week.\n"
    "user: Then ship it."
)
GROWN = BODY + "\nassistant: Shipped.\nuser: Thanks."
SID = "22222222-3333-4444-8555-666666666666"


def _span(text: str, quote: str) -> tuple[int, int]:
    start = text.index(quote)
    return start, start + len(quote)


# ---------- turn_starts: the lines speaker_kind reads, and nothing else ----------


def test_turn_starts_are_exactly_the_marker_lines_speaker_kind_reads():
    text = "preamble\nuser: a\nb\nASSISTANT:  c\nsystem: d\nunknown: e\nAI: f"
    starts = evidence.turn_starts(text)
    assert starts == [text.index("user:"), text.index("ASSISTANT:"), text.index("system:"),
                      text.index("unknown:"), text.index("AI:")]
    assert [evidence.speaker_kind(text, s) for s in starts] == ["user", "assistant", "user", "user", "assistant"]


def test_a_marker_less_document_has_no_turn_starts():
    assert evidence.turn_starts("A note with no speaker lines.\nuser mentioned: nothing") == []


# ---------- span_status ----------


def test_current_when_the_hash_matches_or_none_was_given():
    _s, e = _span(BODY, "bob-example agreed")
    assert evidence.span_status(BODY, end=e, hash=evidence.body_hash(BODY)) == evidence.SPAN_CURRENT
    assert evidence.span_status(BODY, end=e, hash="") == evidence.SPAN_CURRENT
    assert evidence.span_status(BODY, end=e, hash=None) == evidence.SPAN_CURRENT


def test_grown_when_turns_were_appended_after_the_span_was_minted():
    s, e = _span(BODY, "bob-example agreed")
    assert evidence.span_status(GROWN, end=e, hash=evidence.body_hash(BODY)) == evidence.SPAN_GROWN
    assert GROWN[s:e] == BODY[s:e]  # the offsets still mean the same words


def test_stale_when_a_byte_before_the_span_changed():
    _s, e = _span(BODY, "bob-example agreed")
    edited = GROWN.replace("Should", "Shall")
    assert evidence.span_status(edited, end=e, hash=evidence.body_hash(BODY)) == evidence.SPAN_STALE


def test_stale_when_the_matching_prefix_ends_before_the_span():
    # The only prefix hashing to the old value is BODY itself; a span that
    # reaches past it cannot have been minted against it.
    _s, e = _span(GROWN, "Shipped")
    assert evidence.span_status(GROWN, end=e, hash=evidence.body_hash(BODY)) == evidence.SPAN_STALE


def test_a_page_never_grows():
    _s, e = _span(BODY, "bob-example agreed")
    assert evidence.span_status(GROWN, end=e, hash=evidence.body_hash(BODY),
                                appendable=False) == evidence.SPAN_STALE


def test_grown_is_exact_across_non_ascii_text():
    base = "user: café 🙂 naïve résumé\nassistant: 東京 ok"
    _s, e = _span(base, "東京")
    assert evidence.span_status(base + "\nuser: more 🙂", end=e,
                                hash=evidence.body_hash(base)) == evidence.SPAN_GROWN


# ---------- through the real writers ----------


def _line(typ: str, content, ts: str = "2026-09-03T10:00:00.000Z") -> str:
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID,
                       "cwd": "/home/example/alpha-project", "message": {"role": typ, "content": content}})


def _transcript(turns: list[tuple[str, str]]) -> str:
    return "\n".join(_line(r, t if r == "user" else [{"type": "text", "text": t}]) for r, t in turns) + "\n"


@pytest.fixture
def bank(tmp_path: Path, monkeypatch) -> Path:
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    projects = tmp_path / "claude-projects"
    (projects / "-home-example-alpha-project").mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: projects)
    monkeypatch.setattr(tc, "_episode_cache", {})
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


def test_a_stop_hook_episode_that_took_another_turn_reads_grown_not_stale(bank, tmp_path):
    transcript = tmp_path / "claude-projects" / "-home-example-alpha-project" / f"{SID}.jsonl"
    first = [("user", "Should alpha-project move to sqlite-vec?"),
             ("assistant", "Yes — bob-example agreed last week.")]
    transcript.write_text(_transcript(first), encoding="utf-8")
    r1 = tc.capture_transcript(bank, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                               cwd=None, keep_assistant=True)
    ev = evidence.verify(bank, r1.episode_id, "bob-example agreed")
    assert ev.is_span() and ev.kind == "assistant"

    transcript.write_text(_transcript(first + [("user", "Then ship it."), ("assistant", "Shipped.")]),
                          encoding="utf-8")
    r2 = tc.capture_transcript(bank, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                               cwd=None, keep_assistant=True)
    assert r2.status == "updated" and r2.episode_id == r1.episode_id

    params = {"start": ev.start, "end": ev.end, "hash": ev.hash}
    with TestClient(main.app) as client:
        grown = client.get(f"/episodes/{ev.episode}/span", params=params).json()
        assert grown["stale"] is False and grown["grown"] is True
        assert grown["text"] == "bob-example agreed"

        # A byte edited BEFORE the span: nothing may be highlighted.
        path = bank / "episodes" / f"{ev.episode}.md"
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, parsed.frontmatter, parsed.body.replace("Should", "Shall", 1))
        stale = client.get(f"/episodes/{ev.episode}/span", params=params).json()
    assert stale["stale"] is True and stale["grown"] is False


def test_a_current_span_reports_grown_false(bank):
    markdown_parser.write(bank / "episodes" / "ep_2026-09-01_001.md", {"id": "ep_2026-09-01_001"}, BODY)
    s, e = _span(BODY, "bob-example agreed")
    with TestClient(main.app) as client:
        data = client.get("/episodes/ep_2026-09-01_001/span",
                          params={"start": s, "end": e, "hash": evidence.body_hash(BODY)}).json()
    assert data["stale"] is False and data["grown"] is False


def test_a_grown_chat_export_reads_grown(tmp_path):
    def export(messages):
        return [{"uuid": "uuid-grow", "name": "Planning", "created_at": "2026-02-24T12:39:00.000000Z",
                 "updated_at": f"2026-02-24T13:{len(messages):02d}:00.000000Z",
                 "chat_messages": [{"uuid": f"m{i}", "sender": s, "text": t, "content": [],
                                    "created_at": f"2026-02-24T12:39:{i:02d}.000000Z"}
                                   for i, (s, t) in enumerate(messages)]}]

    ep_dir = tmp_path / "episodes"
    first = [("human", "Does alpha-project use sqlite-vec?"), ("assistant", "Yes, since last week.")]
    conv._stage_episodes(conv.parse_anthropic_conversations(export(first)), ep_dir)
    path = next(ep_dir.glob("*.md"))
    ev = evidence.verify(tmp_path, path.stem, "since last week")
    conv._stage_episodes(conv.parse_anthropic_conversations(export(first + [("human", "Great.")])), ep_dir)
    text = evidence.source_text(tmp_path, path.stem)
    assert text.endswith("user: Great.")
    assert evidence.span_status(text, end=ev.end, hash=ev.hash) == evidence.SPAN_GROWN


def test_the_inbox_cause_keeps_its_asserted_span_when_the_conversation_continued(tmp_path):
    bank_index.invalidate()
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    (memory / "inbox").mkdir()
    ep_path = memory / "episodes" / "ep_2026-08-20_001.md"
    first = "user: Bob Example moved to beta-corp last week."
    markdown_parser.write(ep_path, {"id": "ep_2026-08-20_001", "timestamp": "2026-08-20T10:00:00+00:00",
                                    "title": "Planning", "session_id": "ses_2026-08-20_abcdef12",
                                    "harness": "claude-code", "origin": "claude-code", "processed": True}, first)
    s, e = _span(first, "moved to beta-corp")
    claim = Claim(id="clm_2026-08-20_b2", text="Bob Example works at beta-corp", subject="bob-example",
                  predicate="works-at", object="beta-corp", valid_from="2026-08-20", recorded_at="2026-08-20",
                  source_episodes=["ep_2026-08-20_001"],
                  evidence=[Evidence(episode="ep_2026-08-20_001", start=s, end=e, kind="user",
                                     hash=evidence.body_hash(first))])
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active", "confidence": 0.6,
                           "created": "2026-08-01", "last_referenced": "2026-08-20", "source_episodes": [],
                           "tags": [], "related": [], "version": 1},
                          write_claims("# Bob Example\n", [claim]))
    markdown_parser.write(memory / "inbox" / "inbox-005.md",
                          {"status": "pending", "required_input": "choice", "created_date": "2026-08-21",
                           "kind": "conflict", "entity_id": "bob-example", "entity_name": "Bob Example",
                           "title": "q", "predicate": "works-at", "question": "q?",
                           "claim_id": "clm_2026-08-20_b2",
                           "options": [{"key": "b", "label": "beta-corp", "claim_id": "clm_2026-08-20_b2"}]},
                          "ctx")
    # The conversation continued after Sleep minted the span.
    markdown_parser.write(ep_path, markdown_parser.parse(ep_path).frontmatter,
                          first + "\nassistant: Noted.\nuser: And bob-example starts Monday.")
    [item] = inbox_service.load_inbox(memory)
    assert item.cause.span_kind == "asserted"
    ms, me = item.cause.mention_offsets[0]
    assert item.cause.excerpt[ms:me] == "moved to beta-corp"
