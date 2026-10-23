"""`cicada_project` after the 2026-10-23 live test: a conversation that names the project once is not its history,
a moment leads with what was said about the project, a session in the project's repository is activity, and the
status says where the project stands — never "planned" because one old deadline exists.

Synthetic bank, placeholder names only."""
from __future__ import annotations

from datetime import date

from _synthetic_bank import _bank, _entity
from api.services import bank_index, markdown_parser, project_state, project_text, project_timeline, workspace_identity
from api.services.claims import Claim, Evidence, write_claims

TZ = "UTC"
TODAY = date(2026, 10, 23)
REPO_DIR = "/home/someone/code/alpha-project"


def _span(ep: str) -> list[Evidence]:
    return [Evidence(episode=ep, start=0, end=10, kind="user", hash="000000000000")]


def _claim(cid, subject, text, ep, day, *, predicate="relates-to", obj="", kind="node"):
    return Claim(id=cid, text=text, subject=subject, predicate=predicate, object=obj, object_kind=kind,
                 valid_from=day, source_episodes=[ep], evidence=_span(ep))


def _ep(memory, ep, ts, body="user: a conversation about many things", **fm):
    markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "timestamp": ts, "processed": True, **fm}, body)


def _page(memory, eid, claims, **fm):
    _entity(memory, eid, body=write_claims("## Summary\nA fixture.\n", claims), **fm)


def _bank_with_noise(tmp_path):
    """alpha-project discussed in substance once (three claims, ep 001) and named once in a long conversation about
    other things (ep 002: one claim naming it among twelve)."""
    memory = _bank(tmp_path, git=False)
    _entity(memory, "bob-example", type="person", owner=True, name="Bob Example")
    deep, noisy = "ep_2026-10-10_001", "ep_2026-10-12_002"
    _ep(memory, deep, "2026-10-10T09:00:00+00:00")
    _ep(memory, noisy, "2026-10-12T09:00:00+00:00")
    _page(memory, "alpha-project", [
        _claim("clm_a1", "alpha-project", "Alpha Project uses Tool Example", deep, "2026-10-10", predicate="uses",
               obj="tool-example"),
        _claim("clm_a2", "alpha-project", "Alpha Project targets the lab demo", deep, "2026-10-10",
               predicate="targets", obj="lab-demo", kind="literal"),
    ], type="project", created="2026-10-01")
    owner = [_claim("clm_o1", "bob-example", "Bob Example works on Alpha Project", deep, "2026-10-10",
                    predicate="works-on", obj="alpha-project"),
             _claim("clm_o2", "bob-example", "Bob Example mentions Alpha Project in a cover letter", noisy,
                    "2026-10-12", predicate="mentions", obj="alpha-project")]
    owner += [_claim(f"clm_n{i}", "bob-example", f"Bob Example syncs drive number {i}", noisy, "2026-10-12",
                     predicate="syncs", obj=f"drive-{i}", kind="literal") for i in range(11)]
    _page(memory, "bob-example", owner, type="person", owner=True, name="Bob Example")
    bank_index.invalidate()
    return memory, deep, noisy


def test_a_conversation_naming_the_project_once_is_not_its_history(tmp_path):
    memory, deep, noisy = _bank_with_noise(tmp_path)
    tl = project_timeline.build(memory, "alpha-project", tz_name=TZ)
    moments = [i for i in tl.items if i.kind == "moment"]
    assert [m.conversation.episode_id for m in moments] == [deep]
    # The passing mention's day still counts as activity: the list and the detail read the same days (R-PJB19).
    assert "2026-10-12" in tl.moment_days


