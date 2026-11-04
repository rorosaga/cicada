"""A page's prose follows a conversation that revised itself (G104 slice 2, owner 2026-11-03).

`episode_revision` reads an edited conversation as a revision of itself and closes the claims only its removed text
said. The prose written from the first read — the Summary, the Article, Key Facts, Open Questions — still said the old
thing: in #581's measured run a meeting moved from Friday to Thursday read as both, and a removed line's fact stayed in
Key Facts. The owner, 2026-11-03: "Sleep regenerates a page's prose from its corrected claims when a revision closes
one, limited to the pages a revision touched."

**What changed** (:func:`changes_of`). Each replaced or removed block of the line diff, with the words it took away:
the tokens of its removed text the new body no longer has anywhere (``gone``), and the tokens its replacement brings
(``fresh``). A block that took no word away — a reworded line saying the same things, an addition, whitespace — is no
change here, so a no-op revision costs nothing.

**Which pages** (:func:`page_job`). A page where this batch's revision closed or withdrew a claim (the claim pipeline's
``revision_closed``), or one whose passage was written from the version Sleep read (a `section_provenance` row into
the revised conversation at its old hash) and says a word the revision took away. The claim layer is the extractor's
choice — #581's haiku run held the meeting as a node, never as a day — so the provenance rows are the second way the
same fact is found: the passage came from those words, and those words are gone.

**Which passages: provenance only** (review of #589). A passage that says a gone word is offered for rewriting only
when its rows name the revised conversation and no other source it cites still says that word — a passage resting
also on another conversation that says it keeps it (#581's settle rule: another conversation's word is never closed
by this one's edit). A passage with no rows is never rewritten (legacy prose, the person's typed or edited line, a line
a page merge carried: protection by default). History is never rewritten: it is the record of what was said when.
Beside them, the passages this batch already wrote from the revision's new words (rows at the new hash, a fresh word),
so the writer can keep the current fact once instead of twice.

**Never over the person's or an agent's words.** A passage is held (:func:`_held`) when it sits in a Summary or Article
someone rewrote (`entity_body.has_human_prose`), carries a pinned fix (G198 ``corrections``) about the words that
changed, or has a line git blames on a page edit (`page_edits` commits, any door); a passage with no rows is asked about
only when one of these says it is the person's, and otherwise left alone. A held passage is never rewritten:
the writer's proposal for it becomes ONE ``page_edit`` question per page in the inbox, Cicada's own (``origin:
revision``), which the person applies or leaves with one tap. A word-level pinned fix elsewhere in a rewritten passage
is applied again over what is written (`page_edits.apply_corrections`).

**One call per page, at most** (:func:`_call`), on the engine Sleep is running, inside its write window (Stage 5.58),
committed with the batch under Sleep's trailers. The writer returns the passages it changes — rewritten, or empty to
remove one that has nothing left or repeats a current fact — and one History sentence per change the History does not
already record. Code holds the rails (:func:`_rewrite_ok`): a rewrite never keeps a gone word its passage had, adds no
name, number or link that neither the passage nor the change's words give, holds no heading or fence and no relative
time word; a lead is never emptied; a fresh word the passages carried stays on the page; a History line names what was
there before. History is dated the day the conversation was revised (its ``revised.at``), never erased. Anything the
answer fails is left as it was; a failed call leaves the page as it was.

**Provenance moves with it** (:func:`reanchor_rows`, #581's "left" list). On every page citing a revised conversation,
a span row is located again on the new body (never fuzzily) and a whole-conversation row takes the new hash — except on
a passage that still says a gone word, whose rows keep the old hash (it rests on the version that said it). A rewritten
passage carries its old rows into other conversations plus the revision itself.

Never raises into the cycle."""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from api.services import (entity_article, entity_body, episode_revision, evidence, markdown_parser, page_edits,
                          section_provenance)
from api.services.claims import Evidence

#: Cicada's own inbox proposal for a held passage (`page_edits.write_proposal`'s ``origin``).
ORIGIN = "revision"
AUTHOR = "cicada"
#: Sections whose passages may be rewritten. History is the record; Links and Related are rebuilt from the graph.
SECTIONS = ("summary", "article", "key_facts", "open_questions")
#: At most this many pages a batch get the writer, and this many passages a page; the rest is logged and left.
MAX_PAGES = 40
MAX_PASSAGES = 40
MAX_CHANGES = 12
MAX_TEXT = 1200
MAX_HISTORY = 300

