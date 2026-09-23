"""G141 PJ-1 — the derived timeline, on a freshly generated demo bank (spec §12)."""
from __future__ import annotations

import subprocess

import pytest

from _demo_scenario import T, TZ, d, day_one
from _synthetic_bank import _bank, _entity
from api.services import bank_index, markdown_parser, project_state, project_timeline, search_index
from api.services.claims import Claim, Evidence, write_claims


def _ep(bank, needle):
    return next(p.stem for p in (bank / "episodes").glob("*.md") if needle in p.read_text())


def _with_claims(memory, eid, claims, *, body="## Summary\nA fixture.\n", **fm):
    _entity(memory, eid, body=write_claims(body, claims), **fm)


def _ep_file(memory, ep, body, ts):
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "timestamp": ts, "processed": True}, body)


@pytest.fixture
def bank(tmp_path):
    return day_one(tmp_path)


def test_the_s7_moment_carries_its_participants_quote_and_url(bank):
    tl = project_timeline.build(bank, "rover-arm-project", tz_name=TZ)
    s7 = _ep(bank, "Yesterday Hana")
    m = next(i for i in tl.items if i.kind == "moment" and i.id == f"m:{s7}:{d(0)}")
    assert m.day == d(0) and m.at == f"{d(0)}T16:04:00Z" and m.date_basis == "turn"
    assert m.via == "pick-and-place-demo"
    assert {f.predicate for f in m.facts} >= {"provides", "runs-on", "connects-to"}
    by_id = {p.id: p for p in m.participants}
    assert by_id["bob-example"].is_owner and "hana-example" in by_id and "lab-cluster-example" in by_id
    assert by_id["media-example-cluster-guide"].url == "https://example.com/guides/lab-cluster-onboarding.pdf"
    assert m.quote.kind == "user" and m.quote.status == "current" and m.quote.start is not None
    assert m.conversation.origin == "telegram" and m.conversation.resumable is False


def test_a_telegram_episode_without_turns_is_dated_by_the_episode(bank):
    tl = project_timeline.build(bank, "rover-arm-project", tz_name=TZ)
    s3 = next(i for i in tl.items if i.kind == "moment" and i.day == d(-45))
    assert s3.date_basis == "episode" and s3.via is None


def test_expected_values_after_pj1(bank):
    tl = project_timeline.build(bank, "rover-arm-project", tz_name=TZ)
    assert tl.moment_days == [d(x) for x in (-70, -63, -45, -35, -24, -14, -1, 0)]
    st = project_state.timeline_state(project_state.input_from_timeline(tl), T)
    assert st["quietThreshold"] == 20 and st["medianGapDays"] == 10.0
    assert st["progress"] == {"done": 0, "total": 4} and st["next"] == f"due-{d(12)}"
    assert tl.now.threads == [] and tl.now.last.kind == "moment" and tl.now.last.day == d(0)
    assert tl.now.next.slug == f"due-{d(12)}" and tl.now.next.name == "Pick And Place Demo"
    assert tl.now.next.on == "pick-and-place-demo"
    assert tl.pending.unconsolidated == 1 and tl.pending.newest_day == d(0)


def test_read_compat_dues_after_expiry_never_read_missed(bank):
    tl = project_timeline.build(bank, "rover-arm-project", tz_name=TZ)
    rows = {m.slug: m for m in tl.milestones}
    assert rows[f"due-{d(-42)}"].status == "passed-no-word" and rows[f"due-{d(-42)}"].name == "Arm assembled"
    assert rows[f"due-{d(-14)}"].status == "passed-no-word" and rows[f"due-{d(-14)}"].name == "First grasp"
    assert rows[f"due-{d(40)}"].status == "planned" and rows[f"due-{d(40)}"].name == "Lab showcase"
    assert all(m.status != "missed" for m in tl.milestones) and all(m.source == "due" for m in tl.milestones)
    assert [c.id for c in rows[f"due-{d(-42)}"].chain]


