"""Same name, different things: a short qualifier in parentheses, Wikipedia-style (G227, owner 2026-10-29).

The owner: one name is both a program in his life and a public IDE, "called the same. So how does cicada tackle this?
Maybe a (parenthesis) with which one we refer to might be useful?" When two or more pages share a title, each one is
shown as ``<name> (<qualifier>)`` — "<name-a> (program)" / "<name-a> (IDE)" — on every surface and through every
door. **Derived on read, never stored:** the page's title stays clean; nothing here writes a file.

**Which pages** (:func:`qualifiers`): every page that is not ``dropped`` (an archived page is still listed, linked and
read in history, where a bare title is the same ambiguity) whose title folds (``fold``: NFKC, case, spacing) to the
same text as another's. A page alone with its title has no qualifier, so a bank with no collision shows nothing new.

**What the qualifier says** — only what the record already holds, never a guess (:func:`derive`). Per page, in order:

1. what the page's own first sentence says it is — "<name> is an AI-powered IDE …" gives ``IDE``, "… is an
   accelerator program …" ``program`` (:func:`described_as`: the head noun of the words after "is a/an/the"). A
   saved link is never read this way (its description is the site's own blurb);
2. where a person works or studies, when a current claim on the page says so (``works-at``/``studies-at``…);
3. a saved link's site (``example.com``), then its site and first path segment (``example.com/docs``), from the
   URL Cicada saved — only a real domain (a dot in it), never an extension id or a machine name;
4. the page's type, said as a word (``tool``, ``company``, ``saved link`` …);
5. the type word and the month the page was first heard of (``tool, May 2025``; a saved link: the day it was
   saved, ``saved link, 12 Oct 2026``); and last, a number in the order the pages were made — only when everything
   above is the same.

Each page starts at the first rung it has; while two pages in a group would read the same, both step down a rung. A
rung that says the title back (``<name-a> (<name-a>)``) is skipped.

**Cache.** One map per bank, keyed by the ``entities/`` directory's own mtime (every bank write is a rename into it,
which moves it — the card ETag's rule, `page_blocks.card_etag`) and its entry count: one ``stat`` per call when
nothing changed. A rebuild reads frontmatter from `bank_index` (already warm on every list route) and the bodies of
the colliding pages only. Pure read; engine-free; never raises.
"""
from __future__ import annotations

import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loguru import logger

SHAPE = "same-name-1"

#: The type said as a word (the inbox's ``_NOUNS``, plus the kinds a person never needs spelled as a slug).
TYPE_WORDS = {
    "person": "person", "company": "company", "project": "project", "tool": "tool", "location": "place",
    "skill": "skill", "directory": "folder", "concept": "concept", "event": "event", "deadline": "deadline",
    "media": "saved link",
}
#: A current claim with one of these says where a person is; its object is that person's qualifier.
ORG_PREDICATES = ("works-at", "employed-by", "studies-at", "member-of", "affiliated-with")
MAX_QUALIFIER = 32

_JOINERS = frozenset({"and", "or", "&", "a", "an", "the", "plus"})
#: Heads that say nothing about which thing it is.
_VAGUE = frozenset({"thing", "one", "kind", "type", "part", "way", "lot", "number", "set", "name", "word", "term"})
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_IS_A = re.compile(r"^\s*(?:(?P<subject>[^.;:]{1,80}?)\s+)?(?:is|was|are)\s+(?:a|an|the)\s+(?P<rest>.+)$", re.I)
_STOP = re.compile(
    r"(?:[,.;:()\[\]—–]| - |(?<=\s)(?:that|which|who|whose|for|by|from|of|in|on|at|with|to|where|when|"
    r"like|than|as|since|until|built|made|run|known|written|held|grown|led|sold|given|shown|set)\b)", re.I)
#: A participle after the head noun ("a company headquartered in …", "a platform owned by …") ends the phrase.
_PARTICIPLE = re.compile(r"\w(?:ed|ing)$", re.I)
_WORD = re.compile(r"^[\w][\w+.#&'/]*$", re.UNICODE)


