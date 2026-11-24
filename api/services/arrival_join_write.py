"""What the arrival join writes, how it is recorded, and how the person takes it back (plan 3.5 and 3.6, G245).

`arrival_join` decides; this module is the only thing that ever writes for it, and only when `arrival_join.LIVE` says so. It is
built and tested whole (an end-to-end run on scratch banks forces ``LIVE`` on in the test only) so the day the coordinator's
per-item reading of the real bank flips the one constant, nothing else has to be written.

**What it writes (Route D, a page exists).** The join IS the alias: the arrival's full name is added to the first-name page's
``aliases`` — one ``cicada`` commit, trigger ``sleep/arrival-join``, its own path only, restored if it fails. The title stays; no
claim moves, no history is rewritten, no page is made. The consequences come from the existing rematches, the same night, each
in its own commit: the LinkedIn rematch matches every page by name or alias, and an alias-only match attaches the profile link
as a PROPOSED source (`linkedin_people.basis` is ``alias``; never a confident link, so no photo request leaves the Mac until the
person takes it — `person_photo.is_own_account`); the Contacts rematch attaches the card's sources and photo. A final step,
:func:`finish`, runs after both and records which commits the join caused.

**Where the state lives: in the bank**, so a handed-over or moved bank keeps its undo. The page's own frontmatter carries
``arrival_joins`` — ``[{id, alias_key, refs, kinds, days, delta, on, state, commits, claims, sources, contacts}]``: the page, a
hash of the folded full name, the directory rows' hashes, both days, the commits the join caused, the claim ids it wrote, and a
hash of each source link it added. Never a name, a company, a headline, a link or an e-mail of a directory row; the alias
itself is on the page as every alias is, and the History line reads it from there.

**Undone** by :func:`undo` (``POST /entities/{id}/arrival-join/undo``, "Not them"): in one commit set, the alias leaves through
the removed-alias record; the join's attaches go (the LinkedIn source through its tombstone and the claims it wrote closed by
id; the Contacts entries through the refusal rows, so the next sync does not put them back); the pair is refused — against the
page of that name when one exists now, else by the holder and a hash of the name (`merge_rejections.add_arrival_refusal`); the
record says ``undone`` and the commit carries ``Undoes: <sha>`` for every commit the record lists. If the person edited the
alias or took a source since, the undo writes nothing and says which alias, source and claims remain, each by id.

**A later page can never re-join the pair.** :func:`promote_refusals` (the nightly step, before the same-name review slot where
74 / 74a / 74b run) turns each refusal whose full name now belongs to a page into a refused PAIR of pages
(`merge_rejections.add_rejected`), which every other joiner already honours.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import (alias_policy, arrival_join, bank_index, fact_sources, git_service, markdown_parser, merge_rejections,
                          page_edits, page_lock, people_directory)
from api.services.claims import parse_claims, write_claims

KEY = "arrival_joins"
SUBJECT_JOIN = "Arrival join"
SUBJECT_UNDO = "Undid an arrival join"
SUBJECT_RECORD = "Arrival join recorded"
UNDOES = "Undoes: "
TRIGGER_UNDO = "user/companion_app"
JOINED, UNDONE = "joined", "undone"
MAX_RECORDS = 20
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


class UndoError(ValueError):
    """An undo refused, with a sentence the person can read and the HTTP status it answers."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _hash(text) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def _path(memory_path: Path, page: str) -> Path:
    return Path(memory_path) / "entities" / f"{page}.md"


def _invalidate(memory_path: Path) -> None:
    import os

    from api.services import page_redirects

    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))
    page_redirects.invalidate()


