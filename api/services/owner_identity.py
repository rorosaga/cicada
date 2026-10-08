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
import unicodedata
from dataclasses import dataclass
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


#: G169 — what a conversation or an extraction calls the person when it does not
#: use their name: Stage 1 writes "User" or "the user"; a transcript says "me" or
#: "I"; a Spanish one says "el usuario", "yo" or "mí". The ONE list: the resolver's
#: set below and the prompts' wording (``entity_extractor.owner_block``,
#: ``conflict_resolver._owner_line``) are both built from it. Closed on purpose
#: (R-PJ17, R-CS2). Not "you" — in a transcript that is the assistant speaking to
#: the person, and in an export it is as often a title; not "mi" — a brand as often
#: as an unaccented "mí".
SELF_REFERENCE_FORMS = (
    "User", "the user", "I", "me", "myself", "the person", "the owner", "owner",
    "el usuario", "la usuaria", "usuario", "usuaria", "yo", "mí",
)


def _self_key(name: str) -> str:
    """A name as the self-reference set compares it: NFC (so a composed and a
    decomposed "mí" agree), inner spacing collapsed, lower-cased, outer quotes and
    trailing punctuation dropped."""
    text = unicodedata.normalize("NFC", str(name or ""))
    return " ".join(text.split()).lower().strip(" \"'`.,;:!?")


SELF_REFERENCES = frozenset(_self_key(f) for f in SELF_REFERENCE_FORMS)


def self_reference_list() -> str:
    """:data:`SELF_REFERENCE_FORMS` as prompt text — '"User", "the user", … or "mí"' —
    so a prompt can never name a form the resolver does not route, or miss one."""
    quoted = [f'"{f}"' for f in SELF_REFERENCE_FORMS]
    return ", ".join(quoted[:-1]) + " or " + quoted[-1]


def is_self_reference(name: str) -> bool:
    """Is ``name`` SPELLED like one of :data:`SELF_REFERENCE_FORMS`? Spelling only —
    whether it IS the person is :class:`SelfReferences`' question (a company called
    "Owner" is spelled like one and is not)."""
    return _self_key(name) in SELF_REFERENCES


@dataclass(frozen=True)
class SelfReferences:
    """G169 — the one qualified decision: is this name the person speaking?

    A name spelled like a self-reference is a SPEAKER reference — the bank's
    owner — only when (a) it is a person or carries no type (an edge or claim
    endpoint, a wikilink) and (b) no non-person page, and no non-person entity in
    the batch, holds that exact name: a company "Owner", a concept "I", a tool
    "Me", a company "Yo" keep their own facts, edges and claims. An old duplicate
    PERSON page named "User" reserves nothing, so the person's words stop feeding
    it. Built once from the same inputs by every step that keys a name — Stage 2's
    entities, edges and promotion, Sleep's claims and holds, the wikilink edges —
    so they can never disagree."""

    owner_id: str | None
    reserved: frozenset[str] = frozenset()

    def is_speaker(self, name: str, kind: str | None = None) -> bool:
        key = _self_key(name)
        if key not in SELF_REFERENCES or key in self.reserved:
            return False
        return not kind or str(kind).strip().lower() == "person"

    def owner_for(self, name: str, kind: str | None = None) -> str | None:
        """The owner page a speaker reference keys to (``None`` without one)."""
        return self.owner_id if self.is_speaker(name, kind) else None

    def reserved_slugs(self) -> frozenset[str]:
        return frozenset(sanitize_id(k) for k in self.reserved)


def _non_person(kind) -> bool:
    return str(kind or "concept").strip().lower() != "person"


