"""G141 §5.1 — `progress.py`, the one event writer, and the refusals that keep
it the only one (`write_claim` refuses event predicates; `claim_pipeline`
relabels a stray Stage-1 label, R-PJB12).

Each case runs on a FRESH small synthetic bank (`alpha-project`,
`hana-example`, `example.com` only), so one case's slugs never collide with
another's. In `_bank` the owner resolves to `"owner"` and no page carries
`owner: true`.
"""
from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

from _synthetic_bank import _bank, _entity

from api.services import agentic_write, markdown_parser, mcp_tools, progress
from api.services import when as when_mod
from api.services.claim_pipeline import run_claim_pipeline
from api.services.claims import is_event, parse_claims

EP = "ep_2026-09-23_001"
DAY = date(2026, 9, 23)
TZ = "Europe/Madrid"
AGENT = dict(observer="agent", origin="mcp", authored_by="claude-code", session_id="ses_x", today=DAY, tz_name=TZ)


def _fresh(tmp_path):
    memory = _bank(tmp_path, git=False)
    markdown_parser.write(memory / "episodes" / f"{EP}.md",
                          {"id": EP, "timestamp": "2026-09-23T16:04:00+00:00", "processed": True,
                           "turns": [{"offset": 0, "ts": "2026-09-23T16:04:00+00:00", "speaker": "user"}]},
                          "user: Yesterday Hana Example sent me the guide.\nassistant: ok")
    _entity(memory, "hana-example", type="person", last_referenced="2026-09-01")
    return memory


def _claims(memory, eid="alpha-project"):
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body, strict=True)


def _fm(memory, eid="alpha-project"):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _bytes(memory, eid="alpha-project"):
    return (memory / "entities" / f"{eid}.md").read_bytes()


def _assert_no_relative_words(memory):
    """Case 7 — the R-PJ6 gate: nothing relative is stored on any event."""
    for f in (memory / "entities").glob("*.md"):
        for c in parse_claims(markdown_parser.parse(f).body):
            if is_event(c):
                for value in (c.text, c.valid_from, c.target, c.status):
                    assert not when_mod.RELATIVE_GREP.search(value or ""), (c.id, value)


# 1 -------------------------------------------------------------------------

def test_a_done_happening_with_a_stated_day(tmp_path):
    memory = _fresh(tmp_path)
    r = progress.record_happening(
        memory, subject="alpha-project", text="Bob got the guide from Hana Example", status="done",
        when="yesterday", evidence=[{"episode": EP, "quote": "Yesterday Hana Example sent me the guide"}],
        participants=[{"role": "from", "surface": "Hana Example"}, {"role": "with", "surface": "Nobody Here"}],
        **AGENT)
    assert r["action"] == "written" and r["matched"] is True
    c = next(c for c in _claims(memory) if c.id == r["claim_id"])
    assert c.valid_from == c.valid_to == "2026-09-22"
    assert (c.date_basis, c.status) == ("stated", "done")
    assert re.fullmatch(r"clm_alpha-project_happened_[0-9a-f]{8}_2026-09-22", c.id)
    assert c.participants == [{"role": "from", "surface": "Hana Example", "entity": "hana-example"}]
    assert str(_fm(memory)["last_referenced"]) == "2026-09-22"          # was 2026-09-02
    assert str(_fm(memory, "hana-example")["last_referenced"]) == "2026-09-22"
    assert set(r["paths"]) == {"entities/alpha-project.md", "entities/hana-example.md"}
    _assert_no_relative_words(memory)


def test_the_participant_surface_must_be_in_the_sentence(tmp_path):
    memory = _fresh(tmp_path)
    r = progress.record_happening(memory, subject="alpha-project", text="Bob got the guide", status="done",
                                  participants=[{"role": "from", "name": "Hana Example"}], **AGENT)
    c = next(c for c in _claims(memory) if c.id == r["claim_id"])
    assert c.participants == [{"role": "from", "entity": "hana-example"}]


def test_a_participant_ref_that_is_a_path_is_never_stored_or_bumped(tmp_path):
    """Task 4 review r1 (finding 1): `entity` is an id, never a path. A
    `../episodes/<ep>` ref, or one reaching outside the bank, is not stored on
    the claim and the file it names keeps its bytes — `_bump` touches only a
    page directly inside entities/."""
    memory = _fresh(tmp_path)
    outside = tmp_path / "outside.md"
    markdown_parser.write(outside, {"id": "outside"}, "not a page")
    ep_path = memory / "episodes" / f"{EP}.md"
    ep_before, out_before = ep_path.read_bytes(), outside.read_bytes()
    rel_out = "../" * (len(memory.relative_to(tmp_path).parts) + 1) + "outside"
    r = progress.record_happening(
        memory, subject="alpha-project", text="Bob met Hana Example", status="done", when="2026-09-22",
        participants=[{"role": "with", "entity": f"../episodes/{EP}"},
                      {"role": "with", "entity": rel_out},
                      {"role": "with", "entity": str(outside.with_suffix(""))},
                      {"role": "with", "entity": f"../episodes/{EP}", "surface": "Hana Example"}],
        **AGENT)
    assert r["action"] == "written"
    c = next(c for c in _claims(memory) if c.id == r["claim_id"])
    assert c.participants == [{"role": "with", "surface": "Hana Example", "entity": "hana-example"}]
    assert ep_path.read_bytes() == ep_before and outside.read_bytes() == out_before
    assert set(r["paths"]) == {"entities/alpha-project.md", "entities/hana-example.md"}
    # The bump itself refuses a path, whatever a claim was carrying.
    assert progress._bump(memory, [f"../episodes/{EP}", rel_out], "2026-09-30") == []
    assert ep_path.read_bytes() == ep_before and outside.read_bytes() == out_before


