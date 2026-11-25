"""A synthetic bank of the owner's size for the graph's list bubbles: build it, or time the graph route on it.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.graph_bubbles build --bank <dir>/bank
    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.graph_bubbles measure --bank <dir>/bank

``build`` writes the core of the graph with the link shape of a real memory (``graph-bank-shape.js``'s ``bankShaped``:
3,698 pages, ~41,570 links; run through ``node``), and ~5,100 saved items filed under real lists, each with a media
block and a save episode, in the mix measured on a real memory (counts only; every name and link is synthetic):
YouTube playlists ~3,150, browser bookmarks ~880 in folders, X and LinkedIn posts ~455, books ~290, starred
repositories ~200, feed items ~130. A dozen saved items are mentioned in a conversation, so they are not quiet.

``measure`` prints the graph build cold and warm, the response's size and its node and bubble counts.

Nothing touches a real bank, ``~/.cicada`` or ``HOME``: ``isolate`` pins every root to the scratch directory first.
"""
from __future__ import annotations

from . import isolate  # noqa: F401  - first: pins HOME and CICADA_HOME to the scratch directory

import argparse
import json
import random
import subprocess
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SHAPE_JS = ROOT / "app/CicadaApp/Tests/graph/graph-bank-shape.js"
TYPE_MAP = {"hub": None, "repo": "tool", "directory": "concept"}
SEED = 20261125

# (origin, url template, lists (folder names; None = no folder), count)
SAVED = (
    ("youtube-playlist", "https://www.youtube.com/watch?v={n:011d}",
     [f"Playlist {i:02d}" for i in range(24)] + ["Watch later", "Liked videos"], 3150),
    ("chrome-bookmark", "https://example.com/articles/{n}", [f"Folder {i:02d}" for i in range(14)] + [None], 880),
    ("x-bookmarks", "https://x.com/user_{u}/status/{n}", [None], 260),
    ("x-likes", "https://x.com/user_{u}/status/{n}", [None], 60),
    ("linkedin-saved", "https://www.linkedin.com/feed/update/urn:li:activity:{n}/", [None], 135),
    ("apple-books", "https://example.org/book/{n}", [None], 290),
    ("github-starred", "https://github.com/alpha-org-{u}/repo-{n}", [None], 200),
    ("feed", "https://example.net/posts/{n}", [None], 130),
)
MENTIONED = 12


def _doc(fm: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n" + body


def _core_shape(seed: int) -> dict:
    script = (f"const s=require({json.dumps(str(SHAPE_JS))});"
              f"process.stdout.write(JSON.stringify(s.bankShaped({seed})))")
    return json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout)


def build(bank: Path, seed: int = 7) -> dict:
    rng = random.Random(SEED)
    for d in ("entities", "episodes", "hubs", "inbox"):
        (bank / d).mkdir(parents=True, exist_ok=True)
    (bank / "_bank.yaml").write_text("name: synthetic-bubbles-bank\n", encoding="utf-8")
    day = lambda i: f"2026-{1 + i % 11:02d}-{1 + i % 28:02d}"   # noqa: E731

    shape = _core_shape(seed)
    talk: list[str] = []
    for i in range(600):
        eid = f"ep_{day(i)}_{i:05d}"
        talk.append(eid)
        efm = {"id": eid, "source": "claude-code", "timestamp": f"{day(i)}T09:00:00+00:00", "origin": "claude-code",
               "title": f"Synthetic conversation {i}", "processed": True, "processed_by": "sleep",
               "turns": [{"speaker": "user", "text": "a synthetic turn"}]}
        (bank / "episodes" / f"{eid}.md").write_text(_doc(efm, "user: a synthetic turn\n"), encoding="utf-8")
    core = 0
    for i, n in enumerate(shape["nodes"]):
        if n.get("isHub") or n.get("isFacet") or n["type"] == "hub":
            continue
        ptype = TYPE_MAP.get(n["type"], n["type"])
        pfm = {"name": f"Synthetic page {i}", "type": ptype, "status": n.get("status", "active"),
               "confidence": round(float(n.get("confidence", 0.6)), 2), "decay_class": "durable",
               "created": day(i), "last_referenced": day(i), "source_episodes": [talk[i % len(talk)]]}
        (bank / "entities" / f"{n['id']}.md").write_text(_doc(pfm, "## Summary\n\nA synthetic page.\n"),
                                                         encoding="utf-8")
        core += 1
    page_ids = {p.stem for p in (bank / "entities").glob("*.md")}
    edges = [{"source": l["source"], "target": l["target"], "label": "related to"} for l in shape["links"]
             if l["source"] in page_ids and l["target"] in page_ids]
    (bank / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": edges}), encoding="utf-8")

    saved = 0
    k = 0
    for origin, template, lists, count in SAVED:
        for j in range(count):
            k += 1
            pid = f"media-saved-{origin}-{j:05d}"
            eid = f"ep_{day(k)}_{10000 + k:05d}"
            url = template.format(u=j % 83, n=1_000_000 + k * 7)
            folder = lists[j % len(lists)]
            mentioned = j < MENTIONED // 2 and origin in ("youtube-playlist", "x-bookmarks")
            efm = {"id": eid, "source": "url", "timestamp": f"{day(k)}T10:00:00+00:00", "origin": origin, "url": url,
                   "title": f"Saved item {k}", "media_entity_id": pid, "processed": True, "processed_by": "sleep",
                   "saved_at": day(k)}
            (bank / "episodes" / f"{eid}.md").write_text(_doc(efm, f"# Saved item {k}\n"), encoding="utf-8")
            pfm = {"name": f"Saved item {k}", "type": "media", "status": "active", "confidence": 0.5,
                   "decay_class": "durable", "origin": origin, "created": day(k), "last_referenced": day(k),
                   "source_episodes": [eid] + ([talk[k % len(talk)]] if mentioned else []),
                   "media": {"url": url, "media_type": "url", "saved_at": day(k)}}
            if folder:
                pfm["folder"] = folder
            (bank / "entities" / f"{pid}.md").write_text(_doc(pfm, "## Summary\n\nA synthetic saved item.\n"),
                                                         encoding="utf-8")
            saved += 1
    return {"core_pages": core, "edges": len(edges), "saved": saved, "pages": core + saved}


def measure(bank: Path) -> dict:
    import api.main  # noqa: F401
    from api.services import graph_builder

    bank = bank.resolve()
    t = time.perf_counter()
    g = graph_builder.build_graph(bank)
    cold = (time.perf_counter() - t) * 1000
    warm = []
    for _ in range(5):
        t = time.perf_counter()
        graph_builder.build_graph(bank)
        warm.append((time.perf_counter() - t) * 1000)
    body = g.model_dump_json(by_alias=True)
    nodes = g.nodes
    folded = sum(len(b.members) for b in g.bubbles)
    return {"build_cold_ms": round(cold), "build_warm_ms": round(min(warm)), "json_bytes": len(body),
            "bubbles_bytes": len(json.dumps([b.model_dump(by_alias=True) for b in g.bubbles])),
            "nodes": len(nodes), "links": len(g.links), "quiet": sum(1 for n in nodes if n.quiet),
            "bubbles": len(g.bubbles), "folded": folded, "drawn_when_closed": len(nodes) - folded + len(g.bubbles),
            "lists": [(b.name, b.count, len(b.folders), len(b.outside)) for b in g.bubbles]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("build", "measure"))
    ap.add_argument("--bank", required=True, type=Path)
    args = ap.parse_args()
    out = build(args.bank) if args.what == "build" else measure(args.bank)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
