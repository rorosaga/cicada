"""Unified inbox service — one read path + one kind-dispatched resolver.

Replaces the split ``nudges`` / ``clarifications`` plumbing. All pending items
live as ``memory/inbox/inbox-NNN.md`` with a ``kind`` discriminator; this module
loads them into ``InboxItem`` and resolves them by routing on ``kind``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from api.config import Settings
from api.models.schemas import InboxItem, InboxOption, InboxResolveRequest
from api.services import decay_policy, inbox_questions, markdown_parser
from api.services.id_utils import resolve_entity_file, sanitize_id

logger = logging.getLogger(__name__)


# ---------- Loading ----------


def _inbox_dir(memory_path: Path) -> Path:
    return memory_path / "inbox"


def next_inbox_num(inbox_dir: Path) -> int:
    """Next inbox number = max existing number + 1 (never count-based)."""
    max_num = 0
    for filepath in inbox_dir.glob("inbox-*.md"):
        try:
            max_num = max(max_num, int(filepath.stem.split("-")[-1]))
        except ValueError:
            continue
    return max_num + 1


def _required_input_for(kind: str) -> str:
    if kind == "decay":
        return "choice"
    if kind == "conflict":
        return "choice"
    if kind == "merge_suggestion":
        return "merge"
    return "freetext"


def _item_from_file(filepath: Path, *, today: str | None = None) -> InboxItem:
    parsed = markdown_parser.parse(filepath)
    fm = parsed.frontmatter
    kind = str(fm.get("kind", "decay"))
    required_input = str(fm.get("required_input", "") or _required_input_for(kind))
    now = today or str(date.today())

    options: list[InboxOption] = []
    for raw in inbox_questions.normalize_options(fm.get("options")):
        observed = _opt_str(raw.get("observed_at"))
        last_ref = _opt_str(raw.get("last_referenced")) or observed
        options.append(
            InboxOption(
                key=str(raw.get("key", "")),
                label=str(raw.get("label", "")),
                description=_opt_str(raw.get("description")),
                claim_id=_opt_str(raw.get("claim_id")),
                observed_at=observed,
                last_referenced=last_ref,
                age_days=inbox_questions.age_days(last_ref, now),
            )
        )

    return InboxItem(
        id=filepath.stem,
        kind=kind,
        required_input=required_input,
        status=str(fm.get("status", "pending") or "pending"),
        priority=float(fm.get("priority", 0.0) or 0.0),
        entity_id=str(fm.get("entity_id", "") or ""),
        entity_name=str(fm.get("entity_name", "") or ""),
        title=str(fm.get("title", "") or fm.get("entity_name", "") or ""),
        body=parsed.body,
        options=options,
        created_date=str(fm.get("created_date", "") or ""),
        question=_opt_str(fm.get("question")),
        # Conflicts and clarifications always accept a free-text answer and a
        # deferral on the resolve path, so legacy items (written before G60,
        # no allow_* keys) must not lock the user into the closed option set.
        allow_other=bool(fm.get("allow_other", kind in ("conflict", "clarification"))),
        allow_defer=bool(fm.get("allow_defer", kind in ("conflict", "clarification"))),
        predicate=_opt_str(fm.get("predicate")),
        hint=_opt_str(fm.get("hint")),
        remind_after=_opt_str(fm.get("remind_after")),
        updated_date=_opt_str(fm.get("updated_date")),
        uncertainty_type=fm.get("uncertainty_type"),
        suggested_classification=fm.get("suggested_classification"),
        suggested_confidence=fm.get("suggested_confidence"),
        merge_target_hint=fm.get("merge_target_hint"),
    )


def _opt_str(value: object) -> str | None:
    """Normalize an optional YAML scalar to ``str`` (YAML may parse dates)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _subject_gone(memory_path: Path, entity_id: str, kind: str) -> bool:
    """G98: True when ``entity_id`` no longer names a live entity.

    The decay engine can archive (or a merge/manual edit can drop) the very
    entity an inbox item is still asking about — the item then becomes
    structurally unanswerable and must not be served. An unparseable page is
    NOT treated as gone (fail open — a read error must not silently hide a
    live question).

    **A missing page is kind-aware (Devin PR #24 round 1, finding 1).** For
    ``conflict`` and ``merge_suggestion`` a missing subject genuinely means
    the question is dead — those kinds are only ever generated FROM an
    existing page. A ``clarification``, though, can legitimately be about an
    entity that has no page yet: answering it is what CREATES the page (see
    ``clarification_manager`` — the subject is minted with no existence
    check). Gating a missing-page clarification would remove the user's only
    manual path to promote it, so a missing page is NOT "gone" for that kind
    — only an explicit ``archived``/``dropped`` status is, same as every
    other kind, since that is a real "we gave up on this" signal regardless
    of whether the item is asking a question or reporting a conflict.
    """
    if not entity_id:
        return False
    filepath = resolve_entity_file(memory_path, entity_id)
    if filepath is None:
        return kind != "clarification"
    try:
        fm = markdown_parser.parse(filepath).frontmatter
    except Exception:
        return False
    return str(fm.get("status", "active") or "active") in ("archived", "dropped")


