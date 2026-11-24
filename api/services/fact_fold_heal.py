"""A one-time heal for pages that already repeat a fact (G148, owner 2026-11-23): plan with a judge, apply with none.

The live fold (`fact_fold`) acts only when a write brings a new fact to a page, so a page written before it keeps its
repeats until Sleep happens to write it again — and then one big ask under-proposes: a small judge shown twelve new lines
at once names a few pairs and lets the rest by (a reported page: 16 bullets, 7 pairs proposed in one ask, 3 folded). Read
one conversation at a time the same facts end at 5 to 6. So the heal does not ask once; it REPLAYS the page.

**Plan** (:func:`plan_page`, writes nothing): the page's Key Facts arrive in page order, the oldest first, as
`CHUNK` new lines against the bullets that survived so far — the shape the incremental path asks in — through the live
module's own ask, guard (`fact_fold.covers`), second reader and link rule (`orient`). A line that resembles no survivor
(`MIN_OVERLAP`: a shared name or number, or three shared words) costs no call; a page with no such line costs none. A
second sweep (`PASSES`) asks again about what the first left, because the judge and the second reader vary run to run, and
the first sweep that folds nothing ends it. Every
fold records the line kept, the line dropped, the path it took and the conversations whose source rows move.
Before any model call :func:`census` says how many pages would be asked and the most calls they could cost.

**Apply** (:func:`apply`, no model call) writes exactly the folds of a reviewed plan file: a page whose Key Facts changed
since the plan is skipped and reported, never re-judged; a fold struck from the file is not made.

Loss-free by construction (the brief's rail, ruling 23): a line is KEPT as a holder only when G118's rows prove Sleep
wrote it (a holder with no rows could not receive the sources). A line with no rows — written before the rows existed —
may be DROPPED into a sourced line that says it in full, and never holds one (owner 2026-11-24: *"yeah go ahead"* to
removing an old line with no source record when a sourced line says the same thing in full, on pages nobody edited;
until then it was never dropped either). Such a fold says so in the plan (`unsourced`). A
pinned correction is never dropped; a page a person edited is never touched; every fold passes the SAME guard as a write
on the page's whole neighbourhood, and a line already holding others moves them on only when the new holder covers them
all (`_admit`). The claims fence, History, Open Questions, the article and the frontmatter other than the provenance rows
a fold must move are byte for byte as they were: only the dropped bullets' lines leave the Key Facts section.
Equal and word-for-word-extending bullets fold by the same rule a write applies (`fact_policy.restates`/`extends`),
never a paraphrase by code.

Pure apart from the injected judge, the bank read and :func:`apply`'s writes (admission, `page_lock`, one `cicada`
commit of only its own paths).
"""
from __future__ import annotations

import contextlib
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (
    claims, entity_body, fact_fold, fact_policy, git_service, link_names, markdown_parser, page_lock,
    section_provenance, write_admission,
)

TRIGGER = "maintenance/fact-fold-heal"
#: New lines per ask. 1 is the incremental path's shape; measured against 3 and 12 in `docs/architecture/capture-and-sleep.md`.
CHUNK = 3
#: A bullet is asked about only when it shares this much with a surviving one (`fact_fold._overlap`: 3 a name or a number,
#: 1 a content word), names read as the page's neighbours' (`fact_fold.People`). Measured on the invented pairs: every pair
#: a person would fold scores 5 or more but one — a translated line sharing no name, number or word with its holder (1),
#: which the live path finds only by showing the judge the newest bullets: left here, a miss and never a loss.
MIN_OVERLAP = 3
#: Pages with more bullets are listed and left (the pairwise resemblance is quadratic).
MAX_BULLETS = 300
#: Sweeps over a page: a second one asks again about what a first left (the judge and the second reader vary run to run),
#: and ends the first one that folds nothing.
PASSES = 2
#: Calls one page may cost (an ask and a check per chunk), and the default for a run.
MAX_CALLS_PAGE = 40
VERSION = 1


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: write nothing."""


class EngineDown(RuntimeError):
    """The engine failed several calls in a row (a plan limit, a lost sign-in): stop, the run resumes."""


# --------------------------------------------------------------------------- reading a page


def _norm(text: str) -> str:
    return fact_policy.normalized(text)


def _groups(lines: list[str]) -> list[tuple[int, int]] | None:
    """The line ranges of a Key Facts section's items, as `entity_body._bullet_lines` groups them; ``None`` when a line
    is neither a bullet nor an item's continuation (free prose a legacy writer left: rebuilding the list would lose it)."""
    groups: list[list[int]] = []
    indent = 0
    for at, raw in enumerate(lines):
        stripped = raw.strip()
        depth = len(raw) - len(raw.lstrip())
        if groups and depth > indent:
            groups[-1][1] = at + 1
        elif stripped.startswith(("- ", "* ")):
            indent = depth
            groups.append([at, at + 1])
        elif groups and not stripped:
            groups[-1][1] = at + 1
        elif stripped:
            return None
    return [(a, b) for a, b in groups]


