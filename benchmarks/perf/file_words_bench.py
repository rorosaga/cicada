"""Added files found by the words inside them (ROR-117, G43): the palette's latency with the words leg, and the recall of
a once-said distinctive word with and without it.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.perf.file_words_bench latency [--passages 2000 10000 25000]
    SCALE_SCRATCH=<dir> HF_HUB_OFFLINE=1 api/.venv/bin/python -m benchmarks.perf.file_words_bench recall [--recordings 60]

``latency`` builds a synthetic bank of the size the 12.5 ms palette figure was measured at (2,000 pages, 1,500
conversations), adds recordings until the words index holds each ``--passages`` count (made-up speech, a Zipf
vocabulary, 20 distinctive words said once), and times ``search_service.search`` in prefix mode — the palette's
keystroke pass — with the palette's kinds and with ``file`` added, and the words leg alone. Only numbers are printed.

``recall`` writes ``--recordings`` made-up recordings (two topics each, ten-second segments) that say 40 distinctive
words — an invented surname, a product code, an eight-digit number — once each, indexes them with the real text model
(``google/embeddinggemma-300m`` from the local Hugging Face cache, 4 threads) and asks for each word alone and inside a
question, three ways: by meaning only (what ``media_files.search_text`` returned before), by words only, and fused
(``media_files.find``). A hit is a passage that holds the word; it counts at rank 1, in the top 3, and in the top 8.
"""
from __future__ import annotations

from benchmarks.scale import isolate  # noqa: F401  (first)

import argparse
import json
import random
import statistics
import time
from pathlib import Path

PALETTE = ("entity", "claim", "episode", "media")
SYLLABLES = ["ba", "ke", "lo", "mi", "ra", "su", "ti", "vo", "ne", "da", "fi", "gu", "ha", "jo", "pe", "qui", "wen", "zor"]
TOPICS = {
    "garden": "tomato seedlings compost soil watering raised beds basil harvest weeds mulch greenhouse",
    "budget": "quarterly budget spending forecast invoices savings expenses revenue spreadsheet costs payroll",
    "guitar": "guitar chords strings capo fingerpicking song melody tuning amplifier practice rhythm",
    "travel": "train tickets hotel booking passport itinerary airport luggage city map museum",
    "cooking": "recipe oven pasta garlic onions simmer sauce spices dough bake dinner",
    "running": "marathon training pace miles intervals shoes stretching race recovery hills",
    "moving": "apartment lease boxes movers landlord deposit furniture neighborhood keys rent",
    "course": "lecture assignment exam grades semester professor essay reading deadline syllabus",
}
FILLER = "so we talked about it and then we went over the next part and that was the plan for the week".split()


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))]


def stats(lat: list[float]) -> dict:
    return {"p50": round(statistics.median(lat), 2), "p95": round(pct(lat, 0.95), 2), "n": len(lat)}


def distinctive(rng: random.Random, kind: int) -> str:
    if kind == 0:
        return "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(3, 4))).capitalize()
    if kind == 1:
        return f"{''.join(rng.choice('ZXKQ') for _ in range(2))}-{rng.randint(1000, 9999)}"
    return str(rng.randint(10_000_000, 99_999_999))


def zipf_vocab(rng: random.Random, n: int = 4000) -> tuple[list[str], list[float]]:
    words = sorted({"".join(rng.choice(SYLLABLES) for _ in range(rng.randint(1, 3))) + rng.choice(["", "s", "ing", "ed"])
                    for _ in range(n * 2)})[:n]
    rng.shuffle(words)
    return words, [1.0 / (i + 1) for i in range(len(words))]


def make_recordings(bank: Path, passages: int, rng: random.Random, words_said: int = 20) -> list[str]:
    """Made-up speech until the words index holds ``passages``; returns the distinctive words said once each."""
    from api.services import file_words, media_files

    vocab, weights = zipf_vocab(rng)
    said, n, i = [], file_words.count(bank), len(media_files.list_files(bank))
    while n < passages:
        segs = []
        for s in range(120):
            text = " ".join(rng.choices(vocab, weights, k=24)).capitalize() + "."
            segs.append({"start": s * 10.0, "end": s * 10.0 + 9.5, "text": text})
        if len(said) < words_said and (i + 1) % 7 == 0:
            w = distinctive(rng, len(said) % 3)
            segs[rng.randrange(len(segs))]["text"] += f" I spoke with {w} about it."
            said.append(w)
        sha = f"{i:064x}"
        media_files.record_media(bank, name=f"recording {i}", kind="audio", sha256=sha, segments=segs)
        i += 1
        n = file_words.count(bank)
    return said


