"""G188 — the opt-in agent detector registry, Instinct first, and the person's override.

The spec's acceptance, one test each: a synthetic Instinct match is recognized when enabled; a similarly named human
is not confidently classified; ambiguous cases are surfaced; an override survives the next sync (in
``test_messages_source``); removing the detector keeps ordinary capture and every saved conversation. Synthetic names
and counts only."""
from __future__ import annotations

import pytest

from api.services import agent_detectors as ad
from api.services import messages_source

INSTINCT_CADENCE = {"from_me": 191, "from_them": 716}   # the measured shape of the owner's conversation
HUMAN_CADENCE = {"from_me": 120, "from_them": 131}


def _meta(name, **counts):
    return ad.ConversationMeta(name=name, **counts)


def test_instinct_with_an_agents_cadence_is_identified():
    found = ad.detect(_meta("Instinct", **INSTINCT_CADENCE))
    assert (found.outcome, found.detector, found.version, found.signal, found.label) == (
        ad.IDENTIFIED, "instinct", 1, "name+cadence", "Instinct")


@pytest.mark.parametrize("name", ["instinct", "INSTINCT ", "Instinct 🤖", "Instinct AI", "Ínstinct"])
def test_the_name_is_compared_folded(name):
    assert ad.detect(_meta(name, **INSTINCT_CADENCE)).outcome == ad.IDENTIFIED


def test_the_chat_name_counts_like_the_contact_name():
    assert ad.detect(ad.ConversationMeta(name="+1 555 000 0001", display_name="Instinct",
                                         **INSTINCT_CADENCE)).outcome == ad.IDENTIFIED


def test_a_name_alone_is_never_proof():
    found = ad.detect(_meta("Instinct", **HUMAN_CADENCE))
    assert (found.outcome, found.signal) == (ad.UNCERTAIN, "name")


@pytest.mark.parametrize("name,counts,outcome", [
    ("Jane Instinct", HUMAN_CADENCE, ad.UNKNOWN),             # a similarly named human: never classified
    ("Jane Instinct", INSTINCT_CADENCE, ad.UNCERTAIN),        # …and with an agent's cadence only asked about
    ("Instincts Bakery", INSTINCT_CADENCE, ad.UNKNOWN),       # a different word
    ("Alice Example", INSTINCT_CADENCE, ad.UNKNOWN),          # cadence alone is not a name
    ("", INSTINCT_CADENCE, ad.UNKNOWN),
])
def test_similar_names_are_never_confidently_classified(name, counts, outcome):
    assert ad.detect(_meta(name, **counts)).outcome == outcome


def test_group_chats_are_never_classified():
    assert ad.detect(ad.ConversationMeta(name="Instinct", group=True, **INSTINCT_CADENCE)).outcome == ad.UNKNOWN


def test_detection_off_answers_unknown():
    assert ad.detect(_meta("Instinct", **INSTINCT_CADENCE), enabled=False) == ad.Detection()


def test_an_uncertain_detection_is_a_question_never_applied():
    actor = ad.resolve_actor("Instinct", None, ad.detect(_meta("Instinct", **HUMAN_CADENCE)))
    assert (actor.kind, actor.decided_by) == (None, "none")
    assert actor.to_dict()["detection"] == ad.UNCERTAIN


@pytest.mark.parametrize("override,kind", [({"kind": "person"}, "person"), ({"kind": "agent"}, "agent")])
def test_the_persons_mark_wins_over_any_detection(override, kind):
    for detection in (ad.detect(_meta("Instinct", **INSTINCT_CADENCE)), ad.Detection()):
        actor = ad.resolve_actor("Instinct", override, detection)
        assert (actor.kind, actor.decided_by) == (kind, "person")


def test_a_marked_label_names_the_turns():
    actor = ad.resolve_actor("+1 555 000 0001", {"kind": "agent", "label": "Instinct"}, ad.Detection())
    assert actor.label == "Instinct" and actor.to_dict()["name"] == "Instinct"


def test_removing_every_detector_keeps_capture_and_the_persons_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "DETECTORS", ())
    assert ad.detect(_meta("Instinct", **INSTINCT_CADENCE)).outcome == ad.UNKNOWN
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    cid = "c" * 24
    messages_source.update_settings(memory, conversation={"id": cid, "name": "Instinct", "ticked": True,
                                                          "actor": {"kind": "agent"}})
    out = messages_source.ingest(memory, {
        "conversation": {"id": cid, "name": "Instinct", **INSTINCT_CADENCE},
        "messages": [{"guid": "g-1", "date": 800_000_000_000_000_000, "is_from_me": False, "text": "Hello."}]})
    assert out["created"] == 1 and out["actor"]["kind"] == "agent" and out["actor"]["decided_by"] == "person"


def test_detection_never_ticks_a_conversation(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (row,) = messages_source.describe(memory, [{"id": "d" * 24, "name": "Instinct", **INSTINCT_CADENCE}])
    assert row["suggestion"]["outcome"] == ad.IDENTIFIED and row["ticked"] is False
    with pytest.raises(messages_source.NotSelected):
        messages_source.ingest(memory, {"conversation": {"id": "d" * 24, "name": "Instinct"}, "messages": []})
