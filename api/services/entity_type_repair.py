"""Give pages outside the closed type set a type inside it — run by the person, never automatically (2026-10-17).

    api/.venv/bin/python -m api.scripts.repair_entity_types --bank <path>                 # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_entity_types --bank <path> --list          # + each page, this terminal
    api/.venv/bin/python -m api.scripts.repair_entity_types --bank <path> --apply         # one `cicada` commit
    api/.venv/bin/python -m api.scripts.repair_entity_types --bank <path> --apply --as <id>=project

Before ``entity_types`` held Stage 1's output, a plain-JSON engine could write a type the set of 10 does not hold
(``organization``, ``product``, ``program``). Each such page gets the type :func:`entity_types.producible` maps it to
(``organization`` → ``company``, ``product`` → ``tool``, ``program`` → ``project``; a word with no mapping →
``concept``) unless the person names another with ``--as <id>=<type>`` after reading ``--list``. Only ``type``
changes: the body, claims, sources and decay fields stay as they are (every type the repair writes but ``skill``
shares the ``active`` default, and an explicit ``decay_class`` was the writer's, not the type's).

Deterministic, no model, no network. The dry run prints counts and type words only, never a page name or a word of
the bank; ``--list`` prints each page id with its old and new type for the person's own terminal — never paste it into
the repo or a PR. ``--apply`` refuses while Sleep runs or holds the pages, or when the backend cannot be asked; a page
dirty in git (or whose claims ledger is), or written after the survey, is skipped. A second run changes nothing. Order: write admission → page lock → git.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import entity_types, git_service, markdown_parser, page_lock, write_admission

TRIGGER = "maintenance/entity-types"


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: repair nothing."""


class BadOverride(ValueError):
    """An ``--as`` names a page that needs no repair or a type Stage 1 may not produce."""


@dataclass
class Survey:
    """Counts and type words only — never a name, a path or a word of the bank."""

    pages: int = 0
    out_of_set: int = 0
    mapped: dict[str, int] = field(default_factory=dict)   # "organization -> company": n
    fallback: int = 0          # no mapping: became concept (unless overridden)
    overridden: int = 0
    dirty: int = 0
    repaired: int = 0
    committed: bool = False
    _todo: dict[Path, tuple[str, str, str]] = field(default_factory=dict, repr=False)   # path -> (text, old, new)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def listing(self) -> list[dict]:
        """Each page the repair would retype — for the person's own terminal only."""
        return [{"id": p.stem, "from": old, "to": new} for p, (_t, old, new) in sorted(self._todo.items())]


def _type_of(text: str):
    split = markdown_parser.split_frontmatter(text)
    if not split:
        return None
    try:
        fm = markdown_parser.load_yaml(split[0])
    except Exception:
        return None
    return fm.get("type") if isinstance(fm, dict) else None


def _check_overrides(overrides: dict[str, str]) -> dict[str, str]:
    out = {}
    for page, kind in (overrides or {}).items():
        key = str(kind or "").strip().lower()
        if key not in entity_types.PRODUCIBLE:
            raise BadOverride(f"--as {page}={kind}: the type must be one of {', '.join(sorted(entity_types.PRODUCIBLE))}")
        out[str(page).strip()] = key
    return out


def survey(memory_path, *, overrides: dict[str, str] | None = None) -> Survey:
    """What ``apply`` would do, read-only. ``overrides`` maps a page id to the type the person chose for it."""
    memory_path = Path(memory_path)
    chosen = _check_overrides(overrides or {})
    result = Survey()
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "entities")
        except git_service.GitError:
            dirty = frozenset()
    mapped: Counter[str] = Counter()
    needing: set[str] = set()
    for path in sorted((memory_path / "entities").glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        result.pages += 1
        raw = _type_of(text)
        if raw is None or entity_types.known(raw) is not None:
            continue   # no frontmatter type (not a page this repair understands), or already in the set
        result.out_of_set += 1
        needing.add(path.stem)
        old = str(raw).strip()
        if path.stem in chosen:
            new = chosen[path.stem]
            result.overridden += 1
        else:
            new = entity_types.producible(raw)
            if entity_types._key(raw) not in entity_types.SYNONYMS:
                result.fallback += 1
        mapped[f"{old.lower()} -> {new}"] += 1
        if f"entities/{path.name}" in dirty or f"entities/{path.stem}.claims.jsonl" in dirty:
            # The page or its claims ledger holds someone else's uncommitted change: committing it would put that
            # change under this repair's name.
            result.dirty += 1
            continue
        result._todo[path] = (text, old, new)
    if unknown := set(chosen) - needing:
        raise BadOverride(f"--as names {len(unknown)} page(s) that need no type repair")
    result.mapped = dict(sorted(mapped.items()))
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool], overrides: dict[str, str] | None = None) -> Survey:
    """Retype every page the survey found and commit them in ONE commit authored ``cicada``. Raises
    :class:`SleepRunning` before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    written: list[tuple[Path, str]] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; repair after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path, overrides=overrides)
            for path, (surveyed, _old, new) in result._todo.items():
                if path.read_text(encoding="utf-8") != surveyed:   # written since the survey: its writer's to commit
                    result.dirty += 1
                    continue
                parsed = markdown_parser.parse(path)
                markdown_parser.write(path, {**parsed.frontmatter, "type": new}, parsed.body)
                written.append((path, path.read_text(encoding="utf-8")))
            rels = [f"entities/{p.name}" for p, _ in written]
            result.repaired = len(rels)
            if rels and (memory_path / ".git").exists():
                ledgers = [f"entities/{p.stem}.claims.jsonl" for p, _ in written
                           if (p.parent / f"{p.stem}.claims.jsonl").exists()]
                message = git_service.build_commit_message(
                    f"Page types brought into the closed set: {len(rels)} page(s)",
                    [f"{rel}: retyped (trigger: {TRIGGER})" for rel in rels],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, [*rels, *ledgers])
                result.committed = True
    if written:
        logger.info(f"entity type repair: {len(written)} page(s)")
    return result