def _fences(body: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in claims._CLAIMS_BLOCK_RE.finditer(body or "")]


def _key_facts_span(body: str) -> tuple[int, int] | None:
    """``(start, end)`` of the Key Facts section's content in ``body``: after its heading line, up to the next heading or
    the claims fence. ``None`` unless the page has exactly one such heading."""
    fences = _fences(body)

    def outside(at: int) -> bool:
        return not any(a <= at < b for a, b in fences)

    heads = [m for m in entity_body._H2.finditer(body) if outside(m.start())]
    mine = [m for m in heads if m.group(1).strip() == "Key Facts"]
    if len(mine) != 1:
        return None
    head = mine[0]
    start = head.end()
    if body[start:start + 2] == "\r\n":
        start += 2
    elif body[start:start + 1] == "\n":
        start += 1
    ends = [m.start() for m in heads if m.start() > head.start()] + [a for a, _ in fences if a > head.start()]
    return start, min(ends) if ends else len(body)


@dataclass
class Read:
    """One page as the heal sees it: its Key Facts, which of them G118 proves Sleep wrote, and why it may be skipped."""
    id: str
    name: str = ""
    skip: str | None = None
    bullets: list[str] = field(default_factory=list)
    rowed: list[bool] = field(default_factory=list)
    sources: list[frozenset] = field(default_factory=list)     # per bullet: the conversations its rows name
    pinned: frozenset[str] = frozenset()
    own: list[str] = field(default_factory=list)
    kf_hash: str = ""

    @property
    def foldable(self) -> list[int]:
        return [i for i, ok in enumerate(self.rowed) if ok]


def read_page(page_id: str, fm: dict, body: str, *, max_bullets: int = MAX_BULLETS) -> Read:
    fm = fm or {}
    out = Read(page_id, str(fm.get("name") or page_id))
    if str(fm.get("status") or "active") in ("archived", "dropped"):
        out.skip = "archived"
        return out
    sections = entity_body.parse_sections(claims.strip_claims_block(body))
    if entity_body.has_human_prose(fm, sections):
        out.skip = "human_page"
        return out
    kf = sections.get("Key Facts", "")
    bullets = entity_body._bullet_lines(kf)
    out.bullets = bullets
    if len(bullets) < 2:
        out.skip = "few_facts"
        return out
    if len(bullets) > max_bullets:
        out.skip = "too_many_facts"
        return out
    if _item_groups(body, bullets) is None:
        out.skip = "format"
        return out
    raw = fm.get(section_provenance.FIELD)
    decoded = section_provenance.decode(raw)
    if raw is not None and decoded is None:
        out.skip = "provenance_unreadable"
        return out
    if "key_facts" in section_provenance.unavailable_sections(body, decoded or {}):
        out.skip = "provenance_unreadable"
        return out
    matched = section_provenance.matched(fm, body).get("key_facts", {})
    items = {entity_body._normalize_fact(i.text): i for i in section_provenance.scan(body).get("key_facts", [])
             if not i.ambiguous and i.key in matched}
    for bullet in bullets:
        item = items.get(entity_body._normalize_fact(bullet))
        out.rowed.append(item is not None)
        out.sources.append(frozenset(ev.episode for ev in matched[item.key][1]) if item is not None else frozenset())
    out.pinned = frozenset(_norm(str(r.get("new") or "")) for r in (fm.get("corrections") or []) if isinstance(r, dict))
    out.own = [str(a) for a in fm.get("aliases") or []]
    out.kf_hash = hashlib.sha256(kf.encode("utf-8")).hexdigest()[:16]
    return out


