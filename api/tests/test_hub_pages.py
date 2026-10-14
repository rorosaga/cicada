"""The owner's page as a page again (owner page, 2026-10-14): a claims ledger beside a very large page, a rolled-up
Related on a hub, an article whose inputs fit their budget, a prose-first `cicada_recall_detail`, a card that opens
without waiting on `git blame` — and, through all of it, not one claim, evidence span or link lost.

Synthetic only: an owner page shaped like the measured one (thousands of "<owner> asked about X" claims, hundreds of
Related lines), placeholder names (`Owner Example`, `alpha-0001`).
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.config import Settings
from api.services import (
    agentic_write, claim_recovery, claims, claims_ledger, conflict_resolver, dedup_sweep, entity_body, entity_merge,
    git_service, hub_pages, markdown_parser, mcp_tools,
)
from api.services.claims import Claim, Evidence

OWNER = "owner-example"
ACTIVITY = [("asked-about", "asked about"), ("worked-on", "worked on"),
            ("asked-for-an-explanation-of", "asked for an explanation of"), ("developed", "developed")]


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _claim(i: int, target: str, pred: str, label: str, day: str, closed: bool = False) -> Claim:
    ep = f"ep_{day}_{1 + i % 9:03d}"
    c = Claim(id=f"clm_{i:05d}", text=f"Owner Example {label} {target.replace('-', ' ').title()}", subject=OWNER,
              predicate=pred, object=target, valid_from=day, recorded_at=day, source_episodes=[ep],
              premises=[f"clm_p{i:05d}"], session_id=f"ses-{i:08d}", session_ids=[f"ses-{i:08d}"],
              evidence=[Evidence(episode=ep, start=40 + i, end=120 + i, kind="user", hash=f"{i:012x}"[-12:]),
                        Evidence(episode=ep, start=200 + i, end=260 + i, kind="assistant", hash=f"{i + 7:012x}"[-12:])])
    if closed:
        c.valid_to, c.superseded_by = day, f"clm_{i:05d}_next"
    return c


def _owner_bank(tmp_path: Path, *, n_claims=1500, n_pages=300, git=True) -> Path:
    """A bank whose owner page is the measured shape, small enough for a test: activity claims to many pages, a few
    facts about the person, a Related line per page — written raw, as an old bank holds it (no ledger yet)."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    pages = [f"alpha-{i:04d}" for i in range(n_pages)]
    for i, eid in enumerate(pages):
        kind = "person" if i % 50 == 0 else "project"
        fm = {"name": eid.replace("-", " ").title(), "type": kind, "status": "active", "created": "2026-01-01",
              "source_episodes": [], "related": []}
        (memory / "entities" / f"{eid}.md").write_bytes(markdown_parser._render(fm, f"## Summary\n{eid} is a page."))
    for eid, name in (("synthetic-university", "Synthetic University"), ("example-city", "Example City")):
        fm = {"name": name, "type": "location", "status": "active", "created": "2026-01-01"}
        (memory / "entities" / f"{eid}.md").write_bytes(markdown_parser._render(fm, f"## Summary\n{name}."))
    rows = []
    for i in range(n_claims):
        pred, label = ACTIVITY[i % len(ACTIVITY)]
        day = f"2026-{1 + (i * 9) // n_claims:02d}-{1 + i % 28:02d}"
        rows.append(_claim(i, pages[(i * 7) % n_pages], pred, label, day, closed=i % 20 == 0))
    rows.insert(3, Claim(id="clm_studies", text="Owner Example studies at Synthetic University", subject=OWNER,
                         predicate="studies-at", object="synthetic-university", valid_from="2026-01-02",
                         recorded_at="2026-01-02", evidence=[Evidence(episode="ep_2026-01-02_001", start=1, end=40,
                                                                      kind="user", hash="aaaaaaaaaaaa")]))
    rows.insert(5, Claim(id="clm_lives", text="Owner Example lives in Example City", subject=OWNER,
                         predicate="lives-in", object="example-city", valid_from="2026-01-03",
                         recorded_at="2026-01-03"))
    related = "\n".join(f"- [[{p.replace('-', ' ').title()}]] — {ACTIVITY[i % 4][1]}" for i, p in enumerate(pages))
    prose = ("## Summary\nOwner Example is the person this synthetic bank belongs to.\n\n## Key Facts\n"
             "- Studies at [[Synthetic University]].\n\n## History\n- 2026-01-02: Started a synthetic degree.\n\n"
             f"## Related\n{related}\n- [[Synthetic University]] — studies at\n- [[Example City]] — lives in")
    fm = {"name": "Owner Example", "type": "person", "status": "active", "owner": True, "decay_class": "evergreen",
          "created": "2026-01-01", "last_referenced": "2026-09-30", "aliases": ["Owner"],
          "source_episodes": [f"ep_2026-0{1 + i % 9}-{1 + i % 28:02d}_001" for i in range(60)],
          "related": pages + ["synthetic-university", "example-city"]}
    (memory / "entities" / f"{OWNER}.md").write_bytes(markdown_parser._render(fm, claims.write_claims(prose, rows)))
    if git:
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                     ["add", "."], ["commit", "-q", "-m", "Seed\n\nCicada-Author: cicada"]):
            _git(memory, *args)
    return memory


