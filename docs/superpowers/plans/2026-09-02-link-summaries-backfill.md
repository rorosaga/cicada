# Saved-link Summaries Backfill + Relations (G102 cheap slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every saved link in the bank gets a short description (reusing the OpenGraph text already stored when it is substantive, fetching + summarizing once when it is not) and — the part that matters for the graph — `about` edges to the concepts, tools, companies, people and projects the page is actually about, produced by the EXISTING Stage-1 extraction prompt over `title + description` and the EXISTING Stage-2 "is this an existing entity?" judgment. Links stop being islands. The owner's ask (2026-09-02): *"an easy way that we can read the contents of all these websites for small summaries of what they are so it's easier to drive correlation in the memory graph between those entities."*

**Architecture:** One new driver, `link_enrichment.backfill`, that works over EXISTING media pages (not the cycle's `changes`), oldest-imported first, keyed on the one fact that matters — *does this page carry a `describes` claim yet?* — with three tiers: zero-LLM reuse of a substantive stored description (§2a), a bounded fetch + one summarize call (§2b), and G102 recon (batched extraction → Stage-2 match → `about` claims, projected into `graph_edges.yaml` by the existing Stage 5.7 code). Exposed twice: `POST /maintenance/enrich-links?limit=N` (user-initiated, never network-gated) and a Sleep-tail step in the same clean-tree-guarded branch as the connector poll (runs on idle nights, drains `link_enrich_backfill_per_cycle` per night). Every write lands in one scoped commit with the structured manifest and a `Cicada-Author:` trailer that is `cicada` when no model ran.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), YAML frontmatter + ```claims blocks + git (`memory/`), SwiftUI + XCTest (`app/CicadaApp`, Task 5 only).

**Spec:** `docs/goals/memory-evolution.md` row **G102** (site recon → RELATIONS, not summaries; cheap first slice = extract over the OG text already stored; fetching only on the Sleep tail behind the connector gate; ToS rail; G86's interstitial skip). Also the G74/G80 Sleep-safety ruling (no LLM at capture time; engine-free read paths) and TODO.md ruling 4 (scheduled cycles never spend plan quota).

## What the code actually does today (verified, corrects the brief)

The brief says Stage 5.57 "only looks at entities touched in the current cycle". That is not what the code does — and it matters for the design:

- `link_enrichment._candidates` (`api/services/link_enrichment.py:157-190`) globs **every** `entities/media-*.md` in the bank; `changes` is only used by `_episode_persons` for the `recommends` claims. So the reason the live bank has ZERO `describes` claims is three other properties: (1) the pass runs only inside `_run_stages` after Stage 5 (`sleep_cycle.py:1011-1018`) — an idle night (zero episodes) never enriches anything; (2) it takes the 20 **most recent** pages per cycle (`_candidates` sorts `last_referenced` descending, lines 189-190), so a bulk import's older pages are never reached; (3) a page marked `enrichment_attempted` is never retried (line 169), so one failed fetch retires a link for good, and the in-cycle §2b summarizer needs a `## Description` to be *thin* — 210 of the 370 stored descriptions are substantive, which the §2a path would have promoted for free had the pass ever run over them.
- **Both production LLM seams swallow engine failures today**, which is why R9 below needs code, not just a `try/except` in the driver: `_summarize_excerpt` (`link_enrichment.py:254-284`) catches `Exception` and returns `None`, and `entity_extractor.extract` (`entity_extractor.py:378-406`) catches every `EngineError` / `litellm` auth error per episode, counts it `failed`, and leaves the episode out of its result list. Fed straight into the backfill, a signed-out engine would stamp every page `failed:no_summary` (30-day backoff) or `recon_attempted` (never retried) — the exact failure mode G74(a) fixed in the Stage-2 judge. The one extraction entry point that *raises* is the per-chunk `entity_extractor._extract_chunk` (206-253: one retry on a transient error, then the exception propagates); Task 2's `default_extract` uses it directly.
- The backfill therefore fixes *where* and *in what order* the pass runs and *what counts as done* — not the tier logic, which is reused verbatim (`_is_substantive`, `_extract_description_section`, `_build_describes_claim`, `_append_claim`, `_summarize_excerpt`, `_extract_visible_text`).
- Media pages are `evergreen` (`decay_policy.default_class_for("media", ...)` at `media_ingestor.py:1489`), so an `about` claim on a media page never decays (claim multiplier 0.0) and never generates a decay nudge. `about` is not in the predicate seed, so the cardinality oracle treats it as multi-valued (`predicates.py:170-189`: unseen ⇒ coexist) — many `about` objects on one link can never raise a conflict item.
- `GET /sources`'s ETag already covers `entities` (`sources.py:367`), and that component is the max **file** mtime under `entities/` (`sync_service.py:148` → `graph_builder._dir_mtime`, 536-545), so an in-place edit of a media page invalidates `/sources`, `/graph` (via `entities` + `edges`) and `/entities/{id}` without any ETag widening. The progress marker written by this plan lives outside the bank and feeds no response, so nothing needs widening.

## Global Constraints

- Work ONLY in `<worktree>/` (branch `feat/link-summaries`, based on `dev` @ `bad8461`). Every shell command is `cd <worktree>/ && <cmd>` with absolute paths (`zoxide` hijacks relative `cd`; ignore its stderr warning). Never `grep --include=*.ext` (zsh globbing breaks it).
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari`, or `~/.claude/projects` — real personal data. Fixtures are synthetic: `alpha-project`, `bob-example`, `example.com`, `robotics.example`.
- Python tests: `cd <worktree>/ && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. Full suite `api/tests`: the baseline has exactly 8 date-dependent failures in `test_calendar_registry.py` plus `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` (order-dependent, pre-existing). Everything else must be green after every task.
- Swift tests (Task 5 only): `cd <worktree>/app/CicadaApp && swift test --filter FeedIdentityTests`.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no subagents. Ignore Devin/PR comments.
- **No network in tests.** `conftest.py` already sets `CICADA_API_AUTH=off`, `CICADA_ALLOW_LOGO_FETCH=off`, `CICADA_ALLOW_CONNECTOR_FETCH=off`, `CICADA_TELEMETRY=off` and makes a real `claude` spawn an `AssertionError`. Every test injects `fetch_fn` / `summarize_fn` / `extract_fn` / `match_fn` / `indexer_factory`; the default (network, LLM, embedding) seams are never reached from a test.
- **Sleep-safety (G80 ruling):** nothing in this plan runs at capture time; the read paths (`GET /sources`, `GET /entities/{id}`) stay engine-free; the only LLM call sites are the backfill's §2b summarizer, the recon extraction and the Stage-2 judge, all reached only from the maintenance endpoint or the Sleep tail.
- **Portability:** no owner name, no author-machine path, no bank-specific slug in code, tests or docs. Privacy rule for `docs/goals/`, `CLAUDE.md`, commits and PR bodies: placeholders only.
- Docstrings explain WHY and cite the G-row / review that motivated a rule — match the density of `link_enrichment.py` and `sleep_cycle._poll_connectors_safely`.
- Line numbers below are from base commit `bad8461` and drift by a few lines as tasks land — read the cited code before editing.

## Rulings (binding — decided here so no task re-derives them)

- **R1 — the page is the state; the marker is a report.** Idempotency and resumability come from the media page's own frontmatter and claims: *done* = a `describes` claim exists (and, for recon, `recon_attempted` is set); a failed fetch is `fetch_status` + `fetch_attempted_at` with a `link_enrich_fetch_retry_days` (30) backoff; junk is `enrichment_status: junk`. The old `enrichment_attempted` flag is **not** consulted by the backfill (it retired pages permanently after one failed fetch — the third gap above); the backfill still sets it after writing a claim so the in-cycle `_candidates` stops re-selecting the page. The progress marker at `$CICADA_HOME/link_enrich/<bank>.json` (outside the bank — a derived artifact is never tracked in a bank's git, TODO.md ruling 3) records the last run's counters + `remaining` for a human/agent to read; nothing load-bearing reads it. Rescanning ~600 pages is milliseconds, and it can never disagree with the pages.
- **R2 — selection order.** Junk pages (interstitial / login wall, zero network, `classify_page`) are marked first and never count against `limit`. Then §2a reuse candidates (substantive stored description — free), then §2b fetch candidates, each oldest-imported first (`saved_at` → `created` → `media.saved_at`, then id). `limit` bounds reuse + fetch together; the §2b tier gets whatever is left. Recon has its own scan (`## Description` ≥ `link_enrich_min_desc_len`, no `recon_attempted`), order and cap (`link_recon_max_per_cycle`, default 40 links ≈ 5 extraction calls), so a link whose description landed in an earlier run is still picked up.
- **R3 — a summary is written to the page body, not just a claim.** The §2b summary goes into the body's `## Description` section (inserted after `## Summary`; the ```claims block and every other section are preserved byte-for-byte) with `description_source: summary` in frontmatter, AND into the `describes` claim (which carries `authored_by: <model>`). Reason: the Feed preview and the entity card already render `## Description` (`FeedView.swift:373-378`, `EntityDetailCard.swift:765-770`), so the surface needs no new render path; the claim keeps provenance. A §2a reuse claim is `authored_by: cicada` — no model touched it (the in-cycle pass stamps `litellm_model` on a zero-LLM reuse; the backfill does not repeat that inaccuracy).
- **R4 — recon batches 8 links per extraction call and attributes by surface form.** The EXISTING `EXTRACTION_SYSTEM_PROMPT` (≈1.1k tokens) is fed a rendered batch of `link_recon_batch_size` (8) links, each `title + description` clipped to 300 words (≈400 tokens) — ≈4.3k input tokens and ≤ ~3k output per call, one call per 8 links instead of one per link. The prompt has no per-link attribution, so an extracted entity is attributed to every link in the batch whose `title + description` contains the entity's name or an alias (normalized, token-based); an entity that matches **no** link's text is dropped. That drop is also the hallucination rail: the prompt's "extract every URL / history" instincts produce nothing groundable here, and anything not literally on the card cannot be an `about` edge.
- **R5 — route through the Stage-2 *judgment*, not the Stage-2 *driver*.** `entity_resolver.resolve()` would (a) create pages for anything that clears the promotion threshold (a link mention linked to an existing entity by a relationship clears `_is_linked_to_existing`), (b) queue a "Who is X?" clarification for every low-confidence name (`entity_resolver.py:277-283`, the `pending_actions` entry carrying `_infer_uncertainty_type`) — an inbox flood from bookmark blurbs — and (c) promote pending entries. The promotion rule in CLAUDE.md says a single link mention must **never** create an entity. So recon calls a new public `entity_resolver.match_existing(entity, existing_by_name, settings, cache=)` that wraps exactly the two matchers `resolve()` uses (`_find_direct_candidate_match` at 510-543, then `_find_llm_candidate_match` at 794-877 — same fuzz threshold, same type gate, same judge, same cache) and returns an existing id only on `decision == "same"` with `source == "existing"`; `unsure` → `None`, no clarification. Unmatched mentions become **candidates** the same way Stage 2 records a first mention — `indexer.index_pending_entity(PendingEntity(...))` (the promotion model's rung 1), so a later conversation mention promotes them with the link as backfilled context. The indexer is injected (`indexer_factory`, default `SqliteVecIndexer`, `None` on failure) exactly as `resolve()` guards it.
- **R6 — `about` is a claim on the media page; the target page is never touched.** `subject=<media-id> predicate=about object=<entity-id> object_kind=node observer=agent source_trust=agent_extracted confidence=min(extracted, 0.7) origin=sleep/link_recon source_episodes=[<the link's own episode>]`, id `clm_about_<sha1(media, target)[:8]>` (deterministic → `_append_claim`'s id-dedupe makes a re-run a no-op). The entity id is also appended to the media page's `related:` list (so `/sources`'s `related_count` and the entity card's Related pills reflect it). The target's page gets **nothing**: no `related` entry, no `last_referenced` bump — a bookmark blurb mentioning a tool is not the user referencing it, and bumping would defeat decay ("time as a signal"). The graph edge comes from Stage 5.7's `regenerate_edges_from_claims` (`graph_builder.py:396-484`), which the backfill calls itself so an endpoint run shows edges immediately. Only `person|project|company|concept|tool|location` types are related (never `skill`/`directory`).
- **R7 — one scoped commit per run, authored honestly.** `git_service.commit_paths` (never `git add -A`) over exactly the media files written + `graph_edges.yaml` when it changed. Subject `Link enrichment <date>`; manifest lines `entities/<id>.md: enriched (source: <ep>, trigger: sleep/link_enrichment)` / `entities/<id>.md: related (source: <ep>, trigger: sleep/link_recon)` / `entities/<id>.md: skipped (source: n/a, trigger: sleep/link_enrichment)` / `graph_edges.yaml: updated (trigger: sleep/link_recon)`. `Cicada-Author: cicada` when the run made zero model calls (pure §2a + junk marking — the G85 pattern); otherwise the models that ran: on the agent engine the delta of `agent_engine.models_used()` across the run, on litellm `settings.litellm_model` plus `litellm_disambiguation_model` when the judge ran. `Cicada-Engine:` only when a model ran (a `cicada` commit carries no engine — same contract as the decay-only commit).
- **R8 — fetch rails (G102 ToS + G86).** `default_fetch`: fresh `httpx.AsyncClient` per call, no cookies, `trust_env=False`, `User-Agent = media_ingestor.USER_AGENT`, 4 s timeout, ≤ 5 redirects, stream-read capped at 512 KB, HTML/text content types only. 401/403/407/451, or a redirect that lands on a consent/login host → `blocked` (never retried with different headers — no circumventing a block). A fetched page whose `<title>` is an interstitial → `interstitial`. `<100` visible chars → `failed:empty_body` (JS-rendered; out of scope). Every non-`ok` status is recorded on the page with `fetch_attempted_at` and retried only after `link_enrich_fetch_retry_days`.
- **R9 — engine failures are not page failures.** A summarize/extract/judge call that raises `engine_errors.EngineError`, `litellm.exceptions.AuthenticationError` or `litellm.exceptions.NotFoundError` aborts the LLM tiers for the run (`engine_aborted` on the report, one log line) and leaves the pages **unmarked** — they stay candidates. Only page-specific outcomes (fetch status, empty text, a `<20`-char summary) mark a page. Mirrors `_llm_judge_same_entity`'s G74(a) rule at `entity_resolver.py:783-788`. **This needs two seam changes, because neither production seam raises today** (see "What the code actually does"): (i) `_summarize_excerpt`'s `except Exception` gains a leading `if _is_engine_failure(e): raise` — in-cycle behaviour is unchanged, because `enrich_media_links` wraps its `summarize_fn` call in its own `except Exception` and marks the page `no_description` either way (line 359-363), exactly what a `None` return did; (ii) `link_recon.default_extract` calls `entity_extractor._extract_chunk` (which retries once then propagates), never `entity_extractor.extract` (which swallows and drops the episode). The judge already raises (G74(a)).
- **R10 — the Sleep tail resolves its engine lazily and honours ruling 4.** The tail calls `engine_select.resolve_settings(settings, user_triggered=)` **only** when the scan shows LLM work (a §2b or recon candidate exists) — a scheduled cycle gets `byok` before the registry is touched (`engine_select.py:155-156`); a user-triggered idle cycle may probe cache-first. `CICADA_ALLOW_CONNECTOR_FETCH` gates ONLY the tail's default `fetch_fn` (opt-out, exactly the connector contract: G71 final review H2); `POST /maintenance/enrich-links` is user-initiated and never gated. `link_enrich_enabled=False` kills both entry points.
- **R11 — the endpoint refuses to overlap a running cycle.** `409` while `sleep_cycle.get_sleep_state().status == "running"` (the tail is inside that window, so the two writers never overlap in that direction). The other direction — a cycle starting while an endpoint run is mid-write — is a narrow window bounded by `limit` and closed by the run's immediate `commit_paths`; disclosed, not fixed.
- **R12 — `GET /sources` gains `description` and `about`; nothing else on the wire changes.** `description` = the first 280 chars of `## Description` (word boundary, `…`), `about` = the media page's `related:` ids (only this path writes `related` on a media page — `write_media_entity` seeds `[]` and Stage 5 never updates a media page). Read from the page the endpoint already parses; no extra I/O. Swift `MediaFeedItem` decodes both as optionals so an older backend still decodes.

---

## File map

| File | Responsibility |
|---|---|
| `api/config.py` | `link_enrich_backfill_per_cycle`, `link_enrich_fetch_retry_days`, `link_recon_batch_size`, `link_recon_max_per_cycle` |
| `api/services/link_enrichment.py` | `classify_page`, `_excluded_media`, `FetchResult`/`default_fetch`, `scan_backfill`, `_upsert_description`, `BackfillReport`, `backfill`, `_commit_backfill`, `write_progress_marker`; `_summarize_excerpt` re-raises engine failures (R9) |
| `api/services/link_recon.py` (new) | `render_batch`, `attribute`, `scan_recon`, `run_recon`, `_build_about_claim`, `default_extract` |
| `api/services/entity_resolver.py` | `existing_by_name`, `match_existing` (public wrappers, no behaviour change to `resolve`) |
| `api/routers/maintenance.py`, `api/models/schemas.py` | `POST /maintenance/enrich-links`, `MaintenanceEnrichLinksResponse`, `MediaSourceItem.description/about` |
| `api/services/sleep_cycle.py` | `_backfill_links_safely`, `user_triggered` threaded into the tail |
| `api/routers/sources.py` | `description` / `about` on each row |
| `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift`, `Views/Feed/FeedView.swift`, `Tests/CicadaAppTests/FeedIdentityTests.swift` | `MediaFeedItem` fields, preview seeded from the row |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | docs |
| Tests: `api/tests/test_link_backfill.py`, `test_link_recon.py`, `test_maintenance_enrich_links.py`, `test_sleep_link_backfill.py`, `test_sources_about.py` | one file per task |

---

### Task 1: The backfill driver — §2a reuse, §2b fetch + summarize, junk, backoff, one commit

**Files:**
- Modify: `api/config.py:168-171` (add four settings after `link_enrich_excerpt_chars`)
- Modify: `api/services/link_enrichment.py` (new section appended after `enrich_media_links`; `_candidates` at 157-190 refactored to share `_excluded_media` + skip junk; `_summarize_excerpt` at 254-284 re-raises engine failures)
- Test: `api/tests/test_link_backfill.py` (new)

**Interfaces:**
- Produces: `link_enrichment.classify_page(title, url) -> "interstitial" | "login_wall" | None`; `link_enrichment.FetchResult(status, text)`; `FetchFn = Callable[[str, object], Awaitable[FetchResult]]`; `ExcerptSummarizeFn = Callable[[str, str, str, object], Awaitable[str | None]]` (this IS `_summarize_excerpt`'s signature); `link_enrichment.scan_backfill(memory_path, settings, *, today=None) -> _Scan`; `link_enrichment.backfill(memory_path, settings, *, limit=None, summarize_fn=None, fetch_fn=None, recon_limit=None, extract_fn=None, match_fn=None, indexer_factory=None, engine=None, commit=True, today=None) -> BackfillReport` (the recon kwargs are accepted here and wired in Task 2 — in Task 1 `backfill` passes them to a `_run_recon` stub that returns zeros); `BackfillReport.as_dict()`.
- Consumes: `_is_substantive`, `_extract_description_section`, `_build_describes_claim(media_id, text, episode, today, model)`, `_append_claim(path, claim) -> bool`, `_extract_visible_text(html, limit)`, `_summarize_excerpt(title, excerpt, url, settings)` (all existing), `git_service.build_commit_message(subject, body_lines, authors=, engine=)` / `commit_paths(memory_path, message, paths)` / `_run_git(memory_path, *args)`, `agent_engine.models_used()`, `auth.cicada_home()`.
- Every Task-1 test passes `recon_limit=0` (through the `_backfill` helper below): in Task 1 `_run_recon` is a stub, but once Task 2 lands, an omitted `recon_limit` means the real `default_extract` — a network call from a test, and an extra `llm_calls` that breaks the `cicada`-author assertions. Task 2's own tests exercise recon with injected seams.

- [ ] **Step 1: Add the settings**

In `api/config.py`, directly after line 171 (`link_enrich_excerpt_chars`):

```python
    # G102 cheap slice + backfill (2026-09-02). `link_enrich_max_per_cycle`
    # above caps the IN-CYCLE Stage 5.57 pass; this caps the Sleep-tail
    # BACKFILL over the whole bank's pre-existing media pages, which runs on
    # idle nights too (`sleep_cycle._backfill_links_safely`) and drains the
    # bank oldest-first until nothing is left. 20/night keeps a 600-link
    # bank draining in about a month with at most 20 fetches + 20 summaries
    # + ~5 extraction calls per night.
    link_enrich_backfill_per_cycle: int = 20   # CICADA_LINK_ENRICH_BACKFILL_PER_CYCLE
    # A failed/blocked page fetch is recorded on the page (`fetch_status`,
    # `fetch_attempted_at`) and not retried before this many days — so a
    # dead link costs one fetch a month, not one a night, and a block is
    # never hammered (G102 ToS rail).
    link_enrich_fetch_retry_days: int = 30     # CICADA_LINK_ENRICH_FETCH_RETRY_DAYS
    # G102 recon: links per Stage-1 extraction call (8 x ~400 tokens of
    # title+description under the ~1.1k-token prompt stays a small call),
    # and links related per run.
    link_recon_batch_size: int = 8             # CICADA_LINK_RECON_BATCH_SIZE
    link_recon_max_per_cycle: int = 40         # CICADA_LINK_RECON_MAX_PER_CYCLE
```

- [ ] **Step 2: Write the failing tests**

```python
# api/tests/test_link_backfill.py
"""G102 cheap slice — the backfill over EXISTING media pages.

Hermetic: no network, no real LLM, no embedding model. `fetch_fn` and
`summarize_fn` are injected; the recon seams are injected as no-ops here
(Task 2 covers them). Real git is used where the commit's provenance is the
thing under test — mirrors test_sleep_connector_poll.py's H1 test.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import link_enrichment, markdown_parser
from api.services.claims import parse_claims

LONG = (
    "A curated list of robotics conferences and workshops for graduate "
    "researchers, with submission deadlines and location details."
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """The progress marker lives under `cicada_home()`; a test must never
    write into the developer's real ~/.cicada."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _settings(memory: Path, **over):
    base = dict(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        llm_mode="byok",
        link_enrich_enabled=True,
        link_enrich_max_per_cycle=20,
        link_enrich_min_desc_len=120,
        link_enrich_excerpt_chars=2000,
        link_enrich_backfill_per_cycle=20,
        link_enrich_fetch_retry_days=30,
        link_recon_batch_size=8,
        link_recon_max_per_cycle=40,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _media(memory: Path, stem: str, name: str, url: str, *, saved_at: str,
           description: str = "", extra_fm: dict | None = None):
    fm = {
        "name": name, "type": "media", "status": "active", "confidence": 0.7,
        "created": saved_at, "last_referenced": saved_at, "saved_at": saved_at,
        "source_episodes": [f"ep_{saved_at}_001"], "tags": ["bookmark"], "related": [],
        "media": {"url": url, "media_type": "bookmark", "site": "example.com"},
    }
    fm.update(extra_fm or {})
    body = f"## Summary\nSaved bookmark — {name}."
    if description:
        body += f"\n\n## Description\n{description}"
    markdown_parser.write(memory / "entities" / f"{stem}.md", fm, body)


def _bank(tmp_path: Path, *, git: bool = False) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    if git:
        for args in (("init", "-q"), ("config", "user.email", "t@example.com"),
                     ("config", "user.name", "t")):
            subprocess.run(["git", "-C", str(memory), *args], check=True)
    return memory


def _git_log(memory: Path) -> str:
    return subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"],
                          check=True, capture_output=True, text=True).stdout


def _seed_commit(memory: Path) -> None:
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-q", "-m", "seed"], check=True)


def _claims(memory: Path, stem: str):
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{stem}.md").body)


def _fm(memory: Path, stem: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{stem}.md").frontmatter


async def _fetch_ok(url, settings):
    return link_enrichment.FetchResult("ok", "Robotics workshop programme " * 20)


async def _fetch_boom(url, settings):
    raise RuntimeError("never called")


async def _summ(title, excerpt, url, settings):
    return f"A programme page for {title}, listing sessions and speakers."


def run(coro):
    return asyncio.run(coro)


def _backfill(memory, settings, **kw):
    """Every Task-1 call pins ``recon_limit=0``: the recon tier is Task 2's, and
    an omitted limit would reach the real ``default_extract`` once it lands."""
    kw.setdefault("recon_limit", 0)
    return run(link_enrichment.backfill(memory, settings, **kw))


# --- classify_page ---------------------------------------------------------

def test_classify_page_interstitials_and_login_walls():
    assert link_enrichment.classify_page("Before you continue to Google Search", "https://www.google.com/search?q=x") == "interstitial"
    assert link_enrichment.classify_page("Antes de continuar", "https://consent.google.com/m?x") == "interstitial"
    assert link_enrichment.classify_page("Sign in - Example", "https://example.com/") == "login_wall"
    assert link_enrichment.classify_page("Anything", "https://accounts.google.com/signin/v2") == "login_wall"
    assert link_enrichment.classify_page("Dashboard", "https://app.example.com/login?next=/") == "login_wall"
    assert link_enrichment.classify_page("Robotics Conf List", "https://robotics.example/conf") is None
    assert link_enrichment.classify_page("", "") is None


# --- scan + ordering -------------------------------------------------------

def test_scan_orders_reuse_before_fetch_oldest_first_and_skips_done(tmp_path):
    memory = _bank(tmp_path)
    _media(memory, "media-new-thin", "New Thin", "https://example.com/new", saved_at="2026-08-01")
    _media(memory, "media-old-thin", "Old Thin", "https://example.com/old", saved_at="2026-01-01")
    _media(memory, "media-old-rich", "Old Rich", "https://example.com/rich", saved_at="2026-02-01", description=LONG)
    _media(memory, "media-new-rich", "New Rich", "https://example.com/rich2", saved_at="2026-07-01", description=LONG)
    _media(memory, "media-yt", "A Video", "https://www.youtube.com/watch?v=abc", saved_at="2025-01-01")
    _media(memory, "media-consent", "Before you continue to Google Search", "https://www.google.com/search", saved_at="2025-01-01")
    scan = link_enrichment.scan_backfill(memory, _settings(memory), today=date(2026, 9, 2))
    assert [c.media_id for c in scan.reuse] == ["media-old-rich", "media-new-rich"]
    assert [c.media_id for c in scan.fetch] == ["media-old-thin", "media-new-thin"]
    assert [p.stem for p, kind in scan.junk] == ["media-consent"]
    assert scan.junk[0][1] == "interstitial"


def test_scan_respects_fetch_backoff_and_retries_after_30_days(tmp_path):
    memory = _bank(tmp_path)
    today = date(2026, 9, 2)
    _media(memory, "media-recent-fail", "Recent Fail", "https://example.com/a", saved_at="2026-01-01",
           extra_fm={"fetch_status": "failed:ConnectError", "fetch_attempted_at": str(today - timedelta(days=5))})
    _media(memory, "media-old-fail", "Old Fail", "https://example.com/b", saved_at="2026-01-02",
           extra_fm={"fetch_status": "blocked", "fetch_attempted_at": str(today - timedelta(days=31))})
    # Legacy in-cycle marker alone is NOT a reason to skip (R1): no describes claim => still a candidate.
    _media(memory, "media-legacy", "Legacy", "https://example.com/c", saved_at="2026-01-03",
           extra_fm={"enrichment_attempted": True, "enrichment_status": "no_description"})
    scan = link_enrichment.scan_backfill(memory, _settings(memory), today=today)
    assert [c.media_id for c in scan.fetch] == ["media-old-fail", "media-legacy"]
    assert scan.backoff == 1


# --- the driver ------------------------------------------------------------

def test_reuse_tier_is_zero_llm_and_authored_cicada(tmp_path):
    memory = _bank(tmp_path, git=True)
    _media(memory, "media-old-rich", "Old Rich", "https://example.com/rich", saved_at="2026-02-01", description=LONG)
    _seed_commit(memory)
    report = _backfill(memory, _settings(memory), limit=20,
                                          summarize_fn=None, fetch_fn=_fetch_boom)
    assert (report.selected, report.reused, report.summarized, report.fetched, report.failed) == (1, 1, 0, 0, 0)
    assert report.llm_calls == 0 and report.remaining == 0
    claim = [c for c in _claims(memory, "media-old-rich") if c.predicate == "describes"][0]
    assert claim.authored_by == "cicada" and claim.origin == "sleep/link_enrichment"
    assert claim.source_episodes == ["ep_2026-02-01_001"]
    assert _fm(memory, "media-old-rich")["enrichment_attempted"] is True
    log = _git_log(memory)
    assert log.startswith("Link enrichment ")
    assert "entities/media-old-rich.md: enriched (source: ep_2026-02-01_001, trigger: sleep/link_enrichment)" in log
    assert "Cicada-Author: cicada" in log
    assert "Cicada-Engine:" not in log
    assert report.commit


def test_fetch_tier_writes_description_section_and_model_authored_claim(tmp_path):
    memory = _bank(tmp_path, git=True)
    _media(memory, "media-old-thin", "Old Thin", "https://example.com/old", saved_at="2026-01-01")
    _seed_commit(memory)
    report = _backfill(memory, _settings(memory), limit=20,
                                          summarize_fn=_summ, fetch_fn=_fetch_ok, engine="litellm")
    assert (report.reused, report.fetched, report.summarized, report.failed) == (0, 1, 1, 0)
    assert report.llm_calls == 1
    parsed = markdown_parser.parse(memory / "entities" / "media-old-thin.md")
    assert "## Description\nA programme page for Old Thin" in parsed.body
    assert parsed.body.index("## Summary") < parsed.body.index("## Description") < parsed.body.index("```claims")
    assert parsed.frontmatter["description_source"] == "summary"
    assert parsed.frontmatter["fetch_status"] == "ok"
    assert parsed.frontmatter["fetch_attempted_at"] == str(date.today())
    claim = [c for c in parse_claims(parsed.body) if c.predicate == "describes"][0]
    assert claim.authored_by == "gpt-5.4-mini"
    log = _git_log(memory)
    assert "Cicada-Author: gpt-5.4-mini" in log and "Cicada-Engine: litellm" in log


def test_failed_and_blocked_fetches_are_recorded_never_raised(tmp_path):
    memory = _bank(tmp_path)
    _media(memory, "media-a", "A", "https://example.com/a", saved_at="2026-01-01")
    _media(memory, "media-b", "B", "https://example.com/b", saved_at="2026-01-02")
    _media(memory, "media-c", "C", "https://example.com/c", saved_at="2026-01-03")
    statuses = {"https://example.com/a": "failed:http_500", "https://example.com/b": "blocked"}

    async def fetch(url, settings):
        if url == "https://example.com/c":
            raise RuntimeError("socket exploded")
        return link_enrichment.FetchResult(statuses[url])

    report = _backfill(memory, _settings(memory), limit=20,
                                          summarize_fn=_summ, fetch_fn=fetch, commit=False)
    assert report.failed == 3 and report.summarized == 0 and report.llm_calls == 0
    assert _fm(memory, "media-a")["fetch_status"] == "failed:http_500"
    assert _fm(memory, "media-b")["fetch_status"] == "blocked"
    assert _fm(memory, "media-c")["fetch_status"] == "failed:RuntimeError"
    assert all(_fm(memory, s)["fetch_attempted_at"] == str(date.today()) for s in ("media-a", "media-b", "media-c"))
    # In backoff now: a second run selects nothing and reports them as remaining-but-deferred.
    again = _backfill(memory, _settings(memory), limit=20,
                                         summarize_fn=_summ, fetch_fn=_fetch_boom, commit=False)
    assert again.selected == 0 and again.remaining == 0 and again.deferred == 3


def test_engine_failure_aborts_llm_tier_without_marking_pages(tmp_path):
    from api.services import engine_errors

    memory = _bank(tmp_path)
    _media(memory, "media-a", "A", "https://example.com/a", saved_at="2026-01-01")
    _media(memory, "media-b", "B", "https://example.com/b", saved_at="2026-01-02")
    calls = []

    async def summ(title, excerpt, url, settings):
        calls.append(title)
        raise engine_errors.EngineUnavailable("signed out")

    report = _backfill(memory, _settings(memory), limit=20,
                                          summarize_fn=summ, fetch_fn=_fetch_ok, commit=False)
    assert calls == ["A"]                       # aborted after the first engine failure
    assert report.engine_aborted == "EngineUnavailable"
    assert report.summarized == 0 and report.failed == 0
    assert not [c for c in _claims(memory, "media-a") if c.predicate == "describes"]
    assert _fm(memory, "media-b").get("fetch_attempted_at") is None   # never reached
    assert report.remaining == 2


def test_summarize_excerpt_reraises_engine_failures_but_swallows_page_failures(monkeypatch):
    """R9 seam change: the production summarizer must let an ENGINE failure
    propagate (so the driver aborts and leaves pages unmarked) while a
    page-level failure (bad response, parse error) still degrades to None."""
    from api.services import engine_errors, providers

    def _resolver_raising(exc):
        def resolve(settings, **kw):
            async def llm_fn(**kw2):
                raise exc
            return llm_fn
        return resolve

    monkeypatch.setattr(providers, "resolve_llm_fn", _resolver_raising(engine_errors.EngineUnavailable("signed out")))
    with pytest.raises(engine_errors.EngineUnavailable):
        run(link_enrichment._summarize_excerpt("T", "excerpt text", "https://example.com/x", _settings(Path("/x"))))
    monkeypatch.setattr(providers, "resolve_llm_fn", _resolver_raising(ValueError("malformed response")))
    assert run(link_enrichment._summarize_excerpt("T", "excerpt text", "https://example.com/x", _settings(Path("/x")))) is None


def test_junk_pages_are_marked_free_and_never_count_against_limit(tmp_path):
    memory = _bank(tmp_path)
    _media(memory, "media-consent", "Before you continue to Google Search", "https://www.google.com/search", saved_at="2025-01-01")
    _media(memory, "media-login", "Sign in", "https://example.com/login", saved_at="2025-01-02")
    _media(memory, "media-old-rich", "Old Rich", "https://example.com/rich", saved_at="2026-02-01", description=LONG)
    report = _backfill(memory, _settings(memory), limit=1, summarize_fn=None, fetch_fn=None, commit=False)
    assert report.skipped == 2 and report.selected == 1 and report.reused == 1
    fm = _fm(memory, "media-consent")
    assert fm["enrichment_status"] == "junk" and fm["fetch_status"] == "skipped:interstitial"
    assert _fm(memory, "media-login")["fetch_status"] == "skipped:login_wall"
    # Idempotent: nothing left to do.
    again = _backfill(memory, _settings(memory), limit=20, summarize_fn=None, fetch_fn=None, commit=False)
    assert again.selected == 0 and again.skipped == 0 and again.remaining == 0


def test_limit_and_remaining_and_second_run_resumes(tmp_path):
    memory = _bank(tmp_path)
    for i in range(5):
        _media(memory, f"media-r{i}", f"Rich {i}", f"https://example.com/{i}", saved_at=f"2026-01-0{i + 1}", description=LONG)
    first = _backfill(memory, _settings(memory), limit=2, summarize_fn=None, fetch_fn=None, commit=False)
    assert first.selected == 2 and first.remaining == 3
    assert [c.predicate for c in _claims(memory, "media-r0")] == ["describes"]
    assert not _claims(memory, "media-r2")
    second = _backfill(memory, _settings(memory), limit=10, summarize_fn=None, fetch_fn=None, commit=False)
    assert second.selected == 3 and second.remaining == 0
    third = _backfill(memory, _settings(memory), limit=10, summarize_fn=None, fetch_fn=None, commit=False)
    assert third.selected == 0


def test_kill_switch_and_no_git_are_safe(tmp_path):
    memory = _bank(tmp_path)
    _media(memory, "media-old-rich", "Old Rich", "https://example.com/rich", saved_at="2026-02-01", description=LONG)
    off = _backfill(memory, _settings(memory, link_enrich_enabled=False), limit=20)
    assert off.selected == 0 and not _claims(memory, "media-old-rich")
    # Not a git repo: the writes still land, the commit is skipped with a warning, nothing raises.
    on = _backfill(memory, _settings(memory), limit=20)
    assert on.reused == 1 and on.commit is None


def test_progress_marker_is_written_outside_the_bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    _media(memory, "media-old-rich", "Old Rich", "https://example.com/rich", saved_at="2026-02-01", description=LONG)
    _backfill(memory, _settings(memory), limit=20, commit=False)
    marker = tmp_path / "home" / "link_enrich" / "memory.json"
    data = json.loads(marker.read_text())
    assert data["reused"] == 1 and data["remaining"] == 0 and data["last_run"]
    assert not list(memory.rglob("*.json"))   # nothing derived inside the bank


def test_upsert_description_preserves_claims_block_and_other_sections():
    body = "## Summary\nS.\n\n## Notes\nN.\n\n```claims\n- id: clm_x\n  text: t\n```\n"
    out = link_enrichment._upsert_description(body, "New description.")
    assert out.index("## Summary") < out.index("## Description\nNew description.") < out.index("## Notes") < out.index("```claims")
    again = link_enrichment._upsert_description(out, "Replaced.")
    assert "New description." not in again and "## Description\nReplaced." in again
    assert again.count("```claims") == 1 and "## Notes\nN." in again


def test_in_cycle_candidates_now_skip_junk(tmp_path):
    memory = _bank(tmp_path)
    _media(memory, "media-consent", "Before you continue to Google Search", "https://www.google.com/search", saved_at="2025-01-01")
    _media(memory, "media-ok", "OK", "https://example.com/ok", saved_at="2026-01-01")
    assert [p.stem for p in link_enrichment._candidates(memory, 20)] == ["media-ok"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_link_backfill.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'api.services.link_enrichment' has no attribute 'classify_page'` (and the rest).

- [ ] **Step 4: Implement**

In `api/services/link_enrichment.py`, extend the imports (`from __future__` stays first; `hashlib`, `Path`, `Awaitable`/`Callable`, `logger`, `markdown_parser` and the `claims` names are already there): add `import json`, `import re`, `from dataclasses import dataclass, field`, change `from datetime import date` to `from datetime import date, datetime, timedelta`, add `from urllib.parse import urlparse`, and change `from api.services import markdown_parser` to `from api.services import engine_errors, git_service, markdown_parser` (neither module imports back into `api.services` — `engine_errors` is import-free by design, `git_service` imports only `api.models.schemas` — so no cycle).

**R9 seam change — `_summarize_excerpt` (254-284):** at the top of its `except Exception as e:` block insert

```python
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
```

before the existing `logger.warning(...)` / `return None`. `_is_engine_failure` is defined further down the module (below); it resolves at call time, so the forward reference is fine.

Refactor `_candidates` (157-190): replace the four exclusion `if`s with `_excluded_media(url, mtype)` and add a junk skip. Then append the backfill section:

```python
def _excluded_media(url: str, mtype: str) -> bool:
    """Media this module never fetches: YouTube/video (oEmbed only, no page
    text), Instagram (login-walled), LinkedIn (ToS §8.2 — G71 §3 fix round).
    Shared by the in-cycle ``_candidates`` and the backfill scan so the two
    can never disagree about what is off-limits."""
    url = (url or "").lower()
    mtype = (mtype or "").lower()
    if mtype in ("youtube", "video") or "youtube.com" in url or "youtu.be" in url:
        return True
    return "instagram.com" in url or "linkedin.com" in url
```

and in `_candidates`, after computing `url`: `if _excluded_media(url, mtype): continue` and `if classify_page(str(fm.get("name") or ""), url) is not None: continue` (G86: a cookie banner must never be summarized).

```python
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
_LOGIN_PATH_RE = re.compile(
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
                if classify_page("", str(resp.url)) is not None:
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
        payload = {"last_run": datetime.now().isoformat(timespec="seconds"), **report.as_dict()}
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

    def _describe(cand: _Candidate, text: str, authored_by: str) -> None:
        claim = _build_describes_claim(cand.media_id, text, cand.episode, today_s, authored_by)
        _append_claim(cand.path, claim)
        _stamp(cand.path, enrichment_attempted=True)
        report.touched(
            f"entities/{cand.media_id}.md",
            f"entities/{cand.media_id}.md: enriched (source: {cand.episode or 'n/a'}, trigger: sleep/link_enrichment)",
        )

    # §2a reuse — zero LLM.
    for cand in scan.reuse[:cap]:
        _describe(cand, cand.description, "cicada")
        report.selected += 1
        report.reused += 1

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
        # the `enriched` line only once a claim actually lands.
        report.touched(f"entities/{cand.media_id}.md",
                       f"entities/{cand.media_id}.md: fetch {result.status} (source: {cand.episode or 'n/a'}, trigger: sleep/link_enrichment)")
        if result.status != "ok" or not result.text:
            report.failed += 1
            continue
        report.fetched += 1
        try:
            report.llm_calls += 1
            summary = await summarize_fn(cand.title, result.text, cand.url, settings)
        except Exception as e:
            if _is_engine_failure(e):
                report.engine_aborted = type(e).__name__
                logger.warning(f"link summarize engine failure — leaving pages unmarked: {type(e).__name__}: {e}")
                report.selected -= 1
                break
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
        _describe(cand, summary, model)
        report.summarized += 1

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
```

The `report.selected -= 1` on an engine abort keeps `selected` honest (that page was not processed). The `fetch <status>` manifest action (e.g. `fetch failed:http_500`) is safe for the history readers: `git_service` matches an entity's manifest line by its `entities/<id>.md:` prefix (`git_service.py:238`), not by an action-word regex, so a status token with a colon in it neither breaks parsing nor is mistaken for a trailer.

- [ ] **Step 5: Run the new tests plus the existing enrichment/sleep tests**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_link_backfill.py api/tests/test_link_enrichment.py api/tests/test_sleep_connector_poll.py api/tests/test_sleep_cycle_logo_warmup.py -q -p no:cacheprovider`
Expected: all PASS. If `test_upsert_description_preserves_claims_block_and_other_sections` fails on whitespace, fix `_upsert_description`, not the test: the invariant is order + one claims fence + every other section intact.

- [ ] **Step 6: Commit**

```bash
cd <worktree>/ && git add api/config.py api/services/link_enrichment.py api/tests/test_link_backfill.py && git commit -m "feat(links): backfill describes claims over existing media pages — oldest-first, junk-aware, dated fetch backoff, one scoped commit (G102 cheap slice, part 1)"
```

---

### Task 2: G102 recon — batched extraction → Stage-2 match → `about` claims + edges

**Files:**
- Create: `api/services/link_recon.py`
- Modify: `api/services/entity_resolver.py` (add `existing_by_name`, `match_existing` after `resolve`; no change to `resolve`)
- Modify: `api/services/link_enrichment.py` (`_run_recon` delegates to `link_recon.run_recon`)
- Test: `api/tests/test_link_recon.py` (new)

**Interfaces:**
- Produces: `entity_resolver.existing_by_name(existing: list[dict]) -> dict[str, dict]`; `entity_resolver.match_existing(entity, existing_by_name, settings, *, cache=None) -> str | None`; `link_recon.render_batch(links: list[LinkCard]) -> str`; `link_recon.attribute(entities, links) -> dict[str, list[dict]]` (media_id → entities); `link_recon.scan_recon(memory_path, settings) -> list[LinkCard]`; `link_recon.run_recon(memory_path, settings, report, *, limit, extract_fn, match_fn, indexer_factory, engine, today) -> None` (mutates `report.extracted/related/llm_calls/judge_calls/remaining_recon/engine_aborted` and calls `report.touched`); `link_recon.default_extract(text, settings) -> list[dict]`.
- `ExtractFn = Callable[[str, object], Awaitable[list[dict]]]`, `MatchFn = Callable[[dict, dict, object, dict], Awaitable[str | None]]`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_link_recon.py
"""G102 cheap slice — recon over stored title+description: batched Stage-1
extraction, Stage-2 MATCH (never create), `about` claims on the media page,
edges via Stage 5.7. Hermetic: extract/match/indexer all injected."""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.services import entity_resolver, link_enrichment, link_recon, markdown_parser
from api.services.claims import parse_claims

# `api/tests/` is not a package and no test imports another, so the three
# fixture helpers are repeated here rather than imported from test_link_backfill.


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _settings(memory: Path, **over):
    base = dict(
        memory_path=memory, litellm_model="gpt-5.4-mini", litellm_disambiguation_model="gpt-5.4-nano",
        llm_mode="byok", link_enrich_enabled=True, link_enrich_max_per_cycle=20, link_enrich_min_desc_len=120,
        link_enrich_excerpt_chars=2000, link_enrich_backfill_per_cycle=20, link_enrich_fetch_retry_days=30,
        link_recon_batch_size=8, link_recon_max_per_cycle=40,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _media(memory: Path, stem: str, name: str, url: str, *, saved_at: str, description: str = ""):
    fm = {
        "name": name, "type": "media", "status": "active", "confidence": 0.7,
        "created": saved_at, "last_referenced": saved_at, "saved_at": saved_at,
        "source_episodes": [f"ep_{saved_at}_001"], "tags": ["bookmark"], "related": [],
        "media": {"url": url, "media_type": "bookmark", "site": "example.com"},
    }
    body = f"## Summary\nSaved bookmark — {name}."
    if description:
        body += f"\n\n## Description\n{description}"
    markdown_parser.write(memory / "entities" / f"{stem}.md", fm, body)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    return memory


def _fm(memory: Path, stem: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{stem}.md").frontmatter


def run(coro):
    return asyncio.run(coro)


def _entity(memory: Path, stem: str, name: str, etype: str = "concept"):
    markdown_parser.write(memory / "entities" / f"{stem}.md",
                          {"name": name, "type": etype, "status": "active", "confidence": 0.8,
                           "created": "2026-01-01", "last_referenced": "2026-05-01", "related": []},
                          f"## Summary\n{name}.")


ROBOTICS = ("A curated list of robotics conferences and workshops for graduate researchers, "
            "with submission deadlines, ROS tutorials and location details.")
GRAPHS = ("An introduction to knowledge graphs for personal memory systems, comparing "
          "Neo4j with plain markdown and wikilinks for small-scale use.")


class _Spy:
    def __init__(self):
        self.pending = []
        self.rebuilt = 0

    def index_pending_entity(self, entity):
        self.pending.append(entity)

    def rebuild_pending_index(self):
        self.rebuilt += 1
        return len(self.pending)


def _extract_fixed(entities):
    calls = []

    async def extract(text, settings):
        calls.append(text)
        return entities

    extract.calls = calls
    return extract


async def _match_direct(entity, existing_by_name, settings, cache):
    hit = existing_by_name.get((entity.get("name") or "").lower())
    return hit["id"] if hit else None


def test_render_batch_clips_and_numbers():
    cards = [link_recon.LinkCard(media_id=f"media-{i}", title=f"T{i}", url=f"https://example.com/{i}",
                                 description="word " * 400, episode="ep") for i in range(2)]
    text = link_recon.render_batch(cards)
    assert "[1] Title: T0" in text and "[2] Title: T1" in text
    assert text.count("word") <= 2 * link_recon.MAX_WORDS_PER_LINK + 2


def test_attribute_by_surface_form_drops_ungrounded_entities():
    cards = [link_recon.LinkCard("media-a", "Robotics Conf List", "https://a", ROBOTICS, "ep1"),
             link_recon.LinkCard("media-b", "Graph Intro", "https://b", GRAPHS, "ep2")]
    ents = [{"name": "ROS", "type": "tool", "aliases": []},
            {"name": "Knowledge Graphs", "type": "concept", "aliases": ["knowledge graph"]},
            {"name": "Neo4j", "type": "tool", "aliases": []},
            {"name": "Bob Example", "type": "person", "aliases": []},      # never on either card
            {"name": "Prefers concise", "type": "skill", "aliases": []}]   # type never related
    out = link_recon.attribute(ents, cards)
    assert [e["name"] for e in out["media-a"]] == ["ROS"]
    assert [e["name"] for e in out["media-b"]] == ["Knowledge Graphs", "Neo4j"]


def test_recon_relates_existing_entities_and_candidates_the_rest(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "ros", "ROS", "tool")
    _entity(memory, "knowledge-graphs", "Knowledge Graphs", "concept")
    _media(memory, "media-a", "Robotics Conf List", "https://a.example", saved_at="2026-01-01", description=ROBOTICS)
    _media(memory, "media-b", "Graph Intro", "https://b.example", saved_at="2026-01-02", description=GRAPHS)
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "ros", "target": "knowledge-graphs", "label": "used with"}]}))
    extract = _extract_fixed([
        {"name": "ROS", "type": "tool", "confidence": 0.9, "aliases": [], "summary": "Robot Operating System"},
        {"name": "Knowledge Graphs", "type": "concept", "confidence": 0.8, "aliases": ["knowledge graph"]},
        {"name": "Neo4j", "type": "tool", "confidence": 0.6, "aliases": []},
    ])
    spy = _Spy()
    report = run(link_enrichment.backfill(
        memory, _settings(memory), limit=20, extract_fn=extract, match_fn=_match_direct,
        indexer_factory=lambda memory_path: spy, engine="litellm", commit=False))
    assert len(extract.calls) == 1 and "[2] Title: Graph Intro" in extract.calls[0]
    assert report.extracted == 3 and report.related == 2 and report.llm_calls == 1
    about_a = [c for c in parse_claims(markdown_parser.parse(memory / "entities" / "media-a.md").body) if c.predicate == "about"]
    assert [(c.object, c.object_kind, c.observer, c.source_trust, c.origin) for c in about_a] == \
        [("ros", "node", "agent", "agent_extracted", "sleep/link_recon")]
    assert about_a[0].confidence == 0.7 and about_a[0].source_episodes == ["ep_2026-01-01_001"]
    assert about_a[0].authored_by == "gpt-5.4-mini"
    assert _fm(memory, "media-a")["related"] == ["ros"]
    assert _fm(memory, "media-b")["related"] == ["knowledge-graphs"]
    assert _fm(memory, "media-a")["recon_attempted"] == str(date.today())
    # Target pages untouched (R6): no related entry, no last_referenced bump.
    assert _fm(memory, "ros")["related"] == [] and str(_fm(memory, "ros")["last_referenced"]) == "2026-05-01"
    # Neo4j matched nothing -> candidate, never a page.
    assert [p.name for p in spy.pending] == ["Neo4j"] and spy.rebuilt == 1
    assert not (memory / "entities" / "neo4j.md").exists()
    # Stage 5.7 projected the claims into edges and kept the non-claim edge.
    edges = yaml.safe_load((memory / "graph_edges.yaml").read_text())["edges"]
    assert {"source": "ros", "target": "knowledge-graphs", "label": "used with"} in edges
    assert any(e["source"] == "media-a" and e["target"] == "ros" and e["label"] == "about" and e.get("claim_id") for e in edges)
    assert "graph_edges.yaml: updated (trigger: sleep/link_recon)" in report.manifest
    assert "entities/media-a.md: related (source: ep_2026-01-01_001, trigger: sleep/link_recon)" in report.manifest


def test_recon_is_idempotent_and_capped(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "ros", "ROS", "tool")
    for i in range(3):
        _media(memory, f"media-{i}", f"Robotics {i}", f"https://{i}.example", saved_at=f"2026-01-0{i + 1}", description=ROBOTICS)
    extract = _extract_fixed([{"name": "ROS", "type": "tool", "confidence": 0.9}])
    s = _settings(memory, link_recon_batch_size=2)
    first = run(link_enrichment.backfill(memory, s, limit=20, recon_limit=2, extract_fn=extract,
                                         match_fn=_match_direct, indexer_factory=lambda p: None, commit=False))
    assert len(extract.calls) == 1 and first.related == 2 and first.remaining_recon == 1
    second = run(link_enrichment.backfill(memory, s, limit=20, recon_limit=10, extract_fn=extract,
                                          match_fn=_match_direct, indexer_factory=lambda p: None, commit=False))
    assert len(extract.calls) == 2 and second.related == 1 and second.remaining_recon == 0
    third = run(link_enrichment.backfill(memory, s, limit=20, extract_fn=extract, match_fn=_match_direct,
                                         indexer_factory=lambda p: None, commit=False))
    assert len(extract.calls) == 2 and third.related == 0
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "media-0.md").body)
    assert len([c for c in claims if c.predicate == "about"]) == 1


def test_recon_skips_thin_descriptions_and_survives_an_engine_failure(tmp_path):
    from api.services import engine_errors

    memory = _bank(tmp_path)
    _media(memory, "media-thin", "Thin", "https://t.example", saved_at="2026-01-01", description="Short.")
    _media(memory, "media-rich", "Rich", "https://r.example", saved_at="2026-01-02", description=ROBOTICS)

    async def extract(text, settings):
        raise engine_errors.EngineThrottled("429")

    report = run(link_enrichment.backfill(memory, _settings(memory), limit=20, extract_fn=extract,
                                          match_fn=_match_direct, indexer_factory=lambda p: None, commit=False))
    assert report.engine_aborted == "EngineThrottled" and report.related == 0
    assert "recon_attempted" not in _fm(memory, "media-rich")   # unmarked: still a candidate
    assert report.remaining_recon == 1


def test_match_existing_uses_direct_then_llm_and_never_creates(tmp_path, monkeypatch):
    existing = entity_resolver.existing_by_name([
        {"id": "knowledge-graphs", "frontmatter": {"name": "Knowledge Graphs", "type": "concept"}, "body": "## Summary\nKG."},
    ])
    s = _settings(tmp_path)
    run_ = asyncio.run
    assert run_(entity_resolver.match_existing({"name": "knowledge graphs", "type": "concept"}, existing, s)) == "knowledge-graphs"

    async def judge(**kwargs):
        return "same" if kwargs["new_name"] == "Knowledge Graph Systems" else "unsure"

    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    cache: dict = {}
    assert run_(entity_resolver.match_existing({"name": "Knowledge Graph Systems", "type": "concept"}, existing, s, cache=cache)) == "knowledge-graphs"
    assert run_(entity_resolver.match_existing({"name": "Graphs Weekly", "type": "concept"}, existing, s, cache=cache)) is None
    assert run_(entity_resolver.match_existing({"name": "Knowledge Base", "type": "tool"}, existing, s, cache=cache)) is None  # type gate
    assert not list(tmp_path.rglob("*.md"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_link_recon.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.link_recon'`.

- [ ] **Step 3: Add the public matcher to `entity_resolver.py`**

After `resolve()` (before `_specificity_key`, line ~383):

```python
def existing_by_name(existing: list[dict]) -> dict[str, dict]:
    """The ``name.lower() -> entity`` index ``resolve`` builds at its top (the
    four lines at the head of that function), exposed so a caller that only
    needs the Stage-2 *judgment* (G102 recon) indexes the graph the same way."""
    out: dict[str, dict] = {}
    for e in existing:
        name = e["frontmatter"].get("name", e["id"].replace("-", " ").title())
        out[str(name).lower()] = e
    return out


async def match_existing(
    entity: dict, existing_by_name: dict[str, dict], settings: Settings, *, cache: dict | None = None
) -> str | None:
    """Is ``entity`` an EXISTING page? The Stage-2 judgment alone (G102 R5).

    Exactly the two matchers ``resolve`` runs per name — the strict/fuzzy
    ``_find_direct_candidate_match`` then the type-gated, token-gated
    ``_find_llm_candidate_match`` with the same judge and cache — and nothing
    else: no promotion, no page creation, no clarification. Returns the
    existing id only on a ``same`` verdict against an on-disk entity;
    ``unsure`` is ``None`` (a bookmark blurb must never open a "Who is X?"
    inbox item), and a first mention is left to the caller to record as a
    pending candidate — the promotion model's rung 1 — so a later
    conversation mention still promotes it.
    """
    cache = cache if cache is not None else {}
    match = _find_direct_candidate_match(new_entity=entity, existing_by_name=existing_by_name, created_by_id={})
    if match is None:
        match = await _find_llm_candidate_match(
            new_entity=entity, existing_by_name=existing_by_name, created_by_id={}, cache=cache, settings=settings,
        )
    if match is not None and match["decision"] == "same" and match["candidate"].get("source") == "existing":
        return match["candidate"]["id"]
    return None
```

- [ ] **Step 4: Create `api/services/link_recon.py`**

```python
"""G102 cheap slice — site recon over the OG text ALREADY STORED on a media page.

The G102 ruling: a summary is a nicer card; what makes a saved link part of
the graph is running entity extraction over what the page is about and
routing the mentions through Stage-2 resolution, so a bookmark gets edges to
the concepts, tools, companies and people it concerns. This module is the
zero-new-fetch first slice: the EXISTING Stage-1 prompt over ``title +
## Description`` (OpenGraph at ingest, or a backfill summary), batched
``link_recon_batch_size`` links per call (R4), attributed back to each link
by surface form, matched against existing entities with the EXISTING Stage-2
judgment (``entity_resolver.match_existing``, R5) and written as ``about``
claims on the media page (R6) that Stage 5.7 projects into edges. The target
page is never touched — a blurb mentioning a tool is not the user referencing
it. Unmatched mentions become pending candidates, never pages.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import engine_errors, markdown_parser
from api.services.claims import Claim

MAX_WORDS_PER_LINK = 300
RELATABLE_TYPES = frozenset({"person", "project", "company", "concept", "tool", "location"})

ExtractFn = Callable[[str, object], Awaitable[list[dict]]]
MatchFn = Callable[[dict, dict, object, dict], Awaitable[str | None]]


@dataclass
class LinkCard:
    media_id: str
    title: str
    url: str
    description: str
    episode: str

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}"


def _clip_words(text: str, n: int) -> str:
    words = (text or "").split()
    return " ".join(words[:n]) + (" …" if len(words) > n else "")


def render_batch(cards: list[LinkCard]) -> str:
    """The 'transcript' the Stage-1 prompt is shown: one numbered card per link."""
    parts = [
        "Saved links the user bookmarked. For each one: the page title, its URL, and "
        "the page's own description. Extract the entities these pages are ABOUT."
    ]
    for i, c in enumerate(cards, 1):
        parts.append(f"[{i}] Title: {c.title}\nURL: {c.url}\nDescription: {_clip_words(c.description, MAX_WORDS_PER_LINK)}")
    return "\n\n".join(parts)


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


def _mentions(surface: str, haystack_tokens: set[str], haystack_text: str) -> bool:
    """Whole-token match — never a bare substring: "ROS" must not be found
    inside "prose", nor "Go" inside "Google". A multi-word surface may also
    match as an exact phrase so "knowledge graph" grounds against
    "knowledge-graph"."""
    toks = _tokens(surface)
    if not toks:
        return False
    if len(toks) >= 2 and surface.strip().lower() in haystack_text:
        return True
    return all(t in haystack_tokens for t in toks)


def attribute(entities: list[dict], cards: list[LinkCard]) -> dict[str, list[dict]]:
    """media_id -> entities whose name/alias appears on that card (R4).

    The prompt has no per-link attribution, so grounding is literal: an
    entity is attributed to every card whose ``title + description`` contains
    its name or an alias (case-folded substring, or every name token
    present). An entity on no card is dropped — that is also the
    hallucination rail. ``skill``/``directory`` are never related.
    """
    out: dict[str, list[dict]] = {c.media_id: [] for c in cards}
    prepared = [(c, set(_tokens(c.text)), c.text.lower()) for c in cards]
    for ent in entities:
        if str(ent.get("type") or "").lower() not in RELATABLE_TYPES:
            continue
        surfaces = [str(ent.get("name") or "")] + [str(a) for a in (ent.get("aliases") or [])]
        for card, toks, text in prepared:
            if any(_mentions(s, toks, text) for s in surfaces):
                out[card.media_id].append(ent)
    return out


def scan_recon(memory_path: Path, settings) -> list[LinkCard]:
    """Media pages with a substantive ``## Description`` and no ``recon_attempted``,
    oldest-imported first — its own scan (R2) so a link whose description
    landed in an earlier run is still picked up."""
    from api.services.link_enrichment import (
        _excluded_media, _extract_description_section, _is_substantive, _saved_sort_key, classify_page,
    )

    min_len = int(getattr(settings, "link_enrich_min_desc_len", 120) or 120)
    entities_dir = Path(memory_path) / "entities"
    cards: list[tuple[str, LinkCard]] = []
    if not entities_dir.exists():
        return []
    for fp in sorted(entities_dir.glob("media-*.md")):
        try:
            parsed = markdown_parser.parse(fp)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        if fm.get("type") != "media" or fm.get("recon_attempted") or fm.get("enrichment_status") == "junk":
            continue
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        url = str(media.get("url") or "")
        title = str(fm.get("name") or fp.stem)
        if _excluded_media(url, str(media.get("media_type") or "")) or classify_page(title, url):
            continue
        desc = _extract_description_section(parsed.body)
        if not _is_substantive(desc, min_len):
            continue
        episodes = fm.get("source_episodes") or []
        cards.append((_saved_sort_key(fm), LinkCard(fp.stem, title, url, desc, str(episodes[0]) if episodes else "")))
    cards.sort(key=lambda t: (t[0], t[1].media_id))
    return [c for _, c in cards]


def _build_about_claim(media_id: str, target_id: str, target_name: str, confidence: float,
                       episode: str, today: str, model: str) -> Claim:
    return Claim(
        id=f"clm_about_{hashlib.sha1(f'{media_id}\x00{target_id}'.encode()).hexdigest()[:8]}",
        text=f"This saved page is about {target_name}.",
        subject=media_id, predicate="about", object=target_id, object_kind="node",
        observer="agent", context="general", epistemic="explicit", source_trust="agent_extracted",
        confidence=round(min(float(confidence or 0.5), 0.7), 2),
        valid_from=today, recorded_at=today,
        source_episodes=[episode] if episode else [],
        authored_by=model or "unknown", origin="sleep/link_recon",
    )


async def default_extract(text: str, settings) -> list[dict]:
    """One Stage-1 call over a rendered batch — the SAME prompt, engine seam,
    one-retry policy and telemetry as the cycle's extraction — through the
    per-chunk ``entity_extractor._extract_chunk``, deliberately NOT the public
    ``extract``: ``extract`` catches every engine failure per episode
    (``entity_extractor.py:378-406``), counts it ``failed`` and drops the
    episode from its result, which here would read as "the batch contained
    no entities" and stamp ``recon_attempted`` on eight links that were never
    looked at. ``_extract_chunk`` retries a transient error once and then
    raises, which is what R9 needs. The batch is one chunk by construction
    (8 x 300 words is well under ``CHUNK_SIZE``); ``sanitize_decay_class`` is
    irrelevant here because recon never creates a page.
    """
    from api.services.entity_extractor import _extract_chunk

    parsed = await _extract_chunk("link-recon", text, 0, 1, settings)
    return [e for e in (parsed.get("entities") or []) if isinstance(e, dict)]


async def default_match(entity: dict, existing_by_name: dict, settings, cache: dict) -> str | None:
    from api.services.entity_resolver import match_existing

    return await match_existing(entity, existing_by_name, settings, cache=cache)


def _default_indexer(memory_path: Path):
    try:
        from api.services.vector_index import SqliteVecIndexer

        return SqliteVecIndexer(memory_path)
    except Exception as e:
        logger.debug(f"pending store unavailable for link recon: {e}")
        return None


async def run_recon(memory_path: Path, settings, report, *, limit=None, extract_fn=None, match_fn=None,
                    indexer_factory=None, engine=None, today: date | None = None) -> None:
    """Relate up to ``limit`` links (default ``link_recon_max_per_cycle``);
    mutates ``report`` (extracted/related/llm_calls/judge_calls/remaining_recon/
    engine_aborted, plus the manifest). Never raises."""
    from api.services import entity_resolver
    from api.services.claims import parse_claims
    from api.services.link_enrichment import _append_claim, _stamp
    from api.services.sleep_cycle import _load_existing_entities

    memory_path = Path(memory_path)
    today = today or date.today()
    cap = int(limit if limit is not None else getattr(settings, "link_recon_max_per_cycle", 40) or 40)
    batch = max(1, int(getattr(settings, "link_recon_batch_size", 8) or 8))
    cards = scan_recon(memory_path, settings)
    report.remaining_recon = max(0, len(cards) - cap)
    cards = cards[:cap]
    if not cards:
        return
    extract_fn = extract_fn or default_extract
    match_fn = match_fn or default_match
    indexer = (indexer_factory or _default_indexer)(memory_path)
    model = str(getattr(settings, "agent_model" if engine == "claude-cli" else "litellm_model", "") or "unknown")
    existing = entity_resolver.existing_by_name(
        [e for e in _load_existing_entities(memory_path) if (e["frontmatter"] or {}).get("type") != "media"]
    )
    name_of = {e["id"]: str((e["frontmatter"] or {}).get("name") or e["id"]) for e in existing.values()}
    cache: dict = {}
    pending_written = 0
    for start in range(0, len(cards), batch):
        chunk = cards[start:start + batch]
        try:
            report.llm_calls += 1
            entities = await extract_fn(render_batch(chunk), settings)
        except Exception as e:
            if isinstance(e, engine_errors.EngineError) or _looks_like_engine_failure(e):
                report.engine_aborted = type(e).__name__
                logger.warning(f"link recon engine failure — leaving pages unmarked: {type(e).__name__}: {e}")
                report.remaining_recon += len(cards) - start
                return
            logger.warning(f"link recon extraction failed for a batch: {type(e).__name__}: {e}")
            entities = []
        report.extracted += len(entities)
        by_card = attribute(entities, chunk)
        for card in chunk:
            related_ids: list[tuple[str, dict]] = []
            for ent in by_card.get(card.media_id, []):
                try:
                    before = len(cache)
                    target = await match_fn(ent, existing, settings, cache)
                    report.judge_calls += len(cache) - before
                except Exception as e:
                    if isinstance(e, engine_errors.EngineError) or _looks_like_engine_failure(e):
                        report.engine_aborted = type(e).__name__
                        logger.warning(f"link recon judge engine failure — leaving pages unmarked: {type(e).__name__}")
                        report.remaining_recon += len(cards) - start
                        return
                    target = None
                if target and target != card.media_id:
                    related_ids.append((target, ent))
                elif indexer is not None:
                    try:
                        from api.services.vector_index import PendingEntity

                        indexer.index_pending_entity(PendingEntity(
                            name=str(ent.get("name") or ""), type=str(ent.get("type") or "concept"),
                            description=str(ent.get("summary") or ent.get("description") or card.title),
                            source_episode=card.episode, confidence=float(ent.get("confidence", 0.3) or 0.3),
                            tags=list(ent.get("tags") or []), history_entries=[],
                        ))
                        pending_written += 1
                    except Exception as e:
                        logger.debug(f"pending candidate not recorded: {type(e).__name__}: {e}")
            fp = memory_path / "entities" / f"{card.media_id}.md"
            seen: set[str] = set()
            for target, ent in related_ids:
                if target in seen:
                    continue
                seen.add(target)
                claim = _build_about_claim(card.media_id, target, name_of.get(target, target),
                                           ent.get("confidence", 0.5), card.episode, today.isoformat(), model)
                if _append_claim(fp, claim):
                    report.related += 1
            parsed = markdown_parser.parse(fp)
            related = [str(r) for r in (parsed.frontmatter.get("related") or [])]
            for target in seen:
                if target not in related:
                    related.append(target)
            parsed.frontmatter["related"] = related
            parsed.frontmatter["recon_attempted"] = today.isoformat()
            parsed.frontmatter["recon_status"] = "ok" if seen else "no_matches"
            markdown_parser.write(fp, parsed.frontmatter, parsed.body)
            # Honest manifest: `related` only when an edge landed; a page that
            # matched nothing is recorded as `recon no_matches` (still a write
            # — the stamp — so it belongs in the commit's file list).
            action = "related" if seen else "recon no_matches"
            report.touched(f"entities/{card.media_id}.md",
                           f"entities/{card.media_id}.md: {action} (source: {card.episode or 'n/a'}, trigger: sleep/link_recon)")
    if indexer is not None and pending_written:
        try:
            indexer.rebuild_pending_index()
        except Exception as e:
            logger.debug(f"pending index rebuild skipped: {e}")
    if report.related:
        from api.services.graph_builder import regenerate_edges_from_claims

        edges_file = memory_path / "graph_edges.yaml"
        before = edges_file.read_bytes() if edges_file.exists() else b""
        try:
            regenerate_edges_from_claims(memory_path)
        except Exception as e:
            logger.warning(f"claim-edge regeneration after link recon failed: {type(e).__name__}: {e}")
        if edges_file.exists() and edges_file.read_bytes() != before:
            report.touched("graph_edges.yaml", "graph_edges.yaml: updated (trigger: sleep/link_recon)")


def _looks_like_engine_failure(exc: BaseException) -> bool:
    from api.services.link_enrichment import _is_engine_failure

    return _is_engine_failure(exc)
```

Then in `link_enrichment.py` replace the `_run_recon` stub body with:

```python
async def _run_recon(memory_path: Path, settings, report: BackfillReport, **kwargs) -> None:
    from api.services.link_recon import run_recon

    try:
        await run_recon(memory_path, settings, report, **kwargs)
    except Exception as e:  # the driver's contract: never raise
        logger.warning(f"link recon failed: {type(e).__name__}: {e}")
```

Note the `judge_calls` accounting piggybacks on the judge cache growing by one entry per LLM verdict (`_find_llm_candidate_match` writes `cache[(name, id)] = decision` after each call, `entity_resolver.py:861`); an injected `match_fn` that never touches `cache` reports 0, which is correct.

`_load_existing_entities` lives in `sleep_cycle` (`sleep_cycle.py:1273-1289`); importing it lazily inside `run_recon` avoids a module-level cycle (`sleep_cycle` imports `link_enrichment` lazily too).

- [ ] **Step 5: Run the tests**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_link_recon.py api/tests/test_link_backfill.py api/tests/test_entity_resolver_transactional.py api/tests/test_claim_edge_regen.py api/tests/test_graph_claim_overlay.py -q -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd <worktree>/ && git add api/services/link_recon.py api/services/entity_resolver.py api/services/link_enrichment.py api/tests/test_link_recon.py && git commit -m "feat(links): G102 recon — batched Stage-1 extraction over stored title+description, Stage-2 match, about claims → edges; unmatched mentions become pending candidates"
```

---

### Task 3: `POST /maintenance/enrich-links?limit=N`

**Files:**
- Modify: `api/models/schemas.py` (after `MaintenanceDedupSweepResponse`, which starts at line 1261)
- Modify: `api/routers/maintenance.py`
- Test: `api/tests/test_maintenance_enrich_links.py` (new)

**Interfaces:**
- Produces: `POST /maintenance/enrich-links?limit=N&recon_limit=M` → `MaintenanceEnrichLinksResponse` (camelCase): `selected, reused, summarized, fetched, failed, skipped, extracted, related, remaining, remainingRecon, deferred, llmCalls, engineAborted, commit, engine, engineDetail`. Auth like every other endpoint (bearer, `CICADA_API_AUTH=off` in tests). `409` while a Sleep cycle is running (R11).

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_maintenance_enrich_links.py
"""Router tests for POST /maintenance/enrich-links (G102 cheap slice).
Hermetic: `link_enrichment.backfill` is monkeypatched to a spy so the router
contract (query params, engine resolution, 409 guard, response shape) is what
is under test — the driver has its own suite."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import link_enrichment, sleep_cycle


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """`engine_select.resolve_settings` reads the connections registry under
    `cicada_home()` (prefs only, for byok) — never the developer's real one."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def _spy(monkeypatch, report=None):
    calls = []

    async def fake_backfill(memory_path, settings, **kwargs):
        calls.append((memory_path, settings, kwargs))
        r = link_enrichment.BackfillReport(selected=3, reused=2, summarized=1, fetched=1, remaining=7)
        r.commit = "abc123"
        return r

    monkeypatch.setattr(link_enrichment, "backfill", fake_backfill)
    return calls


def test_endpoint_runs_backfill_with_the_live_seams_and_reports(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    calls = _spy(monkeypatch)
    resp = client.post("/maintenance/enrich-links?limit=50&recon_limit=10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["selected"], body["reused"], body["summarized"], body["fetched"], body["remaining"]) == (3, 2, 1, 1, 7)
    assert body["commit"] == "abc123" and body["engine"] == "litellm" and body["engineDetail"]
    (path, settings, kwargs), = calls
    assert path == memory and kwargs["limit"] == 50 and kwargs["recon_limit"] == 10
    # User-initiated: the LIVE fetch + summarize seams are passed, never gated (R10).
    assert kwargs["fetch_fn"] is link_enrichment.default_fetch
    assert kwargs["summarize_fn"] is link_enrichment._summarize_excerpt
    assert kwargs["engine"] == "litellm"
    config.get_settings.cache_clear()


def test_limit_defaults_to_the_per_cycle_setting_and_is_bounded(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    calls = _spy(monkeypatch)
    assert client.post("/maintenance/enrich-links").status_code == 200
    assert calls[-1][2]["limit"] == config.get_settings().link_enrich_backfill_per_cycle
    assert client.post("/maintenance/enrich-links?limit=0").status_code == 422
    assert client.post("/maintenance/enrich-links?limit=501").status_code == 422
    config.get_settings.cache_clear()


def test_409_while_a_sleep_cycle_is_running(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    calls = _spy(monkeypatch)
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    resp = client.post("/maintenance/enrich-links?limit=5")
    assert resp.status_code == 409 and calls == []
    config.get_settings.cache_clear()


def test_kill_switch_short_circuits_before_engine_resolution(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    calls = _spy(monkeypatch)
    monkeypatch.setenv("CICADA_LINK_ENRICH_ENABLED", "0")
    config.get_settings.cache_clear()

    async def boom(*a, **k):
        raise AssertionError("engine must not be resolved when the feature is off")

    monkeypatch.setattr("api.services.engine_select.resolve_settings", boom)
    resp = client.post("/maintenance/enrich-links?limit=5")
    assert resp.status_code == 200 and resp.json()["selected"] == 0 and calls == []
    config.get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_maintenance_enrich_links.py -q -p no:cacheprovider`
Expected: FAIL — `404` from the first request (no route), then the rest.

- [ ] **Step 3: Implement**

`api/models/schemas.py`, after `MaintenanceDedupSweepResponse`:

```python
class MaintenanceEnrichLinksResponse(CamelModel):
    """What one `POST /maintenance/enrich-links` run did (G102 cheap slice).
    Mirrors `link_enrichment.BackfillReport.as_dict()`; `remaining` is the
    live count of media pages still owed a description, `remainingRecon` the
    pages still owed relations, `deferred` the failed fetches inside their
    30-day backoff. `engine`/`engineDetail` say which engine the run resolved
    (a $0 run reports the configured engine but makes no call)."""
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
    engine_aborted: Optional[str] = None
    commit: Optional[str] = None
    engine: Optional[str] = None
    engine_detail: Optional[str] = None
```

`api/routers/maintenance.py` — add imports `from fastapi import APIRouter, Depends, HTTPException, Query` and `from api.models.schemas import MaintenanceEnrichLinksResponse`, then:

```python
@router.post("/maintenance/enrich-links", response_model=MaintenanceEnrichLinksResponse)
async def run_enrich_links(
    limit: int | None = Query(None, ge=1, le=500),
    recon_limit: int | None = Query(None, ge=0, le=500),
    settings: Settings = Depends(get_settings),
):
    """Describe + relate saved links now (G102 cheap slice) — the on-demand
    twin of the Sleep-tail backfill.

    User-initiated, so (R10) the live fetch + summarize seams are passed
    ungated — ``CICADA_ALLOW_CONNECTOR_FETCH`` gates only the unattended
    nightly poll, exactly the connector contract (G71 final review H2) — and
    the engine is resolved as a user-triggered cycle would resolve it, so a
    connected Claude plan is used when the owner asked for it. ``409`` while
    a Sleep cycle is running: the tail writes the same media pages (R11).
    Warm a bulk-imported bank with ``?limit=50`` a few times; each run
    reports ``remaining`` so the drain is visible.
    """
    from api.services import engine_select, link_enrichment, sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(409, "a Sleep cycle is running and writes the same media pages — retry when it finishes")
    if not settings.link_enrich_enabled:
        return MaintenanceEnrichLinksResponse()
    resolved, why = await engine_select.resolve_settings(settings, user_triggered=True)
    engine = engine_select.engine_label(resolved)
    report = await link_enrichment.backfill(
        resolved.memory_path, resolved,
        limit=limit if limit is not None else resolved.link_enrich_backfill_per_cycle,
        recon_limit=recon_limit,
        summarize_fn=link_enrichment._summarize_excerpt,
        fetch_fn=link_enrichment.default_fetch,
        engine=engine,
    )
    return MaintenanceEnrichLinksResponse(**report.as_dict(), engine=engine, engine_detail=why)
```

Also add the module docstring line: "...plus `enrich-links`, the on-demand twin of the Sleep-tail link backfill (G102)."

- [ ] **Step 4: Run the tests**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_maintenance_enrich_links.py api/tests/test_maintenance_dedup_sweep.py api/tests/test_auth.py -q -p no:cacheprovider`
Expected: all PASS (`test_auth.py` proves the new route is bearer-gated like every other non-exempt path — `auth.py`'s exemption list is untouched).

- [ ] **Step 5: Commit**

```bash
cd <worktree>/ && git add api/models/schemas.py api/routers/maintenance.py api/tests/test_maintenance_enrich_links.py && git commit -m "feat(api): POST /maintenance/enrich-links — on-demand link backfill with live counts, 409 while Sleep runs (G102)"
```

---

### Task 4: Sleep-tail step — drain `link_enrich_backfill_per_cycle` per night

**Files:**
- Modify: `api/services/sleep_cycle.py:548-601` (`_run_engine_independent_tail`), `604-713` (`run` threads `user_triggered` to the tail), new `_backfill_links_safely` beside `_poll_feeds_and_calendars_safely`
- Test: `api/tests/test_sleep_link_backfill.py` (new)

**Interfaces:**
- `_run_engine_independent_tail(memory_path, settings, outcome, *, user_triggered: bool = True)`; `_backfill_links_safely(memory_path, settings, *, user_triggered: bool) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_sleep_link_backfill.py
"""The nightly link backfill rides the Sleep cycle's engine-independent tail
(G102 cheap slice) — in the SAME clean-tree-guarded branch as the connector
and feed polls, on idle nights too. Hermetic: `link_enrichment.backfill` is a
spy; no network, no real model, no real git except where noted."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api.config import Settings
from api.services import engine_select, git_service, link_enrichment, predicates, sleep_cycle


def _empty_memory(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _settings(memory, **over):
    base = dict(memory_path=memory, litellm_model="gpt-5.4-mini", litellm_disambiguation_model="gpt-5.4-nano",
                archive_threshold=0.2, decay_nudge_threshold=0.4, link_enrich_enabled=True,
                link_enrich_backfill_per_cycle=20, link_recon_max_per_cycle=40, inbox_stale_after_days=90)
    base.update(over)
    return SimpleNamespace(**base)


def _spy(monkeypatch, *, scan=None):
    calls = []

    async def fake_backfill(memory_path, settings, **kwargs):
        calls.append((memory_path, settings, kwargs))
        return link_enrichment.BackfillReport()

    monkeypatch.setattr(link_enrichment, "backfill", fake_backfill)
    if scan is not None:
        monkeypatch.setattr(link_enrichment, "scan_backfill", lambda *a, **k: scan)
        monkeypatch.setattr("api.services.link_recon.scan_recon", lambda *a, **k: [])
    return calls


def _quiet_peers(monkeypatch):
    async def quiet(*a, **k):
        return None

    for name in ("_poll_connectors_safely", "_poll_feeds_and_calendars_safely", "_warm_logos_safely", "_refresh_questions_safely"):
        monkeypatch.setattr(sleep_cycle, name, quiet)


def test_backfill_runs_on_the_idle_early_return_with_the_per_cycle_cap(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    # One junk page owed: the step must call the driver. (A fully empty scan
    # is the "nothing owed" early return, covered below.)
    calls = _spy(monkeypatch, scan=link_enrichment._Scan(junk=[(Path("x"), "interstitial")]))
    _quiet_peers(monkeypatch)
    asyncio.run(sleep_cycle.run(_settings(memory, link_enrich_backfill_per_cycle=7), "cycle-empty"))
    (path, _, kwargs), = calls
    assert path == memory and kwargs["limit"] == 7
    assert sleep_cycle.get_sleep_state().status == "idle"


def test_zero_llm_work_never_resolves_the_engine(tmp_path, monkeypatch):
    """R10: a scan with only §2a reuse candidates (free) must not touch the
    connections registry — fix round 1, M1's idle-cycle rule stands."""
    memory = _empty_memory(tmp_path)
    scan = link_enrichment._Scan(reuse=[link_enrichment._Candidate(Path("x"), "media-x", "X", "https://x.example", "", "d", "2026")])
    calls = _spy(monkeypatch, scan=scan)
    _quiet_peers(monkeypatch)

    async def boom(*a, **k):
        raise AssertionError("resolve_settings must not run for zero-LLM work")

    monkeypatch.setattr(engine_select, "resolve_settings", boom)
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory), user_triggered=True))
    (_, _, kwargs), = calls
    assert kwargs["summarize_fn"] is None and kwargs["fetch_fn"] is None and kwargs["engine"] is None


