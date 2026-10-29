"""Where a project page comes from (G141, TODO ruling 36 D4).

A project page is born from one of two things, never from consolidation alone:

* **a repository** the person works in with an agent: a harness session whose episode carries the hook's own
  observation of a git checkout (``workspace_identity`` with a ``family_hash``, G110 D2) and whose ``project_dir``
  names the thing Stage 1 called a project. The backend reads only those two stored values; it never opens, stats or
  runs git in the path. The hook observes no remote (D2 allows only the ``rev-parse`` pair), so the repository's name
  is read from the stored path itself: its last component, or the one before a ``.worktrees``/``worktrees`` folder.
* **the person's own words** saying it is a project: one sentence of their own turn (or another person's in a
  meeting) that names the thing beside a word for "project" (a few languages, :data:`PROJECT_WORD`), located exactly
  in the conversation and kept as a span, never a copy (G118).
* A watched folder the person named in the app (``folder_source.ensure_project``) is the person's own words too: they
  typed the name. Its ``born`` says ``via: folder``.

Everything else Stage 1 calls a project is never a project page. Below the promotion bar it waits as a mention in the
pending store, as any name does (``pending_store``). Over the bar — counted over every spelling the judge says is the
same thing — it gets a **fallback page** (owner 2026-10-23): a ``concept`` marked :data:`PROPOSED_KEY`, so it shows in
the app; a later repository or the person's words make that page the project (:func:`retype_on_birth`), never a
second page (``entity_resolver._settle_unborn``). Pages born before this rule are
never archived or deleted for it: :func:`classify` says, per page, which origin the bank can show and why, and the
dry run (``python -m api.scripts.project_origins``) lists them for the owner to read.

The ``born`` frontmatter key is written once, where the page is born, and never rewritten:
``{origin: repo|words, day, episode, repo?: {name, family}, span?: {start, end, hash, kind}, via?: folder}``.
"""
from __future__ import annotations

import posixpath
import re
from functools import lru_cache
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from api.services import authorship, evidence, promotion, workspace_identity

REPO, WORDS = "repo", "words"

#: The word that makes a sentence say "this is a project", in the languages the owner's conversations use, plus the
#: two nearest. A whole word, any case; plural included.
PROJECT_WORD = re.compile(r"(?<!\w)(?:projects?|proyectos?|projets?|projekte?|progett[oi]|projetos?)(?!\w)",
                          re.IGNORECASE)
#: How many words may stand between the name and the project word, inside one clause ("my garden-plan project", "the
#: project I call garden-plan", "garden-plan is going to be my project"). Further apart, or across a comma, the
#: sentence is about two things.
MAX_GAP_WORDS = 5
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_WORD = re.compile(r"\w+")
_CLAUSE_BREAK = re.compile(r"[,;:()]")
_WORKTREE_DIRS = frozenset({".worktrees", "worktrees", ".worktree"})


@lru_cache(maxsize=65536)
def fold(name: str) -> str:
    """A name as a repository's folder would spell it: no accents, no case, letters and digits only. Remembered per
    name (speed 2026-10-29: the Projects list folds every page's names on every read, ~8k a call)."""
    decomposed = unicodedata.normalize("NFD", name or "")
    return "".join(c for c in decomposed if c.isalnum() and not unicodedata.combining(c)).lower()


def _names(entity: dict) -> list[str]:
    name = str(entity.get("name") or "").strip()
    out = [name, re.sub(r"\s*\([^)]*\)\s*$", "", name), *(str(a) for a in entity.get("aliases") or [] if a)]
    seen, names = set(), []
    for n in out:
        n = n.strip()
        if len(fold(n)) >= 2 and n.lower() not in seen:
            seen.add(n.lower())
            names.append(n)
    return names


# --- the repository -------------------------------------------------------------------------------------------------


def repo_names(project_dir) -> list[str]:
    """The names a stored checkout path gives its repository, read from the string alone (no I/O): its last
    component, and the one before a worktrees folder (``…/alpha/.worktrees/fix-x`` is ``alpha``)."""
    if not isinstance(project_dir, str) or not project_dir.startswith("/"):
        return []
    parts = [p for p in posixpath.normpath(project_dir).split("/") if p]
    out = parts[-1:]
    for i, part in enumerate(parts):
        if part in _WORKTREE_DIRS and i:
            out.append(parts[i - 1])
    return list(dict.fromkeys(out))


