"""ROR-129 — the one-time reset of facts' clocks by real age: dry run counts, apply is one commit, a second run is a no-op."""
from __future__ import annotations

import json
import subprocess
from datetime import date

import pytest

from api.scripts import reset_fact_clocks
from api.services import claims as claims_mod, fact_clock_reset, markdown_parser
from api.services.claims import Claim

TODAY = date(2026, 11, 6)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _page(repo, pid, fm, cs):
    markdown_parser.write(repo / "entities" / f"{pid}.md", fm, claims_mod.write_claims("# P\n", cs))


def _fact(cid, **kw):
    base = dict(id=cid, text=f"fact {cid}", subject="owner", predicate="holds", object="x", confidence=0.8,
                valid_from="2022-01-01", recorded_at="2026-10-08", decayed_through="2026-10-08",
                source_episodes=["ep_2022-03-01_001"])
    base.update(kw)
    return Claim(**base)


@pytest.fixture
def bank(tmp_path):
    repo = tmp_path / "bank"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@cicada.local")
    _git(repo, "config", "user.name", "T")
    _page(repo, "owner", {"name": "Owner", "type": "person", "status": "active", "decay_class": "evergreen",
                          "decay_rate": 0.0}, [
        _fact("old"),                                               # said 2022, read 2026-10-08, never charged
        _fact("kept", decay_class="evergreen", class_by="user"),    # never fades: untouched
        _fact("export", source_episodes=[]),                        # no dated conversation: no age to count
    ])
    _page(repo, "a-book", {"name": "A Book", "type": "media", "status": "active", "decay_class": "evergreen"},
          [_fact("m", subject="a-book")])                           # a media page's facts never fade
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _conf(repo, pid, cid):
    page = markdown_parser.parse(repo / "entities" / f"{pid}.md")
    return next(c for c in claims_mod.parse_claims(page.body) if c.id == cid)


def test_the_dry_run_counts_and_writes_nothing(bank):
    head = _git(bank, "rev-parse", "HEAD")
    counts = fact_clock_reset.survey(bank, today=TODAY).counts()
    assert counts["claims_lowered"] == 1 and counts["eligible"] == 1
    assert _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""
    assert _conf(bank, "owner", "old").confidence == 0.8


def test_apply_charges_the_real_age_once_in_one_commit(bank):
    result = fact_clock_reset.apply(bank, sleep_running=lambda: False, today=TODAY)
    assert result.committed and result.written == 1
    old = _conf(bank, "owner", "old")
    assert old.confidence < 0.8 and old.decayed_through >= "2026-10-08"
    assert _conf(bank, "owner", "kept").confidence == 0.8                # a kept fact is never charged
    assert _conf(bank, "owner", "export").confidence == 0.8              # no dated conversation: left alone
    assert _conf(bank, "a-book", "m").confidence == 0.8                  # a media page's fact: artifacts
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    again = fact_clock_reset.apply(bank, sleep_running=lambda: False, today=TODAY)
    assert again.written == 0 and not again.committed and again.already_by_age == 1


def test_it_refuses_while_sleep_runs(bank):
    with pytest.raises(fact_clock_reset.SleepRunning):
        fact_clock_reset.apply(bank, sleep_running=lambda: True, today=TODAY)


def test_the_script_is_a_dry_run_unless_told(bank, capsys):
    assert reset_fact_clocks.main(["--bank", str(bank)]) == 0
    assert json.loads(capsys.readouterr().out)["claims_lowered"] == 1
    assert _conf(bank, "owner", "old").confidence == 0.8
