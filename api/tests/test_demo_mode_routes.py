"""G117 round 4 (T-Demo, F-08) — the demo's doors on the server: `/banks` says which bank is the demo (from
`demo_guard`, never the name), `POST /banks/leave-demo` returns to the person's own memory, and `POST /banks/demo`
re-opens a demo that already exists instead of refusing. Hermetic: a bank is marked demo by its manifest
(`demo_guard.write_manifest`), so no test here pays for a full `populate`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, bank_registry, demo_bank, demo_guard


def _client(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    return TestClient(main.app), root


def _demo(root, name: str = "demo") -> None:
    bank_registry.create_bank(root, name)
    demo_guard.write_manifest(bank_registry.bank_dir(root, name))


def _rows(body) -> dict:
    return {b["name"]: b for b in body["banks"]}


def test_banks_rows_say_which_bank_is_the_demo_and_the_name_never_decides(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    _demo(root, "try-it")
    bank_registry.create_bank(root, "demo")   # a real bank the person happened to call "demo"
    rows = _rows(client.get("/banks").json())
    assert rows["try-it"]["demo"] is True
    assert rows["demo"]["demo"] is False and rows["default"]["demo"] is False
    config.get_settings.cache_clear()


def test_the_banks_etag_still_revalidates(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    first = client.get("/banks")
    assert client.get("/banks", headers={"If-None-Match": first.headers["etag"]}).status_code == 304
    config.get_settings.cache_clear()


def test_leaving_returns_to_the_bank_left_most_recently(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    bank_registry.create_bank(root, "work")
    _demo(root)
    bank_registry.activate_bank(root, "work")
    bank_registry.activate_bank(root, "demo")   # entering the demo stamps `work` (R-CS11)
    body = client.post("/banks/leave-demo").json()
    assert body["active"] == "work"
    assert _rows(body)["demo"]["demo"] is True, "the demo stays, ready for the next visit"
    config.get_settings.cache_clear()


def test_with_no_stamp_it_returns_to_the_default_memory(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    bank_registry.create_bank(root, "work")
    _demo(root)
    registry = bank_registry.load_registry(root)
    registry["active"] = "demo"                 # a demo opened before `last_active_at` existed
    bank_registry.save_registry(root, registry)
    assert client.post("/banks/leave-demo").json()["active"] == "default"
    config.get_settings.cache_clear()


def test_with_no_real_memory_it_makes_one(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    _demo(root)
    bank_registry.save_registry(root, {"active": "demo", "banks": {"demo": {"legacy": False, "created": "2026-09-01"}}})
    body = client.post("/banks/leave-demo").json()
    assert body["active"] == "my-memory"
    assert _rows(body)["my-memory"]["demo"] is False
    assert (root / "banks" / "my-memory" / "entities").is_dir()
    config.get_settings.cache_clear()


def test_outside_the_demo_leaving_moves_nothing(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    _demo(root)
    r = client.post("/banks/leave-demo")
    assert r.status_code == 200 and r.json()["active"] == "default"
    config.get_settings.cache_clear()


def test_a_demo_that_exists_is_reopened_never_repopulated(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    _demo(root)

    def boom(*_a, **_k):
        raise AssertionError("an existing demo must never be re-populated")

    monkeypatch.setattr(demo_bank, "populate", boom)
    r = client.post("/banks/demo")
    assert r.status_code == 200 and r.json()["active"] == "demo"
    config.get_settings.cache_clear()


def test_a_real_bank_called_demo_is_still_refused(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    bank_registry.create_bank(root, "demo")
    r = client.post("/banks/demo")
    assert r.status_code == 409 and r.json()["detail"] == "Bank 'demo' already exists"
    config.get_settings.cache_clear()