def _item_groups(body: str, bullets: list[str]) -> list[tuple[int, int]] | None:
    """The Key Facts section's item line ranges, when they are exactly ``bullets`` (one section, nothing but items)."""
    span = _key_facts_span(body)
    if span is None:
        return None
    lines = body[span[0]:span[1]].splitlines(keepends=True)
    groups = _groups(lines)
    if groups is None or len(groups) != len(bullets):
        return None
    if any(entity_body._bullet_lines("".join(lines[a:b])) != [bullet] for (a, b), bullet in zip(groups, bullets)):
        return None
    return groups


# --------------------------------------------------------------------------- the page's neighbourhood


def context(read: Read, names: "link_names.Names | None", owner: str | None) -> fact_fold.Ask:
    """The page's whole neighbourhood as an ask with no lines: who a name means (`fact_fold.People`, from every bullet) and
    the words and other names the guard allows. Plan and apply judge a fold against this one object."""
    people = fact_fold.neighbourhood(read.id, names, read.bullets, owner)
    also: dict[str, list[str]] = {}
    if names is not None:
        for text in read.bullets:
            for m in fact_fold._LINK.finditer(text):
                page = names.resolve(m.group(1))
                if page and names.names[page] not in also and names.aliases.get(page):
                    also[names.names[page]] = names.aliases[page][:6]
    if people is not None:
        for pid in people.mentioned(read.bullets):
            others = [f for f in people.spellings[pid] if fact_fold._key(f) != fact_fold._key(people.names[pid])]
            if others:
                also[people.names[pid]] = others[:10]
    allowed = fact_fold._held_words([read.name, *read.own, *([owner] if owner else [])])
    return fact_fold.Ask(read.id, read.name, [], also, allowed, True, people)


def _admit(ctx: fact_fold.Ask, holder: str, drop: str) -> bool:
    """The live path's guard and link rule, on the page's whole neighbourhood."""
    return (fact_fold.covers(holder, drop, allowed=fact_fold._allowed(ctx, holder), people=ctx.people)
            and fact_fold._loses_no_link(drop, holder, ctx))


def _resembles(text: str, others, canon: Callable[[str], str] = lambda t: t) -> bool:
    """``text`` shares enough with one of ``others`` to be asked about; names the page's neighbourhood gives two spellings
    ("Pip", "<owner>'s girlfriend") are compared as the one page's name (`fact_fold.People.canon`)."""
    mine = canon(text)
    return any(fact_fold._overlap(mine, canon(o)) >= MIN_OVERLAP for o in others)


# --------------------------------------------------------------------------- the plan


@dataclass
class Fold:
    drop: str
    into: str
    how: str                        # rule-equal | rule-extends | judged
    guard: str | None = None        # plain | neighbourhood (judged)
    flipped: bool = False
    ask: int = 0                    # which ask of the page's replay
    second_reader: bool = False
    chain: list[str] = field(default_factory=list)   # lines it passed through before the one kept
    sources: list[str] = field(default_factory=list)
    unsourced: bool = False         # the dropped line had no source rows (written before they existed)

    def row(self, page: str, n: int) -> dict:
        return {"id": f"{page}#{n}", "drop": self.drop, "into": self.into, "how": self.how, "guard": self.guard,
                "flipped": self.flipped, "ask": self.ask, "second_reader": "agreed" if self.second_reader else None,
                "chain": self.chain, "sources_move": self.sources, "unsourced": self.unsourced, "strike": False}


