"""Side-by-side recall test for what an entity page's search vector is made from (2026-10-16, owner decision 4).

Builds the bank's entity vectors twice, into two throwaway indexes OUTSIDE the bank — A: ``full`` (today: the whole
body, its claims fence included), B: ``prose`` (no claims fence, capped at ``ENTITY_EMBED_MAX_CHARS``) — runs every
query against both, and reports recall@k, MRR and each query's win, loss or tie — on ``/search``'s page ranking (words,
the entity vectors and the pages their claims are about, fused: what the person's search returns; the verdict) and on
the entity vectors alone (the diagnostic). The words index is built in the throwaway folder too: the bank is only read.

    api/.venv/bin/python -m benchmarks.recall_ab --bank <bank dir> --queries <file> --out <result.json>

``--queries``: either the retrieval benchmark's YAML (``questions: [{question, expected_entities: [...]}]``, as in
``benchmarks/questions.example.yaml``) or JSON Lines (``{"query": "...", "relevant": ["entity-id", ...]}``). An
expected entity is a page id or a page name. A query with no expected entities still runs and is reported by how
much the two top-k lists agree.

The embedder is the bank's own search model (``--embedder configured``, the default — what the person's search uses)
or a feature-hashing stand-in (``--embedder hash``, for a synthetic proof only: it is not a learned model). A hosted,
metered model is refused unless ``--allow-metered``. Per-query lines carry the query's number, never its text, unless
``--show-queries``. The exit code is 0 when B is no worse than A on every recall@k and on MRR (beyond
``--tolerance``), 1 when it is worse, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

KS = (1, 3, 5, 10)


def load_queries(path: Path) -> list[dict]:
    """``[{"query": str, "relevant": [str]}]`` from the YAML question set or JSON Lines."""
    text = path.read_text(encoding="utf-8")
    rows: list[dict] = []
    if path.suffix in (".yaml", ".yml"):
        import yaml

        for q in (yaml.safe_load(text) or {}).get("questions", []):
            if q.get("question"):
                rows.append({"query": str(q["question"]),
                             "relevant": [str(e) for e in (q.get("expected_entities") or [])]})
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        rows.append({"query": str(obj["query"]), "relevant": [str(e) for e in (obj.get("relevant") or [])]})
    return rows


def _ids_by_name(bank: Path) -> dict[str, str]:
    """Lower-cased page id and name (and aliases) -> page id, so an expected entity may be written either way."""
    from api.services import markdown_parser

    out: dict[str, str] = {}
    for page in sorted((bank / "entities").glob("*.md")):
        try:
            fm = markdown_parser.parse(page, ledger=False).frontmatter or {}
        except Exception:  # noqa: BLE001
            continue
        out.setdefault(page.stem.lower(), page.stem)
        for name in [fm.get("name"), *(fm.get("aliases") or [])]:
            if name:
                out.setdefault(str(name).strip().lower(), page.stem)
    return out


def _metrics(ranked: list[str], relevant: set[str], ks) -> dict:
    first = next((i + 1 for i, eid in enumerate(ranked) if eid in relevant), None)
    out = {"rank": first, "rr": 1.0 / first if first else 0.0}
    for k in ks:
        out[f"recall@{k}"] = len(relevant & set(ranked[:k])) / len(relevant)
    return out


#: ``--hash-window``: how many leading word tokens the stand-in reads (0 = all). The local search model reads the
#: first 512 tokens of a text and drops the rest, so ``512`` makes the stand-in cut where the real model does.
HASH_WINDOW = 0


def hash_embed(texts, *, is_query=False):
    """Feature hashing over word tokens, 512 dims, sublinear term weight — a synthetic proof's stand-in only, not a
    learned model."""
    import hashlib
    import re

    import numpy as np

    out = np.zeros((len(texts), 512), dtype=np.float32)
    for row, text in enumerate(texts):
        counts: dict[int, int] = {}
        tokens = re.findall(r"[a-z0-9][a-z0-9-]*", text.lower())
        for token in (tokens[:HASH_WINDOW] if HASH_WINDOW else tokens):
            slot = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "little") % 512
            counts[slot] = counts.get(slot, 0) + 1
        for slot, n in counts.items():
            out[row, slot] = 1.0 + np.log(n)
        norm = np.linalg.norm(out[row])
        if norm:
            out[row] /= norm
    return out


def _embedder(kind: str, bank: Path, allow_metered: bool):
    if kind == "hash":
        return hash_embed, "feature-hash-512"
    from api.config import get_settings
    from api.services import embedding_models
    from api.services.providers import resolve_embed_fn_for_model

    settings = get_settings()
    model = embedding_models.build_model(bank, settings)
    metered = model.startswith(("text-embedding-", "openai/", "openrouter/")) or "gemini" in model
    if metered and not allow_metered:
        raise SystemExit(f"the bank's search model ({model}) is a hosted, metered one: embedding the bank twice "
                         "is billed. Pass --allow-metered to run it anyway.")
    return resolve_embed_fn_for_model(model, settings)


def build(bank: Path, mode: str, db: Path, embed_fn, model: str):
    from api.services import vector_index

    idx = vector_index.SqliteVecIndexer(bank, embed_fn=embed_fn, model_name=model, db_path=db, entity_text=mode)
    started = time.perf_counter()
    pages = idx.index_entities()
    seconds = time.perf_counter() - started
    chars = 0
    from api.services import markdown_parser

    for page in sorted((bank / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(page)
        except Exception:  # noqa: BLE001
            continue
        chars += len(vector_index._entity_embed_text(parsed.frontmatter or {}, parsed.body, page.stem, mode=mode))
    return idx, {"pages": pages, "build_s": round(seconds, 2), "embedded_chars": chars}


SURFACES = ("hybrid", "vector")


def _hybrid(bank: Path, work: Path):
    """``/search``'s page ranking (lexical pages, the entity vectors and the pages their claims are about, fused), with
    its words index built in ``work`` instead of the bank, and its vector leg answered by the index under test."""
    from api.services import search_index, search_service

    fts = work / "fts.db"
    real_db_path = search_index.db_path

    def restore():
        search_index.db_path = real_db_path
        search_index.invalidate(bank)   # forget the throwaway index's state: the bank's own is read next time

    search_index.db_path = lambda memory_path: fts if Path(memory_path).resolve() == bank else real_db_path(memory_path)
    try:
        if search_index.ensure_fresh(bank, wait=True) not in ("ready", "stale"):
            raise SystemExit("the words index could not be built (no FTS5?)")
    except BaseException:
        restore()
        raise
    per_kind = min(max(KS), search_service.MAX_PER_KIND)

    def rank(idx, query: str) -> list[str]:
        def legs(ctx, embed_fn):
            found = idx.search_kinds(ctx.q, {"entities": ctx.per_kind * 2})
            return found if any(found.values()) else None

        real = search_service._vector_legs
        search_service._vector_legs = legs
        try:
            resp = search_service.search(bank, query, kinds=("entity",), mode="hybrid", per_kind=per_kind,
                                         freshness_ttl_s=1e9)
        finally:
            search_service._vector_legs = real
        return [h.id for h in resp.results]

    return rank, restore


def run(bank: Path, queries: list[dict], work: Path, embed_fn, model: str, *, ks=KS, show=False) -> dict:
    names = _ids_by_name(bank)
    built = {}
    for mode in ("full", "prose"):
        built[mode] = build(bank, mode, work / f"{mode}.db", embed_fn, model)
    hybrid, restore = _hybrid(bank, work)
    try:
        per_query = _per_query(queries, names, built, hybrid, ks, show)
    finally:
        restore()
    return _summarize(per_query, built, model, ks)


def _per_query(queries, names, built, hybrid, ks, show) -> list[dict]:
    top = max(ks)
    per_query = []
    for n, q in enumerate(queries, 1):
        relevant = {names.get(r.strip().lower(), r.strip()) for r in q["relevant"] if r.strip()}
        row: dict = {"n": n}
        if show:
            row["query"] = q["query"]
        for surface in SURFACES:
            ranked = {}
            for mode, (idx, _) in built.items():
                if surface == "vector":
                    ranked[mode] = [h.get("metadata", {}).get("entity_id") for h in
                                    idx.search_entities(q["query"], top_k=top)]
                else:
                    ranked[mode] = hybrid(idx, q["query"])
            cell: dict = {"top_full": ranked["full"][:5], "top_prose": ranked["prose"][:5]}
            if relevant:
                a, b = _metrics(ranked["full"], relevant, ks), _metrics(ranked["prose"], relevant, ks)
                cell.update({"full": a, "prose": b,
                             "outcome": "win" if b["rr"] > a["rr"] else "loss" if b["rr"] < a["rr"] else "tie"})
            else:
                cell.update({"overlap@5": len(set(ranked["full"][:5]) & set(ranked["prose"][:5])) / 5,
                             "outcome": "unlabeled"})
            row[surface] = cell
        if relevant:
            row["relevant"] = sorted(relevant)
        per_query.append(row)
    return per_query


def _summarize(per_query, built, model, ks) -> dict:
    summary: dict = {"queries": len(per_query), "labeled": sum(1 for r in per_query if "relevant" in r)}
    for mode in ("full", "prose"):
        summary[mode] = dict(built[mode][1])
    for surface in SURFACES:
        cells = [r[surface] for r in per_query if r[surface]["outcome"] != "unlabeled"]

        def mean(mode, key, cells=cells):
            return round(statistics.fmean(c[mode][key] for c in cells), 4) if cells else None

        block: dict = {mode: {"mrr": mean(mode, "rr"), **{f"recall@{k}": mean(mode, f"recall@{k}") for k in ks}}
                       for mode in ("full", "prose")}
        block["delta"] = ({key: round(block["prose"][key] - block["full"][key], 4)
                           for key in ["mrr", *[f"recall@{k}" for k in ks]]} if cells else {})
        for outcome, key in (("win", "wins"), ("loss", "losses"), ("tie", "ties")):
            block[key] = sum(c["outcome"] == outcome for c in cells)
        unl = [r[surface]["overlap@5"] for r in per_query if r[surface]["outcome"] == "unlabeled"]
        block["unlabeled_overlap@5"] = round(statistics.fmean(unl), 4) if unl else None
        summary[surface] = block
    return {"model": model, "summary": summary, "per_query": per_query}


def no_worse(result: dict, tolerance: float) -> bool:
    """The verdict reads ``/search``'s ranking (``hybrid``) — what the person's search returns."""
    delta = result["summary"]["hybrid"]["delta"]
    return bool(delta) and all(v >= -tolerance for v in delta.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--queries", required=True, type=Path)
    ap.add_argument("--embedder", choices=("configured", "hash"), default="configured")
    ap.add_argument("--allow-metered", action="store_true")
    ap.add_argument("--hash-window", type=int, default=0,
                    help="with --embedder hash: read only the first N word tokens of a text, as a model's window does")
    ap.add_argument("--work", type=Path, help="where the two throwaway indexes go (default: a temp dir, removed)")
    ap.add_argument("--out", type=Path, help="write the full result as JSON here")
    ap.add_argument("--tolerance", type=float, default=0.0)
    ap.add_argument("--show-queries", action="store_true", help="print each query's text beside its number")
    a = ap.parse_args(argv)
    global HASH_WINDOW
    HASH_WINDOW = max(0, a.hash_window)
    os.environ.setdefault("CICADA_TELEMETRY", "off")   # a measurement, not the person's use
    os.environ.setdefault("CICADA_CAPTURE", "off")
    bank = a.bank.expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(f"no entities/ under {bank}", file=sys.stderr)
        return 2
    queries = load_queries(a.queries)
    if not queries:
        print("no queries", file=sys.stderr)
        return 2
    work = (a.work or Path(tempfile.mkdtemp(prefix="cicada-recall-ab-"))).expanduser().resolve()
    if work == bank or bank in work.parents:
        print("--work must be outside the bank: the bank is only read", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    try:
        embed_fn, model = _embedder(a.embedder, bank, a.allow_metered)
        result = run(bank, queries, work, embed_fn, model, show=a.show_queries)
    finally:
        if a.work is None:
            shutil.rmtree(work, ignore_errors=True)
    s = result["summary"]
    print(f"model {result['model']} · {s['queries']} queries ({s['labeled']} labeled)")
    for mode in ("full", "prose"):
        print(f"  {mode:6} {s[mode]['pages']} pages, {s[mode]['embedded_chars']:,} characters embedded, "
              f"built in {s[mode]['build_s']} s")
    for surface in SURFACES:
        b = s[surface]
        title = "search (/search's page ranking: words + vectors + claims)" if surface == "hybrid" else \
            "entity vectors alone"
        print(f"\n{title}")
        print(f"{'':8}{'MRR':>8}" + "".join(f"{'R@' + str(k):>8}" for k in KS))
        for mode in ("full", "prose"):
            print(f"{mode:8}{b[mode]['mrr'] or 0:>8.3f}" + "".join(f"{(b[mode][f'recall@{k}'] or 0):>8.3f}" for k in KS))
        if b["delta"]:
            print("delta   " + " ".join(f"{k} {v:+.4f}" for k, v in b["delta"].items()))
            print(f"per query: {b['wins']} better, {b['losses']} worse, {b['ties']} same (by reciprocal rank)")
        if b["unlabeled_overlap@5"] is not None:
            print(f"unlabeled queries: top-5 overlap {b['unlabeled_overlap@5']:.2f}")
        for r in result["per_query"]:
            c = r[surface]
            if c["outcome"] in ("win", "loss"):
                label = f"#{r['n']}" + (f" {r['query']!r}" if a.show_queries else "")
                print(f"  {c['outcome']:5} {label}: rank {c['full']['rank']} -> {c['prose']['rank']}")
    if a.out:
        a.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
        os.chmod(a.out, 0o600)
    verdict = no_worse(result, a.tolerance)
    print("\nVERDICT (search): prose is " + ("no worse than" if verdict else "WORSE than") + " full"
          + ("" if s["hybrid"]["delta"] else " (no labeled queries: nothing to compare)"))
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
