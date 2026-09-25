"""G118 slice 1 — `api.services.evidence`: the engine-free span module.

Every fixture is synthetic. Covers R1 (text normalisation), R2 (hash), R3
(document resolution incl. path-traversal refusal), R4 (speaker kind), R5
(the locate ladder and its refusal to go fuzzy), R6 (reasoning fallback).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from api.services import evidence, markdown_parser
from api.services.claims import Claim, Evidence, write_claims

EPISODE = (
    "user: I moved the alpha-project index to sqlite-vec last week.\n"
    "assistant: Noted — sqlite-vec replaces LEANN for alpha-project.\n"
    "user: Yes,   and bob-example   reviewed the migration."
)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md",
                          {"id": "ep_2026-09-01_001", "processed": False}, EPISODE)
    page_body = "## Summary\nSaved bookmark.\n\n## Description\nA guide to ROS and sqlite-vec for robotics."
    markdown_parser.write(memory / "entities" / "media-ros-guide.md",
                          {"name": "ROS guide", "type": "media"},
                          write_claims(page_body, [Claim(id="clm_a", text="x")]))
    return memory


def test_body_hash_is_sha256_twelve_hex():
    assert evidence.body_hash("abc") == hashlib.sha256(b"abc").hexdigest()[:12]
    assert evidence.body_hash("") == hashlib.sha256(b"").hexdigest()[:12]


def test_source_text_is_the_parsed_body_for_an_episode(tmp_path):
    memory = _bank(tmp_path)
    assert evidence.source_text(memory, "ep_2026-09-01_001") == EPISODE  # R1: parse().body, already stripped


def test_source_text_strips_the_claims_block_for_an_entity_page(tmp_path):
    memory = _bank(tmp_path)
    text = evidence.source_text(memory, "media-ros-guide")
    assert text.endswith("for robotics.")
    assert "```claims" not in text
    # R1: appending another claim must not change the evidence text.
    fp = memory / "entities" / "media-ros-guide.md"
    parsed = markdown_parser.parse(fp)
    markdown_parser.write(fp, parsed.frontmatter, write_claims(parsed.body, [Claim(id="clm_a", text="x"), Claim(id="clm_b", text="y")]))
    assert evidence.source_text(memory, "media-ros-guide") == text


def test_source_path_refuses_traversal_and_unknown_docs(tmp_path):
    memory = _bank(tmp_path)
    assert evidence.source_path(memory, "../episodes/ep_2026-09-01_001") is None
    assert evidence.source_path(memory, "ep_2026-09-01_001/../../x") is None
    assert evidence.source_path(memory, "") is None
    assert evidence.source_path(memory, "ep_2026-01-01_999") is None
    assert evidence.source_text(memory, "nope") is None


def test_locate_exact_then_normalised_then_case_insensitive_never_fuzzy():
    assert evidence.locate(EPISODE, "moved the alpha-project index") == (8, 37)
    # whitespace-normalised: the quote collapses the body's runs of spaces
    s, e = evidence.locate(EPISODE, "Yes, and bob-example reviewed")
    assert EPISODE[s:e] == "Yes,   and bob-example   reviewed"
    # case-insensitive
    s, e = evidence.locate(EPISODE, "SQLITE-VEC REPLACES leann")
    assert EPISODE[s:e] == "sqlite-vec replaces LEANN"
    # never fuzzy: one wrong word is a miss
    assert evidence.locate(EPISODE, "moved the beta-project index") is None
    assert evidence.locate(EPISODE, "") is None
    assert evidence.locate("", "x") is None


def test_locate_prefers_the_window_then_falls_back_to_first_occurrence():
    text = "user: alpha-project\nassistant: alpha-project again\nuser: alpha-project once more"
    first = text.find("alpha-project")
    third = text.rfind("alpha-project")
    assert evidence.locate(text, "alpha-project") == (first, first + 13)
    assert evidence.locate(text, "alpha-project", window=(40, len(text))) == (third, third + 13)
    # window contains no occurrence -> first overall, not None
    assert evidence.locate(text, "alpha-project", window=(0, 3)) == (first, first + 13)


def test_locate_clips_overlong_quotes_to_240_chars():
    body = "user: " + ("x" * 300) + " tail"
    quote = "x" * 300
    s, e = evidence.locate(body, quote)
    assert (s, e) == (6, 6 + evidence.MAX_QUOTE_CHARS)


def test_locate_whole_word_never_matches_inside_a_longer_token():
    text = "Google ships Go tooling"
    assert evidence.locate(text, "Go", whole_word=True) == (13, 15)
    assert evidence.locate("Google only", "Go", whole_word=True) is None
    assert evidence.locate("Google only", "Go") == (0, 2)  # the plain rung is substring


def test_speaker_kind_follows_the_last_turn_marker_and_defaults_to_user():
    assert evidence.speaker_kind(EPISODE, EPISODE.find("moved")) == "user"
    assert evidence.speaker_kind(EPISODE, EPISODE.find("replaces")) == "assistant"
    assert evidence.speaker_kind(EPISODE, EPISODE.find("reviewed")) == "user"
    assert evidence.speaker_kind("AI: done\nHuman: thanks", 4) == "assistant"
    assert evidence.speaker_kind("AI: done\nHuman: thanks", 16) == "user"
    assert evidence.speaker_kind("system: project notes", 8) == "user"  # R4
    assert evidence.speaker_kind("no markers at all here", 5) == "user"  # R4
    # R4 "at": a quote that begins ON the marker line's first character still
    # belongs to that marker, not to the previous turn.
    assert evidence.speaker_kind(EPISODE, EPISODE.find("assistant:")) == "assistant"
    # R4: `unknown:` (an export message with no role) resets to user rather
    # than inheriting the assistant marker above it.
    assert evidence.speaker_kind("assistant: a\nunknown: b", 16) == "user"


def test_verify_returns_a_span_for_an_episode_and_page_kind_for_an_entity(tmp_path):
    memory = _bank(tmp_path)
    ev = evidence.verify(memory, "ep_2026-09-01_001", "sqlite-vec replaces LEANN")
    assert ev == Evidence(episode="ep_2026-09-01_001", start=EPISODE.find("sqlite-vec replaces"),
                          end=EPISODE.find("LEANN") + 5, kind="assistant", hash=evidence.body_hash(EPISODE))
    page = evidence.verify(memory, "media-ros-guide", "ROS", whole_word=True)
    text = evidence.source_text(memory, "media-ros-guide")
    assert page.kind == "page" and text[page.start:page.end] == "ROS" and page.hash == evidence.body_hash(text)


def test_verify_falls_back_to_reasoning_never_a_faked_span(tmp_path):
    memory = _bank(tmp_path)
    miss = evidence.verify(memory, "ep_2026-09-01_001", "something nobody said")
    assert miss == Evidence(episode="ep_2026-09-01_001", start=-1, end=-1, kind="reasoning",
                            hash=evidence.body_hash(EPISODE))  # doc readable -> hash kept
    gone = evidence.verify(memory, "ep_2026-01-01_999", "anything")
    assert gone == Evidence(episode="ep_2026-01-01_999", start=-1, end=-1, kind="reasoning", hash="")
    assert evidence.verify(memory, "", "anything") == Evidence()
    assert evidence.reasoning("ep_x") == Evidence(episode="ep_x", start=-1, end=-1, kind="reasoning", hash="")


def test_verify_with_inline_text_needs_no_disk(tmp_path):
    # `memory_path=None` + `text=` never touches disk (R11). The quote is
    # whitespace-collapsed; the span slices the BODY's own spacing back out —
    # offsets into stored text, never the caller's copy (R5).
    ev = evidence.verify(None, "ep_2026-09-01_001", "bob-example reviewed", text=EPISODE)
    assert EPISODE[ev.start:ev.end] == "bob-example   reviewed" and ev.kind == "user"
    assert ev.is_span() and ev.hash == evidence.body_hash(EPISODE)


def test_verify_many_skips_junk_and_dedupes(tmp_path):
    memory = _bank(tmp_path)
    out = evidence.verify_many(memory, [
        {"episode": "ep_2026-09-01_001", "quote": "moved the alpha-project index"},
        {"episode": "ep_2026-09-01_001", "quote": "moved the alpha-project index"},
        {"quote": "no episode"},
        "junk",
        {"episode": "ep_2026-09-01_001", "quote": "not in there"},
    ])
    assert len(out) == 2
    assert out[0].is_span() and out[1].kind == "reasoning"
    assert evidence.verify_many(memory, None) == []
    # An optional `window` item key (internal — writers that know the section)
    # prefers an occurrence inside it: "alpha-project" first appears at 18
    # (line 1) and again at 112 (line 2); the window selects the second.
    (win,) = evidence.verify_many(memory, [
        {"episode": "ep_2026-09-01_001", "quote": "alpha-project", "window": [60, len(EPISODE)]}])
    assert win.is_span() and win.start >= 60 and EPISODE[win.start:win.end] == "alpha-project"


def test_attach_relationship_evidence_pops_the_quote_and_records_offsets():
    rel = {"source": "alpha-project", "target": "sqlite-vec", "label": "uses",
           "evidence_quote": "moved the alpha-project index to sqlite-vec"}
    evidence.attach_relationship_evidence(rel, "ep_2026-09-01_001", EPISODE, window=(0, 70))
    assert "evidence_quote" not in rel  # spans, not copies — even in the transient dict
    (ev,) = rel["evidence"]
    assert ev["kind"] == "user" and EPISODE[ev["start"]:ev["end"]] == "moved the alpha-project index to sqlite-vec"
    assert ev["hash"] == evidence.body_hash(EPISODE)
    bare = {"source": "a", "target": "b", "label": "uses"}
    evidence.attach_relationship_evidence(bare, "ep_2026-09-01_001", EPISODE)
    assert bare["evidence"] == [{"episode": "ep_2026-09-01_001", "start": -1, "end": -1,
                                 "kind": "reasoning", "hash": evidence.body_hash(EPISODE)}]
