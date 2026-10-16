"""The other side of a message conversation is its own page, of its own type (G179, owner 2026-10-15).

A ticked Messages conversation's episodes carry a ``correspondent`` record (`messages_source`): who is on the other
side, what they are (``agent`` | ``person``) and who decided it — the person's mark, or an ``identified`` detection
(`agent_detectors`). A name that IS that record's name, in an entity Stage 1 extracted from one of those very
episodes, is the correspondent: not a mention of some page that happens to share the letters. Before this, Stage 2
resolved it by name alone, so a texted agent landed on an archived ``concept`` page about the ordinary word.

The one rule, shared by Stage 1 (marks the entity and gives it its type), Stage 2 (finds or creates the page and pins
the conversation's own edges and claims to it) and the repair of a bank already split wrong
(`correspondent_repair`):

* **The signal** is the episode's own ``correspondent`` record with a decided kind — never a name seen anywhere else,
  never a detector's ``uncertain`` guess (that record says ``unknown``), and only for an entity extracted from that
  episode whose name or one of its aliases folds (`agent_detectors.fold`) to exactly the record's name. A mention of
  the same letters in any other conversation goes through the general resolver as before, so this cannot widen into
  ordinary homonym handling.
* **The type:** an AI agent is a ``tool`` (the closed set's place for software the person uses; it is not a person
  and not an idea), a texted person a ``person``.
* **The page:** an existing page of that type whose name or alias folds to the name — the one named so first — else
  the promotion rule decides, as for any name. Below it, the correspondent waits in the pending store under its own
  key (:func:`free_id`, ``<id>-agent`` / ``<id>-person``, never the plain same-name id; :func:`held_line` finds it
  again); once the rule passes, its page is created under that id with everything held.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from api.services import agent_detectors
from api.services.id_utils import sanitize_id

#: A correspondent's kind -> the page type it gets.
PAGE_TYPE = {agent_detectors.AGENT: "tool", agent_detectors.PERSON: "person"}
#: A correspondent's kind -> the id suffix used when its name's id is taken by another page.
ID_SUFFIX = {agent_detectors.AGENT: "agent", agent_detectors.PERSON: "person"}

#: The key Stage 1 sets on an entity (and on its extraction) that is the episode's correspondent.
MARK = "correspondent"
#: The keys Stage 2 sets on a relationship endpoint that is the correspondent: the page it is pinned to.
SOURCE_PAGE = "source_page"
TARGET_PAGE = "target_page"
#: What the model may never set (stripped from its answer before anything reads it).
RESERVED_KEYS = (MARK, SOURCE_PAGE, TARGET_PAGE)


@dataclass(frozen=True)
class Identity:
    name: str
    kind: str

    @property
    def key(self) -> str:
        return agent_detectors.fold(self.name)

    @property
    def page_type(self) -> str:
        return PAGE_TYPE[self.kind]

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind}


def identity(record) -> Identity | None:
    """The correspondent an episode's ``correspondent`` record names, or ``None`` when it decides nothing: no record,
    an unknown kind (nobody marked it and no detector identified it), or no name the person sees."""
    if not isinstance(record, dict):
        return None
    kind = record.get("kind")
    if kind not in PAGE_TYPE:
        return None
    name = " ".join(str(record.get("name") or "").split())
    if not name or name == agent_detectors.UNNAMED or not agent_detectors.fold(name):
        return None
    return Identity(name=name, kind=str(kind))


def from_mark(mark) -> Identity | None:
    """The identity Stage 1 stamped on an entity or extraction (:data:`MARK`)."""
    return identity(mark)


def names_it(names, ident: Identity) -> bool:
    """Does one of ``names`` fold to exactly the correspondent's name?"""
    return any(agent_detectors.fold(str(n or "")) == ident.key for n in names if n)


def entity_names(entity: dict) -> list:
    aliases = entity.get("aliases") if isinstance(entity.get("aliases"), list) else []
    return [entity.get("name"), *aliases]


def mark_extraction(result: dict, record) -> int:
    """Stage 1: stamp an episode's extraction with its correspondent, and every entity extracted from it that names
    them with the mark and the correspondent's page type. Strips what the model may never set first. Returns how
    many entities it marked."""
    for item in (*(result.get("entities") or []), *(result.get("relationships") or [])):
        if isinstance(item, dict):
            for key in RESERVED_KEYS:
                item.pop(key, None)
    ident = identity(record)
    if ident is None:
        return 0
    result[MARK] = ident.to_dict()
    marked = 0
    for entity in result.get("entities") or []:
        if isinstance(entity, dict) and names_it(entity_names(entity), ident):
            entity[MARK] = ident.to_dict()
            entity["type"] = ident.page_type
            marked += 1
    return marked


def _page_names(page: dict) -> tuple[str, list]:
    fm = page.get("frontmatter") or {}
    aliases = fm.get("aliases")
    if isinstance(aliases, str):
        aliases = [aliases]
    return str(fm.get("name") or ""), [a for a in aliases or [] if a] if isinstance(aliases, list) else []


def find_page(pages: list[dict], ident: Identity) -> dict | None:
    """The existing page that is this correspondent: its type, and its name (else one of its aliases) folding to the
    correspondent's name. Never the owner's page. A page named so wins over one that only lists the alias; ties go to
    the smallest id, so the choice is the same every run."""
    named, aliased = [], []
    for page in pages:
        fm = page.get("frontmatter") or {}
        # A page the person dropped is still theirs: it is updated and stays dropped (the update branch never
        # resurfaces one), never replaced by a fresh page.
        if str(fm.get("type") or "").lower() != ident.page_type or fm.get("owner") is True:
            continue
        name, aliases = _page_names(page)
        if names_it([name], ident):
            named.append(page)
        elif names_it(aliases, ident):
            aliased.append(page)
    for group in (named, aliased):
        if group:
            return min(group, key=lambda p: str(p.get("id") or ""))
    return None


def free_id(ident: Identity, taken, entities_dir: Path | None = None) -> str:
    """The id a new correspondent page is written under — and, while it waits below the promotion bar, its pending
    line's key: always ``<id>-agent`` / ``<id>-person`` (then ``-2``, ``-3``…), never the name's plain id, so a
    same-name page or a same-name pending line can never take what is held for it. ``taken`` is every id already used
    (on disk, created in this batch, and every pending line's slug); ``entities_dir`` is checked too, so a page the
    caller did not load is never overwritten."""
    taken = set(taken)

    def used(candidate: str) -> bool:
        return candidate in taken or (entities_dir is not None and (Path(entities_dir) / f"{candidate}.md").exists())

    qualified = f"{sanitize_id(ident.name)}-{ID_SUFFIX[ident.kind]}"
    candidate, n = qualified, 2
    while used(candidate):
        candidate, n = f"{qualified}-{n}", n + 1
    return candidate


def held_line(lines, ident: Identity):
    """The pending line holding this correspondent below the promotion bar (``PendingEntity.correspondent``), or
    ``None``. Matched by the correspondent record, never by name: a same-name line is someone else's."""
    for line in lines or ():
        if identity(getattr(line, "correspondent", None)) == ident:
            return line
    return None