_TOKEN = re.compile(r"\w+", re.UNICODE)
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_STOP = frozenset("""
a an and are as at be been but by can did do does for from had has have he her his how i if in into is it its me my
no not of on or our she so than that the their them then there these they this those to was we were what when where
which who will with would you your about after again also any because before being both each few more most other over
own same should some such through under until very while just only now said says say yes
""".split())


def tokens(text: str) -> set[str]:
    """The words that can carry a fact: three letters or more, not a function word, casefolded."""
    return {t for t in (w.casefold() for w in _TOKEN.findall(text or "")) if len(t) >= 3 and t not in _STOP}


def _raw(text: str) -> set[str]:
    return {w.casefold() for w in _TOKEN.findall(text or "")}


@dataclass(frozen=True)
class Change:
    episode: str
    before: str
    after: str          # "" when the lines were only removed
    gone: frozenset
    fresh: frozenset


_SPEAKER = re.compile(r"^\s*(?:user|assistant|speaker:[^:\n]*):[ \t]*", re.M)


def _unmarked(text: str) -> str:
    """A block's words without the episode's speaker marks (``user:``, ``assistant:``, ``speaker:<label>:``)."""
    return _SPEAKER.sub("", text).strip()


def changes_of(rev) -> list[Change]:
    """Each replaced or removed block of ``rev`` that took a word away from the conversation."""
    if not rev.closes or rev.noop:
        return []      # a capped transcript's turns slide out by its cap, never by revision; whitespace says nothing
    body, prior = tokens(rev.body), tokens(rev.prior)
    out = []
    for tag, i1, i2, j1, j2 in rev.blocks:
        if tag not in ("replace", "delete"):
            continue
        before = _unmarked(rev.prior[i1:i2])
        after = _unmarked(rev.body[j1:j2]) if tag == "replace" else ""
        gone = tokens(before) - body
        if gone:
            out.append(Change(rev.episode_id, before, after, frozenset(gone), frozenset(tokens(after) - prior)))
    return out


@dataclass
class Passage:
    n: int
    section: str
    text: str
    ranges: tuple
    rows: list
    role: str                  # "old": says a gone word; "new": written this batch from the revision's new words
    held: str | None = None    # why it is never rewritten
    gone: frozenset = frozenset()


@dataclass
class Job:
    entity_id: str
    path: Path
    name: str
    frontmatter: dict
    body: str
    passages: list
    changes: list
    history: list              # the page's History lines, for the writer and the "already recorded" check
    days: dict                 # episode -> the day it was revised
    refused: dict = field(default_factory=dict)   # rail -> how many answers it refused (`_refusal`)


@dataclass
class Report:
    pages: int = 0
    calls: int = 0
    rewritten: int = 0
    removed: int = 0
    history: int = 0
    proposals: int = 0
    rows_moved: int = 0
    refused: int = 0
    refused_why: dict = field(default_factory=dict)
    failed: int = 0
    left: int = 0
    paths: list = field(default_factory=list)


# --------------------------------------------------------------------------- which passages


def _hand_lines(memory_path: Path, rel: str) -> set[str] | None:
    """The page's lines (stripped, bullet marks off) git blames on a page edit — the person's or an agent's own words,
    any door (`page_edits.COMMIT_SUBJECT`). ``None`` when git cannot say: the caller then rewrites nothing there."""
    if not (memory_path / ".git").exists():
        return set()
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel], cwd=memory_path,
                                 capture_output=True, timeout=10, env=env)
        if tracked.returncode != 0:
            return set()     # never committed: no edit of anyone's on it
        out = subprocess.run(["git", "blame", "--porcelain", "--", rel], cwd=memory_path, capture_output=True,
                             text=True, timeout=30, env=env)
        if out.returncode != 0:
            return None
        by_sha: dict[str, list[str]] = {}
        sha = None
        for line in out.stdout.splitlines():
            if line.startswith("\t"):
                if sha:
                    by_sha.setdefault(sha, []).append(line[1:])
            elif re.match(r"^[0-9a-f]{40} \d+ \d+", line):
                sha = line.split(" ", 1)[0]
        shas = [s for s in by_sha if s != "0" * 40]
        if not shas:
            return set()
        log = subprocess.run(["git", "log", "--no-walk=unsorted", "--format=%H%x1f%s", *shas, "--"], cwd=memory_path,
                             capture_output=True, text=True, timeout=30, env=env)
        if log.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    edits = set()
    for row in log.stdout.splitlines():
        sha, _, subject = row.partition("\x1f")
        subject = subject.strip()
        if subject == page_edits.COMMIT_SUBJECT or (subject.startswith(page_edits.COMMIT_SUBJECT + " ")
                                                   and not subject.startswith(page_edits.PROPOSAL_SUBJECT)):
            edits.add(sha)
    return {_line_key(text) for sha, lines in by_sha.items() if sha in edits for text in lines if text.strip()}


