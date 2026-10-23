"""The new user, fourth pass (benchmarks/newuser, 2026-10-23; G148). Placeholders stand in for the persona's names.

1. A switch said for a project is written on the project (Stage 1's prompt), and "<project> replaces <tool>" — the
   label two of twenty replays wrote — ends the project's use like "dropped". An ending said about the person still
   never closes a project's claim (owner, 2026-10-23).
2. W6: a Stage 4 skill whose summary rests on a belief that closed after it was written leaves *How to work with me*.
3. W7: an end said relative to a day is stored as the absolute day Stage 1 resolved (``ends``); a job's end closes the
   working relationships that name it in ``premises`` ("reports to" said with ``at``), never the person's own under an
   agent's word.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from api.services import (claim_expiry, claim_pipeline, claim_reconciler, entity_extractor, markdown_parser,
                          predicates, state_dictionary)
from api.services.claims import Claim, parse_claims, write_claims

PERSON, PROJECT = "bob-example", "alpha-project"


def _settings(memory: Path):
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    markdown_parser.write(memory / "entities" / f"{PERSON}.md",
                          {"name": "Bob Example", "type": "person", "status": "active"}, "## Summary\nA person.")
    markdown_parser.write(memory / "entities" / f"{PROJECT}.md",
                          {"name": "alpha-project", "type": "project", "status": "active"}, "## Summary\nA project.")
    return memory


def _sleep(memory: Path, day: str, n: int, subject: str, rels: list[tuple], *, now: str | None = None) -> dict:
    """``rels``: ``(label, target)`` or ``(label, target, {"ends": ..., "at": ...})``."""
    ep = f"ep_{day}_{n:03d}"
    rows = []
    for rel in rels:
        label, target, extra = (*rel, {}) if len(rel) == 2 else rel
        rows.append({"source": subject, "target": target, "label": label, "source_episode": ep,
                     "source_episode_timestamp": f"{day}T10:00:00", **extra})
    extracted = [{"episode_id": ep, "episode_timestamp": f"{day}T10:00:00", "origin": "claude-code", "entities": [],
                  "relationships": rows}]
    return claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=now or day)


def _claims(memory: Path, page: str, predicate: str | None = None):
    claims = parse_claims(markdown_parser.parse(memory / "entities" / f"{page}.md").body, strict=True)
    return [c for c in claims if predicate is None or c.predicate == predicate]


# --- 1. a switch said for a project ---------------------------------------------------------------------------------

def test_the_prompt_writes_a_switch_on_the_project_and_never_suggests_replaced_by():
    prompt = entity_extractor.EXTRACTION_SYSTEM_PROMPT
    assert "A SWITCH IS SAID ABOUT WHAT SWITCHED" in prompt
    assert '"<project> dropped <old thing>"' in prompt
    assert '"replaced by", "due"' not in prompt, "the passive example label is gone from the verb list"
    assert '"ends": "YYYY-MM-DD' in prompt and '"at": "Organisation Name' in prompt


def test_a_project_that_replaces_a_tool_stops_using_it(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-28", 1, "alpha-project", [("uses", "Tool Example"), ("depends on", "Tool Example")])
    _sleep(memory, "2026-10-09", 2, "alpha-project", [("replaces", "Tool Example")])
    open_ = [c for c in _claims(memory, PROJECT) if c.object == "tool-example" and c.valid_to is None]
    assert open_ == [], "the use and its relative both close on the day"


def test_replaces_with_nothing_in_use_keeps_its_own_label(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-10-09", 1, "alpha-project", [("replaces", "Tool Example")])
    assert [(c.predicate, c.valid_to) for c in _claims(memory, PROJECT)] == [("replaces", None)]


def test_a_drop_said_about_the_person_still_leaves_the_project_alone(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-28", 1, "alpha-project", [("uses", "Tool Example")])
    _sleep(memory, "2026-10-09", 2, "Bob Example", [("dropped", "Tool Example")])
    assert [c.valid_to for c in _claims(memory, PROJECT, "uses")] == [None], "the owner's rule: no cross-subject end"


# --- 3. W7: a stated day, and what rests on a job --------------------------------------------------------------------

def _rel(label, target, **extra):
    return {"source": "Bob Example", "target": target, "label": label, "source_episode": "ep_2026-09-04_001",
            "source_episode_timestamp": "2026-09-04T10:00:00", **extra}


def _emit(*rels):
    return entity_extractor.entities_to_claims(
        [{"episode_id": "ep_2026-09-04_001", "origin": "claude-code", "relationships": list(rels)}], None)


def test_an_ending_is_dated_by_the_day_it_ended_and_any_other_label_gets_a_stated_end():
    left, works, relative = _emit(_rel("left", "Acme Example", ends="2026-09-11"),
                                  _rel("works at", "Acme Example", ends="2026-09-11"),
                                  _rel("works at", "Beta Example", ends="a week from today"))
    assert (left.valid_from, left.expected_end) == ("2026-09-11", None)
    assert (works.valid_from, works.expected_end) == ("2026-09-04", "2026-09-11")
    assert (relative.valid_from, relative.expected_end) == ("2026-09-04", None), "nothing relative is stored"


def test_a_stated_end_before_the_belief_began_is_ignored():
    (works,) = _emit(_rel("works at", "Acme Example", ends="2026-08-01"))
    assert works.expected_end is None


def test_at_rides_only_on_a_working_relationship():
    reports, uses = _emit(_rel("reports to", "Dana Example", at="Acme Example"),
                          _rel("uses", "Tool Example", at="Acme Example"))
    assert getattr(reports, "premise_at", None) == "acme-example"
    assert getattr(uses, "premise_at", None) is None


def test_a_last_day_a_week_ahead_closes_the_job_and_its_manager_on_that_day(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-25", 1, "Bob Example",
           [("works at", "Acme Example"), ("reports to", "Dana Example", {"at": "Acme Example"})])
    _sleep(memory, "2026-09-12", 2, "Bob Example", [("left", "Acme Example", {"ends": "2026-09-11"})])
    works = [c for c in _claims(memory, PERSON, "works-at") if c.valid_from == "2026-08-25"]
    assert [c.valid_to for c in works] == ["2026-09-11"], "the stated last day, not the day it was said"
    reports = _claims(memory, PERSON, "reports-to")
    assert [(c.valid_to, c.premises) for c in reports] == [("2026-09-11", [works[0].id])]


def test_an_end_still_ahead_is_a_stated_end_never_a_future_closing(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-25", 1, "Bob Example", [("works at", "Acme Example")])
    _sleep(memory, "2026-09-04", 2, "Bob Example", [("left", "Acme Example", {"ends": "2026-09-11"})])
    (works,) = [c for c in _claims(memory, PERSON, "works-at") if c.valid_from == "2026-08-25"]
    assert (works.valid_to, works.expected_end) == (None, "2026-09-11"), "still current the day it was said"


def test_expiry_closes_the_job_and_what_rests_on_it(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-25", 1, "Bob Example",
           [("works at", "Acme Example"), ("reports to", "Dana Example", {"at": "Acme Example"})])
    _sleep(memory, "2026-09-04", 2, "Bob Example", [("works at", "Acme Example", {"ends": "2026-09-11"})])
    assert [c.valid_to for c in _claims(memory, PERSON, "reports-to")] == [None]
    claim_expiry.expire(memory, date(2026, 9, 20))
    assert [c.valid_to for c in _claims(memory, PERSON, "works-at")] == ["2026-09-11"]
    assert [c.valid_to for c in _claims(memory, PERSON, "reports-to")] == ["2026-09-11"]


def test_a_manager_at_another_place_or_with_no_place_stays(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-25", 1, "Bob Example",
           [("works at", "Acme Example"), ("works at", "Lab Example"),
            ("reports to", "Dana Example", {"at": "Lab Example"}), ("managed by", "Erin Example")])
    _sleep(memory, "2026-09-12", 2, "Bob Example", [("left", "Acme Example", {"ends": "2026-09-11"})])
    assert {c.object: c.valid_to for c in _claims(memory, PERSON) if c.predicate in ("reports-to", "managed-by")} \
        == {"dana-example": None, "erin-example": None}


def _job_pair(dep_origin: str, dep_trust: str):
    job = Claim(id="clm_job", text="Bob works at Acme", subject=PERSON, predicate="works-at", object="acme-example",
                valid_from="2026-08-25", valid_to="2026-09-11", superseded_by="clm_left")
    left = Claim(id="clm_left", text="Bob left Acme", subject=PERSON, predicate="works-at", object="acme-example",
                 valid_from="2026-09-11", valid_to="2026-09-11", origin="claude-code")
    dep = Claim(id="clm_dep", text="Bob reports to Dana", subject=PERSON, predicate="reports-to", object="dana",
                valid_from="2026-08-25", premises=["clm_job"], origin=dep_origin, source_trust=dep_trust,
                source_episodes=["ep_2026-08-25_001"])
    return [job, left, dep], dep


def test_the_persons_own_relationship_never_closes_under_an_agents_word():
    depends_on = predicates.build_endings_fn(None).depends_on
    slot, dep = _job_pair("manual_edit", "user_stated")
    audit: list[dict] = []
    assert claim_reconciler.close_dependents(slot, depends_on, "2026-09-20", audit) == []
    assert dep.valid_to is None and audit[0]["action"] == "dependent_shadowed_by_human"
    slot, dep = _job_pair("claude-code", "agent_extracted")
    assert claim_reconciler.close_dependents(slot, depends_on, "2026-09-20") == ["clm_dep"]
    assert dep.valid_to == "2026-09-11"


def _own(memory: Path, *claims: Claim):
    """The person's own claims (a manual edit) on their page."""
    for c in claims:
        c.origin, c.source_trust = "manual_edit", "user_stated"
    path = memory / "entities" / f"{PERSON}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, list(claims)))


