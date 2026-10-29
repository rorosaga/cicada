"""2026-10-29 — the live paths the vetted bank repairs pointed at, each closed as a class (owner: "apply fixes that make
them generalizable so it won't happen again").

(a) a belief that held and ended is never reopened by an older mention read later, however it was closed; (b) a
record's filing label (a folder, a list) is never the person's words and never a conversation for the 2+ rule; (c) no
automatic writer adds a pronoun, a reference or another page's own name as a page's alias; (d) once a thing holds its
application on its own page, the owner's extraction about it goes there from any conversation; (e) two near names a
ratio joins (a letter prefix, an acronym, a model number) are never one inbox question.

Every bank, name and episode here is synthetic: `bob-example`, `acme-example`, `alpha-hackathon`, `Owner Example`.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from api.services import (alias_policy, application_page, claim_pipeline, conflict_resolver, entity_extractor,
                          evidence, markdown_parser, past_roles_repair, predicates, promotion, role_people)
from api.services.claims import Claim, parse_claims, write_claims
from api.services.clarification_manager import _same_mention
from api.services.entity_merge import merge_entities

PERSON = "bob-example"


def _settings(memory: Path):
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    for eid, name, etype in ((PERSON, "Bob Example", "person"), ("acme-example", "Acme Example", "company"),
                             ("uni-example", "Uni Example", "company")):
        markdown_parser.write(memory / "entities" / f"{eid}.md", {"name": name, "type": etype, "status": "active"},
                              f"## Summary\n{name}.")
    return memory


def _sleep(memory: Path, day: str, n: int, rels: list[tuple[str, str]]) -> dict:
    ep = f"ep_{day}_{n:03d}"
    extracted = [{"episode_id": ep, "episode_timestamp": f"{day}T10:00:00", "origin": "claude-code", "entities": [],
                  "relationships": [{"source": "Bob Example", "target": target, "label": label, "source_episode": ep,
                                     "source_episode_timestamp": f"{day}T10:00:00"} for label, target in rels]}]
    return claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=day)


def _claims(memory: Path, page: str = PERSON) -> list[Claim]:
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{page}.md").body, strict=True)


def _close(memory: Path, predicate: str, obj: str, on: str) -> None:
    """Close the open belief the way an expiry or the person's edit does: ``valid_to`` set, no ending words."""
    path = memory / "entities" / f"{PERSON}.md"
    parsed = markdown_parser.parse(path)
    claims = parse_claims(parsed.body, strict=True)
    for c in claims:
        if c.predicate == predicate and c.object == obj and c.valid_to is None:
            c.valid_to = on
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))


# --- (a) an ended belief is never reopened ---------------------------------------------------------------------------


