"""Full-graph dedup sweep (G21): embedding-gate same-type pairs, LLM same/
different/unsure judge with both pages, auto-merge high-confidence, nudge the
uncertain. Runs on a duplicate bank; never on the live bank in tests.

A real (not dry) sweep is one transaction per merge (G183(e)), never spanning
the judge's model call: under the page lock and the bank's git write lock it
computes the merge's footprint before any write, refuses a merge whose
footprint is dirty or cannot be put back exactly, commits only the merge's own
changed paths (``cicada``), and puts a failed merge's footprint back as it was
found; one that cannot be put back stops the sweep (``recovery_failed``).
``may_write`` is asked before every judge call and again once the merge holds
the bank's write admission (G183), which it keeps through its commit: once
Sleep's write window opens, the sweep stops (``stopped_for_sleep``), and a
window never opens mid-merge."""
from __future__ import annotations
import logging
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable
from api.services import (entity_merge, git_service, markdown_parser, merge_rejections, page_lock, telemetry,
                          write_admission)
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
    skipped_dirty, skipped_unsafe, failed = [], [], []
    recovery_failed = False
    for a, b in pairs:
        if stopped_for_sleep or (may_write is not None and not may_write()):
            stopped_for_sleep = True   # no judge call spent while Sleep holds the pages, a dry run's either
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
                else:
                    applied = _merge_and_commit(memory_path, loser, winner, engine, may_write)
                    if applied == STOPPED:
                        # Sleep's write window opened while the judge answered or
                        # while the merge waited for the page lock.
                        stopped_for_sleep = True
                    elif applied == MERGED:
                        merged.append((loser, winner))
                        gone.add(loser)
                    elif applied == DIRTY:
                        skipped_dirty.append((loser, winner))
                    elif applied == UNSAFE:
                        skipped_unsafe.append((loser, winner))
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
        except RecoveryFailed as exc:
            # The bank is not as the merge found it: no further merge on top of that.
            logger.error("dedup_sweep: a failed merge could not be put back (%s); sweep stopped", exc)
            failed.append((b if winner == a else a, winner))
            recovery_failed = True
            break
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
        "skipped_unsafe": skipped_unsafe,
        "failed": failed,
        "recovery_failed": recovery_failed,
    }


def commit_message(paths: list[str], loser: str, today: date, engine: str | None = None) -> str:
    """``Dedup sweep <date>``, one manifest line per path the merge wrote or
    removed, ``Cicada-Author: cicada``, and the judge's engine when known."""
    removed = f"entities/{loser}.md"
    lines = [f"{rel}: removed (merged, trigger: {TRIGGER})" if rel == removed
             else f"{rel}: updated (trigger: {TRIGGER})" for rel in dict.fromkeys(paths)]
    return git_service.build_commit_message(f"Dedup sweep {today.isoformat()}", lines,
                                            authors=[AUTHOR], engine=engine)


MERGED, DIRTY, UNSAFE, FAILED, STOPPED = "merged", "dirty", "unsafe", "failed", "stopped"


class RecoveryFailed(Exception):
    """A failed merge could not be put back as it was: the sweep stops and says so."""


@dataclass(frozen=True)
class _Found:
    """One footprint path as the transaction found it."""
    data: bytes | None              # None: the file is absent
    mode: int | None                # its permission bits
    index: tuple[str, str] | None   # its stage-0 (mode, blob); None: not in the index


def _merge_and_commit(memory_path: Path, loser: str, winner: str, engine: str | None,
                      may_write: Callable[[], bool] | None = None) -> str:
    """One merge as one transaction: the page lock, then the bank's git write
    lock, held from the footprint check through the commit or the recovery (page
    → git order), so no in-process git writer — Sleep's ``git add -A`` included —
    can commit a half-done or failed merge in between.

    Its footprint (:func:`entity_merge.merge_footprint`: winner, loser, the graph
    when an edge names the loser, each page naming the loser — the same matcher
    the merge repoints with) is known BEFORE any write, and the merge is refused
    without writing anything when a footprint path is unsafe to put back
    (``UNSAFE``: unmerged index stages, a symlink, not a regular file) or dirty
    (``DIRTY``: someone else's uncommitted edit, which a ``cicada`` commit must
    never carry). Only the footprint is snapshotted (bytes, permission bits,
    stage-0 index entry or absence); only the merge's own written paths whose
    bytes changed are committed; a recovery restores only footprint paths, so a
    write elsewhere in the bank is neither committed nor erased. A merge that
    wrote outside its footprint, a failed put-back, or a HEAD that moved inside
    the transaction raises :class:`RecoveryFailed`.

    The whole transaction holds the bank's write admission (G183), taken first
    (admission → page → git): ``may_write`` is asked once it is held
    (``STOPPED``), and a Sleep window cannot open until the merge has committed
    or been put back — Sleep sets its flag and then waits for this hold."""
    memory_path = Path(memory_path)
    with write_admission.shared(memory_path):
        if may_write is not None and not may_write():
            return STOPPED
        with page_lock.page_lock(memory_path):
            if not (memory_path / ".git").exists():
                merge_entities(memory_path, loser_id=loser, winner_id=winner)
                return MERGED
            with git_service.write_lock(memory_path):
                return _merge_transaction(memory_path, loser, winner, engine)


