"""G245 (ruling 78 (c), owner 2026-11-24): one full-name mention of a LinkedIn connection is enough for that person's page.

Asked "If you mention a LinkedIn connection by full name once and they have no Contacts card, is that enough for a page?",
the owner answered "yes it should be enough." Earlier that day: "a linkedin connection doesnt need a page just for the sake
of having a page, the person is what gets a page." So the mention makes the page and the connection attaches in the same
write; a connection nobody mentioned still makes nothing. The rule is the Contacts rule (`entity_resolver._card_for`) with
every one of its refusals, and the attached link is only PROPOSED: a connection list is far larger than an address book,
so a name alone must never hand the link a photo request (`person_photo.is_own_account`).

One departure from the plan, the coordinator's reading of the owner's example (he "wrote some in Apple Notes"): a full name
in the person's OWN note counts for a connection (`entity_resolver.CONNECTION_NAMED_IN_OWN_NOTES`, one line to turn off);
the Contacts rule is untouched.

Synthetic people, placeholder links; nothing reads a real bank, `~/.cicada` or the network."""
from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import pytest

from _synthetic_bank import _entity
from api.services import (authorship, bank_index, conflict_resolver, contacts_local, demo_guard, entity_resolver as er,
                          fact_sources, linkedin_people, markdown_parser, person_photo, promotion, role_people,
                          same_name_doubts, source_proposals, web_context, web_settle)
from api.services.claims import parse_claims

LI = "https://www.linkedin.com/in"
DAY = "2026-11-01"
TODAY = "2026-11-24"

#: Every episode the cases below name. ``(frontmatter, body)``; the ids are the numbers.
EPISODES = {
    "conv": ({"harness": "claude-code"}, "user: lunch with Finn Sample today\n\nassistant: noted"),
    "reversed": ({"harness": "claude-code"}, "user: lunch with Sample Finn today"),
    "reply": ({"harness": "claude-code"}, "user: who did we meet?\n\nassistant: Finn Sample was there."),
    "relayed": ({"source": "mcp-remote", "evidence_kind": "assistant"},
                "user: who wrote it?\n\nassistant: Finn Sample wrote it."),
    "save": ({"source": "url", "media_entity_id": "media-x", "url": "https://example.com"}, "A page that names Finn Sample."),
    "feed": ({"source": "rss", "origin": "rss"}, "Finn Sample launches a thing."),
    "tabs": ({"source": "tab-group", "source_id": "tab-group:chrome:Default:x"},
             "# Research\n\n- Finn Sample | Profile - https://example.com/in/x"),
    "calendar": ({"source": "calendar", "origin": "calendar-local"}, "Lunch with Finn Sample"),
    "link": ({"harness": "claude-code"}, f"user: have a look at {LI}/finn-sample please"),
    "other": ({"harness": "claude-code"}, "user: lunch with Erin Example today"),
    "twins": ({"harness": "claude-code"}, "user: lunch with Gale Twin today"),
    "doubt": ({"harness": "claude-code"}, "user: lunch with Ivan Doubt today"),
    "owner": ({"harness": "claude-code"}, "user: I am Pat Owner, hello"),
    "both": ({"harness": "claude-code"}, "user: lunch with Jo Both today"),
    "grace": ({"harness": "claude-code"}, "user: I was reading about Grace Example the founder and author"),
    # the person's own notes: Apple Notes (no kind declared) and a Notion export (declared the person's own)
    "apple": ({"source": "apple-notes", "origin": "apple-notes"},
              "# Event\n\n**Folder:** Meetups\n\nMet Hal Sample at the event, follow up next week"),
    "notion": ({"source": "notion-export", "origin": "notion-export", "evidence_kind": "user"},
               "# Event\n\n**Database:** People\n\nHal Sample, met at the event"),
    "note_title": ({"source": "apple-notes", "origin": "apple-notes"}, "# Hal Sample\n\n**Folder:** Notes\n\nfollow up"),
    "note_folder": ({"source": "apple-notes", "origin": "apple-notes"},
                    "# Plans\n\n**Folder:** Hal Sample\n\nnothing to say here"),
    "note_link": ({"source": "apple-notes", "origin": "apple-notes"}, f"# Links\n\n**Folder:** Notes\n\n{LI}/hal-sample"),
    "note_locked": ({"source": "apple-notes", "origin": "apple-notes", "locked_note": True},
                    "# Event\n\n**Folder:** Meetups\n\nMet Hal Sample at the event"),
    "note_stub": ({"source": "apple-notes", "origin": "apple-notes", "title": "Locked note"}, "# Locked note\n"),
    "note_agent": ({"source": "mcp", "origin": "apple-notes"}, "# Event\n\nMet Hal Sample at the event"),
    "note_agent_cli": ({"source": "cli", "origin": "apple-notes", "harness": "claude-code", "session_id": "s1"},
                       "# Event\n\nMet Hal Sample at the event"),
    "note_other": ({"source": "notion-export", "origin": "notion-export", "evidence_kind": "assistant",
                    "notion_by_other": True}, "# Event\n\nHal Sample, met at the event"),
    "note_clip": ({"source": "apple-notes", "origin": "apple-notes", "url": "https://example.com/clip"},
                  "# Clipped\n\nHal Sample wrote this"),
    "other_note": ({"source": "mcp", "origin": "elsewhere"}, "# Event\n\nMet Hal Sample at the event"),
    "unrelated_note": ({"source": "bookmark-sync", "origin": "elsewhere"}, "# Event\n\nMet Hal Sample at the event"),
}
IDS = {key: f"ep_2026-10-01_{n:03d}" for n, key in enumerate(EPISODES, start=1)}


