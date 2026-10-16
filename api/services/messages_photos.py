"""The photo a ticked Messages chat shares, as its correspondent page's picture everywhere (G179, owner 2026-10-16).

#312 drew the photo a chat's other side shares through Messages' "Share Name and Photo" on the Messages bubble only,
in the app's memory. This module makes it a rung of the one picture precedence (`entity_picture.resolve`): the
person's own choice → a Contacts photo → **the photo the chat shares in Messages** → the rest → a monogram — so the
Graph, the entity card and every other picture of the chat's page draw it.

**Who reads what.** The APP reads ``~/Library/Messages/NickNameCache`` (from a copy, for ticked chats only —
`MessagesSharedPhotos.swift`), shrinks the image to at most 128 px and posts the PNG bytes here; the backend never
opens that path. **Where the bytes live:** ``$CICADA_HOME/pictures/<bank>/messages/<conversation>.png`` beside the
Contacts and public-profile caches — outside every bank, never in git, never sent anywhere — with ``meta.json``
holding each conversation's hash. Nothing is written to a page: the link is derived.

**Which page.** Stored by conversation and served at its *linked page*: the page the conversation's newest live
sitting's decided ``correspondent`` record resolves to through `correspondents.find_page` — the rule Stage 2 resolves
the correspondent by and `messages_source.waiting` names, so the bubble, Sleep and the picture agree. Keyed by
conversation rather than by page because the page usually does not exist yet when the photo is first read (a chat is
held below the promotion bar until Sleep creates it); the link follows the record — a page Sleep creates later, the
person's mark, its removal — with no second post. No decided record, no page of that type, or the chat unticked: no
link, and the rung never fires.

**Lifetime.** Only a ticked chat is accepted (409 otherwise); unticking removes its photo (`forget`, from the settings
route); a changed photo replaces it (a new hash, so a new ``?v=``); a post saying the chat shares none removes it.
The person's own picture always wins — it is the rung above. `stamp` rides the ``photos`` sync component, which the
app already maps onto the graph, so a link or a photo that moves re-renders every picture of the page.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import threading
from pathlib import Path

from api.services import entity_picture, logo_service

DIR = "messages"
META_FILENAME = "meta.json"
#: The app posts ≤ 128 px PNGs (a few KB); this bounds anything else that arrives.
MAX_BYTES = 256 * 1024
MAX_ITEMS = 200
#: A conversation's page can only be one of the correspondent page types (`correspondents.PAGE_TYPE`).
PAGE_TYPES = ("person", "tool")
_LOCK = threading.Lock()
_MEMO: dict[str, tuple[tuple, dict]] = {}


class PayloadError(ValueError):
    """A post the backend cannot trust — answered 422, nothing written."""


def _root(bank: str) -> Path:
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(raw).expanduser() / "pictures" / (bank or "default") / DIR


def meta_path(bank: str) -> Path:
    """The index, without creating anything (a read must not conjure a folder)."""
    return _root(bank) / META_FILENAME


def photo_path(bank: str, conversation: str, ext: str = "png") -> Path | None:
    """The stored photo's path, derived from the conversation id; None for an id or ext it never stores."""
    from api.services import messages_source

    if ext not in entity_picture.UPLOAD_EXTS or not messages_source.CONVERSATION_ID_RE.match(str(conversation or "")):
        return None
    base = _root(bank).resolve()
    path = (base / f"{conversation}.{ext}").resolve()
    return path if path.parent == base else None


