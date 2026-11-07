"""The picture index's cold build, measured with the real image encoder on synthetic pictures (vision item 3):

    CICADA_HOME=<scratch home with models/embeddinggemma-2 + its image encoder> \\
      api/.venv/bin/python -m benchmarks.perf.image_index_build --bank <scratch dir> [--n 400] [--side 640x400]

Draws ``--n`` pictures (a coloured shape on a plain ground, JPEG through ``sips`` — no real picture, no download),
builds the ``images`` table from nothing through ``image_index.refresh`` exactly as the background refresher does
(the picture child, ``embed_worker.images``), and reports: the wall time and pictures per second; the child's peak
resident memory (sampled with ``ps`` every 0.2 s) and the backend side's own growth; the table's size on disk; then
the search leg's p95 over 60 text queries and, as a real-model check of the floor, how often a query naming a
shape and colour gets that picture back and how often a query about nothing drawn gets any picture.
"""
from __future__ import annotations

import argparse
import itertools
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

COLOURS = {"red": (220, 30, 30), "green": (30, 170, 60), "blue": (30, 70, 220), "yellow": (240, 210, 20),
           "purple": (130, 40, 170), "orange": (245, 130, 20), "black": (15, 15, 15), "white": (250, 250, 250)}
SHAPES = ("circle", "square", "triangle", "stripes")
GROUNDS = {"grey": (128, 128, 128), "cream": (245, 238, 220), "navy": (20, 25, 60)}
NOTHING = ("a tax form for the quarter", "the dentist appointment next week", "a recipe for lentil soup",
           "the train timetable to the airport", "notes from the budget meeting", "a poem about the sea")


