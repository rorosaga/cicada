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

G102 cheap slice (2026-09-02): the in-cycle pass above only ever sees the 20
most recent pages of a cycle that had episodes. ``backfill`` (bottom of this
module) is the whole-bank, oldest-first driver that closes that gap on the
engine-independent Sleep tail and on demand; its rulings (R1-R9) are in
``docs/superpowers/plans/2026-09-02-link-summaries-backfill.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

from loguru import logger

# Neither module imports back into ``api.services``: ``engine_errors`` is
# import-free by design and ``git_service`` imports only ``api.models.schemas``,
# so pulling them in at module level creates no cycle.
from api.services import engine_errors, git_service, markdown_parser
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims
from api.services.episode_ids import utc_now_iso

# summarize_fn(title, url, settings) -> description string | None
SummarizeFn = Callable[[str, str, object], Awaitable[str | None]]

_SENTENCE_END = (".", "!", "?")


def _is_substantive(text: str, min_len: int) -> bool:
    text = (text or "").strip()
    return len(text) >= min_len and any(ch in text for ch in _SENTENCE_END)


def _extract_description_section(body: str) -> str:
    """Return the ``## Description`` section text of a media page body (or '').

    The ```claims fence is stripped first (the ``entity_body.py`` pattern):
    ``parse_sections`` ends a section at the next H2 or EOF and knows nothing
    about the fence, so on a page whose ``## Description`` is the last H2 —
    every G71 ``/save <url> <reason>`` page, and any media page that received
    an MCP claim — the raw section swallowed the whole serialized claims YAML.
    Two corruptions followed (Task 1 review H1): a ``describes`` claim whose
    text embedded another claim's YAML, and a thin description padded past
    ``link_enrich_min_desc_len`` by that YAML so the page took the zero-LLM
    reuse tier instead of the fetch tier and was marked done with garbage.
    """
    from api.services.claims import strip_claims_block
    from api.services.entity_body import parse_sections

    return (parse_sections(strip_claims_block(body)).get("Description", "") or "").strip()


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
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError as exc:
        logger.error(f"corrupt ```claims block on {filepath.name}, skipping enrichment: {exc}")
        return False
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


def _excluded_media(url: str, mtype: str) -> bool:
    """Media this module never fetches: YouTube/video (oEmbed only, no page
    text), Instagram (login-walled), LinkedIn (ToS §8.2 — G71 §3 fix round:
    excluding it here closes the backdoor that ingest-time's ``enrich()``
    short-circuit would otherwise leave open — a LinkedIn page has no
    description at save time by design, so it would be the *first* thing a
    Sleep-time live fetch picks up and scrapes). Shared by the in-cycle
    ``_candidates`` and the backfill scan so the two can never disagree
    about what is off-limits."""
    url = (url or "").lower()
    mtype = (mtype or "").lower()
    if mtype in ("youtube", "video") or "youtube.com" in url or "youtu.be" in url:
        return True
    return "instagram.com" in url or "linkedin.com" in url


def _candidates(memory_path: Path, max_per_cycle: int) -> list[Path]:
    """Media pages needing IN-CYCLE enrichment: type==media, not an excluded
    host (``_excluded_media``), not junk (``classify_page`` — G86: a cookie
    banner must never be summarized), not already attempted. Capped at
    ``max_per_cycle`` (most recent first). The whole-bank, oldest-first pass
    over pages this one never reaches is ``backfill`` below."""
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
        mtype = str(media.get("media_type", ""))
        url = str(media.get("url", ""))
        if _excluded_media(url, mtype):
            continue
        if classify_page(str(fm.get("name") or ""), url) is not None:
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

    return await _summarize_excerpt(title, excerpt, url, settings)