def _line_key(line: str) -> str:
    return " ".join(re.sub(r"^\s*[-*+]\s+", "", line).split())


def _held(section: str, text: str, gone: set[str], frontmatter: dict, human: bool, hand: set[str]) -> str | None:
    if section in ("summary", "article") and human:
        return "the lead or article was rewritten by hand"
    for row in page_edits.corrections(frontmatter):
        if row["new"] and row["new"] in text and (tokens(row["new"]) | tokens(row["old"])) & gone:
            return "it carries a pinned fix"
    if any(_line_key(line) in hand for line in text.splitlines() if line.strip()):
        return "its words were written by a page edit"
    return None


def page_job(memory_path: Path, entity_id: str, path: Path, revisions: dict, changes: dict[str, list[Change]],
             closed: set[str], days: dict[str, str]) -> Job | None:
    """The page's passages that say what a revision took away, or ``None`` (nothing to do: no call).

    **A passage is offered for rewriting only on its provenance** (review of #589, B2/B3): its `section_provenance`
    rows name the revised conversation on a version before this one, and no other source it cites still says the
    removed word — a passage resting also on another conversation that says it is that conversation's word too (#581's
    settle rule), never settled here. A passage with no rows is never rewritten: legacy prose, the person's typed or
    edited line (an edit drops its rows), or a line a page merge carried over — protection by default, whatever git
    blame says. Such a passage is only *asked about* when it is identifiably the person's (a pinned fix on the changed
    words, a hand-rewritten lead or article, a line blamed on a page edit)."""
    parsed = markdown_parser.parse(path, ledger=False)
    fm, body = parsed.frontmatter, parsed.body
    records = section_provenance.matched(fm, body)
    scanned = section_provenance.scan(body)
    unavailable = section_provenance.unavailable_sections(body)
    on_page: set[str] = set(closed)       # revisions that touched this page
    found: list[tuple] = []
    texts: dict[str, set[str] | None] = {}

    def still_says(ep: str) -> set[str] | None:
        """The words an episode's current text says (``None``: unreadable, so it may say anything)."""
        if ep not in texts:
            text = revisions[ep].body if ep in revisions else evidence.source_text(memory_path, ep)
            texts[ep] = None if text is None else tokens(text)
        return texts[ep]

    for section in SECTIONS:
        if section in unavailable:
            continue
        for item in scanned.get(section, []):
            rows = list(records.get(section, {}).get(item.key, (None, []))[1])
            said = tokens(item.text)
            for row in page_edits.corrections(fm):   # a pinned fix's own words count as what the passage says
                if row["new"] and row["new"] in item.text:
                    said |= tokens(row["old"])
            old_gone: set[str] = set()
            hand_gone: set[str] = set()
            fresh_hit = False
            for ep, chs in changes.items():
                rev = revisions[ep]
                gone = set().union(*(c.gone for c in chs)) & said
                if gone and not rows:
                    hand_gone |= gone        # asked about only if it is identifiably the person's (below)
                elif gone and any(ev.episode == ep and ev.hash != rev.hash for ev in rows):
                    others = {ev.episode for ev in rows if ev.episode != ep}
                    if all((words := still_says(o)) is not None and not words & gone for o in others):
                        old_gone |= gone
                        on_page.add(ep)
                if any(ev.episode == ep and ev.hash == rev.hash for ev in rows):
                    # The page was written from this revision too: its person's lines saying a removed word are
                    # asked about (never rewritten) even when no Sleep passage carried that word.
                    on_page.add(ep)
                    fresh_hit = fresh_hit or any(c.fresh & said for c in chs)
            if old_gone:
                found.append(("old", section, item, rows, frozenset(old_gone)))
            elif hand_gone:
                found.append(("hand", section, item, rows, frozenset(hand_gone)))
            elif fresh_hit:
                found.append(("new", section, item, rows, frozenset()))
    if not on_page:
        return None
    page_changes = [c for ep in sorted(on_page) for c in changes.get(ep, [])]
    if not page_changes:
        return None
    gone_all = set().union(*(c.gone for c in page_changes))
    # Only the words of the revisions that touched this page count.
    found = [(role, section, item, rows, gone & gone_all if role in ("old", "hand") else gone)
             for role, section, item, rows, gone in found if role == "new" or gone & gone_all]
    if not any(role in ("old", "hand") for role, *_ in found):
        return None
    sections = entity_body.parse_sections(page_edits.split_prose(body)[0])
    human = entity_body.has_human_prose(fm, sections)
    hand = _hand_lines(memory_path, f"entities/{path.name}")
    passages: list[Passage] = []
    for role, section, item, rows, gone in found[:MAX_PASSAGES]:
        if role == "new" and not any(c.fresh & tokens(item.text) for c in page_changes):
            continue
        held = "git could not say who wrote it" if hand is None else _held(section, item.text, gone_all, fm, human,
                                                                             hand)
        if role == "hand":
            if held is None or hand is None:
                continue             # no provenance and nothing says it is the person's: left alone, not asked
            role = "old"
        passages.append(Passage(len(passages) + 1, section, item.text, item.ranges, rows, role, held, gone))
    if not any(p.role == "old" for p in passages):
        return None
    history = [line.strip() for line in entity_body._bullet_lines(sections.get("History", ""))]
    return Job(entity_id, path, str(fm.get("name") or entity_id), fm, body, passages, page_changes[:MAX_CHANGES],
               history, days)


