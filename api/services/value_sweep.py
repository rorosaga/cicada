"""A one-time sweep for values a memory already holds twice (G148, owner 2026-11-24): plan with a judge, apply with none.

The live join (`value_alignment.align`) acts when a NEW value arrives, and the second reading (#840) only on that same
arrival. A pair the small judge refused before that fix is never looked at again: the newer value is no longer new. So a
page written earlier keeps "price per postcard: 4 euros" beside "card price: 5 euros", both current.

**Plan** (:func:`plan_page`, writes nothing): for each page with two or more open values, every value that has an OLDER one
of its slot that is worded differently and says a different thing is shown as NEW to the main model, through the live
module's own second-reading prompt (`value_alignment.REREAD`), proposals and check (`value_alignment.proposals`,
`confirmed`): a join needs both answers, as in the live path. Before the check, code refuses what the live path's rails
refuse (:func:`refusal`): the person's own words closed in favour of a machine claim (`inbox_tend.may_close`), a pair with
an open inbox question, a person's edit, a newer value that is not dated later, two values one conversation stated
together. Every pair, the judge's own words and what would change are written to a file the person reads.

**Apply** (:func:`apply`, no model call) writes exactly the groups of a reviewed plan file: the newer value takes the older's
predicate and the older is CLOSED (`claim_reconciler._close`: ``valid_to``, ``superseded_by``), never deleted, as one `cicada`
commit one ``git revert`` undoes. A group whose claims changed since the plan is skipped and counted, never re-judged.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (
    claim_reconciler as reconciler, claims_ledger, git_service, inbox_generator, inbox_questions, markdown_parser, page_lock,
    value_alignment as va, write_admission,
)
from api.services.claims import parse_claims, write_claims

TRIGGER = "maintenance/value-sweep"
VERSION = 1
#: Calls one page may cost (an ask and a check per proposal), and a page with more value attributes is left alone.
MAX_CALLS_PAGE = 8
MAX_LINES = va.MAX_LINES


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: write nothing."""


class NoGit(RuntimeError):
    """The bank is not a git repository: an undo (one ``git revert``) would not exist, so nothing is written."""


class EngineDown(RuntimeError):
    """The engine failed several calls in a row (a plan limit, a lost sign-in): stop, the run resumes."""


@dataclass
class Meter:
    ask: int = 0
    check: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.ask + self.check


# --------------------------------------------------------------------------- reading a page


def _said(line: va.Line) -> str:
    return str(line.latest.valid_from or "")[:10]


@dataclass
class Read:
    id: str
    name: str = ""
    skip: str | None = None
    claims: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    eligible: list = field(default_factory=list)   # lines that have an older, differently worded value of their slot


def read_page(page_id: str, fm: dict, body: str) -> Read:
    fm = fm or {}
    out = Read(page_id, str(fm.get("name") or page_id))
    if str(fm.get("status") or "active") in ("archived", "dropped"):
        out.skip = "archived"
        return out
    try:
        out.claims = parse_claims(body, strict=True)   # as every read-modify-write path: a line that does not parse is never dropped
    except Exception:  # noqa: BLE001 - a page whose claims cannot be read is left alone, whole
        out.skip = "claims_unreadable"
        return out
    values = [c for c in out.claims if va._open_value(c)]
    if len(values) < 2:
        out.skip = "few_values"
        return out
    lines = va._lines([], values)
    if len(lines) < 2:
        out.skip = "few_values"
        return out
    if len(lines) > MAX_LINES:
        out.skip = "too_many_values"
        return out
    if any(len(ln.claims) > 1 for ln in lines):
        out.skip = "two_open_in_one_slot"   # a state the live path never leaves: not guessed at here
        return out
    out.lines = lines
    out.eligible = [ln for ln in lines if any(
        o is not ln and va._joinable(ln, o) and not va._worded_alike(ln, o) and _said(o) and _said(o) < _said(ln)
        and _object(o) != _object(ln) for o in lines)]
    if not out.eligible:
        out.skip = "nothing_to_join"
    return out


