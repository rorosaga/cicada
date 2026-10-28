"""The catch-up chat: the person hops into a short conversation and their agent asks what matters most first (vision
item 10, S2, S7 and S10).

The owner (2026-10-28): "a nice quick, hop on a chat with cicada to catch him up to speed … just have the user answer
at first those things linked to more accessed entities", asked "in more human concrete format", and "these things
at consolidation should be detected".

Three parts, one module:

* **The read** (:func:`select`, served as ``cicada_check_nudges(mode="catchup")``): every question the person can
  answer in conversation, most-used page first (``page_use.rank``: Sleep's priority moved by how much the person's
  life uses the page), a handful at a time (:data:`LIMIT`), each in its human words with its reason
  (``inbox_wording``). Frontmatter only until the top few are picked, so a 400-question inbox costs one cached
  directory read, not 400 cause lookups.
* **The cursor** (:class:`Cursor`): what one session's catch-up already served is not served again — "more" moves on,
  a resumed conversation does not start over. Outside every bank (``$CICADA_HOME/inbox_catchup``), ids and times only,
  forgotten after :data:`CURSOR_HOURS`.
* **One person under several names** (:func:`groups`, :func:`propose_nicknames`): Sleep's pairwise "Is A the same as
  B?" questions about people that chain together (A~B, B~C) are asked once, as "Are A, B and C the same person?"; and
  a drain proposes the pair spelling alone suggests (one name begins the other: a nickname and its long form) that no
  question holds yet. A question only — ruling 41 and G209 hold: no name is ever joined to another without the
  person's own words (Sleep reads their answer from the captured conversation, ruling 29 part 1), and a pair the
  person said is two people (``merge_rejections``) is never proposed again. Spelling, like saying two names together,
  is a reason to ask, never proof.

**The volume rail (S10).** :class:`Budget` is one drain's allowance of NEW questions across the proposers that feed
the catch-up (``still_questions``, :func:`propose_nicknames`): :data:`NEW_PER_DRAIN` in all, each proposer also under
its own open-count ceiling, so a ~400-question inbox never grows by more than a few a night, and only while those
few are unanswered.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, inbox_wording, markdown_parser, page_use

LIMIT = 3
CURSOR_HOURS = 12
NEW_PER_DRAIN = 3
NICKNAME_MAX_OPEN = 3
NICKNAME_TRIGGER = "sleep/nickname-questions"
#: Never in a catch-up: app-only audit rows, an agent's proposed edit, an agent request, and the grouped "Confirm N
#: links" review (the app's one screen, ruling 36 D5).
NEVER = frozenset({"normalization", "page_edit", "agent_request"})
MIN_PREFIX = 3
MAX_TAIL = 8
MAX_RATIO = 0.6


# --------------------------------------------------------------------------- the budget (S10)


class Budget:
    """One drain's allowance of new questions, shared by every proposer that feeds the catch-up."""

    def __init__(self, cap: int | None = NEW_PER_DRAIN):
        self.cap = None if cap is None else max(0, int(cap))
        self.taken: dict[str, int] = {}

    def take(self, who: str) -> bool:
        if self.cap is not None and sum(self.taken.values()) >= self.cap:
            return False
        self.taken[who] = self.taken.get(who, 0) + 1
        return True

    @property
    def used(self) -> int:
        return sum(self.taken.values())


# --------------------------------------------------------------------------- the cursor


def _cursor_dir() -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / "inbox_catchup"


class Cursor:
    """The ids one session's catch-up already served. ``$CICADA_HOME/inbox_catchup/<hash>.json`` — the hash of the
    bank's path and the session id, never either in clear; ids and a time, nothing else."""

    def __init__(self, memory_path: Path, session_id: str | None):
        raw = f"{Path(memory_path).resolve()}\x00{session_id or 'no-session'}"
        self.path = _cursor_dir() / f"{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}.json"

    def seen(self) -> set[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        if not isinstance(data, dict) or time.time() - float(data.get("at") or 0) > CURSOR_HOURS * 3600:
            return set()
        return {str(i) for i in data.get("ids") or [] if re.fullmatch(r"inbox-\d+", str(i))}

    def add(self, ids) -> None:
        ids = sorted(self.seen() | {str(i) for i in ids})
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cursor-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"ids": ids, "at": time.time()}, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError as exc:   # a cursor never costs the read: the next call may repeat, nothing worse
            logger.warning(f"catch-up cursor not saved: {type(exc).__name__}")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def sweep(now: float | None = None) -> int:
    """Forget every cursor older than :data:`CURSOR_HOURS` (called on each read; a handful of tiny files)."""
    now = now or time.time()
    gone = 0
    try:
        for p in _cursor_dir().glob("*.json"):
            try:
                if now - p.stat().st_mtime > CURSOR_HOURS * 3600:
                    p.unlink()
                    gone += 1
            except OSError:
                continue
    except OSError:
        pass
    return gone