# --------------------------------------------------------------------------- the call


SYSTEM = """You correct an entity page in a personal knowledge graph after a conversation it was written from was edited.

The CHANGES are the conversation's own lines before and after the edit (or removed). The PASSAGES are the page's sentences that may say what the old lines said. Each fact should end up stated once, as the conversation says it now. For each passage that states something a change replaced or removed:
- when another passage (one marked (new), or one you keep) already states what the conversation says now, take the changed fact out of this passage: rewrite it with only its other details, or return "" to remove it when nothing else is left;
- otherwise rewrite it so it says what the conversation says now, keeping every other word, detail and [[link]] as written;
- when the change only removed the lines, take what they said out of the passage, or return "" when nothing else is left.
Leave a passage that does not state the changed fact out of your answer. A passage marked (new) was just written from the edited conversation and states the current fact: when two or more passages state the same changed fact, in any words, keep the one that says it best and return "" for each of the others (or rewrite one without that fact when it also says something else). A passage marked (held) was written or fixed by the person: still give the rewrite you would make (never ""); Cicada asks them before changing it. Never return "" for a Summary passage.
Never add a fact, name, number or link that neither the passage nor the change gives. Never write "currently", "now", "recently" or "soon".

`history`: for each change listed under WRITE A HISTORY SENTENCE, one sentence saying what changed, naming what it was before and what it is now (for example "The design review meeting moved from Friday to Thursday." or "The notes no longer say the project targets Linux only."). No date: Cicada adds it.

Respond with JSON only: {"passages": [{"n": 1, "text": "the passage as it should read, or empty"}], "history": [{"change": 1, "event": "one sentence"}]}"""


def prompt(job: Job) -> str:
    lines = [f"ENTITY: {job.name}", "", "CHANGES:"]
    for i, c in enumerate(job.changes, 1):
        lines.append(f"{i}. before: {c.before[:600]}")
        lines.append(f"   after: {c.after[:600] if c.after else '(removed)'}")
    lines += ["", "PASSAGES:"]
    for p in job.passages:
        mark = " (held)" if p.held else ""
        mark += " (new)" if p.role == "new" else ""
        title = section_provenance.TITLES[p.section]
        lines.append(f"{p.n}. [{title}]{mark} {' '.join(p.text.split())[:MAX_TEXT]}")
    relevant = [h for h in job.history if tokens(h) & set().union(*(c.gone | c.fresh for c in job.changes))]
    lines += ["", "HISTORY:", *([f"- {h}" for h in relevant] or ["(none about these changes)"])]
    # Which changes History does not record yet is Cicada's call (`_recorded`), not the writer's.
    needed = [str(i) for i, c in enumerate(job.changes, 1) if not _recorded(c, job.history)]
    lines += ["", f"WRITE A HISTORY SENTENCE FOR CHANGES: {', '.join(needed) if needed else '(none)'}"]
    return "\n".join(lines)