def load_inbox(memory_path: Path, *, include_deferred: bool = False) -> list[InboxItem]:
    """Load inbox items, sorted: pending first, then priority desc, date desc.

    Deferred items (``remind_after`` still in the future, §2.3-4) are hidden by
    default — the file stays on disk and the card returns on its own the day the
    date passes. ``include_deferred=True`` is for maintenance callers.

    Two defensive filters (G98) apply regardless of ``include_deferred``, and
    filter at read only — nothing is deleted on disk:
    - an item that fails to parse is skipped with a logged warning naming the
      file (previously a bare ``except: continue`` made it invisible forever,
      e.g. ``inbox-3747.md``'s unquoted colon in ``uncertainty_type``);
    - an item whose subject is ``archived``/``dropped`` is skipped for every
      kind; an item whose ``entity_id`` resolves to no file at all is skipped
      for ``conflict``/``merge_suggestion``/``decay`` (only ever generated
      FROM an existing page) but kept for ``clarification`` — its subject can
      legitimately not have a page yet, and answering it is what creates one
      (see :func:`_subject_gone`).
    """
    inbox_dir = _inbox_dir(memory_path)
    today = str(date.today())
    items: list[InboxItem] = []
    for filepath in sorted(inbox_dir.glob("inbox-*.md")):
        try:
            item = _item_from_file(filepath, today=today)
        except Exception as exc:
            logger.warning(f"skipping unparseable inbox item {filepath.name}: {exc}")
            continue
        if not include_deferred and item.remind_after and inbox_questions.is_deferred(
            {"remind_after": item.remind_after}, today
        ):
            continue
        if _subject_gone(memory_path, item.entity_id, item.kind):
            continue
        items.append(item)
    # pending first, then priority desc, then created_date desc.
    items.sort(
        key=lambda i: (
            0 if i.status == "pending" else 1,
            -i.priority,
            _neg_date_key(i.created_date),
        )
    )
    return items


def _neg_date_key(created_date: str) -> str:
    """Invert a YYYY-MM-DD string so ascending sort yields descending dates."""
    inverted = []
    for ch in created_date:
        if ch.isdigit():
            inverted.append(str(9 - int(ch)))
        else:
            inverted.append(ch)
    return "".join(inverted)


# ---------- Date helpers (mirrors conflict_resolver / clarifications) ----------


def _extract_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _max_date(*candidates: str | None) -> str | None:
    values = [c for c in candidates if c]
    return max(values) if values else None


# ---------- Git move/remove helpers (merge-direction renames) ----------


async def _git_move(memory_path: Path, src: Path, dst: Path) -> None:
    """Rename ``src`` -> ``dst`` via ``git mv`` so history follows the file.

    Falls back to a filesystem rename when git refuses (e.g. the file is
    untracked). The trailing ``commit_resolution`` runs ``git add -A`` either
    way, so the move is captured in the commit regardless of path taken.
    """
    from api.services import git_service

    try:
        await git_service._run_git(
            memory_path, "mv", "-f", str(src), str(dst)
        )
    except Exception:
        if src.exists():
            src.replace(dst)


