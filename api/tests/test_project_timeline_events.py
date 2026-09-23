"""G141 PJ-3a (T5) — the event layer of the read model, on the demo with its
event commits in place and the person's moves (T6) and follow-ups (T7) off:
spec §12's "after PJ-3" values that do not depend on the person's hand."""
from datetime import UTC, datetime

import pytest

from _demo_scenario import T, d, demo
from api.remote import catalog
from api.services import handshake, markdown_parser, mcp_tools, project_state, project_timeline, state_dictionary

ONGOING = "Bob is connecting to Lab Cluster Example to run the Pick And Place Demo"
CAMERA = "Bob started calibrating the gripper camera"


@pytest.fixture(scope="module")
def bank(tmp_path_factory):
    return demo(tmp_path_factory.mktemp("events"), person=False, followups=False)


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(mcp_tools, "_today_in", lambda tz: T)
    monkeypatch.setattr(mcp_tools, "_now_in", lambda tz: datetime(2026, 9, 23, 18, tzinfo=UTC))


def _ep(bank, title):
    return next(p.stem for p in sorted((bank / "episodes").glob("*.md"))
                if markdown_parser.parse(p).frontmatter.get("title") == title)


def _ctx(bank, *, remote_scopes=None):
    kw = {}
    if remote_scopes is not None:
        kw = {"connector_id": "abcd1234", "available": catalog.tool_names_for(remote_scopes),
              "raw_excerpts": "sources" in remote_scopes, "read_surface": "remote"}
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code", **kw)


def test_now_holds_both_open_threads_and_the_last_done_happening(bank):
    tl = project_timeline.build(bank, "rover-arm-project", tz_name="UTC")
    threads = tl.now.threads
    assert [t.text for t in threads] == [ONGOING, CAMERA]
    assert (threads[0].since, threads[0].last_heard, threads[0].on) == (d(0), d(0), "pick-and-place-demo")
    assert (threads[1].since, threads[1].last_heard, threads[1].on) == (d(-24), d(-24), None)
    last = tl.now.last
    assert last.kind == "happening" and last.day == d(-1) and last.state == "done"
    assert last.claim.date_basis == "stated" and not last.verbatim
    assert {p.id for p in last.participants} >= {"bob-example", "hana-example", "media-example-cluster-guide"}
    guide = next(p for p in last.participants if p.role == "document")
    assert guide.url == "https://example.com/guides/lab-cluster-onboarding.pdf"


def test_a_cited_episode_suppresses_its_moment_and_keeps_its_day(bank):
    tl = project_timeline.build(bank, "rover-arm-project", tz_name="UTC")
    s7 = _ep(bank, "Notes on the lab cluster")
    moments = [i for i in tl.items if i.kind == "moment"]
    assert not any(i.conversation and i.conversation.episode_id == s7 for i in moments)
    assert tl.moment_days == [d(-70), d(-63), d(-45), d(-35), d(-24), d(-14), d(-1), d(0)]
    assert tl.median_gap_days == 10.0
    happenings = [i for i in tl.items if i.kind == "happening"]
    assert len(happenings) == 5 and all(i.claim is not None for i in happenings)
    people = next(g for g in tl.cluster.groups if g.label == "People")
    hana = next(m for m in people.members if m.id == "hana-example")
    assert hana.role_phrase == "from"


def test_the_list_and_the_derived_state_agree(bank):
    rows = {r.id: r for r in project_timeline.list_projects(bank, tz_name="UTC").projects}
    rover = rows["rover-arm-project"]
    assert [t.text for t in rover.open_threads] == [ONGOING, CAMERA]
    assert rover.last_moment_day == d(0) and rover.median_gap_days == 10.0
    tl = project_timeline.build(bank, "rover-arm-project", tz_name="UTC")
    state = project_state.timeline_state(project_state.input_from_timeline(tl), T)
    camera = next(t for t in state["threads"] if t["claimId"] == rover.open_threads[1].claim_id)
    assert camera == {"claimId": rover.open_threads[1].claim_id, "quietDays": 24, "followupEligible": True}
    assert state["quietThreshold"] == 20


def test_state_v3_carries_the_newest_open_thread_as_now(bank):
    state_dictionary.refresh(bank, None, force=True, today=T, probe_repos=False)
    rover = next(p for p in state_dictionary.read_state(bank)["projects"] if p["id"] == "rover-arm-project")
    tl = project_timeline.build(bank, "rover-arm-project", tz_name="UTC")
    assert rover["now"] == {"claim": tl.now.threads[0].claim_id, "text": ONGOING, "since": d(0)}


def test_the_project_reply_prints_now_quiet_and_the_closing_clause(bank, clock):
    tl = project_timeline.build(bank, "rover-arm-project", tz_name="UTC")
    ongoing, camera = (t.claim_id for t in tl.now.threads)
    out = mcp_tools.project(_ctx(bank), "rover-arm-project")
    assert f"Now: {ONGOING} — since today (2026-09-23) [on Pick And Place Demo; {ongoing}]" in out, out
    assert f"Quiet: {CAMERA} — quiet 24 days (last 2026-08-30) [{camera}]" in out
    assert f"Now: {CAMERA}" not in out
    assert "- yesterday (2026-09-22) · done · Bob got the lab cluster onboarding guide from Hana Example" in out
    assert "<https://example.com/guides/lab-cluster-onboarding.pdf>" in out
    assert out.rstrip().endswith("; record progress with cicada_note_progress "
                                 "(settles=<claim id> to finish a thread above).")
    remote = mcp_tools.project(_ctx(bank, remote_scopes={"search", "read"}), "rover-arm-project")
    assert "cicada_note_progress" not in remote and f"Now: {ONGOING}" in remote
