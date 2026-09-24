"""G147 — per-type pace: Cicada proposes from the bank's OWN decay answers
(git history, never the telemetry ledger), and nothing changes until the person
applies it (UX principle 3; G78/G113: nothing learned is auto-applied).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import types
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from api.models.schemas import InboxResolveRequest
from api.routers import memory as memory_router
from api.services import conflict_resolver, decay_tuning, git_service, inbox_service, markdown_parser

TODAY = date(2026, 9, 24)


def run(coro):
    return asyncio.run(coro)


def _git(m: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(m), *args], check=True, capture_output=True, text=True,
        env={**os.environ, **(env or {})},
    ).stdout


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


class _SleepSettings(_FakeSettings):
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


def _page(m: Path, eid: str, etype: str, **fm) -> None:
    base = {"name": eid, "type": etype, "status": "active", "confidence": 0.5}
    base.update(fm)
    markdown_parser.write(m / "entities" / f"{eid}.md", base, "A synthetic page.\n")


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    for i in range(1, 11):
        _page(m, f"person-{i:02d}", "person")
    for i in range(1, 4):
        _page(m, f"tool-{i:02d}", "tool")
    _git(m, "add", "-A")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def _answer(m: Path, eid: str, label: str, *, days_ago: int, today: date = TODAY) -> None:
    """One decay answer, committed exactly as `git_service.commit_resolution` writes it."""
    when = datetime.combine(today - timedelta(days=days_ago), datetime.min.time()).replace(hour=12)
    change = "status active" if label == "keep_active" else "status archived"
    message = git_service.build_commit_message(
        f"Inbox resolution (decay) {when.date().isoformat()}",
        [f"entities/{eid}.md: {change} (trigger: inbox/decay/resolved:{label})"],
        authors=["user"],
    )
    stamp = when.isoformat()
    _git(m, "commit", "-q", "--allow-empty", "-m", message,
         env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})


def _suggestions(m: Path, today: date = TODAY) -> list[dict]:
    return run(decay_tuning.overview(m, today=today))["suggestions"]


# --- suggestions (R-FD6) --------------------------------------------------------


def test_nine_keeps_of_ten_people_suggest_fading_people_more_slowly(bank):
    for i in range(1, 10):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=20 + i)
    _answer(bank, "person-10", "archive", days_ago=5)
    assert _suggestions(bank) == [{
        "type": "person", "direction": "slower", "multiplier": 0.5,
        "kept": 9, "archived": 1, "answers": 10,
    }]


def test_fewer_than_five_answers_suggest_nothing(bank):
    for i in range(1, 5):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    assert _suggestions(bank) == []


def test_eighty_percent_is_on_the_line_and_seventy_is_not(bank):
    for i in range(1, 5):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    _answer(bank, "person-05", "archive", days_ago=6)
    assert [s["direction"] for s in _suggestions(bank)] == ["slower"]  # 4 of 5
    for i in range(6, 11):
        _answer(bank, f"person-{i:02d}", "archive" if i >= 9 else "keep_active", days_ago=i)
    # now 7 kept of 10 (person-05, -09, -10 archived) -> 70 %: nothing either way
    assert _suggestions(bank) == []


def test_mostly_archived_suggests_fading_faster(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "archive", days_ago=i)
    assert _suggestions(bank) == [{
        "type": "person", "direction": "faster", "multiplier": 1.5,
        "kept": 0, "archived": 5, "answers": 5,
    }]


def test_one_vote_per_page_its_latest_answer(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "archive", days_ago=40)
    for i in range(1, 5):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=3)
    assert _suggestions(bank) == [{
        "type": "person", "direction": "slower", "multiplier": 0.5,
        "kept": 4, "archived": 1, "answers": 5,
    }]


def test_answers_older_than_the_window_do_not_count(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=200)
    assert _suggestions(bank) == []
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=170)
    assert _suggestions(bank)[0]["answers"] == 5


def test_deferrals_and_other_kinds_are_not_verdicts(bank):
    for i in range(1, 7):
        message = git_service.build_commit_message(
            "Inbox resolution (conflict) 2026-09-20",
            [f"entities/person-{i:02d}.md: updated (trigger: inbox/conflict/resolved:pick:1)",
             f"inbox/inbox-{i:03d}.md: deferred until 2026-10-01 (trigger: inbox/deferred)"],
            authors=["user"],
        )
        _git(bank, "commit", "-q", "--allow-empty", "-m", message)
    assert _suggestions(bank, today=date.today()) == []


def test_a_page_that_no_longer_exists_is_skipped(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    (bank / "entities" / "person-01.md").unlink()
    assert _suggestions(bank) == []  # 4 answers left


def test_a_pace_already_applied_is_not_offered_again(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    decay_tuning.save(bank, {"person": 0.5})
    out = run(decay_tuning.overview(bank, today=TODAY))
    assert out["suggestions"] == []
    assert out["tuning"] == {"person": 0.5}


def test_the_payload_carries_no_page_ids_or_names(bank):
    for i in range(1, 10):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    text = json.dumps(run(decay_tuning.overview(bank, today=TODAY)))
    assert "person-0" not in text


def test_the_real_resolver_is_what_the_parser_reads(bank):
    """Producer and parser pinned together: five real keep answers through
    `inbox_service.resolve` (the app's and the MCP tool's one path)."""
    (bank / "inbox").mkdir()
    for i in range(1, 6):
        (bank / "inbox" / f"inbox-{i:03d}.md").write_text(
            "---\nkind: decay\nrequired_input: choice\nstatus: pending\npriority: 0.3\n"
            f"entity_id: person-{i:02d}\nentity_name: Person {i}\n"
            f"title: Still tracking Person {i}?\ncreated_date: 2026-08-01\n---\n"
        )
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "items")

    class _InboxSettings(_FakeSettings):
        inbox_defer_days = 30
        litellm_model = "test-model"
        inbox_stale_after_days = 90

    for i in range(1, 6):
        run(inbox_service.resolve(f"inbox-{i:03d}", InboxResolveRequest(action="keep_active"),
                                  _InboxSettings(bank)))
    assert _suggestions(bank, today=date.today()) == [{
        "type": "person", "direction": "slower", "multiplier": 0.5,
        "kept": 5, "archived": 0, "answers": 5,
    }]


def test_an_unknown_head_never_keys_the_cache(bank, monkeypatch):
    """A worktree or submodule bank's `.git` is a FILE that `git_head` does not
    follow, so its HEAD reads as "" — a key that never moves. Caching under it
    would hide every answer given after the first read of the day (R-FD6)."""
    from api.services import sync_service

    monkeypatch.setattr(sync_service, "git_head", lambda _p: "")
    for i in range(1, 5):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    assert _suggestions(bank) == []
    _answer(bank, "person-05", "keep_active", days_ago=1)
    assert _suggestions(bank)[0]["answers"] == 5


# --- the file (R-FD7) --------------------------------------------------------------


def test_load_keeps_only_valid_entries(bank):
    (bank / decay_tuning.FILE).write_text(
        "types:\n  person: 0.5\n  unicorn: 0.5\n  tool: fast\n  company: 9\n  concept: 1.0\n"
        "  skill: true\n"
    )
    assert decay_tuning.load(bank) == {"person": 0.5}
    (bank / decay_tuning.FILE).write_text("types: [unclosed\n")
    assert decay_tuning.load(bank) == {}
    assert decay_tuning.load(None) == {}


def test_merge_sets_clears_and_refuses():
    assert decay_tuning.merge({"person": 0.5}, {"tool": 1.5}) == {"person": 0.5, "tool": 1.5}
    assert decay_tuning.merge({"person": 0.5}, {"person": None}) == {}
    assert decay_tuning.merge({"person": 0.5}, {"person": 1.0}) == {}
    with pytest.raises(ValueError):
        decay_tuning.merge({}, {"unicorn": 0.5})
    with pytest.raises(ValueError):
        decay_tuning.merge({}, {"person": 0.1})
    with pytest.raises(ValueError):
        decay_tuning.merge({}, {"person": 4.0})


def test_save_never_creates_a_file_to_hold_nothing(bank):
    assert decay_tuning.save(bank, {}) is False
    assert not (bank / decay_tuning.FILE).exists()
    assert decay_tuning.save(bank, {"person": 0.5}) is True
    assert decay_tuning.save(bank, {"person": 0.5}) is False
    assert (bank / decay_tuning.FILE).read_text().startswith("#")


# --- the endpoints ------------------------------------------------------------------


def test_put_writes_the_file_and_commits_it_alone_as_the_person(bank):
    (bank / "entities" / "tool-01.md").write_text("an unrelated edit\n")
    out = run(memory_router.put_decay_tuning({"person": 0.5}, settings=_FakeSettings(bank)))
    assert out.tuning == {"person": 0.5}
    body = _git(bank, "log", "-1", "--format=%B")
    assert body.startswith("Decay tuning ")
    assert f"{decay_tuning.FILE}: updated (trigger: user/companion_app)" in body
    assert "Cicada-Author: user" in body
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [decay_tuning.FILE]
    assert "entities/tool-01.md" in _git(bank, "status", "--porcelain")


def test_put_null_clears_and_an_unchanged_put_makes_no_commit(bank):
    run(memory_router.put_decay_tuning({"person": 0.5}, settings=_FakeSettings(bank)))
    head = _git(bank, "rev-parse", "HEAD")
    run(memory_router.put_decay_tuning({"person": 0.5}, settings=_FakeSettings(bank)))
    assert _git(bank, "rev-parse", "HEAD") == head
    out = run(memory_router.put_decay_tuning({"person": None}, settings=_FakeSettings(bank)))
    assert out.tuning == {}
    assert _git(bank, "rev-parse", "HEAD") != head


def test_put_refuses_an_unknown_type_or_an_out_of_range_pace(bank):
    for body in ({"unicorn": 0.5}, {"person": 0.1}):
        with pytest.raises(HTTPException) as exc:
            run(memory_router.put_decay_tuning(body, settings=_FakeSettings(bank)))
        assert exc.value.status_code == 422
    assert not (bank / decay_tuning.FILE).exists()


def test_put_is_refused_while_sleep_runs(bank, monkeypatch):
    from api.services import sleep_cycle

    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: types.SimpleNamespace(status="running"))
    with pytest.raises(HTTPException) as exc:
        run(memory_router.put_decay_tuning({"person": 0.5}, settings=_FakeSettings(bank)))
    assert exc.value.status_code == 409
    assert not (bank / decay_tuning.FILE).exists()


def test_get_answers_with_the_same_shape(bank):
    out = run(memory_router.get_decay_suggestions(settings=_FakeSettings(bank)))
    dumped = out.model_dump(mode="json")
    assert dumped == {"bank": "memory", "windowDays": 180, "tuning": {}, "suggestions": []}


def test_main_mounts_both_routes():
    from api import main

    routes = {(m, r.path) for r in main.app.routes if isinstance(r, APIRoute) for m in r.methods}
    assert ("GET", "/memory/decay-suggestions") in routes
    assert ("PUT", "/memory/decay-tuning") in routes


# --- the pass reads the bank's pace ---------------------------------------------------


def test_the_decay_pass_multiplies_by_the_bank_pace(bank):
    decay_tuning.save(bank, {"person": 0.5})
    ago = str(date.today() - timedelta(days=35))
    existing = [
        {"id": "person-01", "frontmatter": {"type": "person", "status": "active", "confidence": 0.7,
                                            "decay_class": "active", "last_referenced": ago}, "body": ""},
        {"id": "tool-01", "frontmatter": {"type": "tool", "status": "active", "confidence": 0.7,
                                          "decay_class": "active", "last_referenced": ago}, "body": ""},
    ]
    changes = {c["id"]: c for c in run(conflict_resolver.resolve_and_prune([], existing, _SleepSettings(bank)))}
    assert changes["person-01"]["new_confidence"] == pytest.approx(0.7 - 0.025)
    assert changes["tool-01"]["new_confidence"] == pytest.approx(0.7 - 0.05)


def test_a_file_that_is_not_utf8_reads_as_no_tuning_and_sleep_still_decays(bank):
    """R4 final review: a hand edit saved as Latin-1 raised UnicodeDecodeError out
    of ``load`` — Stage 3 failed every night after the LLM spend, every entity read
    failed, and the /memory routes that could Reset it failed too."""
    (bank / decay_tuning.FILE).write_bytes(b"types:\n  person: 0.5  # caf\xe9\n")
    assert decay_tuning.load(bank) == {}
    ago = str(date.today() - timedelta(days=35))
    existing = [
        {"id": "person-01", "frontmatter": {"type": "person", "status": "active", "confidence": 0.7,
                                            "decay_class": "active", "last_referenced": ago}, "body": ""},
    ]
    changes = {c["id"]: c for c in run(conflict_resolver.resolve_and_prune([], existing, _SleepSettings(bank)))}
    assert changes["person-01"]["new_confidence"] == pytest.approx(0.7 - 0.05)