async def _call(job: Job, settings, text: str) -> dict | None:
    from api.services import conflict_resolver, engine_identity, json_parse
    from api.services.providers import resolve_llm_fn

    llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model,
                            completion=conflict_resolver._litellm().acompletion, stage="merge")
    response = await llm_fn(messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
                            response_format={"type": "json_object"})
    raw = response.choices[0].message.content or ""
    try:
        parsed = json_parse.parse_json_object(raw)
    except Exception:  # noqa: BLE001 - an answer that is not JSON changes nothing
        return None
    plan_ids = await engine_identity.aidentities(settings)
    if plan_ids and engine_identity.leaks(parsed, text, plan_ids):
        return None   # the plan account's identity, which the page never gave it (perf report 2026-10-24, item 1)
    return parsed if isinstance(parsed, dict) else None


# --------------------------------------------------------------------------- the rails


def _allowed(job: Job) -> set[str]:
    words = _raw(job.name) | _raw(" ".join(job.frontmatter.get("aliases") or []))
    for p in job.passages:
        words |= _raw(p.text)
    for c in job.changes:
        words |= _raw(c.after)
    return words


def _gives_nothing_new(text: str, allowed: set[str], links) -> bool:
    """No capitalised word or number, and no ``[[link]]``, that the passages and the change do not give. A link may be
    one a passage already has, or a name the words allow whose page exists (``links`` answers both)."""
    for word in _TOKEN.findall(text):
        if (word[:1].isupper() or any(ch.isdigit() for ch in word)) and word.casefold() not in allowed:
            return False
    return all(" ".join(m.split()).casefold() in links for m in _LINK.findall(text))


class _Links:
    """``name in links``: a ``[[link]]`` some passage already has, or one to an existing page whose words the
    passages or the change give (`id_utils.sanitize_id`, the id a page of that name has)."""

    def __init__(self, job: "Job", allowed: set[str]):
        self.known = {" ".join(m.split()).casefold() for p in job.passages for m in _LINK.findall(p.text)}
        self.allowed = allowed
        self.entities = job.path.parent if job.path is not None else None

    def __contains__(self, name: str) -> bool:
        if name in self.known:
            return True
        if self.entities is None or not _raw(name) <= self.allowed:
            return False
        from api.services.id_utils import sanitize_id

        return (self.entities / f"{sanitize_id(name)}.md").is_file()


def _refusal(p: Passage, text: str, allowed: set[str], links) -> str | None:
    """Why a rewrite is refused (an enum, never its words), or ``None``."""
    if not text:
        return "lead_emptied" if p.section == "summary" else None
    if "\n" in text or len(text) > max(2 * len(p.text) + 200, 400) or page_edits._structural(text):
        return "shape"
    if entity_article._RELATIVE.search(text) or entity_article._THE_USER.search(text):
        return "relative_time"
    if tokens(text) & p.gone:
        return "keeps_old_word"
    return None if _gives_nothing_new(text, allowed, links) else "new_name_or_link"


def _rewrite_ok(p: Passage, text: str, allowed: set[str], links) -> bool:
    return _refusal(p, text, allowed, links) is None


def _history_ok(event: str, change: Change, allowed: set[str], links: set[str]) -> bool:
    if not event or "\n" in event or len(event) > MAX_HISTORY or page_edits._structural(event):
        return False
    if entity_article._RELATIVE.search(event) or entity_article._THE_USER.search(event):
        return False
    return bool(tokens(event) & change.gone) and _gives_nothing_new(event, allowed | _raw(change.before), links)


#: A History line that calls the two values a conflict (the merge's reading before the source corrected itself) is no
#: record of the change; a removal is recorded only by a line that says the words went.
_CONFLICT = re.compile(r"\b(?:conflict\w*|contradict\w*|differ\w*|inconsistent)\b", re.I)
_GONE = re.compile(r"\b(?:no longer|removed|dropped|withdrawn|deleted|retracted|taken out)\b", re.I)


def _recorded(change: Change, history: list[str]) -> bool:
    for line in history:
        said = tokens(line)
        if not said & change.gone or _CONFLICT.search(line):
            continue
        if change.after and (said & change.fresh or not change.fresh):
            return True
        if not change.after and _GONE.search(line):
            return True
    return False


def _fallback_history(change: Change) -> str:
    before = " ".join(change.before.split())[:200]
    if change.after:
        return f"An edited conversation changed “{before}” to “{' '.join(change.after.split())[:200]}”."
    return f"An edited conversation no longer says “{before}”."


