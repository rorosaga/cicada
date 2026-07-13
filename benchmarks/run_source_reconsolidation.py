"""Resumable, cost-instrumented batch runner for the source-grounded rewrite
pass (Phase 3). Thin/low-confidence pages first; a done-marker makes it
resumable. Runs on the DUPLICATE bank only."""
from __future__ import annotations
import logging
import subprocess
from pathlib import Path
from api.services import git_service, markdown_parser

logger = logging.getLogger(__name__)


def ordered_entities(memory_path: Path) -> list[str]:
    scored = []
    for f in (memory_path / "entities").glob("*.md"):
        par = markdown_parser.parse(f)
        words = len((par.body or "").split())
        conf = float(par.frontmatter.get("confidence", 0.5) or 0.5)
        scored.append((words + conf * 100, f.stem))   # thin + low-conf sort first
    scored.sort(key=lambda x: x[0])
    return [eid for _s, eid in scored]


def _load_done(marker_path: Path | None) -> set[str]:
    if marker_path and marker_path.exists():
        return set(marker_path.read_text().split())
    return set()


def _mark_done(marker_path: Path | None, eid: str) -> None:
    if marker_path:
        with marker_path.open("a") as fh:
            fh.write(eid + "\n")


def _commit_entity(memory_path: Path, eid: str, r: dict, settings) -> None:
    """Commit a single rewritten entity file so it lands as its own
    git-blame-able commit, authored by the consolidation model.

    Degrades gracefully (logs and returns) when ``memory_path`` isn't a git
    repo, or on any git failure — a commit failure must never abort the batch
    since the rewrite already succeeded on disk.
    """
    if not (memory_path / ".git").exists():
        return
    author = "unknown"
    if settings is not None and hasattr(settings, "effective_consolidation_model"):
        author = settings.effective_consolidation_model
    subject = f"entities/{eid}.md: source-grounded reconsolidation"
    body_lines = [
        f"entities/{eid}.md: rewritten (trigger: sleep/reconsolidation, "
        f"before_words: {r.get('before_words', 0)}, after_words: {r.get('after_words', 0)})"
    ]
    message = git_service.build_commit_message(subject, body_lines, authors=[author])
    rel_path = f"entities/{eid}.md"
    try:
        subprocess.run(
            ["git", "-C", str(memory_path), "add", "--", rel_path],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "-C", str(memory_path), "commit", "-m", message],
            check=True, capture_output=True, text=True,
        )
    except Exception as exc:
        logger.warning("run_source_reconsolidation: commit failed for %s: %s", eid, exc)


def run_batch(memory_path: Path, settings, *, limit=None, corpus_path=None,
              rewrite_fn=None, marker_path=None, commit: bool = True) -> dict:
    if rewrite_fn is None:  # pragma: no cover - runtime
        from api.services.source_rewrite import rewrite_entity_from_sources as rewrite_fn
    done = _load_done(marker_path)
    order = [e for e in ordered_entities(memory_path) if e not in done]
    if limit is not None:
        order = order[:limit]
    rewritten = skipped = wb = wa = 0
    for eid in order:
        try:
            r = rewrite_fn(memory_path, eid, settings, corpus_path=corpus_path)
        except Exception:
            skipped += 1
            continue
        if r.get("changed"):
            rewritten += 1
            wb += r.get("before_words", 0)
            wa += r.get("after_words", 0)
            if commit:
                _commit_entity(memory_path, eid, r, settings)
        else:
            skipped += 1
        _mark_done(marker_path, eid)
    return {"rewritten": rewritten, "skipped": skipped,
            "words_before": wb, "words_after": wa}


def main(argv=None):  # pragma: no cover
    import argparse
    from api.config import get_settings
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", required=True)
    ap.add_argument("--corpus", default="cicada-data")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="print planned order + count, spend nothing")
    args = ap.parse_args(argv)
    mp = Path(args.memory)
    order = ordered_entities(mp)
    print(f"{len(order)} entities; first 10: {order[:10]}")
    if args.dry_run:
        return
    out = run_batch(mp, get_settings(), limit=args.limit,
                    corpus_path=Path(args.corpus) if args.corpus else None,
                    marker_path=mp / ".reconsolidation_done")
    print(out)


if __name__ == "__main__":  # pragma: no cover
    main()
