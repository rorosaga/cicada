"""Whose projects are listed (TODO ruling 45, 2026-10-27; ruling 56, 2026-11-04): the person's, and only theirs.

The Projects page lists the projects the person made or claimed. Nothing Cicada detects is offered there any more
(ruling 56): every other page stays a page, reachable by search, the graph, recall and ``cicada_project``, never
archived, deleted, renamed or retyped in bulk. A project is the person's when:

* they started it — in the app, from their own shell (``cicada`` CLI), or by asking a trusted agent (the G198 trust
  list, ``page_editors``) that called ``cicada_create_project``;
* they named a watched folder as it (``born: {via: folder}``, ``folder_source.ensure_project``);
* they added an existing page to their projects, or accepted a suggestion before suggestions went;
* they already logged progress on it in the app — a claim with ``origin: companion_app`` on the page (Q2: derived on
  read, never written, so no bulk write ever runs over a bank);
* they made it in Claude, read from a Claude export's ``projects.json`` (addendum, confirmed by ruling 56:
  :data:`CLAUDE_EXPORT_MINE`).

**Starting a project whose page already exists adopts that page** (:func:`start_target`, :func:`start`): the same id,
body, claims and history, never a second page under the same name. Only a page that can honestly be the project is
adopted (:data:`ADOPTABLE`); anything else is refused, naming the page.

**The keys, all frontmatter on the page itself** (so they travel with a merge and with the bank — portability), each
written only by the person's doors (the app's routes, the CLI, a trusted agent on their ask), never by Sleep, which
carries them through every rewrite (``conflict_resolver`` updates the page's own frontmatter) and every merge
(:func:`carry_on_merge`):

``mine: {via, day, by, session?}``         in the person's list
``not_mine: {day}``                         taken out of the person's list; a page they said is not theirs
``started_from: {type, proposed?, wrote_born?}``   what a start retyped, so Remove gives the page back (`project_birth`)
``description`` / ``description_by``        the person's header line and who last set it (Sleep never writes it)
``conversations_added`` / ``conversations_removed``   conversations tied or untied by hand (``project_conversations``)
``entities_added`` / ``entities_removed``   pages tied to the project by hand, or "Not part of it" (``project_pages``)
``repositories`` / ``repositories_removed``   its GitHub repositories and the person's unlinks (``github_repos``, G230)
``provider_projects: [{provider, id, name?, episode?, docs?}]``   the project's own id in Claude or ChatGPT

``born`` keeps its D4 meaning (where the page came from); ``mine`` is whose list it is in. The two are independent.
This module is the one writer of ``mine``, ``not_mine``, the two conversation lists and the two page lists.

**Why the page lists are frontmatter, not claims** (2026-10-28, decision 10): "Not part of it" is a negative that must
win over every automatic tie, and a claim cannot say "no edge here" without a new predicate and closure rules; a
``part-of`` claim is already what makes a sub-project (``project_timeline._tree``), so a hand tie written as one would
silently re-parent pages; and membership is the person's curation of their own project, not a belief about the world
with evidence, decay and supersession. The conversation lists set the precedent: one writer, carried on a merge, kept
by Sleep, travelling with the bank.
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
PAGES_ADDED_KEY = "entities_added"
PAGES_REMOVED_KEY = "entities_removed"
#: Every key the person's doors write and Sleep must never drop (carried on a merge, never moved by a split).
PERSON_KEYS = (MINE_KEY, NOT_MINE_KEY, DESCRIPTION_KEY, DESCRIPTION_BY_KEY, ADDED_KEY, REMOVED_KEY, PROVIDER_KEY,
               PAGES_ADDED_KEY, PAGES_REMOVED_KEY)

#: How a project came to be the person's (``mine.via``).
VIA_APP, VIA_CLI, VIA_AGENT, VIA_ACCEPTED, VIA_FOLDER, VIA_IMPORT, VIA_PROGRESS = (
    "app", "cli", "agent", "accepted", "folder", "import", "progress")
#: Addendum (owner, 2026-10-27): a project the person made in Claude is theirs on import. Confirmed in ruling 56 (owner,
#: 2026-11-04: "Yes imported Claude projects are mine.").
CLAUDE_EXPORT_MINE = True

MAX_NAME = 120
#: The person's description is the project page's lead in their own words (owner 2026-11-04: "a better bigger page
#: view for describing this"): paragraphs kept, at most this many characters.
MAX_DESCRIPTION = 4000
#: Pages attached in one New project, at most.
MAX_ATTACH = 100
MAX_TIED = 500
#: At most this much of an agent's one-sentence reason is kept on a link it made.
MAX_REASON = 300
#: The page types a start may adopt, strongest first: a project page; a concept (a fallback page, or the thing Stage 1
#: filed as an idea); a tool (what the person builds is often read as one). A person, an organisation, a place, a
#: repository page (ruling 53: never a project) or the rest is refused by name: retyping one would break what it is.
ADOPTABLE = ("project", "concept", "tool")

_HUMAN_PROGRESS_ORIGIN = "companion_app"


class OwnershipError(ValueError):
    """A change refused, with a sentence for the person or the agent. Nothing was written."""


def name_taken(exc: Exception) -> bool:
    """The refusal is about a name a page already holds (the route's 409)."""
    return "already a page" in str(exc) or "Several pages answer" in str(exc)


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
    """The person's description as they wrote it, paragraphs kept (:func:`clean_description`'s form)."""
    value = (fm or {}).get(DESCRIPTION_KEY)
    return clean_description_lenient(value) if value else ""


def clean_description_lenient(text) -> str:
    """:func:`clean_description` without the length check (a page written before the cap moved is read as it is)."""
    lines = [" ".join(line.split()) for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def first_line(text: str | None) -> str:
    """The description's first non-empty line: what one-line surfaces (the list row) show."""
    return next((line.strip() for line in str(text or "").split("\n") if line.strip()), "")


def description_by(fm: dict | None) -> dict | None:
    return _dict((fm or {}).get(DESCRIPTION_BY_KEY))


def _entry_episode(x) -> str | None:
    if isinstance(x, str) and x.strip():
        return x.strip()
    if isinstance(x, dict) and isinstance(x.get("episode"), str) and x["episode"].strip():
        return x["episode"].strip()
    return None


def _is_proposal(x) -> bool:
    return isinstance(x, dict) and bool(x.get("proposed"))


def tied(fm: dict | None, key: str) -> list[str]:
    """The episode ids in ``conversations_added`` / ``conversations_removed``. An entry is the id (the person's) or
    ``{episode, by, session?, reason?, proposed?}`` (an agent's tie, so it may untie only what it tied). A proposal
    (ruling 56: an agent not on the trust list) is not a tie until the person takes it: :func:`proposed_ties`."""
    raw = (fm or {}).get(key)
    return [e for e in (_entry_episode(x) for x in raw if not _is_proposal(x)) if e] if isinstance(raw, list) else []


def proposed_ties(fm: dict | None) -> list[dict]:
    """Conversation ties waiting for the person: never counted, never activity, shown on the project's page."""
    raw = (fm or {}).get(ADDED_KEY)
    return [dict(x) for x in raw if _is_proposal(x) and _entry_episode(x)] if isinstance(raw, list) else []


def tie_row(fm: dict | None, episode: str) -> dict | None:
    """The agent's row that tied ``episode``, or ``None`` (the person's bare id, or no hand tie)."""
    for x in (fm or {}).get(ADDED_KEY) or []:
        if isinstance(x, dict) and _entry_episode(x) == episode:
            return dict(x)
    return None


def clean_reason(reason, *, bank: str | None = None) -> str | None:
    """An agent's why, as a link row keeps it: one line, scrubbed (every writer scrubs), at most :data:`MAX_REASON`."""
    from api.services import episode_scrub

    text = " ".join(str(reason or "").split())
    if not text:
        return None
    scrubbed, n = episode_scrub.scrub(text)
    episode_scrub.record("project", n, bank=bank)
    return scrubbed[:MAX_REASON]


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


def unstarted(fm: dict | None, page: Path) -> bool:
    """A project page or fallback page that is not in the person's list and that they never took out of it: what an agent
    may offer to start, once, in its own words (ruling 56). Never a list, never an inbox question."""
    return is_project_like(fm) and not dismissed(fm) and not listed(fm, page)


def is_project_like(fm: dict | None) -> bool:
    """A project page, or a fallback page Cicada wrote for a thing called a project (``project_birth.proposed``)."""
    fm = fm or {}
    return str(fm.get("type") or "") == "project" or project_birth.proposed(fm)


def logged_progress_on_page(page: Path) -> bool:
    """:func:`logged_progress` from a page's path, for a pass over many pages. Cheap first: a page whose bytes never name
    the app's progress origin cannot pass (a copy of the owner's bank, 707 project pages: parsing each took ~95 ms warm;
    this read ~10), its ledger included."""
    from api.services.claims import parse_claims

    try:
        ledger = page.with_name(f"{page.stem}.claims.jsonl")
        hit = _HUMAN_PROGRESS_ORIGIN in page.read_text(encoding="utf-8", errors="replace") or (
            ledger.is_file() and _HUMAN_PROGRESS_ORIGIN in ledger.read_text(encoding="utf-8", errors="replace"))
        return hit and logged_progress(parse_claims(markdown_parser.parse(page).body))
    except Exception:  # noqa: BLE001 — an unreadable page is not the person's by this door
        return False


def listed(fm: dict | None, page: Path) -> bool:
    """The page is in the person's list, read from its frontmatter and, only when that leaves it open, its bytes."""
    return is_mine(fm) or (not dismissed(fm) and logged_progress_on_page(page))


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


def clean_description(text, *, bank: str | None = None) -> str:
    """The person's words with their paragraphs and line breaks kept: runs of spaces inside a line fold to one, each
    line is trimmed, and more than one blank line folds to one. Every door that writes a description comes through here
    (create, the header's PATCH, ``page_edits``, a provider import), so it scrubs: secrets and one-time codes redacted
    first, the count ledgered as ``project`` (every writer scrubs; ``backlog._scrub``'s R-B10)."""
    from api.services import episode_scrub

    scrubbed, n = episode_scrub.scrub(str(text or ""))
    episode_scrub.record("project", n, bank=bank)
    out = clean_description_lenient(scrubbed)
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


def revive(fm: dict, day: str) -> bool:
    """A person starting a project is a mention of it: a faded or archived page comes back, or it would be listed and
    missing from what an arriving agent is told until Sleep next heard it. `conflict_resolver`'s mention rule, in small."""
    from api.services.conflict_resolver import RECOVERY_CONFIDENCE

    if str(fm.get("status") or "active") in ("decaying", "archived"):
        fm["status"] = "active"
        fm["confidence"] = max(float(fm.get("confidence", 0.0) or 0.0), RECOVERY_CONFIDENCE)
    fm.pop(decay_policy.FADED_BY_AGE_KEY, None)
    fm["last_referenced"] = day
    fm["decayed_through"] = day
    return True


def start_target(memory_path: Path, name: str) -> str | None:
    """The page a start under ``name`` adopts, or ``None`` when no page answers to the name. Raises
    :class:`OwnershipError` in words when pages answer and none can be adopted, or two could and nothing tells them
    apart: a name is never minted beside a page that holds it, and one is never picked by listing order."""
    want, sid = project_birth.fold(name), sanitize_id(name)
    hits: list[tuple[str, dict]] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("status") or "active") == "dropped":
            continue
        if f.stem == sid or want in project_birth.name_folds({"name": fm.get("name") or f.stem,
                                                             "aliases": fm.get("aliases") or []}):
            hits.append((f.stem, fm))
    if not hits:
        return None
    from api.services import github_repos

    can = [(stem, fm) for stem, fm in hits if str(fm.get("type") or "concept") in ADOPTABLE
           and fm.get("owner") is not True and not github_repos.is_repository_page(fm)]
    if not can:
        raise OwnershipError(f"'{name}' is already a page in memory ({hits[0][0]}). Use that page instead.")
    rank = min(ADOPTABLE.index(str(fm.get("type") or "concept")) for _, fm in can)
    best = [stem for stem, fm in can if ADOPTABLE.index(str(fm.get("type") or "concept")) == rank]
    if len(best) > 1:
        if sid in best:
            return sid
        raise OwnershipError(f"Several pages answer to '{name}': {', '.join(sorted(best))}. Say which by its id.")
    return best[0]


def start(memory_path: Path, stem: str, desc: str = "", *, via: str, by: str, session: str | None = None,
          episode: str | None = None, span: dict | None = None, today: date | None = None,
          repo_seen: dict | None = None) -> list[str]:
    """Start a project from a page that already exists: the person's act, or a trusted agent's on their ask. The page
    keeps its id, body, claims and history; a concept or tool becomes the project in place, a signal Sleep recorded
    stays as ``born``, a mark that said it was not theirs is lifted, and a description is set only when one is given.
    Idempotent."""
    day = _today(today)

    def change(fm: dict):
        if str(fm.get("type") or "concept") not in ADOPTABLE:
            raise OwnershipError(f"{stem!r} can't become a project.")
        birth: dict = {"origin": "created", "via": via, "day": day}
        if via == VIA_AGENT:
            birth["by"] = by
            if session:
                birth["session"] = session
        if episode:
            birth["episode"] = episode
        if span:
            birth["span"] = span
        if repo_seen:
            birth["repo"] = repo_seen
        changed = project_birth.start_page(fm, birth)
        if fm.pop(NOT_MINE_KEY, None) is not None:
            changed = True
        if _dict(fm.get(MINE_KEY)) is None:
            fm[MINE_KEY] = _mark(via, by=by, day=day, session=session)
            changed = revive(fm, day)
        if str(desc or "").strip():
            changed = bool(apply_header(fm, desc=desc, by=by, day=day, session=session,
                                        bank=Path(memory_path).name)) or changed
        return changed or False

    return _rewrite(memory_path, stem, change)


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
           today: date | None = None, repo_seen: dict | None = None) -> tuple[str, list[str]]:
    """A new project page the person (or an agent on their ask) started: ``(id, paths written)``. ``born`` says it was
    created and through which door; ``mine`` is written only when ``listed`` (the person's own doors, or a trusted
    agent). Raises :class:`OwnershipError` for a name already taken: a start goes through :func:`start_target` first.
    ``repo_seen`` is the hook's observation of the checkout when the agent said the project IS this repository."""
    memory_path = Path(memory_path)
    name = clean_name(name)
    desc = clean_description(desc, bank=memory_path.name)
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
    if repo_seen:
        born["repo"] = repo_seen
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
    elif via == VIA_AGENT:
        # Ruling 56: another client's proposal is a quiet concept until the person takes it in the inbox.
        fm["type"] = project_birth.FALLBACK_TYPE
        fm[project_birth.PROPOSED_KEY] = "project"
    if provider:
        fm[PROVIDER_KEY] = [provider]
    page = memory_path / "entities" / f"{eid}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    lead = " ".join(desc.split()) if desc else name
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
    """The person adds an existing page to their projects ("Add to my projects"). A fallback concept becomes the project
    in place (``project_birth.start_page``); a "not mine" is lifted. Idempotent."""
    day = _today(today)

    def change(fm: dict):
        if not is_project_like(fm):
            raise OwnershipError(f"{stem!r} is not a project.")
        if project_birth.proposed(fm):
            project_birth.start_page(fm, {"origin": "created", "via": VIA_ACCEPTED, "day": day})
        if name:
            _rename(fm, clean_name(name))
        changed = fm.pop(NOT_MINE_KEY, None) is not None
        if _dict(fm.get(MINE_KEY)) is None:
            fm[MINE_KEY] = _mark(VIA_ACCEPTED, by=by, day=day)
            changed = revive(fm, day)
        return changed or None

    return _rewrite(memory_path, stem, change)