def decide(job: Job, answer: dict | None) -> tuple[dict[int, str], list[str], dict[int, str]]:
    """``({passage n: new text}, [history events], {held passage n: proposed text})`` the rails let through."""
    allowed = _allowed(job)
    links = _Links(job, allowed)
    by_n = {p.n: p for p in job.passages}
    edits: dict[int, str] = {}
    proposals: dict[int, str] = {}
    for row in (answer or {}).get("passages") or []:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            continue
        try:
            n = int(row.get("n"))
        except (TypeError, ValueError):
            continue
        p = by_n.get(n)
        text = " ".join(row["text"].split())
        if p is None or text == " ".join(p.text.split()):
            continue
        why = _refusal(p, text, allowed, links)
        if why is not None:
            job.refused[why] = job.refused.get(why, 0) + 1
            continue
        if p.held:
            if text:
                proposals[n] = text
        else:
            edits[n] = text
    # A rewrite that now says word for word what another passage of its section says is that passage's repeat.
    for n, text in list(edits.items()):
        p = by_n[n]
        if not text or p.section not in ("key_facts", "open_questions"):
            continue
        key = entity_body._normalize_fact(text)
        if any(o.n != n and o.section == p.section and entity_body._normalize_fact(edits.get(o.n, o.text)) == key
               for o in job.passages):
            edits[n] = ""
    # A fresh word the passages carried stays on the page: a removal that would take the last one is undone.
    for change in job.changes:
        for word in change.fresh:
            carried = [p for p in job.passages if not p.held and word in tokens(p.text)]
            if carried and not any(word in tokens(edits.get(p.n, p.text)) for p in carried):
                keep = next((p for p in carried if p.role == "new" and edits.get(p.n) == ""), None)
                if keep is not None:
                    edits.pop(keep.n)
    events: list[str] = []
    answered = {}
    for row in (answer or {}).get("history") or []:
        if isinstance(row, dict) and isinstance(row.get("event"), str):
            try:
                answered.setdefault(int(row.get("change")), " ".join(row["event"].split()))
            except (TypeError, ValueError):
                continue
    if edits or proposals:
        for i, change in enumerate(job.changes, 1):
            if _recorded(change, job.history):
                continue
            event = answered.get(i, "")
            events.append(event if _history_ok(event, change, allowed, links) else _fallback_history(change))
    return edits, events, proposals


# --------------------------------------------------------------------------- the write


def _apply(body: str, job: Job, edits: dict[int, str]) -> str:
    by_n = {p.n: p for p in job.passages}
    spans = []
    for n, text in edits.items():
        p = by_n[n]
        if len(p.ranges) != 1:
            continue
        start, end = p.ranges[0]
        if not text:
            # The whole item goes: a bullet's line (its mark included), a paragraph with the blank line after it.
            start = body.rfind("\n", 0, start) + 1
            nl = body.find("\n", end)
            end = len(body) if nl < 0 else nl + 1
            if p.section == "article" and body[end:end + 1] == "\n":
                end += 1
        spans.append((start, end, text))
    for start, end, text in sorted(spans, reverse=True):
        body = body[:start] + text + body[end:]
    return body


def _add_history(body: str, day: str, events: list[str]) -> str:
    """The dated lines merged into the page's History (`entity_body._merge_history_bullets`: deduped, by date), in
    place — every other section byte for byte; a page without one gets it before Links, Open Questions or Related."""
    if not events:
        return body
    prose, rest = page_edits.split_prose(body)
    entries = [{"date": day, "event": e} for e in events]
    marks = [h for h in page_edits.headings(prose) if h.level == 2]
    history = next((h for h in marks if h.title == "History"), None)
    if history is not None:
        merged = entity_body._merge_history_bullets(prose[history.content:history.end], entries)
        tail = prose[history.end:]
        prose = prose[:history.content] + merged + ("\n\n" if tail.strip() else "\n") + tail.lstrip("\n")
    else:
        block = "## History\n" + entity_body._merge_history_bullets("", entries) + "\n\n"
        after = next((h for h in marks if h.title in ("Links", "Open Questions", "Related")), None)
        if after is not None:
            prose = prose[:after.start] + block + prose[after.start:]
        else:
            prose = prose.rstrip() + "\n\n" + block
    return prose.rstrip() + "\n\n" + rest if rest else prose.rstrip() + "\n"


