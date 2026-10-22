"""Prove each passing property can fail on the real code, without touching the working tree.

For every scratch break, in a temporary copy of the tree: edit api/services/video_queue.py, show a real test
fail, show coverage.py exit 3 naming the edited function (so run.sh would refuse to call the model current), show
the mirrored `break-*` model check fail, restore the file, and show the real test pass again. The working tree's
video_queue.py is hashed before and after; any difference fails the run.

Usage, from the repo root: python3 .claude/skills/verify-video-queue/able_to_fail.py [break-name ...]
PYTHON names the interpreter that has the backend's dependencies (default: api/.venv/bin/python in this checkout,
else in the main checkout of a worktree)."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SKILL = HERE.relative_to(ROOT)
TARGET = "api/services/video_queue.py"
QUEUE_TESTS = "api/tests/test_video_queue.py"
FORMAL_TESTS = "api/tests/test_video_queue_formal.py"
COPIED = ["api", "mcp", "plugins", str(SKILL)]

# name -> (the function the edit lands in, text in video_queue.py, its broken replacement, the real test that fails)
BREAKS = {
    "lapse_ignores_lease": (
        "_lapsed",
        '    return lease is None or lease <= now\n',
        '    return True\n',
        f"{QUEUE_TESTS}::test_a_lease_is_never_given_twice"),
    "nolock": (
        "_locked",
        '        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)\n',
        '        pass\n',
        f"{FORMAL_TESTS}::test_p1_two_claimers_that_read_at_once_never_share_a_video"),
    "no_lapse": (
        "_lapsed",
        '    if row["state"] != "claimed":\n        return False\n    lease = _parse(row.get("lease_until"))\n',
        '    return False\n    lease = _parse(row.get("lease_until"))\n',
        f"{QUEUE_TESTS}::test_a_lapse_returns_the_video_with_one_more_attempt_and_the_third_fails_it"),
    "no_fail_expiry": (
        "_failed_expiry",
        '    return stamp + timedelta(days=EXPIRE_FAILED_DAYS) if stamp else None\n',
        '    return None\n',
        f"{QUEUE_TESTS}::test_failed_rows_and_finished_batches_expire_in_memory_and_persist_only_on_a_write"),
    "record_ignores_token": (
        "complete",
        '            done = row["state"] == "claimed" and _token_matches(row, lease_token)\n',
        '            done = row["state"] == "claimed"\n',
        f"{QUEUE_TESTS}::test_the_satisfaction_table"),
    "release_ignores_token": (
        "release",
        '            if not _token_matches(row, item.get("lease_token")):\n',
        '            if False:\n',
        f"{FORMAL_TESTS}::test_f1_a_session_cannot_hand_back_another_sessions_lease"),
    "no_lease_cap": (
        "_refresh",
        '            until = min(now + timedelta(minutes=LEASE_MINUTES), cap)\n',
        '            until = now + timedelta(minutes=LEASE_MINUTES)\n',
        f"{FORMAL_TESTS}::test_f4_a_session_that_keeps_calling_holds_a_lease_at_most_three_periods"),
    "stays_counts_attempt": (
        "complete",
        '        if not done:\n            _write(target, rows, batches)\n',
        '        if not done:\n            row["attempts"] = int(row.get("attempts") or 0) + 1\n'
        '            _write(target, rows, batches)\n',
        f"{FORMAL_TESTS}::test_p6_releasing_or_recording_twice_leaves_the_queue_as_once"),
    "settle_ignores_holding": (
        "_settle",
        '    if lapsed and not (holding is not None and holding()):\n',
        '    if lapsed:\n',
        f"{QUEUE_TESTS}::test_lease_not_judged_while_pages_held"),
    "settle_ignores_records": (
        "_settle",
        '            if video_state.satisfies(mine, row["want"], since=row.get("requested_at")):\n',
        '            if False:\n',
        f"{QUEUE_TESTS}::test_a_lapse_with_a_newer_satisfying_record_closes_the_entry_as_done"),
    "claim_takes_failed": (
        "claim",
        '        queued = sorted((r for r in rows if r["state"] == "queued" and r["key"] in saved)',
        '        queued = sorted((r for r in rows if r["state"] in ("queued", "failed") and r["key"] in saved)',
        f"{FORMAL_TESTS}::test_p11_a_failed_video_waits_for_the_person"),
    "put_restarts_claimed": (
        "_upsert",
        '    if row["state"] == "failed":\n        _reset(row)\n',
        '    if row["state"] in ("failed", "claimed"):\n        _reset(row)\n',
        f"{QUEUE_TESTS}::test_handoff_waiting_count_matches_the_shared_cases"),
}


def python() -> str:
    if os.environ.get("PYTHON"):
        return os.environ["PYTHON"]
    here = ROOT / "api/.venv/bin/python"
    if here.exists():
        return str(here)
    common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"], capture_output=True,
                            text=True).stdout.strip()
    return str((ROOT / common).resolve().parent / "api/.venv/bin/python")


def copy_tree(dest: Path) -> None:
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", *COPIED],
                            capture_output=True, text=True, check=True).stdout.splitlines()
    for rel in listed:
        src = ROOT / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)


def pytest_ok(tree: Path, node: str) -> bool:
    run = subprocess.run([python(), "-m", "pytest", node, "-q", "-p", "no:cacheprovider"], cwd=tree,
                         capture_output=True, text=True)
    return run.returncode == 0


def coverage_names(tree: Path, function: str) -> bool:
    """coverage.py exits 3 and the definitions it lists as changed are exactly the edited one."""
    run = subprocess.run([sys.executable, "-I", str(tree / SKILL / "coverage.py")], cwd=tree, capture_output=True,
                         text=True)
    listed, section = set(), None
    for line in run.stdout.splitlines():
        if not line.startswith("  "):
            section = line
        elif section and section.startswith("Covered code changed"):
            listed.add(line.strip())
    return run.returncode == 3 and listed == {f"video_queue::{function}"}


def model_check(tree: Path, name: str) -> str:
    run = subprocess.run([str(tree / SKILL / "run.sh"), "--only", f"break-{name}"], cwd=tree, capture_output=True,
                         text=True, env={**os.environ, "ALLOW_DRIFT": "1"})
    line = next((ln for ln in run.stdout.splitlines() if ln.startswith(f"break-{name}")), run.stdout + run.stderr)
    return ("caught: " if run.returncode == 0 else "NOT CAUGHT: ") + " ".join(line.split())


def main(names: list[str]) -> int:
    real = ROOT / TARGET
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    failures = 0
    with tempfile.TemporaryDirectory(prefix="vq-able-to-fail-") as tmp:
        tree = Path(tmp)
        copy_tree(tree)
        target = tree / TARGET
        original = target.read_bytes()
        for name in names or list(BREAKS):
            function, old, new, node = BREAKS[name]
            text = original.decode("utf-8")
            if text.count(old) != 1:
                print(f"{name}: the code moved; update BREAKS before trusting this run")
                failures += 1
                continue
            target.write_text(text.replace(old, new), encoding="utf-8")
            broken_fails = not pytest_ok(tree, node)
            drift_named = coverage_names(tree, function)
            verdict = model_check(tree, name)
            target.write_bytes(original)
            restored_passes = pytest_ok(tree, node)
            ok = broken_fails and drift_named and verdict.startswith("caught") and restored_passes
            failures += not ok
            print(f"{name}: real test {'fails' if broken_fails else 'STILL PASSES'} when broken, "
                  f"{'passes' if restored_passes else 'FAILS'} when restored; coverage.py "
                  f"{'names ' + function if drift_named else 'DOES NOT NAME ' + function}; model {verdict}")
    after = hashlib.sha256(real.read_bytes()).hexdigest()
    print("working tree untouched" if after == before else "THE WORKING TREE'S video_queue.py CHANGED")
    return 1 if failures or after != before else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
