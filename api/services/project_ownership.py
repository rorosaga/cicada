"""Whose projects are listed (TODO ruling 45, 2026-10-27, amends ruling 36 D4): the person's, and only theirs.

The Projects page lists the projects the person made or claimed; everything Cicada detected waits under **Suggested**
with its reason, never archived, deleted, renamed or retyped. A project is the person's when:

* they created it — in the app, from their own shell (``cicada`` CLI), or by asking a trusted agent (the G198 trust
  list, ``page_editors``) that called ``cicada_create_project``;
* they named a watched folder as it (``born: {via: folder}``, ``folder_source.ensure_project``);
* they accepted a suggestion;
* they already logged progress on it in the app — a claim with ``origin: companion_app`` on the page (Q2: derived on
  read, never written, so no bulk write ever runs over a bank);
* they made it in Claude, read from a Claude export's ``projects.json`` (addendum: :data:`CLAUDE_EXPORT_MINE`, one
  constant the acting owner may flip to make those suggestions instead).

**The keys, all frontmatter on the page itself** (so they travel with a merge and with the bank — portability), each
written only by the person's doors (the app's routes, the CLI, a trusted agent on their ask), never by Sleep, which
carries them through every rewrite (``conflict_resolver`` updates the page's own frontmatter) and every merge
(:func:`carry_on_merge`):

``mine: {via, day, by, session?}``         in the person's list
``not_mine: {day}``                         a dismissed suggestion
``description`` / ``description_by``        the person's header line and who last set it (Sleep never writes it)
``conversations_added`` / ``conversations_removed``   conversations tied or untied by hand (``project_conversations``)
``provider_projects: [{provider, id, name?, episode?, docs?}]``   the project's own id in Claude or ChatGPT

``born`` keeps its D4 meaning (where the page came from); ``mine`` is whose list it is in. The two are independent.
This module is the one writer of ``mine``, ``not_mine`` and the two conversation lists.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from api.services import bank_index, decay_policy, markdown_parser, page_lock, project_birth
from api.services.id_utils import sanitize_id

MINE_KEY = "mine"
NOT_MINE_KEY = "not_mine"
DESCRIPTION_KEY = "description"
DESCRIPTION_BY_KEY = "description_by"
ADDED_KEY = "conversations_added"
REMOVED_KEY = "conversations_removed"
PROVIDER_KEY = "provider_projects"
#: Every key the person's doors write and Sleep must never drop (carried on a merge, never moved by a split).
PERSON_KEYS = (MINE_KEY, NOT_MINE_KEY, DESCRIPTION_KEY, DESCRIPTION_BY_KEY, ADDED_KEY, REMOVED_KEY, PROVIDER_KEY)

#: How a project came to be the person's (``mine.via``).
VIA_APP, VIA_CLI, VIA_AGENT, VIA_ACCEPTED, VIA_FOLDER, VIA_IMPORT, VIA_PROGRESS = (
    "app", "cli", "agent", "accepted", "folder", "import", "progress")
#: Addendum (owner, 2026-10-27): a project the person made in Claude is theirs on import. The acting owner confirms
#: this with the owner; ``False`` makes every imported Claude project a suggestion instead ("From your Claude export").
CLAUDE_EXPORT_MINE = True

MAX_NAME = 120
MAX_DESCRIPTION = 600
MAX_TIED = 500
#: A suggestion's reason, strongest first: how the list orders them (proposal §2.3, mitigation 2).
WHY_ORDER = ("repo", "words", "agent", "provider", "export", "none", "fallback")

_HUMAN_PROGRESS_ORIGIN = "companion_app"


class OwnershipError(ValueError):
    """A change refused, with a sentence for the person or the agent. Nothing was written."""


# --- reading -------------------------------------------------------------------------------------------------------


def _dict(value) -> dict | None:
    return value if isinstance(value, dict) else None


def dismissed(fm: dict | None) -> bool:
    return _dict((fm or {}).get(NOT_MINE_KEY)) is not None


def mine_via(fm: dict | None, *, logged_progress: bool = False) -> str | None:
    """How the project is the person's, or ``None`` (a suggestion). A dismissal wins over everything but an explicit
    ``mine`` written after it (accepting a dismissed suggestion drops ``not_mine``)."""
    fm = fm or {}
    mine = _dict(fm.get(MINE_KEY))
    if mine is not None:
        return str(mine.get("via") or VIA_APP)
    if dismissed(fm):
        return None
    born = _dict(fm.get("born")) or {}
    if born.get("via") == "folder" or (not born and project_birth.recorded_kind(fm) == project_birth.WORDS
                                       and ("folder" in (fm.get("tags") or [])
                                            or any(isinstance(p, dict) for p in fm.get("paths") or []))):
        return VIA_FOLDER
    if logged_progress:
        return VIA_PROGRESS
    return None


def is_mine(fm: dict | None, *, logged_progress: bool = False) -> bool:
    return mine_via(fm, logged_progress=logged_progress) is not None


def logged_progress(claims) -> bool:
    """Q2: the person logged progress on this page in the app — a claim the projects router wrote as theirs."""
    return any(str(getattr(c, "origin", "") or "") == _HUMAN_PROGRESS_ORIGIN for c in claims or ())


def description(fm: dict | None) -> str:
    return " ".join(str((fm or {}).get(DESCRIPTION_KEY) or "").split())


def description_by(fm: dict | None) -> dict | None:
    return _dict((fm or {}).get(DESCRIPTION_BY_KEY))


def _entry_episode(x) -> str | None:
    if isinstance(x, str) and x.strip():
        return x.strip()
    if isinstance(x, dict) and isinstance(x.get("episode"), str) and x["episode"].strip():
        return x["episode"].strip()
    return None


def tied(fm: dict | None, key: str) -> list[str]:
    """The episode ids in ``conversations_added`` / ``conversations_removed``. An entry is the id (the person's) or
    ``{episode, by, session?}`` (an agent's tie, so it may untie only what it tied)."""
    raw = (fm or {}).get(key)
    return [e for e in (_entry_episode(x) for x in raw) if e] if isinstance(raw, list) else []


def tied_by(fm: dict | None, episode: str) -> str:
    """Who tied ``episode`` by hand: ``user`` for a bare id, else the agent's label."""
    for x in (fm or {}).get(ADDED_KEY) or []:
        if _entry_episode(x) == episode:
            return str(x.get("by") or "agent") if isinstance(x, dict) else "user"
    return ""


def provider_projects(fm: dict | None) -> list[dict]:
    raw = (fm or {}).get(PROVIDER_KEY)
    return [dict(r) for r in raw if isinstance(r, dict) and r.get("provider") and r.get("id")] \
        if isinstance(raw, list) else []


def is_project_like(fm: dict | None) -> bool:
    """A project page, or a fallback page Cicada wrote for a thing called a project (``project_birth.proposed``)."""
    fm = fm or {}
    return str(fm.get("type") or "") == "project" or project_birth.proposed(fm)


# --- suggestions ---------------------------------------------------------------------------------------------------


@dataclass
class Why:
    """Why a suggestion is offered: ``kind`` (one of :data:`WHY_ORDER`), one sentence, and what backs it."""

    kind: str
    text: str
    quote: str | None = None
    episode: str | None = None
    day: str | None = None
    repo_name: str | None = None
    sessions: int = 0
    by: str | None = None


def why(memory_path: Path, stem: str, fm: dict, *, repo_sessions: int = 0, conversations: int = 0) -> Why:
    """The reason a page is a suggestion, from what the page itself records (no conversation re-read beyond the one
    sentence a words birth points at)."""
    fm = fm or {}
    born = _dict(fm.get("born")) or {}
    if project_birth.proposed(fm):
        n = conversations or len([e for e in fm.get("source_episodes") or [] if e])
        return Why("fallback", f"Came up in {n} conversation{'s' if n != 1 else ''}; you never called it a project.",
                   sessions=n)
    if born.get("origin") == "created" and born.get("via") == "agent":
        by = str(born.get("by") or "an agent")
        return Why("agent", f"Proposed by {by}.", by=by, day=born.get("day"), episode=born.get("episode"))
    if born.get("origin") == "created" and born.get("via") == "claude-export":
        return Why("export", "From your Claude export.", day=born.get("day"))
    if born.get("origin") == project_birth.REPO or (not born and [r for r in fm.get("repos") or [] if r]):
        name = (born.get("repo") or {}).get("name") or next((str(r) for r in fm.get("repos") or [] if r), None)
        n = repo_sessions
        tail = f" · {n} session{'s' if n != 1 else ''}" if n else ""
        return Why("repo", f"From the repository {name or '?'}{tail}.", repo_name=name, day=born.get("day"),
                   episode=born.get("episode"), sessions=n)
    if born.get("origin") == project_birth.WORDS:
        said = project_birth.quote(memory_path, born)
        return Why("words", "You called it a project in a conversation.", quote=said, episode=born.get("episode"),
                   day=born.get("day"))
    n = conversations or len([e for e in fm.get("source_episodes") or [] if e])
    made = f"Cicada made this page from {n} conversation{'s' if n != 1 else ''}" if n else "Cicada made this page"
    return Why("none", f"{made}; nothing on the record says it is yours.", sessions=n)


def strength(w: Why) -> tuple:
    return (WHY_ORDER.index(w.kind) if w.kind in WHY_ORDER else len(WHY_ORDER), -w.sessions)


# --- writing -------------------------------------------------------------------------------------------------------


def _today(today: date | None) -> str:
    return (today or date.today()).isoformat()


def _mark(via: str, *, by: str, day: str, session: str | None = None) -> dict:
    out = {"via": via, "day": day, "by": by}
    if session:
        out["session"] = session
    return out


def clean_name(name) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise OwnershipError("Give the project a name.")
    if len(text) > MAX_NAME:
        raise OwnershipError(f"A project's name is at most {MAX_NAME} characters.")
    return text


def clean_description(text) -> str:
    out = " ".join(str(text or "").split())
    if len(out) > MAX_DESCRIPTION:
        raise OwnershipError(f"A description is at most {MAX_DESCRIPTION} characters.")
    return out


def existing_named(memory_path: Path, name: str) -> str | None:
    """The live page a name already resolves to, by id or by a name or alias that folds the same — what a create
    refuses (the refusal names it, so an agent links it instead)."""
    want = project_birth.fold(name)
    sid = sanitize_id(name)
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("status") or "active") == "dropped":
            continue
        if f.stem == sid or want in project_birth.name_folds({"name": fm.get("name") or f.stem,
                                                             "aliases": fm.get("aliases") or []}):
            return f.stem
    return None


def _free_id(memory_path: Path, name: str) -> str:
    eid = sanitize_id(name)
    page = Path(memory_path) / "entities" / f"{eid}.md"
    if page.exists():
        eid = f"{eid}-{hashlib.sha1(name.encode()).hexdigest()[:4]}"
    return eid


@page_lock.locked
def create(memory_path: Path, name: str, desc: str = "", *, via: str, by: str, listed: bool,
           session: str | None = None, episode: str | None = None, span: dict | None = None,
           repo: str | None = None, born_via: str | None = None, provider: dict | None = None,
           today: date | None = None) -> tuple[str, list[str]]:
    """A new project page the person (or an agent on their ask) started: ``(id, paths written)``. ``born`` says it was
    created and through which door; ``mine`` is written only when ``listed`` (the person's own doors, or a trusted
    agent), else the page waits under Suggested. Raises :class:`OwnershipError` for a name already taken."""
    memory_path = Path(memory_path)
    name = clean_name(name)
    desc = clean_description(desc)
    if (taken := existing_named(memory_path, name)) is not None:
        raise OwnershipError(f"'{name}' is already a page in memory ({taken}). Use that page instead.")
    day = _today(today)
    eid = _free_id(memory_path, name)
    born: dict = {"origin": "created", "via": born_via or via, "day": day}
    if via == VIA_AGENT:
        born["by"] = by
        if session:
            born["session"] = session
    if episode:
        born["episode"] = episode
    if span:
        born["span"] = span
    fm: dict = {
        "name": name, "type": "project", "status": "active", "confidence": 0.9,
        "created": day, "last_referenced": day,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("project")),
        "source_episodes": [episode] if episode else [], "tags": [], "related": [], "version": 1,
        "born": born,
    }
    if repo:
        fm["repos"] = [str(repo)]
    if desc:
        fm[DESCRIPTION_KEY] = desc
        fm[DESCRIPTION_BY_KEY] = {"by": by, "day": day, **({"session": session} if session else {})}
    if listed:
        fm[MINE_KEY] = _mark(VIA_IMPORT if born_via == "claude-export" else via, by=by, day=day, session=session)
    if provider:
        fm[PROVIDER_KEY] = [provider]
    page = memory_path / "entities" / f"{eid}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    lead = desc or name
    markdown_parser.write(page, fm, f"## Summary\n{lead}")
    bank_index.invalidate()
    return eid, [f"entities/{eid}.md"]


