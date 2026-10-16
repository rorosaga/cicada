"""Split a page that absorbed a message conversation's correspondent (G179 repair, owner 2026-10-15/16).

Before `correspondents`, Stage 2 resolved a texted agent by name alone, so an existing page that shared its letters —
an archived ``concept`` about the ordinary word — took the agent's conversations: its claims, its source credit, an
article rewritten about the agent, and the life those mentions gave the page. This finds such a page and splits it.

**The rule: nothing that is not attributable to the correspondent's conversation is lost or moved.** The split starts
from the page as it is NOW and subtracts only what the conversation brought.

**Found:** for each conversation whose episodes carry a decided ``correspondent`` record (the newest sitting's record
names it — the person's current mark), a page whose own ``name`` folds to the correspondent's name (as
`correspondents` folds), that credits one of those episodes (in ``source_episodes``, or a claim resting only on them)
while its type is not the correspondent's. A page that only lists the name as an alias is not split (``skipped_alias``). Pages that
legitimately credit the conversation (the projects it talked about) are never touched.

**From git**, the *base* is the page in the parent of the first commit that credited the conversation, and every
commit since is read in order:

* **Claims** (current state kept): a claim whose ``source_episodes`` and evidence are all the conversation's moves to
  the correspondent's page, re-subjected, every provenance field as it is. A claim also backed by another
  conversation stays on the old page untouched; a copy carrying only the conversation's episodes and evidence goes to
  the correspondent's page. Every other claim — older ones with their later closures — stays as it is.
* **Credit:** the conversation's episodes leave the old page's ``source_episodes`` for the new page's.
* **Prose and the list frontmatter** (``tags``, ``aliases``, ``related``, ``sources`` rows): moved only when every
  commit since the base that changed them was a Sleep commit adding nothing but the conversation's episodes to the
  page — then what they added is the conversation's: the old page's prose goes back to the base's, and the lead and
  Article the absorption rewrote (verbatim, so a machine article keeps its stamp; no model), the list items and list
  values it added move. Otherwise the old page's prose and lists stay as they are, the correspondent's page gets its
  facts from its claims, and the split is counted ``prose_left``.
* **Never moved, never changed:** what the person set — ``sources_removed``, ``aliases_removed``, ``corrections``,
  ``picture`` and every other key not named above.
* **Status and confidence** come from the page's own remaining history: the base state, then every later commit's
  change to them except a commit that credited the conversation, and — once the conversation had lifted the page —
  except Sleep's later decay commits charged against that lift (the next Sleep pass charges from the restored
  watermark). ``last_referenced`` is the latest day the remaining conversations were said; a ``dropped`` page stays
  dropped.

**The correspondent's page:** an existing page of the right type named so (merged human-safe, its own lead kept), else
a new one under `correspondents.free_id`, born as a create is: ``active``, ``RECOVERY_CONFIDENCE``, ``created`` /
``last_referenced`` from its conversations' own days, ``decayed_through`` = ``last_referenced``, ``learned_on`` today,
the decay class of its type. Other pages' claims resting only on the conversation whose node object is the old id
point at it; claim edges are regenerated (`graph_builder.regenerate_edges_from_claims`, Sleep's Stage 5.7). A
``[[wikilink]]`` by name in other prose is left as written.

A page with no version before the conversation, or a bank without git, is counted (``no_history``) and left alone.
The survey prints counts only. ``apply`` is refused while Sleep runs or holds the pages, skips a split whose footprint
is dirty in git, writes everything in one ``cicada`` commit (trigger ``maintenance/correspondent-split``), and a
second run finds nothing to do.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import yaml
from loguru import logger

from api.services import claims_ledger, correspondents, decay_policy, entity_body, episode_time, markdown_parser
from api.services.claims import Claim, parse_claims, strip_claims_block, write_claims

TRIGGER = "maintenance/correspondent-split"
AUTHOR = "cicada"
_LIST_SECTIONS = ("Key Facts", "History", "Links", "Open Questions")
#: Frontmatter lists Sleep extends from what a conversation said: moved only when every change to them is attributable.
_LIST_KEYS = ("tags", "aliases", "related", "sources")
#: The page's life: recomputed from its remaining history.
_STATE_KEYS = ("status", "confidence", "last_referenced", "decayed_through", "learned_on",
               decay_policy.FADED_BY_AGE_KEY, "confidence_before_mention")
_DECAY_PRODUCTS = ("status", "confidence", "decayed_through", decay_policy.FADED_BY_AGE_KEY)
#: How many claim sentences a page whose prose was left gets as its Key Facts.
MAX_FACTS_FROM_CLAIMS = 30


class SleepRunning(RuntimeError):
    """Sleep runs or holds this bank's pages: nothing was written."""


