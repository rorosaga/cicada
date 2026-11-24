"""A one-time sweep for people a memory holds under a qualified name (G148, owner 2026-11-24): never a join, no model call.

Before #846 a conversation naming two people of one first name ("Nico from work finally met my cousin Nico") left each
waiting on a held line titled with the qualifier ("Nico (finance lead)"), never matched to the Nico who already has a
page. #846 treats such a person as a mention of the bare name from now on; a line already held stays as it is.

**This is a repair of an old shape, not a second place where people get joined.** Sleep already has the machinery that
joins two people of one name or keeps them apart, on located evidence, with two reads and an undo
(`same_name_people`, `same_name_tend`, ruling 74a). The sweep only turns an old line into the shape Stage 2 writes today
and lets that machinery decide later:

* a line written ``Name (qualifier)`` becomes a person held under the bare name **as a second person in doubt**: a free
  ``<name>-2`` key, the bare name as its title (`same_name_people.free_id`; ``entity_resolver._pending_line``'s own shape),
  the written name kept as an alias, its held claims kept on its own id (`pending_store._repoint`), and a doubt recorded
  against every page and every other held line that answers to the bare name, by name OR alias
  (`entity_resolver._record_doubt_pairs`, the live writer);
* only when nothing else in the bank answers to the bare name is the line simply renamed to the bare name, as Stage 2
  sends a lone qualified mention (the written name kept as an alias).

It never renames a line onto a page's id, never merges two lines, never calls a model. Every exclusion Stage 2 applies
before it treats a qualified name as a mention of the bare name is Stage 2's own function (`entity_resolver.same_name_skip`).

**Plan** (:func:`plan_rows`, no model, writes nothing) shows every line: its own words, what it will be titled, and each page
or line it will be held in doubt against, with that page's first summary sentence and status. **Apply**
(:func:`apply_rows`) derives the plan again from the bank as it is now and writes a row only when it comes out the same
(a hash over the line AND everything it is held against): anything that changed since the plan is skipped and counted.

Pages titled with a qualifier are counted and listed, never changed: moving a page is the page join's, which has its own undo.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from api.services import (
    agent_engine, entity_body, entity_resolver, markdown_parser, media_pages, owner_identity, pending_store,
    people_directory, role_people, same_name_doubts, same_name_people as snp,
)
from api.services.claims import Claim, strip_claims_block
from api.services.id_utils import sanitize_id

TRIGGER = "maintenance/name-sweep"
VERSION = 2
RENAME, HOLD, LEAVE = "rename_bare", "hold_in_doubt", "leave"
#: The two files a name row writes. Apply refuses a bank where either has uncommitted changes (never swept in).
FILES = (pending_store.PENDING_STORE_FILE, same_name_doubts.FILE)

_WHY = {
    "handle": "a handle the record paired",
    "speaker": "a self-reference",
    "owner_first_name": "the owner's first name",
    "not_bare": "not one bare name",
    "label_only": "a label, not a person",
    "runtime_path": "a runtime path",
    "unnamed": "a person known only by a relation",
    "correspondent": "a message correspondent",
    "address_book_card": "an address-book card",
}


# --------------------------------------------------------------------------- reading the bank


@dataclass
class Bank:
    pages: list[dict] = field(default_factory=list)       # {"id", "frontmatter", "body"}
    lines: list = field(default_factory=list)             # PendingEntity
    owner_id: str | None = None
    owner_name: str = ""
    path: Path | None = None
    refs: object = None
    open_questions: set = field(default_factory=set)

    @property
    def owner_first(self) -> list[str]:
        return self.owner_name.split()[:1]


def _open_question_names(bank: Path) -> set[str]:
    """What an open inbox question names (an entity id or a name, lower case): a line a question is about is left alone."""
    out: set[str] = set()
    folder = Path(bank) / "inbox"
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            fm = markdown_parser.parse(path).frontmatter or {}
        except Exception:  # noqa: BLE001
            continue
        if str(fm.get("status") or "pending") in ("resolved", "answered", "dismissed", "done"):
            continue
        for key in ("entity_id", "entity_name", "name", "merge_target_hint"):
            if fm.get(key):
                out.add(str(fm[key]).strip().lower())
        for key in ("covered", "entity_ids", "pages"):
            for item in fm.get(key) or []:
                out.add(str(item.get("entity_id") if isinstance(item, dict) else item).strip().lower())
    return out


def load(bank: Path) -> Bank:
    out = Bank(lines=pending_store.load(bank), path=Path(bank))
    for path in sorted((Path(bank) / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - an unreadable page is left alone
            continue
        out.pages.append({"id": path.stem, "frontmatter": parsed.frontmatter or {}, "body": parsed.body})
    out.owner_id = owner_identity.owner_page_id(out.pages, Path(bank), None)
    owner = next((p for p in out.pages if p["id"] == out.owner_id), None)
    out.owner_name = str(((owner or {}).get("frontmatter") or {}).get("name") or "")
    out.refs = owner_identity.self_references(out.pages, None, Path(bank), None)
    out.open_questions = _open_question_names(bank)
    return out


def qualified_pages(bank: Bank) -> list[str]:
    """Person pages titled ``Name (qualifier)``: counted and listed, never changed here."""
    return [p["id"] for p in bank.pages
            if str(p["frontmatter"].get("type") or "").lower() == "person"
            and str(p["frontmatter"].get("status") or "") != "dropped"
            and snp.stem_of(str(p["frontmatter"].get("name") or "")) is not None]


def _fold(text) -> str:
    return people_directory.fold(text)


def _sentence(text: str, limit: int = 240) -> str:
    text = " ".join(str(text or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return (m.group(1) if m else text)[:limit]


def _page_says(page: dict) -> str:
    body = strip_claims_block(page.get("body") or "")
    summary = entity_body.parse_sections(body).get("Summary") or ""
    if not summary.strip():
        summary = next((ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")), "")
    return _sentence(summary)


def _line_says(line) -> str:
    return _sentence(line.summary or line.description or (line.key_facts[0] if line.key_facts else ""))


# --------------------------------------------------------------------------- who answers to a bare name


@dataclass(frozen=True)
class Against:
    """A person (or a thing) that answers to the bare name, as the review shows it and the binding hash sees it."""

    kind: str          # "page" | "line"
    ref: str           # the page's id, the line's name
    name: str          # how it is titled
    status: str
    says: str          # its first summary sentence
    how: str           # "name", "alias", "id" or "same name, written with a qualifier"
    fingerprint: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "name": self.name, "status": self.status, "says": self.says, "how": self.how}


def _digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _page_against(page: dict, how: str) -> Against:
    fm = page["frontmatter"]
    status = str(fm.get("status") or "active")
    says = _page_says(page)
    aliases = sorted(str(a) for a in fm.get("aliases") or [])
    return Against("page", page["id"], str(fm.get("name") or page["id"]), status, says, how,
                   _digest("page", page["id"], fm.get("name"), aliases, fm.get("type"), status, bool(fm.get("owner")), says))


def _line_against(line, how: str) -> Against:
    says = _line_says(line)
    return Against("line", line.name, line.title or line.name, "held (below the bar)", says, how,
                   _digest("line", line.name, line.title, sorted(line.aliases), line.type, line.episodes(), says))


def answering(bank: Bank, stem: str, group: set[str]) -> list[Against] | None:
    """Everything in the bank that answers to the bare name ``stem`` (a person or owner page by title, alias or id; a held
    line by name, title, alias or key; a held line written with a qualifier of the same bare name that this sweep leaves
    alone), except the lines in ``group``. ``None`` when the name is not for this rule: the owner's page, a nickname or a
    relation bears it, or a page that is not a person holds its key. The live rule's own read decides the title case
    (`entity_resolver._same_name_identities`)."""
    low, slug, folded = stem.lower(), sanitize_id(stem), _fold(stem)
    out: list[Against] = []
    same_title = [p for p in bank.pages if str(p["frontmatter"].get("name") or "").lower() == low
                  and str(p["frontmatter"].get("status") or "") != "dropped"
                  and not agent_engine.is_runtime_path(str(p["frontmatter"].get("name") or ""))]
    others = [ln for ln in bank.lines if ln.name not in group]
    if entity_resolver._same_name_identities(low, same_title, others, bank.owner_id, bank.path) is None:
        return None
    for page in bank.pages:
        fm = page["frontmatter"]
        if str(fm.get("status") or "") == "dropped" or media_pages.is_file_page(fm):
            continue
        name = str(fm.get("name") or "")
        aliases = {_fold(a) for a in fm.get("aliases") or [] if str(a).strip()}
        how = ("name" if name.lower() == low else "alias" if folded in aliases else "id" if page["id"] == slug else "")
        if not how:
            continue
        if fm.get("owner") or fm.get(role_people.NICKNAME_KEY) or fm.get(role_people.UNNAMED_KEY) or page["id"] == bank.owner_id:
            return None
        if str(fm.get("type") or "").lower() != "person":
            return None   # a page of another kind holds the key: not for a person line to sit beside
        out.append(_page_against(page, how))
    for line in others:
        if line.type != "person":
            continue
        qualified = snp.stem_of(line.name)
        aliases = {_fold(a) for a in line.aliases if str(a).strip()}
        if line.name.lower() == low or sanitize_id(line.name) == slug:
            how = "name"
        elif (line.title or "").lower() == low:
            how = "title"
        elif folded in aliases:
            how = "alias"
        elif qualified is not None and qualified[0].lower() == low:
            how = "same name, written with a qualifier"
        else:
            continue
        out.append(_line_against(line, how))
    return sorted(out, key=lambda a: (a.kind, a.ref))


# --------------------------------------------------------------------------- the lines


def skip_reason(bank: Bank, line) -> str | None:
    """Why a held line written with a qualifier is not swept (``None``: it is). Stage 2's own exclusions first."""
    if line.type != "person":
        return "not a person"
    stem = snp.stem_of(line.name)
    if stem is None:
        return "not written with a qualifier"
    why = entity_resolver.same_name_skip(line.name, {"type": line.type, "name": line.name}, bank.refs, bank.owner_first)
    if why is not None:
        return _WHY.get(why, why)
    if bank.owner_first and _fold(stem[0]) == _fold(bank.owner_first[0]):
        return _WHY["owner_first_name"]
    if line.correspondent:
        return _WHY["correspondent"]
    if line.apart:
        return "the person said it is not a page"
    if {sanitize_id(line.name), line.name.lower(), sanitize_id(line.name).lower()} & bank.open_questions:
        return "an open question names it (answer or dismiss that first)"
    return None


