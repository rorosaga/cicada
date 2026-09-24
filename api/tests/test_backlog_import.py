"""G150 R-B15 — a markdown backlog in this repository's G-row shape files into a project's backlog, keeping ids
and states, and a second run changes nothing. The file below is SYNTHETIC, shaped like the real one."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from _synthetic_bank import _bank
from api.services import backlog, backlog_import, bank_index

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
ALL = ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
SYNTHETIC = """# Goal: an example backlog

## APPLY — buildable now

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G1 | **Cache the timeline** (bob-example 2026-08-01: "it's slow") | `_tree` re-reads pages; see PR #12. | ✅ shipped (PR #12) |
| G2 💸 | **Re-extract with a big model** | Costs a paid run \\| worth it later. | 🔲 |
| G3 | *(merged into [G1](#g1) — same fix)* | — | — |

## DESIGN — new structures (2026-08-20)

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G4 | **Pick a storage shape** | Two options. | ❓ |
| G5 | **Read the other system's docs** | Compare. | 🛠️ slice 1 ✅ (PR #30); slice 2 open |
| R1 | Not a G row | ignored | 🔲 |

### G6 — Write the assembly checklist 💸

Status: 🔬 researching
Step by step, with photos.

### G7: A section with no status
Plain body.
"""


@pytest.fixture
def bank(tmp_path):
    memory = _bank(tmp_path, git=False)
    bank_index.invalidate()
    return memory


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def test_the_file_reads_as_rows_of_one_prefix():
    rows = {r.id: r for r in backlog_import.parse(SYNTHETIC)}
    assert list(rows) == ALL
    assert rows["G1"].title == "Cache the timeline" and rows["G1"].created == "2026-08-01"
    assert rows["G1"].description.startswith('(bob-example 2026-08-01: "it\'s slow")')
    assert rows["G2"].paid and rows["G2"].description == "Costs a paid run | worth it later."
    assert rows["G3"].title == "merged into G1 — same fix"
    assert rows["G4"].created == "2026-08-20" and rows["G4"].triage is None
    assert rows["G6"].paid and rows["G6"].status_cell == "🔬 researching"
    assert rows["G6"].description == "Step by step, with photos." and rows["G6"].title == "Write the assembly checklist"
    assert rows["G7"].title == "A section with no status" and rows["G7"].description == "Plain body."
    assert [r.id for r in backlog_import.parse(SYNTHETIC, prefix="R")] == ["R1"]


@pytest.mark.parametrize("cell,expected", [
    ("✅ shipped", ("done", None)), ("🛠️ slice 1 ✅; slice 2 open", ("doing", None)), ("🔲", ("open", None)),
    ("❓", ("open", "decide")), ("🔬 researching", ("doing", "research")), ("🅿️ parked", ("open", None)),
    ("🟡 PJ-1 built", ("doing", None)), ("—", ("dropped", None)), ("**Closed 2026-09-01**", ("dropped", None)),
    ("", ("open", None)), ("see the notes", ("open", None)),
])
def test_the_first_mark_decides_the_status(cell, expected):
    assert backlog_import.status_of(cell) == expected


def test_an_import_keeps_ids_and_states_and_a_second_run_changes_nothing(bank):
    first = backlog_import.import_markdown(bank, project="alpha-project", text=SYNTHETIC, now=NOW, tz_name="UTC")
    assert (first.created, first.skipped, first.failed, first.error) == (ALL, [], [], None)
    items = {i.id: i for i in backlog.list_items(bank, "alpha-project")}
    assert {k: (v.status, v.triage, v.paid) for k, v in items.items()} == {
        "G1": ("done", "apply", False), "G2": ("open", "apply", True), "G3": ("dropped", "apply", False),
        "G4": ("open", "decide", False), "G5": ("doing", None, False), "G6": ("doing", "research", True),
        "G7": ("open", None, False)}
    g1 = backlog.get_item(bank, "alpha-project", "G1")
    assert g1.created == "2026-08-01" and g1.links == [{"kind": "pr", "ref": "#12"}]
    assert g1.notes[0].text == "Imported from a backlog file. Its status there: ✅ shipped (PR #12)"
    assert g1.notes[0].by == "user" and items["G2"].created == "2026-09-24"          # no date anywhere: today
    folder = bank / "backlog" / "alpha-project"
    before = {p.name: p.read_bytes() for p in folder.glob("*.md")}
    second = backlog_import.import_markdown(bank, project="alpha-project", text=SYNTHETIC, now=NOW, tz_name="UTC")
    assert (second.created, second.skipped, second.paths) == ([], ALL, [])
    assert {p.name: p.read_bytes() for p in folder.glob("*.md")} == before
    nxt = backlog.add_item(bank, project="alpha-project", title="Next idea", author="user", now=NOW, tz_name="UTC")
    assert nxt["item"].id == "G8"                                                      # R-B2: the sequence continues


def test_a_long_title_is_cut_at_a_word_and_kept_whole_in_the_description(bank):
    long = " ".join(["word"] * 60)
    text = f"| ID | Item | Notes | Status |\n|--|--|--|--|\n| G1 | **{long}** | why | 🔲 |\n"
    backlog_import.import_markdown(bank, project="alpha-project", text=text, now=NOW, tz_name="UTC")
    g1 = backlog.get_item(bank, "alpha-project", "G1")
    assert len(g1.title) <= backlog.TITLE_CHARS and g1.title.endswith("…")
    assert g1.description.startswith(long)


def test_an_import_refuses_what_it_cannot_file(bank):
    assert backlog_import.import_markdown(bank, project="no-such-project", text=SYNTHETIC).error
    assert backlog_import.import_markdown(bank, project="alpha-project", text=SYNTHETIC, prefix="g1").error
    too_big = "x" * (backlog_import.MAX_CHARS + 1)
    assert backlog_import.import_markdown(bank, project="alpha-project", text=too_big).error
    assert not (bank / "backlog").exists()


def test_import_file_commits_once_as_the_person(tmp_path):
    bank = _bank(tmp_path)                                                              # a git bank
    src = tmp_path / "backlog.md"
    src.write_text(SYNTHETIC, encoding="utf-8")
    report = backlog_import.import_file(bank, "alpha-project", src, sleep_running=lambda: False)
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Backlog import ") and "Cicada-Author: user" in log
    assert "trigger: user/backlog_import" in log
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(report.paths)
    head = _git(bank, "rev-parse", "HEAD")
    assert backlog_import.import_file(bank, "alpha-project", src, sleep_running=lambda: False).created == []
    assert _git(bank, "rev-parse", "HEAD") == head


def test_the_script_runs_twice_and_the_second_run_changes_nothing(tmp_path):
    bank = _bank(tmp_path)
    src = tmp_path / "backlog.md"
    src.write_text(SYNTHETIC, encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "import-backlog.sh"
    # Port 9 refuses: no backend is no cycle, and the suite never asks a live one.
    env = {**os.environ, "CICADA_TELEMETRY": "off", "CICADA_HOME": str(tmp_path / "home"),
           "CICADA_BACKEND_URL": "http://127.0.0.1:9"}

    def run():
        done = subprocess.run(["bash", str(script), str(bank), "alpha-project", str(src)], capture_output=True,
                              text=True, env=env)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    assert run() == {"created": 7, "skipped": 0, "failed": [], "error": None}
    head = _git(bank, "rev-parse", "HEAD")
    assert run() == {"created": 0, "skipped": 7, "failed": [], "error": None}
    assert _git(bank, "rev-parse", "HEAD") == head


def test_import_file_refuses_while_sleep_runs_and_a_demo_bank(tmp_path):
    """G150 final review, finding 3: the script writes a bank in-process, so a
    running cycle's `git add -A` would take the files under a model's author
    — it refuses and writes nothing; and a demo bank never takes real rows."""
    bank = _bank(tmp_path)
    src = tmp_path / "backlog.md"
    src.write_text(SYNTHETIC, encoding="utf-8")
    head = _git(bank, "rev-parse", "HEAD")
    report = backlog_import.import_file(bank, "alpha-project", src, sleep_running=lambda: True)
    assert report.error == backlog_import.SLEEP_REFUSAL and report.created == []
    assert not (bank / "backlog").exists() and _git(bank, "rev-parse", "HEAD") == head
    (bank / "_bank.yaml").write_text("kind: demo\n", encoding="utf-8")
    report = backlog_import.import_file(bank, "alpha-project", src, sleep_running=lambda: False)
    assert report.error == backlog_import.DEMO_REFUSAL and not (bank / "backlog").exists()
