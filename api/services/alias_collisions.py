"""Two pages that go by one name: a title outranks an alias (G21, G209; owner 2026-11-24).

A page that lists, among the names it goes by, the TITLE of another live page makes that name point at two pages: Stage 2
and recall may resolve it to either, and the "same as?" lead it raises (`person_leads`) is asked of the person and cannot
be answered (a question about two existing pages that is not a page question never folds either: `inbox_service`'s
"the fold is the person's call"). Measured on one real bank (real values redacted): of 6,582 live pages, 112 listed as
an alias the title of another page, 129 such pairs; set aside the people (ruling 74 owns every pair of people) and the
saved links, they were three kinds in roughly equal parts: (a) one thing under two names, one page each (an
abbreviation and its full name, a product with and without its vendor's suffix); (b) a part, product or member
carrying the whole's name, or the reverse; (c) two unrelated things (an organisation carrying another's name, a short
name two different things fairly go by). The birth half is `wrong_aliases.title_of_other_page`; this is the half for what
is already in the bank, as Sleep's own tending — never a one-off script.

**What decides, and who.** The code finds the pairs (`pairs`) and settles by what the record already says, with no model:

* a pair with a saved link's `media` page on either side is quiet (`quiet_pages`): no question, no name taken from the real
  page — any open "same as?" about it is closed (rule ``alias_quiet``);
* a pair the record holds as two things (a relation claim, the person's "different", a split) loses the alias that makes
  them look like one (rule ``alias_apart``): no model, as the person's own "No" is not asked twice.

Anything else is read by the engine's main model, at most :data:`MAX_READS` pairs a run, on a plan only through
ruling 4's switch (`same_name_tend.main_engine`): both pages (name, type, other names, what they say) and the alias, answer
``same`` / ``part`` / ``different`` / ``unsure``; a second, differently framed read looks for the opposite reason. Then:

* both read ``part`` or ``different`` -> the alias is removed from the page that lists it, remembered in
  ``aliases_removed`` (no automatic writer adds it back), as one undoable Sleep settle (``alias_apart``). **Why removed,
  not kept with the pair recorded as two things:** the alias is the defect, the name still pulls Stage 2 and recall to two
  pages; recording "two things" would leave the name pointing at both and make `names_other_thing` forbid only NEW
  aliases. An undo is the person keeping it: `wrong_aliases.KEPT`, never proposed or removed again.
  **Never from a page the person's own words call by that name** (the alias, a whole word, in one of their turns of that
  page's conversations: a short name two things fairly share stays with the thing called by it);
* both read ``same`` -> ONE question for the pair, worded as one thing under two names (``detected: alias_collision``,
  `fold_page`: the person's yes folds the less-used page into the other, no keeps them apart and then the alias goes), the
  older "same as?" about the pair is that question, or is closed; never asked twice;
* anything else (``unsure``, the two reads disagree, or a read of two things where the person's own words call the page by
  the alias) is held quietly: **nothing is written and no open question is closed** (ruling 29 lets Sleep settle only on the
  person's own words or a small-stuff rule, and a model that could not tell is neither), the read is remembered, and the
  pair is not read again until a page it read changes. The same when the record says two things but not by the person
  (a relation claim may be a model's) and the alias is the person's own word: the question stays open.

**What the person holds is never touched.** A question about the pair that the person took back (``sleep_settle: undone``)
or put off is theirs: this step reads, closes, rewrites and counts none of them, asks no second question beside one, and
leaves the pair alone until they answer or the day passes (`person_holds`).

Sleep never folds two pages here: the fold stays the person's call. A person page on either side, or the owner's, is never
read (ruling 74). What a read stood on is kept outside every bank, ids and a hash only (`_seen`).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import engine_errors, text_fold, wrong_aliases

DETECTED = "alias_collision"
APART, QUIET, DOUBT = "alias_apart", "alias_quiet", "alias_doubt"
#: The words the settled list shows for each rule (merged into `inbox_tend.RULES`).
WORDS = {
    APART: "Two different things: one no longer lists the other's name as its own",
    QUIET: "A saved link shares the name; it is no question about your memory",
    # No longer written (a doubt closes nothing); kept so the settles made before still read in the list.
    DOUBT: "Sleep could not tell whether they are one thing; nothing was changed",
}
#: Pairs the model reads in one run (two calls each); the rest wait for the next one.
MAX_READS = 8
#: Engine-free settles in one run (each is one commit).
MAX_FREE = 40
#: What a read shows of each page.
PAGE_CHARS = 1200
#: The most conversations one page may list for Sleep to look through for the alias in the person's own words (newest
#: first, stopping at the first hit). A page with more is not scanned: the alias is kept, never removed.
MAX_EPISODES = 200
#: A read that could not be made is tried this many times with the record unchanged.
MAX_UNREAD_TRIES = 2

SYSTEM = ("You decide whether two entries of one person's private memory are the same real-world thing, and you answer "
          "in JSON.")

PROMPT = """Two pages of a personal memory meet on one name. {lead}

