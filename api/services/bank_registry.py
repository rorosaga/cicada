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

import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from api.services.id_utils import sanitize_id

REGISTRY_FILENAME = "banks.yaml"
BANKS_SUBDIR = "banks"
DEFAULT_BANK = "default"

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

    predicates_path = path / "_predicates.yaml"
    if not predicates_path.exists():
        predicates_path.write_text("{}\n", encoding="utf-8")
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
    """Point ``active`` at ``name``. Raises ``ValueError`` if unknown."""
    root = Path(root)
    registry = _ensure_registry(root)
    if name not in (registry.get("banks", {}) or {}):
        raise ValueError(f"Unknown bank '{name}'")
    registry["active"] = name
    save_registry(root, registry)


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
    _ignore = shutil.ignore_patterns(".git", BANKS_SUBDIR, REGISTRY_FILENAME)
    for child in src.iterdir():
        if child.name in (".git", BANKS_SUBDIR, REGISTRY_FILENAME):
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