async def _summarize_excerpt(title: str, excerpt: str, url: str, settings) -> str | None:
    """One bounded mini-model call over an already-fetched excerpt."""
    try:
        import litellm

        from api.services.providers import resolve_llm_fn

        prompt = (
            "You are summarizing a web page for a personal memory system.\n"
            "Given the page title and a text excerpt, write a 1-2 sentence "
            "description of what this site or page is about. Be specific about the "
            'topic. Be concise. Do not start with "This site" or "This page".\n\n'
            f"Title: {title}\nExcerpt:\n{excerpt}\n\nDescription (1-2 sentences):"
        )
        llm_fn = resolve_llm_fn(
            settings,
            model=getattr(settings, "litellm_model", "") or "gpt-5.4-mini",
            completion=litellm.acompletion,
            stage="enrichment",
        )
        response = await llm_fn(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )
        text = (response.choices[0].message.content or "").strip()
        return text or None
    except Exception as e:
        if _is_engine_failure(e):
            # R9 (G102 backfill): an engine that cannot work — signed-out
            # Claude, a bad API key, a missing model — is not a page that
            # cannot be described. Propagate so the backfill driver aborts
            # the LLM tier and leaves the page a candidate, instead of
            # stamping a 30-day `failed:no_summary` on every link in the
            # run. In-cycle `enrich_media_links` catches this itself and
            # marks `no_description`, exactly as a None return did (G74(a)
            # is the precedent: `_llm_judge_same_entity` re-raises too).
            raise
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


# --------------------------------------------------------------------------- #
# Backfill over EXISTING media pages (G102 cheap slice, 2026-09-02)
# --------------------------------------------------------------------------- #
#
# ``enrich_media_links`` above already globs the whole bank — but it only runs
# inside ``sleep_cycle._run_stages`` after Stage 5 (an idle night enriches
# nothing), takes the 20 MOST RECENT pages per cycle (a bulk import's older
# pages are never reached), and never retries an ``enrichment_attempted`` page
# (one failed fetch retires a link for good). Measured on the live bank
# 2026-09-02: 603 media pages, 370 with a ``## Description``, 210 of them
# substantive, ZERO ``describes`` claims. ``backfill`` closes those three gaps:
# it runs on the engine-independent Sleep tail (idle nights included) and on
# demand, oldest-imported first, keyed on the one fact that matters — "does
# this page carry a ``describes`` claim yet?" — with a dated fetch backoff.
# Every tier here reuses the helpers above verbatim.

FETCH_TIMEOUT_S = 4.0
FETCH_MAX_BYTES = 512_000
FETCH_MAX_REDIRECTS = 5
MIN_EXCERPT_CHARS = 100
MIN_SUMMARY_CHARS = 20
DESCRIPTION_PREVIEW_CHARS = 280


@dataclass
class FetchResult:
    """``status``: ``ok`` | ``blocked`` | ``interstitial`` | ``failed:<reason>``.
    ``text`` is the visible-text excerpt when ``ok``. Recorded on the media
    page as ``fetch_status`` so a failure is visible and not retried nightly."""

    status: str
    text: str | None = None


# fetch_fn(url, settings) -> FetchResult
FetchFn = Callable[[str, object], Awaitable[FetchResult]]
# summarize_fn(title, excerpt, url, settings) -> description | None  (== _summarize_excerpt)
ExcerptSummarizeFn = Callable[[str, str, str, object], Awaitable[str | None]]

_INTERSTITIAL_TITLE_RE = re.compile(
    r"^\s*(before you continue|antes de continuar|avant de continuer|"
    r"bevor (sie|du) (fortfahren|fortfährst)|prima di continuare)",
    re.IGNORECASE,
)
_LOGIN_TITLE_RE = re.compile(
    r"^\s*(sign in|log ?in|log on|iniciar sesi[oó]n|anmelden|se connecter)\b",
    re.IGNORECASE,
)
_LOGIN_HOSTS = frozenset({
    "accounts.google.com", "login.microsoftonline.com", "login.live.com",
    "auth.openai.com", "appleid.apple.com", "login.salesforce.com",
})
# A login-page PATH the user saved. Deliberately narrow: ``auth``/``oauth2``/
# ``sso`` were dropped (Task 1 review M1) because developer bookmarks are dense
# with ``/guides/auth``-style documentation paths, and a ``login_wall`` verdict
# is permanent — ``backfill`` stamps ``enrichment_status: junk`` and
# ``scan_backfill`` never revisits it. R2 wants a login WALL detector, not
# "a page about authentication".
_LOGIN_PATH_RE = re.compile(r"/(login|log-in|signin|sign-in|sign_in)(/|$|\?)", re.IGNORECASE)
# The wider set is honoured only for a REDIRECT TARGET in ``default_fetch``:
# being bounced from the saved URL onto ``/oauth2/…`` or ``/sso`` is a
# wall, whereas saving such a URL on purpose is not.
_LOGIN_REDIRECT_PATH_RE = re.compile(
    r"/(login|log-in|signin|sign-in|sign_in|auth|oauth2?|sso)(/|$|\?)", re.IGNORECASE
)


