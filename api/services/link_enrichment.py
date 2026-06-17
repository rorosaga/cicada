"""M5f Stage 5.57 — Sleep link-enrichment subagent (the John→websites design).

Per ``docs/goals/m5-prep/link-enrichment.md``: when a saved ``media`` link lands
in Sleep with no meaningful description, this bounded subagent records a
``describes`` claim (so the link is retrievable by topic) and, when a person who
shares the media's source episode recommended it, a ``recommends`` claim on that
person, plus bidirectional ``![[…]]`` transclusion in both pages.

Two enrichment paths:

* **§2a reuse (zero LLM, default):** if the media page already carries a
  substantive ``## Description`` (≥ ``link_enrich_min_desc_len`` chars and a
  sentence-ending character), promote that string into a ``describes`` claim — no
  network, no model call. This is the common case (Open-Graph description present
  at ingest but never surfaced as a claim).

* **§2b scour + summarize (bounded LLM):** when the description is absent/thin, a
  single mini-model call summarizes the page. The summarizer is injected via
  ``summarize_fn`` (so tests are hermetic); the default fetches the URL through
  ``media_ingestor``'s HTTP path and calls ``settings.litellm_model``. Capped at
  ``link_enrich_max_per_cycle`` calls/cycle; every failure mode is offline-safe.

Idempotency: ``enrichment_attempted`` in the media page frontmatter short-circuits
a second pass. The whole stage is wrapped in a try/except by ``sleep_cycle`` so a
network timeout can never hard-block the cycle; ``link_enrich_enabled=False`` is a
clean kill switch.

Scope note (M5f): the bounded zero-LLM reuse path + recommends/transclusion is
shipped and tested hermetically. The live §2b network fetch reuses the existing
``media_ingestor`` HTTP helpers behind the injectable ``summarize_fn`` seam; it is
offline-safe (any fetch/LLM failure marks the page attempted and writes no claim).
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import markdown_parser
from api.services.claims import Claim, parse_claims, write_claims

# summarize_fn(title, url, settings) -> description string | None
SummarizeFn = Callable[[str, str, object], Awaitable[str | None]]

_SENTENCE_END = (".", "!", "?")


def _is_substantive(text: str, min_len: int) -> bool:
    text = (text or "").strip()
    return len(text) >= min_len and any(ch in text for ch in _SENTENCE_END)


def _extract_description_section(body: str) -> str:
    """Return the ``## Description`` section text of a media page body (or '')."""
    from api.services.entity_body import parse_sections

    return (parse_sections(body).get("Description", "") or "").strip()


