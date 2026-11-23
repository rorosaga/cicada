"""A correction reaches everything it touched (G104 slice 3, T3, owner 2026-11-23).

``episode_revision`` withdraws the claims only the removed text said and ``revision_prose`` rewrites the passages written
from it. What a consolidated edit also left behind — a page made only from the removed words, an alias it gave, a name
held for a page, a question it raised — is closed here, **by rule, with no engine**, and **never past independent
support**: a thing something else also supports (a later conversation, the person, an agent) is kept and listed.

Where it runs: once PER BATCH, in ``sleep_cycle`` after Stage 5.565 and before Stage 5.58 (a page archived here costs
``revision_prose`` no engine call), inside the write window, so every write rides the batch's one commit.
:func:`run` writes pages and the pending store only; **it never writes ``inbox/``**. The questions it would withdraw are
returned (``Report.questions``) and settled after the commit by ``inbox_tend``'s ``source_corrected`` rule through the
person's own resolver as Sleep's commit (undoable, ``inbox/<kind>/settled:``). That rule re-derives the same answer from
the bank alone (:func:`question_withdrawal`), so a stop between the commit and the settle leaves nothing half-decided.

What it closes
--------------
* **A page** only the removed text supported is archived (``status: archived``, ``removed_at`` and
  ``archived_by: {reason: revision, episode, day, prior_status, prior_confidence}``): *candidate* when it cites a revised
  conversation, is not new this batch, and either lost a claim to the revision or its name and aliases occurred in the
  version Sleep read and none occur in the new body (exact -> whitespace -> case-insensitive, never fuzzy). A candidate
  is kept when ANY support holds (:data:`SUPPORTS`, first match is reported). Never the owner's page, a project, a
  ``media`` page, a page a person or agent authored a commit on, anything pinned. Decay archives carry no
  ``archived_by``, so :func:`restore` never reopens one.
* **An alias** on a kept page that occurs only in the removed text (and in none of the page's other conversations) is
  dropped from ``aliases``, never added to ``aliases_removed`` (a later real mention may add it again). There is no alias
  provenance, so the guard is conservative (:func:`_droppable`).
* **A held name** (``pending_store``) whose name no longer occurs leaves the revised conversation's ``heard_in``; the
  held claims only that conversation said go with it; a line whose ONLY conversation it was is removed whole.
* **Held prose** (T6): a pending line also carries the first read's PROSE — ``summary``, ``description``, ``key_facts``,
  ``history_entries`` and the ``item_inputs`` rows that cite their source — which a page born from the line would be
  written from. :func:`drop_held_prose` runs BEFORE Stage 2 in the drain that reads the revision (a page is born from a
  line in that same drain) and drops each item whose rows are all this conversation at the version Sleep read and that
  says a word the revision removed (`revision_prose.changes_of`, the one test; ``sleep_cycle._words_taken``). An item
  that cites another conversation too, says no removed word, or has no row stays; a history entry (no row of its own) goes
  only from a line this conversation alone heard. Counted in ``held.prose_dropped`` and in no other count.
* **A question** (returned, not written): about a page this run archived; a conflict whose option claims the revision
  closed (all, or all but one); a name question raised from the revised conversation about a name no longer in it and
  with no other conversation.

The report (``Report.as_dict()``) — ids, enums and counts only, never a title, alias, held name or claim text; the
fold T4 turns into the run record, page History lines and the app's Corrections section::

    {"revised":         [episode id, ...],                       # revisions that removed words and could close
     "pages_archived":  [{"page": id, "episode": id, "claims": [claim id, ...]}],     # claims = what it lost
     "pages_kept":      [{"page": id, "episode": id, "support": <enum of SUPPORTS>, "claims": [claim id, ...]}],
     "aliases_dropped": [{"page": id, "episode": id, "count": n}],
     "held":            {"lines_removed": n, "episodes_left": n, "claims_dropped": n,   # this module's
                         "claims_withdrawn": n,                                       # the claim pipeline's, pre-release
                         "prose_dropped": n},                                         # held summary/fact/history items
     "questions":       [{"item": inbox id, "kind": kind, "episode": id, "why": "page_archived"|"options_closed"|"name_gone"}],
     "paths":           [memory-relative path written, ...],
     "counts":          {"revised", "pages_archived", "pages_kept", "aliases_dropped", "held_lines_removed",
                         "held_claims_dropped" (both kinds), "questions"}}

``claims`` on an archived or kept page are the claim ids that revision withdrew or superseded there (``lost``); the
claim pipeline's own counts (claims withdrawn, spans re-anchored, held claims dropped) stay in its audit.

:func:`restore` is the one writer that undoes an archive: it reads ``archived_by`` and puts back the status and
confidence the page had. Never raises into the cycle from :func:`run`: a failing step is logged by class and skipped."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, entity_body, evidence, markdown_parser, pending_store, text_fold
from api.services.claims import is_record, parse_claims
from api.services.episode_revision import AUTHOR as REVISION_AUTHOR, Revision

#: ``archived_by.reason`` of a page this module archived (the restore reads it).
REASON = "revision"
#: The stamp on the archived page.
ARCHIVED_KEY = "archived_by"
#: Support kinds, in the order they are tried (the cheap frontmatter ones first, git and the lexical index last).
SUPPORTS = ("owner", "project", "media", "pinned", "contacts", "person_source", "import", "other_conversation",
            "surviving_claim", "authored_commit", "waiting_conversation", "still_named")
#: Pinned frontmatter (G198 and the person's own edits): a page carrying any is the person's word.
PINNED_KEYS = ("corrections", "aliases_removed", "aliases_kept")
#: A kept page's alias is read against at most this many other conversations; past it nothing is dropped.
MAX_OTHER_BODIES = 40
#: Per name, how many conversations the lexical index is asked for when looking for one still waiting.
SEARCH_PER_NAME = 40
#: ``archived_by``/History-facing question reasons.
WHY_ARCHIVED, WHY_OPTIONS, WHY_NAME = "page_archived", "options_closed", "name_gone"
_GENERIC_KEYS = frozenset({"both", "neither", "other", "remind_later"})
_INACTIVE = frozenset({"archived", "dropped"})


@dataclass
class Report:
    revised: list[str] = field(default_factory=list)
    pages_archived: list[dict] = field(default_factory=list)
    pages_kept: list[dict] = field(default_factory=list)
    aliases_dropped: list[dict] = field(default_factory=list)
    held: dict = field(default_factory=lambda: {"lines_removed": 0, "episodes_left": 0, "claims_dropped": 0,
                                                "claims_withdrawn": 0, "prose_dropped": 0})
    questions: list[dict] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)

    def counts(self) -> dict:
        return {"revised": len(self.revised), "pages_archived": len(self.pages_archived),
                "pages_kept": len(self.pages_kept),
                "aliases_dropped": sum(int(a.get("count", 0)) for a in self.aliases_dropped),
                "held_lines_removed": self.held["lines_removed"],
                "held_claims_dropped": self.held["claims_dropped"] + self.held["claims_withdrawn"],
                "questions": len(self.questions)}

    def as_dict(self) -> dict:
        return {"revised": list(self.revised), "pages_archived": [dict(r) for r in self.pages_archived],
                "pages_kept": [dict(r) for r in self.pages_kept],
                "aliases_dropped": [dict(r) for r in self.aliases_dropped], "held": dict(self.held),
                "questions": [dict(r) for r in self.questions], "paths": list(self.paths), "counts": self.counts()}

    def corrected(self) -> dict[str, str]:
        """``{inbox item id: the revised episode}`` for ``inbox_tend.tend(corrected=...)``."""
        return {q["item"]: q["episode"] for q in self.questions}

    def __bool__(self) -> bool:
        return bool(self.pages_archived or self.pages_kept or self.aliases_dropped or self.questions
                    or any(self.held.values()))


# --------------------------------------------------------------------------- small readers


def _occurs(text: str, name: str) -> bool:
    """The evidence locator (exact, whitespace, case-insensitive; never fuzzy), not whole-word: a doubt reads as
    "still there", which keeps a page and an alias."""
    return bool(name and name.strip()) and evidence.locate(text, name) is not None


def _fold(text) -> str:
    return " ".join(text_fold.words(str(text or "")))


def _names_of(fm: dict) -> list[str]:
    out = [str(fm.get("name") or "").strip()]
    out += [str(a).strip() for a in fm.get("aliases") or [] if isinstance(a, str)]
    return [n for n in dict.fromkeys(out) if n]


def _episodes_of(fm: dict) -> list[str]:
    raw = fm.get("source_episodes")
    values = raw if isinstance(raw, list) else ([raw] if raw else [])
    return [str(v).split("#", 1)[0] for v in values if str(v or "").startswith("ep_")]


def _removes(rev: Revision) -> bool:
    """A revision that took words away and may close what rested on them (never a capped transcript's slide, a book's
    mark or a whitespace move)."""
    return bool(rev.closes and not rev.noop and rev.removed and not rev.book)


def _project_listed(memory_path: Path) -> frozenset[str]:
    """Every page id any project page ties by hand (``entities_added``)."""
    from api.services import project_ownership

    out: set[str] = set()
    for entry in bank_index.files(memory_path, "entities"):
        fm = entry.frontmatter or {}
        if fm.get(project_ownership.PAGES_ADDED_KEY):
            out.update(project_ownership.pages(fm, project_ownership.PAGES_ADDED_KEY))
    return frozenset(out)


def _processed(memory_path: Path, episode_id: str) -> bool | None:
    entry = bank_index.file(memory_path, "episodes", f"{episode_id}.md")
    if entry is None:
        return None
    return bool((entry.frontmatter or {}).get("processed"))


def naming_conversations(memory_path: Path, names: list[str], exclude: set[str], *, waiting_only: bool) -> list[str] | None:
    """Conversations other than ``exclude`` whose own text names any of ``names`` — found by the lexical index (words
    only, no model) and confirmed on their text. ``waiting_only``: only ones Sleep has not read yet (a page's read ones
    are its ``source_episodes``). ``None`` when the index cannot be read: the caller then assumes support."""
    from api.services import search_index, search_service

    try:
        search_index.ensure_fresh(memory_path, wait=True, max_age_s=0)
    except Exception as exc:  # noqa: BLE001 - a derived index
        logger.info(f"revision cascade: lexical index unavailable ({type(exc).__name__})")
    found: list[str] = []
    for name in names[:3]:
        try:
            hits = search_service.search(memory_path, name, kinds=("episode",), mode="prefix",
                                         per_kind=SEARCH_PER_NAME).results
        except Exception as exc:  # noqa: BLE001
            logger.info(f"revision cascade: lexical search unavailable ({type(exc).__name__})")
            return None
        found += [str(h.episode_id or h.id) for h in hits if str(h.episode_id or h.id or "").startswith("ep_")]
    out: list[str] = []
    for eid in dict.fromkeys(found):
        if eid in exclude:
            continue
        if waiting_only and _processed(memory_path, eid) is not False:
            continue
        text = evidence.source_text(memory_path, eid) or ""
        if any(_occurs(text, n) for n in names):
            out.append(eid)
    return out


# --------------------------------------------------------------------------- git: who wrote a page


def _person_commits(memory_path: Path, page_id: str, *, limit: int = 40) -> list[tuple[str, str]] | None:
    """``[(sha, author kind)]`` newest first for the commits that touched ``entities/<id>.md`` and were authored by a
    ``user`` or a ``harness`` (``git_service.author_identity``; the ``Cicada-Author`` trailer). ``None`` when git cannot
    answer — the caller keeps the page. One ``git log``, engine-free."""
    from api.services import git_service

    if not (memory_path / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "log", f"-n{limit}", "--format=%x1e%H%x1f%b", "--end-of-options", "HEAD", "--",
             f"entities/{page_id}.md"], cwd=str(memory_path), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        # An empty bank (no HEAD) has no commits: nobody wrote the page.
        return [] if "unknown revision" in proc.stderr or "does not have any commits" in proc.stderr else None
    out: list[tuple[str, str]] = []
    for record in proc.stdout.split("\x1e")[1:]:
        sha, _, body = record.partition("\x1f")
        for author in git_service._parse_authors(body):  # noqa: SLF001 - the one trailer parser
            kind = git_service.author_identity(author)[0]
            if kind in ("user", "harness"):
                out.append((sha.strip(), kind))
                break
    return out


def _added_lines(memory_path: Path, page_id: str, sha: str) -> str | None:
    try:
        proc = subprocess.run(["git", "show", "--format=", "--unified=0", sha, "--", f"entities/{page_id}.md"],
                              cwd=str(memory_path), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return "\n".join(line[1:] for line in proc.stdout.splitlines() if line.startswith("+") and not line.startswith("+++"))


# --------------------------------------------------------------------------- the support table (ruling 4)


def _fixed(page_id: str, fm: dict, listed: frozenset[str]) -> str | None:
    """``owner`` | ``project`` | ``media`` for the pages a correction never archives or re-names (rulings 53, 56, 62)."""
    from api.services import project_ownership

    if fm.get("owner") is True or fm.get("owner") == "true":
        return "owner"
    if (str(fm.get("type") or "").split(" ")[0].lower() == "project" or fm.get(project_ownership.MINE_KEY)
            or fm.get("born") or fm.get("repositories") or page_id in listed):
        return "project"
    if isinstance(fm.get("media"), dict) or str(fm.get("type") or "").lower() == "media":
        return "media"
    return None


def support_of(memory_path: Path, page_id: str, fm: dict, body: str, claims: list, affecting: set[str], *,
               listed: frozenset[str], kind_of) -> str | None:
    """Why this page is kept, one of :data:`SUPPORTS`, or ``None`` when only the removed text stood behind it. Each is
    read from a field that exists today; the first that holds is returned (cheap ones first)."""
    from api.services import contacts_local, quiet_pages

    fixed = _fixed(page_id, fm, listed)
    if fixed:
        return fixed
    if any(fm.get(k) for k in (*PINNED_KEYS, "human_edited")) or entity_body.has_human_prose(
            fm, entity_body.parse_sections(body)):
        return "pinned"
    sources = [s for s in fm.get("sources") or [] if isinstance(s, dict)]
    if fm.get(contacts_local.FRONTMATTER_KEY) or any(contacts_local._is_mine(s) for s in sources):  # noqa: SLF001
        return "contacts"
    if any(str(s.get("added_by") or "") == "user" for s in sources):
        return "person_source"
    episodes = _episodes_of(fm)
    if any(kind_of(e) in (quiet_pages.IMPORT, quiet_pages.CHECK) for e in episodes):
        return "import"
    if any(e not in affecting for e in episodes):
        return "other_conversation"
    if any(c.valid_to is None and not is_record(c) for c in claims):
        return "surviving_claim"
    person = _person_commits(memory_path, page_id)
    if person is None or person:
        return "authored_commit"      # a person or an agent wrote it — or git cannot say, which keeps it
    names = _names_of(fm)
    others = naming_conversations(memory_path, names, set(affecting), waiting_only=True) if names else []
    if others is None or others:
        return "waiting_conversation"
    return None


# --------------------------------------------------------------------------- aliases


def _droppable(memory_path: Path, page_id: str, fm: dict, eps: list[str], revisions: dict[str, Revision],
               names_elsewhere: dict[str, set[str]], listed: frozenset[str]) -> list[str]:
    """The aliases of this kept page that only the removed text said. Conservative: nothing from a page with pinned
    edits, an alias another page (or this one's name) bears, one added by any person- or agent-authored commit of the page, or
    one in any of its other conversations (more than :data:`MAX_OTHER_BODIES` of them, or one unreadable: nothing)."""
    if any(fm.get(k) for k in (*PINNED_KEYS, "human_edited")) or _fixed(page_id, fm, listed):
        return []
    aliases = [a for a in fm.get("aliases") or [] if isinstance(a, str) and a.strip()]
    if not aliases:
        return []
    own_name = _fold(fm.get("name"))
    revised_here = [e for e in eps if e in revisions]
    maybe = []
    for alias in aliases:
        folded = _fold(alias)
        if not folded or folded == own_name or f" {folded} " in f" {own_name} " or f" {own_name} " in f" {folded} ":
            continue
        if names_elsewhere.get(folded, set()) - {page_id}:
            continue
        if not any(_occurs(revisions[e].prior, alias) for e in revised_here):
            continue
        if any(_occurs(revisions[e].body, alias) for e in revised_here):
            continue
        maybe.append(alias)
    if not maybe:
        return []
    others = [e for e in _episodes_of(fm) if e not in revisions]
    if len(others) > MAX_OTHER_BODIES:
        return []
    texts = []
    for e in others:
        text = evidence.source_text(memory_path, e)
        if text is None:
            return []
        texts.append(text)
    maybe = [a for a in maybe if not any(_occurs(t, a) for t in texts)]
    if not maybe:
        return []
    person = _person_commits(memory_path, page_id)
    if person is None:
        return []
    for sha, _kind in person:
        # Every commit a person or an agent authored protects what it added, not only the newest: a later harness
        # commit must not unprotect an alias the person put there before it (G104 slice 3, review B2).
        added = _added_lines(memory_path, page_id, sha)
        if added is None:
            return []
        maybe = [a for a in maybe if not _occurs(added, a)]
        if not maybe:
            return []
    return maybe


# --------------------------------------------------------------------------- questions


def _closed_by(claim, by_id: dict, basis: str) -> bool:
    """Was this claim closed by the revision of ``basis``: withdrawn by its record, or replaced by the same source's new
    value?"""
    if claim.valid_to is None or not claim.superseded_by:
        return False
    closer = by_id.get(claim.superseded_by)
    if closer is None:
        return False
    if is_record(closer):
        return closer.authored_by == REVISION_AUTHOR and any(e.episode == basis for e in closer.evidence)
    return (bool(claim.source_episodes) and set(claim.source_episodes) <= {basis}
            and {e.episode for e in closer.evidence} <= {basis})


def question_withdrawal(memory_path: Path, fm: dict, basis: str, *, prior: str | None = None) -> str | None:
    """Why this open question is withdrawn because the conversation ``basis`` was corrected, or ``None`` (it stays).
    Derived from the bank alone — ``inbox_tend``'s ``source_corrected`` rule runs it again at settle time, and the
    cascade runs it to choose. ``prior`` (the version Sleep read, known only in the batch) makes a name question stricter:
    the name must have been in it.

    * the page it is about was archived by this correction (``page_archived``);
    * a conflict whose option claims the revision closed — every one, or every one but one (``options_closed``): no
      value is lost, the claims are closed, never deleted (ruling 73);
    * a name question raised from this conversation about a name with no page, no longer in it, held by no other
      conversation and named by no other (``name_gone``) — the page's own test, ruling 4's table."""
    from api.services import inbox_questions

    kind = str(fm.get("kind") or "")
    entity_id = str(fm.get("entity_id") or "").strip()
    page = bank_index.file(memory_path, "entities", f"{entity_id}.md") if entity_id else None
    if page is not None:
        by = (page.frontmatter or {}).get(ARCHIVED_KEY)
        if (str((page.frontmatter or {}).get("status") or "") == "archived" and isinstance(by, dict)
                and by.get("reason") == REASON and by.get("episode") == basis):
            return WHY_ARCHIVED
    if kind == "conflict":
        if page is None:
            return None
        options = [o for o in inbox_questions.normalize_options(fm.get("options"))
                   if str(o.get("key")) not in _GENERIC_KEYS and o.get("claim_id")]
        if len(options) < 2:
            return None
        try:
            by_id = {c.id: c for c in parse_claims(page.body())}
        except Exception:  # noqa: BLE001 - an unreadable fence closes nothing
            return None
        closed = [o for o in options if o["claim_id"] in by_id and _closed_by(by_id[o["claim_id"]], by_id, basis)]
        return WHY_OPTIONS if closed and len(options) - len(closed) <= 1 else None
    if kind not in ("clarification", "merge_suggestion") or str(fm.get("source_episode") or "") != basis:
        return None
    if page is not None or str(fm.get("asks") or "") or fm.get("owner_role"):
        return None   # a page holds it (its own test is the page's), or a question asked on purpose
    name = str(fm.get("entity_name") or fm.get("entity_mention") or "").strip()
    text = evidence.source_text(memory_path, basis)
    if not name or text is None or _occurs(text, name):
        return None
    if prior is not None and not _occurs(prior, name):
        return None
    line = pending_store.held_line(memory_path, name)
    if line is not None and any(e != basis for e in line.episodes()):
        return None
    others = naming_conversations(memory_path, [name], {basis}, waiting_only=False)
    return WHY_NAME if others == [] else None


def drop_held_prose(memory_path: Path, revisions: dict[str, Revision], *, words_taken=None) -> int:
    """T6: before Stage 2 in the drain that reads ``revisions``, take out of the pending lines the prose only the removed
    text said (module docstring, "Held prose"), so no page is born from a line with it. ``words_taken(rev)`` is the words
    a revision removed (default ``revision_prose.changes_of``'s ``gone``); an item says one when its tokens hold it.
    Never raises; returns how many items left."""
    from api.services import revision_prose

    def taken(rev) -> frozenset:
        return frozenset().union(*(c.gone for c in revision_prose.changes_of(rev)))

    taken = words_taken or taken
    total = 0
    for eid, rev in (revisions or {}).items():
        try:
            if not _removes(rev):
                continue
            gone = taken(rev)
            if not gone:
                continue
            total += pending_store.drop_prose(Path(memory_path), eid, rev.prior_hash,
                                              lambda text, gone=gone: bool(revision_prose.tokens(text) & gone))
        except Exception as exc:  # noqa: BLE001 - a correction is never worth the batch
            logger.warning(f"Revision cascade held prose failed: {type(exc).__name__}")
    return total


# --------------------------------------------------------------------------- the run


def run(memory_path: Path, revisions: dict[str, Revision], *, revised_out: dict[str, str] | None = None,
        new_pages: set[str] | frozenset[str] = frozenset(), held_withdrawn: int = 0, prose_dropped: int = 0,
        today: str | None = None) -> Report:
    """One batch's cascade (module docstring). ``revisions``: the batch's read revisions; ``revised_out``: the claim
    pipeline's ``{claim id: revised episode}`` for the claims only the removed text said (they are closed on the pages by
    now); ``new_pages``: pages this batch created; ``held_withdrawn``: how many held claims the claim pipeline already dropped before their
    release (counted in the report beside what this module drops); ``prose_dropped``: how many held prose items
    :func:`drop_held_prose` dropped before Stage 2 (counted as ``held.prose_dropped``). Writes pages and the pending store only. Never
    raises."""
    memory_path = Path(memory_path)
    report = Report()
    effective = {eid: rev for eid, rev in (revisions or {}).items() if _removes(rev)}
    report.revised = sorted(effective)
    report.held["claims_withdrawn"] = int(held_withdrawn or 0)
    report.held["prose_dropped"] = int(prose_dropped or 0)
    if prose_dropped and pending_store.PENDING_STORE_FILE not in report.paths:
        report.paths.append(pending_store.PENDING_STORE_FILE)
    if not effective:
        return report
    today = today or str(date.today())
    revised_out = revised_out or {}
    try:
        _pages(memory_path, effective, revised_out, set(new_pages or ()), today, report)
    except Exception as exc:  # noqa: BLE001 - a cascade is never worth the batch
        logger.warning(f"Revision cascade pages failed: {type(exc).__name__}")
    try:
        _held(memory_path, effective, report)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Revision cascade held names failed: {type(exc).__name__}")
    try:
        _questions(memory_path, effective, revised_out, report, today)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Revision cascade questions failed: {type(exc).__name__}")
    return report


def _pages(memory_path: Path, effective: dict[str, Revision], revised_out: dict[str, str], new_pages: set[str],
           today: str, report: Report) -> None:
    from api.services import quiet_pages

    entries = [e for e in bank_index.files(memory_path, "entities")
               if any(ep in effective for ep in _episodes_of(e.frontmatter or {}))]
    if not entries:
        return
    names_elsewhere: dict[str, set[str]] = {}
    for entry in bank_index.files(memory_path, "entities"):
        for n in _names_of(entry.frontmatter or {}):
            names_elsewhere.setdefault(_fold(n), set()).add(entry.stem)
    listed = _project_listed(memory_path)
    kind_of = quiet_pages.episode_lookup(memory_path)
    for entry in sorted(entries, key=lambda e: e.stem):
        page_id, fm = entry.stem, dict(entry.frontmatter or {})
        if page_id in new_pages or str(fm.get("status") or "active") in _INACTIVE:
            continue
        try:
            _page(memory_path, page_id, entry, fm, effective, revised_out, names_elsewhere, listed, kind_of, today,
                  report)
        except Exception as exc:  # noqa: BLE001 - one page never stops the rest
            logger.warning(f"Revision cascade skipped a page: {type(exc).__name__}")


def _page(memory_path, page_id, entry, fm, effective, revised_out, names_elsewhere, listed, kind_of, today,
          report) -> None:
    eps = [e for e in _episodes_of(fm) if e in effective]
    body = entry.body()
    claims = parse_claims(body)
    lost: dict[str, list[str]] = {}
    for c in claims:
        ep = revised_out.get(c.id)
        if ep in effective and ep in eps and c.valid_to is not None:
            lost.setdefault(ep, []).append(c.id)
    names = _names_of(fm)
    gone = [e for e in eps if any(_occurs(effective[e].prior, n) for n in names)
            and not any(_occurs(effective[e].body, n) for n in names)]
    affecting = set(lost) | set(gone)
    rel = f"entities/{page_id}.md"
    if affecting:
        # A conversation that lost a claim about the page but still names it still speaks of it (review B1): the page
        # was promoted for being talked about, and it still is. Only a name gone from every affecting conversation
        # can leave a page with nothing.
        still_named = any(_occurs(effective[e].body, n) for e in affecting for n in names)
        why = "still_named" if still_named else support_of(memory_path, page_id, fm, body, claims, affecting,
                                                            listed=listed, kind_of=kind_of)
        episode = sorted(affecting)[0]
        lost_ids = [i for e in sorted(lost) for i in lost[e]]
        if why is not None:
            report.pages_kept.append({"page": page_id, "episode": episode, "support": why, "claims": lost_ids})
        else:
            parsed = markdown_parser.parse(memory_path / rel)
            pfm = parsed.frontmatter
            pfm[ARCHIVED_KEY] = {"reason": REASON, "episode": episode, "day": today,
                                 "prior_status": str(pfm.get("status") or "active"),
                                 "prior_confidence": pfm.get("confidence")}
            pfm["status"] = "archived"
            pfm["removed_at"] = _now()
            markdown_parser.write(memory_path / rel, pfm, parsed.body)
            report.pages_archived.append({"page": page_id, "episode": episode, "claims": lost_ids})
            report.paths.append(rel)
            return
    drop = _droppable(memory_path, page_id, fm, eps, effective, names_elsewhere, listed)
    if drop:
        parsed = markdown_parser.parse(memory_path / rel)
        pfm = parsed.frontmatter
        gone_aliases = {a for a in drop}
        pfm["aliases"] = [a for a in pfm.get("aliases") or [] if a not in gone_aliases]
        if not pfm["aliases"]:
            pfm.pop("aliases")
        markdown_parser.write(memory_path / rel, pfm, parsed.body)
        report.aliases_dropped.append({"page": page_id, "episode": eps[0], "count": len(drop)})
        if rel not in report.paths:
            report.paths.append(rel)


def _now() -> str:
    from api.services import episode_ids

    return episode_ids.utc_now_seconds()


def _held(memory_path: Path, effective: dict[str, Revision], report: Report) -> None:
    for eid, rev in effective.items():
        def gone(line, rev=rev) -> bool:
            names = [line.name, *(line.aliases or [])]
            return any(_occurs(rev.prior, n) for n in names) and not any(_occurs(rev.body, n) for n in names)

        counts = pending_store.withdraw_episode(memory_path, eid, gone)
        for key, value in counts.items():
            report.held[key] += value
        if any(counts.values()) and pending_store.PENDING_STORE_FILE not in report.paths:
            report.paths.append(pending_store.PENDING_STORE_FILE)


def _questions(memory_path: Path, effective: dict[str, Revision], revised_out: dict[str, str], report: Report,
               today: str) -> None:
    from api.services import inbox_tend

    archived = {r["page"]: r["episode"] for r in report.pages_archived}
    conflicts: dict[str, set[str]] = {}
    for page_id, episodes in _lost_pages(memory_path, effective, revised_out).items():
        conflicts[page_id] = episodes
    for path, fm, _body in inbox_tend.pending(memory_path):
        if inbox_tend._blocked(fm, today):  # noqa: SLF001 - the one "never touched" test
            continue
        entity_id = str(fm.get("entity_id") or "")
        bases = [b for b in (archived.get(entity_id), str(fm.get("source_episode") or ""),
                             *sorted(conflicts.get(entity_id, ()))) if b in effective]
        for basis in dict.fromkeys(bases):
            why = question_withdrawal(memory_path, fm, basis, prior=effective[basis].prior)
            if why:
                report.questions.append({"item": path.stem, "kind": str(fm.get("kind") or ""), "episode": basis,
                                         "why": why})
                break


def _lost_pages(memory_path: Path, effective: dict, revised_out: dict[str, str]) -> dict[str, set[str]]:
    """``{page id: the revised episodes that closed a claim on it}`` — the pages a conflict question may be about."""
    out: dict[str, set[str]] = {}
    if not revised_out:
        return out
    for entry in bank_index.files(memory_path, "entities"):
        eps = {e for e in _episodes_of(entry.frontmatter or {}) if e in effective}
        if not eps:
            continue
        for c in parse_claims(entry.body()):
            ep = revised_out.get(c.id)
            if ep in eps and c.valid_to is not None:
                out.setdefault(entry.stem, set()).add(ep)
    return out


# --------------------------------------------------------------------------- the restore writer


class Refused(ValueError):
    """The page is not one this module archived (``code``: ``missing`` | ``not_archived``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def restore(memory_path: Path, entity_id: str) -> dict:
    """Put back a page :func:`run` archived: its prior status and confidence, ``removed_at`` and ``archived_by`` gone.
    Reads ``archived_by`` (a page decay archived carries none and is never reopened here). The caller holds the write
    admission and commits ``paths``. Raises :class:`Refused`."""
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not entity_id or "/" in entity_id or not path.is_file():
        raise Refused("missing", "No such page")
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    by = fm.get(ARCHIVED_KEY)
    if str(fm.get("status") or "") != "archived" or not isinstance(by, dict) or by.get("reason") != REASON:
        raise Refused("not_archived", "This page was not archived by a correction")
    status = str(by.get("prior_status") or "active")
    fm["status"] = status if status not in _INACTIVE else "active"
    if isinstance(by.get("prior_confidence"), (int, float)):
        fm["confidence"] = by["prior_confidence"]
    fm.pop("removed_at", None)
    fm.pop(ARCHIVED_KEY, None)
    markdown_parser.write(path, fm, parsed.body)
    return {"entity_id": entity_id, "status": fm["status"], "confidence": fm.get("confidence"),
            "paths": [f"entities/{entity_id}.md"]}


def commit_message(entity_id: str) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Restored a page {date.today().isoformat()}",
        [f"entities/{entity_id}.md: updated (trigger: user/restore_correction)"], authors=[git_service.USER_AUTHOR])