def _settings(bank):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=1)


def _conn(first, last, slug="", company="", position="", day="2026-10-05"):
    return linkedin_people.Connection(first, last, f"{LI}/{slug}" if slug else None, company, position, day)


@pytest.fixture
def stage2(tmp_path, monkeypatch):
    """A bank with kept connections and NO waiting Contacts card (the case the guards at the top of Stage 2 once skipped)."""
    bank = tmp_path / "mentionbank"
    for name in ("entities", "episodes", "inbox"):
        (bank / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)

    async def different(*_a, **_k):
        return "different"

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return ["different" for _ in entries]

    monkeypatch.setattr(er, "_llm_judge_same_entity", different)
    monkeypatch.setattr(er, "_llm_judge_batch", batch)
    for key, (fm, body) in EPISODES.items():
        markdown_parser.write(bank / "episodes" / f"{IDS[key]}.md",
                              {"id": IDS[key], "timestamp": "2026-10-01T12:00:00+00:00", "processed": False, **fm}, body)
    linkedin_people.save_directory(bank.name, [
        _conn("Finn", "Sample", "finn-sample", "Acme Robotics", "Engineer"),
        _conn("Erin", "Example", "erin-example"),
        _conn("Gale", "Twin"), _conn("Gale", "Twin"),                       # two rows, no link: two people
        _conn("Hal", "Sample", "hal-sample", "Beta Labs", "Designer"),
        _conn("Ivan", "Doubt", "ivan-doubt"),
        _conn("Pat", "Owner", "pat-owner"),
        _conn("Jo", "Both", "jo-both"),
        _conn("Grace", "Example", "grace-example", "Gamma Works", "Engineer"),
        _conn("Kay", "Unmentioned", "kay-unmentioned"),
    ], DAY)
    same_name_doubts.add_pairs(bank, [("ivan-held", "Ivan Doubt")], today=TODAY)
    _entity(bank, "pat-owner", type="person", name="Pat Owner", owner=True)
    bank_index.invalidate()
    yield bank
    bank_index.invalidate()


def _mention(name, key="conv", *, etype="person", named=True, **extra):
    ep = IDS[key]
    return [{"episode_id": ep, "relationships": [], "entities": [
        {"name": name, "type": etype, "confidence": 0.6, "description": f"{name} came up.", "source_episode": ep,
         "source_episode_timestamp": "2026-10-01T12:00:00Z", "named_by_person": named, **extra}]}]


def _resolve(bank, extracted, pages=()):
    return asyncio.run(er.resolve(extracted, list(pages), _settings(bank)))


def _creates(out):
    return [c for c in out["changes"] if c.get("action") == "create"]


def _born(bank, out):
    conflict_resolver.apply_changes(out["changes"], bank)
    bank_index.invalidate()


def _fm(bank, eid):
    return markdown_parser.parse(bank / "entities" / f"{eid}.md").frontmatter


def _linkedin(bank, eid):
    return [s for s in _fm(bank, eid).get("sources") or [] if s.get("predicate") == "linkedin"]


