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
