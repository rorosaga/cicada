"""2026-10-27 — past roles are history, a start is the belief it starts, and a bank written before is repaired.

The case these reproduce in small: one conversation said a person "worked at" one company, "worked on" a project
there, and had joined another company the day before (Stage 1 now writes that as "works at" with its STARTS day). The page kept both past roles as current, dated the day it was
said, and its "Works at" named the old employer. Every bank here is synthetic (`bob-example`, `acme-example`,
`globex-example`, made-up episodes).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.services import (claim_pipeline, entity_extractor, git_service, markdown_parser, past_roles_repair,
                          predicates, project_timeline)
from api.services.claims import Claim, Evidence, parse_claims, write_claims

PERSON = "bob-example"
PAGES = {
    PERSON: ("Bob Example", "person"),
    "acme-example": ("Acme Example", "company"),
    "globex-example": ("Globex Example", "company"),
    "initech-example": ("Initech Example", "company"),
    "uni-example": ("Uni Example", "company"),
    "lisbon-example": ("Lisbon Example", "location"),
    "porto-example": ("Porto Example", "location"),
    "rover-project": ("Rover Project", "project"),
    "dana-example": ("Dana Example", "person"),
    # The closed types file a club, a team and a university as `company`, and an office as `location` (review).
    "chess-club": ("Chess Club", "company"),
    "robotics-team": ("Robotics Team", "company"),
    "office-example": ("Office Example", "location"),
}


def _settings(memory: Path):
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4)


def _bank(tmp_path: Path, *, stale: bool = False) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    if stale:
        # A bank seeded before 2026-10-27: `install_predicate_map` never refreshes a populated map, so its normalizer
        # knows none of the new synonyms, and it has no endings or starts of its own.
        path = memory / predicates.RUNTIME_FILE
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["synonyms"] = {k: v for k, v in data["synonyms"].items()
                            if v not in ("lives-in", "studies-at", "reports-to") and not k.startswith(("formerly",
                                                                                                     "previously"))}
        data.pop("endings", None)
        data.pop("starts", None)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    for eid, (name, etype) in PAGES.items():
        markdown_parser.write(memory / "entities" / f"{eid}.md", {"name": name, "type": etype, "status": "active"},
                              f"## Summary\n{name}.")
    return memory


def _sleep(memory: Path, day: str, n: int, rels: list[tuple], *, source: str = "Bob Example") -> dict:
    """One Sleep-style pass over one conversation on `day`: Stage 1 projection, Stage 3, Stage 5 write. A relationship
    is ``(label, target)`` or ``(label, target, extra fields)``."""
    ep = f"ep_{day}_{n:03d}"
    out = []
    for rel in rels:
        label, target, extra = (*rel, {})[:3]
        out.append({"source": source, "target": target, "label": label, "source_episode": ep,
                    "source_episode_timestamp": f"{day}T10:00:00", **extra})
    extracted = [{"episode_id": ep, "episode_timestamp": f"{day}T10:00:00", "origin": "claude-code", "entities": [],
                  "relationships": out}]
    return claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=day)


def _claims(memory: Path, page: str = PERSON) -> list[Claim]:
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{page}.md").body, strict=True)


def _current(memory: Path, predicate: str, page: str = PERSON) -> set[str]:
    return {c.object for c in _claims(memory, page) if c.predicate == predicate and c.valid_to is None}


# --- the vocabulary ----------------------------------------------------------------------------------------------


def test_every_state_predicate_has_a_past_tense_and_an_ending(tmp_path):
    memory = _bank(tmp_path)
    ending = predicates.build_endings_fn(memory)
    for label, canonical in (("worked at", "works-at"), ("lived in", "lives-in"),
                             ("studied at", "studies-at"), ("reported to", "reports-to")):
        assert ending(label) == predicates.Ending(canonical, "past", True), label
    assert ending("worked on") is None, "\"I worked on alpha-project today\" reports ongoing work (review)"
    for label, canonical in (("formerly worked at", "works-at"), ("previously worked on", "works-on"),
                             ("moved out of", "lives-in"), ("graduated from", "studies-at"),
                             ("previously reported to", "reports-to")):
        assert ending(label).canonical == canonical and ending(label).mode == "over", label
    for present in ("works at", "works on", "lives in", "studies at", "reports to"):
        assert ending(present) is None, present
    for canonical in ("lives-in", "studies-at", "reports-to"):
        assert predicates.build_cardinality_fn(memory)(canonical) is False, "a person's places coexist"


def test_start_labels_compare_slugged_and_an_ambiguous_start_starts_nothing(tmp_path):
    memory = _bank(tmp_path)
    onset = predicates.build_onsets_fn(memory)
    assert onset("Started Working At").canonical == "works-at"
    assert onset("was hired by").canonical == "works-at"
    for ambiguous in ("joined", "joins", "started at", "moved into"):
        assert onset(ambiguous) is None, f"{ambiguous}: a club, a team, a university or an office is no job or home"
    assert onset("moved to").canonical == "lives-in"
    assert onset("enrolled at").canonical == "studies-at"
    assert onset("enrolled in") is None, "a course or a programme is no school"
    assert onset("works at") is None
    hired = onset("was hired by")
    assert hired.fits("person", "company") and not hired.fits("company", "project")
    path = memory / predicates.RUNTIME_FILE
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["starts"] = {"lives-in": {"subject": ["person"], "object": ["location"], "labels": ["was hired by"]}}
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert predicates.build_onsets_fn(memory)("was hired by") is None, "two canonicals claim it: when unsure, no fold"
    assert predicates.build_endings_fn(memory).onset("relocated to").canonical == "lives-in"


# --- Stage 1 ------------------------------------------------------------------------------------------------------


def test_a_stated_start_dates_the_belief_and_a_past_tense_keeps_the_day_it_was_said(tmp_path):
    memory = _bank(tmp_path)
    ep = "ep_2026-05-20_001"
    rels = [{"source": "Bob Example", "target": "Globex Example", "label": "works at", "starts": "2026-05-19"},
            {"source": "Bob Example", "target": "Acme Example", "label": "worked at", "starts": "2019-01-01"},
            {"source": "Bob Example", "target": "Initech Example", "label": "works at", "starts": "yesterday"}]
    claims = entity_extractor.entities_to_claims(
        [{"episode_id": ep, "origin": "claude-code",
          "relationships": [{**r, "source_episode": ep, "source_episode_timestamp": "2026-05-20T10:00:00"}
                            for r in rels]}], memory)
    by_target = {c.object: c for c in claims}
    assert by_target["globex-example"].valid_from == "2026-05-19", "the day it became true, as said"
    assert by_target["acme-example"].valid_from == "2026-05-20", "a past tense is history dated when it was said"
    assert by_target["initech-example"].valid_from == "2026-05-20", "nothing relative is stored"


# --- Stage 3 ------------------------------------------------------------------------------------------------------


def test_one_conversation_with_a_past_job_and_a_new_one_names_only_the_new_job(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-05-20", 1, [("worked at", "Acme Example"), ("previously worked on", "Rover Project"),
                                     ("works at", "Globex Example", {"starts": "2026-05-19"})])
    assert _current(memory, "works-at") == {"globex-example"}
    assert _current(memory, "works-on") == set()
    claims = _claims(memory)
    acme = next(c for c in claims if c.object == "acme-example")
    rover = next(c for c in claims if c.object == "rover-project")
    globex = next(c for c in claims if c.object == "globex-example")
    assert acme.predicate == "works-at" and acme.valid_to == acme.valid_from, "closed history, never current"
    assert rover.predicate == "works-on" and rover.valid_to == rover.valid_from
    assert globex.predicate == "works-at" and globex.valid_from == "2026-05-19" and globex.valid_to is None


def test_worked_on_today_is_ongoing_work_never_closed(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-06-01", 1, [("worked on", "Rover Project")])
    assert _current(memory, "works-on") == {"rover-project"}
    _sleep(memory, "2026-06-02", 2, [("works on", "Rover Project")])
    assert _current(memory, "works-on") == {"rover-project"}
    assert len([c for c in _claims(memory) if c.predicate == "works-on"]) == 1


@pytest.mark.parametrize("target", ["Chess Club", "Robotics Team", "Uni Example"])
def test_joining_a_club_a_team_or_a_university_is_no_job(tmp_path, target):
    memory = _bank(tmp_path)
    for n, label in enumerate(("joined", "joins", "started at"), start=1):
        _sleep(memory, f"2026-06-0{n}", n, [(label, target)])
    assert _current(memory, "works-at") == set(), "the card never reads \"Works at: <a club>\""
    assert {c.predicate for c in _claims(memory)} == {"joined", "joins", "started-at"}


def test_a_hire_is_a_job_and_moving_into_an_office_is_no_home(tmp_path):
    memory = _bank(tmp_path)
    result = _sleep(memory, "2026-06-01", 1, [("was hired by", "Globex Example"), ("moved into", "Office Example")])
    assert _current(memory, "works-at") == {"globex-example"}
    assert _current(memory, "lives-in") == set()
    assert not [n for n in result["nudges"] if n.get("kind") == "normalization_audit"
                or n.get("type") == "normalization_audit"], "a curated start asks no fold question"


@pytest.mark.parametrize("past,present,target,predicate", [
    ("worked at", "works at", "Acme Example", "works-at"),
    ("lived in", "lives in", "Lisbon Example", "lives-in"),
    ("studied at", "studies at", "Uni Example", "studies-at"),
    ("reported to", "reports to", "Dana Example", "reports-to"),
])
def test_a_past_tense_is_history_alone_and_reinforces_a_current_belief_in_either_order(
        tmp_path, past, present, target, predicate):
    for stale in (False, True):
        alone = _bank(tmp_path / f"alone-{stale}", stale=stale)
        _sleep(alone, "2026-06-01", 1, [(past, target)])
        assert _current(alone, predicate) == set(), "said alone, a past tense is never current"
        assert [c.valid_to for c in _claims(alone) if c.predicate == predicate] == ["2026-06-01"], stale

    later = _bank(tmp_path / "later")
    _sleep(later, "2026-06-01", 1, [(present, target)])
    _sleep(later, "2026-06-05", 2, [(past, target)])
    slug = target.lower().replace(" ", "-")
    assert _current(later, predicate) == {slug}, "said while it holds, the past tense reinforces it"
    assert len([c for c in _claims(later) if c.predicate == predicate]) == 1

    earlier = _bank(tmp_path / "earlier")
    _sleep(earlier, "2026-06-01", 1, [(past, target)])
    _sleep(earlier, "2026-06-05", 2, [(present, target)])
    assert _current(earlier, predicate) == {slug}, "a newer present statement stands"


def test_a_start_never_closes_another_current_place(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-06-01", 1, [("works at", "Acme Example"), ("lives in", "Lisbon Example")])
    _sleep(memory, "2026-07-01", 2, [("started working at", "Globex Example"), ("moved to", "Porto Example")])
    assert _current(memory, "works-at") == {"acme-example", "globex-example"}, "a person holds several places"
    assert _current(memory, "lives-in") == {"lisbon-example", "porto-example"}
    _sleep(memory, "2026-08-01", 3, [("left", "Acme Example"), ("moved out of", "Lisbon Example")])
    assert _current(memory, "works-at") == {"globex-example"}, "only an ending closes one"
    assert _current(memory, "lives-in") == {"porto-example"}


def test_a_start_between_the_wrong_types_or_to_no_page_keeps_its_own_label(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-06-01", 1, [("started working at", "Rover Project"),
                                     ("started working at", "Unknown Example"), ("moved to", "Acme Example")])
    claims = _claims(memory)
    assert {c.predicate for c in claims} == {"started-working-at", "moved-to"}
    assert _current(memory, "works-at") == set() and _current(memory, "lives-in") == set()
    _sleep(memory, "2026-06-02", 2, [("was hired by", "Initech Example")], source="Acme Example")
    assert {c.predicate for c in _claims(memory, "acme-example")} == {"was-hired-by"}, "a company hired is no job"


def test_an_agent_ending_never_closes_the_persons_own_place(tmp_path):
    memory = _bank(tmp_path)
    own = Claim(id="clm_own", text="Bob Example lives in Lisbon Example", subject=PERSON, predicate="lives-in",
                object="lisbon-example", observer="agent", context="general", source_trust="user_stated",
                origin="manual_edit", valid_from="2026-06-01", recorded_at="2026-06-01")
    path = memory / "entities" / f"{PERSON}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [own]))
    _sleep(memory, "2026-07-01", 1, [("moved out of", "Lisbon Example")])
    assert _current(memory, "lives-in") == {"lisbon-example"}


# --- the person card's neighbour: a project's member line ----------------------------------------------------------


def test_a_members_line_names_the_newest_current_place():
    old = Claim(id="a", text="", subject=PERSON, predicate="works-at", object="acme-example", valid_from="2026-01-01")
    new = Claim(id="b", text="", subject=PERSON, predicate="works-at", object="globex-example",
                valid_from="2026-05-19")
    gone = Claim(id="c", text="", subject=PERSON, predicate="works-at", object="initech-example",
                 valid_from="2026-09-01", valid_to="2026-09-01")
    bank = SimpleNamespace(type_of=lambda _e: "person", fm=lambda _e: {}, claims=lambda _e: [old, new, gone],
                           resolve=lambda e: e, name=lambda e: e.replace("-", " ").title())
    assert project_timeline._member_fact(bank, PERSON) == "Globex Example"


# --- the repair --------------------------------------------------------------------------------------------------


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(bank), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def gitbank(tmp_path: Path) -> Path:
    bank = _bank(tmp_path)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "config", "user.name", "Cicada Test")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "setup")
    return bank


def _legacy(cid: str, predicate: str, obj: str, text: str, day: str = "2026-05-20", **kw) -> Claim:
    """A claim as a bank written before 2026-10-14 holds it: a past tense folded into the present, left open."""
    kw.setdefault("source_episodes", [f"ep_{day}_002"])
    return Claim(id=cid, text=text, subject=PERSON, predicate=predicate, object=obj, observer="agent",
                 context="general", valid_from=day, recorded_at="2026-10-08", **kw)


def _seed(bank: Path, claims: list[Claim]) -> None:
    path = bank / "entities" / f"{PERSON}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "Sleep cycle 2026-10-08")


def test_the_repair_closes_past_roles_writes_starts_and_spares_the_persons_own(gitbank):
    _seed(gitbank, [
        _legacy("clm_old_job", "works-at", "acme-example", "Bob Example worked at Acme Example"),
        _legacy("clm_old_work", "works-on", "rover-project", "Bob Example previously worked on Rover Project"),
        _legacy("clm_today", "works-on", "lab-project", "Bob Example worked on Lab Project"),
        _legacy("clm_with", "works-with", "dana-example", "Bob Example worked with Dana Example"),
        _legacy("clm_club", "joined", "chess-club", "Bob Example joined Chess Club"),
        _legacy("clm_join", "started-working-at", "globex-example", "Bob Example started working at Globex Example"),
        _legacy("clm_home", "lived-in", "lisbon-example", "Bob Example lived in Lisbon Example"),
        _legacy("clm_now", "works-at", "initech-example", "Bob Example works at Initech Example"),
        _legacy("clm_mine", "works-at", "uni-example", "Bob Example worked at Uni Example",
                source_trust="user_stated", origin="manual_edit"),
        _legacy("clm_proj", "started-working-at", "rover-project", "Bob Example started working at Rover Project"),
    ])
    plan = past_roles_repair.analyze(gitbank)
    verdicts = {i.claim_id: (i.action, i.reason) for i in plan.items}
    assert verdicts == {
        "clm_old_job": ("close", "past_words"), "clm_old_work": ("close", "past_words"),
        "clm_join": ("start", "start_label"), "clm_home": ("close", "ending_label"),
        "clm_mine": (None, "persons_own"), "clm_proj": (None, "types"),
    }
    head = _git(gitbank, "rev-parse", "HEAD")
    result = past_roles_repair.apply(gitbank, sleep_holding=lambda: False)
    assert (result.closed, result.started, result.pages) == (3, 1, [f"entities/{PERSON}.md"])
    by_id = {c.id: c for c in _claims(gitbank)}
    assert by_id["clm_old_job"].valid_to == "2026-05-20" and by_id["clm_old_work"].valid_to == "2026-05-20"
    assert by_id["clm_home"].predicate == "lives-in" and by_id["clm_home"].valid_to == "2026-05-20"
    assert by_id["clm_join"].predicate == "works-at" and by_id["clm_join"].valid_to is None
    assert by_id["clm_now"].valid_to is None and by_id["clm_mine"].valid_to is None
    assert by_id["clm_today"].valid_to is None, "\"worked on\" is ongoing work, never closed"
    assert by_id["clm_with"].valid_to is None, "nor is \"worked with\", in a bank's history"
    assert by_id["clm_club"].predicate == "joined" and by_id["clm_club"].valid_to is None
    assert _current(gitbank, "works-at") == {"globex-example", "initech-example", "uni-example"}
    log = _git(gitbank, "log", "-1", "--format=%B")
    assert log.startswith("Close past roles") and "Cicada-Author: cicada" in log
    assert _git(gitbank, "rev-parse", "HEAD~1").strip() == head.strip(), "one commit, alone"
    assert past_roles_repair.analyze(gitbank).changes == [], "a re-run finds nothing"


def test_the_repair_skips_a_dirty_page_and_refuses_while_sleep_writes(gitbank):
    _seed(gitbank, [_legacy("clm_old_job", "works-at", "acme-example", "Bob Example worked at Acme Example")])
    with pytest.raises(past_roles_repair.SleepIsWriting):
        past_roles_repair.apply(gitbank, sleep_holding=lambda: True)
    path = gitbank / "entities" / f"{PERSON}.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nAn edit not yet committed.\n", encoding="utf-8")
    result = past_roles_repair.apply(gitbank, sleep_holding=lambda: False)
    assert result.skipped_dirty == [f"entities/{PERSON}.md"] and result.commit is None


def test_the_repair_reads_only_a_git_bank(tmp_path):
    with pytest.raises(past_roles_repair.NotAGitBank):
        past_roles_repair.analyze(_bank(tmp_path))
    assert git_service.CICADA_AUTHOR == past_roles_repair.AUTHOR


def _episode(bank: Path, ep: str, text: str) -> None:
    markdown_parser.write(bank / "episodes" / f"{ep}.md", {"id": ep, "processed": True}, text)


def _span(bank: Path, ep: str, quote: str) -> Evidence:
    body = markdown_parser.parse(bank / "episodes" / f"{ep}.md").body
    start = body.index(quote)
    return Evidence(episode=ep, start=start, end=start + len(quote), kind="user", hash="x")


def test_the_repair_keeps_a_claim_later_conversations_restated(gitbank):
    """A restatement adds sources and never rewrites the words: "worked at" first, "works at" in two later
    conversations, is one open claim whose text is still the first one (review)."""
    days = ("2026-05-20", "2026-09-01", "2026-10-01")
    words = ("Bob Example worked at Acme Example once.", "Bob Example works at Acme Example now.",
             "Bob Example works at Acme Example still.")
    for day, text in zip(days, words):
        _episode(gitbank, f"ep_{day}_001", text)
    quotes = ("worked at Acme Example", "works at Acme Example", "works at Acme Example")
    restated = _legacy("clm_restated", "works-at", "acme-example", "Bob Example worked at Acme Example",
                       source_episodes=[f"ep_{d}_001" for d in days],
                       evidence=[_span(gitbank, f"ep_{d}_001", q) for d, q in zip(days, quotes)])
    _episode(gitbank, "ep_2026-05-21_001", "Bob Example worked at Initech Example. He was there long ago.")
    _episode(gitbank, "ep_2026-06-21_001", "Again: Bob Example worked at Initech Example years ago.")
    all_past = _legacy("clm_all_past", "works-at", "initech-example", "Bob Example worked at Initech Example",
                       source_episodes=["ep_2026-05-21_001", "ep_2026-06-21_001"],
                       evidence=[_span(gitbank, "ep_2026-05-21_001", "worked at Initech Example"),
                                 _span(gitbank, "ep_2026-06-21_001", "worked at Initech Example")])
    unquoted = _legacy("clm_unquoted", "works-at", "globex-example", "Bob Example worked at Globex Example",
                       source_episodes=["ep_2026-05-22_001", "ep_2026-06-22_001"])
    _seed(gitbank, [restated, all_past, unquoted])
    verdicts = {i.claim_id: (i.action, i.reason) for i in past_roles_repair.analyze(gitbank).items}
    assert verdicts == {"clm_restated": (None, "restated"), "clm_all_past": ("close", "past_words"),
                        "clm_unquoted": (None, "restated")}
