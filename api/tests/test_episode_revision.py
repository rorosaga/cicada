"""G104 (owner 2026-11-03): `episode_revision` — the diff, the version git holds, re-anchoring and what closes."""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

from api.services import episode_revision as er, evidence, markdown_parser
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, is_record

EP = "ep_2026-11-03_001"


def _rev(prior: str, body: str, **episode) -> er.Revision:
    rev = er.build({"id": EP, "content": body, **episode}, prior)
    assert rev is not None
    return rev


def _claim(cid: str, text: str, quote: str, obj: str | None = None, **kw) -> Claim:
    ev = evidence.verify(None, EP, quote, text=text)
    assert ev.is_span()
    return Claim(id=cid, text=quote, subject="alpha", predicate=kw.pop("predicate", "says"), object=obj or quote,
                 evidence=[ev], source_episodes=[EP], valid_from="2026-11-03", **kw)


PRIOR = "user: notes\nthe review is on Friday.\nwe use tokio.\nwe target Linux only."


# --------------------------------------------------------------------------- the diff


def test_whitespace_only_is_a_noop_with_no_window():
    rev = _rev("user: a b.\nc d.", "user: a  b.\n\nc d.  ")
    assert rev.noop and rev.windows == () and rev.changed == () and rev.removed == ()


def test_the_same_text_is_no_revision():
    assert er.build({"id": EP, "content": PRIOR}, PRIOR) is None


def test_a_changed_line_is_read_with_its_context_and_a_removal_reads_nothing():
    lines = [f"user: line {i} says something." for i in range(400)]
    body = "\n".join(lines[:300] + ["user: a new line."] + lines[300:])
    rev = _rev("\n".join(lines), body)
    (window,) = rev.windows
    at = body.index("user: a new line.")
    seen = body[window[0]:window[1]]
    assert at - window[0] >= er.CONTEXT_CHARS and at - window[0] < er.CONTEXT_CHARS + 40
    assert body[at:window[1]].count("\n") == er.CONTEXT_LINES + 1 and len(seen) < len(body) / 2
    gone = _rev("\n".join(lines), "\n".join(lines[:5] + lines[6:]))
    assert gone.windows == () and len(gone.removed) == 1 and not gone.noop


def test_a_rewrite_reads_the_whole_body():
    rev = _rev("user: one.\nuser: two.", "user: three.\nuser: four.")
    assert rev.windows == ((0, len(rev.body)),)


# --------------------------------------------------------------------------- re-anchoring and what closes


def test_spans_move_and_only_the_removed_lines_claim_is_marked():
    body = "user: notes\n\nthe review is on Thursday.\nwe  use tokio."
    rev = _rev(PRIOR, body)
    review = _claim("c1", PRIOR, "the review is on Friday")
    tokio = _claim("c2", PRIOR, "we use tokio")
    linux = _claim("c3", PRIOR, "we target Linux only")
    plan = er.reanchor({"alpha": [review, tokio, linux]}, {EP: rev})
    assert set(plan.revised_out) == {"c1", "c3"} and plan.reanchored == 1 and plan.stale == 2
    (ev,) = tokio.evidence
    assert body[ev.start:ev.end] == "we  use tokio" and ev.hash == rev.hash   # the whitespace rung, never fuzzy


def test_what_is_never_closed_by_a_revision():
    body = "user: notes\nthe review is on Thursday."
    rev = _rev("user: notes\nthe review is on Friday.", body)
    prior = rev.prior
    other = _claim("other", prior, "the review is on Friday")
    other.source_episodes.append("ep_2026-11-02_001")            # another conversation says it too
    human = _claim("human", prior, "the review is on Friday", source_trust="user_stated", origin="manual_edit")
    agent = _claim("agent", prior, "the review is on Friday", recorded_ts="2026-11-03T10:00:00Z")
    older = _claim("older", prior, "the review is on Friday")
    older.evidence[0].hash = "0" * 12                               # minted on a body this diff does not know
    closed = _claim("closed", prior, "the review is on Friday", valid_to="2026-11-03")
    plan = er.reanchor({"alpha": [other, human, agent, older, closed]}, {EP: rev})
    assert plan.revised_out == {}