def _page(memory_path: Path, stem: str) -> Path:
    page = Path(memory_path) / "entities" / f"{stem}.md"
    if not page.is_file():
        raise OwnershipError(f"No page {stem!r}.")
    return page


@page_lock.locked
def _rewrite(memory_path: Path, stem: str, change) -> list[str]:
    page = _page(memory_path, stem)
    parsed = markdown_parser.parse(page, ledger=False)
    fm = dict(parsed.frontmatter)
    if change(fm) is False:
        return []
    markdown_parser.write(page, fm, parsed.body)
    bank_index.invalidate()
    return [f"entities/{page.name}"]


def accept(memory_path: Path, stem: str, *, name: str | None = None, by: str = "user",
           today: date | None = None) -> list[str]:
    """The person adds a suggestion to their projects. A fallback concept becomes the project in place
    (``project_birth.retype_on_birth``, ``born: {origin: created, via: accepted}``); a dismissal is lifted. Idempotent."""
    day = _today(today)

    def change(fm: dict):
        if not is_project_like(fm):
            raise OwnershipError(f"{stem!r} is not a project or a suggested one.")
        if project_birth.proposed(fm):
            project_birth.retype_on_birth(fm, {"origin": "created", "via": VIA_ACCEPTED, "day": day})
        if name:
            _rename(fm, clean_name(name))
        changed = fm.pop(NOT_MINE_KEY, None) is not None
        if _dict(fm.get(MINE_KEY)) is None:
            fm[MINE_KEY] = _mark(VIA_ACCEPTED, by=by, day=day)
            changed = True
        return changed or None

    return _rewrite(memory_path, stem, change)