def reanchor_rows(frontmatter: dict, body: str, revisions: dict, gone: dict[str, set[str]]) -> int:
    """Every row into a revised conversation moved onto its new body (`episode_revision.provenance_row`), except on a
    passage that still says a word that revision took away. Returns how many rows moved."""
    def move(section: str, text: str, ev: Evidence):
        rev = revisions.get(ev.episode)
        if rev is None or tokens(text) & gone.get(ev.episode, set()):
            return None
        return episode_revision.provenance_row(rev, ev)
    return section_provenance.remap(frontmatter, body, move)


def _inputs(job: Job, edits: dict[int, str], revisions: dict) -> list[dict]:
    """A rewritten passage's rows: those into other conversations, and the revision it now follows."""
    by_n = {p.n: p for p in job.passages}
    out = []
    for n, text in edits.items():
        p = by_n[n]
        if not text or p.section not in ("summary", "key_facts", "article"):
            continue
        # The revisions whose words this passage said; its rows into other conversations (none says a gone word,
        # `page_job`) stay.
        eps = sorted({c.episode for c in job.changes if c.gone & p.gone or c.fresh & tokens(p.text)})
        rows = [ev for ev in p.rows if ev.episode not in eps]
        rows += [Evidence(episode=ep, start=-1, end=-1, kind="reasoning", hash=revisions[ep].hash) for ep in eps]
        out.append({"field": {"key_facts": "key_facts", "summary": "summary", "article": "article"}[p.section],
                    "text": text, "evidence": [ev.to_dict() for ev in rows]})
    return out


def _day(days: dict[str, str], job: Job, today: str) -> str:
    seen = sorted(days.get(c.episode) or today for c in job.changes)
    return seen[-1] if seen else today


def write(memory_path: Path, job: Job, edits: dict[int, str], events: list[str], revisions: dict,
          today: str) -> bool:
    """The page with its rewritten passages and History line, its pinned fixes applied again, its stamp carried and
    its provenance moved. Re-reads the page: one written since the job was built is left (``False``)."""
    current = markdown_parser.parse(job.path, ledger=False)
    if current.body != job.body:
        return False
    fm = dict(current.frontmatter)
    original = current.body
    body = _apply(original, job, edits)
    body = _add_history(body, _day(job.days, job, today), events)
    body, _ = page_edits.apply_corrections(fm, body)
    if body == original:
        return False
    entity_article.carry_stamp(fm, original, body)
    inputs = _inputs(job, edits, revisions)
    entity = {section_provenance.INPUTS: inputs}
    if any(r["field"] == "summary" for r in inputs):
        entity["summary"] = next(r["text"] for r in inputs if r["field"] == "summary")
    section_provenance.refresh(fm, original, body, entity)
    markdown_parser.write(job.path, fm, body)
    return True


def propose(memory_path: Path, job: Job, proposals: dict[int, str], events: list[str], today: str) -> bool:
    """One ``page_edit`` question for the page's held passages — never a second one while one waits."""
    inbox = memory_path / "inbox"
    if inbox.is_dir():
        for item in inbox.glob("inbox-*.md"):
            try:
                fm = markdown_parser.parse(item, ledger=False).frontmatter
            except Exception:  # noqa: BLE001 - an unreadable item is no pending proposal
                continue
            if (fm.get("kind") == page_edits.KIND and fm.get("origin") == ORIGIN and fm.get("status") == "pending"
                    and fm.get("entity_id") == job.entity_id):
                return False
    by_n = {p.n: p for p in job.passages}
    rows = [{"old": by_n[n].text, "new": text} for n, text in proposals.items()]
    try:
        request = page_edits.parse_request(rows)
        page_edits.plan(job.frontmatter, job.body, request, author=AUTHOR)   # it can apply as it stands
    except page_edits.EditError:
        return False
    gone = set().union(*(by_n[n].gone for n in proposals))
    change = next((c for c in job.changes if c.gone & gone), None)
    said = next((e for e in events if tokens(e) & gone), None) or (
        _fallback_history(change) if change is not None else "A conversation this page was written from was edited")
    reason = (f"{said.rstrip('.')}. The words on the page that still say what it said before were written or fixed "
              "by hand, so they change only if you say so.")
    page_edits.write_proposal(memory_path, entity_id=job.entity_id, name=job.name, request=request, reason=reason,
                              author=AUTHOR, session=None, day=today, origin=ORIGIN)
    return True


# --------------------------------------------------------------------------- the step