def _record(memory: Path, eid: str = OWNER) -> tuple[set, set]:
    every = claims.parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body, strict=True)
    return ({c.id for c in every}, {(c.id, e.episode, e.start, e.end, e.kind, e.hash) for c in every
                                    for e in c.evidence})


def _related_links(body: str) -> set[str]:
    block = hub_pages._related_block(body)
    return {n.strip().lower() for n in re.findall(r"\[\[([^\]|#]+)", block)}


# --------------------------------------------------------------------------- the ledger


def test_a_write_over_the_budget_moves_the_oldest_logs_into_the_ledger_and_a_read_folds_them_back(tmp_path):
    memory = _owner_bank(tmp_path, git=False)
    page = memory / "entities" / f"{OWNER}.md"
    ids, spans = _record(memory)
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body)

    ledger = claims_ledger.path_for(page)
    assert ledger.exists() and page.stat().st_size < 60_000
    own = claims_ledger._fence(markdown_parser.parse(page, ledger=False).body)[1]
    assert sum(len(line) + 1 for line in own) <= claims_ledger.SPILL_TO
    assert _record(memory) == (ids, spans)                       # every claim and span, read through the page
    stamp = markdown_parser.parse(page, ledger=False).frontmatter[claims_ledger.STAMP]
    assert stamp["claims"] == len(claims_ledger.read_lines(ledger))
    on_page = {claims_ledger.line_id(line) for line in own}
    assert {"clm_studies", "clm_lives"} <= on_page               # the facts about the person stay on the page
    assert "clm_00000" not in on_page                            # a closed claim is the first to go


def test_a_write_from_the_page_alone_never_drops_a_ledger_line(tmp_path):
    memory = _owner_bank(tmp_path, git=False)
    page = memory / "entities" / f"{OWNER}.md"
    ids, spans = _record(memory)
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    raw = markdown_parser.parse(page, ledger=False)              # a raw reader: the page without its ledger
    extra = Claim(id="clm_new", text="Owner Example plans a synthetic trip", subject=OWNER, predicate="plans",
                  object="example-city", valid_from="2026-10-01", recorded_at="2026-10-01")
    markdown_parser.write(page, raw.frontmatter,
                          claims.write_claims(raw.body, claims.parse_claims(raw.body, strict=True) + [extra]))
    assert _record(memory)[0] == ids | {"clm_new"}
    assert spans <= _record(memory)[1]


