"""Any join can be undone: merge two pages, split one page, both by the person — each one commit, each undoable
(G227 follow-up, owner 2026-10-29).

The owner, on two things with one name that one page had absorbed: "this should be something that can be merged and
stuff down the line, or entities can be separated if they were joined like what happened now." Before this a merge was
only an inbox answer and a wrong join could not be taken back by the person at all. UX principle 3 — agent proposes,
user disposes; every automated action can be overridden — was missing for the commonest memory error.

**Merge** (:func:`merge`): one page folds into another through the one merge primitive (``entity_merge.merge_entities``:
claims with their ids, evidence and history, sources, aliases, pictures, looks, every backlink and edge), the loser's
id keeps resolving (``page_redirects``), and any "different" answer or split between the two is cleared
(``merge_rejections.clear_pairs``) — the person has now said they are one.

**Split** (:func:`split_plan`, :func:`split`): the person picks what belongs to the other thing — sentences of the
prose (numbered exactly as ``same_name_split.sentences`` numbers them, so its judge's proposal is the starting
selection), claims, sources and conversations — and those move to a new page with a clean title and a distinct id
(``<slug>-2`` when the title is taken, G227: the qualifier tells them apart, derived on read). Other pages' links to
the old page are re-pointed only where the person said so; the plan pre-ticks a page only when the evidence says which
one it meant (:func:`reference_choice`) and leaves the rest for the person to say. A split records the pair as two
things (``merge_rejections.add_split``), so the dedup sweep, Sleep's inbox tending and the person-name review never
join them back, while the name itself can still reach either page (Stage 2's same-title judge, G227).

**Undo** (:func:`undo`): the reverse of the join's commit, applied onto each file as it is now — the "Settled by Sleep"
pattern (``inbox_tend.undo``): a file unchanged since is put back, the bank's two lists are reversed by meaning, and a
change since in the same place refuses the whole undo with a sentence, nothing written.

Every write here is a caller's: the caller holds the bank's write admission and its page lock (lock order admission →
page → git) and passes ``before`` (``git_service.snapshot_dirty_sync``), so an edit already on a page is committed apart,
never as the person's join. Engine-free; never a model call.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import markdown_parser

SUBJECT_MERGE = "Merged pages"
SUBJECT_SPLIT = "Split a page"
SUBJECT_UNDO = "Undid a page join"
SUBJECTS = (SUBJECT_MERGE, SUBJECT_SPLIT)
#: The undo commit's body line naming the join it took back (read by ``page_history`` to stop offering it).
UNDOES = "Undoes: "
#: The app's door; an agent's is ``mcp/<harness>`` (``ToolContext.trigger``).
TRIGGER_APP = "user/companion_app"
MAX_REASON = 300

_SHA = re.compile(r"^[0-9a-f]{7,40}$")


class JoinError(ValueError):
    """A join refused, with a sentence the person can read and the HTTP status it answers."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def kind_of(subject: str) -> str | None:
    """``merge`` / ``split`` / ``undo`` for a join commit's subject line, else ``None``."""
    s = str(subject or "")
    if s.startswith(SUBJECT_MERGE):
        return "merge"
    if s.startswith(SUBJECT_SPLIT):
        return "split"
    if s.startswith(SUBJECT_UNDO):
        return "undo"
    return None


def _page(memory_path: Path, entity_id: str) -> Path:
    eid = str(entity_id or "").strip()
    p = Path(memory_path) / "entities" / f"{eid}.md"
    if not eid or "/" in eid or not p.is_file():
        raise JoinError(f"No page '{entity_id}'.", 404)
    return p


def _clean_reason(reason: str | None) -> str:
    return " ".join(str(reason or "").split())[:MAX_REASON]


def _invalidate(memory_path: Path) -> None:
    import os

    from api.services import bank_index, page_redirects

    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))
    page_redirects.invalidate()


def _commit(memory_path: Path, subject: str, lines: list[str], paths: list[str], *, authors: list[str],
            session: str | None, before) -> str | None:
    """Commit exactly ``paths`` under ``authors``; the new commit's id, or ``None`` with no git."""
    from api.services import git_service

    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        return None
    message = git_service.build_commit_message(f"{subject} {date.today().isoformat()}", lines, authors=authors,
                                               sessions=[session] if session else None)
    with git_service.write_lock(memory_path):
        git_service.commit_touched_sync(memory_path, message, paths, before=before,
                                        kept_subject=f"Uncommitted edit kept apart {date.today().isoformat()}",
                                        kept_trigger="user/kept-apart")
        out = subprocess.run(["git", "-C", str(memory_path), "log", "-1", "--format=%H%x1f%s"],
                             capture_output=True, text=True)
    sha, _, subj = out.stdout.strip().partition("\x1f")
    return sha if out.returncode == 0 and subj.startswith(subject) else None