class _Replay:
    """One page's survivors, the lines each holds, and every fold made so far."""

    def __init__(self, read: Read, ctx: fact_fold.Ask) -> None:
        self.read, self.ctx = read, ctx
        self.alive: dict[str, None] = {}                 # surviving text, in order
        self.holds: dict[str, list[str]] = {}            # survivor -> every line dropped into it
        self.folds: dict[str, Fold] = {}                 # dropped text -> fold
        self.refused: list[dict] = []
        self._canon: dict[str, str] = {}
        self.src = {read.bullets[i]: read.sources[i] for i in read.foldable}

    def pinned(self, text: str) -> bool:
        return _norm(text) in self.read.pinned

    def sourced(self, text: str) -> bool:
        """G118's rows prove Sleep wrote this line: only such a line may hold another."""
        return text in self.src

    def canon(self, text: str) -> str:
        people = self.ctx.people
        if not people:
            return text
        if text not in self._canon:
            self._canon[text] = people.canon(text)[0]
        return self._canon[text]

    def take(self, drop: str, holder: str, how: str, **info) -> bool:
        """Drop ``drop`` into ``holder`` when nothing is lost: not pinned, both still alive, and the holder covers the line
        and everything the line already holds."""
        if drop == holder or drop not in self.alive or holder not in self.alive or self.pinned(drop):
            return False
        if not self.sourced(holder):
            self.refused.append({"drop": drop, "by": holder, "stage": "the kept line has no source record"})
            return False
        carried = [drop, *self.holds.get(drop, [])]
        bad = next((x for x in carried if not _admit(self.ctx, holder, x)), None)
        if bad is not None:
            self.refused.append({"drop": drop, "by": holder, "stage": "page guard" if bad == drop else "carried line"})
            return False
        del self.alive[drop]
        self.holds.setdefault(holder, []).extend(carried)
        self.holds.pop(drop, None)
        for fold in self.folds.values():
            if fold.into == drop:
                fold.into = holder
                fold.chain.append(drop)
        self.folds[drop] = Fold(drop, holder, how, sources=sorted(self.src.get(drop, ())),
                                unsourced=not self.sourced(drop), **info)
        return True

    def add(self, text: str) -> None:
        self.alive.setdefault(text, None)


def _rule_step(replay: _Replay) -> None:
    """Equal and word-for-word-extending bullets, by the rule every write applies — in page order, the earlier bullet
    holding, unless it is the one that may not go (pinned) or the earlier one cannot hold (no source rows)."""
    for text in replay.read.bullets:
        replay.add(text)
        for held in list(replay.alive):
            if text not in replay.alive:
                break
            if held == text or held not in replay.alive:
                continue
            if fact_policy.restates(text, held):
                replay.take(text, held, "rule-equal") or replay.take(held, text, "rule-equal")
            elif fact_policy.extends(held, text):
                replay.take(text, held, "rule-extends")
            elif fact_policy.extends(text, held):
                replay.take(held, text, "rule-extends")


@dataclass
class Meter:
    """Calls made, by kind; ``failed`` counts consecutive engine failures (three stop the run)."""
    ask: int = 0
    check: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.ask + self.check


def census(read: Read, *, chunk: int = CHUNK, page_cap: int = MAX_CALLS_PAGE, passes: int = PASSES,
           names: "link_names.Names | None" = None, owner: str | None = None) -> dict:
    """What a page would cost, with no model: bullets a rule folds, bullets that resemble an earlier one (the only ones
    that can be asked about) and the most calls that is (an ask and a check per chunk, capped per page)."""
    if read.skip or not read.foldable:
        return {"candidates": 0, "max_calls": 0}
    replay = _Replay(read, context(read, names, owner))
    _rule_step(replay)
    survivors = list(replay.alive)
    candidates = sum(1 for at, t in enumerate(survivors) if at and _resembles(t, survivors[:at], replay.canon))
    return {"candidates": candidates, "rule_folds": len(replay.folds),
            "max_calls": min(page_cap, passes * 2 * math.ceil(candidates / chunk))}