def test_a_crash_between_the_ledger_and_the_page_reads_each_claim_once(tmp_path):
    memory = _owner_bank(tmp_path, git=False)
    page = memory / "entities" / f"{OWNER}.md"
    old = page.read_bytes()
    ids, _ = _record(memory)
    parsed = markdown_parser.parse(page)
    fm, body, ledger = claims_ledger.split(page, parsed.frontmatter, parsed.body)
    claims_ledger.path_for(page).write_bytes(ledger)             # the ledger landed; the page did not
    fm_old = markdown_parser.parse(page, ledger=False).frontmatter
    page.write_bytes(markdown_parser._render({**fm_old, claims_ledger.STAMP: fm[claims_ledger.STAMP]},
                                             markdown_parser.split_frontmatter(old.decode())[1].strip()))
    every = claims.parse_claims(markdown_parser.parse(page).body, strict=True)
    assert len(every) == len(ids) and {c.id for c in every} == ids


def test_an_unreadable_fence_is_never_split(tmp_path):
    page = tmp_path / "entities" / "alpha-project.md"
    page.parent.mkdir()
    body = "## Summary\nAlpha.\n\n```claims\n" + "x" * (claims_ledger.FENCE_MAX_CHARS + 10) + "\n"   # unterminated
    markdown_parser.write(page, {"name": "Alpha"}, body)
    assert not claims_ledger.path_for(page).exists()
    assert markdown_parser.parse(page).body == body.strip()


def test_a_small_page_is_written_exactly_as_before(tmp_path):
    page = tmp_path / "entities" / "alpha-project.md"
    page.parent.mkdir()
    body = claims.write_claims("## Summary\nAlpha.", [_claim(1, "beta", "uses", "uses", "2026-01-01")])
    markdown_parser.write(page, {"name": "Alpha"}, body)
    assert page.read_bytes() == markdown_parser._render({"name": "Alpha"}, body)
    assert not claims_ledger.path_for(page).exists()


# --------------------------------------------------------------------------- git: a page and its ledger are one unit


def test_a_commit_naming_the_page_takes_its_ledger_and_a_checkout_puts_it_back(tmp_path):
    memory = _owner_bank(tmp_path)
    page = memory / "entities" / f"{OWNER}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    git_service.commit_paths_sync(memory, "Split\n\nCicada-Author: cicada", [f"entities/{OWNER}.md"])
    assert _git(memory, "status", "--porcelain") == ""
    assert f"entities/{OWNER}.claims.jsonl" in _git(memory, "show", "--name-only", "--format=", "HEAD")
    ledger = claims_ledger.path_for(page)
    kept = ledger.read_bytes()
    ledger.write_text("damaged\n")
    page.write_text(page.read_text() + "\n")
    git_service.run_git_write_sync(memory, "checkout", "--", f"entities/{OWNER}.md")
    assert ledger.read_bytes() == kept


def test_claim_recovery_sees_a_moved_claim_as_present(tmp_path):
    memory = _owner_bank(tmp_path)
    hub_pages.apply(memory, sleep_running=lambda: False)
    plan = claim_recovery.analyze(memory)
    assert plan.items == []


def test_a_merge_carries_the_losers_ledger_and_removes_it(tmp_path):
    memory = _owner_bank(tmp_path, git=False)
    loser = memory / "entities" / f"{OWNER}.md"
    parsed = markdown_parser.parse(loser)
    markdown_parser.write(loser, parsed.frontmatter, parsed.body)
    ids, spans = _record(memory)
    markdown_parser.write(memory / "entities" / "owner-twin.md", {"name": "Owner Twin", "type": "person"},
                          "## Summary\nA duplicate.")
    footprint = entity_merge.merge_footprint(memory, OWNER, "owner-twin")
    assert f"entities/{OWNER}.claims.jsonl" in footprint
    out = entity_merge.merge_entities(memory, loser_id=OWNER, winner_id="owner-twin")
    assert not claims_ledger.path_for(loser).exists()
    assert f"entities/{OWNER}.claims.jsonl" in out["paths"] and set(out["paths"]) <= set(footprint)
    assert _record(memory, "owner-twin")[0] >= ids


