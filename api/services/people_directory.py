"""The people directory — the people a person knows who have no page yet, kept outside every bank (owner 2026-10-16,
2026-10-20).

Two sources fill it, and both follow G154's rail: a card or a connection **enriches a page and never mints one on its
own**. What matches no page waits here, at ``$CICADA_HOME/people/<bank>/`` (folder 0700, every file 0600, written by a
rename), until a page for that person exists:

- ``linkedin-connections.json`` — the person's LinkedIn export (``linkedin_people``);
- ``contacts.json`` + ``contacts/<key>.<jpg|png>`` — the Mac's address-book cards that matched no page, with exactly
  what G154 posts (names, which facts the card holds, a thumbnail ≤ 64 KB) and nothing else (``contacts_local``).

This module owns the folder: where it is, how a file is read and written, the folded name keys both sources match on,
and what a bank's trash or rename does to it. Nothing here is ever in a bank, in git, or in a log.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from loguru import logger

from api.services import text_fold


def folder(bank: str) -> Path:
    """``$CICADA_HOME/people/<bank>/``. Pure: a read never conjures a folder (the ``contacts_local.photo_path`` rule) —
    the writers create it."""
    root = Path(os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")).expanduser()
    return root / "people" / (bank or "default")


def path(bank: str, name: str) -> Path:
    return folder(bank) / name


def ensure(bank: str) -> Path:
    """Create the bank's folder (and ``people/``) private to this user."""
    target = folder(bank)
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in (target, target.parent):
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    return target


def load_json(bank: str, name: str) -> dict:
    try:
        data = json.loads(path(bank, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json(bank: str, name: str, payload: dict) -> Path:
    """Write one file of the directory: 0600, by a rename, so a reader never sees half of it."""
    target = path(bank, name)
    ensure(bank)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def write_bytes(target: Path, data: bytes) -> None:
    """One binary file under the directory (a waiting card's thumbnail): 0600, by a rename."""
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def fold(text) -> str:
    """A label folded like search (`text_fold.words`), words joined by one space."""
    return " ".join(text_fold.words(str(text or "")))


def name_keys(given, family) -> set[str]:
    """Both orders of a two-part name, folded like search; nothing for a one-part name — a first name alone never
    matches anybody."""
    first, last = fold(given), fold(family)
    if not first or not last:
        return set()
    return {f"{first} {last}", f"{last} {first}"}


def forget(bank: str) -> None:
    """A bank moved to the trash takes its directory with it: the names outlive no bank, and a new bank of the same
    name never inherits them. Never raises."""
    target = folder(bank)
    try:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
    except OSError as exc:
        logger.warning(f"people directory: the trashed bank's folder was not removed ({type(exc).__name__})")


def rename(old: str, new: str) -> None:
    """A renamed bank keeps its directory (it is keyed by the bank's folder name). Never raises; a folder already
    under the new name is left as it is."""
    src, dst = folder(old), folder(new)
    try:
        if src.is_dir() and not src.is_symlink() and not dst.exists():
            src.rename(dst)
    except OSError as exc:
        logger.warning(f"people directory: the renamed bank's folder was not moved ({type(exc).__name__})")
