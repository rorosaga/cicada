"""Deterministic tiny synthetic Aseprite sheets; never production art. Stdlib only."""
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).parent


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(path):
    # Three 2x2 frames, packed left to right. The third repeats the first rect in JSON.
    pixels = [[(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)],
              [(255, 255, 255, 255), (0, 0, 0, 0), (0, 0, 0, 255), (0, 255, 255, 255)]]
    raw = b"".join(b"\0" + bytes(c for p in row for c in p) for row in pixels)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 2, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def sheet(name, tags):
    png(ROOT / (name + ".png"))
    frames = [{"filename": f"synthetic {i}.aseprite", "frame": {"x": x, "y": 0, "w": 2, "h": 2},
               "sourceSize": {"w": 2, "h": 2}, "duration": ms, "trimmed": False, "rotated": False}
              for i, (x, ms) in enumerate([(0, 100), (2, 200), (0, 300)])]
    meta = {"image": name + ".png", "size": {"w": 4, "h": 2}, "frameTags": tags,
            "slices": [{"name": "eye", "keys": [{"frame": 0, "bounds": {"x": 0, "y": 0, "w": 1, "h": 1}}]}]}
    (ROOT / (name + ".json")).write_text(json.dumps({"frames": frames, "meta": meta}, indent=2) + "\n")


sheet("probe", [{"name": d, "from": 0, "to": 2, "direction": d, "repeat": "3"}
                for d in ["forward", "reverse", "pingpong", "pingpong_reverse"]]
      + [{"name": "idle", "from": 0, "to": 2, "direction": "forward"},
         {"name": "talk.center", "from": 1, "to": 2, "direction": "forward"}])
sheet("no-idle", [{"name": "other", "from": 1, "to": 2, "direction": "forward"}])
sheet("no-tags", [])

# Failure fixtures exercise the loader without installing placeholder production resources.
(ROOT / "bad-json.json").write_text("{broken\n")
png(ROOT / "bad-json.png")
(ROOT / "bad-png.json").write_bytes((ROOT / "probe.json").read_bytes())
(ROOT / "bad-png.png").write_bytes(b"not a PNG\n")
