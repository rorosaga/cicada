"""Paper details from the official APIs, and nothing else (R-F3 · R-LS18 · R-LS19).

arXiv and Crossref both publish machine interfaces with written terms, and
Cicada uses exactly those: ``export.arxiv.org/api/query`` (Atom; "no more than
one request every three seconds … a single connection at a time"; metadata is
CC0; "must not store and serve arXiv e-prints") and ``api.crossref.org/works``
(JSON; the public pool — the polite pool wants a contact email, and Cicada
never sends the person's email). Never ``arxiv.org/abs|pdf|html`` (its
robots file asks for 15 s and forbids indiscriminate downloads), never a PDF,
never behind auth; 4 s and ≤ 512 KB per response, like every other fetch
under the ToS rail.

What a response becomes is a WORLD-tier cache (G121): the abstract as the
page's ``## Description`` and one ``describes`` claim with
``source_trust: external``, an ``external:arxiv|crossref`` observer, ``cicada``
as author and the fetch date as ``recorded_at``. The personal tier — why the
paper is in the person's memory — is ``papers``' and never touched here.

Two callers: the folder sync's ``?resolve=true`` (the person asked; runs in the
background, one run per process) and the Sleep tail (unattended; behind
``CICADA_ALLOW_CONNECTOR_FETCH`` and capped per cycle).
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import bank_index, evidence, fact_sources, folder_source, markdown_parser, media_ingestor, papers
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, strip_claims_block, write_claims

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works/"
TIMEOUT_S = 4.0
MAX_BYTES = 512_000
ARXIV_SPACING_S = 3.0
CROSSREF_SPACING_S = 1.0
ARXIV_BATCH = 50
RETRY_DAYS = 30
TAIL_ARXIV_IDS = 200
TAIL_CROSSREF_DOIS = 30
# Names the software, as `logos.manifest.json`'s `userAgent` already does — never a person.
USER_AGENT = "CicadaPaperMetadata/1.0 (+https://github.com/rorosaga/cicada)"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_TAG_RE = re.compile(r"<[^>]+>")
_run_lock = threading.Lock()
#: Monotonic start of each API's last request, ACROSS runs: arXiv's "one request every three
#: seconds" does not reset because a run ended (a second "Sync now" right after a first). Only the
#: real clock shares it; a test's injected clock gets a fresh pacer.
_LAST_START: dict[str, float] = {}


@dataclass
class Response:
    status: int
    content_type: str = ""
    body: bytes = b""
    error: str | None = None


FetchFn = Callable[[str, dict], Awaitable[Response]]


async def default_fetch(url: str, params: dict) -> Response:
    """One GET under the ToS rail: 4 s, ≤ 512 KB read, no cookies (a fresh client
    per call), no proxy env, Cicada's own User-Agent, ≤ 3 redirects. Never
    raises; a transport failure is ``status 0`` carrying the exception's name."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True, max_redirects=3,
                                     headers={"User-Agent": USER_AGENT}, trust_env=False) as client:
            async with client.stream("GET", url, params=params or None) as resp:
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_BYTES:
                        break
                return Response(resp.status_code, (resp.headers.get("content-type") or "").lower(),
                                b"".join(chunks)[:MAX_BYTES])
    except Exception as e:  # noqa: BLE001 - recorded, never raised
        return Response(0, error=type(e).__name__)


