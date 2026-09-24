"""G150 (R-B26) — the app's backlog fixture IS the server's wire on the demo scenario (R-PP27's precedent: two
languages, one table). Regenerate after a deliberate wire change:
`CICADA_WRITE_APP_FIXTURE=1 api/.venv/bin/python -m pytest api/tests/test_backlog_app_fixture.py`."""
import json
import os
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from _demo_scenario import T, demo
from api import config, main
from api.services import bank_index, handshake

FIXTURE = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Tests" / "fixtures" / "backlog-demo.json"


def _wire(tmp_path, monkeypatch) -> tuple[dict, Path]:
    bank = demo(tmp_path, index=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        c = TestClient(main.app)
        return {"today": T.isoformat(), "list": c.get("/projects/rover-arm-project/backlog").json(),
                "item": c.get("/backlog/rover-arm-project/RAP3").json()}, bank
    finally:
        config.get_settings.cache_clear()


def test_the_app_fixture_is_the_demo_wire(tmp_path, monkeypatch):
    wire, _bank = _wire(tmp_path, monkeypatch)
    text = json.dumps(wire, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("CICADA_WRITE_APP_FIXTURE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, (
        "the app's fixture drifted from the demo wire — rerun with CICADA_WRITE_APP_FIXTURE=1 after a deliberate change")


def test_the_demo_backlog_reads_as_the_rulings_say(tmp_path, monkeypatch):
    wire, bank = _wire(tmp_path, monkeypatch)
    listed = wire["list"]
    assert listed["prefix"] == "RAP" and listed["counts"] == {"open": 2, "doing": 1, "done": 1, "dropped": 1}
    assert [i["id"] for i in listed["items"]] == ["RAP5", "RAP3", "RAP4", "RAP2", "RAP1"]
    notes = wire["item"]["notes"]
    assert [(n["byLabel"], n["byKind"]) for n in notes] == [("Claude Code", "harness"), ("You", "user")]
    assert notes[0]["session"] == "ses_demo_rover_02" and all(n["authorModel"] is None for n in notes)
    log = subprocess.run(["git", "-C", str(bank), "log", "--format=%s%n%b---END---"], check=True, capture_output=True,
                         text=True).stdout.split("---END---")
    backlog_commits = [c for c in log if "backlog/rover-arm-project/" in c]
    assert len(backlog_commits) == 10                        # five items + five notes, each alone (R-B26)
    assert all(("Cicada-Author: user" in c and "trigger: user/companion_app" in c)
               or ("Cicada-Author: claude-code" in c and "trigger: mcp/claude-code" in c
                   and "Cicada-Session: ses_demo_rover_02" in c) for c in backlog_commits)


def test_the_fixture_is_synthetic():
    """Privacy (CLAUDE.md): demo fiction only, every URL on example.com, no machine path."""
    raw = FIXTURE.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "/private/" not in raw and "/home/" not in raw
    for url in re.findall(r"https?://[^\s\"']+", raw):
        assert url.split("/")[2].endswith("example.com"), url
