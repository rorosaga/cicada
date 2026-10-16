"""The entity card's History comes from ONE `git log` over the page (F3, benchmarks/scale).

`git blame --porcelain` plus one `git log -1` per surviving commit cost 1.0 s on a 3,500-claim page (41 commits) and
1.7 s at 6,000 (61); one log over the path is ~30 ms. The rows become "every commit that touched the page", newest
first — the rule `entity_commit_authors` already serves the provenance strip.
"""
from __future__ import annotations

from api.services import git_service
from api.tests.test_contributors import _commit, _init_repo, _write_entity, run

import pytest


@pytest.fixture
def repo(tmp_path):
    _init_repo(tmp_path / "memory")
    return tmp_path / "memory"


def _three_commits(repo):
    _write_entity(repo, "alpha-project", "first line\n")
    _commit(repo, git_service.build_commit_message(
        "Sleep cycle 2026-10-01", ["entities/alpha-project.md: created (trigger: sleep/extraction, sessions: ses_a)",
                                   "entities/beta-tool.md: created"], authors=["model-a"], sessions=["ses_a", "ses_b"]))
    _write_entity(repo, "alpha-project", "rewritten line\n")
    _commit(repo, git_service.build_commit_message(
        "Inbox resolution 2026-10-02", ["entities/alpha-project.md: status changed | archived"], authors=["user"]))
    _write_entity(repo, "alpha-project", "rewritten line\nsecond line\n")
    _commit(repo, git_service.build_commit_message(
        "Sleep cycle 2026-10-03", ["entities/alpha-project.md: updated (trigger: sleep, sessions: ses_c)"],
        authors=["model-b"]))


def test_history_lists_every_commit_that_touched_the_page_newest_first(repo):
    _three_commits(repo)
    history = run(git_service.get_entity_history("alpha-project", repo))
    assert [e.author for e in history] == ["model-b", "user", "model-a"]
    # The creating commit's line was overwritten; blame dropped it, the page's history keeps it.
    created = history[-1]
    assert created.change_type == "created"
    assert created.sessions == ["ses_a"]
    assert created.description.startswith("entities/alpha-project.md: created")
    assert history[1].change_type == "statusChange"
    assert history[1].description == "entities/alpha-project.md: status changed | archived"
    assert history[0].sessions == ["ses_c"]
    assert all(len(e.commit_hash) == 40 for e in history)


def test_history_is_one_git_call_under_the_cap_and_bounded_past_it(repo, monkeypatch):
    _three_commits(repo)
    calls = []
    original = git_service._run_git

    async def counting(memory_path, *args):
        calls.append(args[0])
        return await original(memory_path, *args)

    monkeypatch.setattr(git_service, "_run_git", counting)
    run(git_service.get_entity_history("alpha-project", repo))
    assert calls == ["log"]
    calls.clear()
    monkeypatch.setattr(git_service, "MAX_PROVENANCE_COMMITS", 2)
    history = run(git_service.get_entity_history("alpha-project", repo))
    # Past the cap, blame finds which commits still author lines; both survivors are already in the window (the
    # creating commit's only line was rewritten), so no third call.
    assert calls == ["log", "blame"]
    assert [e.author for e in history] == ["model-b", "user"]


def test_history_of_a_page_outside_git_is_empty(tmp_path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "alpha-project.md").write_text("x\n")
    assert run(git_service.get_entity_history("alpha-project", tmp_path)) == []


def _long_history(repo, extra: int = 1):
    """One persistent line written by the creating commit, a second line rewritten by every later commit — past
    MAX_PROVENANCE_COMMITS (the review's round-1 reproduction, with the real cap)."""
    import subprocess

    stream = bytearray()
    for i in range(git_service.MAX_PROVENANCE_COMMITS + extra):
        content = f"---\nname: Alpha Project\ntype: project\n---\n\n## Summary\nPersistent original statement.\nState {i}.\n".encode()
        message = git_service.build_commit_message(
            f"Synthetic update {i}",
            ["entities/alpha-project.md: created (sessions: ses_initial)" if i == 0 else
             "entities/alpha-project.md: updated"], authors=["seed-author" if i == 0 else "update-author"]).encode()
        stream.extend(f"commit refs/heads/synthetic\ncommitter Synthetic <probe@example.com> {1767225600 + i} +0000\n"
                      f"data {len(message)}\n".encode())
        stream.extend(message + b"\nM 100644 inline entities/alpha-project.md\n")
        stream.extend(f"data {len(content)}\n".encode() + content + b"\n")
    subprocess.run(["git", "-C", str(repo), "symbolic-ref", "HEAD", "refs/heads/synthetic"], check=True)
    subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"], input=bytes(stream), check=True)
    subprocess.run(["git", "-C", str(repo), "reset", "--hard", "-q"], check=True)


def test_past_the_cap_every_surviving_commit_stays_and_the_cut_is_said(repo):
    _long_history(repo)
    rows, truncated = run(git_service.entity_history("alpha-project", repo))
    assert truncated is True
    created = [e for e in rows if e.change_type == "created"]
    assert len(created) == 1
    assert created[0].author == "seed-author" and created[0].sessions == ["ses_initial"]
    assert rows[-1].commit_hash == created[0].commit_hash          # newest first, the survivor last
    assert len(rows) == git_service.MAX_PROVENANCE_COMMITS + 1
    assert len({e.commit_hash for e in rows}) == len(rows)
    # The plain list the card and the History route serve keeps the creation row too.
    assert created[0].commit_hash in {e.commit_hash for e in run(git_service.get_entity_history("alpha-project", repo))}


def test_older_rows_are_reachable_with_skip(repo):
    _long_history(repo, extra=3)
    newest, truncated = run(git_service.entity_history("alpha-project", repo))
    older, more = run(git_service.entity_history("alpha-project", repo, skip=git_service.MAX_PROVENANCE_COMMITS))
    assert truncated is True and more is False
    assert [e.description for e in older] == ["entities/alpha-project.md: updated"] * 2 + [
        "entities/alpha-project.md: created (sessions: ses_initial)"]
    assert not {e.commit_hash for e in older} & {e.commit_hash for e in newest[:git_service.MAX_PROVENANCE_COMMITS]}


def test_under_the_cap_nothing_is_flagged(repo):
    _three_commits(repo)
    rows, truncated = run(git_service.entity_history("alpha-project", repo))
    assert truncated is False and len(rows) == 3


def test_the_card_and_the_history_route_carry_the_flag_and_the_skip(repo, monkeypatch):
    from api.routers import entities as entities_router

    _long_history(repo)
    settings = type("S", (), {"memory_path": repo})()
    monkeypatch.setattr(entities_router.decay_policy, "spacing_params", lambda s: (0.5, 0.1))
    card = run(entities_router.get_entity("alpha-project", settings))
    assert card.history_truncated is True
    older = run(entities_router.get_entity_history("alpha-project", skip=git_service.MAX_PROVENANCE_COMMITS,
                                                   settings=settings))
    assert [e.change_type for e in older] == ["created"]
