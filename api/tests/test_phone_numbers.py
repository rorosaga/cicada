"""G81, proposed ruling 55: a number the person gives lands on the right page as a token; its digits stay outside the bank.

Every number is synthetic, in the 555-01xx range. Covers: one number written many ways is one token, what counts as a
number, the switch (off, nothing moves), whose words are kept, no re-read of old chats, what Stage 1's output becomes,
the change table, what asks, the answer, held names, the duplicate-people signal, Contacts, and every door."""
from __future__ import annotations

import json
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
def on(monkeypatch):
    monkeypatch.setenv("CICADA_PHONE_NUMBERS", "on")


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
    "her number is 202 555 0143", "phone: 2025550143", "su celular es 202 555 0143", "Bob 2025550143",
    "Bob Example: 202 555 0143", "call Ana at 202-555-0143",
])
def test_these_are_numbers(home, line):
    out, n = phone_numbers.tokenise(line, "b")
    assert n == 1 and "555" not in out and phone_numbers.has_token(out)


@pytest.mark.parametrize("line", [
    "order number 123456789", "invoice 1234567890", "room 101 102 103", "2026-10-28 10:30", "built in 2024 2025 2026",
    "wrote code in 2019", "it cost $1 299 000 000", "sku 123-456-789", "see v1.2.3", "ping 192.168.1.10",
    "the years 1999-2003-2010", "flight 123456789", "a 1730000000 timestamp", "@15550100",
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
    assert A in message.text


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
    monkeypatch.setenv("CICADA_PHONE_NUMBERS", "on")
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
    monkeypatch.setenv("CICADA_PHONE_NUMBERS", "on")
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
    monkeypatch.setenv("CICADA_PHONE_NUMBERS", "on")
    ingest(bank, [row("AAA1", T0, f"Ana's number is {A}", me=True)])
    before = stored(bank)
    monkeypatch.setenv("CICADA_PHONE_NUMBERS", "off")
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


@pytest.mark.parametrize(("line", "kind"), [
    ("Ana's new number is X", phone_numbers.CHANGED), ("she changed her number to X", phone_numbers.CHANGED),
    ("Ana now uses X", phone_numbers.CHANGED), ("el nuevo número de Ana es X", phone_numbers.CHANGED),
    ("Ana's work number is X", phone_numbers.ADDITIONAL), ("she also has X", phone_numbers.ADDITIONAL),
    ("su otro móvil es X", phone_numbers.ADDITIONAL), ("her old number was X", phone_numbers.PAST),
    ("Ana is X", phone_numbers.UNKNOWN), ("Ana's number is X", phone_numbers.UNKNOWN),
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
    assert out.status_code == 200 and out.json() == {"numbers": {t: A}}
    monkeypatch.setattr("api.routers.local_sources.request_device", lambda _r: SimpleNamespace(id="d", kind="full"))
    assert client.post("/people/numbers/reveal", json={"tokens": [t]}).status_code == 403
    assert client.get("/people/numbers/match-key").status_code == 403


def test_the_match_key_is_nothing_while_off(client, monkeypatch):
    monkeypatch.setenv("CICADA_PHONE_NUMBERS", "off")
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
    messages_source.update_settings(memory, conversation={"id": conversation_id(db.chat_guid(agent)), "name": "Instinct",
                                                          "ticked": True, "history": True})

    def sync():
        guid = db.chat_guid(agent)
        body = payload(guid, read_rows(db.path, agent))
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
        assert phone_numbers.has_token(lines[0]) and "[redacted]" in lines[1] and phone_numbers.has_token(lines[2])
        assert A_DIGITS not in body and "202 555 0143" not in body and B_DIGITS not in body
        assert sync()["updated"] == 0 and stored(bank) == before
    finally:
        db.close()


def test_messages_turning_it_on_moves_no_stored_byte(bank, tmp_path, monkeypatch):
    db, sync = _messages_chat(tmp_path, bank)
    try:
        sync()
        before = stored(bank)
        (body, _fm), = before.values()
        assert body.startswith("user: Add Ana Diaz, her number is [redacted]") and B_DIGITS in body
        monkeypatch.setenv("CICADA_PHONE_NUMBERS", "on")
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
    assert phone_numbers.has_token(message.text) and agent.text.endswith(A)
    assert "[redacted]" in episode_scrub.scrub_for(agent.text, messages_source.SCRUB_WRITER)[0]


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
