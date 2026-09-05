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
from api.models.schemas import InboxCause, InboxItem, InboxOption, InboxResolveRequest
from api.services import (
    decay_policy,
    inbox_context,
    inbox_questions,
    markdown_parser,
    predicates,
    telemetry,
)
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
    if kind in ("decay", "conflict", "divergence", "normalization", "removal"):
        return "choice"
    if kind == "merge_suggestion":
        return "merge"
    return "freetext"


def _item_from_file(
    filepath: Path, *, today: str | None = None, context: "inbox_context.InboxContext | None" = None
) -> InboxItem:
    """One inbox file → ``InboxItem``.

    ``context`` (G115 Phase 1, R2) is the per-``load_inbox`` read cache; with it
    the item also carries what the OLD read path threw away at the API boundary
    (G97): the subject's type, the cause (conversation + excerpt), the
    extractor's confidence/model behind the item, and the G98 ``informational``
    flag for a conflict on a multi-valued predicate. Without it — every legacy
    caller and test — the shape is exactly what it was.
    """
    parsed = markdown_parser.parse(filepath)
    fm = parsed.frontmatter
    kind = str(fm.get("kind", "decay"))
    required_input = str(fm.get("required_input", "") or _required_input_for(kind))
    now = today or str(date.today())
    entity_id = str(fm.get("entity_id", "") or "")
    raw_options = inbox_questions.normalize_options(fm.get("options"))
    question = _opt_str(fm.get("question"))
    # Conflicts and clarifications always accept a free-text answer and a
    # deferral on the resolve path, so legacy items (written before G60,
    # no allow_* keys) must not lock the user into the closed option set.
    allow_other = bool(fm.get("allow_other", kind in ("conflict", "clarification")))
    allow_defer = bool(fm.get("allow_defer", kind in ("conflict", "clarification", "divergence")))

    extra: dict = {}
    if context is not None:
        if kind == "decay" and not raw_options:
            # G115 R5: decay is SERVED as a question object and never written as
            # one — the age phrase is computed from the subject page's live
            # `last_referenced`, so a stored copy could only go stale.
            synthesised = inbox_questions.decay_question(
                str(fm.get("entity_name", "") or entity_id),
                context.entity_last_referenced(entity_id),
                now,
            )
            question = synthesised["question"]
            raw_options = inbox_questions.normalize_options(synthesised["options"])
            allow_other, allow_defer = synthesised["allow_other"], synthesised["allow_defer"]
        # G115 R6: Sleep's own proposal is served FIRST so the card's initial
        # highlight (and `1`) lands on it. The file on disk keeps its order —
        # this is a read-time projection, like `age_days` and `cause`.
        rec = recommended_key(kind, fm, raw_options)
        raw_options = [o for o in raw_options if str(o.get("key")) == rec] + [
            o for o in raw_options if str(o.get("key")) != rec
        ]
        extra["recommended_key"] = rec
        extra["entity_type"] = context.entity_type(entity_id)
        extra["cause"] = InboxCause(**context.cause_for(fm, raw_options).to_wire())
        extra["informational"] = (
            kind == "conflict"
            and predicates.cardinality(context.memory_path, str(fm.get("predicate", "") or "")) == "multi"
        )
        extra.update(_extractor_refs(fm, kind, context))

    options: list[InboxOption] = []
    for raw in raw_options:
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
                # Both derived at read (G115 R6). Without a `context` the item
                # keeps its pre-G115 shape: no marker, no wire verdict.
                recommended=(context is not None and str(raw.get("key")) == extra.get("recommended_key")),
                verdict=(
                    _option_verdict(kind, str(raw.get("key", "")), fm, raw_options)
                    if context is not None
                    else None
                ),
            )
        )

    return InboxItem(
        id=filepath.stem,
        kind=kind,
        required_input=required_input,
        status=str(fm.get("status", "pending") or "pending"),
        priority=float(fm.get("priority", 0.0) or 0.0),
        entity_id=entity_id,
        entity_name=str(fm.get("entity_name", "") or ""),
        title=str(fm.get("title", "") or fm.get("entity_name", "") or ""),
        body=parsed.body,
        options=options,
        created_date=str(fm.get("created_date", "") or ""),
        question=question,
        allow_other=allow_other,
        allow_defer=allow_defer,
        predicate=_opt_str(fm.get("predicate")),
        hint=_opt_str(fm.get("hint")),
        channel=_opt_str(fm.get("channel")),
        remind_after=_opt_str(fm.get("remind_after")),
        updated_date=_opt_str(fm.get("updated_date")),
        uncertainty_type=fm.get("uncertainty_type"),
        suggested_classification=fm.get("suggested_classification"),
        suggested_confidence=fm.get("suggested_confidence"),
        merge_target_hint=fm.get("merge_target_hint"),
        source_episode=_opt_str(fm.get("source_episode")),
        source_episode_timestamp=_opt_str(fm.get("source_episode_timestamp")),
        claim_id=_opt_str(fm.get("claim_id")),
        **extra,
    )