# 2 -------------------------------------------------------------------------

def test_no_when_uses_the_turn_then_the_write_day(tmp_path):
    memory = _fresh(tmp_path)
    r = progress.record_happening(memory, subject="alpha-project", text="Hana sent the guide", status="done",
                                  evidence=[{"episode": EP, "quote": "Hana Example sent me the guide"}], **AGENT)
    assert (r["day"], r["date_basis"], r["matched"]) == ("2026-09-23", "turn", False)
    r = progress.record_happening(memory, subject="alpha-project", text="Started the arm rewrite",
                                  status="ongoing", **{**AGENT, "today": date(2026, 9, 20)})
    assert (r["day"], r["date_basis"]) == ("2026-09-20", "written")
    _assert_no_relative_words(memory)


# 3 -------------------------------------------------------------------------

def test_refusals_write_nothing(tmp_path):
    memory = _fresh(tmp_path)
    before = _bytes(memory)
    cases = [
        dict(text="Bob got the guide", status="planned"),
        dict(text="Bob got the guide", status="done", when="tomorrow"),
        dict(text="Bob got the guide yesterday", status="done"),
        dict(text="Bob got the guide", status="done", settles="clm_nothing"),
    ]
    for kw in cases:
        r = progress.record_happening(memory, subject="alpha-project", **kw, **AGENT)
        assert r["action"] == "error", kw
    assert "future" in progress.record_happening(memory, subject="alpha-project", text="x", status="done",
                                                 when="tomorrow", **AGENT)["error"]
    assert "no open thread" in progress.record_happening(memory, subject="alpha-project", text="x",
                                                         status="done", settles="clm_nothing", **AGENT)["error"]
    assert _bytes(memory) == before
    r = progress.record_happening(memory, subject="nowhere-example", text="x", status="done", **AGENT)
    assert r["action"] == "not_found"
    assert not (memory / "entities" / "nowhere-example.md").exists()


# 4 -------------------------------------------------------------------------

def test_milestones_set_collide_and_advance(tmp_path):
    memory = _fresh(tmp_path)
    r = progress.set_milestone(memory, subject="alpha-project", name="First grasp", target="2026-10-01", **AGENT)
    assert r["action"] == "written" and r["slug"] == "first-grasp"
    assert r["claim_id"] == "clm_alpha-project_milestone_first-grasp_2026-09-23"
    c = next(c for c in _claims(memory) if c.id == r["claim_id"])
    assert (c.object, c.target, c.status, c.valid_to) == ("first-grasp", "2026-10-01", "planned", None)
    assert progress.set_milestone(memory, subject="alpha-project", name="First grasp", **AGENT)["slug"] \
        == "first-grasp-2"
    r = progress.advance(memory, subject="alpha-project", slug="first-grasp", status="done", on=DAY, **AGENT)
    assert r["claim_id"] == "clm_alpha-project_milestone_first-grasp_2026-09-23-2"
    by_id = {c.id: c for c in _claims(memory)}
    old = by_id["clm_alpha-project_milestone_first-grasp_2026-09-23"]
    assert old.superseded_by == r["claim_id"] and old.valid_to == "2026-09-23"
    assert by_id[r["claim_id"]].status == "done" and by_id[r["claim_id"]].target == "2026-10-01"
    assert progress.advance(memory, subject="alpha-project", slug="nothing-here", status="done",
                            **AGENT)["action"] == "not_found"
    assert progress.set_milestone(memory, subject="alpha-project", name="Demo", target="soonish",
                                  **AGENT)["action"] == "error"
    _assert_no_relative_words(memory)


# 5 -------------------------------------------------------------------------

def _due(memory, *, valid_to, human=False):
    agentic_write.write_claim(memory, "alpha-project", "due", "2026-09-09", observer="owner" if human else "agent",
                              text="First grasp due 2026-09-09", object_kind="literal", today=date(2026, 9, 1))
    page = memory / "entities" / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    claims = parse_claims(parsed.body, strict=True)
    due = next(c for c in claims if c.predicate == "due")
    due.valid_from, due.valid_to = "2026-09-01", valid_to
    from api.services.claims import write_claims
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    return due.id