def dismiss(memory_path: Path, stem: str, *, today: date | None = None) -> list[str]:
    """"Remove from my projects": the page leaves the person's list, never archived or deleted. A page a start retyped goes
    back to what it was (`project_birth.undo_start`); a project page can be added again from its own head."""
    day = _today(today)

    def change(fm: dict):
        if not is_project_like(fm):
            raise OwnershipError(f"{stem!r} is not a project.")
        if dismissed(fm) and MINE_KEY not in fm:
            return False
        fm.pop(MINE_KEY, None)
        fm[NOT_MINE_KEY] = {"day": day}
        project_birth.undo_start(fm)
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
                 session: str | None = None, bank: str | None = None) -> list[str]:
    """Rename (the slug never changes; the old name becomes an alias) and set the description with its blame, in a
    frontmatter dict. Returns the changes, in words. ``page_edits.plan`` and the app's PATCH both come through here."""
    changes: list[str] = []
    if name is not None and _rename(fm, clean_name(name)):
        fm["name_by"] = {"by": by, "day": day}      # a source's later rename never overrides it (ROR-122, source_names)
        changes.append("renamed")
    if desc is not None:
        text = clean_description(desc, bank=bank)
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
        return bool(apply_header(fm, name=name, desc=desc, by=by, day=day, session=session,
                                 bank=Path(memory_path).name)) or False

    return _rewrite(memory_path, stem, change)


