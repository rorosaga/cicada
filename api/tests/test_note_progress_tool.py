"""G141 PJ-3a (T5) — `cicada_note_progress`, the agent path onto a project timeline.

An agent records what the person said happened: dated against the turn it was
said in, observer always the agent (remote or not), one commit under the
harness, never a new page. Every refusal is one line and writes nothing.
"""
import re
from datetime import UTC, datetime

import pytest

from _demo_scenario import day_one, demo, treat_as_real
from api.remote import catalog
from api.remote.runtime import BUSY_TEXT, RemoteRuntime
from api.services import agent_commits, handshake, markdown_parser, mcp_tools
from api.services.claims import parse_claims

SENTENCE = "Bob got the lab cluster onboarding guide from Hana Example"
GUIDE = "https://example.com/guides/lab-cluster-onboarding.pdf"
PARTICIPANTS = [{"name": "Bob", "role": "owner"}, {"name": "Hana Example", "role": "from"},
                {"name": "lab cluster onboarding guide", "role": "document", "url": GUIDE}]
CLAIM_ID = re.compile(r"claim `(clm_[^`]+)`")


@pytest.fixture(autouse=True)
def _scenario_is_not_refused_as_a_demo(monkeypatch):
    treat_as_real(monkeypatch)


@pytest.fixture
def commits(monkeypatch):
    calls: list[dict] = []
    real = agent_commits.commit_write

    def spy(memory_path, **kw):
        calls.append(kw)
        return real(memory_path, **kw)

    monkeypatch.setattr(agent_commits, "commit_write", spy)
    return calls


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(mcp_tools, "_now_in", lambda tz: datetime(2026, 9, 23, 18, tzinfo=UTC))


@pytest.fixture
def bank(tmp_path, clock):
    return day_one(tmp_path, index=False)


def _ctx(bank, *, remote_scopes=None):
    kw = {}
    if remote_scopes is not None:
        kw = {"connector_id": "abcd1234", "available": catalog.tool_names_for(remote_scopes),
              "raw_excerpts": "sources" in remote_scopes, "read_surface": "remote"}
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code", **kw)


def _claims(bank, stem):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{stem}.md").body)


def _ep(bank, title):
    return next(p.stem for p in sorted((bank / "episodes").glob("*.md"))
                if markdown_parser.parse(p).frontmatter.get("title") == title)


