"""A page for a specific thing the person applied to or registered for (TODO ruling 42, owner 2026-10-27).

The promotion rule gives a name its page on two conversations (`promotion`, `entity_resolver`). Ruling 42 makes one
named exception: **one conversation is enough when the person acted on a specific event, program, hackathon,
fellowship or application** — they applied, registered or filled in a form, or an agent did it for them. The
application then lives on that page — its status, the day, who filled it (the agent and session from the episode's
own record) and a step left open — and the owner's page keeps at most a link, so "applied to X" lines stop piling up
there and go stale on the thing they are about, by its own decay.

Narrow on purpose. Three things must hold, each from the conversation itself, never guessed:

* Stage 1 marked the entity with an ``application`` (its status, and whether the user or the assistant acted), and
  its type is one a specific event, program or opening can carry (not a person, tool, skill, place or folder);
* **one sentence of the person's own turn** names it and says it was done — applied, registered, signed up,
  submitted, filled in its form, requested to join (:data:`DONE`, a few languages) — with no question, plan, wish or
  negation in it (:data:`NOT_DONE`; a sentence ending "?" never counts) — or, in a harness session the hook captured
  (``capture_kind: transcript``), **one sentence of the agent's own line** does ("The X form is filled in");
* the name is located exactly in that sentence (the same matching as `project_birth`), and the span is kept, never
  a copy — and it is the act's object, not the place it is held or who runs it ("signed up for an <event> at the
  <venue>" gives the venue nothing, `act_object`, 2026-10-28).

A bookmark, a save, a watched video or a passing mention never qualifies, nor does "Should I register for X?", "I'm
planning to apply to X" or a form in another sentence. A texted agent's explanation ("register soon") is not an act
either: only a harness agent acts in the person's tools.

The record (``application_birth`` on the extraction, never the model's to set) is
``{episode, day?, status, by: "user"|<agent name>, session?, span: {start, end, hash, kind}}``.
"""
from __future__ import annotations

import re

from api.services import evidence, promotion
from api.services.project_birth import _name_pattern

#: A completed act on an application, in the languages the owner's conversations use: applied, registered, signed
#: up, RSVP'd, enrolled, submitted, sent the application / form / request, filled in (or out) its form, requested to
#: join, drafted it, was accepted or rejected, attended. Whole words, any case. A bare "apply", "register" or "form"
#: is a plan, a question or another thing entirely.
DONE = re.compile(
    r"(?<!\w)(?:applied|registered|signed[ -]?up|rsvp'?d|enrol(?:l)?ed|submitted|requested to join|drafted|"
    r"sent (?:\w+ ){0,3}(?:application|form|request)s?|filled (?:in|out)|"
    r"(?:got|was|been|were) (?:accepted|rejected|admitted)|attended|"
    r"me (?:inscrib[ií]|apunt[eé]|registr[eé])|apliqu[eé]|postul[eé]|envi[eé] (?:la|el|mi) (?:solicitud|formulario|"
    r"aplicaci[oó]n))(?!\w)", re.IGNORECASE)
#: What makes a sentence with such a word not a completed act: a question, a plan, a wish or a negation.
NOT_DONE = re.compile(
    r"(?<!\w)(?:should (?:i|we)|shall (?:i|we)|planning to|plan to|plans to|going to|gonna|want(?:s|ed)? to|"
    r"would like to|thinking (?:of|about)|consider(?:ing)?|might|maybe|whether|if i|haven'?t|hasn'?t|have not|"
    r"has not|didn'?t|did not|not yet|never|will|won'?t|can'?t|cannot|debería|voy a|quiero|pienso)(?!\w)",
    re.IGNORECASE)

#: The statuses an application moves through, as the page records them.
STATUSES = ("drafted", "filled", "sent", "registered", "accepted", "rejected", "attended")
#: Statuses that leave a step to the person.
OPEN = frozenset({"drafted", "filled"})
#: Types a specific event, program or opening never has.
NOT_AN_APPLICATION = frozenset({"person", "tool", "skill", "location", "directory", "media", "deadline"})

KEY = "application_birth"


def _marked(entity: dict) -> dict | None:
    raw = entity.get("application")
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status") or "").strip().lower()
    if status not in STATUSES:
        return None
    by = "assistant" if str(raw.get("by") or "").strip().lower() == "assistant" else "user"
    return {"status": status, "by": by}


def completed_act(sentence: str) -> bool:
    """One sentence says an application was acted on: a completed act (:data:`DONE`), and no question, plan or
    negation (:data:`NOT_DONE`) — "I applied to X", "The X form is filled in"; never "Should I register for X?", "I'm
    planning to apply to X", "I haven't sent the X form"."""
    sentence = " ".join(str(sentence or "").split())
    return bool(DONE.search(sentence)) and not NOT_DONE.search(sentence) and not sentence.rstrip().endswith("?")


_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def _acted(entity: dict, text: str, *, roles: frozenset, override: str | None, gaps) -> evidence.Evidence | None:
    """The first sentence, in a turn of one of ``roles``, that names the entity and says it was acted on
    (:func:`completed_act`), as a span over the name."""
    from api.services import act_object

    pattern = _name_pattern(entity)
    if pattern is None or not text:
        return None
    for turn in evidence.turns(text, override=override, gaps=gaps):
        if turn.role not in roles:
            continue
        words = text[turn.content_start:turn.end]
        for s in _SENTENCE.finditer(words):
            name = pattern.search(s.group(0))
            if name is None or not completed_act(s.group(0)):
                continue
            if act_object.venue(s.group(0), name) is not None:
                continue    # "signed up for an <event> at the <name>": the name is where, not what (2026-10-28)
            start = turn.content_start + s.start() + name.start()
            end = turn.content_start + s.start() + name.end()
            if evidence.touches_gap(start, end, gaps):
                continue
            return evidence.Evidence(episode="", start=start, end=end, kind=turn.role, hash=evidence.body_hash(text))
    return None