def _claims(bank, eid, predicate=None):
    claims = parse_claims(markdown_parser.parse(bank / "entities" / f"{eid}.md").body)
    return [c for c in claims if c.observer == linkedin_people.OBSERVER and (predicate is None or c.predicate == predicate)]


# --- the rule ------------------------------------------------------------------------------------------------------


def test_a_bank_with_connections_and_no_waiting_card_makes_the_page_on_one_full_name_mention(stage2):
    assert contacts_local.waiting_index(stage2).cards == {}, "the case: connections, and no card waiting"
    out = _resolve(stage2, _mention("Finn Sample"))
    (change,) = _creates(out)
    assert (change["id"], change["entity"]["name"]) == ("finn-sample", "Finn Sample")
    assert change[er.LINKEDIN_MENTION_KEY] == {"id": change[er.LINKEDIN_MENTION_KEY]["id"], "name": "Finn Sample"}
    assert not change.get("contacts_card")
    _born(stage2, out)                                   # Stage 5 only: no tail, no commit
    fm = _fm(stage2, "finn-sample")
    assert fm["name"] == "Finn Sample" and er.LINKEDIN_MENTION_KEY not in fm, "the key is transient: never on a page"
    (link,) = _linkedin(stage2, "finn-sample")
    assert (link["ref"], link["added_by"], link["kind"]) == (f"{LI}/finn-sample", "cicada", "url")
    assert [c.object for c in _claims(stage2, "finn-sample", "connected-on")] == ["2026-10-05"]
    assert [c.object for c in _claims(stage2, "finn-sample", "works-at")] == ["Acme Robotics"]
    assert linkedin_people.rematch(stage2).paths == [], "attached in the same write: nothing left for the night's tail"


def test_the_mention_in_another_order_is_renamed_to_the_connections_name_and_kept_as_an_alias(stage2):
    out = _resolve(stage2, _mention("Sample Finn", "reversed"))
    (change,) = _creates(out)
    assert change["entity"]["name"] == "Finn Sample" and "Sample Finn" in change["entity"]["aliases"]
    assert out["name_to_id"]["sample finn"] == "finn-sample"


def test_two_spellings_of_one_connection_in_one_batch_are_one_page(stage2):
    out = _resolve(stage2, _mention("Finn Sample") + _mention("Sample Finn", "reversed"))
    (change,) = _creates(out)
    assert change["id"] == "finn-sample"
    assert out["name_to_id"]["sample finn"] == "finn-sample"