def test_scheduled_cycle_resolves_byok_without_probing_and_passes_gated_fetch(tmp_path, monkeypatch):
    """TODO.md ruling 4: a scheduled cycle never spends plan quota."""
    memory = _empty_memory(tmp_path)
    scan = link_enrichment._Scan(fetch=[link_enrichment._Candidate(Path("x"), "media-x", "X", "https://x.example", "", "", "2026")])
    calls = _spy(monkeypatch, scan=scan)

    async def never(*a, **k):
        raise AssertionError("the registry must not be probed on a scheduled cycle")

    monkeypatch.setattr(engine_select, "_connected", never)
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "1")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    # A REAL Settings (not a SimpleNamespace) so `resolve_settings` takes the
    # `model_copy` path; `memory_path` is a computed property over
    # `memory_root`, which only the env alias sets (config.py:33-41).
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_LLM_MODE", "auto")
    settings = Settings()
    asyncio.run(sleep_cycle._backfill_links_safely(memory, settings, user_triggered=False))
    (_, resolved, kwargs), = calls
    assert resolved.llm_mode == "byok" and kwargs["engine"] == "litellm"
    assert kwargs["fetch_fn"] is link_enrichment.default_fetch
    assert kwargs["summarize_fn"] is link_enrichment._summarize_excerpt