def _merge_transaction(memory_path: Path, loser: str, winner: str, engine: str | None) -> str:
    footprint = entity_merge.merge_footprint(memory_path, loser, winner)
    index = _index_entries(memory_path, footprint)
    if _unsafe(memory_path, footprint, index):
        return UNSAFE
    if git_service.dirty_paths_sync(memory_path, *footprint):
        return DIRTY
    found = {rel: _found(memory_path / rel, index.get(rel, [])) for rel in footprint}
    head = _head(memory_path)
    try:
        written = list(dict.fromkeys(
            merge_entities(memory_path, loser_id=loser, winner_id=winner).get("paths") or []))
        outside = [rel for rel in written if rel not in found]
        if outside:
            _recover(memory_path, found, head)
            raise RecoveryFailed(f"the merge wrote {len(outside)} path(s) outside its footprint")
        changed = [rel for rel in written if _read(memory_path / rel) != found[rel].data]
        git_service.commit_paths_sync(memory_path, commit_message(changed, loser, date.today(), engine), changed)
        return MERGED
    except RecoveryFailed:
        raise
    except Exception as exc:  # noqa: BLE001 — logged by class; the footprint is put back below
        logger.warning("dedup_sweep: merge failed (%s); putting its pages back", type(exc).__name__)
    _recover(memory_path, found, head)
    return FAILED


def _unsafe(memory_path: Path, footprint: list[str], index: dict[str, list[tuple[str, str, str]]]) -> bool:
    """A path the transaction could not put back exactly: an unmerged index entry
    (any stage but 0), a symlink, or anything but a regular file."""
    for rel in footprint:
        if any(stage != "0" for _mode, _blob, stage in index.get(rel, [])):
            return True
        path = memory_path / rel
        if os.path.islink(path):
            return True
        if os.path.lexists(path) and not stat.S_ISREG(os.lstat(path).st_mode):
            return True
    return False


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _found(path: Path, entries: list[tuple[str, str, str]]) -> _Found:
    stage0 = next(((mode, blob) for mode, blob, stage in entries if stage == "0"), None)
    if not path.is_file():
        return _Found(None, None, stage0)
    return _Found(path.read_bytes(), stat.S_IMODE(path.stat().st_mode), stage0)


def _recover(memory_path: Path, found: dict[str, _Found], head: str) -> None:
    """Each footprint path gets the bytes, permission bits and stage-0 index
    entry (or absence) it was found with; nothing outside the footprint is read
    or written. HEAD must be where the transaction found it: a moved HEAD means
    something committed inside it, and putting files back then could undo that —
    so it is reported instead."""
    try:
        if _head(memory_path) != head:
            raise RecoveryFailed("HEAD moved inside a failed merge")
        now_index = _index_entries(memory_path, list(found))
        for rel, was in found.items():
            path = memory_path / rel
            if _read(path) != was.data or (was.data is not None and stat.S_IMODE(path.stat().st_mode) != was.mode):
                _put_back(path, was)
            now = next(((m, b) for m, b, stage in now_index.get(rel, []) if stage == "0"), None)
            if now == was.index:
                continue
            if was.index is not None:
                git_service._git_sync(memory_path, "update-index", "--add", "--cacheinfo",
                                      f"{was.index[0]},{was.index[1]},{rel}")
            else:
                git_service._git_sync(memory_path, "update-index", "--force-remove", "--", rel)
    except RecoveryFailed:
        raise
    except Exception as exc:  # noqa: BLE001 — any failure here leaves the tree unknown
        raise RecoveryFailed(type(exc).__name__) from exc


def _head(memory_path: Path) -> str:
    try:
        return git_service._git_sync(memory_path, "rev-parse", "--verify", "-q", "HEAD^{commit}").strip()
    except git_service.GitError:
        return ""   # an unborn branch


def _index_entries(memory_path: Path, paths: list[str]) -> dict[str, list[tuple[str, str, str]]]:
    """``path -> [(mode, blob, stage), …]`` — every index entry of ``paths``, conflict stages included."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    if not paths:
        return out
    listing = git_service._git_sync(memory_path, "ls-files", "-s", "-z", "--", *paths)
    for record in listing.split("\0"):
        if not record or "\t" not in record:
            continue
        meta, rel = record.split("\t", 1)
        mode, blob, stage = meta.split()
        out.setdefault(rel, []).append((mode, blob, stage))
    return out


def _put_back(path: Path, was: _Found) -> None:
    """Restore one regular file's bytes and permission bits, atomically (``None``: remove it)."""
    if was.data is None:
        path.unlink(missing_ok=True)
        return
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".restore")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(was.data)
        os.chmod(tmp, was.mode if was.mode is not None else 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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
