"""G141 §5.1 — `claim_reconciler.reconcile_events`, the event branch of Stage 3.

Happenings fold by span identity, then by day and words; a milestone has one
open head per `(subject, milestone, slug)` across observers; a done happening
is born closed; an agent never closes the person's thread or milestone
(R-PJB14, R-PJB27); events never decay (R-PJ12) and never reach the `K` table.
All synthetic (`alpha-project`, `hana-example`), all engine-free.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, Evidence

EP = "ep_2026-09-23_001"
TODAY = "2026-09-23"


@dataclass
class _Settings:
    memory_path: Path
    litellm_model: str = "test"
    archive_threshold: float = 0.2
    decay_nudge_threshold: float = 0.4
    auto_settle: bool = False


def _span(start, end, episode=EP):
    return Evidence(episode=episode, start=start, end=end, kind="user", hash="h")


def _ev(cid, *, predicate="happened", status="done", text="Bob got the guide", obj=None, day="2026-09-22",
        spans=(), observer="agent", source_trust="agent_extracted", origin="mcp", session=None,
        target=None, participants=None, valid_to=None, recorded_at=None, confidence=0.8,
        subject="alpha-project"):
    return Claim(id=cid, text=text, subject=subject, predicate=predicate,
                 object=obj if obj is not None else " ".join(text.lower().split()),
                 object_kind="literal", observer=observer, source_trust=source_trust, origin=origin,
                 valid_from=day, valid_to=valid_to, recorded_at=recorded_at, confidence=confidence,
                 session_id=session, evidence=list(spans), status=status, target=target,
                 participants=list(participants or []))


def _human(cid, **kw):
    kw.setdefault("observer", "owner")
    kw.setdefault("source_trust", "user_stated")
    kw.setdefault("origin", "manual_edit")
    return _ev(cid, **kw)


def _run(tmp_path, incoming, existing, *, today=TODAY, auto_settle=False):
    out, nudges, audit = reconcile_stage3(incoming, {"alpha-project": existing},
                                          _Settings(tmp_path, auto_settle=auto_settle), now_date=today)
    return out["alpha-project"], nudges, audit


def _events(slot):
    return [c for c in slot if c.predicate in ("happened", "milestone")]


# 1 -------------------------------------------------------------------------

def test_a_reworded_re_extraction_with_an_overlapping_span_folds(tmp_path):
    old = _ev("h1", text="Bob got the guide from Hana", spans=[_span(0, 40)], session="ses_a",
              valid_to="2026-09-22", recorded_at="2026-09-22")
    new = _ev("h2", text="Hana sent Bob the guide", spans=[_span(10, 50)], session="ses_b")
    slot, _, _ = _run(tmp_path, [new], [old])
    assert [c.id for c in _events(slot)] == ["h1"]
    assert slot[0].valid_from == "2026-09-22"
    assert set(slot[0].all_session_ids()) == {"ses_a", "ses_b"}


# 2 -------------------------------------------------------------------------

def test_a_combined_sentence_keeps_one_done_and_one_ongoing(tmp_path):
    whole = [_span(0, 80)]
    first = [_ev("d1", text="got the guide", status="done", spans=whole),
             _ev("o1", text="connecting to the cluster", status="ongoing", spans=whole)]
    slot, _, _ = _run(tmp_path, first, [])
    again = [_ev("d2", text="received the guide", status="done", spans=whole),
             _ev("o2", text="still connecting to the cluster", status="ongoing", spans=whole)]
    slot, _, _ = _run(tmp_path, again, slot)
    assert sorted(c.status for c in _events(slot)) == ["done", "ongoing"]


# 3 -------------------------------------------------------------------------

def test_an_ongoing_restatement_on_a_later_day_reinforces_the_open_thread(tmp_path):
    thread = _ev("o1", text="connecting to the cluster", status="ongoing", day="2026-09-10",
                 recorded_at="2026-09-10")
    later = _ev("o2", text="connecting to the cluster", status="ongoing", day="2026-09-23",
                spans=[_span(0, 20, episode="ep_2026-09-23_002")])
    slot, _, _ = _run(tmp_path, [later], [thread])
    opens = [c for c in _events(slot) if c.valid_to is None]
    assert [c.id for c in opens] == ["o1"]
    assert opens[0].recorded_at == "2026-09-23"
    assert opens[0].valid_from == "2026-09-10"


# 4 -------------------------------------------------------------------------

def test_the_same_words_on_two_dates_are_two_happenings(tmp_path):
    a = _ev("clm_x_2026-09-20", day="2026-09-20", valid_to="2026-09-20", spans=[_span(0, 10, "ep_2026-09-20_001")])
    b = _ev("clm_x_2026-09-22", day="2026-09-22", spans=[_span(0, 10, "ep_2026-09-22_001")])
    slot, _, _ = _run(tmp_path, [b], [a])
    assert sorted(c.id for c in _events(slot)) == ["clm_x_2026-09-20", "clm_x_2026-09-22"]


# 5 -------------------------------------------------------------------------

def test_a_human_milestone_planned_then_done_the_same_day_supersedes(tmp_path):
    planned = _human("m1", predicate="milestone", status="planned", text="First grasp", obj="first-grasp",
                     day=TODAY, target="2026-10-01")
    slot, nudges, _ = _run(tmp_path, [planned], [])
    done = _human("m2", predicate="milestone", status="done", text="First grasp", obj="first-grasp", day=TODAY)
    slot, nudges, _ = _run(tmp_path, [done], slot)
    by_id = {c.id: c for c in slot}
    assert by_id["m1"].superseded_by == "m2" and by_id["m1"].valid_to == TODAY
    assert by_id["m2"].valid_to is None and by_id["m2"].supersedes == "m1"
    assert not [n for n in nudges if n["action"] == "conflict_nudge"]


# 6 -------------------------------------------------------------------------

def test_an_agent_done_beside_a_human_planned_head_coexists_with_one_divergence(tmp_path):
    head = _human("m1", predicate="milestone", status="planned", text="First grasp", obj="first-grasp",
                  day="2026-09-20", target="2026-10-01", recorded_at="2026-09-20")
    agent = _ev("m2", predicate="milestone", status="done", text="First grasp", obj="first-grasp", day=TODAY)
    slot, nudges, _ = _run(tmp_path, [agent], [head])
    assert all(c.valid_to is None for c in _events(slot))
    assert getattr(agent, "_status_note", None) == "shadowed_by_human"
    assert [n["action"] for n in nudges] == ["divergence_nudge"]


def test_the_persons_backdated_done_supersedes_any_head_and_never_closes_before_it_opened(tmp_path):
    for head in (_ev("m1", predicate="milestone", status="planned", text="First grasp", obj="first-grasp",
                     day="2026-09-23", recorded_at="2026-09-23"),
                 _human("m1", predicate="milestone", status="planned", text="First grasp", obj="first-grasp",
                        day="2026-09-23", recorded_at="2026-09-23")):
        done = _human("m2", predicate="milestone", status="done", text="First grasp", obj="first-grasp",
                      day="2026-09-22")
        slot, nudges, _ = _run(tmp_path, [done], [head])
        by_id = {c.id: c for c in slot}
        assert by_id["m1"].superseded_by == "m2"
        assert by_id["m1"].valid_to == "2026-09-23"          # clamped to its own valid_from
        assert by_id["m2"].valid_to is None
        assert not nudges


# 7 -------------------------------------------------------------------------

def test_settles_closes_an_agent_thread(tmp_path):
    thread = _ev("o1", text="connecting to the cluster", status="ongoing", day="2026-09-10")
    done = _ev("d1", text="connected to the cluster", status="done", day="2026-09-22")
    setattr(done, "_settles", "o1")
    slot, _, audit = _run(tmp_path, [done], [thread])
    by_id = {c.id: c for c in slot}
    assert by_id["o1"].valid_to == "2026-09-22" and by_id["o1"].superseded_by == "d1"
    assert getattr(done, "_settle_result") == "closed"
    assert {"action": "supersede", "closed": "o1", "by": "d1"} in audit


def test_an_agents_settles_never_closes_a_human_thread(tmp_path):
    thread = _human("o1", text="connecting to the cluster", status="ongoing", day="2026-09-10")
    done = _ev("d1", text="connected to the cluster", status="done", day="2026-09-22")
    setattr(done, "_settles", "o1")
    slot, _, _ = _run(tmp_path, [done], [thread])
    by_id = {c.id: c for c in slot}
    assert by_id["o1"].valid_to is None
    assert by_id["d1"].valid_to == "2026-09-22"            # still written, born closed
    assert getattr(done, "_settle_result") == "refused"


def test_a_done_that_folds_still_settles_the_thread_by_the_claim_it_folded_into(tmp_path):
    thread = _ev("o1", text="connecting to the cluster", status="ongoing", day="2026-09-10")
    logged = _ev("d1", text="connected to the cluster", status="done", day="2026-09-22", valid_to="2026-09-22")
    again = _human("d2", text="connected to the cluster", status="done", day="2026-09-22")
    setattr(again, "_settles", "o1")
    slot, _, _ = _run(tmp_path, [again], [thread, logged])
    by_id = {c.id: c for c in slot}
    assert "d2" not in by_id and getattr(again, "_folded_into") == "d1"
    assert by_id["o1"].superseded_by == "d1" and by_id["o1"].valid_to == "2026-09-22"


# 8 -------------------------------------------------------------------------

def _people(*ids):
    return [{"role": "owner", "entity": "bob-example"}] + [{"role": "with", "entity": i} for i in ids]


def test_auto_settle_needs_two_shared_non_owner_participants(tmp_path):
    def run(done_people, auto):
        thread = _ev("o1", text="connecting to the cluster", status="ongoing", day="2026-09-10",
                     participants=_people("hana-example", "lab-cluster-example"))
        done = _ev("d1", text="connected, finally", status="done", day="2026-09-22", participants=done_people)
        slot, _, _ = _run(tmp_path, [done], [thread], auto_settle=auto)
        return {c.id: c for c in slot}["o1"].valid_to

    assert run(_people("hana-example", "lab-cluster-example"), True) == "2026-09-22"
    assert run(_people("hana-example"), True) is None
    assert run(_people("hana-example", "lab-cluster-example"), False) is None


# 9 -------------------------------------------------------------------------

def test_a_done_happening_is_born_closed_and_an_ongoing_one_is_open(tmp_path):
    slot, _, _ = _run(tmp_path, [_ev("d1", status="done"),
                                 _ev("o1", status="ongoing", text="connecting to the cluster")], [])
    by_id = {c.id: c for c in slot}
    assert by_id["d1"].valid_to == by_id["d1"].valid_from == "2026-09-22"
    assert by_id["o1"].valid_to is None


# 10 ------------------------------------------------------------------------

def test_events_never_decay(tmp_path):
    ms = _ev("m1", predicate="milestone", status="planned", text="First grasp", obj="first-grasp",
             day="2026-01-01", recorded_at="2026-01-01", confidence=0.8)
    th = _ev("o1", status="ongoing", text="connecting", day="2026-01-01", recorded_at="2026-01-01",
             confidence=0.8)
    out, _, _ = reconcile_stage3([], {"alpha-project": [ms, th]}, _Settings(tmp_path), now_date=TODAY)
    assert [c.confidence for c in out["alpha-project"]] == [0.8, 0.8]


# 11 ------------------------------------------------------------------------

def test_events_never_reach_the_k_table(tmp_path):
    incoming = [
        _ev("m1", predicate="milestone", status="planned", text="First grasp", obj="first-grasp"),
        _ev("m2", predicate="milestone", status="planned", text="Demo day", obj="demo-day"),
        _ev("h1", text="fixed the arm", spans=[_span(0, 5)]),
        _ev("h2", text="ordered parts", spans=[_span(10, 15)]),
        _ev("h3", text="wrote the guide", status="ongoing", spans=[_span(20, 25)]),
    ]
    slot, nudges, _ = _run(tmp_path, incoming, [])
    assert len(_events(slot)) == 5
    assert not [n for n in nudges if n["action"] == "conflict_nudge"]


# The readers (R-PJ3, R-PJB11) and expiry ------------------------------------

def test_a_born_closed_happening_is_history_nowhere_it_is_read(tmp_path, monkeypatch):
    """Not current in `get_perspective`, not a graph edge — but found in FTS as
    a current `done` hit, and cited by its episode as current."""
    import importlib.util
    import sys
    from datetime import date

    from _synthetic_bank import _bank

    from api.services import bank_index, graph_builder, markdown_parser, progress, provenance, search_index
    from api.services import search_service
    from api.services.claims import parse_claims

    memory = _bank(tmp_path)
    markdown_parser.write(memory / "episodes" / f"{EP}.md",
                          {"id": EP, "timestamp": "2026-09-23T16:04:00+00:00", "processed": True},
                          "user: Hana Example sent me the calibration guide.\nassistant: ok")
    r = progress.record_happening(memory, subject="alpha-project", text="Bob received the calibration guide",
                                  status="done", when="2026-09-22", evidence=[{"episode": EP,
                                  "quote": "Hana Example sent me the calibration guide"}], observer="agent",
                                  origin="mcp", authored_by="claude-code", today=date(2026, 9, 23),
                                  tz_name="Europe/Madrid")
    claim = next(c for c in parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)
                 if c.id == r["claim_id"])
    assert claim.valid_to == claim.valid_from == "2026-09-22"

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    spec = importlib.util.spec_from_file_location("cicada_mcp_server",
                                                  Path(__file__).resolve().parents[2] / "mcp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server"] = server
    spec.loader.exec_module(server)
    assert "calibration" not in server.handle_get_perspective("alpha-project")

    assert graph_builder._claim_edge_row(claim, "alpha-project") is None

    bank_index.invalidate()
    search_index.ensure_fresh(memory, wait=True, max_age_s=0)
    resp = search_service.search(memory, "calibration", kinds=("claim",), mode="prefix")
    hit = next(h for h in resp.results if h.id == claim.id)
    assert hit.valid_to is None and hit.superseded_by is None
    assert (hit.event_status, hit.event_day) == ("done", "2026-09-22")

    cites = provenance.episode_citations(memory, EP)
    row = next(c for c in cites.citations if c.claim_id == claim.id)
    assert row.current is True and (row.event_status, row.event_day) == ("done", "2026-09-22")


def test_expiry_never_closes_a_milestone_by_its_target(tmp_path):
    from datetime import date

    from api.services import claim_expiry, markdown_parser
    from api.services.claims import parse_claims, write_claims

    (tmp_path / "entities").mkdir()
    page = tmp_path / "entities" / "alpha-project.md"
    ms = _ev("m1", predicate="milestone", status="planned", text="First grasp", obj="first-grasp",
             day="2026-08-01", target="2026-09-01")
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project"}, write_claims("A page.", [ms]))
    report = claim_expiry.expire(tmp_path, date(2026, 9, 23))
    assert report.claims == []
    assert parse_claims(markdown_parser.parse(page).body)[0].valid_to is None