def test_a_stage1_node_due_reads_the_same(tmp_path):
    """R-PJB22: Stage 1 writes the date as a node object; read-compat is shape-blind."""
    memory = _bank(tmp_path, git=False)
    _with_claims(memory, "omega-project", [Claim(
        id="clm_2026-07-01_aaaa0001", text="Omega Project due 2026-12-01", subject="omega-project",
        predicate="due", object="2026-12-01", object_kind="node", valid_from="2026-07-01")],
        type="project", created="2026-07-01")
    bank_index.invalidate()
    (row,) = project_timeline.build(memory, "omega-project", tz_name=TZ).milestones
    assert (row.slug, row.name, row.status, row.target, row.source) == (
        "due-2026-12-01", "Omega Project", "planned", "2026-12-01", "due")


def test_the_garden_project_is_unplanned_and_in_motion(bank):
    tl = project_timeline.build(bank, "garden-sensor-project", tz_name=TZ)
    st = project_state.timeline_state(project_state.input_from_timeline(tl), T)
    assert tl.milestones == [] and st["planned"] is False
    assert st["quietThreshold"] == 43 and st["section"] == "inMotion"


def test_the_cluster_groups_members_with_a_fact_each(bank):
    tl = project_timeline.build(bank, "rover-arm-project", tz_name=TZ)
    groups = {g.label: g for g in tl.cluster.groups}
    tools = {m.id: m for m in groups["Tools & infrastructure"].members}
    assert tools["lab-cluster-example"].fact == "4 GPU nodes · Slurm-example scheduler · login.example.com"
    assert [m.id for m in groups["Sub-projects"].members] == ["pick-and-place-demo"]
    assert "bob-example" not in {m.id for g in tl.cluster.groups for m in g.members}   # "You", never a member


def test_the_commons_guard(tmp_path):
    """R-PJ20: a tool linked from 13 projects goes to alsoUses and its claims stay out of moments."""
    memory = _bank(tmp_path, git=False)
    ep = "ep_2026-09-10_001"
    _ep_file(memory, ep, "user: the hub got faster", "2026-09-10T09:00:00+00:00")
    for n in range(1, 14):
        _with_claims(memory, f"proj-{n:02d}", [Claim(
            id=f"clm_p{n:02d}", text=f"Proj {n} uses Tool Hub", subject=f"proj-{n:02d}", predicate="uses",
            object="tool-hub", valid_from="2026-09-10", source_episodes=[ep])], type="project", created="2026-08-01")
    _with_claims(memory, "tool-hub", [Claim(
        id="clm_hub_1", text="Tool Hub got faster", subject="tool-hub", predicate="spec", object="faster",
        object_kind="literal", valid_from="2026-09-10", source_episodes=[ep])], type="tool")
    bank_index.invalidate()
    tl = project_timeline.build(memory, "proj-01", tz_name=TZ)
    assert "tool-hub" in {m.id for m in tl.cluster.also_uses}
    assert "tool-hub" not in {m.id for g in tl.cluster.groups for m in g.members}
    assert "clm_hub_1" not in {f.claim_id for i in tl.items for f in i.facts}


def test_history_bullets_are_grey_rows_and_out_of_window_reads_undated(tmp_path):
    memory = _bank(tmp_path, git=False)
    _entity(memory, "omega-project", type="project", created="2026-07-01", last_referenced="2026-09-01",
            body="## Summary\nOmega.\n\n## History\n- 2026-08-01 — kicked off\n- 1990-01-01 — a typo\n- no date here\n")
    bank_index.invalidate()
    rows = [i for i in project_timeline.build(memory, "omega-project", tz_name=TZ).items if i.kind == "history"]
    assert [(r.day, r.text) for r in rows] == [
        ("2026-08-01", "kicked off"), (None, "1990-01-01 — a typo"), (None, "no date here")]


