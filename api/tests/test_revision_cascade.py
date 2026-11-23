"""G104 slice 3 (T3): a correction reaches what it touched — the cascade's rules, on scratch banks.

``revision_cascade.run`` over hand-built revisions: pages only the removed text supported are archived (undoable), a
kept page lists what it lost and why it stays, aliases and held names follow, and the open questions it would withdraw
are returned (never written) and settled by ``inbox_tend``'s ``source_corrected`` rule. Synthetic names only; git is
real, no engine is ever opened."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import (bank_index, conflict_resolver, episode_revision, inbox_tend, markdown_parser, pending_store,
                          predicates, revision_cascade)
from api.services.claims import Claim, Evidence, parse_claims, write_claims

E1, E2, E3 = "ep_2026-11-01_001", "ep_2026-11-02_001", "ep_2026-11-03_001"
PRIOR = "user: Notes.\nZed Unknown (zu) demoed the Gamma Board.\nalpha tasks continue."
BODY = "user: Notes.\nalpha tasks continue."


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory: Path, msg: str = "seed", author: str | None = None, touch: str | None = None) -> None:
    """Commit the tree; ``touch``: first move that page's ``version``, so the commit is one ON the page."""
    if touch:
        path = memory / "entities" / f"{touch}.md"
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, {**parsed.frontmatter, "version": int(parsed.frontmatter.get("version", 1)) + 1},
                              parsed.body)
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", msg + (f"\n\nCicada-Author: {author}" if author else ""), "--allow-empty")
    bank_index.invalidate()


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90
        self.llm_mode = "byok"


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _episode(m, E1, BODY)
    _commit(m)
    return m


def _episode(memory: Path, eid: str, body: str, **fm) -> None:
    meta = {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": True, "source": "note"}
    meta.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", meta, body)


def _claim(cid: str, subject: str, episode: str, *, closed_by: str | None = None, **kw) -> Claim:
    c = Claim(id=cid, text="x", subject=subject, predicate="value-of-role", object="demoer", valid_from="2026-11-01",
              recorded_at="2026-11-01", evidence=[Evidence(episode=episode, kind="user")],
              source_episodes=[episode], **kw)
    if closed_by:
        c.valid_to, c.superseded_by = "2026-11-05", closed_by
    return c


def _record(cid: str, target: Claim, episode: str) -> Claim:
    return Claim(id=cid, text=episode_revision.WITHDRAW_REASON, subject=target.subject, predicate="retracts",
                 object=target.id, valid_from="2026-11-05", valid_to="2026-11-05", supersedes=target.id,
                 recorded_at="2026-11-05", authored_by=episode_revision.AUTHOR,
                 evidence=[Evidence(episode=episode, start=-1, end=-1, kind="reasoning")])


def _page(memory: Path, pid: str, claims: list[Claim] | None = None, **fm) -> None:
    base = {"name": pid.replace("-", " ").title(), "type": "person", "status": "active", "confidence": 0.8,
            "created": "2026-11-01", "last_referenced": "2026-11-01", "source_episodes": [E1], "tags": [],
            "related": [], "version": 1}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{pid}.md", base,
                          write_claims("## Summary\nA person.\n", claims or []))


def _lost_page(memory: Path, pid: str = "zed-unknown", *, claim_id: str = "clm_a", **fm):
    """A page whose one claim the revision of E1 withdrew; returns ``revised_out``."""
    c = _claim(claim_id, pid, E1)
    rec = _record(f"clm_r_{claim_id}", c, E1)
    c.valid_to, c.superseded_by = "2026-11-05", rec.id
    _page(memory, pid, [c, rec], **fm)
    return {claim_id: E1}


def _rev(prior: str = PRIOR, body: str = BODY, eid: str = E1):
    rev = episode_revision.build({"id": eid, "content": body}, prior)
    assert rev is not None
    return {eid: rev}