async def _git_remove(memory_path: Path, target: Path) -> None:
    """Remove ``target`` via ``git rm`` (filesystem fallback when untracked)."""
    from api.services import git_service

    try:
        await git_service._run_git(memory_path, "rm", "-f", str(target))
    except Exception:
        if target.exists():
            target.unlink()


# ---------- Resolution dispatch ----------


# Option keys that carry their own meaning rather than pointing at one option:
# "both" keeps every competing claim open, "neither" closes them all.
_SPECIAL_KEYS = {"both", "neither"}


def _action_label(kind: str, request: InboxResolveRequest, options: list[dict]) -> str:
    """Name the action a resolution took, for the commit trigger and the ledger.

    G113: an inbox resolution is the user's verdict on the extractor's belief —
    the grounded reward the Era-of-Experience framing says the system should
    learn from. Recording only that the item was resolved threw that verdict
    away; the label (``archive``, ``pick:1``, ``neither``, ``reject`` …) is what
    lets a later reader tell agreement from overrule. Pure. ``options`` is the
    item's normalized option list (``{"key": ...}`` dicts) so a picked key can be
    checked against the special ``both``/``neither`` keys.
    """
    action = (request.action or "").strip().lower()
    key = (request.option_key or "").strip()
    if kind == "decay":
        return action or "answer"
    if kind in ("conflict", "divergence", "normalization"):
        if action == "dismiss":
            return "dismiss"
        if action == "skip":
            return "skip"
        if key:
            return key if key in _SPECIAL_KEYS else f"pick:{key}"
        if request.answer:
            return "answer"
        return action or "answer"
    # clarification / merge_suggestion
    if action in ("answer", "resolve"):
        return "answer"
    if action in ("dismiss", "merge", "reject", "skip"):
        return action
    return action or "answer"


async def resolve(
    item_id: str, request: InboxResolveRequest, settings: Settings
) -> dict:
    """Resolve an inbox item by routing on its ``kind``. Returns a status dict."""
    path = _inbox_dir(settings.memory_path) / f"{item_id}.md"
    if not path.exists():
        raise HTTPException(404, f"Inbox item {item_id} not found")

    parsed = markdown_parser.parse(path)
    kind = str(parsed.frontmatter.get("kind", "decay"))

    # G60 §2.4 — `defer` is kind-agnostic: it never touches claims or the entity
    # page, it just pushes the item out of sight until `remind_after`.
    if request.action == "defer":
        return await _defer(path, parsed, request, settings, item_id)

    extra_lines: list[str] = []
    if kind == "decay":
        entity_id, skipped = await _resolve_decay(path, parsed, request, settings)
    elif kind == "conflict":
        entity_id, skipped, extra_lines = await _resolve_conflict(
            path, parsed, request, settings
        )
    elif kind in ("clarification", "merge_suggestion"):
        entity_id, skipped = await _resolve_clarification(
            path, parsed, request, settings
        )
    else:
        raise HTTPException(400, f"Unknown kind {kind}")

    if skipped:
        return {"status": "skipped", "id": item_id}

    # Avoid the local import becoming a hard module-load dependency cycle.
    from api.services import git_service

    # G113 R1/R2 — the trigger names the action taken, and a decay verdict
    # states the resulting status so history classifies it as `statusChange`.
    # ``parsed`` was read before the branch unlinked the item file; never
    # re-read it here.
    label = _action_label(
        kind, request, inbox_questions.normalize_options(parsed.frontmatter.get("options") or [])
    )
    change = "updated"
    if kind == "decay" and label == "archive":
        change = "status archived"
    elif kind == "decay" and label == "keep_active":
        change = "status active"
    await git_service.commit_resolution(
        settings.memory_path,
        entity_id,
        f"inbox/{kind}/resolved:{label}",
        extra_lines,
        change=change,
    )
    return {"status": "resolved", "id": item_id}