def plan_page(read: Read, names: "link_names.Names | None", owner: str | None, judge: Callable[[str], dict], meter: Meter,
              *, chunk: int = CHUNK, max_calls: int = MAX_CALLS_PAGE, run_calls_left: int | None = None,
              passes: int = PASSES) -> dict:
    """One page's folds, by replaying its Key Facts (see the module). The row :func:`apply` reads."""
    ctx = context(read, names, owner)
    replay = _Replay(read, ctx)
    _rule_step(replay)
    start = meter.total
    status = "done"
    pending: list[str] = []
    asks = 0

    def budget() -> bool:
        used = meter.total - start
        return used + 2 <= max_calls and (run_calls_left is None or used + 2 <= run_calls_left)

    def flush() -> bool:
        nonlocal asks
        if not pending:
            return True
        if not budget():
            return False
        ask = fact_fold.build(read.id, read.name, list(replay.alive), pending, heal=True, pinned=read.pinned,
                              names=names, own=[*read.own, *([owner] if owner else [])], owner=owner)
        batch = list(pending)
        pending.clear()
        if ask is None:
            for text in batch:
                replay.add(text)
            return True
        asks += 1
        try:
            meter.ask += 1
            reply = judge(fact_fold.prompt(ask))
            proposed = fact_fold.proposals(reply, ask)
            oriented = _holders(fact_fold.orient(_holders(proposed, ask, replay), ask), ask, replay)
            if oriented:
                meter.check += 1
            confirmed = fact_fold.checks(oriented, ask, judge)
            decided = fact_fold.folds(confirmed, ask)
            meter.failed = 0
        except Exception as exc:  # noqa: BLE001 - a failed call decides nothing; three in a row stop the run
            meter.failed += 1
            logger.info(f"fact fold heal: a call failed ({type(exc).__name__})")
            if meter.failed >= 3:
                raise EngineDown(type(exc).__name__) from exc
            for text in batch:
                replay.add(text)
            return True
        _note_refusals(replay, reply, ask, proposed, oriented, confirmed, decided)
        for text in batch:
            replay.add(text)
        agreed = {d.text for d, _ in confirmed}
        for drop, holder in decided.items():
            replay.take(drop, holder, "judged", guard=ask.paths.get(drop, "plain"),
                        flipped=ask.paths.get(drop) == "flipped", ask=asks, second_reader=drop in agreed)
        return True

    for sweep in range(passes):
        order = list(replay.alive)
        first = order[:1]
        replay.alive = dict.fromkeys([*first, *[t for t in order if replay.pinned(t) and t not in first]])
        rest = [t for t in order[1:] if not replay.pinned(t)]
        before = len(replay.folds)
        reached = 0
        for reached, text in enumerate(rest, 1):
            if _resembles(text, [*replay.alive, *pending], replay.canon):
                pending.append(text)
                if len(pending) >= chunk and not flush():
                    status = "capped"
                    break
            else:
                replay.add(text)
        if status == "done" and not flush():
            status = "capped"
        if status == "capped":
            for text in [*pending, *rest[reached:]]:   # what was not reached keeps its place
                replay.add(text)
            pending.clear()
            break
        if len(replay.folds) == before:   # a sweep that folds nothing ends it
            break
    folds = [f.row(read.id, n) for n, f in enumerate(replay.folds.values(), 1)]
    survivors = set(replay.alive)
    assert all(f["into"] in survivors and f["drop"] not in survivors for f in folds)
    return {"v": VERSION, "page": read.id, "name": read.name, "kf_hash": read.kf_hash, "before": len(read.bullets),
            "after": len(read.bullets) - len(folds), "status": status,
            "calls": {"ask": asks, "total": meter.total - start},
            "rowless_kept": sum(1 for b, ok in zip(read.bullets, read.rowed) if not ok and b in survivors),
            "unsourced_dropped": sum(1 for f in folds if f["unsourced"]), "folds": folds,
            "refused": replay.refused[:50], "strike": False}


def _holders(pairs, ask: fact_fold.Ask, replay: "_Replay"):
    """Each ``(drop, keep)`` pair whose kept line has no source rows is turned round when the other line can hold it (it
    has rows, the kept one may go, and the guard and the link rule pass THAT way — the second reader is then asked about
    that direction), and left out when it cannot."""
    out = []
    for drop, keep in pairs:
        if replay.sourced(keep.text):
            out.append((drop, keep))
        elif (replay.sourced(drop.text) and fact_fold._droppable(keep, ask) and not replay.pinned(keep.text)
              and fact_fold._admits(drop, keep, ask)):
            ask.paths[keep.text] = "flipped"
            out.append((keep, drop))
    seen: set[int] = set()
    return [pair for pair in out if not (pair[0].n in seen or seen.add(pair[0].n))]