def _authors(author) -> list[str]:
    return [author] if isinstance(author, str) else [str(a) for a in author or () if a] or ["user"]


def _manifest(paths: list[str], trigger: str, *, created: set[str] = frozenset(),
              removed: set[str] = frozenset()) -> list[str]:
    out = []
    for rel in dict.fromkeys(paths):
        verb = "created" if rel in created else "removed" if rel in removed else "updated"
        out.append(f"{rel}: {verb} (trigger: {trigger})")
    return out


# --- merge ------------------------------------------------------------------------------------------------------------

def merge(memory_path, loser_id: str, winner_id: str, *, author: str | list[str] = "user",
          trigger: str = TRIGGER_APP, reason: str | None = None, session: str | None = None, before=None,
          extra_paths=(), extra_lines=()) -> dict:
    """Fold ``loser_id`` into ``winner_id`` and commit it alone. ``{winner, loser, commit, paths, ...}``."""
    from api.services import entity_merge, merge_rejections
    from api.services.claims import MalformedClaimsBlockError
    from api.services.id_utils import sanitize_id

    memory_path = Path(memory_path)
    lp, wp = _page(memory_path, loser_id), _page(memory_path, winner_id)
    if lp.stem == wp.stem or lp.samefile(wp):
        raise JoinError("A page cannot be merged into itself.")
    lfm = markdown_parser.parse(lp).frontmatter
    wfm = markdown_parser.parse(wp).frontmatter

    def names(fm: dict, pid: str) -> set[str]:
        return {pid, sanitize_id(str(fm.get("name") or pid))}

    try:
        result = entity_merge.merge_entities(memory_path, loser_id=lp.stem, winner_id=wp.stem)
    except MalformedClaimsBlockError as exc:
        raise JoinError("A page's beliefs could not be read; nothing was merged.", 409) from exc
    # The person said they are one: any "different" answer or split between them is cleared.
    cleared = merge_rejections.clear_pairs(
        memory_path, [(a, b) for a in names(lfm, lp.stem) for b in names(wfm, wp.stem) if a != b])
    paths = list(dict.fromkeys(result.get("paths") or []))
    if cleared:
        paths.append(merge_rejections.FILE)
    # And a held mention's "Another one" (#546, `pending_store.mark_apart`) under either page's name that kept it apart
    # from the other: the person has now said they are one.
    from api.services import pending_store

    lifted = False
    for name, other in ((str(lfm.get("name") or lp.stem), wp.stem), (str(wfm.get("name") or wp.stem), lp.stem)):
        lifted |= pending_store.clear_apart(memory_path, name, other)
    if lifted:
        paths.append(pending_store.PENDING_STORE_FILE)
    lines = [*_manifest(paths, trigger, removed={f"entities/{lp.stem}.md"}), *extra_lines]
    if reason:
        lines += ["", f"Reason: {_clean_reason(reason)}"]
    commit = _commit(memory_path, SUBJECT_MERGE, lines, [*paths, *extra_paths], authors=_authors(author),
                     session=session, before=before)
    _invalidate(memory_path)
    logger.info(f"page_join: merged {lp.stem} into {wp.stem} ({len(paths)} paths)")
    return {"winner": wp.stem, "loser": lp.stem, "commit": commit, "paths": paths,
            "merged_claims": result.get("merged_claims", 0), "repointed_refs": result.get("repointed_refs", 0)}


# --- split ------------------------------------------------------------------------------------------------------------

def reference_choice(episodes, moved: set[str], staying: set[str]) -> str:
    """Which page another page's link meant, from its own evidence only: ``new`` when every conversation it rests on
    moved to the new page, ``stay`` when every one stayed, ``ask`` otherwise (mixed, none, or not this page's) — never
    a guess."""
    eps = {str(e) for e in episodes or () if e}
    if not eps:
        return "ask"
    if eps <= moved and not eps & staying:
        return "new"
    if eps <= staying and not eps & moved:
        return "stay"
    return "ask"


@dataclass
class _Ref:
    page_id: str
    name: str
    claims: list[str] = field(default_factory=list)   # this page's claim ids naming the split page as object
    episodes: set[str] = field(default_factory=set)
    links: int = 0                                    # wikilinks / related / source links to it


def _wikilink_id_re(page_id: str, name: str) -> re.Pattern:
    from api.services import entity_merge

    return entity_merge._wikilink_re(page_id, name)