def test_a_transcripts_removals_close_nothing():
    rev = _rev("user: one thing.\nuser: two things.", "user: one thing.", capture_kind="transcript")
    claim = _claim("c", rev.prior, "two things")
    assert er.reanchor({"alpha": [claim]}, {EP: rev}).revised_out == {}


# --------------------------------------------------------------------------- Stage 1's filter


def test_only_what_changed_is_kept_from_the_models_answer():
    prior = "user: we use tokio."
    body = "user: we use tokio.\nuser: we ship in December with rustfft."
    rev = _rev(prior, body)
    old = {"source": "alpha", "target": "tokio", "evidence": [evidence.verify(None, EP, "we use tokio", text=body).to_dict()]}
    new = {"source": "alpha", "target": "rustfft",
           "evidence": [evidence.verify(None, EP, "ship in December with rustfft", text=body).to_dict()]}
    unplaced = {"source": "alpha", "target": "gamma", "evidence": [evidence.reasoning(EP).to_dict()]}
    ents = [{"name": "tokio"}, {"name": "rustfft"}, {"name": "alpha"}, {"name": "gamma"}, {"name": "Beta"}]
    kept_e, kept_r, kept_v, left = er.keep_changed(rev, ents, [old, new, unplaced], [])
    assert kept_r == [new, unplaced] and [e["name"] for e in kept_e] == ["rustfft", "alpha", "gamma"] and left == 3


# --------------------------------------------------------------------------- Stage 3


def _settings():
    return SimpleNamespace(memory_path=None, litellm_model="fake", archive_threshold=0.2, decay_nudge_threshold=0.4)


def _value(cid: str, text: str, quote: str, value: str, ep: str = EP) -> Claim:
    ev = evidence.verify(None, ep, quote, text=text)
    return Claim(id=cid, text=quote, subject="alpha", predicate="value-of-review-day", object=value,
                 object_kind="literal", evidence=[ev], source_episodes=[ep], valid_from="2026-11-03",
                 recorded_at="2026-11-03", decayed_through="2026-11-03")


def test_the_same_source_revising_itself_supersedes_without_a_question():
    body = "user: the review is on Thursday."
    rev = _rev("user: the review is on Friday.", body)
    old = _value("old", rev.prior, "the review is on Friday", "Friday")
    pages = {"alpha": [old]}
    plan = er.reanchor(pages, {EP: rev})
    new = _value("new", body, "the review is on Thursday", "Thursday")
    out, nudges, audit = reconcile_stage3([new], pages, _settings(), now_date="2026-11-04", decay=False,
                                          revised=plan.revised_out)
    assert not nudges and old.superseded_by == "new" and old.valid_to == "2026-11-03"
    assert {"action": "revised", "closed": "old", "by": "new"} in audit
    assert er.settle(out, plan, {EP: rev}, "2026-11-04", audit) == 0


def test_a_later_conversation_saying_otherwise_is_still_a_question():
    old = _value("old", "user: the review is on Friday.", "the review is on Friday", "Friday")
    later = "ep_2026-11-03_002"
    new = _value("new", "user: the review is on Thursday.", "the review is on Thursday", "Thursday", ep=later)
    _, nudges, _ = reconcile_stage3([new], {"alpha": [old]}, _settings(), now_date="2026-11-04", decay=False,
                                    revised={"old": EP})
    assert old.valid_to is None and len(nudges) == 1


def test_a_removed_claim_is_withdrawn_by_a_record_and_a_restated_one_kept():
    body = "user: the review is on Friday, as planned."
    rev = _rev("user: the review is on Friday.\nwe target Linux only.", body)
    review = _claim("review", rev.prior, "the review is on Friday")
    linux = _claim("linux", rev.prior, "we target Linux only")
    pages = {"alpha": [review, linux]}
    plan = er.reanchor(pages, {EP: rev})
    assert set(plan.revised_out) == {"linux"}   # "the review is on Friday" is still there, in the replacing line
    audit: list = []
    assert er.settle(pages, plan, {EP: rev}, "2026-11-04", audit) == 1
    assert linux.valid_to == "2026-11-04" and linux.superseded_by.startswith("clm_retract_")
    (record,) = [c for c in pages["alpha"] if is_record(c)]
    assert record.object == "linux" and record.evidence[0].hash == rev.hash and record.authored_by == er.AUTHOR


