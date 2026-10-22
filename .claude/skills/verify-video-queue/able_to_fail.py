"""Prove each passing property can fail on the real code.

For every scratch break: edit api/services/video_queue.py, show a real test fail, show the mirrored
`break-*` model check fail, restore the file byte for byte, show the real test pass again.

Usage, from the repo root: python3 .claude/skills/verify-video-queue/able_to_fail.py [break-name ...]
PYTHON names the interpreter that has the backend's dependencies (default api/.venv/bin/python)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TARGET = ROOT / "api/services/video_queue.py"
QUEUE_TESTS = "api/tests/test_video_queue.py"
FORMAL_TESTS = "api/tests/test_video_queue_formal.py"

# name -> (text in video_queue.py, its broken replacement, the real test that must fail)
BREAKS = {
    "lapse_ignores_lease": (
        '    return lease is None or lease <= now\n',
        '    return True\n',
        f"{QUEUE_TESTS}::test_a_lease_is_never_given_twice"),
    "nolock": (
        '        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)\n',
        '        pass\n',
        f"{FORMAL_TESTS}::test_p1_two_claimers_that_read_at_once_never_share_a_video"),
    "no_lapse": (
        '    if row["state"] != "claimed":\n        return False\n    lease = _parse(row.get("lease_until"))\n',
        '    return False\n    lease = _parse(row.get("lease_until"))\n',
        f"{QUEUE_TESTS}::test_a_lapse_returns_the_video_with_one_more_attempt_and_the_third_fails_it"),
    "no_fail_expiry": (
        '    return stamp + timedelta(days=EXPIRE_FAILED_DAYS) if stamp else None\n',
        '    return None\n',
        f"{QUEUE_TESTS}::test_failed_rows_and_finished_batches_expire_in_memory_and_persist_only_on_a_write"),
    "record_ignores_session": (
        '            done = row["state"] == "claimed" and bool(session) and row.get("session") == session\n',
        '            done = row["state"] == "claimed"\n',
        f"{QUEUE_TESTS}::test_the_satisfaction_table"),
    "stays_counts_attempt": (
        '        if not done:\n            _write(target, rows, batches)\n',
        '        if not done:\n            row["attempts"] = int(row.get("attempts") or 0) + 1\n'
        '            _write(target, rows, batches)\n',
        f"{FORMAL_TESTS}::test_p6_releasing_or_recording_twice_leaves_the_queue_as_once"),
    "settle_ignores_holding": (
        '    if lapsed and not (holding is not None and holding()):\n',
        '    if lapsed:\n',
        f"{QUEUE_TESTS}::test_lease_not_judged_while_pages_held"),
    "settle_ignores_records": (
        '            if video_state.satisfies(mine, row["want"], since=row.get("requested_at")):\n',
        '            if False:\n',
        f"{QUEUE_TESTS}::test_a_lapse_with_a_newer_satisfying_record_closes_the_entry_as_done"),
    "claim_takes_failed": (
        '        queued = sorted((r for r in rows if r["state"] == "queued" and r["key"] in saved)',
        '        queued = sorted((r for r in rows if r["state"] in ("queued", "failed") and r["key"] in saved)',
        f"{FORMAL_TESTS}::test_p11_a_failed_video_waits_for_the_person"),
    "put_restarts_claimed": (
        '    if row["state"] == "failed":\n        _reset(row)\n',
        '    if row["state"] in ("failed", "claimed"):\n        _reset(row)\n',
        f"{QUEUE_TESTS}::test_handoff_waiting_count_matches_the_shared_cases"),
}


def pytest_ok(node: str) -> bool:
    python = os.environ.get("PYTHON") or str(ROOT / "api/.venv/bin/python")
    run = subprocess.run([python, "-m", "pytest", node, "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                         capture_output=True, text=True)
    return run.returncode == 0


def model_check(name: str) -> str:
    run = subprocess.run([str(HERE / "run.sh"), "--only", f"break-{name}"], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "ALLOW_DRIFT": "1"})
    line = next((ln for ln in run.stdout.splitlines() if ln.startswith(f"break-{name}")), run.stdout + run.stderr)
    return ("caught: " if run.returncode == 0 else "NOT CAUGHT: ") + " ".join(line.split())


def main(names: list[str]) -> int:
    original = TARGET.read_bytes()
    failures = 0
    try:
        for name in names or list(BREAKS):
            old, new, node = BREAKS[name]
            text = original.decode("utf-8")
            if text.count(old) != 1:
                print(f"{name}: the code moved; update BREAKS before trusting this run")
                failures += 1
                continue
            TARGET.write_text(text.replace(old, new), encoding="utf-8")
            broken_fails = not pytest_ok(node)
            verdict = model_check(name)
            TARGET.write_bytes(original)
            restored_passes = pytest_ok(node)
            ok = broken_fails and verdict.startswith("caught") and restored_passes
            failures += not ok
            print(f"{name}: real test {'fails' if broken_fails else 'STILL PASSES'} when broken, "
                  f"{'passes' if restored_passes else 'FAILS'} when restored; model {verdict}")
    finally:
        TARGET.write_bytes(original)
    print("video_queue.py restored byte for byte" if TARGET.read_bytes() == original else "RESTORE FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