def agent_of(frontmatter: dict) -> str | None:
    """The agent that acts in the person's tools in this episode: a harness-captured session's harness, by name."""
    harness = str(frontmatter.get("harness") or "").strip().lower()
    if not harness or frontmatter.get("capture_kind") != "transcript" or frontmatter.get("evidence_kind"):
        return None
    from api.services.episode_title import PRODUCT

    return PRODUCT.get(harness, harness)


def at_extraction(entity: dict, *, episode_id: str, frontmatter: dict, text: str, day: str | None,
                  override: str | None = None, gaps=()) -> dict | None:
    """The ``application_birth`` record this conversation gives the entity, or ``None`` (module docstring)."""
    mark = _marked(entity)
    if mark is None or str(entity.get("type") or "") in NOT_AN_APPLICATION:
        return None
    agent = agent_of(frontmatter)
    span = _acted(entity, text, roles=promotion.PERSON_KINDS, override=override, gaps=gaps)
    by = "user"
    if mark["by"] == "assistant" and agent:
        agent_span = _acted(entity, text, roles=frozenset({"assistant"}), override=override, gaps=gaps)
        if agent_span is not None:
            span, by = agent_span, agent
    if span is None:
        return None
    record = {"episode": episode_id, "status": mark["status"], "by": by,
              "span": {"start": span.start, "end": span.end, "hash": span.hash, "kind": span.kind}}
    if day:
        record["day"] = day
    session = str(frontmatter.get("session_id") or "").strip()
    if by != "user" and session:
        record["session"] = session
    return record


def birth_of(entity: dict, siblings=()) -> dict | None:
    """The first ``application_birth`` among one name's extractions in a batch, oldest conversation first."""
    found = [e.get(KEY) for e in (entity, *siblings) if isinstance(e.get(KEY), dict)]
    return min(found, key=lambda b: (str(b.get("day") or "~"), str(b.get("episode") or ""))) if found else None


def record_facts(entity: dict, birth: dict, *, owner: str | None) -> dict | None:
    """Write the application onto its own entity, from the record: a dated fact saying where it stands and who acted
    (the agent and its session, from the episode), an open question when a step is left to the person, and the status
    as a value (``values[]``) a later conversation's status replaces. Returns that value, or ``None``."""
    name = str(entity.get("name") or "").strip()
    if not name:
        return None
    status, by, day = birth["status"], birth["by"], birth.get("day")
    who = owner or "the person"
    when = f"As of {day}" if day else "In this conversation"
    doing = {"drafted": "drafted", "filled": "filled in", "sent": "sent", "registered": "registered",
             "accepted": "accepted", "rejected": "rejected", "attended": "attended"}[status]
    if by == "user":
        fact = f"{when}, {who}'s application to [[{name}]] was {doing}"
    else:
        session = f" (session {birth['session'][:8]})" if birth.get("session") else ""
        fact = f"{when}, {by}{session} had {doing} {who}'s application to [[{name}]]"
    fact += f"; sending it was left to {who}." if status in OPEN else "."
    facts = [f for f in entity.get("key_facts") or [] if isinstance(f, str)]
    entity["key_facts"] = [fact, *facts]
    if status in OPEN and not entity.get("open_questions"):
        entity["open_questions"] = [f"Has {who} sent the [[{name}]] application?"]
    return {"entity": name, "attribute": "application status", "value": status,
            "evidence": [evidence.reasoning(birth["episode"], hash=birth["span"]["hash"]).to_dict()]}


def _names_it(text: str, names: list[str]) -> bool:
    folded = str(text or "").lower()
    return any(n and (f"[[{n.lower()}" in folded or re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", folded))
               for n in names)


def move_from_owner(owner_entity: dict, target: dict) -> int:
    """Move what the owner's extraction says about ``target`` (an application entity) onto it: key facts, summary
    sentences (each standing alone, `fact_policy.standalone`) and history entries that name it. The owner keeps its
    relationship to the thing (the link); nothing is dropped. Returns how many items moved."""
    from api.services import fact_policy

    names = [str(target.get("name") or "").strip(), *(str(a) for a in target.get("aliases") or [] if a)]
    names = [n for n in names if len(n) >= 3]
    if not names:
        return 0
    moved: list[str] = []
    facts = [f for f in owner_entity.get("key_facts") or [] if isinstance(f, str)]
    keep = [f for f in facts if not _names_it(f, names)]
    moved += [f for f in facts if _names_it(f, names)]
    if len(keep) != len(facts):
        owner_entity["key_facts"] = keep
    owner_names = [owner_entity.get("name"), *(owner_entity.get("aliases") or [])]
    for field in ("summary", "description"):
        text = str(owner_entity.get(field) or "")
        if not text or not _names_it(text, names):
            continue
        parts = fact_policy.standalone(text, owner_names)
        about = [p for p in parts if _names_it(p, names)]
        owner_entity[field] = " ".join(p for p in parts if p not in about)
        moved += [p for p in about if p not in moved]
    history = [h for h in owner_entity.get("history_entries") or [] if isinstance(h, dict)]
    hits = [h for h in history if _names_it(h.get("event"), names)]
    if hits:
        owner_entity["history_entries"] = [h for h in history if h not in hits]
        target["history_entries"] = [*(target.get("history_entries") or []), *hits]
    if moved:
        target["key_facts"] = list(dict.fromkeys([*(target.get("key_facts") or []), *moved]))
    return len(moved) + len(hits)