def conversation_episodes(memory_path: Path, episode: str) -> list[str]:
    """Every episode of the conversation ``episode`` belongs to — the same session id, else the same source id
    (`project_timeline._conv_key`'s rule), oldest first; the episode alone when it has neither."""
    files = {f.stem: f.frontmatter or {} for f in bank_index.files(Path(memory_path), "episodes")}
    fm = files.get(episode) or {}
    for key in ("session_id", "source_id"):
        value = str(fm.get(key) or "").strip()
        if value:
            return sorted(stem for stem, efm in files.items() if str(efm.get(key) or "").strip() == value)
    return [episode]


@page_lock.locked
def tie(memory_path: Path, stem: str, episode: str, *, remove: bool = False, by: str = "user",
        session: str | None = None, trusted: bool = True, reason: str | None = None) -> list[str]:
    """Tie a conversation to the project by hand, or untie it — every episode of the conversation at once
    (:func:`conversation_episodes`), in one page write, so a conversation never comes back through an older episode.

    The person's untie overrides every automatic signal and no signal re-adds it (the ``sources_removed`` rule); tying
    it again lifts the untie. An agent's tie is recorded with its name and its reason; an agent on the person's trust
    list ties at once, any other only proposes (``proposed: true``, ruling 56: never counted until the person takes it).
    An agent may untie only what it tied (the "withdraw only what it wrote" rail), which drops its tie and never marks
    the conversation untied. Every check runs before anything is written: a refusal writes nothing."""
    from api.services import evidence

    if not evidence.is_episode_id(episode):
        raise OwnershipError(f"{episode!r} is not a conversation id (like ep_2026-10-01_001).")
    if not (Path(memory_path) / "episodes" / f"{episode}.md").is_file():
        raise OwnershipError(f"No conversation {episode!r}.")
    episodes = conversation_episodes(memory_path, episode) or [episode]
    person = by == "user"
    why = clean_reason(reason, bank=Path(memory_path).name)

    def change(fm: dict):
        if not is_project_like(fm):
            raise OwnershipError(f"{stem!r} is not a project.")
        added = [x for x in (fm.get(ADDED_KEY) or []) if _entry_episode(x)]
        removed = [x for x in (fm.get(REMOVED_KEY) or []) if _entry_episode(x)]
        untied = set(tied(fm, REMOVED_KEY))
        ours = set(episodes)
        if remove:
            if not person:
                mine = [x for x in added if _entry_episode(x) in ours and isinstance(x, dict) and x.get("by") == by]
                if not mine:
                    raise OwnershipError("You can untie only a conversation you tied; the person decides the rest in "
                                         "the app.")
                added = [x for x in added if not any(x is m for m in mine)]
            else:
                if ours <= untied and not any(_entry_episode(x) in ours for x in added):
                    return False
                added = [x for x in added if _entry_episode(x) not in ours]
                removed += [e for e in episodes if e not in untied]
        else:
            if ours & untied and not person:
                raise OwnershipError("The person untied that conversation from this project; it stays untied.")
            removed = [x for x in removed if _entry_episode(x) not in ours]
            if person or trusted:   # the person, or a trusted agent, turns a waiting proposal into a tie
                added = [x for x in added if not (_is_proposal(x) and _entry_episode(x) in ours)]
            have = {_entry_episode(x) for x in added}
            missing = [e for e in episodes if e not in have]
            if not missing and not (ours & untied):
                return False
            for e in missing:
                added.append(e if person else {"episode": e, "by": by, **({"session": session} if session else {}),
                                               **({"reason": why} if why else {}),
                                               **({} if trusted else {"proposed": True})})
        for key, rows in ((ADDED_KEY, added), (REMOVED_KEY, removed)):
            if rows:
                fm[key] = rows[-MAX_TIED:]
            else:
                fm.pop(key, None)
        return None

    return _rewrite(memory_path, stem, change)


