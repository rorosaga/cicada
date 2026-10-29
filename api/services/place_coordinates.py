"""A place's coordinates, stored once and drawn from the record (ruling 48 part 6; vision item 5 part B, 2026-10-29).

The owner, 2026-10-28: "if we can use the cool looking macos maps that'd be nice". The card draws native MapKit from
coordinates the page stores (``lat``/``lon`` at the frontmatter's top level — the keys ``page_blocks.coordinates``
already serves). Before this, the app geocoded the page's NAME through Apple on every open of a place page.

Who resolves a place, and when — **the backend never geocodes**:

* The Mac's own geocoder (``CLGeocoder`` / ``MKLocalSearch``) runs **in the app**, on the person's first open of a
  place page with no coordinates (or the app's small background pass over :func:`unplaced`), and the app posts the
  result here (:func:`store`). After that, no open of the page sends anything anywhere.
* Apple's forward geocoder is a network request to Apple's service — not on-device. Apple's own terms say the request
  is not tied to an Apple Account, but the place's name still leaves the Mac. So :func:`geocode_verdict` decides,
  with nothing sent, whether a place may be resolved without asking: only a **public place** on ruling 44's local
  test (``web_context.local_verdict`` — never the owner, a project, a name carrying a person's name or the person's
  own thing), whose name is neither **address-shaped** (a number and a street word) nor a **home word** (home, house,
  flat, apartment…). Anything else is private: the app shows a placeholder with *Place on the map* and resolves it
  only on that click (``by="person"``). A private place is never resolved automatically, and :func:`store` refuses an
  automatic result for one.
* The person can take a pin back (``DELETE``): the page then says ``coordinates_by: none`` and nothing resolves it
  again automatically. When the Mac's geocoder finds nothing, the app records ``coordinates_by: unfound`` (review of
  #521) — upkeep, authored ``cicada``, never the person's act — and nothing retries it on its own either; the person's
  click still may.

Nearby places (:func:`nearby`) are every other place on the record within :data:`NEARBY_KM`, from one index of the
pages' frontmatter (``bank_index``'s stat cache) — read when the map draws, never when the card opens.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from api.services import bank_index, page_blocks

#: Stored once per place; ``none`` means "do not resolve automatically" (no match, or the person took the pin back).
#: ``none`` is the person taking a pin back (only ``DELETE`` writes it); ``unfound`` is the geocoder finding nothing.
BY_VALUES = ("geocoder", "person", "unfound", "none")
#: What a ``PUT`` may say: everything but ``none``, which is the person's own act and has its own route.
PUT_VALUES = ("geocoder", "person", "unfound")
#: Values that stop every automatic resolve, and the reason ``state`` gives for each.
_STOPPED = {"none": "taken_back", "unfound": "not_found"}
NEARBY_KM = 5.0
MAX_NEARBY = 8
MAX_UNPLACED = 20
#: A home or a dwelling: never resolved without the person's click, whatever its name's shape.
_HOME = re.compile(r"\b(?:home|house|flat|apartment|apartments?|apartamentos?|piso|casa|residence|residencia|dorm|"
                   r"dormitory|room|bedroom|garage|garden|cabin|cottage|villa|chalet|my|our|mi|nuestra|nuestro)\b",
                   re.IGNORECASE)
#: A street address: a number next to a street word, or a postcode-shaped token next to one.
_STREET = re.compile(r"\b(?:street|st|road|rd|avenue|ave|av|avda|lane|ln|drive|dr|boulevard|blvd|way|court|ct|"
                     r"place|pl|square|sq|calle|c/|rua|via|viale|plaza|paseo|camino|carrer|rue|strasse|straße|"
                     r"weg|platz|piazza|travessa|largo|n[º°o]\.?)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d{1,5}[a-z]?\b", re.IGNORECASE)
_WITHIN = re.compile(r"(?:^|[-_ ])(?:located[-_ ]in|in|within|part[-_ ]of|city|country|region)$", re.IGNORECASE)


@dataclass
class Verdict:
    allowed: bool          # may be resolved without the person's click
    reason: str            # public_place | type | address | home | <web_context's private reasons>


def address_shaped(name: str) -> bool:
    text = str(name or "")
    return bool(_NUMBER.search(text) and _STREET.search(text))


def geocode_verdict(memory_path: Path, entity_id: str, *, facts=None) -> Verdict:
    """Whether the app may resolve this place without asking — nothing is sent to decide it."""
    from api.services import web_context, web_settle

    page = web_context.load_page(Path(memory_path), entity_id)
    if page is None or page.type != "location":
        return Verdict(False, "type")
    if address_shaped(page.name):
        return Verdict(False, "address")
    if _HOME.search(page.name):
        return Verdict(False, "home")
    local = web_context.local_verdict(Path(memory_path), page, facts or web_settle.bank_facts(Path(memory_path)))
    if local.public is not True:
        return Verdict(False, local.reason)
    return Verdict(True, "public_place")


def query_for(memory_path: Path, entity_id: str, fm: dict, claims: list, *, facts=None) -> str:
    """What the app asks the geocoder: the page's name, and the name of the place the record says it is in ("Example
    Park" → "Example Park, Example City"), when one relation says so — only when that containing place passes the
    same test (:func:`geocode_verdict`) as the page itself (review of #521): a public cafe "in" a private farm named for
    a family sends the cafe's name alone, never the farm's."""
    name = " ".join(str(fm.get("name") or entity_id).split())
    for c in claims or []:
        if getattr(c, "object_kind", None) != "node" or not _WITHIN.search(str(c.predicate or "")):
            continue
        entry = bank_index.file(Path(memory_path), "entities", f"{c.object}.md")
        other = (entry.frontmatter or {}) if entry is not None else {}
        if str(other.get("type") or "").lower() == "location" and other.get("name"):
            within = " ".join(str(other["name"]).split())
            if within.lower() not in name.lower() and geocode_verdict(memory_path, str(c.object), facts=facts).allowed:
                return f"{name}, {within}"
    return name


# ---- nearby --------------------------------------------------------------------------------------------------------


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def placed(memory_path: Path) -> list[dict]:
    """Every page that stores coordinates: ``{id, name, lat, lon}`` — from the frontmatter cache, no page parse."""
    out = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("status") or "") in ("archived", "dropped"):
            continue
        c = page_blocks.coordinates(fm, str(fm.get("name") or f.stem))
        if c is not None:
            out.append({"id": f.stem, "name": c["label"], "lat": c["lat"], "lon": c["lon"]})
    return out


def nearby(memory_path: Path, entity_id: str, lat: float, lon: float) -> list[dict]:
    """The places on the record within :data:`NEARBY_KM` of a point, nearest first, at most :data:`MAX_NEARBY`."""
    rows = []
    for p in placed(memory_path):
        if p["id"] == entity_id:
            continue
        km = _km(lat, lon, p["lat"], p["lon"])
        if km <= NEARBY_KM:
            rows.append({**p, "km": round(km, 2)})
    rows.sort(key=lambda r: (r["km"], r["id"]))
    return rows[:MAX_NEARBY]


# ---- what the map reads --------------------------------------------------------------------------------------------


def state(memory_path: Path, entity_id: str) -> dict | None:
    """``GET /entities/{id}/place``: the stored coordinates and the places near them, or — when none are stored —
    whether the app may resolve it without asking and what it would ask. ``None`` for a page that is not there."""
    from api.services import markdown_parser
    from api.services.claims import parse_claims

    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not path.is_file():
        return None
    parsed = markdown_parser.parse(path, ledger=False)
    fm = parsed.frontmatter
    name = str(fm.get("name") or entity_id)
    coords = page_blocks.coordinates(fm, name)
    by = str(fm.get("coordinates_by") or "")
    out: dict = {"entityId": entity_id, "type": str(fm.get("type") or ""), "coordinates": coords,
                 "by": by or None, "at": str(fm.get("coordinates_at") or "") or None, "nearby": [], "geocode": None}
    if coords is not None:
        out["nearby"] = nearby(memory_path, entity_id, coords["lat"], coords["lon"])
        return out
    if str(fm.get("type") or "").lower() != "location":
        return out
    verdict = geocode_verdict(memory_path, entity_id)
    try:
        claims = parse_claims(parsed.body or "")
    except Exception:  # noqa: BLE001 — an unreadable fence is no relation
        claims = []
    out["geocode"] = {"allowed": verdict.allowed and by not in _STOPPED, "reason": _STOPPED.get(by, verdict.reason),
                      "query": query_for(memory_path, entity_id, fm, claims)}
    return out


def unplaced(memory_path: Path, *, limit: int = MAX_UNPLACED) -> list[dict]:
    """Place pages the app may resolve on its own (the background pass): no coordinates, never taken back, public on
    :func:`geocode_verdict`. Most recently mentioned first, at most ``limit``."""
    from api.services import markdown_parser, web_settle
    from api.services.claims import parse_claims

    mp = Path(memory_path)
    todo = []
    for f in bank_index.files(mp, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "").lower() != "location" or fm.get("coordinates_by"):
            continue
        if str(fm.get("status") or "") in ("archived", "dropped") or page_blocks.coordinates(fm) is not None:
            continue
        todo.append((str(fm.get("last_referenced") or ""), f.stem, fm))
    todo.sort(key=lambda t: (t[0], t[1]), reverse=True)
    facts = web_settle.bank_facts(mp) if todo else None
    out = []
    for _, entity_id, fm in todo:
        if len(out) >= limit:
            break
        if not geocode_verdict(mp, entity_id, facts=facts).allowed:
            continue
        try:
            claims = parse_claims(markdown_parser.parse(mp / "entities" / f"{entity_id}.md", ledger=False).body or "")
        except Exception:  # noqa: BLE001
            claims = []
        out.append({"entityId": entity_id, "name": str(fm.get("name") or entity_id),
                    "query": query_for(mp, entity_id, fm, claims, facts=facts)})
    return out


# ---- writes (the app posts; the backend never geocodes) ------------------------------------------------------------


class Refused(ValueError):
    """A write this rail refuses, with the sentence the person reads."""


def fields(lat: float | None, lon: float | None, by: str, today: date | None = None) -> dict:
    """The frontmatter keys one write sets. ``none`` / ``unfound`` clear the coordinates and stop automatic
    resolving."""
    today = today or date.today()
    if by not in BY_VALUES:
        raise Refused(f"by must be one of {', '.join(BY_VALUES)}")
    if by in _STOPPED:
        return {"lat": None, "lon": None, "coordinates_by": by, "coordinates_at": today.isoformat()}
    la = page_blocks._coordinate(lat, 90.0)
    lo = page_blocks._coordinate(lon, 180.0)
    if la is None or lo is None:
        raise Refused("lat must be within ±90 and lon within ±180")
    return {"lat": round(la, 6), "lon": round(lo, 6), "coordinates_by": by, "coordinates_at": today.isoformat()}


def apply(fm: dict, values: dict) -> None:
    """Set ``values`` on a page's frontmatter; a ``None`` removes the key (and its long-form twin)."""
    for key, value in values.items():
        if value is None:
            fm.pop(key, None)
            fm.pop({"lat": "latitude", "lon": "longitude"}.get(key, ""), None)
        else:
            fm[key] = value
    if values.get("lat") is not None:
        fm.pop("latitude", None)
        fm.pop("longitude", None)


def check(memory_path: Path, entity_id: str, by: str) -> None:
    """Refuse what the rail forbids before anything is written: coordinates on a page that is not a place, and an
    automatic result for a private place (the person's own click, ``by="person"``, is always theirs to make)."""
    from api.services import markdown_parser

    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    fm = markdown_parser.parse(path, ledger=False).frontmatter
    if str(fm.get("type") or "").lower() != "location":
        raise Refused("Only a place page stores coordinates.")
    if by in ("geocoder", "unfound"):   # the app's own, automatic results
        if str(fm.get("coordinates_by") or "") == "none":
            raise Refused("You took this place off the map; it is placed again only when you ask.")
        if not geocode_verdict(memory_path, entity_id).allowed:
            raise Refused("This looks like a private place; it is placed on the map only when you ask.")
