"""A first name still held below the promotion bar, born as the full name of the person who newly appeared the same week
(Route H of the arrival join; owner 2026-11-24, ruling 79 (c), G245).

The owner's own example: he met people at an event, connected with some of them that week, and wrote a few first names in a
note. A first name written once in one note normally has NO page — it is a line in the pending store (`pending_store`), below the
promotion bar — so `arrival_join`'s first route (a page of one word gets the full name as an alias) never sees it. This module is
the case in his example: the held first name and the one person of that given name who newly appeared in the same week are
joined **at the page's birth** — the page is made under the FULL name, the said form kept as an alias, the arrival attached, the
held line's own words and claims landing on it, in one write and one commit (the same move as a page one full-name mention of a
LinkedIn connection makes, `entity_resolver._connection_for`; the connection's link only PROPOSED, never confident, no photo or
service request).

**It decides with the same function.** A held line becomes a :class:`arrival_join.Holder` (``held=True``) and a case of the same
list `arrival_join.gather` returns; :func:`arrival_join.decide` applies every rule to it, unchanged — two namesakes, a stale
directory, a conflict, a veto, a doubt, a split, a relation title, the owner's own name — and `arrival_join.run_tail` pays the
two-read veto from the same night's bound and the same cache. This module only says what is different about a *line*:

* Its words must be the person's OWN, in a conversation of its own day: a marked turn of his (`entity_resolver._said_in_person_turn`,
  never an agent's reply, a relayed turn, a tab group, a calendar entry or a feed item) or his own unlocked note
  (`entity_resolver._said_in_own_note`), dated by `arrival_join.episode_day` (a note by its CREATED day, never its last edit; a
  save or a feed no day at all). The day is the earliest such conversation's; own words more than a week apart are a name that has
  been around, and have no day.
* Exactly one holder is counted over pages AND other lines (`arrival_join.carriers`).
* It is not a second person of one name (``title``), a name held against a page, a mention the person said is none of those
  pages, a message correspondent, a self-reference or the owner's own name, nor a relation word.

**Where it runs, and why not in the resolver.** The plan put it in `entity_resolver` where a name would be held. The directory
must have been looked at a week after the holder's day (rule 9) — so at the moment a name is held it is, by construction, never
yet fresh, and a decision there would refuse every note on the night it was written and never look again until the name was
mentioned a second time (when promotion would have made the page anyway). The tail re-reads every held line nightly, the way
Route D re-reads pages, so the join happens the first night the directory is fresh. The write is the same birth the resolver
makes, through the same page writer (`conflict_resolver.apply_changes`'s create).

**It ships deciding and reporting only: :data:`LIVE` is false** (separate from `arrival_join.LIVE`). With it false nothing is
written and a held name is held exactly as before; the night's report (`arrival_join.report_path`) carries the decision as an item
marked ``"route": "birth"`` — ``would_birth`` — by ids, days, hashes and counts, a held name by a hash, never a word. The write
and its undo are built whole and tested with the constant forced on in the test only.

**Undone** ("Not them", the same route and the same record as Route D, `arrival_join_write.undo`): the born page is ARCHIVED, not
deleted (its stamp ``archived_by`` records the status it had; the commit is in git), the said form leaves its aliases through the
removed-alias record, the connection's proposed link and the claims it wrote go (`arrival_join_write.detach`), the held line is put
back as it was in the commit before the birth (read from the bank's own history), and the pair — the held name and that page — is
refused for every later joiner (`merge_rejections.add_rejected`: the resolver's `_said_different` keeps the name from the page, 74
/ 74a / 74b and Route D honour the pair). If the person changed the name or took the link since, or the page has heard another
conversation since (so what is on it is no longer only what the birth put there), nothing is written and the sentence says what is
left.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from api.services import (alias_policy, arrival_join as aj, arrival_join_write as w, bank_index, fact_sources, git_service,
                          markdown_parser, merge_rejections, page_edits, page_lock, pending_store, people_directory)
from api.services.id_utils import sanitize_id

#: **The switch.** False: the held names are decided and reported (``would_birth``), nothing is written and every name stays held
#: exactly as today. A one-line change flips it, only on the coordinator's per-item reading of the real bank (plan 3.8).
LIVE = False

ARCHIVE_REASON = "arrival_birth"
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


# --------------------------------------------------------------------------- the held line as a holder (reads, never writes)


def _owner_words(pages: dict[str, dict], owners: set[str]) -> set[str]:
    """The folded names the owner's page answers to, and each one's first word: a line with one of them is the owner's own name."""
    words: set[str] = set()
    for stem, fm in pages.items():
        if stem in owners or fm.get("owner") is True:
            for label in aj._labels(fm, stem):
                folded = aj._fold(label)
                if folded:
                    words.add(folded)
                    words.add(folded.split()[0])
    return words