def _restated(evidence_list, ep=EP, cid="linux", quote="we target Linux only") -> Claim:
    """What Stage 1 emits when a conversation says the claim again: same slot and object, its own evidence."""
    return Claim(id=cid, text=quote, subject="alpha", predicate="says", object=quote, evidence=evidence_list,
                 source_episodes=[ep], valid_from="2026-11-03")


def _through_stage3(pages, plan, rev, incoming):
    out, nudges, audit = reconcile_stage3(incoming, pages, _settings(), now_date="2026-11-04", decay=False,
                                          revised=plan.revised_out)
    return out, nudges, audit, er.settle(out, plan, {EP: rev}, "2026-11-04", audit)


def test_a_marked_claim_the_revision_restates_keeps_only_its_new_span():
    rev = _rev("user: we target Linux only.", "user: Linux only is the target.")
    claim = _claim("linux", rev.prior, "we target Linux only")
    pages = {"alpha": [claim]}
    plan = er.reanchor(pages, {EP: rev})
    assert plan.revised_out == {"linux": EP}
    out, nudges, audit, withdrawn = _through_stage3(
        pages, plan, rev, [_restated([evidence.verify(None, EP, "Linux only", text=rev.body)])])
    assert withdrawn == 0 and not nudges and claim.valid_to is None
    assert [e.hash for e in claim.evidence] == [rev.hash] and not any(is_record(c) for c in out["alpha"])


def test_a_restatement_whose_quote_does_not_locate_still_keeps_the_claim():
    """Provenance never blocks memory: the revision says it again, the quote is unlocatable (`reasoning`), and Stage 3's
    reinforce drops a reasoning entry for a conversation the claim already cites (R8) — the claim stays open."""
    rev = _rev("user: notes\nwe target Linux only.", "user: notes\nLinux is the only platform we ship for.")
    claim = _claim("linux", rev.prior, "we target Linux only")
    pages = {"alpha": [claim]}
    plan = er.reanchor(pages, {EP: rev})
    assert plan.revised_out == {"linux": EP}
    out, _, audit, withdrawn = _through_stage3(pages, plan, rev, [_restated([evidence.reasoning(EP, hash=rev.hash)])])
    assert withdrawn == 0 and claim.valid_to is None and claim.superseded_by is None
    assert not any(is_record(c) for c in out["alpha"])
    assert {"action": "revision_restated", "kept": "linux"} in audit


def test_another_conversation_in_the_same_batch_keeps_the_claim_open():
    """The revision removed the line, but another conversation read in the same batch says it: not the source's word
    alone any more, so nothing is withdrawn (an unsent message splitting a Messages sitting does this)."""
    rev = _rev("user: the review is on Friday.\nwe target Linux only.", "user: the review is on Friday.")
    claim = _claim("linux", rev.prior, "we target Linux only")
    pages = {"alpha": [claim]}
    plan = er.reanchor(pages, {EP: rev})
    assert plan.revised_out == {"linux": EP}
    other = "ep_2026-11-03_002"
    said = evidence.verify(None, other, "we target Linux only", text="user: we target Linux only.")
    out, _, _, withdrawn = _through_stage3(pages, plan, rev, [_restated([said], ep=other, cid="linux2")])
    assert withdrawn == 0 and claim.valid_to is None and other in claim.source_episodes
    assert [c.id for c in out["alpha"] if c.valid_to is None] == ["linux"]


# --------------------------------------------------------------------------- the version git holds


def _git(memory, *args):
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args], cwd=memory, check=True,
                   capture_output=True)


def _episode(memory, body, **fm):
    path = memory / "episodes" / f"{EP}.md"
    markdown_parser.write(path, {"id": EP, "source": "note", **fm}, body)
    return {"id": EP, "content": body, "filepath": path}


def test_the_version_sleep_read_comes_from_git(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    _episode(memory, "user: first.", processed=True, processed_by="sleep")
    assert er.prior_bodies(memory, [{"id": EP, "content": "x", "filepath": memory / "episodes" / f"{EP}.md"}]) == {}
    _git(memory, "init", "-q")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "Sleep")
    ep = _episode(memory, "user: second.", processed=False)
    assert er.prior_bodies(memory, [ep]) == {EP: "user: first."}
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "capture")      # a published capture log: HEAD holds the unread edit
    assert er.prior_bodies(memory, [ep]) == {EP: "user: first."}
    revisions = er.attach(memory, [ep])
    assert ep[er.KEY] is revisions[EP] and revisions[EP].prior == "user: first."