async def _defer(path, parsed, request, settings, item_id: str) -> dict:
    """Push an item's ``remind_after`` into the future; the file stays.

    The rewritten item is committed here (scoped to the one inbox file) so the
    deferral never lingers as an uncommitted change waiting for the next Sleep
    cycle to sweep it in under an inferred trigger.
    """
    from api.services import git_service

    days = request.remind_days
    if days is None:
        days = int(getattr(settings, "inbox_defer_days", 30) or 30)
    remind_after = str(date.today() + timedelta(days=max(1, int(days))))
    parsed.frontmatter["remind_after"] = remind_after
    parsed.frontmatter["updated_date"] = str(date.today())
    markdown_parser.write(path, parsed.frontmatter, parsed.body)

    rel = f"inbox/{path.name}"
    message = git_service.build_commit_message(
        f"Inbox deferral {date.today().isoformat()}",
        [f"{rel}: deferred until {remind_after} (trigger: inbox/deferred)"],
        authors=["user"],
    )
    try:
        await git_service.commit_paths(settings.memory_path, message, [rel])
    except Exception as exc:  # pragma: no cover - non-git workspace
        logger.warning(f"Inbox defer commit skipped: {exc}")
    return {"status": "deferred", "id": item_id, "remindAfter": remind_after}


async def _resolve_decay(path, parsed, request, settings) -> tuple[str, bool]:
    """Port of the nudges.py decay branch (keep / archive / remind_later)."""
    entity_id = parsed.frontmatter.get("entity_id", "")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"

    if request.action == "keep_active" and entity_path.exists():
        entity = markdown_parser.parse(entity_path)
        entity.frontmatter["status"] = "active"
        entity.frontmatter["confidence"] = max(
            entity.frontmatter.get("confidence", 0.5), 0.6
        )
        entity.frontmatter["last_referenced"] = str(date.today())
        markdown_parser.write(entity_path, entity.frontmatter, entity.body)
        path.unlink()

    elif request.action == "archive" and entity_path.exists():
        entity = markdown_parser.parse(entity_path)
        entity.frontmatter["status"] = "archived"
        markdown_parser.write(entity_path, entity.frontmatter, entity.body)
        path.unlink()

    elif request.action == "remind_later":
        new_date = date.today() + timedelta(days=7)
        parsed.frontmatter["status"] = "snoozed"
        parsed.frontmatter["snooze_until"] = str(new_date)
        markdown_parser.write(path, parsed.frontmatter, parsed.body)

    else:
        # Unknown action on a decay item — fall through to deletion so a stray
        # entity-less decay nudge can still be cleared.
        if entity_path.exists() and request.answer:
            entity = markdown_parser.parse(entity_path)
            entity.frontmatter["last_referenced"] = str(date.today())
            body = entity.body + f"\n\n{request.answer}"
            markdown_parser.write(entity_path, entity.frontmatter, body)
        path.unlink()

    return entity_id, False


def _user_claim_id(entity_id: str, predicate: str, obj: str, today: str) -> str:
    """Stable id for a user-authored resolution claim (mirrors agentic_write)."""
    import hashlib

    digest = hashlib.sha1(
        f"{entity_id}\x00{predicate}\x00{obj}\x00user\x00{today}".encode("utf-8")
    ).hexdigest()[:8]
    return f"clm_{today}_user_{digest}"


def _close_today(old, *, by, today: str) -> None:
    """Bi-temporally close ``old`` in favor of ``by``, but with ``valid_to``
    pinned to *today* (the resolution date) rather than ``_close``'s default of
    the winner's ``valid_from`` — a user resolving a conflict today closes the
    old belief today, regardless of when the winning claim was first observed.
    """
    from api.services.claim_reconciler import _close

    _close(old, by=by)
    old.valid_to = today