def held_block(line, word: str, owner_words: set[str]) -> str | None:
    """Rule 2 for a line: why this held name is not a first-name holder, or None. Pure."""
    from api.services import role_people

    if line.title:
        return "holder_second_of_name"           # the second person of one name waits for its own line (`same_name_people`)
    if line.held_against:
        return "holder_held_against"             # held against a page that bears its name: Stage 2's, never this
    if line.apart_pages():
        return "holder_apart"                    # the person said this mention is none of those pages
    if line.correspondent:
        return "holder_correspondent"            # a message conversation's other side has its own rules
    if not alias_policy.admits(line.name) or word in owner_words:
        return "holder_owner"                    # a self-reference ("me", "yo") or the owner's own given name
    if len(word) < aj.MIN_WORD:
        return "holder_short_word"
    try:
        if role_people.parse(line.name, bare=True):
            return "holder_role"
    except Exception:  # noqa: BLE001
        pass
    return None


def _theirs(memory_path: Path, episode: str, fm: dict, word: str) -> bool:
    """Is ``word`` in the person's OWN words in this conversation (3.3, 3.4 rule 2)? A note: their own unlocked note. Any other
    conversation: a marked turn of theirs. Never an agent's reply, a relayed turn, a save, a tab group, a calendar entry."""
    from api.services import entity_resolver as er

    try:
        if str(fm.get("origin") or fm.get("source") or "") in aj.NOTE_ORIGINS:
            return er._said_in_own_note(memory_path, episode, {word})
        return er._said_in_person_turn(memory_path, episode, None, keys={word}, mask_urls=True)
    except Exception:  # noqa: BLE001 - an unreadable conversation says nothing for the join
        return False


def held_day(memory_path: Path, line, word: str) -> tuple[str | None, str, list[str], str | None]:
    """``(day, kind, the conversations that dated it, a rule-2 refusal)`` of a held line: the earliest day of its conversations
    that count as time (`arrival_join.episode_day`) AND hold ``word`` in the person's own words. Several own conversations more
    than :data:`arrival_join.WINDOW_DAYS` apart are a name that has been around: no day. Dated conversations in none of which
    the person said it themselves refuse the line (``holder_not_own_words``)."""
    dated: list[tuple[str, str, str]] = []
    for episode in line.episodes():
        entry = bank_index.file(memory_path, "episodes", f"{str(episode).split('#', 1)[0]}.md")
        if entry is None:
            continue
        fm = entry.frontmatter or {}
        day, kind = aj.episode_day(fm)
        if day:
            dated.append((day, kind, str(episode), fm))
    if not dated:
        return None, "", [], None
    own = [(d, k, e) for d, k, e, fm in dated if _theirs(memory_path, e, fm, word)]
    if not own:
        return None, "", [], "holder_not_own_words"
    own.sort()
    first, last = own[0][0], own[-1][0]
    if (aj.gap(first, last) or 0) > aj.WINDOW_DAYS:
        return None, "spread", [], None
    return first, own[0][1], [e for d, _k, e in own if d == first], None