def census(bank: Bank) -> dict:
    left: dict[str, int] = {}
    swept = 0
    for line in bank.lines:
        if line.type == "person" and snp.stem_of(line.name) is not None:
            why = skip_reason(bank, line)
            if why:
                left[why] = left.get(why, 0) + 1
            else:
                swept += 1
    return {"lines": swept, "left_alone_by_reason": dict(sorted(left.items())),
            "pages_titled_with_a_qualifier": len(qualified_pages(bank))}


def _day(line) -> str:
    days = [str(h.get("day") or h.get("timestamp") or "")[:10] for h in line.heard_in if isinstance(h, dict)]
    days = [d for d in days if d]
    if not days and line.source_episode.startswith("ep_"):
        days = [line.source_episode[3:13]]
    return min(days) if days else ""


def plan_rows(bank: Bank) -> list[dict]:
    """The row of every held person line written with a qualifier: what it will be, and what it is held against. No model."""
    rows: list[dict] = []
    by_stem: dict[str, list] = {}
    for line in bank.lines:
        if line.type == "person" and snp.stem_of(line.name) is not None:
            by_stem.setdefault(snp.stem_of(line.name)[0].lower(), []).append(line)
    taken = {sanitize_id(ln.name) for ln in bank.lines} | {p["id"] for p in bank.pages}
    for low, lines in sorted(by_stem.items()):
        stem = snp.stem_of(lines[0].name)[0]
        group = sorted((ln for ln in lines if skip_reason(bank, ln) is None), key=lambda ln: (_day(ln), ln.name))
        for line in lines:
            why = skip_reason(bank, line)
            if why is not None:
                rows.append(_row(line, LEAVE, f"left as it is: {why}"))
        if not group:
            continue
        found = answering(bank, stem, {ln.name for ln in group})
        if found is None:
            for line in group:
                rows.append(_row(line, LEAVE, "left as it is: the owner's page, a nickname, a relation or a page that is not a "
                                              "person bears this name"))
            continue
        if not found and len(group) == 1:
            line = group[0]
            slug = sanitize_id(stem)
            rows.append({**_row(line, RENAME, ""), "new_name": stem, "state": _digest(line.to_dict(), [], slug)})
            continue
        siblings = {ln.name: _line_against(ln, "same name, written with a qualifier") for ln in group}
        ids: dict[str, str] = {}
        for line in group:
            new_id = snp.free_id(sanitize_id(stem), taken)
            taken.add(new_id)
            ids[line.name] = new_id
        for line in group:
            against = [*found, *(a for name, a in siblings.items() if name != line.name)]
            rows.append({**_row(line, HOLD, ""), "new_id": ids[line.name], "title": stem,
                         "against": [a.to_dict() for a in against],
                         "also_new": sorted(i for n, i in ids.items() if n != line.name),
                         "state": _digest(line.to_dict(), [a.fingerprint for a in against], ids[line.name])})
    return rows


