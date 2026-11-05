"""G81, proposed ruling 55: a number the person gives lands on the right page as a token; its digits stay outside the bank.

Every number is synthetic, in the 555-01xx range. Covers: one number written many ways is one token, what counts as a
number, the switch (off, nothing moves), whose words are kept, no re-read of old chats, what Stage 1's output becomes,
the change table, what asks, the answer, held names, the duplicate-people signal, Contacts, and every door."""
from __future__ import annotations

import json
import re
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.models.schemas import InboxResolveRequest
from api.services import (agentic_write, bank_index, chat_live, claim_pipeline, claim_reconciler, contacts_local,
                          episode_scrub, inbox_generator, inbox_service, markdown_parser, pending_store, people_directory,
                          phone_numbers, whatsapp_source)
from api.services.claims import Claim, Evidence, parse_claims

SPEC = whatsapp_source.SPEC
CHAT = chat_live.hash_id("15550000002@s.whatsapp.net")
APPLE = 978_307_200
T0 = 1_788_000_000
A = "+1 202 555 0143"
A_DIGITS = "2025550143"
B = "+1 202 555 0177"
B_DIGITS = "2025550177"


def row(stanza, at, text="", *, me=False):
    return {"stanza": stanza, "date": at - APPLE, "from_me": me, "text": text, "type": 0, "member": None,
            "metadata": None, "media": None}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def bank(tmp_path, home):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources", "inbox"):
        (memory / sub).mkdir(parents=True)
    bank_index.invalidate()
    chat_live.update_settings(memory, SPEC, {"id": CHAT, "name": "Bob Example", "group": False, "ticked": True},
                              now="2026-08-28T00:00:00+00:00")
    return memory


@pytest.fixture
def on(home):
    phone_numbers.set_enabled(True)


def ingest(bank, rows):
    out = whatsapp_source.ingest(bank, {"conversation": {"id": CHAT, "name": "Bob Example", "group": False,
                                                         "members": []}, "messages": rows, "reactions": []})
    bank_index.invalidate()
    return out


def stored(bank) -> dict[str, tuple[str, dict]]:
    return {p.stem: (markdown_parser.parse(p).body, dict(markdown_parser.parse(p).frontmatter))
            for p in sorted((bank / "episodes").glob("*.md"))}


def every_byte(root: Path) -> bytes:
    return b"\n".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


def tok(bank, raw) -> str:
    return phone_numbers.token(phone_numbers.mint_many(bank.name, [raw])[raw])


def settings_for(memory):
    return SimpleNamespace(memory_path=memory, litellm_model="m", litellm_disambiguation_model="m", archive_threshold=0.2,
                           decay_nudge_threshold=0.4)


# ---- one number, one fact ----

@pytest.mark.parametrize("same", ["+1 202 555 0143", "+12025550143", "(202) 555-0143", "202.555.0143", "1-202-555-0143",
                                  "tel:+12025550143", "0012025550143", "202 555 0143"])
def test_the_same_number_written_differently_is_one_token(home, same):
    first = phone_numbers.mint_many("b", ["+12025550143"])["+12025550143"]
    assert phone_numbers.mint_many("b", [same])[same] == first


def test_a_different_number_is_a_different_token_and_a_token_has_no_digit(home):
    ids = phone_numbers.mint_many("b", [A, B])
    assert ids[A] != ids[B]
    assert all(c.isalpha() and c.islower() for c in ids[A])


def test_a_trunk_zero_and_a_country_code_fall_away(home):
    pairs = [("+33 6 55 01 01 43", "06 55 01 01 43"), ("+34 612 555 014", "612 555 014"), ("+44 20 7946 0143", "020 7946 0143")]
    for left, right in pairs:
        ids = phone_numbers.mint_many("b", [left, right])
        assert ids[left] == ids[right]


def test_a_short_number_with_and_without_its_code_reads_as_two_so_it_asks(home):
    ids = phone_numbers.mint_many("b", ["+507 6555 0143", "6555 0143"])
    assert ids["+507 6555 0143"] != ids["6555 0143"]


def test_the_hash_needs_the_vaults_key(home, tmp_path, monkeypatch):
    """An unsalted hash of about 10^10 phone numbers is one laptop-minute: a bank handed over must not open that way."""
    first = phone_numbers.mint_many("b", [A])[A]
    assert phone_numbers.mint_many("another-bank", [A])[A] != first


def test_the_vault_is_private_and_outside_the_bank(bank, on):
    tok(bank, A)
    path = people_directory.path(bank.name, phone_numbers.VAULT_FILE)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not str(path).startswith(str(bank))
    assert phone_numbers.reveal(bank.name, phone_numbers.mint_many(bank.name, [A]).values()) == {
        phone_numbers.mint_many(bank.name, [A])[A]: A}


def test_a_written_form_with_a_plus_replaces_one_without(home):
    tid = phone_numbers.mint_many("b", ["202 555 0143"])["202 555 0143"]
    phone_numbers.mint_many("b", [A])
    assert phone_numbers.reveal("b", [tid])[tid] == A
    phone_numbers.mint_many("b", ["202 555 0143"])
    assert phone_numbers.reveal("b", [tid])[tid] == A


# ---- what counts as a number in the person's own line ----

@pytest.mark.parametrize("line", [
    f"Bob's number is {A}", "call him on (202) 555-0143", "202.555.0143 is Bob", "tel:+12025550143",
    "her number is 202 555 0143", "phone: 2025550143", "su celular es 202 555 0143", "Ana's new number is 2025550143",
    "call Ana at 202-555-0143", "mi móvil: 202 555 0143", "I was texting Ana on 2025550143",
    # The owner's own scenario: how a number is really typed to a texted agent.
    "Ana 2025550143", "add Ana, 2025550143", "Bob Example 2025550177", "she's on 2025550143", "Ana: 202 555 0143",
    "Bob Example: 202 555 0143", "Ana at 2025550143", "add ana 2025550143", "Ana 612 345 678", "Ana 06 12 34 56 78", "Ana 0612 34 56 78",
    "save my sister Ana 5550143", "Ana 2025550143 please", "he is on 2025550143",
])
def test_these_are_numbers(home, line):
    out, n = phone_numbers.tokenise(line, "b")
    assert n == 1 and "555" not in out and phone_numbers.has_token(out)


@pytest.mark.parametrize("line", [
    "order number 123456789", "invoice 1234567890", "room 101 102 103", "2026-10-28 10:30", "built in 2024 2025 2026",
    "wrote code in 2019", "it cost $1 299 000 000", "sku 123-456-789", "see v1.2.3", "ping 192.168.1.10",
    "the years 1999-2003-2010", "flight 123456789", "a 1730000000 timestamp", "@15550100",
    # G81 review, item 5: a bare run needs a positive signal, never the mere absence of a negative one.
    "my order number is 123456789", "my passport number is 123456789", "my flight number is 123456789",
    "see example.com/product-1234567890", "write to 5550100000@example.com", "it sold for 1 299 000 000",
    "we met at 40.7128 -74.0060", "isbn 978-0-306-40615-7", "on 12 03 2026 14 30",
    "her membership number is 123456789", "phone: 5550100000@example.com",
    # G81 review 3, item 8.
    "see example.com/x?phone=1234567890", "example.com/samsung-phone-1234567890", "tel-1234567890.pdf",
    "call him at 1030 1100",
    # A name's word is not enough: #502's lost words stay in both directions.
    "Bob 1500000", "Tesla 1500000", "Sold 123456789", "Invoice 123456789", "Order 1234567890", "Monday 12 03 2026", "Ana 12 03 2026 14 30",
    "Room 101 102 103", "Years 2024 2025 2026", "Bob 1 299 000 000", "Bob 2025550143 dollars", "Grew by 1500000 users",
    "Ana 1999-2003-2010", "Ana 2026-10-28 10:30", "2025550143", "ping Ana 192.168.1.10", "Budget 1500000",
])
def test_these_are_not(home, line):
    assert phone_numbers.tokenise(line, "b") == (line, 0)


def test_a_token_survives_the_chat_scrub_unchanged(home):
    line, _ = phone_numbers.tokenise(f"Bob's number is {A}", "b")
    assert episode_scrub.scrub_for(line, "whatsapp") == (line, 0)


# ---- the switch ----

def test_off_nothing_is_minted_and_the_body_is_todays(bank, home):
    ingest(bank, [row("AAA1", T0, f"Bob's number is {A}", me=True), row("AAA2", T0 + 5, "her number is 202 555 0177", me=True)])
    (body, _fm), = stored(bank).values()
    assert "user: Bob's number is [redacted]" in body
    assert "her number is 202 555 0177" in body     # the bare-digit exception, as it was
    assert not people_directory.path(bank.name, phone_numbers.VAULT_FILE).exists()


def test_off_stage_one_is_given_no_note(bank):
    assert phone_numbers.has_token("user: Bob's number is [redacted]") is False


# ---- whose words ----

def test_only_the_persons_own_words_are_tokened(bank, on):
    ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True),
                  row("AAA2", T0 + 5, f"Thanks, my new number is {B}")])
    (body, _fm), = stored(bank).values()
    assert phone_numbers.token_ids(body.split("\n")[0])
    assert "[redacted]" in body.split("\n")[1] and not phone_numbers.has_token(body.split("\n")[1])
    assert B_DIGITS[-4:] not in body and A_DIGITS[-4:] not in body


def test_a_forwarded_message_is_someone_elses_words(bank, on):
    message = SimpleNamespace(key="k", from_me=True, unsent=False, forwarded_from={"name": "x"}, text=f"call {A}")
    phone_numbers.tokenise_batch([message], {}, writer="whatsapp", bank=bank.name)
    assert "[redacted]" in message.text and not phone_numbers.has_token(message.text)


def test_no_digit_of_a_chats_number_reaches_any_file_of_the_bank(bank, on):
    ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True), row("AAA2", T0 + 5, f"mine is {B}")])
    raw = every_byte(bank)
    assert b"555 0143" not in raw and A_DIGITS.encode() not in raw and B_DIGITS.encode() not in raw


# ---- no mass re-read of old chats ----

def _old_chat(bank):
    ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True),
                  row("AAA2", T0 + 5, "her number is 202 555 0177", me=True),
                  row("AAA3", T0 + 9, f"ok, {B}")])
    return stored(bank)


def test_turning_it_on_moves_no_stored_byte_on_a_read_again(bank, monkeypatch):
    before = _old_chat(bank)
    for path in (bank / "episodes").glob("*.md"):   # as Sleep leaves one
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, {**parsed.frontmatter, "processed": True, "processed_by": "sleep"}, parsed.body)
    bank_index.invalidate()
    frozen = stored(bank)
    phone_numbers.set_enabled(True)
    out = ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True),
                        row("AAA2", T0 + 5, "her number is 202 555 0177", me=True),
                        row("AAA3", T0 + 9, f"ok, {B}")])
    assert out["updated"] == 0 and out["created"] == 0
    after = stored(bank)
    assert after == frozen
    assert [b for b, _ in after.values()] == [b for b, _ in before.values()]
    assert all(fm["processed"] is True and "revised" not in fm for _b, fm in after.values())


