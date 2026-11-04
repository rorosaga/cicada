"""What a "Possible duplicate" question between two people must rest on (owner 2026-11-04, `pair_evidence`).

The owner, on "Is <handle> the same as <owner>?" (Cicada's guess 0.90, its evidence a chat with someone else that named
neither): "why tf would <handle> be me?" Measured on a copy of the owner's bank (real values redacted): a link to a
POST by that handle, written on the owner's page, was read as the owner's own account; the question was raised
whenever any conversation matched the owner's page, with that conversation as its evidence; and its guess was the
matched mention's extraction confidence. Synthetic banks only (owner-example, bex42, bob-example, ann-sample, tool-a);
no engine, no network."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import (bank_index, clarification_manager, entity_resolver as er, inbox_tend, markdown_parser,
                          owner_identity, pair_evidence, person_leads, predicates, web_settle)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _page(memory: Path, eid: str, name: str, *, body: str = "", **fm) -> dict:
    meta = {"name": name, "type": "person", "status": "active", "confidence": 0.8, "created": "2026-10-01",
            "last_referenced": "2026-10-20", "source_episodes": [], "related": [], "version": 1}
    meta.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", meta, body or f"## Summary\n{name}, synthetic.\n")
    bank_index.invalidate(memory)
    return {"id": eid, "frontmatter": meta, "body": body or f"## Summary\n{name}, synthetic.\n"}


def _episode(memory: Path, eid: str, body: str, **fm) -> None:
    meta = {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": True, "title": "chat",
            "source": "claude-code"}
    meta.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", meta, body)
    bank_index.invalidate(memory)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _page(m, "owner-example", "Owner Example", owner=True,
          body="## Summary\nOwner Example, synthetic.\n\n- Shared [a post](https://x.com/bex42/status/123) by bex42.\n")
    _page(m, "bex42", "bex42", body="## Summary\nbex42 is a developer handle whose posts the owner reads.\n")
    _git(m, "add", "-A")
    _git(m, "commit", "-qm", "seed")
    return m


def _ask(memory: Path, name: str, target: str, *, episode: str, confidence: float = 0.9,
         classification: str = "person — could refer to the same person") -> str | None:
    return clarification_manager.ClarificationManager(memory).create(
        entity_name=name, source_episode=episode, uncertainty_type=f"Possible duplicate of {target}",
        suggested_classification=classification, suggested_confidence=confidence, source_context="Context.")


# --------------------------------------------------------------------------- the owner's page


def test_the_owners_page_is_never_paired_with_a_handle_on_a_conversation_that_names_neither(memory):
    _episode(memory, "ep_2026-10-26_001", "user: hola, nos vemos mañana\nassistant: ok")
    assert _ask(memory, "bex42", "Owner Example", episode="ep_2026-10-26_001") is None
    assert list((memory / "inbox").glob("inbox-*.md")) == []


def test_a_conversation_naming_both_is_still_not_the_person_saying_who_they_are(memory):
    _episode(memory, "ep_2026-10-26_002", "user: Owner Example here, I read a post by bex42 today\nassistant: nice")
    assert _ask(memory, "bex42", "Owner Example", episode="ep_2026-10-26_002") is None


def test_the_persons_own_words_naming_themselves_by_the_handle_let_it_be_asked(memory):
    _episode(memory, "ep_2026-10-26_003", "user: btw I'm bex42 on there.\nassistant: noted, Owner Example")
    assert _ask(memory, "bex42", "Owner Example", episode="ep_2026-10-26_003") is not None


def test_an_agents_words_or_a_longer_word_are_not_self_reference(memory):
    _episode(memory, "ep_2026-10-26_004",
             "user: I'm bex42-ing my workflow, Owner Example style\nassistant: you are bex42, Owner Example")
    assert pair_evidence.self_named(memory, ["bex42"]) is None
    assert _ask(memory, "bex42", "Owner Example", episode="ep_2026-10-26_004") is None


def test_the_handle_the_person_gave_cicada_for_themselves_is_self_reference(memory):
    owner_identity.save_owner({"name": "Owner Example", "handle": "bex42"})
    _episode(memory, "ep_2026-10-26_005", "user: Owner Example and bex42\nassistant: ok")
    assert pair_evidence.self_named(memory, ["bex42"]) == pair_evidence.SelfNamed(declared=True)
    assert _ask(memory, "bex42", "Owner Example", episode="ep_2026-10-26_005") is not None


@pytest.mark.parametrize("line, expected", [
    ("I'm bex42.", True), ("I am bex42, a developer", True), ("my x handle is @bex42", True),
    ("soy bex42 y programo", True), ("call me bex42", True), ("I'm bex42's fan", False),
    ("I'm bex42 mode today", False), ("bex42 is great", False), ("I read bex42", False),
])
def test_what_counts_as_naming_oneself(line, expected):
    assert pair_evidence._names_self(line, ["bex42"]) is expected


# --------------------------------------------------------------------------- the evidence names both sides


def test_two_people_no_conversation_names_together_are_not_asked(memory):
    _page(memory, "bob-example", "Bob Example")
    _episode(memory, "ep_2026-10-27_001", "user: I met Bobby yesterday\nassistant: ok")
    assert _ask(memory, "Bobby", "Bob Example", episode="ep_2026-10-27_001", confidence=0.7) is None


def test_the_question_rests_on_the_conversation_that_names_both_with_a_bounded_guess(memory):
    _page(memory, "bob-example", "Bob Example", source_episodes=["ep_2026-10-27_003"])
    _episode(memory, "ep_2026-10-27_002", "user: Bobby called\nassistant: ok")
    _episode(memory, "ep_2026-10-27_003", "user: Bob Example, whom everyone calls Bobby, called\nassistant: ok")
    item = _ask(memory, "Bobby", "Bob Example", episode="ep_2026-10-27_002", confidence=0.95)
    fm = markdown_parser.parse(memory / "inbox" / f"{item}.md").frontmatter
    assert fm["source_episode"] == "ep_2026-10-27_003"          # the excerpt is about the pair
    assert fm["source_episode_timestamp"].startswith("2026-10-27")
    assert fm["suggested_confidence"] == pair_evidence.MAX_GUESS  # below ruling 29's act threshold
    assert fm["priority"] == pair_evidence.MAX_GUESS


def test_a_question_the_record_raises_with_no_conversation_is_exempt_from_the_evidence_rule(memory):
    _page(memory, "bob-example", "Bob Example")
    _page(memory, "partner-example", "Partner")
    item = _ask(memory, "Partner", "Bob Example", episode="", confidence=0.6)
    assert markdown_parser.parse(memory / "inbox" / f"{item}.md").frontmatter["suggested_confidence"] == 0.6


def test_a_thing_pair_is_still_asked_but_its_guess_says_nothing_names_both(memory):
    _page(memory, "tool-a", "Tool A", type="tool")
    _episode(memory, "ep_2026-10-28_001", "user: I set up Tool Alpha\nassistant: ok")
    item = _ask(memory, "Tool Alpha", "Tool A", episode="ep_2026-10-28_001", confidence=0.9,
                classification="tool — could refer to the same entity as Tool A")
    assert markdown_parser.parse(memory / "inbox" / f"{item}.md").frontmatter["suggested_confidence"] == \
        pair_evidence.UNPAIRED_GUESS


@pytest.mark.parametrize("base, paired, expected", [(0.95, True, 0.8), (0.6, True, 0.6), (0.9, False, 0.4),
                                                    (None, True, 0.5), ("x", True, 0.5)])
def test_the_guess_is_bounded(base, paired, expected):
    assert pair_evidence.guess(base, paired) == expected


# --------------------------------------------------------------------------- the lead itself


def test_a_post_link_in_a_pages_body_is_not_its_account_but_its_profile_link_is():
    shared = {"id": "owner-example", "frontmatter": {"name": "Owner Example", "type": "person"},
              "body": "- [a post](https://x.com/bex42/status/123)"}
    profile = {"id": "ann-sample", "frontmatter": {"name": "Ann Sample", "type": "person"},
               "body": "- [GitHub](https://github.com/asample)\n- [LinkedIn](https://www.linkedin.com/in/asample)"}
    tracked = {"id": "cy-sample", "frontmatter": {"name": "Cy Sample", "type": "person",
                                                  "sources": [{"ref": "https://x.com/csample/status/9"}]}, "body": ""}
    assert person_leads.account_links(shared) == []
    assert person_leads.account_links(profile) == [("github", "asample"), ("linkedin", "asample")]
    assert person_leads.account_links(tracked) == [("x", "csample")]
    pages = [shared, profile, tracked, *({"id": h, "frontmatter": {"name": h, "type": "person"}, "body": ""}
                                          for h in ("bex42", "asample", "csample"))]
    leads = {(lead.page, lead.holder) for lead in person_leads.PersonIndex(pages).all_leads()}
    assert leads == {("asample", "ann-sample"), ("csample", "cy-sample")}


def test_a_conversation_that_matches_the_owners_page_raises_nothing_about_a_handle(memory, monkeypatch):
    """The live failure end to end: the owner's page links a post BY the handle (a body link, as Sleep writes them) and
    a chat with someone else matches the owner's page. Before: "Is bex42 the same as Owner Example?" at 0.9."""
    _episode(memory, "ep_2026-10-26_009", "user: hola Owner Example aquí\nassistant: ok")
    pages = [{"id": p.stem, "frontmatter": markdown_parser.parse(p).frontmatter, "body": markdown_parser.parse(p).body}
             for p in sorted((memory / "entities").glob("*.md"))]
    # Even an older index that still read the body post link as the owner's account asks nothing now.
    pages[1]["body"] += "\n- [X](https://x.com/bex42)\n"
    extracted = [{"episode_id": "ep_2026-10-26_009", "relationships": [], "entities": [
        {"name": "Owner Example", "type": "person", "confidence": 0.9, "summary": "the owner", "aliases": [],
         "source_episode": "ep_2026-10-26_009", "source_episode_timestamp": "2026-10-26T09:00:00Z"}]}]
    settings = SimpleNamespace(memory_path=memory, litellm_model="synthetic-model", litellm_disambiguation_model="",
                               sleep_promotion_threshold=2, sleep_resolve_concurrency=1)

    async def judge(*_a, **_k):
        return "different"

    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)
    monkeypatch.setattr(er, "_llm_judge_same_entity", judge)
    asyncio.run(er.resolve(extracted, pages, settings))
    assert [markdown_parser.parse(p).frontmatter.get("title") for p in (memory / "inbox").glob("inbox-*.md")] == []


