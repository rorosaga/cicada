"""G117 R2 (Task 2, step 7a) — ``EntityResponse.is_owner`` on ``GET /entities/{id}``.

Task 1 added ``GraphNode.is_owner`` (backs ``/graph``) from the entity's own
``owner: true`` frontmatter (written by ``owner_identity.ensure_owner_entity``),
but never touched the detail-card response, ``GET /entities/{id}``. Without
this mirror, ``EntityDetailCard`` has no way to render "Name (you)" — it would
need a second lookup against ``/graph`` just to answer "is this the owner's
page", which the plan (R2 step 7) rejects in favor of one additive field on
the response the detail card already fetches.

Hermetic: a throwaway memory workspace in a tmp dir, ``CICADA_MEMORY_PATH``
pointed at it. No git init needed — ``get_entity_history`` degrades to ``[]``
on a non-repo. The live ``memory/`` is never touched.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser


def _make_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def _write_person(memory: Path, eid: str, *, owner: bool) -> None:
    fm = {
        "name": "Bob Example",
        "type": "person",
        "status": "active",
        "confidence": 0.9,
        "created": "2026-09-01",
        "last_referenced": "2026-09-01",
        "decay_rate": 0.0,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    if owner:
        fm["owner"] = True
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, "## Summary\n\nThe owner.")


def test_owner_page_reports_is_owner_true(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)
    _write_person(memory, "bob-example", owner=True)

    resp = client.get("/entities/bob-example")
    assert resp.status_code == 200, resp.text
    assert resp.json()["isOwner"] is True


def test_non_owner_page_reports_is_owner_false(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)
    _write_person(memory, "alpha-project", owner=False)

    resp = client.get("/entities/alpha-project")
    assert resp.status_code == 200, resp.text
    assert resp.json()["isOwner"] is False
