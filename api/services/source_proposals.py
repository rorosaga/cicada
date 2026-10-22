"""G61 "Where to check" (G208, ruling 36 D5, 2026-10-22) — the links already on the record, proposed as sources.

The owner, 2026-10-22: update sources are "of extreme importance, so any agent and cicada as well can provide/have a
heads up as to where to check the info … it might as well be a personal website, a google scholar account or anything".
Their name in every surface is **Where to check**; the stored key stays ``sources:`` (``fact_sources``).

Measured on the owner's bank before this step: 0 of 277 person pages carried a source, because every writer was
type-restricted, predicate-restricted or forbidden to infer, and every non-owner picture rung keys on a source. This
module is the inferred path that never writes the person's trust:

- :func:`candidates` — engine-free, no fetch. A **person** page's profile links (GitHub, X, Instagram, LinkedIn, Google
  Scholar, ORCID — :func:`profile_of`) written in the page's own text, or in a line of the person's OWN turn, in a
  conversation the page rests on, that also names the page. A **project** or **tool** page's GitHub repository when the
  repository's name is the page's own name. Never a URL guessed from a name, never a handle read off a saved post.
- :func:`propose` — Sleep's tail step: each candidate lands as an untrusted entry (``proposed: true`` plus where it was
  found, ``evidence``), respecting ``sources_removed`` and the caps, then :func:`sync_question` keeps ONE question per
  page (``kind: clarification``, ``asks: sources``) listing every proposal still waiting — an agent's too
  (``cicada_add_source(inferred=true)``). Idempotent: a second run writes nothing.
- :func:`settle_rule` — ruling 29: Sleep may answer the question only when every link it lists was found in the
  person's own located words naming the page (``named_account``); anything else waits for the person.
- :func:`answer` — the inbox resolver's body: ``yes`` takes each listed proposal (``accepted``, which is what makes it
  their own account for a picture and a tracked source for ruling 26), ``no`` removes it and remembers the removal.
- :func:`link_kind` — what the entity card's chips draw for any source.

A proposal is never trusted (``fact_sources.trusted``), never the person's own account (``person_photo``), never
re-checked (``source_refresh.tracked``) until the person takes it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from loguru import logger

from api.services import fact_sources, markdown_parser, page_lock, person_photo, text_fold

ASKS = "sources"
YES = "yes"
NO = "no"
TRIGGER = "sleep/where-to-check"
AUTHOR = fact_sources.CICADA
UNCERTAINTY = "where_to_check"
PERSON_TYPES = frozenset({"person"})
REPO_TYPES = frozenset({"project", "tool"})
#: Proposals written on one page in one run, and conversations read per page (the newest).
MAX_PER_PAGE = 4
MAX_EPISODES = 40
MAX_LINE_CHARS = 400
#: The predicates a proposal is filed under — each a profile predicate `person_photo.is_own_account` accepts once taken.
PROFILE_KINDS = ("github", "x", "instagram", "linkedin", "scholar", "orcid")
REPO = "repo"

_ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")
_SCHOLAR_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,20}")


# ---- what a link is ------------------------------------------------------------------------------------------------


def _scholar_id(ref: str) -> str | None:
    try:
        parsed = urlparse(ref.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not re.fullmatch(r"scholar\.google\.[a-z.]{2,8}", host):
        return None
    if parsed.path.rstrip("/") != "/citations":
        return None
    user = (parse_qs(parsed.query).get("user") or [""])[0]
    return user if _SCHOLAR_ID_RE.fullmatch(user) else None


def _orcid(ref: str) -> str | None:
    parts = person_photo._profile_parts(ref, ("orcid.org", "www.orcid.org"))
    if not parts or len(parts) != 1 or not _ORCID_RE.fullmatch(parts[0]):
        return None
    return parts[0]


def github_repo(ref) -> tuple[str, str] | None:
    """``(owner, repo)`` of a GitHub repository's own URL (`https://github.com/<owner>/<repo>`) — None otherwise."""
    parts = person_photo._profile_parts(ref, ("github.com", "www.github.com"))
    if not parts or len(parts) != 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if person_photo.github_username(f"https://github.com/{owner}") is None or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}",
                                                                                                 repo):
        return None
    return owner, repo


