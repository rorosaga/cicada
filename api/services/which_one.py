"""Were you talking about A or B? — one question for a mention that could be several known pages (ruling 83, owner 2026-11-25).

The owner, after two people who share a first name and a nickname were asked as "Is <Full Name> the same as <First>?":
"if its not implied in the context then a better question is 'where you talking about your brother or <Full Name>?' like a
human would. Make sure this is the behaviour we achieve for everything in cicada."

Three halves, one module (`same_name_pick` keeps the answering: the keys, the verbs and the "Another one"):

* **What a mention could be** (:func:`answering`): every live page a name answers to — its title, an alias or nickname,
  or, for a person, a short name inside a full name ("<First>" in "<First> <Surname>"). Read from the headers only.
* **The one door every lane calls** (:func:`raise_question`): a lane that ends at "could be A or B" — Stage 2's judge, the
  second look, an agent working the open questions — hands over the mention, its conversation and the candidate ids and
  gets ONE question of the pick form (`same_name_pick`), never one pairwise question per candidate. It refuses a pair the
  person already refused, a mention they already said is another one, and a mention already asked about.
* **Sleep's tending** (:func:`tend`): a pairwise "is <mention> the same as <page>?" about a held mention (no page yet, or a
  page titled by a nickname) that has two or more candidates is rewritten, in place, into that one question; the other
  pairwise files of the mention are folded into it and removed. Every candidate they named stays on the question
  (ruling 73: no value lost), nothing is asked beside it, and a question the person took back or put off is theirs.
  Engine-free.

The words are `inbox_wording`'s, at read; nothing here stores wording. The answer is the existing verbs: a picked page is
``merge`` (the held mention folded into it, G209); "Someone else" keeps the mention apart from every candidate
(`pending_store.mark_apart`, scoped to the mention and every conversation the question came from, never a name→page
rejection) whoever raised the question. **A pick is that mention's answer and nothing more:** what was held lands on the picked
page, but the name is neither made its alias nor left as its "the person said so" note, which Stage 2 reads as the person's
word and uses to join every later mention with no look at its own conversation (`entity_resolver._answered_match`); a later
mention is decided by its own context and asked again only if that does not decide either.

Folding keeps everything: the survivor takes every candidate, every conversation (``source_episodes``, :func:`episodes_of`) and
every distinct body of the questions folded into it, and each folded file is closed as Sleep closes any question — moved whole
to ``inbox/settled/<id>.md`` (rule :data:`RULE`), so the Inbox lists it and Sleep's undo reopens it. The report remembers the
bytes read before each write (:func:`restore`), so a failed commit puts every question back as it was. Pure apart from the page
reads it is handed; never raises into Sleep.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, markdown_parser, same_name

TRIGGER = "sleep/which-one"
DETECTED = "which_one"
#: The most pages one question names (`clarification_manager` keeps six on a question).
MAX_CANDIDATES = 6
_DEAD = frozenset({"dropped", "archived"})
#: The relation a person page holds to the owner, said as the person says it ("your brother").
ROLES_KEY = "owner_roles"
#: A first or last word of a full name matches a mention only from this many letters ("Al", "J" are no one's short name).
MIN_SHORT_NAME = 3
#: A short name — a mention that is the first or last word of a full name — adds a page the question did not name only
#: while at most this many live pages answer to it: three buttons still read as one sentence ("A, B or C") on the card. A
#: name more people share is a common name, and a common name alone says nothing about which of them was meant.
MAX_SHORT_NAME = 3
#: The same, when the question or the held line already points at a page of that name: then the name is demonstrably a
#: short name of that page, and its namesakes are real alternatives the question had not listed. Capped at the five the
#: card is built and tested to show (`test_question_inventory`), never the six a question may hold.
MAX_SHORT_NAME_POINTED = 5


def _live(fm: dict) -> bool:
    return str((fm or {}).get("status") or "") not in _DEAD and str((fm or {}).get("type") or "") != "media"


def _is_person(fm: dict) -> bool:
    return str((fm or {}).get("type") or "").lower() == "person"


def _tokens(name) -> list[str]:
    return same_name.fold(name).split()


def is_owner(fm: dict) -> bool:
    """The person's own page: never a candidate (it is who is asking, not someone they could have meant)."""
    return bool((fm or {}).get("owner"))