def _references(memory_path: Path, page_id: str, name: str) -> list[_Ref]:
    """Every other page that points at ``page_id``: a claim whose node object names it, a wikilink by its id or
    title, a ``related`` entry, a source's ``entity:`` link. One read of each page whose text names it."""
    from api.services import bank_index
    from api.services.claims import MalformedClaimsBlockError, parse_claims

    keys = {page_id.lower(), str(name or "").lower()} - {""}
    link_re = _wikilink_id_re(page_id, name)
    out: list[_Ref] = []
    named = _pages_naming(Path(memory_path), keys)
    ents = Path(memory_path) / "entities"
    if named is not None:
        paths = [ents / f"{stem}.md" for stem in sorted(named) if (ents / f"{stem}.md").is_file()]
    else:
        paths = [f.path for f in bank_index.files(memory_path, "entities")]
    for path in paths:
        if path.stem == page_id:
            continue
        if named is None:
            try:
                low = path.read_text(encoding="utf-8").lower()
            except OSError:
                continue
            if not any(k in low for k in keys):
                ledger = path.with_name(f"{path.stem}.claims.jsonl")
                if not ledger.exists() or page_id not in ledger.read_text(encoding="utf-8", errors="replace"):
                    continue
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        ref = _Ref(path.stem, str(fm.get("name") or path.stem))
        try:
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError:
            claims = []
        for c in claims:
            if c.object_kind != "literal" and str(c.object or "").strip().lower() == page_id.lower():
                ref.claims.append(c.id)
                ref.episodes.update(str(e) for e in c.source_episodes or () if e)
        ref.links += len(link_re.findall(parsed.body))
        ref.links += sum(1 for r in fm.get("related") or () if isinstance(r, str) and r.lower() == page_id.lower())
        ref.links += sum(1 for s in fm.get("sources") or () if isinstance(s, dict) and str(s.get("entity") or "")
                         == page_id)
        if ref.claims or ref.links:
            out.append(ref)
    return out


def _pages_naming(memory_path: Path, keys: set[str]) -> set[str] | None:
    """The page ids whose file or claims ledger names any of ``keys`` (case-insensitive), by one ``git grep`` over the
    working tree (tracked and untracked) — ~0.1 s against reading every page on an 8,000-page bank. ``None`` when the
    bank is not under git or the grep fails: the caller reads every page instead."""
    if not (memory_path / ".git").exists() or not keys:
        return None
    args = ["git", "-C", str(memory_path), "grep", "-l", "-z", "-i", "-F", "--untracked"]
    for k in sorted(keys):
        args += ["-e", k]
    proc = subprocess.run([*args, "--", "entities/"], capture_output=True)
    if proc.returncode not in (0, 1):
        return None
    out: set[str] = set()
    for rel in proc.stdout.decode("utf-8", "replace").split("\0"):
        name = rel.rsplit("/", 1)[-1]
        if name.endswith(".claims.jsonl"):
            out.add(name[: -len(".claims.jsonl")])
        elif name.endswith(".md"):
            out.add(name[:-3])
    return out


def split_plan(memory_path, page_id: str, moves=()) -> dict:
    """What the split sheet shows: the page's numbered sentences (``moves`` from ``same_name_split`` pre-tick theirs,
    with the judge's reason), its claims, sources, conversations and the pages that link to it — each link with what
    its evidence says (``episodes``; the sheet applies :func:`reference_choice` as conversations are ticked). Reads
    only; the new page's proposed id and title come with it."""
    from api.services import bank_index, fact_sources, same_name_split
    from api.services.claims import is_event, is_record, parse_claims

    memory_path = Path(memory_path)
    page = _page(memory_path, page_id)
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter or {}
    name = str(fm.get("name") or page.stem)
    suggested = {int(m.n): str(m.reason or "") for m in moves or () if getattr(m, "page_id", page.stem) == page.stem}
    sentences = [{"n": s.n, "section": s.section, "text": s.text, "suggested": s.n in suggested,
                  "reason": suggested.get(s.n) or None}
                 for s in same_name_split.sentences(parsed.body)]
    claims = [{"id": c.id, "text": c.text, "predicate": c.predicate, "object": c.object,
               "episodes": list(c.source_episodes or []),
               # R-PJ3: a done happening is born closed — a dated event, never a belief "no longer current".
               "event": is_event(c), "record": is_record(c),
               "current": is_event(c) or (c.valid_to is None and not c.superseded_by)}
              for c in parse_claims(parsed.body)]
    sources = [{"ref": str(s.get("ref") or ""), "predicate": str(s.get("predicate") or "") or None,
                "label": str(s.get("label") or s.get("title") or "") or None}
               for s in fact_sources.as_sources(fm.get("sources")) if s.get("ref")]
    conversations = []
    for eid in fm.get("source_episodes") or []:
        ep = bank_index.file(memory_path, "episodes", f"{eid}.md")
        efm = (ep.frontmatter if ep is not None else {}) or {}
        conversations.append({"id": str(eid), "title": str(efm.get("title") or "") or None,
                              "date": str(efm.get("timestamp") or "")[:10] or None})
    staying = {str(e) for e in fm.get("source_episodes") or []}
    references = [{"page_id": r.page_id, "name": r.name, "claims": len(r.claims), "links": r.links,
                   "episodes": sorted(r.episodes), "suggested": reference_choice(r.episodes, set(), staying)}
                  for r in _references(memory_path, page.stem, name)]
    return {"entity_id": page.stem, "name": name, "type": str(fm.get("type") or "concept"),
            "new_id": _new_id(memory_path, name), "new_name": name,
            "sentences": sentences, "claims": claims, "sources": sources, "conversations": conversations,
            "references": references}


