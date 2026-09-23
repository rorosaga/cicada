"""G61 phase 2 S2 — which inbox questions a source could answer (spec §4, plan
R-AC34…R-AC39). Pure: no bank, no network, no model. The table includes shapes
like the on-disk demo's `uses` item (informational), an unseen predicate
(`unknown` → needs a person's source) and a decay item (never), built here —
the tests never read a bank."""
from __future__ import annotations

import pytest

from api.services import source_check
from api.services.claims import Claim

VOCAB = source_check.vocab_for(None)
TODAY = "2026-09-23"
PAGE = "https://example.com/company-b/team"
LINKEDIN = "https://www.linkedin.com/in/bob-example"


def _conflict(predicate="works-at", *, claim_id="clm_b", b_seen="2026-09-01", **extra) -> dict:
    fm = {"kind": "conflict", "entity_id": "bob-example", "predicate": predicate, "claim_id": claim_id,
          "options": [{"key": "a", "label": "company-a", "claim_id": "clm_a", "last_referenced": "2026-05-01"},
                      {"key": "b", "label": "company-b", "claim_id": "clm_b", "last_referenced": b_seen},
                      {"key": "both", "label": "Both are true (different contexts)"}]}
    fm.update(extra)
    return fm


def _src(ref=PAGE, *, predicate="works-at", added_by="user", **extra) -> dict:
    s = {"ref": ref, "kind": "url" if ref.startswith("http") else "note", "added_by": added_by}
    if predicate:
        s["predicate"] = predicate
    s.update(extra)
    return s


def _check(fm, *, sources=(), owner=False, claims=None, subject=True):
    subject_fm = None
    if subject:
        subject_fm = {"name": "Bob Example", "type": "person", "sources": list(sources)}
        if owner:
            subject_fm["owner"] = True
    return source_check.checkability(fm, options=fm.get("options") or [], option_claims=claims or {},
                                     subject_fm=subject_fm, vocab=VOCAB, today=TODAY)


def _human(key="a") -> dict:
    return {key: Claim(id="clm_a", text="x", subject="bob-example", predicate="works-at", object="company-a",
                       source_trust="user_stated", origin="clarification")}


@pytest.mark.parametrize("kind", ["decay", "normalization", "removal"])
def test_what_is_not_a_question_of_fact_is_never_checked(kind):
    c = _check({"kind": kind, "entity_id": "bob-example"}, sources=[_src(access="public")])
    assert (c.state, c.reason, c.targets, c.rungs, c.settle_eligible) == ("never", "not_a_question", (), (), False)


def test_an_unknown_kind_is_never_checked():
    assert (_check({"kind": "mystery"}).state, _check({"kind": "mystery"}).reason) == ("never", "unknown_kind")


def test_a_merge_suggestion_is_inform_only_and_never_marked():
    c = _check({"kind": "merge_suggestion", "entity_id": "bob-example"}, sources=[_src()])
    assert (c.state, c.reason, c.targets) == ("inform_only", "merge_suggestion", ())


def test_a_multi_valued_conflict_is_informational():
    c = _check(_conflict("uses"), sources=[_src(predicate="uses", access="public")])
    assert (c.state, c.reason) == ("never", "informational")


def test_what_someone_prefers_is_never_checked():
    div = {"kind": "divergence", "entity_id": "bob-example", "predicate": "considering", "options": []}
    c = _check(div, sources=[_src(predicate="considering", access="public")])
    assert (c.state, c.reason, c.locus) == ("never", "person_locus", "person")
    # `considering` is also seed multi_valued, so its conflicts stop one row earlier.
    assert _check(_conflict("considering")).reason == "informational"


def test_an_unseen_predicate_needs_a_source_the_person_attached():
    fm = _conflict("wears-hat-of")
    assert (_check(fm).state, _check(fm).reason) == ("needs_source", "no_source")
    agent = _check(fm, sources=[_src(predicate="wears-hat-of", added_by="claude-code", access="public")])
    assert (agent.state, agent.reason, agent.locus) == ("needs_source", "unknown_locus", "unknown")
    person = _check(fm, sources=[_src(predicate="wears-hat-of", access="public")])
    assert (person.state, person.reason, person.settle_eligible) == ("checkable", "settle_eligible", True)


def test_the_worked_example_is_settle_eligible():
    """Spec §4.4: two agent options on works-at, a person-added public page."""
    c = _check(_conflict(), sources=[_src(access="public")])
    assert (c.state, c.reason, c.locus, c.rungs, c.settle_eligible) == (
        "checkable", "settle_eligible", "world", ("fetch", "agent"), True)
    t = c.targets[0]
    assert (t.ref, t.access, t.added_by, t.predicate_matched, t.own_session_only) == (PAGE, "public", "user", True, False)


@pytest.mark.parametrize("kwargs, reason", [
    ({"sources": [_src()]}, "access_unverified"),
    ({"sources": [_src(access="public")], "claims": _human()}, "human_option"),
    ({"sources": [_src(access="public")], "owner": True}, "owner_subject"),
    ({"sources": [_src(access="signed_in")]}, "no_settle_grade_source"),
    ({"sources": [_src(added_by="claude-code", access="public")]}, "no_settle_grade_source"),
    ({"sources": [_src(predicate="located-in", access="public")]}, "no_settle_grade_source"),
])
def test_each_clamp_alone_turns_settling_off(kwargs, reason):
    c = _check(_conflict(), **kwargs)
    assert (c.state, c.reason, c.settle_eligible) == ("checkable", reason, False)


