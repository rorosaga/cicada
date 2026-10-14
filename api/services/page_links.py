"""A page's link facts (owner rulings 2026-10-14): everything a link card in the article draws, per URL in its prose.

The app parses no URL for meaning and fetches nothing: the title, the site, the description, the read and save dates,
the stored picture and the saved look all come from here. Every fact is one Cicada already holds —

* the **saved page** for the URL (a ``media`` page, matched through ``url_index.json`` by ``media_ingestor.url_hash``,
  the one normaliser): its name, ``## Description`` (else ``## Summary``), ``saved_at`` (the person's own save date,
  else when Cicada took it in), ``read_at`` (stamped by ``link_enrichment`` when it read the page's words, else the
  person's agent's ``read.at``) and its stored picture (``entity_picture.media_picture``, never a provider URL);
* the **looks** (G196) saved of the same URL, newest first, each with its day, its screenshot's API path and palette;
* ``captures`` — dated screenshots from the site-exploration pipeline. Empty until that lands; the app falls back to
  a look's screenshot and says "No capture of this page yet" otherwise.

A URL Cicada never read carries only its site (owner ruling 3: drawing a page is not a click, so nothing here
fetches). ``icon`` says whether ``/entities/{id}/sources/icon/{site}`` serves the site's mark for this page
(:func:`linked_sites`). Pure read; engine-free.
"""
from __future__ import annotations

from pathlib import Path

from api.services import design_refs, entity_body, entity_picture, link_views, markdown_parser, reading_hosts
from api.services.claims import served_prose

SHAPE = "page-links-1"
#: Distinct URLs served per page; an owner-sized page links far fewer.
MAX_LINKS = 200
#: Looks served per URL.
MAX_LOOKS = 12
_DESC_CHARS = 400


def prose_links(body: str) -> list[link_views.LinkRef]:
    """Every link in the page's served prose (claims fences out), outside code fences, in order."""
    out: list[link_views.LinkRef] = []
    fence = None
    for line in served_prose(body or "")[0].splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mark = stripped[:3]
            fence = None if fence == mark else (fence or mark)
            continue
        if fence is None and "http" in line:
            out.extend(link_views.links_in(line))
    return out


def _site(url: str) -> str | None:
    try:
        return reading_hosts.site_of(url) or None
    except Exception:  # noqa: BLE001 — a malformed URL has no site
        return None


def _saved_page(memory_path: Path, index: dict, url: str) -> tuple[str, dict, str] | None:
    """``(page_id, frontmatter, body)`` of the saved ``media`` page for ``url``, or None."""
    from api.services import media_ingestor

    entry = index.get(media_ingestor.url_hash(url))
    if not isinstance(entry, dict):
        return None
    if entry.get("alias_of") and isinstance(index.get(entry["alias_of"]), dict):
        entry = index[entry["alias_of"]]
    page_id = str(entry.get("media_entity_id") or "").strip()
    if not page_id or "/" in page_id or page_id.startswith("."):
        return None
    path = Path(memory_path) / "entities" / f"{page_id}.md"
    if not path.is_file():
        return None
    try:
        parsed = markdown_parser.parse(path, ledger=False)
    except Exception:  # noqa: BLE001 — a hand-broken page is a page we know nothing about
        return None
    if str(parsed.frontmatter.get("type") or "").strip().lower() != "media":
        return None
    return page_id, dict(parsed.frontmatter), parsed.body or ""


def linked_sites(memory_path: Path, body: str) -> set[str]:
    """The sites of the **saved** pages this prose links to — the person saved each one, so its mark may be drawn
    (the icon route's second allowance, beside a page's trusted sources). Nothing else: a site only linked, never
    saved, draws a monogram."""
    from api.services import media_ingestor

    index = media_ingestor.load_url_index(Path(memory_path))
    sites: set[str] = set()
    seen: set[str] = set()
    for ref in prose_links(body):
        if ref.url in seen:
            continue
        seen.add(ref.url)
        if len(seen) > MAX_LINKS:
            break
        if _saved_page(memory_path, index, ref.url) is not None and (site := _site(ref.url)):
            sites.add(site)
    return sites


def _description(body: str) -> str | None:
    sections = entity_body.parse_sections(body)
    for name in ("Description", "Summary"):
        text = " ".join(link_views.plain(sections.get(name, "") or "").split())
        if text:
            return text[:_DESC_CHARS] + ("…" if len(text) > _DESC_CHARS else "")
    return None


def _looks_by_url(memory_path: Path) -> dict[str, list]:
    from api.services import media_ingestor

    out: dict[str, list] = {}
    for ref in design_refs.list_refs(memory_path):     # newest first
        if ref.url and ref.image.get("sha256"):
            out.setdefault(media_ingestor.normalize_url(ref.url), []).append(ref)
    return out


def _look(ref) -> dict:
    return {"id": ref.id, "day": ref.day, "image": f"/design/{ref.id}/image?v={str(ref.image['sha256'])[:12]}",
            "palette": [{"hex": str(c["hex"]), "share": float(c.get("share") or 0)} for c in ref.palette][:8]}


def facts(memory_path: Path, page: Path, *, icon_allowed: set[str] | None = None) -> dict:
    """``{entity_id, links: [...]}`` for ``page`` (an existing entity file) — the ``/links`` payload."""
    from api.services import media_ingestor

    memory_path = Path(memory_path)
    try:
        parsed = markdown_parser.parse(page)
    except Exception:  # noqa: BLE001 — an unreadable page has no links to draw
        return {"entity_id": page.stem, "links": []}
    order: dict[str, list[str]] = {}
    for ref in prose_links(parsed.body or ""):
        views = order.setdefault(ref.url, [])
        if ref.asked not in views:
            views.append(ref.asked)
        if len(order) >= MAX_LINKS:
            break
    if not order:
        return {"entity_id": page.stem, "links": []}
    index = media_ingestor.load_url_index(memory_path)
    looks = _looks_by_url(memory_path)
    allowed = icon_allowed if icon_allowed is not None else set()
    links: list[dict] = []
    for url, views in order.items():
        fact: dict = {"url": url, "views": views, "site": _site(url), "captures": []}
        saved = _saved_page(memory_path, index, url)
        if saved is not None:
            page_id, fm, body = saved
            media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
            read = fm.get("read") if isinstance(fm.get("read"), dict) else {}
            fact.update({
                "page_id": page_id,
                "title": str(fm.get("name") or "").strip() or None,
                "description": _description(body),
                "saved_at": str(fm.get("saved_at") or media.get("saved_at") or "") or None,
                "read_at": str(fm.get("read_at") or read.get("at") or "") or None,
                "preview": entity_picture.media_picture(page_id, fm),
            })
        found = looks.get(media_ingestor.normalize_url(url), [])[:MAX_LOOKS]
        if found:
            fact["looks"] = [_look(r) for r in found]
        fact["icon"] = bool(fact["site"]) and _site(url) in allowed
        links.append(fact)
    return {"entity_id": page.stem, "links": links}