def answering(memory_path, mention: str, *, exclude: frozenset[str] | set[str] = frozenset(),
              pointed: frozenset[str] | set[str] | list[str] = frozenset()) -> list[str]:
    """The ids of the live pages ``mention`` could be: titled by it, listing it as another name, or — for a person and a
    one-word mention of at least :data:`MIN_SHORT_NAME` letters — carrying it as the first or last word of a full name.
    The owner's own page is never one. A short-name match adds a page only while at most :data:`MAX_SHORT_NAME` pages
    answer to the name, or :data:`MAX_SHORT_NAME_POINTED` when ``pointed`` (the pages the question or the held line already
    names) holds one of them; past that the short-name pages are left out and the question keeps the candidates it had. A
    thing is never matched to a person by a word they share. Stable order, at most :data:`MAX_CANDIDATES`; empty for a
    mention that is not a name. Headers only, no model."""
    key = same_name.fold(mention)
    if not key:
        return []
    short_ok = " " not in key and len(key) >= MIN_SHORT_NAME
    hits: list[tuple[str, bool]] = []   # (page id, found only as a short name)
    for entry in bank_index.files(Path(memory_path), "entities"):
        fm = entry.frontmatter or {}
        if entry.stem in exclude or not _live(fm) or is_owner(fm):
            continue
        names = [fm.get("name") or entry.stem.replace("-", " "), *(a for a in (fm.get("aliases") or [])
                                                                    if isinstance(a, str))]
        if key in {same_name.fold(n) for n in names}:
            hits.append((entry.stem, False))
        elif short_ok and _is_person(fm):
            words = _tokens(fm.get("name") or "")
            if len(words) >= 2 and key in (words[0], words[-1]):
                hits.append((entry.stem, True))
    if any(short for _stem, short in hits):
        points = set(pointed) & {stem for stem, _short in hits}
        if len(hits) > (MAX_SHORT_NAME_POINTED if points else MAX_SHORT_NAME):
            hits = [(stem, short) for stem, short in hits if not short]
    return [stem for stem, _short in hits][:MAX_CANDIDATES]


def roles_of(fm: dict) -> list[str]:
    raw = (fm or {}).get(ROLES_KEY)
    return [str(r).strip().lower() for r in raw if str(r).strip()] if isinstance(raw, list) else []


def labels(pages: list[dict]) -> list[str]:
    """The answer buttons for ``pages`` (``{id, name, type, roles, qualifier}`` each), as the person refers to them: a
    relation to the owner ("Your brother") — but only when it is unique among these pages (two brothers are not told apart
    by "your brother") — else the name, said with its qualifier only when the name alone would not tell it from another
    (`same_name`). Two choices never show the same words: a pair that still reads alike is told apart by the qualifier
    `same_name_pick` derives, else the page's type word, else its id."""
    rows = []
    for page in pages:
        person = str(page.get("type") or "").lower() == "person"
        roles = roles_of({ROLES_KEY: page.get("roles")}) if person else []
        rows.append((" ".join(str(page.get("name") or page.get("id") or "").split()), roles[0] if roles else None,
                     page.get("qualifier") or None, str(page.get("type") or "").strip().lower(), str(page.get("id") or "")))
    taken = Counter(role for _n, role, _q, _t, _i in rows if role)
    out = [f"Your {role}" if role and taken[role] == 1 else same_name.display(name, qualifier)
           for name, role, qualifier, _t, _i in rows]
    for step in (lambda r: r[2] or same_name.TYPE_WORDS.get(r[3]), lambda r: r[4]):
        seen = Counter(same_name.fold(o) for o in out)
        out = [same_name.display(r[0], step(r)) if seen[same_name.fold(o)] > 1 and step(r) else o
               for r, o in zip(rows, out)]
    return out


def label(page_id: str, fm: dict, qualifier: str | None = None) -> str:
    """One page as the person refers to it (:func:`labels` over a single page)."""
    return labels([{"id": page_id, "name": (fm or {}).get("name"), "type": (fm or {}).get("type"),
                    "roles": roles_of(fm), "qualifier": qualifier}])[0]