def test_an_older_mention_read_after_a_close_without_ending_words_stays_history(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-01-10", 1, [("works at", "Acme Example")])
    _close(memory, "works-at", "acme-example", "2026-06-30")       # a stated end, an expiry: no "left" said
    _sleep(memory, "2026-03-01", 2, [("works at", "Acme Example")])   # an older conversation, read late
    works = [c for c in _claims(memory) if c.predicate == "works-at"]
    assert not [c for c in works if c.valid_to is None], "what ended stays ended"
    assert all(c.valid_to == "2026-06-30" for c in works)


def test_a_start_read_after_the_belief_ended_is_kept_closed(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2025-09-01", 1, [("studies at", "Uni Example")])
    _close(memory, "studies-at", "uni-example", "2026-06-30")
    _sleep(memory, "2026-01-15", 2, [("enrolled at", "Uni Example")])
    assert not [c for c in _claims(memory) if c.predicate == "studies-at" and c.valid_to is None]


def test_a_mention_said_after_the_end_is_current_again_and_a_withdrawn_claim_ends_nothing(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-01-10", 1, [("works at", "Acme Example")])
    _close(memory, "works-at", "acme-example", "2026-03-01")
    _sleep(memory, "2026-09-01", 2, [("works at", "Acme Example")])   # went back: the newer word stands
    assert {c.object for c in _claims(memory) if c.predicate == "works-at" and c.valid_to is None} == {"acme-example"}


def test_the_past_roles_repair_never_reopens_an_ended_belief(tmp_path):
    memory = _bank(tmp_path)
    vocab = past_roles_repair._vocabulary(memory)
    ended = Claim(id="clm_a", text="Bob Example studies at Uni Example", subject=PERSON, predicate="studies-at",
                  object="uni-example", valid_from="2025-09-01", valid_to="2026-06-30", recorded_at="2026-06-30")
    start = Claim(id="clm_b", text="Bob Example enrolled at Uni Example", subject=PERSON, predicate="enrolled-at",
                  object="uni-example", valid_from="2025-10-01", recorded_at="2026-10-01")
    types = {PERSON: "person", "uni-example": "company"}
    verdict = past_roles_repair.classify(start, [ended, start], vocab, lambda e: types.get(e, ""))
    assert verdict[:2] == (None, "ended_since")
    later = Claim(id="clm_c", text="Bob Example enrolled at Uni Example", subject=PERSON, predicate="enrolled-at",
                  object="uni-example", valid_from="2026-09-01", recorded_at="2026-09-01")
    assert past_roles_repair.classify(later, [ended, later], vocab, lambda e: types.get(e, ""))[0] == "start"


# --- (b) a filing label is never the person's words ------------------------------------------------------------------

NOTE = "# Groceries\n\n**Folder:** Crypto Example\n**Modified:** 2026-10-01\n\nBuy milk and eggs.\n"
SAVE = "# A page\n\n**Source:** article\n**URL:** https://example.com/a\n**Folder:** Bookmarks Bar/Crypto Example\n" \
       "**Saved:** 2026-10-01\n\n## Description\nA page about something else.\n"


def test_a_label_span_is_page_words_whatever_the_episode_says():
    at = NOTE.index("Crypto Example")
    assert evidence.kind_for("ep_2026-10-01_001", NOTE, at, "user") == "page"
    assert evidence.kind_for("ep_2026-10-01_001", NOTE, NOTE.index("Buy milk"), "user") == "user"
    assert evidence.kind_for("ep_2026-10-01_001", SAVE, SAVE.index("Crypto Example"), evidence.SAVE_KIND) == "page"
    # Only the header Cicada's writer put there: the same words the person typed in the body are theirs.
    typed = NOTE + "**Folder:** mine\n"
    assert evidence.kind_for("ep_2026-10-01_001", typed, typed.rindex("mine"), "user") == "user"


def test_a_label_is_no_exchange_and_a_name_only_a_label_carries_is_no_mention():
    units = promotion.exchanges(NOTE, override="user")
    assert all("Crypto" not in whole for _p, whole in units)
    entity = {"name": "Crypto Example"}
    assert promotion.measure(entity, units) == (0, False)
    assert promotion.label_only(entity, NOTE) and promotion.label_only(entity, SAVE)
    assert not promotion.label_only({"name": "Groceries"}, NOTE), "the title is not a label"
    said = NOTE.replace("Buy milk", "Bought Crypto Example and milk")
    assert not promotion.label_only(entity, said), "named in the body too: an ordinary mention"


# --- (c) no automatic writer adds a pronoun, a reference or another page's name -------------------------------------


def test_admits_refuses_pronouns_and_references_and_a_crossed_name_is_found_by_id(tmp_path):
    for bad in ("she", "her", "ella", "the girlfriend", "", None):
        assert not alias_policy.admits(bad), bad
    assert alias_policy.admits("Ella") and alias_policy.admits("Bobby")
    memory = _bank(tmp_path)
    entities = memory / "entities"
    assert alias_policy.names_another_page("Acme Example", PERSON, entities)
    assert not alias_policy.names_another_page("Bob Example", PERSON, entities), "its own name is no crossing"
    assert not alias_policy.names_another_page("Bobby", PERSON, entities)


def test_sleep_never_adds_another_pages_name_as_an_alias(tmp_path):
    memory = _bank(tmp_path)
    change = {"id": PERSON, "action": "update",
              "entity": {"name": "Bob Example", "type": "person", "aliases": ["Acme Example", "Bobby", "she"]}}
    conflict_resolver.apply_changes([change], memory)
    aliases = markdown_parser.parse(memory / "entities" / f"{PERSON}.md").frontmatter.get("aliases") or []
    assert aliases == ["Bobby"]


def test_a_merge_never_carries_a_pronoun_or_a_reference_onto_the_winner(tmp_path):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "friend.md",
                          {"name": "friend", "type": "person", "status": "active",
                           "aliases": ["she", "the girlfriend", "Dana Example"]}, "## Summary\nA friend.")
    merge_entities(memory, loser_id="friend", winner_id=PERSON)
    aliases = markdown_parser.parse(memory / "entities" / f"{PERSON}.md").frontmatter.get("aliases") or []
    assert "she" not in aliases and "the girlfriend" not in aliases
    assert "Dana Example" in aliases and "friend" in aliases


def test_a_nickname_writer_refuses_a_pronoun():
    fm = {"aliases": ["Bobby"]}
    role_people._add_alias(fm, "her")
    role_people._add_alias(fm, "Bo")
    assert fm["aliases"] == ["Bobby", "Bo"]


# --- (d) an application on record takes the owner's lines about it from any conversation ----------------------------


def test_owner_lines_about_an_application_on_record_move_without_a_new_act(tmp_path):
    memory = _bank(tmp_path)
    status = Claim(id="clm_s", text="Alpha Hackathon application status: sent", subject="alpha-hackathon",
                   predicate=application_page.STATUS_PREDICATE, object="sent", object_kind="literal",
                   valid_from="2026-10-20", recorded_at="2026-10-20")
    markdown_parser.write(memory / "entities" / "alpha-hackathon.md",
                          {"name": "Alpha Hackathon", "type": "concept", "status": "active"},
                          write_claims("## Summary\nA hackathon.", [status]))
    owner = {"name": "Owner Example", "type": "person",
             "key_facts": ["Owner Example's application to [[Alpha Hackathon]] lists his role as developer.",
                           "Owner Example lives in Example City."],
             "history_entries": [{"date": "2026-10-21", "event": "Filled in the Alpha Hackathon registration form."},
                                 {"date": "2026-10-22", "event": "Booked flights to the Alpha Hackathon."}]}
    event = {"name": "Alpha Hackathon", "type": "concept"}
    other = {"name": "Beta Meetup", "type": "concept"}
    text = "user: remind me about flights for the alpha hackathon\nassistant: sure."
    episode = {"id": "ep_2026-10-21_001", "source": "imessage"}
    entity_extractor._application_pages([owner, event, other], episode, "ep_2026-10-21_001", text,
                                        owner="Owner Example", day="2026-10-21",
                                        on_record=application_page.standing(memory))
    assert owner["key_facts"] == ["Owner Example lives in Example City."]
    assert [h["event"] for h in owner["history_entries"]] == ["Booked flights to the Alpha Hackathon."], \
        "only lines about the application move; the owner's trip stays theirs"
    assert event["key_facts"] == ["Owner Example's application to [[Alpha Hackathon]] lists his role as developer."]
    assert [h["event"] for h in event["history_entries"]] == ["Filled in the Alpha Hackathon registration form."]
    assert application_page.KEY not in event, "no new act: no birth, no status written"


def _company_with_status(memory: Path, status: str) -> None:
    claim = Claim(id=f"clm_{status}", text=f"Acme Example application status: {status}", subject="acme-example",
                  predicate=application_page.STATUS_PREDICATE, object=status, object_kind="literal",
                  valid_from="2025-03-01", recorded_at="2025-03-01")
    markdown_parser.write(memory / "entities" / "acme-example.md",
                          {"name": "Acme Example", "type": "company", "status": "active"},
                          write_claims("## Summary\nA company.", [claim]))


LIFE = ["Joined Acme Example as an engineer in 2027.", "Started a full-time job at Acme Example.",
        "Lives next to the Acme Example office."]


def test_the_owners_own_life_never_leaves_for_an_application_page(tmp_path):
    """Review of #548: a company the owner applied to in 2025 (rejected), then a 2027 conversation "I started at
    <company> today": the job start and where they live stay on the owner's page, whatever the status."""
    for status in ("rejected", "sent"):
        memory = _bank(tmp_path / status)
        _company_with_status(memory, status)
        owner = {"name": "Owner Example", "type": "person",
                 "key_facts": [*LIFE, "Owner Example's application to Acme Example was submitted in March 2025."],
                 "summary": "Owner Example started at Acme Example today.",
                 "history_entries": [{"date": "2027-01-10", "event": "Started at Acme Example."}]}
        acme = {"name": "Acme Example", "type": "company"}
        entity_extractor._application_pages([owner, acme], {"id": "ep_2027-01-10_001"}, "ep_2027-01-10_001",
                                            "user: I started at Acme Example today", owner="Owner Example",
                                            day="2027-01-10", on_record=application_page.standing(memory))
        assert owner["key_facts"][:3] == LIFE, status
        assert owner["summary"] == "Owner Example started at Acme Example today.", status
        assert [h["event"] for h in owner["history_entries"]] == ["Started at Acme Example."], status
        moved = acme.get("key_facts") or []
        if status == "rejected":
            assert not moved and len(owner["key_facts"]) == 4, "a final status takes nothing more"
        else:
            assert moved == ["Owner Example's application to Acme Example was submitted in March 2025."]


def test_a_thing_with_no_application_on_record_keeps_the_owners_lines(tmp_path):
    memory = _bank(tmp_path)
    owner = {"name": "Owner Example", "type": "person", "key_facts": ["Owner Example asked about the Acme Example."]}
    acme = {"name": "Acme Example", "type": "company"}
    entity_extractor._application_pages([owner, acme], {"id": "ep_x"}, "ep_x", "user: hi", owner="Owner Example",
                                        day=None, on_record=application_page.standing(memory))
    assert owner["key_facts"] == ["Owner Example asked about the Acme Example."]


# --- (e) near names are two questions --------------------------------------------------------------------------------


def test_near_names_a_ratio_joins_are_never_one_question():
    for a, b in (("pstack", "stack"), ("dpr", "gdpr"), ("unitree go2", "unitree g1"), ("xrpl", "xrp"),
                 ("ask", "dask"), ("gpt-4o", "gpt-4")):
        assert not _same_mention(a, b), (a, b)
    assert _same_mention("open ai", "openai"), "spacing is one name"
    assert _same_mention("alice", "alice example"), "a name inside the other is still the token rule's"