def profile_of(ref) -> tuple[str, str, str] | None:
    """``(kind, canonical ref, label)`` for a profile link of one of :data:`PROFILE_KINDS` — None for anything else
    (a post, a repository, a site page, another host). The canonical ref is the one form every writer stores, so one
    profile is never listed twice under two spellings."""
    if not isinstance(ref, str):
        return None
    if (name := person_photo.github_username(ref)) is not None:
        return "github", f"https://github.com/{name}", f"@{name}"
    if (name := person_photo.x_handle(ref)) is not None:
        return "x", f"https://x.com/{name}", f"@{name}"
    if (name := person_photo.instagram_handle(ref)) is not None:
        return "instagram", f"https://www.instagram.com/{name}", f"@{name}"
    if (name := person_photo.linkedin_slug(ref)) is not None:
        return "linkedin", f"https://www.linkedin.com/in/{name}", "LinkedIn"
    if (name := _scholar_id(ref)) is not None:
        return "scholar", f"https://scholar.google.com/citations?user={name}", "Google Scholar"
    if (name := _orcid(ref)) is not None:
        return "orcid", f"https://orcid.org/{name}", "ORCID"
    return None


def link_kind(source: dict) -> tuple[str, str]:
    """``(kind, label)`` the entity card draws for one source — a chip's glyph and its words. ``kind`` is one of
    the :data:`PROFILE_KINDS`, ``repo``, ``contacts``, ``website``, ``app``, ``path`` or ``note``. Derived at read,
    never stored."""
    from api.services import reading_hosts

    ref = str(source.get("ref") or "").strip()
    kind = str(source.get("kind") or "").strip().lower()
    if ref.startswith("addressbook://"):
        return "contacts", "Contacts"
    if kind == fact_sources.KIND_NOTE:
        return "note", ref if len(ref) <= 40 else ref[:39].rstrip() + "…"
    if kind in fact_sources.LOCAL_KINDS:
        return "path", Path(ref).name or ref
    if kind == fact_sources.KIND_APP:
        return "app", ref
    if (profile := profile_of(ref)) is not None:
        return profile[0], profile[2]
    if (repo := github_repo(ref)) is not None:
        return REPO, f"{repo[0]}/{repo[1]}"
    try:
        site = reading_hosts.site_of(ref)
    except Exception:  # noqa: BLE001 — an odd ref is still a chip
        site = ""
    return "website", site or ref


# ---- finding them on the record ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    ref: str
    predicate: str
    #: ``{"page": true}`` (the page's own text) or ``{"episode", "start", "end"}`` (the person's own line).
    evidence: dict


def _names(fm: dict) -> list[str]:
    out = [str(fm.get("name") or "").strip()]
    out += [str(a).strip() for a in fm.get("aliases") or [] if str(a).strip()]
    return [n for n in out if len(n) >= 2]


def names_page(text: str, fm: dict) -> bool:
    """The page's name or one of its aliases, whole-word, in ``text``."""
    from api.services import evidence

    return any(evidence.locate(text, name, whole_word=True) for name in _names(fm))


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text_fold.fold(text))


def _person_line_hits(memory_path: Path, fm: dict) -> list[Candidate]:
    """Profile links in a line of the person's own turn that names the page, across the page's newest conversations."""
    from api.services import evidence, inbox_tend

    out: list[Candidate] = []
    episodes = [str(e) for e in fm.get("source_episodes") or [] if str(e).startswith("ep_")]
    for ep in sorted(set(episodes))[-MAX_EPISODES:]:
        doc = evidence.source_document(memory_path, ep)
        if doc is None:
            continue
        ep_fm, text = doc
        for turn in evidence.turns(text, override=ep_fm.get("evidence_kind"), gaps=evidence.gap_ranges(ep_fm, text)):
            if turn.role != "user" or inbox_tend._agent_note(ep_fm.get("source"), turn):
                continue
            pos = turn.content_start
            for line in text[turn.content_start:turn.end].split("\n"):
                start, end = pos, pos + len(line)
                pos = end + 1
                if "http" not in line or len(line.strip()) > MAX_LINE_CHARS or not names_page(line, fm):
                    continue
                for url in fact_sources.urls_in(line):
                    if (profile := profile_of(url)) is not None:
                        lead = len(line) - len(line.lstrip())
                        tail = len(line.rstrip())
                        out.append(Candidate(profile[1], profile[0],
                                             {"episode": ep, "start": start + lead, "end": start + tail}))
    return out


