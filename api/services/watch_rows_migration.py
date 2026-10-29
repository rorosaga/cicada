"""One-shot, idempotent: move each watched day's rows out of its episode's frontmatter into its own file.

Before 2026-10-29 a watched day carried every video it lists — url, title, channel, every time, every raw instant —
as a ``watched`` list in its frontmatter. Every episode header is read on a cold start and cached for the backend's
life (``bank_index``), so a heavy watcher's years of rows cost every cold start ~1.3 s and their share of the header
cache. ``watch_history`` now keeps them in ``sources/watched/<platform>/<day>.json`` (the shape #528 gave Spotify's
plays) and reads either form, so nothing breaks before this runs; this moves the rest at once.

Scope, exactly: an episode of a watched day (``source: watch-history`` with a ``watched`` list). Its rows go to its
rows file as they are (raw, never re-derived); the episode keeps everything else, the ``watched`` key removed. The
body, ``content_hash`` and ``processed`` are untouched, so nothing re-queues and no span moves. A rows file that
already exists for that day is left as it is (the newer writer's) and only the frontmatter copy goes.

**Never automatic.** A bulk write to the person's bank waits for their OK (standing rule): nothing calls
:func:`move_rows` at start or on a bank switch. The person runs ``cicada maintenance move-watched-rows`` in their
own terminal — a dry run (:func:`survey`: counts and a few day ids) — and then the same with ``--apply``
(``POST /maintenance/watched-rows``; refused from an agent's shell, it acts as the person). Until then every reader
takes either form and every new or updated day already writes its rows file.

Marker-guarded (``.watch_rows_v1``: a second apply is a no-op), admitted (``write_admission``: refused while Sleep
writes), under the stager's lock and the episode lock (the order ``watch_history.record`` takes), committed as
``cicada`` with exactly the paths it wrote. Never raises into its caller.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger

from api.services import (episode_ids, episode_staging, git_service, markdown_parser, watch_history,
                          write_admission)

_MARKER = ".watch_rows_v1"
TRIGGER = "maintenance/watch-rows"
#: How many day ids a dry run names.
SAMPLE = 5


def _legacy(fm) -> bool:
    return (isinstance(fm, dict) and str(fm.get("source") or "") == watch_history.SOURCE
            and isinstance(fm.get("watched"), list) and watch_history._day_key(fm) is not None)


def survey(memory_path) -> dict:
    """What an apply would do, writing nothing: ``{days, rows, rows_files_kept, applied, sample}`` — counts, and the
    first few day ids (``ep_…``, never a title)."""
    from api.services import bank_index

    memory_path = Path(memory_path)
    days = rows = kept = 0
    sample: list[str] = []
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        if not _legacy(fm):
            continue
        days += 1
        rows += len(fm["watched"])
        kept += watch_history.rows_path(memory_path, *watch_history._day_key(fm)).exists()
        if len(sample) < SAMPLE:
            sample.append(f.stem)
    return {"days": days, "rows": rows, "rows_files_kept": kept, "applied": (memory_path / _MARKER).exists(),
            "sample": sample}


def move_rows(memory_path) -> int:
    """Move one bank's watched rows — the person's ``--apply``, never automatic. Returns how many days moved; raises
    ``write_admission.SleepHolding`` while Sleep holds the pages (the route answers 409)."""
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    marker = memory_path / _MARKER
    if marker.exists() or not episodes_dir.is_dir():
        return 0
    try:
        # Lock order: admission, then the commit's write lock, then the episode lock — never a commit inside it.
        with write_admission.admitted(memory_path):
            with episode_staging.STAGE_LOCK, episode_ids.episode_lock(episodes_dir):
                written = _move(memory_path, episodes_dir)
            days = sum(1 for p in written if p.parent == episodes_dir)
            if written:
                try:
                    _commit(memory_path, written)
                except Exception as exc:  # noqa: BLE001
                    # The files are right on disk; the next start finds nothing left to move, writes the marker, and
                    # the moved files ride the bank's next commit (the `export_origin_migration` trade).
                    logger.warning(f"Watched-rows move commit skipped ({type(exc).__name__})")
                    return days
    except write_admission.SleepHolding:
        raise
    except Exception as exc:  # noqa: BLE001 — a migration never fails a start or a bank switch
        logger.error(f"Watched-rows move failed — left as it was ({type(exc).__name__})")
        return 0
    marker.write_text("v1", encoding="utf-8")
    return days


def _move(memory_path: Path, episodes_dir: Path) -> list[Path]:
    written: list[Path] = []
    for path in sorted(episodes_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — an unreadable episode is left for its own reader to report
            continue
        fm = parsed.frontmatter
        if not _legacy(fm):
            continue
        key = watch_history._day_key(fm)
        rows_file = watch_history.rows_path(memory_path, *key)
        if not rows_file.exists():
            watch_history.write_rows(memory_path, key[0], key[1], fm["watched"])
            written.append(rows_file)
        fm = {k: v for k, v in fm.items() if k != "watched"}
        markdown_parser.write(path, fm, parsed.body)
        written.append(path)
    return written


def _commit(memory_path: Path, written: list[Path]) -> None:
    rel = sorted({str(p.relative_to(memory_path)) for p in written})
    days = sum(1 for r in rel if r.startswith("episodes/"))
    message = git_service.build_commit_message(
        f"Move watched rows {date.today().isoformat()}",
        [f"episodes/: {days} watched day(s) keep their rows in sources/watched/ (trigger: {TRIGGER})"],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, rel)
