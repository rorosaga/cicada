"""G141 §5.1 — the ONE module that writes an event claim ($0, engine-free).

Every writer — an agent over MCP (`cicada_note_progress`), the person in the app
(`routers/projects.py`), an inbox follow-up answer, the demo generator — goes
through here, so the born-closed rule (R-PJ3), the dated ids, span-identity
dedup (`claim_reconciler.reconcile_events`), the surface check (R-PJ15), the
date resolver (R-PJ6) and the `last_referenced` bump (R-PJ12) cannot drift
between writers. `agentic_write.write_claim` refuses these predicates and
`claim_pipeline` relabels a stray Stage-1 label, so nothing else can write one.

The callers pass the ACTIVE bank's path (the split-brain rule) and commit the
memory-relative `paths` this returns themselves — each with its own author and
trigger; nothing here commits and nothing here raises on a normal input (an
error is an `{"action": "error"}` reply, the `agentic_write` contract).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
from pathlib import Path

from loguru import logger

from api.services import claim_expiry, inbox_generator, markdown_parser, owner_identity, telemetry
from api.services import evidence as evidence_mod
# Aliased: `record_happening` takes a `when` argument (the MCP schema's name), so
# a bare module name would be the caller's string inside it (Global Constraints).
from api.services import when as when_mod
from api.services.agentic_write import MAX_REASON_CHARS, _withdrawal_record
from api.services.claim_reconciler import is_human, reconcile_stage3
from api.services.claims import (EVENT_STATUSES, HAPPENED, MILESTONE, PARTICIPANT_ROLES, Claim,
                                 MalformedClaimsBlockError, clean_participants, is_event, parse_claims,
                                 write_claims)
from api.services.id_utils import bank_file, resolve_entity_file, sanitize_id

OBJECT_CHARS = 120
_DUE_SLUG = re.compile(r"^due-(\d{4}-\d{2}-\d{2})(?:-\d+)?$")


@dataclass
class _Settings:
    """`reconcile_stage3`'s duck-typed settings for an event write.
    `litellm_model` is only the `_stamp_new` fallback author — every writer
    here passes its own `authored_by`, so it never reaches a page."""
    memory_path: Path
    litellm_model: str = "progress"
    archive_threshold: float = 0.2
    decay_nudge_threshold: float = 0.4
    auto_settle: bool = False          # R-PJB25: PJ-7's switch


def normalize_sentence(text: str) -> str:
    """A happening's `object`: the sentence folded to lower-case single spaces,
    so rule 2 of `reconcile_events` ("same day and words") compares words, not
    whitespace, and an id hashes the same sentence the same way."""
    return " ".join((text or "").lower().split())[:OBJECT_CHARS]


def event_claim_id(subject: str, predicate: str, key: str, valid_from: str, taken: set[str]) -> str:
    """§5.1: `clm_<subject>_<predicate>_<sha8>_<valid_from>`, the slug in place
    of the hash for a milestone; `-2`, `-3` … on a same-day collision. The
    date is in the id because the same words on two days are two happenings
    (`agentic_write._claim_id` has none — one fact, one id)."""
    part = key if predicate == MILESTONE else hashlib.sha1(
        f"{subject}\x00{predicate}\x00{key}".encode("utf-8")).hexdigest()[:8]
    base = f"clm_{subject}_{predicate}_{part}_{valid_from}"
    cid, n = base, 1
    while cid in taken:
        n += 1
        cid = f"{base}-{n}"
    return cid


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _error(message: str, **extra) -> dict:
    return {"action": "error", "error": message, **extra}


def _page(memory_path: Path, subject: str):
    """`(page, entity_id, parsed, claims)` for an EXISTING page, or a reply.

    Never creates a page: an event belongs to a project the person already
    has, and a typo must not mint a stub (the `write_claim` duplicate-stub
    finding). A corrupt fence is refused — a lenient parse would read it as
    "no claims" and the rewrite would wipe it."""
    subject = (subject or "").strip()
    page = resolve_entity_file(memory_path, subject) if subject else None
    if page is None or not page.exists():
        return {"action": "not_found", "error": f"no page for {subject!r}; nothing was written"}
    # `resolve_entity_file` can echo the caller's casing on a case-insensitive
    # filesystem; the real stem is the id every claim keys off.
    page = next((f for f in page.parent.glob("*.md") if f.name.lower() == page.name.lower()), page)
    try:
        parsed = markdown_parser.parse(page)
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError:
        return _error(f"{page.stem} has an unreadable claims block; nothing was written")
    return page, page.stem, parsed, claims


def _zone(tz_name: str | None) -> tzinfo:
    """The machine zone unless the caller names one (R-PJ6: dates are decided
    where the person lives, and a zone is never worth a failed write)."""
    if not tz_name:
        from api.services import handshake

        tz_name = handshake.local_timezone()
    return when_mod.zone(tz_name)


def _default_now(today: date | None, tz: tzinfo) -> datetime:
    """Noon of `today` in `tz` when a day is pinned (the demo, a test), so a
    pinned writer never reads the real clock; else the real now."""
    if today is not None:
        return datetime.combine(today, time(12, 0), tzinfo=tz)
    return datetime.now(tz)


def _owner_id(memory_path: Path) -> str:
    """The same call `agentic_write.write_claim` makes, so "is this observer
    the owner" and `source_trust` agree across writers."""
    from api.config import get_settings

    return owner_identity.resolve_observer(memory_path, get_settings())