# --------------------------------------------------------------------------- the migration


def test_the_split_loses_no_claim_span_or_link_and_runs_once(tmp_path):
    memory = _owner_bank(tmp_path)
    page = memory / "entities" / f"{OWNER}.md"
    before_bytes = page.stat().st_size
    ids, spans = _record(memory)
    links = _related_links(markdown_parser.parse(page).body)
    dry = hub_pages.survey(memory)
    assert dry.selected >= 1 and dry.failed_check == 0 and _git(memory, "status", "--porcelain") == ""

    result = hub_pages.apply(memory, sleep_running=lambda: False)
    assert result.committed and result.written == dry.selected and result.failed_check == 0
    assert _record(memory) == (ids, spans)
    after = markdown_parser.parse(page)
    rolled = _related_links(after.body)
    names = rolled | {s.lower() for s in after.frontmatter["related"]}
    assert all(n in names or n.replace(" ", "-") in names for n in links)
    related_lines = hub_pages._bullets(hub_pages._related_block(after.body))
    assert related_lines <= entity_body.RELATED_MAX + len(ACTIVITY) + 1
    assert "[[synthetic university]]" in after.body.lower()      # a relation keeps its own line
    assert page.stat().st_size < before_bytes / 5
    assert _git(memory, "status", "--porcelain") == ""
    log = _git(memory, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in log and hub_pages.TRIGGER in log
    again = hub_pages.apply(memory, sleep_running=lambda: False)
    assert again.selected == 0 and again.written == 0 and not again.committed


def test_the_split_refuses_while_sleep_runs(tmp_path):
    memory = _owner_bank(tmp_path)
    head = _git(memory, "rev-parse", "HEAD")
    with pytest.raises(hub_pages.SleepRunning):
        hub_pages.apply(memory, sleep_running=lambda: True)
    assert _git(memory, "rev-parse", "HEAD") == head and _git(memory, "status", "--porcelain") == ""


def test_the_script_dry_run_prints_counts_only(tmp_path, capsys):
    from api.scripts import split_hub_pages

    memory = _owner_bank(tmp_path)
    assert split_hub_pages.main(["--bank", str(memory)]) == 0
    out = capsys.readouterr().out
    assert '"selected"' in out and "Owner" not in out and "alpha" not in out
    assert _git(memory, "status", "--porcelain") == ""


# --------------------------------------------------------------------------- what an agent and the writer read


def _article_job(memory: Path, max_chars: int = 60_000):
    page = markdown_parser.parse(memory / "entities" / f"{OWNER}.md")
    existing = [{"id": p.stem, "frontmatter": markdown_parser.parse(p, ledger=False).frontmatter, "body": ""}
                for p in (memory / "entities").glob("*.md")]
    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(memory), page_articles_enabled=True)
    context = conflict_resolver._article_context(existing, settings, "2026-10-14", memory)
    context["max_chars"] = max_chars
    change = {"id": OWNER, "action": "update", "source_episodes": ["ep_2026-10-14_001"], "entity": {}}
    return conflict_resolver._article_job(change, {"frontmatter": page.frontmatter, "body": page.body}, {}, context)


@pytest.mark.parametrize("split", [False, True])
def test_the_owner_page_gets_an_article_within_its_budget_and_its_facts_reach_the_writer(tmp_path, split):
    memory = _owner_bank(tmp_path)
    if split:
        hub_pages.apply(memory, sleep_running=lambda: False)
    job = _article_job(memory)
    assert job is not None and len(job["prompt"]) <= 60_000
    assert "studies at Synthetic University" in job["prompt"] and "lives in Example City" in job["prompt"]
    assert "Started a synthetic degree" in job["prompt"]
    # The people in the owner's life (person pages with a current claim; 0, 100 and 200 only have closed ones).
    assert all(f"Alpha {i:04d}" in job["prompt"] for i in (50, 150, 250))
    assert len(job["prompt"]) > 30_000                            # filled toward the budget, not starved