# --- pages tied by hand (decision 10, 2026-10-28) ----------------------------------------------------------------------


def _entry_page(x) -> str | None:
    if isinstance(x, str) and x.strip():
        return x.strip()
    if isinstance(x, dict) and isinstance(x.get("entity"), str) and x["entity"].strip():
        return x["entity"].strip()
    return None


def page_entries(fm: dict | None, key: str) -> list:
    """The raw rows of ``entities_added`` / ``entities_removed``: a bare page id (the person's) or ``{entity, by,
    session?, reason?, proposed?}`` (an agent's — ``proposed`` when that agent is not on the person's trust list)."""
    raw = (fm or {}).get(key)
    return [x for x in raw if _entry_page(x)] if isinstance(raw, list) else []


def pages(fm: dict | None, key: str) -> list[str]:
    return list(dict.fromkeys(e for e in (_entry_page(x) for x in page_entries(fm, key)) if e))


def page_tie(fm: dict | None, entity: str) -> dict | None:
    """How ``entity`` was tied by hand: ``{by: user}`` for the person's, else the agent's row (``proposed`` kept)."""
    for x in page_entries(fm, PAGES_ADDED_KEY):
        if _entry_page(x) == entity:
            return {"by": "user"} if isinstance(x, str) else dict(x)
    return None