def _own_job_and_manager(memory: Path, *, end: str | None = None):
    _own(memory,
         Claim(id="clm_own_job", text="Bob works at Acme", subject=PERSON, predicate="works-at",
               object="acme-example", valid_from="2026-08-20", expected_end=end),
         Claim(id="clm_own_dep", text="Bob reports to Dana", subject=PERSON, predicate="reports-to",
               object="dana-example", valid_from="2026-08-20", premises=["clm_own_job"]))


def test_an_agents_stated_end_never_closes_the_persons_own_job_or_manager(tmp_path):
    """Review of #459: an extracted ``ends`` restating the person's own job must not land on it, so neither the job
    nor the manager resting on it closes when expiry passes that day."""
    memory = _bank(tmp_path)
    _own_job_and_manager(memory)
    _sleep(memory, "2026-09-04", 1, "Bob Example",
           [("works at", "Acme Example", {"ends": "2026-09-11"}),
            ("reports to", "Dana Example", {"at": "Acme Example"})])
    claim_expiry.expire(memory, date(2026, 9, 20))
    by_id = {c.id: c for c in _claims(memory, PERSON)}
    assert (by_id["clm_own_job"].valid_to, by_id["clm_own_job"].expected_end) == (None, None)
    assert by_id["clm_own_dep"].valid_to is None