def latency(a) -> dict:
    from benchmarks.scale import synth

    bank = Path(isolate.SCRATCH) / "bank"
    synth.JSONL = True   # the form every production writer emits
    synth.build(bank, 3500, 2000, 1500, 975, 40, 7)
    isolate.pin_bank(bank)
    from api.services import bank_index, file_words, search_index, search_service

    search_index.ensure_fresh(bank, wait=True)
    rng = random.Random(5)
    names = [" ".join(str((f.frontmatter or {}).get("name") or "").split()[:1]) for f in bank_index.files(bank, "entities")]
    names = [n for n in names if len(n) >= 4]
    out = {"pages": len(names), "runs": []}
    said: list[str] = []
    for target in a.passages:
        t0 = time.monotonic()
        said += make_recordings(bank, target, rng, words_said=0 if said else 20)
        file_words.ensure(bank, force=True)
        built = round(time.monotonic() - t0, 1)
        typed = [n[:k].lower() for n in rng.sample(names, 40) for k in (2, 3, 4)]
        typed += [w[:k].lower() for w in said for k in (3, 4, len(w))]
        for _ in range(2):   # warm
            for q in typed[:20]:
                search_service.search(bank, q, kinds=(*PALETTE, "file"), mode="prefix")

        def timed(kinds):
            lat = []
            for rep in range(3):
                for q in typed:
                    t = time.perf_counter()
                    search_service.search(bank, q, kinds=kinds, mode="prefix")
                    if rep:
                        lat.append(1000 * (time.perf_counter() - t))
            return stats(lat)

        words_only = []
        for rep in range(3):
            for q in typed:
                t = time.perf_counter()
                file_words.search(bank, q, limit=8)
                if rep:
                    words_only.append(1000 * (time.perf_counter() - t))
        out["runs"].append({"passages": file_words.count(bank), "build_s": built, "palette": timed(PALETTE),
                            "palette+file": timed((*PALETTE, "file")), "file": timed(("file",)),
                            "words_leg_only": stats(words_only)})
        print(json.dumps(out["runs"][-1]), flush=True)
    return out


def recall(a) -> dict:
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(4)
    model = SentenceTransformer("google/embeddinggemma-300m", device="cpu")

    def embed(texts, *, is_query=False):
        vecs = model.encode_query(list(texts)) if is_query else model.encode_document(list(texts), batch_size=8)
        vecs = np.asarray(vecs, dtype=np.float32)
        return vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)

    bank = Path(isolate.SCRATCH) / "bank"
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    isolate.pin_bank(bank)
    from api.services import file_words, media_files, search_index

    search_index.ensure_fresh(bank, wait=True)
    rng = random.Random(11)
    names = list(TOPICS)
    said: list[str] = []
    for r in range(a.recordings):
        topics = rng.sample(names, 2)
        segs = []
        for s in range(60):
            vocab = TOPICS[topics[s // 30]].split()
            words = [rng.choice(vocab) if rng.random() < 0.35 else rng.choice(FILLER) for _ in range(25)]
            segs.append({"start": s * 10.0, "end": s * 10.0 + 9.5, "text": " ".join(words).capitalize() + "."})
        if len(said) < a.words and r * a.words // a.recordings >= len(said):
            w = distinctive(rng, len(said) % 3)
            segs[rng.randrange(len(segs))]["text"] += f" Then {w} came up."
            said.append(w)
        media_files.record_media(bank, name=f"recording {r}", kind="audio", sha256=f"{r:064x}", segments=segs)
    t0 = time.monotonic()
    media_files.refresh_text(bank, embed_fn=embed)
    out = {"recordings": a.recordings, "passages": file_words.count(bank), "words_said_once": len(said),
           "embed_s": round(time.monotonic() - t0, 1)}

    def holds(rows, w):
        return [w in (r.get("text") or r.get("body") or "") for r in rows]

    def rank(flags):
        return flags.index(True) + 1 if True in flags else None

    legs = {
        "meaning": lambda q: media_files.search_text(bank, q, top_k=8, embed_fn=embed),
        "words": lambda q: file_words.search(bank, q, limit=8, plain_words=True),
        "fused": lambda q: media_files.find(bank, q, top_k=8, embed_fn=embed),
    }
    shapes = {"the word alone": lambda w: w, "inside a question": lambda w: f"what did they say about {w}"}
    for shape, ask in shapes.items():
        row = {}
        for leg, fn in legs.items():
            ranks = [rank(holds(fn(ask(w)), w)) for w in said]
            row[leg] = {"top1": sum(1 for r in ranks if r == 1), "top3": sum(1 for r in ranks if r and r <= 3),
                        "top8": sum(1 for r in ranks if r), "of": len(said)}
        out[shape] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lat = sub.add_parser("latency")
    lat.add_argument("--passages", type=int, nargs="+", default=[2000, 10000, 25000])
    rec = sub.add_parser("recall")
    rec.add_argument("--recordings", type=int, default=60)
    rec.add_argument("--words", type=int, default=40)
    a = ap.parse_args()
    print(json.dumps(latency(a) if a.cmd == "latency" else recall(a), indent=2))


if __name__ == "__main__":
    main()
