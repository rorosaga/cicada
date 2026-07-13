"""Consolidation model-comparison harness (Table-X, M5 prep).

For each candidate LLM id, run Cicada's **real** Stage-1 entity/claim extraction
(``api.services.entity_extractor``) on the N biggest real episodes in
``memory/episodes/`` and dump each model's output side-by-side so the thesis can
compare consolidation quality + cost across providers (all routed through
litellm; OpenRouter is just one of the model-id prefixes).

Output (all under the gitignored ``benchmark_results/`` — NEVER committed):

    benchmark_results/model_comparison/
        <episode_id>/<model_slug>.json     # entities, relationships, claims, summaries, usage
        index.md                            # side-by-side table (episodes x models)
        embed_test.json                     # --embed-test: dims + cost for the embedding model

Per-call cost + tokens come from the litellm response ``usage`` (OpenRouter
returns ``usage.cost``). Everything is bounded by ``--models``, ``--n`` episodes,
and a per-episode ``--max-chars`` truncation so a run can't blow the budget.

This is a RUN-phase tool — it makes real network calls and is NOT part of the
unit suite. It is read-only over ``memory/episodes/`` and never mutates ``memory/``.

Examples
--------
    api/.venv/bin/python -m benchmarks.run_model_comparison --n 1
    api/.venv/bin/python -m benchmarks.run_model_comparison \
        --models openrouter/z-ai/glm-5.2 openrouter/qwen/qwen3.7-max --n 3
    api/.venv/bin/python -m benchmarks.run_model_comparison --embed-test --n 0
"""

from __future__ import annotations

# Must be first — sets sys.path and loads api/.env (OPENROUTER_API_KEY etc.).
from benchmarks import _bootstrap  # noqa: F401

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from benchmarks._bootstrap import BENCHMARK_RESULTS, LIVE_MEMORY_PATH

from api.config import Settings
from api.services import entity_extractor

DEFAULT_MODELS = [
    "openrouter/z-ai/glm-5.2",
    "openrouter/minimax/minimax-m3",
    "openrouter/qwen/qwen3.7-max",
]
DEFAULT_EMBED_MODEL = "google/gemini-embedding-2"
OUT_DIR = BENCHMARK_RESULTS / "model_comparison"


def _model_slug(model: str) -> str:
    return model.replace("/", "__")


def _biggest_episodes(episodes_dir: Path, n: int) -> list[Path]:
    files = sorted(episodes_dir.glob("ep_*.md"), key=lambda p: p.stat().st_size, reverse=True)
    return files[:n]


def _load_episode(path: Path, max_chars: int) -> dict:
    """Read an episode file into the ``extract`` episode dict shape, truncated."""
    from api.services import markdown_parser

    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter or {}
    content = parsed.body or ""
    if max_chars and len(content) > max_chars:
        content = content[:max_chars]
    return {
        "id": str(fm.get("id", path.stem)),
        "content": content,
        "timestamp": str(fm.get("timestamp", "")),
        "origin": str(fm.get("source", "unknown")),
        "_file": str(path),
        "_bytes": path.stat().st_size,
        "_used_chars": len(content),
    }


def _sum_usage(usages: list) -> dict:
    """Aggregate litellm ``usage`` objects (dict or attr-style) into totals."""
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    cost = 0.0
    for u in usages:
        if u is None:
            continue
        get = (lambda k: u.get(k)) if isinstance(u, dict) else (lambda k: getattr(u, k, None))
        prompt_tokens += int(get("prompt_tokens") or 0)
        completion_tokens += int(get("completion_tokens") or 0)
        total_tokens += int(get("total_tokens") or 0)
        c = get("cost")
        if c is None:
            # OpenRouter sometimes nests cost under a hidden field on the response.
            c = get("response_cost")
        cost += float(c or 0.0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost": round(cost, 6),
    }


async def _extract_one(episode: dict, model: str) -> dict:
    """Run real Stage-1 extraction for one (episode, model), capturing usage.

    We reuse the production chunk+extract path but wrap litellm so we can collect
    per-call usage; ``entity_extractor.extract`` returns the same entity/relation
    shape it feeds into consolidation.
    """
    import litellm

    settings = Settings(litellm_model=model)
    usages: list = []

    orig_acompletion = litellm.acompletion

    async def _wrapped_acompletion(**kwargs):
        resp = await orig_acompletion(**kwargs)
        usages.append(getattr(resp, "usage", None))
        return resp

    litellm.acompletion = _wrapped_acompletion
    t0 = time.monotonic()
    try:
        extracted = await entity_extractor.extract([episode], settings)
    finally:
        litellm.acompletion = orig_acompletion
    elapsed = time.monotonic() - t0

    record = extracted[0] if extracted else {"entities": [], "relationships": []}
    # Derive perspectival claims via the real projection (no normalizer => slugged).
    claims = entity_extractor.entities_to_claims(extracted, None)
    summaries = [
        {"name": e.get("name"), "type": e.get("type"), "summary": e.get("summary", "")}
        for e in record.get("entities", [])
    ]
    return {
        "model": model,
        "episode_id": episode["id"],
        "source_bytes": episode["_bytes"],
        "used_chars": episode["_used_chars"],
        "elapsed_s": round(elapsed, 2),
        "entities": record.get("entities", []),
        "relationships": record.get("relationships", []),
        "claims": [c.to_dict() if hasattr(c, "to_dict") else vars(c) for c in claims],
        "summaries": summaries,
        "counts": {
            "entities": len(record.get("entities", [])),
            "relationships": len(record.get("relationships", [])),
            "claims": len(claims),
        },
        "usage": _sum_usage(usages),
        "n_llm_calls": len(usages),
    }


