# api/services/entity_merge.py
"""Merge two rich entity pages into one (the G21 primitive the inbox lacks).

Unions list frontmatter, section-merges bodies (human-prose-safe), carries the
loser's claims with their provenance and supersession history (audit
2026-10-05 P1-1), repoints graph_edges.yaml endpoints and every other page's
references loser->winner, then deletes the loser. Reversible via git.
"""
from __future__ import annotations
import re
from pathlib import Path
import yaml
from loguru import logger

from api.services import markdown_parser, entity_body, page_lock
from api.services.claims import (
    Claim, MalformedClaimsBlockError, parse_claims, strip_claims_block, write_claims,
)

_LIST_FIELDS = ("source_episodes", "tags", "related", "aliases")


def _union(a, b):
    seen, out = set(), []
    for x in list(a or []) + list(b or []):
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def _merge_sources(winner_id: str, loser_id: str, wfm: dict, lfm: dict) -> None:
    """G61 S3-a: the loser's ``sources:`` and ``sources_removed:`` travel to the
    winner — before this a page merge silently dropped them. Deduped on the
    ``(ref, predicate)`` key (the winner's entry wins), capped as a page is, and
    an ``entity:`` link that pointed at the loser now points at the winner (one
    that would point at its own page is dropped)."""
    from api.services import fact_sources as fs

    def key(row):
        return (str(row.get("ref", "")).strip(), str(row.get("predicate") or "").strip().lower())

    candidates: list[dict] = []
    seen: set = set()
    for row in fs.as_sources(wfm.get("sources")) + fs.as_sources(lfm.get("sources")):
        if key(row) in seen:
            continue
        seen.add(key(row))
        candidates.append(row)
    # The caps hold on a merge too, and the person's own entries are the last to go: they are taken first, then
    # everyone else's while the page and each fact have room. File order is kept in the result.
    person = [r for r in candidates if (str(r.get("added_by") or fs.USER).strip() or fs.USER) == fs.USER]
    others = [r for r in candidates if r not in person]
    kept: list[dict] = []
    per: dict[str, int] = {}
    for row in person + others:
        if len(kept) >= fs.MAX_SOURCES:
            break
        pred = str(row.get("predicate") or "").strip().lower()
        if row not in person and per.get(pred, 0) >= fs.MAX_PER_PREDICATE:
            continue
        per[pred] = per.get(pred, 0) + 1
        kept.append(row)
    merged = [r for r in candidates if any(r is k for k in kept)]
    for row in merged:
        if str(row.get("entity") or "") == loser_id:
            row["entity"] = winner_id
        if str(row.get("entity") or "") == winner_id:
            row.pop("entity", None)
    if merged:
        wfm["sources"] = merged
    tombs: list[dict] = []
    seen = set()
    for row in fs._tombstones(lfm) + fs._tombstones(wfm):   # the winner's are the newer word
        if key(row) in seen:
            tombs = [t for t in tombs if key(t) != key(row)]
        seen.add(key(row))
        tombs.append(row)
    if tombs:
        wfm[fs.REMOVED_KEY] = tombs[-fs.MAX_TOMBSTONES:]


def _names(eid: str, name: str) -> set[str]:
    return {eid.lower(), (name or eid).lower()}


def _wikilink_re(old_id: str, old_name: str) -> re.Pattern:
    """``[[target]]``, ``[[target|label]]`` and ``[[target#Section]]`` — group 1
    and group 2 are kept, only the target between them is replaced."""
    targets = {old_id, old_name}
    return re.compile(r"(\[\[\s*)(?:" + "|".join(re.escape(t) for t in targets if t) + r")(\s*(?:[|#][^\]]*)?\]\])",
                      re.IGNORECASE)


def _relink(pattern: re.Pattern, new_name: str, text: str) -> tuple[str, int]:
    return pattern.subn(lambda m: f"{m.group(1)}{new_name}{m.group(2)}", text)


def append_note(body: str, note: str) -> str:
    """Append ``note`` to a page's prose — above its ```claims fence, which
    stays the page's last block (the fence's one writer, `write_claims`)."""
    prose = strip_claims_block(body)
    if prose == (body or "").strip():
        return (body or "").rstrip() + note
    return write_claims(prose.rstrip() + note, parse_claims(body, strict=True))


