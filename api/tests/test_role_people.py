"""Placeholder people — a person known only by their relation to the owner (brief 2026-10-14, `role_people`).

Measured on the owner's bank (real values redacted): 6 of 251 person pages were titled "<owner>'s partner",
"<owner>'s friend", "<owner>'s father", "Replacement roommate (unnamed)"…; one person was split across
"<owner>'s friend" (active) and "<owner>'s partner" (archived). Covered here, on synthetic banks only:

* the relation is read from a name by one closed vocabulary, and a name is never read as a relation;
* Stage 2 titles a role-only person by the relation and keeps every later mention on that one page;
* a full Sleep cycle writes "Partner" (never "<owner>'s partner") and asks its name once;
* the repair merges a placeholder only on evidence on the record, retitles and asks for the rest, and is idempotent;
* answering names the page (claims, references and edges follow) or merges it into the person of that name;
  "I'd rather not say" keeps a role title and is never asked again;
* no merge without evidence: a plural relation, two named holders, a past relation, a first name alone.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.models.schemas import InboxResolveRequest
from api.scripts import repair_placeholder_people
from api.services import entity_resolver, inbox_service, markdown_parser, owner_identity, role_people, sleep_cycle
from api.services.claims import Claim, parse_claims, write_claims
from api.tests.test_sleep_cycle_hold import _bank, _entity, _episode, _patch, _settings

OWNER_ID, OWNER_NAME = "alpha-owner", "Alpha Owner"
OWNER_FM = {"name": OWNER_NAME, "type": "person", "owner": True}
EP_A, TS_A = "ep_2026-09-20_001", "2026-09-20T10:00:00+00:00"
EP_B, TS_B = "ep_2026-09-21_001", "2026-09-21T10:00:00+00:00"


# --- the vocabulary ------------------------------------------------------------------------


@pytest.mark.parametrize("name,key,singular", [
    ("Alpha Owner's partner", "partner", True),
    ("Alpha’s partner", "partner", True),
    ("Alpha Owner's friend", "friend", False),
    ("Alpha Owner's father", "father", True),
    ("Alpha Owner's former roommate", "former roommate", False),
    ("Alpha Owner's teacher", "teacher", False),
    ("Replacement roommate (unnamed)", "replacement roommate", False),
    ("Unnamed partner", "partner", True),
    ("the user's girlfriend", "girlfriend", True),
    ("my mom", "mom", True),
    ("pareja de Alpha Owner", "pareja", True),
    ("Partner", "partner", True),
    ("Partner (another)", "partner", True),
    ("Friend from university", "friend from university", False),
    ("Alpha Owner's ex-girlfriend", "ex-girlfriend", False),
])
def test_a_relation_to_the_owner_is_read_from_the_name(name, key, singular):
    role = role_people.parse(name, role_people.owner_names(OWNER_FM))
    assert role is not None and (role.key, role.singular) == (key, singular)
    assert "Alpha" not in role.title


@pytest.mark.parametrize("name", [
    "Alice Example", "friend Alice", "Doctor Who", "Alpha Owner's daughter's teacher", "Beta Other's partner",
    "Alpha Owner", "Partners Example", "",
])
def test_a_name_is_never_read_as_a_relation(name):
    assert role_people.parse(name, role_people.owner_names(OWNER_FM)) is None


# --- Stage 2 ---------------------------------------------------------------------------------


def _person(name: str, ep: str, ts: str, **extra) -> dict:
    entity = _entity(name, "person", ep, ts)
    entity.update(extra)
    return entity


def test_stage_2_titles_a_role_only_person_by_the_relation_and_keeps_one_page_per_relation():
    extracted = [
        {"episode_id": EP_A, "entities": [_person("Alpha Owner's partner", EP_A, TS_A,
                                                  summary="Lives with [[Alpha Owner's partner]].")],
         "relationships": [{"source": "Alpha Owner's partner", "target": "Gamma", "label": "works at"}]},
        {"episode_id": EP_B, "entities": [_person("the user's partner", EP_B, TS_B),
                                          _person("Alpha's friend", EP_B, TS_B),
                                          {"name": "Partner", "type": "company"}],
         "relationships": [{"source": "Alpha Owner", "target": "my partner", "label": "lives with"}]},
    ]
    existing = [{"id": OWNER_ID, "frontmatter": OWNER_FM}]
    role_people.canonicalize(extracted, existing, OWNER_FM)
    a, b = extracted
    assert a["entities"][0]["name"] == "Partner" and b["entities"][0]["name"] == "Partner"
    assert a["entities"][0][role_people.UNNAMED_KEY] is True and a["entities"][0][role_people.ROLES_KEY] == ["partner"]
    assert a["entities"][0]["summary"] == "Lives with [[Partner]]."
    assert a["relationships"][0]["source"] == "Partner" and b["relationships"][0]["target"] == "Partner"
    assert b["entities"][1]["name"] == "Friend"
    assert b["entities"][2]["name"] == "Partner" and b["entities"][2]["type"] == "company"   # not a person: untouched


def test_stage_2_attaches_a_singular_relation_to_the_named_person_the_record_holds_but_never_a_plural_one():
    existing = [
        {"id": OWNER_ID, "frontmatter": OWNER_FM},
        {"id": "dana-example", "frontmatter": {"name": "Dana Example", "type": "person", "owner_roles": ["partner"]}},
        {"id": "bob-example", "frontmatter": {"name": "Bob Example", "type": "person", "owner_roles": ["friend"]}},
    ]
    extracted = [{"episode_id": EP_A, "entities": [_person("Alpha Owner's partner", EP_A, TS_A),
                                                   _person("Alpha Owner's friend", EP_A, TS_A)],
                  "relationships": []}]
    role_people.canonicalize(extracted, existing, OWNER_FM)
    partner, friend = extracted[0]["entities"]
    assert partner["name"] == "Dana Example" and role_people.UNNAMED_KEY not in partner
    assert friend["name"] == "Friend" and friend[role_people.UNNAMED_KEY] is True


def test_stage_2_attaches_to_the_existing_placeholder_page_of_that_relation():
    existing = [{"id": OWNER_ID, "frontmatter": OWNER_FM},
                {"id": "alpha-owner's-partner", "frontmatter": {"name": "Alpha Owner's partner", "type": "person"}}]
    extracted = [{"episode_id": EP_A, "entities": [_person("my partner", EP_A, TS_A)], "relationships": []}]
    role_people.canonicalize(extracted, existing, OWNER_FM)
    assert extracted[0]["entities"][0]["name"] == "Alpha Owner's partner"   # the page the repair will retitle


# --- a full Sleep cycle ----------------------------------------------------------------------


def _owner_page(memory: Path) -> None:
    owner_identity.save_owner({"name": OWNER_NAME, "entity_id": OWNER_ID})
    assert owner_identity.ensure_default_owner(memory) == OWNER_ID


def _substantive_person(name: str, ep: str, ts: str) -> dict:
    entity = _person(name, ep, ts)
    entity.update(confidence=0.99, description="Discussed at length. " * 12, mention_exchanges=4,
                  named_by_person=True)
    return entity


def _name_questions(memory: Path) -> list[dict]:
    out = []
    for path in sorted((memory / "inbox").glob("inbox-*.md")):
        fm = markdown_parser.parse(path).frontmatter
        if fm.get("asks") == "name":
            out.append({**fm, "_id": path.stem})
    return out


def test_a_sleep_cycle_writes_the_relation_title_and_asks_the_name_once(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _owner_page(memory)
    _episode(memory, EP_A, TS_A, "user: My partner and I moved.\nassistant: Congratulations.")
    _episode(memory, EP_B, TS_B, "user: My partner starts a new job.\nassistant: Good luck to them.")
    first = [{"episode_id": EP_A, "episode_timestamp": TS_A, "origin": "claude-export",
              "entities": [_substantive_person("Alpha Owner's partner", EP_A, TS_A)], "relationships": []}]
    second = [{"episode_id": EP_B, "episode_timestamp": TS_B, "origin": "claude-export",
               "entities": [_substantive_person("the user's partner", EP_B, TS_B)], "relationships": []}]
    _patch(monkeypatch, [first, second])

    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="roles_1"))
    pages = {p.stem for p in (memory / "entities").glob("*.md")}
    assert pages == {OWNER_ID, "partner"}
    page = markdown_parser.parse(memory / "entities" / "partner.md").frontmatter
    assert page["name"] == "Partner" and page["unnamed"] is True and page["owner_roles"] == ["partner"]
    (question,) = _name_questions(memory)
    assert question["question"] == "What's the name of your partner?" and question["entity_id"] == "partner"
    assert question["options"] == [{"key": "rather_not_say", "label": "I'd rather not say"}]
    assert not [q for q in _all_items(memory) if q.get("title", "").startswith("Who or what is")]

    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="roles_2"))
    assert {p.stem for p in (memory / "entities").glob("*.md")} == {OWNER_ID, "partner"}
    assert markdown_parser.parse(memory / "entities" / "partner.md").frontmatter["source_episodes"] == [EP_A, EP_B]
    assert len(_name_questions(memory)) == 1   # one question per page


def _all_items(memory: Path) -> list[dict]:
    return [markdown_parser.parse(p).frontmatter for p in sorted((memory / "inbox").glob("inbox-*.md"))]


# --- the repair ------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _claim(cid: str, subject: str, predicate: str, obj: str, **extra) -> Claim:
    return Claim(id=cid, text=f"{subject} {predicate} {obj}", subject=subject, predicate=predicate, object=obj,
                 valid_from="2026-01-01", **extra)


def _page(memory: Path, eid: str, fm: dict, prose: str, claims: list[Claim] | None = None) -> None:
    body = write_claims(prose, claims) if claims else prose
    markdown_parser.write(memory / "entities" / f"{eid}.md", {"type": "person", "status": "active",
                                                               "confidence": 0.8, **fm}, body)


def _git_bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    return memory


def _split_bank(tmp_path: Path) -> Path:
    """The measured shape, synthetic: one person split across "<owner>'s friend" (live, with claims) and
    "<owner>'s partner" (archived), a "<owner>'s father" placeholder the record ties to one named person, a page
    and an edge pointing at a placeholder, and a named friend the record ties to the owner (no merge: plural)."""
    memory = _git_bank(tmp_path)
    _page(memory, OWNER_ID, {**OWNER_FM, "confidence": 1.0}, "## Summary\nThe owner.",
          [_claim("c-owner-1", OWNER_ID, "lives-with", "alpha-owner's-friend")])
    _page(memory, "alpha-owner's-friend", {"name": "Alpha Owner's friend", "confidence": 0.91,
                                            "source_episodes": [EP_A, EP_B]},
          "## Summary\nStudies design.",
          [_claim("c-friend-1", "alpha-owner's-friend", "studies", "Design", object_kind="literal"),
           _claim("c-friend-2", "alpha-owner's-friend", "works-at", "gamma-studio")])
    _page(memory, "alpha-owner's-partner", {"name": "Alpha Owner's partner", "status": "archived",
                                             "confidence": 0.0, "source_episodes": [EP_A]},
          "## Summary\nMoved in last spring.",
          [_claim("c-partner-1", "alpha-owner's-partner", "moved-to", "Lisbon", object_kind="literal")])
    _page(memory, "alpha-owner's-father", {"name": "Alpha Owner's father", "source_episodes": [EP_B]},
          "## Summary\nA retired engineer.",
          [_claim("c-father-1", "alpha-owner's-father", "retired-from", "Engineering", object_kind="literal")])
    _page(memory, "carl-example", {"name": "Carl Example", "source_episodes": [EP_A]}, "## Summary\nAn engineer.",
          [_claim("c-carl-1", "carl-example", "father-of", OWNER_ID)])
    _page(memory, "bob-example", {"name": "Bob Example"}, "## Summary\nA classmate.",
          [_claim("c-bob-1", "bob-example", "friend-of", OWNER_ID)])
    markdown_parser.write(memory / "entities" / "gamma-studio.md",
                          {"name": "Gamma Studio", "type": "company", "status": "active",
                           "related": ["Alpha Owner's partner"]},
                          "## Summary\nWhere [[Alpha Owner's partner]] once worked.")
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "alpha-owner's-friend", "target": "gamma-studio", "label": "works at"}]}))
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


def _claim_ids(memory: Path) -> set[str]:
    out = set()
    for path in (memory / "entities").glob("*.md"):
        out |= {c.id for c in parse_claims(markdown_parser.parse(path).body)}
    return out


def test_the_dry_run_counts_only_and_writes_nothing(tmp_path, capsys):
    memory = _split_bank(tmp_path)
    assert repair_placeholder_people.main(["--bank", str(memory)]) == 0
    counts = json.loads(capsys.readouterr().out)
    assert counts["placeholder_pages"] == 3
    assert (counts["would_merge"], counts["would_retitle"], counts["would_ask"]) == (1, 2, 2)
    assert "Alpha" not in json.dumps(counts) and "partner" not in json.dumps(counts)
    assert _git(memory, "status", "--porcelain") == ""


def test_the_repair_merges_on_evidence_retitles_and_asks_the_rest_in_one_commit(tmp_path):
    memory = _split_bank(tmp_path)
    before = _claim_ids(memory)
    plan = role_people.apply(memory, sleep_running=lambda: False)
    assert (len(plan.merges), len(plan.retitles), plan.asked, plan.committed) == (1, 2, 2, True)

    pages = {p.stem for p in (memory / "entities").glob("*.md")}
    assert not [p for p in pages if "alpha-owner's" in p]
    assert {"partner", "friend", "carl-example", "bob-example"} <= pages
    # The father merged into the one person the record names as the owner's father, every claim with it.
    carl = markdown_parser.parse(memory / "entities" / "carl-example.md")
    assert carl.frontmatter["owner_roles"] == ["father"]
    assert not any("Alpha" in a for a in carl.frontmatter.get("aliases") or [])
    assert "c-father-1" in {c.id for c in parse_claims(carl.body)}
    # Nothing said about anyone was lost; the claims now name the new ids.
    assert _claim_ids(memory) == before
    friend = markdown_parser.parse(memory / "entities" / "friend.md")
    assert friend.frontmatter["name"] == "Friend" and friend.frontmatter["unnamed"] is True
    assert {c.subject for c in parse_claims(friend.body)} == {"friend"}
    owner = parse_claims(markdown_parser.parse(memory / "entities" / f"{OWNER_ID}.md").body)
    assert [c.object for c in owner] == ["friend"]
    gamma = markdown_parser.parse(memory / "entities" / "gamma-studio.md")
    assert gamma.frontmatter["related"] == ["Partner"] and "[[Partner]]" in gamma.body
    edges = yaml.safe_load((memory / "graph_edges.yaml").read_text())["edges"]
    assert edges[0]["source"] == "friend"
    # One question per unnamed page, the archived partner included; the friend (plural) never merged into Bob.
    questions = {q["entity_id"]: q["question"] for q in _name_questions(memory)}
    assert questions == {"partner": "What's the name of your partner?", "friend": "What's the name of your friend?"}
    served = {i.entity_id for i in inbox_service.load_inbox(memory) if i.asks == "name"}
    assert served == {"partner", "friend"}
    # One commit, by cicada, and a clean tree.
    assert _git(memory, "status", "--porcelain") == ""
    log = _git(memory, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in log and "maintenance/placeholder-people" in log
    # A second run finds nothing to do.
    again = role_people.apply(memory, sleep_running=lambda: False)
    assert (len(again.merges), len(again.retitles), again.asked, again.written) == (0, 0, 0, 0)


def test_the_repair_refuses_while_sleep_runs_and_writes_nothing(tmp_path):
    memory = _split_bank(tmp_path)
    with pytest.raises(role_people.SleepRunning):
        role_people.apply(memory, sleep_running=lambda: True)
    assert _git(memory, "status", "--porcelain") == ""


@pytest.mark.parametrize("claims,why", [
    ([_claim("x1", "carl-example", "father-of", OWNER_ID), _claim("x2", "dan-example", "father-of", OWNER_ID)],
     "two named people hold it"),
    ([_claim("x1", "carl-example", "former-father-of", OWNER_ID)], "a past relation"),
    ([_claim("x1", "carl-example", "father-of", OWNER_ID, valid_to="2026-02-01")], "a closed claim"),
    ([_claim("x1", OWNER_ID, "father-of", "carl-example")], "the other direction"),
    ([], "nothing on the record"),
])
def test_no_merge_without_evidence(tmp_path, claims, why):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.")
    _page(memory, "alpha-owner's-father", {"name": "Alpha Owner's father"}, "A retired engineer.")
    _page(memory, "carl-example", {"name": "Carl Example"}, "An engineer.",
          [c for c in claims if c.subject == "carl-example"])
    _page(memory, "dan-example", {"name": "Dan Example"}, "An engineer.",
          [c for c in claims if c.subject == "dan-example"])
    owner_claims = [c for c in claims if c.subject == OWNER_ID]
    if owner_claims:
        _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.", owner_claims)
    plan = role_people.survey(memory)
    assert plan.merges == [], why
    assert [t for _p, t, _k in plan.retitles] == ["Father"], why


# --- the answer ------------------------------------------------------------------------------


def _resolve(memory: Path, item: str, **request) -> dict:
    return asyncio.run(inbox_service.resolve(item, InboxResolveRequest(**request), SimpleNamespace(memory_path=memory)))


def _question_for(memory: Path, page_id: str) -> str:
    return next(q["_id"] for q in _name_questions(memory) if q["entity_id"] == page_id)


def test_answering_names_the_page_then_a_second_answer_merges_the_split_person(tmp_path):
    memory = _split_bank(tmp_path)
    role_people.apply(memory, sleep_running=lambda: False)
    before = _claim_ids(memory)

    assert _resolve(memory, _question_for(memory, "partner"), action="resolve", answer="Dana Example")["status"] == \
        "resolved"
    dana = markdown_parser.parse(memory / "entities" / "dana-example.md")
    assert dana.frontmatter["name"] == "Dana Example" and dana.frontmatter["owner_roles"] == ["partner"]
    assert "unnamed" not in dana.frontmatter and not (memory / "entities" / "partner.md").exists()
    assert {c.subject for c in parse_claims(dana.body)} == {"dana-example"}
    gamma = markdown_parser.parse(memory / "entities" / "gamma-studio.md")
    assert gamma.frontmatter["related"] == ["Dana Example"] and "[[Dana Example]]" in gamma.body

    # The same person was also kept as "friend": the person's answer is the evidence, and the page folds in.
    _resolve(memory, _question_for(memory, "friend"), action="resolve", answer="dana example")
    assert not (memory / "entities" / "friend.md").exists()
    dana = markdown_parser.parse(memory / "entities" / "dana-example.md")
    assert set(dana.frontmatter["owner_roles"]) == {"partner", "friend"}
    assert set(dana.frontmatter["source_episodes"]) == {EP_A, EP_B}
    assert _claim_ids(memory) == before
    owner = parse_claims(markdown_parser.parse(memory / "entities" / f"{OWNER_ID}.md").body)
    assert [c.object for c in owner] == ["dana-example"]
    assert _name_questions(memory) == []
    assert _git(memory, "status", "--porcelain") == ""
    answers = _git(memory, "log", "--format=%B", "--grep=inbox/clarification/resolved")
    assert answers.count("Cicada-Author: user") == 2 and "removed (merged)" in answers

    # A later "<owner>'s partner" mention attaches to Dana: the record now says she holds it.
    existing = [{"id": p.stem, "frontmatter": markdown_parser.parse(p).frontmatter}
                for p in (memory / "entities").glob("*.md")]
    extracted = [{"episode_id": EP_B, "entities": [_person("Alpha Owner's partner", EP_B, TS_B)],
                  "relationships": []}]
    role_people.canonicalize(extracted, existing, OWNER_FM)
    assert extracted[0]["entities"][0]["name"] == "Dana Example"


def test_a_first_name_alone_never_merges_it_files_a_duplicate_question_that_does(tmp_path):
    memory = _split_bank(tmp_path)
    role_people.apply(memory, sleep_running=lambda: False)
    _resolve(memory, _question_for(memory, "partner"), action="resolve", answer="Carl")
    assert (memory / "entities" / "carl.md").exists() and (memory / "entities" / "carl-example.md").exists()
    (suggestion,) = [(p.stem, markdown_parser.parse(p).frontmatter) for p in (memory / "inbox").glob("inbox-*.md")
                     if markdown_parser.parse(p).frontmatter.get("kind") == "merge_suggestion"]
    item, fm = suggestion
    assert (fm["entity_id"], fm["merge_target_hint"]) == ("carl", "carl-example")
    _resolve(memory, item, action="merge", merge_target="carl-example")
    assert not (memory / "entities" / "carl.md").exists()
    carl = markdown_parser.parse(memory / "entities" / "carl-example.md")
    assert "c-partner-1" in {c.id for c in parse_claims(carl.body)}


def test_rather_not_say_keeps_a_role_title_without_the_owners_name_and_is_never_asked_again(tmp_path):
    memory = _git_bank(tmp_path)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.")
    _page(memory, "alpha-owner's-teacher", {"name": "Alpha Owner's teacher", "unnamed": True,
                                             "owner_roles": ["teacher"]}, "## Summary\nTeaches piano.")
    path = role_people.ensure_question(memory, "alpha-owner's-teacher", owner_fm=OWNER_FM)
    assert path is not None
    _resolve(memory, path.stem, action="resolve", option_key="rather_not_say")
    page = markdown_parser.parse(memory / "entities" / "teacher.md").frontmatter
    assert page["name"] == "Teacher" and page["name_declined"] is True and page["unnamed"] is True
    assert role_people.ensure_question(memory, "teacher", owner_fm=OWNER_FM) is None
    assert role_people.survey(memory).asked == 0


@pytest.mark.parametrize("answer", ["my girlfriend", "Partner", "me", "   "])
def test_an_answer_that_is_not_a_name_is_refused_and_writes_nothing(tmp_path, answer):
    from fastapi import HTTPException

    memory = _git_bank(tmp_path)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.")
    _page(memory, "partner", {"name": "Partner", "unnamed": True, "owner_roles": ["partner"]}, "Lives nearby.")
    path = role_people.ensure_question(memory, "partner", owner_fm=OWNER_FM)
    with pytest.raises(HTTPException) as err:
        _resolve(memory, path.stem, action="resolve", answer=answer)
    assert err.value.status_code == 400
    assert path.exists() and (memory / "entities" / "partner.md").exists()


def test_a_page_someone_is_editing_is_never_swept_into_the_repairs_commit(tmp_path):
    memory = _split_bank(tmp_path)
    gamma = memory / "entities" / "gamma-studio.md"
    gamma.write_text(gamma.read_text() + "\nA hand edit in progress.\n")   # it links to "<owner>'s partner"
    plan = role_people.apply(memory, sleep_running=lambda: False)
    assert plan.dirty == 1
    assert (memory / "entities" / "alpha-owner's-partner.md").exists()   # its retitle waits for a clean tree
    assert "A hand edit in progress." in gamma.read_text()
    assert _git(memory, "status", "--porcelain").strip() == "M entities/gamma-studio.md"
