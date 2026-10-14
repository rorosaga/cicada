"""Pixels from an image's bytes, for the design board's palette and its image vectors (design taste, 2026-10-14).

The server keeps no image library (`entity_picture`'s "no Pillow" rule, `pdf_page`'s precedent), and a screenshot is
bytes somebody else's tool wrote. So the decode runs in a **child process**: macOS's own ``sips`` reads the bytes the
backend wrote to a temporary file of its own (never a path a request names), resizes them and writes an uncompressed
BMP, which is parsed here with numpy. A hostile or broken file costs a failed decode, never the backend; anything else
— a timeout, an odd header, ``sips`` missing (a future Linux host) — is :class:`DecodeError`, which every caller turns
into "no palette, no image vector" and never into a failed save.

What comes back is ``uint8 [height, width, 3]`` RGB, any alpha flattened onto white (a transparent screenshot region
reads as the page behind it most often is).
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np

SIPS = "/usr/bin/sips"
TIMEOUT_S = 15.0
#: A decoded image never exceeds this many pixels a side (a 6K screenshot is shrunk before it is parsed).
MAX_SIDE = 4096


class DecodeError(RuntimeError):
    """The bytes couldn't be turned into pixels here."""


def sniff(data: bytes) -> str | None:
    """``png``, ``jpg``, ``webp``, ``gif``, ``heic`` or ``tiff`` from the magic bytes, else None."""
    head = bytes(data[:16])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return "heic"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def available() -> bool:
    return Path(SIPS).is_file() or shutil.which("sips") is not None


def _sips() -> str:
    sips = SIPS if Path(SIPS).is_file() else shutil.which("sips")
    if not sips:
        raise DecodeError("no image decoder on this host")
    return sips


def _run(cmd: list[str], tmp: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S, env={"PATH": "/usr/bin:/bin", "HOME": tmp})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DecodeError("the decoder stopped") from exc


def _probe(sips: str, src: Path, tmp: str) -> tuple[int, int]:
    done = _run([sips, "-g", "pixelWidth", "-g", "pixelHeight", str(src)], tmp)
    found: dict[str, int] = {}
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        key, _, value = line.strip().partition(":")
        if key in ("pixelWidth", "pixelHeight") and value.strip().isdigit():
            found[key] = int(value.strip())
    if done.returncode != 0 or len(found) != 2:
        raise DecodeError("the decoder couldn't read it")
    return found["pixelWidth"], found["pixelHeight"]


def fit(width: int, height: int, max_side: int) -> tuple[int, int]:
    """``(width, height)`` shrunk to at most ``max_side`` a side, aspect kept — never enlarged."""
    scale = min(1.0, max_side / max(width, height, 1))
    return max(1, round(width * scale)), max(1, round(height * scale))


def decode(data: bytes, *, max_side: int | None = None, size: tuple[int, int] | None = None) -> np.ndarray:
    """RGB pixels: at most ``max_side`` a side (aspect kept, never enlarged), or exactly ``size`` = ``(width,
    height)``."""
    if sniff(data) is None:
        raise DecodeError("not an image Cicada reads")
    sips = _sips()
    with tempfile.TemporaryDirectory(prefix="cicada-img-") as tmp:
        src, out = Path(tmp) / "in", Path(tmp) / "out.bmp"
        src.write_bytes(data)
        if size is None:
            from api.services import entity_picture

            w0, h0 = entity_picture.dimensions(data) or _probe(sips, src, tmp)
            size = fit(w0, h0, max(1, min(int(max_side or MAX_SIDE), MAX_SIDE)))
        w, h = (max(1, min(int(v), MAX_SIDE)) for v in size)
        done = _run([sips, "-s", "format", "bmp", "-z", str(h), str(w), str(src), "--out", str(out)], tmp)
        if done.returncode != 0 or not out.is_file():
            raise DecodeError("the decoder couldn't read it")
        return parse_bmp(out.read_bytes())


def parse_bmp(raw: bytes) -> np.ndarray:
    """An uncompressed 24- or 32-bit BMP (``BI_RGB`` or ``BI_BITFIELDS``, either row order) as RGB, alpha over white."""
    if len(raw) < 54 or raw[:2] != b"BM":
        raise DecodeError("not a bitmap")
    offset = struct.unpack_from("<I", raw, 10)[0]
    header = struct.unpack_from("<I", raw, 14)[0]
    width, height = struct.unpack_from("<ii", raw, 18)
    bpp = struct.unpack_from("<H", raw, 28)[0]
    compression = struct.unpack_from("<I", raw, 30)[0]
    if width <= 0 or height == 0 or bpp not in (24, 32) or compression not in (0, 3):
        raise DecodeError("an unsupported bitmap")
    top_down = height < 0
    h = abs(height)
    if width > MAX_SIDE * 2 or h > MAX_SIDE * 2:
        raise DecodeError("too large")
    channels = bpp // 8
    stride = (width * channels + 3) & ~3
    if offset + stride * h > len(raw):
        raise DecodeError("a truncated bitmap")
    rows = np.frombuffer(raw, dtype=np.uint8, count=stride * h, offset=offset).reshape(h, stride)
    px = rows[:, : width * channels].reshape(h, width, channels)
    if not top_down:
        px = px[::-1]
    if channels == 3:
        return np.ascontiguousarray(px[:, :, ::-1])
    masks = (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    if compression == 3 and header >= 52:
        r, g, b = struct.unpack_from("<III", raw, 54)
        a = struct.unpack_from("<I", raw, 66)[0] if header >= 56 else 0
        masks = (r, g, b, a)
    word = px.view("<u4").reshape(h, width).astype(np.uint32)

    def take(mask: int) -> np.ndarray:
        if not mask:
            return np.full((h, width), 255, dtype=np.float32)
        shift = (mask & -mask).bit_length() - 1
        top = mask >> shift
        return ((word & mask) >> shift).astype(np.float32) * (255.0 / top)

    rgb = np.stack([take(masks[0]), take(masks[1]), take(masks[2])], axis=-1)
    alpha = take(masks[3])[..., None] / 255.0 if masks[3] else 1.0
    if masks[3] and float(np.min(alpha)) < 1.0:
        rgb = rgb * alpha + 255.0 * (1.0 - alpha)
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)


def dimensions(data: bytes) -> tuple[int, int] | None:
    """(width, height): from the header for PNG and JPEG (`entity_picture.dimensions`), else asked of the decoder."""
    from api.services import entity_picture

    got = entity_picture.dimensions(data)
    if got is not None or sniff(data) is None:
        return got
    try:
        sips = _sips()
        with tempfile.TemporaryDirectory(prefix="cicada-img-") as tmp:
            src = Path(tmp) / "in"
            src.write_bytes(data)
            return _probe(sips, src, tmp)
    except DecodeError:
        return None
