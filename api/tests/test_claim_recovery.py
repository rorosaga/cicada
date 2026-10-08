"""G148 follow-up — recover the claims a Sleep prose rewrite dropped, from git alone, ONLY as closed history.

Every bank here is synthetic: `alpha-project`, `bob-example`, made-up claims and one made-up episode. The fixture page
keeps its fence inside its last section when sectioned raw — the layout the unfixed rewrite tore."""
from __future__ import annotations

import http.server
import json
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from api.services import claim_recovery, claims, evidence, git_service, markdown_parser, write_admission
from api.services.claims import RETRACT_PREDICATE, Claim, parse_claims, raw_claim_entries, write_claims

EP = "ep_2026-10-01_001"
EP_BODY = "user: alpha-project now uses the example tool for its builds\nassistant: noted\n"
PAGE = "entities/alpha-project.md"
DROP_DAY = "2026-10-02"
FIRST = "## Overview\nFirst prose.\n"
REWRITTEN = "## Overview\nRewritten, longer prose.\n"


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(bank), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path: Path, monkeypatch) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    (bank / "episodes").mkdir()
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "config", "user.name", "Cicada Test")
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"{DROP_DAY}T12:00:00+00:00")
    markdown_parser.write(bank / "episodes" / f"{EP}.md", {"id": EP, "processed": True}, EP_BODY)
    _commit(bank, "Sources ingest 2026-10-01", [f"episodes/{EP}.md"], author="cicada")
    return bank


def _claim(n: int, **kw) -> Claim:
    base = dict(id=f"clm_2026-10-01_{n:03d}", text=f"Synthetic fact number {n} about alpha-project.",
                subject="alpha-project", predicate="uses", object=f"tool-{n}", recorded_at="2026-10-01",
                valid_from="2026-10-01")
    base.update(kw)
    return Claim(**base)


def _restated(old: Claim, n: int, **kw) -> Claim:
    """The pipeline re-asserting the same fact under a new id — a current replacement."""
    return _claim(n, object=old.object, predicate=old.predicate, **kw)


def _spanned(bank: Path, n: int) -> Claim:
    span = evidence.verify(bank, EP, "uses the example tool")
    assert span.is_span()
    return _claim(n, evidence=[span], source_episodes=[EP])


def _page(bank: Path, eid: str, prose: str, claims: list[Claim], *, status: str = "active") -> str:
    fm = {"id": eid, "name": eid.replace("-", " ").title(), "type": "project", "status": status}
    markdown_parser.write(bank / "entities" / f"{eid}.md", fm, write_claims(prose, claims))
    return f"entities/{eid}.md"


def _commit(bank: Path, subject: str, paths: list[str], *, author: str | None = "claude-sonnet-test") -> None:
    message = git_service.build_commit_message(subject, [f"{p}: updated (trigger: test)" for p in paths],
                                               authors=[author] if author else [])
    git_service.commit_touched_sync(bank, message, paths)


def _seed(bank: Path, claims: list[Claim], prose: str = FIRST) -> str:
    _commit(bank, "Sleep cycle 2026-10-01", [_page(bank, "alpha-project", prose, claims)])
    return (bank / PAGE).read_text(encoding="utf-8")


def _drop(bank: Path, keep: list[Claim], *, prose: str = REWRITTEN,
          subject: str = "Sleep cycle 2026-10-02 (batch 1 of 2)", author: str | None = "claude-sonnet-test",
          status: str = "active") -> None:
    _commit(bank, subject, [_page(bank, "alpha-project", prose, keep, status=status)], author=author)