def test_the_persons_own_stated_end_still_closes_their_job_and_manager(tmp_path):
    memory = _bank(tmp_path)
    _own_job_and_manager(memory, end="2026-09-11")
    claim_expiry.expire(memory, date(2026, 9, 20))
    by_id = {c.id: c for c in _claims(memory, PERSON)}
    assert by_id["clm_own_job"].valid_to == "2026-09-11"
    assert by_id["clm_own_dep"].valid_to == "2026-09-11"


def test_a_closer_missing_from_the_page_never_closes_the_persons_own_relationship():
    depends_on = predicates.build_endings_fn(None).depends_on
    slot, dep = _job_pair("manual_edit", "user_stated")
    slot = [c for c in slot if c.id != "clm_left"]
    slot[0].origin, slot[0].source_trust = "manual_edit", "user_stated"
    assert claim_reconciler.close_dependents(slot, depends_on, "2026-09-20") == []


def test_a_relationship_said_after_the_job_ended_is_news():
    depends_on = predicates.build_endings_fn(None).depends_on
    slot, dep = _job_pair("claude-code", "agent_extracted")
    dep.source_episodes = ["ep_2026-09-15_001"]
    assert claim_reconciler.close_dependents(slot, depends_on, "2026-09-20") == []


def test_dependents_table():
    depends_on = predicates.build_endings_fn(None).depends_on
    assert [depends_on(p) for p in ("reports-to", "managed-by", "manages", "reports-to-directly", "works-with")] \
        == ["works-at", "works-at", "works-at", "works-at", None]


# --- 2. W6: a skill resting on a closed belief -----------------------------------------------------------------------

def _skill(memory: Path, sid: str, summary: str, related: list[str], episodes: list[str]):
    from api.services import section_provenance

    body = f"## Summary\n{summary}"
    rows = [{"episode": e, "hash": "0" * 12, "start": -1, "end": -1, "kind": "reasoning"} for e in episodes]
    entity = {"summary": summary, section_provenance.INPUTS: [{"field": "summary", "text": summary,
                                                                "evidence": rows}]}
    fm = {"name": sid.replace("-", " ").title(), "type": "skill", "status": "active", "decay_class": "durable",
          "confidence": 0.7, "related": related, "tags": []}
    section_provenance.refresh(fm, "", body, entity)
    markdown_parser.write(memory / "entities" / f"{sid}.md", fm, body)


