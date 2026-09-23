"""G133 / R-F3 — papers parsed with no LLM; why they matter, as spans (R-LS14 … R-LS17, R-LS20)."""
from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, folder_source as fs, markdown_parser, media_ingestor, papers
from api.services.claims import parse_claims

REFERENCES = """# References

## Retrieval

- [Paper Alpha](https://arxiv.org/abs/2401.00001v2) — the architecture alpha-project builds on
- [Paper Beta](https://doi.org/10.1234/Example.5678) — why we cite it
- [A tool](https://github.com/example/tool) — not a paper

## Evaluation

- [Paper Alpha](https://arxiv.org/abs/2401.00001) — reused for the eval baseline
"""
PLAN = "# Plan\n\nWe follow arXiv:2401.00001 and doi:10.1234/example.5678 for alpha-project.\n"
BETA = papers.PaperKey(doi="10.1234/example.5678").entity_id


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(rel, mtime, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


def _body(files):
    return {"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}
                      for f in files], "deleted": []}


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    return memory


def _folder(bank):
    project_id, _ = fs.ensure_project(bank, "alpha-project", path="/Users/example/alpha-project", device="mac-1")
    return fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                       project_id=project_id)


def _sync(bank, folder, files, deleted=()):
    bank_index.invalidate()
    out = fs.sync(bank, folder, files, list(deleted))
    staged = out["_staged"]
    return papers.reconcile(bank, fs.get_folder(bank, folder["id"]), touched=staged.touched,
                            tombstoned=staged.tombstoned_sources, renamed=staged.renamed_sources)


def _claims(bank, entity_id):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{entity_id}.md").body)


def _claim(bank, entity_id, predicate):
    (claim,) = [c for c in _claims(bank, entity_id) if c.predicate == predicate]
    return claim


def test_parse_reads_bullets_sections_and_bare_mentions():
    bullets = [c for c in papers.parse(REFERENCES) if c.kind == "bullet"]
    assert [(c.key.arxiv_id or c.key.doi, c.section) for c in bullets] == [
        ("2401.00001", "Retrieval"), ("10.1234/example.5678", "Retrieval"), ("2401.00001", "Evaluation")]
    first = bullets[0]
    assert REFERENCES[first.line_start:first.line_end].startswith("- [Paper Alpha]")
    assert first.note == "the architecture alpha-project builds on" and first.title == "Paper Alpha"
    assert REFERENCES[first.heading_start:first.heading_end] == "Retrieval"
    assert {(c.kind, c.key.arxiv_id or c.key.doi) for c in papers.parse(PLAN)} == {
        ("mention", "2401.00001"), ("mention", "10.1234/example.5678")}
    fence = "`" * 3
    assert papers.parse(f"{fence}\n- [X](https://arxiv.org/abs/2401.00003)\n{fence}\n") == []
    assert papers.count_papers([REFERENCES, PLAN]) == 2


def test_keys_normalise():
    assert papers.key_from_url("https://arxiv.org/pdf/2401.00001v3.pdf") == papers.PaperKey(arxiv_id="2401.00001")
    assert papers.key_for_doi("10.48550/arXiv.2401.00001") == papers.PaperKey(arxiv_id="2401.00001")
    assert papers.key_for_doi("10.1234/ABC.9).") == papers.PaperKey(doi="10.1234/abc.9")
    assert papers.PaperKey(arxiv_id="2401.00001").entity_id == "media-arxiv-2401-00001"
    assert papers.key_from_url("https://example.com/x") is None


