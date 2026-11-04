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
    assert {f for f in hit.__dataclass_fields__} == {"kind", "start", "end", "sure"}


@pytest.mark.parametrize("body,sure", [
    ("user: my password is Kp92mQzx", True),                  # letters and digits, however it is said
    ("user: the password is Kp92mQzx", True),
    ("user: password: Kp92mQzx", True),
    ("user: my password is sunshine.", False),                # letters alone may be a word
    ("user: the password is 'blue heron'", False),
    ("user: my passcode is 482913", True),                    # digits, and someone's
    ("user: la clave del cajero es 8842", True),
    ("user: la clave es 77889944", False),                    # a weak word no one claimed
    ("user: my card is 4539 1488 0343 6467", True),           # checksums
    ("user: DE75512108001245126199", True),
    ("user: mi DNI es 12345678Z", True),
    ("user: my account number is 000123456789", False),       # nothing to check it against
    ("user: my passport number is X4829173", True),           # a named ID claimed
    ("user: pasaporte: G48291735", False),                    # a named ID no one claimed
    ("user: DB_PASSWORD=Kp92mQzxL7", True),                   # shapes
    ("user: postgres://app:Kp92mQzxL@db.internal:5432/main", True),
])
def test_how_sure_a_hit_is_decides_whether_an_engine_reads_it(body, sure):
    (hit,) = st.find(body)
    assert hit.sure is sure


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
    # Rulings 57, 58: a person's turn an app relayed still carries what they typed; its reply is still the model's.
    assert _kinds(f"user: {line}", override="assistant") == {st.PASSWORD}
    assert _kinds(f"relayed [Claude]: {line}") == {st.PASSWORD}
    assert _kinds(f"assistant: {line}", override="assistant") == set()


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


@pytest.mark.parametrize("line", [
    "my season pass is A1B2C3",
    "my mountain pass is K2base",
    "boarding pass: G12A",
    "the ski pass is G12A9",
    "pw: 2024-11-01",
    "my passport expires 2031-05-01",
    "checking account 2024-11-04",
    "my password is Bitwarden.",
    "my password is 1Password.",
])
def test_things_that_are_not_a_password_are_not_found(line):
    assert st.find(f"user: {line}") == []


@pytest.mark.parametrize("line", ["mi contraseña es guatemala.", "my password is sunshine."])
def test_a_plain_word_called_a_password_is_unsure_at_most(line):
    assert all(not h.sure for h in st.find(f"user: {line}"))


@pytest.mark.parametrize("line", [
    "my wifi pass is K2base9", "my new pass is K2base9", "my pass is K2base9", "pw: K2base9x", "the vpn pw is K2base9x"])
def test_a_real_pass_is_still_found(line):
    assert [h.kind for h in st.find(f"user: {line}")] == ["password"]


def test_a_passport_number_is_still_found():
    assert [h.kind for h in st.find("user: my passport number is G1239876")] == ["id"]


@pytest.mark.parametrize("line, sure", [
    ("user: mi clave es gpt-4o", False),
    ("user: my pass is gpt-4o", False),
    ("user: mi clave es 77889944", False),
    ("user: mi clave de gmail es Xy7hj2k", True),
    ("user: my password is gpt-4o", True),
])
def test_a_weak_word_alone_is_never_sure_a_named_system_makes_it(line, sure):
    hits = st.find(line)
    assert len(hits) == 1 and hits[0].sure is sure


#: A made-up sample of every vendor shape, spelled in two parts so no scanner takes it for a live key.
_SAMPLES = ("sk-" + "a1" * 12, "ghp_" + "a1" * 12, "github_pat_" + "a1" * 12, "xoxb-" + "a1" * 8, "AKIA" + "J7K2LQ9XW3MBV5TN",
            "AIza" + "SyDk3hQw7ZtLm9Xc2Vb8Nf4Gr6Ty1Uj5Ke0", "eyJ" + "a1a1a1a1a1.eyJa1a1a1a1a1.a1a1a1a1a1", "sk_" + "live_" + "a1" * 10,
            "glpat-" + "a1" * 10, "npm_" + "a1" * 16, "hf_" + "a1" * 16, "SG." + "a1" * 10 + "." + "a1" * 10, "xai-" + "a1" * 16,
            "gsk_" + "a1" * 16, "pplx-" + "a1" * 16)