def test_a_new_message_on_an_old_sitting_tokens_only_itself(bank, monkeypatch):
    (old_body, _), = _old_chat(bank).values()
    phone_numbers.set_enabled(True)
    ingest(bank, [row("AAA4", T0 + 20, f"Bob's new number is {A}", me=True)])
    (body, _), = stored(bank).values()
    lines = body.split("\n")
    assert "\n".join(lines[:3]) == old_body
    assert phone_numbers.has_token(lines[3]) and A_DIGITS[-4:] not in body


def test_a_tokened_line_posted_again_stays_as_it_is(bank, on):
    ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True)])
    before = stored(bank)
    assert ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True)])["updated"] == 0
    assert stored(bank) == before


def test_switched_off_again_a_tokened_line_posted_again_stays(bank, monkeypatch):
    phone_numbers.set_enabled(True)
    ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True)])
    before = stored(bank)
    phone_numbers.set_enabled(False)
    assert ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True)])["updated"] == 0
    assert stored(bank) == before


def test_a_real_edit_is_tokened_and_is_a_revision(bank, on):
    ingest(bank, [row("AAA1", T0, "Ana's number is coming", me=True)])
    assert ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True)])["updated"] == 1
    (body, fm), = stored(bank).values()
    assert phone_numbers.has_token(body) and fm["revised"]["count"] == 1


# ---- Stage 1's output ----

def test_a_value_on_the_persons_line_becomes_a_located_number_entry(home):
    t = tok(SimpleNamespace(name="b"), A)
    content = f"user: Ana's number is {t}\nassistant: Saved."
    values = [{"entity": "Ana Diaz", "attribute": "phone number", "value": t, "evidence": []}]
    assert phone_numbers.take([], [], values, content, "ep_2026-08-29_001", bank="b") == 1
    entry = values[0]
    assert entry[phone_numbers.ITEM_KEY] and entry["evidence"][0]["kind"] == "user"
    span = entry["evidence"][0]
    assert t in content[span["start"]:span["end"]]


def test_a_token_copied_without_its_brackets_is_still_this_conversations_number(home):
    """Measured on the first real run at haiku: it wrote the ten letters alone, as a ``value-of-phone-number``."""
    t = tok(SimpleNamespace(name="b"), A)
    bare = phone_numbers.token_ids(t)[0]
    values = [{"entity": "Ana Diaz", "attribute": "phone number", "value": bare}]
    entities = [{"name": "Ana Diaz", "summary": f"reachable on {bare}", "key_facts": [f"number {bare}"]}]
    assert phone_numbers.take(entities, [], values, f"user: Ana {t}", "ep_2026-08-29_001", bank="b") == 1
    assert values[0]["value"] == t and values[0][phone_numbers.ITEM_KEY] == bare
    assert bare not in json.dumps(entities)


def test_a_number_said_twice_rests_on_the_line_about_this_person(home):
    t = tok(SimpleNamespace(name="b"), A)
    content = f"user: Bob Example shares a phone, {t}\nuser: Ana Diaz's new number is {t}"
    values = [{"entity": "Ana Diaz", "attribute": "phone number", "value": t}]
    phone_numbers.take([], [], values, content, "ep_2026-08-29_001", bank="b")
    span = values[0]["evidence"][0]
    assert "Ana Diaz" in content[span["start"]:span["end"]]


def test_a_relationship_to_a_token_becomes_the_same_entry(home):
    t = tok(SimpleNamespace(name="b"), A)
    rels = [{"source": "Ana Diaz", "target": t, "label": "has phone"}, {"source": "Ana Diaz", "target": "Acme", "label": "works at"}]
    values: list = []
    phone_numbers.take([], rels, values, f"user: Ana {t}", "ep_2026-08-29_001", bank="b")
    assert [r["target"] for r in rels] == ["Acme"] and values[0]["value"] == t


def test_a_number_only_an_agents_line_holds_is_dropped(home):
    t = tok(SimpleNamespace(name="b"), A)
    values = [{"entity": "Ana Diaz", "attribute": "phone number", "value": t}]
    assert phone_numbers.take([], [], values, f"user: add her\nassistant: Added {t}", "ep_2026-08-29_001", bank="b") == 0
    assert values == []


def test_no_token_stays_in_a_pages_prose(home):
    t = tok(SimpleNamespace(name="b"), A)
    entities = [{"name": "Ana Diaz", "type": "person", "summary": f"Ana, reachable at {t}.", "key_facts": [f"Her number is {t}", "Lives nearby"],
                 "history_entries": [{"date": "2026-08-29", "event": f"gave {t}"}]}]
    phone_numbers.take(entities, [], [], f"user: Ana {t}", "ep_2026-08-29_001", bank="b")
    blob = json.dumps(entities)
    assert "[number:" not in blob and "Lives nearby" in blob and "a number" in entities[0]["summary"]


def test_a_name_the_model_gave_no_entity_still_gets_a_line_to_wait_on(home):
    t = tok(SimpleNamespace(name="b"), A)
    entities: list = []
    phone_numbers.take(entities, [], [{"entity": "Ana Diaz", "attribute": "phone number", "value": t}], f"user: Ana {t}",
                       "ep_2026-08-29_001", bank="b")
    assert entities[0]["name"] == "Ana Diaz" and entities[0]["type"] == "person"


def test_digits_a_model_wrote_from_a_writer_with_no_chat_scrub_are_minted(home, on):
    values = [{"entity": "Ana Diaz", "attribute": "phone number", "value": "+12025550143"}]
    phone_numbers.take([], [], values, f"user: Ana is on {A}", "ep_2026-08-29_001", bank="b")
    assert phone_numbers.has_token(values[0]["value"]) and values[0]["evidence"][0]["kind"] == "user"


def test_digits_are_left_alone_while_it_is_off(home):
    values = [{"entity": "Ana Diaz", "attribute": "phone number", "value": "+12025550143"}]
    phone_numbers.take([], [], values, f"user: Ana is on {A}", "ep_2026-08-29_001", bank="b")
    assert values == [{"entity": "Ana Diaz", "attribute": "phone number", "value": "+12025550143"}]


def test_a_claim_from_an_entry_is_a_literal_phone_claim(home):
    from api.services.entity_extractor import entities_to_claims

    t = tok(SimpleNamespace(name="b"), A)
    values: list = [{"entity": "Ana Diaz", "attribute": "phone number", "value": t}]
    phone_numbers.take([], [], values, f"user: Ana {t}", "ep_2026-08-29_001", bank="b")
    claims = entities_to_claims([{"episode_id": "ep_2026-08-29_001", "origin": "whatsapp", "values": values}], None)
    assert [(c.subject, c.predicate, c.object, c.object_kind) for c in claims] == [("ana-diaz", "phone", t, "literal")]
    assert phone_numbers.is_number_claim(claims[0])


# ---- the change table ----

def number(token_text, day, *, change=phone_numbers.UNKNOWN, ask=None, replaces=()) -> Claim:
    claim = Claim(id=f"c-{token_text[-5:]}-{day}", text="x", subject="ana-diaz", predicate="phone", object=token_text,
                  object_kind="literal", valid_from=day, source_episodes=[f"ep_{day}_001"])
    claim.number_change, claim.number_replaces = change, list(replaces)
    if ask:
        claim.number_ask = ask
    return claim


@pytest.fixture
def table(tmp_path, home):
    settings = settings_for(tmp_path / "t")

    def run(slot: list[Claim], new: Claim):
        nudges: list = []
        audit: list = []
        kept = claim_reconciler._place_number(new, slot, settings, "2026-09-01", nudges, audit)
        return kept, nudges, audit
    return run


def current(slot):
    return [c.object for c in slot if c.valid_to is None]