def _bmp(rgb: np.ndarray) -> bytes:
    h, w, _ = rgb.shape
    row = (w * 3 + 3) & ~3
    data = bytearray()
    for y in range(h - 1, -1, -1):
        line = rgb[y, :, ::-1].tobytes()
        data += line + b"\0" * (row - len(line))
    header = b"BM" + (54 + len(data)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little")
    info = (40).to_bytes(4, "little") + w.to_bytes(4, "little") + h.to_bytes(4, "little", signed=True) + \
        (1).to_bytes(2, "little") + (24).to_bytes(2, "little") + b"\0" * 24
    return header + info + bytes(data)


def draw(shape: str, colour: str, ground: str, w: int, h: int, rng: np.random.Generator) -> np.ndarray:
    img = np.empty((h, w, 3), dtype=np.uint8)
    img[:] = GROUNDS[ground]
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w * rng.uniform(0.35, 0.65), h * rng.uniform(0.35, 0.65)
    r = min(w, h) * rng.uniform(0.22, 0.32)
    if shape == "circle":
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    elif shape == "square":
        mask = (abs(xx - cx) <= r) & (abs(yy - cy) <= r)
    elif shape == "triangle":
        mask = (yy >= cy - r) & (yy <= cy + r) & (abs(xx - cx) <= (yy - (cy - r)) / 2)
    else:
        mask = ((xx // max(1, int(r / 3))) % 2 == 0)
    img[mask] = COLOURS[colour]
    return img


def make(n: int, w: int, h: int, folder: Path) -> list[tuple[Path, str, str]]:
    rng = np.random.default_rng(7)
    combos = list(itertools.product(SHAPES, COLOURS, GROUNDS))
    out = []
    for i in range(n):
        shape, colour, ground = combos[i % len(combos)]
        bmp = folder / f"p{i:05d}.bmp"
        bmp.write_bytes(_bmp(draw(shape, colour, ground, w, h, rng)))
        jpg = folder / f"p{i:05d}.jpg"
        subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", str(bmp), "--out", str(jpg)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        bmp.unlink()
        out.append((jpg, shape, colour))
    return out


def _rss_mb(pid: int) -> float:
    try:
        out = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout
        return int(out.strip() or 0) / 1024
    except (OSError, ValueError):
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--side", default="640x400")
    a = ap.parse_args()
    w, h = (int(x) for x in a.side.split("x"))
    bank = a.bank.resolve()
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    from api.services import embed_worker, image_index

    pics_dir = Path(tempfile.mkdtemp(prefix="pics-", dir=bank))
    t0 = time.monotonic()
    drawn = make(a.n, w, h, pics_dir)
    print(f"drew {len(drawn)} pictures {w}x{h} in {time.monotonic() - t0:.1f}s "
          f"(mean {statistics.mean(p.stat().st_size for p, _s, _c in drawn) / 1024:.0f} KB)")
    pictures = [image_index.Picture(f"capture:p{i:05d}", "capture", p, title=f"a {c} {s}", entity_id=f"p{i:05d}")
                for i, (p, s, c) in enumerate(drawn)]
    emb = image_index.default_embedder()
    if emb is None:
        sys.exit("no image encoder under CICADA_HOME/models")
    parent_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    peak = {"child": 0.0}
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            for worker in list(embed_worker._WORKERS.values()):
                if worker.pid:
                    peak["child"] = max(peak["child"], _rss_mb(worker.pid))
            time.sleep(0.2)

    threading.Thread(target=sample, daemon=True).start()
    t0 = time.monotonic()
    counts = image_index.refresh(bank, emb, pictures=pictures)
    took = time.monotonic() - t0
    stop.set()
    parent_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    db = bank / "vector_index.db"
    size = sum(f.stat().st_size for f in bank.glob("vector_index.db*"))
    print(f"cold build: {counts} in {took:.1f}s = {counts['embedded'] / max(took, 1e-9):.1f} pictures/s "
          f"({1000 * took / max(1, counts['embedded']):.0f} ms each, child start + model load included)")
    print(f"picture child peak RSS {peak['child']:.0f} MB (ceiling {embed_worker.VISION_MEMORY_MB} MB); "
          f"this process's peak {parent_before:.0f} → {parent_after:.0f} MB; table on disk {size / 1e6:.1f} MB ({db.name})")
    t0 = time.monotonic()
    again = image_index.refresh(bank, emb, pictures=pictures)
    print(f"warm refresh (nothing changed): {again} in {1000 * (time.monotonic() - t0):.0f} ms")
    # The search leg: text queries only (the image encoder is never loaded to search).
    queries = [(f"a {c} {s}", s, c) for s, c in itertools.islice(itertools.product(SHAPES, COLOURS), 32)]
    image_index.search(bank, "warm up")
    lat, right, shown_none = [], 0, 0
    for q, s, c in queries:
        t0 = time.perf_counter()
        hits = image_index.search(bank, q, top_k=8)
        lat.append(1000 * (time.perf_counter() - t0))
        if hits and hits[0]["metadata"].get("title", "").endswith(f"{c} {s}"):
            right += 1
    zs_none = []
    for q in NOTHING * 5:
        t0 = time.perf_counter()
        hits = image_index.search(bank, q, top_k=8)
        lat.append(1000 * (time.perf_counter() - t0))
        shown_none += bool(hits)
    lat.sort()
    print(f"search leg p50 {statistics.median(lat):.1f} ms, p95 {lat[int(0.95 * (len(lat) - 1))]:.1f} ms "
          f"over {len(lat)} queries (query vector cached after the first of each)")
    print(f"real-model floor check: '{{colour}} {{shape}}' first picture right {right}/{len(queries)}; "
          f"a query about nothing drawn showed a picture {shown_none}/{len(NOTHING) * 5}")
    for q in ("a red circle", "a blue square", NOTHING[0]):
        from api.services import vector_index

        hits = image_index.search(bank, q, top_k=3)
        print(f"  {q!r}: {[(h['metadata'].get('title'), h['score']) for h in hits]}")
    embed_worker.shutdown()


if __name__ == "__main__":
    os.environ.setdefault("CICADA_CAPTURE", "off")
    main()