def test_the_samples_cover_every_vendor_shape():
    assert [rx.pattern for rx in st._VENDOR_RES if not any(rx.search(s) for s in _SAMPLES)] == []


@pytest.mark.parametrize("value", _SAMPLES)
def test_a_key_of_any_vendor_shape_is_found_with_nothing_else_on_the_line(value):
    hits = st.find(f"user: look at this {value}")
    assert [(h.kind, h.sure) for h in hits] == [(st.KEY, True)]


# ---- a password is a placeholder only as a whole, and what closes it


def _password(line: str) -> list[str]:
    text = f"user: {line}"
    return [text[h.start:h.end] for h in st.find(text) if h.kind == st.PASSWORD]


@pytest.mark.parametrize("value", [
    "hunter2-Xq7!", "Perro123456", "Qwerty2024!", "Clave2024!", "Hunter2947", "Zanate2-Xq7!", "Password2024!",
    "Testigo42x", "Secretaria9", "Barco-2024", "Foolproof7", "mi-Perro-9x", "Examples88",
])
def test_a_stated_password_that_merely_contains_a_placeholder_word_is_found(value):
    assert _password(f"my gmail password is {value}") == [value]


@pytest.mark.parametrize("value", [
    "password", "password123", "Password1!", "passw0rd", "P@ssw0rd", "pa55word", "changeme", "change-me", "secret123",
    "test1234", "test_password", "testpass", "test-only", "example123", "sample-password", "dummy1", "your-password",
    "your_password_here", "YOUR_PASSWORD", "<your-password>", "my-secret-password", "mysecretpassword", "xxxxx",
    "xxxx-xxxx", "xxx123", "****", "pa***rd", "abc123", "abcd1234", "abcdef", "qwerty", "qwerty123", "asdf1234", "hunter2",
    "letmein", "123456", "12345678", "admin123", "contraseña123", "tu-clave", "mi_clave", "foobar", "mock-token",
])
def test_a_placeholder_as_the_whole_value_is_no_password(value):
    assert _password(f"my gmail password is {value}") == []


def test_a_long_run_of_a_placeholder_character_answers_at_once():
    assert _password(f"my gmail password is {'x' * 63}y!") == [f"{'x' * 63}y"]


@pytest.mark.parametrize("line,value", [
    ("my gmail password is Zanate2-Xq7!", "Zanate2-Xq7!"),
    ("my gmail password is Zanate2-Xq7!!", "Zanate2-Xq7!!"),
    ("my gmail password is Zanate2-Xq7!.", "Zanate2-Xq7!"),
    ("my gmail password is Zanate2-Xq7!, ok", "Zanate2-Xq7!"),
    ("my gmail password is Zanate2-Xq7.", "Zanate2-Xq7"),
    ("my gmail password is Zanate2-Xq7! thanks", "Zanate2-Xq7"),   # may be the sentence's own
    ("my gmail password is Cocodrilo!", "Cocodrilo"),              # a word said loudly
    ("my gmail password is 48210957!", "48210957"),
])
def test_a_closing_bang_is_part_of_a_mixed_value_with_no_space_after_it(line, value):
    assert _password(line) == [value]


def test_a_name_is_not_a_value_for_being_closed_by_a_bang():
    assert _password("my gmail password is API_KEY!") == []


def test_by_value_a_closing_bang_is_found_with_or_without_it_and_only_for_a_mixed_value():
    assert st.take_out("in with Zanate2-Xq7! and Zanate2-Xq7.", {"Zanate2-Xq7!": "M"})[0] == "in with M and M."
    assert st.holds("at Cocodrilo today", "Cocodrilo!") is False
    assert st.holds("code 48210957 today", "48210957!") is False
    assert st.holds("Zanate2-Xq7!", "Zanate2-Xq7") is True
