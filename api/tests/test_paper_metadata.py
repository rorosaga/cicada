"""R-F3 / R-LS18 / R-LS19 — paper details from the official APIs only, paced, gated."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (
    bank_index, channel_registry, folder_source as fs, link_enrichment, markdown_parser, media_ingestor,
    paper_metadata as pm, papers, sleep_cycle, sync_state,
)
from api.services.claims import parse_claims

FIX = Path(__file__).parent / "fixtures" / "papers"
ATOM = (FIX / "arxiv_query.atom").read_bytes()
CROSSREF = (FIX / "crossref_work.json").read_bytes()
REFERENCES = """# References

## Retrieval

- [Paper Alpha](https://arxiv.org/abs/2401.00001) — the architecture alpha-project builds on
- [Paper Beta](https://doi.org/10.1234/example.5678) — why we cite it
"""
SWEEP = "An agent found arXiv:2401.00009 while reading."
ALPHA, NINE = "media-arxiv-2401-00001", "media-arxiv-2401-00009"
BETA = papers.PaperKey(doi="10.1234/example.5678").entity_id


def _file(rel, text):
    raw = text.encode()
    return fs.IncomingFile(rel, 1_756_000_000.0, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    project_id, _ = fs.ensure_project(memory, "alpha-project", path="/Users/example/alpha-project", device="mac-1")
    folder = fs.register(memory, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                         project_id=project_id)
    out = fs.sync(memory, folder, [_file("REFERENCES.md", REFERENCES), _file("archive/sweep.md", SWEEP)], [])
    staged = out["_staged"]
    papers.reconcile(memory, folder, touched=staged.touched, tombstoned={}, renamed=[])
    bank_index.invalidate()
    return memory


class _Clock:
    def __init__(self):
        self.t, self.waits = 0.0, []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.waits.append(round(s, 3))
        self.t += s


def _fetcher(calls, *, arxiv=(200, "application/atom+xml", ATOM), crossref=(200, "application/json", CROSSREF)):
    async def fetch(url, params):
        calls.append((url, dict(params)))
        status, ctype, body = arxiv if url == pm.ARXIV_API else crossref
        return pm.Response(status, ctype, body)
    return fetch


def test_parse_arxiv_atom():
    meta = pm.parse_arxiv_atom(ATOM)
    assert list(meta) == ["2401.00001"]
    a = meta["2401.00001"]
    assert a["title"] == "Paper Alpha: A Synthetic Study" and a["authors"] == ["Ada Example", "Bob Example"]
    assert (a["published"], a["updated"], a["primary_category"]) == ("2024-01-02", "2024-02-01", "cs.LG")
    assert a["doi"] == "10.9999/alpha.2024" and a["abstract"].startswith("We study a synthetic problem")
    assert pm.parse_arxiv_atom(b"<not xml") == {}


def test_parse_crossref():
    b = pm.parse_crossref(CROSSREF)
    assert b == {"title": "Paper Beta: Examples at Scale", "authors": ["Carol Example"], "published": "2023-05-17",
                 "abstract": "We report synthetic results.", "venue": "Journal of Synthetic Results",
                 "doi": "10.1234/example.5678"}


def test_resolve_fills_pages_paced_and_backs_off(bank):
    calls, clock = [], _Clock()
    report = asyncio.run(pm.resolve(bank, fetch_fn=_fetcher(calls), clock=clock.now, sleep=clock.sleep))
    assert [c[0] for c in calls] == [pm.ARXIV_API, pm.CROSSREF_API + "10.1234/example.5678"]
    assert calls[0][1] == {"id_list": "2401.00001,2401.00009", "max_results": "2"}
    assert (report["resolved"], report["failed"], report["remaining"]) == (2, 1, 0)
    page = markdown_parser.parse(bank / "entities" / f"{ALPHA}.md")
    paper = page.frontmatter["paper"]
    assert page.frontmatter["name"] == "Paper Alpha"  # the person's title stays the page name
    assert (paper["title"], paper["doi"], paper["metadata_source"]) == (
        "Paper Alpha: A Synthetic Study", "10.9999/alpha.2024", "arxiv")
    assert paper["metadata_at"] == date.today().isoformat()
    assert link_enrichment._extract_description_section(page.body).startswith("We study a synthetic problem")
    (describes,) = [c for c in parse_claims(page.body) if c.predicate == "describes"]
    assert (describes.source_trust, describes.observer, describes.authored_by) == ("external", "external:arxiv", "cicada")
    assert describes.evidence[0].kind == "page" and describes.recorded_at == date.today().isoformat()
    idx = media_ingestor.load_url_index(bank)
    assert idx[media_ingestor.url_hash("https://doi.org/10.9999/alpha.2024")]["alias_of"]
    nine = markdown_parser.parse(bank / "entities" / f"{NINE}.md").frontmatter["paper"]
    assert nine["metadata_status"] == "not_found" and nine["metadata_attempted_at"] == date.today().isoformat()
    beta = markdown_parser.parse(bank / "entities" / f"{BETA}.md").frontmatter["paper"]
    assert beta["venue"] == "Journal of Synthetic Results" and beta["metadata_source"] == "crossref"
    calls.clear()
    bank_index.invalidate()
    asyncio.run(pm.resolve(bank, fetch_fn=_fetcher(calls), clock=clock.now, sleep=clock.sleep))
    assert calls == []  # nothing pending; the missing id is backing off (R-LS18)


def test_arxiv_requests_are_three_seconds_apart(bank, monkeypatch):
    monkeypatch.setattr(pm, "ARXIV_BATCH", 1)
    calls, clock = [], _Clock()
    asyncio.run(pm.resolve(bank, fetch_fn=_fetcher(calls), clock=clock.now, sleep=clock.sleep))
    assert [c[0] for c in calls].count(pm.ARXIV_API) == 2
    assert clock.waits == [pm.ARXIV_SPACING_S]


def test_a_429_stops_arxiv_but_not_crossref_and_marks_nothing(bank):
    calls = []
    report = asyncio.run(pm.resolve(bank, fetch_fn=_fetcher(calls, arxiv=(429, "text/plain", b"")),
                                    clock=_Clock().now, sleep=_Clock().sleep))
    assert report["error"] == "arXiv HTTP 429" and report["resolved"] == 1
    assert "metadata_status" not in markdown_parser.parse(bank / "entities" / f"{ALPHA}.md").frontmatter["paper"]


def test_the_sleep_tail_is_gated_and_finishes_deferred_folders(bank, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no network with the gate off")

    monkeypatch.setattr(pm, "resolve", boom)
    (folder,) = fs.list_folders(bank)
    fs.set_flags(bank, folder["id"], papers_pending=True)
    (bank / "entities" / f"{BETA}.md").unlink()
    asyncio.run(sleep_cycle._resolve_papers_safely(bank))
    assert (bank / "entities" / f"{BETA}.md").exists()  # the deterministic half ran
    assert sync_state.read_sync_state(bank)["papers"]["last_skip_reason"] == "network fetch disabled"


def test_link_enrichment_never_fetches_a_paper_page(bank):
    scan = link_enrichment.scan_backfill(bank, config.Settings())
    assert not any(c.media_id.startswith("media-arxiv-") or c.media_id.startswith("media-doi-")
                   for c in scan.fetch + scan.reuse)
    assert not any(p.stem.startswith(("media-arxiv-", "media-doi-")) for p in link_enrichment._candidates(bank, 50))


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_feed_shows_one_row_per_paper_with_its_byline(bank, client):
    asyncio.run(pm.resolve(bank, fetch_fn=_fetcher([]), clock=_Clock().now, sleep=_Clock().sleep))
    bank_index.invalidate()
    items = client.get("/sources").json()["items"]
    alpha = [i for i in items if i["mediaEntityId"] == ALPHA]
    assert len(alpha) == 1 and alpha[0]["kind"] == "paper"  # the DOI alias is not a second row
    assert alpha[0]["paper"] == {"authors": ["Ada Example", "Bob Example"], "arxivId": "2401.00001",
                                 "doi": "10.9999/alpha.2024", "published": "2024-01-02",
                                 "venue": "Journal of Examples 1 (2024)"}
    files = channel_registry.build_channels(bank, telegram_enabled=False)
    idx = media_ingestor.load_url_index(bank)
    assert next(r for r in files if r["id"] == "files")["count"] == sum(1 for e in idx.values() if not e.get("alias_of"))
    assert client.get(f"/entities/{ALPHA}").json()["media"]["kind"] == "paper"


def test_the_paper_endpoint_leads_with_why_then_context(bank, client):
    asyncio.run(pm.resolve(bank, fetch_fn=_fetcher([]), clock=_Clock().now, sleep=_Clock().sleep))
    bank_index.invalidate()
    body = client.get(f"/entities/{ALPHA}/paper").json()
    assert [w["predicate"] for w in body["why"]] == ["saved-because", "cited-in"]
    saved = body["why"][0]
    assert (saved["file"], saved["heading"], saved["kind"], saved["text"]) == (
        "REFERENCES.md", "Retrieval", "user", "the architecture alpha-project builds on")
    assert saved["snippet"][saved["highlightStart"]:saved["highlightEnd"]] == saved["text"]
    assert body["agentOnly"] is False
    assert body["context"].startswith("We study") and body["contextSource"] == "arxiv"
    assert body["absUrl"] == "https://arxiv.org/abs/2401.00001" and body["doiUrl"] == "https://doi.org/10.9999/alpha.2024"
    assert client.get(f"/entities/{NINE}/paper").json()["agentOnly"] is True
    assert client.get("/entities/alpha-project/paper").status_code == 404
    assert client.get("/entities/..%2Fsecrets/paper").status_code == 404


def test_a_user_triggered_sync_schedules_one_background_run(bank, client, monkeypatch):
    seen = []

    async def fake(memory_path):
        seen.append(Path(memory_path))

    monkeypatch.setattr(pm, "resolve_in_background", fake)
    (folder,) = fs.list_folders(bank)
    r = client.post(f"/sources/folders/{folder['id']}/sync", params={"resolve": "true"},
                    json={"files": [], "deleted": []})
    assert r.status_code == 200 and seen == [bank]
