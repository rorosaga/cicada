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


def ensure_owner_entity(memory_path: Path, name: str) -> tuple[str, bool]:
    """Create-or-update the owner's `person` page at `sanitize_id(name)`.

    R3: never touches a page under any OTHER slug, even one that is clearly
    "the same person" under an older name — that reconciliation is a
    separate, harder problem (entity merge) and out of this row's scope.
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

    if filepath.exists():
        parsed = markdown_parser.parse(filepath)
        parsed.frontmatter["owner"] = True
        parsed.frontmatter["name"] = name.strip() or parsed.frontmatter.get("name", entity_id)
        markdown_parser.write(filepath, parsed.frontmatter, parsed.body)
        return entity_id, False

    frontmatter = {
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
    body = entity_body.compose_body_v2(
        summary=f"{frontmatter['name']} — this bank's owner.",
        key_facts=[], history_entries=[], related=[], links=[], open_questions=[],
    )
    markdown_parser.write(filepath, frontmatter, body)
    return entity_id, True