def _fm(memory: Path, pid: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{pid}.md").frontmatter


def _run(memory: Path, revisions=None, revised_out=None, **kw):
    bank_index.invalidate(memory)
    return revision_cascade.run(memory, revisions or _rev(), revised_out=revised_out or {}, today="2026-11-05", **kw)


# --------------------------------------------------------------------------- pages


def test_a_page_only_the_removed_text_supported_is_archived_and_restoring_puts_it_back(memory):
    out = _lost_page(memory, confidence=0.7)
    report = _run(memory, revised_out=out)
    assert [r["page"] for r in report.pages_archived] == ["zed-unknown"]
    assert report.pages_archived[0] == {"page": "zed-unknown", "episode": E1, "claims": ["clm_a"]}
    fm = _fm(memory, "zed-unknown")
    assert fm["status"] == "archived" and fm["removed_at"]
    assert fm["archived_by"] == {"reason": "revision", "episode": E1, "day": "2026-11-05", "prior_status": "active",
                                 "prior_confidence": 0.7}
    assert report.paths == ["entities/zed-unknown.md"]
    # The claims stay (closed, never deleted).
    assert len(parse_claims(markdown_parser.parse(memory / "entities" / "zed-unknown.md").body)) == 2

    result = revision_cascade.restore(memory, "zed-unknown")
    fm = _fm(memory, "zed-unknown")
    assert (fm["status"], fm["confidence"]) == ("active", 0.7) and "archived_by" not in fm and "removed_at" not in fm
    assert result["paths"] == ["entities/zed-unknown.md"]


def test_restore_refuses_a_page_decay_archived_or_one_that_is_not_there(memory):
    _page(memory, "decayed", status="archived", confidence=0.1)
    with pytest.raises(revision_cascade.Refused) as exc:
        revision_cascade.restore(memory, "decayed")
    assert exc.value.code == "not_archived"
    with pytest.raises(revision_cascade.Refused) as exc:
        revision_cascade.restore(memory, "nobody")
    assert exc.value.code == "missing"
    assert _fm(memory, "decayed")["status"] == "archived"


def test_a_later_real_mention_reopens_an_archived_page_and_drops_the_stamp(memory):
    out = _lost_page(memory, confidence=0.7)
    _run(memory, revised_out=out)
    from api.tests.test_decay_engines import _update

    conflict_resolver.apply_changes([_update("zed-unknown")], memory)
    fm = _fm(memory, "zed-unknown")
    assert fm["status"] == "active" and "archived_by" not in fm and "removed_at" not in fm


def test_another_conversation_keeps_the_page_and_the_record_lists_the_claims_it_lost(memory):
    _episode(memory, E2, "user: Zed Unknown came to lunch.")
    out = _lost_page(memory, source_episodes=[E1, E2])
    report = _run(memory, revised_out=out)
    assert report.pages_archived == []
    assert report.pages_kept == [{"page": "zed-unknown", "episode": E1, "support": "other_conversation",
                                  "claims": ["clm_a"]}]
    assert _fm(memory, "zed-unknown")["status"] == "active"


def test_a_claim_that_survived_keeps_the_page(memory):
    out = _lost_page(memory)
    path = memory / "entities" / "zed-unknown.md"
    parsed = markdown_parser.parse(path)
    kept = _claim("clm_b", "zed-unknown", E1)
    kept.predicate, kept.object = "value-of-city", "Porto"
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [*parse_claims(parsed.body), kept]))
    report = _run(memory, revised_out=out)
    assert [(r["page"], r["support"]) for r in report.pages_kept] == [("zed-unknown", "surviving_claim")]


@pytest.mark.parametrize("fm, why", [
    ({"owner": True}, "owner"),
    ({"type": "project"}, "project"),
    ({"type": "concept", "mine": {"via": "app"}}, "project"),
    ({"type": "media", "media": {"url": "https://example.invalid/a"}}, "media"),
    ({"corrections": [{"from": "a", "to": "b"}]}, "pinned"),
    ({"aliases_removed": ["zz"]}, "pinned"),
    ({"human_edited": True}, "pinned"),
    ({"sources": [{"ref": "https://example.invalid/z", "added_by": "user"}]}, "person_source"),
])
def test_the_owner_a_project_a_media_page_and_anything_pinned_are_never_archived(memory, fm, why):
    out = _lost_page(memory, **fm)
    report = _run(memory, revised_out=out)
    assert report.pages_archived == []
    assert [(r["page"], r["support"]) for r in report.pages_kept] == [("zed-unknown", why)]
    assert _fm(memory, "zed-unknown")["status"] == "active"


