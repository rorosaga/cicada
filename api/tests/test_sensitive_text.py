"""G235: the detector — what it finds, what it leaves, and that crying wolf stays measured.

The labelled sets (`fixtures/sensitive_corpus.py`) pin precision and recall. They are the floor of a measure: written by the
author of the rules, and the held-out set stopped being held out when its misses were fixed. The real figures are counts
from `scripts/sensitive_census.py` on a real bank, recorded in G235."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from api.services import evidence, sensitive_text as st
from api.tests.fixtures.sensitive_corpus import HELDOUT_NEGATIVES, HELDOUT_POSITIVES, NEGATIVES, POSITIVES

ROOT = Path(__file__).resolve().parents[2]


def _kinds(body, harness=False, **kw):
    return {h.kind for h in st.find(body, harness=harness, **kw)}


@pytest.mark.parametrize("positives,negatives", [(POSITIVES, NEGATIVES), (HELDOUT_POSITIVES, HELDOUT_NEGATIVES)])
def test_precision_and_recall_on_the_labelled_sets_hold(positives, negatives):
    found, missed = Counter(), Counter()
    for kind, body, harness in positives:
        (found if kind in _kinds(body, harness) else missed)[kind] += 1
    alarms = [body for body, harness in negatives if st.find(body, harness=harness)]
    assert alarms == []                                # one wrong alarm a night teaches a person to ignore it
    total = sum(found.values()) + sum(missed.values())
    assert sum(found.values()) / total >= 0.95, missed


def test_each_negative_and_positive_names_only_known_kinds():
    assert {k for k, _b, _h in [*POSITIVES, *HELDOUT_POSITIVES]} == set(st.KINDS)


def test_a_hit_holds_offsets_and_a_kind_never_the_value():
    body = "user: mi contraseña es gato1234 y ya"
    (hit,) = st.find(body)
    assert body[hit.start:hit.end] == "gato1234" and hit.kind == st.PASSWORD
    assert "gato1234" not in repr(hit)
    assert {f for f in hit.__dataclass_fields__} == {"kind", "start", "end"}


def test_offsets_are_right_on_a_later_line_of_a_marked_body():
    body = "user: hola\nassistant: hola\nuser: my password is Tr0ub4dor\n"
    (hit,) = st.find(body)
    assert body[hit.start:hit.end] == "Tr0ub4dor"


def test_who_said_it_decides_how_it_is_read():
    line = "The password is Kp92mQzxL"
    assert _kinds(f"user: {line}") == {st.PASSWORD}
    assert _kinds(f"assistant: {line}") == set()               # an agent explaining a fixture
    assert _kinds(f"user: {line}", harness=True) == set()      # a coding session needs "my" or a named system
    assert _kinds(f"user: my password is Kp92mQzxL", harness=True) == {st.PASSWORD}
    assert _kinds(f"speaker:Alex: {line}") == {st.PASSWORD}    # a meeting's speaker
    assert _kinds(f"video [0:10]: {line}") == set()            # a video's words
    assert _kinds(line, override=evidence.SAVE_KIND) == set()  # a saved page's public text
    assert _kinds(line, override=evidence.AGENT_KIND) == set()  # an agent's saved note


def test_a_code_fence_is_read_only_for_shapes():
    assert _kinds("user: ```\npassword: Kp92mQzx\n```") == set()
    assert _kinds("user: ```\nglpat-" + "x7Kp2mQz9RtLw3vB1nYc\n```") == {st.KEY}
    assert _kinds("user: ```\nDB_PASSWORD=Kp92mQzxL7\n```") == {st.KEY}
    # a new turn closes a fence its last turn left open
    assert _kinds("user: ```\nsome code\nassistant: ok\nuser: my password is Kp92mQzx") == {st.PASSWORD}


def test_validated_numbers_rest_on_their_checksums():
    assert _kinds("user: my card is 4539 1488 0343 6467") == {st.CARD}
    assert _kinds("user: my card is 4539 1488 0343 6468") == set()     # Luhn fails
    assert _kinds("user: 4539148803436467") == set()                   # valid, but no card layout and no card word
    assert _kinds("user: 4242 4242 4242 4242") == set()                # an issuer's published test number
    assert _kinds("user: DE75512108001245126199") == {st.BANK}
    assert _kinds("user: DE75512108001245126198") == set()             # mod-97 fails
    assert _kinds("user: mi DNI es 12345678Z") == {st.ID}
    assert _kinds("user: mi DNI es 12345678A") == set()                # the letter is the checksum


def test_medical_and_legal_words_are_never_flagged():
    for body in ("user: my doctor says the biopsy came back positive", "user: me diagnosticaron depresión",
                 "user: the lawyer filed case 2024-1192 for the divorce"):
        assert st.find(body) == []


def test_held_text_covers_a_value_across_a_chunk_edge_and_keeps_no_piece():
    text = "user: my password is Kp92mQzxL ok"
    hits = st.find(text)
    (hit,) = hits
    head = st.held_text(text, 0, hit.start + 3, hits)
    tail = st.held_text(text, hit.start + 3, len(text), hits)
    assert "Kp9" not in head and "2mQzxL" not in tail
    assert head.endswith("[held back: password]") and tail.startswith("[held back: password]")


def test_strip_values_is_exact_whole_token_and_case_sensitive():
    assert st.strip_values("a Kp92mQzx b", ("Kp92mQzx",)) == ("a [removed] b", 1)
    assert st.strip_values("aKp92mQzxb", ("Kp92mQzx",)) == ("aKp92mQzxb", 0)
    assert st.strip_values("a kp92mqzx b", ("Kp92mQzx",)) == ("a kp92mqzx b", 0)


def test_this_repository_talking_about_passwords_raises_no_password_alarm():
    """Real code talk: the docs and the code of a project that discusses tokens and passwords all day."""
    alarms = Counter()
    for rel in ("CLAUDE.md", "docs/architecture/capture-and-sleep.md", "docs/architecture/network.md",
                "docs/architecture/mcp.md", "docs/goals/working-method.md", "api/services/episode_scrub.py",
                "api/services/auth.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            for ctx in (st.Context("person", True), st.Context("agent", True)):
                alarms.update(h.kind for h in st.find_in_line(line, 0, ctx))
    assert alarms[st.PASSWORD] == 0, alarms
    assert alarms[st.CARD] == alarms[st.BANK] == alarms[st.ID] == 0, alarms