async def _resolve_conflict(path, parsed, request, settings) -> tuple[str, bool, list[str]]:
    """Claim-aware conflict adjudication (§2.4).

    The chosen option decides what happens in the ``claims`` block FIRST — a
    winning claim is reinforced and every loser is bi-temporally closed, "both"
    keeps them all open with a context qualifier, and "neither"/free text writes
    a ``user_stated`` claim that closes them. Only then is a full sentence (not
    a raw button label — the old bug) fed to the LLM body rewrite.

    Two requests are refused outright rather than interpreted: an ``option_key``
    that matches no option (400) and a resolve carrying neither a pick nor free
    text (400) — both used to land in the "neither" branch and close every
    competing claim. A claims block that will not parse aborts the resolve
    (409) with the page untouched and the question kept.
    """
    from api.services import predicates
    from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims
    from api.services.conflict_resolver import _synthesize_entity_update

    fm_item = parsed.frontmatter
    entity_id = str(fm_item.get("entity_id", "") or "")

    if request.action == "skip":
        return entity_id, True, []

    # Legacy pre-G60 conflict items carry neither `options` nor `question` —
    # there is nothing to pick from, so the strict "optionKey or answer
    # required" guard below would strand them behind an error toast forever.
    # `InboxCardView`'s bare Dismiss button (and the deprecated `/nudges` shim,
    # whose `NudgeResolveRequest` has no `optionKey` field at all) fire exactly
    # action="dismiss" with no key and no answer for such an item. Honor it the
    # old way: remove the item, touch no claims. A modern question item (has
    # `options` and/or a `question`) still gets the strict 400 below.
    if (
        request.action == "dismiss"
        and not fm_item.get("options")
        and not str(fm_item.get("question", "") or "").strip()
        and not (request.option_key or "").strip()
        and not (request.answer or "").strip()
    ):
        path.unlink()
        return entity_id, False, []

    predicate_raw = str(fm_item.get("predicate", "") or "description")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    options = inbox_questions.normalize_options(fm_item.get("options"))
    option_key = (request.option_key or "").strip()
    answer = (request.answer or "").strip()
    today = str(date.today())
    extra_lines: list[str] = []

    # A pick this function cannot make sense of must NEVER fall through to the
    # "neither" branch below — that branch permanently closes every competing
    # claim on the entity, and a typo'd/absent key is a client bug, not the
    # user saying "none of these". Reject loudly instead; nothing is written.
    known_keys = {str(o.get("key")) for o in options} | {"both", "neither"}
    if option_key and option_key not in known_keys:
        raise HTTPException(
            400,
            f"Unknown optionKey {option_key!r} for {path.stem} — expected one of "
            f"{sorted(known_keys)}, or free text in `answer`.",
        )
    if not option_key and not answer:
        raise HTTPException(
            400,
            f"Resolving conflict {path.stem} requires an optionKey or a free-text "
            "answer (use optionKey='neither' to state that none are current, or "
            "action='defer'/'skip' to postpone).",
        )

    if not entity_path.exists():
        # Nothing to write into; clear the question rather than stranding it.
        path.unlink()
        return entity_id, False, extra_lines

    entity = markdown_parser.parse(entity_path)
    fm = entity.frontmatter
    name = str(fm.get("name", entity_id) or entity_id)
    normalize_predicate = predicates.load_normalizer(settings.memory_path)
    predicate = normalize_predicate(predicate_raw) or predicate_raw

    try:
        claim_list = parse_claims(entity.body, strict=True)
    except MalformedClaimsBlockError as exc:
        # A corrupt claims block must never be silently overwritten — and the
        # rest of this function rewrites the page (an LLM body synthesis on a
        # body whose machine layer we could not read) and then deletes the
        # question. Abort the whole resolve: the entity stays byte-identical,
        # the inbox item stays pending, and the user is told why.
        logger.error(f"inbox resolve aborted — unparseable claims in {entity_path.name}: {exc}")
        raise HTTPException(
            409,
            f"Cannot resolve {path.stem}: the ```claims block in "
            f"entities/{entity_id}.md is malformed ({exc}). Fix the page by hand; "
            "the question has been kept.",
        ) from exc

    by_id = {c.id: c for c in claim_list}
    option_claims = [
        by_id[str(o["claim_id"])]
        for o in options
        if o.get("claim_id") and str(o["claim_id"]) in by_id
    ]
    chosen = next((o for o in options if str(o.get("key")) == option_key), None)

    sentence = answer or ""

    # Picking a real option is an AFFIRMATIVE choice whether or not that option
    # is claim-backed. Legacy (pre-G60) conflicts and every entity-path question
    # built by `conflict_resolver.build_entity_question` carry `claim_id: None`
    # on all options; requiring a claim id here used to drop those picks into
    # the neither/free-text branch below, which stamped "none of these are
    # current" onto the page — the exact opposite of what the user said.
    if chosen is not None and option_key not in ("both", "neither"):
        winner = by_id.get(str(chosen.get("claim_id") or ""))
        if winner is not None:
            winner.confidence = max(winner.confidence, 0.9)
        for loser in option_claims:
            if winner is not None and loser.id == winner.id:
                continue
            if loser.valid_to is None:
                if winner is not None:
                    _close_today(loser, by=winner, today=today)
                else:
                    # The pick is claim-less, so there is no claim to point
                    # the supersession at — but the losing values are still
                    # no longer current, and leaving them open would just
                    # regenerate this question next cycle.
                    loser.valid_to = today
                line = (
                    f"entities/{entity_id}.md: updated "
                    f"(source: {path.stem}, trigger: inbox/conflict/resolved)"
                )
                # The manifest is a set of paths, not a per-claim tally.
                if line not in extra_lines:
                    extra_lines.append(line)
        # The chosen label IS the answer, claim-backed or not.
        sentence = (
            f"{predicates.predicate_phrase(predicate, name, chosen['label'])} "
            f"(confirmed by user on {today})."
        )

    else:
        if option_key == "both":
            labels = []
            for claim in option_claims:
                if claim.context == "general":
                    claim.context = f"as of {claim.valid_from or today}"
                labels.append(claim.object)
            sentence = (
                f"Both are true: {' and '.join(labels)} (confirmed by user on {today})."
                if labels else sentence
            )

        else:
            # `neither`, or free text with no option key.
            if answer:
                new_claim = Claim(
                    id=_user_claim_id(entity_id, predicate, answer, today),
                    text=f"{predicates.predicate_phrase(predicate, name, answer)}.",
                    subject=entity_id,
                    predicate=predicate,
                    object=answer,
                    # Keep the SAME belief slot (observer) as the claims being
                    # replaced so future reconciliation sees one lineage.
                    observer=option_claims[0].observer if option_claims else "rodrigo",
                    context=option_claims[0].context if option_claims else "general",
                    source_trust="user_stated",
                    origin="clarification",
                    authored_by="user",
                    confidence=0.95,
                    valid_from=today,
                    recorded_at=today,
                )
                for loser in option_claims:
                    if loser.valid_to is None:
                        _close_today(loser, by=new_claim, today=today)
                claim_list.append(new_claim)
                sentence = (
                    f"{predicates.predicate_phrase(predicate, name, answer)} "
                    f"(stated by user on {today})."
                )
            else:
                for loser in option_claims:
                    if loser.valid_to is None:
                        loser.valid_to = today
                sentence = (
                    f"None of the previously recorded values for "
                    f"'{predicate}' are current as of {today}."
                )

    entity.body = write_claims(entity.body, claim_list)

    new_body = None
    if sentence:
        try:
            new_body = await _synthesize_entity_update(
                entity_name=name,
                entity_type=fm.get("type", "concept"),
                existing_body=entity.body,
                new_description=sentence,
                new_history_entries=[],
                source_reference_date=today,
                settings=settings,
            )
        except Exception:
            new_body = None
        if not new_body:
            # Safe fallback: dedup guard instead of blind append.
            new_body = (
                entity.body.rstrip() + f"\n\n{sentence}"
                if sentence not in entity.body
                else entity.body
            )

    if new_body is not None:
        # The synthesizer only ever returns prose; re-attach the machine layer
        # so an LLM rewrite can never drop the claims block.
        new_body = write_claims(new_body, claim_list)

    fm["last_referenced"] = today
    fm["version"] = int(fm.get("version", 1) or 1) + 1
    markdown_parser.write(entity_path, fm, new_body or entity.body)

    path.unlink()
    return entity_id, False, extra_lines