def test_a_moment_leads_with_what_was_said_about_the_project(tmp_path):
    memory, deep, _ = _bank_with_noise(tmp_path)
    # Owner facts about other things co-cited in the deep conversation must not lead it.
    owner = markdown_parser.parse(memory / "entities" / "bob-example.md")
    extra = [_claim("clm_x", "bob-example", "Bob Example likes long walks", deep, "2026-10-10",
                    predicate="likes", obj="long walks", kind="literal")]
    # The longest span of the person's own words: the old lead rule put it first.
    extra[0].evidence = [Evidence(episode=deep, start=0, end=30, kind="user", hash="000000000000")]
    from api.services.claims import parse_claims
    markdown_parser.write(memory / "entities" / "bob-example.md", owner.frontmatter,
                          write_claims("## Summary\nA fixture.\n", parse_claims(owner.body) + extra))
    bank_index.invalidate()
    tl = project_timeline.build(memory, "alpha-project", tz_name=TZ)
    (moment,) = [i for i in tl.items if i.kind == "moment"]
    assert moment.facts[0].claim_id in {"clm_a1", "clm_a2", "clm_o1"}
    assert "long walks" not in moment.text


def test_a_session_in_the_repository_is_activity_and_the_status_says_active(tmp_path):
    memory = _bank(tmp_path, git=False)
    old = "ep_2026-08-01_001"
    _ep(memory, old, "2026-08-01T09:00:00+00:00")
    _page(memory, "alpha-project", [
        _claim("clm_a1", "alpha-project", "Alpha Project uses Tool Example", old, "2026-08-01", predicate="uses",
               obj="tool-example"),
        _claim("clm_a2", "alpha-project", "Alpha Project targets the lab demo", old, "2026-08-01",
               predicate="targets", obj="lab-demo", kind="literal"),
        # One old deadline that passed: a milestone, never the project's status.
        Claim(id="clm_due", text="Alpha Project due 2026-09-01", subject="alpha-project", predicate="due",
              object="2026-09-01", object_kind="literal", valid_from="2026-08-01", valid_to="2026-09-01",
              expected_end="2026-09-01", source_episodes=[old]),
    ], type="project", created="2026-08-01")
    seen = {"cwd_hash": workspace_identity.digest(REPO_DIR), "family_hash": "a" * 16, "checkout_hash": "b" * 16,
            "observed_at": "2026-10-20T10:00:00+00:00"}
    # A days-long session in the repository, not consolidated yet: its last turn is today.
    _ep(memory, "ep_2026-10-20_001", "2026-10-20T10:00:00+00:00", processed=False, harness="claude-code",
        project_dir=REPO_DIR, workspace_identity=seen, last_turn_at="2026-10-23T08:00:00Z")
    bank_index.invalidate()
    tl = project_timeline.build(memory, "alpha-project", tz_name=TZ)
    assert tl.last_repo_day == "2026-10-23" and tl.last_moment_day == "2026-10-23"
    state = project_state.timeline_state(project_state.input_from_timeline(tl), TODAY)
    text = project_text.render(tl, state, memory_path=memory, today=TODAY, raw=True, can_note=False,
                               can_detail=False)
    head = text.splitlines()[0]
    assert head.startswith("Alpha Project — active · last activity today (2026-10-23), a session in its repository")
    assert "planned" not in head and "0 of 1 milestones done" in head
    # The list reads the same activity (R-PJB19).
    row = next(r for r in project_timeline.list_projects(memory, tz_name=TZ).projects if r.id == "alpha-project")
    assert row.last_moment_day == "2026-10-23" and row.last_repo_day == "2026-10-23"


def test_without_recent_activity_the_status_is_quiet_or_resting(tmp_path):
    memory = _bank(tmp_path, git=False)
    old = "ep_2026-08-01_001"
    _ep(memory, old, "2026-08-01T09:00:00+00:00")
    _page(memory, "alpha-project", [
        _claim("clm_a1", "alpha-project", "Alpha Project uses Tool Example", old, "2026-08-01", predicate="uses",
               obj="tool-example")], type="project", created="2026-08-01")
    bank_index.invalidate()
    tl = project_timeline.build(memory, "alpha-project", tz_name=TZ)
    assert tl.last_repo_day is None
    quiet = project_state.timeline_state(project_state.input_from_timeline(tl), TODAY)
    assert project_text.status_word(tl, quiet) == "quiet"
    resting = project_state.timeline_state(project_state.input_from_timeline(tl), date(2027, 3, 1))
    assert project_text.status_word(tl, resting) == "resting"
