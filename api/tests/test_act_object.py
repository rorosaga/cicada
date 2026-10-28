"""An act on an application is about the event, never its venue or organiser (ruling 42, `act_object`, 2026-10-28).
Synthetic names only."""
import re

import pytest

from api.services import act_object, application_page, evidence

BODY = ("user: The hull is faired. I signed up for an epoxy workshop at the Example Makerspace on October 17th.\n"
        "assistant: Good call.\n")


def _rel(target, label="signed up for", source="Pat Example", quote=None):
    rel = {"source": source, "target": target, "label": label,
           "evidence_quote": quote or "I signed up for an epoxy workshop at the Example Makerspace on October 17th."}
    evidence.attach_relationship_evidence(rel, "ep_2026-09-30_001", BODY)
    return rel


@pytest.mark.parametrize("sentence,name,marker", [
    ("I signed up for an epoxy workshop at the Example Makerspace.", "Example Makerspace", "at"),
    ("I registered for a pottery course run by Example Guild.", "Example Guild", "run by"),
    ("I applied to a design role with Example Studio.", "Example Studio", "with"),
    ("I enrolled in an evening class in the Example Hall.", "Example Hall", "in"),
    ("Me inscribí en un taller de cerámica en el Example Taller.", "Example Taller", "en"),
    # the name IS the object: kept
    ("I signed up for the Example Workshop.", "Example Workshop", None),
    ("I signed up for the Example Makerspace workshop.", "Example Makerspace", None),
    ("I applied to Example Fellowship at last.", "Example Fellowship", None),
    ("I enrolled in Example Course.", "Example Course", None),
    # no act before the name: not judged
    ("At the Example Makerspace I signed up for a workshop.", "Example Makerspace", None),
    ("The workshop is at the Example Makerspace.", "Example Makerspace", None),
])
def test_venue_reads_the_object_from_the_sentence(sentence, name, marker):
    m = re.search(re.escape(name), sentence)
    assert act_object.venue(sentence, m) == marker


def test_the_venue_gets_the_events_link_with_the_persons_span():
    rels = [_rel("Epoxy Workshop"), _rel("Example Makerspace")]
    assert rels[1]["evidence"][0]["kind"] == "user"
    assert act_object.hold(rels, BODY) == 1
    assert [(r["source"], r["label"], r["target"]) for r in rels] == [
        ("Pat Example", "signed up for", "Epoxy Workshop"), ("Epoxy Workshop", "at", "Example Makerspace")]
    assert rels[1]["evidence"][0]["kind"] == "user", "the span is kept"


def test_a_link_already_there_drops_the_duplicate():
    rels = [_rel("Epoxy Workshop"), _rel("Example Makerspace"),
            _rel("Example Makerspace", label="held at", source="Epoxy Workshop")]
    assert act_object.hold(rels, BODY) == 1
    assert [(r["source"], r["label"], r["target"]) for r in rels] == [
        ("Pat Example", "signed up for", "Epoxy Workshop"), ("Epoxy Workshop", "held at", "Example Makerspace")]


def test_a_label_that_already_says_where_folds_into_the_events_link():
    """The 2026-10-28 before-run's variant: "signed up for workshop at" <venue> beside the act on the workshop."""
    rels = [_rel("Epoxy Workshop", label="registered for"), _rel("Example Makerspace", label="signed up for workshop at"),
            _rel("Example Makerspace", label="held at", source="Epoxy Workshop")]
    assert act_object.hold(rels, BODY) == 1
    assert [(r["source"], r["label"], r["target"]) for r in rels] == [
        ("Pat Example", "registered for", "Epoxy Workshop"), ("Epoxy Workshop", "held at", "Example Makerspace")]
    alone = [_rel("Example Makerspace", label="signed up for workshop at")]
    assert act_object.hold(alone, BODY) == 0 and alone[0]["label"] == "signed up for workshop at", \
        "with no act on the event, a label that says where is true as written"


@pytest.mark.parametrize("sentence,event,act,place_label,place", [
    # review of #497: a label that merely ends in a place word, beside an act on something else in the sentence
    ("I signed up for the Berlin Marathon and enrolled my son in Riverside School.",
     ("signed up for", "Berlin Marathon"), "enrolled son in", None, "Riverside School"),
    ("I applied to the Acme Fellowship and registered my startup in Delaware.",
     ("applied to", "Acme Fellowship"), "registered startup in", None, "Delaware"),
    ("I applied to the Marathon and submitted my paper with Ana.",
     ("applied to", "Marathon"), "submitted paper with", None, "Ana"),
    # the strict branch: the event is in an earlier clause, not this act's
    ("I applied to the Acme Fellowship and signed up for a class at Delaware Hall.",
     ("applied to", "Acme Fellowship"), "signed up for", "signed up for something at", "Delaware Hall"),
])
def test_an_act_in_another_clause_is_never_the_event(sentence, event, act, place_label, place):
    body = f"user: {sentence}\n"
    rels = [{"source": "Me", "target": event[1], "label": event[0], "evidence_quote": sentence},
            {"source": "Me", "target": place, "label": act, "evidence_quote": sentence}]
    for r in rels:
        evidence.attach_relationship_evidence(r, "ep_2026-09-30_001", body)
    assert all(r["evidence"][0]["kind"] == "user" for r in rels)
    act_object.hold(rels, body)
    assert [(r["source"], r["label"], r["target"]) for r in rels] == [
        ("Me", event[0], event[1]), ("Me", place_label or act, place)], "no event→place link is invented"


def test_with_no_event_extracted_it_says_what_the_sentence_says():
    rels = [_rel("Example Makerspace", label="signed_up_for")]
    assert act_object.hold(rels, BODY) == 1
    assert rels[0]["label"] == "signed up for something at" and rels[0]["source"] == "Pat Example"


def test_the_object_an_unlocated_quote_and_other_labels_are_kept():
    rels = [_rel("Epoxy Workshop"), _rel("Example Makerspace", quote="not in the transcript"),
            _rel("Example Makerspace", label="visited")]
    before = [dict(r) for r in rels]
    assert act_object.hold(rels, BODY) == 0
    assert rels == before


def test_the_venue_never_gets_an_application_page():
    text = BODY
    workshop = {"name": "Epoxy Workshop", "type": "concept", "application": {"status": "registered"}}
    venue = {"name": "Example Makerspace", "type": "company", "application": {"status": "registered"}}
    fm = {"id": "ep_2026-09-30_001"}
    assert application_page.at_extraction(workshop, episode_id="ep_2026-09-30_001", frontmatter=fm, text=text,
                                          day="2026-09-30") is not None
    assert application_page.at_extraction(venue, episode_id="ep_2026-09-30_001", frontmatter=fm, text=text,
                                          day="2026-09-30") is None