def test_a_page_whose_own_record_is_over_the_budget_still_takes_todays_path(tmp_path):
    memory = _owner_bank(tmp_path, git=False)
    assert _article_job(memory, max_chars=2_000) is None


def _ctx(memory, **kw):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown", **kw)


def test_recall_detail_answers_with_the_prose_first_and_every_claim_stays_reachable(tmp_path):
    memory = _owner_bank(tmp_path)
    hub_pages.apply(memory, sleep_running=lambda: False)
    ids, _ = _record(memory)
    started = time.perf_counter()
    first = str(mcp_tools.recall_detail(_ctx(memory), OWNER))
    assert time.perf_counter() - started < 2.0
    assert first.startswith("# Owner Example (the owner)") and "## Summary" in first
    assert "source_episodes:" not in first and len(first) <= mcp_tools.RECALL_DETAIL_BUDGET + 400
    assert f'cicada_recall_detail(entity_id="{OWNER}", start=1)' in first
    seen, start = "", 1
    pattern = re.compile(r'cicada_recall_detail\(entity_id="owner-example", start=(\d+)\)')
    for _ in range(200):
        part = str(mcp_tools.recall_detail(_ctx(memory), OWNER, start=start))
        seen += part.rpartition("\n— lines ")[0]
        match = pattern.search(part.rpartition("\n— lines ")[2])
        if match is None:
            break
        start = int(match.group(1))
    assert "## Claims ledger" in seen
    assert all(f'"id": "{cid}"' in seen for cid in ids)


# --------------------------------------------------------------------------- the card