def classify_page(title: str, url: str) -> str | None:
    """``"interstitial"`` / ``"login_wall"`` / ``None`` — zero network.

    G86: 148 live bookmarks are Google consent interstitials ("Before you
    continue…", plus 27 on the Portuguese variant) that collapsed onto one
    entity; recon over them would extract entities from a cookie banner.
    G102's ToS rail: a login wall is never fetched, never worked around. Both
    are decided from the title + URL the page already carries, so junk is
    retired before a single byte is fetched.
    """
    text = (title or "").strip()
    if _INTERSTITIAL_TITLE_RE.match(text):
        return "interstitial"
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("consent."):
        return "interstitial"
    if host in _LOGIN_HOSTS:
        return "login_wall"
    if _LOGIN_TITLE_RE.match(text) or _LOGIN_PATH_RE.search(parsed.path or ""):
        return "login_wall"
    return None


def _redirected_to_wall(requested: str, final: str) -> bool:
    """True when following ``requested`` LANDED on a consent/login page.

    ``final`` gets the full ``classify_page`` treatment, plus the wider
    ``_LOGIN_REDIRECT_PATH_RE`` — but that one only when the server actually
    moved us (``final`` differs from ``requested``): httpx reports the final
    URL even when no redirect happened, so without that check a saved
    ``/guides/auth`` docs page would be ``blocked`` by the very regex M1
    removed from ``classify_page``.
    """
    if classify_page("", final) is not None:
        return True
    if final.rstrip("/") == (requested or "").rstrip("/"):
        return False
    try:
        path = urlparse(final).path or ""
    except ValueError:
        return False
    return bool(_LOGIN_REDIRECT_PATH_RE.search(path))


