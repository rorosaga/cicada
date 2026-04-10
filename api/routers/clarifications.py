from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import ClarificationResolveRequest, ClarificationResponse
from api.services import git_service, markdown_parser
from api.services.id_utils import sanitize_id

router = APIRouter()


def _extract_date(value: str | None) -> str | None:
    """Parse an ISO-8601 timestamp or plain YYYY-MM-DD string into a date.

    Mirrors ``conflict_resolver._extract_date_string`` so clarification
    resolution paths can derive the same "real source conversation date"
    that the resolver/conflict pipeline writes into entity frontmatter.
    """
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
    """Return the latest YYYY-MM-DD string from the arguments, or None."""
    values = [c for c in candidates if c]
    return max(values) if values else None


def _load_clarifications(memory_path: Path) -> list[ClarificationResponse]:
    clar_dir = memory_path / "clarifications"
    results: list[ClarificationResponse] = []
    for filepath in sorted(clar_dir.glob("*.md")):
        parsed = markdown_parser.parse(filepath)
        fm = parsed.frontmatter
        results.append(
            ClarificationResponse(
                id=filepath.stem,
                entity_mention=fm.get("entity_mention", ""),
                uncertainty_type=fm.get("uncertainty_type", ""),
                source_context=parsed.body,
                suggested_classification=fm.get("suggested_classification"),
                suggested_confidence=fm.get("suggested_confidence"),
                created_date=str(fm.get("created_date", "")),
            )
        )
    return results


@router.get("/clarifications", response_model=list[ClarificationResponse])
async def list_clarifications(settings: Settings = Depends(get_settings)):
    return _load_clarifications(settings.memory_path)


@router.post("/clarifications/{clarification_id}")
async def resolve_clarification(
    clarification_id: str,
    request: ClarificationResolveRequest,
    settings: Settings = Depends(get_settings),
):
    clar_path = settings.memory_path / "clarifications" / f"{clarification_id}.md"
    if not clar_path.exists():
        raise HTTPException(404, f"Clarification {clarification_id} not found")

    parsed = markdown_parser.parse(clar_path)
    entity_mention = parsed.frontmatter.get("entity_mention", "")
    entity_id = sanitize_id(entity_mention)

    # Source conversation chronology — derived from the persisted episode
    # timestamp when available, falling back to the clarification's
    # created_date, then today. This keeps resolution paths consistent with
    # the resolver/conflict pipeline, which stamps entities with the earliest
    # and latest source_episode timestamps rather than the current wall clock.
    source_episode = str(
        parsed.frontmatter.get("source_episode", "") or ""
    ).strip()
    source_timestamp = str(
        parsed.frontmatter.get("source_episode_timestamp", "") or ""
    ).strip()
    clar_created = str(
        parsed.frontmatter.get("created_date", "") or ""
    ).strip()
    today = str(date.today())
    source_date = (
        _extract_date(source_timestamp)
        or _extract_date(clar_created)
        or today
    )

    if request.action == "answer":
        # ``answer`` is declared Optional on the request schema (the same
        # schema is reused for merge/dismiss/skip where no answer is needed),
        # so we have to validate it explicitly here. Without this guard, the
        # update branch below would f-string ``None`` into the entity body and
        # the create branch would persist an empty body.
        answer_text = (request.answer or "").strip()
        if not answer_text:
            raise HTTPException(
                400, "answer is required when action is 'answer'"
            )

        # Create or update the entity, preserving provenance and chronology.
        entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
        if entity_path.exists():
            entity = markdown_parser.parse(entity_path)

            # Add source episode to provenance if missing.
            if source_episode:
                episodes = list(
                    entity.frontmatter.get("source_episodes", []) or []
                )
                if source_episode not in episodes:
                    episodes.append(source_episode)
                entity.frontmatter["source_episodes"] = episodes

            # Advance last_referenced to the later of the existing value and
            # the source conversation date. Never clobber a newer stamp with
            # an older one.
            existing_last = str(
                entity.frontmatter.get("last_referenced", "") or ""
            ).strip()
            entity.frontmatter["last_referenced"] = (
                _max_date(existing_last, source_date) or today
            )
            entity.frontmatter["version"] = int(
                entity.frontmatter.get("version", 1) or 1
            ) + 1

            body = entity.body.rstrip() + f"\n\n{answer_text}"
            markdown_parser.write(entity_path, entity.frontmatter, body)
        else:
            # Fresh entity — seed the full provenance/chronology set so this
            # page is indistinguishable from one that came out of the Sleep
            # cycle's entity_resolver -> conflict_resolver pipeline.
            frontmatter = {
                "name": entity_mention,
                "type": parsed.frontmatter.get("suggested_classification", "concept").split(" ")[0].lower(),
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
        clar_path.unlink()

    elif request.action == "dismiss":
        clar_path.unlink()

    elif request.action == "merge" and request.merge_target:
        # The resolver now intentionally routes ambiguous duplicates into the
        # clarification queue instead of inventing a new entity page, so this
        # merge path is the *primary* resolution for "same entity, different
        # name" cases. It absorbs the ambiguous mention's provenance into the
        # target: adds the source episode, advances last_referenced to the
        # real source conversation date (not the clarification creation
        # date), bumps version, and stamps a resolution note into the body.
        target_path = settings.memory_path / "entities" / f"{request.merge_target}.md"
        if not target_path.exists():
            raise HTTPException(
                404, f"Merge target '{request.merge_target}' not found"
            )

        target = markdown_parser.parse(target_path)
        mention = (
            str(parsed.frontmatter.get("entity_mention", "") or "").strip()
            or entity_mention
        )

        # 1. Add the clarification's source episode to the target's provenance.
        if source_episode:
            episodes = list(target.frontmatter.get("source_episodes", []) or [])
            if source_episode not in episodes:
                episodes.append(source_episode)
            target.frontmatter["source_episodes"] = episodes

        # 2. Advance last_referenced to the later of (existing, source
        # conversation date). ``source_date`` above already prefers the
        # persisted source_episode_timestamp over the clarification's
        # created_date. Preserve ``created`` — that baseline is set once at
        # entity creation by conflict_resolver._earliest_change_date.
        existing_last = str(
            target.frontmatter.get("last_referenced", "") or ""
        ).strip()
        target.frontmatter["last_referenced"] = (
            _max_date(existing_last, source_date) or today
        )

        # 3. Bump the version counter so consumers can tell something changed.
        target.frontmatter["version"] = int(
            target.frontmatter.get("version", 1) or 1
        ) + 1

        # 4. Leave a visible resolution note in the body.
        note = f"\n\n_Resolved ambiguous mention '{mention}' into this entity._"
        new_body = (target.body or "").rstrip() + note

        markdown_parser.write(target_path, target.frontmatter, new_body)
        clar_path.unlink()

        # Point the commit trail at the absorbing entity, not a ghost id
        # derived from the clarification mention.
        entity_id = request.merge_target

    elif request.action == "skip":
        return {"status": "skipped", "clarification_id": clarification_id}

    else:
        raise HTTPException(400, f"Unknown action: {request.action}")

    await git_service.commit_resolution(
        settings.memory_path, entity_id, "clarification/resolved"
    )
    return {"status": "resolved", "clarification_id": clarification_id}