def records(fm: dict) -> list[dict]:
    raw = (fm or {}).get(KEY)
    return [dict(r) for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def latest(fm: dict, state: str | None = None) -> dict | None:
    rows = [r for r in records(fm) if state is None or r.get("state") == state]
    return rows[-1] if rows else None


def alias_of(fm: dict, record: dict) -> str | None:
    """The alias on the page that this record's hash names (the join's own name), or None if it is no longer there as written."""
    for a in fm.get("aliases") or []:
        if isinstance(a, str) and arrival_join.key_hash(people_directory.fold(a)) == record.get("alias_key"):
            return a
    return None


def name_of(fm: dict, record: dict) -> str | None:
    """The full name a record joined, from the page's own words: its alias while joined, else the removed-alias row that
    names it once the person said "Not them". None when neither is there."""
    alias = alias_of(fm, record)
    if alias:
        return alias
    for row in fm.get(page_edits.ALIASES_REMOVED) or []:
        name = row.get("alias") if isinstance(row, dict) else row
        if isinstance(name, str) and arrival_join.key_hash(people_directory.fold(name)) == record.get("alias_key"):
            return name
    return None


# --------------------------------------------------------------------------- the display name (read back, never stored apart from the alias)


def display_name(memory_path: Path, refs, kinds) -> str | None:
    """The arrival's full name as its directory spells it, read back by the row hashes (a connection's id, a card's hashed id)
    through the public readers. A connection's spelling wins over a card's. None when the row is no longer in a directory."""
    from api.services import contacts_local, linkedin_people

    refs = set(refs)
    bank = Path(memory_path).name
    for a in linkedin_people.arrivals(memory_path, bank):
        if a.id in refs and a.connection.first and a.connection.last:
            return a.name
    for card in contacts_local.load_waiting(bank):
        if contacts_local.card_hash(card["id"]) in refs:
            name = contacts_local.card_name(card)
            if len(name.split()) > 1:
                return name
    return None


# --------------------------------------------------------------------------- the join


@dataclass
class Applied:
    page: str
    path: str
    record_id: str


def _snapshot(memory_path: Path, fm: dict, body: str) -> tuple[list[str], list[str]]:
    """``(the LinkedIn claim ids on the page, a hash of every source link)`` before the join — what :func:`finish` diffs to
    learn what the join's consequences wrote."""
    try:
        from api.services import linkedin_people

        claims = [c.id for c in parse_claims(body) if c.observer == linkedin_people.OBSERVER]
    except Exception:  # noqa: BLE001
        claims = []
    sources = [_hash(s.get("ref")) for s in fact_sources.as_sources(fm.get("sources")) if s.get("ref")]
    return claims, sources


def apply_join(memory_path: Path, decision, *, today: str | None = None, skip: frozenset[str] = frozenset()) -> Applied | None:
    """Add the arrival's full name to the first-name page and record the join, in memory-relative path ``entities/<id>.md``
    (the caller commits it alone). Nothing is written, and None returned, when the page is dirty (in ``skip``), has changed
    since the decision (no longer one word, now archived or carrying a full-name alias already), the name is no longer in a
    directory, or the writer refuses it. Never a page created, never a title moved."""
    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    rel = f"entities/{decision.page}.md"
    if rel in skip:
        return None
    name = display_name(memory_path, decision.refs, decision.kinds)
    if not name or arrival_join.key_hash(people_directory.fold(name)) != decision.alias_key:
        return None
    if not alias_policy.admits(name) or alias_policy.names_another_page(name, decision.page, memory_path / "entities"):
        return None
    path = _path(memory_path, decision.page)
    with page_lock.page_lock(memory_path):
        if not path.is_file():
            return None
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        owners = arrival_join._owner_ids(memory_path)
        if arrival_join.holder_block(fm, decision.page, owners):
            return None
        aliases = [a for a in fm.get("aliases") or [] if isinstance(a, str)] if isinstance(fm.get("aliases"), list) else []
        if any(len(people_directory.fold(a).split()) > 1 for a in aliases):
            return None
        if people_directory.fold(name) in page_edits.removed_aliases(fm) or any(
                arrival_join.key_hash(people_directory.fold(a)) == decision.alias_key for a in aliases):
            return None
        claims, sources = _snapshot(memory_path, fm, parsed.body)
        record = {"id": _hash(f"{decision.page}\x00{decision.alias_key}\x00{today}"), "alias_key": decision.alias_key,
                  "refs": list(decision.refs), "kinds": list(decision.kinds),
                  "days": {"holder": decision.holder_day, "arrival": decision.arrival_day}, "delta": decision.delta,
                  "on": today, "state": JOINED, "commits": [], "pre": {"claims": claims, "sources": sources}}
        fm["aliases"] = [*aliases, name]
        fm[KEY] = [*[r for r in records(fm) if r.get("alias_key") != decision.alias_key][-(MAX_RECORDS - 1):], record]
        markdown_parser.write(path, fm, parsed.body)
    _invalidate(memory_path)
    return Applied(decision.page, rel, record["id"])


def commit_message(page: str, decision, today: date) -> str:
    """The join commit: page id, both days and the gap — never a directory row's name, company, headline, link or e-mail."""
    lines = [f"entities/{page}.md: updated (source: n/a, trigger: {arrival_join.TRIGGER})",
             "", f"Reason: the same first name, new the same week ({decision.delta} days apart; "
                 f"{decision.holder_day} and {decision.arrival_day})"]
    return git_service.build_commit_message(f"{SUBJECT_JOIN} {today.isoformat()}", lines, authors=["cicada"])


def restore(memory_path: Path, rel: str) -> None:
    """Undo a join whose commit failed, so no later ``git add -A`` sweeps it under another author."""
    memory_path = Path(memory_path)
    if (memory_path / ".git").exists():
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", rel)
        except git_service.GitError as exc:
            logger.warning(f"Arrival join restore failed: {type(exc).__name__}")
    _invalidate(memory_path)


# --------------------------------------------------------------------------- the record, once the rematches have run


def _git(memory_path: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(memory_path), *args], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def commits_caused(memory_path: Path, page: str) -> list[str]:
    """The join's own commit and the rematch commits since that touched this page (``sleep/linkedin-connections``,
    ``sleep/contacts``), oldest first. Read from git; empty without it."""
    if not (Path(memory_path) / ".git").exists():
        return []
    rows = _git(memory_path, "log", "-n", "40", "--format=%H%x1f%s%x1f%b%x1e", "--", f"entities/{page}.md").split("\x1e")
    found: list[tuple[str, str]] = []
    for row in rows:
        parts = row.strip("\n").split("\x1f")
        if len(parts) >= 2 and parts[0].strip():
            found.append((parts[0].strip(), parts[1] + "\n" + (parts[2] if len(parts) > 2 else "")))
    found.reverse()
    out: list[str] = []
    joined = False
    for sha, text in found:
        if text.startswith(SUBJECT_JOIN) and not text.startswith(SUBJECT_UNDO) and not text.startswith(SUBJECT_RECORD):
            joined, out = True, [sha]
        elif joined and ("trigger: sleep/linkedin-connections" in text or "trigger: sleep/contacts" in text):
            out.append(sha)
    return out


def finish(memory_path: Path, *, today: str | None = None) -> list[str]:
    """After the two rematches: for each joined record not yet finished, note the commits the join caused, the claim ids and
    source hashes written since the join, and drop the pre-join snapshot. Returns the memory-relative paths written (the
    caller commits them alone). Nothing to do — nothing written — unless a join is on record."""
    memory_path = Path(memory_path)
    written: list[str] = []
    for f in bank_index.files(memory_path, "entities"):
        fm0 = f.frontmatter or {}
        if not any(r.get("state") == JOINED and "pre" in r for r in records(fm0)):
            continue
        path = _path(memory_path, f.stem)
        with page_lock.page_lock(memory_path):
            parsed = markdown_parser.parse(path)
            fm = dict(parsed.frontmatter)
            rows = records(fm)
            changed = False
            for r in rows:
                if r.get("state") != JOINED or "pre" not in r:
                    continue
                pre = r.pop("pre") or {}
                try:
                    from api.services import linkedin_people

                    now_claims = [c.id for c in parse_claims(parsed.body) if c.observer == linkedin_people.OBSERVER]
                except Exception:  # noqa: BLE001
                    now_claims = []
                r["claims"] = [c for c in now_claims if c not in set(pre.get("claims") or [])]
                before = set(pre.get("sources") or [])
                added = [s for s in fact_sources.as_sources(fm.get("sources")) if s.get("ref") and _hash(s["ref"]) not in before]
                r["sources"] = [_hash(s["ref"]) for s in added]
                r["contacts"] = bool(fm.get("contacts_photo")) or any(str(s.get("ref")).startswith("addressbook://") for s in added)
                r["commits"] = commits_caused(memory_path, f.stem)
                changed = True
            if changed:
                fm[KEY] = rows
                markdown_parser.write(path, fm, parsed.body)
                written.append(f"entities/{f.stem}.md")
    if written:
        _invalidate(memory_path)
    return written


def record_commit_message(paths: list[str], today: date) -> str:
    lines = [f"{p}: updated (source: n/a, trigger: {arrival_join.TRIGGER})" for p in paths]
    return git_service.build_commit_message(f"{SUBJECT_RECORD} {today.isoformat()}", lines, authors=["cicada"])


# --------------------------------------------------------------------------- a refusal that becomes a pair of pages


def promote_refusals(memory_path: Path) -> list[str]:
    """Each "Not them" kept by (holder, hash of the name) whose full name now belongs to a person page becomes a refused PAIR
    of pages (`merge_rejections.add_rejected`) — the one thing every joiner (ruling 74's two signals, 74a, 74b, the dedup
    sweep) already honours — and leaves the arrival list. Returns the memory-relative paths written
    (``_merge_rejected.yaml``), for the caller to commit; ``[]`` and no read of any page when nobody was refused."""
    memory_path = Path(memory_path)
    rows = merge_rejections.arrival_refusals(memory_path)
    if not rows:
        return []
    by_key: dict[str, str] = {}
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "") != "person" or str(fm.get("status") or "") == "dropped":
            continue
        for label in people_directory.labels(fm, f.stem):
            folded = people_directory.fold(label)
            if len(folded.split()) > 1:
                by_key.setdefault(arrival_join.key_hash(folded), f.stem)
    changed = False
    for row in rows:
        page = by_key.get(row["key"])
        if page and page != row["holder"]:
            merge_rejections.add_rejected(memory_path, row["holder"], page)
            merge_rejections.drop_arrival_refusal(memory_path, row["holder"], row["key"])
            changed = True
    return [merge_rejections.FILE] if changed else []