def observed_repo(frontmatter: dict) -> dict | None:
    """``{family, names}`` when an episode was captured in a git checkout the hook observed, else ``None``.

    The observation must be bound to the stored ``project_dir`` (its ``cwd_hash``) and carry a family: a failed or
    foreign observation is no repository."""
    fm = frontmatter or {}
    cwd = fm.get("project_dir")
    seen = workspace_identity.clean(fm.get("workspace_identity"))
    if not seen or "family_hash" not in seen or not isinstance(cwd, str):
        return None
    if seen["cwd_hash"] not in (workspace_identity.digest(cwd), workspace_identity.digest(posixpath.normpath(cwd))):
        return None
    names = repo_names(cwd)
    return {"family": seen["family_hash"], "names": names} if names else None


def name_folds(entity: dict) -> set[str]:
    """The folded names (:func:`fold`) a repository named for ``entity`` could carry — the keys :func:`repo_match`
    compares, for a caller matching many episodes against many pages at once."""
    return {f for f in (fold(n) for n in _names(entity)) if len(f) >= 2}


def repo_match(entity: dict, frontmatter: dict) -> dict | None:
    """``{name, family}`` when the entity is the repository this episode was captured in."""
    repo = observed_repo(frontmatter)
    if repo is None:
        return None
    by_fold = {fold(n): n for n in repo["names"] if len(fold(n)) >= 2}
    for name in _names(entity):
        hit = by_fold.get(fold(name))
        if hit is not None:
            return {"name": hit, "family": repo["family"]}
    return None


# --- the person's words ---------------------------------------------------------------------------------------------


def _name_pattern(entity: dict) -> re.Pattern | None:
    names = _names(entity)
    if not names:
        return None
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def _close(sentence: str, a: tuple[int, int], b: tuple[int, int]) -> bool:
    """The name and the project word sit in one clause, at most :data:`MAX_GAP_WORDS` words apart."""
    lo, hi = (a[1], b[0]) if a[0] <= b[0] else (b[1], a[0])
    between = sentence[lo:hi]
    if lo > hi:
        return False
    if b[0] < a[0]:
        # "New project with Teo: fernpost" — a colon after the project word's clause introduces its name, when the
        # name is the first thing after it (benchmarks/newuser, owner 2026-10-22). A name BEFORE a colon still
        # starts a new thought ("fernpost: the project at work …").
        head, colon, tail = between.rpartition(":")
        if colon and not tail.strip() and not _CLAUSE_BREAK.search(head) \
                and len(_WORD.findall(head)) <= MAX_GAP_WORDS:
            return True
    return not _CLAUSE_BREAK.search(between) and len(_WORD.findall(between)) <= MAX_GAP_WORDS


def said_project(entity: dict, text: str, *, override: str | None = None, gaps=(),
                 persons: frozenset[str] = promotion.PERSON_KINDS) -> evidence.Evidence | None:
    """The first sentence of a person's own turn that names the entity beside a project word, as a span into
    ``text`` (the episode's evidence text), or ``None``. Exact and case-insensitive, never fuzzy; the model's
    turns, a video's and a quoted page's never count (``promotion.PERSON_KINDS``)."""
    pattern = _name_pattern(entity)
    if pattern is None or not text:
        return None
    for turn in evidence.turns(text, override=override, gaps=gaps):
        if turn.role not in persons:
            continue
        words = text[turn.content_start:turn.end]
        for s in _SENTENCE.finditer(words):
            sentence = s.group(0)
            names = [m.span() for m in pattern.finditer(sentence)]
            marks = [m.span() for m in PROJECT_WORD.finditer(sentence)]
            if any(_close(sentence, n, w) for n in names for w in marks):
                lead = len(sentence) - len(sentence.lstrip())
                start = turn.content_start + s.start() + lead
                end = turn.content_start + s.start() + len(sentence.rstrip())
                if evidence.touches_gap(start, end, gaps):
                    continue
                return evidence.Evidence(episode="", start=start, end=end, kind=turn.role,
                                         hash=evidence.body_hash(text))
    return None


# --- birth, where Stage 1 reads a conversation ----------------------------------------------------------------------


def at_extraction(entity: dict, *, episode_id: str, frontmatter: dict, text: str, day: str | None,
                  override: str | None = None, gaps=()) -> dict | None:
    """The ``born`` record a project entity earns in this conversation, or ``None``. A repository wins over words
    when both hold (the stronger, steadier origin)."""
    base = {"day": day, "episode": episode_id} if day else {"episode": episode_id}
    repo = repo_match(entity, frontmatter)
    if repo is not None:
        return {"origin": REPO, **base, "repo": repo}
    span = said_project(entity, text, override=override, gaps=gaps, persons=promotion.person_kinds(frontmatter))
    if span is not None:
        return {"origin": WORDS, **base,
                "span": {"start": span.start, "end": span.end, "hash": span.hash, "kind": span.kind}}
    return None