def test_a_page_a_person_or_an_agent_wrote_a_commit_on_is_never_archived(memory):
    out = _lost_page(memory)
    _commit(memory, "Sleep", author="gpt-5.4-mini", touch="zed-unknown")      # Sleep's own commit: no support
    _commit(memory, "a person's edit", author="user", touch="zed-unknown")
    report = _run(memory, revised_out=out)
    assert report.pages_archived == []
    assert report.pages_kept[0]["support"] == "authored_commit"


def test_a_page_a_trusted_agent_edited_is_kept_too(memory):
    out = _lost_page(memory)
    _commit(memory, "edit", author="claude-code", touch="zed-unknown")
    assert _run(memory, revised_out=out).pages_kept[0]["support"] == "authored_commit"


def test_a_page_only_sleep_wrote_is_archived_whatever_model_wrote_it(memory):
    out = _lost_page(memory)
    _commit(memory, "Sleep", author="gpt-5.4-mini", touch="zed-unknown")
    assert [r["page"] for r in _run(memory, revised_out=out).pages_archived] == ["zed-unknown"]


def test_a_conversation_still_waiting_that_names_the_page_keeps_it(memory):
    out = _lost_page(memory)
    _episode(memory, E3, "user: Zed Unknown said hello again today.", processed=False)
    report = _run(memory, revised_out=out)
    assert report.pages_archived == []
    assert report.pages_kept[0]["support"] == "waiting_conversation"


def test_a_page_listed_by_a_project_and_one_imported_are_kept(memory):
    out = _lost_page(memory)
    _page(memory, "alpha-project", type="project", entities_added=["zed-unknown"], source_episodes=[])
    assert _run(memory, revised_out=out).pages_kept[0]["support"] == "project"


def test_a_page_with_no_lost_claim_whose_name_is_still_said_is_never_a_candidate(memory):
    _page(memory, "alpha", name="Alpha")
    report = _run(memory, revisions=_rev("user: Notes.\nAlpha spoke.\nZed Unknown left.", "user: Notes.\nAlpha spoke."))
    assert report.pages_archived == [] and report.pages_kept == []


def test_a_page_new_this_batch_and_a_revision_that_removed_nothing_are_left_alone(memory):
    out = _lost_page(memory)
    assert _run(memory, revised_out=out, new_pages={"zed-unknown"}).pages_archived == []
    noop = {E1: episode_revision.build({"id": E1, "content": "user: a  b"}, "user: a b")}
    assert not _run(memory, revisions=noop, revised_out=out)
    transcript = {E1: episode_revision.build({"id": E1, "content": BODY, "capture_kind": "transcript"}, PRIOR)}
    assert not _run(memory, revisions=transcript, revised_out=out)
    assert _fm(memory, "zed-unknown")["status"] == "active"


def test_a_page_whose_name_left_the_text_with_no_claim_is_archived_only_if_it_was_in_the_read_version(memory):
    _page(memory, "zed-unknown")      # no claims
    assert [r["page"] for r in _run(memory).pages_archived] == ["zed-unknown"]
    revision_cascade.restore(memory, "zed-unknown")
    # Its name was never in the version Sleep read: the revision removed nothing of it, so it is no candidate.
    report = _run(memory, revisions=_rev("user: Notes.\nsomething else.\nalpha tasks continue.", BODY))
    assert report.pages_archived == [] and _fm(memory, "zed-unknown")["status"] == "active"


def test_a_page_the_person_restored_is_never_archived_again(memory):
    out = _lost_page(memory)
    _run(memory, revised_out=out)
    revision_cascade.restore(memory, "zed-unknown")
    _commit(memory, "restore", author="user", touch="zed-unknown")     # what the restore route commits
    assert _run(memory, revised_out=out).pages_kept[0]["support"] == "authored_commit"


# --------------------------------------------------------------------------- aliases


