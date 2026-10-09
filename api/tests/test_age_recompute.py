"""The one-shot recompute that charges an existing bank the age of what it came from (owner ruling 2026-10-09;
``age_recompute``, ``api/scripts/recompute_decay_by_age.py``). Synthetic banks only."""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

from api.models.schemas import DecayClass
from api.scripts import recompute_decay_by_age as script
from api.services import age_recompute as recompute
from api.services import conflict_resolver, decay_policy, markdown_parser
from api.services.claims import parse_claims, raw_claim_entries

TODAY = date(2026, 10, 9)
ADDED = "2026-10-07T12:00:00+00:00"   # the day the synthetic bank was consolidated (its seed commit)


def _git(path: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}).stdout


def _page(bank: Path, page_id: str, said: str | None, *, conf: float = 0.99, kind: str = "concept",
          weeks: list[str] | None = None, body: str = "## Summary\nA synthetic thing.\n", **extra) -> Path:
    fm = {"name": page_id, "type": kind, "status": "active", "confidence": conf, "created": said or "2026-10-07",
          "decayed_through": "2026-10-08", **decay_policy.frontmatter_fields(decay_policy.default_class_for(kind)),
          "source_episodes": [f"ep_{d}_001" for d in (weeks or ([said] if said else []))], **extra}
    if said:
        fm["last_referenced"] = said
    path = bank / "entities" / f"{page_id}.md"
    markdown_parser.write(path, fm, body)
    return path


CLAIMS_BODY = (
    "## Summary\nA synthetic thing.\n\n```claims\n"
    + json.dumps({"id": "clm_old", "text": "old fact", "subject": "with-claims", "predicate": "uses",
                  "object": "postgres", "confidence": 0.9, "recorded_at": "2026-10-07", "decayed_through": "2026-10-08",
                  "source_episodes": ["ep_2024-03-05_001"], "x_custom": 1}) + "\n"
    + json.dumps({"id": "clm_live", "text": "live fact", "subject": "with-claims", "predicate": "uses",
                  "object": "sqlite", "confidence": 0.9, "recorded_at": "2026-10-07", "decayed_through": "2026-10-08",
                  "source_episodes": ["ep_2026-10-07_001"]}) + "\n```\n"
)


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    root = tmp_path / "bank"
    (root / "entities").mkdir(parents=True)
    (root / "episodes").mkdir()
    markdown_parser.write(root / "episodes" / "ep_2024-05-01_001.md",
                          {"id": "ep_2024-05-01_001", "source": "claude_memory"}, "Facts.\n")
    _page(root, "script-2024", "2024-03-05")
    _page(root, "quarter-old", "2026-07-12")
    _page(root, "eleven-days", "2026-09-28")
    _page(root, "said-after-added", "2026-10-08")
    spaced = ["2026-04-13", "2026-04-20", "2026-04-27", "2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25",
              "2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29"]
    _page(root, "spaced", spaced[-1], weeks=spaced)
    _page(root, "once", spaced[-1])
    _page(root, "saved-article", "2024-03-05", kind="media")
    _page(root, "owner-example", "2024-03-05", kind="person", owner=True,
          **decay_policy.frontmatter_fields(DecayClass.evergreen))
    _page(root, "export-only", None, weeks=["2024-05-01"])
    _page(root, "already-archived", "2024-03-05", conf=0.1, status="archived")
    _page(root, "with-claims", "2026-10-07", body=CLAIMS_BODY)
    _page(root, "edited-by-hand", "2024-03-05")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Synthetic")
    _git(root, "config", "user.email", "synthetic@example.com")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed", env={"GIT_COMMITTER_DATE": ADDED, "GIT_AUTHOR_DATE": ADDED})
    # A hand edit not yet committed: never touched.
    path = root / "entities" / "edited-by-hand.md"
    path.write_text(path.read_text() + "\nA note.\n")
    return root


def _fm(bank: Path, page_id: str) -> dict:
    return markdown_parser.parse(bank / "entities" / f"{page_id}.md").frontmatter


def test_the_dry_run_counts_by_type_and_age_and_writes_nothing(bank):
    before = {p.name: p.read_text() for p in (bank / "entities").glob("*.md")}
    counts = recompute.survey(bank, today=TODAY).counts()
    assert {p.name: p.read_text() for p in (bank / "entities").glob("*.md")} == before

    assert counts["eligible"] == 7 and counts["dirty"] == 1
    assert counts["lowered"] == 5                     # said-after-added was read live; with-claims is fresh
    assert counts["would_archive"] == 1               # script-2024
    assert counts["would_decay_quietly"] == 2         # quarter-old, once — heard late: no question
    assert counts["would_be_asked"] == 0
    assert counts["claims_lowered"] == 1 and counts["claims_below_nudge"] == 1
    assert counts["learned_from_git"] == 7 and counts["learned_without_git"] == 0
    assert counts["by_age"]["over_1_year"] == {"pages": 1, "lowered": 1, "archive": 1, "decaying": 0}
    assert counts["by_age"]["3_to_12_months"] == {"pages": 2, "lowered": 2, "archive": 0, "decaying": 1}
    assert counts["by_age"]["under_3_months"] == {"pages": 4, "lowered": 2, "archive": 0, "decaying": 1}
    assert counts["by_type"]["concept"]["lowered"] == 5
    text = json.dumps(counts)
    assert "script-2024" not in text and "spaced" not in text, "counts only, never a page name"


