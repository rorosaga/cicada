"""G141 PJ-5 — the app's Projects fixture IS the server's wire on the demo scenario (R-PP27).

Every Swift test of the Projects page (decode, `ProjectState`, the band, the story) reads
`app/CicadaApp/Tests/fixtures/projects-demo.json`. This test regenerates the same payloads from a
fresh demo bank with `today` pinned (spec §12) and fails on any byte of drift — the
`video_urls.json` / `timeline_state.json` precedent: two languages, one table, so the app can never
be tested against a wire the server no longer sends. Synthetic only: demo fiction on example.com.

After a deliberate wire change, rewrite it: `CICADA_WRITE_APP_FIXTURE=1 python -m pytest <this file>`.
"""
import json
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from _demo_scenario import T, demo
from api import config, main
from api.services import bank_index, handshake

FIXTURE = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Tests" / "fixtures" / "projects-demo.json"
PROJECTS = ("rover-arm-project", "pick-and-place-demo", "garden-sensor-project")
# A follow-up's question and its options' age phrases are synthesised at read from the real clock (spec §9: "last
# heard 4 weeks ago"), so only the fields that never move are pinned — the ones the app joins a thread on.
FOLLOWUP_KEYS = ("id", "kind", "requiredInput", "status", "title", "entityId", "entityName", "claimId", "predicate",
                 "createdDate")


def _wire(tmp_path, monkeypatch, *, showcase: bool = False) -> dict:
    bank = demo(tmp_path, showcase=showcase)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        c = TestClient(main.app)
        return {
            "today": T.isoformat(),
            "projects": c.get("/projects").json(),
            "timelines": {pid: c.get(f"/projects/{pid}/timeline").json() for pid in PROJECTS},
            "followup": {k: v for k, v in next(i for i in c.get("/inbox").json() if i["kind"] == "followup").items()
                         if k in FOLLOWUP_KEYS},
        }
    finally:
        config.get_settings.cache_clear()


def test_the_app_fixture_is_the_demo_wire(tmp_path, monkeypatch):
    text = json.dumps(_wire(tmp_path, monkeypatch), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("CICADA_WRITE_APP_FIXTURE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, (
        "the app's fixture drifted from the demo wire — rerun with CICADA_WRITE_APP_FIXTURE=1 after a deliberate change")


def test_the_showcase_leaves_the_projects_wire_alone(tmp_path, monkeypatch):
    """Round 4 (T-Demo): the showcase is written into the same demo, so the fixture is only the demo's wire if the
    showcase never touches it — nothing it writes names the scenario's projects or their people. If this fails, change
    the showcase, never the fixture."""
    text = json.dumps(_wire(tmp_path, monkeypatch, showcase=True), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    assert FIXTURE.read_text(encoding="utf-8") == text


def test_the_fixture_is_synthetic():
    """Privacy (CLAUDE.md): demo fiction only, every URL on example.com, no machine path."""
    raw = FIXTURE.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "/private/" not in raw and "/home/" not in raw
    for url in re.findall(r"https?://[^\s\"']+", raw):
        assert url.split("/")[2].endswith("example.com"), url