def _page_bytes(bank):
    return {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")}


def test_the_owners_sentence_is_dated_from_its_turn_and_filed_once(bank, commits):
    s7 = _ep(bank, "Notes on the lab cluster")
    kw = dict(when="yesterday", participants=PARTICIPANTS,
              evidence=[{"episode": s7, "quote": "Yesterday Hana Example sent me the lab cluster onboarding guide"}])
    out = mcp_tools.note_progress(_ctx(bank), "pick-and-place-demo", "happened", SENTENCE, "done", **kw)
    assert "filed on Pick And Place Demo, dated 2026-09-22 from 'yesterday'" in out, out
    assert "1 quote verified" in out
    [claim] = [c for c in _claims(bank, "pick-and-place-demo") if c.predicate == "happened"]
    assert claim.valid_from == claim.valid_to == "2026-09-22" and claim.status == "done"      # born closed
    assert (claim.observer, claim.origin, claim.authored_by) == ("agent", "mcp", "claude-code")
    assert claim.date_basis == "stated"
    roles = {p["role"]: p.get("entity") for p in claim.participants}
    assert roles == {"owner": "bob-example", "from": "hana-example", "document": "media-example-cluster-guide"}
    assert len(commits) == 1
    assert "entities/pick-and-place-demo.md" in commits[0]["paths"]
    assert commits[0]["author"] == "claude-code"
    assert all("trigger: mcp/claude-code" in line for line in commits[0]["lines"])

    again = mcp_tools.note_progress(_ctx(bank), "pick-and-place-demo", "happened", SENTENCE, "done", **kw)
    assert again.startswith("Already recorded on Pick And Place Demo: nothing new (reinforced claim"), again
    assert len([c for c in _claims(bank, "pick-and-place-demo") if c.predicate == "happened"]) == 1


def test_milestones_advance_a_named_due_then_move_on_and_open_new_slots(bank, commits):
    out = mcp_tools.note_progress(_ctx(bank), "rover-arm-project", "milestone", "Lab showcase", "planned",
                                  target="2026-11-02")
    assert "filed on Rover Arm Project as milestone 'lab-showcase' — planned, target 2026-11-02" in out, out
    page = _claims(bank, "rover-arm-project")
    [head] = [c for c in page if c.predicate == "milestone"]
    due = next(c for c in page if c.predicate == "due" and c.object == "2026-11-02")
    assert head.object == "lab-showcase" and head.supersedes == due.id and due.superseded_by == head.id

    done = mcp_tools.note_progress(_ctx(bank), "rover-arm-project", "milestone", "Lab showcase", "done",
                                   milestone="Lab showcase")
    assert "as milestone 'lab-showcase' — done" in done, done
    heads = [c for c in _claims(bank, "rover-arm-project")
             if c.predicate == "milestone" and c.valid_to is None and c.object == "lab-showcase"]
    assert [h.status for h in heads] == ["done"]

    video = mcp_tools.note_progress(_ctx(bank), "rover-arm-project", "milestone", "Arm demo video", "planned",
                                    target="2026-10-20")
    assert "as milestone 'arm-demo-video' — planned, target 2026-10-20" in video, video
    missing = mcp_tools.note_progress(_ctx(bank), "rover-arm-project", "milestone", "Something", "done",
                                      milestone="Nothing like it")
    assert missing.startswith("No milestone 'Nothing like it' on Rover Arm Project — open milestones:"), missing
    assert "arm-demo-video" in missing


def test_a_milestones_when_is_its_day_and_the_reply_says_so(bank, commits):
    """Task-5 review r1: `when` on a milestone reached only `record_happening`,
    so "done yesterday" was stored as today with no word in the reply."""
    out = mcp_tools.note_progress(_ctx(bank), "rover-arm-project", "milestone", "Lab showcase", "done",
                                  milestone="Lab showcase", when="yesterday")
    assert "as milestone 'lab-showcase' — done, on 2026-09-22 from 'yesterday'" in out, out
    [head] = [c for c in _claims(bank, "rover-arm-project")
              if c.predicate == "milestone" and c.object == "lab-showcase"]
    assert (head.valid_from, head.status, head.date_basis) == ("2026-09-22", "done", "stated")

    new = mcp_tools.note_progress(_ctx(bank), "rover-arm-project", "milestone", "Arm demo video", "done",
                                  when="2026-09-20")
    assert "as milestone 'arm-demo-video' — done, on 2026-09-20 from '2026-09-20'" in new, new
    video = next(c for c in _claims(bank, "rover-arm-project") if c.object == "arm-demo-video")
    assert video.valid_from == "2026-09-20"

    before = _page_bytes(bank)
    for when in ("someday soon", "tomorrow"):
        refused = mcp_tools.note_progress(_ctx(bank), "rover-arm-project", "milestone", "Poster", "done",
                                          when=when)
        assert refused.startswith(f"I can't read '{when}' as a day") and "\n" not in refused, refused
    assert _page_bytes(bank) == before


@pytest.mark.parametrize("call, expected", [
    (("pick-and-place-demo", "happened", SENTENCE, "planned"), "'planned' isn't a status for a happened"),
    (("pick-and-place-demo", "happened", SENTENCE, "done", {"when": "tomorrow"}), "can't be in the future"),
    (("pick-and-place-demo", "happened", "Bob got the guide today", "done"), "Write the summary without time words"),
    (("lab-cluster-example", "happened", SENTENCE, "done"), "Lab Cluster Example is a tool; name the project it belongs to."),
    (("rover-arm", "happened", SENTENCE, "done"), "ambiguous subject 'rover-arm'"),
    (("pick-and-place-demo", "happened", SENTENCE, "done", {"settles": "clm_nothing"}),
     "No open thread `clm_nothing` in Pick And Place Demo — nothing was recorded."),
])
def test_every_refusal_is_one_line_and_writes_nothing(bank, commits, call, expected):
    before = _page_bytes(bank)
    args, kw = (call[:4], call[4]) if len(call) == 5 else (call, {})
    out = mcp_tools.note_progress(_ctx(bank), *args, **kw)
    assert expected in out, out
    assert "\n" not in out.strip() or out.startswith("NOT recorded")
    assert _page_bytes(bank) == before and commits == []


def test_a_remote_write_is_the_agents_never_the_owners(bank, commits):
    out = mcp_tools.note_progress(_ctx(bank, remote_scopes={"record"}), "pick-and-place-demo", "happened",
                                  "Bob is connecting to Lab Cluster Example", "ongoing")
    assert out.startswith("Recorded: filed on Pick And Place Demo, dated 2026-09-23 (when it was recorded)"), out
    [claim] = [c for c in _claims(bank, "pick-and-place-demo") if c.predicate == "happened"]
    assert (claim.observer, claim.origin, claim.date_basis) == ("agent", "remote:abcd1234", "written")
    assert claim.source_trust != "user_stated"
    assert "cicada_note_progress" in catalog.WRITE_TOOLS and catalog.TOOL_SCOPE["cicada_note_progress"] == "record"
    connector = catalog.Connector(id="abcd1234", label="Phone", app="claude", scopes=frozenset({"record"}),
                                  created_at="2026-09-01T00:00:00+00:00")
    runtime = RemoteRuntime(memory_path=lambda: bank, sleep_running=lambda: True)
    text, status = runtime.call(connector, "cicada_note_progress",
                                {"project": "pick-and-place-demo", "kind": "happened",
                                 "summary": "Bob is still connecting", "status": "ongoing"})
    assert (text, status) == (BUSY_TEXT, "busy")


def test_retract_withdraws_an_event_through_progress_and_never_someone_elses(bank, commits, tmp_path):
    out = mcp_tools.note_progress(_ctx(bank), "pick-and-place-demo", "happened", SENTENCE, "done")
    cid = CLAIM_ID.search(out).group(1)
    reply = mcp_tools.retract_claim(_ctx(bank), "pick-and-place-demo", cid, "Wrong project")
    assert reply.startswith(f"Withdrew claim `{cid}` on `pick-and-place-demo`"), reply
    page = _claims(bank, "pick-and-place-demo")
    target = next(c for c in page if c.id == cid)
    assert mcp_tools._how_closed(target, page).startswith("withdrawn by claude-code")

    full = demo(tmp_path / "full", index=False, person=False, followups=False)
    s3 = next(c for c in _claims(full, "rover-arm-project")
              if c.predicate == "happened" and c.text == "The arm is fully assembled")
    reply = mcp_tools.retract_claim(_ctx(full), "rover-arm-project", s3.id, "Not true")
    assert "was not written by this agent" in reply and "already stopped" not in reply, reply


def test_settles_finds_the_thread_anywhere_in_the_projects_tree(bank, commits):
    opened = mcp_tools.note_progress(_ctx(bank), "pick-and-place-demo", "happened",
                                     "Bob is connecting to Lab Cluster Example", "ongoing")
    thread = CLAIM_ID.search(opened).group(1)
    done = mcp_tools.note_progress(_ctx(bank), "rover-arm-project", "happened",
                                   "Bob connected to Lab Cluster Example", "done", settles=thread)
    assert "filed on Pick And Place Demo" in done and "thread" in done, done
    page = _claims(bank, "pick-and-place-demo")
    closer = next(c for c in page if c.text == "Bob connected to Lab Cluster Example")
    closed = next(c for c in page if c.id == thread)
    assert closed.valid_to == "2026-09-23" and closed.superseded_by == closer.id
    assert not any(c.predicate == "happened" for c in _claims(bank, "rover-arm-project"))
