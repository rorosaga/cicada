"""G140 Q-R6/Q-R7 (R3 P8) — a fact with a stated end stops being current at
that end: `expected_end`, or a G17 `due` date, closed by Sleep's engine-free
tail in its own `cicada` commit. Synthetic bank; no LLM, no network."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api.remote import tools as remote_tools
from api.services import claim_expiry, git_service, markdown_parser, mcp_tools, sleep_cycle
from api.services.claim_reconciler import _reinforce
from api.services.claims import Claim, parse_claims, write_claims

TODAY = date(2026, 9, 23)


def _page(memory: Path, eid: str, claims: list[Claim], body: str | None = None):
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": eid.replace("-", " ").title(), "type": "project", "status": "active"},
                          body if body is not None else write_claims("## Summary\nA page.\n", claims))


def _claims(memory: Path, eid: str) -> dict[str, Claim]:
    return {c.id: c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)}


def _c(cid, **kw) -> Claim:
    kw.setdefault("subject", "alpha-project")
    kw.setdefault("predicate", "has")
    kw.setdefault("object", cid)
    kw.setdefault("valid_from", "2026-09-18")
    return Claim(id=cid, text=f"alpha {cid}", **kw)


def _git(memory: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def test_expected_end_round_trips_and_is_omitted_when_unset():
    claim = _c("c1", expected_end="2026-09-27")
    assert claim.to_dict()["expected_end"] == "2026-09-27"
    assert Claim.from_dict(claim.to_dict()).expected_end == "2026-09-27"
    assert "expected_end" not in _c("c2").to_dict(), "a legacy page never diffs"
    fence = "`" * 3
    body = f"{fence}claims\n- id: c3\n  text: t\n  expected_end: 2026-09-27\n{fence}\n"
    assert parse_claims(body)[0].expected_end == "2026-09-27", "YAML's date comes back as the ISO string"


def test_a_stated_end_that_has_passed_closes_the_claim(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("gone", expected_end="2026-09-20"),
                                    _c("today", expected_end="2026-09-23"),
                                    _c("open")])
    report = claim_expiry.expire(memory, TODAY)
    claims = _claims(memory, "alpha-project")
    assert claims["gone"].valid_to == "2026-09-20" and claims["gone"].superseded_by is None
    assert claims["today"].valid_to is None, "an end is inclusive: current through its own day"
    assert claims["open"].valid_to is None
    assert report.paths == ["entities/alpha-project.md"] and report.claims == [("alpha-project", "gone")]


def test_a_past_due_date_is_its_own_stated_end(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("due", predicate="due", object="2026-09-10", valid_from="2026-09-01"),
                                    _c("due-word", predicate="due", object="next-friday")])
    claim_expiry.expire(memory, TODAY)
    claims = _claims(memory, "alpha-project")
    assert claims["due"].valid_to == "2026-09-10"
    assert claims["due-word"].valid_to is None, "not a date, not an end"


def test_the_persons_own_stated_end_closes_too(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("mine", observer="owner", source_trust="user_stated",
                                       origin="manual_edit", expected_end="2026-09-20")])
    claim_expiry.expire(memory, TODAY)
    assert _claims(memory, "alpha-project")["mine"].valid_to == "2026-09-20", "Q-R7: the end is their statement"


def test_an_end_recorded_after_it_passed_never_closes_before_it_began(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("late", valid_from="2026-09-22", expected_end="2026-09-15"),
                                    _c("undated", valid_from="undated", expected_end="2026-09-15")])
    claim_expiry.expire(memory, TODAY)
    claims = _claims(memory, "alpha-project")
    assert claims["late"].valid_to == "2026-09-22"
    assert claims["undated"].valid_to == "2026-09-15", "a non-date valid_from never becomes valid_to"


def test_closed_claims_and_corrupt_pages_are_left_alone(tmp_path):
    memory = tmp_path / "m"
    _page(memory, "alpha-project", [_c("done", expected_end="2026-09-20", valid_to="2026-09-19",
                                       superseded_by="x")])
    fence = "`" * 3
    corrupt = f"## Summary\nA page.\n\n{fence}claims\n- id: bad\n  expected_end: [unclosed\n{fence}\n"
    _page(memory, "beta-project", [], body=corrupt)
    before = (memory / "entities" / "beta-project.md").read_text()
    report = claim_expiry.expire(memory, TODAY)
    assert report.paths == []
    assert _claims(memory, "alpha-project")["done"].valid_to == "2026-09-19"
    assert (memory / "entities" / "beta-project.md").read_text() == before


def test_a_page_without_a_stated_end_is_never_parsed(tmp_path, monkeypatch):
    memory = tmp_path / "m"
    _page(memory, "plain", [_c("c", predicate="uses")])
    calls: list = []
    real = markdown_parser.parse
    monkeypatch.setattr(markdown_parser, "parse", lambda p: calls.append(p) or real(p))
    claim_expiry.expire(memory, TODAY)
    assert calls == []


def test_a_restated_end_replaces_the_old_one():
    existing = _c("a", expected_end="2026-09-20")
    _reinforce(existing, _c("a", expected_end="2026-09-27"))
    assert existing.expected_end == "2026-09-27"
    _reinforce(existing, _c("a"))
    assert existing.expected_end == "2026-09-27", "a restatement without an end keeps it"


def test_write_claim_takes_an_expected_end(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    out = server.handle_tool("cicada_write_claim", {"subject": "alpha-project", "predicate": "has",
                                                     "object": "exams", "expected_end": "2026-09-27"})
    assert "current through 2026-09-27" in out
    bad = server.handle_tool("cicada_write_claim", {"subject": "alpha-project", "predicate": "has",
                                                     "object": "a trip", "expected_end": "next week"})
    assert "expected_end ignored" in bad
    by_obj = {c.object: c for c in _claims(memory, "alpha-project").values()}
    assert by_obj["exams"].expected_end == "2026-09-27" and by_obj["a trip"].expected_end is None
    for props in ({t["name"]: t for t in server.TOOLS}["cicada_write_claim"]["inputSchema"]["properties"],
                  remote_tools.REMOTE_TOOLS["cicada_write_claim"]["inputSchema"]["properties"]):
        assert props["expected_end"]["type"] == "string"


def _git_bank(tmp_path) -> Path:
    memory = _bank(tmp_path)
    ended = (date.today() - timedelta(days=3)).isoformat()
    _page(memory, "alpha-project", [_c("gone", expected_end=ended, valid_from="2026-01-01")])
    _git(memory, "add", "entities/alpha-project.md")
    _git(memory, "commit", "-q", "-m", "seed a stated end")
    return memory


def test_the_tail_commits_expiry_alone_as_cicada(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _git_bank(tmp_path)
    asyncio.run(sleep_cycle._expire_claims_safely(memory))
    log = _git(memory, "log", "-1", "--format=%s%n%b")
    assert log.startswith(f"Expiry {date.today().isoformat()}")
    assert "entities/alpha-project.md: expired (source: n/a, trigger: sleep/expiry)" in log
    assert "Cicada-Author: cicada" in log and "Cicada-Engine" not in log
    assert _git(memory, "status", "--porcelain") == ""
    history = asyncio.run(git_service.get_sleep_history(memory, limit=10))
    assert not any(h.message.startswith("Expiry") for h in history), "the Sleep page lists consolidations"


def test_a_failed_expiry_commit_puts_the_pages_back(tmp_path, monkeypatch):
    memory = _git_bank(tmp_path)

    async def boom(*a, **k):
        raise git_service.GitError("index.lock is held")

    monkeypatch.setattr(git_service, "commit_paths", boom)
    asyncio.run(sleep_cycle._expire_claims_safely(memory))
    assert _git(memory, "status", "--porcelain") == "", "never left for the next `git add -A` writer"
    assert _claims(memory, "alpha-project")["gone"].valid_to is None, "re-derived tomorrow"


def _order(monkeypatch) -> list[str]:
    order: list[str] = []

    def fake(name):
        async def _f(*a, **k):
            order.append(name)
        return _f

    for name in ("_refresh_state_safely", "_expire_claims_safely", "_poll_connectors_safely",
                 "_poll_feeds_and_calendars_safely", "_backfill_links_safely", "_warm_logos_safely",
                 "_refresh_questions_safely"):
        monkeypatch.setattr(sleep_cycle, name, fake(name))
    return order


def test_expiry_runs_first_in_the_guarded_branch(monkeypatch):
    order = _order(monkeypatch)
    asyncio.run(sleep_cycle._run_engine_independent_tail(
        Path("/nonexistent"), SimpleNamespace(), sleep_cycle._StageOutcome(committed=True)))
    assert order[:3] == ["_refresh_state_safely", "_expire_claims_safely", "_poll_connectors_safely"]


def test_expiry_never_runs_on_a_half_written_cycle(monkeypatch):
    order = _order(monkeypatch)

    async def dirty(_path):
        return " M entities/x.md\n"

    monkeypatch.setattr(git_service, "porcelain_status", dirty)
    sleep_cycle._state.write_started = True
    try:
        asyncio.run(sleep_cycle._run_engine_independent_tail(
            Path("/nonexistent"), SimpleNamespace(), sleep_cycle._StageOutcome(committed=False)))
    finally:
        sleep_cycle._state.write_started = False
    assert "_expire_claims_safely" not in order


def test_history_says_a_fact_ended_at_its_stated_end(tmp_path):
    memory = tmp_path / "m"
    ended = (date.today() - timedelta(days=2)).isoformat()
    _page(memory, "alpha-project", [_c("exams", expected_end=ended, valid_from="2026-01-01", valid_to=ended)])
    lines = mcp_tools._recent_changes(memory / "entities", [{"entity_id": "alpha-project"}], date.today())
    assert lines == [f'- `alpha-project` has: "exams" ended {ended} (its stated end)']