def test_the_first_number_is_kept(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    assert current(slot) == ["[number:aaaaaaaaaa]"]


def test_a_restatement_is_one_fact_never_two_current(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    _kept, nudges, _a = table(slot, number("[number:aaaaaaaaaa]", "2026-08-20"))
    assert current(slot) == ["[number:aaaaaaaaaa]"] and len(slot) == 1 and not nudges


def test_a_changed_number_supersedes_and_the_old_stays_as_history(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    table(slot, number("[number:bbbbbbbbbb]", "2026-08-20", change=phone_numbers.CHANGED))
    assert current(slot) == ["[number:bbbbbbbbbb]"]
    old = slot[0]
    assert old.valid_to == "2026-08-20" and old.superseded_by == slot[1].id and slot[1].supersedes == old.id


def test_a_second_number_sits_beside_the_first(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    table(slot, number("[number:bbbbbbbbbb]", "2026-08-20", change=phone_numbers.ADDITIONAL))
    assert sorted(current(slot)) == ["[number:aaaaaaaaaa]", "[number:bbbbbbbbbb]"]


def test_a_different_number_with_no_word_for_it_asks_and_does_not_become_current(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    _kept, nudges, _a = table(slot, number("[number:bbbbbbbbbb]", "2026-08-20"))
    assert current(slot) == ["[number:aaaaaaaaaa]"]
    assert nudges[0]["action"] == "divergence_nudge" and nudges[0]["existing_claim_id"] == slot[0].id
    assert "[number:" not in json.dumps(nudges[0]) and slot[1].context == phone_numbers.ASKED


def test_saying_the_asked_number_again_does_not_ask_twice(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    table(slot, number("[number:bbbbbbbbbb]", "2026-08-20"))
    _kept, nudges, _a = table(slot, number("[number:bbbbbbbbbb]", "2026-08-25"))
    assert not nudges and len(slot) == 2


def test_new_with_two_held_asks_which(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    table(slot, number("[number:bbbbbbbbbb]", "2026-08-02", change=phone_numbers.ADDITIONAL))
    _k, nudges, _a = table(slot, number("[number:cccccccccc]", "2026-08-20", change=phone_numbers.CHANGED))
    assert nudges and sorted(current(slot)) == ["[number:aaaaaaaaaa]", "[number:bbbbbbbbbb]"]


def test_new_naming_the_one_it_replaces_closes_that_one(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    table(slot, number("[number:bbbbbbbbbb]", "2026-08-02", change=phone_numbers.ADDITIONAL))
    table(slot, number("[number:cccccccccc]", "2026-08-20", change=phone_numbers.CHANGED, replaces=["aaaaaaaaaa"]))
    assert sorted(current(slot)) == ["[number:bbbbbbbbbb]", "[number:cccccccccc]"]


def test_a_number_the_person_confirmed_is_never_closed_by_a_reading(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    slot[0].source_trust, slot[0].origin = "user_stated", "clarification"
    _k, nudges, _a = table(slot, number("[number:bbbbbbbbbb]", "2026-08-20", change=phone_numbers.CHANGED))
    assert nudges and current(slot) == ["[number:aaaaaaaaaa]"]


def test_an_older_change_read_late_is_history(table):
    slot: list = []
    table(slot, number("[number:bbbbbbbbbb]", "2026-08-20"))
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01", change=phone_numbers.CHANGED))
    assert current(slot) == ["[number:bbbbbbbbbb]"]
    assert slot[1].valid_to == "2026-08-20" and slot[1].superseded_by == slot[0].id


def test_an_old_number_said_as_old_never_opens(table):
    slot: list = []
    table(slot, number("[number:bbbbbbbbbb]", "2026-08-20"))
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-21", change=phone_numbers.PAST))
    assert current(slot) == ["[number:bbbbbbbbbb]"]


def test_going_back_to_an_earlier_number_asks(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    table(slot, number("[number:bbbbbbbbbb]", "2026-08-20", change=phone_numbers.CHANGED))
    _k, nudges, _a = table(slot, number("[number:aaaaaaaaaa]", "2026-08-25", change=phone_numbers.CHANGED))
    assert nudges and current(slot) == ["[number:bbbbbbbbbb]"]


def test_reading_the_same_conversation_again_writes_nothing_new(table):
    slot: list = []
    table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    _k, nudges, _a = table(slot, number("[number:aaaaaaaaaa]", "2026-08-01"))
    assert len(slot) == 1 and not nudges


X = "[number:xxxxxxxxxx]"
Y = "[number:yyyyyyyyyy]"


@pytest.mark.parametrize(("line", "kind"), [
    (f"Ana's new number is {X}", phone_numbers.CHANGED), (f"she changed her number to {X}", phone_numbers.CHANGED),
    (f"her number is now {X}", phone_numbers.CHANGED), (f"el nuevo número de Ana es {X}", phone_numbers.CHANGED),
    (f"Ana changed her number, it's {X} now", phone_numbers.CHANGED), (f"Ana changed her number, she's on {X}", phone_numbers.CHANGED), (f"{X} is her new number", phone_numbers.CHANGED),
    (f"Ana's work number is {X}", phone_numbers.ADDITIONAL), (f"she also has {X}", phone_numbers.ADDITIONAL),
    (f"su otro móvil es {X}", phone_numbers.ADDITIONAL), (f"her old number was {X}", phone_numbers.PAST),
    (f"Ana is {X}", phone_numbers.UNKNOWN), (f"Ana's number is {X}", phone_numbers.UNKNOWN),
    # G81 review, item 4: an unclear line asks. Not one of these says the number changed or ended.
    (f"I was talking to Ana, her number is {X}", phone_numbers.UNKNOWN), (f"I was texting Ana on {X}", phone_numbers.UNKNOWN),
    (f"Ana got a new job, her desk line is {X}", phone_numbers.UNKNOWN), (f"Ana now uses {X}", phone_numbers.UNKNOWN),
    (f"new year, Ana's number is {X}", phone_numbers.UNKNOWN), (f"I used to call Ana, she is on {X}", phone_numbers.UNKNOWN),
    (f"Bob's new number is coming and Ana's number is {X}", phone_numbers.UNKNOWN),
])
def test_what_the_persons_line_says(line, kind):
    assert phone_numbers.classify(line) == kind


# ---- what may land where ----

def page(memory, stem, name, *, type_="person", **fm):
    path = memory / "entities" / f"{stem}.md"
    markdown_parser.write(path, {"id": stem, "name": name, "type": type_, "status": "active", "confidence": 0.8, **fm},
                          f"# {name}\n\n## Summary\nSomeone.\n")
    return path


def episode(memory, day, line, *, stem=None) -> str:
    ep = stem or f"ep_{day}_001"
    markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "timestamp": f"{day}T10:00:00+00:00", "source": "whatsapp",
                                                             "origin": "whatsapp", "processed": False}, f"user: {line}")
    return ep


def extraction(memory, ep, name, t, *, ts=None) -> dict:
    day = ep[3:13]
    values: list = [{"entity": name, "attribute": "phone number", "value": t}]
    body = markdown_parser.parse(memory / "episodes" / f"{ep}.md").body
    phone_numbers.take([], [], values, body, ep, bank=memory.name)
    for v in values:
        v.update(source_episode=ep, source_episode_timestamp=ts or f"{day}T10:00:00+00:00", origin="whatsapp")
    return {"episode_id": ep, "episode_timestamp": ts or f"{day}T10:00:00+00:00", "origin": "whatsapp", "entities": [],
            "relationships": [], "values": values}


def pipeline(memory, *extracted, name_to_id=None, day="2026-09-01"):
    return claim_pipeline.run_claim_pipeline(list(extracted), [], memory, settings_for(memory), now_date=day,
                                             name_to_id=name_to_id or {}, decay=False)


def claims_on(memory, stem):
    return parse_claims((memory / "entities" / f"{stem}.md").read_text())


@pytest.fixture
def memory(tmp_path, home, on):
    memory = tmp_path / "bank-t"
    for sub in ("episodes", "entities", "sources", "inbox"):
        (memory / sub).mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(memory)], check=True)
    subprocess.run(["git", "-C", str(memory), "config", "user.email", "t@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(memory), "config", "user.name", "t"], check=True)
    bank_index.invalidate()
    return memory


def test_a_number_lands_on_a_persons_page_with_located_evidence(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t = tok(memory, A)
    ep = episode(memory, "2026-08-20", f"Ana Diaz's number is {t}")
    pipeline(memory, extraction(memory, ep, "Ana Diaz", t), name_to_id={"ana diaz": "ana-diaz"})
    got, = [c for c in claims_on(memory, "ana-diaz") if c.predicate == "phone"]
    assert got.object == t and got.object_kind == "literal" and got.valid_to is None
    span = got.evidence[0]
    assert span.kind == "user" and t in markdown_parser.parse(memory / "episodes" / f"{ep}.md").body[span.start:span.end]


def test_a_changed_number_end_to_end_through_the_persons_line(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t1, t2 = tok(memory, A), tok(memory, B)
    pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Ana Diaz's number is {t1}"), "Ana Diaz", t1),
             name_to_id={"ana diaz": "ana-diaz"})
    pipeline(memory, extraction(memory, episode(memory, "2026-08-25", f"Ana Diaz changed her number to {t2}"), "Ana Diaz", t2),
             name_to_id={"ana diaz": "ana-diaz"})
    numbers = {c.object: c for c in claims_on(memory, "ana-diaz") if c.predicate == "phone"}
    assert numbers[t2].valid_to is None and numbers[t1].valid_to == "2026-08-25"


def test_changed_from_one_to_another_files_only_the_new_one(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t1, t2 = tok(memory, A), tok(memory, B)
    pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Ana Diaz's number is {t1}"), "Ana Diaz", t1),
             name_to_id={"ana diaz": "ana-diaz"})
    ep = episode(memory, "2026-08-25", f"Ana Diaz changed her number from {t1} to {t2}")
    pipeline(memory, extraction(memory, ep, "Ana Diaz", t2), name_to_id={"ana diaz": "ana-diaz"})
    assert [c.object for c in claims_on(memory, "ana-diaz") if c.predicate == "phone" and c.valid_to is None] == [t2]


def test_changed_from_one_to_another_with_both_filed_keeps_only_the_new_one_either_order(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t1, t2 = tok(memory, A), tok(memory, B)
    ep = episode(memory, "2026-08-25", f"Ana Diaz changed her number from {t1} to {t2}")
    both = extraction(memory, ep, "Ana Diaz", t2)
    both["values"] = extraction(memory, ep, "Ana Diaz", t2)["values"] + extraction(memory, ep, "Ana Diaz", t1)["values"]
    pipeline(memory, both, name_to_id={"ana diaz": "ana-diaz"})
    assert [c.object for c in claims_on(memory, "ana-diaz") if c.predicate == "phone" and c.valid_to is None] == [t2]


def test_two_people_on_one_line_are_two_numbers(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    page(memory, "bob-example", "Bob Example")
    t1, t2 = tok(memory, A), tok(memory, B)
    ep = episode(memory, "2026-08-25", f"Ana Diaz's new number is {t1} and Bob Example's new number is {t2}")
    both = extraction(memory, ep, "Ana Diaz", t1)
    both["values"] += extraction(memory, ep, "Bob Example", t2)["values"]
    pipeline(memory, both, name_to_id={"ana diaz": "ana-diaz", "bob example": "bob-example"})
    assert [c.object for c in claims_on(memory, "ana-diaz") if c.predicate == "phone" and c.valid_to is None] == [t1]
    assert [c.object for c in claims_on(memory, "bob-example") if c.predicate == "phone" and c.valid_to is None] == [t2]


def test_digits_in_another_script_are_not_a_number_to_hash(home):
    assert phone_numbers.match_digits("\u0662\u0660\u0662\u0665\u0665\u0665\u0660\u0661\u0664\u0663") is None


def test_a_number_for_a_name_with_no_page_is_held_and_lands_when_it_has_one(memory):
    t = tok(memory, A)
    ep = episode(memory, "2026-08-20", f"Carla Example's number is {t}")
    pending_store.upsert(memory, pending_store.PendingEntity(name="Carla Example", type="person", description="", source_episode=ep,
                                                             confidence=0.6, tags=[], history_entries=[]))
    out = pipeline(memory, extraction(memory, ep, "Carla Example", t))
    assert out["claims_held"] == 1
    assert not (memory / "entities" / "carla-example.md").exists()
    assert t in (memory / pending_store.PENDING_STORE_FILE).read_text()
    assert A_DIGITS.encode() not in every_byte(memory)
    page(memory, "carla-example", "Carla Example")
    pipeline(memory, name_to_id={"carla example": "carla-example"})
    assert [c.object for c in claims_on(memory, "carla-example") if c.predicate == "phone"] == [t]


def test_a_number_never_goes_on_a_page_that_is_no_person(memory):
    page(memory, "acme", "Acme", type_="company")
    t = tok(memory, A)
    pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Acme's number is {t}"), "Acme", t),
             name_to_id={"acme": "acme"})
    assert not [c for c in claims_on(memory, "acme") if c.predicate == "phone"]


def _one_word(memory, **fm):
    page(memory, "ana", "Ana", **fm)
    t = tok(memory, A)
    out = pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Ana's number is {t}"), "Ana", t),
                   name_to_id={"ana": "ana"})
    return t, out


def test_a_first_name_only_page_asks_and_holds_nothing_as_current(memory):
    t, out = _one_word(memory)
    got, = [c for c in claims_on(memory, "ana") if c.predicate == "phone"]
    assert got.object == t and got.valid_to is not None and got.context == phone_numbers.ASKED
    nudge, = [n for n in out["nudges"] if n["action"] == "divergence_nudge"]
    assert nudge["existing_claim_id"] is None and "[number:" not in json.dumps(nudge)


def test_a_relation_page_needs_no_asking(memory):
    t, out = _one_word(memory, unnamed=True)
    got, = [c for c in claims_on(memory, "ana") if c.predicate == "phone"]
    assert got.valid_to is None and not [n for n in out["nudges"] if n["action"] == "divergence_nudge"]


def test_a_card_the_page_carries_and_that_holds_the_number_settles_the_name(memory):
    card = "12345678-1234-1234-1234-123456789012:ABPerson"
    t = tok(memory, A)
    phone_numbers.save_cards(memory.name, {phone_numbers.token_ids(t)[0]: [card]})
    page(memory, "ana", "Ana", sources=[{"ref": f"addressbook://{card}", "kind": "app", "predicate": "phone"}])
    pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Ana's number is {t}"), "Ana", t), name_to_id={"ana": "ana"})
    got, = [c for c in claims_on(memory, "ana") if c.predicate == "phone"]
    assert got.valid_to is None


def test_a_card_another_page_carries_asks(memory):
    t = tok(memory, A)
    phone_numbers.save_cards(memory.name, {phone_numbers.token_ids(t)[0]: ["11111111-1111-1111-1111-111111111111:ABPerson"]})
    page(memory, "ana-diaz", "Ana Diaz", sources=[{"ref": "addressbook://22222222-2222-2222-2222-222222222222:ABPerson",
                                                    "kind": "app", "predicate": "phone"}])
    out = pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Ana Diaz's number is {t}"), "Ana Diaz", t),
                   name_to_id={"ana diaz": "ana-diaz"})
    got, = [c for c in claims_on(memory, "ana-diaz") if c.predicate == "phone"]
    assert got.valid_to is not None and "another card" in next(n for n in out["nudges"] if n["action"] == "divergence_nudge")["conflict_context"]


def test_the_owners_own_number_lands_on_the_owners_page_without_asking(memory):
    page(memory, "alex-owner", "Alex", owner=True)
    t = tok(memory, A)
    ep = episode(memory, "2026-08-20", f"my number is {t}")
    claim_pipeline.run_claim_pipeline([extraction(memory, ep, "the user", t)],
                                      [{"id": "alex-owner", "name": "Alex", "frontmatter": {"owner": True}}], memory,
                                      settings_for(memory), now_date="2026-09-01", decay=False)
    got, = [c for c in claims_on(memory, "alex-owner") if c.predicate == "phone"]
    assert got.object == t and got.valid_to is None


# ---- the answer ----

def _asked(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t1, t2 = tok(memory, A), tok(memory, B)
    pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Ana Diaz's number is {t1}"), "Ana Diaz", t1),
             name_to_id={"ana diaz": "ana-diaz"})
    out = pipeline(memory, extraction(memory, episode(memory, "2026-08-25", f"for Ana Diaz, {t2}"), "Ana Diaz", t2),
                   name_to_id={"ana diaz": "ana-diaz"})
    inbox_generator.write_claim_nudges(out["nudges"], memory)
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True)
    item, = [p for p in (memory / "inbox").glob("inbox-*.md")
             if markdown_parser.parse(p).frontmatter.get("predicate") == "phone"]
    return t1, t2, item


def _answer(memory, item, key):
    import asyncio

    asyncio.run(inbox_service.resolve(item.stem, InboxResolveRequest(action="resolve", option_key=key), settings_for(memory)))
    return {c.object: c for c in claims_on(memory, "ana-diaz") if c.predicate == "phone"}


def test_the_question_carries_no_number_and_says_what_it_asks(memory):
    _t1, _t2, item = _asked(memory)
    text = item.read_text()
    assert "[number:" not in text and A_DIGITS not in text and "number change" in text


@pytest.mark.parametrize(("key", "first_open", "second_open"), [("0", True, False), ("1", False, True), ("2", True, True)])
def test_the_persons_answer_decides(memory, key, first_open, second_open):
    t1, t2, item = _asked(memory)
    numbers = _answer(memory, item, key)
    assert (numbers[t1].valid_to is None) is first_open
    assert (numbers[t2].valid_to is None) is second_open
    if second_open:
        assert numbers[t2].source_trust == "user_stated" and numbers[t2].context == "general"
    else:
        assert numbers[t2].context == phone_numbers.REFUSED


# ---- G209 ----

def test_two_people_with_one_number_are_asked_about_and_never_merged(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    page(memory, "ann-example", "Ann Example")
    t = tok(memory, A)
    pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Ana Diaz's number is {t}"), "Ana Diaz", t),
             extraction(memory, episode(memory, "2026-08-21", f"Ann Example's number is {t}"), "Ann Example", t),
             name_to_id={"ana diaz": "ana-diaz", "ann example": "ann-example"})
    assert (memory / "entities" / "ana-diaz.md").exists() and (memory / "entities" / "ann-example.md").exists()
    items = [markdown_parser.parse(p) for p in (memory / "inbox").glob("*.md")]
    asked = [i for i in items if i.frontmatter.get("merge_target_hint") == "ann-example"]
    assert len(asked) == 1 and asked[0].frontmatter["entity_id"] == "ana-diaz"


def test_a_number_on_the_owners_page_is_never_a_duplicate_signal(memory):
    claim = lambda s: Claim(id=s, text="x", subject=s, predicate="phone", object="[number:aaaaaaaaaa]", object_kind="literal")  # noqa: E731
    assert phone_numbers.shared_pairs({"me": [claim("me")], "ana": [claim("ana")]}, {"[number:aaaaaaaaaa]"}, owner_id="me") == []


# ---- Contacts ----

def test_a_contacts_sync_keeps_hashes_outside_the_bank_and_refuses_a_digit(memory):
    good = "abcdefghij"
    contacts_local.sync(memory, {"contacts": [
        {"id": "11111111-1111-1111-1111-111111111111:ABPerson", "given_name": "Ana", "family_name": "Diaz", "phone_keys": [good, A_DIGITS, A]},
        {"id": "22222222-2222-2222-2222-222222222222:ABPerson", "given_name": "Me", "family_name": "Me", "phone_keys": [good], "is_me": True},
    ]})
    cards = phone_numbers.cards_of(memory.name)
    assert list(cards) == [good] and sorted(cards[good]) == ["11111111-1111-1111-1111-111111111111:ABPerson", "me"]
    raw = every_byte(memory) + every_byte(people_directory.folder(memory.name))
    assert A_DIGITS.encode() not in raw and good.encode() not in every_byte(memory)
    waiting = json.loads(people_directory.path(memory.name, contacts_local.WAITING_FILE).read_text())
    assert "phone_keys" not in json.dumps(waiting)


def test_a_contacts_sync_keeps_no_hash_while_it_is_off(bank):
    contacts_local.sync(bank, {"contacts": [{"id": "11111111-1111-1111-1111-111111111111:ABPerson", "given_name": "Ana",
                                             "family_name": "Diaz", "phone_keys": ["abcdefghij"]}]})
    assert not people_directory.path(bank.name, phone_numbers.CARDS_FILE).exists()


def test_the_app_and_the_backend_compute_one_token():
    """The Swift half (`PhoneNumberKeys`) is pinned to these values by `PhoneNumberKeysTests`."""
    key = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
    assert phone_numbers.match_digits("+1 202 555 0143") == "025550143"
    assert phone_numbers._token_id(key, "025550143") == VECTOR


VECTOR = "zgjpbdixkc"


# ---- the doors ----

@pytest.fixture
def client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_reveal_route_answers_the_mac_and_refuses_a_device(client, memory, monkeypatch):
    t = phone_numbers.token_ids(tok(memory, A))[0]
    out = client.post("/people/numbers/reveal", json={"tokens": [t, "not-a-token"]})
    assert out.status_code == 200 and out.json() == {"numbers": {t: A}, "problem": None}
    monkeypatch.setattr("api.routers.local_sources.request_device", lambda _r: SimpleNamespace(id="d", kind="full"))
    assert client.post("/people/numbers/reveal", json={"tokens": [t]}).status_code == 403
    assert client.get("/people/numbers/match-key").status_code == 403


def test_the_match_key_is_nothing_while_off(client, monkeypatch):
    phone_numbers.set_enabled(False)
    assert client.get("/people/numbers/match-key").json() == {"key": None}


def _bank_with_numbers(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t = tok(memory, A)
    ep = episode(memory, "2026-08-20", f"Ana Diaz's number is {t}")
    pipeline(memory, extraction(memory, ep, "Ana Diaz", t), name_to_id={"ana diaz": "ana-diaz"})
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True)
    bank_index.invalidate()
    return t


def test_nothing_in_the_bank_or_its_history_holds_a_digit(memory):
    _bank_with_numbers(memory)
    assert A_DIGITS.encode() not in every_byte(memory)
    log = subprocess.run(["git", "-C", str(memory), "log", "-p", "--all"], capture_output=True, check=True).stdout
    assert A_DIGITS.encode() not in log and b"555 0143" not in log


def test_the_agent_tools_read_the_token_never_the_digits(memory):
    from api.services import mcp_tools

    t = _bank_with_numbers(memory)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="claude-code", client_name="claude-code")
    reply = json.dumps(mcp_tools.recall_detail(ctx, "ana-diaz", whole=True), default=str)
    assert A_DIGITS not in reply and "555 0143" not in reply
    assert t in reply or "phone" in reply


def test_the_handshake_says_nothing_of_a_number(memory, tmp_path):
    from api.services import handshake

    _bank_with_numbers(memory)
    reply, _meta = handshake.load_or_build(memory, "claude-code", variant="claude-code", cache_dir=tmp_path / "cache")
    assert A_DIGITS not in reply and "555 0143" not in reply and "[number:" not in reply


def test_the_engine_is_given_the_token_never_the_digits(memory, monkeypatch):
    """Stage 1's whole prompt, from a real chat's stored body."""
    import asyncio

    from api.services import entity_extractor

    chat_live.update_settings(memory, SPEC, {"id": CHAT, "name": "Bob Example", "group": False, "ticked": True},
                              now="2026-08-28T00:00:00+00:00")
    ingest(memory, [row("AAA1", T0, f"Ana Diaz's number is {A}", me=True), row("AAA2", T0 + 5, f"mine is {B}")])
    seen: list[str] = []

    async def fake(ep_id, chunk, ci, total, settings, **kw):
        seen.append(chunk + "\n" + str(kw.get("source_note") or ""))
        return {"entities": [], "relationships": [], "values": []}

    monkeypatch.setattr(entity_extractor, "_extract_chunk", fake)
    path = next((memory / "episodes").glob("*.md"))
    parsed = markdown_parser.parse(path)
    episode_ = {**parsed.frontmatter, "id": path.stem, "content": parsed.body}
    asyncio.run(entity_extractor.extract([episode_], settings_for(memory)))
    prompt = "\n".join(seen)
    assert "[number:" in prompt and "stands for a phone number" in prompt
    assert A_DIGITS not in prompt and B_DIGITS not in prompt and "555 0143" not in prompt


def test_the_engine_is_given_no_note_when_no_token_is_there(memory, monkeypatch):
    import asyncio

    from api.services import entity_extractor

    seen: list[str] = []

    async def fake(ep_id, chunk, ci, total, settings, **kw):
        seen.append(str(kw.get("source_note") or ""))
        return {"entities": [], "relationships": [], "values": []}

    monkeypatch.setattr(entity_extractor, "_extract_chunk", fake)
    episode_ = {"id": "ep_2026-08-29_001", "timestamp": "2026-08-29T10:00:00+00:00", "content": "user: hello there", "origin": "x"}
    asyncio.run(entity_extractor.extract([episode_], settings_for(memory)))
    assert seen and all("stands for a phone number" not in s for s in seen)


def test_the_reveal_is_on_the_mac_only_never_the_remote_listener():
    """The remote listener serves MCP, `/v1` and its OAuth (G135); the route is on the local app alone."""
    from pathlib import Path as P

    listener = "\n".join(p.read_text() for p in (P(__file__).parents[1] / "services").glob("remote*.py"))
    assert "numbers/reveal" not in listener and "local_sources" not in listener


def _messages_chat(tmp_path, memory):
    from _imessage_fixtures import ChatDB, conversation_id, payload, read_rows, utc
    from api.models.schemas import MessagesSyncRequest
    from api.services import messages_source

    db = ChatDB(tmp_path / "chat.db")
    agent = db.chat("+15550100001")
    db.message(agent, utc(2026, 9, 3, 10, 0), from_me=True, text=f"Add Ana Diaz, her number is {A}")
    db.message(agent, utc(2026, 9, 3, 10, 1), from_me=False, text=f"Added Ana Diaz at {A}")
    db.message(agent, utc(2026, 9, 3, 10, 2), from_me=True, text="and Bob Example 2025550177")
    db.db.commit()
    messages_source.update_settings(memory, conversation={"id": conversation_id(db.chat_guid(agent)), "name": "Agent Example",
                                                          "ticked": True, "history": True})

    def sync():
        guid = db.chat_guid(agent)
        body = payload(guid, read_rows(db.path, agent), name="Agent Example")
        out = messages_source.ingest(memory, MessagesSyncRequest.model_validate(body).model_dump(by_alias=False), bank=memory.name)
        bank_index.invalidate()
        return out
    return db, sync


def test_messages_the_owners_own_case_through_the_real_reader(bank, tmp_path, on):
    """A texted agent: the person's numbers as tokens, the agent's echo redacted, and a re-read moves nothing."""
    db, sync = _messages_chat(tmp_path, bank)
    try:
        sync()
        before = stored(bank)
        (body, _fm), = before.values()
        lines = body.split("\n")
        assert phone_numbers.has_token(lines[0]) and "[redacted]" in lines[1]
        assert A_DIGITS not in body and "202 555 0143" not in body
        assert phone_numbers.has_token(lines[2]) and B_DIGITS not in body
        assert sync()["updated"] == 0 and stored(bank) == before
    finally:
        db.close()


def test_messages_turning_it_on_moves_no_stored_byte(bank, tmp_path, monkeypatch):
    db, sync = _messages_chat(tmp_path, bank)
    try:
        sync()
        before = stored(bank)
        (body, _fm), = before.values()
        assert body.startswith("user: Add Ana Diaz, her number is [redacted]") and B_DIGITS in body   # as it was stored
        phone_numbers.set_enabled(True)
        assert sync()["updated"] == 0
        assert stored(bank) == before
    finally:
        db.close()


def test_messages_tokens_the_persons_words_too(tmp_path, home, on):
    """The owner's own case: a texted agent, through Messages."""
    from api.services import messages_source

    memory = tmp_path / "m"
    (memory / "episodes").mkdir(parents=True)
    message = messages_source.Message(key="k1", ts="2026-09-01T10:00:00+00:00", from_me=True, text=f"add Ana, {A}")
    agent = messages_source.Message(key="k2", ts="2026-09-01T10:00:05+00:00", from_me=False, text=f"Added Ana at {A}")
    phone_numbers.tokenise_batch([message, agent], {}, writer=messages_source.SCRUB_WRITER, bank=memory.name)
    assert phone_numbers.has_token(message.text)
    assert "[redacted]" in agent.text and not phone_numbers.has_token(agent.text)


def test_the_note_stage_one_is_given_holds_no_digit():
    assert not any(c.isdigit() for c in phone_numbers.NOTE)


def test_a_writer_never_logs_a_number(bank, on, capfd):
    from loguru import logger

    sink = []
    handle = logger.add(sink.append)
    try:
        ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True)])
    finally:
        logger.remove(handle)
    assert not any(A_DIGITS in str(s) or "555 0143" in str(s) for s in sink)


def test_an_agents_claim_is_a_token_too_when_on(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    agentic_write.write_claim(memory, "Ana Diaz", "phone", A, observer="external:claude-code", object_kind="literal")
    got, = [c for c in claims_on(memory, "ana-diaz") if c.predicate == "phone"]
    assert phone_numbers.has_token(got.object) and A_DIGITS not in got.text and "555 0143" not in got.text


def test_an_agents_claim_is_as_it_was_while_off(bank):
    page(bank, "ana-diaz", "Ana Diaz")
    agentic_write.write_claim(bank, "Ana Diaz", "phone", A, observer="external:claude-code", object_kind="literal")
    got, = [c for c in claims_on(bank, "ana-diaz") if c.predicate == "phone"]
    assert got.object == A


# ---- the review of #603, one test per item (the reviewer reproduced each with the switch on) ----

def _phones(memory, stem="ana-diaz"):
    return {c.object: c for c in claims_on(memory, stem) if c.predicate == "phone"}


NAME = {"ana diaz": "ana-diaz"}


def _file(memory, day, line, *tokens, name="Ana Diaz", **kw):
    ep = episode(memory, day, line)
    filed = extraction(memory, ep, name, tokens[0])
    for t in tokens[1:]:
        filed["values"] += extraction(memory, ep, name, t)["values"]
    return pipeline(memory, filed, name_to_id=NAME, **kw)


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_item_3_new_then_old_on_one_line_leaves_the_new_one_current(memory, order):
    page(memory, "ana-diaz", "Ana Diaz")
    old, new = tok(memory, A), tok(memory, B)
    _file(memory, "2026-08-20", f"Ana Diaz's number is {old}", old)
    both = [new, old]
    _file(memory, "2026-08-25", f"Ana Diaz's new number is {new}, the old one was {old}", both[order[0]], both[order[1]])
    numbers = _phones(memory)
    assert numbers[new].valid_to is None and numbers[old].valid_to is not None


def test_item_3_a_number_the_line_says_replaced_another_never_closes_a_third(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    third, new, old = tok(memory, A), tok(memory, B), tok(memory, "+1 202 555 0166")
    _file(memory, "2026-08-20", f"Ana Diaz's number is {third}", third)
    out = _file(memory, "2026-08-25", f"Ana Diaz's new number is {new}, the old one was {old}", new)
    numbers = _phones(memory)
    assert numbers[third].valid_to is None and numbers[new].context == phone_numbers.ASKED
    assert [n for n in out["nudges"] if n["action"] == "divergence_nudge"]


@pytest.mark.parametrize("line", ["I was talking to Ana Diaz, her number is {t}", "I was texting Ana Diaz on {t}",
                                  "Ana Diaz got a new job, her desk line is {t}"])
def test_item_4_an_unclear_line_asks_and_closes_nothing(memory, line):
    page(memory, "ana-diaz", "Ana Diaz")
    held, said = tok(memory, A), tok(memory, B)
    _file(memory, "2026-08-20", f"Ana Diaz's number is {held}", held)
    out = _file(memory, "2026-08-25", line.format(t=said), said)
    numbers = _phones(memory)
    assert numbers[held].valid_to is None and numbers[said].valid_to is not None
    assert numbers[said].context == phone_numbers.ASKED
    assert [n for n in out["nudges"] if n["action"] == "divergence_nudge"]


def test_item_4_an_unclear_line_about_a_first_number_lands_open(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    said = tok(memory, A)
    _file(memory, "2026-08-25", f"I was talking to Ana Diaz, her number is {said}", said)
    assert _phones(memory)[said].valid_to is None


def test_item_5_two_numbers_sharing_their_last_nine_digits_keep_two_tokens_and_both_forms(home):
    a, b = "+1 202 555 0143", "+44 202 555 0143"
    ids = phone_numbers.mint_many("b", [a, b])
    assert ids[a] != ids[b]
    assert phone_numbers.reveal("b", [ids[a], ids[b]]) == {ids[a]: a, ids[b]: b}
    # the same two again resolve to the same two
    assert phone_numbers.mint_many("b", [a, b]) == ids


def test_item_5_every_written_form_of_a_number_is_kept(home):
    a, b = "202 555 0143", "(202) 555-0143"
    ids = phone_numbers.mint_many("b", [a, b])
    assert ids[a] == ids[b]
    held = json.loads(people_directory.path("b", phone_numbers.VAULT_FILE).read_text())["numbers"][ids[a]]
    assert held["forms"] == [a, b]


@pytest.mark.parametrize("label", ["phone", "phone_number", "mobile number", "mobile_number", "has_phone", "tel", "cell",
                                   "whatsapp", "work phone", "contact number", "number", "phone number", "teléfono"])
def test_item_6_these_labels_say_phone(label):
    assert phone_numbers.is_phone_label(label)


@pytest.mark.parametrize("label", ["membership number", "order number", "passport number", "mobile app version",
                                   "flight number", "account number", "number of rooms", "", "age"])
def test_item_6_these_do_not(label):
    assert not phone_numbers.is_phone_label(label)


def test_item_6_a_models_membership_number_stays_what_it_is(home, on):
    values = [{"entity": "Ana Diaz", "attribute": "membership number", "value": "2025550143"}]
    assert phone_numbers.take([], [], values, "user: Ana's membership number is 2025550143", "ep_2026-08-29_001", bank="b") == 0
    assert values == [{"entity": "Ana Diaz", "attribute": "membership number", "value": "2025550143"}]


def test_item_6_an_agents_order_number_stays_what_it_is(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    agentic_write.write_claim(memory, "Ana Diaz", "order number", "2025550143", observer="external:claude-code",
                              object_kind="literal")
    assert not [c for c in claims_on(memory, "ana-diaz") if c.predicate == "phone"]


@pytest.mark.parametrize("label", ["phone_number", "mobile_number", "has_phone", "tel", "phone"])
def test_item_7_an_agents_phone_claim_holds_no_digit_whatever_its_label(memory, label):
    page(memory, "ana-diaz", "Ana Diaz")
    out = agentic_write.write_claim(memory, "Ana Diaz", label, "+12025550143", observer="external:claude-code",
                                    object_kind="literal")
    assert out["action"] != "error"
    got, = [c for c in claims_on(memory, "ana-diaz") if c.predicate == "phone"]
    assert phone_numbers.has_token(got.object)
    assert A_DIGITS not in (memory / "entities" / "ana-diaz.md").read_text()


def test_item_7_changed_from_one_to_another_leaves_no_digit_in_the_line(home):
    out, n = phone_numbers.tokenise("she changed her number from 2025550143 to 2025550177", "b")
    assert n == 2 and not any(c.isdigit() for c in out) and len(phone_numbers.token_ids(out)) == 2
    first, second = phone_numbers.token_ids(out)
    read = phone_numbers.read_line(out)
    assert read[first][0] == phone_numbers.PAST and read[second] == (phone_numbers.CHANGED, [first])


def test_item_7_the_body_and_prompt_of_that_scenario_hold_no_digit(bank, on):
    ingest(bank, [row("AAA1", T0, "she changed her number from 2025550143 to 2025550177", me=True)])
    (body, _fm), = stored(bank).values()
    assert A_DIGITS not in body and B_DIGITS not in body and phone_numbers.has_token(body)


def test_item_7_a_pages_prose_holds_no_number_whoever_wrote_it(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    path = memory / "entities" / "ana-diaz.md"
    parsed = markdown_parser.parse(path)
    t = tok(memory, B)
    fence = ('```claims\n{"id": "c1", "text": "x", "subject": "ana-diaz", "predicate": "phone", "object": "' + t +
             '", "object_kind": "literal"}\n```\n')
    markdown_parser.write(path, parsed.frontmatter, f"# Ana\n\nHer number is {A}. Also {t}.\n\n{fence}")
    text = path.read_text()
    assert A_DIGITS not in text and "202 555 0143" not in text
    prose = text.split("```claims")[0]
    assert "[number:" not in prose and t in text
    # nothing lost: the digits are in the vault
    tid = phone_numbers.mint_many(memory, [A])[A]
    assert phone_numbers.reveal(memory, [tid])[tid] == A


def test_item_7_while_off_a_pages_digits_are_as_they_were(bank):
    path = bank / "entities" / "x.md"
    markdown_parser.write(path, {"name": "X", "type": "person"}, f"Her number is {A}.")
    assert A in path.read_text()


def test_round_3_item_7_while_off_not_one_byte_of_any_page_changes(bank):
    path = bank / "entities" / "x.md"
    body = f"She quotes [number:abcdefghij] and {A}."
    markdown_parser.write(path, {"name": "X", "type": "person"}, body)
    assert body in path.read_text()
    assert phone_numbers.clean_page(body, bank) == body


def test_item_7_a_digit_fact_from_a_conversation_with_no_token_leaves_the_prose(home, on):
    entities = [{"name": "Ana Diaz", "summary": f"her number is {A}", "key_facts": [f"her number is {A}", "lives nearby"]}]
    phone_numbers.take(entities, [], [], f"user: her number is {A}", "ep_2026-08-29_001", bank="b")
    assert "555" not in json.dumps(entities) and "lives nearby" in json.dumps(entities)


def _damage(memory):
    path = people_directory.path(memory.name, phone_numbers.VAULT_FILE)
    path.write_text("{ not json")
    return path, path.read_bytes()


def test_item_8_a_damaged_vault_is_never_overwritten_and_gets_no_new_key(memory):
    tok(memory, A)
    path, damaged = _damage(memory)
    with pytest.raises(phone_numbers.VaultUnavailable):
        phone_numbers.mint_many(memory, [B])
    with pytest.raises(phone_numbers.VaultUnavailable):
        phone_numbers.match_key(memory)
    assert path.read_bytes() == damaged
    assert "can't be read" in phone_numbers.problem(memory)


@pytest.mark.parametrize("content", ['{"numbers": {}}', '{"key": "short", "numbers": {}}', '[]', '{"key": "AAAA", "numbers": 3}'])
def test_item_8_a_vault_of_the_wrong_shape_counts_as_damaged(memory, content):
    tok(memory, A)
    path = people_directory.path(memory.name, phone_numbers.VAULT_FILE)
    path.write_text(content)
    with pytest.raises(phone_numbers.VaultUnavailable):
        phone_numbers.mint_many(memory, [B])
    assert path.read_text() == content


def test_item_8_with_no_usable_vault_a_chat_number_is_redacted_never_stored(bank, on):
    tok(bank, A)
    _damage(bank)
    ingest(bank, [row("AAA1", T0, "her number is 202 555 0177", me=True)])
    (body, _fm), = stored(bank).values()
    assert "[redacted]" in body and B_DIGITS[-4:] not in body and "[number:" not in body


def test_item_8_a_missing_vault_with_tokens_in_the_bank_is_the_same_case(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t = tok(memory, A)
    _file(memory, "2026-08-20", f"Ana Diaz's number is {t}", t)
    people_directory.path(memory.name, phone_numbers.VAULT_FILE).unlink()
    with pytest.raises(phone_numbers.VaultUnavailable):
        phone_numbers.mint_many(memory, [B])
    assert not people_directory.path(memory.name, phone_numbers.VAULT_FILE).exists()
    assert "gone" in phone_numbers.problem(memory)


def test_item_8_a_restatement_with_a_lost_vault_still_reads_as_the_same_number(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t = tok(memory, A)
    _file(memory, "2026-08-20", f"Ana Diaz's number is {t}", t)
    _damage(memory)
    out = _file(memory, "2026-08-25", f"Ana Diaz's number is {t}", t)
    assert not [n for n in out["nudges"] if n["action"] == "divergence_nudge"]
    assert _phones(memory)[t].valid_to is None


def test_item_8_an_agents_digit_claim_is_refused_in_words_with_no_usable_vault(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    tok(memory, A)
    _damage(memory)
    out = agentic_write.write_claim(memory, "Ana Diaz", "phone", B, observer="external:claude-code", object_kind="literal")
    assert out["action"] == "error" and "private file" in out["error"]
    assert B_DIGITS[-4:] not in (memory / "entities" / "ana-diaz.md").read_text()


def test_item_8_a_new_vault_is_the_persons_own_act_and_keeps_the_old_file(memory, client):
    tok(memory, A)
    path, damaged = _damage(memory)
    assert client.post("/people/numbers/reveal", json={"tokens": []}).json()["problem"]
    kept = client.post("/people/numbers/new-vault").json()["set_aside"]
    assert (path.parent / kept).read_bytes() == damaged
    assert client.post("/people/numbers/reveal", json={"tokens": []}).json()["problem"] is None
    assert phone_numbers.mint_many(memory, [B])


def test_item_8_the_trash_keeps_the_vault_beside_the_bank_and_a_restored_bank_finds_it(tmp_path, home):
    root = tmp_path / "root"
    memory = root / "banks" / "alpha"
    (memory / "episodes").mkdir(parents=True)
    t = tok(memory, A)
    (memory / "episodes" / "ep_2026-08-20_001.md").write_text(f"---\nid: x\norigin: whatsapp\n---\nuser: her number is {t}")
    trashed = root / ".trash" / "alpha-20261104T000000Z"
    trashed.parent.mkdir(parents=True)
    phone_numbers.park_for_trash("alpha", trashed)
    parked = trashed.with_name(f"{trashed.name}.numbers.json")
    assert parked.is_file() and stat.S_IMODE(parked.stat().st_mode) == 0o600
    people_directory.forget("alpha")
    assert not people_directory.path("alpha", phone_numbers.VAULT_FILE).exists()
    # restored by hand: the bank's own folder back, its numbers with it, the same key
    assert phone_numbers.mint_many(memory, [A])[A] == phone_numbers.token_ids(t)[0]
    assert phone_numbers.reveal(memory, phone_numbers.token_ids(t))[phone_numbers.token_ids(t)[0]] == A
    assert not parked.exists()


def test_item_8_emptying_the_trash_takes_the_digits(tmp_path, home):
    root = tmp_path / "root"
    memory = root / "banks" / "alpha"
    (memory / "episodes").mkdir(parents=True)
    tok(memory, A)
    trashed = root / ".trash" / "alpha-20261104T000000Z"
    trashed.parent.mkdir(parents=True)
    phone_numbers.park_for_trash("alpha", trashed)
    assert A_DIGITS[-4:] not in every_byte(people_directory.folder("alpha")).decode() if people_directory.folder("alpha").exists() else True
    trashed.with_name(f"{trashed.name}.numbers.json").unlink()   # what emptying the trash does
    assert A_DIGITS[-4:] not in every_byte(root).decode()


def _revise(memory, ep, new_body):
    from api.services import episode_revision

    path = memory / "episodes" / f"{ep}.md"
    parsed = markdown_parser.parse(path)
    prior = parsed.body
    markdown_parser.write(path, parsed.frontmatter, new_body)
    rev = episode_revision.build({"id": ep, "content": new_body}, prior)
    assert rev is not None
    return rev


def _revision_filed(memory, ep, name, t):
    day = ep[3:13]
    values = [{"entity": name, "attribute": "phone number", "value": t}]
    body = markdown_parser.parse(memory / "episodes" / f"{ep}.md").body
    phone_numbers.take([], [], values, body, ep, bank=memory)
    for v in values:
        v.update(source_episode=ep, source_episode_timestamp=f"{day}T10:00:00+00:00", origin="whatsapp")
    return {"episode_id": ep, "episode_timestamp": f"{day}T10:00:00+00:00", "origin": "whatsapp", "entities": [],
            "relationships": [], "values": values}


def test_item_9_rewording_a_line_keeps_its_number_with_no_question(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t = tok(memory, A)
    ep = episode(memory, "2026-08-20", f"Ana Diaz's number is {t}")
    pipeline(memory, extraction(memory, ep, "Ana Diaz", t), name_to_id=NAME)
    rev = _revise(memory, ep, f"user: Oh, and Ana Diaz's number is {t}")
    out = claim_pipeline.run_claim_pipeline(
        [_revision_filed(memory, ep, "Ana Diaz", t)], [], memory, settings_for(memory), now_date="2026-09-01",
        name_to_id=NAME, decay=False, revisions={ep: rev})
    numbers = _phones(memory)
    assert numbers[t].valid_to is None
    assert not [n for n in out["nudges"] if n["action"] == "divergence_nudge"]
    assert not [c for c in claims_on(memory, "ana-diaz") if c.predicate == "retracts"]


def test_item_9_fixing_a_typo_in_a_number_supersedes_in_place_and_leaves_one_open(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    typo, fixed = tok(memory, "+1 202 555 0134"), tok(memory, A)
    ep = episode(memory, "2026-08-20", f"Ana Diaz's number is {typo}")
    pipeline(memory, extraction(memory, ep, "Ana Diaz", typo), name_to_id=NAME)
    rev = _revise(memory, ep, f"user: Ana Diaz's number is {fixed}")
    out = claim_pipeline.run_claim_pipeline(
        [_revision_filed(memory, ep, "Ana Diaz", fixed)], [], memory, settings_for(memory), now_date="2026-09-01",
        name_to_id=NAME, decay=False, revisions={ep: rev})
    numbers = _phones(memory)
    assert numbers[fixed].valid_to is None and numbers[typo].valid_to is not None
    assert numbers[typo].superseded_by == numbers[fixed].id
    assert not [n for n in out["nudges"] if n["action"] == "divergence_nudge"]


def test_item_9_another_conversations_different_number_still_asks(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    a, b = tok(memory, A), tok(memory, B)
    _file(memory, "2026-08-20", f"Ana Diaz's number is {a}", a)
    out = _file(memory, "2026-08-25", f"Ana Diaz's number is {b}", b)
    assert [n for n in out["nudges"] if n["action"] == "divergence_nudge"]


CARD = "11111111-1111-1111-1111-111111111111:ABPerson"


def test_item_10_stopping_contacts_wipes_the_hashes_and_no_reader_keeps_them(memory):
    t = tok(memory, A)
    tid = phone_numbers.token_ids(t)[0]
    contacts_local.sync(memory, {"contacts": [{"id": CARD, "given_name": "Ana", "family_name": "Diaz", "phone_keys": [tid]}]})
    path = people_directory.path(memory.name, phone_numbers.CARDS_FILE)
    assert path.exists()
    page(memory, "ana", "Ana", sources=[{"ref": f"addressbook://{CARD}", "kind": "app", "predicate": "phone"}])
    contacts_local.forget_waiting()
    assert not path.exists() and phone_numbers.cards_of(memory) == {}
    # the name a card used to settle asks again
    pipeline(memory, extraction(memory, episode(memory, "2026-08-20", f"Ana's number is {t}"), "Ana", t), name_to_id={"ana": "ana"})
    assert _phones(memory, "ana")[t].context == phone_numbers.ASKED


def test_item_10_a_sync_read_before_the_stop_brings_nothing_back(memory, monkeypatch):
    monkeypatch.setattr(contacts_local, "forgotten_since", lambda _at: True)
    contacts_local.sync(memory, {"contacts": [{"id": CARD, "given_name": "Ana", "family_name": "Diaz", "phone_keys": ["abcdefghij"]}]})
    assert not people_directory.path(memory.name, phone_numbers.CARDS_FILE).exists()


def test_item_10_a_client_with_no_key_never_empties_the_file(memory):
    keys = {"contacts": [{"id": CARD, "given_name": "Ana", "family_name": "Diaz", "phone_keys": ["abcdefghij"]}]}
    contacts_local.sync(memory, keys)
    contacts_local.sync(memory, {"contacts": [{"id": CARD, "given_name": "Ana", "family_name": "Diaz"}]})
    assert phone_numbers.cards_of(memory) == {"abcdefghij": [CARD]}


def test_item_11_off_after_on_a_bare_number_posted_again_keeps_its_token(bank, on):
    lines = [row("AAA1", T0, "her number is 202 555 0143", me=True), row("AAA2", T0 + 5, f"and {B}, phone", me=True)]
    ingest(bank, lines)
    before = stored(bank)
    (body, _fm), = before.values()
    assert phone_numbers.has_token(body) and A_DIGITS[-4:] not in body
    phone_numbers.set_enabled(False)
    assert ingest(bank, lines)["updated"] == 0
    assert stored(bank) == before


def test_item_11_off_after_on_a_real_edit_still_is_one(bank, on):
    ingest(bank, [row("AAA1", T0, "her number is 202 555 0143", me=True)])
    phone_numbers.set_enabled(False)
    assert ingest(bank, [row("AAA1", T0, "her number was lost", me=True)])["updated"] == 1


def test_item_11_with_a_lost_vault_a_line_posted_again_still_stays(bank, on):
    lines = [row("AAA1", T0, "her number is 202 555 0143", me=True)]
    ingest(bank, lines)
    before = stored(bank)
    _damage(bank)
    assert ingest(bank, lines)["updated"] == 0
    assert stored(bank) == before


def test_item_12_every_process_reads_one_switch_and_the_environment_is_not_it(home, monkeypatch):
    import subprocess as sp
    import sys

    root = str(Path(__file__).resolve().parents[2])
    probe = [sys.executable, "-c", "from api.services import phone_numbers as p; print(p.enabled())"]
    env = {"CICADA_HOME": str(home), "PYTHONPATH": root, "PATH": "/usr/bin:/bin", "LITELLM_MODE": "PRODUCTION",
           "CICADA_PHONE_NUMBERS": "on"}
    assert sp.run(probe, env=env, capture_output=True, text=True, cwd=root).stdout.strip() == "False"
    phone_numbers.set_enabled(True)
    env.pop("CICADA_PHONE_NUMBERS")
    assert sp.run(probe, env=env, capture_output=True, text=True, cwd=root).stdout.strip() == "True"
    assert phone_numbers.enabled() is True
    monkeypatch.setenv("CICADA_PHONE_NUMBERS", "off")
    assert phone_numbers.enabled() is True


def test_item_12_a_damaged_switch_is_off(home):
    phone_numbers.set_enabled(True)
    phone_numbers._switch_path().write_text("{ not json")
    assert phone_numbers.enabled() is False


def test_item_12_the_yes_is_recorded_with_who_and_when_and_private(home):
    record = phone_numbers.set_enabled(True)
    saved = json.loads(phone_numbers._switch_path().read_text())
    assert saved == record and saved["on"] is True and saved["by"] == "api-token" and saved["at"]
    assert stat.S_IMODE(phone_numbers._switch_path().stat().st_mode) == 0o600


def test_item_12_the_route_turns_it_on_and_a_device_cannot(client, monkeypatch):
    assert client.put("/people/numbers/switch", json={"on": False}).json()["on"] is False
    assert phone_numbers.enabled() is False
    assert client.put("/people/numbers/switch", json={"on": True}).json()["on"] is True
    assert client.get("/people/numbers/switch").json()["on"] is True
    monkeypatch.setattr("api.routers.local_sources.request_device", lambda _r: SimpleNamespace(id="d", kind="full"))
    assert client.put("/people/numbers/switch", json={"on": False}).status_code == 403
    assert phone_numbers.enabled() is True


def test_item_12_the_vault_routes_are_refused_on_a_replica():
    from api.services import replica_routes

    for route in ("POST /people/numbers/reveal", "PUT /people/numbers/switch", "POST /people/numbers/new-vault"):
        assert replica_routes.ROUTES[route] == replica_routes.REFUSE


def test_a_numbers_question_recommends_nothing_because_it_proposes_nothing(memory):
    _t1, _t2, item = _asked(memory)
    fm = markdown_parser.parse(item).frontmatter
    options = inbox_service.inbox_questions.normalize_options(fm.get("options"))
    assert inbox_service.recommended_key("divergence", fm, options) is None


def test_an_answer_after_the_number_was_replaced_never_makes_two_current(memory):
    t1, t2, item = _asked(memory)
    t3 = tok(memory, "+1 202 555 0166")
    _file(memory, "2026-08-28", f"Ana Diaz's new number is {t3}", t3)
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "later"], check=True)
    numbers = _answer(memory, item, "1")
    assert [o for o, c in numbers.items() if c.valid_to is None] == [t3]
    assert numbers[t2].context == "general" and numbers[t2].source_trust == "user_stated"


def test_an_agents_different_number_is_refused_in_words_and_changes_nothing(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t = tok(memory, A)
    _file(memory, "2026-08-20", f"Ana Diaz's number is {t}", t)
    before = (memory / "entities" / "ana-diaz.md").read_text()
    out = agentic_write.write_claim(memory, "Ana Diaz", "phone", B, observer="external:claude-code", object_kind="literal")
    assert out["action"] == "error" and "person's own words" in out["error"]
    assert (memory / "entities" / "ana-diaz.md").read_text() == before
    # nothing was written: the refused number is not in the vault either, and the page's one still is
    held = json.loads(people_directory.path(memory.name, phone_numbers.VAULT_FILE).read_text())["numbers"]
    assert [v["forms"] for v in held.values()] == [[A]]


def test_an_agent_restating_the_same_number_changes_nothing_new(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    t = tok(memory, A)
    _file(memory, "2026-08-20", f"Ana Diaz's number is {t}", t)
    out = agentic_write.write_claim(memory, "Ana Diaz", "phone", "(202) 555-0143", observer="external:claude-code",
                                    object_kind="literal")
    assert out["action"] != "error"
    assert [o for o, c in _phones(memory).items() if c.valid_to is None] == [t]


# ---- the review of bb8145a2 ----

def _harness_session(memory, line):
    ep = "ep_2026-08-19_001"
    markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "origin": "claude-code", "source": "claude-code"}, f"user: {line}")
    return ep


def test_round_3_the_owners_own_lines_through_a_real_ingest(bank, on):
    ingest(bank, [row("AAA1", T0, "add Ana, 2025550143", me=True), row("AAA2", T0 + 5, "Added Ana at 2025550143"),
                  row("AAA3", T0 + 9, "Bob Example 2025550177", me=True), row("AAA4", T0 + 14, "she's on 2025550143", me=True),
                  row("AAA5", T0 + 20, "and my new number is 2025550166")])
    (body, _fm), = stored(bank).values()
    lines = body.split("\n")
    assert phone_numbers.has_token(lines[0]) and phone_numbers.has_token(lines[2]) and phone_numbers.has_token(lines[3])
    assert lines[0].split(", ")[1] == lines[3].split("on ")[1]     # one number, one token
    assert "[redacted]" in lines[1] and "[redacted]" in lines[4]
    assert "[number:" not in lines[1] and "[number:" not in lines[4]
    raw = every_byte(bank)
    for digits in (A_DIGITS, B_DIGITS, "2025550166"):
        assert digits.encode() not in raw
    # the vault holds only what the person gave
    assert "2025550166" not in people_directory.path(bank.name, phone_numbers.VAULT_FILE).read_text()


def test_round_3_the_echo_and_the_correspondent_posted_again_move_nothing(bank, on):
    lines = [row("AAA1", T0, "add Ana, 2025550143", me=True), row("AAA2", T0 + 5, "Added Ana at 2025550143"),
             row("AAA3", T0 + 9, "my new number is 2025550166")]
    ingest(bank, lines)
    before = stored(bank)
    assert ingest(bank, lines)["updated"] == 0
    assert stored(bank) == before


def test_round_3_old_bare_lines_stored_while_off_never_move_when_switched_on(bank):
    lines = [row("AAA1", T0, "add Ana, 2025550143", me=True), row("AAA2", T0 + 5, "Added Ana at 2025550143")]
    ingest(bank, lines)
    before = stored(bank)
    (body, _fm), = before.values()
    assert A_DIGITS in body      # as stored before the switch: it stays, and a re-read does not rewrite it
    phone_numbers.set_enabled(True)
    assert ingest(bank, lines)["updated"] == 0
    assert stored(bank) == before


def test_round_3_a_bare_number_beside_a_name_reaches_the_page_as_a_token(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    line, n = phone_numbers.tokenise("add Ana Diaz, 2025550143", memory)
    assert n == 1
    t = phone_numbers.token(phone_numbers.token_ids(line)[0])
    _file(memory, "2026-08-20", line, t)
    assert _phones(memory)[t].valid_to is None


def test_round_3_seven_digits_beside_a_person_this_memory_knows(memory):
    page(memory, "ana-diaz", "Ana Diaz", aliases=["Anita"])
    bank_index.invalidate()
    assert phone_numbers.tokenise("Ana 5550143", memory)[1] == 1
    assert phone_numbers.tokenise("Anita 5550143", memory)[1] == 1
    assert phone_numbers.tokenise("Tesla 5550144", memory)[1] == 0


def test_round_3_a_known_false_positive_is_pinned_and_the_digits_are_kept(memory):
    """A capitalised word no list knows, then nine digits or more, ending the clause: read as a name. The vault keeps it."""
    line, n = phone_numbers.tokenise("Tesla 2025550143", memory)
    assert n == 1
    tid = phone_numbers.token_ids(line)[0]
    assert phone_numbers.reveal(memory, [tid])[tid] == "2025550143"


def test_round_3_item_1_a_session_that_mentions_the_shape_is_no_token(memory):
    _harness_session(memory, "the token looks like [number:abcdefghij] in the bank")
    page(memory, "feature", "Feature", type_="concept")
    (memory / "entities" / "note.md").write_text("---\nname: Note\n---\nIt quotes [number:klmnopqrst].\n")
    assert phone_numbers.bank_token_ids(memory) == set()
    assert phone_numbers.problem(memory) is None
    assert phone_numbers.mint_many(memory, [A])


def test_round_3_item_1_a_real_token_is_found_in_a_chat_a_claim_or_a_held_line(memory):
    ep = "ep_2026-08-20_001"
    markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "origin": "whatsapp", "source": "whatsapp"},
                          "user: Ana [number:abcdefghij]\nassistant: [number:zzzzzzzzzz]")
    assert phone_numbers.bank_token_ids(memory) == {"abcdefghij"}


def _trashed(root, name, stamp="20261104T000000Z"):
    trashed = root / ".trash" / f"{name}-{stamp}"
    trashed.parent.mkdir(parents=True, exist_ok=True)
    phone_numbers.park_for_trash(name, trashed)
    people_directory.forget(name)
    return trashed.with_name(f"{trashed.name}.numbers.json")


def _bank_at(root, name):
    memory = root / "banks" / name
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    return memory


def _chat_episode(memory, t):
    (memory / "episodes" / "ep_2026-08-20_001.md").write_text(f"---\nid: x\norigin: whatsapp\n---\nuser: Ana {t}")


def test_round_3_item_2_a_new_bank_of_a_trashed_name_inherits_nothing(tmp_path, home):
    root = tmp_path / "root"
    old = _bank_at(root, "alpha")
    t = tok(old, A)
    _chat_episode(old, t)
    parked = _trashed(root, "alpha")
    # a brand new bank takes the name
    import shutil

    shutil.rmtree(old)
    fresh = _bank_at(root, "alpha")
    tid = phone_numbers.mint_many(fresh, [B])[B]
    assert parked.exists() and A not in phone_numbers.reveal(fresh, phone_numbers.token_ids(t)).values()
    assert phone_numbers.reveal(fresh, [tid]) == {tid: B}


def test_round_3_item_2_a_similar_name_never_takes_it(tmp_path, home):
    root = tmp_path / "root"
    old = _bank_at(root, "work-old")
    t = tok(old, A)
    _chat_episode(old, t)
    parked = _trashed(root, "work-old")
    other = _bank_at(root, "work")
    _chat_episode(other, t)      # even holding the same letters: the stamp is not its name's
    assert phone_numbers.problem(other) is not None and parked.exists()
    assert not people_directory.path("work", phone_numbers.VAULT_FILE).exists()


def test_round_3_item_2_the_old_bank_restored_still_finds_it(tmp_path, home):
    root = tmp_path / "root"
    old = _bank_at(root, "alpha")
    t = tok(old, A)
    _chat_episode(old, t)
    parked = _trashed(root, "alpha")
    assert phone_numbers.problem(old) is None
    assert not parked.exists()
    assert phone_numbers.reveal(old, phone_numbers.token_ids(t)) == {phone_numbers.token_ids(t)[0]: A}


@pytest.mark.parametrize("switch", [True, False])
def test_round_3_item_3_a_re_post_with_the_vault_gone_rewrites_nothing(bank, on, switch):
    lines = [row("AAA1", T0, f"Ana's number is {A}", me=True), row("AAA2", T0 + 5, "her number is 202 555 0177", me=True)]
    ingest(bank, lines)
    for path in (bank / "episodes").glob("*.md"):
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, {**parsed.frontmatter, "processed": True, "processed_by": "sleep"}, parsed.body)
    bank_index.invalidate()
    before = stored(bank)
    people_directory.path(bank.name, phone_numbers.VAULT_FILE).unlink()
    phone_numbers.set_enabled(switch)
    assert ingest(bank, lines)["updated"] == 0
    assert stored(bank) == before


def test_round_3_item_3_after_a_new_vault_a_re_post_rewrites_nothing(bank, on):
    lines = [row("AAA1", T0, f"Ana's number is {A}", me=True)]
    ingest(bank, lines)
    before = stored(bank)
    _damage(bank)
    phone_numbers.new_vault(bank)
    assert ingest(bank, lines)["updated"] == 0
    assert stored(bank) == before


def test_round_3_item_4_a_healthy_vault_is_never_set_aside(memory, client):
    t = tok(memory, A)
    tid = phone_numbers.token_ids(t)[0]
    out = client.post("/people/numbers/new-vault")
    assert out.status_code == 409 and "fine" in out.json()["detail"]
    assert phone_numbers.reveal(memory, [tid]) == {tid: A}
    with pytest.raises(phone_numbers.VaultHealthy):
        phone_numbers.new_vault(memory)


def test_round_3_item_4_the_person_has_a_door(client):
    from api.services import cli_map

    assert "numbers new-vault" in {r.name for r in cli_map.rows() if r.person}


def test_round_3_item_5_any_other_page_is_never_touched(memory):
    path = memory / "entities" / "acme.md"
    body = (f"Grew by 2025550143 users. Call [chat](https://example.com/{A_DIGITS}) or [calls](tel:+{A_DIGITS}). "
            f"Our number is {A}. Quote [number:abcdefghij].")
    markdown_parser.write(path, {"name": "Acme", "type": "company"}, body)
    assert body in path.read_text()
    assert not people_directory.path(memory.name, phone_numbers.VAULT_FILE).exists()


def test_round_3_item_5_a_persons_page_keeps_its_links_and_other_digits(memory):
    t = tok(memory, B)
    path = memory / "entities" / "ana-diaz.md"
    body = (f"[chat](https://example.com/{A_DIGITS}) and [calls](tel:+{A_DIGITS}) and https://example.com/{A_DIGITS} "
            f"her ticket is 2025550199 and she has 2025550188 points, quoting [number:abcdefghij], her number is {t}.")
    markdown_parser.write(path, {"name": "Ana Diaz", "type": "person"}, body)
    text = path.read_text()
    assert f"(https://example.com/{A_DIGITS})" in text and f"(tel:+{A_DIGITS})" in text and f"https://example.com/{A_DIGITS} " in text
    assert "2025550199" in text and "2025550188" in text and "[number:abcdefghij]" in text
    assert t not in text and "her number is a number" in text


@pytest.mark.parametrize("line", [
    "not sure if her new number is {t}", "I don't have her new number, I only have {t}",
    "got a new phone, her number is {t}", "maybe her new number is {t}", "is her new number {t}?", "her new number might be {t}",
    "no sé si su nuevo número es {t}", "I think she changed her number to {t}",
])
def test_round_3_item_6_a_hedged_line_asks(memory, line):
    page(memory, "ana-diaz", "Ana Diaz")
    held, said = tok(memory, A), tok(memory, B)
    _file(memory, "2026-08-20", f"Ana Diaz's number is {held}", held)
    out = _file(memory, "2026-08-25", "Ana Diaz: " + line.format(t=said), said)
    numbers = _phones(memory)
    assert numbers[held].valid_to is None and numbers[said].context == phone_numbers.ASKED
    assert [n for n in out["nudges"] if n["action"] == "divergence_nudge"]


@pytest.mark.parametrize("label", ["contact", "reachable_at", "sms", "signal"])
def test_round_3_item_8_these_labels_become_tokens(memory, label):
    page(memory, "ana-diaz", "Ana Diaz")
    out = agentic_write.write_claim(memory, "Ana Diaz", label, A, observer="external:claude-code", object_kind="literal")
    assert out["action"] != "error"
    assert A_DIGITS not in (memory / "entities" / "ana-diaz.md").read_text()


def test_round_3_item_8_a_claims_sentence_holds_no_number(memory):
    page(memory, "ana-diaz", "Ana Diaz")
    agentic_write.write_claim(memory, "Ana Diaz", "knows", "Bob Example", observer="external:claude-code",
                              text="her number is 2025550143")
    assert A_DIGITS not in (memory / "entities" / "ana-diaz.md").read_text()


def test_round_3_item_8_the_old_one_was_when_a_number_is_on_the_line(home):
    out, n = phone_numbers.tokenise("her new number is 2025550143, the old one was 2025550177", "b")
    assert n == 2 and not any(c.isdigit() for c in out)
    assert phone_numbers.tokenise("the old one was 2025550178", "b")[1] == 0


def test_round_3_item_8_a_budget_after_a_number_stays_in_the_words(home):
    out, n = phone_numbers.tokenise("her number is 2025550143 and 1500000 is the budget", "b")
    assert n == 1 and "1500000" in out


def test_round_3_item_8_a_page_born_by_write_new_is_checked_too(memory):
    path = memory / "entities" / "new.md"
    markdown_parser.write_new(path, {"name": "New", "type": "person"}, f"Her number is {A}.")
    assert A_DIGITS not in path.read_text() and "202 555 0143" not in path.read_text()


def test_round_3_item_9_the_record_says_what_asked(client):
    client.put("/people/numbers/switch", json={"on": True})
    assert json.loads(phone_numbers._switch_path().read_text())["by"] == "api-token"


def test_round_3_the_count_only_script_prints_counts_only(memory):
    from api.scripts import numbers_rule_dry_run

    ep = "ep_2026-08-20_001"
    markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "origin": "whatsapp", "source": "whatsapp"},
                          "user: Ana 2025550143\nuser: order 2025550177\nassistant: Added Ana at 2025550143")
    counts = numbers_rule_dry_run.run(memory)
    assert counts["would_token"] == 1 and counts["digit_runs_left"] == 1 and counts["other_lines_would_redact"] == 1
    assert all(isinstance(v, int) for v in counts.values())
    assert not people_directory.path(memory.name, phone_numbers.VAULT_FILE).exists()



# ---- a run the vault holds, whatever stands around it (real Sleep on scratch, 2026-11-05: an echo's "to N" had no signal) ----

def joined(bank) -> str:
    return "\n".join(body for body, _fm in stored(bank).values())


def test_round_4_an_echo_of_a_number_the_vault_holds_is_redacted_with_no_signal(bank, on):
    ingest(bank, [row("AAA1", T0, "Carla Example 2025550144", me=True),
                  row("AAA2", T0 + 5, "Updated Carla Example to 202 555 0144.")])
    body = joined(bank)
    assert "2025550144" not in re.sub(r"[ .-]", "", body) and "[redacted]" in body and phone_numbers.has_token(body)


def test_round_4_an_echo_before_the_persons_line_in_one_post_is_redacted_too(bank, on):
    ingest(bank, [row("AAA1", T0, "is it 2025550144 now?"), row("AAA2", T0 + 5, "Carla Example 2025550144", me=True)])
    assert "2025550144" not in joined(bank)


def test_round_4_the_person_repeating_a_held_number_gets_its_one_token(bank, on):
    ingest(bank, [row("AAA1", T0, "Carla Example 2025550144", me=True),
                  row("AAA2", T0 + 5, "ring back 202 555 0144 later", me=True)])
    body = joined(bank)
    tokens = phone_numbers.token_ids(body)
    assert len(tokens) == 2 and len(set(tokens)) == 1 and "ring back" in body


def test_round_4_a_run_the_vault_does_not_hold_stays_in_the_words(bank, on):
    ingest(bank, [row("AAA1", T0, "Carla Example 2025550144", me=True),
                  row("AAA2", T0 + 5, "ticket closed under 2025559999 today")])
    assert "2025559999" in joined(bank)


def test_round_4_an_echo_posted_again_with_the_vault_gone_stays_redacted(bank, on, home):
    rows = [row("AAA1", T0, "Carla Example 2025550144", me=True),
            row("AAA2", T0 + 5, "Updated Carla Example to 2025550144.")]
    ingest(bank, rows)
    before = stored(bank)
    people_directory.path(bank.name, phone_numbers.VAULT_FILE).unlink()
    assert ingest(bank, rows)["updated"] == 0
    assert stored(bank) == before
