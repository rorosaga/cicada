"""The new-user benchmark's endings (benchmarks/newuser, 2026-10-22): a former colleague is not a current collaborator,
and a tool the person dropped is not one they still use.

Measured on the synthetic new user's first Sleep (real values are placeholders): "worked with <person-a>" (a colleague
from a job the person left) was folded into ``works-with`` — a current collaboration — and raised a "Confirm a predicate
fold" question no newcomer could read; "alpha-project dropped <tool-a>" closed nothing, so every "uses <tool-a>" claim
stayed current after the reversal. ``works-at`` already reads its past tense and its departures this way
(``predicates-seed.yaml`` ``endings``); these are the same two rules for two more predicates.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from api.services import claim_pipeline, markdown_parser, predicates
from api.services.claims import parse_claims

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


def _sleep(memory: Path, day: str, n: int, subject: str, rels: list[tuple[str, str]]) -> dict:
    ep = f"ep_{day}_{n:03d}"
    extracted = [{"episode_id": ep, "episode_timestamp": f"{day}T10:00:00", "origin": "claude-code", "entities": [],
                  "relationships": [{"source": subject, "target": target, "label": label, "source_episode": ep,
                                     "source_episode_timestamp": f"{day}T10:00:00"} for label, target in rels]}]
    return claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=day)


def _claims(memory: Path, page: str, predicate: str):
    claims = parse_claims(markdown_parser.parse(memory / "entities" / f"{page}.md").body, strict=True)
    return [c for c in claims if c.predicate == predicate]


def _fold_questions(memory: Path) -> list[str]:
    inbox = memory / "inbox"
    return [p.read_text() for p in inbox.glob("*.md")] if inbox.is_dir() else []


def test_worked_with_is_history_never_a_current_collaborator(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-09-04", 1, "Bob Example", [("worked with", "Carol Example")])
    works = _claims(memory, PERSON, "works-with")
    assert [(c.object, c.valid_to) for c in works] == [("carol-example", "2026-09-04")], "kept as closed history"
    assert not any("worked with" in q for q in _fold_questions(memory)), "a curated ending raises no fold question"


def test_worked_with_reinforces_a_current_collaboration(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-09-01", 1, "Bob Example", [("works with", "Carol Example")])
    _sleep(memory, "2026-09-04", 2, "Bob Example", [("worked with", "Carol Example")])
    works = _claims(memory, PERSON, "works-with")
    assert len(works) == 1 and works[0].valid_to is None, "past tense never closes a current collaboration"
    assert "ep_2026-09-04_002" in works[0].source_episodes


def test_dropping_a_tool_ends_its_use(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-28", 1, "alpha-project", [("uses", "Tool Example"), ("uses", "Other Example")])
    _sleep(memory, "2026-10-09", 2, "alpha-project", [("dropped", "Tool Example")])
    uses = _claims(memory, PROJECT, "uses")
    current = {c.object for c in uses if c.valid_to is None}
    assert current == {"other-example"}, "only the dropped tool ends"
    tool = [c for c in uses if c.object == "tool-example"]
    assert sorted(c.valid_to for c in tool) == ["2026-10-09", "2026-10-09"], "closed on the day, the ending kept"


def test_dropping_something_never_used_keeps_its_own_label(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-10-09", 1, "alpha-project", [("dropped", "Feature Example")])
    claims = parse_claims(markdown_parser.parse(memory / "entities" / f"{PROJECT}.md").body, strict=True)
    assert [(c.predicate, c.valid_to) for c in claims] == [("dropped", None)], "never becomes a tool it used"


def test_the_new_endings_are_unambiguous():
    ending = predicates.build_endings_fn(None)
    assert ending("worked with") == predicates.Ending("works-with", predicates.ENDING_PAST, True)
    for label in ("dropped", "stopped using", "no longer uses", "migrated off", "switched away from"):
        assert ending(label) is not None and ending(label).canonical == "uses", label
        assert ending(label).mode == predicates.ENDING_OVER, label


def _open(memory: Path, page: str) -> set[tuple[str, str]]:
    claims = parse_claims(markdown_parser.parse(memory / "entities" / f"{page}.md").body, strict=True)
    return {(c.predicate, c.object) for c in claims if c.valid_to is None}


def test_dropping_a_tool_ends_its_qualified_and_related_uses(tmp_path):
    """2026-10-23 (benchmarks/newuser): "dropped <tool-a>" closed only a plain ``uses``; the project's "uses for auth and
    data", "stores data in <tool-a> Postgres", "depends on" and "backed by" the same tool stayed current."""
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-28", 1, "alpha-project", [("uses for auth and data", "Tool Example"),
                                                     ("stores data in Tool Example Postgres", "Tool Example"),
                                                     ("tracks", "Tool Example"), ("uses", "Other Example")])
    _sleep(memory, "2026-09-16", 2, "alpha-project", [("depends on", "Tool Example"), ("backed by", "Tool Example"),
                                                     ("relies on", "Other Example")])
    _sleep(memory, "2026-10-09", 3, "alpha-project", [("dropped", "Tool Example")])
    assert _open(memory, PROJECT) == {("tracks", "tool-example"), ("uses", "other-example"),
                                      ("depends-on", "other-example")}, \
        "every use of the dropped tool ends; another tool, and a relation no ending lists, stay"
    claims = parse_claims(markdown_parser.parse(memory / "entities" / f"{PROJECT}.md").body, strict=True)
    closed = {c.predicate: c.valid_to for c in claims if c.object == "tool-example" and c.valid_to}
    assert closed == {"uses-for-auth-and-data": "2026-10-09", "stores-data-in-tool-example-postgres": "2026-10-09",
                      "depends-on": "2026-10-09", "backed-by": "2026-10-09", "uses": "2026-10-09"}, \
        "each keeps its own predicate, closed the day it was dropped; the ending kept as history"