@dataclass
class Conversation:
    ident: correspondents.Identity
    episodes: set[str] = field(default_factory=set)
    days: dict[str, str] = field(default_factory=dict)   # episode id -> YYYY-MM-DD it was said


@dataclass
class Split:
    page_id: str
    target_id: str
    target_exists: bool
    conversation: Conversation
    base_rev: str
    old_fm: dict
    old_body: str
    new_fm: dict
    new_body: str
    claims_moved: int
    claims_copied: int
    sources_moved: int
    prose_moved: bool
    repoint: dict[str, list[str]]   # other page id -> the claim ids whose object moves


@dataclass
class Plan:
    conversations: int = 0
    candidates: int = 0
    splits: list[Split] = field(default_factory=list)
    no_history: int = 0
    skipped_alias: int = 0
    dirty: int = 0
    written: int = 0
    applied: bool = False
    committed: bool = False

    def counts(self) -> dict:
        return {
            "conversations": self.conversations,
            "pages_to_split": self.candidates,
            "splits": len(self.splits),
            "new_pages": sum(1 for s in self.splits if not s.target_exists),
            "into_existing_pages": sum(1 for s in self.splits if s.target_exists),
            "claims_moved": sum(s.claims_moved for s in self.splits),
            "claims_copied": sum(s.claims_copied for s in self.splits),
            "sources_moved": sum(s.sources_moved for s in self.splits),
            "prose_moved": sum(1 for s in self.splits if s.prose_moved),
            "prose_left": sum(1 for s in self.splits if not s.prose_moved),
            "claims_repointed": sum(len(v) for s in self.splits for v in s.repoint.values()),
            "skipped_alias": self.skipped_alias,
            "no_history": self.no_history,
            "dirty": self.dirty,
            "written": self.written,
            "applied": self.applied,
            "committed": self.committed,
        }


# --------------------------------------------------------------------------- reading


def _day(value) -> str:
    text = str(value or "")
    return text[:10] if len(text) >= 10 and text[4:5] == "-" else ""


def conversations(memory_path: Path) -> dict[str, Conversation]:
    """Every message conversation whose newest sitting names a decided correspondent, with all its episode ids."""
    found: dict[str, tuple[str, correspondents.Identity | None, set[str], dict[str, str]]] = {}
    for path in sorted((Path(memory_path) / "episodes").glob("*.md")):
        try:
            fm = markdown_parser.parse(path, ledger=False).frontmatter
        except Exception:  # noqa: BLE001 - an unreadable episode is not this repair's to judge
            continue
        record, cid = fm.get("correspondent"), str(fm.get("conversation") or "")
        if not isinstance(record, dict) or not cid:
            continue
        ep_id = str(fm.get("id") or path.stem)
        stamp = str(fm.get("timestamp") or "")
        newest, ident, eps, days = found.get(cid, ("", None, set(), {}))
        eps.add(ep_id)
        days[ep_id] = _day(fm.get("timestamp")) or _day(ep_id[3:])
        if stamp >= newest:
            newest, ident = stamp, correspondents.identity(record)
        found[cid] = (newest, ident, eps, days)
    return {cid: Conversation(ident, eps, days) for cid, (_n, ident, eps, days) in found.items() if ident is not None}


def _episode_day(memory_path: Path, episode_id: str) -> str:
    """The day an episode was said, or ``""`` when it is no mention (a memory export entry) or cannot be read."""
    path = Path(memory_path) / "episodes" / f"{episode_id}.md"
    try:
        fm = markdown_parser.parse(path, ledger=False).frontmatter if path.is_file() else {}
    except Exception:  # noqa: BLE001
        fm = {}
    if not episode_time.counts_as_activity(fm):
        return ""
    return _day(fm.get("timestamp")) or _day(str(episode_id)[3:])