def _object(line: va.Line) -> str:
    return " ".join(str(line.latest.object or "").lower().split())


def census(read: Read) -> dict:
    """What a page would cost, with no model: one ask, and a check for each proposal (at most one per eligible line)."""
    if read.skip:
        return {"eligible": 0, "max_calls": 0}
    return {"eligible": len(read.eligible), "values": len(read.lines),
            "max_calls": min(MAX_CALLS_PAGE, 1 + len(read.eligible))}


#: A question the person (or Sleep) has finished with is gone from the inbox; these statuses are the ones a file may still carry.
_CLOSED = frozenset({"resolved", "answered", "dismissed", "done"})


def question_claims(fm: dict) -> set[str]:
    """Every claim id an inbox item names, by the readers the inbox itself uses: the claim that opened it and the ones it
    covers (`inbox_generator.fold_claims`, `decay_claim_ids`), either side of a conflict, and each option's claim."""
    out = {cid for _entity, cid in inbox_generator.fold_claims(fm)} | set(inbox_generator.decay_claim_ids(fm))
    for key in ("existing_claim_id", "new_claim_id", "old_claim_id"):
        if fm.get(key):
            out.add(str(fm[key]).strip())
    for option in inbox_questions.normalize_options(fm.get("options")):
        if option.get("claim_id"):
            out.add(str(option["claim_id"]).strip())
    return {c for c in out if c}


def open_questions(bank: Path) -> set[str]:
    """The claim ids an open inbox question names: a pair with one is left to the question. A deferred question is open (it
    comes back the day its reminder passes)."""
    out: set[str] = set()
    for path in sorted((Path(bank) / "inbox").glob("*.md")) if (Path(bank) / "inbox").is_dir() else []:
        try:
            fm = markdown_parser.parse(path).frontmatter or {}
        except Exception:  # noqa: BLE001
            continue
        if str(fm.get("status") or "pending") in _CLOSED:
            continue
        out |= question_claims(fm)
    return out


_DAY = re.compile(r"\d{4}-\d{2}-\d{2}(?:$|[T ])")
_EPISODE_DAY = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_")


def said_in(line: va.Line) -> tuple[str, str]:
    """``(the day, the conversation id)`` the value was first said: the earliest of the claim's conversations (an
    ``ep_YYYY-MM-DD_NNN`` id carries the conversation's own day, ruling 34); ``("", "")`` when it names none."""
    c = line.latest
    seen = [str(e) for e in [*(c.source_episodes or []), *(getattr(ev, "episode", "") for ev in (c.evidence or []))] if e]
    days = sorted((m.group(1), e) for e in dict.fromkeys(seen) if (m := _EPISODE_DAY.match(e)))
    return days[0] if days else ("", "")


def refusal(older: va.Line, newer: va.Line, asked: set[str]) -> str | None:
    """Why a pair may not be joined whatever the judge says: the live path's rails, in code."""
    from api.services.inbox_tend import may_close

    a, b = older.latest, newer.latest
    for ln in (older, newer):
        if not _DAY.match(str(ln.latest.valid_from or "")):
            return f"a value's date is less precise than a day (\"{ln.latest.valid_from or 'none'}\"): which is newer cannot be told"
    if not (_said(older) and _said(newer)) or _said(older) >= _said(newer):
        return "the newer value is not dated later than the older"
    if older.episodes & newer.episodes:
        return "one conversation stated both"
    (day_a, _ep_a), (day_b, _ep_b) = said_in(older), said_in(newer)
    if not day_a or not day_b:
        return "one of the two names no conversation, so the day it was said is unknown"
    if day_a >= day_b:
        return (f"the dates and the conversations disagree: the value dated {_said(older)} was said on {day_a}, "
                f"the one dated {_said(newer)} on {day_b}")
    if reconciler.is_human(a) or reconciler.is_human(b):
        return "a person's own edit is one of them"
    if {a.id, b.id} & asked:
        return "an open inbox question names one of them"
    if _object(older) == _object(newer):
        return "both say the same thing"
    if not may_close(b, [a]):
        return "the person's own words would be closed in favour of a machine claim"
    if reconciler.trust_decision(b, a) != "SUPERSEDE":
        return "the trust rules would not let the newer close the older"
    return None