def _new_id(memory_path: Path, name: str) -> str:
    """The title's own slug when it is free, else ``<slug>-2``, ``-3`` … — `entity_resolver._another_id`'s rule, spelled
    here because importing the resolver cost 2.3 s of a 3.0 s cold split-sheet open on an 8,000-page bank copy. A slug
    a merge retired (`page_redirects`) is never reused: its old links would open the new page."""
    from api.services import page_redirects
    from api.services.id_utils import sanitize_id

    ents = Path(memory_path) / "entities"
    taken = set(page_redirects.load(memory_path))
    slug = sanitize_id(name)
    if slug and slug not in taken and not (ents / f"{slug}.md").exists():
        return slug
    n = 2
    while f"{slug}-{n}" in taken or (ents / f"{slug}-{n}.md").exists():
        n += 1
    return f"{slug}-{n}"


def _take_sentences(prose: str, picked: set[int]) -> tuple[str, list[tuple[str, str]]]:
    """``prose`` without the picked sentences, and the picked ``[(section, sentence)]`` in reading order. Walks the
    lines exactly as ``same_name_split.sentences`` numbers them; a line left with nothing is dropped, and a heading
    whose section is left empty goes with it."""
    from api.services import same_name_split as sns

    out_lines: list[str] = []
    moved: list[tuple[str, str]] = []
    section = ""
    in_fence = False
    n = 0
    for raw in prose.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            out_lines.append(raw)
            continue
        if in_fence or not line:
            out_lines.append(raw)
            continue
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            out_lines.append(raw)
            continue
        if sns._LINK_ONLY.match(line) or line.startswith("|"):
            out_lines.append(raw)
            continue
        marker = re.match(r"^(\s*(?:(?:[-*+]|\d+[.)])\s+)?)", raw).group(1)
        content = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line)
        kept: list[str] = []
        took = False
        for piece in sns._SPLIT.split(content):
            text = piece.strip()
            if len(text) >= sns.MIN_CHARS and re.search(r"[A-Za-z]", text):
                n += 1
                if n in picked:
                    moved.append((section, text))
                    took = True
                    continue
            if text:
                kept.append(text)
        if not took:
            out_lines.append(raw)
        elif kept:
            out_lines.append(marker + " ".join(kept))
    # A heading left with nothing under it (its every sentence moved) goes too.
    cleaned: list[str] = []
    for i, raw in enumerate(out_lines):
        if raw.strip().startswith("#"):
            rest = out_lines[i + 1:]
            nxt = next((r for r in rest if r.strip()), "")
            if not nxt or nxt.strip().startswith("#"):
                had = any(sec == raw.strip().lstrip("#").strip() for sec, _ in moved)
                if had:
                    continue
        cleaned.append(raw)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()
    return text, moved


def _new_body(moved: list[tuple[str, str]]) -> str:
    """The new page's prose: the moved sentences under the headings they sat under, a Summary first."""
    groups: dict[str, list[str]] = {}
    for section, text in moved:
        groups.setdefault(section or "Summary", []).append(text)
    if "Summary" not in groups and groups:
        first = next(iter(groups))
        groups = {"Summary": groups[first], **{k: v for k, v in groups.items() if k != first}}
    return "\n\n".join(f"## {sec}\n{' '.join(texts)}" for sec, texts in groups.items())


