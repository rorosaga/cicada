"""A one-time sweep for people a memory holds under a qualified name (G148, owner 2026-11-24): plan with a judge, apply with none.

Before #846 a conversation naming two people of one first name ("Nico from work finally met my cousin Nico") left each
waiting on a held line titled with the qualifier ("Nico (finance lead)"), never matched to the Nico who already has a
page. #846 treats such a person as a mention of the bare name from now on; a line already held stays as it is.

**Plan** (:func:`plan_line`, writes nothing): each held person line written ``Name (qualifier)`` is placed by the live
module itself (`same_name_people.plan`, the small judge, the main model's second reading, the thin-description and
same-conversation rules, run on the bank's own pages and lines exactly as Stage 2 gives them): to the plain person, to a
person on record (a page or a held line), or to a person of its own held in doubt. Never a join on the name alone
(ruling 74): when the plan finds no reading, or a person it cannot place, the line is **left as it is** and the row says so.
A handle the record paired (``Full Name (handle)``), the owner's first name, a name of two words, a line the person said was
not a page (`apart`), a message correspondent and anything that is not a person are never touched.

**Apply** (:func:`apply_rows`, no model call) writes exactly the rows of a reviewed plan: the line's name becomes the page's
or the bare name's (or a free ``<name>-2`` key for a person of its own with the bare name as its title, the pair recorded
in doubt), the written name kept as an alias, its held claims re-pointed (`pending_store._repoint`) and the line's facts
folded into the line it joins (`pending_store._carry`). The next Sleep releases a line's claims onto a page that bears its
name, as it does for every held name (`pending_store.ready`). A row whose line changed since the plan is skipped and counted.

Pages titled with a qualifier are counted and listed, never changed: moving a page is the page join's, which has its own
undo.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import (
    entity_resolver, git_service, markdown_parser, pending_store, person_leads, same_name_doubts, same_name_people as snp,
)
from api.services.claims import Claim
from api.services.id_utils import sanitize_id

TRIGGER = "maintenance/name-sweep"
VERSION = 1
#: Lines one run may place (each is one judge call or more); the rest wait for another run.
MAX_LINES = 40


class EngineDown(RuntimeError):
    """The engine failed several calls in a row: stop, the run resumes."""


@dataclass
class Meter:
    small: int = 0
    strong: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.small + self.strong


# --------------------------------------------------------------------------- reading the bank


@dataclass
class Bank:
    pages: list[dict] = field(default_factory=list)       # {"id", "frontmatter", "body"}
    lines: list = field(default_factory=list)             # PendingEntity
    owner_id: str | None = None
    owner_name: str = ""
    path: Path | None = None

    @property
    def owner_first(self) -> str:
        return (self.owner_name.split() or [""])[0].lower()


def load(bank: Path) -> Bank:
    out = Bank(lines=pending_store.load(bank), path=Path(bank))
    for path in sorted((Path(bank) / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - an unreadable page is left alone
            continue
        fm = parsed.frontmatter or {}
        out.pages.append({"id": path.stem, "frontmatter": fm, "body": parsed.body})
        if fm.get("owner") and out.owner_id is None:
            out.owner_id, out.owner_name = path.stem, str(fm.get("name") or "")
    return out


def qualified_pages(bank: Bank) -> list[str]:
    """Person pages titled ``Name (qualifier)``: counted and listed, never changed here."""
    return [p["id"] for p in bank.pages
            if str(p["frontmatter"].get("type") or "").lower() == "person"
            and str(p["frontmatter"].get("status") or "") != "dropped"
            and snp.stem_of(str(p["frontmatter"].get("name") or "")) is not None]


def candidates(bank: Bank) -> tuple[list, dict[str, int]]:
    """The held person lines written with a qualifier, and the ones left alone with why (counts)."""
    out, left = [], {}
    for line in bank.lines:
        stem = snp.stem_of(line.name) if line.type == "person" else None
        if stem is None:
            continue
        why = None
        if person_leads.split_named_handle(line.name) is not None:
            why = "a handle the record paired"
        elif stem[0].lower() == bank.owner_first:
            why = "the owner's first name"
        elif line.correspondent or line.apart:
            why = "a correspondent, or the person said it is not a page"
        if why:
            left[why] = left.get(why, 0) + 1
        else:
            out.append(line)
    return out, left


def line_state(line) -> str:
    return hashlib.sha256(json.dumps(line.to_dict(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def mention_for(line, plain_episodes: frozenset[str]) -> snp.Mention:
    stem = snp.stem_of(line.name)
    day = next((str(h.get("timestamp") or h.get("day") or "")[:10] for h in line.heard_in if h.get("episode") == line.source_episode),
               "")
    text = snp.describe({"name": line.name, "summary": line.summary or line.description, "key_facts": line.key_facts,
                         "source_episode_timestamp": day})
    return snp.Mention(snp.mention_key(line.source_episode, line.name), text, line.source_episode, True,
                       line.source_episode in plain_episodes)


def census(bank: Bank) -> dict:
    cands, left = candidates(bank)
    names = {snp.stem_of(c.name)[0].lower() for c in cands}
    return {"lines": len(cands), "bare_names": len(names), "left_alone_by_reason": dict(sorted(left.items())),
            "pages_titled_with_a_qualifier": len(qualified_pages(bank)),
            "most_calls_possible": 2 * len(names)}


# --------------------------------------------------------------------------- the plan


def recorder(ask: Callable[[str, str], object], meter: Meter, kind: str, said: list) -> Callable[[str, str], Awaitable[object]]:
    async def call(system: str, prompt: str) -> object:
        setattr(meter, kind, getattr(meter, kind) + 1)
        try:
            reply = await asyncio.to_thread(ask, system, prompt)
        except Exception as exc:  # noqa: BLE001
            meter.failed += 1
            logger.info(f"name sweep: a call failed ({type(exc).__name__})")
            if meter.failed >= 3:
                raise EngineDown(type(exc).__name__) from exc
            raise
        meter.failed = 0
        said.append(reply)
        return reply
    return call


def _reasons(said: list) -> list[str]:
    out = []
    for reply in said:
        if not isinstance(reply, dict):
            continue
        for key in ("people", "pairs"):
            for item in reply.get(key) or []:
                if isinstance(item, dict) and item.get("reason"):
                    out.append(str(item["reason"]))
    return out


def identities_for(bank: Bank, stem: str, exclude: set[str]) -> list | None:
    """The people on record under the bare name, as Stage 2 gives them to the judge (`entity_resolver`'s own builder);
    ``None`` when the name is not for this rule (the owner's page, a nickname or a relation bears it)."""
    low = stem.lower()
    pages = [p for p in bank.pages if str(p["frontmatter"].get("name") or "").lower() == low
             and str(p["frontmatter"].get("status") or "") != "dropped"]
    lines = [ln for ln in bank.lines if ln.name not in exclude]
    return entity_resolver._same_name_identities(low, pages, lines, bank.owner_id, bank.path)


def action_of(dest: snp.Destination, identities: list) -> tuple[str, str]:
    """``(action, target)``: what applying a destination does to the line."""
    if dest.kind == "new":
        return "new_person", ""
    if dest.kind == "plain":
        plain = next((i for i in identities if i.plain), None)
        if plain is None:
            return "rename_bare", ""
        return ("to_page" if plain.kind == "page" else "merge_line"), plain.ref
    return ("to_page" if dest.kind == "page" else "merge_line"), dest.ref


async def plan_name(bank: Bank, stem: str, lines: list, small: Callable, strong: Callable, meter: Meter) -> list[dict]:
    """The rows of every swept line that is written with this bare name: placed together, as Stage 2 places the mentions of
    one name in one batch."""
    identities = identities_for(bank, stem, {ln.name for ln in lines})
    base = {"v": VERSION, "pass": "names", "stem": stem, "strike": False}
    if identities is None:
        return [{**base, "line": ln.name, "state": line_state(ln), "action": "leave",
                 "reason": "the owner's page, a nickname or a relation bears this name"} for ln in lines]
    plain_eps = next((i.episodes for i in identities if i.plain), frozenset())
    mentions = [mention_for(ln, plain_eps) for ln in lines]
    said: list = []
    if not identities and len(mentions) == 1:
        moves, called, flagged = {mentions[0].episode: snp.Destination("plain", "")}, False, set()
    else:
        # `_plan`, not `plan`: `plan` ends by sending every qualified mention nothing placed to the bare name (right for a
        # new mention, which was always the bare name's), and that is a join on the name alone (ruling 74). A line the
        # reader placed nowhere stays as it is, and the row says so.
        outcome = await snp._plan(stem, mentions, identities, recorder(small, meter, "small", said),
                                  recorder(strong, meter, "strong", said), bank.owner_name or None)
        moves, called, flagged = outcome.moves, outcome.called, set(outcome.review_pages)
    compared = [sanitize_id(i.ref) for i in identities[: snp.MAX_IDENTITIES]]
    rows = []
    for line, mention in zip(lines, mentions):
        dest = moves.get(mention.episode)
        row = {**base, "line": line.name, "state": line_state(line), "episodes": line.episodes(),
               "facts": len(line.key_facts), "held_claims": len(line.held_claims),
               "text": mention.text, "alias": line.name, "judge_said": _reasons(said) if called else []}
        if dest is None:
            rows.append({**row, "action": "leave", "reason": "the reader placed it nowhere (a thin description, no usable reading, or only the name to go on)"})
            continue
        action, target = action_of(dest, identities)
        if target and target in flagged:
            rows.append({**row, "action": "leave", "reason": f"the reading also says the page {target} holds two people already: "
                         "joining a line to it would add to that; look at the page first (Sleep's same-name review)"})
            continue
        if mention.no_rename and action in ("to_page", "merge_line") and any(i.plain and i.ref == target for i in identities):
            rows.append({**row, "action": "leave", "reason": "its own conversation also names the bare name's person, so it is "
                         "another person than that one: never joined to it on a reading of its description"})
            continue
        rows.append({**row, "action": action, "target": target, "doubt": dest.doubt, "compared": compared,
                     "destination": f"{dest.kind}:{dest.ref}"})
    return rows


def review_text(rows: list[dict]) -> str:
    lines: list[str] = []
    for row in sorted(rows, key=lambda r: (r.get("action") == "leave", str(r.get("line")))):
        lines.append(f"## {row['line']}  -> {row['action']}" + (f" {row.get('target')}" if row.get("target") else "")
                     + ("  (held in doubt)" if row.get("doubt") else "") + ("  [STRUCK]" if row.get("strike") else ""))
        if row.get("text"):
            lines.append(f"    this line says: {row['text']}")
        lines.append(f"    holds {row.get('facts', 0)} fact(s), {row.get('held_claims', 0)} held claim(s), "
                     f"conversations {', '.join(row.get('episodes') or [])}")
        for text in row.get("judge_said") or []:
            lines.append(f"    reader: {text}")
        if row.get("reason"):
            lines.append(f"    left as it is: {row['reason']}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- apply


@dataclass
class Result:
    rows: int = 0
    applied: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list = field(default_factory=list)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def counts(self) -> dict:
        return {"lines_in_plan": self.rows, "applied": dict(sorted(self.applied.items())),
                "skipped": dict(sorted(self.skipped.items()))}


def _aliases(line, *extra: str) -> list[str]:
    seen, out = set(), []
    for name in [*line.aliases, *extra]:
        if name and name.lower() not in seen and name.lower() != (line.name or "").lower():
            seen.add(name.lower())
            out.append(name)
    return out


def _repointed(line, target_slug: str) -> list[dict]:
    claims = []
    for data in line.held_claims:
        try:
            claims.append(Claim.from_dict(data))
        except (TypeError, ValueError):
            return list(line.held_claims)   # a held claim that does not parse moves nothing
    return [c.to_dict() for c in pending_store._repoint(claims, sanitize_id(line.name), target_slug)]


def apply_rows(bank_path_: Path, rows: list[dict], *, skip_lines=(), check: bool = False) -> Result:
    """Write the reviewed rows onto the pending store (and the doubt pairs of a person of its own). The caller holds the
    bank's admission and lock and commits ``Result.paths``."""
    bank_path_ = Path(bank_path_)
    result = Result()
    entries = pending_store.load(bank_path_)
    bank = load(bank_path_)
    pairs: list[tuple[str, str]] = []
    changed = False
    for row in rows:
        result.rows += 1
        action = row.get("action")
        if row.get("strike") or row.get("line") in set(skip_lines):
            result.skip("struck")
            continue
        if action not in ("rename_bare", "to_page", "merge_line", "new_person"):
            result.skip("left_alone")
            continue
        line = next((e for e in entries if e.name == row.get("line")), None)
        if line is None:
            result.skip("line_missing")
            continue
        if line_state(line) != row.get("state"):
            result.skip("changed_since_plan")
            continue
        stem = snp.stem_of(line.name)
        if stem is None or line.type != "person":
            result.skip("not_qualified")
            continue
        names = {e.name.lower(): e for e in entries if e is not line}
        pages = {p["id"]: p for p in bank.pages}
        written, slug = line.name, sanitize_id(stem[0])
        old = sanitize_id(line.name)
        target = str(row.get("target") or "")
        if action == "rename_bare":
            if slug in pages or stem[0].lower() in names or any(sanitize_id(n) == slug for n in names):
                result.skip("target_appeared")
                continue
            line.held_claims = _repointed(line, slug)
            line.name = stem[0]
            line.aliases = _aliases(line, written)
        elif action == "to_page":
            page = pages.get(target)
            if page is None or str(page["frontmatter"].get("type") or "").lower() != "person":
                result.skip("page_gone")
                continue
            title = str(page["frontmatter"].get("name") or target)
            new_name = title if sanitize_id(title) == target else target
            if new_name.lower() in names:
                result.skip("target_appeared")
                continue
            line.held_claims = _repointed(line, target)
            line.name = new_name
            line.aliases = _aliases(line, written)
            line.title = title if new_name != title else ""
        elif action == "merge_line":
            into = names.get(target.lower())
            if into is None or into.type != "person":
                result.skip("line_gone")
                continue
            moving = pending_store.PendingEntity.from_dict(line.to_dict())
            moving.held_claims = _repointed(line, sanitize_id(into.name))
            moving.aliases = _aliases(moving, written)
            held = pending_store._merged(moving.held_claims, into.held_claims)
            pending_store._carry(moving, into)
            into.held_claims = held
            into.aliases = _aliases(into, *moving.aliases)
            entries = [e for e in entries if e is not line]
            result.applied[action] = result.applied.get(action, 0) + 1
            changed = True
            continue
        else:   # new_person
            taken = {sanitize_id(e.name) for e in entries} | set(pages)
            new_id = snp.free_id(slug, taken)
            line.held_claims = _repointed(line, new_id)
            line.name = new_id
            line.aliases = _aliases(line, written)
            line.title = stem[0]
            others = {slug, *(str(c) for c in row.get("compared") or [])} - {new_id}
            for other in sorted(others):
                pairs.append((new_id, other))
        result.applied[action] = result.applied.get(action, 0) + 1
        changed = True
    if changed and not check:
        pending_store.save(bank_path_, entries)
        result.paths.append(pending_store.PENDING_STORE_FILE)
        if pairs:
            doubt = [p for p in pairs]
            if same_name_doubts.add_pairs(bank_path_, doubt):
                result.paths.append(same_name_doubts.FILE)
    return result


def commit_message(result: Result) -> tuple[str, list[str]]:
    n = sum(result.applied.values())
    return (f"People held under a qualified name placed: {n} line(s)",
            [f"{rel}: a held person written \"Name (qualifier)\" placed as a mention of the bare name (trigger: {TRIGGER})"
             for rel in result.paths])