def _alias_bank(memory: Path, aliases=("zu",), **fm):
    """A kept page (E2 also cites it, and never says the alias) whose alias is only in E1's removed text."""
    _episode(memory, E2, "user: Zed Unknown came to lunch.")
    out = _lost_page(memory, aliases=list(aliases), source_episodes=[E1, E2], **fm)
    _commit(memory, "pages", author="gpt-5.4-mini", touch="zed-unknown")
    return out


def test_an_alias_only_the_removed_text_said_is_dropped_and_not_added_to_the_removed_list(memory):
    out = _alias_bank(memory, aliases=["zu", "zed"])
    _episode(memory, E2, "user: Zed Unknown came to lunch, zed said.")   # "zed" is also in another conversation
    report = _run(memory, revised_out=out)
    assert report.aliases_dropped == [{"page": "zed-unknown", "episode": E1, "count": 1}]
    fm = _fm(memory, "zed-unknown")
    assert fm["aliases"] == ["zed"] and "aliases_removed" not in fm


@pytest.mark.parametrize("fm", [{"corrections": [{"from": "a", "to": "b"}]}, {"aliases_kept": ["zu"]},
                                {"aliases_removed": ["q"]}, {"human_edited": True}])
def test_nothing_is_dropped_from_a_page_with_pinned_edits(memory, fm):
    out = _alias_bank(memory, **fm)
    _run(memory, revised_out=out)
    assert _fm(memory, "zed-unknown")["aliases"] == ["zu"]


def test_an_alias_another_page_bears_or_the_person_wrote_last_is_kept(memory):
    out = _alias_bank(memory)
    _page(memory, "other-zu", name="Zu", source_episodes=[E2])
    _run(memory, revised_out=out)
    assert _fm(memory, "zed-unknown")["aliases"] == ["zu"]
    (memory / "entities" / "other-zu.md").unlink()
    path = memory / "entities" / "zed-unknown.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "aliases": ["zu", "ZU"]}, parsed.body)
    _commit(memory, "alias by the person", author="user", touch="zed-unknown")
    _run(memory, revised_out=out)
    assert "zu" in _fm(memory, "zed-unknown")["aliases"]


def test_an_alias_on_a_project_page_is_never_dropped(memory):
    out = _alias_bank(memory, type="project")
    _run(memory, revised_out=out)
    assert _fm(memory, "zed-unknown")["aliases"] == ["zu"]


# --------------------------------------------------------------------------- held names


def _held(name: str, episodes: list[str], claims: list[dict] | None = None):
    pending_store.upsert(Path(_held.memory), pending_store.PendingEntity(
        name=name, type="person", description="d", source_episode=episodes[0], confidence=0.5, tags=[],
        history_entries=[], held_claims=claims or [], heard_in=[{"episode": e} for e in episodes[1:]],
        summary="kept summary", key_facts=["a fact"]))


def test_a_held_name_no_longer_in_the_text_leaves_the_conversation(memory):
    _held.memory = memory
    only = _claim("clm_h1", "zed-unknown", E1).to_dict()
    both = _claim("clm_h2", "zed-unknown", E2).to_dict()
    _held("Zed Unknown", [E1, E2], [only, both])          # heard twice: keeps the other, drops what only E1 said
    _held("Zed Alone", [E1], [_claim("clm_h3", "zed-alone", E1).to_dict()])   # only E1: removed whole
    _held("Alpha Tasks", [E1])                                                # still in the text: untouched
    prior = "user: Notes.\nZed Unknown and Zed Alone were here.\nalpha tasks continue."
    report = _run(memory, revisions=_rev(prior, BODY))
    assert report.held == {"lines_removed": 1, "episodes_left": 1, "claims_dropped": 2, "claims_withdrawn": 0}
    lines = {e.name: e for e in pending_store.load(memory)}
    assert set(lines) == {"Zed Unknown", "Alpha Tasks"}
    zed = lines["Zed Unknown"]
    assert zed.episodes() == [E2] and [d["id"] for d in zed.held_claims] == ["clm_h2"]
    assert zed.summary == "kept summary" and zed.key_facts == ["a fact"]
    assert lines["Alpha Tasks"].episodes() == [E1]
    assert pending_store.PENDING_STORE_FILE in report.paths
    assert _run(memory, held_withdrawn=3).as_dict()["counts"]["held_claims_dropped"] == 3