def fold(name) -> str:
    """The key two titles are "the same" under: NFKC, case-folded, one space between words."""
    text = unicodedata.normalize("NFKC", str(name or "")).casefold()
    return " ".join(text.split())


def display(name, qualifier: str | None) -> str:
    """``"<name> (<qualifier>)"``, or the name alone when there is no qualifier."""
    name = " ".join(str(name or "").split())
    return f"{name} ({qualifier})" if qualifier else name


@dataclass
class Page:
    id: str
    name: str
    type: str
    created: str = ""
    summary: str = ""
    org: str = ""
    site: str = ""
    path: str = ""


def _word(token: str) -> str:
    """A token as a qualifier shows it: an acronym or a mixed-case name kept, anything else lower-cased."""
    return token if sum(1 for c in token if c.isupper()) >= 2 or token.isupper() else token.lower()


def described_as(summary: str, name: str = "") -> str | None:
    """What the page's own first sentence says the thing is, as a short noun ("IDE", "accelerator program"), or None.

    Only a sentence shaped "<it or its name> is a/an/the <noun phrase> …": the phrase ends at a comma, a linking word
    or a participle after its head ("a company headquartered in …"), and its last word — the head noun — is the
    answer ("an AI-powered IDE" → "IDE", "an accelerator program" → "program"). Anything else — a sentence of another
    shape, a phrase longer than five words, a head that is not a word or says nothing ("a kind") — is None, never a
    guess."""
    first = re.split(r"(?<=[.!?])\s", " ".join(str(summary or "").split()), maxsplit=1)[0]
    first = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", first).replace("**", "").replace("*", "")
    m = _IS_A.match(first)
    if not m:
        return None
    subject = fold(m.group("subject") or "")
    if subject and subject not in ("it", "this", "this is", fold(name)) and not subject.startswith(fold(name)):
        return None
    rest = m.group("rest")
    stop = _STOP.search(rest)
    words = (rest[: stop.start()] if stop else rest).split()
    for i, w in enumerate(words[1:], start=1):
        if _PARTICIPLE.search(w):
            words = words[:i]
            break
    while words and words[-1].lower() in _JOINERS:
        words = words[:-1]
    if not words or len(words) > 5 or words[-1].endswith("-") or not _WORD.match(words[-1]):
        return None
    out = _word(words[-1])
    if fold(out) == fold(name) or len(out) > MAX_QUALIFIER or out.lower() in _VAGUE:
        return None
    return out


def _month(day: str) -> str | None:
    try:
        d = date.fromisoformat(str(day or "")[:10])
    except ValueError:
        return None
    return f"{_MONTHS[d.month - 1]} {d.year}"


def _day(day: str) -> str | None:
    try:
        d = date.fromisoformat(str(day or "")[:10])
    except ValueError:
        return None
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _rungs(page: Page) -> list[str]:
    word = TYPE_WORDS.get(page.type, page.type or "page")
    rungs: list[str] = []
    if page.type != "media":
        if said := described_as(page.summary, page.name):
            rungs.append(said)
    if page.org:
        rungs.append(page.org[:MAX_QUALIFIER])
    if page.site:
        rungs.append(page.site[:MAX_QUALIFIER])
        if page.path:
            rungs.append(f"{page.site}/{page.path}"[:MAX_QUALIFIER])
    rungs.append(word)
    if page.type == "media" and (day := _day(page.created)):
        rungs.append(f"{word}, {day}")
    elif month := _month(page.created):
        rungs.append(f"{word}, {month}")
    return [r for r in dict.fromkeys(rungs) if fold(r) != fold(page.name)]