def candidates(memory_path: Path, fm: dict, body: str) -> list[Candidate]:
    """What the record already says this page can be checked at — see the module docstring. Deduplicated by ref (the
    person's own line wins over the page's text: it carries their words), in the order found."""
    kind = str(fm.get("type") or "").strip().lower()
    found: list[Candidate] = []
    if kind in PERSON_TYPES:
        found += _person_line_hits(memory_path, fm)
        for url in fact_sources.urls_in(body or ""):
            if (profile := profile_of(url)) is not None:
                found.append(Candidate(profile[1], profile[0], {"page": True}))
    elif kind in REPO_TYPES:
        own = {_squash(n) for n in _names(fm)} - {""}
        for url in fact_sources.urls_in(body or ""):
            repo = github_repo(url)
            if repo is not None and _squash(repo[1]) in own:
                found.append(Candidate(f"https://github.com/{repo[0]}/{repo[1]}", REPO, {"page": True}))
    out: list[Candidate] = []
    for cand in found:
        if all(c.ref.lower() != cand.ref.lower() for c in out):
            out.append(cand)
    return out


def _listed(fm: dict, ref: str) -> bool:
    """Already a source under any fact, or removed under any fact (whoever removed it)."""
    key = ref.lower().rstrip("/")
    for s in fact_sources.as_sources(fm.get("sources")):
        if str(s.get("ref") or "").strip().lower().rstrip("/") == key:
            return True
        theirs = profile_of(str(s.get("ref") or ""))
        if theirs is not None and theirs[1].lower() == key:
            return True
    for tomb in fm.get(fact_sources.REMOVED_KEY) or []:
        if isinstance(tomb, dict):
            other = str(tomb.get("ref") or "").strip()
            theirs = profile_of(other)
            if other.lower().rstrip("/") == key or (theirs is not None and theirs[1].lower() == key):
                return True
    return False


def propose_on(fm: dict, cands: list[Candidate], *, today: str | None = None, limit: int = MAX_PER_PAGE) -> int:
    """Put each candidate on ``fm`` as a proposal by Cicada (pure over the dict; the caller writes). Never over a
    listed or removed key, never past a cap. Returns how many were added."""
    added = 0
    for cand in cands:
        if added >= limit:
            break
        existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
        if _listed(fm, cand.ref):
            continue
        if len(existing) >= fact_sources.MAX_SOURCES or sum(
                1 for s in existing if fact_sources.same_predicate(s.get("predicate"), cand.predicate)) \
                >= fact_sources.MAX_PER_PREDICATE:
            break
        fm["sources"] = existing + [{
            "ref": cand.ref, "kind": fact_sources.KIND_URL, "predicate": cand.predicate, "added_by": AUTHOR,
            "added_at": today or str(date.today()), fact_sources.PROPOSED: True, "evidence": dict(cand.evidence)}]
        added += 1
    return added


def pending(fm: dict) -> list[dict]:
    """The page's proposals still waiting for the person, in file order."""
    return [s for s in fact_sources.as_sources(fm.get("sources")) if fact_sources.is_proposed(s)]


# ---- the one question per page -------------------------------------------------------------------------------------