def _observer(memory_path: Path, observer: str | None) -> tuple[str, str]:
    """`(observer, owner)` with the two portable keywords normalised to the
    resolved owner (G117), exactly as `write_claim` does."""
    owner = _owner_id(memory_path)
    observer = (observer or "agent").strip() or "agent"
    if observer in (owner_identity.DEFAULT_OBSERVER, owner_identity.LEGACY_OBSERVER):
        observer = owner
    return observer, owner


def _spans(memory_path: Path, evidence, source_episode: str | None) -> list:
    """G118: verified spans, else one `reasoning` entry — provenance never
    blocks memory (the `write_claim` R6 rule)."""
    spans = evidence_mod.verify_many(memory_path, evidence)
    if not spans:
        spans = [evidence_mod.verify(memory_path, source_episode, "") if source_episode
                 else evidence_mod.reasoning("")]
    return spans


def _anchor(memory_path: Path, spans: list, now: datetime, tz: tzinfo) -> when_mod.Anchor:
    """What a time word is resolved against (R-PJ6): the cited turn's own `ts`,
    else the cited episode's `timestamp`, else the write instant. "Yesterday"
    in a conversation means the day before the person SAID it — not the day
    before an agent or Sleep got round to writing it down."""
    for ev in spans:
        if not ev.episode:
            continue
        doc = evidence_mod.source_document(memory_path, ev.episode)
        if doc is None:
            continue
        fm, text = doc
        if ev.is_span():
            turn = evidence_mod.turn_at(text, ev.start, evidence_mod.turn_stamps(fm))
            instant = when_mod.parse_instant((turn or {}).get("ts"))
            if instant is not None:
                return when_mod.Anchor(instant, "turn", tz)
        instant = when_mod.parse_instant(fm.get("timestamp"))
        if instant is not None:
            return when_mod.Anchor(instant, "episode", tz)
    return when_mod.Anchor(now, "written", tz)


def _entity_index(memory_path: Path) -> tuple[dict[str, str], str | None]:
    """`(lower-cased name/alias/slug → stem, the owner: true page)` in one pass
    over `entities/`. Exact keys only — a participant is never linked by a
    fuzzy guess (R-PJ15)."""
    index: dict[str, str] = {}
    owner_page: str | None = None
    for f in sorted((memory_path / "entities").glob("*.md")):
        try:
            fm = markdown_parser.parse(f).frontmatter or {}
        except Exception:  # noqa: BLE001 — one unreadable page never fails a write
            fm = {}
        stem = f.stem
        index.setdefault(stem.lower(), stem)
        index.setdefault(stem.replace("-", " ").lower(), stem)
        names = [fm.get("name")] + list(fm.get("aliases") or [])
        for name in names:
            name = str(name or "").strip()
            if name:
                index.setdefault(name.lower(), stem)
                index.setdefault(sanitize_id(name), stem)
        if fm.get("owner") is True and owner_page is None:
            owner_page = stem
    return index, owner_page


