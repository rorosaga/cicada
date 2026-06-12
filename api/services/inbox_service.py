"""Unified inbox service — one read path + one kind-dispatched resolver.

Replaces the split ``nudges`` / ``clarifications`` plumbing. All pending items
live as ``memory/inbox/inbox-NNN.md`` with a ``kind`` discriminator; this module
loads them into ``InboxItem`` and resolves them by routing on ``kind``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from api.config import Settings
from api.models.schemas import InboxItem, InboxResolveRequest
from api.services import markdown_parser
from api.services.id_utils import resolve_entity_file, sanitize_id


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


def _item_from_file(filepath: Path) -> InboxItem:
    parsed = markdown_parser.parse(filepath)
    fm = parsed.frontmatter
    kind = str(fm.get("kind", "decay"))
    required_input = str(fm.get("required_input", "") or _required_input_for(kind))
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
        options=fm.get("options"),
        created_date=str(fm.get("created_date", "") or ""),
        uncertainty_type=fm.get("uncertainty_type"),
        suggested_classification=fm.get("suggested_classification"),
        suggested_confidence=fm.get("suggested_confidence"),
        merge_target_hint=fm.get("merge_target_hint"),
    )


def load_inbox(memory_path: Path) -> list[InboxItem]:
    """Load all inbox items, sorted: pending first, then priority desc, date desc."""
    inbox_dir = _inbox_dir(memory_path)
    items: list[InboxItem] = []
    for filepath in sorted(inbox_dir.glob("inbox-*.md")):
        try:
            items.append(_item_from_file(filepath))
        except Exception:
            continue
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


# ---------- Resolution dispatch ----------


async def resolve(
    item_id: str, request: InboxResolveRequest, settings: Settings
) -> dict:
    """Resolve an inbox item by routing on its ``kind``. Returns a status dict."""
    path = _inbox_dir(settings.memory_path) / f"{item_id}.md"
    if not path.exists():
        raise HTTPException(404, f"Inbox item {item_id} not found")

    parsed = markdown_parser.parse(path)
    kind = str(parsed.frontmatter.get("kind", "decay"))

    if kind == "decay":
        entity_id, skipped = await _resolve_decay(path, parsed, request, settings)
    elif kind == "conflict":
        entity_id, skipped = await _resolve_conflict(path, parsed, request, settings)
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

    await git_service.commit_resolution(
        settings.memory_path, entity_id, f"inbox/{kind}/resolved"
    )
    return {"status": "resolved", "id": item_id}


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


async def _resolve_conflict(path, parsed, request, settings) -> tuple[str, bool]:
    """Conflict adjudication — LLM-synthesize the answer into the entity body.

    The user's chosen option (or free text) becomes the authoritative
    description; ``conflict_resolver._synthesize_entity_update`` integrates it
    coherently instead of accreting a disconnected paragraph (the old bug). A
    non-LLM dedup fallback keeps the resolve path working without an API key.
    """
    from api.services.conflict_resolver import _synthesize_entity_update

    entity_id = parsed.frontmatter.get("entity_id", "")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    answer = (request.answer or "").strip()

    if entity_path.exists() and answer:
        entity = markdown_parser.parse(entity_path)
        fm = entity.frontmatter
        new_body = None
        try:
            new_body = await _synthesize_entity_update(
                entity_name=fm.get("name", entity_id),
                entity_type=fm.get("type", "concept"),
                existing_body=entity.body,
                new_description=answer,
                new_history_entries=[],
                source_reference_date=str(date.today()),
                settings=settings,
            )
        except Exception:
            new_body = None
        if not new_body:
            # Safe fallback: dedup guard instead of blind append.
            new_body = (
                entity.body.rstrip() + f"\n\n{answer}"
                if answer not in entity.body
                else entity.body
            )
        fm["last_referenced"] = str(date.today())
        fm["version"] = int(fm.get("version", 1) or 1) + 1
        markdown_parser.write(entity_path, fm, new_body)

    path.unlink()
    return entity_id, False


async def _resolve_clarification(path, parsed, request, settings) -> tuple[str, bool]:
    """Port of the clarifications.py logic (answer / dismiss / merge / skip).

    Lifted verbatim — the source_date/_max_date chronology handling is already
    correct. Returns ``(entity_id, skipped)``; ``skipped`` short-circuits the
    commit in :func:`resolve`.
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

    if request.action == "answer":
        answer_text = (request.answer or "").strip()
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
            frontmatter = {
                "name": entity_mention,
                "type": str(
                    parsed.frontmatter.get("suggested_classification", "concept")
                ).split(" ")[0].lower(),
                "status": "active",
                "confidence": parsed.frontmatter.get("suggested_confidence", 0.5),
                "created": source_date,
                "last_referenced": source_date,
                "decay_rate": 0.05,
                "source_episodes": [source_episode] if source_episode else [],
                "tags": [],
                "related": [],
                "version": 1,
            }
            markdown_parser.write(entity_path, frontmatter, answer_text)
        path.unlink()

    elif request.action == "dismiss":
        path.unlink()

    elif request.action == "merge" and request.merge_target:
        # Tolerant lookup: merge_target may arrive as a slug or a display name.
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

        note = f"\n\n_Resolved ambiguous mention '{mention}' into this entity._"
        new_body = (target.body or "").rstrip() + note
        markdown_parser.write(target_path, target.frontmatter, new_body)
        path.unlink()

        # Point the commit trail at the absorbing entity.
        entity_id = target_path.stem

    elif request.action == "skip":
        return entity_id, True

    else:
        raise HTTPException(400, f"Unknown action: {request.action}")

    return entity_id, False