def test_connector_gate_off_disables_only_the_fetch_tier(tmp_path, monkeypatch):
    """CICADA_ALLOW_CONNECTOR_FETCH=off (what the suite sets): no default fetch
    on the unattended tail — reuse + recon still run."""
    memory = _empty_memory(tmp_path)
    scan = link_enrichment._Scan(fetch=[link_enrichment._Candidate(Path("x"), "media-x", "X", "https://x.example", "", "", "2026")])
    calls = _spy(monkeypatch, scan=scan)
    monkeypatch.setattr(engine_select, "resolve_settings", _passthrough)
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory), user_triggered=True))
    (_, _, kwargs), = calls
    assert kwargs["fetch_fn"] is None and kwargs["summarize_fn"] is None and kwargs["engine"] == "litellm"


async def _passthrough(settings, *, user_triggered=True):
    return settings, "test"


def test_backfill_is_skipped_once_the_cycle_has_written_and_not_committed(monkeypatch):
    """Same H1 risk window as the connector/feed polls: the backfill commits
    with commit_paths (scoped), but its writes would still land on a dirty
    tree the next `_finalize` sweeps with `git add -A`."""
    calls = _spy(monkeypatch)
    _quiet_peers(monkeypatch)

    async def dirty(_path):
        return " M entities/x.md\n"

    monkeypatch.setattr(git_service, "porcelain_status", dirty)
    sleep_cycle._state.write_started = True
    try:
        asyncio.run(sleep_cycle._run_engine_independent_tail(
            Path("/nonexistent"), _settings(Path("/nonexistent")), sleep_cycle._StageOutcome(committed=False)))
    finally:
        sleep_cycle._state.write_started = False
    assert calls == []


