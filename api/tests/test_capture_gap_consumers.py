"""G110 gate B2, fix round 1 (review blocker 1): the dropped-middle marker is
Cicada's own line, never a speaker's — for every consumer, not only `verify`.

At the REAL 100,000-character cap, with the head ending on a person's turn:
the Reader gives the marker its own `gap` block (the person's turn ends before
it), turn numbering skips it, a focus on it never highlights, search neither
indexes its words nor returns it as anyone's span, the span route names it
`gap`, and Sleep's extraction prompt receives it as a labelled note, never as
conversation text. A person who TYPES marker-like text inside a turn keeps it as
their words. Synthetic transcripts only."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.config import Settings
from api.services import (
    entity_extractor, evidence, markdown_parser, provenance, providers, search_index, search_service,
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
    return SimpleNamespace(id=r.episode_id, fm=doc.frontmatter, body=doc.body, marker=marker, at=at,
                           memory=memory)


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
    hit = evidence.turn_at(ep.body, last, stamps)
    assert hit["number"] == hit["of"] == ep.fm["turn_count"]


def test_a_span_on_the_marker_is_never_a_speaker_and_never_highlights(ep):
    start, end = ep.at + 1, ep.at + 20
    assert evidence.kind_for(ep.id, ep.body, start) == "gap"
    assert evidence.speaker_kind(ep.body, start) == "gap"
    assert evidence.verify(None, ep.id, ep.marker[1:30], text=ep.body).kind == "reasoning"
    focus = provenance._asserted_focus(ep.id, ep.body, start, end, evidence.body_hash(ep.body), is_episode=True)
    assert focus.start is None and focus.end is None and focus.kind == "gap"


def test_search_neither_indexes_the_marker_nor_returns_it_as_a_span(ep):
    # The rows FTS stores tile the body with the marker blanked to spaces: offsets hold, the words are gone.
    masked = evidence.mask_gaps(ep.body)
    assert len(masked) == len(ep.body) and "[Cicada:" not in masked and "were not kept" not in masked
    assert masked[: ep.at] == ep.body[: ep.at]
    search_index.rebuild(ep.memory)
    hits = search_service.search(ep.memory, "kept", kinds=["episode"], mode="prefix").results
    assert not any(h.episode_id == ep.id for h in hits)
    # A hit whose line is the marker (raw text, as a stale or foreign index might hold) carries no span or kind.
    doc = SimpleNamespace(id=1, ref=ep.id, meta={"hash": evidence.body_hash(ep.body)})
    ctx = SimpleNamespace(tokens=["cicada"], reader=SimpleNamespace(
        episode_passages=lambda *a, **k: [(1, 0, len(ep.body), ep.body)]))
    hit = search_service._episode_hit(ctx, SimpleNamespace(doc=doc, passage=(1, 0, len(ep.body)), label="body"), 1.0)
    assert hit.evidence_kind is None and hit.start is None and hit.hash is None


def test_sleep_reads_the_marker_as_a_labelled_note_not_conversation(ep):
    seen = []

    async def fake(**kw):
        seen.append(kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    chunk = ep.body[ep.at - 300: ep.at + len(ep.marker) + 300]                # a chunk crossing the gap
    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake):
        asyncio.run(entity_extractor._extract_chunk(ep.id, chunk, 0, 1, Settings(_env_file=None)))
    sent = seen[0]
    assert ep.marker not in sent and "[Cicada:" not in sent
    assert entity_extractor.GAP_NOTE_PREFIX in sent and "user: turn 059" not in sent[sent.index(entity_extractor.GAP_NOTE_PREFIX):]
    assert len(sent.splitlines()) == len(chunk.splitlines())


def test_marker_like_words_a_person_typed_inside_a_turn_stay_theirs(roots, memory):
    typed = "I saw this in the episode: [Cicada: 3 turns were not kept] — is that a bug?"
    r = _capture(roots, memory, [("user", typed), ("assistant", "It marks a gap.")])
    body = markdown_parser.parse(_episode(memory, r)).body
    assert evidence.speaker_kind(body, body.index("[Cicada:")) == "user"
    assert evidence.mask_gaps(body) == body
    assert evidence.verify(None, r.episode_id, "[Cicada: 3 turns were not kept]", text=body).kind == "user"
