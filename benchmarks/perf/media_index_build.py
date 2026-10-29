"""An hour of a recording's words into the meaning index, measured with the real text model, and the passage floor
calibrated (meaning index 2):

    CICADA_HOME=<scratch home with models/embeddinggemma-2> \\
      api/.venv/bin/python -m benchmarks.perf.media_index_build --bank <scratch dir> [--hours 1]

Writes ``--hours`` of synthetic speech (150 words a minute, a 10-second segment each, eight made-up topics in turn —
no real recording, nothing downloaded) through ``media_files.record_media`` as the app would post it, builds the
``files`` kind cold through ``media_files.refresh_text`` (the embed child, as the background refresher does), and
reports the wall time per hour and the passages. Then the floor: the lift of the best passage for a query about each
topic said in the recording, and for a query about a topic never said.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import statistics
import time
from pathlib import Path

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
ABSENT = ["the insurance claim for the car accident", "a dentist appointment about my wisdom teeth",
          "the election results and the polls", "a knitting pattern for a wool scarf"]


def speech(hours: float, seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    segs, t = [], 0.0
    names = list(TOPICS)
    per_topic = max(1, int(hours * 360 / len(names)))      # 360 ten-second segments an hour
    for name in names * max(1, int(hours)):
        words = TOPICS[name].split()
        for _ in range(per_topic):
            seg = [rng.choice(words) if rng.random() < 0.35 else rng.choice(FILLER) for _ in range(25)]
            segs.append({"start": t, "end": t + 9.8, "text": " ".join(seg).capitalize() + "."})
            t += 10.0
    return segs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--hours", type=float, default=1.0)
    a = ap.parse_args()
    bank = a.bank.resolve()
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    from api.services import embed_worker, media_files, onnx_embedder, providers

    fn, model = providers.cached_embed_fn_for_model(onnx_embedder.PREFERRED_ID)
    embed = embed_worker.documents(model, fn) if embed_worker.eligible(model) else fn

    def embed_fn(texts, *, is_query=False):
        return fn(texts, is_query=True) if is_query else embed(texts, is_query=False)

    segs = speech(a.hours)
    sha = hashlib.sha256(str(len(segs)).encode()).hexdigest()
    media_files.record_media(bank, name="a synthetic hour.m4a", kind="audio", sha256=sha,
                             duration_s=segs[-1]["end"], segments=segs)
    words = sum(len(s["text"].split()) for s in segs)
    t0 = time.monotonic()
    stats = media_files.refresh_text(bank, embed_fn=embed_fn)
    took = time.monotonic() - t0
    print(f"{a.hours:g} h of speech: {len(segs)} segments, {words:,} words, {stats['embedded']} passages, "
          f"cold embed {took:.1f} s = {took / a.hours:.1f} s per hour (text model {model}, child for long batches)")
    lifts_said, lifts_absent = [], []
    for name, vocab in TOPICS.items():
        q = " ".join(vocab.split()[:4])
        hits = media_files.search_text(bank, q, top_k=1, embed_fn=embed_fn)
        lifts_said.append(hits[0]["score"] if hits else None)
    saved = media_files.TEXT_LIFT_MIN
    media_files.TEXT_LIFT_MIN = -1.0                      # read the raw best lift for the absent topics
    for q in ABSENT:
        hits = media_files.search_text(bank, q, top_k=1, embed_fn=embed_fn)
        lifts_absent.append(hits[0]["score"] if hits else None)
    media_files.TEXT_LIFT_MIN = saved
    shown = [x for x in lifts_said if x is not None]
    print(f"best-passage lift, topic said: min {min(shown):.3f} median {statistics.median(shown):.3f} "
          f"({len(shown)}/{len(lifts_said)} above the floor {saved})")
    print(f"best-passage lift, topic never said: max {max(lifts_absent):.3f} (raw, no floor)")
    lat = []
    for _ in range(3):
        for name, vocab in TOPICS.items():
            t0 = time.perf_counter()
            media_files.search_text(bank, " ".join(vocab.split()[2:6]), top_k=8, embed_fn=embed_fn)
            lat.append(1000 * (time.perf_counter() - t0))
    lat.sort()
    print(f"files leg p50 {statistics.median(lat):.1f} ms, p95 {lat[int(0.95 * (len(lat) - 1))]:.1f} ms")
    embed_worker.shutdown()


if __name__ == "__main__":
    main()