# --------------------------------------------------------------------------- "Not them"


def _page_of_name(memory_path: Path, key: str, exclude: str) -> str | None:
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if f.stem == exclude or str(fm.get("type") or "") != "person" or str(fm.get("status") or "") == "dropped":
            continue
        if any(arrival_join.key_hash(people_directory.fold(x)) == key for x in people_directory.labels(fm, f.stem)
               if len(people_directory.fold(x).split()) > 1):
            return f.stem
    return None


def _remaining(memory_path: Path, fm: dict, body: str, record: dict) -> str:
    """The sentence a refused undo says: what is left on the page, each by id."""
    bits = []
    alias = alias_of(fm, record)
    bits.append("the name is on the page" if alias else "the name was changed or taken off by you")
    kept = [h for h in record.get("sources") or []]
    if kept:
        bits.append("source " + ", ".join(kept))
    after = [c.id for c in parse_claims(body) if (c.recorded_at or "") >= str(record.get("on") or "")
             and c.id not in set(record.get("claims") or [])]
    if after:
        bits.append("claims written since: " + ", ".join(after[:12]))
    return "; ".join(bits)


def undo(memory_path: Path, entity_id: str, *, author: str = "user", trigger: str = TRIGGER_UNDO, before=None,
         session: str | None = None, today: str | None = None) -> dict:
    """The person says "Not them". See the module docstring. ``{"commit", "restored": [], "removed": [], "page"}``; raises
    :class:`UndoError` with the sentence and status, writing nothing, when there is no join to take back (404), it was already
    taken back (409), or the person changed the name or a link since (409)."""
    memory_path = Path(memory_path)
    day = today or date.today().isoformat()
    path = _path(memory_path, entity_id)
    if not path.is_file():
        raise UndoError(f"No page '{entity_id}'.", 404)
    with page_lock.page_lock(memory_path):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        record = latest(fm, JOINED)
        if record is None:
            raise UndoError("Nothing to take back: this page has no name joined by Cicada." if not records(fm)
                            else "That join was already taken back.", 404 if not records(fm) else 409)
        alias = alias_of(fm, record)
        raw = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
        ours = set(record.get("sources") or [])
        mine = [s for s in raw if _hash(s.get("ref")) in ours]
        # a link the person took (trusted) or changed hands is theirs now, and a link that is gone was taken off by them
        taken = [s for s in mine if fact_sources.trusted(s) or str(s.get("added_by") or "").strip().lower() != fact_sources.CICADA]
        missing = ours - {_hash(s.get("ref")) for s in mine}
        if alias is None or taken or missing:
            raise UndoError("Nothing was undone: you changed this since Cicada made the join. Still there: "
                            + _remaining(memory_path, fm, parsed.body, record)
                            + ". Take what you do not want off the page yourself (its name, its link).", 409)
        # the alias leaves, and no automatic writer may add it back
        fm["aliases"] = [a for a in fm.get("aliases") or [] if a != alias]
        if not fm["aliases"]:
            fm.pop("aliases")
        removed = [r for r in fm.get(page_edits.ALIASES_REMOVED) or []] if isinstance(fm.get(page_edits.ALIASES_REMOVED), list) else []
        removed.append({"alias": alias, "by": author, "on": day})
        fm[page_edits.ALIASES_REMOVED] = removed[-page_edits.MAX_ALIASES_REMOVED:]
        # the claims the join's attaches wrote close, by id
        body = parsed.body
        if record.get("claims"):
            ids = set(record["claims"])
            claims = parse_claims(body, strict=True)
            for c in claims:
                if c.id in ids and not c.valid_to:
                    c.valid_to = day
            body = write_claims(body, claims)
        rows = records(fm)
        for row in rows:
            if row.get("id") == record.get("id"):
                row["state"], row["undone_on"] = UNDONE, day
        fm[KEY] = rows
        paths = [f"entities/{entity_id}.md"]
        # the Contacts entries leave through the refusal rows, so the next sync never puts them back; a LinkedIn link leaves
        # through its tombstone (`sources_removed`), which no import or rematch writes over
        from api.services import contacts_local

        tombs = [dict(r) for r in fm.get(fact_sources.REMOVED_KEY) or [] if isinstance(r, dict)]
        for s in mine:
            if str(s.get("ref") or "").startswith(contacts_local.REF_SCHEME):
                if contacts_local.remember_removal(memory_path, entity_id, s):
                    paths.append(contacts_local.REFUSED_FILE)
            else:
                tombs.append({"ref": str(s.get("ref")), "predicate": s.get("predicate") or "", "by": author, "at": day})
        if record.get("contacts"):
            fm.pop(contacts_local.FRONTMATTER_KEY, None)
            contacts_local.detach_photo(memory_path.name, entity_id)
        if tombs != [dict(r) for r in fm.get(fact_sources.REMOVED_KEY) or [] if isinstance(r, dict)]:
            fm[fact_sources.REMOVED_KEY] = tombs[-fact_sources.MAX_TOMBSTONES:]
        kept = [s for s in raw if not any(s is m for m in mine)]
        if kept:
            fm["sources"] = kept
        else:
            fm.pop("sources", None)
        markdown_parser.write(path, fm, body)
        # the pair is refused: against the page of that name when one exists now, else by name
        key = str(record.get("alias_key"))
        other = _page_of_name(memory_path, key, entity_id)
        if other:
            merge_rejections.add_rejected(memory_path, entity_id, other)
        else:
            merge_rejections.add_arrival_refusal(memory_path, entity_id, key, on=day)
        paths.append(merge_rejections.FILE)
        _invalidate(memory_path)
        commit = _commit_undo(memory_path, list(dict.fromkeys(paths)), record, trigger=trigger, author=author, session=session,
                              before=before)
    return {"kind": "arrival-undo", "page": entity_id, "commit": commit, "restored": [], "removed": []}


