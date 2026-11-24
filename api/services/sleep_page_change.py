"""One page's change in one run, ready to render (owner 2026-11-24: "pages should render normally, not as raw markdown,
because it's harder to read what the actual changes were — and I don't get why <a page> was modified, what influenced
this change?").

``GET /sleep/runs/{id}/pages/{page}/change`` and ``GET /sleep/history/{commit}/pages/{page}/change``. The page's row is
the opened card's (``sleep_consolidated.survey``: the same final class, the same ``episodes`` and ``steps`` — why it
changed), and its change is its two versions compared (``page_change.compare``): the one before the run's first commit
that touched it and the one after the last. Nothing here reads a model, a diff of the file, or a claim by its json.

The change is the run's own: each commit of the run that touched the page is compared with its own parent and the
results composed (``page_change.compose``), never the page's first and last versions — a commit by the person or
another writer between two batches stays out of it. A page the run made or deleted is its whole text.

* **Facts** are the page's claims — its fence and its ledger — added, withdrawn, or changed in a field a person reads.
  Each is the one claim wire (``transclusion_resolver.claim_to_model``), with what moved (``page_change.CLAIM_FIELDS``)
  and the conversation its own evidence names. A fact whose confidence alone moved is counted in ``faded``, not shown.
* **Prose** is the page's own markdown in blocks (``page_change.prose_blocks``): added, removed, edited (with the words
  that changed, a link kept whole), a block of context either side, each with the heading it sits under.
* **Other** is the few non-bookkeeping frontmatter changes (status, name, type, aliases, tags, sources, decay class).

Bounded: ``MAX_FACTS`` of each kind, ``page_change.MAX_BLOCKS`` changed blocks, ``page_change.BLOCK_CHARS`` a block;
``truncated`` and the whole ``counts`` say when something was cut.
"""
from __future__ import annotations

from pathlib import Path

from api.models.schemas import (
    SleepChangeBlock,
    SleepChangeFact,
    SleepChangeFacts,
    SleepChangeFieldChange,
    SleepChangeOther,
    SleepChangeProse,
    SleepChangeSegment,
    SleepConversation,
    SleepPageChange,
)
from api.services import bank_index, commit_changes, git_service, page_change, sleep_consolidated, transclusion_resolver
from api.services.claims import Claim

MAX_FACTS = 80


def _text(value) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _field_changes(meaningful: dict[str, tuple]) -> list[SleepChangeFieldChange]:
    out: list[SleepChangeFieldChange] = []
    for name in page_change.CLAIM_FIELDS:
        if name not in meaningful:
            continue
        before, after = meaningful[name]
        if name == "sources":
            b, a = list(before or []), list(after or [])
            out.append(SleepChangeFieldChange(field=name, added=[x for x in a if x not in b],
                                              removed=[x for x in b if x not in a]))
        elif name == "details":
            out.append(SleepChangeFieldChange(field=name))
        else:
            out.append(SleepChangeFieldChange(field=name, before=_text(before), after=_text(after)))
    return out


def _evidence_conversation(memory_path: Path, entry: dict, run_eps: frozenset[str]) -> str | None:
    """The conversation a fact's own evidence (then its ``source_episodes``) names: one that exists in the bank,
    preferring one this run read."""
    named = [str(ev.get("episode")) for ev in entry.get("evidence") or [] if isinstance(ev, dict) and ev.get("episode")]
    named += [str(e) for e in entry.get("source_episodes") or [] if e]
    named = [e for e in dict.fromkeys(named) if bank_index.file(memory_path, "episodes", f"{e}.md") is not None]
    return next((e for e in named if e in run_eps), named[0] if named else None)


_NO_PROSE = {"blocks": [], "counts": {"added": 0, "removed": 0, "edited": 0}, "truncated": False}


def _compose_prose(raw: list[tuple], per: list[tuple], deltas: list) -> dict:
    """The prose blocks the run's commits changed. Commits that follow one another with nothing between them (the page
    at one commit's end is the next one's start) are one stretch and compare as one — a paragraph edited twice reads as
    one edit; a stretch that ends where it began, though a commit in it changed the words, lists each commit's blocks
    instead, so the card never says nothing changed. Stretches are joined in order, bounded as a single comparison."""
    stretches: list[list[int]] = [[0]]
    for i in range(1, len(raw)):
        if (raw[i][0], raw[i][2]) == (raw[i - 1][1], raw[i - 1][3]):
            stretches[-1].append(i)
        else:
            stretches.append([i])
    parts: list[dict] = []
    for idx in stretches:
        if not any(deltas[i].prose_changed for i in idx):
            continue
        net = page_change.prose_blocks(per[idx[0]][0].prose, per[idx[-1]][1].prose)
        if any(net["counts"].values()):
            parts.append(net)
        else:
            parts.extend(page_change.prose_blocks(per[i][0].prose, per[i][1].prose) for i in idx
                         if deltas[i].prose_changed)
    if not parts:
        return _NO_PROSE
    blocks: list[dict] = []
    counts = {"added": 0, "removed": 0, "edited": 0}
    truncated = False
    seen = 0
    for part in parts:
        truncated = truncated or part["truncated"]
        for key in counts:
            counts[key] += part["counts"][key]
        for b in part["blocks"]:
            if b["op"] != "context":
                seen += 1
                if seen > page_change.MAX_BLOCKS:
                    truncated = True
                    continue
            blocks.append(b)
    return {"blocks": blocks, "counts": counts, "truncated": truncated}