@page_lock.locked
def tie_page(memory_path: Path, stem: str, entity: str, *, remove: bool = False, by: str = "user",
             session: str | None = None, trusted: bool = True, reason: str | None = None) -> list[str]:
    """Tie a page to the project by hand ("Add"), or say it is "Not part of it".

    The person's word is final both ways: their "Not part of it" wins over every automatic tie (a claim, an event's
    participant) and no agent re-adds it; their Add lifts it, and turns an agent's proposal into their own tie. An
    agent on the person's trust list (G198, ``page_editors``) ties at once; any other agent's tie is recorded as a
    PROPOSAL (``proposed: true``) the person takes or turns down on the panel — never drawn as part of the project
    until then. An agent removes only what it tied or proposed (the withdraw-only-what-it-wrote rail) and never marks a
    page "Not part of it". Every check runs before anything is written: a refusal writes nothing."""
    from api.services.id_utils import resolve_entity_file

    page = resolve_entity_file(memory_path, str(entity or "").strip())
    if page is None:
        raise OwnershipError(f"No page {entity!r}.")
    target = page.stem
    if target == stem:
        raise OwnershipError("A project is not a page of itself.")
    tfm = markdown_parser.parse(page, ledger=False).frontmatter or {}
    if str(tfm.get("status") or "active") == "dropped":
        raise OwnershipError(f"{target!r} was dropped from memory.")
    if tfm.get("owner") is True:
        raise OwnershipError("The person's own page is part of every project; it is never tied by hand.")
    # A sub-project is the project's own tree (`part-of`, `project_timeline._tree`) and is listed under its parent,
    # never in "Pages in this project": a tie or an untie would be written and never shown.
    from api.services.project_timeline import _Bank, _tree

    tree = _tree(_Bank(memory_path, None), stem)[0]
    if target in tree[1:]:
        project_name = str((markdown_parser.parse(_page(memory_path, stem), ledger=False).frontmatter or {})
                           .get("name") or stem)
        raise OwnershipError(f"{target!r} is already a sub-project of {project_name}; it shows under it in the list.")
    person = by == "user"
    why = clean_reason(reason, bank=Path(memory_path).name)

    def change(fm: dict):
        if not is_project_like(fm):
            raise OwnershipError(f"{stem!r} is not a project.")
        added = page_entries(fm, PAGES_ADDED_KEY)
        removed = page_entries(fm, PAGES_REMOVED_KEY)
        untied = target in {_entry_page(x) for x in removed}
        mine = [x for x in added if _entry_page(x) == target]
        if remove:
            if person:
                if untied and not mine:
                    return False
                added = [x for x in added if _entry_page(x) != target]
                if not untied:
                    removed.append(target)
            else:
                own = [x for x in mine if isinstance(x, dict) and x.get("by") == by]
                if not own:
                    raise OwnershipError("You can take back only a page you tied; the person decides the rest in the "
                                         "app.")
                added = [x for x in added if not any(x is o for o in own)]
        else:
            if untied and not person:
                raise OwnershipError("The person said that page is not part of this project; it stays out.")
            if person:
                if any(isinstance(x, str) for x in mine) and not untied:
                    return False
                added = [x for x in added if _entry_page(x) != target] + [target]
                removed = [x for x in removed if _entry_page(x) != target]
            else:
                if mine:
                    return False
                row = {"entity": target, "by": by}
                if session:
                    row["session"] = session
                if why:
                    row["reason"] = why
                if not trusted:
                    row["proposed"] = True
                added.append(row)
        for key, rows in ((PAGES_ADDED_KEY, added), (PAGES_REMOVED_KEY, removed)):
            if rows:
                fm[key] = rows[-MAX_TIED:]
            else:
                fm.pop(key, None)
        return None

    return _rewrite(memory_path, stem, change)


