"""G117 — owner identity: one machine-global file (`~/.cicada/owner.json`)
naming the person, and the one function every claim-writing site resolves
"who is the owner" through.

Two things this module deliberately keeps separate:

* `owner.json` — a machine-global USER CHOICE, same class of file as
  `connections.json` (registry.py's `PREFS_FILE_NAME` pattern: `cicada_home()`,
  0600, plain JSON) — never a bank file, never a secret (name/handle/email
  only; CLAUDE.md's rail).
* the owner ENTITY PAGE — a per-bank `entities/<slug>.md`, created the first
  time `ensure_owner_entity` runs against a given bank, marked `owner: true`
  so `GET /graph` can flag the node (see `graph_builder.py`) and the app can
  render "Name (you)".

`resolve_observer` (R1) is the single function that replaces the hardcoded
literal `"rodrigo"` at every one of the five sites CLAUDE.md's "Open observer
inconsistency" paragraph names (`inbox_service._owner_observer`,
`telegram_capture.py`, `agentic_write.write_claim`'s two checks, and
`mcp/server.py`'s tool schema/handler). ONE resolution, called everywhere,
is what keeps a bank's claim lineage from forking — the exact failure mode
`inbox_service.py`'s pre-existing `TODO(G117)` warns about.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from loguru import logger

from api.config import Settings
from api.services import decay_policy, entity_body, markdown_parser
from api.services.auth import cicada_home
from api.services.id_utils import sanitize_id
from api.models.schemas import DecayClass

OWNER_FILE_NAME = "owner.json"
# R1 rung 4 — a fresh bank (no owner.json, no legacy `rodrigo.md`) resolves
# here: a portable keyword, never a name, never blank. Anything that isn't
# "agent" or "external:*" reads as the owner on the app side (R2), so this
# keyword renders correctly with zero app-side plumbing.
DEFAULT_OBSERVER = "owner"
LEGACY_OBSERVER = "rodrigo"
# What a new bank's owner page is called before anyone has said their name. The
# page id is `sanitize_id(...)` of it — `owner`, the same keyword `resolve_observer`
# returns for a fresh bank, so the observer on the person's first claims and the
# page they land on are one thing from the first cycle.
PLACEHOLDER_NAME = "Owner"
# The one line an auto-created owner page opens with (shown under "Name (you)").
DEFAULT_SUMMARY = "The main person this memory belongs to."
# Frontmatter marker: this owner page was created before the person's name was
# known, so `ensure_owner_entity` adopts it (renames it, keeps its id and its
# claims) instead of writing a second owner page beside it. Dropped on adoption.
PLACEHOLDER_KEY = "owner_placeholder"


def owner_json_path() -> Path:
    return cicada_home() / OWNER_FILE_NAME


def load_owner() -> dict:
    try:
        return json.loads(owner_json_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_owner(data: dict) -> None:
    path = owner_json_path()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def resolve_observer(memory_path: Path | None, settings: Settings | None = None) -> str:
    """R1 — the value every user-stated claim's `observer=` should carry.

    Precedence: an explicit `CICADA_OBSERVER_OWNER` env value (unchanged,
    power-user override) > `owner.json`'s `entity_id` (set by
    `PUT /settings/owner`) > the legacy literal `"rodrigo"`, but ONLY when
    THIS bank already has that page (an install that predates onboarding
    keeps its one lineage rather than forking) > `DEFAULT_OBSERVER` for a
    genuinely fresh bank. Never raises — a corrupt owner.json reads as
    "nothing set", matching every other prefs reader in this codebase
    (`connections/registry.py`'s `prefs()`).
    """
    if settings is not None:
        env_val = str(getattr(settings, "observer_owner", "") or "").strip()
        if env_val:
            return env_val
    entity_id = str(load_owner().get("entity_id") or "").strip()
    if entity_id:
        return entity_id
    if memory_path is not None and (Path(memory_path) / "entities" / f"{LEGACY_OBSERVER}.md").exists():
        return LEGACY_OBSERVER
    return DEFAULT_OBSERVER


def _owner_frontmatter(name: str, entity_id: str, today: str) -> dict:
    return {
        "name": name.strip() or entity_id.replace("-", " ").title(),
        "type": "person",
        "status": "active",
        "confidence": 1.0,
        "created": today,
        "last_referenced": today,
        **decay_policy.frontmatter_fields(DecayClass.evergreen),
        "source_episodes": [],
        "tags": ["owner"],
        "related": [],
        "version": 1,
        "layout_version": 2,
        "owner": True,
    }


def _placeholder_owner_id(entities_dir: Path) -> str | None:
    """The id of this bank's not-yet-named owner page, or ``None``."""
    for path in sorted(entities_dir.glob("*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001 - one unreadable page never blocks the owner write
            continue
        if fm.get("owner") is True and fm.get(PLACEHOLDER_KEY) is True:
            return path.stem
    return None


def ensure_owner_entity(memory_path: Path, name: str) -> tuple[str, bool]:
    """Create-or-update the owner's `person` page at `sanitize_id(name)`.

    R3: never touches a page under any OTHER slug, even one that is clearly
    "the same person" under an older name — that reconciliation is a
    separate, harder problem (entity merge) and out of this row's scope.
    ONE exception, the page this module itself made before the name was known
    (:func:`ensure_default_owner`, marked ``owner_placeholder``): saying the name
    ADOPTS it — the page keeps its id (so the observer, every claim and every
    wikilink already pointing at it stay valid) and takes the name — rather than
    leaving a second owner page beside an empty one.
    Evergreen (CLAUDE.md's decay-class rail: reserved for ingest writers and
    the user — a direct `PUT /settings/owner` from onboarding is a user
    write) — the owner's own page does not decay for being unmentioned.
    """
    memory_path = Path(memory_path)
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    entity_id = sanitize_id(name)
    filepath = entities_dir / f"{entity_id}.md"
    today = str(date.today())

    if not filepath.exists():
        adopted = _placeholder_owner_id(entities_dir)
        if adopted is not None:
            entity_id, filepath = adopted, entities_dir / f"{adopted}.md"

    if filepath.exists():
        parsed = markdown_parser.parse(filepath)
        parsed.frontmatter["owner"] = True
        parsed.frontmatter["name"] = name.strip() or parsed.frontmatter.get("name", entity_id)
        parsed.frontmatter.pop(PLACEHOLDER_KEY, None)
        markdown_parser.write(filepath, parsed.frontmatter, parsed.body)
        return entity_id, False

    frontmatter = _owner_frontmatter(name, entity_id, today)
    body = entity_body.compose_body_v2(
        summary=f"{frontmatter['name']} — this bank's owner.",
        key_facts=[], history_entries=[], related=[], links=[], open_questions=[],
    )
    markdown_parser.write(filepath, frontmatter, body)
    return entity_id, True


def _has_owner_page(entities_dir: Path) -> bool:
    for path in entities_dir.glob("*.md"):
        try:
            if markdown_parser.parse(path).frontmatter.get("owner") is True:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def ensure_default_owner(memory_path: Path) -> str | None:
    """A new bank's owner page — created once, never twice. Returns its id when
    THIS call wrote it, else ``None`` (the bank already has an owner page, or the
    id it would take belongs to some other page, which is left alone).

    The name is the machine-level one (``owner.json``, what onboarding's
    ``PUT /settings/owner`` saved — never a bank's own contents, so no knowledge
    crosses banks) and its id is the one ``resolve_observer`` already answers
    with for every bank; with no name saved, a neutral :data:`PLACEHOLDER_NAME`.
    ``name`` stays the plain name, and the app renders "Name (you)" from
    ``owner: true`` (`Copy.Graph.ownerName`): Stage 2 matches a mention to a page
    by its ``name`` exactly (and then fuzzily), so a stored "Name (you)" would
    stop the person's own name in a conversation from ever resolving to their
    page. The page carries one line ("The main person this memory belongs to.")
    and fills with beliefs through chats and consolidation.

    Never the demo bank's job (it writes its own owner, `demo_bank`); the caller
    passes only a bank it just created.
    """
    memory_path = Path(memory_path)
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    if _has_owner_page(entities_dir):
        return None

    saved = load_owner()
    name = str(saved.get("name") or "").strip()
    entity_id = (str(saved.get("entity_id") or "").strip() or sanitize_id(name)) if name else DEFAULT_OBSERVER
    if not entity_id or (entities_dir / f"{entity_id}.md").exists():
        return None

    frontmatter = _owner_frontmatter(name or PLACEHOLDER_NAME, entity_id, str(date.today()))
    if not name:
        frontmatter[PLACEHOLDER_KEY] = True
    body = entity_body.compose_body_v2(
        summary=DEFAULT_SUMMARY,
        key_facts=[], history_entries=[], related=[], links=[], open_questions=[],
    )
    markdown_parser.write(entities_dir / f"{entity_id}.md", frontmatter, body)
    return entity_id


def seed_owner_page(memory_path: Path) -> str | None:
    """:func:`ensure_default_owner` plus its own commit, for a bank creator.

    Committed alone (``commit_paths_sync``, never ``git add -A``) as ``cicada`` —
    no model wrote it and no person's words are in it — because an untracked page
    would be swept into the next ``git add -A`` writer's commit under that
    writer's author (the G85 smear). Never raises: a bank without a page, or with
    an uncommitted one, is a degraded bank, never a failed creation."""
    from api.services import git_service

    try:
        entity_id = ensure_default_owner(memory_path)
    except OSError as exc:
        logger.warning(f"owner page not created: {exc}")
        return None
    if entity_id is None:
        return None
    try:
        message = git_service.build_commit_message(
            f"Owner page {date.today().isoformat()}",
            [f"entities/{entity_id}.md: created (trigger: user/companion_app)"],
            authors=["cicada"],
        )
        git_service.commit_paths_sync(memory_path, message, [f"entities/{entity_id}.md"])
    except Exception as exc:  # noqa: BLE001 - git absent or unconfigured degrades, never blocks
        logger.warning(f"owner page written but not committed: {exc}")
    return entity_id
