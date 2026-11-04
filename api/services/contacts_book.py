"""The Contacts page's faces — every card on this Mac, for this Mac's own app to draw (G154, G161, owner 2026-11-04).

The waiting set (``contacts_local``, ruling 33) keeps only the cards Sleep could one day match, so the page could not
show the rest of the address book: a one-part name is never kept there, by rule. This is a second store with one job,
drawing the grid, and it is deliberately not a way into the first:

* **Nothing reads it but its own routes, and ``name_guard``.** ``WaitingIndex``, ``seed_page``, ``rematch`` and
  ``waiting_status`` read ``contacts.json``; none of them knows this file, so a one-part name still never matches or
  promotes anybody. The guard (ruling 54) reads its names only to keep them out of a web search; it writes nothing.
* **Names and a thumbnail only.** Never which facts a card holds, never its id in the clear (a key hashed from it, the
  waiting thumbnails' rule), and never an organisation's name: a card with no personal name is kept nameless.
* **Which card has a page is derived on read**, from the ``addressbook://`` sources on the pages: a Sleep rematch, a
  first mention's seed or the person removing a wrong match shows at once, with no second match rule to drift.
* **Per device.** ``$CICADA_HOME/people/<bank>/contacts-book/<scope>/``: the backend's own computer is one scope and
  each per-device token its own, so a client of a backend elsewhere reads the book it posted, never another Mac's. On a
  copy the routes run locally (``replica_routes``), since the book is where the reader is, not at the home.
* **Forgotten with the rest.** ``contacts_local.forget_waiting`` removes every scope under its lock and its marker
  stops a save read before it; revoking a device removes that device's scope and stops a save still in flight
  (:func:`forget_device`).

Outside every bank and git (folder 0700, files 0600, written by a rename); empty on a demo bank.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from api.services import bank_index, contacts_local, fact_sources, people_directory

BOOK_DIR = people_directory.CONTACTS_BOOK_DIR
BOOK_FILE = "book.json"
#: The scopes of revoked devices, one file in ``$CICADA_HOME/people/``: a PUT already past the token check when its
#: device was revoked never brings that book back. Scopes are hashes, so no device id is kept; ids are never reused.
REVOKED_FILE = ".contacts-book-revoked"
REVOKED_KEEP = 64
#: This backend's own computer, when no per-device token signed the request.
HERE = "here"
NAME_CAP = 200
_KEY = re.compile(r"[0-9a-f]{16}")


def scope_of(device_id: str | None) -> str:
    """The folder a request's book lives in: ``device_id`` comes from its token (``device_context``), never its body."""
    if not device_id:
        return HERE
    return "device-" + hashlib.sha256(str(device_id).encode("utf-8")).hexdigest()[:16]


def _folder(bank: str, scope: str) -> Path:
    return people_directory.path(bank, BOOK_DIR) / scope


def _label(value) -> str:
    return " ".join(str(value or "").split())[:NAME_CAP]


def name_of(card: dict) -> str:
    return " ".join(p for p in (card.get("given"), card.get("family")) if p and isinstance(p, str))


def save(bank: str, scope: str, cards: list[dict], *, connection: str | None = None) -> int:
    """The whole book, replacing the last one, thumbnails included. Returns how many cards it holds. Raises
    :class:`contacts_local.Disconnected` for a connection the person ended; a forget since this read wins and saves
    nothing."""
    read_at = time.time_ns()
    if contacts_local.connection_ended(connection):
        raise contacts_local.Disconnected("Contacts was disconnected; this sync was sent before that and is dropped.")
    if len(cards) > contacts_local.MAX_CONTACTS:
        raise contacts_local.PayloadError(f"at most {contacts_local.MAX_CONTACTS} contacts per sync")
    rows: dict[str, dict] = {}
    photos: dict[str, bytes] = {}
    for card in cards:
        card_id = str(card.get("id") or "").strip()
        if not 0 < len(card_id) <= contacts_local.ID_CAP:
            continue
        key = contacts_local._card_key(card_id)
        row = {"key": key, "given": _label(card.get("given_name")), "family": _label(card.get("family_name"))}
        photo = contacts_local._photo(card.get("photo_b64"))
        if photo is not None:
            row["photo"] = f"{key}.{photo[1]}"
            row["sha"] = hashlib.sha256(photo[0]).hexdigest()[:12]
            photos[row["photo"]] = photo[0]
        rows[key] = row
    with contacts_local._WAITING_LOCK:
        if contacts_local.forgotten_since(read_at) or scope in _revoked():
            return 0
        _write(bank, scope, list(rows.values()), photos)
    return len(rows)