def phrase(option: dict) -> str:
    """An option as it reads inside the question: "your brother", "<Full Name>", "the <name> IDE"."""
    text = " ".join(str(option.get("label") or "").split())
    if text.startswith("Your "):
        return "y" + text[1:]
    qualifier = str(option.get("qualifier") or "").strip()
    name = " ".join(str(option.get("page_name") or "").split())
    if qualifier and name and "," in qualifier:
        return same_name.display(name, qualifier)   # "Alex (person, Sep 2026)": a qualifier that is no one word
    if qualifier and name:
        from api.services import inbox_wording

        return inbox_wording.thing_phrase(name, qualifier)
    return text


def _or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


MAX_QUESTION = 160


def ask(mention: str, options: list[dict]) -> str:
    """"Were you talking about your brother or <Full Name>?" — the question a person would ask about a mention, built
    from the answers the question offers (a page option's ``label``, ``page_name`` and ``qualifier``). Too long for the
    card with many candidates: "Which one did you mean by <mention>?" (the answers are the buttons)."""
    pages = [o for o in options if str(o.get("key") or "").startswith("page:")]
    said = [phrase(o) for o in pages]
    question = f"Were you talking about {_or(said)}?" if said else ""
    if not question or len(question) > MAX_QUESTION:
        name = " ".join(str(mention or "").split()) or "this"
        question = f"Which one did you mean by {name}?"
    return question


def where_of(memory_path, fm: dict) -> str | None:
    """The title of the conversation a name's question came from, from the record, for the words "Who or what is <name>,
    from “<title>”?" (a clarification only; None when the conversation has no title). No model."""
    episode = str((fm or {}).get("source_episode") or "").strip()
    if str((fm or {}).get("kind") or "") != "clarification" or not episode:
        return None
    entry = bank_index.file(Path(memory_path), "episodes", f"{episode}.md")
    title = " ".join(str(((entry.frontmatter if entry is not None else {}) or {}).get("title") or "").split())
    return title or None


# --------------------------------------------------------------------------- raising (the one door)

def _inbox(memory_path) -> Path:
    path = Path(memory_path) / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _open_for(memory_path, mention_id: str) -> Path | None:
    from api.services import inbox_tend

    for path, fm, _body in inbox_tend.pending(Path(memory_path)):
        if (str(fm.get("kind") or "") == "merge_suggestion" and str(fm.get("status") or "pending") == "pending"
                and str(fm.get("entity_id") or "") == mention_id):
            return path
    return None


def usable(memory_path, mention: str, candidates: list[str]) -> list[str]:
    """The candidates a question may still offer: live, never the owner's own page, not refused for this mention, and
    not already said to be "another one" for it."""
    from api.services import merge_rejections, pending_store
    from api.services.id_utils import sanitize_id

    mention_id = sanitize_id(mention)
    apart = pending_store.apart_of(Path(memory_path), mention)
    out: list[str] = []
    for pid in dict.fromkeys(str(c) for c in candidates if str(c).strip()):
        entry = bank_index.file(Path(memory_path), "entities", f"{pid}.md")
        if (entry is None or not _live(entry.frontmatter or {}) or is_owner(entry.frontmatter or {})
                or pid == mention_id or pid in apart):
            continue
        if merge_rejections.is_rejected(Path(memory_path), mention_id, pid):
            continue
        out.append(pid)
    return out[:MAX_CANDIDATES]


def candidates_for(memory_path, mention: str, pointed: list[str] | None = None) -> list[str]:
    """The pages ``mention`` could be and a question may still offer (:func:`answering` then :func:`usable`), the ones the
    caller already points at first. ``[]`` unless two or more are left: below that the question is a pairwise one."""
    from api.services.id_utils import sanitize_id

    mention_id = sanitize_id(mention)
    named = [str(p) for p in (pointed or []) if str(p).strip()]
    found = answering(Path(memory_path), mention, exclude={mention_id}, pointed=set(named))
    ids = usable(memory_path, mention, [*named, *found])
    return ids if len(ids) >= 2 else []