def _commit_undo(memory_path: Path, paths: list[str], record: dict, *, trigger: str, author: str, session, before) -> str | None:
    if not (memory_path / ".git").exists():
        return None
    lines = [f"{p}: updated (trigger: {trigger})" for p in paths]
    lines += ["", *[f"{UNDOES}{sha}" for sha in record.get("commits") or []],
              "Reason: you said this first name is not the person it was joined to"]
    message = git_service.build_commit_message(f"{SUBJECT_UNDO} {date.today().isoformat()}", lines, authors=[author],
                                               sessions=[session] if session else None)
    with git_service.write_lock(memory_path):
        git_service.commit_touched_sync(memory_path, message, paths, before=before,
                                        kept_subject=f"Uncommitted edit kept apart {date.today().isoformat()}",
                                        kept_trigger="user/kept-apart")
        out = _git(memory_path, "log", "-1", "--format=%H%x1f%s").strip()
    sha, _, subject = out.partition("\x1f")
    return sha if subject.startswith(SUBJECT_UNDO) else None


def joined_for(memory_path: Path) -> dict[str, dict]:
    """``{directory row hash: {page, name, on, delta, holderDay}}`` for every row an arrival join is standing on — what the connections list
    shows beside a row ("joined to <page>, undo"). Derived on read from the pages' own records."""
    out: dict[str, dict] = {}
    for f in bank_index.files(Path(memory_path), "entities"):
        for r in records(f.frontmatter or {}):
            if r.get("state") == JOINED:
                for ref in r.get("refs") or []:
                    out[str(ref)] = {"page": f.stem, "name": str((f.frontmatter or {}).get("name") or f.stem), "on": r.get("on"),
                                     "delta": r.get("delta"), "holderDay": (r.get("days") or {}).get("holder")}
    return out