def test_recent_speech_and_an_artifact_and_the_entity_path_recommend_only():
    recent = _check(_conflict(b_seen="2026-09-20"), sources=[_src(access="public")])
    artifact = _check(_conflict("runs-on"), sources=[_src(predicate="runs-on", access="public")])
    entity = _check(_conflict("description", claim_id=None), sources=[_src(predicate=None, access="public")])
    assert [(x.state, x.reason) for x in (recent, artifact, entity)] == [
        ("checkable", "recent_speech"), ("checkable", "artifact_locus"), ("checkable", "entity_path")]


def test_an_accepted_agent_source_is_settle_grade():
    c = _check(_conflict(), sources=[_src(added_by="claude-code", access="public", accepted=True)])
    assert (c.reason, c.settle_eligible) == ("settle_eligible", True)


def test_only_i_know_silences_the_fact_and_is_never_a_target():
    only_me = {"ref": "Only I know", "kind": "note", "predicate": "works-at", "added_by": "user", "only_me": True}
    c = _check(_conflict(), sources=[_src(access="public"), only_me])
    assert (c.state, c.reason, c.targets) == ("inform_only", "only_me", ())
    agents = dict(only_me, added_by="claude-code")
    assert _check(_conflict(), sources=[_src(access="public"), agents]).state == "checkable"


def test_a_refused_host_is_an_own_session_agent_rung_only():
    """D-AC2: a LinkedIn-class page gets an agent in the person's own open
    session, never Cicada's fetch, and never settles."""
    c = _check(_conflict(), sources=[_src(LINKEDIN)])
    t = c.targets[0]
    assert (c.state, c.reason) == ("inform_only", "refused_host_only")
    assert (t.rungs, t.own_session_only, t.access) == (("agent",), True, "signed_in")
    mixed = _check(_conflict(), sources=[_src(LINKEDIN), _src(access="public")])
    assert (mixed.state, mixed.reason, [t.own_session_only for t in mixed.targets]) == (
        "checkable", "settle_eligible", [True, False])


@pytest.mark.parametrize("source, rungs, access", [
    ({"ref": "Calendar", "kind": "app"}, ("agent_local",), "signed_in"),
    ({"ref": "~/src/alpha-project", "kind": "repo"}, ("agent_local",), "local"),
    ({"ref": "~/Documents/cv.pdf", "kind": "path"}, ("agent_local",), "local"),
    ({"ref": "ask me — I announce job changes", "kind": "note"}, ("agent",), "unknown"),
    ({"ref": PAGE, "kind": "url", "access": "signed_in"}, ("agent",), "signed_in"),
    ({"ref": PAGE, "kind": "url"}, ("fetch", "agent"), "unknown"),
])
def test_the_rungs_follow_the_kind_and_the_access(source, rungs, access):
    c = _check(_conflict(), sources=[dict(source, predicate="works-at", added_by="user")])
    assert (c.targets[0].rungs, c.targets[0].access, c.rungs) == (rungs, access, rungs)


def test_divergence_and_clarification_are_inform_only():
    div = {"kind": "divergence", "entity_id": "bob-example", "predicate": "works-at", "options": []}
    assert (_check(div, sources=[_src()]).state, _check(div, sources=[_src()]).reason) == ("inform_only", "divergence")
    assert _check(div).state == "needs_source"
    clar = {"kind": "clarification", "entity_id": "sam-example", "options": []}
    assert (_check(clar, subject=False).state, _check(clar, subject=False).reason) == ("needs_source", "no_source")
    assert _check(clar, sources=[_src(predicate=None)]).reason == "clarification"


def test_the_owners_page_counts_only_the_persons_sources():
    c = _check(_conflict(), sources=[_src(added_by="claude-code", access="public")], owner=True)
    assert (c.state, c.reason) == ("needs_source", "owner_subject")


def test_targets_rank_the_person_then_cicada_then_agents_and_stop_at_three():
    c = _check(_conflict(), sources=[
        _src("https://example.com/agent", added_by="claude-code"), _src("https://example.com/cicada", added_by="cicada"),
        _src("https://example.com/person"), _src("https://example.com/agent-2", added_by="gpt-5.4-mini")])
    assert [t.ref for t in c.targets] == ["https://example.com/person", "https://example.com/cicada",
                                          "https://example.com/agent"]


def test_the_wire_shape():
    wire = _check(_conflict(), sources=[_src(access="public")]).to_wire()
    assert set(wire) == {"state", "reason", "locus", "targets", "rungs", "settle_eligible"}
    assert set(wire["targets"][0]) == {"ref", "kind", "access", "added_by", "predicate_matched", "accepted",
                                       "rungs", "own_session_only"}
    for state, reasons in source_check.REASONS.items():
        assert state in source_check.STATES and reasons
