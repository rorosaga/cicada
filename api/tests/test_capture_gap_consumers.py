"""G110 gate B2, fix round 1 (review blocker 1): the dropped-middle marker is
Cicada's own line, never a speaker's — for every consumer, not only `verify`.

At the REAL 100,000-character cap, with the head ending on a person's turn:
the Reader gives the marker its own `gap` block (the person's turn ends before
it), turn numbering skips it, a focus on it never highlights, search neither
indexes its words nor returns it as anyone's span, the span route names it
`gap`, and Sleep's extraction prompt receives it as a labelled note, never as
conversation text. A person who TYPES marker-like text inside a turn keeps it as
their words.

Fix round 2: a gap exists ONLY where the episode's own `capture_gap` says, at a
validated offset (`evidence.gap_ranges`) — never inferred from words. Without
capture metadata, a pasted marker line and everything after it stay the
person's; Sleep masks the authoritative range on the WHOLE body before the
production chunker slices it, so no chunk carries an unlabelled fragment.
Synthetic transcripts only."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.config import Settings
from api.services import (
    entity_extractor, evidence, markdown_parser, provenance, providers, search_index, search_service, sleep_cycle,
    transcript_extract,
)
from api.tests.test_capture_metadata import _capture, _episode, _fresh, memory, roots  # noqa: F401 - fixtures

#: 1,000-character turns; turn 59 (the head's last, at the real 60k head) is the person's.
TURNS = [("user" if i % 2 == 0 or i == 59 else "assistant", (f"turn {i:03d} " + "word " * 220)[:1000])
         for i in range(140)]


@pytest.fixture
def ep(roots, memory):
    assert transcript_extract.SESSION_CAP_CHARS == 100_000
    r = _capture(roots, memory, TURNS)
    doc = markdown_parser.parse(_episode(memory, r))
    marker = next(line for line in doc.body.split("\n") if evidence.is_gap_line(line))
    at = doc.body.index(marker)
    assert doc.frontmatter["capture_gap"]["offset"] == at          # the authoritative range is stored
    gaps = evidence.gap_ranges(doc.frontmatter, doc.body)
    assert gaps == ((at, at + len(marker)),)
    return SimpleNamespace(id=r.episode_id, fm=doc.frontmatter, body=doc.body, marker=marker, at=at,
                           memory=memory, gaps=gaps)


def test_the_reader_gives_the_marker_its_own_non_speaker_block(ep):
    text = provenance.episode_document(ep.memory, ep.id)
    gap = [t for t in text.turns if t.role == "gap"]
    assert len(gap) == 1 and ep.body[gap[0].content_start:gap[0].end] == ep.marker
    before = next(t for t in text.turns if t.end <= gap[0].start and t.start <= ep.at - 2 < t.end)
    assert before.role == "user" and "[Cicada:" not in ep.body[before.content_start:before.end]
    assert all(t.role in ("user", "assistant", "gap") for t in text.turns)


def test_turn_numbering_counts_turns_not_the_marker(ep):
    stamps = evidence.turn_stamps(ep.fm)
    last = max(stamps)
    hit = evidence.turn_at(ep.body, last, stamps, gaps=ep.gaps)
    assert hit["number"] == hit["of"] == ep.fm["turn_count"]


def test_a_span_on_the_marker_is_never_a_speaker_and_never_highlights(ep):
    start, end = ep.at + 1, ep.at + 20
    assert evidence.kind_for(ep.id, ep.body, start, gaps=ep.gaps) == "gap"
    assert evidence.speaker_kind(ep.body, start, gaps=ep.gaps) == "gap"
    assert evidence.verify(None, ep.id, ep.marker[1:30], text=ep.body, gaps=ep.gaps).kind == "reasoning"
    assert evidence.verify(ep.memory, ep.id, ep.marker[1:30]).kind == "reasoning"       # read from disk: its own fm
    focus = provenance._asserted_focus(ep.id, ep.body, start, end, evidence.body_hash(ep.body), is_episode=True,
                                       gaps=ep.gaps)
    assert focus.start is None and focus.end is None and focus.kind == "gap"


def test_search_neither_indexes_the_marker_nor_returns_it_as_a_span(ep):
    # The rows FTS stores tile the body with the marker blanked to spaces: offsets hold, the words are gone.
    masked = evidence.mask_gaps(ep.body, ep.gaps)
    assert len(masked) == len(ep.body) and "[Cicada:" not in masked and "were not kept" not in masked
    assert masked[: ep.at] == ep.body[: ep.at]
    search_index.rebuild(ep.memory)
    hits = search_service.search(ep.memory, "kept", kinds=["episode"], mode="prefix").results
    assert not any(h.episode_id == ep.id for h in hits)
    # A hit whose line is the marker (raw text, as a stale or foreign index might hold) carries no span or kind.
    doc = SimpleNamespace(id=1, ref=ep.id, meta={"hash": evidence.body_hash(ep.body), "gaps": [list(ep.gaps[0])]})
    ctx = SimpleNamespace(tokens=["cicada"], reader=SimpleNamespace(
        episode_passages=lambda *a, **k: [(1, 0, len(ep.body), ep.body)]))
    hit = search_service._episode_hit(ctx, SimpleNamespace(doc=doc, passage=(1, 0, len(ep.body)), label="body"), 1.0)
    assert hit.evidence_kind is None and hit.start is None and hit.hash is None


def _sleep_prompts(memory) -> list[str]:
    """Stage 1 over the bank's queue, through the real loader and chunker; the
    completion is fake and records each user message."""
    seen: list[str] = []

    async def fake(**kw):
        seen.append(kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    episodes = sleep_cycle._get_unprocessed_episodes(memory)
    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake):
        asyncio.run(entity_extractor.extract(episodes, Settings(_env_file=None)))
    return seen


def test_sleep_reads_the_marker_as_a_separate_note_not_conversation(ep):
    sent = _sleep_prompts(ep.memory)
    assert sent and all("[Cicada:" not in m and "were not kept" not in m for m in sent)
    noted = [m for m in sent if entity_extractor.GAP_NOTE_PREFIX in m]
    assert len(noted) >= 1
    for m in noted:
        assert m.startswith(entity_extractor.GAP_NOTE_PREFIX)        # the note leads, apart from the conversation


def test_a_production_chunk_starting_inside_the_marker_carries_no_fragment(roots, memory):
    """Review r2: at the real cap, 3,621 alternating 28-character turns put the
    marker at [80325, 80417) and the production chunker starts a chunk inside
    it. The body is masked before slicing, so the fragment never reaches the
    model, and that chunk is told about the gap separately."""
    turns = [("user" if i % 2 == 0 else "assistant", (f"turn {i:05d} " + "word " * 220)[:28]) for i in range(3621)]
    r = _capture(roots, memory, turns)
    doc = markdown_parser.parse(_episode(memory, r))
    (g0, g1), = evidence.gap_ranges(doc.frontmatter, doc.body)
    inside = [(s, e) for s, e in entity_extractor._chunk_spans(doc.body) if g0 < s < g1]
    assert inside, "the fixture must reproduce a chunk that starts inside the marker"
    sent = _sleep_prompts(memory)
    assert all("were not kept" not in m and "[Cicada:" not in m for m in sent)
    assert sum(entity_extractor.GAP_NOTE_PREFIX in m for m in sent) >= 2      # both chunks that touch the gap


def test_a_pasted_marker_line_and_the_words_after_it_stay_the_persons(roots, memory):
    """Review r2: no `capture_gap`, so no gap — whatever the words look like."""
    typed = "I pasted the marker below.\n[Cicada: 3 turns were not kept]\nPlease fix alpha-project next."
    r = _capture(roots, memory, [("user", typed), ("assistant", "On it.")])
    doc = markdown_parser.parse(_episode(memory, r))
    body, fm = doc.body, doc.frontmatter
    assert "capture_gap" not in fm and evidence.gap_ranges(fm, body) == ()
    text = provenance.episode_document(memory, r.episode_id)
    assert [t.role for t in text.turns] == ["user", "assistant"]
    assert "Please fix alpha-project next." in body[text.turns[0].content_start:text.turns[0].end]
    for quote in ("Please fix alpha-project next.", "[Cicada: 3 turns were not kept]"):
        assert evidence.verify(memory, r.episode_id, quote).kind == "user", quote
    assert evidence.speaker_kind(body, body.index("Please fix")) == "user"
    assert evidence.mask_gaps(body, evidence.gap_ranges(fm, body)) == body
    sent = _sleep_prompts(memory)
    assert any("[Cicada: 3 turns were not kept]\nPlease fix alpha-project next." in m for m in sent)
    assert not any(entity_extractor.GAP_NOTE_PREFIX in m for m in sent)


def test_an_edited_or_older_marker_is_still_found_by_its_stored_record(ep):
    # Edited at its stored offset: the line there is still Cicada's.
    edited = ep.body[: ep.at] + "[Cicada: some turns were not kept here]" + ep.body[ep.at + len(ep.marker):]
    (g0, g1), = evidence.gap_ranges(ep.fm, edited)
    assert edited[g0:g1] == "[Cicada: some turns were not kept here]"
    assert evidence.speaker_kind(edited, g0 + 3, gaps=((g0, g1),)) == "gap"
    # An episode from before the stored offset (or a shifted body): the ONE line that spells its own record.
    legacy = {k: v for k, v in ep.fm["capture_gap"].items() if k != "offset"}
    shifted = "user: an edit added this line\n" + ep.body
    for fm_gap, body in ((legacy, ep.body), (ep.fm["capture_gap"], shifted)):
        (h0, h1), = evidence.gap_ranges({"capture_gap": fm_gap}, body)
        assert body[h0:h1] == ep.marker
    # A record that matches nothing in the body names no gap at all.
    assert evidence.gap_ranges({"capture_gap": {"dropped_turns": 999}}, ep.body) == ()


def test_an_agent_reading_an_episode_s_text_sees_cicada_s_note_not_the_marker(ep):
    from api.services import entity_sources
    labelled = evidence.label_gaps(ep.body, ep.gaps)
    assert ep.marker not in labelled and evidence.GAP_NOTE in labelled
    page = ep.memory / "entities" / "alpha-project.md"
    page.parent.mkdir(exist_ok=True)
    markdown_parser.write(page, {"name": "alpha-project", "source_episodes": [ep.id]}, "")
    chunk = entity_sources.gather_entity_sources(ep.memory, "alpha-project")["episodes"][0]["chunk"]
    assert ep.marker not in chunk and evidence.GAP_NOTE in chunk