def _claims_now(bank: Path, eid: str = "alpha-project") -> dict[str, Claim]:
    return {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{eid}.md").body, strict=True)}


def _fence(text: str) -> str:
    start = text.index("```claims")
    return text[start:text.index("```", start + 3) + 3]


def _counts(bank: Path) -> dict:
    return claim_recovery.analyze(bank).counts()


# --- restored only as closed history ---------------------------------------------------------------------------


def test_a_dropped_claim_with_a_current_restatement_comes_back_closed_and_marked(bank):
    c1, c2 = _claim(1), _spanned(bank, 2)
    seeded = _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    survivors = _fence((bank / PAGE).read_text(encoding="utf-8"))[:-3]

    plan = claim_recovery.analyze(bank)
    assert plan.counts()["replaced"] == 1 and plan.counts()["no_current_replacement"] == 0
    result = claim_recovery.apply(bank)
    assert result.recovered == 1 and result.pages == [PAGE]

    now_text = (bank / PAGE).read_text(encoding="utf-8")
    assert _fence(now_text).startswith(survivors), "every entry already in the fence keeps its bytes"
    back = _claims_now(bank)[c2.id]
    assert back.valid_to == DROP_DAY, "closed the day the rewrite dropped it — never a current belief"
    assert back.recovered_by == "claim_recovery" and back.recovered_from == plan.items[0].removed_in
    original = Claim.from_dict(raw_claim_entries(seeded)[1]).to_dict()
    restored = back.to_dict()
    for key in ("valid_to", "recovered_from", "recovered_by"):
        restored.pop(key, None)
        original.pop(key, None)
    assert restored == original, "every other field, the evidence span included"
    assert "Rewritten, longer prose." in now_text


def test_a_belief_with_no_current_replacement_is_listed_never_written(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1])
    plan = claim_recovery.analyze(bank)
    assert plan.counts()["no_current_replacement"] == 1
    assert plan.items[0].to_dict() == {"claim_id": c2.id, "page": PAGE, "removed_in": plan.items[0].removed_in,
                                       "class": "no_current_replacement"}
    head = _git(bank, "rev-parse", "HEAD")
    assert claim_recovery.apply(bank).recovered == 0
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_claim_already_closed_when_dropped_comes_back_with_its_own_close(bank):
    c1, c2 = _claim(1), _claim(2, valid_to="2026-09-15", superseded_by="clm_gone")
    _seed(bank, [c1, c2])
    _drop(bank, [c1])
    assert _counts(bank)["closed_history"] == 1
    claim_recovery.apply(bank)
    assert _claims_now(bank)[c2.id].valid_to == "2026-09-15"


def test_a_conflicting_successor_never_leaves_two_open_beliefs(bank):
    """The live order (prose written, THEN the claim pipeline): the old claim vanished before reconciliation, so a
    newer single-valued claim never closed it. Recovery must not hand back the old one open beside it."""
    (bank / "_predicates.yaml").write_text("single_valued:\n  - lives_in\n", encoding="utf-8")
    old = _claim(2, predicate="lives_in", object="city-a")
    _seed(bank, [_claim(1), old])
    new = _claim(5, predicate="lives_in", object="city-b", valid_from=DROP_DAY)
    _drop(bank, [_claim(1), new])
    assert _counts(bank)["replaced"] == 1
    claim_recovery.apply(bank)
    open_slot = [c for c in _claims_now(bank).values() if c.predicate == "lives_in" and c.valid_to is None]
    assert [c.id for c in open_slot] == [new.id]


def test_without_a_vocabulary_a_different_object_is_not_a_replacement(bank):
    old = _claim(2, predicate="lives_in", object="city-a")
    _seed(bank, [_claim(1), old])
    _drop(bank, [_claim(1), _claim(5, predicate="lives_in", object="city-b")])
    assert _counts(bank)["no_current_replacement"] == 1


def test_a_surviving_supersedes_link_marks_it_replaced(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _claim(6, object="tool-other", supersedes=c2.id)])
    assert _counts(bank)["replaced"] == 1
    claim_recovery.apply(bank)
    assert _claims_now(bank)[c2.id].valid_to == DROP_DAY


def test_a_stated_end_that_passed_first_is_the_close(bank):
    c1, c2 = _claim(1), _claim(2, expected_end="2026-09-30", valid_from="2026-09-01")
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    claim_recovery.apply(bank)
    assert _claims_now(bank)[c2.id].valid_to == "2026-09-30"


