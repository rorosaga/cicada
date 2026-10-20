"""What made a conversation a conversation, beside its words: reactions, replies, attachments, edits, unsends.

The owner, 2026-10-20: "In Messages, from the raw conversation, it would be cool to show the reactions and stuff. Same
with everything else." One source-neutral shape every chat source fills where its data has it — Messages (tapbacks,
inline replies, attachments, edits, unsends), the ChatGPT export (attachments, generated images, code runs) and the
Claude export (attached files) — and the Reader draws.

**Never in the words.** Extras live in the episode's frontmatter, OUTSIDE the body the evidence layer indexes and the
content hash covers (G118): a span's offsets into a turn's text cannot move because a reaction arrived, and a reaction
never re-queues a conversation for Sleep. Two keys, written by :mod:`episode_staging` alone (the one writer of a
source-keyed episode), both before the ``turns`` sidecar (R-PB4 keeps it last):

* ``turn_extras: [{offset, reactions?, reply_to?, attachments?, edited?, forwarded_from?, code_runs?}]`` — one entry
  per turn that has any, keyed by the turn's marker-line start (the offset ``evidence.turns`` and the sidecar use).
  ``reactions: [{by, kind, emoji?}]`` where ``by`` is a turn marker (``user``, ``assistant``, ``speaker:<label>``) and
  ``kind`` one of :data:`REACTION_KINDS`; ``reply_to`` the offset of the target turn in this episode, or ``{ref}`` — a
  source's opaque message key — when the target is not in it; ``attachments: [{kind, name, size?, mime?,
  generated?}]`` — a name and a size, never a path and never a byte of the file; ``edited: true``;
  ``forwarded_from`` a name; ``code_runs`` how many code runs fed an agent's reply.
* ``unsent_turns: [{at, speaker, ts?, ref?}]`` — a message its sender unsent: WHERE it was (``at`` = the offset of the
  turn it preceded, or one past the body's end) and who sent it, never its words.

**Reactions are not turns.** They never become a body line, so never a person's statement, an episode of their own,
or anything Sleep reads. Every string here is scrubbed like the body (R-N3). No LLM.
"""

from __future__ import annotations

from api.services import episode_scrub

EXTRAS_KEY = "turn_extras"
UNSENT_KEY = "unsent_turns"
#: Every kind a reaction can be — Messages' six classic tapbacks, an emoji tapback and a sticker one (2000–2007).
REACTION_KINDS = ("love", "like", "dislike", "laugh", "emphasize", "question", "emoji", "sticker")
#: The words a reaction kind shows as when its source gave no emoji of its own.
REACTION_EMOJI = {"love": "❤️", "like": "\U0001f44d", "dislike": "\U0001f44e", "laugh": "\U0001f602",
                  "emphasize": "‼️", "question": "❓"}
ATTACHMENT_KINDS = ("image", "video", "audio", "file", "sticker")
MAX_REACTIONS = 32
MAX_ATTACHMENTS = 10
MAX_UNSENT = 200
NAME_CAP = 120
MARKER_CAP = 64
EMOJI_CAP = 16
MIME_CAP = 80
REF_CAP = 64


def _text(value, cap: int) -> str:
    """One scrubbed line, capped."""
    line = " ".join(str(value or "").split())
    if not line:
        return ""
    return episode_scrub.scrub(line)[0][:cap]


def _marker(value) -> str:
    marker = " ".join(str(value or "").split())[:MARKER_CAP]
    if marker in ("user", "assistant") or (marker.startswith("speaker:") and len(marker) > len("speaker:")):
        return marker
    return ""


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def clean_reactions(raw) -> list[dict]:
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else ():
        if not isinstance(item, dict):
            continue
        by, kind = _marker(item.get("by")), str(item.get("kind") or "")
        if not by or kind not in REACTION_KINDS:
            continue
        entry = {"by": by, "kind": kind}
        emoji = " ".join(str(item.get("emoji") or "").split())[:EMOJI_CAP]
        if emoji:
            entry["emoji"] = emoji
        out.append(entry)
        if len(out) >= MAX_REACTIONS:
            break
    return out


def clean_attachments(raw) -> list[dict]:
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else ():
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "file")
        entry: dict = {"kind": kind if kind in ATTACHMENT_KINDS else "file",
                       "name": _text(str(item.get("name") or "").replace("\\", "/").rsplit("/", 1)[-1], NAME_CAP)}
        if (size := _int(item.get("size"))) is not None:
            entry["size"] = size
        if mime := " ".join(str(item.get("mime") or "").split()).lower()[:MIME_CAP]:
            entry["mime"] = mime
        if item.get("generated") is True:
            entry["generated"] = True
        out.append(entry)
        if len(out) >= MAX_ATTACHMENTS:
            break
    return out


def _clean_ref(value) -> dict | None:
    if isinstance(value, dict) and value.get("ref"):
        ref = str(value["ref"]).strip()[:REF_CAP]
        return {"ref": ref} if ref else None
    return None