# --------------------------------------------------------------------------- Sleep tends the ones already open


def _item(memory: Path, item_id: str, **fm) -> None:
    base = {"kind": "merge_suggestion", "status": "pending", "priority": 0.9, "created_date": "2026-10-30",
            "suggested_classification": "person — could refer to the same person", "suggested_confidence": 0.9}
    base.update(fm)
    markdown_parser.write(memory / "inbox" / f"{item_id}.md", base, "Context.")
    bank_index.invalidate(memory)


def _decide(memory: Path, item_id: str):
    path = memory / "inbox" / f"{item_id}.md"
    return inbox_tend.policy(memory, path, markdown_parser.parse(path).frontmatter)


def test_sleep_retires_an_open_owner_pair_and_an_unpaired_one_and_undo_brings_them_back(memory):
    _page(memory, "bob-example", "Bob Example")
    _page(memory, "bobby", "Bobby")
    _page(memory, "ann-sample", "Ann Sample")
    _page(memory, "annie", "Annie", source_episodes=["ep_2026-10-27_005"])
    _episode(memory, "ep_2026-10-26_001", "user: hola\nassistant: ok")
    _episode(memory, "ep_2026-10-27_004", "user: Bobby called\nassistant: ok")
    _episode(memory, "ep_2026-10-27_005", "user: Ann Sample, Annie to friends\nassistant: ok")
    _item(memory, "inbox-001", entity_id="bex42", entity_name="bex42", merge_target_hint="owner-example",
          source_episode="ep_2026-10-26_001", title="Is bex42 the same as Owner Example?")
    _item(memory, "inbox-002", entity_id="bobby", entity_name="Bobby", merge_target_hint="bob-example",
          source_episode="ep_2026-10-27_004")
    _item(memory, "inbox-003", entity_id="annie", entity_name="Annie", merge_target_hint="ann-sample",
          source_episode="ep_2026-10-27_005")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "items")
    d1, _ = _decide(memory, "inbox-001")
    d2, _ = _decide(memory, "inbox-002")
    assert (d1.rule, d1.request) == ("owner_unsaid", None)
    assert (d2.rule, d2.request) == ("no_pair_evidence", None)
    assert _decide(memory, "inbox-003") == (None, "person")      # evidence names both: the person's to answer
    d1.fingerprint = (memory / "inbox" / "inbox-001.md").read_bytes()
    assert asyncio.run(inbox_tend.apply(memory, SimpleNamespace(memory_path=memory), d1))
    assert not (memory / "inbox" / "inbox-001.md").exists()
    assert {p.stem for p in (memory / "entities").glob("*.md")} >= {"bex42", "owner-example"}   # nothing merged
    rows = web_settle.list_settled(memory)
    assert [(r["group"], r["rule"]) for r in rows] == [("sleep", "owner_unsaid")]
    assert rows[0]["reason"] == inbox_tend.RULES["owner_unsaid"]
    restored, paths, lines, _rec = inbox_tend.undo(memory, "inbox-001")
    web_settle.commit_sync(memory, web_settle.commit_message("Sleep's settle undone", lines, authors=["user"]), paths)
    assert restored == "inbox-001"
    assert _decide(memory, "inbox-001") == (None, "undone")     # the person's now: Sleep never retires it again