# --- who removed it ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("subject,author,reason", [
    ("Memory update 2026-10-02", "user", "person_edit"),
    ("Inbox resolution (conflict) 2026-10-02", "user", "person_edit"),
    ("Inbox resolution (conflict) 2026-10-02", "cicada", "inbox_resolution"),
    ("Agent write 2026-10-02", "claude-code", "other_writer"),
    ("Dedup sweep 2026-10-02", "cicada", "merged"),
    ("Sleep cycle 2026-10-02", "claude-code", "unproven_writer"),
    ("Sleep cycle 2026-10-02", None, "unproven_writer"),
    ("Sleep cycle 2026-10-02", "unknown", "unproven_writer"),
])
def test_only_a_sleep_commit_by_a_model_or_cicada_is_a_rewrite_candidate(bank, subject, author, reason):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)], subject=subject, author=author)
    assert _counts(bank)["excluded"] == {reason: 1}
    assert claim_recovery.apply(bank).recovered == 0


def test_the_last_removal_decides(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1])
    _drop(bank, [c1, c2], prose="## Overview\nAgain.\n", subject="Sleep cycle 2026-10-03")
    _drop(bank, [c1, _restated(c2, 9)], prose="## Overview\nMine.\n", subject="Memory update 2026-10-04",
          author="user")
    assert _counts(bank)["excluded"] == {"person_edit": 1}


def test_a_fence_lost_while_a_different_section_changed_is_not_the_rewrite(bank):
    """A hand edit removed the entry; Sleep later rewrote another section and committed both: not the signature."""
    c1, c2 = _claim(1), _claim(2)
    prose = "## Overview\nFirst prose.\n\n## Related\n- [[bob-example]]\n"
    _seed(bank, [c1, c2], prose=prose)
    _drop(bank, [c1, _restated(c2, 9)], prose="## Overview\nRewritten.\n\n## Related\n- [[bob-example]]\n")
    assert _counts(bank)["excluded"] == {"not_rewrite": 1}


def test_a_fence_lost_under_unchanged_prose_is_not_the_rewrite(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)], prose=FIRST)
    assert _counts(bank)["excluded"] == {"not_rewrite": 1}


# --- what the history says about it -------------------------------------------------------------------------------


def test_a_claim_retracted_at_any_point_is_never_recovered(bank):
    c1, c2 = _claim(1), _claim(2)
    record = _claim(3, predicate=RETRACT_PREDICATE, object=c2.id, valid_from="2026-10-01", valid_to="2026-10-01")
    closed = _claim(2, valid_to="2026-10-01", superseded_by=record.id)
    _seed(bank, [c1, closed, record])
    _drop(bank, [c1, _restated(c2, 9)])   # the rewrite took the target AND its record
    assert _counts(bank)["excluded"] == {"retracted": 2}


def test_a_claim_a_merge_carried_under_a_new_id_is_never_recovered(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    moved = _claim(2, id=f"{c2.id}-from-bob-example", subject="bob-example")
    _commit(bank, "Dedup sweep 2026-10-03", [_page(bank, "bob-example", "## Overview\nBob.\n", [moved])],
            author="cicada")
    assert _counts(bank)["excluded"] == {"merged": 1}


def test_a_page_archived_at_the_removal_stays_excluded_after_reactivation(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)], subject="Sleep cycle 2026-10-02 (decay)", author="cicada",
          status="archived")
    _drop(bank, [c1, _restated(c2, 9)], subject="Memory update 2026-10-03", author="user")   # reactivated
    assert _counts(bank)["excluded"] == {"page_archived": 1}


def test_a_page_deleted_since_is_left_alone(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    (bank / PAGE).unlink()
    _commit(bank, "Memory update 2026-10-04", [PAGE], author="user")
    assert _counts(bank)["excluded"]["page_gone"] == 1


# --- unreadable fences ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("trapped,expected", [
    ("lost", {"candidates": 0}),                      # the id is still there, trapped: not a loss
    ("other", {"excluded": {"unreadable_fence": 1}}),  # the fence cannot be written to: excluded
])
def test_an_unterminated_fence_is_never_written_to(bank, trapped, expected):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    path = bank / PAGE
    text = path.read_text(encoding="utf-8")
    trapped_id = c2.id if trapped == "lost" else "clm_other"
    trapped_entry = claims._jsonl_line({"id": trapped_id, "text": "trapped"})       # the fence's own form
    path.write_text(text[:text.rindex("```")] + trapped_entry + "\n", encoding="utf-8")
    _commit(bank, "Memory update 2026-10-03", [PAGE], author="user")
    before = path.read_bytes()
    counts = _counts(bank)
    assert {k: counts[k] for k in expected} == expected
    assert claim_recovery.apply(bank).recovered == 0
    assert path.read_bytes() == before