def test_apply_charges_once_in_one_commit_and_a_second_run_changes_nothing(bank):
    result = recompute.apply(bank, sleep_running=lambda: False, today=TODAY)
    assert result.written == 6 and result.committed   # five pages lowered + the page whose claim was lowered
    assert len(_git(bank, "log", "--format=%H").split()) == 2
    assert _git(bank, "log", "-1", "--format=%s") == "Decay by age: 6 page(s)\n"
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%b")
    assert _git(bank, "status", "--porcelain").strip() == "M entities/edited-by-hand.md"

    old = _fm(bank, "script-2024")
    assert old["status"] == "archived" and old["confidence"] == 0.0
    assert str(old["learned_on"]) == "2026-10-07" and str(old["decayed_through"]) == "2026-10-08"
    assert (bank / "entities" / "script-2024.md").exists(), "archived, never removed"
    quarter = _fm(bank, "quarter-old")
    weeks = (date(2026, 10, 7) - date(2026, 7, 12)).days / 7
    assert math.isclose(quarter["confidence"], 0.99 - 0.05 * weeks, abs_tol=1e-9) and quarter["status"] == "decaying"
    spaced, once = _fm(bank, "spaced"), _fm(bank, "once")
    assert spaced["status"] == "active" and once["status"] == "decaying"
    assert spaced["confidence"] > once["confidence"], "twelve weeks of mentions fade slower than one"
    for untouched in ("said-after-added", "saved-article", "owner-example", "export-only", "already-archived"):
        assert "learned_on" not in _fm(bank, untouched), untouched
    assert _fm(bank, "saved-article")["confidence"] == 0.99 and _fm(bank, "owner-example")["confidence"] == 0.99

    body = markdown_parser.parse(bank / "entities" / "with-claims.md").body
    by_id = {c.id: c for c in parse_claims(body)}
    assert by_id["clm_old"].confidence == 0.0 and by_id["clm_live"].confidence == 0.9
    raw = {e["id"]: e for e in raw_claim_entries(body)}
    assert raw["clm_old"]["x_custom"] == 1, "a claim line is rewritten without losing a field"
    assert str(_fm(bank, "with-claims")["learned_on"]) == "2026-10-07"

    again = recompute.survey(bank, today=TODAY).counts()
    assert again["lowered"] == 0 and again["claims_lowered"] == 0


def test_after_the_recompute_sleep_never_charges_the_gap_again(bank):
    recompute.apply(bank, sleep_running=lambda: False, today=TODAY)
    before = _fm(bank, "eleven-days")
    existing = [{"id": "eleven-days", "frontmatter": before, "body": ""}]

    class _Settings:
        memory_path = bank
        archive_threshold = 0.2
        decay_nudge_threshold = 0.4

    changes = asyncio.run(conflict_resolver.resolve_and_prune(
        [], existing, _Settings(), now=datetime(2026, 10, 9, 3, 0), tuning={}))
    (change,) = changes
    # One live day (the watermark was the 8th), nothing for the eleven days already charged.
    assert math.isclose(change["new_confidence"], before["confidence"] - 0.05 / 7, abs_tol=1e-9)
    assert change["action"] == "decay"


def test_without_git_the_watermark_is_the_estimate_and_the_count_says_so(tmp_path):
    root = tmp_path / "bank"
    (root / "entities").mkdir(parents=True)
    _page(root, "script-2024", "2024-03-05")
    counts = recompute.survey(root, today=TODAY).counts()
    assert counts["learned_without_git"] == 1 and counts["would_archive"] == 1


def test_apply_is_refused_while_sleep_runs(bank):
    before = (bank / "entities" / "script-2024.md").read_text()
    with pytest.raises(recompute.SleepRunning):
        recompute.apply(bank, sleep_running=lambda: True, today=TODAY)
    assert (bank / "entities" / "script-2024.md").read_text() == before


def test_the_script_is_a_dry_run_unless_told_and_refuses_when_the_backend_is_not_idle(bank, monkeypatch, capsys):
    assert script.main(["--bank", str(bank)]) == 0
    assert json.loads(capsys.readouterr().out)["lowered"] == 5
    assert _fm(bank, "script-2024")["status"] == "active"
    monkeypatch.setattr(script, "backend_running", lambda: True)
    assert script.main(["--bank", str(bank), "--apply"]) == 3
    assert "refused" in json.loads(capsys.readouterr().out)
    assert script.main(["--bank", str(bank / "nowhere")]) == 2