def derive(pages: list[Page]) -> dict[str, str]:
    """``{page id: qualifier}`` for ONE group of pages sharing a title — every qualifier distinct (pure)."""
    rungs = {p.id: _rungs(p) or [TYPE_WORDS.get(p.type, "page")] for p in pages}
    level = {p.id: 0 for p in pages}

    def at(pid: str) -> str:
        return rungs[pid][min(level[pid], len(rungs[pid]) - 1)]

    for _ in range(8):
        seen: dict[str, list[str]] = {}
        for p in pages:
            seen.setdefault(fold(at(p.id)), []).append(p.id)
        clashing = [ids for ids in seen.values() if len(ids) > 1]
        moved = False
        for ids in clashing:
            for pid in ids:
                if level[pid] + 1 < len(rungs[pid]):
                    level[pid] += 1
                    moved = True
        if not clashing or not moved:
            break
    out = {p.id: at(p.id) for p in pages}
    # Everything the record holds reads the same: number them in the order they were made (created, then id).
    by_text: dict[str, list[Page]] = {}
    for p in pages:
        by_text.setdefault(fold(out[p.id]), []).append(p)
    for same in by_text.values():
        if len(same) > 1:
            for n, p in enumerate(sorted(same, key=lambda p: (p.created or "", p.id)), start=1):
                out[p.id] = f"{out[p.id]}, {n}"
    return out


# --------------------------------------------------------------------------- the bank's map, cached

_lock = threading.Lock()
#: bank path -> ((entities mtime_ns, entry count), {page id: qualifier}, {fold(title): [page ids]})
_CACHE: dict[str, tuple[tuple[int, int], dict[str, str], dict[str, list[str]]]] = {}
builds = 0


def _stamp(memory_path: Path) -> tuple[int, int] | None:
    directory = Path(memory_path) / "entities"
    try:
        st = os.stat(directory)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_nlink


def _org_of(body: str) -> str:
    from api.services.claims import parse_claims

    try:
        claims = parse_claims(body)
    except Exception:  # noqa: BLE001 — a hand-broken fence says nothing
        return ""
    return _org_in(claims)


def _org_in(claims) -> str:
    from api.services.claims import is_current, is_event

    for claim in claims or ():
        if claim.predicate in ORG_PREDICATES and claim.object and is_current(claim) and not is_event(claim):
            text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", str(claim.object))
            return " ".join(text.split())
    return ""