def _use(memory: Path, closed: str | None, opened: str = "2026-08-28"):
    markdown_parser.write(memory / "entities" / "tool-example.md",
                          {"name": "Tool Example", "type": "tool", "status": "active"}, "## Summary\nA tool.")
    use = Claim(id="clm_use", text="alpha-project uses Tool Example", subject=PROJECT, predicate="uses",
                object="tool-example", valid_from=opened, valid_to=closed)
    path = memory / "entities" / f"{PROJECT}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [use]))


def _prefs(memory: Path) -> list[str]:
    return [r["id"] for r in state_dictionary._preferences(memory, 10)]


def test_a_skill_citing_a_tool_the_project_later_dropped_leaves_how_to_work_with_me(tmp_path):
    memory = _bank(tmp_path)
    _use(memory, closed="2026-10-09")
    _skill(memory, "review-with-carol", "For alpha-project, Carol reviews the Tool Example pull requests.",
           [PROJECT, "tool-example"], ["ep_2026-09-06_001", "ep_2026-09-27_001"])
    _skill(memory, "short-sessions", "Keep alpha-project sessions short.", [PROJECT, "tool-example"],
           ["ep_2026-09-06_001", "ep_2026-09-27_001"])
    rows = state_dictionary._preferences(memory, 1)
    assert [r["id"] for r in rows] == ["short-sessions"], "only the summary naming the dropped tool goes"
    rows = state_dictionary._preferences(memory, 10)
    assert [r["id"] for r in rows] == ["short-sessions", "review-with-carol"], "under the floor, kept last"
    assert rows[1]["one_liner"].endswith(state_dictionary.STALE_MARK)
    assert not rows[0]["one_liner"].endswith(state_dictionary.STALE_MARK)


def test_how_to_work_with_me_never_empties_and_keeps_the_least_stale(tmp_path):
    memory = _bank(tmp_path)
    _use(memory, closed="2026-10-09")
    path = memory / "entities" / f"{PROJECT}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [
        Claim(id="clm_dep", text="alpha-project depends on Tool Example", subject=PROJECT, predicate="depends-on",
              object="tool-example", valid_from="2026-08-28", valid_to="2026-10-09")]))
    eps = ["ep_2026-09-06_001", "ep_2026-09-27_001"]
    for i in range(5):
        _skill(memory, f"tool-skill-{i}", f"For alpha-project, use Tool Example (way {i}).", [PROJECT, "tool-example"],
               eps)
    rows = state_dictionary._preferences(memory, 5)
    assert len(rows) == state_dictionary.PREFERENCE_FLOOR, "never below the floor, never above it from stale ones"
    assert all(r["one_liner"].endswith(state_dictionary.STALE_MARK) for r in rows)
    assert [r["id"] for r in state_dictionary._preferences(memory, 2)] == ["tool-skill-0", "tool-skill-1"], \
        "the floor never exceeds the row's own cap"


def test_a_belief_no_ending_closes_never_makes_a_skill_stale(tmp_path):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "tool-example.md",
                          {"name": "Tool Example", "type": "tool", "status": "active"}, "## Summary\nA tool.")
    path = memory / "entities" / f"{PROJECT}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [
        Claim(id="clm_m", text="alpha-project mentions Tool Example", subject=PROJECT, predicate="mentions",
              object="tool-example", valid_from="2026-08-28", valid_to="2026-10-09")]))
    _skill(memory, "tool-notes", "For alpha-project, Tool Example notes go in the wiki.", [PROJECT, "tool-example"],
           ["ep_2026-09-06_001"])
    (row,) = state_dictionary._preferences(memory, 1)
    assert row["id"] == "tool-notes" and not row["one_liner"].endswith(state_dictionary.STALE_MARK)


def test_each_page_is_parsed_once_per_rebuild(tmp_path, monkeypatch):
    from api.services import skill_staleness

    memory = _bank(tmp_path)
    _use(memory, closed=None)
    for i in range(6):
        _skill(memory, f"s-{i}", f"For alpha-project, use Tool Example ({i}).", [PROJECT, "tool-example"],
               ["ep_2026-09-06_001"])
    calls: list[int] = []
    real = skill_staleness.parse_claims
    monkeypatch.setattr(skill_staleness, "parse_claims", lambda body: calls.append(1) or real(body))
    assert len(state_dictionary._preferences(memory, 10)) == 6
    assert len(calls) == 2, "the project page and the tool page, once each"


