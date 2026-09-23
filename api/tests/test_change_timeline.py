"""G140 Q-R4 (R3 P6) — `cicada_timeline`: what changed in memory, read from
git on demand. A synthetic bank whose commits carry the manifests Cicada's
writers produce, with fixed dates; no network, nothing stored."""
from __future__ import annotations

import os
import subprocess
from datetime import date

import pytest

from _stdio_server import stdio_server
from api.remote import catalog
from api.services import change_timeline, markdown_parser

D1, D2 = "2026-09-20", "2026-09-21"


def _git(repo, *args, when: str | None = None):
    env = dict(os.environ)
    if when:
        env.update(GIT_AUTHOR_DATE=f"{when}T00:30:00+00:00", GIT_COMMITTER_DATE=f"{when}T00:30:00+00:00")
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _commit(repo, message: str, when: str):
    _git(repo, "commit", "-q", "--allow-empty", "-m", message, when=when)


def _repo(path):
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        _git(path, *args)


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    _repo(memory)
    _commit(memory, "Sleep cycle 2026-09-20\n\n"
            "entities/alpha-project.md: created (source: ep_2026-09-20_001, trigger: sleep/extraction)\n"
            "entities/bob-example.md: updated (source: ep_2026-09-20_001, trigger: sleep/extraction)\n\n"
            "Cicada-Author: gpt-5.4-mini\nCicada-Engine: litellm\nCicada-Session: ses_2026-09-20_abcd1234", D1)
    _commit(memory, "Sleep cycle 2026-09-20 (decay)\n\n"
            "entities/beta-project.md: archive (source: n/a, trigger: sleep/decay)\n"
            "entities/gamma-concept.md: decay (source: n/a, trigger: sleep/decay)\n\nCicada-Author: cicada", D1)
    _commit(memory, "State snapshot 2026-09-20\n\n_state.md: updated (trigger: sleep/state)\n\n"
            "Cicada-Author: cicada", D1)
    _commit(memory, "Agent write 2026-09-21\n\n"
            "entities/alpha-project.md: updated (source: n/a, trigger: mcp/claude-code)\n\n"
            "Cicada-Author: claude-code\nCicada-Session: 11111111-2222-4333-8444-555555555555", D2)
    _commit(memory, "Inbox resolution 2026-09-21\n\n"
            "inbox/inbox-001.md: resolved (trigger: inbox/decay/resolved:keep)\n\nCicada-Author: user", D2)
    markdown_parser.write(memory / "episodes" / "ep_2026-09-21_001.md",
                          {"id": "ep_2026-09-21_001", "timestamp": "2026-09-21T12:00:00+00:00",
                           "origin": "claude-code", "title": "A private title"}, "user: something private")
    return memory


def test_days_are_read_from_the_commit_manifests(bank):
    days = change_timeline.collect(bank, date(2026, 9, 19), date(2026, 9, 22))
    assert [d.day.isoformat() for d in days] == [D2, D1], "newest day first"
    d2, d1 = days
    assert d1.created == ["alpha-project"] and d1.updated == 1 and d1.consolidations == 1
    assert d1.authors == ["gpt-5.4-mini"] and d1.conversations == {"ses_2026-09-20_abcd1234"}
    assert d1.archived == ["beta-project"] and d1.faded == 1
    assert dict(d2.agent_writes) == {"claude-code": 1} and d2.answered == 1
    assert dict(d2.captured) == {"claude-code": 1}


def test_a_state_snapshot_is_not_a_change(bank):
    (d1,) = change_timeline.collect(bank, date(2026, 9, 20), date(2026, 9, 20))
    assert d1.consolidations == 1, "the Sleep cycle, never the State snapshot"
    assert change_timeline.kind_of("State snapshot 2026-09-20") is None


def test_the_reply_is_ids_and_counts_only(bank):
    since, until = date(2026, 9, 19), date(2026, 9, 22)
    text = change_timeline.render(change_timeline.collect(bank, since, until), since, until)
    assert text.index("## 2026-09-21") < text.index("## 2026-09-20")
    assert "`alpha-project`" in text and "`beta-project`" in text
    assert "A private title" not in text and "something private" not in text
    assert "ses_2026" not in text and "11111111" not in text, "conversations are counted, never named"


def test_since_is_a_date_or_a_number_of_days_and_is_clamped():
    today = date(2026, 9, 23)
    assert change_timeline.parse_since(None, today) == date(2026, 9, 16)
    assert change_timeline.parse_since("3", today) == date(2026, 9, 20)
    assert change_timeline.parse_since(3, today) == date(2026, 9, 20)
    assert change_timeline.parse_since("3d", today) == date(2026, 9, 20)
    assert change_timeline.parse_since("2026-09-01", today) == date(2026, 9, 1)
    assert change_timeline.parse_since("2020-01-01", today) == date(2026, 6, 25), "MAX_DAYS back"
    assert change_timeline.parse_since("2027-01-01", today) == today
    assert change_timeline.parse_since("soon", today) == date(2026, 9, 16)


def test_no_git_and_an_empty_window_never_raise(tmp_path):
    memory = tmp_path / "plain"
    (memory / "episodes").mkdir(parents=True)
    assert change_timeline.collect(memory, date(2026, 9, 1), date(2026, 9, 2)) == []
    assert change_timeline.render([], date(2026, 9, 1), date(2026, 9, 2)).startswith("Nothing changed")


def test_a_bank_inside_another_repo_never_reads_that_repo(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    _repo(outer)
    _commit(outer, "Sleep cycle 2026-09-20\n\nentities/x.md: created (source: n/a, trigger: sleep/extraction)", D1)
    memory = outer / "bank"
    (memory / "episodes").mkdir(parents=True)
    assert change_timeline.collect(memory, date(2026, 9, 19), date(2026, 9, 22)) == []


def test_the_tool_is_wired_on_stdio_and_read_scope_remotely(bank, monkeypatch):
    today = date.today().isoformat()
    _commit(bank, f"Agent write {today}\n\nentities/alpha-project.md: updated (source: n/a, "
                  "trigger: mcp/codex)\n\nCicada-Author: codex", today)
    srv = stdio_server()
    monkeypatch.setattr(srv, "get_memory_path", lambda: bank)
    out = srv.handle_tool("cicada_timeline", {"since": "1"})
    assert f"## {today}" in out and "codex 1" in out
    assert {t["name"] for t in srv.TOOLS} >= {"cicada_timeline"}
    assert catalog.TOOL_SCOPE["cicada_timeline"] == "read" and "cicada_timeline" in catalog.READ_TOOLS
    assert "cicada_timeline" in catalog.tool_names_for({"read"})