def _site_and_path(fm: dict) -> tuple[str, str]:
    """A saved link's site and the first segment of its path — a real domain only (a dot in it)."""
    from urllib.parse import urlsplit

    from api.services import reading_hosts

    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    url = str(media.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return "", ""
    try:
        site = reading_hosts.site_of(url) or ""
        segment = next((s for s in urlsplit(url).path.split("/") if s), "")
    except Exception:  # noqa: BLE001 — a malformed URL has no site
        return "", ""
    if "." not in site or not reading_hosts.valid_site_key(site):
        return "", ""
    return site, segment[:24]


def _build(memory_path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """The titles from `search_index.entity_names` (one listing; a page is parsed only when it moved since the
    full-text index or this process read it — a cold recall must not parse the bank), then the frontmatter and body
    of the colliding pages only."""
    global builds
    from api.services import bank_index, graph_builder, search_index

    builds += 1
    stems_by_title: dict[str, list[str]] = {}
    for stem, name in search_index.entity_names(memory_path).items():
        key = fold(name or stem.replace("-", " "))
        if key:
            stems_by_title.setdefault(key, []).append(stem)
    qualifiers: dict[str, str] = {}
    titles: dict[str, list[str]] = {}
    for key, stems in stems_by_title.items():
        if len(stems) < 2:
            continue
        group = [f for f in (bank_index.file(memory_path, "entities", f"{s}.md") for s in stems)
                 if f is not None and str((f.frontmatter or {}).get("status") or "") != "dropped"]
        if len(group) < 2:
            continue
        titles[key] = sorted(f.stem for f in group)
        pages: list[Page] = []
        for f in group:
            fm = f.frontmatter or {}
            try:
                body = f.body()
            except Exception:  # noqa: BLE001 — unreadable: the type word still tells it apart
                body = ""
            kind = _kind(fm)
            pages.append(_page(f.stem, fm, (graph_builder.summarize(body) or "") if kind != "media" else "",
                               lambda body=body: _org_of(body)))
        qualifiers.update(derive(pages))
    return qualifiers, titles


def _kind(fm: dict) -> str:
    return str(fm.get("type") or "concept").strip().lower()


def _page(stem: str, fm: dict, summary: str, org) -> Page:
    """One colliding page as `derive` reads it; ``org`` is called only for a person (it may parse claims)."""
    kind = _kind(fm)
    site, path = _site_and_path(fm) if kind == "media" else ("", "")
    return Page(id=stem, name=str(fm.get("name") or stem), type=kind,
                created=str((fm.get("saved_at") if kind == "media" else None) or fm.get("learned_on")
                            or fm.get("created") or ""),
                summary=summary if kind != "media" else "", org=org() if kind == "person" else "",
                site=site, path=path)


def prime(memory_path, rows, stamp: tuple[int, int] | None) -> dict[str, str]:
    """Build the map from pages a caller has ALREADY read — ``rows`` of ``(stem, frontmatter, summary, claims)`` for
    every page — and keep it under ``stamp`` (the `entities/` stamp the caller took BEFORE reading, :func:`stamp_of`),
    so `graph_builder`'s full build does not list and read the pages a second time. A stamp that moved while the
    caller read is simply stale: the next call rebuilds. Returns the qualifiers."""
    global builds
    builds += 1
    by_title: dict[str, list] = {}
    for row in rows:
        stem, fm = row[0], row[1] or {}
        if str(fm.get("status") or "") == "dropped":
            continue
        if key := fold(fm.get("name") or stem.replace("-", " ")):
            by_title.setdefault(key, []).append(row)
    qualifiers: dict[str, str] = {}
    titles: dict[str, list[str]] = {}
    for key, group in by_title.items():
        if len(group) < 2:
            continue
        titles[key] = sorted(r[0] for r in group)
        qualifiers.update(derive([_page(r[0], r[1] or {}, r[2] or "", lambda r=r: _org_in(r[3])) for r in group]))
    if stamp is not None and memory_path is not None:
        with _lock:
            _CACHE[str(Path(memory_path))] = (stamp, qualifiers, titles)
    return qualifiers


def stamp_of(memory_path) -> tuple[int, int] | None:
    """The `entities/` stamp :func:`prime` keys on — taken before the caller reads the pages."""
    return _stamp(Path(memory_path)) if memory_path is not None else None


def _current(memory_path) -> tuple[dict[str, str], dict[str, list[str]]]:
    if memory_path is None:
        return {}, {}
    memory_path = Path(memory_path)
    stamp = _stamp(memory_path)
    if stamp is None:
        return {}, {}
    key = str(memory_path)
    with _lock:
        hit = _CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1], hit[2]
    try:
        qualifiers, titles = _build(memory_path)
    except Exception as exc:  # noqa: BLE001 — never an error: a bare title is today's answer
        logger.warning(f"same_name: map unavailable ({type(exc).__name__})")
        return {}, {}
    with _lock:
        _CACHE[key] = (stamp, qualifiers, titles)
    return qualifiers, titles


def qualifiers(memory_path) -> dict[str, str]:
    """``{page id: qualifier}`` for every page that shares its title with another (empty when none do)."""
    return _current(memory_path)[0]


def qualifier(memory_path, page_id) -> str | None:
    """The page's qualifier, or None when its title is its own."""
    return qualifiers(memory_path).get(str(page_id or ""))


def label(memory_path, page_id, name) -> str:
    """The name to show for a page: ``"<name> (<qualifier>)"`` when its title is shared, else the name."""
    return display(name, qualifier(memory_path, page_id))


def pages_titled(memory_path, title) -> list[str]:
    """Every page id (not dropped) whose title folds to ``title`` — two or more, or empty when the title is one page's
    (or none's)."""
    return list(_current(memory_path)[1].get(fold(title), ()))


def fields(memory_path, page_id, name) -> dict:
    """The additive wire fields for one page: ``qualifier`` (None when the title is its own) and ``displayName``."""
    q = qualifier(memory_path, page_id)
    return {"qualifier": q, "displayName": display(name, q)}


def invalidate(memory_path=None) -> None:
    with _lock:
        if memory_path is None:
            _CACHE.clear()
        else:
            _CACHE.pop(str(Path(memory_path)), None)