def _revoked() -> list[str]:
    try:
        rows = json.loads((_people_root() / REVOKED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, str)] if isinstance(rows, list) else []


def _people_root() -> Path:
    return people_directory.folder("x").parent


def _write(bank: str, scope: str, rows: list[dict], photos: dict[str, bytes]) -> None:
    folder = _folder(bank, scope)
    people_directory.ensure(bank)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in (folder, folder.parent):
        directory.chmod(0o700)
    for name, data in photos.items():
        target = folder / name
        try:
            if target.read_bytes() == data:
                continue
        except OSError:
            pass
        people_directory.write_bytes(target, data)
    people_directory.save_json(bank, f"{BOOK_DIR}/{scope}/{BOOK_FILE}", {"v": 1, "cards": rows})
    for stale in folder.iterdir():
        if stale.is_file() and stale.name != BOOK_FILE and stale.name not in photos:
            stale.unlink(missing_ok=True)


def _load(bank: str, scope: str) -> list[dict]:
    rows = people_directory.load_json(bank, f"{BOOK_DIR}/{scope}/{BOOK_FILE}").get("cards")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("key") and isinstance(r["key"], str)]


def _links(memory_path: Path, rows: list[dict]) -> dict[str, str]:
    """A card's key → the person page that carries it: the page's own ``addressbook://`` sources, the channel list's
    rule (``channel_items._contacts``). A page with a Contacts photo and no such source (a card holding no facts) is
    joined by the name a sync matched it on, only when exactly one card carries that name."""
    links: dict[str, str] = {}
    photo_only: dict[str, set[str]] = {}
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if fm.get("type") != "person" or fm.get("status") == "dropped":
            continue
        refs = [str(s.get("ref")) for s in fact_sources.as_sources(fm.get("sources"))
                if contacts_local._is_mine(s)]
        for ref in refs:
            links[contacts_local._card_key(ref[len(contacts_local.REF_SCHEME):])] = f.stem
        if not refs and fm.get(contacts_local.FRONTMATTER_KEY):
            for label in people_directory.labels(fm, f.stem):
                folded = people_directory.fold(label)
                if folded:
                    photo_only.setdefault(folded, set()).add(f.stem)
    if photo_only:
        joined: dict[str, list[str]] = {}
        for row in rows:
            if row["key"] in links:
                continue
            hits: set[str] = set()
            for key in contacts_local.name_keys(row.get("given"), row.get("family")):
                hits |= photo_only.get(key, set())
            if len(hits) == 1:
                joined.setdefault(next(iter(hits)), []).append(row["key"])
        links.update({found[0]: eid for eid, found in joined.items() if len(found) == 1})
    return links


def read(memory_path: Path, bank: str, scope: str) -> dict:
    """The book as the app draws it: the cards with a page first, then by name, nameless last. Counts and names only."""
    from api.services import demo_guard

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        return {"total": 0, "in_memory": 0, "cards": []}
    rows = _load(bank, scope)
    links = _links(memory_path, rows) if rows else {}
    cards = [{"key": r["key"], "name": name_of(r), "entity_id": links.get(r["key"]), "photo": r.get("sha")}
             for r in rows]
    cards.sort(key=lambda c: (c["entity_id"] is None, not c["name"], people_directory.fold(c["name"]), c["key"]))
    return {"total": len(cards), "in_memory": sum(1 for c in cards if c["entity_id"]), "cards": cards}


def photo(memory_path: Path, bank: str, scope: str, key: str) -> tuple[bytes, str] | None:
    """One card's thumbnail, by its key in this scope's book only, re-checked by its magic bytes."""
    from api.services import demo_guard

    if not _KEY.fullmatch(key or "") or demo_guard.is_demo(Path(memory_path)):
        return None
    row = next((r for r in _load(bank, scope) if r["key"] == key), None)
    name = str((row or {}).get("photo") or "")
    if not name or "/" in name or name.startswith("."):
        return None
    try:
        data = (_folder(bank, scope) / name).read_bytes()
    except OSError:
        return None
    return contacts_local._photo(base64.b64encode(data).decode("ascii"))


def forget_device(device_id: str) -> None:
    """A revoked device's book, in every bank: a server keeps no address book of a machine it no longer trusts."""
    scope = scope_of(device_id)
    root = _people_root()
    with contacts_local._WAITING_LOCK:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        revoked = [r for r in _revoked() if r != scope] + [scope]
        people_directory.write_bytes(root / REVOKED_FILE, json.dumps(revoked[-REVOKED_KEEP:]).encode("utf-8"))
        for bank in root.iterdir():
            target = bank / BOOK_DIR / scope
            if bank.is_dir() and not bank.is_symlink() and target.is_dir() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=True)