def _entity_page(memory_path: Path, ref: str) -> Path | None:
    """The `entities/<ref>.md` page for a ref that IS one bank id, else None.

    Task 4 review r1 (finding 1, probe-confirmed): a bare
    `(entities / f"{ref}.md").exists()` let `../episodes/<ep>` — or a relative
    path to any .md outside the bank — through; the ref was stored on the
    claim and `_bump` then rewrote that file's frontmatter. `participants`
    reaches this from MCP, remote `record` scope included. The guard is
    `id_utils.bank_file`, the one rule every id-to-page join already uses
    (G135 Task 5 review): a stem with a separator is never a real id and is
    refused lexically, with no `resolve()`, so a bank or page that is itself a
    symlink still works — and a legacy stem `sanitize_id` would not produce
    (upper case) is still a page, not a refusal."""
    path = bank_file(memory_path / "entities", str(ref or "").strip())
    return path if path is not None and path.is_file() else None


def _participants(memory_path: Path, raw, text: str) -> list[dict]:
    """Who took part, linked where the bank already knows them.

    Agent input `{name, role, url}` maps `name` → `surface`. `owner` always
    links the owner page (`owner: true`, else the resolved observer's page) —
    never by name, so "Bob" in a sentence is the person however the page is
    titled. Any other role links by exact slug, then the name/alias index.
    `surface` is kept only when it is an exact substring of `text` (R-PJ15: the
    sentence is never rewritten to fit a name); `url` only for a document; an
    entry left with neither `surface` nor `entity` says nothing and is dropped.
    """
    items = [dict(p) for p in (raw or []) if isinstance(p, dict)]
    if not items:
        return []
    # Task 4 review r1 (finding 3): the name/alias index parses every page
    # under entities/, so it is built only when an exact slug did not settle
    # a participant — most calls name pages by id and never pay for it.
    cache: dict = {}

    def index_and_owner():
        if "v" not in cache:
            cache["v"] = _entity_index(memory_path)
        return cache["v"]

    def owner_page():
        page = index_and_owner()[1]
        if page is None:
            oid = _owner_id(memory_path)
            page = oid if _entity_page(memory_path, oid) is not None else None
        return page

    out: list[dict] = []
    for item in items:
        role = str(item.get("role") or "").strip()
        if role not in PARTICIPANT_ROLES:
            continue
        surface = str(item.get("surface") or item.get("name") or "").strip()
        entity = None
        if role == "owner":
            entity = owner_page()
        else:
            for ref in (item.get("entity"), surface):
                ref = str(ref or "").strip()
                if ref and _entity_page(memory_path, ref) is not None:
                    entity = ref
                    break
            if entity is None:
                # A name, never a path: the index maps only to stems it read
                # off entities/ itself, so an unsafe ref cannot come back out.
                index = index_and_owner()[0]
                for ref in (item.get("entity"), surface):
                    ref = str(ref or "").strip()
                    if ref:
                        entity = index.get(ref.lower()) or index.get(sanitize_id(ref))
                        if entity:
                            break
        entry = {"role": role}
        if surface and surface in text:
            entry["surface"] = surface
        if entity:
            entry["entity"] = entity
        if role == "document" and item.get("url"):
            entry["url"] = str(item["url"])
        if "surface" in entry or "entity" in entry:
            out.append(entry)
    return clean_participants(out)


def _inbox_names(memory_path: Path) -> set[str]:
    inbox = memory_path / "inbox"
    return {f.name for f in inbox.glob("*.md")} if inbox.exists() else set()


def _reconcile_write(memory_path: Path, page: Path, entity_id: str, parsed, existing: list[Claim],
                     claim: Claim, today: date) -> tuple[list[Claim], list[dict], list[dict], list[str]]:
    """One claim through Stage 3's event branch, the page written only when its
    body changed, the audit to the ledger (G113) and any divergence item into
    the inbox. Returns the inbox paths it created so the caller commits them."""
    reconciled, nudges, audit = reconcile_stage3([claim], {entity_id: existing}, _Settings(memory_path),
                                                 now_date=today.isoformat())
    telemetry.record_audit(audit, subject_hint=entity_id, bank=memory_path.name, stage="reconcile")
    claims = reconciled.get(entity_id, existing)
    body = write_claims(parsed.body, claims)
    if body != parsed.body:
        markdown_parser.write(page, parsed.frontmatter, body)
    inbox_paths: list[str] = []
    if nudges:
        before = _inbox_names(memory_path)
        inbox_generator.write_claim_nudges(nudges, memory_path)
        inbox_paths = [f"inbox/{n}" for n in sorted(_inbox_names(memory_path) - before)]
    return claims, nudges, audit, inbox_paths


def _write_claims(page: Path, parsed, claims: list[Claim]) -> None:
    body = write_claims(parsed.body, claims)
    if body != parsed.body:
        markdown_parser.write(page, parsed.frontmatter, body)


