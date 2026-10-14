"""The site-explore skill Cicada ships (G166 exploring): pinned and hash-verified like every catalog skill (G138).

``skills/site-explore/`` holds ``SKILL.md`` and ``explore_capture.py`` — the scripted capture the person's agent runs
inside ``browser-harness`` for each site it leases. Cicada never runs it: the person's agent does, in the person's
browser, with the standing of any reviewed catalog skill (an instruction, never authority; ruling 14).

Its catalog entry (``api/data/recommended_skills.json``, id ``site-explore``) pins the reviewed commit and the sha256
of every file. :func:`verified` recomputes them on this Mac before a claim names the script, so an edited or swapped
copy is never handed to an agent as Cicada's: the claim refuses with a sentence instead. A test holds the pins to the
files, so changing the script without re-pinning it fails the suite (the review gate).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from api.services import skill_catalog

SKILL_ID = "site-explore"
SCRIPT = "explore_capture.py"


def skill_dir() -> Path:
    """The skill as this install carries it: the repo's (or the release bundle's) ``skills/site-explore``."""
    return Path(__file__).resolve().parents[2] / "skills" / SKILL_ID


def script_path() -> Path:
    return skill_dir() / SCRIPT


def pins(catalog: dict | None = None) -> dict[str, str]:
    """``{file name: sha256}`` from the catalog entry's pin: ``SKILL.md`` plus every ``files`` entry."""
    catalog = catalog or skill_catalog.load()
    entry = next((e for e in catalog.get("skills") or [] if e.get("id") == SKILL_ID), None)
    pin = (entry or {}).get("pin") or {}
    out = {"SKILL.md": str(pin.get("skillMdSha256") or "")}
    out.update({str(k): str(v) for k, v in (pin.get("files") or {}).items()})
    return out


def sha256_of(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def verified(catalog: dict | None = None) -> tuple[bool, str]:
    """``(True, "")`` when every pinned file on this Mac matches its reviewed hash; else ``(False, why)``."""
    wanted = pins(catalog)
    if not wanted.get("SKILL.md") or SCRIPT not in wanted:
        return False, "the site-explore skill has no reviewed pin in this install"
    for name, sha in wanted.items():
        got = sha256_of(skill_dir() / name)
        if got is None:
            return False, f"the site-explore skill's {name} is missing from this install"
        if got != sha:
            return False, f"the site-explore skill's {name} on this Mac does not match the reviewed version"
    return True, ""