def dismiss(memory_path: Path, stem: str, *, today: date | None = None) -> list[str]:
    """"Not mine": the page stays as it is (never archived or deleted) and leaves the person's list; it sits behind
    "N dismissed" and can be accepted later."""
    day = _today(today)

    def change(fm: dict):
        if not is_project_like(fm):
            raise OwnershipError(f"{stem!r} is not a project or a suggested one.")
        if dismissed(fm) and MINE_KEY not in fm:
            return False
        fm.pop(MINE_KEY, None)
        fm[NOT_MINE_KEY] = {"day": day}
        return None

    return _rewrite(memory_path, stem, change)


def _rename(fm: dict, new: str) -> bool:
    old = " ".join(str(fm.get("name") or "").split())
    if not new or new == old:
        return False
    fm["name"] = new
    aliases = [a for a in (fm.get("aliases") or []) if isinstance(a, str)]
    if old and old.casefold() not in {a.casefold() for a in aliases}:
        aliases.append(old)
    fm["aliases"] = [a for a in aliases if a.casefold() != new.casefold()]
    if not fm["aliases"]:
        fm.pop("aliases")
    return True


def apply_header(fm: dict, *, name: str | None = None, desc: str | None = None, by: str, day: str,
                 session: str | None = None) -> list[str]:
    """Rename (the slug never changes; the old name becomes an alias) and set the description with its blame, in a
    frontmatter dict. Returns the changes, in words. ``page_edits.plan`` and the app's PATCH both come through here."""
    changes: list[str] = []
    if name is not None and _rename(fm, clean_name(name)):
        changes.append("renamed")
    if desc is not None:
        text = clean_description(desc)
        if text != description(fm):
            if text:
                fm[DESCRIPTION_KEY] = text
            else:
                fm.pop(DESCRIPTION_KEY, None)
            mark = {"by": by, "day": day}
            if session:
                mark["session"] = session
            fm[DESCRIPTION_BY_KEY] = mark
            changes.append("description set" if text else "description cleared")
    return changes