def _write_index(results: dict[str, dict[str, dict]], models: list[str]) -> Path:
    """results: {episode_id: {model: record}} -> a markdown comparison table."""
    lines: list[str] = ["# Model comparison — consolidation Stage-1\n"]
    lines.append("Cells: entities / relationships / claims · tokens · $cost\n")
    header = "| episode | " + " | ".join(models) + " |"
    sep = "|" + "---|" * (len(models) + 1)
    lines.append(header)
    lines.append(sep)
    totals = {m: {"entities": 0, "claims": 0, "tokens": 0, "cost": 0.0} for m in models}
    for ep_id in sorted(results):
        row = [ep_id]
        for m in models:
            rec = results[ep_id].get(m)
            if not rec:
                row.append("—")
                continue
            c = rec["counts"]
            u = rec["usage"]
            row.append(
                f"{c['entities']}/{c['relationships']}/{c['claims']} · "
                f"{u['total_tokens']}t · ${u['cost']:.4f}"
            )
            totals[m]["entities"] += c["entities"]
            totals[m]["claims"] += c["claims"]
            totals[m]["tokens"] += u["total_tokens"]
            totals[m]["cost"] += u["cost"]
        lines.append("| " + " | ".join(row) + " |")
    total_row = ["**TOTAL**"]
    for m in models:
        t = totals[m]
        total_row.append(
            f"**{t['entities']}e/{t['claims']}c · {t['tokens']}t · ${t['cost']:.4f}**"
        )
    lines.append("| " + " | ".join(total_row) + " |")
    lines.append("")
    out = OUT_DIR / "index.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _run_embed_test(settings: Settings) -> Path:
    """Embed a few fixed strings via the configured embedding provider; record dim."""
    from api.services.providers import resolve_embed_fn

    samples = [
        "Cicada consolidates episodic memory into a versioned knowledge graph.",
        "OpenRouter is an OpenAI-compatible router for many models.",
        "The capstone deadline is the binding constraint this term.",
    ]
    embed_fn, model = resolve_embed_fn(settings)
    t0 = time.monotonic()
    vecs = embed_fn(samples, is_query=False)
    elapsed = time.monotonic() - t0
    record = {
        "model": model,
        "mode": settings.resolved_embedding_mode,
        "n_samples": len(samples),
        "dim": int(vecs.shape[1]) if vecs.ndim == 2 else None,
        "elapsed_s": round(elapsed, 2),
        "note": "cost not returned per-embedding by all providers; check OpenRouter dashboard",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "embed_test.json"
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"embed-test: model={model} dim={record['dim']} -> {out}", file=sys.stderr)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path, default=LIVE_MEMORY_PATH)
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    parser.add_argument("--n", type=int, default=1, help="biggest-N episodes to run")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=24_000,
        help="truncate each episode body to this many chars (token-cap proxy)",
    )
    parser.add_argument(
        "--embed-test",
        action="store_true",
        help=f"also embed sample strings with the embedding provider (default {DEFAULT_EMBED_MODEL})",
    )
    parser.add_argument(
        "--embed-mode",
        default="openrouter",
        help="embedding mode for --embed-test (openrouter|openai|local)",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    episodes_dir = args.memory / "episodes"

    if args.embed_test:
        es = Settings(embedding_mode=args.embed_mode, embedding_model_openrouter=DEFAULT_EMBED_MODEL)
        _run_embed_test(es)

    if args.n <= 0:
        print("n<=0: skipping LLM comparison.", file=sys.stderr)
        return

    ep_paths = _biggest_episodes(episodes_dir, args.n)
    if not ep_paths:
        print(f"no episodes found under {episodes_dir}", file=sys.stderr)
        return

    print(
        f"comparing {len(args.models)} models x {len(ep_paths)} episodes "
        f"(max {args.max_chars} chars each)",
        file=sys.stderr,
    )

    results: dict[str, dict[str, dict]] = {}
    for ep_path in ep_paths:
        episode = _load_episode(ep_path, args.max_chars)
        ep_id = episode["id"]
        results.setdefault(ep_id, {})
        ep_out_dir = OUT_DIR / ep_id
        ep_out_dir.mkdir(parents=True, exist_ok=True)
        for model in args.models:
            print(f"  {ep_id}  <-  {model}", file=sys.stderr)
            try:
                record = asyncio.run(_extract_one(episode, model))
            except Exception as exc:  # noqa: BLE001
                print(f"    FAILED ({model}): {type(exc).__name__}: {exc}", file=sys.stderr)
                record = {"model": model, "episode_id": ep_id, "error": str(exc),
                          "counts": {"entities": 0, "relationships": 0, "claims": 0},
                          "usage": {"total_tokens": 0, "cost": 0.0}}
            results[ep_id][model] = record
            out_file = ep_out_dir / f"{_model_slug(model)}.json"
            out_file.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
            u = record.get("usage", {})
            print(
                f"    -> {record['counts']['entities']}e/"
                f"{record['counts'].get('relationships', 0)}r/"
                f"{record['counts']['claims']}c  "
                f"{u.get('total_tokens', 0)}t  ${u.get('cost', 0.0):.4f}",
                file=sys.stderr,
            )

    index = _write_index(results, args.models)
    print(f"\nwrote comparison table -> {index}", file=sys.stderr)


if __name__ == "__main__":
    main()