def self_references(pages: list[dict] | None, extracted: list[dict] | None = None,
                    memory_path: Path | None = None, settings=None) -> SelfReferences:
    """:class:`SelfReferences` for a bank's pages (``[{id, frontmatter}]``, Stage 2's
    ``existing``) plus this batch's Stage-1 output plus the bank's pending lines
    (``pending_store``, under ``memory_path``) — a name heard once as a company "Yo"
    is still that company when a later batch names it only as an endpoint. A page
    with no type reads as a concept, as everywhere else; a batch entity or pending
    line reserves only when it is typed and not a person."""
    reserved: set[str] = set()
    for page in pages or []:
        fm = (page or {}).get("frontmatter") or {}
        key = _self_key(fm.get("name") or "")
        if key in SELF_REFERENCES and not fm.get("owner") and _non_person(fm.get("type")):
            reserved.add(key)
    for extraction in extracted or []:
        for entity in extraction.get("entities", []) or []:
            key = _self_key((entity or {}).get("name") or "")
            if key in SELF_REFERENCES and entity.get("type") and _non_person(entity.get("type")):
                reserved.add(key)
    if memory_path is not None:
        from api.services import pending_store

        try:
            lines = pending_store.load(Path(memory_path))
        except Exception:  # noqa: BLE001 - an unreadable store reserves nothing, never fails a cycle
            lines = []
        for line in lines:
            key = _self_key(line.name)
            if key in SELF_REFERENCES and line.type and _non_person(line.type):
                reserved.add(key)
    return SelfReferences(owner_page_id(pages, memory_path, settings), frozenset(reserved))


def owner_page_id(existing: list[dict] | None, memory_path: Path | None, settings=None) -> str | None:
    """The bank's ``owner: true`` page among Stage 2's ``existing`` list, or ``None``.

    Two owner pages can exist (G117 R3's disclosed gap: re-onboarding under a
    new display name writes a second page); the one :func:`resolve_observer`
    answers with wins, else the first by id, so the answer never depends on file
    order."""
    owners = sorted(
        str(e.get("id")) for e in (existing or [])
        if isinstance(e, dict) and e.get("id") and (e.get("frontmatter") or {}).get("owner")
    )
    if len(owners) <= 1:
        return owners[0] if owners else None
    try:
        resolved = resolve_observer(memory_path, settings)
    except Exception:  # noqa: BLE001 - a tie-break is never worth a failed cycle
        resolved = None
    return resolved if resolved in owners else owners[0]


def _owner_fm_name(fm: dict) -> str | None:
    name = str((fm or {}).get("name") or "").strip()
    return name if (fm or {}).get("owner") is True and name else None


def owner_name(memory_path: Path | None, settings=None) -> str | None:
    """The ``name`` on this bank's ``owner: true`` page, or ``None`` without one —
    what Sleep's prompts call the person (G169). The page :func:`resolve_observer`
    names is read first (one file); only when that is not the owner page is the
    bank scanned."""
    if memory_path is None:
        return None
    entities_dir = Path(memory_path) / "entities"

    def _name(path: Path) -> str | None:
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001 - an unreadable page is no owner
            return None
        return _owner_fm_name(fm)

    try:
        first = entities_dir / f"{resolve_observer(memory_path, settings)}.md"
    except Exception:  # noqa: BLE001
        first = None
    if first is not None and first.is_file():
        name = _name(first)
        if name:
            return name
    # The stat-cached frontmatter every other scan reads: Sleep asks ~21 times a batch, and a fresh parse of every
    # page each time was 42k parses a batch on a 2,000-page bank (F8, benchmarks/scale).
    from api.services import bank_index

    found = [(f.stem, n) for f in sorted(bank_index.files(Path(memory_path), "entities"), key=lambda f: f.path.name)
             if f.path.suffix == ".md" and (n := _owner_fm_name(f.frontmatter))]
    if not found:
        return None
    winner = owner_page_id([{"id": i, "frontmatter": {"owner": True}} for i, _ in found], memory_path, settings)
    return dict(found).get(winner)


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


def seed_owner_if_brand_new(memory_path: Path) -> str | None:
    """The first-boot default bank never passes through ``create_bank``, so the
    lifespan calls this: a bank with no entity page, no episode and so no owner
    page gets the same seed a created bank does. Anything already in it (an
    imported or restored bank, a bank whose owner page was deleted after use)
    is left exactly as it is."""
    memory_path = Path(memory_path)
    for folder in ("entities", "episodes"):
        if any((memory_path / folder).glob("*.md")):
            return None
    return seed_owner_page(memory_path)
