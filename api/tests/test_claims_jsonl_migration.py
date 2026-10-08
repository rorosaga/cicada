"""The one-time conversion of a bank's legacy YAML claims fences to JSON Lines (DECIDE-1).

Counts only in the dry run; one `cicada` commit on apply; every claim reads back the same, unknown fields kept, the
prose and frontmatter byte-identical (so every evidence span still points at the same text); never while Sleep holds
the pages or runs; never on a page with uncommitted changes; never automatically.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from api.services import claims, claims_jsonl_migration as mig, evidence, sleep_cycle, write_admission
from api.services.claims import Claim, Evidence
from api.tests.test_claims_jsonl import legacy_fence

PROSE = "## Summary\nAlpha-project is a synthetic fixture.\n"
FM = "---\nname: {name}\ntype: project\nstatus: active\n---\n\n"
LEGACY_EXTRA = ("```claims\n- id: clm_hand\n  text: hand edited\n  subject: beta-project\n  valid_from: 2026-10-01\n"
                "  future_field:\n    kept: true\n```")


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=bank, check=True, capture_output=True, text=True).stdout


def _rows(stem: str, n: int) -> list[Claim]:
    return [Claim(id=f"clm_{stem}_{i}", text=f"{stem} fact “{i}” — ünïcode", subject=stem, predicate="uses",
                  object=f"tool-{i}", valid_from="2026-10-01", session_ids=["ses_a"],
                  evidence=[Evidence(episode="ep_2026-10-01_001", start=3, end=20, kind="user", hash="abcdef012345")])
            for i in range(n)]


@pytest.fixture
def bank(tmp_path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    pages = {
        "alpha-project": FM.format(name="Alpha") + PROSE + "\n" + legacy_fence(_rows("alpha-project", 3)) + "\n",
        "beta-project": FM.format(name="Beta") + PROSE + "\n" + LEGACY_EXTRA + "\n\n## Links\n- after the fence\n",
        "gamma-project": FM.format(name="Gamma") + claims.write_claims(PROSE, _rows("gamma-project", 2)),
        "delta-project": FM.format(name="Delta") + PROSE,
        "empty-project": FM.format(name="Empty") + PROSE + "\n```claims\n[]\n```\n",
        "broken-project": FM.format(name="Broken") + PROSE + "\n```claims\n- id: [unterminated\n```\n",
    }
    for stem, text in pages.items():
        (bank / "entities" / f"{stem}.md").write_text(text, encoding="utf-8")
    _git(bank, "init", "-q")
    _git(bank, "config", "user.name", "Test")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed\n\nCicada-Author: user")
    return bank


def _snapshot(bank: Path) -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((bank / "entities").glob("*.md"))}


def test_the_dry_run_reports_counts_and_touches_nothing(bank):
    before, head = _snapshot(bank), _git(bank, "rev-parse", "HEAD")
    counts = mig.survey(bank).counts()
    assert counts == {"pages": 6, "no_fence": 1, "jsonl": 1, "legacy": 2, "legacy_claims": 4, "empty": 1,
                      "unreadable": 1, "not_equivalent": 0, "dirty": 0, "converted": 0, "committed": False}
    assert _snapshot(bank) == before and _git(bank, "rev-parse", "HEAD") == head


def test_apply_converts_in_one_cicada_commit_and_every_claim_reads_the_same(bank):
    before = _snapshot(bank)
    result = mig.apply(bank, sleep_running=lambda: False)
    assert result.converted == 2 and result.committed
    after = _snapshot(bank)
    for name in before:
        assert claims.parse_claims(after[name]) == claims.parse_claims(before[name]), name
        # Prose and frontmatter byte-identical: an evidence span into the page reads the same text.
        assert claims.strip_claims_block(after[name]) == claims.strip_claims_block(before[name]), name
        assert evidence.body_hash(claims.strip_claims_block(after[name])) == \
            evidence.body_hash(claims.strip_claims_block(before[name]))
    for name in ("gamma-project.md", "delta-project.md", "empty-project.md", "broken-project.md"):
        assert after[name] == before[name], name
    beta = claims.raw_claim_entries(after["beta-project.md"])
    assert beta == [{"id": "clm_hand", "text": "hand edited", "subject": "beta-project", "valid_from": "2026-10-01",
                     "future_field": {"kept": True}}]
    assert after["beta-project.md"].endswith("```\n\n## Links\n- after the fence\n")
    alpha_fence = after["alpha-project.md"].split("```claims\n", 1)[1].split("\n```", 1)[0].split("\n")
    assert [json.loads(line)["id"] for line in alpha_fence] == [f"clm_alpha-project_{i}" for i in range(3)]
    # One commit, only the converted pages, authored cicada.
    log = _git(bank, "log", "-1", "--format=%B", "--name-only")
    assert "Cicada-Author: cicada" in log and "maintenance/claims-jsonl" in log
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == [
        "entities/alpha-project.md", "entities/beta-project.md"]
    assert _git(bank, "status", "--porcelain") == ""
    # A writer re-rendering a converted page changes nothing (no claim re-diffs).
    assert claims.write_claims(after["alpha-project.md"], claims.parse_claims(after["alpha-project.md"])) == \
        after["alpha-project.md"]
    # Run again: nothing left, no commit.
    head = _git(bank, "rev-parse", "HEAD")
    again = mig.apply(bank, sleep_running=lambda: False)
    assert again.converted == 0 and not again.committed and _git(bank, "rev-parse", "HEAD") == head


def test_apply_refuses_while_sleep_runs_or_holds_the_pages(bank, monkeypatch):
    before, head = _snapshot(bank), _git(bank, "rev-parse", "HEAD")
    with pytest.raises(mig.SleepRunning):
        mig.apply(bank, sleep_running=lambda: True)
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    with pytest.raises(mig.SleepRunning):
        mig.apply(bank, sleep_running=lambda: False)
    assert _snapshot(bank) == before and _git(bank, "rev-parse", "HEAD") == head
    assert write_admission.holders(bank) == 0


def test_a_page_with_uncommitted_changes_is_left_for_its_own_writer(bank):
    page = bank / "entities" / "alpha-project.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nA dirty edit.\n", encoding="utf-8")
    dirty = page.read_text(encoding="utf-8")
    result = mig.apply(bank, sleep_running=lambda: False)
    assert result.dirty == 1 and result.converted == 1
    assert page.read_text(encoding="utf-8") == dirty
    assert "entities/alpha-project.md" not in _git(bank, "show", "--name-only", "--format=", "HEAD")


def test_it_never_runs_automatically():
    services = Path(mig.__file__).parent
    callers = [p.name for p in [*services.glob("*.py"), *(services.parent / "routers").glob("*.py"),
                                services.parent / "main.py"]
               if p.name != "claims_jsonl_migration.py" and "claims_jsonl_migration" in p.read_text(encoding="utf-8")]
    assert callers == []


def test_the_command_dry_runs_by_default_and_prints_counts_only(bank, tmp_path):
    import sys

    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), "CICADA_HOME": str(tmp_path / "home" / ".cicada"),
           "CICADA_PORT": "9", "CICADA_TELEMETRY": "off"}
    repo = Path(__file__).resolve().parents[2]
    before = _snapshot(bank)
    dry = subprocess.run([sys.executable, "-m", "api.scripts.migrate_claims_jsonl", "--bank", str(bank)],
                         cwd=repo, env=env, capture_output=True, text=True, check=True)
    out = json.loads(dry.stdout)
    assert out["legacy"] == 2 and out["converted"] == 0 and _snapshot(bank) == before
    assert "alpha" not in dry.stdout and "alpha" not in dry.stderr
    applied = subprocess.run([sys.executable, "-m", "api.scripts.migrate_claims_jsonl", "--bank", str(bank),
                              "--apply"], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert json.loads(applied.stdout)["converted"] == 2
    missing = subprocess.run([sys.executable, "-m", "api.scripts.migrate_claims_jsonl", "--bank",
                              str(tmp_path / "nowhere")], cwd=repo, env=env, capture_output=True, text=True)
    assert missing.returncode == 2
