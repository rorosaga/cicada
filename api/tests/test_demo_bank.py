"""G117 — the demo bank is deterministic and exercises every read path a
fresh viewer's first click touches. No LLM, no network: pure file + git I/O.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, bank_registry, demo_bank


def _client(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    return TestClient(main.app), root


def test_populate_writes_the_expected_counts(tmp_path):
    bank_dir = tmp_path / "demo"
    bank_registry.scaffold_bank(bank_dir)
    demo_bank.populate(bank_dir)
    assert len(list((bank_dir / "entities").glob("*.md"))) >= 60
    assert len(list((bank_dir / "episodes").glob("*.md"))) >= 40
    assert len(list((bank_dir / "inbox").glob("inbox-*.md"))) == 6
    assert (bank_dir / "entities" / "bob-example.md").exists()  # placeholder owner (R7)


def test_populate_is_only_placeholder_names(tmp_path):
    bank_dir = tmp_path / "demo"
    bank_registry.scaffold_bank(bank_dir)
    demo_bank.populate(bank_dir)
    text = "\n".join(p.read_text() for p in bank_dir.rglob("*.md"))
    assert "http" not in text or "example.com" in text  # no real domains
    assert "rodrigo" not in text.lower()


def test_populate_writes_real_git_history_with_trailers(tmp_path):
    """R7's `_commit_history` groups writes the way a real Sleep cycle would
    (Sleep-cycle commits with Cicada-Author/Cicada-Engine trailers, one
    Cicada-Author: user commit for the owner page) — so a fresh demo bank's
    `GET /contributors` and entity-history views have something real to show
    rather than one big untrailered commit."""
    import subprocess

    bank_dir = tmp_path / "demo"
    bank_registry.scaffold_bank(bank_dir)
    demo_bank.populate(bank_dir)
    log = subprocess.run(
        ["git", "-C", str(bank_dir), "log", "--format=%B---END---"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "Cicada-Author:" in log
    assert "Cicada-Author: user" in log
    assert log.count("---END---") >= 2  # more than one commit


def test_endpoint_creates_and_activates(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    resp = client.post("/banks/demo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] == "demo"
    assert any(b["name"] == "demo" for b in body["banks"])

    # Every read path the sheet's "try it" flow touches must answer.
    assert client.get("/graph").status_code == 200
    assert client.get("/inbox").status_code == 200
    assert client.get("/sleep/episodes").status_code == 200
    assert client.get("/sources/overview").status_code == 200


def test_endpoint_is_409_if_demo_already_exists(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.post("/banks/demo").status_code == 200
    assert client.post("/banks/demo").status_code == 409