def add_cases(out: "aj.Gathered", memory_path: Path, *, lines: list, pages: dict[str, dict], held_lines: list,
              by_given: dict[str, list], fresh: dict, owners: set[str], doubt_refs: set[str], doubt_names: set[str],
              refused: set[tuple[str, str]]) -> None:
    """Every held one-word person line that has a namesake in a directory, as a case of ``out`` (``Holder.held``), decided by the
    same `arrival_join.decide`. Reads only: the pending store, the conversations that dated each name, the directories through the
    rows `arrival_join.gather` already read. Never raises — a line that cannot be read is no case."""
    if not lines:
        return
    owner_words = _owner_words(pages, owners)
    for i, line in enumerate(lines):
        try:
            words = aj._fold(line.name).split()
            if len(words) != 1 or words[0] not in by_given:
                continue
            word, hid = words[0], sanitize_id(line.name)
            out.held += 1
            block = held_block(line, word, owner_words)
            day, kind, used = None, "", []
            if not block:
                day, kind, used, block = held_day(memory_path, line, word)
            claims = _claims_of(line)
            companies, claim_facts = aj.facts_of(claims)
            facts = tuple([*[" ".join(str(f).split())[:220] for f in line.key_facts if str(f).strip()], *claim_facts][:12])
            marked = []
            for r in by_given[word]:
                bad = r.full and (hid, aj.key_hash(r.full)) in refused
                marked.append(replace(r, history="refused") if bad else r)
            elsewhere = "full_name_alias" if any(len(aj._fold(a).split()) > 1 for a in line.aliases) else None
            holder = aj.Holder(
                page=hid, word=word, day=day, day_from=kind, block=block,
                others=aj.carriers(word, pages, held_lines, line=i), doubt=bool(hid in doubt_refs or word in doubt_names),
                elsewhere=elsewhere, companies=companies if not block else (), facts=facts if not block else (),
                summary=" ".join(str(line.summary or line.description or "").split())[:600] if not block else "",
                excerpts=aj._excerpts(memory_path, used, word) if not block else (), held=True, line=line.name)
            out.cases.append(aj.Case(holder, tuple(marked), dict(fresh)))
        except Exception as exc:  # noqa: BLE001 - one unreadable line costs only its own case
            logger.debug(f"Arrival birth: a held name was not read ({type(exc).__name__})")


def _claims_of(line) -> list:
    from api.services.claims import Claim

    out = []
    for data in line.held_claims:
        try:
            out.append(Claim.from_dict(data))
        except (TypeError, ValueError, KeyError):
            continue
    return out


# --------------------------------------------------------------------------- the birth


@dataclass
class Born:
    page: str            # the new page's id
    paths: list[str]     # every memory-relative path written, for the caller to commit together
    record_id: str


def _page_with_name(memory_path: Path, name: str) -> bool:
    """Does any live person page carry this full name, as its title or an alias? (decided a moment ago; checked again at the write)"""
    folded = people_directory.fold(name)
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("status") or "") == "dropped":
            continue
        if any(people_directory.fold(x) == folded for x in people_directory.labels(fm, f.stem)):
            return True
    return False


def apply_birth(memory_path: Path, decision, case, settings=None, *, today: str | None = None,
                skip: frozenset[str] = frozenset()) -> Born | None:
    """Make the page under the arrival's FULL name from the held line, in one write; return what was written, or None and write
    nothing when anything changed since the decision: the line is gone or no longer qualifies, the name is no longer in a
    directory or hashes differently, a page of that name (or an id) exists, a path it would write is dirty (in ``skip``), or the
    writer refuses it.

    The page is the promotion's own: `conflict_resolver.apply_changes`' create from the line (its words, facts, links, history and
    a credit per conversation it was heard in), the said form kept as an alias (`entity_resolver._renamed_entity`), a LinkedIn
    connection of the lead attached in the same write and only PROPOSED (`linkedin_mention`). Then the held claims land on it
    through the person's-own-answer path (`claim_pipeline.land_answered`, "this held name IS that page"), and the line leaves the
    store. A Contacts card of the lead attaches through its own rematch, like Route D's."""
    from api.services import claim_pipeline, conflict_resolver, entity_resolver as er

    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    holder = case.holder
    if not holder.held:
        return None
    name = w.display_name(memory_path, decision.refs, decision.kinds)
    if not name or aj.key_hash(people_directory.fold(name)) != decision.alias_key or not alias_policy.admits(name):
        return None
    page_id = sanitize_id(name)
    rel = f"entities/{page_id}.md"
    if not page_id or {rel, pending_store.PENDING_STORE_FILE} & set(skip):
        return None
    with page_lock.page_lock(memory_path):
        path = memory_path / rel
        line = pending_store.held_line(memory_path, holder.line)
        if path.exists() or line is None or _page_with_name(memory_path, name):
            return None
        word = aj._fold(line.name)
        if str(line.type or "") != "person" or word != holder.word or held_block(line, word, set()) in (
                "holder_second_of_name", "holder_held_against", "holder_apart", "holder_correspondent"):
            return None
        entity = er._renamed_entity({**er._pending_payload(line), "name": line.name, "type": "person"}, name)
        change = er._create_change(page_id, entity)
        er._fold_pending(change, line)
        change["trigger"] = aj.TRIGGER
        if aj.CONNECTION in decision.kinds:
            change[er.LINKEDIN_MENTION_KEY] = {"id": next((r for r in decision.refs), ""), "name": name}
        conflict_resolver.apply_changes([change], memory_path)
        if not path.is_file():
            return None
        paths = [rel]
        # the held claims land first: crediting their conversations is part of what the birth put on the page
        landed = _land_held_claims(memory_path, line, page_id, settings or SimpleNamespace(memory_path=memory_path), claim_pipeline)
        paths += [p for p in landed if p not in paths]
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        episodes = [str(e) for e in fm.get("source_episodes") or []]
        record = {"id": w._hash(f"{page_id}\x00{decision.alias_key}\x00{today}"), "alias_key": decision.alias_key, "birth": True,
                  "said_key": aj.key_hash(word), "refs": list(decision.refs), "kinds": list(decision.kinds),
                  "days": {"holder": decision.holder_day, "arrival": decision.arrival_day}, "delta": decision.delta,
                  "on": today, "state": w.JOINED, "commits": [], "episodes": episodes, "pre": {"claims": [], "sources": []}}
        fm[w.KEY] = [record]
        markdown_parser.write(path, fm, parsed.body)
        pending_store.take(memory_path, line.name)
        if (memory_path / pending_store.PENDING_STORE_FILE).exists():
            paths.append(pending_store.PENDING_STORE_FILE)
    w._invalidate(memory_path)
    return Born(page_id, list(dict.fromkeys(paths)), record["id"])