def repository_page(memory_path: Path, entity: str) -> str | None:
    """The GitHub repository page ``entity`` names (an id or a name; ruling 53), else ``None``."""
    from api.services import github_repos
    from api.services.id_utils import resolve_entity_file

    ref = str(entity or "").strip()
    page = resolve_entity_file(memory_path, ref) if ref else None
    if page is None:
        return None
    fm = markdown_parser.parse(page, ledger=False).frontmatter or {}
    return page.stem if github_repos.is_repository_page(fm) and github_repos.page_repo(fm) else None


def check_attachable(memory_path: Path, entity: str) -> str:
    """The page id the person may attach to a new project, or :class:`OwnershipError` in words — the checks
    :func:`tie_page` makes that do not need the project, run before anything is written."""
    from api.services.id_utils import resolve_entity_file

    page = resolve_entity_file(memory_path, str(entity or "").strip()) if str(entity or "").strip() else None
    if page is None:
        raise OwnershipError(f"No page {entity!r}.")
    fm = markdown_parser.parse(page, ledger=False).frontmatter or {}
    if str(fm.get("status") or "active") == "dropped":
        raise OwnershipError(f"{page.stem!r} was dropped from memory.")
    if fm.get("owner") is True:
        raise OwnershipError("The person's own page is part of every project; it is never tied by hand.")
    return page.stem