class _Pacer:
    """``spacing`` seconds between the starts of consecutive requests, one at a
    time (the caller awaits each fetch before asking again). ``_run_lock`` keeps
    two runs from interleaving in one process, and ``_LAST_START`` carries the
    spacing from one run into the next (R-LS18)."""

    def __init__(self, spacing: float, *, clock, sleep, api: str):
        self.spacing, self._clock, self._sleep = spacing, clock, sleep
        self._key = api if clock is time.monotonic else None
        self._last: float | None = _LAST_START.get(self._key) if self._key else None

    async def wait(self) -> None:
        if self._last is not None:
            gap = self.spacing - (self._clock() - self._last)
            if gap > 0:
                await self._sleep(gap)
        self._last = self._clock()
        if self._key:
            _LAST_START[self._key] = self._last


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def parse_arxiv_atom(body: bytes) -> dict[str, dict] | None:
    """``arxiv id -> metadata`` from an API response. An id the API does not
    know is simply absent (arXiv answers with fewer entries, or an ``Error``
    entry whose id is not an abs URL).

    ``None`` — not ``{}`` — when the body is not XML at all (T4 review round 1,
    finding 4): a 200 that fails to parse is a transport or format problem, most
    likely a response cut at ``MAX_BYTES``, and reading it as "the API knows none
    of these" would back 50 papers off for ``RETRY_DAYS``. ``{}`` stays the
    answer for a valid, empty feed."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    out: dict[str, dict] = {}
    for entry in root.findall(f"{_ATOM}entry"):
        m = papers.ARXIV_URL_RE.search(entry.findtext(f"{_ATOM}id") or "")
        if not m:
            continue
        category = entry.find(f"{_ARXIV}primary_category")
        out[papers.normalise_arxiv(m.group("id"))] = {
            "title": _clean(entry.findtext(f"{_ATOM}title")) or None,
            "abstract": _clean(entry.findtext(f"{_ATOM}summary")) or None,
            "authors": [n for n in (_clean(a.findtext(f"{_ATOM}name")) for a in entry.findall(f"{_ATOM}author")) if n],
            "published": (entry.findtext(f"{_ATOM}published") or "")[:10] or None,
            "updated": (entry.findtext(f"{_ATOM}updated") or "")[:10] or None,
            "primary_category": category.get("term") if category is not None else None,
            "doi": papers.normalise_doi(entry.findtext(f"{_ARXIV}doi") or "") or None,
            "journal_ref": _clean(entry.findtext(f"{_ARXIV}journal_ref")) or None,
        }
    return out


def parse_crossref(body: bytes) -> dict | None:
    try:
        msg = json.loads(body.decode("utf-8", errors="replace")).get("message") or {}
    except (ValueError, AttributeError):
        return None
    authors = []
    for a in msg.get("author") or []:
        name = _clean(" ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name"))
        if name:
            authors.append(name)
    parts: list = []
    for key in ("published", "published-print", "published-online", "issued"):
        candidate = ((msg.get(key) or {}).get("date-parts") or [[]])[0]
        if candidate and candidate[0]:
            parts = candidate
            break
    published = "-".join(f"{int(p):04d}" if i == 0 else f"{int(p):02d}" for i, p in enumerate(parts) if p) or None
    return {
        "title": _clean((msg.get("title") or [None])[0]) or None,
        "authors": authors,
        "published": published,
        "abstract": _clean(_TAG_RE.sub(" ", msg.get("abstract") or "")) or None,
        "venue": _clean((msg.get("container-title") or [None])[0]) or None,
        "doi": papers.normalise_doi(msg.get("DOI") or "") or None,
    }


def _pending(memory_path: Path, today: date) -> list[tuple[str, str | None, str | None]]:
    out = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if not papers.is_paper(fm):
            continue
        paper = fm.get("paper") or {}
        if paper.get("metadata_at"):
            continue
        attempted = str(paper.get("metadata_attempted_at") or "")
        if attempted:
            try:
                if (today - date.fromisoformat(attempted[:10])).days < RETRY_DAYS:
                    continue
            except ValueError:
                pass
        out.append((f.stem, paper.get("arxiv_id"), paper.get("doi")))
    return sorted(out)


def has_pending(memory_path: Path) -> bool:
    return bool(_pending(memory_path, date.today()))


def _mark_failed(memory_path: Path, entity_id: str, status: str, today: str) -> None:
    path = papers.page_path(memory_path, entity_id)
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["paper"] = {**(fm.get("paper") or {}), "metadata_status": status, "metadata_attempted_at": today}
    markdown_parser.write(path, fm, parsed.body)


@dataclass
class _IndexOp:
    """What one ``_apply`` wants from ``url_index.json`` — recorded, never applied
    in place. T4 review round 1, finding 1: holding one loaded index across every
    network wait and saving it at the end silently dropped whatever another writer
    (a bookmark or Safari sync, an MCP ``cicada_save_url``, a Telegram capture, a
    folder sync) had added meanwhile. ``_replay_index`` applies these to a FRESH
    load instead, with no await between its load and its save."""
    entity_id: str
    alias: "papers.PaperKey | None" = None
    title: str | None = None


def _apply(memory_path: Path, entity_id: str, meta: dict, *, source: str, today: str) -> _IndexOp | None:
    """Write one response onto its page; returns the index change it implies
    (a DOI learned from arXiv, a placeholder title replaced), if any."""
    from api.services.link_enrichment import _upsert_description

    path = papers.page_path(memory_path, entity_id)
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    paper = dict(fm.get("paper") or {})
    for key in ("title", "authors", "published", "updated", "primary_category", "journal_ref", "venue"):
        if meta.get(key):
            paper[key] = meta[key]
    learned = None
    if meta.get("doi") and not paper.get("doi"):
        paper["doi"] = learned = meta["doi"]
    paper.update(metadata_source=source, metadata_at=today)
    paper.pop("metadata_status", None)
    paper.pop("metadata_attempted_at", None)
    new_title = None
    if paper.get("title_from") == "placeholder" and meta.get("title"):
        fm["name"] = new_title = meta["title"]
        paper["title_from"] = source
    fm["paper"] = paper
    body = parsed.body
    abstract = meta.get("abstract")
    if abstract:
        body = _upsert_description(body, abstract)
        try:
            claims = parse_claims(body, strict=True)
        except MalformedClaimsBlockError:
            claims = None
        if claims is not None:
            cid = papers.claim_id(entity_id, "describes", source)
            span = evidence.verify(None, entity_id, abstract, text=strip_claims_block(body))
            claims = [c for c in claims if c.id != cid] + [Claim(
                id=cid, text=abstract, subject=entity_id, predicate="describes", object=abstract,
                object_kind="literal", observer=f"external:{source}", context="general",
                epistemic="explicit", source_trust="external", confidence=0.9,
                valid_from=paper.get("published") or today, recorded_at=today, source_episodes=[],
                authored_by="cicada", origin=f"papers/{source}", evidence=[span])]
            body = write_claims(body, claims)
    markdown_parser.write(path, fm, body)
    alias = None
    if learned:
        alias = papers.PaperKey(arxiv_id=paper.get("arxiv_id"), doi=learned)
        fact_sources.add_source(memory_path, entity_id, f"https://doi.org/{learned}", kind="url", added_by="cicada")
    return _IndexOp(entity_id, alias=alias, title=new_title) if (alias or new_title) else None


def _replay_index(memory_path: Path, ops: list[_IndexOp]) -> bool:
    """Apply this run's index changes to a fresh load and save only on a change.
    Synchronous on purpose: nothing awaits between the load and the save, so an
    event-loop writer can never land in between (finding 1)."""
    if not ops:
        return False
    idx = media_ingestor.load_url_index(memory_path)
    before = json.dumps(idx, sort_keys=True)
    for op in ops:
        if op.title:
            # Only the page's primary (Feed) row; the person's own bullet title lives on the page.
            for entry in idx.values():
                if isinstance(entry, dict) and entry.get("media_entity_id") == op.entity_id \
                        and not entry.get("alias_of"):
                    entry["title"] = op.title
        if op.alias:
            papers.index_aliases(idx, op.alias, op.entity_id, title=None)
    if json.dumps(idx, sort_keys=True) == before:
        return False
    media_ingestor.save_url_index(memory_path, idx)
    return True


def _sleep_running() -> bool:
    from api.services import sleep_cycle

    return sleep_cycle.get_sleep_state().status == "running"


def _write_guarded(memory_path: Path, entity_id: str, report: dict, paths: set[str], ops: list[_IndexOp],
                   write: Callable[[], "_IndexOp | None"], *, resolved: bool) -> None:
    """One page write that can never abort the run (T4 review round 1, finding 2):
    a page archived or moved by an inbox resolve mid-run, or one with malformed
    frontmatter, counts as failed and the run goes on — so the pages already
    written still reach ``run_locked``'s scoped commit instead of riding the next
    ``git add -A`` under another author. The path is kept whenever the file
    still exists, because a write can fail after the page was already rewritten."""
    rel = f"entities/{entity_id}.md"
    try:
        op = write()
    except Exception as e:  # noqa: BLE001 - one page never sinks the run
        logger.warning(f"paper details: {entity_id} not written: {type(e).__name__}")
        report["failed"] += 1
        if papers.page_path(memory_path, entity_id).exists():
            paths.add(rel)
        return
    if op:
        ops.append(op)
    report["resolved" if resolved else "failed"] += 1
    paths.add(rel)


def _apply_arxiv_chunk(memory_path: Path, chunk: list[tuple[str, str]], found: dict, *, today: str,
                       report: dict, paths: set[str], ops: list[_IndexOp]) -> None:
    for entity_id, arxiv_id in chunk:
        meta = found.get(arxiv_id)
        if meta:
            _write_guarded(memory_path, entity_id, report, paths, ops, resolved=True,
                           write=lambda e=entity_id, m=meta: _apply(memory_path, e, m, source="arxiv", today=today))
        else:
            _write_guarded(memory_path, entity_id, report, paths, ops, resolved=False,
                           write=lambda e=entity_id: _mark_failed(memory_path, e, "not_found", today))


def new_report() -> dict:
    return {"arxiv_requests": 0, "crossref_requests": 0, "resolved": 0, "failed": 0, "remaining": 0,
            "error": None, "stopped": None, "paths": []}


async def resolve(memory_path: Path, *, fetch_fn: FetchFn | None = None, max_arxiv: int | None = None,
                  max_crossref: int | None = None, clock=time.monotonic, sleep=asyncio.sleep,
                  stop_if_sleeping: bool = False, report: dict | None = None) -> dict:
    """Fetch details for every paper page that has none. Stops an API at its
    first refusal or failure (R-LS18); a record the API does not have backs off
    ``RETRY_DAYS``. Returns counts plus the bank paths written.

    ``report`` may be passed in so a caller still holds the paths written when
    this raises (``run_locked`` commits them in a ``finally``). Bank scans and
    page writes run in a worker thread (T4 review round 1, finding 6); only the
    fetches and the pacer stay on the loop. ``stop_if_sleeping`` is the
    user-triggered run's (finding 3): R-LS17 says paper writes wait while Sleep
    runs, and a long run must not overlap a cycle that starts during it — so the
    Sleep state is checked before every request and again before a response is
    written, and the run stops (the tail picks up what is left). The Sleep tail
    itself never passes it: it runs while the status still reads ``running``."""
    memory_path = Path(memory_path)
    fetch = fetch_fn or default_fetch
    today_d = date.today()
    today = today_d.isoformat()
    report = report if report is not None else new_report()
    paths: set[str] = set()
    ops: list[_IndexOp] = []

    def stop_now() -> bool:
        if stop_if_sleeping and _sleep_running():
            report["stopped"] = "sleep"
            return True
        return False

    try:
        pending = await asyncio.to_thread(_pending, memory_path, today_d)
        arxiv = [(e, a) for e, a, _ in pending if a][:max_arxiv]
        dois = [(e, d) for e, a, d in pending if not a and d][:max_crossref]
        chunks = [arxiv[i:i + ARXIV_BATCH] for i in range(0, len(arxiv), ARXIV_BATCH)]
        pacer = _Pacer(ARXIV_SPACING_S, clock=clock, sleep=sleep, api="arxiv")
        while chunks and not stop_now():
            chunk = chunks.pop(0)
            await pacer.wait()
            resp = await fetch(ARXIV_API, {"id_list": ",".join(a for _, a in chunk), "max_results": str(len(chunk))})
            report["arxiv_requests"] += 1
            if resp.status != 200 or "xml" not in resp.content_type:
                report["error"] = f"arXiv {resp.error or f'HTTP {resp.status}'}"
                break
            if len(resp.body) >= MAX_BYTES:
                # Cut at the ToS rail's 512 KB (finding 4): a large-collaboration paper can list
                # thousands of authors. Ask again in halves; one paper too big on its own is
                # genuinely unreadable under the rail and backs off like a missing one.
                if len(chunk) > 1:
                    half = len(chunk) // 2
                    chunks[:0] = [chunk[:half], chunk[half:]]
                    continue
                entity_id = chunk[0][0]
                await asyncio.to_thread(_write_guarded, memory_path, entity_id, report, paths, ops,
                                        lambda: _mark_failed(memory_path, entity_id, "unreadable", today),
                                        resolved=False)
                continue
            found = parse_arxiv_atom(resp.body)
            if found is None:
                # Never "not found" for a body that is not XML — nothing is marked (finding 4).
                report["error"] = "arXiv unreadable response"
                break
            if stop_now():
                break
            await asyncio.to_thread(_apply_arxiv_chunk, memory_path, chunk, found, today=today,
                                    report=report, paths=paths, ops=ops)
        pacer = _Pacer(CROSSREF_SPACING_S, clock=clock, sleep=sleep, api="crossref")
        for entity_id, doi in dois:
            if report["stopped"] or stop_now():
                break
            await pacer.wait()
            resp = await fetch(CROSSREF_API + urllib.parse.quote(doi, safe="/"), {})
            report["crossref_requests"] += 1
            if resp.status == 404:
                await asyncio.to_thread(_write_guarded, memory_path, entity_id, report, paths, ops,
                                        lambda e=entity_id: _mark_failed(memory_path, e, "not_found", today),
                                        resolved=False)
                continue
            if resp.status != 200 or "json" not in resp.content_type:
                report["error"] = report["error"] or f"Crossref {resp.error or f'HTTP {resp.status}'}"
                break
            if stop_now():
                break
            meta = parse_crossref(resp.body)
            if meta is None:
                write, resolved = (lambda e=entity_id: _mark_failed(memory_path, e, "unreadable", today)), False
            else:
                write, resolved = (lambda e=entity_id, m=meta: _apply(memory_path, e, m, source="crossref",
                                                                      today=today)), True
            await asyncio.to_thread(_write_guarded, memory_path, entity_id, report, paths, ops, write,
                                    resolved=resolved)
    finally:
        # Replayed even when the run raised, so an alias whose page was written is never lost.
        if _replay_index(memory_path, ops):
            paths.add("sources/url_index.json")
        report["paths"] = sorted(paths)
    report["remaining"] = len(await asyncio.to_thread(_pending, memory_path, today_d))
    return report


def record(memory_path: Path, report: dict) -> None:
    """The run's outcome under the ``papers`` key of ``sync_state.json`` —
    not a channel row, a place the next reader can see why details are missing."""
    from api.services import sync_state

    if report.get("error"):
        sync_state.record_error(memory_path, "papers", str(report["error"]))
    else:
        sync_state.record_sync(memory_path, "papers", count=int(report.get("resolved") or 0))


async def run_locked(memory_path: Path, **kwargs) -> dict | None:
    """One run per process: ``None`` when another is in flight (never a 409 —
    nothing was asked of the person that this would refuse)."""
    if not _run_lock.acquire(blocking=False):
        return None
    report = new_report()
    try:
        await resolve(memory_path, report=report, **kwargs)
        return report
    except Exception as e:
        report["error"] = report["error"] or f"paper details {type(e).__name__}"
        raise
    finally:
        # T4 review round 1, finding 2: whatever was written is committed as `cicada` and the
        # outcome recorded even when the run raised — a page left dirty here would ride the next
        # `git add -A` writer's commit under its author (the G85-class smear). F2-back R-B5: a
        # refused commit already said so on the `papers` line; a success stamp would erase it.
        try:
            committed = await folder_source.commit_paths_for(
                memory_path, report["paths"], subject="Paper details", trigger="papers/metadata",
                author="cicada", channel="papers")
            if committed:
                try:
                    record(memory_path, report)
                except Exception as e:  # noqa: BLE001 - a status line never outranks the commit
                    logger.warning(f"paper details: outcome not recorded: {type(e).__name__}")
        finally:
            _run_lock.release()


async def resolve_in_background(memory_path: Path) -> None:
    """The user-triggered run, scheduled by ``POST /sources/folders/{id}/sync?resolve=true``.
    Skipped while a Sleep cycle runs — its tail runs this anyway (R-LS17)."""
    try:
        from api.services import sleep_cycle

        if sleep_cycle.get_sleep_state().status == "running":
            return
        await run_locked(memory_path, stop_if_sleeping=True)
    except Exception as e:  # noqa: BLE001 - a background run never surfaces as a 500
        logger.warning(f"paper details failed: {type(e).__name__}: {e}")