# --------------------------------------------------------------------------- the plan


def _member(line: va.Line, words: str = "") -> dict:
    c = line.latest
    day, episode = said_in(line)
    return {"claim": c.id, "predicate": c.predicate, "object": str(c.object), "said": _said(line),
            "valid_from": str(c.valid_from or ""), "said_on": day, "conversation": episode,
            "text": va._sentence(line).split("\n")[0], "words": words or line.words, "origin": str(c.origin or ""),
            "trust": str(c.source_trust or "")}


def state_hash(members: list[dict], claims_by_id: dict) -> str:
    """What the plan saw of the claims in a group: their id, predicate, object and end. A change to any is a changed page."""
    parts = []
    for m in members:
        c = claims_by_id.get(m["claim"])
        parts.append([m["claim"], getattr(c, "predicate", None), str(getattr(c, "object", None)), getattr(c, "valid_to", None),
                      getattr(c, "superseded_by", None)])
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


class _Recorder:
    """The judge, remembering its last reply so a row can carry the reader's own words."""

    def __init__(self, judge: Callable[[str], dict], meter: Meter, kind: str) -> None:
        self.judge, self.meter, self.kind, self.last = judge, meter, kind, {}

    def __call__(self, prompt: str) -> dict:
        setattr(self.meter, self.kind, getattr(self.meter, self.kind) + 1)
        try:
            self.last = self.judge(prompt)
        except Exception as exc:  # noqa: BLE001 - three in a row stop the run
            self.meter.failed += 1
            logger.info(f"value sweep: a call failed ({type(exc).__name__})")
            if self.meter.failed >= 3:
                raise EngineDown(type(exc).__name__) from exc
            raise
        self.meter.failed = 0
        return self.last


def plan_page(read: Read, bank: Path, judge: Callable[[str], dict], meter: Meter, asked: set[str], *,
              max_calls: int = MAX_CALLS_PAGE, run_calls_left: int | None = None) -> dict:
    """One page's joins: the live second reading and its check, then the live rails. The row :func:`apply` reads."""
    words = va.Words(bank)
    eligible = {id(ln) for ln in read.eligible}
    lines = [va.Line(i, ln.predicate, ln.key, ln.claims, id(ln) in eligible, words.of(ln.latest))
             for i, ln in enumerate(sorted(read.lines, key=lambda ln: (_said(ln), ln.predicate)), 1)]
    ask = va.Ask(read.id, lines)
    start = meter.total
    row = {"v": VERSION, "page": read.id, "name": read.name, "status": "done", "groups": [], "refused": [], "strike": False}
    allowed = min(max_calls, run_calls_left if run_calls_left is not None else max_calls)
    # "capped": the page's own limit (final). "not_read": the run's call limit, or a failed call: the page was not read, and
    # the next run of the same command reads it (the plan tool counts only "done" and "capped" pages as finished).
    cap_status = "capped" if run_calls_left is None or run_calls_left >= max_calls else "not_read"
    if allowed < 2:
        row["status"] = cap_status
        return row
    reader, checker = _Recorder(judge, meter, "ask"), _Recorder(judge, meter, "check")
    try:
        pairs = va.proposals(reader(va.prompt(ask, va.REREAD)), ask)
    except EngineDown:
        raise
    except Exception as exc:  # noqa: BLE001 - a failed call decides nothing, and the page is NOT finished
        row["status"], row["error"] = "not_read", type(exc).__name__
        return row
    kept: list[tuple[va.Line, va.Line]] = []
    why: dict[tuple[int, int], str] = {}
    for new, other in pairs:
        older, newer = sorted((new, other), key=lambda ln: (_said(ln), ln.predicate))
        bad = refusal(older, newer, asked)
        if bad is not None:
            row["refused"].append({"older": _member(older), "newer": _member(newer), "stage": bad})
            continue
        if meter.total - start >= allowed:
            if row["status"] == "done":
                row["status"] = cap_status
            break
        try:
            ok = va.confirmed(new, other, ask, checker)
        except EngineDown:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed check leaves this pair unread, and so the page
            row["status"], row["error"] = "not_read", type(exc).__name__
            continue
        reason = str((checker.last or {}).get("why") or "")
        if ok:
            kept.append((new, other))
            why[(older.n, newer.n)] = reason
        else:
            row["refused"].append({"older": _member(older), "newer": _member(newer),
                                   "stage": "the second reader's check said they differ", "why": reason})
    by_id = {c.id: c for c in read.claims}
    for group in va.groups(kept):
        ordered = sorted(group, key=lambda ln: (_said(ln), ln.predicate))
        # Each step of the chain must pass the rails too (a chain may join two lines the judge never paired).
        stage = next((refusal(a, b, asked) for a, b in zip(ordered, ordered[1:]) if refusal(a, b, asked)), None)
        members = [_member(ln) for ln in ordered]
        if stage is not None:
            row["refused"].append({"older": members[0], "newer": members[-1], "stage": stage})
            continue
        row["groups"].append({
            "id": f"{read.id}#{len(row['groups']) + 1}", "members": members, "keeps_predicate": members[0]["predicate"],
            "why": [why.get((a.n, b.n)) or why.get((b.n, a.n)) or "" for a, b in zip(ordered, ordered[1:])],
            "state": state_hash(members, by_id), "strike": False})
    row["calls"] = {"ask": 1, "check": meter.total - start - 1}
    return row


