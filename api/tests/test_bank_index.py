from __future__ import annotations

import os
import time

from api.services import bank_index


def _write(path, fm: str, body: str = "hello"):
    path.write_text(f"---\n{fm}\n---\n\n{body}\n", encoding="utf-8")


def test_parses_once_and_reuses(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\nprocessed: false\ntimestamp: '2026-08-01T10:00:00'")
    _write(d / "ep2.md", "id: ep2\nprocessed: true\ntimestamp: '2026-08-02T10:00:00'")
    before = bank_index.parse_count
    files = bank_index.files(tmp_path, "episodes")
    assert [f.stem for f in files] == ["ep1", "ep2"]
    assert files[0].frontmatter["processed"] is False
    assert bank_index.parse_count == before + 2
    bank_index.files(tmp_path, "episodes")
    assert bank_index.parse_count == before + 2  # no re-parse


def test_reparses_only_changed_file(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\nprocessed: false")
    _write(d / "ep2.md", "id: ep2\nprocessed: false")
    bank_index.files(tmp_path, "episodes")
    before = bank_index.parse_count
    time.sleep(0.01)
    _write(d / "ep2.md", "id: ep2\nprocessed: true")
    os.utime(d / "ep2.md", None)
    files = bank_index.files(tmp_path, "episodes")
    assert bank_index.parse_count == before + 1
    assert {f.stem: f.frontmatter["processed"] for f in files} == {"ep1": False, "ep2": True}


def test_deleted_file_disappears_and_body_is_lazy(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1", body="the body")
    _write(d / "ep2.md", "id: ep2")
    assert bank_index.files(tmp_path, "episodes")[0].body() == "the body"
    (d / "ep2.md").unlink()
    assert [f.stem for f in bank_index.files(tmp_path, "episodes")] == ["ep1"]


def test_missing_dir_and_malformed_file(tmp_path):
    bank_index.invalidate()
    assert bank_index.files(tmp_path, "episodes") == []
    d = tmp_path / "episodes"; d.mkdir()
    (d / "bad.md").write_text("---\n: [unclosed\n---\n")
    _write(d / "ok.md", "id: ok")
    assert [f.stem for f in bank_index.files(tmp_path, "episodes")] == ["ok"]


def test_dir_stamp_changes_on_write(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "entities"; d.mkdir()
    _write(d / "a.md", "id: a")
    s1 = bank_index.dir_stamp(tmp_path, "entities")
    time.sleep(0.01)
    _write(d / "b.md", "id: b")
    s2 = bank_index.dir_stamp(tmp_path, "entities")
    assert s1 != s2 and s2[0] == 2