def _note_refusals(replay, reply, ask, proposed, oriented, confirmed, decided) -> None:
    """What the judge named and a later stage turned down, with the stage — so the person sees what was left alone."""
    by_n = {line.n: line for line in ask.lines}
    raw = reply.get("answers") if isinstance(reply, dict) else None
    passed = {d.text: k.text for d, k in proposed}
    oriented_ = {d.text for d, _ in oriented}
    confirmed_ = {d.text for d, _ in confirmed}
    for answer in raw if isinstance(raw, list) else []:
        try:
            drop, keep = by_n.get(int(answer.get("line"))), by_n.get(int(answer.get("in_full_by")))
        except (AttributeError, TypeError, ValueError):
            continue
        if drop is None or keep is None or drop is keep:
            continue
        if drop.text not in passed:
            stage = "code guard"
        elif drop.text not in oriented_ and keep.text not in oriented_:
            stage = "link rule" if replay.sourced(keep.text) else "the kept line has no source record"
        elif drop.text not in confirmed_ and keep.text not in confirmed_:
            stage = "second reader"
        else:
            continue
        replay.refused.append({"drop": drop.text, "by": keep.text, "stage": stage})


# --------------------------------------------------------------------------- the plan file


def row_folds(row: dict, skip_folds=()) -> list[dict]:
    """The folds of a plan row that stand: not struck on the row, the page or by id."""
    if row.get("strike"):
        return []
    skip = set(skip_folds)
    return [f for f in row.get("folds") or [] if not f.get("strike") and f.get("id") not in skip]


# --------------------------------------------------------------------------- apply


@dataclass
class Result:
    pages: int = 0
    folds: int = 0
    written: int = 0
    committed: bool = False
    skipped: dict[str, int] = field(default_factory=dict)
    fold_skipped: dict[str, int] = field(default_factory=dict)
    bullets_before: int = 0
    bullets_after: int = 0

    def skip(self, why: str, n: int = 1) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + n

    def counts(self) -> dict:
        return {"pages_in_plan": self.pages, "folds_in_plan": self.folds, "pages_written": self.written,
                "folds_written": self.bullets_before - self.bullets_after, "committed": self.committed,
                "pages_skipped": dict(sorted(self.skipped.items())),
                "folds_skipped": dict(sorted(self.fold_skipped.items()))}


def _splice(body: str, keep: set[int]) -> str | None:
    """``body`` with each Key Facts item whose index is not in ``keep`` removed (its lines, and the blank lines after it
    unless it is the section's last), every other byte as it was; ``None`` when the section cannot be read as items."""
    span = _key_facts_span(body)
    if span is None:
        return None
    lines = body[span[0]:span[1]].splitlines(keepends=True)
    groups = _groups(lines)
    if groups is None:
        return None
    out: list[str] = []
    cursor = 0
    for at, (a, b) in enumerate(groups):
        out += lines[cursor:a]
        cursor = b
        if at in keep:
            out += lines[a:b]
        elif at == len(groups) - 1:
            out += [line for line in lines[a:b] if not line.strip()]
    out += lines[cursor:]
    return body[:span[0]] + "".join(out) + body[span[1]:]