def clean(raw, *, index: int, count: int) -> dict:
    """One draft turn's extras, validated: ``reply_to`` is an index into the draft's turns (another turn's) or
    ``{ref}``; anything malformed is dropped, never raised."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    if reactions := clean_reactions(raw.get("reactions")):
        out["reactions"] = reactions
    reply = raw.get("reply_to")
    target = _int(reply)
    if target is not None and target < count and target != index:
        out["reply_to"] = target
    elif ref := _clean_ref(reply):
        out["reply_to"] = ref
    if attachments := clean_attachments(raw.get("attachments")):
        out["attachments"] = attachments
    if raw.get("edited") is True:
        out["edited"] = True
    if forwarded := _text(raw.get("forwarded_from"), NAME_CAP):
        out["forwarded_from"] = forwarded
    runs = _int(raw.get("code_runs"))
    if runs:
        out["code_runs"] = min(runs, 99)
    return out


def render(turns: list, line_lengths: list[int], unsent: list[dict], body_length: int) -> dict:
    """``{turn_extras?, unsent_turns?}`` for a draft whose turns render to lines of ``line_lengths`` (``\\n``-joined).

    ``turns`` are ``episode_staging.Turn``s (their ``extras``); ``unsent`` the draft's ``[{before, speaker, ts?,
    ref?}]`` with ``before`` an index into the turns (``len(turns)`` = after the last)."""
    starts: list[int] = []
    offset = 0
    for n in line_lengths:
        starts.append(offset)
        offset += n + 1
    count = len(starts)
    entries: list[dict] = []
    for i, turn in enumerate(turns[:count]):
        extras = clean(getattr(turn, "extras", None), index=i, count=count)
        if not extras:
            continue
        if isinstance(extras.get("reply_to"), int):
            extras["reply_to"] = starts[extras["reply_to"]]
        entries.append({"offset": starts[i], **extras})
    gone: list[dict] = []
    for item in unsent if isinstance(unsent, list) else ():
        if not isinstance(item, dict):
            continue
        before = _int(item.get("before"))
        speaker = _marker(item.get("speaker"))
        if before is None or not speaker:
            continue
        entry: dict = {"at": starts[before] if before < count else body_length + 1, "speaker": speaker}
        if item.get("ts"):
            entry["ts"] = str(item["ts"])
        if ref := _clean_ref({"ref": item.get("ref")}):
            entry["ref"] = ref["ref"]
        gone.append(entry)
        if len(gone) >= MAX_UNSENT:
            break
    out: dict = {}
    if entries:
        out[EXTRAS_KEY] = entries
    if gone:
        out[UNSENT_KEY] = gone
    return out


def has_any(turns: list, unsent) -> bool:
    return bool(unsent) or any(getattr(t, "extras", None) for t in turns)


def stored(fm: dict | None) -> dict:
    """The two keys as an episode holds them (``{}`` when it holds neither) — what :func:`apply` compares against."""
    fm = fm or {}
    return {k: fm[k] for k in (EXTRAS_KEY, UNSENT_KEY) if fm.get(k)}


def apply(fm: dict, extras: dict) -> None:
    """Set the episode's extras to exactly ``extras`` (a key it no longer has is dropped). The caller keeps the
    sidecar last (R-PB4): ``episode_staging`` is the one writer."""
    fm.pop(EXTRAS_KEY, None)
    fm.pop(UNSENT_KEY, None)
    for key in (EXTRAS_KEY, UNSENT_KEY):
        if extras.get(key):
            fm[key] = extras[key]


# --- Reading (the Reader, through `provenance`) ---------------------------------------------------------------------


def by_offset(fm: dict | None) -> dict[int, dict]:
    """``offset -> extras`` from a stored episode, tolerant: a malformed entry is skipped, never raised."""
    out: dict[int, dict] = {}
    for entry in (fm or {}).get(EXTRAS_KEY) or []:
        if not isinstance(entry, dict):
            continue
        offset = _int(entry.get("offset"))
        if offset is None or offset in out:
            continue
        out[offset] = {k: v for k, v in entry.items() if k != "offset"}
    return out


def unsent(fm: dict | None) -> list[dict]:
    out: list[dict] = []
    for entry in (fm or {}).get(UNSENT_KEY) or []:
        if isinstance(entry, dict) and _int(entry.get("at")) is not None and _marker(entry.get("speaker")):
            out.append(entry)
    return out


_IMAGE_EXT = ("png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp", "tif", "tiff", "svg")
_VIDEO_EXT = ("mp4", "mov", "m4v", "webm", "avi", "mkv")
_AUDIO_EXT = ("mp3", "m4a", "wav", "aac", "ogg", "flac", "opus", "caf")


def kind_for(mime: str | None = None, name: str | None = None) -> str:
    """An attachment's kind from its type, else its name's extension — never from its bytes."""
    m = str(mime or "").lower()
    for kind in ("image", "video", "audio"):
        if m.startswith(kind + "/"):
            return kind
    ext = str(name or "").rsplit(".", 1)[-1].lower() if "." in str(name or "") else ""
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    return "file"