def test_a_closed_due_is_promoted_to_a_milestone_on_first_touch(tmp_path):
    memory = _fresh(tmp_path)
    due_id = _due(memory, valid_to="2026-09-09")
    r = progress.advance(memory, subject="alpha-project", slug="due-2026-09-09", target="2026-10-01",
                         on=DAY, **AGENT)
    assert r["action"] == "written" and r["slug"] == "first-grasp"
    by_id = {c.id: c for c in _claims(memory)}
    ms = by_id[r["claim_id"]]
    assert (ms.predicate, ms.object, ms.supersedes, ms.target) == ("milestone", "first-grasp", due_id, "2026-10-01")
    assert by_id[due_id].valid_to == "2026-09-09" and by_id[due_id].superseded_by == ms.id


def test_an_open_due_closes_where_the_milestone_begins(tmp_path):
    memory = _fresh(tmp_path)
    due_id = _due(memory, valid_to=None)
    r = progress.advance(memory, subject="alpha-project", slug="due-2026-09-09", target="2026-10-01",
                         on=DAY, **AGENT)
    by_id = {c.id: c for c in _claims(memory)}
    assert by_id[due_id].valid_to == "2026-09-23" and by_id[due_id].superseded_by == r["claim_id"]


def test_an_agent_never_moves_the_persons_own_due(tmp_path):
    memory = _fresh(tmp_path)
    _due(memory, valid_to=None, human=True)
    before = _bytes(memory)
    r = progress.advance(memory, subject="alpha-project", slug="due-2026-09-09", target="2026-10-01",
                         on=DAY, **AGENT)
    assert r["action"] == "error"
    assert _bytes(memory) == before


# 6 -------------------------------------------------------------------------

def test_withdraw_a_born_closed_happening_and_refuse_a_plan_replacing_milestone(tmp_path):
    memory = _fresh(tmp_path)
    r = progress.record_happening(memory, subject="alpha-project", text="Bob got the guide", status="done",
                                  when="2026-09-21", **AGENT)
    w = progress.withdraw(memory, subject="alpha-project", claim_id=r["claim_id"], author="claude-code",
                          reason="it was a different guide", origin="mcp", today=DAY)
    assert w["action"] == "retracted"
    page = _claims(memory)
    target = next(c for c in page if c.id == r["claim_id"])
    assert target.valid_to == "2026-09-21" and target.superseded_by == w["record_id"]
    assert mcp_tools._how_closed(target, page).startswith("withdrawn by ")
    assert progress.withdraw(memory, subject="alpha-project", claim_id=r["claim_id"], author="claude-code",
                             reason="again", origin="mcp", today=DAY)["action"] == "already_closed"

    progress.set_milestone(memory, subject="alpha-project", name="First grasp", target="2026-10-01", **AGENT)
    done = progress.advance(memory, subject="alpha-project", slug="first-grasp", status="done", on=DAY, **AGENT)
    before = _bytes(memory)
    w = progress.withdraw(memory, subject="alpha-project", claim_id=done["claim_id"], author="claude-code",
                          reason="not yet", origin="mcp", today=DAY)
    assert w["action"] == "error" and _bytes(memory) == before
    _assert_no_relative_words(memory)


# refusals elsewhere (Step 5) ----------------------------------------------

def test_write_claim_refuses_event_predicates_and_writes_nothing(tmp_path):
    memory = _fresh(tmp_path)
    before = _bytes(memory)
    r = agentic_write.write_claim(memory, "alpha-project", "happened", "got the guide", observer="agent")
    assert r["action"] == "error" and _bytes(memory) == before
    r = agentic_write.write_claim(memory, "Brand New Thing", "milestone", "first grasp", observer="agent",
                                  force_new_entity=True)
    assert r["action"] == "error"
    assert not (memory / "entities" / "brand-new-thing.md").exists()


def test_claim_pipeline_relabels_a_stray_event_label_without_an_audit_card(tmp_path):
    memory = _fresh(tmp_path)
    _entity(memory, "cicada", type="project")
    _entity(memory, "sqlite-vec", type="tool")
    extracted = [{"episode_id": "ep_2026-06-17_001", "episode_timestamp": "2026-06-17T10:00:00",
                  "origin": "claude-code", "entities": [],
                  "relationships": [{"source": "Cicada", "target": "sqlite-vec", "label": "milestone",
                                     "source_episode": "ep_2026-06-17_001",
                                     "source_episode_timestamp": "2026-06-17T10:00:00"}]}]
    settings = SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini", archive_threshold=0.2,
                               decay_nudge_threshold=0.4)
    result = run_claim_pipeline(extracted, [], memory, settings, now_date="2026-06-17")
    assert result["relabelled_events"] == 1
    assert not [n for n in result["nudges"] if n.get("action") == "normalization_audit"]
    claims = _claims(memory, "cicada")
    assert [c.predicate for c in claims] == ["relates-to"]