def set_header(memory_path: Path, stem: str, *, name: str | None = None, desc: str | None = None,
               by: str = "user", session: str | None = None, today: date | None = None) -> list[str]:
    day = _today(today)

    def change(fm: dict):
        if not is_project_like(fm):
            raise OwnershipError(f"{stem!r} is not a project.")
        return bool(apply_header(fm, name=name, desc=desc, by=by, day=day, session=session)) or False

    return _rewrite(memory_path, stem, change)


def tie(memory_path: Path, stem: str, episode: str, *, remove: bool = False, by: str = "user",
        session: str | None = None) -> list[str]:
    """Tie a conversation to the project by hand, or untie it.

    The person's untie overrides every automatic signal and no signal re-adds it (the ``sources_removed`` rule); tying
    it again lifts the untie. An agent's tie is recorded with its name; an agent may untie only what it tied (the
    "withdraw only what it wrote" rail), which drops its tie and never marks the conversation untied."""
    from api.services import evidence

    if not evidence.is_episode_id(episode):
        raise OwnershipError(f"{episode!r} is not a conversation id (like ep_2026-10-01_001).")
    if not (Path(memory_path) / "episodes" / f"{episode}.md").is_file():
        raise OwnershipError(f"No conversation {episode!r}.")
    person = by == "user"

    def change(fm: dict):
        if not is_project_like(fm):
            raise OwnershipError(f"{stem!r} is not a project.")
        added = [x for x in (fm.get(ADDED_KEY) or []) if _entry_episode(x)]
        removed = [x for x in (fm.get(REMOVED_KEY) or []) if _entry_episode(x)]
        had = [x for x in added if _entry_episode(x) == episode]
        if remove:
            if not person:
                mine = [x for x in had if isinstance(x, dict) and x.get("by") == by]
                if not mine:
                    raise OwnershipError("You can untie only a conversation you tied; the person decides the rest in "
                                         "the app.")
                added = [x for x in added if x not in mine]
            else:
                if episode in tied(fm, REMOVED_KEY) and not had:
                    return False
                added = [x for x in added if _entry_episode(x) != episode]
                removed.append(episode)
        else:
            if episode in tied(fm, REMOVED_KEY) and not person:
                raise OwnershipError("The person untied that conversation from this project; it stays untied.")
            removed = [x for x in removed if _entry_episode(x) != episode]
            if had and episode not in tied(fm, REMOVED_KEY):
                return False
            if not had:
                entry = episode if person else {"episode": episode, "by": by, **({"session": session} if session
                                                                                  else {})}
                added.append(entry)
        for key, rows in ((ADDED_KEY, added), (REMOVED_KEY, removed)):
            if rows:
                fm[key] = rows[-MAX_TIED:]
            else:
                fm.pop(key, None)
        return None

    return _rewrite(memory_path, stem, change)