def _row(line, action: str, reason: str) -> dict:
    return {"v": VERSION, "pass": "names", "line": line.name, "strike": False, "action": action, "reason": reason,
            "alias": line.name, "says": _line_says(line), "facts": len(line.key_facts), "held_claims": len(line.held_claims),
            "episodes": line.episodes(), "state": _digest(line.to_dict()), "against": []}


def review_text(rows: list[dict]) -> str:
    out: list[str] = []
    order = {HOLD: 0, RENAME: 1, LEAVE: 2}
    for row in sorted(rows, key=lambda r: (order.get(r["action"], 3), str(r.get("line")))):
        head = f"## {row['line']}"
        if row["action"] == HOLD:
            head += f"  -> held under the name \"{row['title']}\" as a second person in doubt (key {row['new_id']})"
        elif row["action"] == RENAME:
            head += f"  -> renamed to \"{row['new_name']}\": nobody else in the bank answers to that name"
        else:
            head += "  -> left as it is"
        out.append(head + ("  [STRUCK]" if row.get("strike") else ""))
        out.append(f"    this line says: {row.get('says') or '(nothing recorded)'}")
        out.append(f"    holds {row.get('facts', 0)} fact(s), {row.get('held_claims', 0)} held claim(s), "
                   f"conversations {', '.join(row.get('episodes') or []) or '(none)'}")
        if row["action"] == HOLD:
            out.append(f"    the written name \"{row['alias']}\" stays as an alias; its claims stay on {row['new_id']}")
            out.append("    held in doubt against (Sleep decides later; nothing is joined here):")
            for a in row.get("against") or []:
                out.append(f"      - {a['kind']} {a['ref']} \"{a['name']}\" [{a['status']}] answers by {a['how']}: "
                           f"{a.get('says') or '(nothing recorded)'}")
            for other in row.get("also_new") or []:
                out.append(f"      - the other line(s) of this name made a second person now: {other}")
        elif row["action"] == RENAME:
            out.append(f"    the written name \"{row['alias']}\" stays as an alias; nothing else answers to the bare name")
        if row.get("reason"):
            out.append(f"    {row['reason']}")
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- apply