# --------------------------------------------------------------------------- questions


def _item(memory: Path, item_id: str, **fm) -> Path:
    base = {"status": "pending", "priority": 0.5, "created_date": "2026-11-01"}
    base.update(fm)
    path = memory / "inbox" / f"{item_id}.md"
    markdown_parser.write(path, base, "Context.")
    return path


def test_the_questions_a_correction_made_moot_are_returned_never_written(memory):
    out = _lost_page(memory)
    _item(memory, "inbox-001", kind="clarification", entity_id="zed-unknown", entity_name="Zed Unknown",
          source_episode=E1, uncertainty_type="Insufficient context to classify")
    _item(memory, "inbox-002", kind="clarification", entity_id="zed-unknown", entity_name="Zed Unknown")
    _item(memory, "inbox-003", kind="clarification", entity_id="zed-ghost", entity_name="Zed Ghost", source_episode=E1)
    before = {p.name: p.read_bytes() for p in (memory / "inbox").glob("*.md")}
    report = _run(memory, revisions=_rev("user: Notes.\nZed Unknown and Zed Ghost.\nalpha tasks continue.", BODY),
                  revised_out=out)
    assert {(q["item"], q["why"]) for q in report.questions} == {
        ("inbox-001", "page_archived"), ("inbox-002", "page_archived"), ("inbox-003", "name_gone")}
    assert report.corrected()["inbox-001"] == E1
    assert before == {p.name: p.read_bytes() for p in (memory / "inbox").glob("*.md")}   # the cascade wrote none


def test_a_name_question_with_evidence_elsewhere_stays(memory):
    _episode(memory, E2, "user: Zed Ghost ordered coffee.")
    _item(memory, "inbox-003", kind="clarification", entity_id="zed-ghost", entity_name="Zed Ghost", source_episode=E1)
    report = _run(memory, revisions=_rev("user: Notes.\nZed Ghost.\nalpha tasks continue.", BODY))
    assert report.questions == []
    # ... and a name held for another conversation too.
    (memory / "episodes" / f"{E2}.md").unlink()
    _held.memory = memory
    _held("Zed Ghost", [E1, E3])
    assert _run(memory, revisions=_rev("user: Notes.\nZed Ghost.\nalpha tasks continue.", BODY)).questions == []


def test_a_conflict_whose_options_the_revision_closed_is_withdrawn_but_one_with_a_live_side_is_not(memory):
    a, b = _claim("clm_a", "tool-a", E1), _claim("clm_b", "tool-a", E1)
    b.object = "other"
    rec_a, rec_b = _record("clm_ra", a, E1), _record("clm_rb", b, E1)
    a.valid_to, a.superseded_by, b.valid_to, b.superseded_by = "2026-11-05", rec_a.id, "2026-11-05", rec_b.id
    c = _claim("clm_c", "tool-a", E2)
    _episode(memory, E2, "user: tool-a is great.")
    _page(memory, "tool-a", [a, b, c, rec_a, rec_b], type="tool", source_episodes=[E1, E2], owner=False)
    options = [{"key": "a", "label": "x", "claim_id": "clm_a"}, {"key": "b", "label": "y", "claim_id": "clm_b"},
               {"key": "both", "label": "Both"}]
    _item(memory, "inbox-010", kind="conflict", entity_id="tool-a", predicate="value-of-role", options=options)
    three = [*options[:2], {"key": "c", "label": "z", "claim_id": "clm_c"}]
    _item(memory, "inbox-011", kind="conflict", entity_id="tool-a", predicate="value-of-role", options=three)
    two_live = [{"key": "a", "label": "x", "claim_id": "clm_a"}, {"key": "c", "label": "z", "claim_id": "clm_c"}]
    _item(memory, "inbox-012", kind="conflict", entity_id="tool-a", predicate="value-of-role", options=two_live)
    report = _run(memory, revised_out={"clm_a": E1, "clm_b": E1})
    got = {q["item"]: q["why"] for q in report.questions}
    # Every option closed, all but one closed, and one closed beside one live: nothing is left to choose between.
    assert got["inbox-010"] == "options_closed" and got["inbox-011"] == "options_closed"
    assert got["inbox-012"] == "options_closed"