def _repoint_claim(c: Claim, old: set[str], old_id: str, new_id: str) -> bool:
    """Point one claim's references at ``new_id`` — its subject and a node
    object naming the old entity.
    Everything else — observer, trust, sessions, validity, supersession and
    evidence — is provenance and travels untouched. A ``page`` span that cited
    the old page keeps naming it: its offsets and hash are into THAT text, which
    git still holds; pointed at the new page it would only ever read stale."""
    changed = False
    if c.subject and c.subject.lower() in old:
        c.subject = new_id
        changed = True
    if c.object_kind != "literal" and c.object and c.object.strip().lower() in old:
        c.object = new_id
        changed = True
    return changed


def _same_as(existing: Claim | None, c: Claim, as_id: str) -> bool:
    if existing is None:
        return False
    mine = c.to_dict()
    mine["id"] = as_id
    return existing.to_dict() == mine


def _carry_claims(winner: list[Claim], loser: list[Claim], loser_id: str, loser_name: str,
                  winner_id: str) -> list[Claim]:
    """The winner's claims, then every claim the loser held (audit 2026-10-05 P1-1).

    A loser claim keeps its id, history and provenance, re-subjected to the
    winner. An id the winner already uses is kept under ``<id>-from-<loser>``
    (and the loser's own supersedes/superseded_by/premises follow the rename),
    unless the two claims are identical once re-subjected — then it is one
    claim, kept once. Nothing is reconciled or closed here: two open claims
    that disagree stay two, for Sleep's conflict stage and the person."""
    old = _names(loser_id, loser_name)
    taken = {c.id for c in winner}
    by_id = {c.id: c for c in winner}
    renames: dict[str, str] = {}
    carried: list[Claim] = []
    for c in loser:
        _repoint_claim(c, old, loser_id, winner_id)
        if c.id in taken:
            if by_id.get(c.id) is not None and by_id[c.id].to_dict() == c.to_dict():
                continue
            new_id, n = f"{c.id}-from-{loser_id}", 2
            # A merge re-run after a crash finds its own earlier copy: same claim, kept once.
            while new_id in taken and not _same_as(by_id.get(new_id), c, new_id):
                new_id, n = f"{c.id}-from-{loser_id}-{n}", n + 1
            renames[c.id] = new_id
            if new_id in taken:
                continue
            c.id = new_id
        taken.add(c.id)
        carried.append(c)
    for c in carried:
        if c.supersedes in renames:
            c.supersedes = renames[c.supersedes]
        if c.superseded_by in renames:
            c.superseded_by = renames[c.superseded_by]
        c.premises = [renames.get(p, p) for p in c.premises]
    for c in winner:
        _repoint_claim(c, old, loser_id, winner_id)
    return [*winner, *carried]


def repoint_references(memory_path: Path, old_id: str, old_name: str, new_id: str, new_name: str,
                       *, skip: tuple[str, ...] = ()) -> list[str]:
    """Point every OTHER entity page's references at ``new_id`` before the old
    page goes: ``related:`` entries, ``[[wikilinks]]``, a source's ``entity:``
    link (G61 S3-a), and claims whose subject or node object names the old
    entity. Returns the memory-relative paths it rewrote. A page whose claims
    block will not parse keeps that block byte-for-byte (the strict-parse rule)
    and still has its frontmatter and prose repointed. The raw layer
    (``episodes/``) is never rewritten."""
    ents = Path(memory_path) / "entities"
    old = _names(old_id, old_name)
    wikilink_re = _wikilink_re(old_id, old_name)
    skip_names = {f"{s}.md" for s in (old_id, new_id, *skip)}
    touched: list[str] = []
    for ep in sorted(ents.glob("*.md")):
        if ep.name in skip_names:
            continue
        epar = markdown_parser.parse(ep)
        efm = dict(epar.frontmatter)
        changed = False

        related = efm.get("related")
        if isinstance(related, list):
            new_related, seen_r = [], set()
            for r in related:
                if isinstance(r, str) and r.lower() in old:
                    r = new_name
                dedup_key = r.lower() if isinstance(r, str) else r
                if dedup_key in seen_r:
                    continue
                seen_r.add(dedup_key)
                new_related.append(r)
            if new_related != related:
                efm["related"] = new_related
                changed = True

        srcs = efm.get("sources")
        if isinstance(srcs, list):
            for src in srcs:
                if isinstance(src, dict) and str(src.get("entity") or "") == old_id:
                    src["entity"] = new_id   # G61 S3-a: a source's link follows the merge
                    changed = True

        try:
            page_claims = parse_claims(epar.body, strict=True)
        except MalformedClaimsBlockError:
            logger.warning(f"merge: {ep.stem} has an unparseable claims block; its claims keep their references")
            page_claims = []
        claims_changed = False
        for c in page_claims:
            claims_changed |= _repoint_claim(c, old, old_id, new_id)

        new_body, n_subs = _relink(wikilink_re, new_name, epar.body)
        if claims_changed:
            new_body = write_claims(new_body, page_claims)
        if n_subs or claims_changed:
            changed = True

        if changed:
            markdown_parser.write(ep, efm, new_body)
            touched.append(f"entities/{ep.name}")
    return touched