def test_an_unreadable_page_elsewhere_that_names_the_id_blocks_recovery(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    other = bank / "entities" / "bob-example.md"
    other.write_text(f"---\nid: bob-example\n---\n\n```claims\n- id: {c2.id}\n  text: [unclosed\n```\n",
                     encoding="utf-8")
    _commit(bank, "Memory update 2026-10-03", ["entities/bob-example.md"], author="user")
    assert _counts(bank)["excluded"] == {"unreadable_elsewhere": 1}


# --- bytes ---------------------------------------------------------------------------------------------------------


def test_a_legacy_entry_and_unknown_fields_come_back_as_the_yaml_held_them(bank):
    kept = ("- id: keep-1\n  text: Kept.\n  subject: alpha-project\n  predicate: uses\n  object: tool-9\n"
            "  custom_note: kept verbatim\n")
    lost = "- id: lost-1\n  text: Legacy.\n  subject: alpha-project\n  predicate: uses\n  object: tool-9\n  odd_field: 7\n"
    path = bank / PAGE
    path.write_text(f"---\nid: alpha-project\nstatus: active\n---\n\n{FIRST}\n```claims\n{kept}{lost}```\n",
                    encoding="utf-8")
    _commit(bank, "Sleep cycle 2026-10-01", [PAGE])
    path.write_text(f"---\nid: alpha-project\nstatus: active\n---\n\n{REWRITTEN}\n```claims\n{kept}```\n",
                    encoding="utf-8")
    _commit(bank, "Sleep cycle 2026-10-02", [PAGE])
    before = path.read_text(encoding="utf-8")
    dropped_in = _git(bank, "rev-parse", "HEAD").strip()

    assert claim_recovery.apply(bank).recovered == 1
    after = path.read_text(encoding="utf-8")
    assert after.startswith(before[:before.rindex("```")]), "frontmatter, prose and the surviving entry untouched"
    assert raw_claim_entries(after)[1] == {"id": "lost-1", "text": "Legacy.", "subject": "alpha-project",
                                           "predicate": "uses", "object": "tool-9", "odd_field": 7,
                                           "valid_to": DROP_DAY, "recovered_from": dropped_in,
                                           "recovered_by": "claim_recovery"}


def test_recovery_markers_survive_a_later_writer_re_rendering_the_fence(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    claim_recovery.apply(bank)
    parsed = markdown_parser.parse(bank / PAGE)
    again = parse_claims(write_claims(parsed.body, parse_claims(parsed.body, strict=True)))
    assert next(c for c in again if c.id == c2.id).recovered_by == "claim_recovery"


# --- dry run, apply transaction -----------------------------------------------------------------------------------


def test_a_dry_run_writes_nothing_and_its_plan_carries_no_claim_text(bank, tmp_path, capsys):
    c1, c2 = _claim(1), _spanned(bank, 2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    head = _git(bank, "rev-parse", "HEAD")
    before = (bank / PAGE).read_bytes()
    out = tmp_path / "plan.json"

    assert claim_recovery.main(["--bank", str(bank), "--plan", str(out)]) == 0

    assert _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""
    assert (bank / PAGE).read_bytes() == before
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert plan["counts"]["replaced"] == 1
    assert plan["items"][0]["claim_id"] == c2.id and plan["items"][0]["class"] == "replaced"
    printed = capsys.readouterr().out
    for text in (out.read_text(encoding="utf-8"), printed):
        assert c2.text not in text and c1.text not in text and "example tool" not in text
    assert "replaced: 1" in printed and "no_current_replacement: 0" in printed


def test_apply_commits_only_the_pages_it_touched_as_cicada_and_is_idempotent(bank):
    c1, c2, c3 = _claim(1), _claim(2), _claim(3)
    _seed(bank, [c1, c2, c3])
    _drop(bank, [c1, _restated(c2, 8), _restated(c3, 9)])
    _page(bank, "bob-example", "## Overview\nUncommitted.\n", [])

    assert claim_recovery.apply(bank).recovered == 2
    shown = _git(bank, "show", "--name-only", "--format=%s%n%(trailers:key=Cicada-Author,valueonly)", "HEAD")
    assert shown.splitlines()[0].startswith("Recover dropped claims ")
    assert "cicada" in shown.splitlines()[1]
    assert [ln for ln in shown.splitlines() if ln.startswith("entities/")] == [PAGE]
    assert "?? entities/bob-example.md" in _git(bank, "status", "--porcelain")

    head = _git(bank, "rev-parse", "HEAD")
    again = claim_recovery.apply(bank)
    assert again.recovered == 0 and again.commit is None and _git(bank, "rev-parse", "HEAD") == head
    assert _counts(bank)["candidates"] == 0


def test_apply_refuses_while_sleep_holds_the_pages(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    head = _git(bank, "rev-parse", "HEAD")
    with pytest.raises(claim_recovery.SleepIsWriting):
        claim_recovery.apply(bank, sleep_holding=lambda: True)
    assert _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""


def test_sleep_is_asked_while_the_admission_is_held(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    seen: list[int] = []
    claim_recovery.apply(bank, sleep_holding=lambda: seen.append(write_admission.holders(bank)) or False)
    assert seen == [1], "the answer must hold until the commit: a window cannot open under a shared holder"


def test_apply_skips_a_page_with_an_uncommitted_edit(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    path = bank / PAGE
    path.write_text(path.read_text(encoding="utf-8") + "\nA hand edit.\n", encoding="utf-8")
    edited = path.read_bytes()
    result = claim_recovery.apply(bank)
    assert result.recovered == 0 and result.skipped_dirty == [PAGE] and path.read_bytes() == edited


def test_a_span_that_no_longer_locates_is_kept_as_reasoning(bank):
    c1, c2 = _claim(1), _spanned(bank, 2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    markdown_parser.write(bank / "episodes" / f"{EP}.md", {"id": EP, "processed": True}, "user: something else\n")
    _commit(bank, "Sources ingest 2026-10-04", [f"episodes/{EP}.md"], author="cicada")

    result = claim_recovery.apply(bank)
    assert result.recovered == 1 and result.degraded_spans == 1
    (ev,) = _claims_now(bank)[c2.id].evidence
    assert ev.kind == "reasoning" and ev.start == ev.end == -1 and ev.episode == EP


def test_a_failed_commit_puts_the_pages_back(bank, monkeypatch):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    before = (bank / PAGE).read_bytes()
    real = git_service._git_sync

    def failing_commit(memory_path, *args):
        if args and args[0] == "commit":   # after `git add` staged the recovered page
            raise git_service.GitError("synthetic failure")
        return real(memory_path, *args)

    monkeypatch.setattr(git_service, "_git_sync", failing_commit)
    with pytest.raises(git_service.GitError):
        claim_recovery.apply(bank)
    assert (bank / PAGE).read_bytes() == before and _git(bank, "status", "--porcelain") == ""


def test_a_bank_without_git_is_refused(tmp_path):
    (tmp_path / "plain" / "entities").mkdir(parents=True)
    with pytest.raises(claim_recovery.NotAGitBank):
        claim_recovery.analyze(tmp_path / "plain")
    assert claim_recovery.main(["--bank", str(tmp_path / "plain")]) == 2


# --- the CLI's Sleep check fails closed -----------------------------------------------------------------------------


def _serve(monkeypatch, status: int, body: bytes):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the stdlib's name
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("CICADA_PORT", str(server.server_address[1]))
    return server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("status,body", [
    (401, b'{"detail": "missing or invalid bearer token"}'),
    (403, b"{}"),
    (500, b"oops"),
    (200, b"not json"),
    (200, b'{"status": "idle"}'),
    (200, b'{"writing": "false"}'),
    (200, b'{"writing": true}'),
])
def test_the_cli_refuses_unless_the_backend_clearly_says_sleep_is_not_writing(bank, monkeypatch, status, body):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    head = _git(bank, "rev-parse", "HEAD")
    server = _serve(monkeypatch, status, body)
    try:
        assert claim_recovery.main(["--bank", str(bank), "--apply"]) == 3
    finally:
        server.shutdown()
    assert _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""


def test_the_cli_refuses_when_no_backend_answers(bank, monkeypatch):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    monkeypatch.setenv("CICADA_PORT", str(_free_port()))
    assert claim_recovery.main(["--bank", str(bank), "--apply"]) == 3


def test_the_cli_applies_when_the_backend_says_sleep_is_not_writing(bank, monkeypatch, capsys):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    server = _serve(monkeypatch, 200, b'{"status": "idle", "writing": false}')
    try:
        assert claim_recovery.main(["--bank", str(bank), "--apply"]) == 0
    finally:
        server.shutdown()
    assert _claims_now(bank)[c2.id].valid_to == DROP_DAY
    printed = capsys.readouterr().out
    assert "restored as history: 1 entries" in printed and c2.text not in printed


def test_two_concurrent_applies_restore_once(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    head = _git(bank, "rev-parse", "HEAD").strip()
    results: list[int] = []
    workers = [threading.Thread(target=lambda: results.append(claim_recovery.apply(bank).recovered)) for _ in range(2)]
    for t in workers:
        t.start()
    for t in workers:
        t.join(30)
    assert sorted(results) == [0, 1]
    assert _git(bank, "rev-list", "--count", f"{head}..HEAD").strip() == "1"
    assert [c.id for c in _claims_now(bank).values()].count(c2.id) == 1


# --- fix round 2: later writers never reopen recovered history; unreadable pages are read as YAML ---------------


class _InboxSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


def _recover_replaced(bank: Path) -> tuple[Claim, Claim]:
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    successor = _restated(c2, 9)
    _drop(bank, [c1, successor])
    assert claim_recovery.apply(bank).recovered == 1
    assert _claims_now(bank)[c2.id].recovered_by == "claim_recovery"
    return c2, successor


def test_a_decay_keep_active_never_reopens_a_recovered_entry(bank):
    import asyncio

    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    old, successor = _recover_replaced(bank)
    (bank / "inbox").mkdir()
    (bank / "inbox" / "inbox-030.md").write_text(
        f"---\nkind: decay\nrequired_input: choice\nstatus: pending\npriority: 0.3\nentity_id: alpha-project\n"
        f"entity_name: Alpha Project\ntitle: Still true?\ncreated_date: 2026-10-01\nclaim_id: {old.id}\n"
        f"trigger: sleep/decay\n---\n", encoding="utf-8")
    _commit(bank, "Sleep cycle 2026-10-01", ["inbox/inbox-030.md"])
    before = raw_claim_entries((bank / PAGE).read_text(encoding="utf-8"))

    asyncio.run(inbox_service.resolve("inbox-030", InboxResolveRequest(action="keep_active"), _InboxSettings(bank)))

    now = _claims_now(bank)
    assert now[old.id].valid_to == DROP_DAY and now[old.id].recovered_by == "claim_recovery", "still history"
    assert now[successor.id].valid_to is None, "the current successor is what stays current"
    assert [e for e in raw_claim_entries((bank / PAGE).read_text(encoding="utf-8")) if e["id"] == old.id] == \
        [e for e in before if e["id"] == old.id], "the recovered entry is not touched at all"


def test_a_paper_sync_asserts_afresh_and_never_reopens_a_recovered_entry(bank):
    from api.services import papers

    cid = papers.claim_id("alpha-project", "annotates", "tool-2", "agent", "notes")
    old = _claim(2, id=cid, predicate="annotates", origin=papers.ORIGIN)
    _seed(bank, [_claim(1), old])
    _drop(bank, [_claim(1), _claim(9, predicate="annotates", object="tool-2")])
    assert claim_recovery.apply(bank).recovered == 1
    desired = _claim(2, id=cid, predicate="annotates", origin=papers.ORIGIN, valid_from=None,
                     evidence=[evidence.reasoning(EP)], source_episodes=[EP])

    assert papers.apply_claims(bank / PAGE, EP, [desired], "2026-10-05") is True
    copies = [c for c in parse_claims(markdown_parser.parse(bank / PAGE).body, strict=True) if c.id == cid]
    assert [(c.valid_to, c.recovered_by) for c in copies] == [(DROP_DAY, "claim_recovery"), (None, None)], \
        "the history stays closed; the source's assertion is a fresh entry"
    assert papers.apply_claims(bank / PAGE, EP, [desired], "2026-10-06") is False, "a re-sync matches the fresh one"


def test_every_reopen_in_the_code_consults_the_recovered_history_test():
    """A writer that clears `valid_to` must first ask `claims.is_recovered_history` (G148): recovered history is
    never reopened, by any writer, however it learned the id."""
    import re as _re

    root = Path(__file__).resolve().parents[2]
    reopen = _re.compile(r"\.valid_to\s*=\s*None\b")
    sites = []
    for path in sorted((root / "api").rglob("*.py")) + sorted((root / "mcp").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "/tests/" in rel or ".venv" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        if reopen.search(text):
            sites.append(rel)
            assert "is_recovered_history" in text, f"{rel} reopens a claim without asking is_recovered_history"
    assert sites == ["api/services/inbox_service.py", "api/services/papers.py"], sites


def test_an_escaped_id_in_a_readable_yaml_of_an_unreadable_page_counts_as_present(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    escaped = "".join(f"\\u{ord(ch):04x}" for ch in c2.id)
    other = bank / "entities" / "bob-example.md"   # two fences: unreadable for a writer, both still YAML
    other.write_text(f"---\nid: bob-example\n---\n\n```claims\n- id: x-1\n  text: one\n```\n\n"
                     f"```claims\n- id: \"{escaped}\"\n  text: two\n```\n", encoding="utf-8")
    _commit(bank, "Memory update 2026-10-03", ["entities/bob-example.md"], author="user")
    assert c2.id not in other.read_text(encoding="utf-8")
    assert _counts(bank)["candidates"] == 0, "the id is on a page — trapped, not lost"
    assert claim_recovery.apply(bank).recovered == 0


def test_an_unreadable_page_whose_yaml_will_not_load_blocks_every_recovery(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    escaped = "".join(f"\\u{ord(ch):04x}" for ch in c2.id)
    other = bank / "entities" / "bob-example.md"
    other.write_text(f"---\nid: bob-example\n---\n\n```claims\n- id: \"{escaped}\"\n  text: [unclosed\n```\n",
                     encoding="utf-8")
    _commit(bank, "Memory update 2026-10-03", ["entities/bob-example.md"], author="user")
    assert _counts(bank)["excluded"] == {"unreadable_elsewhere": 1}, "presence cannot be proven: fail closed"
    assert claim_recovery.apply(bank).recovered == 0


def test_a_retraction_record_in_an_unreadable_but_loadable_page_still_excludes(bank):
    c1, c2 = _claim(1), _claim(2)
    _seed(bank, [c1, c2])
    _drop(bank, [c1, _restated(c2, 9)])
    escaped = "".join(f"\\u{ord(ch):04x}" for ch in c2.id)
    other = bank / "entities" / "bob-example.md"
    other.write_text(f"---\nid: bob-example\n---\n\n```claims\n- id: r-1\n  text: why\n  predicate: retracts\n"
                     f"  object: \"{escaped}\"\n", encoding="utf-8")   # unterminated, but its YAML loads
    _commit(bank, "Memory update 2026-10-03", ["entities/bob-example.md"], author="user")
    assert _counts(bank)["excluded"] == {"retracted": 1}


def test_a_recovered_entry_is_never_current(bank):
    """#216's one current-belief test: a recovered entry is history by its close and by its marker alone."""
    from api.services.claims import is_current

    old, successor = _recover_replaced(bank)
    now = _claims_now(bank)
    assert is_current(now[successor.id]) and not is_current(now[old.id])
    stripped = Claim.from_dict({**now[old.id].to_dict(), "valid_to": None})
    assert not is_current(stripped) and not is_current(stripped.to_dict())