def birth_of(entity: dict, siblings=()) -> dict | None:
    """The first ``born`` record among one name's extractions in a batch, oldest conversation first."""
    found = [e.get("project_birth") for e in (entity, *siblings) if isinstance(e.get("project_birth"), dict)]
    return min(found, key=lambda b: (str(b.get("day") or "~"), str(b.get("episode") or ""))) if found else None


def folder_birth(day: str) -> dict:
    """The person named a watched folder as a project in the app."""
    return {"origin": WORDS, "day": day, "via": "folder"}


# --- the fallback page (owner 2026-10-23, amends D4) ----------------------------------------------------------------

#: The frontmatter key a fallback page carries: Stage 1 called the thing a project, nothing gave it a birth, and it
#: cleared the promotion bar, so it was written as :data:`FALLBACK_TYPE` instead of waiting unseen in the pending
#: store. The key is what lets a later birth retype that page (:func:`retype_on_birth`) and lets a later project
#: mention of the same thing be judged against it (``entity_resolver._candidate_types``).
PROPOSED_KEY = "proposed_type"
#: ``concept`` is the closed set's general type (``entity_types.FALLBACK``): of the ten, the only one that holds an
#: endeavour that is not a person, organisation, place, tool, skill or folder — a canoe being built, a garden plan.
FALLBACK_TYPE = "concept"


def proposed(frontmatter: dict | None) -> bool:
    """The page is a fallback page: written as a concept for a thing Stage 1 called a project."""
    return str((frontmatter or {}).get(PROPOSED_KEY) or "").lower() == "project"


def retype_on_birth(frontmatter: dict, birth) -> bool:
    """A fallback page whose thing the person later calls a project in their own words (or a repository gives it):
    the page becomes the project, its ``born`` written once and the marker gone. True when it changed.

    Only a page this fallback wrote — a ``concept`` carrying :data:`PROPOSED_KEY` and no ``born`` — is ever retyped:
    a project page, a page born with any other type, or one the person retyped by hand is left as it is."""
    fm = frontmatter
    if (not isinstance(birth, dict) or not proposed(fm) or str(fm.get("type") or "").lower() != FALLBACK_TYPE
            or isinstance(fm.get("born"), dict)):
        return False
    fm["type"] = "project"
    fm["born"] = birth
    fm.pop(PROPOSED_KEY, None)
    return True


# --- reading it back ------------------------------------------------------------------------------------------------


def quote(memory_path: Path, born: dict) -> str | None:
    """The person's sentence a ``words`` birth points at, while the conversation still holds it byte for byte
    (``evidence.span_status``: current, or grown by appended turns), else ``None``."""
    span = (born or {}).get("span")
    if not isinstance(span, dict):
        return None
    text = evidence.source_text(memory_path, str(born.get("episode") or ""))
    try:
        start, end = int(span.get("start")), int(span.get("end"))
    except (TypeError, ValueError):
        return None
    if text is None or not 0 <= start < end <= len(text):
        return None
    status = evidence.span_status(text, end=end, hash=str(span.get("hash") or ""))
    return text[start:end] if status in (evidence.SPAN_CURRENT, evidence.SPAN_GROWN) else None


@dataclass
class Origin:
    """How a project page's birth reads: ``kind`` is ``repo``, ``words`` or ``None`` (neither); ``stored`` says the
    page carries its ``born`` record (else it was derived now, from what the bank holds); ``why`` is one sentence."""

    kind: str | None
    why: str
    stored: bool = False
    day: str | None = None
    episode: str | None = None
    repo: dict | None = None
    span: dict | None = None
    via: str | None = None
    episodes_read: int = 0


def _from_born(born: dict) -> Origin:
    kind = born.get("origin") if born.get("origin") in (REPO, WORDS) else None
    via = born.get("via")
    if kind == REPO:
        why = f"Born from the repository {((born.get('repo') or {}).get('name') or '?')!r}, where you work with an agent."
    elif via == "folder":
        why = "You named a watched folder as this project."
    elif kind == WORDS:
        why = "You said this is a project."
    else:
        why = "Its birth record names no origin Cicada knows."
    return Origin(kind=kind, why=why, stored=True, day=born.get("day"), episode=born.get("episode"),
                  repo=born.get("repo"), span=born.get("span"), via=via)