def split(memory_path, page_id: str, *, sentences=(), claims=(), sources=(), episodes=(), references=None,
          name: str | None = None, entity_type: str | None = None, author: str | list[str] = "user",
          trigger: str = TRIGGER_APP, reason: str | None = None, session: str | None = None, before=None,
          extra_paths=(), extra_lines=()) -> dict:
    """Move what the person picked from ``page_id`` to a new page and commit it alone.

    ``sentences``: numbers from :func:`split_plan`; ``claims``: claim ids; ``sources``: source refs; ``episodes``:
    conversation ids; ``references``: ``{other page id: "new" | "stay"}`` — a page not named is re-pointed only when
    its evidence says the new page (:func:`reference_choice`), never otherwise. Refused, nothing written (400): nothing
    picked, an id the page does not hold, a type outside the closed set."""
    from api.services import decay_policy, entity_merge, entity_types, fact_sources, merge_rejections, same_name_split
    from api.services.claims import MalformedClaimsBlockError, parse_claims, strip_claims_block, write_claims

    memory_path = Path(memory_path)
    page = _page(memory_path, page_id)
    pid = page.stem
    parsed = markdown_parser.parse(page)
    fm = dict(parsed.frontmatter or {})
    old_name = str(fm.get("name") or pid)
    try:
        all_claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError as exc:
        raise JoinError("This page's beliefs could not be read; nothing was split.", 409) from exc

    picked_n = {int(n) for n in sentences or ()}
    numbered = {s.n for s in same_name_split.sentences(parsed.body)}
    if picked_n - numbered:
        raise JoinError(f"Sentence {sorted(picked_n - numbered)[0]} is not on this page any more; open the split "
                        "again.", 409)
    claim_ids = {str(c) for c in claims or ()}
    by_id = {c.id: c for c in all_claims}
    if claim_ids - set(by_id):
        raise JoinError(f"Belief {sorted(claim_ids - set(by_id))[0]} is not on this page.", 409)
    page_sources = fact_sources.as_sources(fm.get("sources"))
    source_refs = {str(s) for s in sources or ()}
    if source_refs - {str(s.get("ref") or "") for s in page_sources}:
        raise JoinError("A source picked is not on this page.", 409)
    page_eps = [str(e) for e in fm.get("source_episodes") or []]
    ep_ids = {str(e) for e in episodes or ()}
    if ep_ids - set(page_eps):
        raise JoinError("A conversation picked is not on this page.", 409)
    if not picked_n and not claim_ids:
        raise JoinError("Pick at least one sentence or belief that belongs to the other thing.")
    if picked_n and picked_n == numbered and not claim_ids and not strip_claims_block(parsed.body).strip():
        raise JoinError("Every sentence would move; nothing would stay on this page.")
    new_type = str(fm.get("type") or "concept")
    if entity_type:
        known = entity_types.known(entity_type)
        if known is None or known not in entity_types.PRODUCIBLE:   # never a saved link or a deadline by hand
            raise JoinError(f"'{entity_type}' is not a page type a split can make.")
        new_type = known
    new_name = " ".join(str(name or old_name).split()) or old_name
    new_id = _new_id(memory_path, new_name)

    # The page that stays.
    kept_prose, moved_sentences = _take_sentences(strip_claims_block(parsed.body), picked_n)
    moved_claims = [c for c in all_claims if c.id in claim_ids]
    kept_claims = [c for c in all_claims if c.id not in claim_ids]
    fm["source_episodes"] = [e for e in page_eps if e not in ep_ids]
    if not fm["source_episodes"]:
        fm.pop("source_episodes")
    moved_sources = [s for s in page_sources if str(s.get("ref") or "") in source_refs]
    if isinstance(fm.get("sources"), list):
        fm["sources"] = [s for s in fm["sources"]
                         if not (isinstance(s, dict) and str(s.get("ref") or "") in source_refs)]
        if not fm["sources"]:
            fm.pop("sources")
    body = write_claims(kept_prose, kept_claims) if all_claims else kept_prose
    markdown_parser.write(page, fm, body)

    # The new page: a clean title, its own id, what moved.
    for c in moved_claims:
        entity_merge._repoint_claim(c, {pid.lower()}, pid, new_id)
    today = date.today().isoformat()
    cls = decay_policy.default_class_for(new_type) if new_type != fm.get("type") else None
    nfm = {
        "name": new_name, "type": new_type, "status": "active",
        "confidence": float(fm.get("confidence", 0.5) or 0.5),
        "created": today,
        **({"last_referenced": fm["last_referenced"]} if fm.get("last_referenced") else {"last_referenced": today}),
        **({"learned_on": fm["learned_on"]} if fm.get("learned_on") else {}),
        **(decay_policy.frontmatter_fields(cls) if cls is not None else
           {k: fm[k] for k in ("decay_class", "decay_rate") if k in fm}),
        "source_episodes": [e for e in page_eps if e in ep_ids],
        **({"sources": moved_sources} if moved_sources else {}),
        "tags": [], "related": [], "version": 1, "layout_version": 2,
    }
    nbody = _new_body(moved_sentences) or f"## Summary\n{new_name}."
    if moved_claims:
        nbody = write_claims(nbody, moved_claims)
    new_path = page.with_name(f"{new_id}.md")
    try:
        markdown_parser.write_new(new_path, nfm, nbody)
    except FileExistsError as exc:
        raise JoinError("A page with that id appeared meanwhile; try again.", 409) from exc

    paths = [f"entities/{pid}.md", f"entities/{new_id}.md"]
    # Other pages' links: re-pointed only where the person said so, or the evidence says the new page.
    moved_eps, staying = set(ep_ids), {e for e in page_eps if e not in ep_ids}
    chosen = {str(k): str(v) for k, v in (references or {}).items()}
    repointed: list[str] = []
    for ref in _references(memory_path, pid, old_name):
        if ref.page_id == new_id:
            continue
        choice = chosen.get(ref.page_id) or reference_choice(ref.episodes, moved_eps, staying)
        if choice != "new":
            continue
        if _repoint_one(memory_path, ref.page_id, pid, old_name, new_id, new_name):
            repointed.append(ref.page_id)
            paths.append(f"entities/{ref.page_id}.md")
    if _repoint_edges(memory_path, pid, new_id, {c.id for c in moved_claims}, set(repointed)):
        paths.append("graph_edges.yaml")
    merge_rejections.add_split(memory_path, pid, new_id)
    paths.append(merge_rejections.FILE)

    lines = [*_manifest(paths, trigger, created={f"entities/{new_id}.md"}), *extra_lines]
    lines += ["", f"Split from: {pid} -> {new_id} ({len(moved_sentences)} sentences, {len(moved_claims)} beliefs, "
                  f"{len(moved_sources)} sources, {len(ep_ids)} conversations)"]
    if reason:
        lines.append(f"Reason: {_clean_reason(reason)}")
    commit = _commit(memory_path, SUBJECT_SPLIT, lines, [*paths, *extra_paths], authors=_authors(author),
                     session=session, before=before)
    _invalidate(memory_path)
    logger.info(f"page_join: split {pid} -> {new_id} ({len(paths)} paths)")
    return {"entity_id": pid, "new_id": new_id, "new_name": new_name, "commit": commit, "paths": paths,
            "moved": {"sentences": len(moved_sentences), "claims": len(moved_claims), "sources": len(moved_sources),
                      "conversations": len(ep_ids)},
            "repointed": repointed}