def test_a_raising_backfill_never_fails_the_cycle(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    _quiet_peers(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(link_enrichment, "scan_backfill", boom)
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-boom"))
    assert sleep_cycle.get_sleep_state().status == "idle"
    assert sleep_cycle.get_sleep_state().error is None


def test_kill_switch_and_zero_cap_skip_the_step(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    calls = _spy(monkeypatch)
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory, link_enrich_enabled=False), user_triggered=True))
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory, link_enrich_backfill_per_cycle=0), user_triggered=True))
    assert calls == []


def test_nothing_owed_never_calls_the_driver_or_touches_cicada_home(tmp_path, monkeypatch):
    """A bank with no media page owed anything (the state of every existing
    tail test's tmp bank) must not even enter the driver: no commit attempt,
    and no progress marker under `cicada_home()` — conftest does not isolate
    CICADA_HOME, so this is what keeps those suites out of the real ~/.cicada."""
    memory = _empty_memory(tmp_path)
    calls = _spy(monkeypatch, scan=link_enrichment._Scan())
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory), user_triggered=True))
    assert calls == []
    assert not (tmp_path / "home" / "link_enrich").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_sleep_link_backfill.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'api.services.sleep_cycle' has no attribute '_backfill_links_safely'`.

- [ ] **Step 3: Implement**

In `api/services/sleep_cycle.py`, after `_poll_feeds_and_calendars_safely` (326-386, immediately before `_refresh_questions_safely` at 388):

```python
async def _backfill_links_safely(memory_path: Path, settings: Settings, *, user_triggered: bool) -> None:
    """G102 cheap slice: describe + relate ``link_enrich_backfill_per_cycle``
    saved links a night, oldest-imported first, until the bank is drained.

    Lives on the engine-independent tail — idle nights included — because
    the in-cycle Stage 5.57 pass (``enrich_media_links``, above in
    ``_run_stages``) only runs after Stage 5 on a night with episodes and
    takes the 20 MOST RECENT pages, which is why a bulk-imported bank had
    603 media pages and zero ``describes`` claims (2026-09-02). Same
    contract as its neighbours: bounded, never fatal; and it MUST sit in the
    clean-tree-guarded branch — its own commit is scoped (``commit_paths``),
    but its writes on a half-written cycle would still be swept by the next
    ``_finalize``'s ``git add -A`` under that cycle's model.

    Engine (R10 + TODO.md ruling 4): the scan runs first; when it finds only
    zero-LLM work (§2a reuse, junk) nothing is resolved and the run is
    authored ``cicada`` (fix round 1, M1: an idle cycle must not touch the
    connections registry for nothing). Only with a fetch or recon candidate
    is ``engine_select.resolve_settings`` consulted — a scheduled cycle gets
    byok before the registry is touched; a user-triggered one may probe
    cache-first. ``CICADA_ALLOW_CONNECTOR_FETCH`` gates ONLY this unattended
    step's default fetch (opt-out, the connector contract — G71 final review
    H2); reuse and recon are never gated; the maintenance endpoint is never
    gated at all.
    """
    try:
        from api.services import engine_select, link_enrichment
        from api.services.connectors.base import network_allowed
        from api.services.link_recon import scan_recon

        if not bool(getattr(settings, "link_enrich_enabled", True)):
            return
        per_cycle = int(getattr(settings, "link_enrich_backfill_per_cycle", 20) or 0)
        if per_cycle <= 0:
            return
        scan = link_enrichment.scan_backfill(memory_path, settings)
        recon_cards = scan_recon(memory_path, settings)
        if not (scan.junk or scan.reuse or scan.fetch or recon_cards):
            # Nothing owed: no write, no commit, and — deliberately — no
            # progress marker. `conftest.py` isolates the fetch/telemetry
            # gates but NOT `CICADA_HOME`, and several existing tail tests
            # run this step with a stand-in Settings that predates
            # `link_enrich_enabled`; on their empty tmp banks this return is
            # what keeps a `$CICADA_HOME/link_enrich/<bank>.json` from being
            # written into the developer's real ~/.cicada.
            return
        needs_llm = bool(scan.fetch) or bool(recon_cards)
        resolved, engine = settings, None
        if needs_llm:
            resolved, why = await engine_select.resolve_settings(settings, user_triggered=user_triggered)
            engine = engine_select.engine_label(resolved)
            logger.info(f"Link backfill engine: {engine} ({why})")
        fetch_ok = needs_llm and network_allowed()
        if needs_llm and not fetch_ok:
            logger.info('Link backfill: page fetch skipped — CICADA_ALLOW_CONNECTOR_FETCH is off (reuse + recon still run)')
        report = await link_enrichment.backfill(
            memory_path, resolved, limit=per_cycle,
            summarize_fn=link_enrichment._summarize_excerpt if fetch_ok else None,
            fetch_fn=link_enrichment.default_fetch if fetch_ok else None,
            engine=engine,
        )
        if report.selected or report.related or report.skipped:
            logger.info(
                f"Link backfill: {report.reused} reused, {report.summarized} summarized, "
                f"{report.related} related, {report.failed} failed, {report.remaining} remaining"
            )
    except Exception as e:
        logger.warning(f"Link backfill failed: {type(e).__name__}: {e}")
