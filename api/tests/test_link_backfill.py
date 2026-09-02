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
from api.services.claims import Claim, parse_claims, write_claims

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
    # Review M1: a page ABOUT auth is not a login wall. A junk verdict is
    # permanent, and developer bookmarks are dense with these paths.
    assert link_enrichment.classify_page("Auth | Example Docs", "https://docs.example.com/guides/auth") is None
    assert link_enrichment.classify_page("OAuth 2.0 explained", "https://blog.example.com/oauth2/") is None
    assert link_enrichment.classify_page("SSO overview", "https://example.com/sso") is None


def test_redirect_target_uses_the_wider_login_path_set_only_when_moved():
    wall = link_enrichment._redirected_to_wall
    # Bounced onto an auth path: a wall.
    assert wall("https://example.com/report", "https://example.com/oauth2/authorize?next=/report")
    assert wall("https://example.com/report", "https://example.com/sso")
    assert wall("https://example.com/report", "https://accounts.google.com/signin/v2")
    assert wall("https://example.com/report", "https://consent.example.com/m")
    # The saved URL itself, unmoved (httpx reports a final URL either way): not a wall.
    assert not wall("https://docs.example.com/guides/auth", "https://docs.example.com/guides/auth")
    assert not wall("https://blog.example.com/oauth2", "https://blog.example.com/oauth2/")
    # Moved, but onto an ordinary page.
    assert not wall("http://example.com/a", "https://example.com/a/")
    # A saved /login URL is a wall regardless of redirects (classify_page's own rule).
    assert wall("https://app.example.com/login", "https://app.example.com/login")


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


def _saved_because(memory: Path, stem: str, reason: str) -> None:
    """Append a G71 ``saved-because`` claim the way a Telegram ``/save <url>
    <reason>`` does: the ```claims fence lands AFTER the last H2, which is
    the page shape that made review H1 load-bearing."""
    fp = memory / "entities" / f"{stem}.md"
    parsed = markdown_parser.parse(fp)
    claim = Claim(
        id="clm_saved_because_1", text=f"Saved because {reason}", subject=stem,
        predicate="saved-because", object=reason, object_kind="literal",
        observer="rodrigo", source_trust="user_stated", origin="telegram",
    )
    markdown_parser.write(fp, parsed.frontmatter, write_claims(parsed.body, [claim]))


def test_description_section_never_includes_the_claims_block(tmp_path):
    """Review H1: ``parse_sections`` ends a section at the next H2 or EOF, so a
    trailing ```claims fence used to be read as part of ``## Description``."""
    memory = _bank(tmp_path)
    _media(memory, "media-rich", "Rich", "https://example.com/rich", saved_at="2026-02-01", description=LONG)
    _saved_because(memory, "media-rich", "it lists submission deadlines")
    body = markdown_parser.parse(memory / "entities" / "media-rich.md").body
    assert "```claims" in body and body.index("## Description") < body.index("```claims")
    assert link_enrichment._extract_description_section(body) == LONG


def test_reuse_tier_claim_text_is_the_description_only_beside_a_saved_because_claim(tmp_path):
    memory = _bank(tmp_path)
    _media(memory, "media-rich", "Rich", "https://example.com/rich", saved_at="2026-02-01", description=LONG)
    _saved_because(memory, "media-rich", "it lists submission deadlines")
    report = _backfill(memory, _settings(memory), limit=20, summarize_fn=None, fetch_fn=None, commit=False)
    assert report.reused == 1
    claims = _claims(memory, "media-rich")
    assert sorted(c.predicate for c in claims) == ["describes", "saved-because"]
    describes = [c for c in claims if c.predicate == "describes"][0]
    assert describes.text == LONG and describes.object == LONG
    assert "clm_saved_because" not in describes.text and "observer" not in describes.text


def test_thin_description_beside_a_claims_block_goes_to_the_fetch_tier(tmp_path):
    """The YAML must not pad a 40-char description past ``link_enrich_min_desc_len``."""
    memory = _bank(tmp_path)
    _media(memory, "media-thin", "Thin", "https://example.com/thin", saved_at="2026-02-01",
           description="A short forty character description.")
    _saved_because(memory, "media-thin", "it lists submission deadlines")
    scan = link_enrichment.scan_backfill(memory, _settings(memory), today=date(2026, 9, 2))
    assert [c.media_id for c in scan.fetch] == ["media-thin"]
    assert scan.reuse == []


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
    assert report.llm_calls == 0                # the engine never answered (review M2)


def test_engine_abort_commits_the_real_writes_as_cicada_with_no_engine_trailer(tmp_path):
    """Review M2 / R7: the fetch stamp on media-a is a real write and IS
    committed, but no model produced anything, so the commit is ``cicada``'s
    and carries no ``Cicada-Engine:`` — the G85 decay-only precedent."""
    from api.services import engine_errors

    memory = _bank(tmp_path, git=True)
    _media(memory, "media-a", "A", "https://example.com/a", saved_at="2026-01-01")
    _seed_commit(memory)

    async def summ(title, excerpt, url, settings):
        raise engine_errors.EngineUnavailable("signed out")

    report = _backfill(memory, _settings(memory), limit=20, summarize_fn=summ, fetch_fn=_fetch_ok, engine="litellm")
    assert report.engine_aborted == "EngineUnavailable" and report.llm_calls == 0
    assert report.commit
    assert _fm(memory, "media-a")["fetch_status"] == "ok"
    log = _git_log(memory)
    assert "entities/media-a.md: fetch ok (" in log and "enriched" not in log
    assert "Cicada-Author: cicada" in log
    assert "Cicada-Author: gpt-5.4-mini" not in log
    assert "Cicada-Engine:" not in log


def test_page_level_summarize_failure_still_counts_the_model_call(tmp_path):
    memory = _bank(tmp_path)
    _media(memory, "media-a", "A", "https://example.com/a", saved_at="2026-01-01")

    async def summ(title, excerpt, url, settings):
        raise ValueError("malformed response")

    report = _backfill(memory, _settings(memory), limit=20, summarize_fn=summ, fetch_fn=_fetch_ok, commit=False)
    assert report.llm_calls == 1 and report.failed == 1 and report.summarized == 0
    assert _fm(memory, "media-a")["fetch_status"] == "failed:no_summary"


def test_refused_claim_is_not_reported_as_enriched(tmp_path, monkeypatch):
    """Review L2: ``_append_claim`` returning False (block went malformed
    between scan and write, or the id already exists) must leave the page a
    candidate — no ``enrichment_attempted`` stamp, no ``enriched`` line."""
    memory = _bank(tmp_path)
    _media(memory, "media-rich", "Rich", "https://example.com/rich", saved_at="2026-02-01", description=LONG)
    monkeypatch.setattr(link_enrichment, "_append_claim", lambda fp, claim: False)
    report = _backfill(memory, _settings(memory), limit=20, summarize_fn=None, fetch_fn=None, commit=False)
    assert (report.selected, report.reused, report.failed) == (1, 0, 1)
    assert not _claims(memory, "media-rich")
    assert _fm(memory, "media-rich").get("enrichment_attempted") is None
    assert not any("enriched" in line for line in report.manifest)
    assert report.written_paths == []


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
    # Review L1 / G114: aware UTC, never a naive local time.
    assert data["last_run"].endswith("+00:00")
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