def test_an_episode_edited_down_to_nothing_is_still_a_revision(tmp_path):
    """G104 slice 3: a section a note lost is revised to an empty body. ``attach`` used to skip an episode with no
    content, so the words it held were never settled as removed; its ``revised`` record now makes it a revision."""
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    _episode(memory, "user: the review is on Friday.\nuser: we use tokio.", processed=True, processed_by="sleep",
             content_hash="h1")
    _git(memory, "init", "-q")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "Sleep")
    revised = {"count": 1, "consolidated_hash": "h1"}
    ep = {**_episode(memory, "", processed=False, content_hash="h2", revised=revised), "revised": revised}
    (rev,) = er.attach(memory, [ep]).values()
    assert rev.body == "" and rev.prior.startswith("user: the review") and rev.windows == () and not rev.noop
    assert rev.removed and rev.closes and ep[er.KEY] is rev
    # An episode that was always empty, or never edited, is no revision.
    assert er.attach(memory, [{"id": EP, "content": "", "filepath": ep["filepath"]}]) == {}


def test_the_stagers_record_names_the_version_to_diff_against(tmp_path):
    """G95's ``revised.consolidated_hash`` picks the version, even one an agent consolidated, and even past a newer
    commit of a version nobody consolidated."""
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    _episode(memory, "user: first.", processed=True, processed_by="claude-code", content_hash="h1")
    _git(memory, "init", "-q")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "agent marked it read")
    _episode(memory, "user: second.", processed=True, processed_by="parser", content_hash="h2",
             revised={"count": 1, "consolidated_hash": "h1"})
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "parsed edit")
    revised = {"count": 2, "consolidated_hash": "h1"}
    ep = {**_episode(memory, "user: third.", processed=False, content_hash="h3", revised=revised), "revised": revised}
    assert er.prior_bodies(memory, [ep]) == {EP: "user: first."}
    assert er.prior_bodies(memory, [{**ep, "revised": {"count": 2, "consolidated_hash": "gone"}}]) == {}


def test_retiring_refreshes_the_record_and_never_starts_one():
    fm = {"content_hash": "h3", "revised": {"count": 2, "at": "x", "consolidated_hash": "h1"}}
    er.mark_consolidated(fm)
    assert fm["revised"] == {"count": 2, "at": "x", "consolidated_hash": "h3"}
    fresh = {"content_hash": "h1"}
    er.mark_consolidated(fresh)
    assert "revised" not in fresh


def test_a_version_sleep_never_read_is_not_a_prior(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    _episode(memory, "user: first.", processed=True, processed_by="parser")
    _git(memory, "init", "-q")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "import")
    ep = _episode(memory, "user: second.", processed=False)
    assert er.prior_bodies(memory, [ep]) == {}


# --------------------------------------------------------------------------- a date said on another line (G104 slice 3)


def test_says_day_reads_a_day_beside_its_month_in_any_of_the_languages():
    yes = [("El 12 de diciembre, cuando termine", "2026-12-12"), ("on December 12th we leave", "2026-12-12"),
           ("le 3 août", "2026-08-03"), ("am 3. August", "2026-08-03"), ("12/12", "2026-12-12"),
           ("starts 2026-12-12 sharp", "2026-12-12"), ("5 Dec", "2026-12-05")]
    no = [("El 5 de diciembre", "2026-12-12"), ("the 12th of nothing", "2026-12-12"), ("12 items in 2026", "2026-12-12"),
          ("next Friday", "2026-12-12"), ("12 de enero", "2026-12-12"), ("", "2026-12-12"), ("12 dec", None)]
    for text, day in yes:
        assert er.says_day(text, day), (text, day)
    for text, day in no:
        assert not er.says_day(text, day), (text, day)


def _dated_rev(prior, body):
    ep = {"id": "ep_2026-11-01_001", "content": body}
    return er.build(ep, prior)