# --------------------------------------------------------------------------- the plan file


def row_groups(row: dict, skip_groups=()) -> list[dict]:
    if row.get("strike"):
        return []
    skip = set(skip_groups)
    return [g for g in row.get("groups") or [] if not g.get("strike") and g.get("id") not in skip]


GUIDE = """BEFORE YOU APPLY: what to strike

A join below is the reader's reading, and two kinds of it are wrong even when the reader says yes. Strike a row (delete it,
set "strike": true, or name it with --skip-group PAGE#N) when:

  1. The LATER line only restates the earlier one more vaguely. The earlier, more specific value would stop being current
     (a degree, then "studies at the university"; a night shift, then "works at the shop"). The later is no news: keep both.
  2. The two values are BOTH TRUE AT ONCE (two phone numbers, two jobs held together, the editor preferred and the editor in
     daily use). Closing one loses a real value.

Every row shows, for each value, the date it is valid from, the day it was said and the conversation it was said in. Where the
dates and the days disagree, the pair is listed under "left alone": nothing is closed on a guess.
"""


def _line_of(m: dict) -> str:
    return (f"{m['said']}  {m['text']}   [{m['predicate']} = {m['object']}]\n"
            f"            valid from {m.get('valid_from') or '?'}, said on {m.get('said_on') or '?'} in "
            f"{m.get('conversation') or '(no conversation)'}")


def review_text(rows: list[dict]) -> str:
    lines: list[str] = []
    unread = [r for r in rows if r.get("status") == "not_read"]
    for row in sorted(rows, key=lambda r: (-len(r.get("groups") or []), str(r.get("page")))):
        if not row.get("groups") and not row.get("refused"):
            continue
        lines.append(f"## {row['page']}  ({row.get('name')})  [{row['status']}]")
        for g in row.get("groups") or []:
            lines.append(f"  {g['id']}  JOIN" + ("  [STRUCK]" if g.get("strike") else ""))
            for n, m in enumerate(g["members"]):
                lines.append(f"    {'older ' if n == 0 else 'later '} {_line_of(m)}")
                if m.get("words"):
                    lines.append(f"            they said: \"{m['words']}\"")
            for text in g.get("why") or []:
                if text:
                    lines.append(f"    reader: {text}")
            lines.append(f"    would change: the later value{'s take' if len(g['members']) > 2 else ' takes'} the predicate "
                         f"\"{g['keeps_predicate']}\"; the earlier value{'s are' if len(g['members']) > 2 else ' is'} CLOSED "
                         "(kept, ended on the later value's day), the latest stays current")
        for item in row.get("refused") or []:
            lines.append(f"  left alone ({item['stage']}):")
            lines.append(f"    older  {_line_of(item['older'])}")
            lines.append(f"    newer  {_line_of(item['newer'])}"
                         + (f"\n    reader: {item['why']}" if item.get("why") else ""))
        lines.append("")
    if unread:
        lines.append("NOT READ (a call failed or the run's call limit came first; run the same plan command again to read them):")
        lines += [f"  {r['page']}" + (f"  ({r['error']})" if r.get("error") else "") for r in sorted(unread, key=lambda r: r["page"])]
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- apply