def test_a_skill_written_after_the_drop_or_before_the_use_stays(tmp_path):
    memory = _bank(tmp_path)
    _use(memory, closed="2026-10-09")
    _skill(memory, "self-hosting", "For alpha-project, self-host rather than Tool Example.",
           [PROJECT, "tool-example"], ["ep_2026-10-09_001", "ep_2026-10-19_001"])
    assert _prefs(memory) == ["self-hosting"], "its words were written knowing the drop"
    _use(memory, closed="2026-10-12", opened="2026-10-11")
    assert _prefs(memory) == ["self-hosting"], "a belief opened after the summary was never what it rested on"


def test_a_skill_with_no_dated_provenance_is_kept(tmp_path):
    memory = _bank(tmp_path)
    _use(memory, closed="2026-10-09")
    markdown_parser.write(memory / "entities" / "old-skill.md",
                          {"name": "Old skill", "type": "skill", "status": "active", "decay_class": "durable",
                           "related": [PROJECT, "tool-example"], "tags": []},
                          "## Summary\nFor alpha-project, use Tool Example.")
    assert _prefs(memory) == ["old-skill"], "when unsure, kept"


# --- addition (acting owner, 2026-10-23, from a live test): changed facts beside their replacements -----------------

def _value(memory: Path, day: str, n: int, attribute: str, value: str, *, now: str | None = None) -> dict:
    ep = f"ep_{day}_{n:03d}"
    extracted = [{"episode_id": ep, "episode_timestamp": f"{day}T10:00:00", "origin": "claude-code", "entities": [],
                  "relationships": [],
                  "values": [{"entity": "alpha-project", "attribute": attribute, "value": value,
                              "source_episode": ep, "source_episode_timestamp": f"{day}T10:00:00"}]}]
    return claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=now or day)


def _open_values(memory: Path) -> dict[str, str]:
    return {c.predicate: c.object for c in _claims(memory, PROJECT) if c.object_kind == "literal" and c.valid_to is None}


def test_a_newer_release_under_another_wording_closes_the_older(tmp_path):
    memory = _bank(tmp_path)
    _value(memory, "2026-09-02", 1, "latest release", "0.3.1")
    _value(memory, "2026-10-21", 2, "released version", "0.6.0")
    assert list(_open_values(memory).values()) == ["0.6.0"]
    (old,) = [c for c in _claims(memory, PROJECT) if c.object == "0.3.1"]
    assert old.valid_to == "2026-10-21", "closed on the day the newer value was said"


def test_an_older_release_read_late_stays_history(tmp_path):
    memory = _bank(tmp_path)
    _value(memory, "2026-10-21", 1, "released version", "0.6.0")
    _value(memory, "2026-09-02", 2, "latest release", "0.3.1", now="2026-10-22")
    assert list(_open_values(memory).values()) == ["0.6.0"], "the newest dated evidence wins (ruling 26)"


def test_values_outside_a_declared_group_still_coexist(tmp_path):
    memory = _bank(tmp_path)
    _value(memory, "2026-09-02", 1, "release", "0.3.1")
    _value(memory, "2026-10-21", 2, "python version", "3.12")
    assert sorted(_open_values(memory).values()) == ["0.3.1", "3.12"], "no fold by guess"


def test_moved_from_a_to_b_closes_every_a_variant_and_keeps_b(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-20", 1, "alpha-project",
           [("uses", "Index Example"), ("uses for vector search", "Index Example"), ("built on", "Index Example"),
            ("depends on", "Index Example"), ("stores data in", "Index Example")])
    _sleep(memory, "2026-10-05", 2, "alpha-project",
           [("moved from", "Index Example"), ("uses", "Vec Example"), ("replaced with", "Vec Example")])
    still = [(c.predicate, c.object) for c in _claims(memory, PROJECT) if c.valid_to is None]
    assert not [s for s in still if s[1] == "index-example"], still
    assert ("uses", "vec-example") in still, "what replaced it is current; 'replaced with' never ends it"


def test_replaced_a_with_b_said_by_an_agent_never_closes_the_persons_own_use(tmp_path):
    memory = _bank(tmp_path)
    own = Claim(id="clm_own", text="alpha-project uses Index Example", subject=PROJECT, predicate="uses",
                object="index-example", valid_from="2026-08-20", source_trust="user_stated", origin="manual_edit",
                source_episodes=["ep_2026-08-20_001"])
    path = memory / "entities" / f"{PROJECT}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [own]))
    _sleep(memory, "2026-10-05", 2, "alpha-project", [("replaced", "Index Example")])
    (kept,) = [c for c in _claims(memory, PROJECT, "uses") if c.id == "clm_own"]
    assert kept.valid_to is None
