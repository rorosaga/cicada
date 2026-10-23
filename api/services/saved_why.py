"""Ask why at the moment of saving (G191): the person's answer to "What made you save this?".

When the app's bookmark watch sees ONE new bookmark made a moment ago, it shows a small panel with a few one-tap
answers. The answer is the person's own words about their own act, so it is stored on that bookmark's episode — the
same file Sleep reads the page from — through the one staging path (``episode_staging.amend_section``: scrubbed,
written in place, queued for Sleep again). Nothing here calls a model: the choices are a fixed set.

**A few basic reasons (G191 v4, owner 2026-10-15: "some of the options … have nothing to do with it. Can you keep
options to a minimal? Like the design, read later, might be useful for the future, or something else").** The panel
offers exactly :data:`REASONS` — the design, the product, to read later, useful someday — and the person's own words
are the "something else". It no longer offers the person's projects (three "For <project>" chips that named projects
the page had nothing to do with); a project link is Sleep's to infer from the words or the page. What was said before
still reads: a retired reason (:data:`RETIRED`, ``technique``) and a stored ``project`` keep their labels wherever
answers are listed, and an edit of such an answer may keep them.

Two times stay on the record, because a website changes and a later reader must know which page was meant:

* ``added_at`` — when the browser says the bookmark was made (the episode's own key, set at ingest when the browser
  records an instant; ``saved_at`` keeps the day);
* ``saved_why.at`` — when the person said why.

The structured answer rides the episode's frontmatter (``saved_why``) and the source record on the wire
(``GET /sources`` → ``savedWhy``); the words ride its body as a ``## Why it was saved`` section, which Stage 1 reads
like any other text the person wrote (no turn marker, so ``evidence.speaker_kind`` is ``user``).

**Every moment of saving keeps its own reason (G191 v3, owner 2026-10-15: "If I remove the bookmark and bookmark it
again, the prompt doesn't appear").** A bookmark removed and saved again is a new moment of saving, and its answer is a
new dated reason beside the earlier ones — never a replacement. The frontmatter keeps the newest answer as
``saved_why`` (the shape every reader already knows: ``explore_candidates``, ``GET /sources``) and the older ones,
oldest first, as ``saved_why_earlier``; the section lists them all, oldest first. An answer replaces another only
when it is the same answer again — the same ``at`` (the app's retry of a held answer) or the same moment of saving
(the same ``added_at``) — or when the person edits it (:func:`edit`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import bank_index, episode_ids, episode_scrub, episode_staging, media_ingestor, saved_at

#: The fixed one-tap answers, in the order the panel shows them (G191 v4: four, short). Keys are the wire's; labels are
#: the words the section records (the person picked them, so they are the person's answer).
REASONS: dict[str, str] = {
    "design": "The design",
    "product": "The product",
    "read_later": "To read later",
    "someday": "Useful someday",
}
#: Reasons once offered and no longer (G191 v4): an answer that holds one still shows it, by this label, and an edit of
#: that answer may keep it; the panel never offers it again.
RETIRED: dict[str, str] = {
    "technique": "A technique to reuse",
}
#: The reason bank (G191 v7, owner 2026-10-23: "more options that appear smoothly based on the content being saved …
#: found it funny, good asset for video, moodboard potential, interesting design, product, inspiration, aesthetic …
#: let's have a lot of options"). Never the panel's fixed row — :data:`REASONS` stays exactly as it was, so nothing a
#: person relies on moves — but the pool the panel suggests a few from, ranked on the Mac by the site, the link's own
#: words and the person's past picks (``SaveWhySuggest``), plus the search model's similarity only when it is already
#: installed (:func:`model_scores`). A chosen one is stored like any reason: its key in ``saved_why`` and its label as
#: the person's line in the section. Keys are permanent: a reason dropped from the bank moves to :data:`RETIRED`, never
#: out of :data:`LABELS`. The app carries the same keys (``SavedWhyOptions.bank``), pinned by a test on both sides.
MORE: dict[str, str] = {
    "funny": "Found it funny",
    "video_asset": "Asset for a video",
    "moodboard": "For a moodboard",
    "inspiration": "Inspiration",
    "aesthetic": "The aesthetic",
    "product_idea": "A product idea",
    "tool_to_try": "A tool to try",
    "to_buy": "To buy",
    "gift_idea": "A gift idea",
    "reference": "A reference",
    "recipe": "A recipe to try",
    "to_watch": "To watch later",
    "to_listen": "To listen to",
    "to_learn": "To learn from",
    "how_to": "A how-to",
    "research": "Research",
    "typography": "The typography",
    "ui_pattern": "A UI pattern",
    "palette": "The colours",
    "photo": "The photo",
    "art": "The art",
    "music": "The music",
    "quote": "A quote I liked",
    "idea": "An idea to explore",
    "to_share": "To share",
    "news": "News to follow",
    "someone_to_follow": "Someone to follow",
    "for_work": "For work",
    "place": "A place to go",
    "travel": "Travel idea",
    "outfit": "Outfit idea",
    "home": "For the home",
    "workout": "A workout",
    "code": "Code to reuse",
    "good_writing": "Good writing",
    "data": "Interesting data",
    "event": "An event to go to",
    "advice": "Good advice",
}
#: Every reason an answer can hold, offered first, in the order an answer lists them.
LABELS: dict[str, str] = {**REASONS, **MORE, **RETIRED}
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


def options(memory_path: Path) -> dict:
    """The panel's choices: the four reasons, the bank it suggests from (``more``, G191 v7) and the cap on the words.
    ``reasons`` is unchanged since G191 v4, so an older app shows the same four; ``projects`` stays on the wire, always
    empty, so an app built before G191 v4 shows no project chips either."""
    return {
        "reasons": [{"key": k, "label": v} for k, v in REASONS.items()],
        "more": [{"key": k, "label": v} for k, v in MORE.items()],
        "projects": [],
        "max_text": MAX_TEXT,
    }


#: The bank's label vectors per model id, computed once per process.
_LABEL_VECTORS: dict[str, object] = {}
_NONE = {"basis": "none", "scores": []}


def installed_search_model(environ=None):
    """EmbeddingGemma's folder when it is already installed and this Mac runs it, else None. Only a look at what is on
    disk (``onnx_embedder.find``) — never a download, a fetch or a key: the model arrives only on the person's click
    (the search-model rail), and a metered embedding service is never asked for a suggestion."""
    import os

    from api.services import onnx_embedder

    return onnx_embedder.find(onnx_embedder.PREFERRED_ID, os.environ if environ is None else environ)


def model_scores(*, title: str, url: str, environ=None, embed=None, model_id: str = "") -> dict:
    """G191 v7 — how close each bank reason is to the saved link's own words by the local search model, **only when
    it is already installed**: ``{"basis": "model", "scores": [{key, score}]}`` (cosine, in the bank's order), else
    ``{"basis": "none", "scores": []}`` and the Mac's own ranking stands alone. No network, no new model, nothing
    written, nothing logged (the query rail: the title and link are never logged).

    ``embed`` (tests) stands in for the installed model: ``embed(texts, is_query=...) -> 2-D array``."""
    import numpy as np

    words = " ".join(f"{title or ''} {site_words(url)}".split())
    if not words:
        return dict(_NONE)
    if embed is None:
        spec = installed_search_model(environ)
        if spec is None:
            return dict(_NONE)
        from api.services import providers

        try:
            embed, model_id = providers.cached_embed_fn_for_model(spec.id)
        except Exception:  # noqa: BLE001 — a model that will not load suggests nothing; the Mac's ranking stands
            return dict(_NONE)
    keys = tuple(MORE)
    try:
        labels = _LABEL_VECTORS.get(model_id) if model_id else None
        if labels is None:
            labels = np.asarray(embed([MORE[k] for k in keys], is_query=False), dtype=np.float32)
            labels = labels / np.maximum(np.linalg.norm(labels, axis=1, keepdims=True), 1e-9)
            if model_id:
                _LABEL_VECTORS[model_id] = labels
        query = np.asarray(embed([words], is_query=True), dtype=np.float32)[0]
        query = query / max(float(np.linalg.norm(query)), 1e-9)
        sims = labels @ query
    except Exception:  # noqa: BLE001 — a suggestion is never an error
        return dict(_NONE)
    return {"basis": "model", "scores": [{"key": k, "score": round(float(s), 4)} for k, s in zip(keys, sims)]}


def site_words(url: str) -> str:
    """The link's host and path as words ("youtube com watch"), never its query or fragment (which may carry a token)."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return ""
    host = (parts.hostname or "").removeprefix("www.")
    text = f"{host.replace('.', ' ')} {parts.path}"
    for sep in "/-_.+":
        text = text.replace(sep, " ")
    return " ".join(w for w in text.split() if not w.isdigit())


def _project_name(memory_path: Path, project: str, *, live: bool = True) -> str | None:
    entry = bank_index.file(Path(memory_path), "entities", f"{project}.md")
    if entry is None:
        return None
    fm = entry.frontmatter or {}
    if str(fm.get("type") or "") != "project":
        return None
    if live and str(fm.get("status") or "active") in ("archived", "dropped"):
        return None
    return str(fm.get("name") or project).strip() or project


def validate(memory_path: Path, *, reasons: list[str] | None, project: str | None, text: str | None,
             editing: bool = False) -> Answer:
    """The answer as it will be stored, or :class:`SavedWhyError` (422) for one that names nothing or something
    unknown. Order is :data:`LABELS`', duplicates fold. A retired reason is known (an older app still sends it, and an
    edit keeps what the answer held); a project must be a live one, or — ``editing`` an answer that already names it —
    any project page."""
    picked = tuple(k for k in LABELS if k in set(reasons or []))
    unknown = sorted(set(reasons or []) - set(LABELS))
    if unknown:
        raise SavedWhyError(422, f"Unknown reason {unknown[0]!r}")
    project = (project or "").strip() or None
    project_name = None
    if project is not None:
        project_name = _project_name(memory_path, project, live=not editing)
        if project_name is None:
            raise SavedWhyError(422, f"{project!r} is not a live project")
    words = " ".join((text or "").split()) or None
    if words is not None and len(words) > MAX_TEXT:
        raise SavedWhyError(422, f"Keep it under {MAX_TEXT} characters")
    if not picked and project is None and words is None:
        raise SavedWhyError(422, "Pick a reason or say one")
    return Answer(reasons=picked, project=project, project_name=project_name, text=words)


#: G191 (review B1) — how old a client's ``at`` may be: an answer held by the app while Sleep wrote (a 409) or the
#: backend was down is retried later, and keeps the time the person actually said it, for at most this long.
MAX_CLIENT_AGE = timedelta(hours=24)
#: A client clock a little ahead of the backend's is still "now", never later.
CLIENT_SKEW = timedelta(seconds=60)


def client_at(raw: str | None, *, now: datetime | None = None) -> str | None:
    """The answer's time as the app recorded it (aware UTC ISO, seconds), or ``None`` when the client sent none.
    :class:`SavedWhyError` (422) for a naive, unparseable, future or over-a-day-old value — never guessed."""
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise SavedWhyError(422, "`at` must be an ISO time with a zone")
    if dt.tzinfo is None:
        raise SavedWhyError(422, "`at` must carry its zone")
    now = now or datetime.now(timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    if dt > now + CLIENT_SKEW:
        raise SavedWhyError(422, "`at` is in the future")
    if now - dt > MAX_CLIENT_AGE:
        raise SavedWhyError(422, "`at` is more than a day old")
    return dt.isoformat()


def _normal_at(raw: str | None) -> str:
    """An existing answer's time as a client names it (aware ISO, any zone) in the stored form; 422 when it is not
    one. Not bounded by age: it names an answer already on the record, however old."""
    text = str(raw or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise SavedWhyError(422, "`at` must be an ISO time with a zone")
    if dt.tzinfo is None:
        raise SavedWhyError(422, "`at` must carry its zone")
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def render(answer: Answer, *, at: str, added_at: str | None) -> str:
    """The section's text (without its heading): when it was said and saved, then one line per answer."""
    when = f"Said {at}" + (f", about a bookmark saved {added_at}" if added_at else "") + "."
    lines = [when]
    lines += [f"- {LABELS[k]}" for k in answer.reasons]
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


#: The older answers, oldest first, beside the newest in ``saved_why`` (G191 v3).
EARLIER_KEY = "saved_why_earlier"
#: How many answers one link keeps. A link saved over and over keeps its newest reasons; the oldest fall off the
#: frontmatter (git still holds every version).
MAX_ANSWERS = 20


def records_of(fm: dict | None) -> list[dict]:
    """Every answer on an episode, oldest first (by ``at``; an answer with no time sorts first)."""
    fm = fm or {}
    out = [dict(r) for r in (fm.get(EARLIER_KEY) or []) if isinstance(r, dict)]
    latest = fm.get("saved_why")
    if isinstance(latest, dict):
        out.append(dict(latest))
    return sorted(out, key=lambda r: str(r.get("at") or ""))


def _frontmatter(records: list[dict]) -> tuple[dict, tuple[str, ...]]:
    """``(extra, drop)`` that store ``records`` (oldest first): the newest as ``saved_why``, the rest as earlier."""
    records = records[-MAX_ANSWERS:]
    extra = {"saved_why": records[-1]}
    if len(records) > 1:
        extra[EARLIER_KEY] = records[:-1]
        return extra, ()
    return extra, (EARLIER_KEY,)


def _same_answer(record: dict, *, at: str, added_at: str | None) -> bool:
    """Whether a stored answer is the one being written again: its own time, or the same moment of saving."""
    if str(record.get("at") or "") == at:
        return True
    return bool(added_at) and str(record.get("added_at") or "") == added_at


def _name_of(memory_path: Path, project: str | None) -> str | None:
    if not project:
        return None
    return _project_name(memory_path, project, live=False) or project


def render_all(memory_path: Path, records: list[dict], *, episode_added_at: str | None) -> str:
    """The section's text for every answer, oldest first, one paragraph each. The first answer is about the save the
    episode records (its own ``added_at``) unless it says otherwise; a later one names its own moment when it has
    one."""
    paragraphs = []
    for i, record in enumerate(records):
        answer = Answer(reasons=tuple(k for k in LABELS if k in set(record.get("reasons") or [])),
                        project=record.get("project") or None,
                        project_name=_name_of(memory_path, record.get("project")),
                        text=record.get("text") or None)
        added = record.get("added_at") or (episode_added_at if i == 0 else None)
        paragraphs.append(render(answer, at=str(record.get("at") or ""), added_at=added))
    return "\n\n".join(paragraphs)


def _record(answer: Answer, *, at: str, added_at: str | None) -> dict:
    text, _ = episode_scrub.scrub(answer.text) if answer.text else (None, 0)
    record = {"reasons": list(answer.reasons), "project": answer.project, "text": text, "at": at}
    if added_at:
        record["added_at"] = added_at
    return record


def attach(memory_path: Path, *, url: str, answer: Answer, at: str | None = None,
           added_at: str | None = None, bank: str | None = None) -> dict:
    """Write ``answer`` onto the saved link's episode: a new dated reason beside the earlier ones, or in place of the
    same answer sent again (:func:`_same_answer`). ``added_at`` is the moment of saving it answers (the browser's
    instant, when the app has it). Returns the wire shape plus ``episode_id``, ``media_entity_id`` and ``changed``.
    The caller commits (inside its write admission)."""
    memory_path = Path(memory_path)
    episode_id, media_entity_id, path = find_episode(memory_path, url)
    at = at or episode_ids.utc_now_seconds()
    added_at = saved_at.validate_instant(added_at) if added_at else None
    record = _record(answer, at=at, added_at=added_at)
    seen: dict = {}

    def build(fm: dict):
        records = [r for r in records_of(fm) if not _same_answer(r, at=at, added_at=added_at)]
        records = sorted(records + [record], key=lambda r: str(r.get("at") or ""))
        seen["fm"], seen["records"] = fm, records
        extra, drop = _frontmatter(records)
        return render_all(memory_path, records[-MAX_ANSWERS:], episode_added_at=_added(fm)), extra, drop

    changed = episode_staging.revise_section(path, HEADING, build, writer=WRITER, bank=bank or memory_path.name,
                                             before=_BEFORE)
    episode_added = _added(seen.get("fm") or {})
    return {"episode_id": episode_id, "media_entity_id": media_entity_id, "changed": changed,
            "saved_why": wire(record, added_at=episode_added),
            "history": history_wire(seen.get("records") or [record], added_at=episode_added)}


def edit(memory_path: Path, *, url: str, at: str, answer: Answer, bank: str | None = None) -> dict:
    """The person changed one answer (the one said at ``at``) — from the app's bookmark page or any client of the
    route. Its time and its moment of saving are kept, ``edited_at`` records the change; every other answer is
    untouched. :class:`SavedWhyError` 404 when the link has no answer said at ``at``."""
    memory_path = Path(memory_path)
    episode_id, media_entity_id, path = find_episode(memory_path, url)
    at = _normal_at(at)
    found: dict = {}

    def build(fm: dict):
        records = records_of(fm)
        for i, r in enumerate(records):
            if str(r.get("at") or "") == at:
                new = _record(answer, at=at, added_at=r.get("added_at"))
                if _same_words(r, new):
                    # 2026-10-19 (owner: the star on a saved page opens the same panel, filled in): an edit that
                    # changes nothing writes nothing — no `edited_at`, no rewrite, no commit, not queued for Sleep.
                    found["record"] = r
                    break
                new["edited_at"] = episode_ids.utc_now_seconds()
                records[i] = new
                found["record"] = new
                break
        else:
            raise SavedWhyError(404, "There's no answer from that time to change")
        found["fm"], found["records"] = fm, records
        extra, drop = _frontmatter(records)
        return render_all(memory_path, records[-MAX_ANSWERS:], episode_added_at=_added(fm)), extra, drop

    changed = episode_staging.revise_section(path, HEADING, build, writer=WRITER, bank=bank or memory_path.name,
                                             before=_BEFORE)
    episode_added = _added(found.get("fm") or {})
    return {"episode_id": episode_id, "media_entity_id": media_entity_id, "changed": changed,
            "saved_why": wire(found["record"], added_at=episode_added),
            "history": history_wire(found.get("records") or [], added_at=episode_added)}


def _same_words(stored: dict, new: dict) -> bool:
    """Whether an edit leaves an answer as it was: the same reasons (any order), project and words."""
    return (set(stored.get("reasons") or []) == set(new.get("reasons") or [])
            and (stored.get("project") or None) == (new.get("project") or None)
            and (stored.get("text") or None) == (new.get("text") or None))


def _added(fm: dict) -> str | None:
    return str(fm.get("added_at") or "") or None


def wire(record: dict | None, *, added_at: str | None) -> dict | None:
    """The source record's ``savedWhy``: the answer, when it was given, and when the bookmark was made (the answer's
    own moment of saving when it has one — a re-save — else the episode's)."""
    if not isinstance(record, dict):
        return None
    # Retired reasons still read (G191 v4): what the person once picked is still what they picked.
    reasons = [str(k) for k in (record.get("reasons") or []) if str(k) in LABELS]
    return {
        "reasons": reasons,
        "labels": [LABELS[k] for k in reasons],
        "project": record.get("project") or None,
        "text": record.get("text") or None,
        "at": str(record.get("at") or "") or None,
        "added_at": str(record.get("added_at") or "") or added_at,
        "edited_at": str(record.get("edited_at") or "") or None,
    }


def history_wire(records: list[dict], *, added_at: str | None) -> list[dict]:
    """Every answer, oldest first, each as :func:`wire` shapes it (the first about the episode's own save)."""
    out = []
    for i, record in enumerate(records):
        shaped = wire(record, added_at=added_at if i == 0 else None)
        if shaped is not None:
            out.append(shaped)
    return out


def last_saved(fm: dict | None) -> str | None:
    """The newest moment this link was saved, as far as the record knows: the episode's own ``added_at`` or a later
    re-save an answer names (G191 v3) — the history list's order. ``None`` when neither says."""
    fm = fm or {}
    moments = [m for m in [_added(fm)] + [str(r.get("added_at") or "") for r in records_of(fm)] if m]
    return max(moments, key=saved_at.sort_instant) if moments else None


def commit_message(episode_id: str) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        "Why it was saved", [f"episodes/{episode_id}.md: updated (trigger: {TRIGGER})"],
        authors=[git_service.USER_AUTHOR])