def classify(memory_path: Path, stem: str, frontmatter: dict, *, documents=None, limit: int | None = None) -> Origin:
    """Which origin a project page can show, and why. A stored ``born`` record answers. Otherwise it is derived, read
    only: a repository the person declared on the page (``repos:``), a watched folder they named (``paths:``), then
    each conversation the page cites — captured in a checkout of that name, or the person's own words calling it a
    project. ``documents(episode_id)`` returns ``(frontmatter, text)`` (the default reads the bank). ``limit`` reads at
    most that many cited conversations, oldest first (the wire's bound; the dry run reads them all)."""
    fm = frontmatter or {}
    born = fm.get("born")
    if isinstance(born, dict):
        return _from_born(born)
    if [r for r in fm.get("repos") or [] if r]:
        return Origin(kind=REPO, why="You declared a repository on this page.", via="declared")
    if [p for p in fm.get("paths") or [] if isinstance(p, dict)] or "folder" in (fm.get("tags") or []):
        return Origin(kind=WORDS, why="You named a watched folder as this project.", via="folder")
    entity = {"name": fm.get("name") or stem, "aliases": fm.get("aliases") or []}
    read = documents or (lambda ep: evidence.source_document(memory_path, ep))
    cited = [str(e) for e in fm.get("source_episodes") or [] if evidence.is_episode_id(str(e))]
    seen = 0
    words_hit: Origin | None = None
    for ep in sorted(dict.fromkeys(cited))[:limit]:
        doc = read(ep)
        if doc is None:
            continue
        seen += 1
        efm, text = doc
        repo = repo_match(entity, efm)
        if repo is not None:
            return Origin(kind=REPO, why=f"A conversation it cites was captured in the repository {repo['name']!r}.",
                          day=_day(efm, ep), episode=ep, repo=repo, episodes_read=seen)
        if words_hit is None:
            span = said_project(entity, text, override=authorship.of(efm), gaps=evidence.gap_ranges(efm, text),
                                persons=promotion.person_kinds(efm))
            if span is not None:
                words_hit = Origin(kind=WORDS, why="In a conversation it cites, you called it a project.",
                                   day=_day(efm, ep), episode=ep, episodes_read=seen,
                                   span={"start": span.start, "end": span.end, "hash": span.hash, "kind": span.kind})
    if words_hit is not None:
        words_hit.episodes_read = seen
        return words_hit
    missing = len(sorted(dict.fromkeys(cited))[:limit]) - seen
    why = (f"None of the {seen} conversation{'s' if seen != 1 else ''} it cites was captured in a repository of that "
           "name, and none has your own words calling it a project: consolidation alone made this page.")
    if limit is not None and len(dict.fromkeys(cited)) > limit:
        why += f" (Only the first {limit} conversations it cites were read here; the dry run reads them all.)"
    if not cited:
        why = "It cites no conversation, declares no repository and names no folder."
    elif missing:
        why += f" ({missing} cited conversation{'s are' if missing != 1 else ' is'} no longer in the bank.)"
    return Origin(kind=None, why=why, episodes_read=seen)


def _day(fm: dict, ep: str) -> str | None:
    raw = str((fm or {}).get("timestamp") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        return raw[:10]
    m = re.match(r"^ep_(\d{4})(\d{2})(\d{2})", ep) or re.match(r"^ep_(\d{4})-(\d{2})-(\d{2})", ep)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


#: The cited conversations the detail wire reads to derive an older page's origin (a page cited by hundreds stays fast).
WIRE_LIMIT = 40


def wire(memory_path: Path, stem: str, frontmatter: dict, *, documents=None):
    """The Projects page's ``origin`` (``schemas.ProjectOrigin``) for one page."""
    from api.models.schemas import ProjectOrigin

    o = classify(memory_path, stem, frontmatter, documents=documents, limit=WIRE_LIMIT)
    said = quote(memory_path, {"episode": o.episode, "span": o.span}) if o.kind == WORDS and o.span else None
    return ProjectOrigin(kind=o.kind, stored=o.stored, why=o.why, day=o.day, episode=o.episode, quote=said,
                         repo_name=(o.repo or {}).get("name"), via=o.via)


def recorded_kind(frontmatter: dict) -> str | None:
    """The origin a page states without reading a conversation (the list's cheap answer): its birth record, a
    repository the person declared, or a watched folder they named."""
    fm = frontmatter or {}
    born = fm.get("born")
    if isinstance(born, dict):
        return born.get("origin") if born.get("origin") in (REPO, WORDS) else None
    if [r for r in fm.get("repos") or [] if r]:
        return REPO
    if [p for p in fm.get("paths") or [] if isinstance(p, dict)] or "folder" in (fm.get("tags") or []):
        return WORDS
    return None
