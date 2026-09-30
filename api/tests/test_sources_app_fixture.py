"""G61 S3-a — the app's sources fixture IS the server's wire (the `projects-demo.json` precedent).

`app/CicadaApp/Tests/fixtures/sources-living.json` is what `GET /entities/{id}/sources` answers for a page that
holds several sources over three facts: the person's, an agent's, a connection's (`origin`), one the person took,
one linked to its own page, and one whose linked page is gone (served as no link). Regenerated here from a
synthetic bank with every day pinned; any drift fails. After a deliberate wire change:
`CICADA_WRITE_APP_FIXTURE=1 python -m pytest api/tests/test_sources_app_fixture.py`. Synthetic only (example.com)."""
import json
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from _synthetic_bank import _bank, _entity
from api import config, main
from api.services import bank_index, fact_sources, markdown_parser

FIXTURE = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Tests" / "fixtures" / "sources-living.json"
DAY = "2026-09-20"


def _wire(tmp_path, monkeypatch) -> dict:
    memory = _bank(tmp_path)
    _entity(memory, "media-alpha-profile", type="media")
    add = fact_sources.add_source
    add(memory, "bob-example", "https://example.com/staff-directory", predicate="works-at", added_by="user",
        added_at=DAY)
    add(memory, "bob-example", "https://example.com/team", predicate="works-at", added_by="claude-code",
        added_at=DAY)
    add(memory, "bob-example", "https://example.com/in/bob", predicate="profile", added_by="claude-web",
        added_at=DAY, origin="remote:ab12cd34", entity="media-alpha-profile")
    add(memory, "bob-example", "https://example.com/old-team", predicate="works-at", added_by="claude-code",
        added_at=DAY, access="public")
    add(memory, "bob-example", "Ask bob-example, he announces job changes", predicate="works-at", added_by="user",
        added_at=DAY, kind="note")
    add(memory, "bob-example", "https://example.com/about", added_by="cicada", added_at=DAY)
    add(memory, "bob-example", "https://example.com/gone", predicate="profile", added_by="user", added_at=DAY)
    fact_sources.change_source(memory, "bob-example", "https://example.com/old-team", "works-at",
                               actor="user", accepted=True)
    # a link whose page was merged away since: the server serves it as no link
    page = memory / "entities" / "bob-example.md"
    parsed = markdown_parser.parse(page)
    for row in parsed.frontmatter["sources"]:
        if row["ref"].endswith("/gone"):
            row["entity"] = "page-that-was-merged-away"
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        return TestClient(main.app).get("/entities/bob-example/sources").json()
    finally:
        config.get_settings.cache_clear()


def test_the_app_fixture_is_the_sources_wire(tmp_path, monkeypatch):
    text = json.dumps(_wire(tmp_path, monkeypatch), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("CICADA_WRITE_APP_FIXTURE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, (
        "the app's fixture drifted from the sources wire — rerun with CICADA_WRITE_APP_FIXTURE=1 after a deliberate change")


def test_the_fixture_says_what_the_card_needs_and_is_synthetic():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = {r["ref"]: r for r in data["sources"]}
    assert {r.get("predicate") for r in rows.values()} == {"works-at", "profile", None}
    assert rows["https://example.com/in/bob"]["origin"] == "remote:ab12cd34"
    assert rows["https://example.com/in/bob"]["entity"] == "media-alpha-profile"
    assert rows["https://example.com/gone"]["entity"] is None, "a stale link is served as no link"
    assert rows["https://example.com/old-team"]["accepted"] is True
    raw = FIXTURE.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "/private/" not in raw and "/home/" not in raw
    for url in re.findall(r"https?://[^\s\"']+", raw):
        assert url.split("/")[2].endswith("example.com"), url
