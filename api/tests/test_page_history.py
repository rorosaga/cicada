"""The History tab's rows (ruling 48 part 14, DR-77): one bucket rule, a summary per commit, one git call, lazy.

The card open reads no git (part B, 2026-10-29); the tab asks ``GET /entities/{id}/history?summary=true&limit=30``.
"""
from __future__ import annotations

import json

import pytest

from api.services import git_service, page_history
from api.tests.test_contributors import _commit, _init_repo, _write_entity, run


@pytest.fixture
def repo(tmp_path):
    _init_repo(tmp_path / "memory")
    return tmp_path / "memory"


def _claim(cid: str, **kw) -> str:
    return json.dumps({"id": cid, "text": f"Belief {cid}.", "predicate": "is", "superseded_by": None,
                       "valid_to": None, **kw})


def _page(prose: str, claims: list[str], *, conf: str = "0.8") -> str:
    return (f"---\nname: Alpha Place\ntype: location\nconfidence: {conf}\n---\n\n## Summary\n\n{prose}\n\n"
            "```claims\n" + "\n".join(claims) + "\n```\n")


def _history(repo):
    _write_entity(repo, "alpha-place", _page("A place by the [[beta-river|river]].", [_claim("c1")]))
    _commit(repo, git_service.build_commit_message(
        "Sleep cycle 2026-10-01", ["entities/alpha-place.md: created (trigger: sleep/extraction, sessions: ses_a)"],
        authors=["claude-haiku-4-5"]))
    _write_entity(repo, "alpha-place", _page("A place by the river.\nYou build there on **Saturdays**.",
                                             [_claim("c1"), _claim("c2"), _claim("c3")]))
    _commit(repo, git_service.build_commit_message(
        "Sleep cycle 2026-10-02", ["entities/alpha-place.md: updated (trigger: sleep/extraction, sessions: ses_b)"],
        authors=["claude-sonnet-5"]))
    _write_entity(repo, "alpha-place", _page("A place by the river.\nYou build there on **Saturdays**.",
                                             [_claim("c1", valid_to="2026-10-03"), _claim("c2"), _claim("c3")],
                                             conf="0.7"))
    _commit(repo, git_service.build_commit_message(
        "Sleep cycle 2026-10-03 (decay)", ["entities/alpha-place.md: decay (source: n/a, trigger: sleep/decay)"],
        authors=["cicada"]))
    _write_entity(repo, "alpha-place", _page("A makerspace by the river.\nYou build there on **Saturdays**.",
                                             [_claim("c1", valid_to="2026-10-03"), _claim("c2"), _claim("c3")],
                                             conf="0.7"))
    _commit(repo, git_service.build_commit_message(
        "Page edit 2026-10-04", ["entities/alpha-place.md: updated (trigger: mcp/claude-code)"],
        authors=["claude-code"]))
    _write_entity(repo, "alpha-place", _page("A makerspace by the river.\nYou build there on **Saturdays**.",
                                             [_claim("c1", valid_to="2026-10-03"), _claim("c2"),
                                              _claim("c3", superseded_by="c4"), _claim("c4")], conf="0.7"))
    _commit(repo, git_service.build_commit_message(
        "Inbox resolution 2026-10-05", ["entities/alpha-place.md: updated (trigger: inbox/conflict)"],
        authors=["user"]))


@pytest.mark.parametrize("trigger, author, kind, want", [
    ("sleep/extraction", "claude-haiku-4-5", "model", "sleep"),
    ("inbox/conflict/settled", "claude-haiku-4-5", "model", "sleep"),
    ("sleep/decay", "cicada", "system", "upkeep"),
    ("sleep/in-short", "claude-haiku-4-5", "model", "sleep"),
    ("user/companion_app", "user", "user", "you"),
    ("inbox/conflict", "user", "user", "you"),
    ("mcp/claude-code", "claude-code", "harness", "agents"),
    ("remote/claude-web", "claude-web", "harness", "agents"),
    ("sync/geocoder", "cicada", "system", "upkeep"),
    ("user/feed_poll", "cicada", "system", "upkeep"),
    ("migration/sources", "cicada", "system", "upkeep"),
    ("", "user", "user", "you"),
    ("", "claude-code", "harness", "agents"),
    ("", "gpt-5.4-mini", "model", "sleep"),          # a pre-manifest Sleep commit
    ("", "unknown", "unknown", "upkeep"),
])
def test_one_bucket_rule(trigger, author, kind, want):
    assert page_history.bucket(trigger, git_service.history_via(trigger), author, kind) == want