@dataclass
class Result:
    rows: int = 0
    applied: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list = field(default_factory=list)
    pairs: list = field(default_factory=list)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def counts(self) -> dict:
        return {"lines_in_plan": self.rows, "applied": dict(sorted(self.applied.items())),
                "skipped": dict(sorted(self.skipped.items())), "doubt_pairs": len(self.pairs)}


def dirty_files(bank_path) -> frozenset[str] | None:
    """The files a name row writes that have uncommitted changes; ``None`` when git cannot say (no repository)."""
    from api.services import git_service

    if not (Path(bank_path) / ".git").exists():
        return None
    try:
        return frozenset(p for p in git_service.dirty_paths_sync(Path(bank_path), *FILES) if p in FILES)
    except git_service.GitError:
        return None


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


def apply_rows(bank_path, rows: list[dict], *, skip_lines=(), check: bool = False, remember=lambda path: None) -> Result:
    """Write the reviewed rows onto the pending store and record the doubts (the caller holds the bank's admission and
    lock, refuses a bank with a dirty store, and commits ``Result.paths``). The plan is derived again from the bank as it
    is now: a row whose line, or anything the line is held against, differs from the plan's is skipped and counted.
    ``remember(path)`` is told each file before it is first written (the caller's way back from a failure)."""
    bank_path = Path(bank_path)
    result = Result()
    skip = set(skip_lines)
    now = {r["line"]: r for r in plan_rows(load(bank_path))}
    entries = pending_store.load(bank_path)
    changed, pairs, applied_ids = False, [], {}
    wanted = []
    for row in rows:
        result.rows += 1
        if row.get("strike") or row.get("line") in skip:
            result.skip("struck")
        elif row.get("action") not in (RENAME, HOLD):
            result.skip("left_alone")
        else:
            wanted.append(row)
    for row in wanted:
        fresh = now.get(row["line"])
        if fresh is None:
            result.skip("line_missing")
            continue
        if fresh["action"] != row["action"] or fresh["state"] != row.get("state") or fresh.get("new_id") != row.get("new_id"):
            result.skip("changed_since_plan")
            continue
        line = next((e for e in entries if e.name == row["line"]), None)
        if line is None:
            result.skip("line_missing")
            continue
        written, stem = line.name, snp.stem_of(line.name)
        if stem is None:
            result.skip("not_qualified")
            continue
        if fresh["action"] == RENAME:
            slug = sanitize_id(stem[0])
            line.held_claims = _repointed(line, slug)
            line.name = stem[0]
            line.aliases = _aliases(line, written)
        else:
            new_id = fresh["new_id"]
            line.held_claims = _repointed(line, new_id)
            line.name = new_id
            line.aliases = _aliases(line, written)
            line.title = stem[0]
            applied_ids[written] = (new_id, fresh)
        result.applied[fresh["action"]] = result.applied.get(fresh["action"], 0) + 1
        changed = True
    for written, (new_id, fresh) in applied_ids.items():
        # Against every page and line that answers to the bare name (a line still written with a qualifier is either made a
        # second person by this same run, below, or left as it is: no pair is held against its old key), the bare name's
        # own key, and every other line this run made a second person.
        against = {sanitize_id(a["ref"]) for a in fresh.get("against") or []
                   if not (a["kind"] == "line" and snp.stem_of(a["ref"]) is not None)}
        against.add(sanitize_id(snp.stem_of(written)[0]))
        against |= {i for w, (i, _f) in applied_ids.items() if w != written}
        pairs += [tuple(sorted((new_id, other))) for other in sorted(against) if other != new_id]
    result.pairs = sorted(set(pairs))
    if changed and not check:
        before = same_name_doubts_bytes(bank_path)
        remember(bank_path / pending_store.PENDING_STORE_FILE)
        pending_store.save(bank_path, entries)
        result.paths.append(pending_store.PENDING_STORE_FILE)
        if result.pairs:
            remember(bank_path / same_name_doubts.FILE)
            entity_resolver._record_doubt_pairs(bank_path, result.pairs)   # the live writer: records and flags
            if same_name_doubts_bytes(bank_path) != before:
                result.paths.append(same_name_doubts.FILE)
    return result


def same_name_doubts_bytes(bank_path) -> bytes | None:
    path = Path(bank_path) / same_name_doubts.FILE
    return path.read_bytes() if path.is_file() else None


def commit_message(result: Result) -> tuple[str, list[str]]:
    n = sum(result.applied.values())
    return (f"People held under a qualified name turned into the shape Sleep writes today: {n} line(s)",
            [f"{rel}: a held person written \"Name (qualifier)\" held as a second person in doubt, or renamed to the bare "
             f"name when nobody else answers to it; nothing joined (trigger: {TRIGGER})" for rel in result.paths])