def test_a_references_file_makes_paper_pages_with_why_claims(bank):
    markdown_parser.write(bank / "entities" / "retrieval.md", {"name": "Retrieval", "type": "concept"}, "## Summary\nx")
    folder = _folder(bank)
    report = _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    assert (report["papers_created"], report["papers_found"]) == (2, 2)
    page = markdown_parser.parse(bank / "entities" / "media-arxiv-2401-00001.md")
    fm = page.frontmatter
    assert (fm["type"], fm["media"]["kind"], fm["decay_class"], fm["origin"]) == ("media", "paper", "evergreen", "folder")
    assert fm["enrichment_attempted"] is True and fm["name"] == "Paper Alpha"
    assert fm["paper"]["arxiv_id"] == "2401.00001" and set(fm["paper"]["sections"]) == {"Retrieval", "Evaluation"}
    assert [s["ref"] for s in fm["sources"]] == ["https://arxiv.org/abs/2401.00001"]
    saved = [c for c in parse_claims(page.body) if c.predicate == "saved-because"]
    assert {c.object for c in saved} == {"the architecture alpha-project builds on", "reused for the eval baseline"}
    body = markdown_parser.parse(next((bank / "episodes").glob("ep_*.md"))).body
    for claim in saved:
        (ev,) = claim.evidence
        assert (claim.source_trust, claim.observer, ev.kind) == ("user_stated", "owner", "user")
        assert body[ev.start:ev.end] == claim.object
    assert _claim(bank, "media-arxiv-2401-00001", "cited-in").object == folder["project_id"]
    assert _claim(bank, "media-arxiv-2401-00001", "about").object == "retrieval"  # R-LS16: by name only
    idx = media_ingestor.load_url_index(bank)
    rows = [e for e in idx.values() if e["media_entity_id"] == "media-arxiv-2401-00001"]
    assert len(rows) == 1 and rows[0]["kind"] == "paper" and "alias_of" not in rows[0]


def test_a_plan_that_cites_the_paper_adds_its_own_span_to_cited_in(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES), _file("PLAN.md", PLAN)])
    cited = _claim(bank, "media-arxiv-2401-00001", "cited-in")
    assert len({e.episode for e in cited.evidence}) == 2


def test_an_edited_annotation_supersedes_the_old_saved_because(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    edited = REFERENCES.replace("the architecture alpha-project builds on", "the backbone of alpha-project")
    _sync(bank, folder, [_file("REFERENCES.md", edited, mtime=1_756_100_000.0)])
    saved = {c.object: c for c in _claims(bank, "media-arxiv-2401-00001") if c.predicate == "saved-because"}
    old, new = saved["the architecture alpha-project builds on"], saved["the backbone of alpha-project"]
    assert old.valid_to and old.superseded_by == new.id and new.valid_to is None
    assert saved["reused for the eval baseline"].valid_to is None


def test_re_parsing_a_file_replaces_its_span_rather_than_stacking_it(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    _sync(bank, folder, [_file("REFERENCES.md", "Intro.\n\n" + REFERENCES, mtime=1_756_100_000.0)])
    (ev,) = _claim(bank, "media-arxiv-2401-00001", "cited-in").evidence
    assert ev.hash == evidence.body_hash(evidence.source_text(bank, ev.episode))


def test_a_paper_no_file_cites_any_more_asks_through_the_inbox(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES), _file("PLAN.md", PLAN)])
    without_beta = REFERENCES.replace("- [Paper Beta](https://doi.org/10.1234/Example.5678) — why we cite it\n", "")
    assert _sync(bank, folder, [_file("REFERENCES.md", without_beta, mtime=1_756_100_000.0)])["removals_proposed"] == 0
    assert _sync(bank, folder, [], deleted=["PLAN.md"])["removals_proposed"] == 1
    (item,) = (bank / "inbox").glob("inbox-*.md")
    fm = markdown_parser.parse(item).frontmatter
    assert (fm["kind"], fm["entity_id"], fm["channel"]) == ("removal", BETA, f"folder:{folder['id']}")
    assert [o["key"] for o in fm["options"]] == ["keep", "remove"] and fm["allow_other"] is False
    assert _claim(bank, BETA, "cited-in").valid_to
    assert _sync(bank, folder, [], deleted=["PLAN.md"])["removals_proposed"] == 0  # asked once