# --------------------------------------------------------------------------- one person, several names (S7)


def _fold(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _type(memory_path: Path, page_id: str) -> str | None:
    if not page_id:
        return None
    f = bank_index.file(memory_path, "entities", f"{page_id}.md")
    return str((f.frontmatter if f else {}).get("type") or "") or None


def _is_people_pair(memory_path: Path, fm: dict) -> bool:
    a = _type(memory_path, str(fm.get("entity_id") or ""))
    b = _type(memory_path, str(fm.get("merge_target_hint") or ""))
    held = a is None and str(fm.get("suggested_classification") or "person").lower() in ("person", "")
    return b == "person" and (a == "person" or held)


def groups(memory_path: Path, rows: list[tuple[str, dict]]) -> list[list[str]]:
    """Open duplicate questions about people that chain into one person: lists of item ids, three names or more
    (two names are the pair's own question). Only people: a project, a tool and a held name are never grouped."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_item: dict[str, tuple[str, str]] = {}
    for item_id, fm in rows:
        if str(fm.get("kind") or "") != "merge_suggestion" or not _is_people_pair(memory_path, fm):
            continue
        a = str(fm.get("entity_id") or "")
        b = str(fm.get("merge_target_hint") or "")
        if not a or not b or a == b:
            continue
        parent[find(a)] = find(b)
        by_item[item_id] = (a, b)
    comps: dict[str, list[str]] = {}
    names: dict[str, set[str]] = {}
    for item_id, (a, _b) in by_item.items():
        root = find(a)
        comps.setdefault(root, []).append(item_id)
        names.setdefault(root, set()).update(by_item[item_id])
    return [sorted(ids) for root, ids in comps.items() if len(names[root]) >= 3]


def _first(name: str) -> str:
    folded = _fold(name).split()
    return folded[0] if folded else ""


def nickname_pair(a: str, b: str) -> bool:
    """One name is a short form of the other — a nickname and its long form ("Sam" / "Samantha"): the short one
    is a single word (a nickname carries no surname), at least :data:`MIN_PREFIX` letters, a strict prefix of the
    long one's first word and at most :data:`MAX_RATIO` of its length, which runs at most :data:`MAX_TAIL` letters
    past it. The ratio is what keeps two different given names apart: a name and its feminine or longer sibling
    differ by a short ending (measured on a copy of the owner's bank: every pair over 0.6 was two names, every pair
    under it a short form; ``test_catchup``)."""
    fa, fb = _fold(a).split(), _fold(b).split()
    if not fa or not fb:
        return False
    short, long_ = (fa, fb) if len(fa[0]) <= len(fb[0]) else (fb, fa)
    if len(short) != 1 or len(short[0]) < MIN_PREFIX or short[0] == long_[0] or not long_[0].startswith(short[0]):
        return False
    if len(long_[0]) - len(short[0]) > MAX_TAIL or len(short[0]) > MAX_RATIO * len(long_[0]):
        return False
    return True


@dataclass
class NicknameReport:
    written: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)      # page ids, for the dry run
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def nickname_candidates(memory_path: Path, report: NicknameReport | None = None) -> list[tuple[str, str]]:
    """People pages whose names are a nickname and its long form, with no open question and no "two people" answer
    on the pair, most-used pair first. Never the person's own page; never a pair already known as one page's alias."""
    from api.services import everyday_names, merge_rejections
    from api.services.inbox_generator import dedup_key

    report = report if report is not None else NicknameReport()
    memory_path = Path(memory_path)
    owner = everyday_names.owner_id(memory_path)
    people: list[tuple[str, str, set[str]]] = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "") != "person" or f.stem == owner:
            continue
        if str(fm.get("status") or "") in ("archived", "dropped"):
            continue
        name = str(fm.get("name") or f.stem)
        aliases = {_fold(a) for a in (fm.get("aliases") or []) if isinstance(a, str)}
        people.append((f.stem, name, aliases | {_fold(name)}))
    open_pairs = set()
    for f in bank_index.files(memory_path, "inbox"):
        fm = f.frontmatter or {}
        if str(fm.get("kind") or "") == "merge_suggestion":
            open_pairs.add(dedup_key("merge_suggestion", fm))
    rejected = merge_rejections.load_rejected(memory_path)
    by_first: dict[str, list[tuple[str, str, set[str]]]] = {}
    for row in people:
        first = _first(row[1])
        if len(first) >= MIN_PREFIX:
            by_first.setdefault(first[:MIN_PREFIX], []).append(row)
    use = page_use.scores(memory_path)
    out: list[tuple[str, str]] = []
    for bucket_rows in by_first.values():
        for i, (ida, na, alias_a) in enumerate(bucket_rows):
            for idb, nb, alias_b in bucket_rows[i + 1:]:
                if not nickname_pair(na, nb):
                    continue
                pair = tuple(sorted((ida, idb)))
                if alias_a & alias_b:
                    report.skip("already_aliases")
                    continue
                if pair in rejected:
                    report.skip("person_said_two_people")
                    continue
                if pair in open_pairs:
                    report.skip("question_open")
                    continue
                out.append(pair)
    out.sort(key=lambda p: (-max(use.get(p[0], 0.0), use.get(p[1], 0.0)), p))
    report.pairs = list(out)
    return out


def _newest_episode(fm: dict) -> str:
    eps = sorted((str(e) for e in fm.get("source_episodes") or [] if str(e).startswith("ep_")), reverse=True)
    return eps[0] if eps else ""


def propose_nicknames(memory_path: Path, today: date, *, budget: Budget, skip: frozenset[str] = frozenset(),
                      dry_run: bool = False) -> NicknameReport:
    """Ask "Are A and B the same person?" for pairs spelling alone suggests, within the drain's budget and
    :data:`NICKNAME_MAX_OPEN`. Writes ordinary ``merge_suggestion`` questions (the shape ``ClarificationManager``
    writes, marked ``detected: spelling``), the less-used page as the one asked about. Files only."""
    memory_path = Path(memory_path)
    report = NicknameReport()
    found = nickname_candidates(memory_path, report)
    open_count = sum(1 for f in bank_index.files(memory_path, "inbox")
                     if str((f.frontmatter or {}).get("detected") or "") == "spelling")
    use = page_use.scores(memory_path, today=today)
    inbox_dir = memory_path / "inbox"
    for a, b in found:
        if open_count >= NICKNAME_MAX_OPEN:
            report.skip("max_open")
            continue
        if f"entities/{a}.md" in skip or f"entities/{b}.md" in skip:
            report.skip("page_dirty")
            continue
        if not budget.take("nickname"):
            report.skip("drain_budget")
            continue
        open_count += 1
        asked, target = (a, b) if use.get(a, 0.0) <= use.get(b, 0.0) else (b, a)
        if dry_run:
            report.written.append("inbox/<new nickname pair>")
            continue
        fa = (bank_index.file(memory_path, "entities", f"{asked}.md") or None)
        fb = (bank_index.file(memory_path, "entities", f"{target}.md") or None)
        fma, fmb = (fa.frontmatter if fa else {}), (fb.frontmatter if fb else {})
        name_a, name_b = str(fma.get("name") or asked), str(fmb.get("name") or target)
        from api.services import inbox_service   # lazy: its import graph is wide

        inbox_dir.mkdir(parents=True, exist_ok=True)
        path = inbox_dir / f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}.md"
        episode = _newest_episode(fma) or _newest_episode(fmb)
        markdown_parser.write(path, {
            "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.5,
            "entity_id": asked, "entity_name": name_a, "title": f"Is {name_a} the same as {name_b}?",
            "uncertainty_type": f"Possible duplicate of {name_b}", "suggested_classification": "person",
            "suggested_confidence": 0.5, "created_date": today.isoformat(), "merge_target_hint": target,
            "detected": "spelling", **({"source_episode": episode} if episode else {}),
        }, f"One name begins the other ({name_a} / {name_b}); they may be one person under a nickname. "
           "Asked, never joined: only your answer joins them.")
        report.written.append(f"inbox/{path.name}")
    if report.written and not dry_run:
        bank_index.invalidate(memory_path)
    return report


def nickname_commit_message(paths: list[str], today: date) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Same-person questions {today.isoformat()}",
        [f"{p}: created (source: n/a, trigger: {NICKNAME_TRIGGER})" for p in paths], authors=["cicada"])


# --------------------------------------------------------------------------- the read (S2)


@dataclass
class Entry:
    ids: list[str]                 # one id, or a group's ids
    rank: float
    use: float
    fm: dict
    created: str
    group_names: list[str] = field(default_factory=list)


def _visible(memory_path: Path, fm: dict, stem: str, today: str) -> bool:
    from api.services import inbox_service, mcp_tools, predicates

    kind = str(fm.get("kind") or "")
    if kind in NEVER or str(fm.get("asks") or "") == "sources":
        return False
    if str(fm.get("status") or "pending") != "pending":
        return False
    if not mcp_tools.nudge_visible(fm, wanted=frozenset(), today=today, memory_path=memory_path):
        return False
    if inbox_service._subject_gone(memory_path, str(fm.get("entity_id") or ""),
                                   inbox_service._hiding_kind(kind, fm.get("asks"))):
        return False
    if (kind == "conflict" and str(fm.get("asks") or "") != "still"
            and predicates.cardinality(memory_path, str(fm.get("predicate") or "")) == "multi"):
        return False     # G98: a set, not a contradiction — shown in the app, never asked
    return True


def select(memory_path: Path, *, today: str | None = None, exclude=frozenset(), limit: int = LIMIT
           ) -> tuple[list[Entry], int]:
    """``(the next entries to ask, how many remain after them)``: most-used page first, newest on a tie, a chain of
    same-person questions as one entry. ``exclude`` is what this session already served or skipped."""
    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    table = page_use.scores(memory_path)
    rows: list[tuple[str, dict]] = []
    for f in bank_index.files(memory_path, "inbox"):
        if not f.stem.startswith("inbox-") or f.stem in exclude:
            continue
        fm = dict(f.frontmatter or {})
        try:
            if _visible(memory_path, fm, f.stem, today):
                rows.append((f.stem, fm))
        except Exception as exc:  # noqa: BLE001 — one unreadable item never costs the catch-up
            logger.warning(f"catch-up skipped {f.stem}: {type(exc).__name__}")
    by_id = dict(rows)
    grouped: set[str] = set()
    entries: list[Entry] = []
    for ids in groups(memory_path, rows):
        members = [by_id[i] for i in ids]
        uses = [page_use.item_use(table, m) for m in members]
        best = max(range(len(ids)), key=lambda k: page_use.rank(members[k].get("priority"), uses[k]))
        pages = []
        for m in members:
            for pid in (str(m.get("merge_target_hint") or ""), str(m.get("entity_id") or "")):
                if pid and pid not in pages:
                    pages.append(pid)
        names = []
        for pid, m in [(p, next((x for x in members if str(x.get("entity_id")) == p), None)) for p in pages]:
            f = bank_index.file(memory_path, "entities", f"{pid}.md")
            page_fm = f.frontmatter if f else {}
            label = inbox_wording.speakable(page_fm.get("name") or (m or {}).get("entity_name") or pid, page_fm)
            if label not in names:
                names.append(label)
        entries.append(Entry(ids=ids, rank=page_use.rank(members[best].get("priority"), max(uses)), use=max(uses),
                             fm=members[best], created=max(str(m.get("created_date") or "") for m in members),
                             group_names=names))
        grouped.update(ids)
    for stem, fm in rows:
        if stem in grouped:
            continue
        use = page_use.item_use(table, fm)
        entries.append(Entry(ids=[stem], rank=page_use.rank(fm.get("priority"), use), use=use, fm=fm,
                             created=str(fm.get("created_date") or "")))
    entries.sort(key=lambda e: (-e.rank, _neg(e.created), e.ids[0]))
    picked = entries[: max(0, int(limit))]
    return picked, max(0, len(entries) - len(picked))


def _neg(day: str) -> str:
    return "".join(str(9 - int(ch)) if ch.isdigit() else ch for ch in day)


def spoken_for(memory_path: Path, entry: Entry, fm: dict, today: str) -> inbox_wording.Spoken:
    """The entry's human question and reason, read from its pages' frontmatter."""
    from api.services import everyday_names

    def page(pid: str) -> dict | None:
        f = bank_index.file(memory_path, "entities", f"{pid}.md") if pid else None
        return dict(f.frontmatter) if f else None

    return inbox_wording.spoken(fm, today, page_fm=page(str(fm.get("entity_id") or "")),
                                other_fm=page(str(fm.get("merge_target_hint") or "")),
                                owner_id=everyday_names.owner_id(memory_path),
                                group=entry.group_names or None)
