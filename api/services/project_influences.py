"""What fed a project: its sources and influences (TODO ruling 45, Q9; proposal §2.6).

Read from what the bank already holds — no new store:

1. the project page's ``sources`` (G61): links, papers, channels, drawn as link cards (nothing is fetched to draw one);
2. claims on the project with an influence predicate — ``inspired-by``, ``references``, ``uses`` — whose object is a
   page when it resolves, otherwise plain text;
3. ``works-on`` claims on a person's page naming the project (people, reversed), and any other page's influence claim
   naming it (a video watched, a paper read that links to it). Only an explicit claim counts, never co-occurrence.

**Adding one** writes either a source (a link, through ``fact_sources``, whose ``sources_removed`` rule applies) or
one claim on the project (a person: ``<person> works-on <project>`` on the person's page). A name that matches no page
stays a plain-text object and **never mints a page** — promotion stays Sleep's rule (Q9). The person's optional
sentence is a companion episode cited as a ``user`` span (the ``log_happening`` pattern, R-PJ18). Undo withdraws the
claim, which stays as history (a born-closed ``retracts`` record), or removes the source with a tombstone.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from api.services import agentic_write, evidence, fact_sources, markdown_parser, page_lock
from api.services.claim_reconciler import is_human
from api.services.claims import MalformedClaimsBlockError, is_event, parse_claims, write_claims
from api.services.id_utils import resolve_entity_file

#: The "how" chip → its predicate (proposal §2.6). A person is written on their own page, reversed.
HOW = {"inspired": "inspired-by", "reference": "references", "uses": "uses", "person": "works-on"}
PREDICATE_HOW = {v: k for k, v in HOW.items()}
ON_PROJECT = ("inspired-by", "references", "uses")
MAX_SHOWN = 60
WITHDRAW_REASON = "The person took this influence back in Cicada"
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")
_PAPER_HOSTS = ("arxiv.org", "doi.org", "semanticscholar.org")


class InfluenceError(ValueError):
    """Refused, with a sentence; nothing written."""


def _host(ref: str) -> str:
    try:
        host = (urlparse(ref).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def link_tag(ref: str) -> str:
    host = _host(ref)
    if any(host == h or host.endswith("." + h) for h in _VIDEO_HOSTS):
        return "Video"
    if any(host == h or host.endswith("." + h) for h in _PAPER_HOSTS) or ref.lower().endswith(".pdf"):
        return "Paper"
    return "Link"


def page_tag(etype: str | None, fm: dict) -> str:
    """The side panel's group, from the object page's own type (no new taxonomy)."""
    if etype == "person":
        return "Person"
    if etype in ("tool", "skill"):
        return "Tool"
    if etype == "media":
        words = " ".join(str(t) for t in fm.get("tags") or []).lower() + " " + str(fm.get("media_type") or "")
        for word, tag in (("film", "Film"), ("movie", "Film"), ("book", "Book"), ("paper", "Paper"),
                          ("video", "Video"), ("podcast", "Podcast"), ("article", "Article")):
            if word in words:
                return tag
        return "Media"
    return {"company": "Organisation", "organization": "Organisation", "place": "Place",
            "project": "Project", "concept": "Idea"}.get(etype or "", "Thing")


def _who(claim) -> str:
    """``user`` (the person's own word), a harness label (an agent wrote it), else ``sleep`` (a model id)."""
    from api.services.episode_title import PRODUCT

    if is_human(claim):
        return "user"
    author = str(claim.authored_by or "")
    if author in PRODUCT or author.startswith(("api:", "remote:")) or author in ("claude-web", "chatgpt", "agent"):
        return author
    return "sleep"


def build(bank, root: str, reverse: dict[str, list] | None = None) -> list:
    """The project's influences for the detail wire, newest first. ``bank`` is ``project_timeline._Bank``."""
    from api.models.schemas import ProjectInfluence

    out: list[ProjectInfluence] = []
    fm = bank.fm(root)
    for i, src in enumerate(fact_sources.as_sources(fm.get("sources"))):
        if fact_sources.is_proposed(src):
            continue
        ref = str(src.get("ref") or "").strip()
        if not ref:
            continue
        kind = str(src.get("kind") or fact_sources.infer_kind(ref))
        by = str(src.get("added_by") or fact_sources.USER)
        out.append(ProjectInfluence(
            id=f"s:{i}", source="link" if kind == fact_sources.KIND_URL else kind, label=ref, url=ref
            if kind == fact_sources.KIND_URL else None, tag=link_tag(ref) if kind == fact_sources.KIND_URL else "Note",
            how=PREDICATE_HOW.get(str(src.get("predicate") or ""), None), by=by,
            day=str(src.get("added_at") or "")[:10] or None, ref=ref, predicate=src.get("predicate"),
            page=root))
    seen: set[str] = set()

    def claim_row(c, page: str, target: str | None, *, reversed_: bool):
        if c.id in seen or c.valid_to is not None or c.superseded_by or is_event(c):
            return
        seen.add(c.id)
        etype = bank.type_of(target) if target else None
        label = bank.name(target) if target and bank.live(target) else str(c.object or "").strip()
        out.append(ProjectInfluence(
            id=f"c:{c.id}", source="claim", label=label, entity=target if target and bank.live(target) else None,
            entity_type=etype, tag=page_tag(etype, bank.fm(target) if target else {}),
            how=PREDICATE_HOW.get(c.predicate), by=_who(c), day=str(c.valid_from or c.recorded_at or "")[:10] or None,
            claim_id=c.id, predicate=c.predicate, page=page, reversed=reversed_))

    for c in bank.claims(root):
        if c.predicate in ON_PROJECT:
            target = bank.resolve(c.object) if c.object_kind != "literal" else None
            claim_row(c, root, target if target != root else None, reversed_=False)
    for page, claims in (reverse or {}).items():
        for c in claims:
            if c.predicate == "works-on" and bank.type_of(page) == "person" or c.predicate in ON_PROJECT:
                claim_row(c, page, page, reversed_=True)
    out.sort(key=lambda r: (r.day or "", r.id), reverse=True)
    return out[:MAX_SHOWN]


def add(memory_path: Path, stem: str, *, url: str | None = None, what: str | None = None,
        entity: str | None = None, how: str | None = None, observer: str, author: str,
        origin: str | None = None, session_id: str | None = None, evidence: list[dict] | None = None,
        today: date | None = None) -> dict:
    """One influence on the project. ``{action, kind: source|claim, page, claim_id?, ref?, paths}``.

    A ``url`` goes to the project's sources (``added_by`` the author). Otherwise ``entity`` (a page id the person
    picked) or ``what`` (a name: an existing page when it resolves exactly, else plain text) becomes one claim."""
    how = (how or "inspired").strip().lower()
    if how not in HOW:
        raise InfluenceError("`how` is inspired, reference, uses or person.")
    predicate = HOW[how]
    url = (url or "").strip()
    if url:
        try:
            entry = fact_sources.add_source(memory_path, stem, url, predicate=None if how == "person" else predicate,
                                            added_by=author, origin=origin, via_agent=author != fact_sources.USER,
                                            added_at=(today or date.today()).isoformat())
        except (fact_sources.InvalidSource, fact_sources.SourceRemoved, fact_sources.SourceCapReached) as exc:
            raise InfluenceError(str(exc)) from None
        if entry is None:
            raise InfluenceError("That link couldn't be added.")
        return {"action": "added", "kind": "source", "page": stem, "ref": entry["ref"],
                "predicate": entry.get("predicate"), "paths": [f"entities/{stem}.md"]}
    target = None
    if entity:
        page = resolve_entity_file(memory_path, entity.strip())
        if page is None:
            raise InfluenceError(f"No page {entity!r}; name it as `what` to add it as something new.")
        target = page.stem
    elif what and what.strip():
        name = " ".join(what.split())
        if len(name) > 200:
            raise InfluenceError("Name it in at most 200 characters.")
        from api.services import project_ownership

        target = project_ownership.existing_named(memory_path, name)
        if target is None:
            object_, kind = name, "literal"
    else:
        raise InfluenceError("Give a link, or name what influenced it.")
    if target == stem:
        raise InfluenceError("A project can't be its own influence.")
    if target is not None:
        object_, kind = target, "node"
    subject = stem
    if how == "person":
        tfm = markdown_parser.parse(Path(memory_path) / "entities" / f"{target}.md").frontmatter if target else {}
        if target is not None and str(tfm.get("type") or "") == "person":
            subject, object_, kind = target, stem, "node"
        else:
            predicate = "references"
    result = agentic_write.write_claim(
        memory_path, subject, predicate, object_, observer=observer, object_kind=kind, session_id=session_id,
        origin=origin, evidence=evidence, authored_by=author, today=today, force_new_entity=False,
        source_episode=(evidence or [{}])[0].get("episode") if evidence else None)
    if result.get("action") in ("error", "ambiguous_subject", None) or not result.get("claim_id"):
        raise InfluenceError(str(result.get("error") or "That influence couldn't be recorded."))
    return {"action": "added", "kind": "claim", "page": result["entity_id"], "claim_id": result["claim_id"],
            "paths": [result["path"]] if result.get("path") else [f"entities/{subject}.md"]}


@page_lock.locked
def withdraw_claim(memory_path: Path, page: str, claim_id: str, *, author: str = "user",
                   today: date | None = None) -> dict:
    """The person's Undo: close the claim with a ``retracts`` record (history, never deleted). The person may take
    back any influence claim on the project's own page or a person's ``works-on`` naming it — their word overrules."""
    path = resolve_entity_file(memory_path, page)
    if path is None:
        return {"action": "not_found"}
    parsed = markdown_parser.parse(path)
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError:
        return {"action": "error", "error": "the page's claims block is unreadable; nothing was changed"}
    same = [c for c in claims if c.id == claim_id]
    target = next((c for c in same if c.valid_to is None), None)
    if target is None or is_event(target) or target.predicate not in (*ON_PROJECT, "works-on"):
        return {"action": "not_found"}
    day = (today or date.today()).isoformat()
    record = agentic_write._withdrawal_record(target, claims, reason=WITHDRAW_REASON, author=author,
                                              origin="manual_edit", session_id=None,
                                              spans=[evidence.reasoning("")], day=day,
                                              fallback_subject=path.stem)
    target.valid_to = day
    target.superseded_by = record.id
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [*claims, record]))
    return {"action": "retracted", "page": path.stem, "claim_id": claim_id, "paths": [f"entities/{path.name}"]}