def apply(memory_path, rows: list[dict], *, sleep_running: Callable[[], bool], names: "link_names.Names | None" = None,
          owner: str | None = None, skip_pages=(), skip_folds=(), check: bool = False) -> Result:
    """Write the folds of a reviewed plan and commit them in ONE commit authored ``cicada``. No model call. Raises
    :class:`SleepRunning` before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    result = Result()
    skip_pages = set(skip_pages)
    written: list[str] = []
    # ``check`` reads and writes nothing, so it asks nobody whether Sleep runs and holds no lock.
    admission = (contextlib.nullcontext() if check else
                 write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")))
    with admission:
        if not check and sleep_running():
            raise SleepRunning("a Sleep run is in progress; apply after it ends")
        with (contextlib.nullcontext() if check else page_lock.page_lock(memory_path)):
            dirty: frozenset[str] = frozenset()
            if (memory_path / ".git").exists():
                try:
                    dirty = git_service.dirty_paths_sync(memory_path, "entities")
                except git_service.GitError:
                    result.skip("git_unreadable", len(rows))
                    return result
            for row in rows:
                folds = row_folds(row, skip_folds)
                page_id = str(row.get("page") or "")
                result.pages += 1
                result.folds += len(folds)
                if row.get("strike") or page_id in skip_pages:
                    result.skip("struck")
                    continue
                if not folds:
                    result.skip("no_folds" if not row.get("folds") else "struck")
                    continue
                path = memory_path / "entities" / f"{page_id}.md"
                rel = f"entities/{page_id}.md"
                if not re.fullmatch(r"[A-Za-z0-9][\w.-]*", page_id) or not path.is_file():
                    result.skip("page_missing")
                    continue
                if rel in dirty:
                    result.skip("dirty_in_git")
                    continue
                outcome = _apply_page(path, page_id, row, folds, names, owner, result, check)
                if outcome is None:
                    continue
                written.append(rel)
            if written and not check and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Repeated facts folded: {result.bullets_before - result.bullets_after} fact(s) on {len(written)} page(s)",
                    [f"{rel}: folded repeated Key Facts (trigger: {TRIGGER})" for rel in written],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, written)
                result.committed = True
    result.written = len(written)
    if written and not check:
        logger.info(f"fact-fold heal: {len(written)} page(s)")
    return result


def _apply_page(path: Path, page_id: str, row: dict, folds: list[dict], names, owner, result: Result,
                check: bool = False) -> bool | None:
    try:
        parsed = markdown_parser.parse(path)
    except Exception:  # noqa: BLE001 - an unreadable page is skipped
        result.skip("unreadable")
        return None
    fm, body = dict(parsed.frontmatter or {}), parsed.body
    read = read_page(page_id, fm, body, max_bullets=10 ** 6)
    if read.skip:
        result.skip(f"now_{read.skip}")
        return None
    if read.kf_hash != row.get("kf_hash"):
        result.skip("key_facts_changed")
        return None
    ctx = context(read, names, owner)
    index = {b: i for i, b in enumerate(read.bullets)}
    judged: dict[str, str] = {}
    for fold in folds:
        drop, into = str(fold.get("drop")), str(fold.get("into"))
        why = None
        if drop not in index or into not in index or drop == into:
            why = "not_on_page"
        elif not read.rowed[index[into]]:
            why = "no_source_rows"
        elif _norm(drop) in read.pinned:
            why = "pinned"
        elif not _admit(ctx, into, drop):
            why = "guard"
        if why is not None:
            result.fold_skipped[why] = result.fold_skipped.get(why, 0) + 1
            continue
        judged[drop] = into
    # A holder that is itself dropped is followed to the line kept (the plan names the final one; a file edited by hand
    # may not), and a loop folds nothing.
    final: dict[str, str] = {}
    for drop, into in judged.items():
        hops = 0
        while into in judged and hops <= len(judged):
            into, hops = judged[into], hops + 1
        if into in judged or into == drop or not read.rowed[index[into]] or not _admit(ctx, into, drop):
            result.fold_skipped["chain"] = result.fold_skipped.get("chain", 0) + 1
            continue
        final[drop] = into
    if not final:
        result.skip("nothing_left")
        return None
    keep = set(range(len(read.bullets))) - {index[d] for d in final}
    new_body = _splice(body, keep)
    if new_body is None:
        result.skip("format")
        return None
    left = entity_body._bullet_lines(entity_body.parse_sections(claims.strip_claims_block(new_body)).get("Key Facts", ""))
    if left != [b for i, b in enumerate(read.bullets) if i in keep]:
        result.skip("format")
        return None
    # The provenance rows are keyed by the text the scan reads; the plan by the bullet's own text (the same, checked).
    scanned = {entity_body._normalize_fact(i.text): i.text for i in section_provenance.scan(body).get("key_facts", [])}
    moves = {scanned.get(entity_body._normalize_fact(d), d): scanned.get(entity_body._normalize_fact(h), h)
             for d, h in final.items()}
    if not check:
        section_provenance.refresh(fm, body, new_body, {section_provenance.FOLDS: moves})
        markdown_parser.write(path, fm, new_body)
    result.bullets_before += len(read.bullets)
    result.bullets_after += len(read.bullets) - len(final)
    return True
