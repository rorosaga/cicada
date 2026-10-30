"""G132 phase 3a: the incremental bundle sizes phase 1 did not measure, and what each costs on the relay's wire.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.owner_scale --bank <dir>/bank --pages 7150 \
        --saved 850 --episodes 9000 --processed 8000 --inbox 470          # phase 1 B's counts, ~75 s
    cp -R <dir>/bank <dir>/run
    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.relay_bundles --bank <dir>/run

On a copy of a synthetic owner-scale bank it makes, and bundles exactly as ``sync_pack`` does
(``git bundle create <tmp> HEAD ^<have>``):

- **a capture commit:** one new episode, its size drawn from the owner bank's measured episode-size quantiles (a
  read-only ``stat`` of the real bank's files; no content read; the text here is synthetic words);
- **a Sleep batch of 25:** one real ``sleep_cycle`` batch through ``profile_sleep``'s deterministic engine, every
  commit it makes, bundled from before the batch to after it;
- **a day of normal use:** ``--day-captures`` capture commits with ``--day-batches`` Sleep batches between them, both as
  the sum of per-commit bundles (a device that stays online) and as one coalesced ``start..end`` bundle (a device that
  was off all day and is sent ``cursor..HEAD``);
- **the bootstrap:** the whole history.

Each figure is also given as the relay's stored bytes (``sync_relay_crypto.framed_size``: padding buckets, parts,
headers, nonce, tag, signature). The bank is mutated: run it on a copy.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import isolate

#: Episode file sizes in the owner's active bank, 2026-10-29: 8,928 files, p50 859 B, p90 8,161 B, p99 64,213 B
#: (a read-only ``stat``; no content read). Sampled as quantiles so a "day" draws a realistic mix.
EPISODE_QUANTILES = [(0.50, 859), (0.90, 8_161), (0.99, 64_213), (1.00, 120_000)]
WORDS = ("signal graph memory sleep decay claim span evidence vector index lexical prose fence batch drain resolve "
         "ledger trailer session harness backend frontend render decode parse serialize cache page bank owner "
         "alpha-project beta-project uses plan review decided draft release").split()


def git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], text=True, capture_output=True, check=True).stdout.strip()


def head(bank: Path) -> str:
    return git(bank, "rev-parse", "HEAD")


def bundle_bytes(bank: Path, have: str | None) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "b.bundle"
        args = ["bundle", "create", "-q", str(out), "HEAD"] + ([f"^{have}"] if have else [])
        subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True)
        return out.stat().st_size


def episode_size(rng: random.Random) -> int:
    u = rng.random()
    lo_q, lo_s = 0.0, 200
    for q, s in EPISODE_QUANTILES:
        if u <= q:
            return int(lo_s + (s - lo_s) * (u - lo_q) / (q - lo_q))
        lo_q, lo_s = q, s
    return EPISODE_QUANTILES[-1][1]


def capture(bank: Path, rng: random.Random, i: int, size: int | None = None) -> int:
    size = size or episode_size(rng)
    eid = f"ep_2026-10-29_{900 + i:03d}"
    head_text = (f"---\nid: {eid}\ntimestamp: '2026-10-29T09:{i % 60:02d}:00+00:00'\nreceived_at: "
                 f"'2026-10-29T09:{i % 60:02d}:05+00:00'\nprocessed: false\nsource: claude-code\ntitle: Session {i}\n---\n")
    body = []
    while len(head_text) + sum(len(w) + 1 for w in body) < size:
        body.append(rng.choice(WORDS))
    path = bank / "episodes" / f"{eid}.md"
    path.write_text(head_text + "user: " + " ".join(body) + "\n", encoding="utf-8")
    git(bank, "add", str(path.relative_to(bank)))
    git(bank, "commit", "-q", "-m", f"Capture {eid}\n\nCicada-Author: cicada\nCicada-Trigger: sync/capture")
    return path.stat().st_size


def sleep_batch(bank: Path, batch: int) -> dict:
    before = head(bank)
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, "-m", "benchmarks.scale.profile_sleep", "--bank", str(bank),
                           "--batch", str(batch)], capture_output=True, text=True, env=os.environ.copy(),
                          cwd=str(Path(__file__).resolve().parents[2]))
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-3000:])
    after = head(bank)
    files = git(bank, "diff", "--name-only", before, after).splitlines()
    return {"before": before, "after": after, "seconds": round(time.perf_counter() - started, 1),
            "commits": int(git(bank, "rev-list", "--count", f"{before}..{after}")), "files_changed": len(files),
            "entity_files": sum(1 for f in files if f.startswith("entities/")),
            "episode_files": sum(1 for f in files if f.startswith("episodes/"))}


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--captures", type=int, default=30, help="capture commits sampled one by one")
    ap.add_argument("--batches", type=int, default=2, help="Sleep batches of 25 sampled one by one")
    ap.add_argument("--day-captures", type=int, default=48)
    ap.add_argument("--day-batches", type=int, default=2)
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    from api.services.sync_relay_crypto import framed_size

    rng = random.Random(29)
    out: dict = {"bank": {"entities": sum(1 for _ in (bank / "entities").glob("*.md")),
                          "episodes": sum(1 for _ in (bank / "episodes").glob("*.md")),
                          "git_kb": int(subprocess.run(["du", "-sk", str(bank / ".git")], capture_output=True,
                                                       text=True).stdout.split()[0])}}
    out["bootstrap_bytes"] = bundle_bytes(bank, None)

    caps, caps_framed, caps_file = [], [], []
    for i in range(a.captures):
        prev = head(bank)
        caps_file.append(capture(bank, rng, i))
        size = bundle_bytes(bank, prev)
        caps.append(size)
        caps_framed.append(framed_size(size))
    out["capture"] = {"n": len(caps), "file_p50": q(caps_file, .5), "bundle_p50": q(caps, .5),
                      "bundle_p95": q(caps, .95), "bundle_max": max(caps), "framed_p50": q(caps_framed, .5),
                      "framed_p95": q(caps_framed, .95)}

    batches = []
    for _ in range(a.batches):
        info = sleep_batch(bank, 25)
        info["bundle_bytes"] = bundle_bytes(bank, info["before"])
        per_commit = git(bank, "rev-list", "--reverse", f"{info['before']}..{info['after']}").splitlines()
        info["framed_bytes"] = framed_size(info["bundle_bytes"])
        info["per_commit_bundles"] = []
        prev = info["before"]
        for sha in per_commit:
            # A bundle names refs, not bare commits: point a scratch ref at each commit in turn.
            git(bank, "update-ref", "refs/bench/commit", sha)
            with tempfile.TemporaryDirectory() as tmp:
                b = Path(tmp) / "c.bundle"
                subprocess.run(["git", "-C", str(bank), "bundle", "create", "-q", str(b), "refs/bench/commit",
                                f"^{prev}"], check=True, capture_output=True)
                info["per_commit_bundles"].append(b.stat().st_size)
            prev = sha
        git(bank, "update-ref", "-d", "refs/bench/commit")
        batches.append({k: v for k, v in info.items() if k not in ("before", "after")})
    out["sleep_batch_25"] = batches

    start = head(bank)
    live, live_framed, commits = 0, 0, 0
    every = max(1, a.day_captures // (a.day_batches + 1))
    for i in range(a.day_captures):
        prev = head(bank)
        capture(bank, rng, 100 + i)
        size = bundle_bytes(bank, prev)
        live += size
        live_framed += framed_size(size)
        commits += 1
        if (i + 1) % every == 0 and (i + 1) // every <= a.day_batches:
            info = sleep_batch(bank, 25)
            size = bundle_bytes(bank, info["before"])
            live += size
            live_framed += framed_size(size)
            commits += info["commits"]
    coalesced = bundle_bytes(bank, start)
    out["day"] = {"captures": a.day_captures, "sleep_batches": a.day_batches, "commits": commits,
                  "live_sum_bytes": live, "live_framed_bytes": live_framed, "coalesced_bytes": coalesced,
                  "coalesced_framed_bytes": framed_size(coalesced)}
    out["bootstrap_framed_bytes"] = framed_size(out["bootstrap_bytes"])
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