def _client(memory: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_the_owner_card_opens_fast_and_never_reads_the_ledger(tmp_path, monkeypatch):
    memory = _owner_bank(tmp_path, n_claims=3000)
    hub_pages.apply(memory, sleep_running=lambda: False)
    opened = []
    real = claims_ledger.read_lines
    monkeypatch.setattr(claims_ledger, "read_lines", lambda p: opened.append(p) or real(p))
    client = _client(memory, monkeypatch)
    started = time.perf_counter()
    response = client.get(f"/entities/{OWNER}")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200 and elapsed < 1.5, elapsed
    data = response.json()
    assert not data["rawOmitted"] and len(response.content) < 200_000
    assert "## Summary" in data["markdownContent"] and opened == []


def test_the_card_does_not_wait_on_a_slow_blame(tmp_path, monkeypatch):
    memory = _owner_bank(tmp_path, n_claims=200, n_pages=20)
    page = memory / "entities" / f"{OWNER}.md"
    for n in range(4):
        page.write_text(page.read_text() + f"\n<!-- {n} -->\n")
        _git(memory, "commit", "-qam", f"Touch {n}\n\nCicada-Author: cicada")
    monkeypatch.setattr(git_service, "MAX_PROVENANCE_COMMITS", 2)
    git_service._SURVIVORS.clear()
    real = git_service._run_git
    slow = {"calls": 0}

    async def run_git(memory_path, *args):
        if args and args[0] == "blame":
            slow["calls"] += 1
            await asyncio.sleep(1.5)
        return await real(memory_path, *args)

    monkeypatch.setattr(git_service, "_run_git", run_git)

    async def both():
        started = time.perf_counter()
        rows, truncated = await git_service.entity_history(OWNER, memory)
        first = (time.perf_counter() - started, len(rows), truncated)
        await asyncio.sleep(2.0)                                   # the blame finishes in the background
        rows, _ = await git_service.entity_history(OWNER, memory)
        return first, len(rows)

    (elapsed, window, truncated), later = asyncio.run(both())
    assert elapsed < 1.2 and window == 2 and truncated
    assert later > window and slow["calls"] == 1                  # the seed's lines, found once and kept


# --------------------------------------------------------------------------- review 2026-10-14


def test_a_withdrawn_claim_in_the_ledger_survives_its_restatement_under_the_same_id(tmp_path):
    """Ids come from the fact: withdraw → spill → restate leaves a closed and an open copy under one id. Both are read,
    and both survive an unrelated write (the reviewer's reproduction, kept)."""
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    markdown_parser.write(mem / "entities" / "synthetic-university.md",
                          {"name": "Synthetic University", "type": "organization", "status": "active"}, "## Summary\nX.")
    markdown_parser.write(mem / "entities" / "example-city.md",
                          {"name": "Example City", "type": "location", "status": "active"}, "## Summary\nX.")
    page = mem / "entities" / "owner-example.md"
    rows = [Claim(id=f"clm_{i:05d}", text=f"Owner Example asked about Alpha {i}", subject=OWNER,
                  predicate="asked-about", object=f"alpha-{i:04d}", valid_from="2026-01-01",
                  recorded_at=f"2026-01-{1 + i % 28:02d}",
                  evidence=[Evidence(episode="ep_2026-01-01_001", start=i, end=i + 40, kind="user", hash="a" * 12)])
            for i in range(700)]
    markdown_parser.write(page, {"name": "Owner Example", "type": "person", "status": "active", "owner": True},
                          claims.write_claims("## Summary\nOwner Example.", rows))
    kw = dict(observer="agent-example", origin="claude-code", authored_by="claude-code",
              text="Owner Example studies at Synthetic University")
    cid = agentic_write.write_claim(mem, OWNER, "studies-at", "synthetic-university", **kw)["claim_id"]
    assert agentic_write.retract_claim(mem, OWNER, cid, reason="wrong", author="claude-code",
                                       origin="claude-code")["action"] == "retracted"
    p = markdown_parser.parse(page)
    more = [Claim(id=f"clm_pad{i:05d}", text=f"Owner Example worked on Beta {i}", subject=OWNER,
                  predicate="worked-on", object=f"beta-{i:04d}", valid_from="2026-03-01", recorded_at="2026-03-01")
            for i in range(500)]
    markdown_parser.write(page, p.frontmatter,
                          claims.write_claims(p.body, [*claims.parse_claims(p.body, strict=True), *more]))
    assert any(claims_ledger.line_id(line) == cid for line in claims_ledger.ledger_lines(page))

    def copies():
        return [(c.valid_to, c.superseded_by) for c in claims.parse_claims(markdown_parser.parse(page).body)
                if c.id == cid]

    agentic_write.write_claim(mem, OWNER, "studies-at", "synthetic-university", **kw)   # restated
    assert len(copies()) == 2
    agentic_write.write_claim(mem, OWNER, "lives-in", "example-city", observer="agent-example",
                              origin="claude-code", text="Owner Example lives in Example City")
    after = copies()
    assert len(after) == 2 and any(v for v, _ in after) and any(v is None for v, _ in after)


def test_an_edited_ledger_claim_is_never_duplicated(tmp_path):
    memory = _owner_bank(tmp_path, git=False)
    page = memory / "entities" / f"{OWNER}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    moved = claims_ledger.line_id(claims_ledger.ledger_lines(page)[-1])
    every = claims.parse_claims(markdown_parser.parse(page).body, strict=True)
    for c in every:
        if c.id == moved:
            c.valid_to = "2026-10-01"
    p = markdown_parser.parse(page)
    markdown_parser.write(page, p.frontmatter, claims.write_claims(p.body, every))
    copies = [c for c in claims.parse_claims(markdown_parser.parse(page).body) if c.id == moved]
    assert len(copies) == 1 and copies[0].valid_to == "2026-10-01"
    assert len(claims.parse_claims(markdown_parser.parse(page).body)) == len(every)


def test_a_write_that_edits_every_ledger_claim_leaves_no_stale_copy(tmp_path):
    """A pass touching every claim (the review's probe): each comes back once, at its new value."""
    memory = _owner_bank(tmp_path, git=False)
    page = memory / "entities" / f"{OWNER}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    p = markdown_parser.parse(page)
    every = claims.parse_claims(p.body, strict=True)
    for c in every:
        c.confidence = 0.42
    markdown_parser.write(page, p.frontmatter, claims.write_claims(p.body, every))
    after = claims.parse_claims(markdown_parser.parse(page).body, strict=True)
    assert len(after) == len(every) and {c.confidence for c in after} == {0.42}
    assert claims_ledger.path_for(page).exists()            # the edited set spilled again
    assert claims_ledger.READ not in markdown_parser.parse(page, ledger=False).frontmatter[claims_ledger.STAMP]


def test_a_rename_of_a_ledger_page_leaves_no_stale_copies(tmp_path):
    """The inbox's keep-the-cleaner-name rename re-subjects every claim of a page with a ledger: each is read back
    once, under its new subject (the review's re-check reproduction, kept)."""
    from collections import Counter

    ents = tmp_path / "memory" / "entities"
    ents.mkdir(parents=True)
    old = ents / "alpha-proj.md"
    rows = [Claim(id=f"clm_{i:05d}", text=f"Alpha Proj asked about Beta {i} " + "x" * 200, subject="alpha-proj",
                  predicate="asked-about", object=f"beta-{i:04d}", valid_from="2026-01-01",
                  recorded_at=f"2026-01-{1 + i % 28:02d}") for i in range(600)]
    markdown_parser.write(old, {"name": "Alpha Proj", "type": "project", "status": "active"},
                          claims.write_claims("## Summary\nAlpha.", rows))
    assert claims_ledger.ledger_lines(old)
    new = ents / "alpha-project.md"
    old.replace(new)
    claims_ledger.move(old, new)
    entity_merge.rename_references(tmp_path / "memory", "alpha-proj", "Alpha Proj", "alpha-project", "Alpha Project")
    after = claims.parse_claims(markdown_parser.parse(new).body)
    twice = sum(1 for v in Counter(c.id for c in after).values() if v > 1)
    assert (len(after), twice, sum(1 for c in after if c.subject == "alpha-proj")) == (600, 0, 0)


def test_a_body_read_without_the_ledger_never_removes_a_ledger_line(tmp_path):
    memory = _owner_bank(tmp_path, git=False)
    page = memory / "entities" / f"{OWNER}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    held = claims_ledger.ledger_lines(page)
    raw = markdown_parser.parse(page, ledger=False)
    markdown_parser.write(page, raw.frontmatter, claims.write_claims(raw.body, []))   # the page's claims, emptied
    assert claims_ledger.ledger_lines(page) == held


def test_a_failed_dedup_merge_leaves_no_ledger_behind(tmp_path, monkeypatch):
    """A merge whose winner write created its first ledger and then failed puts the winner back without it (the
    reviewer's reproduction, kept): nothing for the winner's next write to adopt."""
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(mem)], check=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        _git(mem, "config", k, v)

    def rows(subject, n, tag):
        return [Claim(id=f"clm_{subject}_{i:05d}", text=f"{subject} {tag} item {i} " + "x" * 60, subject=subject,
                      predicate=f"{tag}-{i % 5}", object=f"thing-{tag}-{i}", valid_from="2026-01-01",
                      recorded_at="2026-01-01") for i in range(n)]

    win, lose = mem / "entities" / "alpha-project.md", mem / "entities" / "alpha-proj.md"
    markdown_parser.write(win, {"name": "Alpha Project", "type": "project", "status": "active"},
                          claims.write_claims("## Summary\nA.", rows("alpha-project", 80, "w")))
    markdown_parser.write(lose, {"name": "Alpha Proj", "type": "project", "status": "active"},
                          claims.write_claims("## Summary\nA.", rows("alpha-proj", 80, "l")))
    assert not claims_ledger.path_for(win).exists()
    _git(mem, "add", "-A")
    _git(mem, "commit", "-qm", "seed")

    def boom(*a, **k):
        raise RuntimeError("synthetic failure after the winner write")

    monkeypatch.setattr(entity_merge, "repoint_references", boom)
    assert dedup_sweep._merge_and_commit(mem, "alpha-proj", "alpha-project", None) == dedup_sweep.FAILED
    assert not claims_ledger.path_for(win).exists()
    assert _git(mem, "status", "--porcelain", "--untracked-files=all").strip() == ""


