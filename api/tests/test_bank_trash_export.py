"""G139 R-O18…R-O20 — delete moves a bank to <root>/.trash (reversible), never
the active or the in-place legacy bank; the trash is never tracked; export zips
a bank's pages and history, never the derived files or another bank."""
from __future__ import annotations

import subprocess
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_registry, sleep_cycle

NOW = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)


def _root(tmp_path):
    root = tmp_path / "root"
    bank_registry.scaffold_bank(root)          # the legacy default, a git repo in place
    bank_registry.create_bank(root, "Scratch")
    (root / "banks" / "scratch" / "entities" / "alpha-project.md").write_text("---\ntype: project\n---\n", encoding="utf-8")
    return root


def test_trash_moves_the_bank_and_forgets_it(tmp_path):
    root = _root(tmp_path)
    dst = bank_registry.trash_bank(root, "scratch", now=NOW)
    assert dst == root / ".trash" / "scratch-20260923T100000Z"
    assert (dst / "entities" / "alpha-project.md").exists()
    assert not (root / "banks" / "scratch").exists()
    assert "scratch" not in bank_registry.load_registry(root)["banks"]


def test_the_trash_never_shows_in_the_root_repo(tmp_path):
    root = _root(tmp_path)
    bank_registry.trash_bank(root, "scratch", now=NOW)
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root,
                            capture_output=True, text=True, check=True).stdout
    assert ".trash" not in status, "an untracked trashed bank would be swept in by the next git add -A"
    assert ".trash/" in (root / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_refuses_the_active_and_the_legacy_and_the_unknown(tmp_path):
    root = _root(tmp_path)
    with pytest.raises(bank_registry.LegacyBankInPlace):
        bank_registry.trash_bank(root, "default")
    bank_registry.activate_bank(root, "scratch")
    with pytest.raises(bank_registry.BankInUse):
        bank_registry.trash_bank(root, "scratch")
    with pytest.raises(bank_registry.UnknownBank):
        bank_registry.trash_bank(root, "ghost")


def test_duplicate_of_the_legacy_root_skips_the_trash(tmp_path):
    root = _root(tmp_path)
    bank_registry.trash_bank(root, "scratch", now=NOW)
    slug = bank_registry.duplicate_bank(root, "default", "Copy")
    assert not (root / "banks" / slug / ".trash").exists()


def test_list_banks_says_which_bank_is_the_folder_itself(tmp_path):
    root = _root(tmp_path)
    rows = {b["name"]: b for b in bank_registry.list_banks(root)["banks"]}
    assert rows["default"]["legacy"] is True and rows["scratch"]["legacy"] is False


def test_export_zips_pages_and_history_but_not_derived_files_or_other_banks(tmp_path):
    root = _root(tmp_path)
    (root / "vector_index.db").write_bytes(b"derived")
    (root / "entities" / "bob-example.md").write_text("---\ntype: person\n---\n", encoding="utf-8")
    path = bank_registry.export_zip(root, "default", tmp_path / "exports", now=NOW)
    names = zipfile.ZipFile(path).namelist()
    assert "default/entities/bob-example.md" in names
    assert any(n.startswith("default/.git/") for n in names), "history travels with the pages"
    assert not any(n.endswith("vector_index.db") for n in names)
    assert not any(n.startswith("default/banks/") or n == "default/banks.yaml" for n in names)
    scratch = zipfile.ZipFile(bank_registry.export_zip(root, "scratch", tmp_path / "exports", now=NOW)).namelist()
    assert "scratch/entities/alpha-project.md" in scratch


def _client(tmp_path, monkeypatch):
    root = _root(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    config.get_settings.cache_clear()
    return TestClient(main.app), root


def test_delete_route_and_its_refusals(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    assert client.delete("/banks/default").status_code == 409
    assert client.delete("/banks/ghost").status_code == 404
    resp = client.delete("/banks/scratch")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trashedTo"].startswith(".trash/scratch-")
    assert all(b["name"] != "scratch" for b in body["banks"])
    assert str(tmp_path) not in resp.text, "no absolute path on the wire"
    config.get_settings.cache_clear()


def test_export_route_streams_and_cleans_up(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    resp = client.get("/banks/scratch/export")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/zip"
    assert "scratch" in resp.headers["content-disposition"]
    assert not list((tmp_path / "_default_cicada_home" / "exports").glob("*.zip")), "deleted after the response"
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    assert client.get("/banks/scratch/export").status_code == 409
    assert client.get("/banks/ghost/export").status_code in (404, 409)
    config.get_settings.cache_clear()


def test_a_body_cached_before_legacy_existed_is_refetched_once(tmp_path, monkeypatch):
    """R-O18 — the app keeps the `/banks` body it cached under an ETag on every
    304. The recipe's shape tag makes an ETag minted before `legacy` existed
    miss once, so the Delete menu never offers the memory folder itself."""
    import hashlib

    from api.services import bank_index
    from api.services.graph_builder import file_mtime

    client, root = _client(tmp_path, monkeypatch)
    parts = [str(file_mtime(root / "banks.yaml"))]          # the pre-G139 recipe
    for name in sorted(bank_registry.load_registry(root)["banks"]):
        path = bank_registry.bank_dir(root, name)
        parts.append(f"{name}:{bank_index.dir_stamp(path, 'entities')}:{bank_index.dir_stamp(path, 'episodes')}")
    old = '"' + hashlib.sha1("|".join(parts).encode()).hexdigest()[:16] + '"'
    fresh = client.get("/banks", headers={"If-None-Match": old})
    assert fresh.status_code == 200
    assert {b["name"]: b["legacy"] for b in fresh.json()["banks"]} == {"default": True, "scratch": False}
    assert client.get("/banks", headers={"If-None-Match": fresh.headers["etag"]}).status_code == 304
    config.get_settings.cache_clear()


def test_an_abandoned_export_is_swept_by_the_next_one(tmp_path):
    """R-O20 — every archive is a full copy of a bank; one whose download broke
    off never reached the response's cleanup, so the next export removes it."""
    import os
    import time

    root = _root(tmp_path)
    exports = tmp_path / "exports"
    exports.mkdir()
    stale = exports / "cicada-scratch-20260101T000000Z.zip"
    stale.write_bytes(b"x")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = bank_registry.export_zip(root, "scratch", exports, now=NOW)
    assert fresh.exists() and not stale.exists()
