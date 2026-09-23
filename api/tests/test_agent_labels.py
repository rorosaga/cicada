"""F2-back R-B9 … R-B11 — an agent's write is labelled by its harness, and the
pre-G135 `mcp-agentic-write` placeholder reads as `agent` everywhere without
rewriting history."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from api.remote import catalog
from api.services import (
    agentic_write, git_service, markdown_parser, provenance, source_overview, telegram_capture,
    transclusion_resolver,
)
from api.services.claims import Claim, parse_claims, write_claims


def _claim(**kw) -> Claim:
    base = dict(id="clm_x", text="alpha-project uses sqlite", subject="alpha-project", predicate="uses",
                object="sqlite", observer="agent", origin="mcp", valid_from="2026-09-01")
    base.update(kw)
    return Claim(**base)


def _bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    return bank


# --- R-B9: the bucket --------------------------------------------------------


def test_every_harness_label_is_a_harness_not_a_model():
    labels = ({k for k in source_overview.HARNESS_LABELS if k != "unknown"}
              | {a.harness for a in catalog.APPS.values()} | {"agent"})
    for label in labels:
        assert git_service.author_identity(label) == ("harness", None), label


def test_models_the_person_and_maintenance_keep_their_buckets():
    assert git_service.author_identity("claude-sonnet-4-5") == ("model", "anthropic")
    assert git_service.author_identity("gpt-5.4-mini") == ("model", "openai")
    assert git_service.author_identity("user") == ("user", None)
    assert git_service.author_identity("cicada") == ("system", None)
    assert git_service.author_identity(None) == ("unknown", None)


def test_contributors_bucket_a_harness_commit_as_a_harness(tmp_path):
    bank = _bank(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=bank, check=True)
    (bank / "entities" / "alpha-project.md").write_text("x\n", encoding="utf-8")
    message = git_service.build_commit_message("Agent write", ["entities/alpha-project.md: updated (trigger: mcp/claude-code)"],
                                               authors=["claude-code"])
    git_service.commit_paths_sync(bank, message, ["entities/alpha-project.md"])
    (row,) = asyncio.run(git_service.get_contributors(bank))
    assert (row.author, row.kind, row.provider) == ("claude-code", "harness", None)


# --- R-B10: the placeholder, read -------------------------------------------


def test_the_old_placeholder_reads_as_an_agent():
    assert git_service.canonical_author("mcp-agentic-write") == "agent"
    assert git_service.canonical_author("claude-code") == "claude-code"
    assert git_service.canonical_author("") == "unknown"
    assert git_service.author_identity("mcp-agentic-write") == ("harness", None)


def test_a_claim_on_the_wire_names_the_agent_not_the_placeholder():
    model = transclusion_resolver.claim_to_model(_claim(authored_by="mcp-agentic-write"))
    assert (model.authored_by, model.author_kind, model.author_provider) == ("agent", "harness", None)
    model = transclusion_resolver.claim_to_model(_claim(authored_by="claude-code"))
    assert (model.authored_by, model.author_kind) == ("claude-code", "harness")


def test_provenance_counts_the_placeholder_and_agent_as_one_writer(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    claims = [_claim(id="clm_1", authored_by="mcp-agentic-write"),
              _claim(id="clm_2", object="redis", text="alpha-project uses redis", authored_by="agent"),
              _claim(id="clm_3", object="duckdb", text="alpha-project uses duckdb", authored_by="claude-code")]
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project"},
                          write_claims("## Summary\nAlpha.\n", claims))
    by = {c.author: c for c in provenance.entity_provenance(bank, page).contributors}
    assert set(by) == {"agent", "claude-code"}
    assert (by["agent"].claims, by["agent"].kind, by["agent"].provider) == (2, "harness", None)


def test_the_placeholder_file_is_never_rewritten(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project"},
                          write_claims("## Summary\nAlpha.\n", [_claim(authored_by="mcp-agentic-write")]))
    before = page.read_bytes()
    provenance.entity_provenance(bank, page)
    assert page.read_bytes() == before


# --- R-B10: who may withdraw what -------------------------------------------


def test_the_agent_bucket_owns_only_what_an_unidentified_mcp_agent_wrote():
    mcp = _claim(id="clm_a", authored_by="agent", origin="mcp")
    note_taker = _claim(id="clm_b", authored_by="agent", origin="wispr-flow")
    folder = _claim(id="clm_c", authored_by="agent", origin="folder")
    assert agentic_write.owns(mcp, author="agent", origin=None)
    assert not agentic_write.owns(note_taker, author="agent", origin=None)
    assert not agentic_write.owns(folder, author="agent", origin=None)
    assert not agentic_write.owns(mcp, author="claude-code", origin=None)
    legacy = _claim(id="clm_d", authored_by="mcp-agentic-write", origin="mcp")
    assert agentic_write.owns(legacy, author="codex", origin=None), "Q-R5's legacy rule is unchanged"


# --- R-B11: new writes -------------------------------------------------------


def test_a_write_that_names_no_author_is_an_agents(tmp_path):
    bank = _bank(tmp_path)
    agentic_write.write_claim(bank, "alpha-project", "uses", "sqlite", observer="agent", force_new_entity=True)
    page = bank / "entities" / "alpha-project.md"
    (claim,) = parse_claims(markdown_parser.parse(page).body)
    assert claim.authored_by == "agent"
    assert "mcp-agentic-write" not in page.read_text(encoding="utf-8")


def test_telegrams_reason_is_the_persons(tmp_path):
    bank = _bank(tmp_path)
    telegram_capture._write_saved_because_claim(bank, "media-example", "for the alpha launch", "")
    (claim,) = parse_claims(markdown_parser.parse(bank / "entities" / "media-example.md").body)
    assert (claim.authored_by, claim.origin) == ("user", "telegram")


# --- R-B10: the ETag moves with the body -------------------------------------


def test_the_contributors_etag_moves_when_the_author_shape_does(tmp_path, monkeypatch):
    """The same commits now serialise with new kinds; `/contributors` is a Store
    domain with an on-disk cache, so a git_head-only ETag would 304 the old rows
    until the next commit (the `graph.NODE_SHAPE` rule)."""
    from fastapi.testclient import TestClient

    from api import config, main

    bank = _bank(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=bank, check=True)
    (bank / "entities" / "alpha-project.md").write_text("x\n", encoding="utf-8")
    git_service.commit_paths_sync(bank, "seed", ["entities/alpha-project.md"])
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        etag = client.get("/contributors").headers["etag"]
        assert client.get("/contributors", headers={"If-None-Match": etag}).status_code == 304
        monkeypatch.setattr(git_service, "AUTHOR_SHAPE", "harness-test")
        assert client.get("/contributors", headers={"If-None-Match": etag}).status_code == 200
    finally:
        config.get_settings.cache_clear()
