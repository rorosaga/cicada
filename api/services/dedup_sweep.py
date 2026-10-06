"""Full-graph dedup sweep (G21): embedding-gate same-type pairs, LLM same/
different/unsure judge with both pages, auto-merge high-confidence, nudge the
uncertain. Runs on a duplicate bank; never on the live bank in tests.

A real (not dry) sweep is one writer per merge (G183(e)): each merge and its
own path-scoped commit run under the bank's page lock — never across the
judge's model call — authored ``cicada``, so no merged page is left dirty for
the next ``git add -A`` writer to sweep under its author. A merge whose commit
fails is put back from HEAD. ``may_write`` is asked before every merge: once
Sleep's write window opens, the sweep stops merging (``stopped_for_sleep``)."""
from __future__ import annotations
import logging
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable
from api.services import git_service, markdown_parser, merge_rejections, page_lock, telemetry
from api.services.entity_merge import merge_entities

logger = logging.getLogger(__name__)

AUTHOR = "cicada"
TRIGGER = "maintenance/dedup-sweep"


def find_candidate_pairs(memory_path: Path, *, embed_fn=None, min_cosine=0.85):
    """Embedding-gate: same-type entity pairs with high cosine. Best-effort;
    returns [] if the index isn't built. (Seeded runs can skip this.)

    Score direction: ``search_entities`` -> ``SqliteVecIndexer._knn`` computes
    ``score = 1.0 - cosine_distance`` (see api/services/vector_index.py), so
    ``hit["score"]`` is a SIMILARITY where HIGHER means closer. The floor
    below is therefore ``score >= min_cosine``.
    """
    from api.services.vector_index import SqliteVecIndexer
    idx = SqliteVecIndexer(memory_path, embed_fn=embed_fn)
    ents = memory_path / "entities"
    pairs, seen = [], set()
    for f in sorted(ents.glob("*.md")):
        par = markdown_parser.parse(f)
        name = str(par.frontmatter.get("name", f.stem))
        own_type = par.frontmatter.get("type")
        for hit in idx.search_entities(name, top_k=4):
            meta = hit.get("metadata", {})
            other = meta.get("entity_id")
            if not other or other == f.stem:
                continue
            score = float(hit.get("score", 0) or 0)
            if score < min_cosine:
                continue  # below the similarity floor
            other_type = meta.get("type")
            if own_type and other_type and own_type != other_type:
                continue  # same-type gate: skip known-differing types
            key = tuple(sorted((f.stem, other)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((key[0], key[1], score))
    return pairs


def dedup_sweep(memory_path: Path, settings, *, judge_fn=None, embed_fn=None,
                seed_pairs=None, auto_merge_threshold=0.9, dry_run=False,
                limit=None, may_write: Callable[[], bool] | None = None,
                engine: str | None = None) -> dict:
    """Run the full-graph dedup sweep.

    ``dry_run`` (G21 maintenance endpoint): when True, a pair the judge calls
    "same" with high enough confidence is reported under ``proposed`` instead
    of actually calling ``merge_entities`` — nothing is written to disk.
    ``limit`` caps how many candidate pairs are considered, bounding judge
    (LLM) calls on a large graph. ``may_write`` (default: always) is asked
    before each merge; ``engine`` is the judge's engine for the commit's
    ``Cicada-Engine`` trailer — resolved from ``settings`` for the default
    judge, omitted for an injected one rather than guessed.
    """
    if judge_fn is None:  # pragma: no cover - resolved at runtime
        judge_fn = _default_judge_fn(settings)
        if engine is None:
            from api.services import engine_select
            engine = engine_select.engine_label(settings)
    pairs = list(seed_pairs or [])
    if not pairs:
        pairs = [(a, b) for (a, b, _score) in find_candidate_pairs(memory_path, embed_fn=embed_fn)]
    if limit is not None:
        pairs = pairs[:limit]

    ents = memory_path / "entities"
    merged, proposed, nudged = [], [], []
    gone: set[str] = set()
    # G113 slice 3b (R5) — a pair the user already told us are NOT duplicates
    # is skipped without ever calling the (paid) judge, mirroring
    # `clarification_manager.create`'s check on the Sleep-time producer side.
    rejected = merge_rejections.load_rejected(memory_path)
    skipped_rejected = 0
    stopped_for_sleep = False
    skipped_dirty, failed = [], []
    for a, b in pairs:
        if stopped_for_sleep or (not dry_run and may_write is not None and not may_write()):
            stopped_for_sleep = True   # no judge call spent on a merge that could not land
            break
        if a in gone or b in gone:
            continue
        if (a, b) in rejected or (b, a) in rejected:
            skipped_rejected += 1
            continue
        ap, bp = ents / f"{a}.md", ents / f"{b}.md"
        if not ap.exists() or not bp.exists():
            continue
        try:
            v = judge_fn(ap.read_text(), bp.read_text(), a, b)
            verdict = v.get("verdict")
            confidence = float(v.get("confidence", 0) or 0)
            winner = v.get("winner")
            applied = "none"
            if (
                verdict == "same"
                and confidence >= auto_merge_threshold
                and winner in (a, b)
            ):
                loser = b if winner == a else a
                if dry_run:
                    proposed.append((loser, winner))
                    applied = "proposed"
                    gone.add(loser)
                elif may_write is not None and not may_write():
                    # Sleep's write window opened while the judge answered: its
                    # batch has loaded the pages this merge would rewrite.
                    stopped_for_sleep = True
                    applied = "stopped"
                else:
                    applied = _merge_and_commit(memory_path, loser, winner, engine)
                    if applied == MERGED:
                        merged.append((loser, winner))
                        gone.add(loser)
                    elif applied == DIRTY:
                        skipped_dirty.append((loser, winner))
                    else:
                        failed.append((loser, winner))
            elif verdict in ("same", "unsure"):
                # Either genuinely uncertain, or "same" with a high enough
                # confidence but a winner that isn't one of the two
                # candidates (hallucinated/mis-cased id) — treat as uncertain
                # rather than guessing which side to keep.
                nudged.append((a, b))
                applied = "nudged"
            # G113 — one ledger row per judged pair, `applied` taken from the
            # branch above (never a second judgement). ``winner`` is recorded
            # only when it names one of the two slugs: the judge is an LLM and a
            # free-text winner is not an id, and ids are all the ledger may hold.
            telemetry.record(telemetry.UsageEvent(
                kind="dedup_verdict", stage="dedup", bank=memory_path.name,
                invocations=0, billing="free",
                refs={
                    "a": a, "b": b, "verdict": verdict, "confidence": confidence,
                    "winner": winner if winner in (a, b) else None, "applied": applied,
                },
            ))
        except Exception as exc:  # noqa: BLE001 - one bad pair must not abort the sweep
            logger.warning("dedup_sweep: skipping pair (%s, %s) after error: %s", a, b, exc)
            continue
    return {
        "merged": merged,
        "proposed": proposed,
        "nudged": nudged,
        "candidate_pairs": len(pairs),
        "skipped_rejected": skipped_rejected,
        "stopped_for_sleep": stopped_for_sleep,
        "skipped_dirty": skipped_dirty,
        "failed": failed,
    }


def commit_message(paths: list[str], loser: str, today: date, engine: str | None = None) -> str:
    """``Dedup sweep <date>``, one manifest line per path the merge wrote or
    removed, ``Cicada-Author: cicada``, and the judge's engine when known."""
    removed = f"entities/{loser}.md"
    lines = [f"{rel}: removed (merged, trigger: {TRIGGER})" if rel == removed
             else f"{rel}: updated (trigger: {TRIGGER})" for rel in dict.fromkeys(paths)]
    return git_service.build_commit_message(f"Dedup sweep {today.isoformat()}", lines,
                                            authors=[AUTHOR], engine=engine)


MERGED, DIRTY, FAILED = "merged", "dirty", "failed"
GRAPH = "graph_edges.yaml"


def _merge_and_commit(memory_path: Path, loser: str, winner: str, engine: str | None) -> str:
    """One merge and its own commit under the page lock (page → git order).

    A merge commits only what is wholly its own (G183(e)): a merge whose winner
    or loser is already dirty is refused before anything is written, and one
    that turns out to change another dirty path (a page that names the loser,
    the graph) is put back byte-for-byte and refused — never committed under
    ``cicada`` with someone else's edit inside. ``DIRTY`` then; the next sweep
    retries once that writer has committed."""
    memory_path = Path(memory_path)
    with page_lock.page_lock(memory_path):
        if not (memory_path / ".git").exists():
            merge_entities(memory_path, loser_id=loser, winner_id=winner)
            return MERGED
        dirty = git_service.dirty_paths_sync(memory_path, "entities", GRAPH)
        if {f"entities/{loser}.md", f"entities/{winner}.md"} & dirty:
            return DIRTY
        snap = _snapshot(memory_path)
        merge_entities(memory_path, loser_id=loser, winner_id=winner)
        changed = _changed(memory_path, snap)
        if set(changed) & dirty:
            _put_back(memory_path, snap, changed)
            return DIRTY
        try:
            git_service.commit_paths_sync(
                memory_path, commit_message(changed, loser, date.today(), engine), changed)
        except Exception as exc:  # noqa: BLE001 — logged by class, the pages are restored
            logger.warning("dedup_sweep: merge commit failed (%s); restoring its pages", type(exc).__name__)
            _restore(memory_path, changed)
            return FAILED
    return MERGED


def _snapshot(memory_path: Path) -> dict[str, bytes | None]:
    """Every byte a merge can change: each page, and the graph (``None``: absent)."""
    snap: dict[str, bytes | None] = {
        f"entities/{p.name}": p.read_bytes() for p in (memory_path / "entities").glob("*.md")}
    graph = memory_path / GRAPH
    snap[GRAPH] = graph.read_bytes() if graph.is_file() else None
    return snap


def _changed(memory_path: Path, snap: dict[str, bytes | None]) -> list[str]:
    """The paths whose bytes differ from ``snap`` now (a page that appeared counts too)."""
    now = _snapshot(memory_path)
    return sorted(rel for rel in set(snap) | set(now) if snap.get(rel) != now.get(rel))


def _put_back(memory_path: Path, snap: dict[str, bytes | None], paths: list[str]) -> None:
    """Restore each path's snapshot bytes, atomically (``None``: remove it)."""
    for rel in paths:
        target = memory_path / rel
        data = snap.get(rel)
        if data is None:
            target.unlink(missing_ok=True)
            continue
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".restore")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _restore(memory_path: Path, paths: list[str]) -> None:
    """Put each path back as HEAD has it (a removed loser comes back too)."""
    for rel in paths:
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "HEAD", "--", rel)
        except git_service.GitError:
            logger.warning("dedup_sweep: could not restore a merged path")


def _default_judge_fn(settings):  # pragma: no cover - needs a real model
    from api.services import json_parse
    from api.services.providers import resolve_llm_fn
    llm = resolve_llm_fn(settings, model=settings.effective_consolidation_model, stage="dedup")

    def judge(a_body, b_body, a_id, b_id):
        prompt = (
            "Are these two knowledge-graph entity pages the SAME real-world thing? "
            "Reply JSON {\"verdict\":\"same|different|unsure\",\"confidence\":0..1,"
            "\"winner\":\"<id to keep>\"}.\n\n"
            f"PAGE A (id={a_id}):\n{a_body[:2500]}\n\nPAGE B (id={b_id}):\n{b_body[:2500]}"
        )
        resp = llm(messages=[{"role": "user", "content": prompt}],
                   response_format={"type": "json_object"})
        txt = resp["choices"][0]["message"]["content"]
        return json_parse.parse_json_object_or(txt, {"verdict": "unsure", "confidence": 0.0})
    return judge