def fields(memory_path, mention: str, ids: list[str]) -> dict:
    """What makes a ``merge_suggestion`` this question (ruling 83): the candidates, the words, the marker. One shape for the
    one door (:func:`raise_question`) and for a lane whose own writer creates the question (`ClarificationManager.create`,
    Stage 2), so no lane writes a pairwise question about a mention that could be several pages."""
    names = [" ".join(str((bank_index.file(Path(memory_path), "entities", f"{p}.md").frontmatter or {}).get("name") or p).split())
             for p in ids]
    said = f"Were you talking about {_or(names)}?"
    return {"title": said if len(said) <= MAX_QUESTION else f"Which one did you mean by {mention}?",
            "uncertainty_type": f"Possible duplicate of {names[0]}", "merge_target_hint": ids[0],
            "same_title": list(ids), "detected": DETECTED}


def open_question(memory_path, mention: str) -> Path | None:
    """The open question about ``mention``, if any (one per mention, whoever raised it)."""
    from api.services.id_utils import sanitize_id

    return _open_for(Path(memory_path), sanitize_id(mention))


def raise_question(memory_path, mention: str, source_episode: str, candidates: list[str] | None = None, *,
                   source_context: str = "", source_episode_timestamp: str | None = None,
                   today: date | None = None) -> str | None:
    """File ONE "were you talking about A or B?" question for ``mention`` said in ``source_episode`` and return its
    inbox path (``inbox/inbox-NNN.md``), or ``None`` when nothing is asked: fewer than two candidates are left after
    refusals, or a question about the mention is already open (the one that is open is the question). ``candidates``
    None means every page the mention answers to (:func:`answering`). A file write only: no model, no network; the
    caller commits it. The pick, "Another one" and the held mention's fate are `same_name_pick`'s."""
    from api.services import inbox_service
    from api.services.id_utils import sanitize_id

    memory_path = Path(memory_path)
    mention = " ".join(str(mention or "").split())
    if not mention:
        return None
    mention_id = sanitize_id(mention)
    ids = usable(memory_path, mention, list(candidates) if candidates is not None
                 else answering(memory_path, mention, exclude={mention_id}))
    if len(ids) < 2 or _open_for(memory_path, mention_id) is not None:
        return None
    day = (today or date.today()).isoformat()
    inbox = _inbox(memory_path)
    path = inbox / f"inbox-{inbox_service.next_inbox_num(inbox):03d}.md"
    frontmatter = {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.5,
        "entity_id": mention_id, "entity_name": mention, "suggested_classification": "",
        "suggested_confidence": 0.5, "created_date": day, "source_episode": str(source_episode or ""),
        **fields(memory_path, mention, ids),
    }
    if source_episode_timestamp:
        frontmatter["source_episode_timestamp"] = str(source_episode_timestamp)
    markdown_parser.write(path, frontmatter, (source_context or "").strip()
                          or "Why this is asked: the name could be any of these, and nothing in the conversation says which.")
    bank_index.invalidate(memory_path)
    return f"inbox/{path.name}"


# --------------------------------------------------------------------------- Sleep's tending

#: The rule a folded question's settled record carries (`inbox_tend.RULES`): Sleep closed it because its candidates are on
#: the one question, and the person may take that back like any other settle.
RULE = "which_one_folded"


def episodes_of(fm: dict) -> list[str]:
    """Every conversation a which-one question came from: the one that raised it, then the ones folded questions came
    from (``source_episodes``). One reading for everything that uses the question's conversations: the evidence shown,
    "Someone else" keeping the mention apart, the page a pick joins the mention to."""
    out: list[str] = []
    for value in [(fm or {}).get("source_episode"), *((fm or {}).get("source_episodes") or [])]:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def about_mention(fm: dict) -> bool:
    """The question is about a mention (a name said in a conversation), never about a page: Stage 2's held mention, or a
    question this module raised or rewrote."""
    return (fm or {}).get("held_mention") is True or str((fm or {}).get("detected") or "") == DETECTED


@dataclass
class Report:
    written: list[str] = field(default_factory=list)
    rewritten: int = 0
    folded: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    #: ``{memory-relative path: the bytes it held before this run touched it}`` (``None``: it did not exist): what
    #: :func:`restore` puts back when the run's commit fails. Unlike a step that only writes new files, this one rewrites a
    #: tracked question and moves others, so undoing means writing back what was read, never only unlinking.
    before: dict[str, bytes | None] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def remember(self, memory_path: Path, rel: str) -> None:
        if rel not in self.before:
            path = Path(memory_path) / rel
            self.before[rel] = path.read_bytes() if path.is_file() else None