def revised_days(episodes: list[dict]) -> dict[str, str]:
    """The local day each waiting episode was edited in place (the stager's ``revised.at``)."""
    out = {}
    for ep in episodes:
        record = ep.get(episode_revision.REVISED_KEY)
        at = record.get("at") if isinstance(record, dict) else None
        if not at:
            continue
        try:
            out[str(ep["id"])] = datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone().date().isoformat()
        except ValueError:
            continue
    return out


def _pages_citing(memory_path: Path, revisions: dict) -> list[Path]:
    keys = [f"{ep} " for ep in revisions]
    out = []
    for path in sorted((memory_path / "entities").glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(k in text for k in keys):
            out.append(path)
    return out


async def run(memory_path: Path, settings, revisions: dict, *, closed: dict[str, list[str]] | None = None,
              days: dict[str, str] | None = None, today: str | None = None) -> Report:
    """Stage 5.58: the pages a revision touched get their prose corrected. Never raises."""
    report = Report()
    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    closed = closed or {}
    days = days or {}
    try:
        changes = {ep: chs for ep, rev in revisions.items() if (chs := changes_of(rev))}
        gone = {ep: set().union(*(c.gone for c in chs)) for ep, chs in changes.items()}
        pages = await asyncio.to_thread(_pages_citing, memory_path, revisions)
        jobs: list[Job] = []
        for path in pages:
            entity_id = path.stem
            on = {ep for ep in closed.get(entity_id, []) if ep in changes}
            if changes:
                try:
                    job = await asyncio.to_thread(page_job, memory_path, entity_id, path, revisions, changes, on, days)
                except Exception as exc:  # noqa: BLE001 - one unreadable page never costs the others
                    logger.warning(f"Revision prose: a page could not be read ({type(exc).__name__})")
                    job = None
                if job is not None:
                    jobs.append(job)
        report.left = max(0, len(jobs) - MAX_PAGES)
        jobs = jobs[:MAX_PAGES]
        sem = asyncio.Semaphore(max(1, int(getattr(settings, "agent_max_concurrency", 3) or 1)))

        async def one(job: Job):
            async with sem:
                try:
                    return await _call(job, settings, prompt(job))
                except Exception as exc:  # noqa: BLE001 - a failed call leaves the page as it was
                    logger.warning(f"Revision prose: a page's call failed ({type(exc).__name__}); left as it was")
                    report.failed += 1
                    return None

        answers = await asyncio.gather(*(one(j) for j in jobs))
        report.calls = len(jobs)
        written: set[Path] = set()
        for job, answer in zip(jobs, answers):
            edits, events, proposals = decide(job, answer)
            for why, n in job.refused.items():
                report.refused += n
                report.refused_why[why] = report.refused_why.get(why, 0) + n
            if edits or events:
                if await asyncio.to_thread(write, memory_path, job, edits, events, revisions, today):
                    report.pages += 1
                    report.rewritten += sum(1 for t in edits.values() if t)
                    report.removed += sum(1 for t in edits.values() if not t)
                    report.history += len(events)
                    written.add(job.path)
            if proposals and await asyncio.to_thread(propose, memory_path, job, proposals, events, today):
                report.proposals += 1
        # Every page citing a revised conversation: its provenance rows onto the new body.
        for path in pages:
            def move(path=path):
                parsed = markdown_parser.parse(path, ledger=False)
                fm = dict(parsed.frontmatter)
                n = reanchor_rows(fm, parsed.body, revisions, gone)
                if n:
                    markdown_parser.write(path, fm, parsed.body)
                return n
            try:
                n = await asyncio.to_thread(move)
            except Exception as exc:  # noqa: BLE001 - a derived row never costs the cycle
                logger.warning(f"Revision prose: provenance rows not moved on a page ({type(exc).__name__})")
                continue
            if n:
                report.rows_moved += n
                written.add(path)
        report.paths = sorted(f"entities/{p.name}" for p in written)
    except Exception as exc:  # noqa: BLE001 - never into the cycle
        logger.warning(f"Revision prose skipped: {type(exc).__name__}")
    return report


def summary(report: Report) -> str:
    return (f"{report.calls} call(s); {report.pages} page(s) corrected — {report.rewritten} passage(s) rewritten, "
            f"{report.removed} removed, {report.history} History line(s); {report.proposals} question(s) for "
            f"passages the person or an agent wrote; {report.rows_moved} provenance row(s) moved; "
            f"{report.refused} answer(s) refused by the rails {dict(sorted(report.refused_why.items()))}, "
            f"{report.failed} call(s) failed, {report.left} page(s) over the cap left")

