"""A PDF's first page as a small PNG — rendered in the backend, never in the app.

Papers and saved PDFs get their own picture the way a link gets its page's image: page 1, rendered once and stored.
The work lives behind the API (owner 2026-10-09: Cicada may become a web app), so the renderer is a bundled one —
``pypdfium2``, PDFium's own binary wheel (macOS arm64 included, so the release build's wheels-only install takes it
and ``sign-app.sh`` signs its dylib like every other) — and the PNG is encoded here with ``zlib``: no Pillow, the
house rule ``logo_service`` and ``entity_picture`` already keep.

**A child process does the rendering.** PDFium parses bytes somebody else wrote; a hostile or broken file must cost
a failed preview, never the backend. ``render_first_page`` runs this module as ``python -m api.services.pdf_page``
(``embed_worker``'s precedent: the same interpreter, this checkout first on ``PYTHONPATH``), hands it the bytes on
stdin, and takes a PNG back on stdout within ``TIMEOUT_S``. Anything else — a crash, a timeout, a page with no
size, the renderer missing — is ``None``.

Only a PDF the person saved (a direct link, fetched under the ToS rail by ``media_preview``) or uploaded
(``POST /entities/{id}/picture/pdf``) ever reaches here; an arXiv PDF never does (G133).
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

from loguru import logger

#: The rendered page's width in pixels: a card's well, not a reader. A tall page is capped at ``MAX_SIDE`` instead.
WIDTH = 480
#: `entity_picture.MAX_SIDE` — what the picture store keeps.
MAX_SIDE = 1024
TIMEOUT_S = 15.0
#: A PDF is a document, not a picture: refuse anything bigger before a child ever starts.
MAX_PDF_BYTES = 32 * 1024 * 1024


def looks_like_pdf(data: bytes) -> bool:
    """``%PDF-`` within the first KB (the spec allows leading junk; readers accept it)."""
    return b"%PDF-" in (data or b"")[:1024]


def encode_png(width: int, height: int, rgb: bytes, stride: int) -> bytes:
    """An 8-bit RGB PNG from packed rows (``stride`` bytes apart, ``width * 3`` used)."""
    row = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:y * stride + row] for y in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def scale_for(page_width: float, page_height: float) -> float:
    """Pixels per PDF unit: ``WIDTH`` wide, unless the page is so tall its height would pass ``MAX_SIDE``."""
    if page_width <= 0 or page_height <= 0:
        return 0.0
    return min(WIDTH / page_width, MAX_SIDE / page_height)


def _render_in_process(data: bytes) -> bytes | None:
    """The child's work: page 1 → RGB → PNG. Imported here so the parent never loads PDFium."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    pdf = pdfium.PdfDocument(data)
    try:
        if len(pdf) < 1:
            return None
        page = pdf[0]
        scale = scale_for(page.get_width(), page.get_height())
        if scale <= 0:
            return None
        bitmap = page.render(scale=scale, force_bitmap_format=pdfium_c.FPDFBitmap_BGR, rev_byteorder=True,
                             may_draw_forms=False)
        width, height = bitmap.width, bitmap.height
        if min(width, height) < 1 or max(width, height) > MAX_SIDE:
            return None
        return encode_png(width, height, bytes(bitmap.buffer), bitmap.stride)
    finally:
        pdf.close()


def render_first_page(data: bytes, *, timeout_s: float = TIMEOUT_S) -> bytes | None:
    """Page 1 of ``data`` as a PNG, or None. Blocking — a caller on the event loop runs it in a thread."""
    if not data or len(data) > MAX_PDF_BYTES or not looks_like_pdf(data):
        return None
    root = str(Path(__file__).resolve().parents[2])
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (root, env.get("PYTHONPATH", "")) if p)
    env["CICADA_CAPTURE"] = "off"
    try:
        done = subprocess.run([sys.executable, "-m", "api.services.pdf_page"], input=data, capture_output=True,
                              env=env, timeout=timeout_s, check=False, close_fds=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug(f"pdf page render failed: {type(exc).__name__}")
        return None
    png = done.stdout
    if done.returncode != 0 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
        logger.debug(f"pdf page render gave nothing (exit {done.returncode})")
        return None
    return png


def _main() -> int:
    data = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        return 2
    try:
        png = _render_in_process(data)
    except Exception:  # noqa: BLE001 — any parse or render failure is "no preview"
        return 3
    if not png:
        return 4
    sys.stdout.buffer.write(png)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