def repoint_edges(memory_path: Path, old_id: str, new_id: str) -> int | None:
    """Repoint ``graph_edges.yaml`` endpoints old -> new, dropping the self-loops
    and duplicates that creates. The number of endpoints moved, or ``None``
    when there is no edges file (nothing written)."""
    edges_file = Path(memory_path) / "graph_edges.yaml"
    if not edges_file.exists():
        return None
    data = yaml.safe_load(edges_file.read_text()) or {}
    repointed = 0
    for e in data.get("edges", []):
        for end in ("source", "target"):
            if e.get(end) == old_id:
                e[end] = new_id; repointed += 1
    seen = set()
    cleaned = []
    for e in data.get("edges", []):
        if e.get("source") == e.get("target"):
            continue  # drop self-loop created by repointing
        key = (e.get("source"), e.get("target"), e.get("label"))
        if key in seen:
            continue  # drop duplicate
        seen.add(key)
        cleaned.append(e)
    data["edges"] = cleaned
    edges_file.write_text(yaml.safe_dump(data, sort_keys=False))
    return repointed


@page_lock.locked
def rename_references(memory_path: Path, old_id: str, old_name: str, new_id: str, new_name: str) -> list[str]:
    """After a page moved from ``old_id`` to ``new_id`` (the inbox's
    keep-the-cleaner-name merge): its own claims, ``related`` and wikilinks
    that named the old id, the graph's edges, and every other page's
    references. Returns the memory-relative paths written."""
    page = Path(memory_path) / "entities" / f"{new_id}.md"
    parsed = markdown_parser.parse(page)
    fm, body = dict(parsed.frontmatter), parsed.body
    own = parse_claims(body, strict=True)
    old = _names(old_id, old_name)
    changed = False
    for c in own:
        changed |= _repoint_claim(c, old, old_id, new_id)
    body, n = _relink(_wikilink_re(old_id, old_name), new_name, body)
    if changed:
        body = write_claims(body, own)
    self_names = old | _names(new_id, new_name)
    if isinstance(fm.get("related"), list):
        related = [r for r in fm["related"] if not (isinstance(r, str) and r.lower() in self_names)]
        if related != fm["related"]:
            fm["related"] = related
            changed = True
    paths = []
    if changed or n:
        markdown_parser.write(page, fm, body)
        paths.append(f"entities/{new_id}.md")
    if repoint_edges(memory_path, old_id, new_id) is not None:
        paths.append("graph_edges.yaml")
    return paths + repoint_references(memory_path, old_id, old_name, new_id, new_name)


