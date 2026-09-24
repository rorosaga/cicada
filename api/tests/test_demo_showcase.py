"""G117, round 4 (T-Demo) — the demo shows everything: pictures, a video, an article with a preview, a paper, a
calendar day, a tab group, beliefs signed with the model and effort of the turn that wrote them, and every inbox
kind. Each piece is read back through the route the app reads it from, so the test fails the way the app would.
Synthetic: demo fiction, and the four public items `demo_showcase.PUBLIC_URLS` names with their licences.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from _demo_scenario import T, demo
from fastapi.testclient import TestClient

from api import config, main
from api.services import (demo_pictures, demo_showcase, entity_picture, handshake, markdown_parser, papers,
                          video_urls)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "demo_showcase.json"
_URL = re.compile(r"https?://[^\s)\"'>\]]+")


@pytest.fixture(scope="module")
def bank(tmp_path_factory):
    return demo(tmp_path_factory.mktemp("showcase"), showcase=True)


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout


def test_the_pictures_are_drawn_in_code_and_kept_as_uploads():
    a = demo_pictures.avatar((214, 226, 234), (169, 192, 210), (94, 127, 163))
    assert a == demo_pictures.avatar((214, 226, 234), (169, 192, 210), (94, 127, 163)), "R7 — deterministic"
    assert entity_picture.validate_upload(a) == "png" and entity_picture.dimensions(a) == (256, 256)
    m = demo_pictures.mark((245, 236, 214), (226, 205, 160), (176, 132, 60))
    assert entity_picture.validate_upload(m) == "png" and len(m) < entity_picture.MAX_UPLOAD_BYTES


def test_people_and_a_company_have_pictures_the_app_can_load(bank, client):
    nodes = {n["id"]: n for n in client.get("/graph").json()["nodes"]}
    for eid in ("leo-example", "paula-example", "maria-example", "nina-example", "acme-example"):
        fm = markdown_parser.parse(bank / "entities" / f"{eid}.md").frontmatter
        assert fm["picture"]["kind"] == "upload" and fm["picture"]["added"] == T.isoformat(), eid
        assert nodes[eid]["pictureSource"] == "upload", eid
        assert nodes[eid]["picture"] == f"/entities/{eid}/picture?v={fm['picture']['sha']}"
        got = client.get(nodes[eid]["picture"])
        assert got.status_code == 200 and got.headers["content-type"] == "image/png", eid
    assert nodes[demo_showcase.VIDEO_ID]["picture"] == demo_showcase.VIDEO_THUMBNAIL
    assert nodes[demo_showcase.ARTICLE_ID]["picture"] == demo_showcase.ARTICLE_THUMBNAIL


def test_the_feed_holds_a_video_an_article_a_paper_and_the_scenarios_guide(client):
    rows = {r["mediaEntityId"]: r for r in client.get("/sources").json()["items"]}
    video = rows[demo_showcase.VIDEO_ID]
    assert video["provider"] == "youtube" and video["thumbnail"] == demo_showcase.VIDEO_THUMBNAIL
    assert video_urls.resolve(video["url"]).kind == "embed", "played in the provider's own player (Track V)"
    assert rows[demo_showcase.ARTICLE_ID]["thumbnail"] == demo_showcase.ARTICLE_THUMBNAIL
    paper = rows[demo_showcase.PAPER_ID]
    assert paper["kind"] == papers.KIND and paper["title"].startswith("Diffusion Policy")
    assert paper["paper"]["arxivId"] == demo_showcase.PAPER_ARXIV_ID and len(paper["paper"]["authors"]) == 8
    assert "media-example-cluster-guide" in rows, "R-DL18 — the scenario's saved guide reaches the Feed"
    assert demo_showcase.BOOKMARK_ID in rows


def test_the_paper_is_described_by_its_arxiv_metadata_and_never_fetched(bank):
    fm = markdown_parser.parse(papers.page_path(bank, demo_showcase.PAPER_ID)).frontmatter
    assert fm["name"] == "Diffusion Policy: Visuomotor Policy Learning via Action Diffusion"
    assert fm["paper"]["metadata_source"] == "arxiv" and fm["paper"]["published"] == "2023-03-07"
    assert fm["enrichment_attempted"] is True and papers.never_scraped(fm["media"]["url"])
    log = _git(bank, "log", "-1", "--format=%B", "--", f"entities/{demo_showcase.PAPER_ID}.md")
    # `paper_metadata.run_locked` commits through `folder_source.commit_paths_for`: an undated subject.
    assert log.startswith("Paper details\n") and "Cicada-Author: cicada" in log


def test_leos_beliefs_are_signed_with_the_model_and_effort_of_their_turn(client):
    claims = client.get(f"/entities/{demo_showcase.PERSON}/claims").json()["claims"]
    signed = [c for c in claims if c.get("authorKind") == "harness"]
    assert len(signed) == 3
    for c in signed:
        assert (c["authorModel"], c["authorEffort"]) == (demo_showcase.MODEL, demo_showcase.EFFORT), c["id"]
        assert c["evidence"][0]["kind"] == "user", "the person's words, quoted"


def test_every_inbox_kind_is_served(client):
    items = client.get("/inbox").json()
    kinds = {i["kind"] for i in items}
    assert kinds == {"decay", "conflict", "clarification", "merge_suggestion", "followup", "removal", "divergence",
                     "normalization"}
    assert any(i["kind"] == "conflict" and i["informational"] for i in items), "G98 — inbox-004's `uses`"
    divergence = next(i for i in items if i["kind"] == "divergence")
    assert divergence["entityId"] == "grace-example" and len(divergence["options"]) == 3


def test_a_calendar_day_and_an_open_tab_group_are_captured(bank):
    eps = [markdown_parser.parse(p).frontmatter for p in sorted((bank / "episodes").glob("*.md"))]
    calendar = [fm for fm in eps if str(fm.get("source_id", "")).startswith("calendar-local:")]
    assert len(calendar) == 4 and {fm["origin"] for fm in calendar} == {"calendar-local"}
    assert all(fm["event_start"].startswith(T.isoformat()) for fm in calendar)
    tabs = [fm for fm in eps if str(fm.get("source_id", "")).startswith("tab-group:chrome:Default:")]
    assert len(tabs) == 1 and tabs[0]["origin"] == "chrome-tab-group" and tabs[0]["tab_group_color"] == "blue"
    state = json.loads((bank / "sync_state.json").read_text())
    assert state["calendar-local"]["last_sync"] == f"{T.isoformat()}T07:00:00+00:00"


def test_each_piece_is_committed_by_its_own_writer_and_nothing_is_left_behind(bank):
    log = _git(bank, "log", "--format=%s|%(trailers:key=Cicada-Author,valueonly,separator=%x2C)")
    subjects = [line for line in log.splitlines() if line]
    day = T.isoformat()
    # The three `folder_source.commit_paths_for` writers (paper details, calendar, tab groups) commit undated subjects;
    # a removal proposal is `bookmark_sync`'s own `cicada` commit, never inside the person's save.
    for subject, author in ((f"Sources ingest {day}", "user"), (f"Bookmark removal sync {day}", "cicada"),
                            ("Paper details", "cicada"), ("Calendar sync", "user"), ("Tab groups sync", "user"),
                            (f"Memory update {day}", "user"), (f"Agent write {day}", "claude-code"),
                            (f"Set picture {day}", "user")):
        assert f"{subject}|{author}" in subjects, subject
    status = set(_git(bank, "status", "--porcelain").splitlines())
    assert status <= {"?? .gitignore", "?? _predicates.yaml", "?? _preferences.md"}, status


def test_every_url_is_example_com_or_a_licensed_public_item(bank):
    text = "\n".join(p.read_text() for p in bank.rglob("*.md")) + (bank / "sources" / "url_index.json").read_text()
    public = {u for u in _URL.findall(text) if "://example.com" not in u and ".example.com" not in u}
    assert public == set(demo_showcase.PUBLIC_URLS)
    assert all(len(why) > 40 for why in demo_showcase.PUBLIC_URLS.values()), "each carries its licence"


def test_the_showcase_is_deterministic(tmp_path):
    a, b = demo(tmp_path / "a", index=False, showcase=True), demo(tmp_path / "b", index=False, showcase=True)
    for sub in ("entities", "episodes", "inbox", "assets/pictures"):
        for p in sorted((a / sub).glob("*")):
            if p.stem == "bob-example":
                continue   # ensure_owner_entity stamps its own created day (test_demo_bank's exception)
            assert p.read_bytes() == (b / sub / p.name).read_bytes(), f"{sub}/{p.name}"


def test_the_apps_showcase_ids_are_the_generators():
    ids = json.loads(FIXTURE.read_text())
    assert (ids["person"], ids["session"], ids["model"], ids["effort"]) == (
        demo_showcase.PERSON, demo_showcase.SESSION, demo_showcase.MODEL, demo_showcase.EFFORT)
    assert ids["project"] == "rover-arm-project"