def _bump(memory_path: Path, ids: list[str], day: str) -> list[str]:
    """R-PJ12: an event is a mention — `last_referenced = max(existing, day)` on
    each live page it names, so a project with fresh happenings never reads
    as quiet to decay. Never moves a date backwards. Returns changed paths."""
    changed: list[str] = []
    for eid in dict.fromkeys(i for i in ids if i):
        # Task 4 review r1: only a page directly inside entities/ is ever
        # touched — an id read back off a claim is data, not a path.
        path = _entity_page(memory_path, eid)
        if path is None:
            continue
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001
            continue
        fm = dict(parsed.frontmatter or {})
        current = str(fm.get("last_referenced") or "")[:10]
        if current >= day:
            continue
        fm["last_referenced"] = day
        markdown_parser.write(path, fm, parsed.body)
        changed.append(f"entities/{path.name}")
    return changed


def _outcome(claim: Claim, claims: list[Claim], audit: list[dict]) -> str:
    """The write's result for the caller's reply and commit line."""
    if getattr(claim, "_folded_into", None):
        return "reinforced"
    if any(a.get("dropped") == claim.id for a in audit):
        return "rejected"
    if getattr(claim, "_status_note", None) == "shadowed_by_human":
        return "coexist"
    return "written" if any(c is claim for c in claims) else "reinforced"


def _open_head(claims: list[Claim], slug: str) -> Claim | None:
    return next((c for c in claims if c.predicate == MILESTONE and c.valid_to is None
                 and (c.object or "") == slug), None)


def _free_slug(claims: list[Claim], base: str) -> str:
    slug, n = base, 1
    while _open_head(claims, slug) is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def _target(target: str | None, today: date | None, tz: tzinfo) -> tuple[str | None, str | None]:
    """`(YYYY-MM-DD, None)` or `(None, error)`. A target must be a date the
    closed table reads, within two years — "soonish" is not a plan."""
    if target is None or str(target).strip() == "":
        return None, None
    day, basis = when_mod.resolve(str(target), when_mod.Anchor(_default_now(today, tz), "written", tz),
                                  direction=when_mod.FUTURE)
    if day is None or basis != "stated":
        return None, "a target must be a date within two years; nothing was written"
    return day.isoformat(), None


def _paths(page: Path, *more: list[str]) -> list[str]:
    out = [f"entities/{page.name}"]
    for group in more:
        out.extend(group)
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------- #
# happenings
# --------------------------------------------------------------------------- #


