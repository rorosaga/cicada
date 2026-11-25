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
(`pending_store.mark_apart`, scoped to the mention, never a name→page rejection). **A nickname both candidates answer to
stays usable for both with no alias written to either:** after a pick the name is listed by the picked page (a merge
lists it, as always) and the other keeps what it already listed; a name two or more person pages list is never a direct
join (`entity_resolver._shared_name`) — a later mention goes to its own conversation and is asked again only if that
does not decide either. Pure apart from the page reads it is handed; never raises into Sleep.
"""
from __future__ import annotations

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


def _live(fm: dict) -> bool:
    return str((fm or {}).get("status") or "") not in _DEAD and str((fm or {}).get("type") or "") != "media"


def _is_person(fm: dict) -> bool:
    return str((fm or {}).get("type") or "").lower() == "person"


def _tokens(name) -> list[str]:
    return same_name.fold(name).split()


def answering(memory_path, mention: str, *, exclude: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """The ids of the live pages ``mention`` could be: titled by it, listing it as another name, or — for a person and a
    one-word mention — carrying it as the first or last word of a full name. Stable order, at most
    :data:`MAX_CANDIDATES`; empty for a mention that is not a name. Headers only, no model."""
    key = same_name.fold(mention)
    if not key:
        return []
    single = " " not in key
    found: list[str] = []
    for entry in bank_index.files(Path(memory_path), "entities"):
        fm = entry.frontmatter or {}
        if entry.stem in exclude or not _live(fm):
            continue
        names = [fm.get("name") or entry.stem.replace("-", " "), *(a for a in (fm.get("aliases") or [])
                                                                    if isinstance(a, str))]
        folded = {same_name.fold(n) for n in names}
        hit = key in folded
        if not hit and single and _is_person(fm):
            words = _tokens(fm.get("name") or "")
            hit = len(words) >= 2 and key in (words[0], words[-1])
        if hit:
            found.append(entry.stem)
    return found[:MAX_CANDIDATES]


def roles_of(fm: dict) -> list[str]:
    raw = (fm or {}).get(ROLES_KEY)
    return [str(r).strip().lower() for r in raw if str(r).strip()] if isinstance(raw, list) else []


def label(page_id: str, fm: dict, qualifier: str | None = None) -> str:
    """One page as the person refers to it, for an answer button: a relation to the owner ("Your brother"), else the
    name, said with its qualifier only when the name alone would not tell it from another (`same_name`)."""
    name = " ".join(str((fm or {}).get("name") or page_id).split())
    roles = roles_of(fm) if _is_person(fm) else []
    if roles:
        return f"Your {roles[0]}"
    return same_name.display(name, qualifier)


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
    """The candidates a question may still offer: live, not refused for this mention, and not already said to be
    "another one" for it."""
    from api.services import merge_rejections, pending_store
    from api.services.id_utils import sanitize_id

    mention_id = sanitize_id(mention)
    apart = pending_store.apart_of(Path(memory_path), mention)
    out: list[str] = []
    for pid in dict.fromkeys(str(c) for c in candidates if str(c).strip()):
        entry = bank_index.file(Path(memory_path), "entities", f"{pid}.md")
        if entry is None or not _live(entry.frontmatter or {}) or pid == mention_id or pid in apart:
            continue
        if merge_rejections.is_rejected(Path(memory_path), mention_id, pid):
            continue
        out.append(pid)
    return out[:MAX_CANDIDATES]


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
    names = [" ".join(str((bank_index.file(memory_path, "entities", f"{p}.md").frontmatter or {}).get("name") or p).split())
             for p in ids]
    inbox = _inbox(memory_path)
    path = inbox / f"inbox-{inbox_service.next_inbox_num(inbox):03d}.md"
    frontmatter = {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.5,
        "entity_id": mention_id, "entity_name": mention,
        "title": f"Were you talking about {_or(names)}?" if len(f"Were you talking about {_or(names)}?") <= MAX_QUESTION
        else f"Which one did you mean by {mention}?",
        "uncertainty_type": f"Possible duplicate of {names[0]}", "suggested_classification": "",
        "suggested_confidence": 0.5, "created_date": day, "source_episode": str(source_episode or ""),
        "merge_target_hint": ids[0], "same_title": ids, "detected": DETECTED,
    }
    if source_episode_timestamp:
        frontmatter["source_episode_timestamp"] = str(source_episode_timestamp)
    markdown_parser.write(path, frontmatter, (source_context or "").strip()
                          or "Why this is asked: the name could be any of these, and nothing in the conversation says which.")
    bank_index.invalidate(memory_path)
    return f"inbox/{path.name}"


# --------------------------------------------------------------------------- Sleep's tending


@dataclass
class Report:
    written: list[str] = field(default_factory=list)
    rewritten: int = 0
    folded: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def _mention_like(memory_path: Path, fm: dict) -> bool:
    """The question's subject is a name, not a page the person has: no page of that id yet (a held mention, G209) or a
    page titled by a nickname — or the question Stage 2 marked as one about a mention it held (``held_mention``)."""
    from api.services import role_people
    from api.services.id_utils import resolve_entity_file

    if fm.get("held_mention"):
        return True
    path = resolve_entity_file(memory_path, str(fm.get("entity_id") or ""))
    if path is None:
        return True
    entry = bank_index.file(memory_path, "entities", path.name)
    return entry is not None and bool((entry.frontmatter or {}).get(role_people.NICKNAME_KEY))


def tend(memory_path, today: date | None = None, *, skip: frozenset[str] = frozenset()) -> Report:
    """Rewrite every pairwise "is <mention> the same as <page>?" whose mention could be two or more pages into the one
    question (see the module). One question per mention is kept — the oldest — and the rest of that mention's pairwise
    files are removed after their candidates are on it. Untouched: a question with a ``detected`` marker (a page pair
    another rule asked), one that names where each side was heard, one the person took back or put off, a file the
    caller marks dirty (``skip``)."""
    from api.services import inbox_tend
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
        if inbox_tend._blocked(fm, day):
            theirs.add(entity_id)
            continue
        if fm.get("detected") or fm.get("heard_in") or fm.get("fold_page") or rel in skip:
            continue
        if entity_id and _mention_like(memory_path, fm):
            groups.setdefault(entity_id, []).append((path, fm, body))
    for entity_id, items in groups.items():
        if entity_id in theirs:
            report.skip("the_persons")
            continue
        first_path, first, body = items[0]
        mention = str(first.get("entity_name") or entity_id)
        named = [str(fm.get("merge_target_hint") or "") for _p, fm, _b in items]
        stored = [pid for _p, fm, _b in items for pid in (fm.get("same_title") or []) if isinstance(pid, str)]
        wanted = usable(memory_path, mention, [*named, *stored, *answering(memory_path, mention, exclude={entity_id})])
        if len(wanted) < 2:
            report.skip("one_candidate")
            continue
        if len(items) == 1 and list(first.get("same_title") or []) == wanted:
            continue   # already the question
        names = [" ".join(str((bank_index.file(memory_path, "entities", f"{p}.md").frontmatter or {}).get("name") or p).split())
                 for p in wanted]
        rewritten = {**first, "same_title": wanted, "merge_target_hint": wanted[0], "detected": DETECTED,
                     "uncertainty_type": f"Possible duplicate of {names[0]}",
                     "title": (f"Were you talking about {_or(names)}?"
                               if len(f"Were you talking about {_or(names)}?") <= MAX_QUESTION
                               else f"Which one did you mean by {mention}?"), "updated_date": day}
        try:
            markdown_parser.write(first_path, rewritten, body)
        except OSError as exc:
            logger.warning(f"which-one rewrite failed: {type(exc).__name__}")
            continue
        report.written.append(f"inbox/{first_path.name}")
        report.rewritten += 1
        for path, _fm, _b in items[1:]:
            try:
                path.unlink()
            except OSError:
                continue
            report.written.append(f"inbox/{path.name}")
            report.folded += 1
    if report.written:
        bank_index.invalidate(memory_path)
    return report


def commit_message(report: Report, today) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Which-one questions {today.isoformat()}",
        [f"{p}: updated (source: n/a, trigger: {TRIGGER})" for p in report.written], authors=["cicada"])