def test_a_related_use_said_after_the_drop_stays_current(tmp_path):
    """Ruling 26: the newest dated evidence wins — a dependency said after the drop is current again."""
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-28", 1, "alpha-project", [("depends on", "Tool Example")])
    _sleep(memory, "2026-10-09", 2, "alpha-project", [("dropped", "Tool Example")])
    _sleep(memory, "2026-10-15", 3, "alpha-project", [("depends on", "Tool Example")])
    assert ("depends-on", "tool-example") in _open(memory, PROJECT)


def test_an_older_related_use_read_after_the_drop_is_history(tmp_path):
    """A drain reads in any order: a dependency said before the drop, read after it, is kept closed."""
    memory = _bank(tmp_path)
    _sleep(memory, "2026-08-28", 1, "alpha-project", [("uses", "Tool Example")])
    _sleep(memory, "2026-10-09", 2, "alpha-project", [("dropped", "Tool Example")])
    _sleep(memory, "2026-09-16", 3, "alpha-project", [("depends on", "Tool Example")])
    assert ("depends-on", "tool-example") not in _open(memory, PROJECT)


def test_a_past_tense_label_still_reinforces_only_its_own_predicate(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-09-01", 1, "Bob Example", [("works with on mobile", "Carol Example")])
    _sleep(memory, "2026-09-04", 2, "Bob Example", [("worked with", "Carol Example")])
    assert ("works-with-on-mobile", "carol-example") in _open(memory, PERSON), "past tense never closes"


def test_the_pages_related_follows_the_drop_in_the_same_pass(tmp_path):
    """Stage 5 rebuilds Related before the batch's claims exist, so the page kept "<tool-a> — uses for auth" after the
    drop until its next write; the claim pass now renames the link from the claims it writes."""
    import yaml

    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "tool-example.md",
                          {"name": "Tool Example", "type": "tool", "status": "active"}, "## Summary\nA tool.")
    page = memory / "entities" / f"{PROJECT}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body + "\n\n## Related\n- [[Tool Example]] — uses for auth\n")
    (memory / "graph_edges.yaml").write_text(yaml.dump({"edges": [
        {"source": PROJECT, "target": "tool-example", "label": "uses for auth"}]}), encoding="utf-8")
    _sleep(memory, "2026-08-28", 1, "alpha-project", [("uses for auth", "Tool Example")])
    assert "- [[Tool Example]] — uses for auth\n" in markdown_parser.parse(page).body
    _sleep(memory, "2026-10-09", 2, "alpha-project", [("dropped", "Tool Example")])
    assert "- [[Tool Example]] — uses for auth (until 2026-10-09)" in markdown_parser.parse(page).body


def test_which_predicates_an_ending_also_ends():
    ended_by = predicates.build_endings_fn(None).ended_by
    for predicate in ("uses", "uses-for-sign-in", "depends-on", "backed-by", "stores-data-in-tool-example-postgres"):
        assert ended_by(predicate) == "uses", predicate
    assert ended_by("works-at-remotely") == "works-at"
    for predicate in ("tracks", "user-of", "", "used-by"):
        assert ended_by(predicate) is None, predicate
