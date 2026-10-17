"""Who is answering an inbox question: the person (the default) or Sleep (ruling 29, owner 2026-10-17).

The inbox has one writer per kind (``inbox_service``'s resolvers). The person's answer and Sleep's settle go through
the same resolvers, so a claim, a closure or a merge is written the same way whoever answered; what differs is who
the record says did it. This ContextVar carries that for the length of one settle — set by ``inbox_tend`` only — and
the few places that name the answerer read it:

* ``git_service.commit_resolution_sync`` commits under Sleep's authors with an ``inbox/<kind>/settled:<label>``
  trigger (never ``resolved:``, so G147's decay-verdict reader and every "the person said" reader skip it), and adds
  the settle's own record (``inbox/settled/<id>.md``) to the same commit;
* ``inbox_service._emit_resolution`` stamps the G113 ledger row ``by: sleep`` with the rule that settled it, so a
  feedback rate never counts Sleep's assumption as the person's verdict;
* the conflict and clarification resolvers say "settled by Sleep" in prose and author a claim as Sleep's, never the
  person's (the person's own words stay the claim's evidence, as spans).

Unset (the default) everything is exactly as before: the person answered.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field


@dataclass
class Actor:
    #: The rule that settled the item (an enum: ``said_in_conversation``, ``same_spelling``, ...).
    rule: str
    #: ``Cicada-Author`` trailers for the commit: the model that judged, or ``cicada`` for an engine-free rule.
    authors: list[str] = field(default_factory=lambda: ["cicada"])
    engine: str | None = None
    #: Memory-relative paths the settle adds to the resolver's own commit (its ``inbox/settled/`` record).
    extra_paths: list[str] = field(default_factory=list)
    extra_lines: list[str] = field(default_factory=list)
    #: The settle's own record, ``(path, frontmatter, body)``: written at the commit, after the resolver's dirty
    #: snapshot, so it is this commit's own file and never "an edit kept apart".
    record: tuple | None = None
    #: Set by the commit hook once the commit returned: the resolver committed, and the record rode with it.
    committed: bool = False


_ACTOR: contextvars.ContextVar[Actor | None] = contextvars.ContextVar("inbox_actor", default=None)


def write_record(actor: Actor) -> None:
    if actor.record is None:
        return
    from api.services import markdown_parser

    path, fm, body = actor.record
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, fm, body)


def current() -> Actor | None:
    return _ACTOR.get()


def set_actor(actor: Actor | None):
    return _ACTOR.set(actor)


def reset(token) -> None:
    _ACTOR.reset(token)


def is_sleep() -> bool:
    return _ACTOR.get() is not None


def claim_author() -> str:
    """``authored_by`` for a claim an answer writes: the person's own act, or Sleep's (its judging model or
    ``cicada``)."""
    actor = _ACTOR.get()
    return "user" if actor is None else (actor.authors[0] if actor.authors else "cicada")


def confirmed_by() -> str:
    """The words a resolver's prose uses for who confirmed it."""
    return "user" if _ACTOR.get() is None else "Sleep"


def ledger_refs() -> dict:
    """Extra refs for the G113 ``resolution`` row: ids and enums only."""
    actor = _ACTOR.get()
    return {} if actor is None else {"by": "sleep", "rule": actor.rule}


def trigger(trigger: str) -> str:
    """``inbox/<kind>/resolved[:label]`` → ``inbox/<kind>/settled[:label]`` while Sleep answers."""
    if _ACTOR.get() is None:
        return trigger
    return trigger.replace("/resolved", "/settled", 1)
