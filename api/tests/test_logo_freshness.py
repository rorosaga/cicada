"""Vision item 4 (2026-10-28): `scripts/logo-freshness.py` reports which bundled marks their vendors still serve —
compared by pixels, so a re-encoded PNG is not a rebrand — and never changes anything. No network: an injected
fetcher and a synthetic set in tmp."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import zlib
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "logo-freshness.py"


@pytest.fixture(scope="module")
def lf():
    spec = importlib.util.spec_from_file_location("logo_freshness", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _pixels(w: int, h: int, shift: int = 0) -> list[list[tuple]]:
    return [[((x * 40 + shift) % 256, (y * 60) % 256, 128, 255) for x in range(w)] for y in range(h)]


def png(px, *, level: int = 9, interlaced: bool = False, filter_type: int = 0) -> bytes:
    """An RGBA PNG; `interlaced` writes Adam7 passes (filter 0), else every row with `filter_type` (0 or 1)."""
    h, w = len(px), len(px[0])
    rows = []
    if interlaced:
        for x0, y0, dx, dy in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2),
                               (0, 1, 1, 2)):
            for y in range(y0, h, dy):
                line = [px[y][x] for x in range(x0, w, dx)]
                if line:
                    rows.append(b"\x00" + b"".join(bytes(p) for p in line))
    else:
        for y in range(h):
            line = b"".join(bytes(p) for p in px[y])
            if filter_type == 1:
                line = bytes((line[i] - (line[i - 4] if i >= 4 else 0)) & 255 for i in range(len(line)))
            rows.append(bytes((filter_type,)) + line)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 1 if interlaced else 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(b"".join(rows), level))
            + _chunk(b"IEND", b""))


def _set(tmp_path: Path, logos: dict[str, bytes], urls: dict[str, str]) -> Path:
    d = tmp_path / "logo-set"
    d.mkdir()
    rows = []
    for slug, data in logos.items():
        ext = "png" if data.startswith(b"\x89PNG") else "svg"
        (d / f"{slug}.{ext}").write_bytes(data)
        rows.append({"slug": slug, "file": f"{slug}.{ext}", "format": ext, "source_url": urls[slug],
                     "fetched": "2026-10-22", "source_tier": "official site",
                     "sha256": hashlib.sha256(data).hexdigest()})
    (d / "manifest.json").write_text(json.dumps({"generated": "2026-10-22", "logos": rows}))
    return d


def test_the_decoder_reads_plain_filtered_and_interlaced_pngs_alike(lf):
    px = _pixels(13, 11)
    plain, filtered, adam7 = png(px), png(px, filter_type=1, level=1), png(px, interlaced=True)
    assert len({plain, filtered, adam7}) == 3, "three different files"
    decoded = {lf.png_rgba(b) for b in (plain, filtered, adam7)}
    assert len(decoded) == 1 and next(iter(decoded))[:2] == (13, 11)
    assert lf.pixel_distance(plain, adam7) == 0


def test_same_re_encoded_changed_pinned_and_unreachable(lf, tmp_path):
    px = _pixels(16, 16)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
    set_dir = _set(tmp_path, {"same": svg, "reenc": png(px), "redrawn": png(px), "pinned": svg, "down": svg}, {
        "same": "https://same.example/favicon.svg", "reenc": "https://reenc.example/i.png",
        "redrawn": "https://redrawn.example/i.png",
        "pinned": "https://raw.githubusercontent.com/o/r/" + "a" * 40 + "/icon.svg",
        "down": "https://down.example/favicon.svg"})
    served = {"https://same.example/favicon.svg": svg, "https://reenc.example/i.png": png(px, interlaced=True),
              "https://redrawn.example/i.png": png(_pixels(16, 16, shift=90))}
    asked: list[str] = []

    def fetcher(url):
        asked.append(url)
        return (served[url], "") if url in served else (None, "HTTP 403")

    save = tmp_path / "review"
    report = lf.check(set_dir, fetcher=fetcher, save_dir=save)
    states = {r["slug"]: r["state"] for r in report["rows"]}
    assert states == {"same": "same", "reenc": "same", "redrawn": "changed", "pinned": "pinned", "down": "unreachable"}
    assert not any("raw.githubusercontent.com" in u for u in asked), "a pinned revision is never asked"
    assert sorted(p.name for p in save.iterdir()) == ["redrawn.png"]
    assert "`redrawn` | changed" in lf.markdown(report)
    assert hashlib.sha256((set_dir / "redrawn.png").read_bytes()).hexdigest() == \
        json.loads((set_dir / "manifest.json").read_text())["logos"][2]["sha256"], "the set itself is never touched"


def test_strict_is_for_a_local_check_and_the_default_always_exits_zero(lf, monkeypatch, capsys):
    monkeypatch.setattr(lf, "check", lambda **kw: {"set_generated": "x", "counts": {"changed": 1}, "rows": []})
    assert lf.main([]) == 0
    assert lf.main(["--strict"]) == 1


def test_the_fetch_refuses_plain_http_before_asking(lf):
    class Boom:
        def open(self, *a, **k):
            raise AssertionError("never opened")

    assert lf.fetch("http://vendor.example/icon.png", opener=Boom()) == (None, "not https")
