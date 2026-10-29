"""macOS Contacts — the backend half (G154; round 4 decision 12; R-SR8, R-SR9).

The address book holds the people a person knows; the graph holds the ones they talk about. G81's rail governs the
join: a contact is a third party's details, and hundreds of dormant cards would flood the graph — so Contacts
**enriches a `person` page Cicada already has and never mints one**. The APP reads the address book after one
standard prompt and posts, per contact, its names and *which* facts the card holds — never an email address or a
phone number (R-SR8 settles G154's open question: no raw value crosses the wire, so none can land in a bank).

A contact matches a page when its given and family name (either order), folded like search, equal the page's name or
one of its aliases — exactly one page, and no other contact on that page. For each fact the card holds, the page
gains a G61 source `{ref: addressbook://<contact id>, kind: app, predicate, added_by: cicada}`: where to look it up,
not a copy. A sync owns exactly the entries whose ref is `addressbook://…` and whose `added_by` is `cicada` — it adds,
keeps and removes those in place, never touches one the person or an agent added, and never re-adds one the person
removed (`_contacts_rejected.yaml`, final review finding 1). **Owner ruling 2026-10-20: unmatched cards wait, and a card is
matched on mention** — never one page per card. A card that matches no page is kept outside every bank, in the people
directory (`people_directory`, `$CICADA_HOME/people/<bank>/contacts.json` and its thumbnails, 0600), with exactly what
the app posted; every sync rewrites it whole, deletions included, and the bank gets nothing for it. The first time a
conversation names that person in full (or by an alias) and exactly one card carries the name, Stage 2 promotes the
mention on that alone (`entity_resolver`, :class:`WaitingIndex`); the page is born under the card's name, with its
sources and photo (:func:`seed_page`), and Sleep's tail matches the cards still waiting against any page born later
(:func:`rematch`). Never a one-part name, a name two cards or two pages share, a person known only by a relation
(`role_people`), or the person's own card: the app marks the "me" card (``is_me``) and it belongs to the owner's
page (G169), never to a namesake. The contact's thumbnail (≤ 64 KB, JPEG or PNG) is cached at `$CICADA_HOME/pictures/<bank>/contacts/<id>.<ext>`
— never in a bank (the logo rule, G59/G146) — and the page carries `contacts_photo: {sha, ext}` so the graph's ETag
moves; `photo_path(bank, entity_id, ext)` builds that one path, the rung C11's `entity_picture.resolve` reads with the
page's `ext` (R-SR9 as amended). No episode is written: nothing is hashed, so the scrub
rule (R-N3) has nothing to act on — and nothing text-shaped from a contact is stored to scrub.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from api.services import bank_index, fact_sources, markdown_parser, people_directory
from api.services.auth import cicada_home

CHANNEL_ID = "contacts-local"
LABEL = "Contacts"
REF_SCHEME = "addressbook://"
ADDED_BY = fact_sources.CICADA
FRONTMATTER_KEY = "contacts_photo"
#: The person's removals of this sync's entries — `(entity, ref, predicate)` rows it never re-adds (final review, 1).
REFUSED_FILE = "_contacts_rejected.yaml"
MAX_CONTACTS = 20000
PHOTO_CAP = 64 * 1024
#: R-SR9 — what a thumbnail may be (by its magic bytes), and the only exts `photo_path` answers for.
PHOTO_EXTS = ("jpg", "png")
ID_CAP = 200
#: A card's fact → the predicate its `sources:` entry serves, in this order (R-SR8).
FACT_PREDICATES = (
    ("has_organization", "works-at"),
    ("has_job_title", "role"),
    ("has_email", "email"),
    ("has_phone", "phone"),
    ("has_birthday", "birthday"),
)
SLEEP_REFUSAL = "Cicada is tidying up your memory right now — Contacts will sync again in a minute."


class Disconnected(ValueError):
    """A sync from a Contacts connection the person has since ended (review of #393): its request was sent before
    Disconnect and handled after the forget. Nothing is read from it and nothing is written."""


class PayloadError(ValueError):
    """A request the backend cannot trust — answered 422, nothing written."""


def photos_dir(bank: str) -> Path:
    """``$CICADA_HOME/pictures/<bank>/contacts/`` — machine-global, never inside a bank (R-SR9). The write side: it
    creates the folder, which `photo_path` never does."""
    path = cicada_home() / "pictures" / (bank or "default") / "contacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def photo_path(bank: str, entity_id: str, ext: str | None) -> Path | None:
    """R-SR9, amended 2026-09-24 (the phase-A contract with T-People) — THE path of a page's Contacts thumbnail,
    ``$CICADA_HOME/pictures/<bank>/contacts/<entity_id>.<ext>``. This module writes the bytes there; T-People's picture
    ladder reads them with the page's ``contacts_photo.ext`` — its ``entity_picture.contacts_path`` gives the same
    answers until it swaps to this one. ``ext`` is jpg or png, and None reads as jpg (what an ext-less mark means);
    any other ext, or an id that would leave the folder, is None. Pure: it never creates a folder — a read must not
    conjure one (``logo_service.meta_path``'s rule), and ``auth.cicada_home`` mkdirs, so the root is read from the
    environment here — and never checks that the file exists (``_cached`` asks that)."""
    ext = ext or "jpg"
    if ext not in PHOTO_EXTS:
        return None
    root = Path(os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")).expanduser()
    base = (root / "pictures" / (bank or "default") / "contacts").resolve()
    path = (base / f"{entity_id}.{ext}").resolve()
    return path if path.parent == base else None


def _cached(bank: str, entity_id: str) -> Path | None:
    """The thumbnail on disk for a page, whichever ext it was written with — the sync's own question."""
    for ext in PHOTO_EXTS:
        path = photo_path(bank, entity_id, ext)
        if path is not None and path.exists():
            return path
    return None


#: Both orders of a two-part name, folded like search; nothing for a one-part name (`people_directory.name_keys`).
name_keys = people_directory.name_keys


def _is_mine(source: dict) -> bool:
    return str(source.get("ref") or "").startswith(REF_SCHEME) and source.get("added_by") == ADDED_BY


def _photo(raw) -> tuple[bytes, str] | None:
    if not raw:
        return None
    try:
        data = base64.b64decode(str(raw), validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(data) > PHOTO_CAP:
        return None
    if data.startswith(b"\xff\xd8\xff"):
        return data, "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "png"
    return None


def _owner_ids(memory_path: Path) -> set[str]:
    """The owner's page: its ``owner: true`` flag, else ``resolve_observer``'s id (the ``linkedin_people`` rule)."""
    from api.services import owner_identity

    try:
        return {owner_identity.resolve_observer(memory_path)}
    except Exception:  # noqa: BLE001 - an unreadable owner.json names no page; the flag still applies
        return set()


def _index(memory_path: Path) -> tuple[dict[str, set[str]], set[str], str | None]:
    """Folded name and alias keys → person page ids, every page that already carries one of this sync's entries (so
    a contact that disappeared is cleaned up wherever its entries were), and the owner's page (G169)."""
    keys: dict[str, set[str]] = {}
    carrying: set[str] = set()
    flagged: list[str] = []
    persons: set[str] = set()
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if any(_is_mine(s) for s in fact_sources.as_sources(fm.get("sources"))) or fm.get(FRONTMATTER_KEY):
            carrying.add(f.stem)
        if fm.get("type") != "person" or fm.get("status") == "dropped":
            continue
        persons.add(f.stem)
        if fm.get("owner") is True:
            flagged.append(f.stem)
        for label in [fm.get("name") or f.stem.replace("-", " "), *(fm.get("aliases") or [])]:
            key = people_directory.fold(label)
            if key:
                keys.setdefault(key, set()).add(f.stem)
    by_id = sorted(_owner_ids(memory_path) & persons)
    owner = sorted(flagged)[0] if flagged else (by_id[0] if by_id else None)
    return keys, carrying, owner


def _remove_photo(bank: str, entity_id: str) -> None:
    for ext in PHOTO_EXTS:
        path = photo_path(bank, entity_id, ext)
        if path is not None:
            path.unlink(missing_ok=True)


def _rebuilt(current: list[dict], desired: dict[tuple, dict]) -> list[dict]:
    """The page's `sources:` with this sync's entries updated IN PLACE (round-4 final review, finding 1).

    The first slice rebuilt Cicada's entries from scratch and appended them after everyone else's, which (a) dropped
    the `accepted` / `access` / `only_me` the person set on one (`fact_sources._apply_persons_fields`), (b) moved
    Cicada's entries behind any source the person added later — one spurious "Contacts sync" commit per such source —
    and (c) shifted the indices the index-based `DELETE /entities/{id}/sources/{index}` removes by, so a card left
    open across a sync could delete the wrong row. So: every entry keeps its position; an owned one that is still
    wanted is `{**kept, <owned fields>}`, one that is not is dropped where it stood (and a duplicate of an owned key
    too), and only a new one is appended."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for source in current:
        if not _is_mine(source):
            out.append(source)
            continue
        key = (source.get("ref"), source.get("predicate"))
        if key in desired and key not in seen:
            out.append({**source, **desired[key]})
            seen.add(key)
    out.extend(entry for key, entry in desired.items() if key not in seen)
    return out


def load_refused(memory_path: Path) -> set[tuple[str, str, str]]:
    """Every `(entity id, addressbook ref, predicate)` the person removed from a page (round-4 final review, finding
    1). Without it the next sync — at the latest a day later, on every launch for a bank not named `default` — put a
    removed entry back under `Cicada-Author: user`, so a wrong name match could only be undone by disconnecting
    Contacts. The `_merge_rejected.yaml` precedent (G113): a small bank file, the person's ruling, versioned."""
    path = Path(memory_path) / REFUSED_FILE
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return set()
    rows = data.get("removed") if isinstance(data, dict) else None
    out: set[tuple[str, str, str]] = set()
    for row in rows or []:
        if isinstance(row, (list, tuple)) and len(row) == 3 and all(isinstance(x, str) for x in row):
            out.add((row[0], row[1], row[2]))
    return out


def remember_removal(memory_path: Path, entity_id: str, source: dict) -> str | None:
    """Record that the person removed one of this sync's entries, so `sync` never re-adds it. Returns the bank-relative
    path to commit with the removal, or None when the entry was not Contacts' own (a person's or an agent's source
    is theirs to remove and ours to forget)."""
    if not isinstance(source, dict) or not _is_mine(source):
        return None
    refused = load_refused(memory_path)
    refused.add((str(entity_id), str(source.get("ref")), str(source.get("predicate") or "")))
    path = Path(memory_path) / REFUSED_FILE
    path.write_text(yaml.safe_dump({"removed": [list(r) for r in sorted(refused)]}, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")
    return REFUSED_FILE


def _desired(eid: str, contact: dict, mine: dict, refused: set, today: str) -> dict[tuple, dict]:
    """The entries this card owns on page ``eid``: one per fact it holds, minus what the person removed."""
    ref = f"{REF_SCHEME}{str(contact['id']).strip()}"
    desired: dict[tuple, dict] = {}
    for fact, predicate in FACT_PREDICATES:
        if contact.get(fact) and (eid, ref, predicate) not in refused:
            kept = mine.get((ref, predicate))
            desired[(ref, predicate)] = {"ref": ref, "kind": fact_sources.KIND_APP, "predicate": predicate,
                                         "added_by": ADDED_BY, "added_at": (kept or {}).get("added_at") or today}
    return desired


def _apply_card(fm: dict, eid: str, contact: dict | None, photo: tuple[bytes, str] | None, *, bank: str,
                refused: set, today: str, counts: dict) -> None:
    """One page's frontmatter brought in line with its card (or with no card): this sync's sources reconciled in
    place, the thumbnail written to (or removed from) the picture cache and marked. Mutates ``fm``."""
    current = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    mine = {(s.get("ref"), s.get("predicate")): s for s in current if _is_mine(s)}
    desired = _desired(eid, contact, mine, refused, today) if contact is not None else {}
    counts["sources_added"] += len(set(desired) - set(mine))
    counts["sources_removed"] += len(set(mine) - set(desired))
    sources = _rebuilt(current, desired)
    if sources:
        fm["sources"] = sources
    else:
        fm.pop("sources", None)
    target = photo_path(bank, eid, photo[1]) if photo is not None else None
    if photo is not None and target is not None:
        data, ext = photo
        mark = {"sha": hashlib.sha256(data).hexdigest()[:12], "ext": ext}
        if fm.get(FRONTMATTER_KEY) != mark or not target.exists():
            _remove_photo(bank, eid)
            photos_dir(bank)   # the write side creates the folder; `photo_path` never does
            target.write_bytes(data)
        fm[FRONTMATTER_KEY] = mark
        counts["photos"] += 1
    elif fm.get(FRONTMATTER_KEY) or _cached(bank, eid) is not None:
        _remove_photo(bank, eid)
        fm.pop(FRONTMATTER_KEY, None)


def _write_page(memory_path: Path, eid: str, contact: dict | None, photo, *, bank: str, refused: set, today: str,
                counts: dict) -> bool:
    path = memory_path / "entities" / f"{eid}.md"
    if not path.exists():
        return False
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    _apply_card(fm, eid, contact, photo, bank=bank, refused=refused, today=today, counts=counts)
    if fm != parsed.frontmatter:
        markdown_parser.write(path, fm, parsed.body)
        return True
    return False


def _counts() -> dict:
    return {"sources_added": 0, "sources_removed": 0, "photos": 0}


def sync(memory_path: Path, payload: dict, *, bank: str | None = None) -> dict:
    """One whole address book (R-SR8). `payload` has snake_case keys. Returns the counts and the bank-relative
    paths to commit.

    Owner ruling 2026-10-20: a card that matches no page is kept waiting outside the bank (:func:`save_waiting`) —
    rewritten whole by every sync, so an edited or deleted card is gone from it at once — and the bank gets nothing
    for it. The person's own card (``is_me``) belongs to the owner's page (G169), never to a namesake, and never waits."""
    read_at = time.time_ns()   # a forget after this moment wins over this sync's waiting set (`forgotten_since`)
    if connection_ended(payload.get("connection")):
        raise Disconnected("Contacts was disconnected; this sync was sent before that and is dropped.")
    memory_path = Path(memory_path)
    bank = bank or memory_path.name
    contacts = [c for c in (payload.get("contacts") or []) if 0 < len(str(c.get("id") or "").strip()) <= ID_CAP]
    if len(contacts) > MAX_CONTACTS:
        raise PayloadError(f"at most {MAX_CONTACTS} contacts per sync")
    keys, carrying, owner = _index(memory_path)
    refused = load_refused(memory_path)
    me = any(c.get("is_me") for c in contacts)
    claims: dict[str, list[dict]] = {}
    unmatched = ambiguous = 0
    waiting: list[dict] = []
    for contact in contacts:
        if contact.get("is_me"):
            if owner:
                claims.setdefault(owner, []).append(contact)
            continue
        card_keys = name_keys(contact.get("given_name"), contact.get("family_name"))
        hits: set[str] = set()
        for key in card_keys:
            hits |= keys.get(key, set())
        if me and owner in hits:
            # The owner's page is the person's own card's alone (G169): a namesake card neither lands on it beside
            # theirs nor waits to seed a second page of the owner's name.
            ambiguous += 1
            continue
        if len(hits) == 1:
            claims.setdefault(next(iter(hits)), []).append(contact)
        elif hits:
            ambiguous += 1
        else:
            unmatched += 1
            if card_keys:   # a one-part name can never be matched to anybody: nothing of it is kept
                waiting.append(contact)
    matched = {eid: found[0] for eid, found in claims.items() if len(found) == 1}
    ambiguous += sum(len(found) for found in claims.values() if len(found) > 1)
    today = str(date.today())
    paths: list[str] = []
    counts = _counts()
    for eid in sorted(set(matched) | carrying):
        contact = matched.get(eid)
        photo = _photo(contact.get("photo_b64")) if contact is not None else None
        if _write_page(memory_path, eid, contact, photo, bank=bank, refused=refused, today=today, counts=counts):
            paths.append(f"entities/{eid}.md")
    kept = save_waiting(bank, waiting, read_at=read_at)
    return {"contacts": len(contacts), "matched": len(matched), "people": len(matched), "ambiguous": ambiguous,
            "unmatched": unmatched, "waiting": kept, **counts, "paths": paths}


# --------------------------------------------------------------------------- the waiting cards (outside every bank)

#: ``$CICADA_HOME/people/<bank>/contacts.json`` (`people_directory`) and the waiting thumbnails beside it.
WAITING_FILE = "contacts.json"
WAITING_PHOTOS = "contacts"
#: What a waiting card keeps — exactly what the app posted (R-SR8), its thumbnail as a file beside it.
_CARD_FIELDS = ("id", "given_name", "family_name", *(fact for fact, _ in FACT_PREDICATES))


def _card_key(card_id: str) -> str:
    """A waiting thumbnail's file name: the card id hashed, never the id itself in a path."""
    return hashlib.sha256(str(card_id).encode("utf-8")).hexdigest()[:16]


def _waiting_photos(bank: str) -> Path:
    return people_directory.path(bank, WAITING_PHOTOS)


#: The forget marker (review of #393): when the person last stopped Contacts, in nanoseconds — one file for every bank,
#: in ``$CICADA_HOME/people/``, outside every bank. A set read before it is a set the person took back.
FORGOTTEN_MARKER = ".contacts-forgotten"
#: The private key a loaded card carries: when its set was read (``load_waiting``), checked against the marker.
READ_AT = "_read_at"
#: A forget and a save of the waiting set never interleave (the backend is the directory's one writer).
_WAITING_LOCK = threading.Lock()
#: The app's Contacts connections the person ended (a random id minted at each Connect, sent with every sync and with
#: the forget): a sync still carrying one is dropped. The newest few are kept — an id is never reused.
ENDED_KEEP = 32
_CONNECTION_ID = re.compile(r"[A-Za-z0-9-]{8,64}")


def _marker_body() -> dict:
    try:
        body = json.loads(_marker().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def connection_ended(connection) -> bool:
    """Did the person end this Contacts connection (Disconnect, or access taken away)? ``None`` (an older app): no."""
    if not isinstance(connection, str) or not _CONNECTION_ID.fullmatch(connection):
        return False
    return connection in (_marker_body().get("ended") or [])


def _marker() -> Path:
    return people_directory.folder("x").parent / FORGOTTEN_MARKER


def forgotten_at() -> int:
    """When the person last stopped Contacts (ns), 0 if never."""
    try:
        return int(_marker_body().get("at") or 0)
    except (TypeError, ValueError):
        return 0


def forgotten_since(read_at) -> bool:
    """Was the waiting set taken back after ``read_at`` (a read's ``time.time_ns()``, or a card's ``READ_AT``)? Then
    whatever was read is treated as empty: never saved back, never matched, never seeded."""
    if read_at is None:
        return False
    try:
        return forgotten_at() > int(read_at)
    except (TypeError, ValueError):
        return True


def card_live(card: dict) -> bool:
    """A loaded card the person has not taken back since it was read."""
    return not forgotten_since(card.get(READ_AT))


def save_waiting(bank: str, contacts: list[dict], *, read_at: int | None = None) -> int:
    """Keep the cards that matched no page — the whole set, replacing the last one, so a card edited away or deleted
    in the address book leaves with the next sync, thumbnail included. Returns how many wait. A bank with nothing
    waiting keeps no file. With ``read_at`` (when the set being saved was read), a forget since then wins: nothing is
    saved and 0 is returned — a sync or a rematch that started before the person stopped Contacts never brings a card
    back."""
    with _WAITING_LOCK:
        if forgotten_since(read_at):
            return 0
        return _save_waiting(bank, contacts)


def _save_waiting(bank: str, contacts: list[dict]) -> int:
    rows: list[dict] = []
    photos: dict[str, bytes] = {}
    for contact in contacts:
        row = {k: contact[k] for k in _CARD_FIELDS if contact.get(k)}
        row["id"] = str(contact["id"]).strip()
        photo = _photo(contact.get("photo_b64"))
        if photo is not None:
            name = f"{_card_key(row['id'])}.{photo[1]}"
            row["photo"] = name
            photos[name] = photo[0]
        rows.append(row)
    folder = _waiting_photos(bank)
    if not rows:
        people_directory.path(bank, WAITING_FILE).unlink(missing_ok=True)
    else:
        for name, data in photos.items():
            target = folder / name
            try:
                if target.read_bytes() == data:
                    continue
            except OSError:
                pass
            people_directory.ensure(bank)
            people_directory.write_bytes(target, data)
        people_directory.save_json(bank, WAITING_FILE, {"v": 1, "synced_at": str(date.today()), "cards": rows})
    if folder.is_dir():
        for stale in folder.iterdir():
            if stale.is_file() and stale.name not in photos:
                stale.unlink(missing_ok=True)
    return len(rows)


def load_waiting(bank: str) -> list[dict]:
    """The waiting cards, each stamped with when they were read (``READ_AT``, taken before the read) so a later use asks
    :func:`card_live` — the forget removes the file first and stamps the marker after, so a read that saw the file
    always reads as taken back."""
    read_at = time.time_ns()
    rows = people_directory.load_json(bank, WAITING_FILE).get("cards")
    if not isinstance(rows, list):
        return []
    return [{**r, READ_AT: read_at} for r in rows if isinstance(r, dict) and str(r.get("id") or "").strip()]


def waiting_photo(bank: str, card: dict) -> tuple[bytes, str] | None:
    """A waiting card's thumbnail, read back and re-checked by its magic bytes (`_photo`'s rule)."""
    name = str(card.get("photo") or "")
    if not name or "/" in name or name.startswith("."):
        return None
    try:
        data = (_waiting_photos(bank) / name).read_bytes()
    except OSError:
        return None
    return _photo(base64.b64encode(data).decode("ascii"))


def forget_waiting(connection: str | None = None) -> int:
    """The person stopped Contacts (Disconnect, or access taken away in System Settings): every bank's waiting cards
    and their thumbnails are deleted — Contacts is connected app-wide, so its kept cards go app-wide too (review of
    #391). Returns how many cards were forgotten. What a sync already wrote on matched pages stays (git holds it; the
    person removes a source as ever). Never raises for a folder that is already gone.

    Accepted even while Sleep runs (review of #393): the files go at once, then the marker is stamped, both under the
    lock every save takes — so whatever Sleep read before it (Stage 2's index, Stage 5's seed, the tail's rematch and
    its save) is treated as empty (:func:`forgotten_since`), and nothing brings a card back."""
    root = people_directory.folder("x").parent
    forgotten = 0
    with _WAITING_LOCK:
        if root.is_dir():
            forgotten = _forget_files(root)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        ended = [c for c in (_marker_body().get("ended") or []) if isinstance(c, str)]
        if isinstance(connection, str) and _CONNECTION_ID.fullmatch(connection) and connection not in ended:
            ended = (ended + [connection])[-ENDED_KEEP:]
        marker = _marker()
        tmp = marker.with_name(f"{FORGOTTEN_MARKER}.tmp")
        tmp.write_text(json.dumps({"at": time.time_ns(), "ended": ended}), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, marker)
    return forgotten


def _forget_files(root: Path) -> int:
    forgotten = 0
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        forgotten += len(load_waiting(folder.name))
        (folder / WAITING_FILE).unlink(missing_ok=True)
        photos = folder / WAITING_PHOTOS
        if photos.is_dir() and not photos.is_symlink():
            for item in photos.iterdir():
                if item.is_file() or item.is_symlink():
                    item.unlink(missing_ok=True)
            try:
                photos.rmdir()
            except OSError:
                pass
    return forgotten


def waiting_status(bank: str) -> dict:
    """What the app may show: how many cards wait — never a name."""
    return {"waiting": len(load_waiting(bank))}


@dataclass
class WaitingIndex:
    """Folded name keys → the waiting cards that carry them — what Stage 2 asks on a first mention."""
    cards: dict[str, list[dict]] = field(default_factory=dict)

    def match(self, labels) -> dict | None:
        """The ONE waiting card a mention's labels (its name and aliases) name in full — a two-part name, either order,
        folded like search — or None: no card, two cards sharing the name, or a one-part label."""
        found: dict[str, dict] = {}
        for label in labels or []:
            key = people_directory.fold(label)
            if " " not in key:
                continue
            for card in self.cards.get(key, []):
                if card_live(card):   # a card the person took back since this index was read matches nothing
                    found[str(card["id"])] = card
        return next(iter(found.values())) if len(found) == 1 else None

    def by_id(self, card_id: str | None) -> dict | None:
        """The waiting card with this id — a chat participant's own card, found by the id the app posted beside the
        chat (`contact_identity`), never by a name. A one-part name never waits, so it is never here; nor the
        person's own card."""
        for cards in self.cards.values():
            for card in cards:
                if str(card.get("id")) == str(card_id or "") and card_live(card):
                    return card
        return None


def waiting_index(memory_path: Path, *, bank: str | None = None) -> WaitingIndex:
    """The waiting cards of this bank, keyed for :meth:`WaitingIndex.match`. Empty on a demo bank (a demo never takes
    in the person's real address book, R-CS16) and when nothing waits."""
    from api.services import demo_guard

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        return WaitingIndex()
    index = WaitingIndex()
    for card in load_waiting(bank or memory_path.name):
        for key in name_keys(card.get("given_name"), card.get("family_name")):
            index.cards.setdefault(key, []).append(card)
    return index


def card_name(card: dict) -> str:
    """The name a page born from a card carries: the card's own, given then family."""
    return " ".join(p for p in (str(card.get("given_name") or "").strip(), str(card.get("family_name") or "").strip())
                    if p)


def seed_page(memory_path: Path, frontmatter: dict, entity_id: str, card: dict, *, bank: str | None = None) -> None:
    """A page born from a card's first mention (Stage 5's create): the card's G61 sources and its thumbnail, exactly
    what a sync writes on a matched page. Mutates ``frontmatter``; the page is written by its caller. A card taken back
    since it was read seeds nothing."""
    if not card_live(card):
        return
    memory_path = Path(memory_path)
    bank = bank or memory_path.name
    _apply_card(frontmatter, entity_id, card, waiting_photo(bank, card), bank=bank,
                refused=load_refused(memory_path), today=str(date.today()), counts=_counts())


@dataclass
class Report:
    matched: int = 0
    paths: list[str] = field(default_factory=list)


def rematch(memory_path: Path, *, bank: str | None = None, skip: frozenset[str] = frozenset()) -> Report:
    """Sleep's tail (the ``linkedin_people.rematch`` pattern): the waiting cards against tonight's pages, so a person
    who got a page since the last sync — promoted on a card's first mention, or any other way — gains their card's
    sources and photo now, not at the next sync. A matched card leaves the waiting set. Pages in ``skip`` (dirty
    before the tail ran) are left alone and their cards keep waiting. Writes nothing on a demo bank."""
    from api.services import demo_guard

    memory_path = Path(memory_path)
    bank = bank or memory_path.name
    report = Report()
    if demo_guard.is_demo(memory_path):
        return report
    cards = load_waiting(bank)
    if not cards:
        return report
    read_at = cards[0][READ_AT]
    keys, _carrying, owner = _index(memory_path)
    # The owner's page takes only the person's own card, and only from a sync (G169): never a waiting namesake.
    keys = {k: ids - {owner} for k, ids in keys.items()} if owner else keys
    claims: dict[str, list[dict]] = {}
    for card in cards:
        hits: set[str] = set()
        for key in name_keys(card.get("given_name"), card.get("family_name")):
            hits |= keys.get(key, set())
        if len(hits) == 1:
            claims.setdefault(next(iter(hits)), []).append(card)
    refused = load_refused(memory_path)
    today = str(date.today())
    done: set[str] = set()
    for eid in sorted(claims):
        found = claims[eid]
        rel = f"entities/{eid}.md"
        if len(found) != 1 or rel in skip:
            continue
        card = found[0]
        if forgotten_since(read_at):
            break   # the person stopped Contacts mid-run: no further page takes a card, and the set is not saved back
        changed = _write_page(memory_path, eid, card, waiting_photo(bank, card), bank=bank, refused=refused,
                              today=today, counts=_counts())
        done.add(str(card["id"]))
        report.matched += 1
        if changed:
            report.paths.append(rel)
    if done:
        save_waiting(bank, [{**c, "photo_b64": _b64(waiting_photo(bank, c))} for c in cards
                            if str(c["id"]) not in done], read_at=read_at)   # the rest, thumbnails kept
    if report.paths:
        bank_index.invalidate(memory_path)
    return report


def _b64(photo: tuple[bytes, str] | None) -> str | None:
    return base64.b64encode(photo[0]).decode("ascii") if photo is not None else None


TRIGGER_REMATCH = "sleep/contacts"


def commit_message(report: Report, today: date) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Contacts {today.isoformat()}",
        [f"{p}: updated (source: n/a, trigger: {TRIGGER_REMATCH})" for p in report.paths], authors=[ADDED_BY])


def restore(memory_path: Path, report: Report) -> None:
    """Undo a tail run whose commit failed, so no later ``git add -A`` sweeps it under another author. The cards it
    matched stay out of the waiting set; the next sync puts them back if their page is gone."""
    from api.services import git_service

    memory_path = Path(memory_path)
    if report.paths and (memory_path / ".git").exists():
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", *report.paths)
        except git_service.GitError as exc:
            from loguru import logger

            logger.warning(f"Contacts rematch restore failed: {type(exc).__name__}")
    bank_index.invalidate(memory_path)