def _html_title(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        return (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    except Exception:
        return ""


async def default_fetch(url: str, settings) -> FetchResult:
    """The live page fetch for the backfill's §2b tier — robots-lite (R8).

    Fresh client per call, no cookies, no proxy env (``trust_env=False``),
    Cicada's own User-Agent, 4 s, ≤ 5 redirects, body streamed and cut at
    512 KB, HTML/text only. 401/403/407/451 — or a redirect that lands on a
    consent/login host — is ``blocked`` and is never retried with different
    headers: G102's rail is "no scraping behind auth, no circumventing a
    block", the same line drawn for LinkedIn and X. A fetched page whose
    title is an interstitial is ``interstitial`` (G86). Never raises.
    """
    if not url:
        return FetchResult("failed:no_url")
    try:
        import httpx

        from api.services.media_ingestor import USER_AGENT

        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_S, follow_redirects=True, max_redirects=FETCH_MAX_REDIRECTS,
            headers={"User-Agent": USER_AGENT}, trust_env=False,
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code in (401, 403, 407, 451):
                    return FetchResult("blocked")
                if resp.status_code >= 400:
                    return FetchResult(f"failed:http_{resp.status_code}")
                if _redirected_to_wall(url, str(resp.url)):
                    return FetchResult("blocked")
                ctype = (resp.headers.get("content-type") or "").lower()
                if "html" not in ctype and "text" not in ctype:
                    return FetchResult("failed:content_type")
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= FETCH_MAX_BYTES:
                        break
                raw = b"".join(chunks)[:FETCH_MAX_BYTES]
                html = raw.decode(resp.encoding or "utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"link fetch failed for {url}: {type(e).__name__}")
        return FetchResult(f"failed:{type(e).__name__}")
    if classify_page(_html_title(html), "") == "interstitial":
        return FetchResult("interstitial")
    excerpt = _extract_visible_text(
        html, int(getattr(settings, "link_enrich_excerpt_chars", 2000) or 2000)
    )
    if len(excerpt) < MIN_EXCERPT_CHARS:
        return FetchResult("failed:empty_body")  # JS-rendered / empty — out of scope
    return FetchResult("ok", excerpt)


@dataclass
class _Candidate:
    path: Path
    media_id: str
    title: str
    url: str
    episode: str
    description: str
    sort_key: str


@dataclass
class _Scan:
    junk: list[tuple[Path, str]] = field(default_factory=list)   # unmarked interstitial/login pages
    reuse: list[_Candidate] = field(default_factory=list)        # §2a — substantive description, zero LLM
    fetch: list[_Candidate] = field(default_factory=list)        # §2b — needs fetch + summary
    backoff: int = 0                                             # failed < retry_days ago; not selectable yet


def _saved_sort_key(fm: dict) -> str:
    """Oldest-imported first (R2): the user's own save date when the source
    export gave one (G99d ``saved_at``), else the ingest date."""
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    return str(fm.get("saved_at") or fm.get("created") or media.get("saved_at") or "")


def _in_fetch_backoff(fm: dict, today: date, retry_days: int) -> bool:
    status = str(fm.get("fetch_status") or "")
    if not status or status == "ok":
        return False
    try:
        attempted = date.fromisoformat(str(fm.get("fetch_attempted_at") or "")[:10])
    except ValueError:
        return False
    return (today - attempted).days < retry_days


def scan_backfill(memory_path: Path, settings, *, today: date | None = None) -> _Scan:
    """Classify every media page by what the backfill still owes it (R1/R2).

    Done = a ``describes`` claim exists. ``enrichment_attempted`` is NOT
    consulted: the in-cycle pass set it after a single failed fetch and never
    looked again — the third gap this backfill exists to close.
    """
    today = today or date.today()
    min_len = int(getattr(settings, "link_enrich_min_desc_len", 120) or 120)
    retry_days = int(getattr(settings, "link_enrich_fetch_retry_days", 30) or 30)
    scan = _Scan()
    entities_dir = Path(memory_path) / "entities"
    if not entities_dir.exists():
        return scan
    for fp in sorted(entities_dir.glob("media-*.md")):
        try:
            parsed = markdown_parser.parse(fp)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        if fm.get("type") != "media" or fm.get("enrichment_status") == "junk":
            continue
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        url = str(media.get("url") or "")
        if _excluded_media(url, str(media.get("media_type") or "")):
            continue
        title = str(fm.get("name") or fp.stem)
        kind = classify_page(title, url)
        if kind is not None:
            scan.junk.append((fp, kind))
            continue
        try:
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError:
            continue  # the corruption guard owns this page; _append_claim would refuse it anyway
        if any(c.predicate == "describes" for c in claims):
            continue
        episodes = fm.get("source_episodes") or []
        cand = _Candidate(
            path=fp, media_id=fp.stem, title=title, url=url,
            episode=str(episodes[0]) if episodes else "",
            description=_extract_description_section(parsed.body),
            sort_key=_saved_sort_key(fm),
        )
        if _is_substantive(cand.description, min_len):
            scan.reuse.append(cand)
        elif _in_fetch_backoff(fm, today, retry_days):
            scan.backoff += 1
        else:
            scan.fetch.append(cand)
    scan.reuse.sort(key=lambda c: (c.sort_key, c.media_id))
    scan.fetch.sort(key=lambda c: (c.sort_key, c.media_id))
    return scan


_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_CLAIMS_FENCE_RE = re.compile(r"^```claims\s*$", re.MULTILINE)


def _upsert_description(body: str, text: str) -> str:
    """Set the body's ``## Description`` section to ``text`` (R3), touching
    nothing else — string surgery, not ``entity_body.render_sections``, which
    re-orders sections and would move the ```claims block. Replaces an
    existing section in place; otherwise inserts after ``## Summary`` (or at
    the top of the sections, or before the claims fence, or at the end)."""
    body = body or ""
    text = (text or "").strip()
    heads = list(_H2_RE.finditer(body))
    fence = _CLAIMS_FENCE_RE.search(body)
    fence_at = fence.start() if fence else len(body)

    def _section_end(i: int) -> int:
        nxt = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        return min(nxt, fence_at) if heads[i].start() < fence_at else nxt

    for i, h in enumerate(heads):
        if h.group(1).strip().lower() == "description":
            return (body[: h.end()] + "\n" + text + "\n\n" + body[_section_end(i):].lstrip("\n")).rstrip() + "\n"
    block = f"## Description\n{text}\n\n"
    for i, h in enumerate(heads):
        if h.group(1).strip().lower() == "summary":
            at = _section_end(i)
            return (body[:at].rstrip() + "\n\n" + block + body[at:].lstrip("\n")).rstrip() + "\n"
    at = heads[0].start() if heads and heads[0].start() < fence_at else fence_at
    return (body[:at].rstrip() + ("\n\n" if body[:at].strip() else "") + block + body[at:].lstrip("\n")).rstrip() + "\n"


def _stamp(fp: Path, **fields) -> None:
    parsed = markdown_parser.parse(fp)
    parsed.frontmatter.update(fields)
    markdown_parser.write(fp, parsed.frontmatter, parsed.body)


_ENGINE_FAILURES: tuple[type[BaseException], ...] = (engine_errors.EngineError,)


def _is_engine_failure(exc: BaseException) -> bool:
    """R9: an engine that cannot work is not a page that cannot be described."""
    if isinstance(exc, _ENGINE_FAILURES):
        return True
    try:
        import litellm

        return isinstance(exc, (litellm.exceptions.AuthenticationError, litellm.exceptions.NotFoundError))
    except Exception:
        return False


@dataclass
class BackfillReport:
    selected: int = 0
    reused: int = 0
    summarized: int = 0
    fetched: int = 0
    failed: int = 0
    skipped: int = 0
    extracted: int = 0
    related: int = 0
    remaining: int = 0
    remaining_recon: int = 0
    deferred: int = 0
    llm_calls: int = 0
    judge_calls: int = 0
    engine_aborted: str | None = None
    commit: str | None = None
    written_paths: list[str] = field(default_factory=list)
    manifest: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            k: getattr(self, k) for k in (
                "selected", "reused", "summarized", "fetched", "failed", "skipped",
                "extracted", "related", "remaining", "remaining_recon", "deferred",
                "llm_calls", "engine_aborted", "commit",
            )
        }

    def touched(self, rel_path: str, line: str) -> None:
        if rel_path not in self.written_paths:
            self.written_paths.append(rel_path)
        if line not in self.manifest:
            self.manifest.append(line)


def progress_marker_path(memory_path: Path) -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / "link_enrich" / f"{Path(memory_path).name}.json"


def write_progress_marker(memory_path: Path, report: BackfillReport) -> None:
    """R1: a report for humans/agents at ``$CICADA_HOME/link_enrich/<bank>.json``
    — outside the bank (a derived artifact is never tracked in a bank's git,
    TODO.md ruling 3). Nothing load-bearing reads it; the pages are the state."""
    try:
        path = progress_marker_path(memory_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Aware UTC (G114's convention for every stamp Cicada writes) — an
        # agent reading a naive local time cannot tell what zone it is in.
        payload = {"last_run": utc_now_iso(), **report.as_dict()}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:  # pragma: no cover - a marker must never fail a run
        logger.debug(f"link_enrich progress marker not written: {type(e).__name__}: {e}")


async def _commit_backfill(memory_path: Path, settings, report: BackfillReport, *, engine: str | None,
                           models_before: set[str]) -> str | None:
    """R7: one commit scoped to exactly the files this run wrote, authored by
    the models that ran — or ``cicada`` when none did (the G85 pattern)."""
    if not report.written_paths:
        return None
    authors: list[str]
    if report.llm_calls == 0:
        authors, engine_trailer = ["cicada"], None
    else:
        engine_trailer = engine or None
        if engine == "claude-cli":
            from api.services import agent_engine

            authors = sorted(set(agent_engine.models_used()) - models_before) or [
                str(getattr(settings, "agent_model", "") or "sonnet")
            ]
        else:
            authors = [str(getattr(settings, "litellm_model", "") or "unknown")]
            judge = str(getattr(settings, "litellm_disambiguation_model", "") or "").strip()
            if report.judge_calls and judge and judge not in authors:
                authors.append(judge)
    message = git_service.build_commit_message(
        f"Link enrichment {date.today().isoformat()}", report.manifest, authors=authors, engine=engine_trailer,
    )
    try:
        await git_service.commit_paths(memory_path, message, sorted(report.written_paths))
        return (await git_service._run_git(memory_path, "rev-parse", "HEAD")).strip()
    except Exception as e:
        logger.warning(f"link enrichment commit skipped: {type(e).__name__}: {e}")
        return None


async def backfill(
    memory_path: Path,
    settings,
    *,
    limit: int | None = None,
    summarize_fn: ExcerptSummarizeFn | None = None,
    fetch_fn: FetchFn | None = None,
    recon_limit: int | None = None,
    extract_fn=None,
    match_fn=None,
    indexer_factory=None,
    engine: str | None = None,
    commit: bool = True,
    today: date | None = None,
) -> BackfillReport:
    """Describe + relate EXISTING media pages, oldest-imported first (R1-R9).

    ``summarize_fn``/``fetch_fn`` ``None`` (the hermetic default) disables the
    §2b tier: the run is then zero-LLM and the commit is authored ``cicada``.
    ``sleep_cycle`` passes ``default_fetch`` (behind the connector gate) and
    ``_summarize_excerpt``; the maintenance endpoint passes both ungated.
    Every failure is recorded per page; this never raises.
    """
    memory_path = Path(memory_path)
    report = BackfillReport()
    if not bool(getattr(settings, "link_enrich_enabled", True)):
        return report
    today = today or date.today()
    today_s = today.isoformat()
    cap = int(limit if limit is not None else getattr(settings, "link_enrich_backfill_per_cycle", 20) or 20)
    from api.services import agent_engine

    models_before = set(agent_engine.models_used())

    scan = scan_backfill(memory_path, settings, today=today)

    # Junk first — free, never counts against the cap (R2), retired for good.
    for fp, kind in scan.junk:
        _stamp(fp, enrichment_attempted=True, enrichment_status="junk", fetch_status=f"skipped:{kind}",
               fetch_attempted_at=today_s)
        report.skipped += 1
        report.touched(f"entities/{fp.stem}.md", f"entities/{fp.stem}.md: skipped (source: n/a, trigger: sleep/link_enrichment)")

    def _describe(cand: _Candidate, text: str, authored_by: str) -> bool:
        """Land the ``describes`` claim; True when it was actually written.

        ``_append_claim`` refuses a page whose ```claims block went malformed
        between the scan and the write (the corruption guard owns it), or one
        that already carries the id. Neither is an enrichment: the page keeps
        its candidate status and the manifest never says ``enriched`` for it
        (Task 1 review L2) — a manifest line is a provenance record, not a
        hope.
        """
        claim = _build_describes_claim(cand.media_id, text, cand.episode, today_s, authored_by)
        if not _append_claim(cand.path, claim):
            logger.warning(f"link backfill: describes claim refused for {cand.media_id}; left as candidate")
            return False
        # Set the in-cycle marker too so ``_candidates`` stops re-selecting
        # this page (R1: the backfill never READS it, but it keeps it honest).
        _stamp(cand.path, enrichment_attempted=True)
        report.touched(
            f"entities/{cand.media_id}.md",
            f"entities/{cand.media_id}.md: enriched (source: {cand.episode or 'n/a'}, trigger: sleep/link_enrichment)",
        )
        return True

    # §2a reuse — zero LLM. R3: no model touched it, so the claim is authored
    # ``cicada`` (the in-cycle pass stamps ``litellm_model`` on a zero-LLM
    # reuse; the backfill does not repeat that inaccuracy).
    for cand in scan.reuse[:cap]:
        report.selected += 1
        if _describe(cand, cand.description, "cicada"):
            report.reused += 1
        else:
            report.failed += 1

    # §2b fetch + summarize — bounded by what is left of the cap.
    model = str(getattr(settings, "litellm_model", "") or "unknown")
    if engine == "claude-cli":
        model = str(getattr(settings, "agent_model", "") or "sonnet")
    for cand in scan.fetch[: max(0, cap - report.selected)]:
        if summarize_fn is None or fetch_fn is None or report.engine_aborted:
            break
        report.selected += 1
        try:
            result = await fetch_fn(cand.url, settings)
        except Exception as e:
            result = FetchResult(f"failed:{type(e).__name__}")
        _stamp(cand.path, fetch_status=result.status, fetch_attempted_at=today_s)
        # Honest manifest: a fetch stamp is not an enrichment. `_describe` adds
        # the `enriched` line only once a claim actually lands. The status
        # token's colon is safe for the history readers: ``git_service``
        # matches an entity's manifest line by its ``entities/<id>.md:``
        # prefix, not by an action-word regex.
        report.touched(f"entities/{cand.media_id}.md",
                       f"entities/{cand.media_id}.md: fetch {result.status} (source: {cand.episode or 'n/a'}, trigger: sleep/link_enrichment)")
        if result.status != "ok" or not result.text:
            report.failed += 1
            continue
        report.fetched += 1
        try:
            summary = await summarize_fn(cand.title, result.text, cand.url, settings)
            # Counted only once a model actually answered (Task 1 review
            # M2): ``_commit_backfill`` keys the author and ``Cicada-Engine:``
            # trailers on this counter, and an engine that never ran (R9
            # abort below) authored nothing — the run's real writes (fetch
            # stamps, junk marks) are then ``cicada``'s, engine-less, exactly
            # like the G85 decay-only commit.
            report.llm_calls += 1
        except Exception as e:
            if _is_engine_failure(e):
                # R9: leave the page a candidate (its fetch_status is ``ok``,
                # which never backs off) and stop spending on a dead engine.
                # ``selected`` is decremented because this page was not
                # processed.
                report.engine_aborted = type(e).__name__
                logger.warning(f"link summarize engine failure — leaving pages unmarked: {type(e).__name__}: {e}")
                report.selected -= 1
                break
            # A page-level failure (malformed response, parse error) still
            # cost a model call — keep the attribution honest in that direction too.
            report.llm_calls += 1
            logger.warning(f"link summarize failed for {cand.media_id}: {type(e).__name__}: {e}")
            summary = None
        summary = (summary or "").strip()
        if len(summary) < MIN_SUMMARY_CHARS:
            _stamp(cand.path, fetch_status="failed:no_summary")
            report.failed += 1
            continue
        parsed = markdown_parser.parse(cand.path)
        parsed.frontmatter["description_source"] = "summary"
        markdown_parser.write(cand.path, parsed.frontmatter, _upsert_description(parsed.body, summary))
        if _describe(cand, summary, model):
            report.summarized += 1
        else:
            report.failed += 1

    # G102 recon (Task 2 wires the real thing).
    if not report.engine_aborted:
        await _run_recon(memory_path, settings, report, limit=recon_limit, extract_fn=extract_fn,
                         match_fn=match_fn, indexer_factory=indexer_factory, engine=engine, today=today)

    after = scan_backfill(memory_path, settings, today=today)
    report.remaining = len(after.reuse) + len(after.fetch)
    report.deferred = after.backoff
    if commit:
        report.commit = await _commit_backfill(memory_path, settings, report, engine=engine, models_before=models_before)
    write_progress_marker(memory_path, report)
    logger.info(
        f"Link backfill: selected={report.selected} reused={report.reused} fetched={report.fetched} "
        f"summarized={report.summarized} failed={report.failed} skipped={report.skipped} "
        f"related={report.related} remaining={report.remaining}"
    )
    return report


async def _run_recon(memory_path: Path, settings, report: BackfillReport, **kwargs) -> None:
    """Task 2 replaces this with ``link_recon.run_recon``."""
    return None
