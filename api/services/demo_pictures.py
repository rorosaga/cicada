"""G117, round 4 (T-Demo) — the demo's pictures, drawn in code.

The owner asked for a demo with "memories with pictures"; the brief: "generate simple synthetic images in code …
NEVER a real person's photo or a stock face". So these are pastel abstractions — a soft vertical gradient with a
head-and-shoulders silhouette for a person, concentric rings for a company — in ART_DIRECTION's palette family, and
nothing a viewer could mistake for someone real.

Stdlib only (`zlib`, `struct`): the server keeps no image library (`entity_picture`'s R-PE2, "no Pillow"), and the
demo is generated on the backend. Deterministic by construction — fixed geometry, fixed palette, no `random` — so a
demo generated twice holds the same bytes (`demo_bank`'s R7), and 256 px sits inside the upload rule's bounds
(`entity_picture.validate_upload`: ≥ 16 px, ≤ 1024 px, ≤ 512 KB).
"""
from __future__ import annotations

import struct
import zlib

SIZE = 256
_SIGNATURE = b"\x89PNG\r\n\x1a\n"

Colour = tuple[int, int, int]


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _png(rows: list[bytes], size: int) -> bytes:
    """An 8-bit RGB PNG, each row prefixed with filter type 0 (none)."""
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return _SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def _mix(a: Colour, b: Colour, t: float) -> Colour:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def _cover(distance: float, edge: float = 1.5) -> float:
    """How much of a pixel a shape covers, from its signed distance to the edge: a soft 3 px ramp, so every edge is
    antialiased without supersampling."""
    if distance <= -edge:
        return 1.0
    if distance >= edge:
        return 0.0
    return 0.5 - distance / (2 * edge)


def avatar(top: Colour, bottom: Colour, figure: Colour, size: int = SIZE) -> bytes:
    """A person's picture: a pastel gradient and a soft head-and-shoulders silhouette — never a face."""
    s = size / 256
    hx, hy, hr = 128 * s, 104 * s, 46 * s
    bx, by, brx, bry = 128 * s, 262 * s, 96 * s, 78 * s
    rows = []
    for y in range(size):
        ground = _mix(top, bottom, y / (size - 1))
        row = bytearray()
        for x in range(size):
            head = ((x - hx) ** 2 + (y - hy) ** 2) ** 0.5 - hr
            body = (((x - bx) / brx) ** 2 + ((y - by) / bry) ** 2) ** 0.5 - 1.0
            row.extend(_mix(ground, figure, max(_cover(head), _cover(body * bry))))
        rows.append(bytes(row))
    return _png(rows, size)


def mark(top: Colour, bottom: Colour, ink: Colour, size: int = SIZE) -> bytes:
    """A company's mark: two concentric rings on a pastel gradient — no real brand's shape."""
    s = size / 256
    c = 128 * s
    rows = []
    for y in range(size):
        ground = _mix(top, bottom, y / (size - 1))
        row = bytearray()
        for x in range(size):
            r = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            ring = max(_cover(abs(r - 70 * s) - 10 * s), _cover(abs(r - 30 * s) - 10 * s))
            row.extend(_mix(ground, ink, ring))
        rows.append(bytes(row))
    return _png(rows, size)


# --- Design taste (2026-10-14): the demo board's screenshots ------------------------------------------------------
#
# Made-up web pages, drawn as blocks: a top bar, a headline and its lines, one button, a row of cards. No real site's
# layout, logo or words — each is a palette and a rhythm, which is what the board is about. numpy draws them (a
# 960 × 600 page in pure Python would take seconds); it is not an image library and the server still keeps none.

def website(background: Colour, surface: Colour, text: Colour, accent: Colour, *, width: int = 960,
            height: int = 600, dense: bool = False, rounded: int = 10, centred: bool = False) -> bytes:
    """A made-up page in four colours: deterministic, so a demo generated twice holds the same bytes."""
    import numpy as np

    img = np.empty((height, width, 3), dtype=np.uint8)
    img[:] = background

    def box(x0: int, y0: int, x1: int, y1: int, colour: Colour, radius: int = 0) -> None:
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
        if x1 <= x0 or y1 <= y0:
            return
        ys, xs = np.mgrid[y0:y1, x0:x1]
        mask = np.ones(xs.shape, dtype=bool)
        if radius:
            r = min(radius, (x1 - x0) // 2, (y1 - y0) // 2)
            cx = np.clip(xs, x0 + r, x1 - 1 - r)
            cy = np.clip(ys, y0 + r, y1 - 1 - r)
            mask = (xs - cx) ** 2 + (ys - cy) ** 2 <= r * r
        img[ys[mask], xs[mask]] = colour

    pad = 40 if not dense else 28
    box(0, 0, width, 56, surface)
    box(pad, 22, pad + 90, 34, text, 6)
    for i in range(4):
        box(width - pad - 70 * (i + 1), 24, width - pad - 70 * i - 20, 32, _mix(text, surface, 0.45), 4)
    left = (width - 560) // 2 if centred else pad
    box(left, 110, left + 520, 146, text, 8)
    box(left, 158, left + 380, 182, text, 8)
    for i, w in enumerate((470, 430, 300)):
        box(left, 206 + i * 22, left + w, 216 + i * 22, _mix(text, background, 0.55), 4)
    box(left, 290, left + 150, 330, accent, rounded)
    box(left + 166, 290, left + 286, 330, _mix(surface, background, 0.3), rounded)
    cards = 4 if dense else 3
    gap = 20
    cw = (width - 2 * pad - gap * (cards - 1)) // cards
    for i in range(cards):
        x = pad + i * (cw + gap)
        box(x, 370, x + cw, height - pad, surface, rounded)
        box(x + 18, 392, x + 18 + 44, 436, _mix(accent, surface, 0.25 * i), rounded // 2 + 2)
        box(x + 18, 456, x + cw - 40, 468, text, 4)
        for j in range(3):
            box(x + 18, 484 + j * 18, x + cw - 18 - 30 * j, 492 + j * 18, _mix(text, surface, 0.5), 3)
    rows = [bytes(img[y].tobytes()) for y in range(height)]
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return _SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")