def test_rows_carry_bucket_time_and_what_changed(repo):
    _history(repo)
    rows, more = run(page_history.page("alpha-place", repo, limit=30))
    assert more is False
    assert [r.bucket for r in rows] == ["you", "agents", "upkeep", "sleep", "sleep"]
    assert all(r.at[:4] == r.date[:4] and "T" in r.at for r in rows)
    you, agent, decay, second, first = rows
    assert (you.summary.plus_claims, you.summary.ended_claims, you.summary.changed_claims) == (1, 1, 1)
    assert agent.summary.prose_added == 1 and agent.summary.prose_removed == 1
    assert [(x.sign, x.text) for x in agent.summary.lines] == [("-", "A place by the river."),
                                                             ("+", "A makerspace by the river.")]
    assert decay.summary.fields == ["confidence"] and decay.summary.ended_claims == 1
    assert second.summary.plus_claims == 2 and second.sessions == ["ses_b"]
    assert ("+", "You build there on Saturdays.") in [(x.sign, x.text) for x in second.summary.lines]
    assert first.summary.plus_claims == 1 and first.change_type == "created"
    assert "river" in first.summary.lines[0].text and "[[" not in first.summary.lines[0].text


def test_frontmatter_list_items_and_ids_are_not_prose():
    patch = ("@@ -12,0 +13,2 @@\n+- ep_2026-10-29_003\n+- makerspace\n@@ -40 +41 @@\n"
             "-The _old_ line about ep_2026-10-29_001.\n+The new line about ep_2026-10-29_001.\n")
    s = page_history.summarize(patch)
    assert (s.prose_added, s.prose_removed) == (1, 1)
    assert [x.text for x in s.lines] == ["The old line about ep_2026-10-29_001.", "The new line about ep_2026-10-29_001."]


def test_one_git_call_bounded_by_limit_and_paged_by_skip(repo, monkeypatch):
    _history(repo)
    calls = []
    original = git_service._run_git

    async def counting(memory_path, *args):
        calls.append(args[0])
        return await original(memory_path, *args)

    monkeypatch.setattr(git_service, "_run_git", counting)
    rows, more = run(page_history.page("alpha-place", repo, limit=2))
    assert calls == ["log"] and len(rows) == 2 and more is True
    older, more = run(page_history.page("alpha-place", repo, limit=2, skip=4))
    assert len(older) == 1 and more is False and older[0].change_type == "created"


def test_a_page_outside_git_has_no_rows(tmp_path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "alpha-place.md").write_text("x\n")
    assert run(page_history.page("alpha-place", tmp_path)) == ([], False)


def test_the_route_serves_summaries_and_says_whether_there_is_more(repo, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    _history(repo)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(repo))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    resp = client.get("/entities/alpha-place/history", params={"summary": "true", "limit": 3})
    assert resp.status_code == 200 and resp.headers["x-history-more"] == "1"
    body = resp.json()
    assert len(body) == 3 and body[0]["bucket"] == "you" and body[0]["summary"]["plusClaims"] == 1
    # The plain route is unchanged: no summary, every row.
    plain = client.get("/entities/alpha-place/history").json()
    assert len(plain) == 5 and plain[0]["summary"] is None
    # The card open reads no git.
    calls = []
    original = git_service._run_git

    async def counting(memory_path, *args):
        calls.append(args[0])
        return await original(memory_path, *args)

    monkeypatch.setattr(git_service, "_run_git", counting)
    card = client.get("/entities/alpha-place").json()
    assert card["history"] == [] and calls == []


def test_the_shared_fixture_carries_every_key_the_route_serves(repo, monkeypatch):
    """`fixtures/page_history.json` is what `PageHistoryTests.swift` decodes: it must hold every key a row has."""
    from pathlib import Path

    from fastapi.testclient import TestClient

    from api import config, main

    _history(repo)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(repo))
    config.get_settings.cache_clear()
    served = TestClient(main.app).get("/entities/alpha-place/history", params={"summary": "true"}).json()
    fixture = json.loads((Path(__file__).parent / "fixtures" / "page_history.json").read_text())["rows"]
    assert set(served[0]) == set(fixture[0])
    assert set(served[0]["summary"]) == set(fixture[0]["summary"])
    assert {r["bucket"] for r in fixture} == set(page_history.BUCKETS)
    for row in fixture:   # the fixture's own rows follow the one rule
        assert page_history.bucket(row["trigger"], row["via"], row["author"], row["authorKind"]) == row["bucket"]