def _repoint_one(memory_path: Path, ref_id: str, old_id: str, old_name: str, new_id: str, new_name: str) -> bool:
    """One other page's links to ``old_id``, now to ``new_id``: its claims' node objects, wikilinks (by id, or by the
    title — written as ``[[new-id|Title]]``, since the title alone names both pages now), ``related`` and a source's
    ``entity:``."""
    from api.services import entity_article
    from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

    path = Path(memory_path) / "entities" / f"{ref_id}.md"
    parsed = markdown_parser.parse(path)
    fm, body = dict(parsed.frontmatter), parsed.body
    changed = False
    try:
        cl = parse_claims(body, strict=True)
    except MalformedClaimsBlockError:
        cl = None
    if cl:
        hit = False
        for c in cl:
            if c.object_kind != "literal" and str(c.object or "").strip().lower() == old_id.lower():
                c.object = new_id
                hit = True
        if hit:
            body = write_claims(body, cl)
            changed = True
    link_re = _wikilink_id_re(old_id, old_name)
    def relink(m: re.Match) -> str:
        tail = m.group(2)
        if "|" not in tail:   # the title alone names both pages now: the link keeps it as its label
            tail = f"{tail[:-2].rstrip()}|{new_name}]]"
        return f"{m.group(1)}{new_id}{tail}"

    relinked, n = link_re.subn(relink, body)
    if n:
        entity_article.carry_stamp(fm, body, relinked)
        body = relinked
        changed = True
    if isinstance(fm.get("related"), list):
        rel = [new_id if isinstance(r, str) and r.lower() == old_id.lower() else r for r in fm["related"]]
        if rel != fm["related"]:
            fm["related"] = rel
            changed = True
    for s in fm.get("sources") or ():
        if isinstance(s, dict) and str(s.get("entity") or "") == old_id:
            s["entity"] = new_id
            changed = True
    if changed:
        markdown_parser.write(path, fm, body)
    return changed


def _repoint_edges(memory_path: Path, old_id: str, new_id: str, claim_ids: set[str], pages: set[str]) -> bool:
    """``graph_edges.yaml``: an edge drawn from a moved claim, or between the split page and a page re-pointed above,
    now ends at the new page. Every other edge, and every field, stays as it was."""
    f = Path(memory_path) / "graph_edges.yaml"
    if not f.exists() or not (claim_ids or pages):
        return False
    data = markdown_parser.load_yaml(f.read_text(encoding="utf-8")) or {}
    changed = False
    for e in data.get("edges") or []:
        if not isinstance(e, dict) or old_id not in (e.get("source"), e.get("target")):
            continue
        other = e.get("target") if e.get("source") == old_id else e.get("source")
        if str(e.get("claim_id") or "") in claim_ids or other in pages:
            for end in ("source", "target"):
                if e.get(end) == old_id:
                    e[end] = new_id
            changed = True
    if changed:
        markdown_parser.write_yaml(f, data)
    return changed


# --- undo -------------------------------------------------------------------------------------------------------------

