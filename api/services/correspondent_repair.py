"""Split a page that absorbed a message conversation's correspondent (G179 repair, owner 2026-10-15).

Before `correspondents`, Stage 2 resolved a texted agent by name alone, so an existing page that shared its letters
— an archived ``concept`` about the ordinary word — took the agent's conversations: its claims, its sources, an
article rewritten about the agent, and the life those mentions gave the page. This finds such a page and splits it.

**Found:** for each conversation whose episodes carry a decided ``correspondent`` record (the newest sitting's record
names it — the person's current mark), a page named so (name or alias, folded as `correspondents` folds) that credits
one of those episodes (``source_episodes``, or a claim's) while its type is not the correspondent's (`tool` for an
agent, `person` for a person). Pages that legitimately credit the conversation (the projects it talked about) are
never touched: only the page named as the correspondent is.

**Split, from the page's own git history:** the *base* is the page as it stood in the parent of the first commit
whose version credited the conversation — what it was before it absorbed anything of it.

* The **old page** goes back to its base — prose, frontmatter, status, confidence, `last_referenced`,
  `decayed_through`, its claims (a claim the absorption touched comes back as the base had it) — plus whatever came
  later that is not the conversation's (a source episode or claim from another conversation, counted as
  ``kept_later``), and its `version` moves on.
* The **correspondent's page** — an existing page of the right type named so (the general merge rules then apply:
  sources and claims unioned, list sections merged human-safe, its own lead kept), else a new page under
  `correspondents.free_id` — gets the conversation's episodes, every claim added since the base that cites one of them
  (re-subjected; id, observer, evidence and every other provenance field as they were), the frontmatter
  ``sources:`` rows, tags and aliases added since the base, and the prose the absorption wrote: the lead and Article
  when they differ from the base's (moved verbatim, so a machine article keeps its stamp and Sleep's writer keeps
  rewriting it — no model here), and the Key Facts, History, Links and Open Questions items the base did not have.
  A new page is born as a create is (`conflict_resolver.apply_changes`): `active`, confidence
  `conflict_resolver.RECOVERY_CONFIDENCE`, `created`/`last_referenced` from its conversations' own days,
  `decayed_through` = `last_referenced`, `learned_on` today, the decay class of its type — so the next decay pass
  charges only the silence its conversations prove (the late-read rule is untouched).
* **Other pages' claims** whose node object is the old id and that cite one of the conversation's episodes now point
  at the correspondent's page; ``graph_edges.yaml``'s claim edges are regenerated from the claims
  (`graph_builder.regenerate_edges_from_claims`, Sleep's own Stage 5.7). A ``[[wikilink]]`` by name in another page's
  prose is left as written (it names letters, not a page).

A page with no version before the conversation (born from it, or a bank without git) is not split and is counted
(``no_history``). The survey prints counts only. ``apply`` is refused while Sleep runs or holds the pages, skips a
split whose footprint is dirty in git, writes everything in one ``cicada`` commit (trigger
``maintenance/correspondent-split``), and a second run finds nothing to do.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import yaml
from loguru import logger

from api.services import claims_ledger, correspondents, decay_policy, entity_body, markdown_parser
from api.services.claims import Claim, parse_claims, strip_claims_block, write_claims

TRIGGER = "maintenance/correspondent-split"
AUTHOR = "cicada"
_LIST_SECTIONS = ("Key Facts", "History", "Links", "Open Questions")


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
    claims_kept_later: int
    sources_moved: int
    repoint: dict[str, list[str]]   # other page id -> the claim ids whose object moves


@dataclass
class Plan:
    conversations: int = 0
    candidates: int = 0
    splits: list[Split] = field(default_factory=list)
    no_history: int = 0
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
            "claims_kept_later": sum(s.claims_kept_later for s in self.splits),
            "sources_moved": sum(s.sources_moved for s in self.splits),
            "claims_repointed": sum(len(v) for s in self.splits for v in s.repoint.values()),
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
    except Exception:  # noqa: BLE001 - an unreadable fence: the page is not split (nothing could be moved safely)
        return []


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


def _base(memory_path: Path, page_id: str, episodes: set[str]) -> tuple[str, dict, str] | None:
    """``(rev, frontmatter, body)``: the page before the first commit that credited the conversation, else ``None``."""
    log = _git(memory_path, "log", "--format=%H", "--", f"entities/{page_id}.md")
    if not log:
        return None
    for rev in reversed(log.split()):
        version = _version(memory_path, rev, page_id)
        if version is None or not _credits(version[0], version[1], episodes):
            continue
        before = _version(memory_path, f"{rev}^", page_id)
        if before is None or _credits(before[0], before[1], episodes):
            return None
        return (f"{rev}^", *before)
    return None


# --------------------------------------------------------------------------- composing


def _items(content: str) -> list[str]:
    return entity_body._bullet_lines(content or "")


def _new_items(current: str, base: str) -> list[str]:
    had = {entity_body._normalize_fact(i) for i in _items(base)}
    return [i for i in _items(current) if entity_body._normalize_fact(i) not in had]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _source_key(row) -> tuple:
    return (str(row.get("ref", "")).strip(), str(row.get("predicate") or "").strip().lower()) \
        if isinstance(row, dict) else (str(row), "")


def _identity_line(ident: correspondents.Identity) -> str:
    if ident.kind == "agent":
        return f"{ident.name} is an AI agent the person texts."
    return f"{ident.name} is someone the person texts."


def _resubject(claim: Claim, old_id: str, new_id: str) -> None:
    if claim.subject == old_id:
        claim.subject = new_id
    if claim.object_kind != "literal" and claim.object == old_id:
        claim.object = new_id


def _plan_split(memory_path: Path, page: dict, conv: Conversation, pages: list[dict], taken: set[str],
                today: str) -> Split | None:
    from api.services.conflict_resolver import RECOVERY_CONFIDENCE

    page_id, cur_fm, cur_body = page["id"], dict(page["frontmatter"]), page["body"]
    base = _base(memory_path, page_id, conv.episodes)
    if base is None:
        return None
    base_rev, base_fm, base_body = base
    eps = conv.episodes

    # Claims: the base's come back as the base had them; later ones go by the episodes they cite.
    base_claims = _claims(base_body)
    base_ids = {c.id for c in base_claims}
    moved, kept_later = [], []
    for claim in _claims(cur_body):
        if claim.id in base_ids:
            continue
        (moved if set(claim.source_episodes) & eps else kept_later).append(claim)

    # The old page: its base, plus what later came from elsewhere.
    old_fm = dict(base_fm)
    base_sources = [str(e) for e in base_fm.get("source_episodes") or []]
    later_sources = [str(e) for e in cur_fm.get("source_episodes") or [] if str(e) not in base_sources]
    old_fm["source_episodes"] = base_sources + [e for e in later_sources if e not in eps]
    old_fm["version"] = int(cur_fm.get("version", 1) or 1) + 1
    if claims_ledger.STAMP in cur_fm:
        # The current ledger as read: this write is the page's whole claim set (`claims_ledger.split`).
        old_fm[claims_ledger.STAMP] = cur_fm[claims_ledger.STAMP]
    else:
        old_fm.pop(claims_ledger.STAMP, None)
    old_prose = strip_claims_block(base_body)
    old_claims = [*base_claims, *kept_later]
    old_body = write_claims(old_prose, old_claims) if old_claims else old_prose

    # What moves: the conversation's episodes, the claims citing them, what the absorption added to the prose.
    conv_sources = [e for e in later_sources if e in eps]
    for claim in moved:
        conv_sources += [e for e in claim.source_episodes if e in eps and e not in conv_sources]
    base_sections = entity_body.parse_sections(strip_claims_block(base_body))
    cur_sections = entity_body.parse_sections(strip_claims_block(cur_body))
    moved_sections: dict[str, str] = {}
    for title in ("Summary", "Article"):
        if (cur_sections.get(title) or "").strip() != (base_sections.get(title) or "").strip():
            moved_sections[title] = cur_sections.get(title) or ""
    for title in _LIST_SECTIONS:
        items = _new_items(cur_sections.get(title, ""), base_sections.get(title, ""))
        if items:
            moved_sections[title] = _bullets(items)
    base_rows = {_source_key(r) for r in base_fm.get("sources") or []}
    moved_rows = [r for r in cur_fm.get("sources") or [] if _source_key(r) not in base_rows]
    base_tags, base_aliases = set(base_fm.get("tags") or []), {str(a).lower() for a in base_fm.get("aliases") or []}
    moved_tags = [t for t in cur_fm.get("tags") or [] if t not in base_tags]
    moved_aliases = [a for a in cur_fm.get("aliases") or [] if str(a).lower() not in base_aliases]
    base_related = {str(r).lower() for r in base_fm.get("related") or []}
    moved_related = [r for r in cur_fm.get("related") or [] if str(r).lower() not in base_related]

    ident = conv.ident
    target = correspondents.find_page(pages, ident)
    if target is not None and target["id"] == page_id:
        target = None
    if target is not None:
        target_id = target["id"]
        new_fm, new_body = _merge_into_target(target, moved_sections, moved, conv_sources, moved_rows, moved_tags,
                                              moved_aliases, conv, page_id)
    else:
        target_id = correspondents.free_id(ident, taken, Path(memory_path) / "entities")
        days = sorted(d for d in (conv.days.get(e, "") for e in conv_sources) if d)
        last = days[-1] if days else today
        decay_class = decay_policy.default_class_for(ident.page_type)
        new_fm = {
            "name": ident.name,
            "type": ident.page_type,
            "status": "active",
            "confidence": RECOVERY_CONFIDENCE,
            "created": days[0] if days else today,
            "last_referenced": last,
            "decayed_through": last,
            "learned_on": today,
            **decay_policy.frontmatter_fields(decay_class),
            "source_episodes": conv_sources,
            "tags": moved_tags,
            "aliases": [a for a in moved_aliases if str(a).lower() != ident.name.lower()],
            "related": moved_related,
            "version": 1,
            "layout_version": 2,
        }
        if moved_rows:
            new_fm["sources"] = moved_rows
        if not (moved_sections.get("Summary") or "").strip():
            moved_sections["Summary"] = _identity_line(ident)
        prose = entity_body.render_sections(moved_sections)
        # The lead and Article moved verbatim keep their article stamp; the G118 item records follow exact items.
        from api.services import entity_article, section_provenance

        for key in (entity_article.FIELD, section_provenance.FIELD):
            if key in cur_fm:
                new_fm[key] = cur_fm[key]
        if not entity_article.stamped(new_fm, entity_body.parse_sections(prose)):
            new_fm.pop(entity_article.FIELD, None)   # only a lead and Article moved as written keep the stamp
        section_provenance.refresh(new_fm, strip_claims_block(cur_body), prose, {})
        for claim in moved:
            _resubject(claim, page_id, target_id)
        new_body = write_claims(prose, moved) if moved else prose

    # Other pages' claims on the conversation that point at the old id.
    repoint: dict[str, list[str]] = {}
    for other in pages:
        if other["id"] in (page_id, target_id):
            continue
        ids = [c.id for c in _claims(other["body"])
               if c.object_kind != "literal" and c.object == page_id and set(c.source_episodes) & eps]
        if ids:
            repoint[other["id"]] = ids

    return Split(page_id=page_id, target_id=target_id, target_exists=target is not None, conversation=conv,
                 base_rev=base_rev, old_fm=old_fm, old_body=old_body, new_fm=new_fm, new_body=new_body,
                 claims_moved=len(moved), claims_kept_later=len(kept_later), sources_moved=len(conv_sources),
                 repoint=repoint)


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
    keys = {_source_key(r) for r in rows}
    rows += [r for r in moved_rows if _source_key(r) not in keys]
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
            names = [fm.get("name"), *(fm.get("aliases") or [] if isinstance(fm.get("aliases"), list) else [])]
            if not correspondents.names_it(names, ident) or not _credits(fm, page["body"], conv.episodes):
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
