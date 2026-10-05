"""Audit 2026-10-02 A04 — duplicating a bank never follows a symlink.

`shutil.copytree`/`copy2` dereference links by default, so a link inside a bank
pulled whatever it pointed at — a directory or file outside the bank — into the
copy as ordinary files. Export already skips links (`os.walk(followlinks=False)`
plus an `is_symlink` check); duplicate now applies the same policy: a symlink is
skipped at any depth, whatever it points at. Synthetic directories only.
"""
from __future__ import annotations

from pathlib import Path

from api.services import bank_registry


def _source(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "registry"
    slug = bank_registry.create_bank(root, "synthetic-source", seed_owner=False)
    bank = bank_registry.bank_dir(root, slug)
    outside = tmp_path / "outside-bank"
    outside.mkdir()
    (outside / "synthetic-only.txt").write_text("Synthetic external file.", encoding="utf-8")
    (bank / "entities" / "alpha-project.md").write_text("---\ntype: project\n---\nBody.\n", encoding="utf-8")
    return root, bank, outside


def _copy(root: Path) -> Path:
    slug = bank_registry.duplicate_bank(root, "synthetic-source", "synthetic-copy")
    return bank_registry.bank_dir(root, slug)


def _all_names(path: Path) -> set[str]:
    return {str(p.relative_to(path)) for p in path.rglob("*") if ".git" not in p.relative_to(path).parts}


def test_a_top_level_directory_link_outside_the_bank_is_not_copied(tmp_path):
    root, bank, outside = _source(tmp_path)
    (bank / "external-alias").symlink_to(outside, target_is_directory=True)
    copy = _copy(root)
    assert not (copy / "external-alias").exists() and not (copy / "external-alias").is_symlink()
    assert (copy / "entities" / "alpha-project.md").is_file(), "real pages still copy"


def test_a_top_level_file_link_is_not_copied(tmp_path):
    root, bank, outside = _source(tmp_path)
    (bank / "notes.txt").symlink_to(outside / "synthetic-only.txt")
    copy = _copy(root)
    assert not (copy / "notes.txt").exists() and not (copy / "notes.txt").is_symlink()


def test_nested_links_are_not_copied_at_any_depth(tmp_path):
    root, bank, outside = _source(tmp_path)
    nested = bank / "sources" / "deep"
    nested.mkdir(parents=True)
    (nested / "dir-alias").symlink_to(outside, target_is_directory=True)
    (nested / "file-alias.md").symlink_to(outside / "synthetic-only.txt")
    (nested / "real.md").write_text("Real.\n", encoding="utf-8")
    copy = _copy(root)
    names = _all_names(copy)
    assert "sources/deep/real.md" in names
    assert not any("alias" in n for n in names)
    assert not any(n.endswith("synthetic-only.txt") for n in names)


def test_a_dangling_link_does_not_break_the_copy(tmp_path):
    root, bank, _ = _source(tmp_path)
    (bank / "entities" / "gone.md").symlink_to(tmp_path / "does-not-exist.md")
    (bank / "gone-dir").symlink_to(tmp_path / "missing-dir", target_is_directory=True)
    copy = _copy(root)
    assert not (copy / "entities" / "gone.md").is_symlink()
    assert not (copy / "gone-dir").is_symlink()
    assert (copy / "entities" / "alpha-project.md").is_file()


def test_a_link_to_a_page_inside_the_same_bank_is_skipped_too(tmp_path):
    # One policy, like export's: a link is skipped whatever it points at. The page
    # it pointed at is copied in its own right.
    root, bank, _ = _source(tmp_path)
    (bank / "entities" / "alias.md").symlink_to(bank / "entities" / "alpha-project.md")
    copy = _copy(root)
    assert not (copy / "entities" / "alias.md").exists()
    assert (copy / "entities" / "alpha-project.md").is_file()
