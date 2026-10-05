"""Synthetic reproductions for audit A01, A02 and A04; no live bank or LLM.

Run with the repository's API virtualenv interpreter. Results describe the
audited implementation; these are diagnostic probes, not passing regression
tests for a future fix. All writable inputs are created and removed under /tmp.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def run(root: Path) -> None:
    # Set before imports: never inherit a real bank, credentials or dotenv file.
    for key, value in {
        "CICADA_HOME": str(root / "home"),
        "CICADA_MEMORY_PATH": str(root / "memory"),
        "CICADA_CAPTURE": "off",
        "PYTHON_DOTENV_DISABLED": "1",
        "CICADA_API_AUTH": "off",
        "CICADA_ALLOW_CONNECTOR_FETCH": "off",
        "CICADA_ALLOW_FEED_FETCH": "off",
        "CICADA_ALLOW_LOGO_FETCH": "off",
    }.items():
        os.environ[key] = value
    from api.services import bank_index, bank_registry, markdown_parser, sleep_cycle

    bank = root / "memory"
    episodes = bank / "episodes"
    episodes.mkdir(parents=True)
    episode = episodes / "2026-10-02-001.md"
    fm = {"id": episode.stem, "timestamp": "2026-10-02T10:00:00+00:00",
          "source": "synthetic-audit", "processed": False, "content_hash": "revision-one"}
    markdown_parser.write(episode, fm, "Synthetic first turn.")
    selected = sleep_cycle._get_unprocessed_episodes(bank)
    markdown_parser.write(episode, {**fm, "content_hash": "revision-two"},
                          "Synthetic first turn. Later synthetic correction.")
    sleep_cycle._mark_episodes_processed(selected)
    current = markdown_parser.parse(episode)
    bank_index.invalidate(bank)
    print(json.dumps({"finding": "A01", "selected_contains_correction":
                      "Later synthetic correction" in selected[0]["content"],
                      "new_revision_marked_processed": current.frontmatter["processed"],
                      "remaining_queue": len(sleep_cycle._get_unprocessed_episodes(bank))}))

    target = root / "atomic-write.md"
    markdown_parser.write(target, {"id": "synthetic-page"}, "Original synthetic body.")
    original = target.read_bytes()
    original_open = Path.open

    class InterruptedWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def write(self, value):
            self.stream.write(value[:20])
            self.stream.flush()
            raise OSError("synthetic interruption after partial write")

    def interrupted_open(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == target and "w" in mode:
            return InterruptedWriter(stream)
        return stream

    with patch.object(Path, "open", interrupted_open):
        try:
            markdown_parser.write(target, {"id": "synthetic-page"}, "Replacement synthetic body.")
        except OSError:
            pass
    print(json.dumps({"finding": "A02", "old_file_preserved": target.read_bytes() == original,
                      "bytes_remaining": len(target.read_bytes())}))

    registry_root = root / "registry"
    source = bank_registry.create_bank(registry_root, "synthetic-source", seed_owner=False)
    source_path = bank_registry.bank_dir(registry_root, source)
    outside = root / "outside-bank"
    outside.mkdir()
    (outside / "synthetic-only.txt").write_text("Synthetic external file.", encoding="utf-8")
    (source_path / "external-alias").symlink_to(outside, target_is_directory=True)
    duplicate = bank_registry.duplicate_bank(registry_root, source, "synthetic-copy")
    copied_alias = bank_registry.bank_dir(registry_root, duplicate) / "external-alias"
    print(json.dumps({"finding": "A04", "external_file_copied":
                      (copied_alias / "synthetic-only.txt").is_file(),
                      "copied_alias_is_symlink": copied_alias.is_symlink()}))


if __name__ == "__main__":
    with TemporaryDirectory(prefix="cicada-audit-storage-", dir="/private/tmp") as scratch:
        run(Path(scratch))