def open_question(memory_path: Path, page_id: str) -> Path | None:
    inbox = Path(memory_path) / "inbox"
    if not inbox.is_dir():
        return None
    for path in sorted(inbox.glob("inbox-*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001 — an unreadable item is no question
            continue
        if str(fm.get("asks") or "") == ASKS and str(fm.get("entity_id") or "") == page_id:
            return path
    return None


def _question_words(fm: dict, n: int) -> tuple[str, list[dict]]:
    name = str(fm.get("name") or "this page").strip()
    if str(fm.get("type") or "").strip().lower() in PERSON_TYPES:
        question = f"Is this {name}'s own account?" if n == 1 else f"Are these {name}'s own accounts?"
        no = "No, not theirs"
    else:
        question = f"Is this where to check for {name}?" if n == 1 else f"Are these where to check for {name}?"
        no = "No, remove"
    return question, [{"key": YES, "label": "Yes, keep them" if n > 1 else "Yes, keep it"}, {"key": NO, "label": no}]


def _question_body(waiting: list[dict]) -> str:
    lines = ["Where to check — links already on the record, waiting for you:", ""]
    for s in waiting:
        kind, label = link_kind(s)
        ev = s.get("evidence") if isinstance(s.get("evidence"), dict) else {}
        where = (f"in your own words, {ev['episode']}" if ev.get("episode") else
                 "in this page's own text" if ev.get("page") else f"added by {s.get('added_by') or 'an agent'}")
        lines.append(f"- {label} ({kind}): {s.get('ref')} — {where}")
    return "\n".join(lines) + "\n"


def sync_question(memory_path: Path, page_id: str, fm: dict, *, today: str | None = None) -> str | None:
    """Keep ONE question about ``page_id``'s waiting proposals: written when the first appears, its list rewritten when
    it changes, removed when none is left. Returns the memory-relative path it wrote or removed, or None."""
    from api.services import inbox_service

    memory_path = Path(memory_path)
    waiting = pending(fm)
    refs = [str(s["ref"]) for s in waiting]
    path = open_question(memory_path, page_id)
    if path is None and not waiting:
        return None
    if path is not None:
        rel = path.relative_to(memory_path).as_posix()
        if not waiting:
            path.unlink()
            return rel
        parsed = markdown_parser.parse(path)
        if list(parsed.frontmatter.get("refs") or []) == refs:
            return None
        item = dict(parsed.frontmatter)
    else:
        inbox = memory_path / "inbox"
        path = inbox / f"inbox-{inbox_service.next_inbox_num(inbox):03d}.md"
        rel = path.relative_to(memory_path).as_posix()
        item = {"kind": "clarification", "asks": ASKS, "required_input": "choice", "status": "pending",
                "priority": 0.5, "entity_id": page_id, "entity_name": str(fm.get("name") or page_id),
                "allow_other": False, "allow_defer": True, "uncertainty_type": UNCERTAINTY,
                "created_date": today or str(date.today())}
    question, options = _question_words(fm, len(refs))
    item.update({"title": question, "question": question, "options": options, "refs": refs})
    episode = next((s["evidence"]["episode"] for s in waiting
                    if isinstance(s.get("evidence"), dict) and s["evidence"].get("episode")), None)
    if episode:
        item["source_episode"] = episode
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, item, _question_body(waiting))
    return rel


# ---- the Sleep step ------------------------------------------------------------------------------------------------


@dataclass
class Report:
    paths: list[str] = field(default_factory=list)
    proposed: int = 0
    pages: int = 0
    questions: int = 0
    #: Every file the step wrote, with its bytes before (None: it did not exist) — :func:`restore` puts them back.
    before: dict[str, bytes | None] = field(default_factory=dict)
    #: The bank the step ran on (set by :func:`propose`), for the commit's manifest verbs.
    root: str = ""

    def touch(self, memory_path: Path, rel: str) -> None:
        if rel not in self.before:
            p = Path(memory_path) / rel
            self.before[rel] = p.read_bytes() if p.exists() else None
        if rel not in self.paths:
            self.paths.append(rel)


def _pages(memory_path: Path):
    for path in sorted((Path(memory_path) / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — an unreadable page proposes nothing
            continue
        yield path, parsed


def plan(memory_path: Path) -> list[tuple[str, list[Candidate]]]:
    """What :func:`propose` would add, per page — read-only (the dry-run script's body)."""
    out = []
    for path, parsed in _pages(memory_path):
        fm = dict(parsed.frontmatter)
        if str(fm.get("status") or "") in ("archived", "dropped"):
            continue
        cands = [c for c in candidates(memory_path, fm, parsed.body) if not _listed(fm, c.ref)][:MAX_PER_PAGE]
        if cands:
            out.append((path.stem, cands))
    return out


def propose(memory_path: Path, skip: frozenset[str] = frozenset(), report: Report | None = None,
            *, today: str | None = None) -> Report:
    """Sleep's tail step (engine-free, no fetch): write each page's new proposals and keep its one question in step.
    Pages (and questions) dirty before the run (``skip``) are left alone. The caller commits ``report.paths``."""
    memory_path = Path(memory_path)
    report = report or Report()
    report.root = str(memory_path)
    for path, parsed in _pages(memory_path):
        rel = f"entities/{path.name}"
        if rel in skip:
            continue
        fm = parsed.frontmatter
        if str(fm.get("status") or "") in ("archived", "dropped"):
            continue
        cands = candidates(memory_path, fm, parsed.body)
        if cands:
            report.touch(memory_path, rel)
            added = propose_on(fm, cands, today=today)
            if added:
                markdown_parser.write(path, fm, parsed.body)
                report.proposed += added
                report.pages += 1
            else:
                report.paths.remove(rel)
                report.before.pop(rel, None)
        question = open_question(memory_path, path.stem)
        if question is not None and question.relative_to(memory_path).as_posix() in skip:
            continue
        if pending(fm) or question is not None:
            if question is not None:
                report.touch(memory_path, question.relative_to(memory_path).as_posix())
            wrote = sync_question(memory_path, path.stem, fm, today=today)
            if wrote:
                report.before.setdefault(wrote, None)   # a new question did not exist before this step
                if wrote not in report.paths:
                    report.paths.append(wrote)
                report.questions += 1
    # A touch whose file ended byte-identical (a question already in step) is no change.
    for rel in list(report.paths):
        p = memory_path / rel
        now = p.read_bytes() if p.exists() else None
        if now == report.before.get(rel):
            report.paths.remove(rel)
            report.before.pop(rel, None)
    return report


def restore(memory_path: Path, report: Report) -> None:
    """Undo every file the step wrote (a failed commit must not leave its pages for another writer to sweep)."""
    for rel, data in report.before.items():
        p = Path(memory_path) / rel
        if data is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(data)


def commit_message(report: Report, day: date) -> str:
    from api.services import git_service

    def verb(rel: str) -> str:
        if report.before.get(rel) is None:
            return "created"
        return "removed" if not (Path(report.root) / rel).exists() else "updated"

    lines = [f"{rel}: {verb(rel)} (trigger: {TRIGGER})" for rel in report.paths]
    return git_service.build_commit_message(f"Where to check {day.isoformat()}", lines, authors=[AUTHOR])


# ---- answering it --------------------------------------------------------------------------------------------------


def settle_rule(memory_path: Path, item_id: str, fm: dict):
    """Ruling 29 for a ``asks: sources`` question: ``(Decision, "")`` — ``named_account``, "yes" — only when every
    link it lists waits on the page with the person's own located words that name the page and carry that very link;
    else ``(None, "person_only")``, so no engine and no other rule ever reads it."""
    from api.services import evidence, inbox_tend

    page_id = str(fm.get("entity_id") or "")
    page = Path(memory_path) / "entities" / f"{page_id}.md"
    if not page.is_file():
        return None, "person_only"
    page_fm = markdown_parser.parse(page).frontmatter
    waiting = {str(s["ref"]): s for s in pending(page_fm)}
    refs = [str(r) for r in fm.get("refs") or []]
    if not refs or any(r not in waiting for r in refs):
        return None, "person_only"
    quote = None
    for ref in refs:
        ev = waiting[ref].get("evidence")
        if not isinstance(ev, dict) or not ev.get("episode"):
            return None, "person_only"
        doc = evidence.source_document(Path(memory_path), str(ev["episode"]))
        if doc is None:
            return None, "person_only"
        try:
            words = doc[1][int(ev["start"]):int(ev["end"])]
        except (KeyError, TypeError, ValueError):
            return None, "person_only"
        if not words or not names_page(words, page_fm) or not any(
                (p := profile_of(u)) is not None and p[1] == ref for u in fact_sources.urls_in(words)):
            return None, "person_only"
        if inbox_tend.persons_span(Path(memory_path), str(ev["episode"]), words) is None:
            return None, "person_only"
        quote = quote or {"episode": str(ev["episode"]), "quote": words}
    return inbox_tend.Decision(item_id, "clarification", "named_account", {"action": "resolve", "option_key": YES},
                               answer="Yes", quote=quote, guard=inbox_tend._guard(memory_path, page_id)), ""


@page_lock.locked
def answer(memory_path: Path, page_id: str, refs: list[str], take: bool) -> int:
    """The person's answer on a page: ``take`` makes each listed, still-waiting proposal theirs (``accepted``); else
    each is removed and remembered as removed by the person. Returns how many entries changed. Holds the page lock
    (re-entrant in one thread); the caller commits."""
    page = Path(memory_path) / "entities" / f"{page_id}.md"
    if not page.is_file():
        return 0
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter
    wanted = {str(r) for r in refs}
    kept: list[dict] = []
    changed = 0
    for s in [s for s in (fm.get("sources") or []) if isinstance(s, dict)]:
        if str(s.get("ref") or "") in wanted and fact_sources.is_proposed(s):
            changed += 1
            if take:
                s = dict(s)
                s["accepted"] = True
                s.pop(fact_sources.PROPOSED, None)
            else:
                fact_sources._push_tombstone(fm, s, by=fact_sources.USER, reason="not where to check")
                continue
        kept.append(s)
    if not changed:
        return 0
    if kept:
        fm["sources"] = kept
    else:
        fm.pop("sources", None)
    markdown_parser.write(page, fm, parsed.body)
    logger.debug(f"where to check: {changed} answered")   # a count only — never a ref
    return changed