def read_meta(bank: str) -> dict:
    try:
        data = json.loads(meta_path(bank).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_meta(bank: str, meta: dict) -> None:
    path = meta_path(bank)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _drop(bank: str, conversation: str, meta: dict) -> bool:
    gone = meta.pop(conversation, None) is not None
    for ext in entity_picture.UPLOAD_EXTS:
        path = photo_path(bank, conversation, ext)
        if path is not None and path.exists():
            path.unlink(missing_ok=True)
            gone = True
    return gone


#: The longest base64 a ``MAX_BYTES`` photo can be: anything longer is refused before a byte is decoded (backend hunt,
#: 2026-10-16 — the decode used to run first).
B64_MAX = 4 * ((MAX_BYTES + 2) // 3)


def _decode(raw) -> tuple[bytes, str]:
    if len(str(raw)) > B64_MAX:
        raise PayloadError("a shared photo is at most 256 KB — the app shrinks it first")
    try:
        data = base64.b64decode(str(raw), validate=True)
    except (binascii.Error, ValueError):
        raise PayloadError("a photo is base64 PNG or JPEG bytes")
    if len(data) > MAX_BYTES:
        raise PayloadError("a shared photo is at most 256 KB — the app shrinks it first")
    try:
        return data, entity_picture.validate_upload(data)
    except entity_picture.InvalidPicture as exc:
        raise PayloadError(str(exc))


def store(memory_path: Path, items: list[dict], *, bank: str | None = None) -> dict:
    """One post from the app: ``[{conversation, photo_b64 | None}]`` for the ticked chats it looked up. ``None``
    means the chat shares no photo (any stored one goes); bytes replace a different stored photo. A chat that is not
    ticked is refused whole (:class:`messages_source.NotSelected`). Returns the counts and each chat's linked page."""
    from api.services import messages_source

    memory_path = Path(memory_path)
    bank = bank or logo_service.bank_name(memory_path)
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise PayloadError(f"at most {MAX_ITEMS} conversations per post")
    ticked = {cid for cid, e in messages_source.load_settings(memory_path)["conversations"].items() if e.get("ticked")}
    decoded: dict[str, tuple[bytes, str] | None] = {}
    for item in items:
        cid = str((item or {}).get("conversation") or "")
        if not messages_source.CONVERSATION_ID_RE.match(cid):
            raise PayloadError("a conversation id is the app's hash of the chat, 16–64 hex characters")
        if cid not in ticked:
            raise messages_source.NotSelected(
                "This conversation isn't ticked in Settings → Integrations → Messages, so its photo wasn't kept.")
        raw = item.get("photo_b64")
        decoded[cid] = _decode(raw) if raw else None
    stored = removed = unchanged = 0
    with _LOCK:
        # Read the ticks again under the lock: an untick (and its `forget`, which takes this lock) that landed since the
        # check above must not be followed by this post writing the chat's photo back (gone on untick).
        still = {cid for cid, e in messages_source.load_settings(memory_path)["conversations"].items()
                 if e.get("ticked")}
        meta = read_meta(bank)
        for cid, photo in decoded.items():
            if cid not in still:
                continue
            if photo is None:
                removed += int(_drop(bank, cid, meta))
                continue
            data, ext = photo
            sha = entity_picture.sha12(data)
            target = photo_path(bank, cid, ext)
            entry = meta.get(cid)
            if isinstance(entry, dict) and entry.get("sha") == sha and entry.get("ext") == ext and target.exists():
                unchanged += 1
                continue
            _drop(bank, cid, meta)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            meta[cid] = {"sha": sha, "ext": ext}
            stored += 1
        if stored or removed:
            _write_meta(bank, meta)
    pages = {link["conversation"]: page for page, link in links(memory_path).items()}
    return {"stored": stored, "removed": removed, "unchanged": unchanged,
            "pages": {cid: pages.get(cid) for cid in decoded}}


def forget(memory_path: Path, conversation: str, *, bank: str | None = None) -> bool:
    """Unticking a chat: its photo and its index entry go. Returns whether anything was there."""
    bank = bank or logo_service.bank_name(Path(memory_path))
    with _LOCK:
        meta = read_meta(bank)
        if not _drop(bank, str(conversation), meta):
            return False
        _write_meta(bank, meta)
        return True


def links(memory_path: Path) -> dict[str, dict]:
    """``{page id: {conversation, sha, ext}}`` — each stored photo of a ticked chat at the page its correspondent
    record resolves to. Empty, reading no episode, when no photo is stored (most banks). Memoized on what it reads:
    the index, the Messages settings, and the episodes' and pages' fingerprints."""
    from api.services import bank_index, correspondents, messages_source

    memory_path = Path(memory_path)
    bank = logo_service.bank_name(memory_path)
    meta = read_meta(bank)
    if not meta:
        return {}

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    key = (json.dumps(meta, sort_keys=True), mtime(messages_source.settings_path(memory_path)),
           bank_index.dir_fingerprint(memory_path / "episodes"), bank_index.dir_fingerprint(memory_path / "entities"))
    memo = _MEMO.get(str(memory_path))
    if memo is not None and memo[0] == key:
        return dict(memo[1])
    ticked = {cid for cid, e in messages_source.load_settings(memory_path)["conversations"].items() if e.get("ticked")}
    wanted = {cid for cid, entry in meta.items() if cid in ticked and isinstance(entry, dict)
              and isinstance(entry.get("sha"), str) and entry.get("ext") in entity_picture.UPLOAD_EXTS}
    out: dict[str, dict] = {}
    if wanted:
        newest: dict[str, tuple[str, dict]] = {}
        for f in bank_index.files(memory_path, "episodes"):
            fm = f.frontmatter or {}
            cid = str(fm.get("conversation") or "")
            if fm.get("origin") != messages_source.ORIGIN or cid not in wanted or fm.get("source_deleted_at"):
                continue
            last = str(fm.get("sitting_last_at") or fm.get("timestamp") or "")
            if cid not in newest or last >= newest[cid][0]:
                record = fm.get("correspondent") if isinstance(fm.get("correspondent"), dict) else {}
                newest[cid] = (last, record)
        idents = {cid: correspondents.identity(record) for cid, (_, record) in newest.items()}
        if any(idents.values()):
            pages = [{"id": f.stem, "frontmatter": f.frontmatter or {}}
                     for f in bank_index.files(memory_path, "entities")]
            # Oldest first, so when two chats name one page the most recently active one is its picture.
            for cid in sorted(idents, key=lambda c: (newest[c][0], c)):
                ident = idents[cid]
                page = correspondents.find_page(pages, ident) if ident is not None else None
                if page is not None:
                    out[str(page["id"])] = {"conversation": cid, "sha": meta[cid]["sha"], "ext": meta[cid]["ext"]}
    _MEMO[str(memory_path)] = (key, out)
    return dict(out)


def picture_path(memory_path: Path, entity_id: str, chats: dict | None = None) -> Path | None:
    """The stored photo a page draws through its chat, or None."""
    link = (links(memory_path) if chats is None else chats).get(entity_id)
    if not isinstance(link, dict):
        return None
    return photo_path(logo_service.bank_name(Path(memory_path)), link["conversation"], link.get("ext") or "png")


def stamp(memory_path: Path) -> str:
    """What moves when any page's chat photo does — a photo stored or gone, a link made or lost. Rides the ``photos``
    sync component (`sync_service`), which the app maps onto the graph."""
    current = links(memory_path)
    if not current:
        return ""
    joined = ",".join(f"{page}={link['sha']}" for page, link in sorted(current.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
