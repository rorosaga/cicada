"""G118 slice 2 — `GET /episodes/{id}/citations`: what a conversation taught Cicada.

The reverse direction (G106 (ii), design §4.8.3): every claim whose evidence
points into the document, every legacy claim that lists it in
`source_episodes` (a derived, labelled name match), and every page that lists
it in frontmatter. Built from the pages' own claims blocks after a raw-text
prefilter (R-PB10) — no index dependency. Synthetic fixtures.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, markdown_parser, provenance
from api.services.claims import Claim, Evidence, write_claims

EP = "ep_2026-09-01_001"
BODY = (
    "user: I moved alpha-project onto sqlite-vec last week.\n"
    "assistant: Noted — sqlite-vec replaces LEANN for alpha-project.\n"
    "user: bob-example reviewed it."
)


def _span(quote: str, kind: str, *, hash: str | None = None) -> Evidence:  # noqa: A002
    s = BODY.index(quote)
    return Evidence(episode=EP, start=s, end=s + len(quote), kind=kind, hash=hash or evidence.body_hash(BODY))


def _page(memory: Path, stem: str, name: str, claims: list[Claim], *, episodes=(), etype: str = "project") -> None:
    markdown_parser.write(memory / "entities" / f"{stem}.md",
                          {"name": name, "type": etype, "status": "active", "source_episodes": list(episodes)},
                          write_claims(f"# {name}\n", claims))


def _build(memory: Path) -> None:
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / f"{EP}.md", {"id": EP, "title": "Index talk"}, BODY)
    markdown_parser.write(memory / "episodes" / "ep_2026-09-02_001.md", {"id": "ep_2026-09-02_001"},
                          "user: gamma-project uses Tool Example C.")
    _page(memory, "alpha-project", "Alpha Project", [
        Claim(id="clm_a1", text="sqlite-vec replaced LEANN", subject="alpha-project",
              authored_by="claude-sonnet-4-5", source_episodes=[EP],
              evidence=[_span("sqlite-vec replaces LEANN", "assistant")]),
        Claim(id="clm_a2", text="alpha-project is active", subject="alpha-project",
              authored_by="gpt-5.4-mini", source_episodes=[EP]),
        Claim(id="clm_a3", text="alpha-project moved to sqlite-vec", subject="alpha-project", authored_by="user",
              valid_to="2026-09-02", superseded_by="clm_a1", source_episodes=[EP],
              evidence=[_span("moved alpha-project onto sqlite-vec", "user")]),
    ], episodes=[EP])
    _page(memory, "bob-example", "Bob Example", [
        Claim(id="clm_b1", text="bob-example reviewed the migration", subject="bob-example",
              evidence=[_span("bob-example reviewed it", "user", hash="deadbeefcafe")]),
        Claim(id="clm_b2", text="bob-example cares about the index", subject="bob-example",
              evidence=[Evidence(episode=EP, kind="reasoning", hash=evidence.body_hash(BODY))]),
    ], etype="person")
    _page(memory, "beta-project", "Beta Project", [], episodes=[EP])
    _page(memory, "gamma-project", "Gamma Project", [
        Claim(id="clm_g1", text="gamma-project uses Tool Example C", subject="gamma-project",
              source_episodes=["ep_2026-09-02_001"])], episodes=["ep_2026-09-02_001"])
    for i in range(40):
        _page(memory, f"filler-{i:02d}", f"Filler {i}", [])


@pytest.fixture
def built(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    _build(memory)
    bank_index.invalidate()
    return memory


def test_citations_list_spans_derived_reasoning_and_pages(built):
    result = provenance.episode_citations(built, EP)
    rows = result.citations
    assert [r.claim_id for r in rows] == ["clm_a3", "clm_a2", "clm_a1", "clm_b1", "clm_b2"]
    a3, a2, a1, b1, b2 = rows
    assert a1.kind == "assistant" and BODY[a1.start:a1.end] == "sqlite-vec replaces LEANN"
    assert a1.evidence.hash == evidence.body_hash(BODY) and (a1.stale, a1.grown, a1.derived) == (False, False, False)
    assert (a1.subject_id, a1.subject_name, a1.subject_type, a1.authored_by) == (
        "alpha-project", "Alpha Project", "project", "claude-sonnet-4-5")
    assert a3.current is False and a1.current is True
    assert (a2.kind, a2.derived, a2.evidence) == ("derived", True, None)
    assert BODY[a2.start:a2.end] == "alpha-project"
    assert b1.stale is True and b1.start is None and b1.end is None and b1.evidence.start >= 0  # R-PB2
    assert b2.kind == "reasoning" and b2.start is None and b2.evidence.kind == "reasoning"
    assert [(e.entity_id, e.name, e.type) for e in result.entities] == [
        ("alpha-project", "Alpha Project", "project"), ("beta-project", "Beta Project", "project")]
    assert result.partial is False


def test_a_conversation_that_continued_still_highlights(built):
    path = built / "episodes" / f"{EP}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body + "\nassistant: Glad it landed.")
    rows = {r.claim_id: r for r in provenance.episode_citations(built, EP).citations}
    assert rows["clm_a1"].grown is True and rows["clm_a1"].start is not None


def test_only_pages_that_name_the_episode_are_parsed(built, monkeypatch):
    calls: list[str] = []
    real = markdown_parser.parse
    monkeypatch.setattr(markdown_parser, "parse", lambda p: (calls.append(Path(p).name), real(p))[1])
    provenance.episode_citations(built, EP)
    assert sorted(calls) == sorted([f"{EP}.md", "alpha-project.md", "beta-project.md", "bob-example.md"])


def test_the_page_cap_says_partial(built, monkeypatch):
    monkeypatch.setattr(provenance, "MAX_CITATION_PAGES", 1)
    result = provenance.episode_citations(built, EP)
    assert result.partial is True
    assert {r.subject_id for r in result.citations} == {"alpha-project"}


def test_an_unknown_document_is_none(built):
    assert provenance.episode_citations(built, "ep_2026-01-01_999") is None
    assert provenance.episode_citations(built, "../episodes/" + EP) is None


@pytest.fixture
def client_bank(tmp_path: Path, monkeypatch):
    memory = tmp_path / "memory"
    _build(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


def test_the_route_serves_camel_case_404s_and_etags(client_bank):
    url = f"/episodes/{EP}/citations"
    path = client_bank / "episodes" / f"{EP}.md"
    with TestClient(main.app) as client:
        ok = client.get(url)
        assert ok.status_code == 200, ok.text
        data = ok.json()
        assert data["episode"] == EP and data["partial"] is False
        assert {"claimId", "subjectId", "subjectName", "evidence", "stale", "derived"} <= set(data["citations"][0])
        assert client.get("/episodes/ep_2026-01-01_999/citations").status_code == 404
        etag = ok.headers["etag"]
        assert client.get(url, headers={"If-None-Match": etag}).status_code == 304
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        assert client.get(url, headers={"If-None-Match": etag}).status_code == 200