PAGE A: "{a_name}" (type: {a_type}; also goes by: {a_names})
{a_text}

PAGE B: "{b_name}" (type: {b_type}; also goes by: {b_names})
{b_text}

Decide what the two pages are.
- "same": ONE real thing held on two pages: an abbreviation and its full name, a name with and without the vendor's or company's suffix, the same product under two spellings.
- "part": two things, one standing to the other as a part, product, service, member, version or maker (a service and its platform, a library and its language, a product and its company), or an alternative to it.
- "different": two unrelated things that happen to share a name or a short form.
- "unsure": anything else, or too little to tell.
Rules:
- An alias is a lead, not proof: short names, abbreviations and first names are often shared by different things. Say "same" only when what the pages say fits ONE thing.
- A part is never the same as its whole, a product never the same as its maker.
- Decide only from what the pages say. What you know about the names yourself is no evidence.
{extra}
Answer in JSON only: {{"decision": "same" | "part" | "different" | "unsure", "reason": "one short sentence"}}
"""
SKEPTIC_TWO = ('You are the sceptical reader. A first reader called these two things (a part, a product, an alternative or '
               'unrelated). Look for any reason they are ONE thing before you answer: an abbreviation and its full name, '
               'a name with and without a vendor suffix. Say "part" or "different" only if you find none.\n')
SKEPTIC_ONE = ('You are the sceptical reader. A first reader called these ONE thing. Look for any reason they are TWO '
               '(a part and its whole, a product and its maker, a shared short name) before you answer. Say "same" only '
               'if you find none.\n')


@dataclass
class Pair:
    """Two live pages that meet on a name: ``listed`` maps each page that lists the other's title to the alias as it
    writes it. ``skip`` says why the pair is never read (a person, the owner's page)."""

    a: str
    b: str
    listed: dict[str, str] = field(default_factory=dict)
    skip: str = ""

    @property
    def key(self) -> str:
        return f"{self.a}|{self.b}"

    @property
    def mutual(self) -> bool:
        return len(self.listed) == 2


@dataclass
class Read:
    verdict: str = "unread"     # same | two | unsure | unread
    reason: str = ""
    model: str | None = None


@dataclass
class Plan:
    """What the tending will do with one pair, and why (ids and a rule only)."""

    pair: Pair
    rule: str = ""              # alias_apart | alias_quiet | alias_doubt | ask | read | ""
    why: str = ""               # a short code for the dry run
    removals: list[tuple[str, str]] = field(default_factory=list)   # (holder, alias)
    reads: int = 0
    reason: str = ""
    model: str | None = None


@dataclass
class Report:
    looked: int = 0
    reads: int = 0
    removed: int = 0
    asked: int = 0
    held: int = 0
    quiet: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    @property
    def joined(self) -> int:     # parity with the other tail steps' reports
        return 0


def _key(text) -> str:
    return wrong_aliases.title_key(text)


def _kind(fm: dict) -> str:
    return "person" if fm.get("owner") is True else str(fm.get("type") or "").strip().lower()


def _names(fm: dict, stem: str) -> list[str]:
    """A page's name and the names it goes by, never one the person removed."""
    removed = {_key(a.get("alias") if isinstance(a, dict) else a) for a in fm.get("aliases_removed") or []}
    return [str(n) for n in [fm.get("name") or stem, *[a for a in fm.get("aliases") or [] if isinstance(a, str)]]
            if str(n or "").strip() and _key(n) not in removed]


# --------------------------------------------------------------------------- finding the pairs (engine-free)


def pairs(memory_path: Path) -> list[Pair]:
    """Every pair of live pages where one lists the other's title as an alias, one entry per unordered pair, by id. A pair
    with a person or the owner's page on either side carries ``skip`` and is never read. Reads cached headers only."""
    from api.services import bank_index

    memory_path = Path(memory_path)
    entries = [(f.stem, f.frontmatter or {}) for f in bank_index.files(memory_path, "entities")
               if str((f.frontmatter or {}).get("status") or "active") not in ("archived", "dropped")]
    fms = dict(entries)
    out: dict[tuple[str, str], Pair] = {}
    for pid, fm in entries:
        own = _key(fm.get("name") or pid)
        gone = {_key(a.get("alias") if isinstance(a, dict) else a) for a in fm.get("aliases_removed") or []}
        kept = wrong_aliases.kept(fm)
        for alias in [a for a in fm.get("aliases") or [] if isinstance(a, str) and a.strip()]:
            key = _key(alias)
            if not key or key == own or key in gone or alias.casefold() in kept:
                continue
            for other, _kind_of in wrong_aliases.titled_pages(memory_path, alias):
                if other == pid or other not in fms:
                    continue
                a, b = sorted((pid, other))
                pair = out.setdefault((a, b), Pair(a, b))
                pair.listed.setdefault(pid, alias)
    for pair in out.values():
        kinds = {_kind(fms[pair.a]), _kind(fms[pair.b])}
        if "person" in kinds:
            pair.skip = "person"
    return sorted(out.values(), key=lambda p: (p.a, p.b))


def _is_media(fm: dict) -> bool:
    return str(fm.get("type") or "").strip().lower() == "media"


def _two_things(memory_path: Path, a: str, b: str) -> bool:
    """The record already says these are two: a relation claim, the person's "different" or a split."""
    from api.services import entity_relations, merge_rejections

    try:
        return (entity_relations.known(memory_path, a, b) or merge_rejections.is_rejected(memory_path, a, b)
                or merge_rejections.is_split(memory_path, a, b))
    except Exception:  # noqa: BLE001 — an unreadable record says nothing
        return False


def _whole_word(alias: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, flags=re.IGNORECASE) is not None


def called_by_own_words(memory_path: Path, holder_fm: dict, alias: str) -> bool:
    """Does the person's own turn, in ANY conversation this page was built from, say the alias (a whole word)? Then the
    alias is what they call that thing, and Sleep never takes it (the brief's short-name rule). Newest first, stops at the
    first hit, reads only the person's turns (`full_name_join._user_turns`, by authorship). A page listing more than
    :data:`MAX_EPISODES` conversations is not scanned and counts as called by it: the alias is kept, never removed."""
    from api.services import full_name_join

    episodes = list(dict.fromkeys(str(e) for e in holder_fm.get("source_episodes") or [] if isinstance(e, str) and e))
    if len(episodes) > MAX_EPISODES:
        return True
    for eid in reversed(episodes):
        try:
            if any(_whole_word(alias, turn) for turn in full_name_join._user_turns(memory_path, eid)):
                return True
        except Exception:  # noqa: BLE001 — a conversation that cannot be read counts as one that might say it
            return True
    return False


def triage(memory_path: Path, pair: Pair) -> Plan:
    """The engine-free outcome for one pair: ``alias_quiet``, ``alias_apart`` (the record already says two things) or
    ``read`` (a model decides). Reads files only."""
    from api.services import bank_index

    fa = bank_index.file(memory_path, "entities", f"{pair.a}.md")
    fb = bank_index.file(memory_path, "entities", f"{pair.b}.md")
    plan = Plan(pair)
    if fa is None or fb is None:
        plan.why = "gone"
        return plan
    if pair.skip:
        plan.why = pair.skip
        return plan
    if _is_media(fa.frontmatter or {}) or _is_media(fb.frontmatter or {}):
        plan.rule, plan.why = QUIET, "saved_link"
        return plan
    if _two_things(memory_path, pair.a, pair.b):
        plan.rule, plan.why = APART, "record_says_two"
        plan.removals = removable(memory_path, pair, {pair.a: fa.frontmatter or {}, pair.b: fb.frontmatter or {}})
        if not plan.removals:
            plan.rule, plan.why = DOUBT, "called_by_own_words"
        return plan
    plan.rule, plan.why = "read", "needs_read"
    return plan


def removable(memory_path: Path, pair: Pair, fms: dict[str, dict]) -> list[tuple[str, str]]:
    """The ``(holder, alias)`` removals this pair may take: the alias on each page that lists the other's title, except
    from a page the person's own words call by it."""
    out = []
    for holder, alias in sorted(pair.listed.items()):
        if not called_by_own_words(memory_path, fms.get(holder) or {}, alias):
            out.append((holder, alias))
    return out


# --------------------------------------------------------------------------- the reading (a model, bounded)


def _page_text(memory_path: Path, page_id: str) -> str:
    from api.services import claims, markdown_parser

    try:
        parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{page_id}.md", ledger=False)
    except Exception:  # noqa: BLE001
        return "(unreadable)"
    text = re.sub(r"\n{3,}", "\n\n", claims.strip_claims_block(parsed.body or "")).strip()
    return (text[:PAGE_CHARS] or "(empty)")


def build_prompt(memory_path: Path, pair: Pair, *, skeptic: str = "") -> str:
    from api.services import bank_index

    fa = (bank_index.file(memory_path, "entities", f"{pair.a}.md").frontmatter or {})
    fb = (bank_index.file(memory_path, "entities", f"{pair.b}.md").frontmatter or {})
    na, nb = str(fa.get("name") or pair.a), str(fb.get("name") or pair.b)
    if pair.mutual:
        lead = f'Each lists the other\'s title among the names it goes by ("{pair.listed[pair.a]}" on A, "{pair.listed[pair.b]}" on B).'
    elif pair.a in pair.listed:
        lead = f'Page A lists "{pair.listed[pair.a]}" among the other names it goes by, which is exactly the title of page B.'
    else:
        lead = f'Page B lists "{pair.listed[pair.b]}" among the other names it goes by, which is exactly the title of page A.'
    others = lambda fm, stem, name: ", ".join(n for n in _names(fm, stem) if n != name) or "nothing else"  # noqa: E731
    return PROMPT.format(
        lead=lead, a_name=na, a_type=str(fa.get("type") or "unknown"), a_names=others(fa, pair.a, na),
        a_text=_page_text(memory_path, pair.a), b_name=nb, b_type=str(fb.get("type") or "unknown"),
        b_names=others(fb, pair.b, nb), b_text=_page_text(memory_path, pair.b), extra=skeptic)


def _parse(raw) -> Read:
    if not isinstance(raw, dict):
        return Read()
    word = str(raw.get("decision") or raw.get("verdict") or "").strip().lower()
    model = str(raw.get("_model") or "").strip() or None
    reason = " ".join(str(raw.get("reason") or "").split())[:160]
    if word == "same":
        return Read("same", reason, model)
    if word in ("part", "different", "related"):
        return Read("two", reason, model)
    if word == "unsure":
        return Read("unsure", reason, model)
    return Read()


async def _read(memory_path: Path, pair: Pair, judge, *, skeptic: str = "") -> Read:
    try:
        raw = await judge(SYSTEM, await asyncio.to_thread(build_prompt, memory_path, pair, skeptic=skeptic))
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 — a read that failed has read nothing
        logger.debug(f"Alias collision read failed: {type(exc).__name__}")
        return Read()
    return _parse(raw)


async def assess(memory_path: Path, pair: Pair, judge) -> Plan:
    """Two reads, the second looking for the opposite reason. ``alias_apart`` needs both to say two things and the alias
    not to be what the person's own words call the page; ``ask`` needs both to say one; anything else is held."""
    from api.services import bank_index

    plan = Plan(pair, rule="read")
    first = await _read(memory_path, pair, judge)
    plan.reads = 1
    if first.verdict == "unread":
        plan.why = "unread"
        return plan
    if first.verdict == "unsure":
        plan.rule, plan.why = DOUBT, "unsure"
        return plan
    second = await _read(memory_path, pair, judge, skeptic=SKEPTIC_ONE if first.verdict == "same" else SKEPTIC_TWO)
    plan.reads = 2
    if second.verdict == "unread":
        plan.why = "unread"
        return plan
    if second.verdict != first.verdict:
        plan.rule, plan.why = DOUBT, "reads_disagree"
        return plan
    plan.reason = first.reason
    plan.model = first.model if first.model and first.model == second.model else None
    if first.verdict == "same":
        plan.rule, plan.why = "ask", "one_thing"
        return plan
    fms = {p: (bank_index.file(memory_path, "entities", f"{p}.md").frontmatter or {}) for p in (pair.a, pair.b)}
    plan.removals = await asyncio.to_thread(removable, memory_path, pair, fms)
    plan.rule, plan.why = (APART, "read_two_things") if plan.removals else (DOUBT, "called_by_own_words")
    return plan


# --------------------------------------------------------------------------- what was read, outside every bank


def _seen_file(memory_path: Path) -> Path:
    from api.services import auth, continuity_sessions

    return auth.cicada_home() / "alias_reads" / f"{continuity_sessions.bank_file_id(Path(memory_path))}.json"


def _seen(memory_path: Path) -> dict[str, str]:
    try:
        data = json.loads(_seen_file(memory_path).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(memory_path: Path, key: str, mark: str) -> None:
    """Ids and a hash only, never a name or a word."""
    try:
        data = _seen(memory_path)
        data[key] = mark
        path = _seen_file(memory_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def digest(memory_path: Path, pair: Pair) -> str:
    """What a read stood on: both pages, whether the record holds them as two things, and the aliases that make the pair."""
    h = hashlib.sha256()
    for rel in (f"entities/{pair.a}.md", f"entities/{pair.b}.md"):
        try:
            h.update((Path(memory_path) / rel).read_bytes())
        except OSError:
            h.update(b"-")
    h.update(b"two" if _two_things(Path(memory_path), pair.a, pair.b) else b"open")
    h.update(json.dumps(sorted(pair.listed.items())).encode())
    return h.hexdigest()[:24]


def owns(memory_path: Path, a: str, b: str) -> bool:
    """Is this pair the tending's to settle, so Stage 2 raises no lead question about it: a question of its own is open, one
    the person holds is open, or a read of it stood (held or asked) and nothing it read has changed since."""
    try:
        pair = Pair(*sorted((a, b)))
        if _seen(memory_path).get(pair.key, "#").find("#") < 0:   # a read that stood; an unread one is tried again
            return True
        from api.services import bank_index

        return (any(str((f.frontmatter or {}).get("detected") or "") == DETECTED
                    and {str(f.frontmatter.get("entity_id") or ""), str(f.frontmatter.get("merge_target_hint") or "")} == {a, b}
                    for f in bank_index.files(Path(memory_path), "inbox"))
                or person_holds(memory_path, pair, date.today().isoformat()))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- open questions about a pair


def _questions(memory_path: Path):
    """Every open "same as?" question about two live pages, ``(path, frontmatter, pair key)``, whoever asked it."""
    from api.services import inbox_tend

    for path, fm, _body in inbox_tend.pending(Path(memory_path)):
        if str(fm.get("kind") or "") != "merge_suggestion" or fm.get("same_title") or fm.get("heard_in"):
            continue
        ask = inbox_tend._page(Path(memory_path), str(fm.get("entity_id") or ""))
        target = inbox_tend._page(Path(memory_path), str(fm.get("merge_target_hint") or ""))
        if ask is not None and target is not None:
            yield path, fm, "|".join(sorted((ask[0].stem, target[0].stem)))


def _held(fm: dict, today: str) -> bool:
    """The person took this settle back or put the question off: it is theirs (`inbox_tend._blocked`, the guard every other
    tending rule uses)."""
    from api.services import inbox_tend

    return inbox_tend._blocked(fm, today) in ("undone", "deferred")


def held_pairs(memory_path: Path, today: str) -> set[str]:
    """The pair keys with a question the person took back or put off: one scan of the inbox."""
    return {key for _p, fm, key in _questions(memory_path) if _held(fm, today)}


def person_holds(memory_path: Path, pair: Pair, today: str) -> bool:
    return pair.key in held_pairs(memory_path, today)


def open_questions(memory_path: Path, pair: Pair, today: str | None = None) -> list[tuple[Path, dict]]:
    """The open "same as?" questions about exactly these two pages, whoever asked them and whichever way round, that Sleep
    may touch: never one the person took back or put off."""
    day = today or date.today().isoformat()
    return [(path, fm) for path, fm, key in _questions(memory_path) if key == pair.key and not _held(fm, day)]


# --------------------------------------------------------------------------- the writers


def _settle_sync(memory_path: Path, plan: Plan, today: str) -> bool:
    """One pair's settle as ONE Sleep commit: the aliases removed (``aliases_removed``, through the page edit writer), every
    open question about the pair closed, and the settle's record (``inbox/settled/<id>.md``, so the Inbox lists it and
    undoes it like any other). The caller holds Sleep's window. False when nothing was written."""
    from api.services import bank_index, git_service, page_edits, page_lock

    pair = plan.pair
    if plan.rule not in (APART, QUIET) or person_holds(memory_path, pair, today):
        return False   # a doubt closes nothing; a question the person holds is theirs
    questions = open_questions(memory_path, pair, today)
    with page_lock.page_lock(memory_path):
        if plan.rule == APART:
            for holder, alias in plan.removals:   # the pair must still be what it was read as
                fm = (bank_index.file(memory_path, "entities", f"{holder}.md") or None)
                if fm is None or alias not in (fm.frontmatter or {}).get("aliases", []):
                    return False
        if not plan.removals and not questions:
            return False
        edits = []
        for holder, alias in plan.removals:   # every edit is planned before any is written: all or none
            page = memory_path / "entities" / f"{holder}.md"
            parsed = page_edits.read(page)
            edits.append((holder, alias, page, page_edits.plan(
                parsed.frontmatter, parsed.body, page_edits.Request(remove_aliases=[alias]), author="cicada", day=today)))
        before = git_service.snapshot_dirty_sync(memory_path)
        paths: list[str] = []
        backups: dict[Path, bytes | None] = {}

        def backup(path: Path) -> None:
            if path not in backups:
                backups[path] = path.read_bytes() if path.is_file() else None

        try:
            return _write_settle(memory_path, plan, today, questions, edits, before, paths, backup)
        except Exception:
            for path, data in backups.items():   # a settle that fails halfway leaves the bank as it was
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
            bank_index.invalidate(memory_path)
            raise


def _write_settle(memory_path: Path, plan: Plan, today: str, questions, edits, before, paths: list[str], backup) -> bool:
    from api.services import bank_index, git_service, inbox_service, inbox_tend, markdown_parser, page_edits

    pair = plan.pair
    for holder, alias, page, outcome in edits:
        backup(page)
        page_edits.write(page, outcome)
        paths.append(f"entities/{holder}.md")
        # An open proposal that would remove the same alias is moot now.
        for rel in _moot_proposals(memory_path, holder, alias):
            backup(memory_path / rel)
            (memory_path / rel).unlink(missing_ok=True)
            paths.append(rel)
    if questions:
        item_id, qfm, qbody = questions[0][0].stem, dict(questions[0][1]), ""
        for path, _fm in questions:
            qbody = qbody or markdown_parser.parse(path).body
            rel = path.relative_to(memory_path).as_posix()
            backup(path)
            path.unlink()
            paths.append(rel)
    else:
        inbox = memory_path / "inbox"
        n = inbox_service.next_inbox_num(inbox)
        while (inbox / "settled" / f"inbox-{n:03d}.md").exists():
            n += 1
        item_id = f"inbox-{n:03d}"
        holder = plan.removals[0][0]
        other = pair.b if holder == pair.a else pair.a
        names = {p: str((bank_index.file(memory_path, "entities", f"{p}.md").frontmatter or {}).get("name") or p)
                 for p in (pair.a, pair.b)}
        qfm = {"kind": "merge_suggestion", "required_input": "merge", "status": "pending", "entity_id": holder,
               "entity_name": names[holder], "merge_target_hint": other, "created_date": today,
               "title": f"Is {names[holder]} the same as {names[other]}?", "detected": DETECTED}
        qbody = ""
    names = {p: str((bank_index.file(memory_path, "entities", f"{p}.md").frontmatter or {}).get("name") or p)
             for p in (pair.a, pair.b)}
    answer = (f"Removed {', '.join('“' + a + '”' for _h, a in plan.removals)} from "
              f"{' and '.join(sorted({names[h] for h, _a in plan.removals}))}" if plan.removals else
              "Not a question: nothing was changed")
    d = inbox_tend.Decision(item_id, "merge_suggestion", plan.rule, None, answer=answer, reason=plan.reason)
    rec = inbox_tend._record(qfm, d, plan.model or "cicada", None)
    if plan.removals:
        rec["alias_apart"] = [{"page": h, "alias": a} for h, a in plan.removals]
    record_rel = f"inbox/{inbox_tend.SETTLED_DIR}/{item_id}.md"
    (memory_path / record_rel).parent.mkdir(parents=True, exist_ok=True)
    backup(memory_path / record_rel)
    markdown_parser.write(memory_path / record_rel, {**qfm, "settled": rec}, qbody)
    paths.append(record_rel)
    bank_index.invalidate(memory_path)
    lines = [f"{rel}: updated (source: {item_id}, trigger: {inbox_tend.TRIGGER}:{plan.rule})"
             for rel in dict.fromkeys(paths)]
    message = git_service.build_commit_message(f"Inbox settled by Sleep (merge_suggestion) {today}", lines,
                                               authors=[plan.model] if plan.model else ["cicada"])
    git_service.commit_touched_sync(memory_path, message, list(dict.fromkeys(paths)), before=before,
                                    kept_subject=f"Uncommitted edit kept apart {today}",
                                    kept_trigger="inbox/kept-apart")
    return True


def _moot_proposals(memory_path: Path, holder: str, alias: str) -> list[str]:
    from api.services import markdown_parser

    out = []
    inbox = Path(memory_path) / "inbox"
    for path in sorted(inbox.glob("inbox-*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            if "page_edit" not in text or holder not in text:
                continue
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001
            continue
        edit = fm.get("edit") if isinstance(fm.get("edit"), dict) else {}
        if (fm.get("kind") == "page_edit" and fm.get("origin") == wrong_aliases.ORIGIN
                and str(fm.get("entity_id") or "") == holder and len(edit.get("remove_aliases") or []) == 1
                and str(edit["remove_aliases"][0]) == alias and not (edit.get("add_aliases") or edit.get("edits"))):
            out.append(path.relative_to(memory_path).as_posix())
    return out


def ask_sync(memory_path: Path, pair: Pair, today: str) -> str | None:
    """The ONE question for a pair read as one thing under two names (``alias_collision``, ``fold_page``): an open "same
    as?" about the pair is rewritten into it, else it is written new; committed as Cicada's own file. ``None`` when a
    question of this kind is already open or nothing needed writing."""
    from api.services import (bank_index, git_service, inbox_service, markdown_parser, page_lock, page_use)

    if person_holds(memory_path, pair, today):
        return None   # the person took one back or put it off: never a second question beside it
    questions = open_questions(memory_path, pair, today)
    if any(str(fm.get("detected") or "") == DETECTED for _p, fm in questions):
        return None
    fa = bank_index.file(memory_path, "entities", f"{pair.a}.md")
    fb = bank_index.file(memory_path, "entities", f"{pair.b}.md")
    if fa is None or fb is None:
        return None
    use = page_use.scores(memory_path, today=date.fromisoformat(today))
    asked, target = (pair.a, pair.b) if use.get(pair.a, 0.0) <= use.get(pair.b, 0.0) else (pair.b, pair.a)
    names = {pair.a: str((fa.frontmatter or {}).get("name") or pair.a), pair.b: str((fb.frontmatter or {}).get("name") or pair.b)}
    fields = {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.5,
        "entity_id": asked, "entity_name": names[asked], "merge_target_hint": target, "fold_page": True,
        "detected": DETECTED, "title": f"Are {names[asked]} and {names[target]} one thing under two names?",
        "uncertainty_type": f"Possible duplicate of {names[target]}", "suggested_confidence": 0.6,
        "suggested_classification": f"{(fa.frontmatter or {}).get('type') or 'concept'} — could be the same thing as {names[target]}",
    }
    body = ("Why this is asked: each page goes by the other's name, and everything both pages say fits one thing under two "
            "names. Asked, never joined: only your answer joins them.")
    with page_lock.page_lock(memory_path):
        before = git_service.snapshot_dirty_sync(memory_path)
        if questions:
            path = questions[0][0]
            parsed = markdown_parser.parse(path)
            markdown_parser.write(path, {**parsed.frontmatter, **fields}, body)
        else:
            inbox = Path(memory_path) / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            path = inbox / f"inbox-{inbox_service.next_inbox_num(inbox):03d}.md"
            markdown_parser.write(path, {**fields, "created_date": today}, body)
        paths = [path.relative_to(memory_path).as_posix()]
        for extra, _fm in questions[1:]:   # one question per pair: a second one asked of the same two is closed
            extra.unlink(missing_ok=True)
            paths.append(extra.relative_to(memory_path).as_posix())
        bank_index.invalidate(memory_path)
        message = git_service.build_commit_message(
            f"Alias collision asked {today}", [f"{p}: updated (source: n/a, trigger: sleep/alias-collision)" for p in paths],
            authors=["cicada"])
        git_service.commit_touched_sync(memory_path, message, paths, before=before,
                                        kept_subject=f"Uncommitted edit kept apart {today}", kept_trigger="inbox/kept-apart")
    return paths[0]


# --------------------------------------------------------------------------- the tail step


def _hold(memory_path: Path, pair: Pair, mark: str, report: Report) -> None:
    """A doubt: remembered (so the pair is not read again until a page it read changes) and nothing else. No open question
    is closed or rewritten: Sleep settles only on the person's own words or a small-stuff rule (ruling 29)."""
    _remember(memory_path, pair.key, mark)
    report.held += 1


async def tend(memory_path: Path, settings, judge, *, today: date | None = None, max_reads: int = MAX_READS,
               no_model: bool = False) -> Report:
    """Settle what the record already says, then read up to ``max_reads`` pairs. The judge runs outside any write; each
    settle is one commit (Sleep's window is held by the caller). Never raises but for an engine failure."""
    memory_path = Path(memory_path)
    day = (today or date.today()).isoformat()
    report = Report()
    seen = _seen(memory_path)
    found = [p for p in await asyncio.to_thread(pairs, memory_path)]
    held = await asyncio.to_thread(held_pairs, memory_path, day)
    free = 0
    for pair in found:
        if pair.skip:
            report.skip(pair.skip)
            continue
        if pair.key in held:   # the person took a settle back or put the question off: it is theirs until they answer
            report.skip("person_holds")
            continue
        plan = await asyncio.to_thread(triage, memory_path, pair)
        mark = await asyncio.to_thread(digest, memory_path, pair)
        before = seen.get(pair.key, "")
        tries = int(before.split("#", 1)[1]) if before.startswith(mark + "#") else 0
        if plan.rule == "read":
            if before == mark or tries >= MAX_UNREAD_TRIES:
                report.skip("read_already")
                continue
            if no_model or judge is None or report.looked >= max_reads:
                report.skip("no_model" if (no_model or judge is None) else "max_reads")
                continue
            report.looked += 1
            plan = await assess(memory_path, pair, judge)
            report.reads += plan.reads
            if plan.rule == "read":   # unread
                _remember(memory_path, pair.key, f"{mark}#{tries + 1}")
                report.skip("unread")
                continue
            if plan.rule == DOUBT:   # a model that could not tell settles nothing: remember the read, change nothing
                _hold(memory_path, pair, mark, report)
                continue
        elif plan.rule in (APART, QUIET, DOUBT):
            if plan.rule == DOUBT:
                if before != mark:
                    _hold(memory_path, pair, mark, report)
                continue
            if free >= MAX_FREE:
                report.skip("max_free")
                continue
            free += 1
        else:
            report.skip(plan.why or "none")
            continue
        try:
            if plan.rule == "ask":
                if await asyncio.to_thread(ask_sync, memory_path, pair, day):
                    report.asked += 1
                _remember(memory_path, pair.key, mark)
                continue
            ok = await asyncio.to_thread(_settle_sync, memory_path, plan, day)
        except Exception as exc:  # noqa: BLE001 — one pair that will not settle never stops the others
            logger.info(f"Alias collision not settled: {type(exc).__name__}")
            ok = False
        _remember(memory_path, pair.key, mark)
        if plan.rule == APART:
            report.removed += 1 if ok else 0
            if not ok:
                report.skip("not_applied")
        elif plan.rule == QUIET:
            report.quiet += 1
    return report


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, judge=None, today: date | None = None) -> Report:
    """Sleep's tail step, after the typo join. No engine is resolved unless a pair needs a read; a scheduled run reaches a
    plan only through the person's switch (ruling 4), a plan limit is a pause, no engine means no read (the engine-free
    settles still run). Never raises."""
    from api.services import full_name_join, same_name_tend

    memory_path = Path(memory_path)
    report = Report()
    try:
        found = await asyncio.to_thread(pairs, memory_path)
        if not any(not p.skip for p in found):
            return report
        no_model = False
        if judge is None:
            strong, why = await same_name_tend.main_engine(settings, user_triggered=user_triggered)
            if strong is None:
                report.skip(why)
                no_model = True
            else:
                async def judge(system: str, prompt: str) -> object:
                    return await full_name_join.ask_main(strong, system, prompt)
        return await tend(memory_path, settings, judge, today=today, no_model=no_model)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")
    except Exception as exc:  # noqa: BLE001 — the tending never fails a Sleep
        logger.warning(f"Alias collisions stopped: {type(exc).__name__}")
        report.skip("error")
    return report