def _claim_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("\x00".join(parts).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


def _build_describes_claim(media_id: str, text: str, episode: str, today: str, model: str) -> Claim:
    return Claim(
        id=_claim_id("clm_describes", media_id, text[:64]),
        text=text,
        subject=media_id,
        predicate="describes",
        object=text,
        object_kind="literal",
        observer="agent",
        context="general",
        epistemic="explicit",
        source_trust="agent_extracted",
        confidence=0.75,
        valid_from=today,
        recorded_at=today,
        source_episodes=[episode] if episode else [],
        authored_by=model or "unknown",
        origin="sleep/link_enrichment",
    )


def _build_recommends_claim(
    person_id: str, media_id: str, title: str, url: str, episode_date: str, today: str, model: str
) -> Claim:
    text = f"{person_id.replace('-', ' ').title()} recommended {title} ({url})."
    return Claim(
        id=_claim_id("clm_recommends", person_id, media_id),
        text=text,
        subject=person_id,
        predicate="recommends",
        object=media_id,
        object_kind="node",
        observer="agent",
        context="general",
        epistemic="explicit",
        source_trust="agent_extracted",
        confidence=0.80,
        valid_from=episode_date or today,
        recorded_at=today,
        source_episodes=[],
        authored_by=model or "unknown",
        origin="sleep/link_enrichment",
    )


def _append_claim(filepath: Path, new_claim: Claim) -> bool:
    """Append ``new_claim`` to a page's ```claims block (dedupe by id). True if added."""
    parsed = markdown_parser.parse(filepath)
    claims = parse_claims(parsed.body)
    if any(c.id == new_claim.id for c in claims):
        return False
    claims.append(new_claim)
    markdown_parser.write(filepath, parsed.frontmatter, write_claims(parsed.body, claims))
    return True


def _add_transclusion(filepath: Path, subsection: str, target_id: str) -> None:
    """Idempotently add a ``![[target_id]]`` embed under a ``## Related`` subsection.

    Read-only embed (transclusion_resolver depth-cap/cycle-guard applies at render
    time); we only author the directive. No-op if the embed already exists.
    """
    parsed = markdown_parser.parse(filepath)
    body = parsed.body or ""
    embed = f"![[{target_id}]]"
    if embed in body:
        return
    block = f"### {subsection}\n{embed}"
    if "## Related" in body:
        # Append the embed under the existing Related section.
        body = body.rstrip() + f"\n\n{block}\n"
    else:
        body = body.rstrip() + f"\n\n## Related\n\n{block}\n"
    markdown_parser.write(filepath, parsed.frontmatter, body)


def _set_attempted(filepath: Path, status: str | None = None) -> None:
    parsed = markdown_parser.parse(filepath)
    parsed.frontmatter["enrichment_attempted"] = True
    if status:
        parsed.frontmatter["enrichment_status"] = status
    markdown_parser.write(filepath, parsed.frontmatter, parsed.body)


def _candidates(memory_path: Path, max_per_cycle: int) -> list[Path]:
    """Media pages needing enrichment: type==media, not YouTube/Instagram, not
    already attempted. Capped at ``max_per_cycle`` (most recent first)."""
    entities_dir = memory_path / "entities"
    if not entities_dir.exists():
        return []
    out: list[tuple[str, Path]] = []
    for fp in entities_dir.glob("media-*.md"):
        try:
            parsed = markdown_parser.parse(fp)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        if fm.get("type") != "media" or fm.get("enrichment_attempted"):
            continue
        media = fm.get("media") or {}
        mtype = str(media.get("media_type", "")).lower()
        url = str(media.get("url", "")).lower()
        if mtype in ("youtube", "video") or "youtube.com" in url or "youtu.be" in url:
            continue
        if "instagram.com" in url:
            continue
        out.append((str(fm.get("last_referenced", "") or ""), fp))
    out.sort(key=lambda t: t[0], reverse=True)
    return [fp for _, fp in out[:max_per_cycle]]


def _episode_persons(memory_path: Path, changes: list[dict]) -> dict[str, list[str]]:
    """episode_id -> [person entity ids resolved this cycle] (for recommends)."""
    out: dict[str, list[str]] = {}
    entities_dir = memory_path / "entities"
    for change in changes or []:
        if not isinstance(change, dict):
            continue
        pid = change.get("id")
        if not pid:
            continue
        etype = (change.get("entity") or {}).get("type")
        if etype is None:
            fp = entities_dir / f"{pid}.md"
            if fp.exists():
                etype = (markdown_parser.parse(fp).frontmatter or {}).get("type")
        if etype != "person":
            continue
        eps = set(change.get("source_episodes") or [])
        if change.get("source_episode"):
            eps.add(change["source_episode"])
        for ep in eps:
            if ep:
                out.setdefault(ep, []).append(pid)
    return out


async def default_summarize(title: str, url: str, settings) -> str | None:
    """The live §2b summarizer: fetch the page via ``media_ingestor``'s HTTP path,
    extract visible text, and make one bounded mini-model call. Offline-safe —
    returns ``None`` on any fetch/parse/LLM failure (caller writes no claim).

    Kept out of the hermetic test path: ``enrich_media_links`` only invokes a
    summarizer that is explicitly passed in, so unit tests never hit the network.
    ``sleep_cycle`` passes THIS function to enable live enrichment.
    """
    if not url:
        return None
    try:
        import httpx

        from api.services.media_ingestor import _MAX_READ, _TIMEOUT, USER_AGENT

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            html = resp.text[:_MAX_READ]
        excerpt = _extract_visible_text(html, int(getattr(settings, "link_enrich_excerpt_chars", 2000) or 2000))
        if len(excerpt) < 100:
            return None  # JS-rendered / empty body
    except Exception as e:
        logger.warning(f"link fetch failed for {url}: {type(e).__name__}: {e}")
        return None

    try:
        import litellm

        prompt = (
            "You are summarizing a web page for a personal memory system.\n"
            "Given the page title and a text excerpt, write a 1-2 sentence "
            "description of what this site or page is about. Be specific about the "
            'topic. Be concise. Do not start with "This site" or "This page".\n\n'
            f"Title: {title}\nExcerpt:\n{excerpt}\n\nDescription (1-2 sentences):"
        )
        response = await litellm.acompletion(
            model=getattr(settings, "litellm_model", "") or "gpt-5.4-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )
        text = (response.choices[0].message.content or "").strip()
        return text or None
    except Exception as e:
        logger.warning(f"link summarize LLM failed for {url}: {type(e).__name__}: {e}")
        return None


def _extract_visible_text(html: str, limit: int) -> str:
    """BeautifulSoup visible-text extractor (headings + main/article/body)."""
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    parts: list[str] = []
    for h in soup.find_all(["h1", "h2"]):
        t = h.get_text(strip=True)
        if t:
            parts.append(t)
    main = soup.find("main") or soup.find("article") or soup.body
    if main:
        parts.append(main.get_text(" ", strip=True))
    return " ".join(parts)[:limit].strip()


async def enrich_media_links(
    memory_path: Path,
    changes: list[dict],
    settings,
    *,
    max_per_cycle: int | None = None,
    summarize_fn: SummarizeFn | None = None,
) -> int:
    """Enrich thin/absent media descriptions into ``describes`` (+ ``recommends``)
    claims with bidirectional transclusion. Returns the count of media entities
    enriched. Offline-safe; never raises out (the caller also wraps it)."""
    memory_path = Path(memory_path)
    if not bool(getattr(settings, "link_enrich_enabled", True)):
        return 0

    cap = max_per_cycle if max_per_cycle is not None else int(
        getattr(settings, "link_enrich_max_per_cycle", 20) or 20
    )
    min_len = int(getattr(settings, "link_enrich_min_desc_len", 120) or 120)
    model = getattr(settings, "litellm_model", "") or "unknown"
    today = str(date.today())

    candidates = _candidates(memory_path, cap)
    if not candidates:
        return 0

    episode_persons = _episode_persons(memory_path, changes)
    entities_dir = memory_path / "entities"
    enriched = 0

    for media_fp in candidates:
        parsed = markdown_parser.parse(media_fp)
        fm = parsed.frontmatter or {}
        media = fm.get("media") or {}
        url = str(media.get("url", "") or "")
        media_id = media_fp.stem
        title = str(fm.get("name", media_id) or media_id)
        episodes = fm.get("source_episodes") or []
        episode = str(episodes[0]) if episodes else ""

        # §2a reuse path: a substantive on-page description -> claim, no LLM.
        desc = _extract_description_section(parsed.body)
        description: str | None = None
        if _is_substantive(desc, min_len):
            description = desc
        elif summarize_fn is not None:
            # §2b scour path (injected/hermetic in tests; default does the real
            # fetch+LLM). Offline-safe: a None/short return writes no claim.
            try:
                summary = await summarize_fn(title, url, settings)
            except Exception as e:
                logger.warning(f"link summarize failed for {media_id}: {type(e).__name__}: {e}")
                summary = None
            if summary and len(summary.strip()) >= 20:
                description = summary.strip()

        if not description:
            # Nothing usable — mark attempted so we don't re-spend next cycle.
            _set_attempted(media_fp, status="no_description")
            continue

        describes = _build_describes_claim(media_id, description, episode, today, model)
        _append_claim(media_fp, describes)
        _set_attempted(media_fp)
        enriched += 1

        # recommends + bidirectional transclusion for any person sharing the episode.
        for ep in episodes:
            for person_id in episode_persons.get(str(ep), []):
                person_fp = entities_dir / f"{person_id}.md"
                if not person_fp.exists():
                    continue
                rec = _build_recommends_claim(
                    person_id, media_id, title, url, str(ep)[:10] if ep else today, today, model
                )
                _append_claim(person_fp, rec)
                _add_transclusion(person_fp, "Recommended links", media_id)
                _add_transclusion(media_fp, "Recommended by", person_id)

    return enriched
