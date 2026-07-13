"""M5-prep consolidation-readiness tests (BACKEND stream).

Four additive, decode-tolerant prep changes ahead of a fresh GLM-5.2
consolidation run into a NEW empty ``claude-chats`` bank, with the OLD
1,882-entity bank preserved + renamed ``original-v1``:

  G17  deadline as a ``due`` claim, not a standalone entity (prompt stops
       producing deadline entities; the type set still ACCEPTS legacy
       ``deadline`` so the old graph never breaks).
  G18  split ``location`` -> ``directory`` (filesystem path) vs ``location``
       (physical place); the ``/entities/{id}/location`` endpoint accepts BOTH.
  per-bank embeddings — the SEARCH path embeds the query with the bank's OWN
       recorded model (``index_meta.model``), not the global config.
  bank rename — ``POST /banks/{name}/rename`` + ``bank_registry.rename_bank``
       (legacy in-place rename = registry rekey only; no relocation).

All hermetic: no real models, no network.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from api import config
from api.models.schemas import (
    PRODUCIBLE_ENTITY_TYPES,
    EntityType,
)
from api.services import bank_registry, providers
from api.services.entity_extractor import EXTRACTION_SYSTEM_PROMPT, entities_to_claims


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# G17 — deadline as a claim, not a standalone entity
# --------------------------------------------------------------------------- #


def test_deadline_is_not_producible_but_still_accepted_for_legacy():
    # The old graph has `deadline` entities — parsing them must never break.
    assert EntityType("deadline") == EntityType.deadline
    # …but the producible set (what Stage-1 may EMIT) no longer includes it.
    assert EntityType.deadline not in PRODUCIBLE_ENTITY_TYPES


def test_extraction_prompt_stops_emitting_deadline_entities():
    prompt = EXTRACTION_SYSTEM_PROMPT
    # The producible type union shown to the model must not offer `deadline`.
    assert "person|project|company|concept|tool|deadline|skill|location" not in prompt
    # Due-dates are attached as a `due` claim/relationship instead.
    assert "due" in prompt.lower()


def test_due_relationship_projects_into_a_claim():
    # A `due` relationship (subject=the thing, object=the date) projects through
    # the existing Stage-1 -> Claim path unchanged (G17 reuses the rel pipeline).
    extracted = [
        {
            "episode_id": "ep_2026-06-17_001",
            "origin": "claude-export",
            "relationships": [
                {
                    "source": "Capstone Thesis",
                    "target": "2026-06-30",
                    "label": "due",
                    "source_episode_timestamp": "2026-06-17T10:00:00Z",
                }
            ],
        }
    ]
    claims = entities_to_claims(extracted, memory_path=None)
    assert len(claims) == 1
    c = claims[0]
    assert c.predicate == "due"
    assert c.object == "2026-06-30"


# --------------------------------------------------------------------------- #
# G18 — split location -> directory vs physical place
# --------------------------------------------------------------------------- #


def test_directory_is_a_real_entity_type():
    assert EntityType("directory") == EntityType.directory
    assert EntityType.directory in PRODUCIBLE_ENTITY_TYPES


def test_extraction_prompt_classifies_paths_as_directory():
    prompt = EXTRACTION_SYSTEM_PROMPT.lower()
    assert "directory" in prompt
    # The guidance distinguishes a filesystem PATH from a physical place.
    assert "path" in prompt


def test_location_endpoint_accepts_directory_type(tmp_path):
    from api.routers import entities as entities_router

    repo = tmp_path
    (repo / "entities").mkdir(parents=True, exist_ok=True)
    target = repo / "proj"
    target.mkdir()
    (target / "a.txt").write_text("x", encoding="utf-8")

    _write_entity(
        repo,
        "src-dir",
        {"name": "src dir", "type": "directory", "path": str(target)},
        "The source directory.",
    )

    class _Settings:
        def __init__(self, p):
            self.memory_path = p

    resp = run(entities_router.get_entity_location("src-dir", settings=_Settings(repo)))
    assert resp.exists is True
    names = {e.name for e in resp.entries}
    assert "a.txt" in names


def test_location_endpoint_still_accepts_legacy_location_type(tmp_path):
    from api.routers import entities as entities_router

    repo = tmp_path
    (repo / "entities").mkdir(parents=True, exist_ok=True)
    target = repo / "place"
    target.mkdir()
    (target / "b.txt").write_text("x", encoding="utf-8")

    _write_entity(
        repo,
        "legacy-loc",
        {"name": "legacy loc", "type": "location", "path": str(target)},
        "A directory recorded as the old location type.",
    )

    class _Settings:
        def __init__(self, p):
            self.memory_path = p

    resp = run(entities_router.get_entity_location("legacy-loc", settings=_Settings(repo)))
    assert resp.exists is True


def test_location_endpoint_rejects_unrelated_type(tmp_path):
    from fastapi import HTTPException

    from api.routers import entities as entities_router

    repo = tmp_path
    (repo / "entities").mkdir(parents=True, exist_ok=True)
    _write_entity(repo, "fastapi", {"name": "FastAPI", "type": "tool"}, "A tool.")

    class _Settings:
        def __init__(self, p):
            self.memory_path = p

    with pytest.raises(HTTPException) as exc:
        run(entities_router.get_entity_location("fastapi", settings=_Settings(repo)))
    assert exc.value.status_code == 400


# --------------------------------------------------------------------------- #
# Per-bank embeddings — search embeds with the bank's recorded model
# --------------------------------------------------------------------------- #


def test_resolve_embed_fn_for_model_local():
    class _FakeST:
        def __init__(self, name):
            self.name = name

        def encode_query(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def encode_document(self, texts):
            return [[0.0, 1.0] for _ in texts]

    settings = config.Settings()
    embed_fn, model = providers.resolve_embed_fn_for_model(
        "google/embeddinggemma-300m",
        settings,
        sentence_transformer_factory=_FakeST,
    )
    assert model == "google/embeddinggemma-300m"
    assert embed_fn(["x"], is_query=True).tolist() == [[1.0, 0.0]]


def test_resolve_embed_fn_for_model_openrouter_gemini(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    class _FakeTransport:
        def __init__(self):
            self.calls = []

        def __call__(self, url, *, headers, json):
            self.calls.append(json)

            class _Resp:
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self_inner):
                    return {"data": [{"embedding": [0.5] * 3072} for _ in json["input"]]}

            return _Resp()

    transport = _FakeTransport()
    settings = config.Settings()
    embed_fn, model = providers.resolve_embed_fn_for_model(
        "google/gemini-embedding-2", settings, transport=transport
    )
    assert model == "google/gemini-embedding-2"
    out = embed_fn(["a", "b"])
    assert out.shape == (2, 3072)
    assert transport.calls[0]["model"] == "google/gemini-embedding-2"


def test_resolve_embed_fn_for_model_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class _FakeEmbeddings:
        def create(self, *, model, input):
            class _D:
                def __init__(self, e):
                    self.embedding = e

            class _R:
                data = [_D([0.1, 0.2]) for _ in input]

            return _R()

    class _FakeOpenAI:
        def __init__(self, *a, **k):
            self.embeddings = _FakeEmbeddings()

    settings = config.Settings()
    embed_fn, model = providers.resolve_embed_fn_for_model(
        "text-embedding-3-small", settings, openai_client_factory=_FakeOpenAI
    )
    assert model == "text-embedding-3-small"
    assert embed_fn(["a"]).shape == (1, 2)


def test_search_uses_banks_recorded_model_not_global(tmp_path, monkeypatch):
    """A bank recorded with model-A queries with model-A even if the global
    default is model-B (the dimension/scoring-hazard fix)."""
    from api.services.vector_index import SqliteVecIndexer

    repo = tmp_path
    (repo / "entities").mkdir(parents=True, exist_ok=True)
    _write_entity(repo, "alpha", {"name": "Alpha", "type": "concept"}, "Alpha body.")

    # Build the index with model-A (a deterministic 2-dim embedder).
    def model_a_embed(texts, *, is_query=False):
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)

    builder = SqliteVecIndexer(repo, embed_fn=model_a_embed, model_name="model-A")
    builder.index_entities()
    assert builder.index_info()["model"] == "model-A"

    # Now: a SEARCH-time indexer constructed WITHOUT an embed_fn must resolve the
    # query embedder from the bank's recorded model ("model-A"), NOT the global
    # default. We inject a resolver-for-model that records which model id it saw.
    seen_models: list[str] = []

    def fake_resolve_for_model(model_id, settings=None, **kw):
        seen_models.append(model_id)

        def _embed(texts, *, is_query=False):
            return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)

        return _embed, model_id

    monkeypatch.setattr(
        "api.services.providers.resolve_embed_fn_for_model", fake_resolve_for_model
    )

    searcher = SqliteVecIndexer(repo)  # no embed_fn -> must use recorded model
    results = searcher.search_entities("alpha", top_k=3)
    assert results, "search should return the indexed entity"
    assert seen_models == ["model-A"], seen_models


# --------------------------------------------------------------------------- #
# Bank rename
# --------------------------------------------------------------------------- #


def test_rename_legacy_default_rekeys_registry_only(tmp_path):
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    (tmp_path / "entities" / "x.md").write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
    # Force the registry to exist with the legacy default recorded.
    bank_registry.create_bank(tmp_path, "Other")

    bank_registry.rename_bank(tmp_path, "default", "original-v1")

    data = bank_registry.list_banks(tmp_path)
    names = {b["name"] for b in data["banks"]}
    assert "original-v1" in names
    assert "default" not in names
    # Legacy files stayed at the root (no relocation).
    assert (tmp_path / "entities" / "x.md").exists()
    assert not (tmp_path / "banks" / "original-v1").exists()
    # The renamed legacy bank still resolves to the root.
    assert bank_registry.bank_dir(tmp_path, "original-v1") == tmp_path


def test_rename_legacy_default_repoints_active(tmp_path):
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    # default is active by default; rename it and confirm active follows.
    bank_registry._ensure_registry(tmp_path)
    bank_registry.rename_bank(tmp_path, "default", "original-v1")
    data = bank_registry.list_banks(tmp_path)
    assert data["active"] == "original-v1"


def test_rename_non_legacy_bank_moves_directory(tmp_path):
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    bank_registry.create_bank(tmp_path, "Lab")
    (tmp_path / "banks" / "lab" / "entities" / "e.md").write_text("e", encoding="utf-8")

    bank_registry.rename_bank(tmp_path, "lab", "Research")

    assert bank_registry.bank_dir(tmp_path, "research") == tmp_path / "banks" / "research"
    assert (tmp_path / "banks" / "research" / "entities" / "e.md").exists()
    assert not (tmp_path / "banks" / "lab").exists()
    names = {b["name"] for b in bank_registry.list_banks(tmp_path)["banks"]}
    assert "research" in names and "lab" not in names


def test_rename_non_legacy_repoints_active_when_active(tmp_path):
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    bank_registry.create_bank(tmp_path, "Lab")
    bank_registry.activate_bank(tmp_path, "lab")
    bank_registry.rename_bank(tmp_path, "lab", "Research")
    assert bank_registry.list_banks(tmp_path)["active"] == "research"


def test_rename_unknown_raises(tmp_path):
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    bank_registry._ensure_registry(tmp_path)
    with pytest.raises(ValueError, match="Unknown bank"):
        bank_registry.rename_bank(tmp_path, "ghost", "x")


def test_rename_collision_raises(tmp_path):
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    bank_registry.create_bank(tmp_path, "Lab")
    bank_registry.create_bank(tmp_path, "Research")
    with pytest.raises(ValueError, match="already exists"):
        bank_registry.rename_bank(tmp_path, "lab", "Research")


def test_rename_blank_raises(tmp_path):
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    bank_registry.create_bank(tmp_path, "Lab")
    with pytest.raises(ValueError):
        bank_registry.rename_bank(tmp_path, "lab", "   ")


# --- rename HTTP endpoint --------------------------------------------------


def _rename_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    return TestClient(main.app)


def test_rename_endpoint_renames_non_legacy(tmp_path, monkeypatch):
    client = _rename_client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Lab"})
    r = client.post("/banks/lab/rename", json={"newName": "Research"})
    assert r.status_code == 200, r.text
    names = {b["name"] for b in r.json()["banks"]}
    assert "research" in names and "lab" not in names
    config.get_settings.cache_clear()


def test_rename_endpoint_unknown_404(tmp_path, monkeypatch):
    client = _rename_client(tmp_path, monkeypatch)
    r = client.post("/banks/ghost/rename", json={"newName": "x"})
    assert r.status_code == 404
    config.get_settings.cache_clear()


def test_rename_endpoint_collision_409(tmp_path, monkeypatch):
    client = _rename_client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Lab"})
    client.post("/banks", json={"name": "Research"})
    r = client.post("/banks/lab/rename", json={"newName": "Research"})
    assert r.status_code == 409
    config.get_settings.cache_clear()


def test_rename_endpoint_blank_400(tmp_path, monkeypatch):
    client = _rename_client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Lab"})
    r = client.post("/banks/lab/rename", json={"newName": "  "})
    assert r.status_code == 400
    config.get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# G18 (cont.) — `directory` entities are discoverable in the hub tier
# --------------------------------------------------------------------------- #


def test_directory_type_has_a_hub_so_entities_are_discoverable(tmp_path):
    # G18 promotes `directory` to a first-class producible type. Without a
    # TYPE_HUBS entry, directory entities are silently skipped by the hub
    # generator (land in by_type["directory"] but never written), so they
    # never appear in the progressive-disclosure/bookworm surface.
    from api.services import hub_builder

    assert any(etype == "directory" for etype, _stem, _name in hub_builder.TYPE_HUBS), (
        "directory must have a TYPE_HUBS entry"
    )

    (tmp_path / "entities").mkdir(parents=True)
    _write_entity(
        tmp_path,
        "cicada-repo",
        {
            "type": "directory",
            "status": "active",
            "confidence": 0.9,
            "name": "Cicada Repo",
        },
        "The repo at /Users/rorosaga/cicada.",
    )

    settings = config.get_settings()
    result = hub_builder.regenerate_hubs_and_index(tmp_path, settings)

    # A directory hub file was written, and it lists the directory entity.
    dir_stem = next(stem for etype, stem, _ in hub_builder.TYPE_HUBS if etype == "directory")
    hub_file = tmp_path / "hubs" / f"{dir_stem}.md"
    assert hub_file.exists(), f"{dir_stem}.md hub must be generated"
    assert f"{dir_stem}.md" in result["hub_files"]
    assert "Cicada Repo" in hub_file.read_text(encoding="utf-8")


# --- helpers ---------------------------------------------------------------


def _write_entity(repo, eid, frontmatter, body):
    import yaml

    fm = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    (repo / "entities" / f"{eid}.md").write_text(
        f"---\n{fm}---\n\n{body}\n", encoding="utf-8"
    )