def _load_pages(memory_path: Path) -> list[dict]:
    pages = []
    for path in sorted((Path(memory_path) / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001
            continue
        pages.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body, "path": path})
    return pages


def _claims(body: str) -> list[Claim]:
    try:
        return parse_claims(body, strict=True)
    except Exception:  # noqa: BLE001 - an unreadable fence: nothing on it is moved
        return []


def _only(claim: Claim, episodes: set[str]) -> bool:
    """The claim rests on the conversation alone: its sources and every evidence span are the conversation's."""
    sources = set(claim.source_episodes)
    spans = {ev.episode for ev in claim.evidence if getattr(ev, "episode", None)}
    return bool(sources) and sources <= episodes and spans <= episodes


def _attributable(fm: dict, body: str, episodes: set[str]) -> bool:
    """Something on the page is the conversation's to take: its credit, or a claim resting on it alone."""
    if set(str(e) for e in fm.get("source_episodes") or []) & episodes:
        return True
    return any(_only(c, episodes) for c in _claims(body))


def _credits(fm: dict, body: str, episodes: set[str]) -> bool:
    if set(str(e) for e in fm.get("source_episodes") or []) & episodes:
        return True
    return any(set(c.source_episodes) & episodes for c in _claims(body))


def _git(memory_path: Path, *args: str) -> str | None:
    """A read-only git command (no lock: nothing is mutated); ``None`` when it fails."""
    try:
        proc = subprocess.run(["git", *args], cwd=str(memory_path), capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else None


def _version(memory_path: Path, rev: str, page_id: str) -> tuple[dict, str] | None:
    """The page as it stood at ``rev`` — frontmatter and body, its ledger's claims folded in — or ``None``."""
    text = _git(memory_path, "show", f"{rev}:entities/{page_id}.md")
    if text is None:
        return None
    split = markdown_parser.split_frontmatter(text)
    if split is None:
        return {}, text.strip()
    fm = yaml.safe_load(split[0].strip()) or {}
    if not isinstance(fm, dict):
        return None
    markdown_parser._normalize_dates(fm)
    body = split[1].strip()
    if claims_ledger.STAMP in fm:
        ledger = _git(memory_path, "show", f"{rev}:entities/{page_id}{claims_ledger.SUFFIX}")
        if ledger:
            body = claims_ledger.merged(body, [line for line in ledger.split("\n") if line.strip()]).strip()
    return fm, body


@dataclass
class _Step:
    """One commit that touched the page since the base: what it was and what it changed."""
    sleep: bool
    added: set[str]
    before: tuple[dict, str]
    after: tuple[dict, str]


def _history(memory_path: Path, page_id: str, episodes: set[str]):
    """``(base_rev, base, steps)``: the page before the first commit that credited the conversation, and every commit
    that touched it since, oldest first. ``None`` when there is no version before the conversation."""
    log = _git(memory_path, "log", "--format=%H%x09%s", "--", f"entities/{page_id}.md")
    if not log:
        return None
    revs = [line.split("\t", 1) for line in log.splitlines() if line.strip()]
    revs = [(r[0], r[1] if len(r) > 1 else "") for r in reversed(revs)]
    start = None
    for i, (rev, _subject) in enumerate(revs):
        version = _version(memory_path, rev, page_id)
        if version is not None and _credits(version[0], version[1], episodes):
            start = i
            break
    if start is None:
        return None
    base_rev = f"{revs[start][0]}^"
    base = _version(memory_path, base_rev, page_id)
    if base is None or _credits(base[0], base[1], episodes):
        return None
    steps: list[_Step] = []
    before = base
    for rev, subject in revs[start:]:
        after = _version(memory_path, rev, page_id)
        if after is None:
            continue
        added = {str(e) for e in after[0].get("source_episodes") or []} - \
            {str(e) for e in before[0].get("source_episodes") or []}
        steps.append(_Step(sleep=subject.lower().startswith("sleep cycle"), added=added, before=before, after=after))
        before = after
    return base_rev, base, steps


# --------------------------------------------------------------------------- composing


def _items(content: str) -> list[str]:
    return entity_body._bullet_lines(content or "")


def _new_items(current: str, base: str) -> list[str]:
    had = {entity_body._normalize_fact(i) for i in _items(base)}
    return [i for i in _items(current) if entity_body._normalize_fact(i) not in had]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _list_key(value) -> str:
    if isinstance(value, dict):
        return f"{str(value.get('ref', '')).strip()}|{str(value.get('predicate') or '').strip().lower()}"
    return str(value).strip().lower()


def _identity_line(ident: correspondents.Identity) -> str:
    if ident.kind == "agent":
        return f"{ident.name} is an AI agent the person texts."
    return f"{ident.name} is someone the person texts."


def _resubject(claim: Claim, old_id: str, new_id: str) -> None:
    if claim.subject == old_id:
        claim.subject = new_id
    if claim.object_kind != "literal" and claim.object == old_id:
        claim.object = new_id


def _prose(body: str) -> str:
    return strip_claims_block(body or "").strip()


def _pure(steps: list[_Step], episodes: set[str]) -> bool:
    """Every commit since the base that changed the page's prose or its list frontmatter was a Sleep commit that
    credited the page with nothing but the conversation's episodes: what they added is the conversation's."""
    for step in steps:
        changed = _prose(step.before[1]) != _prose(step.after[1]) or any(
            step.before[0].get(k) != step.after[0].get(k) for k in _LIST_KEYS)
        if changed and not (step.sleep and step.added and step.added <= episodes):
            return False
    return True


def _state(base_fm: dict, steps: list[_Step], episodes: set[str]) -> dict:
    """The page's life from its own remaining history (see the module docstring)."""
    state = {k: base_fm.get(k) for k in _STATE_KEYS}
    lifted = False
    for step in steps:
        if step.added and step.added <= episodes:
            lifted = True            # the conversation's mention: its effect on the page's life is not the page's
            continue
        for key in _STATE_KEYS:
            if step.before[0].get(key) == step.after[0].get(key):
                continue
            if lifted and step.sleep and not step.added and key in _DECAY_PRODUCTS:
                continue             # a decay charge against the conversation's lift
            state[key] = step.after[0].get(key)
    return state


def _plan_split(memory_path: Path, page: dict, conv: Conversation, pages: list[dict], taken: set[str],
                today: str) -> Split | None:
    from api.services import entity_article, section_provenance
    from api.services.conflict_resolver import RECOVERY_CONFIDENCE

    page_id, cur_fm, cur_body = page["id"], dict(page["frontmatter"]), page["body"]
    history = _history(memory_path, page_id, conv.episodes)
    if history is None:
        return None
    base_rev, (base_fm, base_body), steps = history
    eps = conv.episodes
    ident = conv.ident
    pure = _pure(steps, eps)

    # Claims: current state kept. The conversation's alone move; one also backed elsewhere stays, and is copied.
    kept, moved, copied = [], [], []
    for claim in _claims(cur_body):
        if _only(claim, eps):
            moved.append(claim)
            continue
        kept.append(claim)
        if set(claim.source_episodes) & eps:
            copy = Claim.from_dict(claim.to_dict())
            copy.source_episodes = [e for e in claim.source_episodes if e in eps]
            copy.evidence = [ev for ev in claim.evidence if getattr(ev, "episode", None) in eps]
            copied.append(copy)

    # The old page: the current page, minus what is the conversation's.
    old_fm = dict(cur_fm)
    cur_sources = [str(e) for e in cur_fm.get("source_episodes") or []]
    old_fm["source_episodes"] = [e for e in cur_sources if e not in eps]
    conv_sources = [e for e in cur_sources if e in eps]
    for claim in [*moved, *copied]:
        conv_sources += [e for e in claim.source_episodes if e in eps and e not in conv_sources]
    state = _state(base_fm, steps, eps)
    remaining_days = [d for d in (_episode_day(memory_path, e) for e in old_fm["source_episodes"]) if d]
    said = max([d for d in (_day(state.get("last_referenced")), *remaining_days) if d], default="")
    for key in _STATE_KEYS:
        if key == "last_referenced":
            continue
        if state.get(key) is None:
            old_fm.pop(key, None)
        else:
            old_fm[key] = state[key]
    if said:
        old_fm["last_referenced"] = said
    if str(cur_fm.get("status") or "") == "dropped":
        old_fm["status"] = "dropped"   # the person dismissed it: it stays dismissed
    old_fm["version"] = int(cur_fm.get("version", 1) or 1) + 1
    if claims_ledger.STAMP in cur_fm:
        # The current ledger as read: this write is the page's whole claim set (`claims_ledger.split`).
        old_fm[claims_ledger.STAMP] = cur_fm[claims_ledger.STAMP]

    moved_sections: dict[str, str] = {}
    moved_lists: dict[str, list] = {}
    cur_sections = entity_body.parse_sections(_prose(cur_body))
    if pure:
        base_sections = entity_body.parse_sections(_prose(base_body))
        for title in ("Summary", "Article"):
            if (cur_sections.get(title) or "").strip() != (base_sections.get(title) or "").strip():
                moved_sections[title] = cur_sections.get(title) or ""
        for title in _LIST_SECTIONS:
            items = _new_items(cur_sections.get(title, ""), base_sections.get(title, ""))
            if items:
                moved_sections[title] = _bullets(items)
        old_prose = _prose(base_body)
        for key in _LIST_KEYS:
            had = {_list_key(v) for v in base_fm.get(key) or []}
            current = list(cur_fm.get(key) or [])
            moved_lists[key] = [v for v in current if _list_key(v) not in had]
            rest = [v for v in current if _list_key(v) in had]
            if rest or key in base_fm:
                old_fm[key] = rest
            else:
                old_fm.pop(key, None)
        # The old page's prose records are the base's (its prose is the base's again).
        for key in (entity_article.FIELD, section_provenance.FIELD):
            if key in base_fm:
                old_fm[key] = base_fm[key]
            else:
                old_fm.pop(key, None)
    else:
        old_prose = _prose(cur_body)
        facts = []
        for claim in [*moved, *copied]:
            text = " ".join(str(claim.text or "").split())
            if text and text not in facts:
                facts.append(text)
        if facts:
            moved_sections["Key Facts"] = _bullets(facts[:MAX_FACTS_FROM_CLAIMS])
    old_body = write_claims(old_prose, kept) if kept else old_prose

    target = correspondents.find_page(pages, ident)
    if target is not None and target["id"] == page_id:
        target = None
    if target is not None:
        target_id = target["id"]
        new_fm, new_body = _merge_into_target(target, moved_sections, [*moved, *copied], conv_sources,
                                              moved_lists.get("sources", []), moved_lists.get("tags", []),
                                              moved_lists.get("aliases", []), conv, page_id)
    else:
        target_id = correspondents.free_id(ident, taken, Path(memory_path) / "entities")
        days = sorted(d for d in (conv.days.get(e, "") for e in conv_sources) if d)
        last = days[-1] if days else today
        new_fm = {
            "name": ident.name,
            "type": ident.page_type,
            "status": "active",
            "confidence": RECOVERY_CONFIDENCE,
            "created": days[0] if days else today,
            "last_referenced": last,
            "decayed_through": last,
            "learned_on": today,
            **decay_policy.frontmatter_fields(decay_policy.default_class_for(ident.page_type)),
            "source_episodes": conv_sources,
            "tags": moved_lists.get("tags", []),
            "aliases": [a for a in moved_lists.get("aliases", []) if str(a).lower() != ident.name.lower()],
            "related": moved_lists.get("related", []),
            "version": 1,
            "layout_version": 2,
        }
        if moved_lists.get("sources"):
            new_fm["sources"] = moved_lists["sources"]
        if not (moved_sections.get("Summary") or "").strip():
            moved_sections["Summary"] = _identity_line(ident)
        prose = entity_body.render_sections(moved_sections)
        if pure:
            # The lead and Article moved as written keep their stamp; the G118 item records follow exact items.
            for key in (entity_article.FIELD, section_provenance.FIELD):
                if key in cur_fm:
                    new_fm[key] = cur_fm[key]
            if not entity_article.stamped(new_fm, entity_body.parse_sections(prose)):
                new_fm.pop(entity_article.FIELD, None)
            section_provenance.refresh(new_fm, _prose(cur_body), prose, {})
        for claim in [*moved, *copied]:
            _resubject(claim, page_id, target_id)
        new_claims = list(moved)
        ids = {c.id for c in new_claims}
        new_claims += [c for c in copied if c.id not in ids]
        new_body = write_claims(prose, new_claims) if new_claims else prose

    # Other pages' claims resting on the conversation alone that point at the old id.
    repoint: dict[str, list[str]] = {}
    for other in pages:
        if other["id"] in (page_id, target_id):
            continue
        ids = [c.id for c in _claims(other["body"])
               if c.object_kind != "literal" and c.object == page_id and _only(c, eps)]
        if ids:
            repoint[other["id"]] = ids

    return Split(page_id=page_id, target_id=target_id, target_exists=target is not None, conversation=conv,
                 base_rev=base_rev, old_fm=old_fm, old_body=old_body, new_fm=new_fm, new_body=new_body,
                 claims_moved=len(moved), claims_copied=len(copied), sources_moved=len(conv_sources),
                 prose_moved=pure, repoint=repoint)


def _merge_into_target(target: dict, moved_sections: dict, moved: list[Claim], conv_sources: list[str],
                       moved_rows: list, moved_tags: list, moved_aliases: list, conv: Conversation,
                       old_id: str) -> tuple[dict, str]:
    """The correspondent already has a page of the right type: union into it, its own lead kept (human-safe)."""
    fm = dict(target["frontmatter"])
    body = target["body"]
    fm["source_episodes"] = list(dict.fromkeys([*(fm.get("source_episodes") or []), *conv_sources]))
    fm["tags"] = list(dict.fromkeys([*(fm.get("tags") or []), *moved_tags]))
    aliases = list(fm.get("aliases") or [])
    have = {str(a).lower() for a in aliases} | {str(fm.get("name") or "").lower()}
    aliases += [a for a in moved_aliases if str(a).lower() not in have]
    if aliases:
        fm["aliases"] = aliases
    rows = list(fm.get("sources") or [])
    keys = {_list_key(r) for r in rows}
    rows += [r for r in moved_rows if _list_key(r) not in keys]
    if rows:
        fm["sources"] = rows
    days = [d for d in (conv.days.get(e, "") for e in conv_sources) if d]
    if days:
        fm["last_referenced"] = max([_day(fm.get("last_referenced")) or "", *days])
    fm["version"] = int(fm.get("version", 1) or 1) + 1
    sections = entity_body.parse_sections(strip_claims_block(body))
    fields = entity_body.sections_to_fields({k: v for k, v in moved_sections.items() if k in _LIST_SECTIONS})
    fields["summary"] = ""
    merged = entity_body.merge_sections_human_safe(sections, fields,
                                                   human_edited=entity_body.has_human_prose(fm, sections))
    own = _claims(body)
    have_ids = {c.id for c in own}
    for claim in moved:
        _resubject(claim, old_id, target["id"])
    carried = [c for c in moved if c.id not in have_ids]
    prose = entity_body.render_sections(merged)
    return fm, (write_claims(prose, [*own, *carried]) if (own or carried) else prose)


# --------------------------------------------------------------------------- survey / apply


def survey(memory_path: Path, *, today: str | None = None) -> Plan:
    """What :func:`apply` would do, computed without writing anything."""
    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    plan = Plan()
    by_conversation = conversations(memory_path)
    plan.conversations = len(by_conversation)
    # Two conversations with the same correspondent (the same name and kind) are one correspondent: one page.
    convs: dict[tuple[str, str], Conversation] = {}
    for conv in by_conversation.values():
        key = (conv.ident.key, conv.ident.kind)
        if key in convs:
            convs[key].episodes |= conv.episodes
            convs[key].days.update(conv.days)
        else:
            convs[key] = Conversation(conv.ident, set(conv.episodes), dict(conv.days))
    if not convs:
        return plan
    pages = _load_pages(memory_path)
    taken = {p["id"] for p in pages}
    claimed: set[str] = set()
    for conv in convs.values():
        ident = conv.ident
        for page in pages:
            fm = page["frontmatter"]
            if page["id"] in claimed or str(fm.get("type") or "").lower() == ident.page_type:
                continue
            if not _attributable(fm, page["body"], conv.episodes):
                continue
            if not correspondents.names_it([fm.get("name")], ident):
                aliases = fm.get("aliases") if isinstance(fm.get("aliases"), list) else []
                if correspondents.names_it(aliases, ident):
                    plan.skipped_alias += 1    # only an alias names it: another thing, maybe; never split
                continue
            plan.candidates += 1
            split = _plan_split(memory_path, page, conv, pages, taken, today)
            if split is None:
                plan.no_history += 1
                continue
            claimed.add(page["id"])
            taken.add(split.target_id)
            plan.splits.append(split)
    return plan


def _footprint(split: Split) -> list[str]:
    return [f"entities/{split.page_id}.md", f"entities/{split.target_id}.md",
            *(f"entities/{pid}.md" for pid in split.repoint)]


def apply(memory_path: Path, *, sleep_running: Callable[[], bool], today: str | None = None) -> Plan:
    """Write the survey's splits in ONE ``cicada`` commit. Raises :class:`SleepRunning` before writing anything while
    Sleep runs or holds the pages; a split whose footprint is dirty in git is skipped and counted."""
    from api.services import git_service, page_lock, write_admission

    memory_path = Path(memory_path)
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; repair after it ends")
        with page_lock.page_lock(memory_path):
            plan = survey(memory_path, today=today)
            has_git = (memory_path / ".git").exists()
            others_dirty = frozenset(git_service.dirty_paths_sync(memory_path)) if has_git else frozenset()
            done: list[Split] = []
            written: list[str] = []
            lines: list[str] = []
            for split in plan.splits:
                footprint = claims_ledger.with_ledgers(memory_path, _footprint(split))
                if others_dirty.intersection(footprint):
                    plan.dirty += 1
                    continue
                ents = memory_path / "entities"
                markdown_parser.write(ents / f"{split.page_id}.md", split.old_fm, split.old_body)
                markdown_parser.write(ents / f"{split.target_id}.md", split.new_fm, split.new_body)
                written += [f"entities/{split.page_id}.md", f"entities/{split.target_id}.md"]
                lines += [f"entities/{split.page_id}.md: updated (split, trigger: {TRIGGER})",
                          f"entities/{split.target_id}.md: "
                          f"{'updated' if split.target_exists else 'created'} (split, trigger: {TRIGGER})"]
                for other_id, claim_ids in split.repoint.items():
                    path = ents / f"{other_id}.md"
                    parsed = markdown_parser.parse(path)
                    own = parse_claims(parsed.body, strict=True)
                    for claim in own:
                        if claim.id in claim_ids and claim.object == split.page_id:
                            claim.object = split.target_id
                    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, own))
                    written.append(f"entities/{other_id}.md")
                    lines.append(f"entities/{other_id}.md: updated (claims repointed, trigger: {TRIGGER})")
                done.append(split)
            if done and not others_dirty.intersection({"graph_edges.yaml"}):
                from api.services.graph_builder import regenerate_edges_from_claims

                regenerate_edges_from_claims(memory_path)
                edges_changed = (memory_path / "graph_edges.yaml").exists() and (
                    not has_git or bool((_git(memory_path, "status", "--porcelain", "--", "graph_edges.yaml") or "")
                                        .strip()))
                if edges_changed:
                    written.append("graph_edges.yaml")
                    lines.append(f"graph_edges.yaml: updated (trigger: {TRIGGER})")
            plan.splits = done
            written = list(dict.fromkeys(written))
            plan.written = len(written)
            plan.applied = True
            if written and has_git:
                message = git_service.build_commit_message(
                    f"Correspondent pages: {len(done)} split from a same-name page", list(dict.fromkeys(lines)),
                    authors=[AUTHOR])
                git_service.commit_paths_sync(memory_path, message, written)
                plan.committed = True
    if plan.written:
        logger.info(f"correspondent split: {plan.written} path(s) written")
    return plan