@dataclass
class Result:
    pages: int = 0
    groups: int = 0
    closed: int = 0
    written_pages: list = field(default_factory=list)
    committed: bool = False
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str, n: int = 1) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + n

    def counts(self) -> dict:
        return {"pages_in_plan": self.pages, "groups_in_plan": self.groups, "values_closed": self.closed,
                "pages_written": len(self.written_pages), "committed": self.committed,
                "skipped": dict(sorted(self.skipped.items()))}


class Undo:
    """The bytes of every file about to be written, so a failure after the first write puts exactly those back (a page that
    stays modified and uncommitted would be swept into the next commit by whoever commits next)."""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes | None] = {}

    def remember(self, path) -> None:
        path = Path(path)
        for p in (path, claims_ledger.path_for(path)) if path.suffix == ".md" else (path,):
            if p not in self.saved:
                self.saved[p] = p.read_bytes() if p.is_file() else None

    def restore(self, bank: Path | None = None) -> None:
        for path, data in self.saved.items():
            try:
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
            except OSError as exc:  # noqa: BLE001 - say so, keep restoring the rest
                logger.error(f"sweep: could not restore {path.name} ({type(exc).__name__})")
        if bank is not None and self.saved:
            try:   # a commit that failed after `git add` leaves the paths staged
                rels = [str(p.relative_to(bank)) for p in self.saved if bank in p.parents]
                with git_service.write_lock(Path(bank)):
                    git_service._git_sync(Path(bank), "reset", "-q", "--", *rels)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"sweep: could not unstage ({type(exc).__name__})")


def apply_page(path: Path, row: dict, groups: list[dict], bank: Path, result: Result, check: bool,
               remember=lambda path: None) -> bool:
    """One page's groups, each only if the page still reads as the plan saw it and the rails still pass."""
    try:
        parsed = markdown_parser.parse(path)
    except Exception:  # noqa: BLE001
        result.skip("unreadable")
        return False
    fm, body = dict(parsed.frontmatter or {}), parsed.body
    read = read_page(path.stem, fm, body)
    if read.skip in ("archived", "claims_unreadable"):
        result.skip(f"now_{read.skip}")   # an unreadable line is never re-rendered away: the whole page is left alone
        return False
    claims = read.claims
    by_id = {c.id: c for c in claims}
    asked = open_questions(bank)
    changed = 0
    for group in groups:
        members = group["members"]
        if any(m["claim"] not in by_id for m in members):
            result.skip("claim_missing")
            continue
        if state_hash(members, by_id) != group.get("state"):
            result.skip("changed_since_plan")
            continue
        lines = [next((ln for ln in va._lines([], [c for c in claims if va._open_value(c)])
                       if any(x.id == by_id[m["claim"]].id for x in ln.claims)), None) for m in members]
        if any(ln is None for ln in lines):
            result.skip("no_longer_open")
            continue
        bad = next((refusal(a, b, asked) for a, b in zip(lines, lines[1:]) if refusal(a, b, asked)), None)
        if bad is not None:
            result.skip("rails_now_refuse")
            continue
        keep = by_id[members[0]["claim"]].predicate
        for before, after in zip(members, members[1:]):
            older, newer = by_id[before["claim"]], by_id[after["claim"]]
            newer.predicate = keep
            reconciler._close(older, by=newer)
        changed += len(members) - 1
        result.closed += len(members) - 1
    if not changed:
        return False
    if not check:
        remember(path)
        markdown_parser.write(path, fm, write_claims(body, claims))
    return True