def restore(memory_path, report: Report, rels: list[str] | None = None) -> None:
    """Put every file the run touched (or just ``rels``) back as it was: the rewritten question and the ones folded into
    it as the bytes read before, a settled record that did not exist as gone. Never raises."""
    memory_path = Path(memory_path)
    for rel, data in report.before.items():
        if rels is not None and rel not in rels:
            continue
        path = memory_path / rel
        try:
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        except OSError as exc:
            logger.warning(f"which-one restore skipped {rel}: {type(exc).__name__}")
    bank_index.invalidate(memory_path)


def _mention_like(memory_path: Path, fm: dict) -> bool:
    """The question's subject is a name, not a page the person has: no page of that id yet (a held mention, G209) or a
    page titled by a nickname — or the question Stage 2 marked as one about a mention it held (``held_mention``), or one
    of this module's own."""
    from api.services import role_people
    from api.services.id_utils import resolve_entity_file

    if about_mention(fm):
        return True
    path = resolve_entity_file(memory_path, str(fm.get("entity_id") or ""))
    if path is None:
        return True
    entry = bank_index.file(memory_path, "entities", path.name)
    return entry is not None and bool((entry.frontmatter or {}).get(role_people.NICKNAME_KEY))


def _name_of(memory_path: Path, pid: str) -> str:
    entry = bank_index.file(memory_path, "entities", f"{pid}.md")
    return " ".join(str(((entry.frontmatter if entry is not None else {}) or {}).get("name") or pid).split())


def _carried(survivor: dict, body: str, folded: list[tuple[Path, dict, str]]) -> tuple[dict, str]:
    """What the survivor takes from the questions folded into it: every conversation they came from (``source_episodes``),
    the first reason and timestamp it lacks, ``held_mention`` when any was, and each distinct body — so what a folded
    question stored is on the one question as well as in its settled record (ruling 73)."""
    out = dict(survivor)
    episodes = episodes_of(survivor)
    bodies = [body.strip()] if body.strip() else []
    for _path, fm, text in folded:
        episodes += [e for e in episodes_of(fm) if e not in episodes]
        for key in ("why_asked", "source_episode_timestamp"):
            if fm.get(key) and not out.get(key):
                out[key] = fm[key]
        if fm.get("held_mention") is True:
            out["held_mention"] = True
        if text.strip() and text.strip() not in bodies:
            bodies.append(text.strip())
    if len(episodes) > 1:
        out["source_episodes"] = episodes
    if episodes and not out.get("source_episode"):
        out["source_episode"] = episodes[0]
    return out, "\n\n".join(bodies)


def _retire(memory_path: Path, report: Report, path: Path, fm: dict, body: str, into: str) -> bool:
    """Close a folded question the way Sleep closes any other: moved, whole, to its settled record
    (``inbox/settled/<id>.md``, `inbox_tend.RULES`) so the Inbox lists it and the person can take it back. False (nothing
    written) when a settled record of that number already waits for its undo."""
    from api.services import inbox_tend, markdown_parser

    record_rel = f"inbox/{inbox_tend.SETTLED_DIR}/{path.stem}.md"
    if (memory_path / record_rel).exists():
        return False
    decision = inbox_tend.Decision(path.stem, "merge_suggestion", RULE, None, answer=f"Asked once, in {into}")
    report.remember(memory_path, record_rel)
    report.remember(memory_path, f"inbox/{path.name}")
    (memory_path / record_rel).parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(memory_path / record_rel, {**fm, "settled": inbox_tend._record(fm, decision, "cicada", None)}, body)
    path.unlink()
    report.written += [f"inbox/{path.name}", record_rel]
    return True