def test_a_paper_saved_as_a_bookmark_first_is_upgraded_not_duplicated(bank):
    url = "https://arxiv.org/pdf/2401.00001v2"
    media_ingestor.save_url_index(bank, {media_ingestor.url_hash(url): {
        "media_entity_id": "media-paper-alpha", "episode_id": "ep_2026-01-01_001", "url": url,
        "title": "Paper Alpha", "media_type": "url", "thumbnail": None, "saved_at": "2026-01-01T00:00:00+00:00"}})
    markdown_parser.write(bank / "entities" / "media-paper-alpha.md", {
        "name": "Paper Alpha", "type": "media", "origin": "chrome-bookmark",
        "media": {"url": url, "media_type": "url"}, "tags": ["url"], "source_episodes": ["ep_2026-01-01_001"]},
        "## Summary\nSaved url.")
    folder = _folder(bank)
    assert _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])["papers_created"] == 1  # Beta only
    assert not (bank / "entities" / "media-arxiv-2401-00001.md").exists()
    fm = markdown_parser.parse(bank / "entities" / "media-paper-alpha.md").frontmatter
    assert fm["media"]["kind"] == "paper" and fm["paper"]["arxiv_id"] == "2401.00001" and "paper" in fm["tags"]
    alias = media_ingestor.load_url_index(bank)[media_ingestor.url_hash("https://arxiv.org/abs/2401.00001")]
    assert alias["alias_of"] == media_ingestor.url_hash(url)
    assert _sync(bank, folder, [], deleted=["REFERENCES.md"])["removals_proposed"] == 1  # Beta, never Alpha


def test_a_sweep_only_citation_is_the_agents_word(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("archive/2026-01/sweep.md", "See arXiv:2401.00009 for more.")])
    cited = _claim(bank, "media-arxiv-2401-00009", "cited-in")
    assert (cited.observer, cited.source_trust, cited.evidence[0].kind) == ("agent", "agent_reflected", "assistant")


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def test_the_route_previews_papers_and_waits_for_a_running_sleep(client, monkeypatch):
    from api.services import sleep_cycle

    c, bank = client
    fid = c.post("/sources/folders", json={"label": "alpha-project", "path": "/Users/example/alpha-project"}).json()["id"]
    pre = c.post(f"/sources/folders/{fid}/sync", params={"preview": "true"},
                 json=_body([_file("REFERENCES.md", REFERENCES)])).json()
    assert pre["papersFound"] == 2 and not list((bank / "entities").glob("media-*.md"))
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    r = c.post(f"/sources/folders/{fid}/sync", json=_body([_file("REFERENCES.md", REFERENCES)])).json()
    assert r["papersPending"] is True and r["created"] == 1
    assert not (bank / "entities" / "media-arxiv-2401-00001.md").exists()  # R-LS17
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="idle"))
    r = c.post(f"/sources/folders/{fid}/sync", json=_body([])).json()
    assert r["papersCreated"] == 2 and (bank / "entities" / "media-arxiv-2401-00001.md").exists()
    assert fs.get_folder(bank, fid)["papers_pending"] is False


def test_a_deletion_while_sleep_ran_still_closes_claims_on_the_deferred_reparse(bank):
    """R-LS17 + R-LS20: the deferred path reads deletions and renames back from
    the episode index — the syncs that made them are long gone (Task 3 review)."""
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES), _file("PLAN.md", PLAN)])
    without_beta = REFERENCES.replace("- [Paper Beta](https://doi.org/10.1234/Example.5678) — why we cite it\n", "")
    bank_index.invalidate()
    # Two syncs land while a cycle runs: the route stages them and defers the paper step.
    fs.sync(bank, folder, [_file("REFERENCES.md", without_beta, mtime=1_756_100_000.0)], [])
    bank_index.invalidate()
    assert fs.sync(bank, folder, [_file("NOTES.md", PLAN, mtime=1_756_100_000.0)], ["PLAN.md"])["renamed"] == 1
    bank_index.invalidate()
    report = papers.reparse_folder(bank, fs.get_folder(bank, folder["id"]))
    prefix = fs.channel_id(folder["id"]) + ":"
    assert set(papers.load_citations(bank)) == {prefix + "REFERENCES.md", prefix + "NOTES.md"}
    assert report["removals_proposed"] == 0  # Beta is still cited, from the renamed file
    bank_index.invalidate()
    fs.sync(bank, folder, [], ["NOTES.md"])
    bank_index.invalidate()
    assert papers.reparse_folder(bank, fs.get_folder(bank, folder["id"]))["removals_proposed"] == 1
    assert _claim(bank, BETA, "cited-in").valid_to


def test_a_reconcile_with_nothing_touched_writes_nothing(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    cites = bank / "sources" / papers.CITATIONS_FILENAME
    before = cites.stat().st_mtime_ns
    report = papers.reconcile(bank, fs.get_folder(bank, folder["id"]), touched={}, tombstoned={})
    assert report["paths"] == [] and cites.stat().st_mtime_ns == before