@contextlib.contextmanager
def locked(memory_path, *, sleep_running: Callable[[], bool], check: bool = False):
    """The bank's write admission, the page lock and a Sleep check: what every one-time repair holds while it writes.
    ``check`` reads and writes nothing, so it asks nobody and holds no lock. Raises :class:`SleepRunning` first."""
    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        raise NoGit("the bank is not a git repository: the sweep's one commit, and its undo, would not exist")
    admission = (contextlib.nullcontext() if check else
                 write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")))
    with admission:
        if not check and sleep_running():
            raise SleepRunning("a Sleep run is in progress; apply after it ends")
        with (contextlib.nullcontext() if check else page_lock.page_lock(memory_path)):
            yield


def dirty_paths(memory_path, prefix: str = "entities") -> frozenset[str] | None:
    """Paths under ``prefix`` with uncommitted changes (a page a person is editing); ``None`` when git cannot say."""
    if not (Path(memory_path) / ".git").exists():
        return None
    try:
        return git_service.dirty_paths_sync(Path(memory_path), prefix)
    except git_service.GitError:
        return None


def apply_rows(memory_path, rows: list[dict], *, skip_pages=(), skip_groups=(), check: bool = False,
               dirty: frozenset[str] = frozenset(), remember=lambda path: None) -> Result:
    """Write the groups of a reviewed plan onto the pages (the caller holds :func:`locked` and commits ``written_pages``)."""
    memory_path = Path(memory_path)
    result = Result()
    skip_pages = set(skip_pages)
    for row in rows:
        page_id = str(row.get("page") or "")
        groups = row_groups(row, skip_groups)
        result.pages += 1
        result.groups += len(groups)
        if row.get("status") == "not_read":
            result.skip("not_read")   # a page the plan did not finish reading: its groups are partial, never written
            continue
        if row.get("strike") or page_id in skip_pages or not groups:
            result.skip("struck" if row.get("groups") else "no_groups")
            continue
        path = memory_path / "entities" / f"{page_id}.md"
        rel = f"entities/{page_id}.md"
        if not re.fullmatch(r"[^/\\]+", page_id) or not path.is_file():
            result.skip("page_missing")
            continue
        if rel in dirty:
            result.skip("dirty_in_git")
            continue
        if apply_page(path, row, groups, memory_path, result, check, remember):
            result.written_pages.append(rel)
    return result


def commit_message(result: Result) -> tuple[str, list[str]]:
    return (f"Doubled values closed: {result.closed} older value(s) on {len(result.written_pages)} page(s)",
            [f"{rel}: joined a value to the attribute it restates, the older closed (trigger: {TRIGGER})"
             for rel in result.written_pages])


def apply(memory_path, rows: list[dict], *, sleep_running: Callable[[], bool], skip_pages=(), skip_groups=(),
          check: bool = False) -> Result:
    """This pass alone, in ONE commit authored ``cicada`` (`value_name_sweep` runs both passes in one). A failure after the
    first write puts every written file back, under the same lock."""
    with locked(memory_path, sleep_running=sleep_running, check=check):
        dirty = dirty_paths(memory_path)
        if dirty is None:
            result = Result()
            result.skip("git_unreadable", len(rows))
            return result
        undo = Undo()
        try:
            result = apply_rows(memory_path, rows, skip_pages=skip_pages, skip_groups=skip_groups, check=check, dirty=dirty,
                                remember=undo.remember)
            if result.written_pages and not check:
                head, body = commit_message(result)
                git_service.commit_paths_sync(Path(memory_path),
                                              git_service.build_commit_message(head, body, authors=["cicada"]),
                                              result.written_pages)
                result.committed = True
        except BaseException:
            undo.restore(Path(memory_path))
            raise
    return result
