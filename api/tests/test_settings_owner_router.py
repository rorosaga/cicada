"""G117 — GET/PUT /settings/owner, end to end through the FastAPI app."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, markdown_parser, owner_identity, predicates


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    return TestClient(main.app), memory


def test_get_before_any_put_reads_as_unset(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/settings/owner").json()
    assert body == {"name": "", "handle": None, "email": None, "observer": "owner", "entityId": None}


def test_put_writes_owner_json_and_the_entity_page_and_get_reflects_it(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    resp = client.put("/settings/owner", json={"name": "Bob Example", "handle": "@bob"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "name": "Bob Example", "handle": "@bob", "email": None,
        "observer": "bob-example", "entityId": "bob-example",
    }
    assert (memory / "entities" / "bob-example.md").exists()
    again = client.get("/settings/owner").json()
    assert again == body


def test_put_requires_a_name(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.put("/settings/owner", json={"name": "  "}).status_code == 400


def test_graph_marks_the_owner_node(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    client.put("/settings/owner", json={"name": "Bob Example"})
    nodes = client.get("/graph").json()["nodes"]
    owner_nodes = [n for n in nodes if n["id"] == "bob-example"]
    assert owner_nodes and owner_nodes[0]["isOwner"] is True