async def _resolve_clarification(path, parsed, request, settings) -> tuple[str, bool]:
    """Port of the clarifications.py logic (answer / dismiss / merge / skip).

    Lifted verbatim — the source_date/_max_date chronology handling is already
    correct. Returns ``(entity_id, skipped)``; ``skipped`` short-circuits the
    commit in :func:`resolve`.

    ``resolve`` is accepted as an alias for ``answer`` (G60 §2.1): the MCP tool
    and the app's ``QuestionView`` send one verb for *every* kind carrying a
    question object, so a clarification that grew a question must not 400. A
    ``option_key`` with no free text resolves to that option's label.
    """
    entity_mention = parsed.frontmatter.get("entity_name", "") or parsed.frontmatter.get(
        "entity_mention", ""
    )
    entity_id = parsed.frontmatter.get("entity_id", "") or sanitize_id(entity_mention)

    source_episode = str(parsed.frontmatter.get("source_episode", "") or "").strip()
    source_timestamp = str(
        parsed.frontmatter.get("source_episode_timestamp", "") or ""
    ).strip()
    clar_created = str(parsed.frontmatter.get("created_date", "") or "").strip()
    today = str(date.today())
    source_date = (
        _extract_date(source_timestamp) or _extract_date(clar_created) or today
    )

    action = request.action
    answer_text = (request.answer or "").strip()
    if action == "resolve":
        option_key = (request.option_key or "").strip()
        if not answer_text and option_key:
            chosen = next(
                (
                    o
                    for o in inbox_questions.normalize_options(
                        parsed.frontmatter.get("options")
                    )
                    if str(o.get("key")) == option_key
                ),
                None,
            )
            if chosen is not None:
                answer_text = str(chosen.get("label") or "").strip()
        action = "answer"

    if action == "answer":
        if not answer_text:
            raise HTTPException(400, "answer is required when action is 'answer'")

        entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
        if entity_path.exists():
            entity = markdown_parser.parse(entity_path)
            if source_episode:
                episodes = list(entity.frontmatter.get("source_episodes", []) or [])
                if source_episode not in episodes:
                    episodes.append(source_episode)
                entity.frontmatter["source_episodes"] = episodes
            existing_last = str(
                entity.frontmatter.get("last_referenced", "") or ""
            ).strip()
            entity.frontmatter["last_referenced"] = (
                _max_date(existing_last, source_date) or today
            )
            entity.frontmatter["version"] = (
                int(entity.frontmatter.get("version", 1) or 1) + 1
            )
            body = entity.body.rstrip() + f"\n\n{answer_text}"
            markdown_parser.write(entity_path, entity.frontmatter, body)
        else:
            entity_type = str(
                parsed.frontmatter.get("suggested_classification", "concept")
            ).split(" ")[0].lower()
            frontmatter = {
                "name": entity_mention,
                "type": entity_type,
                "status": "active",
                "confidence": parsed.frontmatter.get("suggested_confidence", 0.5),
                "created": source_date,
                "last_referenced": source_date,
                **decay_policy.frontmatter_fields(
                    decay_policy.default_class_for(entity_type)
                ),
                "source_episodes": [source_episode] if source_episode else [],
                "tags": [],
                "related": [],
                "version": 1,
            }
            markdown_parser.write(entity_path, frontmatter, answer_text)
        path.unlink()

    elif action == "dismiss":
        path.unlink()

    elif action == "merge" and request.merge_target:
        # Tolerant lookup: merge_target may arrive as a slug or a display name.
        # ``merge_target`` is always the existing entity that holds the real data
        # (frontmatter/body/history); it is the merge data SOURCE regardless of
        # direction.
        target_path = resolve_entity_file(settings.memory_path, request.merge_target)
        if target_path is None:
            raise HTTPException(
                404, f"Merge target '{request.merge_target}' not found"
            )

        target = markdown_parser.parse(target_path)
        mention = (
            str(
                parsed.frontmatter.get("entity_name", "")
                or parsed.frontmatter.get("entity_mention", "")
                or ""
            ).strip()
            or entity_mention
        )

        # #1 merge direction. The survivor is the id/name the user wants to KEEP.
        # Default (absent) -> the existing target survives (legacy behavior). When
        # it names the cleaner mention instead, the surviving file is renamed to
        # the survivor's cleaner slug.
        survivor = (request.merge_survivor or "").strip() or request.merge_target
        survivor_slug = sanitize_id(survivor)
        # Decide rename by resolved *file identity*, not raw-slug strings. Live
        # entity stems don't all round-trip through ``sanitize_id`` (e.g.
        # ``atlético-de-madrid``), so a survivor naming the existing target by
        # its display name would otherwise spuriously take the rename branch and
        # orphan the on-disk file's blame/history. If the survivor resolves to
        # the target's own file, it's a "keep existing" merge — never a rename.
        survivor_file = resolve_entity_file(settings.memory_path, survivor)
        rename = survivor_file is None or survivor_file != target_path

        if source_episode:
            episodes = list(target.frontmatter.get("source_episodes", []) or [])
            if source_episode not in episodes:
                episodes.append(source_episode)
            target.frontmatter["source_episodes"] = episodes

        existing_last = str(
            target.frontmatter.get("last_referenced", "") or ""
        ).strip()
        target.frontmatter["last_referenced"] = (
            _max_date(existing_last, source_date) or today
        )
        target.frontmatter["version"] = (
            int(target.frontmatter.get("version", 1) or 1) + 1
        )

        if not rename:
            # Survivor == existing target: absorb the mention into the target.
            note = f"\n\n_Resolved ambiguous mention '{mention}' into this entity._"
            new_body = (target.body or "").rstrip() + note
            markdown_parser.write(target_path, target.frontmatter, new_body)
            path.unlink()
            entity_id = target_path.stem
        else:
            # Survivor == the cleaner mention: keep the cleaner name/id.
            survivor_path = target_path.parent / f"{survivor_slug}.md"
            target.frontmatter["name"] = survivor
            note = (
                f"\n\n_Merged '{target_path.stem}' into this entity "
                f"(kept the cleaner name '{survivor}')._"
            )

            if survivor_path.exists() and survivor_path != target_path:
                # A file already lives at the survivor slug — append into it,
                # never overwrite. Carry the source target's episodes forward.
                existing = markdown_parser.parse(survivor_path)
                eps = list(existing.frontmatter.get("source_episodes", []) or [])
                for ep in target.frontmatter.get("source_episodes", []) or []:
                    if ep not in eps:
                        eps.append(ep)
                existing.frontmatter["source_episodes"] = eps
                ex_last = str(
                    existing.frontmatter.get("last_referenced", "") or ""
                ).strip()
                existing.frontmatter["last_referenced"] = (
                    _max_date(ex_last, target.frontmatter.get("last_referenced"))
                    or today
                )
                existing.frontmatter["version"] = (
                    int(existing.frontmatter.get("version", 1) or 1) + 1
                )
                merged_body = (existing.body or "").rstrip() + note
                markdown_parser.write(
                    survivor_path, existing.frontmatter, merged_body
                )
                # Remove the now-absorbed source target via git so history follows.
                await _git_remove(settings.memory_path, target_path)
            else:
                # Rename the source target file to the survivor's cleaner slug.
                new_body = (target.body or "").rstrip() + note
                markdown_parser.write(target_path, target.frontmatter, new_body)
                await _git_move(settings.memory_path, target_path, survivor_path)

            path.unlink()
            entity_id = survivor_slug

    elif action == "skip":
        return entity_id, True

    else:
        raise HTTPException(400, f"Unknown action: {request.action}")

    return entity_id, False