async def build(memory_path: Path, commits: list[str], settles: list[str], steps: list[tuple[str, str]],
                entity_id: str) -> SleepPageChange | None:
    """The change of page ``entity_id`` across ``commits`` (and the window's tail ``steps``), or ``None`` when no
    commit of the run touched it."""
    memory_path = Path(memory_path)
    sv = await sleep_consolidated.survey(memory_path, commits, settles, steps)
    change = sleep_consolidated.change_of(sv, entity_id)
    if change is None:
        return None
    order = sv.touched.get(entity_id, [])   # the run's commits that touched it, in the order git made them
    whole_page = change in ("created", "removed")
    if whole_page:
        old_text, new_text, old_ledger, new_ledger = await commit_changes.versions(
            memory_path, f"{order[0]}^" if order else None, order[-1] if order else None, entity_id)
        old, new = page_change.read_version(old_text, old_ledger), page_change.read_version(new_text, new_ledger)
        delta = page_change.compare(old, new)
        prose_raw = page_change.prose_blocks(old.prose, new.prose)
    else:
        raw = await commit_changes.commit_versions(memory_path, order, entity_id)
        per = [(page_change.read_version(a, c), page_change.read_version(b, d)) for a, b, c, d in raw]
        deltas = [page_change.compare(o, n) for o, n in per]
        for d, (o, n) in zip(deltas, per):
            if not o.present or not n.present:   # a commit that made or deleted the file: its header is no "change"
                d.other, d.details, d.prose_changed = [], 0, True
        old, delta = per[0][0], page_change.compose(deltas)
        prose_raw = _compose_prose(raw, per, deltas)

    from api.services import episode_copy, turn_authorship

    run_eps = frozenset(n[:-3] for n in sv.episodes)   # an episode's id is its file's stem
    row = sleep_consolidated._page(
        memory_path, entity_id, sv.touched.get(entity_id), change, run_eps, steps=sv.row_steps(entity_id, change),
        last=old.frontmatter if change == "removed" else None)
    turns = turn_authorship.TurnAuthorship(memory_path)

    def wire(entry: dict) -> tuple:
        claim = Claim.from_dict(entry)
        return transclusion_resolver.claim_to_model(claim, turns=turns), _evidence_conversation(memory_path, entry, run_eps)

    named: dict[str, bool] = {ep: True for ep in row.episodes}   # conversation id -> read by this run

    def facts_of(entries: list[dict], meanings: list[dict | None] | None = None) -> list[SleepChangeFact]:
        out: list[SleepChangeFact] = []
        for i, entry in enumerate(entries):
            try:
                out.append(fact(entry, meanings[i] if meanings else None))
            except (TypeError, ValueError):   # a claim that will not read is left out of the page, never a failed page
                continue
        return out

    def fact(entry: dict, meaningful: dict | None = None) -> SleepChangeFact:
        model, conversation = wire(entry)
        if conversation is not None:
            named.setdefault(conversation, conversation in run_eps)
        return SleepChangeFact(claim=model, conversation=conversation, in_run=bool(conversation in run_eps),
                               changes=_field_changes(meaningful) if meaningful else [])

    added = facts_of(delta.new[:MAX_FACTS])
    withdrawn = facts_of(delta.withdrawn[:MAX_FACTS])
    changed = facts_of([after for _b, after, _m in delta.changed[:MAX_FACTS]],
                       [meaningful for _b, _a, meaningful in delta.changed[:MAX_FACTS]])
    for _before, _after, meaningful in delta.changed[:MAX_FACTS]:
        for ep in (meaningful.get("sources") or ((), ()))[1] or []:   # a fact now also said in these conversations
            if bank_index.file(memory_path, "episodes", f"{ep}.md") is not None:
                named.setdefault(str(ep), str(ep) in run_eps)
    counts = {"added": len(delta.new), "withdrawn": len(delta.withdrawn), "changed": len(delta.changed)}
    facts_cut = any(n > MAX_FACTS for n in counts.values())
    facts = SleepChangeFacts(added=added, withdrawn=withdrawn, changed=changed, faded=len(delta.faded), counts=counts,
                             truncated=facts_cut)

    prose = SleepChangeProse(
        blocks=[SleepChangeBlock(op=b["op"], markdown=b["markdown"], heading=b["heading"], level=b["level"],
                                 before=b["before"], after=b["after"],
                                 segments=[SleepChangeSegment(**s) for s in b["segments"]])
                for b in prose_raw["blocks"]],
        counts=prose_raw["counts"], truncated=prose_raw["truncated"])
    other = [] if whole_page else [SleepChangeOther(field=o.field, before=o.before, after=o.after, added=o.added,
                                                   removed=o.removed) for o in delta.other]
    details = 0 if whole_page else delta.details
    own = episode_copy.own_device_id()
    conversations = [SleepConversation(**sleep_consolidated._conversation(memory_path, f"{ep}.md", own).model_dump(),
                                       in_run=in_run) for ep, in_run in named.items()]
    conversations.sort(key=lambda c: (not c.in_run, c.timestamp or "", c.id))
    empty = not (delta.new or delta.withdrawn or delta.changed or prose.blocks or other or details or delta.fed
                 or whole_page)
    return SleepPageChange(page=row, change=change, conversations=conversations, facts=facts, prose=prose,
                           other=other, other_details=details, empty=empty,
                           truncated=facts_cut or prose.truncated)