def record_happening(memory_path: Path, *, subject: str, text: str, status: str, participants=None,
                     when: str | None = None, evidence=None, observer: str, origin: str, authored_by: str,
                     session_id: str | None = None, settles: str | None = None,
                     source_episode: str | None = None, day: date | None = None,
                     date_basis: str | None = None, today: date | None = None, now: datetime | None = None,
                     tz_name: str | None = None) -> dict:
    """Record one thing that happened (or is under way) on `subject`.

    Validated first, written second: a bad status, a relative word in the
    sentence (R-PJ6 — say the day with `when`), a future happening or a
    `settles` naming no open thread is refused before any byte moves, since
    `reconcile_events` appends first and settles second. `day`+`date_basis`
    (the app's date chip) are used as given; otherwise `when` goes through the
    closed table against `_anchor`. Returns `{action: written|reinforced,
    entity_id, claim_id, day, date_basis, matched, settled, paths, evidence}`
    — `claim_id` is the claim it folded into when `reinforced`."""
    try:
        memory_path = Path(memory_path)
        text = " ".join(str(text or "").split())
        if status not in EVENT_STATUSES[HAPPENED]:
            return _error(f"a happening is ongoing, done or dropped — not {status!r}; nothing was written")
        if not text:
            return _error("say what happened; nothing was written")
        if when_mod.has_relative(text):
            return _error("keep the day out of the sentence — pass it as `when` "
                          "(e.g. 'yesterday' or 2026-09-22); nothing was written")
        got = _page(memory_path, subject)
        if isinstance(got, dict):
            return got
        page, entity_id, parsed, existing = got
        if settles:
            if status not in ("done", "dropped"):
                return _error("only a done or dropped happening can settle a thread; nothing was written")
            thread = next((c for c in existing if c.id == settles and c.predicate == HAPPENED
                           and c.status == "ongoing" and c.valid_to is None), None)
            if thread is None:
                return _error(f"no open thread `{settles}` on {entity_id}; nothing was written")
        observer, owner = _observer(memory_path, observer)
        spans = _spans(memory_path, evidence, source_episode)
        tz = _zone(tz_name)
        today = today or date.today()
        matched = False
        if day is not None:
            on, basis = day, (date_basis or "person")
        else:
            anchor = _anchor(memory_path, spans, now or _default_now(today, tz), tz)
            on, basis = when_mod.resolve(when, anchor, direction=when_mod.PAST)
            matched = basis == "stated"
            if on is None:
                ahead, _ = when_mod.resolve(when, anchor, direction=when_mod.FUTURE)
                if ahead is not None and ahead > anchor.day:
                    return _error("a happening can't be in the future — plan it as a milestone; "
                                  "nothing was written")
                return _error("I can't read that date (it must be within the last year); nothing was written")
        valid_from = on.isoformat()
        obj = normalize_sentence(text)
        episodes = list(dict.fromkeys(e.episode for e in spans if e.episode)) or (
            [source_episode] if source_episode else [])
        claim = Claim(
            id=event_claim_id(entity_id, HAPPENED, obj, valid_from, {c.id for c in existing}),
            text=text, subject=entity_id, predicate=HAPPENED, object=obj, object_kind="literal",
            observer=observer, context="general", epistemic="explicit",
            source_trust="user_stated" if observer == owner else "agent_extracted",
            confidence=0.8, valid_from=valid_from, recorded_at=today.isoformat(),
            source_episodes=episodes, origin=origin, authored_by=(authored_by or "").strip() or None,
            session_id=(session_id or "").strip() or None, evidence=spans, status=status,
            participants=_participants(memory_path, participants, text), date_basis=basis)
        if settles:
            setattr(claim, "_settles", settles)
        claims, _, audit, inbox_paths = _reconcile_write(memory_path, page, entity_id, parsed, existing, claim, today)
        bumped = _bump(memory_path, [entity_id] + [p.get("entity") for p in claim.participants], valid_from)
        folded = getattr(claim, "_folded_into", None)
        return {"action": "reinforced" if folded else "written", "entity_id": entity_id,
                "claim_id": folded or claim.id, "day": valid_from, "date_basis": basis, "matched": matched,
                "settled": getattr(claim, "_settle_result", None), "paths": _paths(page, bumped, inbox_paths),
                "evidence": [e.to_dict() for e in spans]}
    except Exception as exc:  # noqa: BLE001 — never raise on a normal input
        logger.warning(f"progress.record_happening failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# milestones
# --------------------------------------------------------------------------- #


def set_milestone(memory_path: Path, *, subject: str, name: str, target: str | None = None,
                  status: str = "planned", slug: str | None = None, on: date | None = None, observer: str,
                  origin: str, authored_by: str, session_id: str | None = None, evidence=None,
                  date_basis: str | None = None, today: date | None = None, tz_name: str | None = None) -> dict:
    """Open a new milestone slot on `subject` (R-PJ4). The slot's key is its
    slug — the `object`, never the `context` — `-2`, `-3` … when an open slot
    already holds that name, so two plans that share a name stay two plans."""
    try:
        memory_path = Path(memory_path)
        name = " ".join(str(name or "").split())
        if not name:
            return _error("a milestone needs a name; nothing was written")
        if when_mod.has_relative(name):
            return _error("keep the day out of the name — pass it as the target; nothing was written")
        if status not in EVENT_STATUSES[MILESTONE]:
            return _error(f"a milestone is planned, done, missed or dropped — not {status!r}; "
                          "nothing was written")
        got = _page(memory_path, subject)
        if isinstance(got, dict):
            return got
        page, entity_id, parsed, existing = got
        tz = _zone(tz_name)
        today = today or date.today()
        tgt, err = _target(target, today, tz)
        if err:
            return _error(err)
        observer, owner = _observer(memory_path, observer)
        spans = _spans(memory_path, evidence, None)
        key = _free_slug(existing, sanitize_id(slug or name))
        valid_from = (on or today).isoformat()
        claim = Claim(
            id=event_claim_id(entity_id, MILESTONE, key, valid_from, {c.id for c in existing}),
            text=name, subject=entity_id, predicate=MILESTONE, object=key, object_kind="literal",
            observer=observer, context="general", epistemic="explicit",
            source_trust="user_stated" if observer == owner else "agent_extracted", confidence=0.8,
            valid_from=valid_from, recorded_at=today.isoformat(),
            source_episodes=list(dict.fromkeys(e.episode for e in spans if e.episode)), origin=origin,
            authored_by=(authored_by or "").strip() or None, session_id=(session_id or "").strip() or None,
            evidence=spans, status=status, target=tgt,
            date_basis=date_basis or ("stated" if tgt else "written"))
        claims, _, audit, inbox_paths = _reconcile_write(memory_path, page, entity_id, parsed, existing, claim, today)
        bumped = _bump(memory_path, [entity_id], valid_from)
        return {"action": _outcome(claim, claims, audit), "entity_id": entity_id,
                "claim_id": getattr(claim, "_folded_into", None) or claim.id, "slug": key, "target": tgt,
                "paths": _paths(page, bumped, inbox_paths), "evidence": [e.to_dict() for e in spans]}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"progress.set_milestone failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def advance(memory_path: Path, *, subject: str, slug: str, status: str | None = None, on: date | None = None,
            target: str | None = None, observer: str, origin: str, authored_by: str,
            session_id: str | None = None, evidence=None, date_basis: str = "person",
            today: date | None = None, tz_name: str | None = None) -> dict:
    """A milestone's new state or date — a NEW claim in its slot (R-PJ4: the
    state is as of `valid_from`, so a change is never an in-place edit).
    `reconcile_events` decides who may close the head (R-PJB27). A read-compat
    `due-<date>` slug (a G17 `due` the read model shows as a milestone) is
    promoted to the first real milestone on its first touch."""
    try:
        memory_path = Path(memory_path)
        if status is not None and status not in EVENT_STATUSES[MILESTONE]:
            return _error(f"a milestone is planned, done, missed or dropped — not {status!r}; "
                          "nothing was written")
        got = _page(memory_path, subject)
        if isinstance(got, dict):
            return got
        page, entity_id, parsed, existing = got
        tz = _zone(tz_name)
        today = today or date.today()
        tgt, err = _target(target, today, tz)
        if err:
            return _error(err)
        observer, owner = _observer(memory_path, observer)
        spans = _spans(memory_path, evidence, None)
        valid_from = (on or today).isoformat()
        taken = {c.id for c in existing}

        def build(key: str, text: str, new_status: str, new_target: str | None) -> Claim:
            return Claim(
                id=event_claim_id(entity_id, MILESTONE, key, valid_from, taken),
                text=text, subject=entity_id, predicate=MILESTONE, object=key, object_kind="literal",
                observer=observer, context="general", epistemic="explicit",
                source_trust="user_stated" if observer == owner else "agent_extracted", confidence=0.8,
                valid_from=valid_from, recorded_at=today.isoformat(),
                source_episodes=list(dict.fromkeys(e.episode for e in spans if e.episode)), origin=origin,
                authored_by=(authored_by or "").strip() or None,
                session_id=(session_id or "").strip() or None, evidence=spans, status=new_status,
                target=new_target, date_basis=date_basis)

        head = _open_head(existing, slug)
        if head is not None:
            claim = build(slug, head.text, status or head.status or "planned", tgt or head.target)
            claims, _, audit, inbox_paths = _reconcile_write(memory_path, page, entity_id, parsed, existing,
                                                             claim, today)
            bumped = _bump(memory_path, [entity_id], valid_from)
            return {"action": _outcome(claim, claims, audit), "entity_id": entity_id,
                    "claim_id": getattr(claim, "_folded_into", None) or claim.id, "slug": slug,
                    "supersedes": claim.supersedes, "paths": _paths(page, bumped, inbox_paths),
                    "evidence": [e.to_dict() for e in spans]}

        m = _DUE_SLUG.match(slug or "")
        due = None
        if m:
            due = next((c for c in existing if c.predicate == "due" and not c.superseded_by
                        and claim_expiry.stated_end(c) == m.group(1)), None)
        if due is None:
            return {"action": "not_found", "error": f"no milestone `{slug}` on {entity_id}; nothing was written"}
        from api.services.project_timeline import _due_name  # one naming rule for reader and writer

        display = str((parsed.frontmatter or {}).get("name") or entity_id)
        name = _due_name(due, display)
        key = _free_slug(existing, sanitize_id(name))
        claim = build(key, name, status or "planned", tgt or claim_expiry.stated_end(due))
        if is_human(due) and not is_human(claim):
            return _error("the person set this date themselves; only they can move it")
        # R-PJ4: the only mutation a closed `due` receives is `superseded_by`;
        # an open one closes where the milestone begins, never before it opened.
        # Set before the reconcile so one page write carries both halves (the
        # new slug has no head, so the milestone is always appended).
        claim.supersedes = due.id
        due.superseded_by = claim.id
        if due.valid_to is None:
            due.valid_to = max(valid_from, (due.valid_from or "")[:10] or valid_from)
        claims, _, audit, inbox_paths = _reconcile_write(memory_path, page, entity_id, parsed, existing, claim,
                                                         today)
        bumped = _bump(memory_path, [entity_id], valid_from)
        return {"action": _outcome(claim, claims, audit), "entity_id": entity_id, "claim_id": claim.id,
                "slug": key, "supersedes": due.id, "paths": _paths(page, bumped, inbox_paths),
                "evidence": [e.to_dict() for e in spans]}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"progress.advance failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def rename_milestone(memory_path: Path, *, subject: str, slug: str, name: str) -> dict:
    """The one in-place edit: the open head's `text` only. A name is a label,
    not a state — git keeps the history, and the slug (the slot) never moves.
    Callers allow it for the person only."""
    try:
        memory_path = Path(memory_path)
        name = " ".join(str(name or "").split())
        if not name or when_mod.has_relative(name):
            return _error("give the milestone a name without a day in it; nothing was written")
        got = _page(memory_path, subject)
        if isinstance(got, dict):
            return got
        page, entity_id, parsed, existing = got
        head = _open_head(existing, slug)
        if head is None:
            return {"action": "not_found", "error": f"no milestone `{slug}` on {entity_id}; nothing was written"}
        head.text = name
        _write_claims(page, parsed, existing)
        return {"action": "renamed", "entity_id": entity_id, "claim_id": head.id, "slug": slug,
                "paths": [f"entities/{page.name}"]}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"progress.rename_milestone failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def withdraw(memory_path: Path, *, subject: str, claim_id: str, author: str, reason: str, origin: str,
             session_id: str | None = None, evidence=None, today: date | None = None) -> dict:
    """Take an event back, keeping it as history (G140 Q-R5's record).

    Ownership is the CALLER's check (the MCP wrapper through
    `agentic_write.owns`; the person may withdraw any claim). A born-closed
    done happening keeps its `valid_to` — that is its shape — and gains only
    `superseded_by` (§5.1: the one mutation a closed event ever receives), so
    `agentic_write.retract_claim`'s "already closed" answer could never reach
    it. A milestone state that replaced an earlier plan is refused (R-PJB28):
    withdrawing it would leave the slot with no open head."""
    try:
        memory_path = Path(memory_path)
        reason = " ".join(str(reason or "").split())[:MAX_REASON_CHARS]
        if not reason:
            return _error("a reason is required — say why it's wrong; nothing was changed")
        got = _page(memory_path, subject)
        if isinstance(got, dict):
            return got
        page, entity_id, parsed, claims = got
        same = [c for c in claims if c.id == claim_id]
        target = next((c for c in same if c.valid_to is None), same[0] if same else None)
        if target is None or not is_event(target):
            return {"action": "not_found", "entity_id": entity_id,
                    "error": f"no happening or milestone {claim_id!r} on {entity_id}"}
        if target.superseded_by:
            return {"action": "already_closed", "entity_id": entity_id, "claim_id": claim_id,
                    "valid_to": target.valid_to}
        if target.predicate == MILESTONE and target.supersedes and any(
                c.id == target.supersedes and c.superseded_by == target.id for c in claims):
            return _error("that replaced an earlier plan — move it or mark it instead")
        day = (today or date.today()).isoformat()
        spans = evidence_mod.verify_many(memory_path, evidence) or [evidence_mod.reasoning("")]
        record = _withdrawal_record(target, claims, reason=reason, author=author, origin=origin,
                                    session_id=session_id, spans=spans, day=day, fallback_subject=entity_id)
        if target.valid_to is None:
            target.valid_to = max(day, (target.valid_from or "")[:10] or day)
        target.superseded_by = record.id
        _write_claims(page, parsed, [*claims, record])
        return {"action": "retracted", "entity_id": entity_id, "claim_id": claim_id, "record_id": record.id,
                "paths": [f"entities/{page.name}"], "evidence": [e.to_dict() for e in spans]}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"progress.withdraw failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")