def _extractor_refs(fm: dict, kind: str, context: "inbox_context.InboxContext") -> dict:
    """The extractor's side of the item, for the card's provenance line.

    Mirrors what ``_feedback_refs`` records at resolve time (G113) so the app
    can show ``Cicada's guess at 0.42`` BEFORE the person answers: decay →
    the item's priority (the decayed confidence), clarification/merge → the
    extractor's ``suggested_confidence``, conflict → the proposed claim's
    ``confidence`` and ``authored_by``. Read-only; ids and numbers only.
    """
    out: dict = {"extractor_confidence": None, "extractor_model": None}
    if kind == "decay":
        out["extractor_confidence"] = _as_float(fm.get("priority"))
    elif kind in ("clarification", "merge_suggestion"):
        out["extractor_confidence"] = _as_float(fm.get("suggested_confidence"))
    else:
        claim_id = _opt_str(fm.get("claim_id"))
        if claim_id:
            claim = next((c for c in context.claims(str(fm.get("entity_id", "") or "")) if c.id == claim_id), None)
            if claim is not None:
                out["extractor_confidence"] = _as_float(claim.confidence)
                out["extractor_model"] = _opt_str(claim.authored_by)
    return out


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

    G115 Phase 1: every item served carries its ``cause`` (G97, three tiers,
    ``[ no source recorded ]`` when none), ``entity_type``, and — for a conflict
    on a predicate the vocabulary marks multi-valued — ``informational: true``
    (G98). All three are derived at read from one shared
    :class:`inbox_context.InboxContext`, never stored.
    """
    inbox_dir = _inbox_dir(memory_path)
    today = str(date.today())
    # G115 R2: one read cache for the whole inbox — episode + entity frontmatter
    # through bank_index, claim blocks parsed once per subject.
    context = inbox_context.InboxContext(memory_path, today=today)
    items: list[InboxItem] = []
    for filepath in sorted(inbox_dir.glob("inbox-*.md")):
        try:
            item = _item_from_file(filepath, today=today, context=context)
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
    if kind == "removal":
        if action == "skip":
            return "skip"
        if key in ("keep", "remove"):
            return key
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


# ---------- Feedback ledger (G113 slice 2) ----------

_NEUTRAL_LABELS = ("defer", "skip", "remind_later")


def _verdict(
    kind: str,
    label: str,
    option_key: str | None,
    item_claim_id: str | None,
    options: list[dict],
) -> str:
    """R3: did the user agree with what the extractor proposed?

    Returns ``agreed`` / ``overruled`` / ``neutral``. The table is fixed HERE, at
    emit time, and the result is written into the ledger as a string — a later
    reader must never re-derive it, because the per-kind rules will drift as
    kinds gain actions and a re-derivation would silently re-grade history.

    A conflict ``pick`` is graded against the item's ``claim_id`` (the NEW claim
    Sleep proposed): picking it is agreement, picking anything else is an
    overrule. An entity-path conflict (``conflict_resolver.build_entity_question``)
    proposes no claim at all — ``claim_id`` is absent and every option carries
    ``claim_id: None`` — so a pick there grades ``neutral``: there is no
    extractor belief to agree or disagree with, and calling it an overrule would
    skew the feedback ratio against a model that never took a side.
    """
    if label in _NEUTRAL_LABELS:
        return "neutral"
    # R3: the proposal came from the browser's own diff, never from the
    # extractor — there is no model belief to agree or disagree with, the
    # same reasoning already used for an entity-path conflict with no
    # `claim_id` just below.
    if kind == "removal":
        return "neutral"
    if kind == "decay":
        return {"archive": "agreed", "keep_active": "overruled"}.get(label, "neutral")
    if kind == "conflict":
        if label == "both":
            return "neutral"
        if label.startswith("pick:"):
            if item_claim_id is None:
                return "neutral"
            picked = next((o for o in options if str(o.get("key")) == str(option_key)), None)
            return (
                "agreed"
                if picked is not None and _opt_str(picked.get("claim_id")) == item_claim_id
                else "overruled"
            )
        return "overruled"  # neither / free-text answer / dismiss
    if kind == "divergence":
        return {"1": "agreed", "0": "overruled"}.get(str(option_key), "neutral")
    if kind == "normalization":
        return {"0": "agreed", "1": "overruled"}.get(str(option_key), "neutral")
    if kind == "clarification":
        return {"answer": "agreed", "merge": "agreed", "dismiss": "overruled"}.get(label, "neutral")
    if kind == "merge_suggestion":
        return {"merge": "agreed", "reject": "overruled"}.get(label, "neutral")
    return "neutral"


# G115 R5 — the keys `QuestionView` sends for a decay item, mapped onto the
# legacy verbs so the G113 R1 trigger labels stay byte-identical.
_DECAY_KEY_TO_ACTION = {"archive": "archive", "keep": "keep_active", "keep_active": "keep_active"}


def _normalize_decay_request(kind: str, request: InboxResolveRequest) -> InboxResolveRequest:
    """`resolve` + `option_key` on a decay item → the legacy verb (R5).

    Every question-carrying kind is answered with one verb (``resolve``) and a
    key; decay's resolver predates that and switches on ``keep_active``/
    ``archive``. Translating here — before :func:`_action_label` — keeps
    :func:`_resolve_decay` and the G113 R1 commit labels untouched. An unknown
    key is a client bug: 400, nothing written, exactly as
    :func:`_resolve_conflict` treats a typo'd key.

    **Free text on a decay item is refused the same way** (final review H1).
    ``decay_question`` sets ``allow_other: False`` — there is no free-text
    answer a decay item can honour — but until this guard an ``answer`` without
    a recognised key fell through to :func:`_resolve_decay`'s ``else`` branch,
    which appended the prose to the entity body, left the page ``decaying`` at
    its decayed confidence and deleted the item: a "yes, still relevant"
    silently inverted into an archive-shaped outcome. Refusing is the only
    honest answer — the caller should send ``keep``/``archive``, or ``defer``.
    """
    if kind != "decay" or (request.action or "").strip().lower() not in ("resolve", "answer"):
        return request
    key = (request.option_key or "").strip().lower()
    if not key:
        if (request.answer or "").strip():
            raise HTTPException(
                400,
                "A decay item takes no free-text answer (allow_other is false) — "
                f"send optionKey one of {sorted(inbox_questions.DECAY_OPTION_KEYS)}, "
                "or action 'defer'.",
            )
        return request
    if key not in _DECAY_KEY_TO_ACTION:
        raise HTTPException(
            400,
            f"Unknown optionKey {key!r} for a decay item — expected one of "
            f"{sorted(inbox_questions.DECAY_OPTION_KEYS)}.",
        )
    return request.model_copy(update={"action": _DECAY_KEY_TO_ACTION[key]})


def _option_verdict(kind: str, key: str, fm: dict, options: list[dict]) -> str:
    """What picking ``key`` would be graded as — the same table the ledger
    writes, evaluated once at read so wire == ledger (G115 §4).

    Never raises. :func:`_normalize_decay_request` 400s on a decay key it does
    not know, which is right on the WRITE path and fatal on the read one: a
    legacy decay item carrying flat options (keys ``"0"``/``"1"``) would raise
    inside :func:`_item_from_file`, and ``load_inbox``'s broad ``except`` would
    then log a warning and drop the card from the inbox entirely. An ungradeable
    key is ``neutral`` here and stays answerable.
    """
    try:
        request = _normalize_decay_request(kind, InboxResolveRequest(action="resolve", option_key=key))
    except HTTPException:
        return "neutral"
    label = _action_label(kind, request, options)
    return _verdict(kind, label, key, _opt_str(fm.get("claim_id")), options)


def recommended_key(kind: str, fm: dict, options: list[dict]) -> str | None:
    """The ONE option Sleep proposed (G115 R6) — the key :func:`_verdict` grades
    ``agreed`` — or ``None``.

    Never ``neither``/``both`` (G121: a stale-escalated question marks Sleep's
    own claim or nothing), never on a ``merge_suggestion`` (G115 §4 — no initial
    highlight on a merge) and never on a ``clarification`` (it proposes nothing;
    every answer grades ``agreed``, so a marker would be freshness dressed as a
    proposal). An entity-path conflict has no item ``claim_id``, grades every
    pick ``neutral``, and therefore carries no recommendation — a large share of
    live conflicts (G98), stated rather than papered over. Nor on ``removal`` —
    Sleep proposed nothing here; the browser did (R3).

    **A decay item's options are synthesised here when the caller has none**
    (final review H2). R5 serves decay's question at READ time and never writes
    it to the file, so the two call sites disagreed: ``_item_from_file`` passes
    the synthesised options and gets ``archive``, while :func:`_emit_resolution`
    reads the item's on-disk frontmatter — which has no ``options:`` at all —
    and recorded ``recommended_key: null`` / ``picked_recommended: false`` for
    the most common inbox kind, even though the card, the MCP blurb and the wire
    all showed ``archive (Recommended)``. Synthesising the same two options here
    makes the ledger's R8 signal agree with what the person was actually shown.
    The name and date are irrelevant to the verdict table (only the KEYS are),
    so the cheap placeholder question is enough.
    """
    if kind in ("merge_suggestion", "clarification", "removal"):
        return None
    if kind == "decay" and not options:
        options = inbox_questions.normalize_options(
            inbox_questions.decay_question("", None, str(date.today()))["options"]
        )
    agreed = [
        str(o.get("key")) for o in options
        if str(o.get("key") or "") not in _SPECIAL_KEYS and str(o.get("key") or "")
        # A legacy decay item with flat options ("0"/"1") is not the synthesised
        # question and has no proposal to mark — `_option_verdict` grades those
        # `neutral`, so they simply never reach `agreed`.
        and _option_verdict(kind, str(o.get("key")), fm, options) == "agreed"
    ]
    return agreed[0] if len(agreed) == 1 else None


def _owner_observer(settings) -> str:
    """The observer id for a claim the OWNER states from the inbox.

    Portability rail (G115 R7): no owner name in code. ``settings.observer_owner``
    (``CICADA_OBSERVER_OWNER``, PR #45) names the person's own entity id; until
    G117's onboarding sets it, an unset value falls back to the literal the
    claim layer has used since the thesis so existing banks keep ONE observer
    lineage — flipping the fallback would split every existing bank's claim
    lineage in two on the next reconciliation.

    TODO(G117): **this is one of five owner-observer sites and the only one that
    reads the setting today** (final review H5). The other four still hardcode
    the literal, so a portable install that sets ``CICADA_OBSERVER_OWNER`` gets
    two lineages in one bank — exactly the split this helper exists to prevent:

    * ``telegram_capture.py`` — the ``saved-because`` claim's ``observer=``
    * ``agentic_write.write_claim`` — the ``source_trust`` gate (``user_stated``
      vs ``agent_extracted``) and the ``origin`` gate (``manual_edit`` vs ``mcp``)
    * ``mcp/server.py`` — the ``cicada_write_claim`` observer enum + its description

    Drop the literal from all five in one change once onboarding writes the
    setting; migrating a bank's existing claims is part of that change, not of
    this one.
    """
    return str(getattr(settings, "observer_owner", "") or "").strip() or "rodrigo"


def _item_age_days(fm: dict, today: date) -> int | None:
    raw = fm.get("created_date")
    if raw in (None, ""):
        return None
    try:
        created = raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None
    return max(0, (today - created).days)


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _feedback_refs(fm: dict, kind: str, label: str, request: InboxResolveRequest, memory_path: Path) -> dict:
    """Which claim won, which lost, and how sure the extractor was — BEFORE the
    resolver touches anything.

    Must run before the kind branch: ``_resolve_conflict`` bumps the winner's
    confidence to 0.9 and unlinks the item file, so reading afterwards would
    record the post-resolution confidence as the extractor's and lose the item.
    A claims block that will not parse (or an entity page that is gone) simply
    yields no claim info — this is bookkeeping, never a reason to block a
    resolve. Only ids and numbers leave this function.
    """
    out: dict = {"winner": None, "losers": [], "extractor_confidence": None, "extractor_model": None}
    item_claim = _opt_str(fm.get("claim_id"))
    existing_claim = _opt_str(fm.get("existing_claim_id"))
    options = inbox_questions.normalize_options(fm.get("options") or [])
    option_ids = [str(o["claim_id"]) for o in options if o.get("claim_id")]
    key = (request.option_key or "").strip()
    lookup_id: str | None = item_claim

    if kind == "decay":
        out["extractor_confidence"] = _as_float(fm.get("priority"))
        return out
    if kind in ("clarification", "merge_suggestion"):
        out["extractor_confidence"] = _as_float(fm.get("suggested_confidence"))
        return out
    if kind == "conflict":
        if label.startswith("pick:"):
            picked = next((o for o in options if str(o.get("key")) == key), None)
            winner = _opt_str(picked.get("claim_id")) if picked else None
            out["winner"] = winner
            out["losers"] = [cid for cid in option_ids if cid != winner]
            lookup_id = winner or item_claim
        elif label in ("neither", "answer"):
            out["losers"] = list(option_ids)
        # both / dismiss / skip / defer: nothing closed, nothing reinforced.
    elif kind == "divergence":
        if key == "0":
            out["winner"], out["losers"] = existing_claim, [c for c in (item_claim,) if c]
        elif key == "1":
            out["winner"], out["losers"] = item_claim, [c for c in (existing_claim,) if c]
    elif kind == "normalization":
        out["winner"] = item_claim

    if lookup_id:
        try:
            from api.services.claims import parse_claims

            entity_path = resolve_entity_file(memory_path, str(fm.get("entity_id", "") or ""))
            if entity_path is not None:
                parsed = markdown_parser.parse(entity_path)
                claim = next((c for c in parse_claims(parsed.body) if c.id == lookup_id), None)
                if claim is not None:
                    out["extractor_confidence"] = _as_float(claim.confidence)
                    out["extractor_model"] = _opt_str(claim.authored_by)
        except Exception:  # noqa: BLE001 — no claim info is an acceptable answer
            logger.debug("feedback refs: claim lookup failed", exc_info=True)
    return out


def _emit_resolution(
    fm: dict,
    item_id: str,
    kind: str,
    request: InboxResolveRequest,
    label: str,
    settings,
    *,
    winner: str | None = None,
    losers=(),
    extractor_confidence: float | None = None,
    extractor_model: str | None = None,
) -> None:
    """Append one ``resolution`` ledger row. Ids/enums/numbers only. Never raises.

    G113: the user's answer is a grounded reward from the environment (Era of
    Experience §3) — the one signal that says whether the extractor's belief
    was right. The entity page keeps the *edit*; this row keeps the *verdict*,
    in the machine-global ledger where `GET /consumption/feedback` can rate a
    model on it without ever opening a bank. No claim text, no label, no
    answer string: the ledger lives outside the bank and must stay safe to
    read anywhere.
    """
    try:
        options = inbox_questions.normalize_options(fm.get("options") or [])
        rec = recommended_key(kind, fm, options)
        verdict = _verdict(kind, label, request.option_key, _opt_str(fm.get("claim_id")), options)
        telemetry.record(
            telemetry.UsageEvent(
                kind="resolution",
                stage="feedback",
                bank=telemetry.bank_name(settings),
                invocations=0,
                billing="free",
                refs={
                    "item_id": item_id,
                    "kind": kind,
                    "predicate": _opt_str(fm.get("predicate")),
                    "entity_id": _opt_str(fm.get("entity_id")),
                    "action": label,
                    "option_key": _opt_str(request.option_key),
                    "verdict": verdict,
                    "winner_claim_id": winner,
                    "loser_claim_ids": list(losers),
                    "extractor_confidence": extractor_confidence,
                    "extractor_model": extractor_model,
                    "item_age_days": _item_age_days(fm, date.today()),
                    # G115 R8: was Sleep's proposal the one picked? Key + bool
                    # only — the ledger never carries a label or an excerpt.
                    "recommended_key": rec,
                    "picked_recommended": bool(rec)
                    and (str(request.option_key or "").strip().lower() == rec or label == rec),
                },
            )
        )
    except Exception:  # noqa: BLE001 — a ledger failure never blocks a user's answer
        logger.debug("resolution ledger write failed", exc_info=True)


async def resolve(
    item_id: str, request: InboxResolveRequest, settings: Settings
) -> dict:
    """Resolve an inbox item by routing on its ``kind``. Returns a status dict."""
    path = _inbox_dir(settings.memory_path) / f"{item_id}.md"
    if not path.exists():
        raise HTTPException(404, f"Inbox item {item_id} not found")

    parsed = markdown_parser.parse(path)
    kind = str(parsed.frontmatter.get("kind", "decay"))

    # G115 R5 — a decay item answered through `QuestionView` arrives as
    # `resolve` + `archive|keep`; translate it into the legacy verb here, before
    # `_action_label`, so the G113 R1 commit triggers stay byte-identical.
    request = _normalize_decay_request(kind, request)
    # G113 R6 (landed by G115 Phase 1): `remind_later` was a snooze nothing
    # read — it wrote `snooze_until`, left the item visible, and committed
    # "entity updated" for an entity it never touched. It is a 7-day defer.
    if kind == "decay" and (request.action or "").strip().lower() == "remind_later":
        return await _defer(
            path, parsed, request.model_copy(update={"remind_days": 7}), settings, item_id,
            label="remind_later",
        )

    # G60 §2.4 — `defer` is kind-agnostic: it never touches claims or the entity
    # page, it just pushes the item out of sight until `remind_after`.
    if request.action == "defer":
        return await _defer(path, parsed, request, settings, item_id)

    # G113 — name the action and read the extractor's side of it BEFORE the
    # branch: the resolvers rewrite claim confidences and unlink the item file.
    label = _action_label(
        kind, request, inbox_questions.normalize_options(parsed.frontmatter.get("options") or [])
    )
    feedback = _feedback_refs(parsed.frontmatter, kind, label, request, settings.memory_path)

    extra_lines: list[str] = []
    if kind == "decay":
        entity_id, skipped = await _resolve_decay(path, parsed, request, settings)
    elif kind == "removal":
        entity_id, skipped = await _resolve_removal(path, parsed, request, settings)
    elif kind == "conflict":
        entity_id, skipped, extra_lines = await _resolve_conflict(
            path, parsed, request, settings
        )
    elif kind == "divergence":
        entity_id, skipped, extra_lines = await _resolve_divergence(
            path, parsed, request, settings, item_id
        )
    elif kind == "normalization":
        entity_id, skipped, extra_lines = await _resolve_normalization(
            path, parsed, request, settings, item_id
        )
    elif kind in ("clarification", "merge_suggestion"):
        entity_id, skipped, extra_lines = await _resolve_clarification(
            path, parsed, request, settings
        )
    else:
        raise HTTPException(400, f"Unknown kind {kind}")

    # A skip is a neutral row, not a missing one — "asked, not answered" is
    # itself informative about the question.
    _emit_resolution(parsed.frontmatter, item_id, kind, request, label, settings, **feedback)

    if skipped:
        return {"status": "skipped", "id": item_id}

    # Avoid the local import becoming a hard module-load dependency cycle.
    from api.services import git_service

    # G113 R1/R2 — the trigger names the action taken, and a decay verdict
    # states the resulting status so history classifies it as `statusChange`.
    # ``parsed`` was read before the branch unlinked the item file; never
    # re-read it here.
    change = "updated"
    if kind == "decay" and label == "archive":
        change = "status archived"
    elif kind == "decay" and label == "keep_active":
        change = "status active"
    elif kind == "removal" and label == "remove":
        change = "status archived"
    await git_service.commit_resolution(
        settings.memory_path,
        entity_id,
        f"inbox/{kind}/resolved:{label}",
        extra_lines,
        change=change,
    )
    # G53 (R4) — the pending count just changed; refresh the projection
    # cheaply (no repo probes, previous blocks carried over) and commit it
    # alone as `cicada`. Best-effort: a projection failure never fails a
    # person's answer. Runs AFTER the commit on purpose: `commit_resolution`
    # is `git add -A`, and refreshing first would attribute the projection
    # to the person's answer. It commits its own rewrite for the mirror
    # reason (final review, 2026-09-03): a rewrite left dirty was reproduced
    # riding in the NEXT resolution's `Cicada-Author: user` commit — the
    # G85-class smear R2/R3 exist to prevent — so `refresh_and_commit`, not
    # `refresh`, is the only regeneration entry point that touches disk.
    try:
        from api.services import state_dictionary

        await state_dictionary.refresh_and_commit(settings.memory_path, settings, probe_repos=False)
    except Exception as exc:
        logger.warning(f"state refresh after resolution skipped: {type(exc).__name__}: {exc}")
    return {"status": "resolved", "id": item_id}


async def _defer(path, parsed, request, settings, item_id: str, *, label: str = "defer") -> dict:
    """Push an item's ``remind_after`` into the future; the file stays.

    The rewritten item is committed here (scoped to the one inbox file) so the
    deferral never lingers as an uncommitted change waiting for the next Sleep
    cycle to sweep it in under an inferred trigger. ``label`` is what the
    ledger row calls the action — ``defer`` here, ``remind_later`` when a decay
    item's snooze routes through this path (R6).
    """
    from api.services import git_service

    kind = str(parsed.frontmatter.get("kind", "decay"))
    feedback = _feedback_refs(parsed.frontmatter, kind, label, request, settings.memory_path)

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
    _emit_resolution(parsed.frontmatter, item_id, kind, request, label, settings, **feedback)
    return {"status": "deferred", "id": item_id, "remindAfter": remind_after}


async def _resolve_decay(path, parsed, request, settings) -> tuple[str, bool]:
    """Port of the nudges.py decay branch (keep / archive).

    ``remind_later`` is routed to :func:`_defer` by :func:`resolve` (G113 R6,
    landed by G115 Phase 1) and never reaches here: the branch that used to
    live here wrote a ``snooze_until`` key no reader consulted, so the item
    stayed visible and the cycle committed "entity updated" for an entity it
    had not touched.
    """
    entity_id = parsed.frontmatter.get("entity_id", "")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"

    if request.action == "keep_active" and entity_path.exists():
        entity = markdown_parser.parse(entity_path)
        entity.frontmatter["status"] = "active"
        entity.frontmatter["confidence"] = max(
            entity.frontmatter.get("confidence", 0.5), 0.6
        )
        entity.frontmatter["last_referenced"] = str(date.today())
        # G113 slice 3c: "still true" is a verdict on the CLAIM the decay nudge
        # was raised over, not just the entity's summary confidence — without
        # this, a `keep_active` left the claim itself faded (and, if decay had
        # already closed it, still closed) while the entity page read `active`.
        claim_id = _opt_str(parsed.frontmatter.get("claim_id"))
        body = entity.body
        if claim_id:
            from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

            try:
                claims = parse_claims(body)
            except MalformedClaimsBlockError:
                # A corrupt claims block degrades this to a no-op claim
                # refresh rather than blocking the "still relevant" answer
                # from clearing the decay nudge (default strict=False below
                # never actually raises this; kept defensive for a future
                # switch to strict=True).
                claims = None
            if claims:
                for c in claims:
                    if c.id == claim_id:
                        c.confidence = max(float(c.confidence or 0), 0.6)
                        if c.valid_to and not c.superseded_by:
                            c.valid_to = None  # faded, not replaced — reopen it
                body = write_claims(body, claims)
        markdown_parser.write(entity_path, entity.frontmatter, body)
        path.unlink()

    elif request.action == "archive" and entity_path.exists():
        entity = markdown_parser.parse(entity_path)
        entity.frontmatter["status"] = "archived"
        markdown_parser.write(entity_path, entity.frontmatter, entity.body)
        path.unlink()

    else:
        # Unknown action on a decay item — fall through to deletion so a stray
        # entity-less decay nudge can still be cleared. A `resolve`/`answer`
        # carrying free text never reaches here any more: decay's question sets
        # `allow_other: False`, so `_normalize_decay_request` 400s it rather
        # than letting a "still relevant" answer be appended to the body while
        # the page stays `decaying` (final review H1).
        if entity_path.exists() and request.answer:
            entity = markdown_parser.parse(entity_path)
            entity.frontmatter["last_referenced"] = str(date.today())
            body = entity.body + f"\n\n{request.answer}"
            markdown_parser.write(entity_path, entity.frontmatter, body)
        path.unlink()

    return entity_id, False


async def _resolve_removal(path, parsed, request: InboxResolveRequest, settings) -> tuple[str, bool]:
    """``keep`` closes the question with no change to the entity — the
    browser's own diff produced this ask, not a belief to walk back. ``remove``
    archives the media entity: NEVER deletes the page (G129 row rule) — it may
    be claim-linked, and git keeps every version regardless of status.

    Finding 2 (G129 slice-2 final review): ``skip`` is an item-preserving
    no-op, like every sibling choice kind gives it (``_resolve_divergence``,
    ``_resolve_normalization``) — the item file is left on disk (unlinked
    nowhere below) so it is asked again later, and ``resolve()`` reports
    ``{"status": "skipped"}`` instead of committing anything.
    ``_action_label`` already computes ``label == "skip"`` for exactly this
    input; without this branch that label was never reachable — the request
    fell through to the "got an unrecognised optionKey/action" 400 below.
    """
    entity_id = str(parsed.frontmatter.get("entity_id", "") or "")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    action = (request.action or "").strip().lower()
    key = (request.option_key or "").strip().lower()

    if action == "skip":
        return entity_id, True

    verb = key if key in ("keep", "remove") else (action if action in ("keep", "remove") else "")

    if not verb:
        raise HTTPException(
            400,
            f"A removal item takes optionKey 'keep' or 'remove' — got {key or action!r}.",
        )
    if verb == "remove" and entity_path.exists():
        entity = markdown_parser.parse(entity_path)
        entity.frontmatter["status"] = "archived"
        entity.frontmatter["last_referenced"] = str(date.today())
        markdown_parser.write(entity_path, entity.frontmatter, entity.body)
    path.unlink(missing_ok=True)
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
    informational = (
        predicates.cardinality(settings.memory_path, str(fm_item.get("predicate", "") or "")) == "multi"
    )
    if request.action == "dismiss" and (
        informational
        or (
            not fm_item.get("options")
            and not str(fm_item.get("question", "") or "").strip()
            and not (request.option_key or "").strip()
            and not (request.answer or "").strip()
        )
    ):
        # Legacy pre-G60 items (above) AND G98/G115 R4 informational items: a
        # conflict on a multi-valued predicate asked for a winner that does not
        # exist — Stage 3 already kept every value open, so dismissing touches
        # no claim. Its G113 R3 grade is `overruled`, and that is right: the
        # belief overruled is the extractor's "these values conflict".
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
                    observer=option_claims[0].observer if option_claims else _owner_observer(settings),
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


async def _resolve_divergence(path, parsed, request, settings, item_id: str) -> tuple[str, bool, list[str]]:
    """G113 slice 3: "I'm reading something different" — a two-claim variant
    of `_resolve_conflict` for the narrow case Sleep already writes a
    dedicated nudge for (`inbox_generator.py`'s `divergence_nudge` branch):
    exactly one NEW claim (`claim_id`) against exactly one EXISTING one
    (`existing_claim_id`). Mirrors `_resolve_conflict`'s shape (parse → mutate
    → `write_claims` → `markdown_parser.write`) rather than reusing it,
    because the two-claim case has no options list to fall back on and no LLM
    body synthesis — a divergence never rewrites the entity's prose.
    """
    from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

    fm = parsed.frontmatter
    entity_id = _opt_str(fm.get("entity_id")) or ""
    key = (request.option_key or "").strip()

    if request.action == "skip":
        return entity_id, True, []
    if request.action == "dismiss" or key not in ("0", "1", "2"):
        # An unrecognised key is a client bug, not a "none of these" answer —
        # `_resolve_conflict` treats the analogous case as a 400 for a modern
        # question item, but a divergence item always has exactly 3 fixed
        # options and no free-text path, so there is nothing to interpret.
        # Removing the item without touching claims is the same "clear the
        # question" behaviour `_resolve_conflict` gives a missing entity page.
        path.unlink(missing_ok=True)
        return entity_id, False, []

    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        path.unlink(missing_ok=True)
        return entity_id, False, []

    entity = markdown_parser.parse(entity_path)
    try:
        # strict=True: parse_claims defaults to strict=False (silently
        # degrades a malformed block to []) — `_resolve_conflict` passes
        # strict=True precisely so a malformed block ABORTS the resolve
        # instead of silently treating a real claims block as empty and
        # skipping the write. Omitting it here would never raise, and the
        # 409 branch below would be dead code.
        claims = parse_claims(entity.body, strict=True)
    except MalformedClaimsBlockError as exc:
        raise HTTPException(status_code=409, detail=f"claims block on {entity_id} will not parse: {exc}") from exc
    by_id = {c.id: c for c in claims}
    new = by_id.get(_opt_str(fm.get("claim_id")) or "")
    existing = by_id.get(_opt_str(fm.get("existing_claim_id")) or "")
    today = str(date.today())
    if new is not None and existing is not None:
        if key == "0":  # keep my statement: the new reading loses
            _close_today(new, by=existing, today=today)
            existing.confidence = max(float(existing.confidence or 0), 0.9)
        elif key == "1":  # update: my old statement loses
            _close_today(existing, by=new, today=today)
            new.confidence = max(float(new.confidence or 0), 0.9)
        else:  # both true — different context
            for c in (existing, new):
                if not c.context or c.context == "general":
                    c.context = f"as of {c.valid_from or today}"
        efm = entity.frontmatter
        efm["last_referenced"] = today
        efm["version"] = int(efm.get("version", 1) or 1) + 1
        markdown_parser.write(entity_path, efm, write_claims(entity.body, claims))
    path.unlink(missing_ok=True)
    return entity_id, False, [f"entities/{entity_id}.md: updated (source: {path.stem}, trigger: inbox/divergence/resolved)"]


async def _resolve_normalization(path, parsed, request, settings, item_id: str) -> tuple[str, bool, list[str]]:
    """G113 slice 3: confirm/reject a predicate fold `claim_reconciler` already
    applied. `0` (correct fold) does nothing to the bank — the fold already
    happened at extraction time, so the resolve is a pure acknowledgement.
    `1` (wrong fold) is the substantive branch: it un-merges the raw label
    from `_predicates.yaml`'s synonym map, adds it as its own canonical
    predicate (R4 — never delete the entity's history, just stop folding the
    label going forward), and repoints the one claim the nudge was raised for
    back onto the raw (now canonical) predicate.
    """
    from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

    fm = parsed.frontmatter
    entity_id = _opt_str(fm.get("entity_id")) or ""
    key = (request.option_key or "").strip()
    if request.action == "skip":
        return entity_id, True, []
    extra: list[str] = []
    if key == "1":  # wrong fold — keep the raw predicate separate
        import yaml

        raw = _opt_str(fm.get("raw_predicate")) or ""
        # `predicates` is already imported at module scope; local imports here
        # match `_resolve_conflict`'s style (`Claim`/`write_claims` imported
        # locally too) so a divergence/normalization resolve never becomes a
        # hard module-load dependency for the rest of this file.
        raw_slug = predicates._slugify_predicate(raw)
        if raw_slug:
            runtime = settings.memory_path / predicates.RUNTIME_FILE
            data = predicates._read_runtime_map(settings.memory_path)
            syn = {str(k): v for k, v in (data.get("synonyms") or {}).items()}
            for k in list(syn):
                if k.strip().lower() in (raw.strip().lower(), raw_slug):
                    syn.pop(k)
            canonical = [str(c) for c in (data.get("canonical") or [])]
            if raw_slug not in canonical:
                canonical.append(raw_slug)
            data["synonyms"], data["canonical"] = syn, canonical
            runtime.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            extra.append(f"{predicates.RUNTIME_FILE}: updated (source: {path.stem}, trigger: inbox/normalization/resolved)")
            entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
            claim_id = _opt_str(fm.get("claim_id"))
            if entity_path.exists() and claim_id:
                entity = markdown_parser.parse(entity_path)
                try:
                    claims = parse_claims(entity.body)
                except MalformedClaimsBlockError:
                    claims = []
                hit = False
                for c in claims:
                    if c.id == claim_id:
                        c.predicate = raw_slug
                        hit = True
                if hit:
                    efm = entity.frontmatter
                    efm["version"] = int(efm.get("version", 1) or 1) + 1
                    markdown_parser.write(entity_path, efm, write_claims(entity.body, claims))
                    extra.append(f"entities/{entity_id}.md: updated (source: {path.stem}, trigger: inbox/normalization/resolved)")
    path.unlink(missing_ok=True)
    return entity_id, False, extra


async def _resolve_clarification(path, parsed, request, settings) -> tuple[str, bool, list[str]]:
    """Port of the clarifications.py logic (answer / dismiss / merge / reject / skip).

    Lifted verbatim — the source_date/_max_date chronology handling is already
    correct. Returns ``(entity_id, skipped, extra_lines)``; ``skipped``
    short-circuits the commit in :func:`resolve`.

    ``resolve`` is accepted as an alias for ``answer`` (G60 §2.1): the MCP tool
    and the app's ``QuestionView`` send one verb for *every* kind carrying a
    question object, so a clarification that grew a question must not 400. A
    ``option_key`` with no free text resolves to that option's label.
    """
    entity_mention = parsed.frontmatter.get("entity_name", "") or parsed.frontmatter.get(
        "entity_mention", ""
    )
    entity_id = parsed.frontmatter.get("entity_id", "") or sanitize_id(entity_mention)

    # G113 slice 3b — "these are NOT the same entity" is a verdict on the
    # *pair*, not a dismissal of the item: without this, deleting the file was
    # the whole effect, and the next Sleep's `_create_duplicate_clarification`
    # (or a dedup sweep) recreated the exact same question. Recording the pair
    # in `_merge_rejected.yaml` lets both producers skip it going forward
    # (R5). Checked before the rest of the dispatch chain and before
    # `source_episode`/`today` are computed — a reject never touches an entity
    # page, so none of that chronology bookkeeping is relevant here.
    if request.action == "reject":
        kind = str(parsed.frontmatter.get("kind", "") or "")
        if kind != "merge_suggestion":
            raise HTTPException(status_code=400, detail="reject is only valid on a merge_suggestion item")
        other = _opt_str(parsed.frontmatter.get("merge_target_hint")) or (
            sanitize_id(request.merge_target) if request.merge_target else ""
        )
        if not other:
            raise HTTPException(status_code=400, detail="reject needs a merge target (hint or mergeTarget)")
        from api.services import merge_rejections

        merge_rejections.add_rejected(settings.memory_path, entity_id, other)
        path.unlink()
        return (
            entity_id,
            False,
            [f"{merge_rejections.FILE}: updated (source: {path.stem}, trigger: inbox/merge_suggestion/rejected)"],
        )

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
            # G113 slice 3c: a clarification answer used to land as prose
            # only — invisible to the claim layer, so nothing downstream
            # (conflict detection, decay, `GET /entities/{id}`'s claims) ever
            # saw it. Write a `user_stated` claim alongside the prose,
            # mirroring `_resolve_conflict`'s free-text branch exactly
            # (same field list, same `_owner_observer` portability rail —
            # G115 R7, no owner name hardcoded here).
            predicate = _opt_str(parsed.frontmatter.get("predicate")) or "description"
            from api.services.claims import (
                Claim,
                MalformedClaimsBlockError,
                parse_claims,
                strip_claims_block,
                write_claims,
            )

            try:
                claims = parse_claims(entity.body)
            except MalformedClaimsBlockError:
                claims = None
            if claims is not None:
                # The raw body has the ```claims fence at the very end;
                # `entity.body.rstrip() + answer_text` would leave the new
                # prose trailing AFTER the machine layer. Strip the fence for
                # the prose append, then let `write_claims` put the
                # (re-rendered) block back where it belongs.
                prose = strip_claims_block(entity.body)
                body = f"{prose}\n\n{answer_text}" if prose else answer_text
                claims.append(Claim(
                    id=_user_claim_id(entity_id, predicate, answer_text, today),
                    text=predicates.predicate_phrase(
                        predicate, entity.frontmatter.get("name", entity_id), answer_text
                    ),
                    subject=entity_id, predicate=predicate, object=answer_text, object_kind="literal",
                    observer=_owner_observer(settings), source_trust="user_stated", origin="clarification",
                    authored_by="user", confidence=0.95, valid_from=today, recorded_at=today,
                ))
                body = write_claims(body, claims)
            else:
                # A corrupt claims block: leave it byte-identical (never
                # silently discard content this module cannot parse) and just
                # append the prose, exactly as before this task — a claim
                # write never blocks the user's answer.
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
        return entity_id, True, []

    else:
        raise HTTPException(400, f"Unknown action: {request.action}")

    return entity_id, False, []
