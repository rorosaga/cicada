"""Ask why at the moment of saving (G191): the person's answer to "What made you save this?".

When the app's bookmark watch sees ONE new bookmark made a moment ago, it shows a small panel with a few one-tap
answers. The answer is the person's own words about their own act, so it is stored on that bookmark's episode — the
same file Sleep reads the page from — through the one staging path (``episode_staging.amend_section``: scrubbed,
written in place, queued for Sleep again). Nothing here calls a model: the choices are a fixed set plus the person's
live projects, read deterministically from the pages and backlog the backend already serves.

Two times stay on the record, because a website changes and a later reader must know which page was meant:

* ``added_at`` — when the browser says the bookmark was made (the episode's own key, set at ingest when the browser
  records an instant; ``saved_at`` keeps the day);
* ``saved_why.at`` — when the person said why.

The structured answer rides the episode's frontmatter (``saved_why``) and the source record on the wire
(``GET /sources`` → ``savedWhy``); the words ride its body as a ``## Why it was saved`` section, which Stage 1 reads
like any other text the person wrote (no turn marker, so ``evidence.speaker_kind`` is ``user``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from api.services import backlog, bank_index, episode_ids, episode_scrub, episode_staging, media_ingestor

#: The fixed one-tap answers, in the order the panel shows them. Keys are the wire's; labels are the words the
#: section records (the person picked them, so they are the person's answer).
REASONS: dict[str, str] = {
    "design": "The design, the look",
    "product": "The product itself",
    "technique": "A technique to reuse",
    "read_later": "To read later",
}
#: How many of the person's projects the panel offers as "For <project>".
MAX_PROJECTS = 3
#: The free-text answer's cap — a short note, never a document.
MAX_TEXT = 500
#: The body section the answer lives in. Its own heading, so a reason the person typed elsewhere (a Telegram
#: ``/save``'s ``## Saved because``) is never replaced by this one.
HEADING = "## Why it was saved"
#: Agent-authored sections the answer must sit above, so a marker-less line is never read as the agent's.
_BEFORE = ("## Note", "## User note")
#: The commit trigger.
TRIGGER = "user/saved_why"
WRITER = "saved-why"


class SavedWhyError(ValueError):
    """A request the route answers with 4xx: ``status`` and a plain sentence."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Answer:
    reasons: tuple[str, ...]
    project: str | None
    project_name: str | None
    text: str | None


def project_options(memory_path: Path) -> list[dict]:
    """Up to :data:`MAX_PROJECTS` live projects, deterministic: those with open backlog items first, then the most
    recently referenced, then by name. A project archived or dropped is never offered."""
    memory_path = Path(memory_path)
    try:
        open_items = backlog.open_counts(memory_path)
    except Exception:  # noqa: BLE001 — a broken backlog folder must not cost the panel its projects
        open_items = {}
    rows: list[tuple[int, str, str, str]] = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "") != "project":
            continue
        if str(fm.get("status") or "active") in ("archived", "dropped"):
            continue
        name = str(fm.get("name") or f.stem).strip() or f.stem
        last = str(fm.get("last_referenced") or "")
        rows.append((0 if open_items.get(f.stem) else 1, last, name, f.stem))
    # Open backlog first; within each, newest reference first, then name — two stable sorts.
    rows.sort(key=lambda r: r[2].lower())
    rows.sort(key=lambda r: r[1], reverse=True)
    rows.sort(key=lambda r: r[0])
    return [{"id": stem, "name": name} for _, _, name, stem in rows[:MAX_PROJECTS]]


def options(memory_path: Path) -> dict:
    return {
        "reasons": [{"key": k, "label": v} for k, v in REASONS.items()],
        "projects": project_options(memory_path),
        "max_text": MAX_TEXT,
    }


def _project_name(memory_path: Path, project: str) -> str | None:
    entry = bank_index.file(Path(memory_path), "entities", f"{project}.md")
    if entry is None:
        return None
    fm = entry.frontmatter or {}
    if str(fm.get("type") or "") != "project" or str(fm.get("status") or "active") in ("archived", "dropped"):
        return None
    return str(fm.get("name") or project).strip() or project