def _land_held_claims(memory_path: Path, line, page_id: str, settings, claim_pipeline) -> list[str]:
    """The line's held claims onto the page it became (`pending_store.answered` + `claim_pipeline.land_answered`: the same path the
    person's own "this held name IS that page" takes), each leaving the line once it has landed. Paths written; ``[]`` for a line
    that held none."""
    from api.services import which_one_file

    release = which_one_file.allowed(memory_path, pending_store.answered(memory_path, line.name, page_id))   # ruling 83: a "no" holds
    if release is None:
        return []
    try:
        written, landed = claim_pipeline.land_answered(memory_path, release, settings)
    except Exception as exc:  # noqa: BLE001 - the page is born; a claim that did not land stays held on the line
        logger.warning(f"Arrival birth: held claims did not land ({type(exc).__name__})")
        return []
    pending_store.drop_released(memory_path, line.name, landed)
    return list(written)


def commit_message(page: str, paths: list[str], decision, today: date) -> str:
    """The birth commit: page ids, both days and the gap — never a directory row's name, company, headline, link or e-mail.
    (The page's own path is the page's id, as every commit names its pages.)"""
    lines = [f"{p}: {'created' if p == f'entities/{page}.md' else 'updated'} (source: n/a, trigger: {aj.TRIGGER})" for p in paths]
    lines += ["", f"Reason: a first name held below the promotion bar, new the same week as its full name ({decision.delta} days "
                  f"apart; {decision.holder_day} and {decision.arrival_day}), born as that page"]
    return git_service.build_commit_message(f"{w.SUBJECT_JOIN} {today.isoformat()}", lines, authors=["cicada"])


def restore(memory_path: Path, paths: list[str]) -> None:
    """Take back a birth whose commit failed, so no later ``git add -A`` sweeps it under another author: a tracked file goes back
    to its committed bytes, a file git never saw (the new page) is removed."""
    memory_path = Path(memory_path)
    for rel in paths:
        tracked = (memory_path / ".git").exists() and bool(w._git(memory_path, "ls-files", "--", rel).strip())
        try:
            if tracked:
                git_service.run_git_write_sync(memory_path, "checkout", "--", rel)
            else:
                (memory_path / rel).unlink(missing_ok=True)
        except (git_service.GitError, OSError) as exc:
            logger.warning(f"Arrival birth restore failed: {type(exc).__name__}")
    w._invalidate(memory_path)


# --------------------------------------------------------------------------- "Not them"