def test_a_legacy_claim_gets_a_derived_quote_and_a_stale_span_loses_offsets(tmp_path):
    memory = _bank(tmp_path, git=False)
    _ep_file(memory, "ep_2026-09-05_001", "user: Omega Project is moving again", "2026-09-05T09:00:00+00:00")
    _ep_file(memory, "ep_2026-09-06_001", "user: rewritten since the span was minted", "2026-09-06T09:00:00+00:00")
    _with_claims(memory, "omega-project", [
        Claim(id="clm_legacy", text="Omega Project relates to Alpha Project", subject="omega-project",
              predicate="relates-to", object="alpha-project", valid_from="2026-09-05",
              source_episodes=["ep_2026-09-05_001"]),
        Claim(id="clm_stale", text="Omega Project uses Tool Z", subject="omega-project", predicate="uses",
              object="tool-z", valid_from="2026-09-06",
              evidence=[Evidence(episode="ep_2026-09-06_001", start=6, end=20, kind="user", hash="000000000000")])],
        type="project", created="2026-09-01")
    bank_index.invalidate()
    moments = {i.day: i for i in project_timeline.build(memory, "omega-project", tz_name=TZ).items
               if i.kind == "moment"}
    legacy, stale = moments["2026-09-05"].quote, moments["2026-09-06"].quote
    assert (legacy.kind, legacy.status, legacy.start, legacy.end) == ("derived", "derived", 6, 19)
    assert (stale.status, stale.start, stale.end) == ("stale", None, None)


def test_the_raw_path_agrees_with_the_index_and_the_cap_sets_partial(bank, monkeypatch):
    fts = project_timeline.build(bank, "rover-arm-project", tz_name=TZ)
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "building")
    raw = project_timeline.build(bank, "rover-arm-project", tz_name=TZ)
    assert [i.id for i in raw.items] == [i.id for i in fts.items]
    monkeypatch.setattr(project_timeline, "MAX_SCAN_PAGES", 5)
    assert project_timeline.build(bank, "rover-arm-project", tz_name=TZ).partial is True


def test_reading_writes_nothing_and_calls_no_engine(bank, monkeypatch):
    def status():
        # A fresh demo bank is never porcelain-clean (the scaffold's .gitignore, _predicates.yaml and
        # _preferences.md stay untracked), so the rail is "reading changed nothing", not "clean".
        return subprocess.run(["git", "-C", str(bank), "status", "--porcelain"], capture_output=True,
                              text=True).stdout
    before = {p: p.stat().st_mtime_ns for p in bank.rglob("*.md")}
    before_status = status()
    def boom(*a, **k):
        raise AssertionError("a read path must not spawn or call an engine")
    import litellm
    # `context()`, not `undo()`: undo would also drop conftest's autouse patches (CICADA_HOME,
    # telemetry off, the Sleep probe) — they share this test's monkeypatch instance.
    with monkeypatch.context() as m:
        m.setattr(subprocess, "Popen", boom)
        m.setattr(subprocess, "run", boom)
        m.setattr(litellm, "completion", boom)
        m.setattr(litellm, "acompletion", boom)
        project_timeline.build(bank, "rover-arm-project", tz_name=TZ)
        project_timeline.list_projects(bank, tz_name=TZ)
    assert {p: p.stat().st_mtime_ns for p in bank.rglob("*.md")} == before
    assert status() == before_status


def test_a_second_bank_is_never_read(tmp_path):
    a, b = day_one(tmp_path / "a"), day_one(tmp_path / "b")
    page = b / "entities" / "rover-arm-project.md"
    parsed = markdown_parser.parse(page)
    parsed.frontmatter["name"] = "Other Bank Rover"
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    assert project_timeline.build(a, "rover-arm-project", tz_name=TZ).project.name == "Rover Arm Project"


def test_the_list_agrees_with_the_detail_on_the_demo(bank):
    rows = {r.id: r for r in project_timeline.list_projects(bank, tz_name=TZ).projects}
    rover = rows["rover-arm-project"]
    assert rover.children == ["pick-and-place-demo"] and rows["pick-and-place-demo"].parent == "rover-arm-project"
    assert rover.median_gap_days == 10.0 and rover.last_moment_day == d(0) and rover.planned is True
    assert rover.progress.total == 4 and len(rover.milestones) <= 5
    assert rows["garden-sensor-project"].median_gap_days == 21.5


def test_a_non_project_page_is_none(bank):
    assert project_timeline.build(bank, "lab-cluster-example", tz_name=TZ) is None
    assert project_timeline.build(bank, "nobody-here", tz_name=TZ) is None