def attach(memory_path: Path, stem: str, entity: str, *, remove: bool = False) -> list[str]:
    """The person attaches a page to their project, or takes it off — one door for every kind of page (owner
    2026-11-04: "selecting entity pages from different sources … that will be linked to a project"). A GitHub
    repository page becomes one of the project's repositories (ruling 53: ``github_repos.link``, the one writer of
    ``repositories:``); every other page is a hand tie (:func:`tie_page`). Taking a repository off unlinks it
    (remembered) and says "Not part of it" as well, so no automatic layer draws it back; adding one the person had
    taken off lifts that. Raises :class:`OwnershipError` in words."""
    repo = repository_page(memory_path, entity)
    project = markdown_parser.parse(_page(memory_path, stem), ledger=False).frontmatter or {}
    if repo is None or str(project.get("type") or "") != "project":
        return tie_page(memory_path, stem, entity, remove=remove)
    from api.services import github_repos

    try:
        paths = github_repos.link(memory_path, stem, repo, remove=remove)
    except (LookupError, github_repos.LinkRefused) as exc:
        raise OwnershipError(f"Nothing changed — {exc}") from exc
    if remove or repo in pages(project, PAGES_REMOVED_KEY):
        paths += tie_page(memory_path, stem, repo, remove=remove)
    return list(dict.fromkeys(paths))