def test_a_successful_dedup_merge_commits_the_ledger_its_winner_write_created(tmp_path):
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(mem)], check=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        _git(mem, "config", k, v)
    win, lose = mem / "entities" / "alpha-project.md", mem / "entities" / "alpha-proj.md"
    for path, eid in ((win, "alpha-project"), (lose, "alpha-proj")):
        rows = [Claim(id=f"clm_{eid}_{i:05d}", text=f"{eid} item {i} " + "x" * 60, subject=eid, predicate=f"p-{i % 5}",
                      object=f"thing-{eid}-{i}", valid_from="2026-01-01", recorded_at="2026-01-01") for i in range(80)]
        markdown_parser.write(path, {"name": eid.replace("-", " ").title(), "type": "project", "status": "active"},
                              claims.write_claims("## Summary\nA.", rows))
    _git(mem, "add", "-A")
    _git(mem, "commit", "-qm", "seed")
    ids = _record(mem, "alpha-project")[0] | _record(mem, "alpha-proj")[0]
    assert dedup_sweep._merge_and_commit(mem, "alpha-proj", "alpha-project", None) == dedup_sweep.MERGED
    assert claims_ledger.path_for(win).exists()
    assert _git(mem, "status", "--porcelain", "--untracked-files=all").strip() == ""
    assert _record(mem, "alpha-project")[0] == ids