def tend(memory_path, today: date | None = None, *, skip: frozenset[str] = frozenset()) -> Report:
    """Rewrite every pairwise "is <mention> the same as <page>?" whose mention could be two or more pages into the one
    question (see the module). One question per mention is kept — the one already in the which-one form, else the oldest —
    and the rest of that mention's pairwise files are folded into it: their candidates and conversations carried onto it,
    each closed through its settled record (:func:`_retire`). A later pairwise question about a mention that already has the
    one is folded into it, never a second. Untouched: a question with another ``detected`` marker (a page pair another rule
    asked), one that names where each side was heard, one the person took back or put off, a file the caller marks dirty
    (``skip``). Every file it touches is remembered in the report for :func:`restore`."""
    from api.services import inbox_tend, markdown_parser, pending_store
    from api.services.id_utils import sanitize_id

    memory_path = Path(memory_path)
    report = Report()
    day = (today or date.today()).isoformat()
    groups: dict[str, list[tuple[Path, dict, str]]] = {}
    theirs: set[str] = set()   # a mention one of whose questions the person took back or put off: all of it is theirs
    for path, fm, body in inbox_tend.pending(memory_path):
        if str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("status") or "pending") != "pending":
            continue
        rel = f"inbox/{path.name}"
        entity_id = sanitize_id(str(fm.get("entity_id") or ""))
        ours = str(fm.get("detected") or "") == DETECTED
        if inbox_tend._blocked(fm, day) or (ours and rel in skip):
            theirs.add(entity_id)   # ... or one this run may not touch: no second question is made beside it
            continue
        if (fm.get("detected") and not ours) or fm.get("heard_in") or fm.get("fold_page") or rel in skip:
            continue
        if entity_id and _mention_like(memory_path, fm):
            groups.setdefault(entity_id, []).append((path, fm, body))
    for entity_id, items in groups.items():
        if entity_id in theirs:
            report.skip("the_persons")
            continue
        items.sort(key=lambda item: str(item[1].get("detected") or "") != DETECTED)   # the one already asked first (stable)
        first_path, first, body = items[0]
        mention = str(first.get("entity_name") or entity_id)
        named = [str(fm.get("merge_target_hint") or "") for _p, fm, _b in items]
        stored = [pid for _p, fm, _b in items for pid in (fm.get("same_title") or []) if isinstance(pid, str)]
        pointed = {*named, *stored, pending_store.held_against(memory_path, mention)}
        wanted = usable(memory_path, mention, [*stored, *named, *answering(memory_path, mention, exclude={entity_id},
                                                                          pointed=pointed)])
        if len(wanted) < 2:
            report.skip("one_candidate")
            continue
        if len(items) == 1 and list(first.get("same_title") or []) == wanted:
            continue   # already the question
        folding = []
        for item in items[1:]:
            if (memory_path / "inbox" / inbox_tend.SETTLED_DIR / f"{item[0].stem}.md").exists():
                report.skip("record_waits")   # a settled question of this number waits for its undo: left alone
            else:
                folding.append(item)
        rewritten, merged_body = _carried(first, body, folding)
        names = [_name_of(memory_path, p) for p in wanted]
        rewritten = {**rewritten, "same_title": wanted, "merge_target_hint": wanted[0], "detected": DETECTED,
                     "uncertainty_type": f"Possible duplicate of {names[0]}",
                     "title": (f"Were you talking about {_or(names)}?"
                               if len(f"Were you talking about {_or(names)}?") <= MAX_QUESTION
                               else f"Which one did you mean by {mention}?"), "updated_date": day}
        first_rel = f"inbox/{first_path.name}"
        touched, folded_here, mark = [first_rel], 0, len(report.written)
        try:
            report.remember(memory_path, first_rel)
            for path, fm, text in folding:
                touched += [f"inbox/{path.name}", f"inbox/{inbox_tend.SETTLED_DIR}/{path.stem}.md"]
                if _retire(memory_path, report, path, fm, text, first_path.stem):
                    folded_here += 1
            markdown_parser.write(first_path, rewritten, merged_body)
        except Exception as exc:  # noqa: BLE001 — a group that will not write is put back; the others go on
            logger.warning(f"which-one rewrite failed: {type(exc).__name__}")
            restore(memory_path, report, touched)
            del report.written[mark:]
            continue
        report.written.insert(mark, first_rel)
        report.rewritten += 1
        report.folded += folded_here
    if report.written:
        bank_index.invalidate(memory_path)
    return report


def commit_message(report: Report, today) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Which-one questions {today.isoformat()}",
        [f"{p}: updated (source: n/a, trigger: {TRIGGER})" for p in dict.fromkeys(report.written)], authors=["cicada"])