```

`connectors.base.network_allowed(allow_fetch: bool | None = None) -> bool` is at `api/services/connectors/base.py:59`; call it with no args so it reads `CICADA_ALLOW_CONNECTOR_FETCH` exactly as the connector poll does.

In `_run_engine_independent_tail` (line 548): add `*, user_triggered: bool = True` to the signature, extend the docstring with one paragraph ("G102: the link backfill shares this branch for the same reason as the feed poll"), and in the guarded branch after `await _poll_feeds_and_calendars_safely(memory_path)` add `await _backfill_links_safely(memory_path, settings, user_triggered=user_triggered)`. Update the `else:` warning text to "connector, feed/calendar and link-backfill steps skipped: …". In `run` (line 711) pass `user_triggered=user_triggered`.

- [ ] **Step 4: Run the tests + every Sleep suite**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_sleep_link_backfill.py api/tests/test_sleep_connector_poll.py api/tests/test_sleep_feed_poll.py api/tests/test_sleep_cycle_logo_warmup.py api/tests/test_sleep_control.py api/tests/test_sleep_resumable.py api/tests/test_sleep_engine_state.py api/tests/test_agent_provenance.py -q -p no:cacheprovider`
Expected: all PASS except the known order-dependent `test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` when run in this subset — re-run it alone to confirm it passes in isolation. If an existing tail test asserts the exact `else:` warning string, update that assertion (the wording change is deliberate). Tail tests that use `SimpleNamespace` settings without the new keys must still pass — the `getattr` defaults above guarantee it; on those (with a real bank of zero media pages) the scan is empty and nothing is resolved.