def test_a_rerun_finishes_an_interrupted_split(tmp_path, monkeypatch):
    memory = _owner_bank(tmp_path)
    ids, spans = _record(memory)
    real = git_service.commit_paths_sync

    def interrupted(*a, **k):
        raise RuntimeError("synthetic stop before the commit")

    monkeypatch.setattr(git_service, "commit_paths_sync", interrupted)
    with pytest.raises(RuntimeError):
        hub_pages.apply(memory, sleep_running=lambda: False)
    assert _git(memory, "status", "--porcelain").strip()            # written, not committed
    monkeypatch.setattr(git_service, "commit_paths_sync", real)
    again = hub_pages.apply(memory, sleep_running=lambda: False)
    assert again.resumed >= 1 and again.committed and again.dirty == 0
    assert _git(memory, "status", "--porcelain", "--untracked-files=all").strip() == ""
    assert _record(memory) == (ids, spans)
    assert hub_pages.TRIGGER in _git(memory, "log", "-1", "--format=%B")


def test_a_rerun_finishes_a_split_stopped_between_the_ledger_and_the_page(tmp_path):
    memory = _owner_bank(tmp_path)
    page = memory / "entities" / f"{OWNER}.md"
    ids, spans = _record(memory)
    plan = hub_pages.survey(memory)._todo[page]
    _fm, _body, ledger = claims_ledger.split(page, plan[1], plan[2])
    claims_ledger.path_for(page).write_bytes(ledger)                 # the ledger landed; the page did not
    result = hub_pages.apply(memory, sleep_running=lambda: False)
    assert result.committed and result.dirty == 0
    assert _git(memory, "status", "--porcelain", "--untracked-files=all").strip() == ""
    assert _record(memory) == (ids, spans)
    assert page.stat().st_size < 60_000


def test_a_persons_edit_on_a_hub_page_is_never_committed_by_the_split(tmp_path):
    memory = _owner_bank(tmp_path)
    page = memory / "entities" / f"{OWNER}.md"
    page.write_text(page.read_text() + "\nA note the person typed.\n")
    result = hub_pages.apply(memory, sleep_running=lambda: False)
    assert result.dirty == 1 and "A note the person typed." in page.read_text()
    assert f"entities/{OWNER}.md" in _git(memory, "status", "--porcelain")
