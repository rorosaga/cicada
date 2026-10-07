"""G148 follow-up — recover claims a Sleep prose rewrite dropped, from git alone, never what someone removed on purpose.

Every bank here is synthetic: `alpha-project`, `bob-example`, made-up claims and one made-up episode."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from api.services import claim_recovery, evidence, git_service, markdown_parser
from api.services.claims import RETRACT_PREDICATE, Claim, parse_claims, write_claims

EP = "ep_2026-10-01_001"
EP_BODY = "user: alpha-project now uses the example tool for its builds\nassistant: noted\n"


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
    markdown_parser.write(bank / "episodes" / f"{EP}.md", {"id": EP, "processed": True}, EP_BODY)
    _commit(bank, "Sources ingest 2026-10-01", [f"episodes/{EP}.md"], author="cicada")
    return bank


def _claim(n: int, **kw) -> Claim:
    base = dict(id=f"clm_2026-10-01_{n:03d}", text=f"Synthetic fact number {n} about alpha-project.",
                subject="alpha-project", predicate="uses", object=f"tool-{n}", recorded_at="2026-10-01")
    base.update(kw)
    return Claim(**base)


def _spanned(bank: Path, n: int) -> Claim:
    span = evidence.verify(bank, EP, "uses the example tool")
    assert span.is_span()
    return _claim(n, evidence=[span], source_episodes=[EP])


def _page(bank: Path, eid: str, prose: str, claims: list[Claim], *, status: str = "active") -> str:
    fm = {"id": eid, "name": eid.replace("-", " ").title(), "type": "project", "status": status}
    markdown_parser.write(bank / "entities" / f"{eid}.md", fm, write_claims(prose, claims))
    return f"entities/{eid}.md"


def _commit(bank: Path, subject: str, paths: list[str], *, author: str = "claude-sonnet-test") -> None:
    message = git_service.build_commit_message(subject, [f"{p}: updated (trigger: test)" for p in paths],
                                               authors=[author])
    git_service.commit_touched_sync(bank, message, paths)


def _fence(text: str) -> str:
    start = text.index("```claims")
    return text[start:text.index("```", start + 3) + 3]


def _ids(bank: Path, eid: str) -> list[str]:
    return [c.id for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{eid}.md").body, strict=True)]


def _drop_by_sleep(bank: Path, *, keep: list[Claim], prose: str = "## Overview\nRewritten, longer prose.\n",
                   subject: str = "Sleep cycle 2026-10-02 (batch 1 of 2)") -> None:
    _commit(bank, subject, [_page(bank, "alpha-project", prose, keep)])


def _seed(bank: Path, claims: list[Claim]) -> str:
    rel = _page(bank, "alpha-project", "## Overview\nFirst prose.\n", claims)
    _commit(bank, "Sleep cycle 2026-10-01", [rel])
    return (bank / rel).read_text(encoding="utf-8")


# --- finding candidates ------------------------------------------------------------------------------------------


def test_a_claim_a_sleep_rewrite_dropped_is_recovered_byte_identically(bank):
    c1, c2 = _claim(1), _spanned(bank, 2)
    seeded = _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])

    plan = claim_recovery.analyze(bank)
    assert plan.counts()["recoverable"] == 1
    assert [(i.claim_id, i.page) for i in plan.recoverable] == [(c2.id, "entities/alpha-project.md")]

    result = claim_recovery.apply(bank)
    assert result.recovered == 1 and result.pages == ["entities/alpha-project.md"]
    now = (bank / "entities" / "alpha-project.md").read_text(encoding="utf-8")
    assert _fence(now) == _fence(seeded), "same ids, same fields, same evidence span — byte for byte"
    assert "Rewritten, longer prose." in now, "the prose the rewrite wrote stays"


def test_a_claim_dropped_and_then_restated_is_not_a_candidate(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    _drop_by_sleep(bank, keep=[c1, c2], subject="Sleep cycle 2026-10-03")
    assert claim_recovery.analyze(bank).counts()["candidates"] == 0


@pytest.mark.parametrize("subject,author,reason", [
    ("Memory update 2026-10-02", "user", "person_edit"),
    ("Inbox resolution (conflict) 2026-10-02", "user", "person_edit"),
    ("Inbox resolution (conflict) 2026-10-02", "cicada", "inbox_resolution"),
    ("Agent write 2026-10-02", "claude-code", "other_writer"),
    ("Dedup sweep 2026-10-02", "cicada", "merged"),
])
def test_a_claim_removed_by_anything_but_a_sleep_rewrite_is_never_recovered(bank, subject, author, reason):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _commit(bank, subject, [_page(bank, "alpha-project", "## Overview\nEdited prose.\n", [c1])], author=author)

    plan = claim_recovery.analyze(bank)
    assert plan.counts()["recoverable"] == 0
    assert plan.counts()["excluded"] == {reason: 1}
    assert claim_recovery.apply(bank).recovered == 0


def test_the_last_removal_decides(bank):
    """Sleep dropped it, the fact came back, then the person removed it: that removal is the one that stands."""
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    _drop_by_sleep(bank, keep=[c1, c2], subject="Sleep cycle 2026-10-03")
    _commit(bank, "Memory update 2026-10-04", [_page(bank, "alpha-project", "## Overview\nMine.\n", [c1])],
            author="user")
    assert claim_recovery.analyze(bank).counts()["excluded"] == {"person_edit": 1}


def test_a_retracted_claim_is_never_recovered(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    record = _claim(3, predicate=RETRACT_PREDICATE, object=c2.id, valid_from="2026-10-02", valid_to="2026-10-02")
    _drop_by_sleep(bank, keep=[c1, record])
    assert claim_recovery.analyze(bank).counts()["excluded"] == {"retracted": 1}


def test_a_claim_a_merge_carried_under_a_new_id_is_never_recovered(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    moved = _claim(2, id=f"{c2.id}-from-bob-example", subject="bob-example")
    _commit(bank, "Dedup sweep 2026-10-03", [_page(bank, "bob-example", "## Overview\nBob.\n", [moved])],
            author="cicada")
    assert claim_recovery.analyze(bank).counts()["excluded"] == {"merged": 1}


def test_a_page_deleted_or_archived_since_is_left_alone(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    _commit(bank, "Sleep cycle 2026-10-03 (decay)",
            [_page(bank, "alpha-project", "## Overview\nRewritten, longer prose.\n", [c1], status="archived")],
            author="cicada")
    assert claim_recovery.analyze(bank).counts()["excluded"] == {"page_archived": 1}

    (bank / "entities" / "alpha-project.md").unlink()
    _commit(bank, "Memory update 2026-10-04", ["entities/alpha-project.md"], author="user")
    # c1 went with the page the person deleted: their removal, not a rewrite's.
    assert claim_recovery.analyze(bank).counts()["excluded"] == {"page_gone": 1, "person_edit": 1}


def test_a_sleep_commit_that_lost_claims_without_rewriting_prose_is_reported_not_recovered(bank):
    """The rewrite bug's signature is prose that moved; a fence that shrank under unchanged prose is something else
    (a hand edit a Sleep commit swept up) — excluded, never guessed at."""
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1], prose="## Overview\nFirst prose.\n")
    assert claim_recovery.analyze(bank).counts()["excluded"] == {"prose_unchanged": 1}


# --- dry run, plan file, CLI -------------------------------------------------------------------------------------


def test_a_dry_run_writes_nothing_and_its_plan_carries_no_claim_text(bank, tmp_path, capsys):
    c1, c2 = _claim(1), _spanned(bank, 2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    head = _git(bank, "rev-parse", "HEAD")
    before = (bank / "entities" / "alpha-project.md").read_bytes()
    out = tmp_path / "plan.json"

    assert claim_recovery.main(["--bank", str(bank), "--plan", str(out)]) == 0

    assert _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""
    assert (bank / "entities" / "alpha-project.md").read_bytes() == before
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert plan["counts"]["recoverable"] == 1
    assert plan["recoverable"][0]["claim_id"] == c2.id
    assert plan["recoverable"][0]["page"] == "entities/alpha-project.md"
    printed = capsys.readouterr().out
    for text in (out.read_text(encoding="utf-8"), printed):
        assert c2.text not in text and c1.text not in text and "example tool" not in text
    assert "recoverable: 1" in printed


def test_the_cli_applies_and_says_what_it_did(bank, capsys):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    assert claim_recovery.main(["--bank", str(bank), "--apply"]) == 0
    assert _ids(bank, "alpha-project") == [c1.id, c2.id]
    printed = capsys.readouterr().out
    assert "recovered: 1" in printed and c2.text not in printed


# --- apply -------------------------------------------------------------------------------------------------------


def test_apply_commits_only_the_pages_it_touched_as_cicada_and_is_idempotent(bank):
    c1, c2, c3 = _claim(1), _claim(2), _claim(3)
    _seed(bank, [c1, c2, c3])
    _drop_by_sleep(bank, keep=[c1])
    _page(bank, "bob-example", "## Overview\nUncommitted.\n", [])   # someone else's uncommitted page

    result = claim_recovery.apply(bank)
    assert result.recovered == 2
    assert _ids(bank, "alpha-project") == [c1.id, c2.id, c3.id]
    shown = _git(bank, "show", "--name-only", "--format=%s%n%(trailers:key=Cicada-Author,valueonly)", "HEAD")
    assert shown.splitlines()[0].startswith("Recover dropped claims ")
    assert "cicada" in shown.splitlines()[1]
    assert [ln for ln in shown.splitlines() if ln.startswith("entities/")] == ["entities/alpha-project.md"]
    assert "?? entities/bob-example.md" in _git(bank, "status", "--porcelain")

    head = _git(bank, "rev-parse", "HEAD")
    again = claim_recovery.apply(bank)
    assert again.recovered == 0 and again.commit is None
    assert _git(bank, "rev-parse", "HEAD") == head
    assert claim_recovery.analyze(bank).counts()["candidates"] == 0


def test_apply_refuses_while_sleep_holds_the_pages(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    head = _git(bank, "rev-parse", "HEAD")
    with pytest.raises(claim_recovery.SleepIsWriting):
        claim_recovery.apply(bank, sleep_holding=lambda: True)
    assert _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""


def test_apply_skips_a_page_with_an_uncommitted_edit(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    path = bank / "entities" / "alpha-project.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nA hand edit.\n", encoding="utf-8")
    edited = path.read_bytes()

    result = claim_recovery.apply(bank)
    assert result.recovered == 0 and result.skipped_dirty == ["entities/alpha-project.md"]
    assert path.read_bytes() == edited


def test_a_span_that_no_longer_locates_is_kept_as_reasoning(bank):
    c1, c2, c3 = _claim(1), _spanned(bank, 2), _spanned(bank, 3)
    _seed(bank, [c1, c2, c3])
    _drop_by_sleep(bank, keep=[c1, c3])
    _drop_by_sleep(bank, keep=[c1], prose="## Overview\nRewritten again.\n", subject="Sleep cycle 2026-10-03")
    # The episode is rewritten in place (not appended to): c2's and c3's offsets no longer point at their words.
    markdown_parser.write(bank / "episodes" / f"{EP}.md", {"id": EP, "processed": True}, "user: something else\n")
    _commit(bank, "Sources ingest 2026-10-04", [f"episodes/{EP}.md"], author="cicada")

    result = claim_recovery.apply(bank)
    assert result.recovered == 2 and result.degraded_spans == 2
    recovered = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / "alpha-project.md").body)}
    for cid in (c2.id, c3.id):
        (ev,) = recovered[cid].evidence
        assert ev.kind == "reasoning" and ev.start == ev.end == -1 and ev.episode == EP
        assert recovered[cid].text == _claim(int(cid[-3:])).text, "the claim is still written"


def test_a_bank_without_git_is_refused(tmp_path):
    (tmp_path / "plain" / "entities").mkdir(parents=True)
    with pytest.raises(claim_recovery.NotAGitBank):
        claim_recovery.analyze(tmp_path / "plain")
    assert claim_recovery.main(["--bank", str(tmp_path / "plain")]) == 2


def test_a_failed_commit_puts_the_pages_back(bank, monkeypatch):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    before = (bank / "entities" / "alpha-project.md").read_bytes()

    real = git_service._git_sync

    def failing_commit(memory_path, *args):
        if args and args[0] == "commit":   # after `git add` staged the recovered page
            raise git_service.GitError("synthetic failure")
        return real(memory_path, *args)

    monkeypatch.setattr(git_service, "_git_sync", failing_commit)
    with pytest.raises(git_service.GitError):
        claim_recovery.apply(bank)
    assert (bank / "entities" / "alpha-project.md").read_bytes() == before
    assert _git(bank, "status", "--porcelain") == ""


def test_sleep_is_asked_while_the_admission_is_held(bank):
    from api.services import write_admission

    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop_by_sleep(bank, keep=[c1])
    seen: list[int] = []
    claim_recovery.apply(bank, sleep_holding=lambda: seen.append(write_admission.holders(bank)) or False)
    assert seen == [1], "the answer must hold until the commit: a window cannot open under a shared holder"
