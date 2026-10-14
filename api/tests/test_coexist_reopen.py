"""2026-10-14 — reopen the places the old single-valued ``works-at`` rule closed only because another place arrived.

Every bank here is synthetic (`bob-example`, `acme-example`, made-up claims); the history is built the way Stage 3
wrote it before the fix — `_close` on a different object, in a `Sleep cycle` commit by a model.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from api.services import claim_reconciler, coexist_reopen, git_service, markdown_parser, predicates
from api.services.claims import Claim, parse_claims, write_claims

PAGE = "entities/bob-example.md"


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(bank), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    (bank / "episodes").mkdir()
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "config", "user.name", "Cicada Test")
    predicates.install_predicate_map(bank)
    _commit(bank, "Bank setup", ["_predicates.yaml"], author="cicada")
    return bank


def _w(cid: str, obj: str, day: str, **kw) -> Claim:
    return Claim(id=cid, text=f"Bob Example works at {obj}", subject="bob-example", predicate="works-at", object=obj,
                 observer="agent", context="general", valid_from=day, recorded_at=day,
                 source_episodes=[f"ep_{day}_001"], authored_by="claude-sonnet-test", **kw)


def _close(old: Claim, by: Claim) -> None:
    claim_reconciler._close(old, by=by)


def _write(bank: Path, claims: list[Claim], *, status: str = "active") -> None:
    markdown_parser.write(bank / PAGE, {"name": "Bob Example", "type": "person", "status": status},
                          write_claims("## Summary\nA person.", claims))


def _commit(bank: Path, subject: str, paths: list[str], *, author: str = "claude-sonnet-test") -> None:
    message = git_service.build_commit_message(subject, [f"{p}: updated (trigger: test)" for p in paths],
                                               authors=[author])
    git_service.commit_touched_sync(bank, message, paths)


def _sleep(bank: Path, day: str, claims: list[Claim]) -> None:
    _write(bank, claims)
    _commit(bank, f"Sleep cycle {day}", [PAGE])


def _now(bank: Path) -> dict[str, Claim]:
    return {c.id: c for c in parse_claims(markdown_parser.parse(bank / PAGE).body, strict=True)}


def _flip_flop(bank: Path) -> dict[str, Claim]:
    """A→B→A→C, as the old rule wrote it: each new place closed the last."""
    a1 = _w("clm_a1", "acme-example", "2026-06-01")
    _sleep(bank, "2026-06-01", [a1])
    b1 = _w("clm_b1", "lab-example", "2026-06-02")
    _close(a1, b1)
    _sleep(bank, "2026-06-02", [a1, b1])
    a2 = _w("clm_a2", "acme-example", "2026-07-15")
    _close(b1, a2)
    _sleep(bank, "2026-07-15", [a1, b1, a2])
    c1 = _w("clm_c1", "side-example", "2026-08-30")
    _close(a2, c1)
    _sleep(bank, "2026-08-30", [a1, b1, a2, c1])
    return {c.id: c for c in (a1, b1, a2, c1)}


def test_dry_run_counts_and_apply_reopens_the_flip_flop_in_one_commit(bank):
    _flip_flop(bank)
    before = (bank / PAGE).read_text(encoding="utf-8")
    plan = coexist_reopen.analyze(bank)
    counts = plan.counts()
    assert (counts["reopen"], counts["kept_closed"]) == (2, {"older_copy": 1})
    assert {i.claim_id for i in plan.reopen} == {"clm_a2", "clm_b1"}, "the newest copy of each place"
    assert (bank / PAGE).read_text(encoding="utf-8") == before, "a dry run writes nothing"

    result = coexist_reopen.apply(bank, sleep_holding=lambda: False)
    assert (result.reopened, result.pages) == (2, [PAGE])
    now = _now(bank)
    assert {c.object for c in now.values() if c.valid_to is None} == {"acme-example", "lab-example", "side-example"}
    assert (now["clm_a2"].superseded_by, now["clm_c1"].supersedes) == (None, None)
    assert (now["clm_a1"].valid_to, now["clm_a1"].superseded_by) == ("2026-06-02", "clm_b1"), "history stays"
    assert len(now) == 4, "nothing deleted"
    log = _git(bank, "log", "-1", "--format=%s%n%b")
    assert log.startswith("Reopen coexisting places ") and "Cicada-Author: cicada" in log
    assert _git(bank, "status", "--porcelain") == ""
    assert coexist_reopen.analyze(bank).reopen == [], "a re-run finds nothing"


def test_evidenced_endings_and_the_persons_word_stay_closed(bank):
    a = _w("clm_a", "acme-example", "2026-06-01")
    left = _w("clm_left", "acme-example", "2026-06-10", valid_to="2026-06-10")   # an ending: same object
    claim_reconciler._close_event(a, by=left)
    h_old = _w("clm_h_old", "old-example", "2026-06-01")
    h_new = _w("clm_h_new", "new-example", "2026-06-05", source_trust="user_stated", origin="clarification")
    _close(h_old, h_new)
    past = _w("clm_past", "past-example", "2026-06-01")
    past.text = "Bob Example worked at past-example"
    past_by = _w("clm_past_by", "lab-example", "2026-06-03")
    _close(past, past_by)
    gone = _w("clm_gone", "gone-example", "2026-06-01")
    gone_by = _w("clm_gone_by", "other-example", "2026-06-04")
    _close(gone, gone_by)
    said_left = Claim(id="clm_said_left", text="Bob Example left gone-example", subject="bob-example",
                      predicate="left", object="gone-example", valid_from="2026-06-04")
    ended = _w("clm_ended", "ended-example", "2026-06-01", expected_end="2026-06-20")
    ended_by = _w("clm_ended_by", "next-example", "2026-07-01")
    _close(ended, ended_by)
    expired = _w("clm_exp", "exp-example", "2026-06-01", valid_to="2026-06-30")   # closed with no successor
    _sleep(bank, "2026-07-01", [a, left, h_old, h_new, past, past_by, gone, gone_by, said_left, ended, ended_by,
                                expired])
    reasons = {i.claim_id: i.reason for i in coexist_reopen.analyze(bank).items}
    assert reasons == {
        "clm_a": "ended", "clm_left": "no_successor", "clm_h_old": "persons_word", "clm_past": "said_past",
        "clm_gone": "departure_stated", "clm_ended": "stated_end", "clm_exp": "no_successor",
    }, reasons


def test_a_close_no_sleep_commit_made_stays_closed(bank):
    a = _w("clm_a", "acme-example", "2026-06-01")
    _sleep(bank, "2026-06-01", [a])
    b = _w("clm_b", "lab-example", "2026-06-02")
    _close(a, b)
    _write(bank, [a, b])
    _commit(bank, "Inbox resolution 2026-06-02", [PAGE], author="user")
    assert [(i.claim_id, i.reason) for i in coexist_reopen.analyze(bank).items] == [("clm_a", "person_edit")]


def test_a_place_already_current_and_a_cutoff_keep_their_closed_copies(bank):
    copies = _flip_flop(bank)
    again = _w("clm_a3", "acme-example", "2026-09-01")
    _sleep(bank, "2026-09-01", [*copies.values(), again])
    reasons = {i.claim_id: i.reason for i in coexist_reopen.analyze(bank).items}
    assert reasons == {"clm_a1": "already_current", "clm_a2": "already_current", "clm_b1": "reopen"}
    cut = {i.claim_id: i.reason for i in coexist_reopen.analyze(bank, said_since="2026-07-01").items}
    assert cut["clm_b1"] == "said_before_cutoff"


def test_apply_refuses_while_sleep_holds_and_skips_a_dirty_page(bank):
    _flip_flop(bank)
    before = (bank / PAGE).read_text(encoding="utf-8")
    with pytest.raises(coexist_reopen.SleepIsWriting):
        coexist_reopen.apply(bank, sleep_holding=lambda: True)
    assert (bank / PAGE).read_text(encoding="utf-8") == before
    (bank / PAGE).write_text(before + "\nA hand edit.\n", encoding="utf-8")
    result = coexist_reopen.apply(bank, sleep_holding=lambda: False)
    assert (result.reopened, result.skipped_dirty, result.commit) == (0, [PAGE], None)


def test_a_reopened_place_stays_current_through_the_next_sleep(bank, tmp_path):
    from types import SimpleNamespace

    _flip_flop(bank)
    coexist_reopen.apply(bank, sleep_holding=lambda: False)
    page = _now(bank)
    newer = _w("clm_d1", "fourth-example", "2026-09-20")
    out, _n, audit = claim_reconciler.reconcile_stage3(
        [newer], {"bob-example": list(page.values())},
        SimpleNamespace(memory_path=bank, litellm_model="gpt-5.4-mini", archive_threshold=0.2,
                        decay_nudge_threshold=0.4),
        now_date="2026-09-20", decay=False)
    assert not [a for a in audit if a["action"] == "supersede"]
    assert {c.object for c in out["bob-example"] if c.valid_to is None} == \
        {"acme-example", "lab-example", "side-example", "fourth-example"}


def test_cli_dry_run_prints_counts_only(bank, capsys):
    _flip_flop(bank)
    assert coexist_reopen.main(["--bank", str(bank)]) == 0
    out = capsys.readouterr().out
    assert "would reopen: 2 on 1 pages" in out and "kept closed (older_copy): 1" in out
    assert "acme" not in out and "Bob" not in out, "counts only, never claim text or names"
    assert coexist_reopen.main(["--bank", str(bank / "nope")]) == 2
