"""Design taste — the MCP image_path refusal is by file identity, never by spelling (review blocker, 2026-10-14).

macOS's default volume is case-insensitive and firmlinks /Users, /private… onto /System/Volumes/Data, so a re-cased or
firmlinked path names a refused folder (~/.claude, ~/Library, ~/.cicada, the bank) while comparing unequal as text.
These five cases were the reviewer's reproduction and stay as permanent tests. Synthetic only: a fake HOME, a
synthetic PNG."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from _synthetic_bank import _bank
from api.services import demo_pictures, design_index, design_refs, mcp_tools

DARK = demo_pictures.website((20, 22, 28), (29, 32, 41), (226, 230, 240), (124, 156, 255))


def _case_insensitive(p: Path) -> bool:
    probe = p / "CaseProbe"
    probe.write_text("x")
    try:
        return (p / "caseprobe").exists()
    finally:
        probe.unlink()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    bank = _bank(tmp_path, git=False)
    monkeypatch.setattr(design_index, "default_embedders", lambda environ=None: None)
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_x", harness="claude-code"), bank


@pytest.mark.parametrize("root,recased", [(".claude", ".CLAUDE"), ("Library", "LIBRARY"), (".cicada", ".Cicada")])
def test_a_recased_refused_root_is_still_refused(ctx, root, recased):
    c, bank = ctx
    home = Path(os.environ["HOME"])
    home.mkdir(parents=True, exist_ok=True)
    if not _case_insensitive(home):
        pytest.skip("this volume is case-sensitive")
    real = home / root / "image-cache" / "x.png"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_bytes(DARK)
    # The exact spelling is refused...
    assert mcp_tools._design_image(c, bank, str(real), None).startswith("Not saved: Cicada doesn't read")
    # ...and the same file, spelled with another case, must be refused too.
    got = mcp_tools._design_image(c, bank, str(home / recased / "image-cache" / "x.png"), None)
    assert isinstance(got, str) and got.startswith("Not saved: Cicada doesn't read"), (
        f"read {len(got)} bytes from inside ~/{root} through ~/{recased}")


def test_a_recased_bank_path_is_still_refused(ctx):
    c, bank = ctx
    if not _case_insensitive(bank):
        pytest.skip("this volume is case-sensitive")
    inside = bank / "assets" / "y.png"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_bytes(DARK)
    recased = Path(str(bank).upper()) / "assets" / "y.png"
    got = mcp_tools._design_image(c, bank, str(recased), None)
    assert isinstance(got, str), "read a picture out of the bank itself through an upper-cased path"


def test_the_data_volume_firmlink_spelling_is_still_refused(ctx):
    """macOS firmlinks /Users, /private… onto /System/Volumes/Data; realpath() does not fold them."""
    c, bank = ctx
    data = Path("/System/Volumes/Data")
    if not data.is_dir():
        pytest.skip("no data-volume firmlink here")
    home = Path(os.environ["HOME"])
    real = home / ".claude" / "image-cache" / "z.png"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_bytes(DARK)
    via = data / str(Path(os.path.realpath(real))).lstrip("/")
    if not via.is_file():
        pytest.skip("this path is not on the data volume")
    got = mcp_tools._design_image(c, bank, str(via), None)
    assert isinstance(got, str), f"read {len(got)} bytes from inside ~/.claude through {via.parents[3]}"


def test_a_symlink_into_a_refused_folder_is_refused(ctx, tmp_path):
    c, bank = ctx
    home = Path(os.environ["HOME"])
    real = home / ".claude" / "image-cache" / "s.png"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_bytes(DARK)
    link = tmp_path / "elsewhere" / "s.png"
    link.parent.mkdir()
    link.symlink_to(real)
    assert mcp_tools._design_image(c, bank, str(link), None).startswith("Not saved: Cicada doesn't read")


def test_a_fifo_is_refused_without_blocking(ctx, tmp_path):
    c, bank = ctx
    fifo = tmp_path / "pipe.png"
    os.mkfifo(fifo)
    assert mcp_tools._design_image(c, bank, str(fifo), None) == "Not saved: that path isn't a file."


def test_an_ordinary_screenshot_still_reads(ctx, tmp_path):
    c, bank = ctx
    shot = tmp_path / "shots" / "page.png"
    shot.parent.mkdir()
    shot.write_bytes(DARK)
    assert mcp_tools._design_image(c, bank, str(shot), None) == DARK
