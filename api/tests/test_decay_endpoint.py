"""G66 §1.7 — decay_class on the wire + the user-override endpoint."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.schemas import DecayClass, EntityDecayUpdate
from api.routers import entities as entities_router
from api.services import graph_builder, markdown_parser


def run(coro):
    return asyncio.run(coro)


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _memory(tmp_path: Path, **fm) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    base = {
        "name": "MongoDB",
        "type": "tool",
        "status": "active",
        "confidence": 0.8,
        "created": "2026-01-01",
        "last_referenced": "2026-08-01",
        "decay_rate": 0.05,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    base.update(fm)
    markdown_parser.write(repo / "entities" / "mongodb.md", base, "## Summary\n\nA db.")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _fm(repo: Path) -> dict:
    return markdown_parser.parse(repo / "entities" / "mongodb.md").frontmatter


# --- GET surfaces the class -------------------------------------------------


def test_entity_response_carries_the_resolved_class(tmp_path):
    repo = _memory(tmp_path, decay_class="volatile", decay_rate=0.15)
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))
    assert resp.decay_class is DecayClass.volatile
    assert resp.decay_rate == 0.15


def test_entity_response_infers_the_class_for_a_legacy_page(tmp_path):
    repo = _memory(tmp_path, type="media", decay_rate=0.03)
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))
    assert resp.decay_class is DecayClass.evergreen
    assert resp.decay_rate == 0.0


def test_entity_response_serialises_the_field_as_camel_case(tmp_path):
    repo = _memory(tmp_path)
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))
    assert resp.model_dump(by_alias=True)["decayClass"] == "active"


# --- graph nodes ------------------------------------------------------------


def test_graph_nodes_carry_the_class_and_fold_it_into_the_content_hash(tmp_path):
    repo = _memory(tmp_path)
    graph_builder._CACHE["key"] = None
    before = {n.id: n for n in graph_builder.build_graph(repo).nodes}["mongodb"]
    assert before.decay_class is DecayClass.active

    fm = _fm(repo)
    fm["decay_class"] = "volatile"
    markdown_parser.write(repo / "entities" / "mongodb.md", fm, "## Summary\n\nA db.")
    graph_builder._CACHE["key"] = None
    after = {n.id: n for n in graph_builder.build_graph(repo).nodes}["mongodb"]

    assert after.decay_class is DecayClass.volatile
    assert after.content_hash != before.content_hash


# --- PUT /entities/{id}/decay -----------------------------------------------


def test_put_decay_writes_the_class_and_its_mapped_rate(tmp_path):
    repo = _memory(tmp_path)
    resp = run(
        entities_router.update_entity_decay(
            "mongodb",
            EntityDecayUpdate(decay_class=DecayClass.evergreen),
            settings=_FakeSettings(repo),
        )
    )
    assert resp.decay_class is DecayClass.evergreen
    fm = _fm(repo)
    assert fm["decay_class"] == "evergreen"
    assert fm["decay_rate"] == 0.0


def test_put_decay_maps_each_class_to_its_rate(tmp_path):
    for cls, rate in [
        (DecayClass.durable, 0.02),
        (DecayClass.active, 0.05),
        (DecayClass.volatile, 0.15),
    ]:
        repo = _memory(tmp_path / cls.value)
        run(
            entities_router.update_entity_decay(
                "mongodb", EntityDecayUpdate(decay_class=cls),
                settings=_FakeSettings(repo),
            )
        )
        fm = _fm(repo)
        assert fm["decay_class"] == cls.value
        assert fm["decay_rate"] == rate


def test_put_decay_commits_as_the_user_with_the_companion_app_trigger(tmp_path):
    repo = _memory(tmp_path)
    run(
        entities_router.update_entity_decay(
            "mongodb", EntityDecayUpdate(decay_class=DecayClass.volatile),
            settings=_FakeSettings(repo),
        )
    )
    log = _git(repo, "log", "--format=%s%n%b", "-1")
    assert "Cicada-Author: user" in log
    assert "user/companion_app" in log
    assert "entities/mongodb.md" in log


def test_put_decay_does_not_sweep_unrelated_dirty_files_into_its_commit(tmp_path):
    repo = _memory(tmp_path)
    (repo / "scratch.txt").write_text("dirty", encoding="utf-8")
    run(
        entities_router.update_entity_decay(
            "mongodb", EntityDecayUpdate(decay_class=DecayClass.durable),
            settings=_FakeSettings(repo),
        )
    )
    assert "scratch.txt" in _git(repo, "status", "--porcelain")


def test_put_decay_leaves_every_other_frontmatter_key_and_the_body_untouched(tmp_path):
    repo = _memory(tmp_path, tags=["database"], confidence=0.83)
    body_before = markdown_parser.parse(repo / "entities" / "mongodb.md").body
    run(
        entities_router.update_entity_decay(
            "mongodb", EntityDecayUpdate(decay_class=DecayClass.durable),
            settings=_FakeSettings(repo),
        )
    )
    fm = _fm(repo)
    assert fm["tags"] == ["database"]
    assert fm["confidence"] == 0.83
    assert fm["version"] == 1, "a decay override is not a content revision"
    assert markdown_parser.parse(repo / "entities" / "mongodb.md").body == body_before


def test_put_decay_404s_for_a_missing_entity(tmp_path):
    repo = _memory(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(
            entities_router.update_entity_decay(
                "nope", EntityDecayUpdate(decay_class=DecayClass.active),
                settings=_FakeSettings(repo),
            )
        )
    assert exc.value.status_code == 404


def test_the_request_model_rejects_an_unknown_class():
    with pytest.raises(Exception):
        EntityDecayUpdate(decay_class="unlimited")


def test_the_request_model_accepts_both_camel_and_snake_case_bodies():
    assert EntityDecayUpdate(**{"decayClass": "durable"}).decay_class is DecayClass.durable
    assert EntityDecayUpdate(**{"decay_class": "durable"}).decay_class is DecayClass.durable