def _line_before_birth(memory_path: Path, entity_id: str, said: str):
    """The held line as it stood in the commit before the page was born, read from the bank's own history — or None."""
    rel = f"entities/{entity_id}.md"
    shas = w._git(memory_path, "log", "--diff-filter=A", "--format=%H", "--", rel).split()
    if not shas or not _SHA.match(shas[0]):
        return None
    store = subprocess.run(["git", "-C", str(memory_path), "show", f"{shas[0]}^:{pending_store.PENDING_STORE_FILE}"],
                           capture_output=True, text=True)
    if store.returncode != 0:
        return None
    for raw in store.stdout.splitlines():
        try:
            line = pending_store.PendingEntity.from_dict(json.loads(raw))
        except Exception:  # noqa: BLE001
            continue
        if str(line.type or "") == "person" and aj._fold(line.name) == aj._fold(said):
            return line
    return None


def _said_alias(fm: dict, record: dict) -> str | None:
    for a in fm.get("aliases") or []:
        if isinstance(a, str) and aj.key_hash(people_directory.fold(a)) == record.get("said_key"):
            return a
    return None


def undo(memory_path: Path, entity_id: str, path: Path, parsed, record: dict, *, author: str, trigger: str, before, session,
         day: str) -> dict:
    """"Not them" for a page this module BORN (called by `arrival_join_write.undo`, inside the page lock): see the module docstring.
    Raises `arrival_join_write.UndoError`, writing nothing, when the person changed the name or took the link since, the page has
    heard another conversation since, or the held line cannot be read back."""
    fm = dict(parsed.frontmatter)
    raw, mine, taken, missing = w.attached(fm, record)
    said = _said_alias(fm, record)
    later = [e for e in fm.get("source_episodes") or [] if str(e) not in set(record.get("episodes") or [])]
    renamed = aj.key_hash(people_directory.fold(str(fm.get("name") or ""))) != record.get("alias_key")
    if renamed or said is None or taken or missing or later:
        bits = ["the name was changed by you" if renamed else "the page still has its name"]
        bits.append("the name you wrote is on the page" if said else "the name you wrote was taken off by you")
        if record.get("sources"):
            bits.append("source " + ", ".join(record["sources"]))
        if later:
            bits.append("conversations heard since: " + ", ".join(str(e) for e in later[:12]))
        raise w.UndoError("Nothing was undone: you changed this since Cicada made the page, or it has heard more since. Still "
                          "there: " + "; ".join(bits) + ". Take what you do not want off the page yourself (its name, its link, "
                          "its conversations).", 409)
    line = _line_before_birth(memory_path, entity_id, said)
    if line is None:
        raise w.UndoError("Nothing was undone: the name you wrote could not be read back from the bank's history.", 409)
    holder_id = sanitize_id(line.name)
    # the said form leaves, and no automatic writer may add it back
    fm["aliases"] = [a for a in fm.get("aliases") or [] if a != said]
    if not fm["aliases"]:
        fm.pop("aliases")
    removed = [r for r in fm.get(page_edits.ALIASES_REMOVED) or []] if isinstance(fm.get(page_edits.ALIASES_REMOVED), list) else []
    removed.append({"alias": said, "by": author, "on": day})
    fm[page_edits.ALIASES_REMOVED] = removed[-page_edits.MAX_ALIASES_REMOVED:]
    paths = [f"entities/{entity_id}.md"]
    body = w.detach(memory_path, entity_id, fm, parsed.body, record, raw, mine, author=author, day=day, paths=paths)
    # the page is archived, undoably: what it was is on its stamp, and the commit is in git
    fm["archived_by"] = {"reason": ARCHIVE_REASON, "day": day, "prior_status": str(fm.get("status") or "active"),
                         "prior_confidence": fm.get("confidence")}
    fm["removed_at"] = day
    fm["status"] = "archived"
    w.mark_undone(fm, record, day)
    markdown_parser.write(path, fm, body)
    # the held name comes back as it was, and the pair is refused for every later joiner
    pending_store.upsert(memory_path, line)
    paths.append(pending_store.PENDING_STORE_FILE)
    merge_rejections.add_rejected(memory_path, holder_id, entity_id)
    paths.append(merge_rejections.FILE)
    w._invalidate(memory_path)
    commit = w._commit_undo(memory_path, list(dict.fromkeys(paths)), record, trigger=trigger, author=author, session=session,
                            before=before)
    return {"kind": "arrival-undo", "page": entity_id, "commit": commit, "restored": [], "removed": []}