def _subject(memory_path: Path, sha: str) -> str:
    out = subprocess.run(["git", "-C", str(memory_path), "log", "-1", "--format=%s", sha], capture_output=True,
                         text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def undone(memory_path, sha: str) -> bool:
    """Has a later commit taken this join back?"""
    out = subprocess.run(["git", "-C", str(memory_path), "log", "--format=%H", "-F", f"--grep={UNDOES}{sha}",
                          "-n1", "HEAD"], capture_output=True, text=True)
    return out.returncode == 0 and bool(out.stdout.strip())


def latest(memory_path, page_id: str) -> tuple[str, str] | None:
    """``(commit, kind)`` of the newest merge or split on ``page_id``'s page not yet taken back — what "undo that split"
    means when the person names the page, not the change. ``None`` when there is none (or no git)."""
    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        return None
    out = subprocess.run(["git", "-C", str(memory_path), "log", "-n200", "--format=%x1e%H%x1f%s%x1f%b",
                          "--", f"entities/{page_id}.md"], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    taken_back: set[str] = set()
    for record in out.stdout.split("\x1e")[1:]:
        sha, _, rest = record.partition("\x1f")
        subject, _, body = rest.partition("\x1f")
        kind = kind_of(subject)
        if kind == "undo":
            taken_back.update(line[len(UNDOES):].strip() for line in body.splitlines() if line.startswith(UNDOES))
        elif kind in ("merge", "split") and sha.strip() not in taken_back:
            return sha.strip(), kind
    return None


def undo(memory_path, sha: str, *, author: str | list[str] = "user", trigger: str = TRIGGER_APP, before=None,
         session: str | None = None, reason: str | None = None, extra_paths=(), extra_lines=()) -> dict:
    """Take one merge or split back: the reverse of its commit applied onto each file as it is now. Refused whole, with
    a sentence and nothing written, when anything since changed the same place (409), when it is not a join (404) or
    was already taken back (409). ``{kind, commit, paths, restored, removed}`` — ``removed``: pages the undo took away
    (a split's new page), so the app leaves one it was showing."""
    from api.services import inbox_tend

    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        raise JoinError("This memory is not versioned; there is nothing to undo.", 409)
    sha = str(sha or "").strip().lower()
    if not _SHA.match(sha):
        raise JoinError("No such change.", 404)
    full = subprocess.run(["git", "-C", str(memory_path), "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
                          capture_output=True, text=True).stdout.strip()
    kind = kind_of(_subject(memory_path, full)) if full else None
    if kind not in ("merge", "split"):
        raise JoinError("That change is not a merge or a split.", 404)
    if undone(memory_path, full):
        raise JoinError("That change was already undone.", 409)
    writes: list[tuple[str, bytes | None]] = []
    created_by_join: set[str] = set()
    for rel in inbox_tend._changed(memory_path, full):
        b = inbox_tend._git_bytes(memory_path, f"{full}^:{rel}")
        a = inbox_tend._git_bytes(memory_path, f"{full}:{rel}")
        target = memory_path / rel
        c = target.read_bytes() if target.is_file() else None
        if a is None:
            created_by_join.add(rel)   # the join removed it (a merge's loser): taking it back restores it
        if c == b:
            continue
        if c == a:
            writes.append((rel, b))
            continue
        if rel in inbox_tend._LIST_FILES and None not in (c, a):
            merged = inbox_tend._reverse_list(rel, c, a, b or b"")
            if merged is not None:
                writes.append((rel, merged))
                continue
        if None not in (c, a, b):
            merged = inbox_tend._reverse(memory_path, c, a, b)
            if merged is not None:
                writes.append((rel, merged))
                continue
        what = "the page" if rel.startswith("entities/") else rel
        raise JoinError(f"{what[0].upper()}{what[1:]} changed since in the same place ({rel}); nothing was undone. "
                        + ("Merge the two pages again instead." if kind == "split"
                           else "Split the page again instead."), 409)
    if not writes:
        raise JoinError("Nothing to undo: the pages are already as they were before.", 409)
    paths: list[str] = []
    restored: list[str] = []
    for rel, data in writes:
        target = memory_path / rel
        if data is None:
            target.unlink(missing_ok=True)
        else:
            inbox_tend._write_bytes(target, data)
            if rel in created_by_join and rel.startswith("entities/") and rel.endswith(".md"):
                restored.append(Path(rel).stem)
        paths.append(rel)
    _invalidate(memory_path)
    lines = _manifest(paths, trigger, created={f"entities/{r}.md" for r in restored},
                      removed={rel for rel, data in writes if data is None})
    lines += [*extra_lines, "", f"{UNDOES}{full}"]
    if reason:
        lines.append(f"Reason: {_clean_reason(reason)}")
    commit = _commit(memory_path, SUBJECT_UNDO, lines, [*paths, *extra_paths], authors=_authors(author),
                     session=session, before=before)
    removed = [Path(rel).stem for rel, data in writes
               if data is None and rel.startswith("entities/") and rel.endswith(".md")]
    return {"kind": kind, "commit": commit, "undid": full, "paths": paths, "restored": restored, "removed": removed}


# --- an agent the person has not listed proposes ----------------------------------------------------------------------

#: A proposed join rides the G198 proposal kind (``page_edit``: "an agent proposed a change to a page; the person
#: applies it or leaves it", one tap, in the app only) with a ``join`` payload instead of an ``edit`` one — one kind, so
#: every surface that already shows, refuses to relay and grades a proposed edit does the same for a join.
PROPOSAL_SUBJECT = "Page join proposed"


def write_proposal(memory_path, *, op: str, entity_id: str, payload: dict, reason: str, author: str,
                   session: str | None) -> str:
    """One ``page_edit`` inbox item carrying a join; returns its bank-relative path. Never replaces an item."""
    from api.services import inbox_service, page_edits

    memory_path = Path(memory_path)
    page = _page(memory_path, entity_id)
    fm0 = markdown_parser.parse(page).frontmatter or {}
    name = str(fm0.get("name") or entity_id)
    if op == "undo":
        what = "merge" if kind_of(_subject(memory_path, str(payload.get("commit") or ""))) == "merge" else "split"
        title = f"Undo the {what} on {name}?"
        lines = [f"- Put **{name}** (`{entity_id}`) back as it was before that {what}."]
    elif op == "merge":
        into = _page(memory_path, str(payload.get("into") or ""))
        into_name = str((markdown_parser.parse(into).frontmatter or {}).get("name") or into.stem)
        title = f"Merge {name} into {into_name}?"
        lines = [f"- Merge **{name}** (`{entity_id}`) into **{into_name}** (`{into.stem}`): its beliefs, sources, "
                 f"aliases and links move there, and `{entity_id}` keeps pointing at it."]
    else:
        plan = split_plan(memory_path, entity_id)
        picked = {int(n) for n in payload.get("sentences") or ()}
        title = f"Split {name}?"
        lines = [f"- Split **{name}** (`{entity_id}`): what follows moves to a new page called "
                 f"**{payload.get('name') or name}**."]
        lines += [f"  > {row['text']}" for row in plan["sentences"] if row["n"] in picked]
        n_claims = len(payload.get("claims") or ())
        if n_claims:
            lines.append(f"- {n_claims} belief{'s' if n_claims != 1 else ''} move with them.")
    fm = {
        "kind": page_edits.KIND, "required_input": "choice", "status": "pending", "priority": 0.5,
        "entity_id": entity_id, "entity_name": name, "title": title, "created_date": date.today().isoformat(),
        "question": f"An agent suggests this: {reason}",
        "options": [{"key": "apply", "label": {"merge": "Merge them", "undo": "Undo it"}.get(op, "Split it")},
                    {"key": "dismiss", "label": "Leave the page as it is"}],
        "allow_other": False, "allow_defer": True,
        "proposed_by": author, "reason": reason, "join": {"op": op, **payload},
        "trigger": f"mcp/{author}",
    }
    if session:
        fm["session_id"] = session
    body = "\n".join([f"Why: {reason}", "", *lines])
    inbox_dir = memory_path / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(50):
        path = inbox_dir / f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}.md"
        try:
            markdown_parser.write_new(path, fm, body)
        except FileExistsError:
            continue
        return f"inbox/{path.name}"
    raise JoinError("Could not file the proposal: the inbox is busy. Try again.", 409)


def apply_proposal(memory_path, fm: dict, *, rel_item: str, trigger: str, before=None) -> dict:
    """The person applied a proposed join: run it as proposed, committed with the retired item under the agent that
    proposed it and the person who accepted it."""
    join = dict(fm.get("join") or {})
    op = str(join.pop("op", ""))
    authors = [str(fm.get("proposed_by") or "agent"), "user"]
    session = str(fm.get("session_id") or "").strip() or None
    reason = str(fm.get("reason") or "") or None
    extra = dict(extra_paths=[rel_item], extra_lines=[f"{rel_item}: removed (trigger: {trigger})"])
    entity_id = str(fm.get("entity_id") or "")
    if op not in ("merge", "split", "undo"):
        raise JoinError("This proposal is not a merge, a split or an undo.", 409)
    item = Path(memory_path) / rel_item
    held = item.read_bytes() if item.is_file() else None
    item.unlink(missing_ok=True)   # retired in the join's own commit
    try:
        if op == "merge":
            return merge(memory_path, entity_id, str(join.get("into") or ""), author=authors, trigger=trigger,
                         reason=reason, session=session, before=before, **extra)
        if op == "undo":
            return undo(memory_path, str(join.get("commit") or ""), author=authors, trigger=trigger, before=before,
                        session=session, reason=reason, **extra)
        return split(memory_path, entity_id, sentences=join.get("sentences") or (), claims=join.get("claims") or (),
                     sources=join.get("sources") or (), episodes=join.get("episodes") or (),
                     references=join.get("references") or None, name=join.get("name"),
                     entity_type=join.get("type"), author=authors, trigger=trigger, reason=reason, session=session,
                     before=before, **extra)
    except JoinError:
        if held is not None:   # refused before writing: the question stays for the person
            item.write_bytes(held)
        raise
