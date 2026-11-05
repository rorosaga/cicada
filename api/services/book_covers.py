"""A book's cover from Apple Books' own cache on this Mac — no network, no query (TODO ruling 61, owner 2026-11-04).

"I want the book covers, yes." Apple Books keeps a rendered cover of every book it has shown, in its sandbox
(``Library/Caches/BCCoverCache-1/BICDiskDataStore/<asset id>/<asset id>|<scale>|<w>|<h>|<n>.<jpg|heic|astc>``, read on
macOS 27.2: one folder per asset, 285 folders for 283 assets). 1 of those 283 assets carries an ISBN, so for a library
this is the only cover there is, and it is the person's own copy's. **The app reads it** (the ``~/Library`` rail, the
same container and the same turned-on switch as the library itself), draws it down to a JPEG and posts the bytes; this
module validates and keeps them **outside every bank** (``$CICADA_HOME/books/covers/<bank>/``, content-addressed, with
``index.json`` mapping an asset to its picture), like every other picture. ``books.apply_pending`` stamps the page's
``book.local_cover`` from that index, so the page says which picture it has and a picture arriving moves the page's
ETag; ``media_preview.source_for`` prefers it over Open Library.

No asset id or title leaves this Mac for this, and nothing here logs either.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from loguru import logger

from api.services import media_preview

INDEX_FILENAME = "index.json"
#: At most this many covers in one post; the app sends the rest in the next.
MAX_PER_POST = 25
_SHA_RE = re.compile(r"[0-9a-f]{12}")
_MAX_ASSET = 200


class PayloadError(ValueError):
    """A post the backend cannot trust — answered 422, nothing written."""


def _root(bank: str) -> Path:
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(raw).expanduser() / "books" / "covers" / (bank or "default")


def read_index(bank: str) -> dict[str, str]:
    """Asset id → the picture's sha; empty when nothing is kept. A read conjures no folder."""
    try:
        data = json.loads((_root(bank) / INDEX_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if _SHA_RE.fullmatch(str(v))} if isinstance(data, dict) else {}


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cover-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def stored(bank: str, sha: str) -> Path | None:
    """The kept picture for ``sha``, or None (another computer's, or never here)."""
    if not _SHA_RE.fullmatch(str(sha or "")):
        return None
    for ext in media_preview.EXTS:
        path = _root(bank) / f"{sha}.{ext}"
        if path.is_file():
            return path
    return None


def store(bank: str, covers: list[dict]) -> dict:
    """Keep what the app read. Returns ``{stored, unchanged, refused}``; a picture that is not one is refused alone, so
    one bad file never stops the rest. Only the index and the pictures change; the page is ``books.apply_pending``'s."""
    if len(covers) > MAX_PER_POST:
        raise PayloadError(f"at most {MAX_PER_POST} covers in one post")
    index = read_index(bank)
    out = {"stored": 0, "unchanged": 0, "refused": 0}
    for item in covers:
        asset = str(item.get("assetId") or "").strip()
        try:
            data = base64.b64decode(str(item.get("coverB64") or ""), validate=True)
        except (binascii.Error, ValueError):
            out["refused"] += 1
            continue
        ext = media_preview.accept_image(data) if len(data) <= media_preview.MAX_BYTES else None
        if not asset or len(asset) > _MAX_ASSET or ext is None:
            out["refused"] += 1
            continue
        sha = hashlib.sha256(data).hexdigest()[:12]
        if index.get(asset) == sha and stored(bank, sha) is not None:
            out["unchanged"] += 1
            continue
        try:
            _write_atomic(_root(bank) / f"{sha}.{ext}", data)
        except OSError as exc:
            logger.warning(f"a book cover was not kept: {type(exc).__name__}")
            out["refused"] += 1
            continue
        index[asset] = sha
        out["stored"] += 1
    if out["stored"]:
        _write_atomic(_root(bank) / INDEX_FILENAME, json.dumps(index, sort_keys=True).encode("utf-8"))
    return out