def test_keep_changed_keeps_a_dated_relationship_only_when_the_changed_lines_say_its_day():
    prior = "user: Ana se muda a Lima.\nuser: El 5 de diciembre se va."
    body = "user: Ana se muda a Lima.\nuser: El 12 de diciembre se va."
    rev = _dated_rev(prior, body)
    span = {"episode": rev.episode_id, "start": 0, "end": 22, "kind": "user", "hash": rev.hash}

    def rel(**kw):
        return {"source": "Ana", "target": "Lima", "label": "moves to", "evidence": [span], **kw}

    ents = [{"name": "Ana"}, {"name": "Lima"}]
    _e, kept, _v, left = er.keep_changed(rev, ents, [rel(starts="2026-12-12")], [])
    assert len(kept) == 1 and left == 2          # the relationship is new; neither name is said in the changed line
    _e, kept, _v, left = er.keep_changed(rev, ents, [rel(starts="2026-12-05")], [])   # the first read's date, gone
    assert kept == [] and left == 3
    _e, kept, _v, _l = er.keep_changed(rev, ents, [rel(starts="2026-12-19")], [])
    assert kept == []
    _e, kept, _v, _l = er.keep_changed(rev, ents, [rel()], [])
    assert kept == []                              # no date: the first read's, as before


# --------------------------------------------------------------------------- a re-read's names are the first read's (G104 slice 3)


def _first_read_bank(tmp_path, *pages, held=()):
    from api.services import pending_store

    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    for slug, name, aliases, eps in pages:
        markdown_parser.write(memory / "entities" / f"{slug}.md",
                              {"name": name, "type": "person", "aliases": aliases, "source_episodes": eps}, "## Summary\nx\n")
    for name in held:
        pending_store.upsert(memory, pending_store.PendingEntity(
            name=name, type="person", description="", source_episode=EP, confidence=0.5, tags=[], history_entries=[]))
    return memory


def _reread():
    ents = [{"name": "Lucía (sister)", "aliases": []}, {"name": "Valencia"}]
    rels = [{"source": "lucia  (sister)", "target": "Valencia", "label": "is moving to"}]
    vals = [{"entity": "LUCÍA", "attribute": "move date", "value": "12 December"}]
    return ents, rels, vals


def test_a_name_with_only_a_note_added_is_the_entity_the_first_read_of_the_conversation_made(tmp_path):
    memory = _first_read_bank(tmp_path, ("lucía", "Lucía", [], [EP]), ("valencia", "Valencia", [], [EP]))
    ents, rels, vals = _reread()
    rev = _rev("user: a.", "user: b.")
    assert er.canonical_names(memory, rev, ents, rels, vals) == 3
    assert [e["name"] for e in ents] == ["Lucía", "Valencia"]
    assert (rels[0]["source"], vals[0]["entity"]) == ("Lucía", "Lucía")          # accents and case folded; the page's own name


def test_a_held_name_without_a_page_counts_as_the_first_reads(tmp_path):
    memory = _first_read_bank(tmp_path, held=["Lucía"])
    ents, rels, vals = _reread()
    er.canonical_names(memory, _rev("user: a.", "user: b."), ents, rels, vals)
    assert ents[0]["name"] == "Lucía"


def test_an_alias_of_a_first_read_page_names_it_and_the_rewrite_is_its_own_name(tmp_path):
    memory = _first_read_bank(tmp_path, ("lucia-perez", "Lucía Pérez", ["Lucía"], [EP]))
    ents, rels, vals = _reread()
    er.canonical_names(memory, _rev("user: a.", "user: b."), ents, rels, vals)
    assert ents[0]["name"] == "Lucía Pérez"


def test_two_first_read_entities_sharing_a_bare_form_are_never_guessed_between(tmp_path):
    memory = _first_read_bank(tmp_path, ("lucia-a", "Lucía", [], [EP]), ("lucia-b", "Lucia (cousin)", [], [EP]))
    ents, rels, vals = _reread()
    assert er.canonical_names(memory, _rev("user: a.", "user: b."), ents, rels, vals) == 0
    assert ents[0]["name"] == "Lucía (sister)" and vals[0]["entity"] == "LUCÍA"


def test_a_page_another_conversation_made_is_not_the_first_reads(tmp_path):
    memory = _first_read_bank(tmp_path, ("lucía", "Lucía", [], ["ep_2026-11-04_001"]))
    ents, rels, vals = _reread()
    assert er.canonical_names(memory, _rev("user: a.", "user: b."), ents, rels, vals) == 0
    assert ents[0]["name"] == "Lucía (sister)"
