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
keeps and removes those, and never touches one the person or an agent added. Unmatched contacts are counted, never
stored. The contact's thumbnail (≤ 64 KB, JPEG or PNG) is cached at `$CICADA_HOME/pictures/<bank>/contacts/<id>.<ext>`
— never in a bank (the logo rule, G59/G146) — and the page carries `contacts_photo: {sha, ext}` so the graph's ETag
moves; `photo_path(bank, entity_id, ext)` builds that one path, the rung C11's `entity_picture.resolve` reads with the
page's `ext` (R-SR9 as amended). No episode is written: nothing is hashed, so the scrub
rule (R-N3) has nothing to act on — and nothing text-shaped from a contact is stored to scrub.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from datetime import date
from pathlib import Path

from api.services import bank_index, fact_sources, markdown_parser, text_fold
from api.services.auth import cicada_home

CHANNEL_ID = "contacts-local"
LABEL = "Contacts"
REF_SCHEME = "addressbook://"
ADDED_BY = fact_sources.CICADA
FRONTMATTER_KEY = "contacts_photo"
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


def name_keys(given, family) -> set[str]:
    """Both orders of a two-part name, folded like search (`text_fold.words`); nothing for a one-part name."""
    first = " ".join(text_fold.words(given))
    last = " ".join(text_fold.words(family))
    if not first or not last:
        return set()
    return {f"{first} {last}", f"{last} {first}"}


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


def _index(memory_path: Path) -> tuple[dict[str, set[str]], set[str]]:
    """Folded name and alias keys → person page ids, and every page that already carries one of this sync's
    entries (so a contact that disappeared is cleaned up wherever its entries were)."""
    keys: dict[str, set[str]] = {}
    carrying: set[str] = set()
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if any(_is_mine(s) for s in fact_sources.as_sources(fm.get("sources"))) or fm.get(FRONTMATTER_KEY):
            carrying.add(f.stem)
        if fm.get("type") != "person" or fm.get("status") == "dropped":
            continue
        for label in [fm.get("name") or f.stem.replace("-", " "), *(fm.get("aliases") or [])]:
            key = " ".join(text_fold.words(str(label)))
            if key:
                keys.setdefault(key, set()).add(f.stem)
    return keys, carrying


def _remove_photo(bank: str, entity_id: str) -> None:
    for ext in PHOTO_EXTS:
        path = photo_path(bank, entity_id, ext)
        if path is not None:
            path.unlink(missing_ok=True)


def sync(memory_path: Path, payload: dict, *, bank: str | None = None) -> dict:
    """One whole address book (R-SR8). `payload` has snake_case keys. Returns the counts and the bank-relative
    paths to commit."""
    memory_path = Path(memory_path)
    bank = bank or memory_path.name
    contacts = [c for c in (payload.get("contacts") or []) if 0 < len(str(c.get("id") or "").strip()) <= ID_CAP]
    if len(contacts) > MAX_CONTACTS:
        raise PayloadError(f"at most {MAX_CONTACTS} contacts per sync")
    keys, carrying = _index(memory_path)
    claims: dict[str, list[dict]] = {}
    unmatched = ambiguous = 0
    for contact in contacts:
        hits: set[str] = set()
        for key in name_keys(contact.get("given_name"), contact.get("family_name")):
            hits |= keys.get(key, set())
        if len(hits) == 1:
            claims.setdefault(next(iter(hits)), []).append(contact)
        elif hits:
            ambiguous += 1
        else:
            unmatched += 1
    matched = {eid: found[0] for eid, found in claims.items() if len(found) == 1}
    ambiguous += sum(len(found) for found in claims.values() if len(found) > 1)
    today = str(date.today())
    paths: list[str] = []
    added = removed = photos = 0
    for eid in sorted(set(matched) | carrying):
        path = memory_path / "entities" / f"{eid}.md"
        if not path.exists():
            continue
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        current = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
        mine = {(s.get("ref"), s.get("predicate")): s for s in current if _is_mine(s)}
        others = [s for s in current if not _is_mine(s)]
        contact = matched.get(eid)
        desired: list[dict] = []
        if contact is not None:
            ref = f"{REF_SCHEME}{str(contact['id']).strip()}"
            for fact, predicate in FACT_PREDICATES:
                if contact.get(fact):
                    kept = mine.get((ref, predicate))
                    desired.append({"ref": ref, "kind": fact_sources.KIND_APP, "predicate": predicate,
                                    "added_by": ADDED_BY, "added_at": (kept or {}).get("added_at") or today})
        wanted = {(s["ref"], s["predicate"]) for s in desired}
        added += len(wanted - set(mine))
        removed += len(set(mine) - wanted)
        sources = others + desired
        if sources:
            fm["sources"] = sources
        else:
            fm.pop("sources", None)
        photo = _photo(contact.get("photo_b64")) if contact is not None else None
        target = photo_path(bank, eid, photo[1]) if photo is not None else None
        if photo is not None and target is not None:
            data, ext = photo
            mark = {"sha": hashlib.sha256(data).hexdigest()[:12], "ext": ext}
            if fm.get(FRONTMATTER_KEY) != mark or not target.exists():
                _remove_photo(bank, eid)
                photos_dir(bank)   # the write side creates the folder; `photo_path` never does
                target.write_bytes(data)
            fm[FRONTMATTER_KEY] = mark
            photos += 1
        elif fm.get(FRONTMATTER_KEY) or _cached(bank, eid) is not None:
            _remove_photo(bank, eid)
            fm.pop(FRONTMATTER_KEY, None)
        if fm != parsed.frontmatter:
            markdown_parser.write(path, fm, parsed.body)
            paths.append(f"entities/{eid}.md")
    return {"contacts": len(contacts), "matched": len(matched), "people": len(matched), "ambiguous": ambiguous,
            "unmatched": unmatched, "sources_added": added, "sources_removed": removed, "photos": photos,
            "paths": paths}