def add_provider(fm: dict, entry: dict) -> bool:
    """Record a provider's own project id on the page (Claude export, a ChatGPT grouping the person named)."""
    rows = provider_projects(fm)
    key = (str(entry.get("provider")), str(entry.get("id")))
    for row in rows:
        if (str(row.get("provider")), str(row.get("id"))) == key:
            before = dict(row)
            row.update({k: v for k, v in entry.items() if v not in (None, "", [])})
            if row == before:
                return False
            fm[PROVIDER_KEY] = rows
            return True
    rows.append({k: v for k, v in entry.items() if v not in (None, "", [])})
    fm[PROVIDER_KEY] = rows
    return True


def carry_on_merge(winner_fm: dict, loser_fm: dict) -> None:
    """A page merge keeps the person's word on either page: the winner's own keys win, the loser's fill what the winner
    lacks, and the tied/untied lists and provider ids union (an untie on either side stays an untie)."""
    for key in (MINE_KEY, DESCRIPTION_KEY, DESCRIPTION_BY_KEY):
        if key not in winner_fm and key in loser_fm:
            winner_fm[key] = loser_fm[key]
    if NOT_MINE_KEY in loser_fm and NOT_MINE_KEY not in winner_fm and MINE_KEY not in winner_fm:
        winner_fm[NOT_MINE_KEY] = loser_fm[NOT_MINE_KEY]
    removed = list(dict.fromkeys(tied(winner_fm, REMOVED_KEY) + tied(loser_fm, REMOVED_KEY)))
    added, seen = [], set()
    for x in list(winner_fm.get(ADDED_KEY) or []) + list(loser_fm.get(ADDED_KEY) or []):
        ep = _entry_episode(x)
        if ep and ep not in seen and ep not in removed:
            seen.add(ep)
            added.append(x)
    for key, rows in ((ADDED_KEY, added), (REMOVED_KEY, removed)):
        if rows:
            winner_fm[key] = rows[-MAX_TIED:]
    for row in provider_projects(loser_fm):
        add_provider(winner_fm, row)


# --- page-less suggestions (a ChatGPT project with no name) -----------------------------------------------------------

#: A bank file for what has no page to carry it: ChatGPT project groupings the person dismissed. In the bank (it is the
#: person's decision about bank content, and travels with it), committed under the person.
GROUPINGS_FILE = "project_groupings.yaml"
_GROUP_ID = re.compile(r"^g-p-[A-Za-z0-9_-]{4,80}$")


def is_group_id(value) -> bool:
    return isinstance(value, str) and bool(_GROUP_ID.match(value))


def dismissed_groups(memory_path: Path) -> set[str]:
    path = Path(memory_path) / GROUPINGS_FILE
    try:
        data = markdown_parser.load_yaml(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return set()
    return {str(g) for g in data.get("dismissed") or [] if is_group_id(str(g))}


def dismiss_group(memory_path: Path, group: str, *, today: date | None = None) -> list[str]:
    if not is_group_id(group):
        raise OwnershipError(f"{group!r} is not a project grouping.")
    have = dismissed_groups(memory_path)
    if group in have:
        return []
    path = Path(memory_path) / GROUPINGS_FILE
    markdown_parser.write_yaml(path, {"dismissed": sorted(have | {group})})
    return [GROUPINGS_FILE]