- [ ] **Step 5: Commit**

```bash
cd <worktree>/ && git add api/services/sleep_cycle.py api/tests/test_sleep_link_backfill.py && git commit -m "feat(sleep): drain the link backfill on the engine-independent tail — idle nights too, connector-gated fetch, scheduled cycles never resolve the plan (G102)"
```

---

### Task 5: Surface — `description` + `about` on `GET /sources`, Feed preview seeded from the row

**Files:**
- Modify: `api/models/schemas.py:1190-1212` (`MediaSourceItem`)
- Modify: `api/routers/sources.py:354-436` (`list_sources`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:198-218` (`MediaFeedItem`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift:330-395` (`FeedItemPreviewSheet` — its header comment at 330-336 and the `.task` at 370-379)
- Test: `api/tests/test_sources_about.py` (new), `app/CicadaApp/Tests/CicadaAppTests/FeedIdentityTests.swift` (+1 test, inserted before the class's closing brace at line 88)

**Interfaces:**
- `MediaSourceItem.description: Optional[str] = None` (≤ 280 chars, word boundary + `…`), `MediaSourceItem.about: list[str] = []`.
- Swift `MediaFeedItem.description: String?`, `MediaFeedItem.about: [String]?`.

What already renders and therefore needs no new UI: the entity card shows `## Description` in the media hero (`app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift:329-334, 765-770`) and `related:` as pills (same file, 894-910), so a related link shows its `about` neighbours there today; the Feed preview sheet fetches the entity to get the description (`FeedView.swift:370-379`) — this task seeds it from the row so the preview is instant and the entity fetch becomes the fallback.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_sources_about.py
"""GET /sources carries the link's description excerpt and its `about`
neighbours (G102 R12), read from the page the endpoint already parses; and the
existing ETag (`entities` = max FILE mtime) already invalidates on an in-place
media-page edit, so no widening is needed — proven here, not assumed."""
from __future__ import annotations

import json
import os
import time

from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "sources").mkdir()
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        "h1": {"url": "https://example.com/rich", "title": "Rich", "media_type": "bookmark",
               "media_entity_id": "media-rich", "saved_at": "2026-01-01T00:00:00+00:00"},
        "h2": {"url": "https://example.com/bare", "title": "Bare", "media_type": "bookmark",
               "media_entity_id": "media-bare", "saved_at": "2026-01-02T00:00:00+00:00"},
    }))
    long_desc = "Word " * 100
    base = {"type": "media", "status": "active", "confidence": 0.7, "created": "2026-01-01",
            "last_referenced": "2026-01-01", "tags": ["bookmark"]}
    markdown_parser.write(memory / "entities" / "media-rich.md",
                          {**base, "name": "Rich", "related": ["ros", "knowledge-graphs"],
                           "media": {"url": "https://example.com/rich", "media_type": "bookmark"}},
                          f"## Summary\nSaved.\n\n## Description\n{long_desc.strip()}")
    markdown_parser.write(memory / "entities" / "media-bare.md",
                          {**base, "name": "Bare", "related": [],
                           "media": {"url": "https://example.com/bare", "media_type": "bookmark"}},
                          "## Summary\nSaved.")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_sources_rows_carry_description_excerpt_and_about(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    rows = {r["mediaEntityId"]: r for r in client.get("/sources").json()["items"]}
    rich, bare = rows["media-rich"], rows["media-bare"]
    assert rich["about"] == ["ros", "knowledge-graphs"] and rich["relatedCount"] == 2
    assert rich["description"].endswith("…") and len(rich["description"]) <= 281
    assert not rich["description"].endswith(" …")   # cut at a word boundary
    assert bare["description"] is None and bare["about"] == []
    config.get_settings.cache_clear()


def test_in_place_edit_of_a_media_page_changes_the_sources_etag(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    first = client.get("/sources")
    etag = first.headers["ETag"]
    assert client.get("/sources", headers={"If-None-Match": etag}).status_code == 304
    fp = memory / "entities" / "media-bare.md"
    parsed = markdown_parser.parse(fp)
    parsed.frontmatter["related"] = ["ros"]
    markdown_parser.write(fp, parsed.frontmatter, parsed.body + "\n\n## Description\nNow described.")
    later = time.time() + 2
    os.utime(fp, (later, later))
    resp = client.get("/sources", headers={"If-None-Match": etag})
    assert resp.status_code == 200 and resp.headers["ETag"] != etag
    bare = [r for r in resp.json()["items"] if r["mediaEntityId"] == "media-bare"][0]
    assert bare["description"] == "Now described." and bare["about"] == ["ros"]
    config.get_settings.cache_clear()
```

Swift, appended inside `FeedIdentityTests` (`app/CicadaApp/Tests/CicadaAppTests/FeedIdentityTests.swift`):

```swift
    // G102: rows may carry the link's description excerpt and `about`
    // neighbours; an older backend omits both and the row still decodes.
    func testDescriptionAndAboutDecodeWhenPresentAndDefaultWhenAbsent() {
        let bare = item("media-a", "https://one.example")
        XCTAssertNil(bare.description)
        XCTAssertNil(bare.about)
        let json = """
        {"mediaEntityId": "media-b", "url": "https://two.example", "title": "t", "mediaType": "bookmark",
         "savedAt": "2026-07-13", "relevance": 0.5, "tags": [],
         "description": "A programme page.", "about": ["ros", "knowledge-graphs"]}
        """
        let rich = try! JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
        XCTAssertEqual(rich.description, "A programme page.")
        XCTAssertEqual(rich.about, ["ros", "knowledge-graphs"])
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_sources_about.py -q -p no:cacheprovider`
Expected: FAIL — `KeyError: 'about'`.
Run: `cd <worktree>/app/CicadaApp && swift test --filter FeedIdentityTests`
Expected: compile error — `value of type 'MediaFeedItem' has no member 'about'`.

- [ ] **Step 3: Implement the server side**

`api/models/schemas.py`, at the end of `MediaSourceItem`:

```python
    # G102 cheap slice (R12): the link's own description — OpenGraph at ingest
    # or the Sleep-tail backfill's summary — cut at ~280 chars on a word
    # boundary, and the ids of the entities the page is `about` (the media
    # page's `related:` list, written only by `link_recon`). Both additive and
    # defaulted so an older client is unaffected; `None`/`[]` mean the link
    # has not been described/related yet, never a guess.
    description: Optional[str] = None
    about: list[str] = []
```

`api/routers/sources.py`, in `list_sources`: inside the `if entity_path.exists(): try:` block, keep the parsed object (`parsed = markdown_parser.parse(entity_path); fm = parsed.frontmatter or {}`) and add these two lines **immediately after the parse, before `related_count`** — the block is one `try` whose `except: pass` would otherwise drop them if a later field (relevance, media) raised on an odd page:

```python
                description = _description_excerpt(parsed.body)
                about = [str(r) for r in (fm.get("related") or []) if str(r).strip()]
```

(initialise `description = None; about: list[str] = []` beside the other defaults above the `if`), pass `description=description, about=about` into `MediaSourceItem(...)`, and add the module-level helper:

```python
def _description_excerpt(body: str, limit: int = 280) -> str | None:
    """First ~``limit`` chars of the page's ``## Description``, cut on a word
    boundary with an ellipsis — the Feed row's own copy of what the backfill
    or ingest-time OpenGraph stored (G102 R12). ``None`` when absent."""
    from api.services.entity_body import parse_sections

    text = " ".join((parse_sections(body or "").get("Description", "") or "").split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{cut}…"
```

- [ ] **Step 4: Implement the Swift side**

`APIClient.swift` `MediaFeedItem`, after `contentSavedAt`:

```swift
    /// G102: the link's own description excerpt (OpenGraph at ingest, or the
    /// nightly backfill's summary) and the ids of the entities the page is
    /// `about`. Both optional: an older backend omits them and the row still
    /// decodes; `nil` means "not described / related yet", never a guess.
    let description: String?
    let about: [String]?
```

`FeedView.swift` `FeedItemPreviewSheet.task` — replace the body of the `.task { ... }` with:

```swift
            // Seed from the row (G102: /sources now carries the excerpt), and
            // only fall back to fetching the entity when the row has none.
            guard enrichedDescription == nil else { return }
            if let seeded = item.description, !seeded.isEmpty {
                enrichedDescription = seeded
                return
            }
            if let entity = try? await APIClient.shared.fetchEntity(id: item.mediaEntityId) {
                enrichedDescription = Self.firstSection(
                    ["## Description", "## Summary"],
                    in: entity.markdownContent
                )
            }
```

Also rewrite the sheet's header comment (`FeedView.swift:330-336`), which currently says the Feed payload "has no description": it now reads the row's `description` first and fetches the entity only as the fallback (G102 R12).

`MediaFeedItem` is a synthesized `Codable` with `let` optionals, so a missing key decodes to `nil` with no custom `init(from:)` needed. Verified at `bad8461`: nothing constructs `MediaFeedItem` memberwise (`grep -rn "MediaFeedItem(" app/CicadaApp/Sources app/CicadaApp/Tests` is empty — every instance is decoded from JSON, including the test helper `item(_:_:)`), so no call site needs `description: nil, about: nil`.

- [ ] **Step 5: Run both test suites**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_sources_about.py api/tests/test_sources.py api/tests/test_sync.py api/tests/test_mcp_sources_tool.py -q -p no:cacheprovider`
Expected: all PASS.
Run: `cd <worktree>/app/CicadaApp && swift test --filter FeedIdentityTests`
Expected: PASS (and the full `swift test` must still build — run it once here; it is the only task touching Swift).

- [ ] **Step 6: Commit**

```bash
cd <worktree>/ && git add api/models/schemas.py api/routers/sources.py api/tests/test_sources_about.py app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift app/CicadaApp/Tests/CicadaAppTests/FeedIdentityTests.swift && git commit -m "feat(feed): GET /sources carries each link's description excerpt and about neighbours; preview seeded from the row (G102)"
```

---

### Task 6: Docs — CLAUDE.md, the G102 row, TODO.md

**Files:**
- Modify: `CLAUDE.md` (new subsection after "Save-with-reason (G71)" at 353-364; API list line after 648)
- Modify: `docs/goals/memory-evolution.md:664` (G102 row)
- Modify: `docs/goals/TODO.md` (Where things stand, Shipped 2026-09-02, Wave C #14, Pick up here)

Privacy rule applies: no bank slugs, no real titles/URLs, no people. The numbers measured on the live bank (603 / 370 / 210 / 0) are counts, not content, and are fine.

- [ ] **Step 1: CLAUDE.md**

Insert after the Save-with-reason subsection (before `### Connector seam (G71)`):

```markdown
### Link enrichment & site recon (Stage 5.57 + the nightly backfill, G102)
Two passes describe and relate saved links, both in `api/services/link_enrichment.py`
(+ `link_recon.py`). **In-cycle Stage 5.57** (`enrich_media_links`, after Stage 5 on a night
with episodes) handles the cycle's fresh media: §2a promotes a substantive stored
`## Description` (≥ `link_enrich_min_desc_len`, a sentence end) into a `describes` claim with
zero LLM; §2b fetches + summarizes a thin one, capped at `link_enrich_max_per_cycle`; plus
`recommends` claims and transclusion for a person sharing the episode. **The backfill**
(`link_enrichment.backfill`) exists because that pass only ever ran after Stage 5, took the 20
most-recent pages, and never retried an `enrichment_attempted` page — a bulk-imported bank
measured 603 media pages, 370 with a description, 210 substantive, zero `describes` claims. It
runs on the engine-independent Sleep tail (idle nights too, in the connector poll's
clean-tree-guarded branch, `link_enrich_backfill_per_cycle`/night, oldest-imported first) and
on demand via `POST /maintenance/enrich-links?limit=N` (409 while Sleep runs). *Done* is a
`describes` claim on the page; a failed/blocked fetch is `fetch_status` + `fetch_attempted_at`
and retried after `link_enrich_fetch_retry_days` (30); consent interstitials and login walls
(`classify_page`, G86 + the ToS rail) are retired as `enrichment_status: junk` without a byte
fetched; a fetched page is 4 s / ≤ 512 KB / no cookies / never behind auth, and a block is
never retried with different headers. A §2b summary lands in the body's `## Description`
(`description_source: summary`) so the Feed preview and entity card render it, AND in the claim
(`authored_by: <model>`); a §2a reuse claim is `authored_by: cicada`. **Recon (the G102 cheap
slice)** runs in the same driver: the EXISTING Stage-1 prompt over `title + ## Description`,
`link_recon_batch_size` (8) links per call, each entity attributed to the links whose card text
contains its name/alias (ungrounded names are dropped), routed through the EXISTING Stage-2
judgment alone (`entity_resolver.match_existing` — direct/fuzzy then the LLM judge; never
`resolve()`, which would create pages and open clarifications from bookmark blurbs). A `same`
verdict against an on-disk entity writes an `about` claim on the **media page** (`object_kind:
node`, `origin: sleep/link_recon`) + the id in its `related:`; Stage 5.7 projects it into
`graph_edges.yaml`; the target page is never touched (a blurb mentioning a tool is not the
user referencing it — bumping it would defeat decay). An unmatched mention becomes a pending
candidate (promotion rung 1), never a page. Each run is one `commit_paths` commit —
`Link enrichment <date>`, `Cicada-Author: cicada` when no model ran, else the models used.
Engine failures abort the LLM tiers and leave pages unmarked (R9); on the scheduled tail the
engine resolves byok before the registry is touched (ruling 4), and
`CICADA_ALLOW_CONNECTOR_FETCH` gates only the tail's default fetch. Media pages are evergreen,
and `about` is multi-valued, so nothing here decays or conflicts. `GET /sources` rows carry
`description` (280-char excerpt) and `about` (the ids). Progress marker (report only):
`$CICADA_HOME/link_enrich/<bank>.json`.
```

In the API list after the `POST /maintenance/dedup-sweep` line (648):

```
POST /maintenance/enrich-links?limit=N     → describe + relate N saved links now (G102); 409 while Sleep runs;
                                            {selected, reused, summarized, fetched, failed, skipped, related, remaining, …}
```

Also in the `GET /sources` line: `→ list ingested sources (+ description excerpt, about ids — G102)`.

- [ ] **Step 2: The G102 row**

Append to the G102 row's third column (before the closing `|`), and change the status cell from `🔲` to `🛠️ cheap slice shipped`:

```
**Cheap slice shipped (2026-09-02, `feat/link-summaries`).** Corrected finding first: Stage 5.57 already globbed the whole bank — the zero-`describes` result came from the pass running only after Stage 5 (never on an idle night), taking the 20 most-recent pages, and never retrying an `enrichment_attempted` page. Shipped: `link_enrichment.backfill` on the Sleep tail (`link_enrich_backfill_per_cycle`/night, oldest-first, dated fetch backoff, junk retired via `classify_page`) + `POST /maintenance/enrich-links?limit=N`; recon in `link_recon.py` — the existing Stage-1 prompt over stored title+description, 8 links per call, surface-form attribution, `entity_resolver.match_existing` (the Stage-2 judgment without `resolve()`'s creates/clarifications), `about` claims on the media page projected by Stage 5.7, unmatched mentions as pending candidates; `GET /sources` carries `description`/`about`. **Not shipped (this row stays open):** page fetching beyond OG+visible-text (JS-rendered pages, YouTube transcripts, PDFs), any `about` edge from the target's side, in-app recon controls, and relating a link to a *pending* candidate once it promotes (today the candidate carries the link's episode as its source, so promotion backfills context but not the edge — a follow-up).
```

- [ ] **Step 3: TODO.md**

- "Where things stand": add a paragraph after the 2026-09-02 one: `**G102 cheap slice (PR against dev from \`feat/link-summaries\`):** saved links get descriptions + \`about\` edges nightly (20/night, oldest first) and on demand. **One-time warm-up the owner can run now:** \`curl -s -X POST -H "Authorization: Bearer $(cat ~/.cicada/api_token)" "http://127.0.0.1:8000/maintenance/enrich-links?limit=50"\` — repeat until \`remaining\` is 0 (each run: ≤ 50 fetches + summaries on the resolved engine, ~7 extraction calls); the response's \`engine\` says whether the plan or the API key paid.`
- "✅ Shipped" → `**2026-09-02**` list: add `- **G102 cheap slice** — link backfill on the Sleep tail + \`POST /maintenance/enrich-links\`; recon over stored OG text → \`about\` claims/edges through the existing Stage-1 prompt and Stage-2 judgment; \`GET /sources\` \`description\`/\`about\`. Plan: \`docs/superpowers/plans/2026-09-02-link-summaries-backfill.md\``
- "🔄 In progress" table (line ~239, the G109 row is the template): add a row `| **G102 cheap slice** | On \`feat/link-summaries\` (2026-09-02): backfill + recon + endpoint + Feed fields, six commits, five new test files | Open the PR against \`dev\` after an independent re-run; owner runs the warm-up curl; merge |` — it moves to Shipped only when the PR merges.
- Wave C #14 (line 309): rewrite to `14. **G102** site recon — cheap slice shipped 2026-09-02 (see Shipped). Next slice: relate a link to a pending candidate when it promotes; fetch-side improvements stay out of scope until a measured need — S`
- "Pick up here": add a numbered item: `**G102 cheap slice is on \`feat/link-summaries\`** — open the PR against \`dev\` after an independent re-run of the five new test files + the full suite; then have the owner run the warm-up curl above and eyeball the Feed (descriptions on rows, \`about\` pills on a link's entity card).`
- Update `_Last synced_` line's date text to mention G102.

- [ ] **Step 4: Verify the docs privacy rule and commit**

Run: `cd <worktree>/ && git diff --stat && git diff CLAUDE.md docs/goals/ | grep -n -i "rorosaga\|/Users/\|claude-chats" ; echo "expect no matches above (the ~/.cicada path in the curl is the documented secret location, not a bank)"`

```bash
cd <worktree>/ && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md && git commit -m "docs: Stage 5.57 backfill + recon in CLAUDE.md, G102 cheap slice shipped, TODO handoff + warm-up note"
```

---

## Not in scope (deliberately)

- JS-rendered pages, headless browsers, YouTube transcripts, PDFs, anything behind auth or a consent wall — a page that yields `<100` visible chars is `failed:empty_body` and retried in 30 days, nothing more.
- A new UI page or in-app recon controls; the only Swift change is two optional fields and the preview seed.
- Writing anything on the target entity's page (`related`, `last_referenced`, a reverse claim) — R6.
- Relating a link to a pending candidate once that candidate promotes (noted in the G102 row as the next slice).
- Re-indexing the vector index after a backfill (the next Sleep cycle's `index_entities()` picks the new descriptions up; an endpoint run does not rebuild embeddings).
- Changing `enrich_media_links`'s own tier logic, the `recommends`/transclusion path, or the predicate seed (`about` stays an unseen ⇒ multi-valued predicate; adding it to `multi_valued` in the seed is a one-liner a later pass can do with the normalization audit).
- Any Telegram/MCP/capture-time hook — Sleep-safety ruling.
- Hunk-level staging: if a Sleep cycle's Stage 5.56 touches a media page in the same night the tail backfills it, `commit_paths` stages the whole file (the same disclosed asymmetry as G85).

## Verification the orchestrator runs at the end

```bash
cd <worktree>/ && git log --oneline bad8461..HEAD
# expect 6 commits, one per task, in order

cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_link_backfill.py api/tests/test_link_recon.py api/tests/test_maintenance_enrich_links.py api/tests/test_sleep_link_backfill.py api/tests/test_sources_about.py -q -p no:cacheprovider
# expect: all pass

cd <worktree>/ && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -15
# expect: exactly the baseline failures — 8 in test_calendar_registry.py, plus
# test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit
# (order-dependent; passes alone). Nothing else red.

cd <worktree>/app/CicadaApp && swift test 2>&1 | tail -5
# expect: all pass (FeedIdentityTests gained one test)

cd <worktree>/ && git status --porcelain
# expect: clean, or only untracked api/.venv / *-report.md — never staged

# Rails grep — nothing in the new code reaches the network by default from a test,
# nothing hardcodes an owner or a machine path, no LLM at capture time:
cd <worktree>/ && grep -n "rorosaga\|/Users/" api/services/link_enrichment.py api/services/link_recon.py api/routers/maintenance.py api/tests/test_link_backfill.py api/tests/test_link_recon.py api/tests/test_sleep_link_backfill.py api/tests/test_maintenance_enrich_links.py api/tests/test_sources_about.py ; echo "expect no output"
cd <worktree>/ && grep -n "link_enrichment\|link_recon" api/routers/capture.py api/services/telegram_capture.py api/services/media_ingestor.py mcp/server.py ; echo "expect no output (no capture-time hook)"

# Diff read: every task's docstrings cite the G-row / ruling (R-numbers or G-ids) that motivated the rule.
cd <worktree>/ && git diff bad8461..HEAD --stat
```

Live check (owner, after merge — not the orchestrator, the bank holds real people): `POST /maintenance/enrich-links?limit=50` against the running backend, confirm the response's `engine` and counts, then `git -C <bank> log -1 --format=%B` shows `Link enrichment <date>` with the expected trailer, and a described link's Feed row shows its excerpt.