@page_lock.locked
def merge_entities(memory_path: Path, loser_id: str, winner_id: str,
                   *, author: str = "user") -> dict:
    """Fold ``loser_id`` into ``winner_id`` and delete the loser's page.

    Returns ``paths``: every memory-relative path written or removed, so the
    caller commits exactly those (a merge is one writer's change)."""
    if loser_id == winner_id:
        raise ValueError(f"cannot merge an entity into itself: {winner_id}")
    ents = memory_path / "entities"
    lp, wp = ents / f"{loser_id}.md", ents / f"{winner_id}.md"
    if not lp.exists() or not wp.exists():
        raise FileNotFoundError(f"merge needs both pages: {loser_id}, {winner_id}")
    if lp.samefile(wp):
        # Two ids for one file (a case-insensitive disk): deleting the "loser"
        # would delete the page itself.
        raise ValueError(f"cannot merge an entity into itself: {loser_id} is {winner_id}")

    lpar, wpar = markdown_parser.parse(lp), markdown_parser.parse(wp)
    lfm, wfm = dict(lpar.frontmatter), dict(wpar.frontmatter)
    winner_name = str(wfm.get("name", winner_id))
    loser_name = str(lfm.get("name", loser_id))

    # strict, both sides: a corrupt block must abort the merge — a lenient parse
    # would read as "no claims", and the rewrite (winner) or the delete (loser)
    # below would destroy it.
    winner_claims = parse_claims(wpar.body, strict=True)
    loser_claims = parse_claims(lpar.body, strict=True)

    for f in _LIST_FIELDS:
        merged = _union(wfm.get(f), lfm.get(f))
        if merged:
            wfm[f] = merged
    if isinstance(wfm.get("aliases"), list):
        wfm["aliases"] = [a for a in wfm["aliases"] if str(a).lower() != winner_name.lower()]
        if not wfm["aliases"]:
            wfm.pop("aliases")
    # The merged page never lists itself, or the page it absorbed, as related.
    self_names = _names(winner_id, winner_name) | _names(loser_id, loser_name)
    if isinstance(wfm.get("related"), list):
        wfm["related"] = [r for r in wfm["related"] if not (isinstance(r, str) and r.lower() in self_names)]
        if not wfm["related"]:
            wfm.pop("related")
    # The loser's name stays findable: a later mention of it resolves here.
    if loser_name.lower() != winner_name.lower():
        aliases = list(wfm.get("aliases") or [])
        if loser_name.lower() not in {str(a).lower() for a in aliases}:
            wfm["aliases"] = [*aliases, loser_name]
    _merge_sources(winner_id, loser_id, wfm, lfm)
    wfm["confidence"] = max(float(wfm.get("confidence", 0) or 0),
                            float(lfm.get("confidence", 0) or 0))
    # Mentioned most recently on either page: a merge must not make the
    # surviving page look staler than what it absorbed (decay reads this).
    last = [v for v in (wfm.get("last_referenced"), lfm.get("last_referenced")) if v]
    if last:
        wfm["last_referenced"] = max(last, key=str)

    # Section-merge loser body into winner (human-safe: never drop winner prose).
    # merge_sections_human_safe needs the STRUCTURED new_fields shape, so convert
    # the loser's sections via sections_to_fields (a raw sections dict merges nothing).
    # Both bodies are merged claims-stripped so a fence can never end up
    # mid-section; the claims are re-attached below as one block.
    human = bool(wfm.get("human_edited"))
    loser_sections = entity_body.parse_sections(strip_claims_block(lpar.body))
    loser_fields = entity_body.sections_to_fields(loser_sections)
    merged_sections = entity_body.merge_sections_human_safe(
        entity_body.parse_sections(strip_claims_block(wpar.body)), loser_fields, human_edited=human)
    # Preserve any non-canonical (human-authored) loser sections too — the
    # structured merge only carries the canonical fields. If the winner
    # already has a same-titled custom section with different content,
    # append rather than silently dropping the loser's content.
    for title, content in loser_sections.items():
        if not title or title in entity_body.CANONICAL_SECTIONS:
            continue
        content = (content or "").strip()
        if not content:
            continue
        existing = (merged_sections.get(title) or "").strip()
        if not existing:
            merged_sections[title] = content
        elif content not in existing:
            merged_sections[title] = existing + "\n\n" + content
        # identical content: keep winner's, no dup
    new_body = "\n\n".join(f"## {t}\n{c}" if t else c
                           for t, c in merged_sections.items() if c).strip()
    # A wikilink to the loser inside the merged prose now names this page.
    new_body, _n = _relink(_wikilink_re(loser_id, loser_name), winner_name, new_body)
    all_claims = _carry_claims(winner_claims, loser_claims, loser_id, loser_name, winner_id)
    if all_claims:
        new_body = write_claims(new_body, all_claims)
    markdown_parser.write(wp, wfm, new_body)
    paths = [f"entities/{winner_id}.md"]

    repointed = repoint_edges(memory_path, loser_id, winner_id)
    if repointed is not None:
        paths.append("graph_edges.yaml")

    # Repoint OTHER entities' references to the loser before it's deleted —
    # otherwise they become dangling references that accumulate across dedup runs.
    others = repoint_references(memory_path, loser_id, loser_name, winner_id, winner_name)
    paths.extend(others)

    lp.unlink()
    paths.append(f"entities/{loser_id}.md")
    return {"winner": winner_id, "merged_source_episodes": len(wfm.get("source_episodes", [])),
            "merged_claims": len(all_claims) - len(winner_claims),
            "repointed_edges": repointed or 0, "repointed_refs": len(others), "paths": paths}
