"""Memory-bank registry: name -> on-disk memory dir, plus an active pointer.

A *memory bank* is one self-contained Cicada memory directory (its own
``entities/``, ``episodes/``, ``.git``, ``vector_index.db``, …). Banks let a
user keep separate knowledge graphs — e.g. one seeded from a Claude export and
one fresh — and switch between them without restarting the backend.

Design (see ``docs/goals/m5-prep/m6m7-banks-import-design.md``):

- The user's existing live memory dir at ``<memory_root>`` is the synthetic
  ``default`` bank, registered **in place** (``legacy: true``) — no bytes move.
- New banks live under ``<memory_root>/banks/<slug>/``, each self-contained.
- A single registry file ``<memory_root>/banks.yaml`` records every bank plus
  the ``active`` pointer.
- ``Settings.memory_path`` is a *computed property* that calls
  :func:`resolve_active_bank_path` on every access, so a bank switch (which
  mutates ``banks.yaml``, not the cached ``Settings`` object) takes effect with
  no restart.

**Legacy fallback (critical):** if ``banks.yaml`` is missing, or the active
bank is the legacy ``default``, :func:`resolve_active_bank_path` returns the
root unchanged. So an install (or a test tmp dir) with no banks structure
behaves *exactly* as before banks existed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from api.services import demo_guard, predicates
from api.services.id_utils import sanitize_id

REGISTRY_FILENAME = "banks.yaml"
BANKS_SUBDIR = "banks"
DEFAULT_BANK = "default"
#: Deleted banks wait here, under the root, until someone empties it by hand
#: (G139 R-O19). Never versioned, never exported, never copied.
TRASH_DIRNAME = ".trash"

# Standard memory subdirectories scaffolded for every bank. Mirrors the set
# created by ``main.py`` lifespan so a fresh bank is immediately usable.
SCAFFOLD_SUBDIRS = (
    "entities",
    "nudges",
    "clarifications",
    "inbox",
    "episodes",
    "hubs",
    "sources",
    "candidates",
    "_procedures",
)

# Derived artifacts that live INSIDE a bank dir but are not memory: rebuildable
# from the markdown, so they are never versioned and never copied by a bank
# operation. The rule (G99): markdown+git is the only source of truth; a `.db`
# may exist only if deleting it costs CPU time and never a fact.
#
# This is not hygiene — it is a size bomb. `git_service.commit_changes` stages
# with `git add -A`, and `vector_index._rebuild_table` DROPs and rebuilds, so a
# tracked index means every Sleep cycle commits the whole file again (~30 MB on
# the live bank, ~11 GB/yr nightly). It also made `duplicate_bank` copy 30 MB
# into commit #1 of every new bank.
DERIVED_ARTIFACTS = (
    "vector_index.db",
    "vector_index.db-wal",
    "vector_index.db-shm",
    # G136: the FTS5 lexical index (`search_index.py`) — same rule, same
    # directory, same reason.
    "search_index.db",
    "search_index.db-wal",
    "search_index.db-shm",
)

_EXCLUDE_HEADER = "# Cicada: derived, rebuildable artifacts - never versioned (G99, G136)"

_BANK_GITIGNORE = "\n".join(
    (
        "# Derived, rebuildable from the markdown — never versioned (G99).",
        *DERIVED_ARTIFACTS,
        "",
    )
)


def _git_dir(path: Path) -> Path | None:
    """The directory git reads this bank's ``info/exclude`` from, or None.

    Usually ``<bank>/.git``. A bank checked out as a git worktree or a
    submodule has a ``.git`` FILE (``gitdir: <path>``) instead, and a
    worktree shares ``info/exclude`` through its common dir
    (``<gitdir>/commondir``). Missing that would leave the index unprotected
    in exactly the layouts nobody tests (G136 R2; portability).
    """
    dot = Path(path) / ".git"
    if dot.is_dir():
        return dot
    # ``surrogateescape`` + ``UnicodeError``: a path git wrote is bytes, not
    # necessarily UTF-8, and a decode error is a ValueError that an
    # OSError-only guard let escape into ``scaffold_bank`` — the lifespan's
    # unguarded call — so one odd byte kept the backend from booting
    # (S-back final review). surrogateescape round-trips through
    # ``os.fsencode``, so the resolved path is still the real one.
    try:
        head = dot.read_text(encoding="utf-8", errors="surrogateescape").strip() if dot.is_file() else ""
        if not head.startswith("gitdir:"):
            return None
        git_dir = (dot.parent / head[len("gitdir:"):].strip()).resolve()
        common = git_dir / "commondir"
        if common.is_file():
            git_dir = (git_dir / common.read_text(encoding="utf-8", errors="surrogateescape").strip()).resolve()
    except (OSError, UnicodeError, ValueError):
        return None
    return git_dir if git_dir.is_dir() else None


def git_dir(path: Path) -> Path | None:
    """This checkout's OWN git dir, or None: ``<bank>/.git``, or the ``gitdir:``
    target of a worktree's or submodule's ``.git`` file — never the common dir
    :func:`_git_dir` follows for ``info/exclude``. The pending-commit ledger
    (F2-back R-B5) is per checkout: two worktree banks share one common dir,
    and one bank's kept paths must never be committed by the other's writer.
    It lives in a git dir for the reason ``info/exclude`` does (G136 R2): a
    file in the tree is swept into the next ``git add -A`` commit under the
    wrong author."""
    dot = Path(path) / ".git"
    if dot.is_dir():
        return dot
    # Same decoding guard as `_git_dir` (S-back final review): git writes bytes.
    try:
        head = dot.read_text(encoding="utf-8", errors="surrogateescape").strip() if dot.is_file() else ""
        if not head.startswith("gitdir:"):
            return None
        own = (dot.parent / head[len("gitdir:"):].strip()).resolve()
    except (OSError, UnicodeError, ValueError):
        return None
    return own if own.is_dir() else None


def _append_exclude(path: Path, names: tuple[str, ...], header: str) -> bool:
    """Append the missing ``names`` to the repo's ``.git/info/exclude`` under
    ``header`` — never ``.gitignore`` (G136 R2: a tracked file dirtied here is
    swept into the next ``git add -A`` commit under the wrong author).
    Idempotent, never raises; a path with no git directory has nothing to
    protect. Read with ``surrogateescape`` and appended in binary, so an odd
    byte someone typed into the file can never block the exclusion."""
    git_dir = _git_dir(path)
    if git_dir is None:
        return False
    exclude = git_dir / "info" / "exclude"
    try:
        raw = exclude.read_bytes() if exclude.exists() else b""
        have = {line.strip() for line in raw.decode("utf-8", errors="surrogateescape").splitlines()}
        missing = [name for name in names if name not in have]
        if not missing:
            return False
        exclude.parent.mkdir(parents=True, exist_ok=True)
        lead = b"" if not raw or raw.endswith(b"\n") else b"\n"
        with exclude.open("ab") as fh:
            fh.write(lead + "\n".join([header, *missing]).encode("utf-8") + b"\n")
        return True
    except (OSError, UnicodeError, ValueError) as exc:
        logger.warning(f"bank_registry: could not update .git/info/exclude ({exc})")
        return False


def ensure_derived_excluded(path: Path) -> bool:
    """Make git ignore every derived artifact in this bank, via
    ``.git/info/exclude``. Returns True when it had to add a line.

    Why the exclude file and not ``.gitignore`` (G136 R2): the append
    branch in :func:`scaffold_bank` only fires when ``vector_index.db`` is
    missing from ``.gitignore``, so an existing bank would never learn a NEW
    derived name — and teaching it through ``.gitignore`` means dirtying a
    tracked file that the next ``git add -A`` writer sweeps into its own
    commit under the wrong author (the G85-class smear), or that trips the
    Sleep tail's clean-tree guard. ``.git/info/exclude`` is never tracked,
    never dirties the tree, and ``git add -A`` / ``git status`` honour it.
    New banks still get every name in ``.gitignore`` (``_BANK_GITIGNORE``) so
    the rule travels with a copied bank; this covers the ones that exist.

    Idempotent, cheap (one small read), never raises; a bank with no git
    directory has nothing to protect.

    The file is hand-editable and git reads it as bytes, so it is read with
    ``surrogateescape`` and appended in binary: a Latin-1 byte someone typed
    into it used to raise ``UnicodeDecodeError`` (a ValueError, past the
    OSError guard) out of ``scaffold_bank`` — failing boot, ``POST /banks``
    and every index build on that bank (S-back final review). Now an odd byte
    can never block the exclusion, and the bytes already there are untouched.
    """
    return _append_exclude(path, DERIVED_ARTIFACTS, _EXCLUDE_HEADER)


# --- Resolution (the load-bearing path) ------------------------------------


def registry_path(root: Path) -> Path:
    return Path(root) / REGISTRY_FILENAME


def resolve_active_bank_path(root: Path) -> Path:
    """Return the on-disk dir for the active bank.

    Legacy fallback: missing registry, or an active bank that is legacy /
    unknown, resolves to ``root`` unchanged. This keeps every pre-banks install
    and every test tmp dir behaving exactly as before.
    """
    root = Path(root)
    reg_file = registry_path(root)
    if not reg_file.exists():
        return root

    try:
        registry = _read_registry_file(reg_file)
    except Exception:
        # A corrupt registry must never break path resolution — degrade to
        # legacy behavior rather than crash every request.
        return root

    active = registry.get("active")
    banks = registry.get("banks", {}) or {}
    record = banks.get(active)
    if not record:
        # Unknown / dangling active pointer degrades gracefully to the root.
        return root
    if record.get("legacy"):
        return root
    return root / BANKS_SUBDIR / active


def bank_dir(root: Path, name: str) -> Path:
    """Resolve a *named* bank's dir (legacy default -> root, else banks/<name>)."""
    root = Path(root)
    reg_file = registry_path(root)
    if reg_file.exists():
        try:
            registry = _read_registry_file(reg_file)
            record = (registry.get("banks", {}) or {}).get(name)
            if record and record.get("legacy"):
                return root
        except Exception:
            pass
    if name == DEFAULT_BANK:
        # No registry yet, or default not explicitly recorded: default is the
        # legacy in-place dir.
        return root
    return root / BANKS_SUBDIR / name