def _tend(memory: Path, corrected: dict[str, str]) -> inbox_tend.Report:
    bank_index.invalidate(memory)
    return asyncio.run(inbox_tend.tend(memory, _Settings(memory), episodes=[], run_policy=False, corrected=corrected))


def test_a_withdrawn_question_is_settled_by_sleep_undoable_and_a_changed_one_is_left(memory):
    out = _lost_page(memory)
    _item(memory, "inbox-001", kind="clarification", entity_id="zed-unknown", entity_name="Zed Unknown",
          source_episode=E1)
    _item(memory, "inbox-002", kind="clarification", entity_id="zed-unknown", entity_name="Zed Unknown",
          source_episode=E1, sleep_settle="undone")
    _item(memory, "inbox-003", kind="followup", entity_id="zed-unknown", entity_name="Zed Unknown")
    _commit(memory)
    report = _run(memory, revised_out=out)
    wanted = report.corrected()
    assert set(wanted) == {"inbox-001", "inbox-003"}      # the one the person took back is never touched
    _commit(memory, "batch", author="cicada")
    tended = _tend(memory, {**wanted, "inbox-002": E1})
    assert tended.settled == 2
    assert not (memory / "inbox" / "inbox-001.md").exists() and (memory / "inbox" / "inbox-002.md").exists()
    record = markdown_parser.parse(memory / "inbox" / "settled" / "inbox-001.md").frontmatter["settled"]
    assert record["rule"] == "source_corrected" and record["by_kind"] == "sleep"
    message = _git(memory, "log", "-1", "--fixed-strings", "--grep=inbox-001", "--format=%B")
    assert "sleep/inbox-tend:source_corrected" in message
    # Undoable like every Sleep settle.
    inbox_tend.undo(memory, "inbox-001")
    assert (memory / "inbox" / "inbox-001.md").exists()


def test_a_question_settles_only_while_the_bank_still_says_so(memory):
    out = _lost_page(memory)
    _item(memory, "inbox-001", kind="clarification", entity_id="zed-unknown", entity_name="Zed Unknown",
          source_episode=E1)
    wanted = _run(memory, revised_out=out).corrected()
    revision_cascade.restore(memory, "zed-unknown")      # the person put the page back before the settle
    _commit(memory, "batch")
    assert _tend(memory, wanted).settled == 0
    assert (memory / "inbox" / "inbox-001.md").exists()


# --------------------------------------------------------------------------- the restore route


def _client(memory, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_the_restore_route_puts_a_corrected_page_back_as_the_person_and_refuses_the_rest(memory, monkeypatch):
    out = _lost_page(memory, confidence=0.7)
    _commit(memory, "pages", author="gpt-5.4-mini")
    _run(memory, revised_out=out)
    _commit(memory, "batch", author="gpt-5.4-mini")
    client = _client(memory, monkeypatch)
    res = client.post("/entities/zed-unknown/restore-correction")
    assert res.status_code == 200, res.text
    assert res.json() == {"entityId": "zed-unknown", "status": "active", "confidence": 0.7}
    assert _fm(memory, "zed-unknown")["status"] == "active"
    assert "Cicada-Author: user" in _git(memory, "log", "-1", "--format=%B", "--", "entities/zed-unknown.md")
    assert client.post("/entities/zed-unknown/restore-correction").status_code == 409     # not archived any more
    assert client.post("/entities/nobody/restore-correction").status_code == 404
    _page(memory, "decayed", status="archived", confidence=0.1)
    assert client.post("/entities/decayed/restore-correction").status_code == 409         # decay's archive stays


def test_the_restore_route_is_refused_in_a_demo_bank(memory, monkeypatch):
    from api.services import demo_guard

    (memory / "_bank.yaml").write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    out = _lost_page(memory)
    _run(memory, revised_out=out)

    assert demo_guard.is_demo(memory)
    assert _client(memory, monkeypatch).post("/entities/zed-unknown/restore-correction").status_code == 409
    assert _fm(memory, "zed-unknown")["status"] == "archived"
