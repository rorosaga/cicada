"""A photo or a file a device shared into Cicada (G91, owner ruling 38, 2026-10-23) — the ONE writer of its bytes.

A paired phone's share sheet sends a photo (JPEG, PNG, HEIC), a PDF or a plain-text file, with an optional caption in
the person's own words, to ``POST /capture/file``. This module decides what is accepted and where each part lives:

* **The bytes live outside every bank and every git repo** — ``$CICADA_HOME/files/<bank>/<sha256>.<ext>`` (0700
  folders, 0600 files), content-addressed, so the same bytes shared twice are one file. The rail followed is the one
  site captures and Messages photos keep (``site_captures``, ``messages_photos``): **pixels the scrub cannot clean
  never enter the bank** — a photo of a screen, a whiteboard, a document can hold a password, a face, an address — and
  a site capture that showed the person's own account keeps even its thumbnail outside. So there is **no thumbnail in
  the bank** either. A photo's EXIF (where it was taken) stays on this machine with it.
* **The bank holds a small episode** (``episode_staging``, the one source-keyed writer: scrubbed, one id rule, queued
  for Sleep): one ``user:`` turn — the caption, then ``[image: <name>]`` or ``[file: <name>]``, the shape Messages
  uses for an attachment — with the file named in ``turn_extras`` (a name, a size, a type; never a path) and the
  record ``file: {kind, mime, name, size, sha256}`` in the frontmatter. A bank handed over keeps the record; a file not
  on this machine reads as "not on this Mac", the way a site capture's full image does.
* **A plain-text file's words** are also a second ``user:`` turn (scrubbed, the first ``TEXT_HEAD_CHARS``): text the
  person chose to share from their phone is treated as their own, as a shared text already is (``/capture/note``) and
  as a watched folder's ``.txt`` is by default (``folder_source``).

**No model at capture.** Nothing here reads a photo's pixels or a PDF's pages: the type is decided from the magic
bytes (never the client's word), and an image is kept exactly as sent — no conversion. The backend keeps no image
library (``image_decode``'s rule) and a headless Linux server has no ``sips``; a HEIC re-encoded to JPEG would lose the
original for nothing the capture needs. Whether Sleep later describes a picture or reads a PDF's text is G195's and
G91's business, not this module's.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from api.services import image_decode, pdf_page, video_queue
from api.services.auth import cicada_home

FILES_DIR = "files"
#: The largest file a device may send (the 2026-10-23 proposal's number): a phone photo is 2–6 MB, a scanned PDF more.
MAX_BYTES = 25 * 1024 * 1024
#: A plain-text file's words kept in the episode — the cap a first person message has in a captured session (G110).
TEXT_HEAD_CHARS = 16_000
NAME_CAP = 120
#: What a device may send, by what the bytes are: kind (the attachment word), MIME type, the stored file's extension.
TYPES = {
    "jpg": ("image", "image/jpeg", "jpg"),
    "png": ("image", "image/png", "png"),
    "heic": ("image", "image/heic", "heic"),
    "pdf": ("file", "application/pdf", "pdf"),
    "text": ("file", "text/plain", "txt"),
}
DEFAULT_STEMS = {"jpg": "photo", "png": "photo", "heic": "photo", "pdf": "document", "text": "note"}


class Refused(ValueError):
    """The file is not one a device may send. ``status`` is the HTTP answer (413 too big, 415 not allowed)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Accepted:
    sniffed: str           # a key of TYPES
    kind: str              # the attachment word: image | file
    mime: str
    ext: str
    sha256: str
    size: int
    text: str | None       # a plain-text file's words, decoded; None for anything else


def sniff(data: bytes, declared_mime: str | None = None, name: str | None = None) -> str | None:
    """What the bytes are, from their magic, else None. Plain text has no magic: it is text only when the client said so
    (``text/plain`` or a ``.txt`` name) AND the bytes are UTF-8 with no NUL — never a binary the client calls text."""
    image = image_decode.sniff(data)
    if image in ("jpg", "png", "heic"):
        return image
    if image is not None:                       # WebP, GIF, TIFF: a picture, but not one a phone shares as a photo
        return None
    said_text = (declared_mime or "").split(";")[0].strip().lower() == "text/plain" or \
        str(name or "").lower().endswith(".txt")
    if data.startswith(b"%PDF-") or (not said_text and pdf_page.looks_like_pdf(data)):
        return "pdf"
    if said_text and b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "text"
    return None


def accept(data: bytes, declared_mime: str | None = None, name: str | None = None) -> Accepted:
    if not data:
        raise Refused(400, "The file is empty.")
    if len(data) > MAX_BYTES:
        raise Refused(413, f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    sniffed = sniff(data, declared_mime, name)
    if sniffed is None:
        raise Refused(415, "Only a photo (JPEG, PNG or HEIC), a PDF or a plain-text file can be sent.")
    kind, mime, ext = TYPES[sniffed]
    text = None
    if sniffed == "text":
        text = data.decode("utf-8").lstrip("﻿")   # a byte-order mark is not a word
        if not text.strip():
            raise Refused(400, "The file is empty.")
    return Accepted(sniffed, kind, mime, ext, hashlib.sha256(data).hexdigest(), len(data), text)


def clean_name(name: str | None, accepted: Accepted) -> str:
    """The file's own name, never a path, brackets turned to parentheses so it cannot close the ``[kind: name]``
    marker; a blank name gets a plain one (``photo.jpg``, ``document.pdf``, ``note.txt``)."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = " ".join(base.replace("[", "(").replace("]", ")").split())[:NAME_CAP].strip()
    if not base:
        return f"{DEFAULT_STEMS[accepted.sniffed]}.{accepted.ext}"
    return base


def outside_root(memory_path) -> Path:
    """``$CICADA_HOME/files/<bank>/`` — a device's shared files, outside every bank and git repo."""
    return cicada_home() / FILES_DIR / video_queue.bank_slug(Path(memory_path))


def stored_path(memory_path, sha256: str, ext: str) -> Path | None:
    """Where the file with this hash lives — only a 64-hex name and an allowed extension, never a path a caller names."""
    if not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or "")) or ext not in {t[2] for t in TYPES.values()}:
        return None
    return outside_root(memory_path) / f"{sha256}.{ext}"


def keep(memory_path, data: bytes, accepted: Accepted) -> Path:
    """Write the bytes once (atomic, 0600); the same bytes again add nothing."""
    path = stored_path(memory_path, accepted.sha256, accepted.ext)
    assert path is not None
    folder = path.parent
    for level in (cicada_home() / FILES_DIR, folder):
        level.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(level, 0o700)
    if path.is_file() and path.stat().st_size == accepted.size:
        return path
    tmp = folder / f".{accepted.sha256}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def record(accepted: Accepted, name: str) -> dict:
    """The episode's ``file:`` record: what was shared, never where it is."""
    return {"kind": "image" if accepted.kind == "image" else accepted.sniffed, "mime": accepted.mime, "name": name,
            "size": accepted.size, "sha256": accepted.sha256}


def turn_texts(accepted: Accepted, name: str, caption: str | None) -> list[str]:
    """The ``user:`` turns' words: the caption and the attachment marker, then a text file's own words."""
    marker = f"[{'image' if accepted.kind == 'image' else 'file'}: {name}]"
    first = f"{caption.strip()}\n{marker}" if caption and caption.strip() else marker
    texts = [first]
    if accepted.text is not None:
        texts.append(accepted.text.strip()[:TEXT_HEAD_CHARS])
    return texts


def default_title(accepted: Accepted, name: str) -> str:
    return name if accepted.kind != "image" else "Photo"