def test_the_link_is_only_proposed_and_no_photo_or_other_service_request_follows(stage2, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("a service request left the Mac")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    out = _resolve(stage2, _mention("Finn Sample"))
    _born(stage2, out)
    (link,) = _linkedin(stage2, "finn-sample")
    assert link["match"] == linkedin_people.MATCH_ALIAS and link[fact_sources.PROPOSED] is True
    assert fact_sources.is_proposed(link) and not fact_sources.trusted(link)
    assert not linkedin_people.from_connections(link), "never 'from their LinkedIn connections' as a confident match"
    assert person_photo.is_own_account(link) is False, "a proposal is never a face"
    fm = _fm(stage2, "finn-sample")
    assert [c for c in person_photo.candidates(fm, proxy=True, public=None) if c.provider == person_photo.LINKEDIN] == []
    assert [s["ref"] for s in source_proposals.pending(fm)] == [f"{LI}/finn-sample"], "it waits in 'Confirm N links'"
    # the same night's tail keeps it a proposal: it never lifts the guess to a confident match behind the person's back
    linkedin_people.rematch(stage2)
    (link,) = _linkedin(stage2, "finn-sample")
    assert link["match"] == linkedin_people.MATCH_ALIAS and fact_sources.is_proposed(link)


def test_taking_the_proposal_makes_it_the_persons_own_account(stage2):
    _born(stage2, _resolve(stage2, _mention("Finn Sample")))
    assert source_proposals.answer(stage2, "finn-sample", [f"{LI}/finn-sample"], True) == 1
    (link,) = _linkedin(stage2, "finn-sample")
    assert fact_sources.trusted(link) and not fact_sources.is_proposed(link) and person_photo.is_own_account(link)


def test_a_proposed_link_is_no_acquaintance_for_the_public_figure_test(stage2):
    """Ruling 44's local test reads the record for an acquaintance (`web_context.known_personally`); the proposed link and the
    dated LinkedIn claims on a mention-born page are not one (a connection list is far larger than an address book)."""
    out = _resolve(stage2, _mention("Grace Example", "grace",
                                    description="Grace Example is a founder and author of a book."))
    _born(stage2, out)
    assert _linkedin(stage2, "grace-example"), "the page has its proposed link"
    page = web_context.load_page(stage2, "grace-example")
    facts = web_settle.bank_facts(stage2)
    assert web_context.known_personally(stage2, page, facts) is None
    verdict = web_context.local_verdict(stage2, page, facts)
    assert verdict.reason not in ("personal_relation", "owner_in_prose", "personal_channel"), verdict


def test_a_card_and_a_connection_of_one_full_name_are_one_lead_and_one_page_with_both(stage2):
    contacts_local.save_waiting(stage2.name, [{"id": "C1", "given_name": "Jo", "family_name": "Both",
                                               "has_organization": True}])
    bank_index.invalidate()
    out = _resolve(stage2, _mention("Jo Both", "both"))
    (change,) = _creates(out)
    assert change["contacts_card"]["id"] == "C1" and er.LINKEDIN_MENTION_KEY not in change, "the card's rule decides"
    _born(stage2, out)
    refs = {(s["predicate"], s["ref"]) for s in _fm(stage2, "jo-both")["sources"]}
    assert ("works-at", "addressbook://C1") in refs and ("linkedin", f"{LI}/jo-both") in refs
    (link,) = _linkedin(stage2, "jo-both")
    assert link["match"] == linkedin_people.MATCH_NAME and not fact_sources.is_proposed(link), "as before: the card is the lead"


def test_a_card_that_carries_the_name_keeps_the_connection_from_a_second_lead(stage2):
    """The card's own rule refuses a name said only in a note, so the connection route must not step in: one lead."""
    contacts_local.save_waiting(stage2.name, [{"id": "C2", "given_name": "Hal", "family_name": "Sample"}])
    bank_index.invalidate()
    assert not _creates(_resolve(stage2, _mention("Hal Sample", "apple")))


def test_a_connection_nobody_mentioned_makes_nothing(stage2):
    out = _resolve(stage2, _mention("Erin Example", "other"))
    assert [c["id"] for c in _creates(out)] == ["erin-example"], "only the mentioned one"
    _born(stage2, out)
    assert sorted(p.stem for p in (stage2 / "entities").glob("*.md")) == ["erin-example", "pat-owner"]
    assert not _resolve(stage2, [])["changes"]
    assert linkedin_people.rematch(stage2).paths == [], "the tail enriches only pages that exist, and this one is done"
    assert not (stage2 / "entities" / "kay-unmentioned.md").exists()


def test_a_demo_bank_never_reads_the_connections(stage2):
    demo_guard.write_manifest(stage2)
    assert _resolve(stage2, _mention("Finn Sample"))["changes"] == []


def test_a_page_born_by_the_usual_rules_keeps_its_confident_match(stage2):
    """Only a birth the connection rule made is demoted: two conversations, as ever, record the match as it is."""
    out = _resolve(stage2, _mention("Finn Sample") + _mention("Finn Sample", "other"))
    (change,) = _creates(out)
    assert er.LINKEDIN_MENTION_KEY not in change
    _born(stage2, out)
    (link,) = _linkedin(stage2, "finn-sample")
    assert link["match"] == linkedin_people.MATCH_NAME and not fact_sources.is_proposed(link)


# --- every refusal of the Contacts rule holds here too -------------------------------------------------------------------


def _held_page(name, *aliases, eid="someone-else"):
    return {"id": eid, "frontmatter": {"name": name, "type": "person", "aliases": list(aliases)}, "body": "## Summary\nA page."}


@pytest.mark.parametrize("why, extracted, pages", [
    ("a one-part name", _mention("Finn"), ()),
    ("two connections of one name, no link on either", _mention("Gale Twin", "twins"), ()),
    ("a same-name doubt holds the name", _mention("Ivan Doubt", "doubt"), ()),
    ("not a person", _mention("Finn Sample", etype="project"), ()),
    ("a relation-only person", _mention("Finn Sample", **{role_people.UNNAMED_KEY: True}), ()),
    ("Stage 1 measured nobody named it", _mention("Finn Sample", named=False), ()),
    ("a name no turn of the person's holds", _mention("Finn Sample", "other"), ()),
    ("an agent's reply names it", _mention("Finn Sample", "reply"), ()),
    ("a relayed connector turn", _mention("Finn Sample", "relayed"), ()),
    ("a save's text", _mention("Finn Sample", "save"), ()),
    ("a feed item", _mention("Finn Sample", "feed"), ()),
    ("a tab group's tab title", _mention("Finn Sample", "tabs"), ()),
    ("a calendar entry", _mention("Finn Sample", "calendar"), ()),
    ("a profile link pasted in a turn is the name spelled, never said", _mention("Finn Sample", "link"), ()),
    ("the owner's own name (the owner's page is not even among the pages Stage 2 was handed)",
     _mention("Pat Owner", "owner"), ()),
    ("a page already holds the name", _mention("Finn Sample"), (_held_page("Finn Sample"),)),
    ("a page holds the name as an alias", _mention("Finn Sample"), (_held_page("Finn S", "Sample Finn"),)),
    ("the same name in the other order", _mention("Sample Finn", "reversed"), (_held_page("Finn Sample"),)),
])
def test_a_connection_never_makes_a_page(stage2, why, extracted, pages):
    out = _resolve(stage2, extracted, pages)
    assert not _creates(out), why
    assert not [c for c in out["changes"] if c.get(er.LINKEDIN_MENTION_KEY)], why


def test_the_owner_exclusion_is_the_directorys_own_not_the_pages_handed_to_stage_2(stage2):
    by = {a.name: a for a in linkedin_people.arrivals(stage2)}
    assert by["Pat Owner"].owner and not by["Pat Owner"].waiting
    assert "pat owner" not in linkedin_people.waiting_connections(stage2)
    assert not _creates(_resolve(stage2, _mention("Pat Owner", "owner")))


def test_a_name_a_page_holds_in_the_bank_is_refused_even_with_no_waiting_card(stage2):
    """The guards at the top of Stage 2: with a card they read the person pages' names; with only connections they once
    read an empty set, so 'no page holds the name' passed vacuously."""
    assert contacts_local.waiting_index(stage2).cards == {}
    pages = [_held_page("Finn Sample", eid="finn-sample")]
    assert not _creates(_resolve(stage2, _mention("Finn Sample"), pages))


# --- the person's own notes (the coordinator's reading, one switch) --------------------------------------------------------


@pytest.mark.parametrize("key", ["apple", "notion", "note_title"])
def test_a_full_name_in_the_persons_own_note_makes_the_page(stage2, key):
    ep = IDS[key]
    fm = markdown_parser.parse(stage2 / "episodes" / f"{ep}.md").frontmatter
    entity = {"name": "Hal Sample", "type": "person"}
    # Stage 1's own measure: a note is the person's own writing, so a name in it is "named by the person"
    units = promotion.exchanges(markdown_parser.parse(stage2 / "episodes" / f"{ep}.md").body,
                                override=authorship.of(fm))
    assert promotion.measure(entity, units)[1] is True
    out = _resolve(stage2, _mention("Hal Sample", key))
    (change,) = _creates(out)
    assert change["id"] == "hal-sample" and change[er.LINKEDIN_MENTION_KEY]["name"] == "Hal Sample"
    _born(stage2, out)
    (link,) = _linkedin(stage2, "hal-sample")
    assert link[fact_sources.PROPOSED] is True and link["match"] == linkedin_people.MATCH_ALIAS


@pytest.mark.parametrize("key, why", [
    ("note_folder", "the folder is a filing label, never the person's words"),
    ("note_link", "a profile link is the name spelled, never said"),
    ("note_locked", "a locked note is never read"),
    ("note_stub", "a locked note's stub holds no words"),
    ("note_agent", "a note an agent saved is the agent's"),
    ("note_agent_cli", "a note an agent's shell saved is the agent's"),
    ("note_other", "a shared Notion row is someone else's words"),
    ("note_clip", "a clipped page is a save"),
    ("other_note", "not one of the person's own notes"),
    ("unrelated_note", "not one of the person's own notes"),
])
def test_a_note_that_is_not_the_persons_own_words_never_makes_a_page(stage2, key, why):
    assert not _creates(_resolve(stage2, _mention("Hal Sample", key))), why


def test_the_note_rule_is_one_switch_and_turning_it_off_leaves_conversations_alone(stage2, monkeypatch):
    assert er.CONNECTION_NAMED_IN_OWN_NOTES is True
    monkeypatch.setattr(er, "CONNECTION_NAMED_IN_OWN_NOTES", False)
    assert not _creates(_resolve(stage2, _mention("Hal Sample", "apple")))
    assert not _creates(_resolve(stage2, _mention("Hal Sample", "notion")))
    (change,) = _creates(_resolve(stage2, _mention("Finn Sample")))          # a conversation still counts
    assert change["id"] == "finn-sample"


def test_a_note_never_promotes_a_contacts_card_as_before(stage2):
    """The Contacts rule is untouched: its own notes do not count for a card (owner ruling 2026-10-20)."""
    contacts_local.save_waiting(stage2.name, [{"id": "C3", "given_name": "Hal", "family_name": "Sample"}])
    linkedin_people.forget_directory(stage2.name)
    bank_index.invalidate()
    assert not _creates(_resolve(stage2, _mention("Hal Sample", "apple")))


# --- the readers a later track builds on ---------------------------------------------------------------------------------


def test_arrivals_say_where_each_connection_stands_and_nothing_else_is_asked(stage2):
    _entity(stage2, "erin-example", type="person", name="Erin Example")
    bank_index.invalidate()
    by = {}
    for a in linkedin_people.arrivals(stage2):
        by.setdefault(a.name, []).append(a)
    assert by["Erin Example"][0].pages == ("erin-example",) and by["Erin Example"][0].page == "erin-example"
    assert not by["Erin Example"][0].waiting
    finn = by["Finn Sample"][0]
    assert (finn.pages, finn.page, finn.waiting, finn.doubted, finn.owner) == ((), None, True, False, False)
    assert (finn.day, finn.precision, finn.dup) == ("2026-10-05", "day", 0)
    assert sorted(a.dup for a in by["Gale Twin"]) == [0, 1], "two linkless rows of one name are told apart"
    assert by["Ivan Doubt"][0].doubted and not by["Ivan Doubt"][0].waiting
    assert by["Pat Owner"][0].owner
    assert all(a.id == a.connection.id for a in linkedin_people.arrivals(stage2))


def test_waiting_connections_offer_a_name_only_when_every_row_of_it_waits(stage2):
    waiting = linkedin_people.waiting_connections(stage2)
    assert [c.name for c in waiting["finn sample"]] == ["Finn Sample"] == [c.name for c in waiting["sample finn"]]
    assert len(waiting["gale twin"]) == 2, "two rows: the caller refuses"
    assert not {"ivan doubt", "pat owner", "doubt ivan"} & set(waiting), "a doubt and the owner are never offered"
    # a row of the name that already lands on a page spoils the name for the other row
    linkedin_people.save_directory(stage2.name, [_conn("Finn", "Sample", "finn-sample"), _conn("Finn", "Sample", "finn-2")], DAY)
    _entity(stage2, "finn-page", type="person", name="Finn Page",
            sources=[{"ref": f"{LI}/finn-sample", "kind": "url", "predicate": "linkedin", "added_by": "user"}])
    bank_index.invalidate()
    assert "finn sample" not in linkedin_people.waiting_connections(stage2)


def test_match_labels_names_exactly_one_in_full(stage2):
    waiting = linkedin_people.waiting_connections(stage2)
    assert linkedin_people.match_labels(waiting, ["Finn Sample"]).name == "Finn Sample"
    assert linkedin_people.match_labels(waiting, ["Sample Finn", "F"]).name == "Finn Sample"
    assert linkedin_people.match_labels(waiting, ["Finn"]) is None
    assert linkedin_people.match_labels(waiting, ["Gale Twin"]) is None
    assert linkedin_people.match_labels(waiting, ["Finn Sample", "Hal Sample"]) is None, "two labels, two people"
    assert linkedin_people.match_labels({}, ["Finn Sample"]) is None


def test_the_attacher_can_only_demote_a_match(stage2):
    attacher = linkedin_people.Attacher(stage2)
    with pytest.raises(ValueError):
        attacher.attach({"name": "Finn Sample", "type": "person"}, "## Summary\nFinn.\n", "finn-sample", how="name")
    with pytest.raises(ValueError):
        attacher.attach({"name": "Finn Sample", "type": "person"}, "## Summary\nFinn.\n", "finn-sample", how="link")
    fm, _ = attacher.attach({"name": "Finn Sample", "type": "person"}, "## Summary\nFinn.\n", "finn-sample",
                            how=linkedin_people.MATCH_ALIAS)
    (source,) = fm["sources"]
    assert source["match"] == "alias" and source["proposed"] is True