# --- Registry I/O ----------------------------------------------------------


def _read_registry_file(reg_file: Path) -> dict[str, Any]:
    data = yaml.safe_load(reg_file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    data.setdefault("banks", {})
    return data


def load_registry(root: Path) -> dict[str, Any]:
    """Load the registry, synthesizing the legacy default bank if absent.

    Always returns a dict with ``active`` (str) and ``banks`` (dict). When no
    ``banks.yaml`` exists yet, the returned registry describes a single legacy
    ``default`` bank pointing at ``root`` in place — but nothing is written to
    disk (resolution stays pure until a mutation forces a write).
    """
    root = Path(root)
    reg_file = registry_path(root)
    if reg_file.exists():
        registry = _read_registry_file(reg_file)
        if registry.get("active") and registry.get("banks"):
            return registry
    # Synthesize the legacy default.
    return {
        "active": DEFAULT_BANK,
        "banks": {
            DEFAULT_BANK: {
                "legacy": True,
                "created": date.today().isoformat(),
                "description": "Primary memory",
            }
        },
    }


def save_registry(root: Path, registry: dict[str, Any]) -> None:
    reg_file = registry_path(Path(root))
    reg_file.parent.mkdir(parents=True, exist_ok=True)
    reg_file.write_text(
        yaml.dump(registry, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _ensure_registry(root: Path) -> dict[str, Any]:
    """Load the registry, persisting the synthesized legacy default if it was
    missing, so subsequent mutations have a concrete file to extend."""
    root = Path(root)
    reg_file = registry_path(root)
    registry = load_registry(root)
    if not reg_file.exists():
        save_registry(root, registry)
    return registry


# --- Scaffolding -----------------------------------------------------------


def scaffold_bank(path: Path, *, git_init: bool = True) -> None:
    """Create the standard memory subdir structure + seed files at ``path``.

    Idempotent. Mirrors ``main.py`` lifespan so a bank dir is immediately a
    valid memory root. Optionally ``git init``s the dir (each bank is its own
    git repo for independent provenance/history).
    """
    path = Path(path)
    for subdir in SCAFFOLD_SUBDIRS:
        (path / subdir).mkdir(parents=True, exist_ok=True)

    gitignore_path = path / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(_BANK_GITIGNORE, encoding="utf-8")
    elif not any(
        line.strip() == DERIVED_ARTIFACTS[0]
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
    ):
        # Existing bank predating this rule: append rather than clobber a
        # user-authored ignore file.
        with gitignore_path.open("a", encoding="utf-8") as fh:
            fh.write("\n" + _BANK_GITIGNORE)

    # Wave-1 1.3: seed the real predicate map (canonical/synonyms/cardinality)
    # rather than a bare `{}` placeholder — an unpopulated map left every
    # predicate to fall through the cardinality oracle's conservative
    # "unseen => coexist" default, silently disabling conflict detection for
    # a brand-new bank until Sleep happened to install the seed itself.
    predicates.install_predicate_map(path)
    preferences_path = path / "_preferences.md"
    if not preferences_path.exists():
        preferences_path.write_text(
            "# Preferences\n\n<!-- Always-injected behavioral block. "
            "Human-authored; never overwritten by Sleep. -->\n",
            encoding="utf-8",
        )

    if git_init and not (path / ".git").exists():
        try:
            subprocess.run(
                ["git", "init"],
                cwd=str(path),
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # git absent / failing must not block bank creation; provenance
            # features simply degrade.
            pass

    # G136: every derived name is excluded even in a bank whose .gitignore
    # predates it (see ensure_derived_excluded for why not .gitignore).
    ensure_derived_excluded(path)


# --- Counts ----------------------------------------------------------------


def _count(path: Path, subdir: str) -> int:
    d = Path(path) / subdir
    if not d.is_dir():
        return 0
    return sum(1 for _ in d.glob("*.md"))


# --- Lifecycle (create / list / activate / duplicate) ----------------------


def list_banks(root: Path) -> dict[str, Any]:
    """Return ``{"banks": [ {name, active, entityCount, episodeCount,
    createdAt, description} ], "active": <name>}`` (snake-cased keys; the
    router maps to the wire schema)."""
    root = Path(root)
    registry = load_registry(root)
    active = registry.get("active", DEFAULT_BANK)
    banks: list[dict[str, Any]] = []
    for name, record in (registry.get("banks", {}) or {}).items():
        path = bank_dir(root, name)
        banks.append(
            {
                "name": name,
                "active": name == active,
                "entity_count": _count(path, "entities"),
                "episode_count": _count(path, "episodes"),
                "created_at": str(record.get("created", "")),
                "description": record.get("description", "") or "",
                # G139 R-O18: the bank that IS the memory folder — never
                # offered for deletion (trash_bank refuses it too).
                "legacy": bool(record.get("legacy")),
            }
        )
    return {"banks": banks, "active": active}


def create_bank(root: Path, name: str, description: str = "") -> str:
    """Create a NEW EMPTY bank under ``<root>/banks/<slug>``. Returns the slug.

    Raises ``ValueError`` if the name slugs to an existing bank (or to the
    reserved legacy default).
    """
    root = Path(root)
    slug = sanitize_id(name)
    registry = _ensure_registry(root)
    banks = registry.setdefault("banks", {})
    if slug in banks:
        raise ValueError(f"Bank '{slug}' already exists")

    path = root / BANKS_SUBDIR / slug
    if path.exists():
        raise ValueError(f"Bank directory '{slug}' already exists on disk")
    scaffold_bank(path)

    banks[slug] = {
        "legacy": False,
        "created": date.today().isoformat(),
        "description": description or "",
    }
    save_registry(root, registry)
    return slug


def activate_bank(root: Path, name: str) -> None:
    """Point ``active`` at ``name``. Raises ``ValueError`` if unknown.

    Stamps ``last_active_at`` (aware UTC) on the bank being LEFT (G141
    capture-side track, R-CS11): the one record of which real bank was open
    most recently, which is where the Stop hook saves a session while the demo
    bank is open (:func:`capture_bank`). Re-activating the active bank stamps
    nothing; ``list_banks`` never reads the key, so ``/banks`` is unchanged.
    """
    root = Path(root)
    registry = _ensure_registry(root)
    banks = registry.get("banks", {}) or {}
    if name not in banks:
        raise ValueError(f"Unknown bank '{name}'")
    previous = registry.get("active")
    if previous and previous != name and isinstance(banks.get(previous), dict):
        banks[previous]["last_active_at"] = datetime.now(timezone.utc).isoformat()
    registry["active"] = name
    save_registry(root, registry)


def most_recent_real_bank(root: Path) -> str | None:
    """The real bank a capture falls back to while a demo bank is active (R-CS11).

    Among the registered banks that are not active, exist on disk and are not
    demo banks: the one LEFT most recently (``last_active_at``). A registry
    written before the stamp existed has none — then the only real bank is the
    answer when there is exactly one (the common install: the legacy
    ``default`` plus ``demo``), and ``None`` when there are several: Cicada
    never guesses which of two real memories a conversation belongs to.
    """
    root = Path(root)
    registry = load_registry(root)
    active = registry.get("active")
    candidates: list[tuple[str, str]] = []
    for name, record in (registry.get("banks", {}) or {}).items():
        if name == active:
            continue
        path = bank_dir(root, name)
        if not path.is_dir() or demo_guard.is_demo(path):
            continue
        stamp = str(record.get("last_active_at") or "") if isinstance(record, dict) else ""
        candidates.append((stamp, name))
    stamped = [c for c in candidates if c[0]]
    if stamped:
        return max(stamped)[1]
    return candidates[0][1] if len(candidates) == 1 else None


@dataclass(frozen=True)
class CaptureBank:
    """Where an unattended capture writes (R-CS12). ``redirected_from`` names
    the demo bank that was active when the capture was sent elsewhere."""

    name: str
    path: Path
    redirected_from: str | None = None


def capture_bank(root: Path) -> CaptureBank | None:
    """The active bank, unless it is a demo bank — then the real bank left most
    recently, or ``None`` when there is none to choose (R-CS12). Resolved per
    call from ``banks.yaml``, like every bank path (the split-brain rule)."""
    root = Path(root)
    registry = load_registry(root)
    active = str(registry.get("active") or DEFAULT_BANK)
    path = resolve_active_bank_path(root)
    if not demo_guard.is_demo(path):
        return CaptureBank(active, path)
    fallback = most_recent_real_bank(root)
    if fallback is None:
        return None
    return CaptureBank(fallback, bank_dir(root, fallback), redirected_from=active)


def duplicate_bank(root: Path, name: str, new_name: str) -> str:
    """Copy the *named* bank's tree into a new ``banks/<newSlug>`` bank.

    Excludes ``.git`` (a fresh ``git init`` is run in the copy so version
    history does not fork-share) and the top-level ``banks/`` container +
    ``banks.yaml`` (relevant only when the source is the legacy default at the
    root). Returns the new slug.
    """
    root = Path(root)
    registry = _ensure_registry(root)
    banks = registry.setdefault("banks", {})
    if name not in banks:
        raise ValueError(f"Unknown bank '{name}'")

    new_slug = sanitize_id(new_name)
    if new_slug in banks:
        raise ValueError(f"Bank '{new_slug}' already exists")

    src = bank_dir(root, name)
    dst = root / BANKS_SUBDIR / new_slug
    if dst.exists():
        raise ValueError(f"Bank directory '{new_slug}' already exists on disk")
    dst.mkdir(parents=True, exist_ok=True)

    # Copy only memory content. When the source is the legacy default (== root),
    # we must NOT recurse into banks/ or copy banks.yaml.
    # G139 R-O19: nor the trash of deleted banks, which sits in the root too.
    _ignore = shutil.ignore_patterns(
        ".git", BANKS_SUBDIR, REGISTRY_FILENAME, TRASH_DIRNAME, *DERIVED_ARTIFACTS
    )
    for child in src.iterdir():
        if child.name in (".git", BANKS_SUBDIR, REGISTRY_FILENAME, TRASH_DIRNAME):
            continue
        if child.name in DERIVED_ARTIFACTS:
            # Rebuilt on first use; copying it would put a ~30 MB blob in the
            # new bank's first commit (G99).
            continue
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target, ignore=_ignore)
        else:
            shutil.copy2(child, target)

    # Ensure the standard scaffold + a fresh independent git repo exist.
    scaffold_bank(dst)

    banks[new_slug] = {
        "legacy": False,
        "created": date.today().isoformat(),
        "description": f"Copy of {name}",
    }
    save_registry(root, registry)
    return new_slug


def rename_bank(root: Path, name: str, new_name: str) -> str:
    """Rename a bank in the registry, returning the new slug.

    - **Legacy default** (in-place at ``root``): renames the registry KEY only.
      The files stay at ``<root>`` (no relocation) and the renamed bank keeps
      ``legacy: True``, so :func:`resolve_active_bank_path` / :func:`bank_dir`
      still resolve it to the root.
    - **Non-legacy bank**: moves ``banks/<oldSlug>`` -> ``banks/<newSlug>`` on
      disk and rekeys the registry.

    The ``active`` pointer follows the rename when the renamed bank was active.

    Raises ``ValueError`` on an unknown source, a blank new name, or a slug
    collision with an existing bank.
    """
    root = Path(root)
    if not (new_name or "").strip():
        raise ValueError("New bank name is required")

    registry = _ensure_registry(root)
    banks = registry.setdefault("banks", {})
    if name not in banks:
        raise ValueError(f"Unknown bank '{name}'")

    new_slug = sanitize_id(new_name)
    if new_slug == name:
        return new_slug
    if new_slug in banks:
        raise ValueError(f"Bank '{new_slug}' already exists")

    record = banks[name]
    if not record.get("legacy"):
        # Relocate the on-disk dir for a non-legacy bank.
        src = root / BANKS_SUBDIR / name
        dst = root / BANKS_SUBDIR / new_slug
        if dst.exists():
            raise ValueError(f"Bank directory '{new_slug}' already exists on disk")
        if src.exists():
            src.rename(dst)

    # Rekey while preserving insertion order is not required; just re-add.
    banks[new_slug] = banks.pop(name)
    if registry.get("active") == name:
        registry["active"] = new_slug
    save_registry(root, registry)
    return new_slug


# --- Trash + export (G139, R-O18…R-O20) -------------------------------------

#: An export older than this in `$CICADA_HOME/exports` was abandoned mid-download.
_EXPORT_MAX_AGE_S = 3600
_TRASH_EXCLUDE_HEADER = "# Cicada: deleted banks wait here, never versioned (G139)"
#: Never exported from, or copied out of, a legacy root: other banks, the
#: registry, and the trash.
_ROOT_ONLY = frozenset({BANKS_SUBDIR, REGISTRY_FILENAME, TRASH_DIRNAME})


class UnknownBank(ValueError):
    pass


class BankInUse(ValueError):
    pass


class LegacyBankInPlace(ValueError):
    pass


def ensure_trash_excluded(root: Path) -> bool:
    """A legacy root IS a git repo (its bank lives in place), and a trashed
    bank carries its own `.git` — untracked, the next `git add -A` would sweep
    it in as a gitlink. So `.trash/` is excluded before anything moves."""
    return _append_exclude(root, (f"{TRASH_DIRNAME}/",), _TRASH_EXCLUDE_HEADER)


def trash_bank(root: Path, name: str, *, now: datetime | None = None) -> Path:
    """Move a bank to `<root>/.trash/<name>-<UTC>` and drop it from the registry.

    Reversible by hand — nothing is erased (spec decision 17). Refuses the
    active bank (the backend is reading it) and a legacy bank (it IS the
    memory folder; moving it would move every other bank with it)."""
    root = Path(root)
    registry = _ensure_registry(root)
    banks = registry.setdefault("banks", {})
    if name not in banks:
        raise UnknownBank(f"Unknown bank '{name}'")
    # Legacy first: the default bank is usually also the active one, and "it IS
    # the memory folder" is the reason that stays true after a switch.
    if (banks[name] or {}).get("legacy"):
        raise LegacyBankInPlace(name)
    if registry.get("active") == name:
        raise BankInUse(name)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    dst = root / TRASH_DIRNAME / f"{name}-{stamp}"
    src = root / BANKS_SUBDIR / name
    ensure_trash_excluded(root)
    if src.exists():
        if dst.exists():
            raise ValueError(f"{dst.name} is already in the trash")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)   # same filesystem: both live under the root
    del banks[name]
    save_registry(root, registry)
    return dst


def export_zip(root: Path, name: str, dest_dir: Path, *, now: datetime | None = None) -> Path:
    """Zip one bank's pages and full history into `dest_dir` (inside
    `$CICADA_HOME`; the caller streams and deletes it, R-O20).

    The archive's top folder is the bank's name. Derived files are rebuilt on
    first use and never travel (G99); a legacy root's other banks, registry and
    trash are not this bank; symlinks are never followed, so nothing outside
    the bank can ride along."""
    root = Path(root)
    if name not in (load_registry(root).get("banks") or {}):
        raise UnknownBank(f"Unknown bank '{name}'")
    src = bank_dir(root, name)
    in_place = src.resolve() == root.resolve()
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    dest_dir.mkdir(parents=True, exist_ok=True)
    # A download the app abandoned mid-stream never reached the response's
    # cleanup, and every archive is a full copy of a bank: sweep any left over
    # from more than an hour ago before writing a new one.
    cutoff = time.time() - _EXPORT_MAX_AGE_S
    for stale in dest_dir.glob("cicada-*.zip"):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass
    dest = dest_dir / f"cicada-{name}-{stamp}.zip"
    # Two exports of one bank in the same second: the second must not
    # truncate the archive the first is still streaming.
    n = 2
    while dest.exists():
        dest = dest_dir / f"cicada-{name}-{stamp}-{n}.zip"
        n += 1
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            here = Path(dirpath)
            rel = here.relative_to(src)
            at_top = rel == Path(".")
            dirnames[:] = [
                d for d in dirnames
                if not (here / d).is_symlink() and not (at_top and (d == TRASH_DIRNAME or (in_place and d in _ROOT_ONLY)))
            ]
            for fn in filenames:
                full = here / fn
                if full.is_symlink():
                    continue
                if at_top and (fn in DERIVED_ARTIFACTS or (in_place and fn in _ROOT_ONLY)):
                    continue
                zf.write(full, arcname=str(Path(name) / rel / fn))
    return dest