def validate(memory_path: Path, *, reasons: list[str] | None, project: str | None, text: str | None) -> Answer:
    """The answer as it will be stored, or :class:`SavedWhyError` (422) for one that names nothing or something
    unknown. Order is the panel's, duplicates fold."""
    picked = tuple(k for k in REASONS if k in set(reasons or []))
    unknown = sorted(set(reasons or []) - set(REASONS))
    if unknown:
        raise SavedWhyError(422, f"Unknown reason {unknown[0]!r}")
    project = (project or "").strip() or None
    project_name = None
    if project is not None:
        project_name = _project_name(memory_path, project)
        if project_name is None:
            raise SavedWhyError(422, f"{project!r} is not a live project")
    words = " ".join((text or "").split()) or None
    if words is not None and len(words) > MAX_TEXT:
        raise SavedWhyError(422, f"Keep it under {MAX_TEXT} characters")
    if not picked and project is None and words is None:
        raise SavedWhyError(422, "Pick a reason or say one")
    return Answer(reasons=picked, project=project, project_name=project_name, text=words)


def render(answer: Answer, *, at: str, added_at: str | None) -> str:
    """The section's text (without its heading): when it was said and saved, then one line per answer."""
    when = f"Said {at}" + (f", about a bookmark saved {added_at}" if added_at else "") + "."
    lines = [when]
    lines += [f"- {REASONS[k]}" for k in answer.reasons]
    if answer.project_name:
        lines.append(f"- For {answer.project_name}")
    if answer.text:
        lines.append(f"- {answer.text}")
    return "\n".join(lines)


def find_episode(memory_path: Path, url: str) -> tuple[str, str, Path]:
    """``(episode_id, media_entity_id, path)`` of the saved link ``url``, or :class:`SavedWhyError` (404)."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise SavedWhyError(422, "URL must start with http:// or https://")
    idx = media_ingestor.load_url_index(memory_path)
    h = media_ingestor.existing_hash(media_ingestor.RawItem(url=url), idx)
    entry = idx.get(h) if h else None
    episode_id = str((entry or {}).get("episode_id") or "")
    path = Path(memory_path) / "episodes" / f"{episode_id}.md"
    if not episode_id or not path.is_file():
        raise SavedWhyError(404, "That link isn't saved yet")
    return episode_id, str(entry.get("media_entity_id") or ""), path


def attach(memory_path: Path, *, url: str, answer: Answer, at: str | None = None,
           bank: str | None = None) -> dict:
    """Write ``answer`` onto the saved link's episode. Returns the wire shape plus ``episode_id``,
    ``media_entity_id`` and ``changed``. The caller commits (inside its write admission)."""
    memory_path = Path(memory_path)
    episode_id, media_entity_id, path = find_episode(memory_path, url)
    at = at or episode_ids.utc_now_seconds()
    entry = bank_index.file(memory_path, "episodes", path.name)
    added_at = str((entry.frontmatter if entry else {}).get("added_at") or "") or None
    text, _ = episode_scrub.scrub(answer.text) if answer.text else (None, 0)
    scrubbed = Answer(reasons=answer.reasons, project=answer.project, project_name=answer.project_name, text=text)
    record = {"reasons": list(scrubbed.reasons), "project": scrubbed.project, "text": scrubbed.text, "at": at}
    changed = episode_staging.amend_section(
        path, HEADING, render(scrubbed, at=at, added_at=added_at), extra={"saved_why": record},
        writer=WRITER, bank=bank or memory_path.name, before=_BEFORE)
    return {"episode_id": episode_id, "media_entity_id": media_entity_id, "changed": changed,
            "saved_why": wire(record, added_at=added_at)}


def wire(record: dict | None, *, added_at: str | None) -> dict | None:
    """The source record's ``savedWhy``: the answer, when it was given, and when the bookmark was made."""
    if not isinstance(record, dict):
        return None
    reasons = [str(k) for k in (record.get("reasons") or []) if str(k) in REASONS]
    return {
        "reasons": reasons,
        "labels": [REASONS[k] for k in reasons],
        "project": record.get("project") or None,
        "text": record.get("text") or None,
        "at": str(record.get("at") or "") or None,
        "added_at": added_at,
    }


def commit_message(episode_id: str) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        "Why it was saved", [f"episodes/{episode_id}.md: updated (trigger: {TRIGGER})"],
        authors=[git_service.USER_AUTHOR])