def create_with_pages(memory_path: Path, name: str, desc: str, pages, *, via: str, by: str = "user",
                      today: date | None = None) -> tuple[str, list[str], list[str]]:
    """New project with the pages the person attached: ``(id, every path written, the paths created)`` — all or
    nothing (review of #595, B1). A name a page already answers to starts that page (:func:`start_target`, ruling 56),
    so nothing is created. Each page is checked first (:func:`check_attachable`); a check that can only run once the
    page exists (a ``part-of`` claim naming the new project by its name makes that page its sub-project, which
    :func:`tie_page` refuses) runs in :func:`attach`, and any failure there — or any other exception — takes back every
    file this call wrote: a new page is removed, and an adopted page and each repository page whose back-link was
    written are restored byte for byte, so a refusal leaves no orphan behind and a retry is not told the name is taken."""
    memory_path = Path(memory_path)
    name = clean_name(name)
    targets = list(dict.fromkeys(check_attachable(memory_path, p) for p in pages))
    adopt = start_target(memory_path, name)
    targets = [t for t in targets if t != adopt]
    # What `attach` may rewrite besides the project: a repository page's back-link (`github_repos.sync_backlinks`).
    saved = {}
    for stem in [*targets, *([adopt] if adopt else [])]:
        if stem == adopt or repository_page(memory_path, stem):
            f = memory_path / "entities" / f"{stem}.md"
            saved[f] = f.read_bytes()
    if adopt:
        eid, created = adopt, []
        paths = start(memory_path, adopt, desc, via=via, by=by, today=today)
    else:
        eid, created = create(memory_path, name, desc, via=via, by=by, listed=True, today=today)
        paths = list(created)
    try:
        for page in targets:
            paths += attach(memory_path, eid, page)
    except BaseException:
        _take_back(memory_path, eid if not adopt else None, saved)
        raise
    return eid, list(dict.fromkeys(paths)), list(created)


@page_lock.locked
def _take_back(memory_path: Path, eid: str | None, saved: dict) -> None:
    for suffix in (".md", ".claims.jsonl") if eid else ():
        (Path(memory_path) / "entities" / f"{eid}{suffix}").unlink(missing_ok=True)
    for f, data in saved.items():
        tmp = f.with_name(f".{f.name}.restore")
        tmp.write_bytes(data)
        tmp.replace(f)
    bank_index.invalidate()


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
    gone = list(dict.fromkeys(pages(winner_fm, PAGES_REMOVED_KEY) + pages(loser_fm, PAGES_REMOVED_KEY)))
    kept, seen = [], set()
    for x in page_entries(winner_fm, PAGES_ADDED_KEY) + page_entries(loser_fm, PAGES_ADDED_KEY):
        e = _entry_page(x)
        if e and e not in seen and e not in gone:
            seen.add(e)
            kept.append(x)
    for key, rows in ((PAGES_ADDED_KEY, kept), (PAGES_REMOVED_KEY, gone)):
        if rows:
            winner_fm[key] = rows[-MAX_TIED:]
    _carry_repositories(winner_fm, loser_fm)


def _carry_repositories(winner_fm: dict, loser_fm: dict) -> None:
    """G230 / ruling 53: a project's repositories (``repositories:``) and the person's unlinks
    (``repositories_removed:``) union across a merge; an unlink on either side wins, as an untie does, so no automatic
    link (``github_repos.link_by_origin``) puts back what the person took off either page."""
    from api.services import github_repos

    gone = list(dict.fromkeys(
        [u for u in winner_fm.get(github_repos.REPOS_REMOVED_KEY) or [] if isinstance(u, str)]
        + [u for u in loser_fm.get(github_repos.REPOS_REMOVED_KEY) or [] if isinstance(u, str)]))
    dropped = {github_repos._norm(u) for u in gone}
    rows, seen = [], set()
    for row in github_repos.link_entries(winner_fm) + github_repos.link_entries(loser_fm):
        url = github_repos._norm(row["url"])
        if url in seen or url in dropped:
            continue
        seen.add(url)
        rows.append(row)
    for key, value in ((github_repos.REPOS_KEY, rows), (github_repos.REPOS_REMOVED_KEY, gone)):
        if value:
            winner_fm[key] = value
        else:
            winner_fm.pop(key, None)


# --- provider groupings ----------------------------------------------------------------------------------------------

#: A bank file for what has no page to carry it: the provider project ids already imported. In the bank (it travels with
#: it), committed under the person.
GROUPINGS_FILE = "project_groupings.yaml"


def read_groupings(memory_path: Path) -> dict:
    """The whole groupings file (``dismissed`` and ``imported``), or ``{}``. Every writer reads it whole and changes
    only its own key (:func:`update_groupings`), so one writer never drops the other's list."""
    path = Path(memory_path) / GROUPINGS_FILE
    try:
        data = markdown_parser.load_yaml(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update_groupings(memory_path: Path, key: str, value) -> list[str]:
    """Set one key of the groupings file, keeping every other key as it is."""
    data = read_groupings(memory_path)
    if data.get(key) == value:
        return []
    data[key] = value
    markdown_parser.write_yaml(Path(memory_path) / GROUPINGS_FILE, data)
    return [GROUPINGS_FILE]
