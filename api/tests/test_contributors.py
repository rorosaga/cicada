"""Hermetic tests for git-provenance contributors + per-entity authoring + diffs.

Every test builds a throwaway git repo in a tmp dir with hand-crafted commits
carrying ``Cicada-Author:`` trailers. The real ``memory/`` and the repo's own
git history are never touched.
"""

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import git_service


def run(coro):
    """Drive an async git_service call from a sync test (no anyio dependency)."""
    return asyncio.run(coro)


# --- tiny git harness -------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    (repo / "entities").mkdir(exist_ok=True)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _write_entity(repo: Path, entity_id: str, body: str) -> None:
    (repo / "entities" / f"{entity_id}.md").write_text(body, encoding="utf-8")


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "memory"
    _init_repo(r)
    return r


# --- commit message builder -------------------------------------------------


def test_build_commit_message_appends_single_author_trailer():
    msg = git_service.build_commit_message(
        "Sleep cycle 2026-06-17",
        body_lines=["entities/foo.md: created (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"],
    )
    assert msg.startswith("Sleep cycle 2026-06-17\n\n")
    assert "entities/foo.md: created" in msg
    assert "Cicada-Author: gpt-5.4-mini" in msg


def test_build_commit_message_dedupes_and_lists_multiple_authors():
    msg = git_service.build_commit_message(
        "Sleep cycle",
        body_lines=["entities/foo.md: updated"],
        authors=["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.4-mini"],
    )
    # one trailer per distinct author, order preserved, no dupes
    trailers = [ln for ln in msg.splitlines() if ln.startswith("Cicada-Author:")]
    assert trailers == [
        "Cicada-Author: gpt-5.4-mini",
        "Cicada-Author: gpt-5.4-nano",
    ]


def test_build_commit_message_no_authors_omits_trailer():
    msg = git_service.build_commit_message("Subject", body_lines=["x: y"], authors=[])
    assert "Cicada-Author" not in msg


# --- contributors aggregation ----------------------------------------------


def test_contributors_aggregates_models_and_user(repo):
    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle 2026-06-15",
            body_lines=["entities/alpha.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini"],
        ),
    )
    _write_entity(repo, "beta", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle 2026-06-16",
            body_lines=["entities/beta.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini", "gpt-5.4-nano"],
        ),
    )
    _write_entity(repo, "alpha", "v2 user edit")
    _commit(
        repo,
        git_service.build_commit_message(
            "Inbox resolution (decay) 2026-06-17",
            body_lines=["entities/alpha.md: updated (trigger: user/companion_app)"],
            authors=["user"],
        ),
    )

    contributors = run(git_service.get_contributors(repo))
    by_author = {c.author: c for c in contributors}

    assert set(by_author) == {"gpt-5.4-mini", "gpt-5.4-nano", "user"}
    assert by_author["gpt-5.4-mini"].commit_count == 2
    assert by_author["gpt-5.4-nano"].commit_count == 1
    assert by_author["user"].commit_count == 1
    # gpt-5.4-mini authored alpha (created) + beta -> 2 distinct entities
    assert by_author["gpt-5.4-mini"].entity_count == 2
    # user touched only alpha
    assert by_author["user"].entity_count == 1
    assert "entities/alpha.md" in by_author["user"].files
    # last-active timestamps are ISO date strings, newest commit wins for user
    assert by_author["user"].last_active >= by_author["gpt-5.4-mini"].last_active


def test_contributors_untrailered_commit_attributed_to_unknown(repo):
    _write_entity(repo, "gamma", "v1")
    # plain commit, no trailer at all
    _commit(repo, "Sleep cycle legacy\n\nentities/gamma.md: created")

    contributors = run(git_service.get_contributors(repo))
    by_author = {c.author: c for c in contributors}
    assert "unknown" in by_author
    assert by_author["unknown"].commit_count == 1


def test_contributors_on_non_git_dir_returns_empty(tmp_path):
    assert run(git_service.get_contributors(tmp_path / "nope")) == []


# --- G15: contributor kind / provider / avatar derivation -------------------


def test_classify_author_kind_user_model_unknown():
    assert git_service._classify_author_kind("user") == "user"
    assert git_service._classify_author_kind("unknown") == "unknown"
    assert git_service._classify_author_kind("gpt-5.4-mini") == "model"
    assert git_service._classify_author_kind("claude-sonnet-4") == "model"
    assert git_service._classify_author_kind("gemini-2.0-flash") == "model"


def test_provider_for_model_openai():
    for mid in ["gpt-5.4-mini", "gpt-4o", "o1-preview", "o3-mini", "text-embedding-3-small"]:
        assert git_service._provider_for_model(mid) == "openai", mid
    # o-series anchored forms: bare id, hyphen-prefixed token, provider-prefixed.
    for mid in ["o1", "o3", "openai/o1-pro", "o3-2025-04-16"]:
        assert git_service._provider_for_model(mid) == "openai", mid


def test_provider_for_model_o_series_not_unanchored_substring():
    # "o1"/"o3" must NOT match as bare substrings of unrelated ids.
    for mid in ["macro1", "no1se", "retro3-model", "calico1"]:
        assert git_service._provider_for_model(mid) == "other", mid


def test_provider_for_model_anthropic():
    for mid in ["claude-sonnet-4-20250514", "anthropic/claude-opus-4", "claude-3-5-haiku"]:
        assert git_service._provider_for_model(mid) == "anthropic", mid


def test_provider_for_model_google():
    for mid in ["gemini-2.0-flash", "gemini/gemini-1.5-pro", "gemma-2-9b", "google/gemma-3"]:
        assert git_service._provider_for_model(mid) == "google", mid


def test_provider_for_model_other_and_non_model():
    # `mistral-large` / `llama-3` used to live here: Track L R-L6 gave the
    # open-weight families real providers, so the "unmatched" case needs an id
    # that genuinely matches nothing — a model behind a router, named bare.
    assert git_service._provider_for_model("glm-5.2") == "other"
    assert git_service._provider_for_model("command-r-plus") == "other"
    # user / unknown are not models -> no provider
    assert git_service._provider_for_model("user") is None
    assert git_service._provider_for_model("unknown") is None


# --- Track L (R-L6): the system author, and the router that billed ----------


def test_classify_author_kind_system():
    """R-L6 — `cicada` is the literal author of system maintenance with no
    model and no user in the loop (the state snapshot, the split-out decay
    commit, the one-shot migrations). It used to classify as a *model* with
    provider "other", so Cicada's own commits showed as an anonymous grey "?"
    in its own contributors list."""
    assert git_service._classify_author_kind("cicada") == "system"
    assert git_service._provider_for_model("cicada") is None


def test_provider_for_model_router_before_the_first_slash_wins():
    """R9/R-L6 — an OpenRouter id names the model it proxied; the router is who
    billed. A bare substring pass would map `openrouter/z-ai/glm-5.2` to
    nothing and `openrouter/anthropic/claude-opus-4` to Anthropic, which is a
    lie about who was paid."""
    assert git_service._provider_for_model("openrouter/z-ai/glm-5.2") == "openrouter"
    assert git_service._provider_for_model("openrouter/anthropic/claude-opus-4") == "openrouter"
    assert git_service._provider_for_model("ollama/llama3.2") == "ollama"
    # A provider prefix that is NOT a router keeps the substring behaviour.
    assert git_service._provider_for_model("anthropic/claude-opus-4") == "anthropic"


def test_provider_for_model_open_weight_families():
    """The families a local/router engine actually serves. Before R-L6 all four
    answered "other" and shared one grey badge with every unknown id."""
    assert git_service._provider_for_model("llama-3") == "meta"
    assert git_service._provider_for_model("mistral-large") == "mistral"
    assert git_service._provider_for_model("mixtral-8x7b") == "mistral"
    assert git_service._provider_for_model("deepseek-v3") == "deepseek"
    assert git_service._provider_for_model("qwen2.5-72b") == "qwen"


def test_github_handle_from_remote_https():
    assert (
        git_service._github_handle_from_remote_url(
            "https://github.com/rorosaga/cicada.git"
        )
        == "rorosaga"
    )


def test_github_handle_from_remote_ssh():
    assert (
        git_service._github_handle_from_remote_url("git@github.com:rorosaga/cicada.git")
        == "rorosaga"
    )


def test_github_handle_from_remote_non_github_is_none():
    assert git_service._github_handle_from_remote_url("https://gitlab.com/x/y.git") is None
    assert git_service._github_handle_from_remote_url("") is None
    assert git_service._github_handle_from_remote_url(None) is None


def test_contributors_avatar_kind_provider_fields(repo):
    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle",
            body_lines=["entities/alpha.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini"],
        ),
    )
    _write_entity(repo, "beta", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Inbox resolution",
            body_lines=["entities/beta.md: updated (trigger: user/companion_app)"],
            authors=["user"],
        ),
    )
    # legacy untrailered commit -> unknown
    _write_entity(repo, "gamma", "v1")
    _commit(repo, "Sleep cycle legacy\n\nentities/gamma.md: created")

    contributors = run(git_service.get_contributors(repo, github_user="rorosaga"))
    by_author = {c.author: c for c in contributors}

    # model: kind=model, provider derived, no avatar
    gpt = by_author["gpt-5.4-mini"]
    assert gpt.kind == "model"
    assert gpt.provider == "openai"
    assert gpt.avatar_url is None

    # user: kind=user, no provider, avatar from explicit handle
    user = by_author["user"]
    assert user.kind == "user"
    assert user.provider is None
    assert user.avatar_url == "https://github.com/rorosaga.png"

    # unknown: kind=unknown, no provider, no avatar
    unk = by_author["unknown"]
    assert unk.kind == "unknown"
    assert unk.provider is None
    assert unk.avatar_url is None


def test_contributors_user_avatar_falls_back_to_remote_handle(repo):
    """No explicit github_user -> derive the handle from `origin` remote."""
    _git(repo, "remote", "add", "origin", "git@github.com:rorosaga/cicada.git")
    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Inbox resolution",
            body_lines=["entities/alpha.md: updated (trigger: user/companion_app)"],
            authors=["user"],
        ),
    )
    contributors = run(git_service.get_contributors(repo))
    user = {c.author: c for c in contributors}["user"]
    assert user.avatar_url == "https://github.com/rorosaga.png"


def test_contributors_user_avatar_none_without_handle_or_remote(repo):
    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Inbox resolution",
            body_lines=["entities/alpha.md: updated (trigger: user/companion_app)"],
            authors=["user"],
        ),
    )
    contributors = run(git_service.get_contributors(repo))
    user = {c.author: c for c in contributors}["user"]
    assert user.avatar_url is None


# --- OPTIONAL #2: sleep history lists files for the root commit --------------


def test_sleep_history_root_commit_lists_files(repo):
    """The initial (parentless) sleep-cycle commit must still report its files."""
    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle 2026-06-15",
            body_lines=["entities/alpha.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini"],
        ),
    )
    history = run(git_service.get_sleep_history(repo))
    assert history
    root = history[-1]  # log is newest-first; the root commit is last
    assert "entities/alpha.md" in root.files_changed


# --- per-entity authoring ---------------------------------------------------


def test_entity_history_carries_authoring_model(repo):
    _write_entity(repo, "alpha", "line one\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle 2026-06-15",
            body_lines=["entities/alpha.md: created (trigger: sleep/extraction)"],
            authors=["gpt-5.4-mini"],
        ),
    )
    _write_entity(repo, "alpha", "line one\nline two by user\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Inbox resolution 2026-06-17",
            body_lines=["entities/alpha.md: updated (trigger: user/manual_edit)"],
            authors=["user"],
        ),
    )

    history = run(git_service.get_entity_history("alpha", repo))
    authors = {e.author for e in history}
    # both the model and the user appear as authors of alpha's current lines
    assert "gpt-5.4-mini" in authors
    assert "user" in authors


def test_entity_history_missing_entity_is_empty(repo):
    assert run(git_service.get_entity_history("does-not-exist", repo)) == []


# --- per-commit diff --------------------------------------------------------


def test_entity_commit_diff_returns_added_and_removed(repo):
    _write_entity(repo, "alpha", "alpha v1\nshared\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", "alpha v2\nshared\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    assert "alpha v2" in diff.added
    assert "alpha v1" in diff.removed
    # unchanged context line is not double-counted as add/remove
    assert "shared" not in diff.added
    assert "shared" not in diff.removed


def test_entity_commit_diff_missing_commit_returns_empty(repo):
    _write_entity(repo, "alpha", "alpha v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    diff = run(git_service.get_entity_commit_diff("alpha", "deadbeef" * 5, repo))
    assert diff.added == "" and diff.removed == ""


# --- MUST-FIX #1: argument injection via commit_hash ------------------------


def test_entity_commit_diff_rejects_flag_like_commit_hash_no_file_write(repo, tmp_path):
    """A commit_hash beginning with '-' must NOT be parsed by git as a flag.

    Reproduces the reported arg-injection: `git show --output=<path>` would write
    an arbitrary file. A malformed/hostile hash must yield an empty diff and write
    nothing.
    """
    _write_entity(repo, "alpha", "alpha v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    pwned = tmp_path / "PWNED"
    assert not pwned.exists()

    diff = run(git_service.get_entity_commit_diff("alpha", f"--output={pwned}", repo))

    # No file written, and the call degrades to an empty diff rather than 500ing.
    assert not pwned.exists()
    assert diff.added == "" and diff.removed == ""


def test_entity_commit_diff_rejects_non_hex_commit_hash(repo):
    """Anything that isn't a 7-40 char hex sha is rejected -> empty diff."""
    _write_entity(repo, "alpha", "alpha v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    for bad in ["HEAD", "main..HEAD", "../etc", "zzzzzzz", "a" * 41, "abc"]:
        diff = run(git_service.get_entity_commit_diff("alpha", bad, repo))
        assert diff.added == "" and diff.removed == "", bad


# --- MUST-FIX #2: diff output must be bounded -------------------------------


def test_entity_commit_diff_is_bounded(repo):
    """A huge rewrite must not produce an unbounded payload; output is capped
    and flagged truncated."""
    _write_entity(repo, "alpha", "seed\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    big = "\n".join(f"line {i}" for i in range(5000)) + "\n"
    _write_entity(repo, "alpha", big)
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    added_lines = diff.added.splitlines()
    # Capped well below the 5000 added lines.
    assert len(added_lines) <= git_service.DIFF_MAX_LINES + 1
    assert diff.truncated is True
    assert any("truncat" in ln.lower() for ln in added_lines[-2:])


def test_entity_commit_diff_small_diff_not_truncated(repo):
    _write_entity(repo, "alpha", "alpha v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", "alpha v2\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )
    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    assert diff.truncated is False


# --- G69: unified diff with context lines + line numbers ---------------------


def _numbered(entity_lines: list[str]) -> str:
    return "\n".join(entity_lines) + "\n"


def test_diff_lines_interleave_context_with_changes_in_file_order(repo):
    """The ordered `lines` list is a real unified diff: unchanged context rows
    sit between the removals and additions, in file order."""
    _write_entity(repo, "alpha", _numbered([f"l{i}" for i in range(1, 11)]))
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    body = [f"l{i}" for i in range(1, 11)]
    body[4] = "CHANGED"
    _write_entity(repo, "alpha", _numbered(body))
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    kinds = [ln.kind for ln in diff.lines]

    assert kinds[0] == "hunk"
    # 4 lines of context either side of the single change (DIFF_CONTEXT_LINES).
    assert kinds[1:] == ["context"] * 4 + ["remove", "add"] + ["context"] * 4
    texts = [ln.text for ln in diff.lines]
    assert texts[1:5] == ["l1", "l2", "l3", "l4"]
    assert texts[5] == "l5" and texts[6] == "CHANGED"
    assert texts[7:] == ["l6", "l7", "l8", "l9"]


def test_diff_line_numbers_follow_git_accounting(repo):
    _write_entity(repo, "alpha", _numbered([f"l{i}" for i in range(1, 11)]))
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    body = [f"l{i}" for i in range(1, 11)]
    body[4] = "CHANGED"
    _write_entity(repo, "alpha", _numbered(body))
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    by_kind = {}
    for ln in run(git_service.get_entity_commit_diff("alpha", sha, repo)).lines:
        by_kind.setdefault(ln.kind, []).append(ln)

    # hunk header carries neither number
    assert by_kind["hunk"][0].old_line is None
    assert by_kind["hunk"][0].new_line is None
    # a removal has only an old number; an addition only a new one
    assert (by_kind["remove"][0].old_line, by_kind["remove"][0].new_line) == (5, None)
    assert (by_kind["add"][0].old_line, by_kind["add"][0].new_line) == (None, 5)
    # context carries both, and they advance in lockstep on an equal-size edit
    first_ctx = by_kind["context"][0]
    assert (first_ctx.old_line, first_ctx.new_line) == (1, 1)
    last_ctx = by_kind["context"][-1]
    assert (last_ctx.old_line, last_ctx.new_line) == (9, 9)


def test_diff_line_numbers_stay_offset_after_an_insertion(repo):
    """After a pure insertion the two sides diverge — old/new must not be
    assumed equal."""
    _write_entity(repo, "alpha", _numbered(["a", "b", "c"]))
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", _numbered(["a", "INSERTED", "b", "c"]))
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    lines = run(git_service.get_entity_commit_diff("alpha", sha, repo)).lines
    inserted = next(ln for ln in lines if ln.text == "INSERTED")
    assert inserted.kind == "add" and inserted.new_line == 2 and inserted.old_line is None
    # "b" was line 2 before, line 3 after
    b = next(ln for ln in lines if ln.text == "b")
    assert (b.kind, b.old_line, b.new_line) == ("context", 2, 3)


def test_diff_lines_carry_multiple_hunks_in_order(repo):
    """Two changes far apart produce two `@@` hunks, ordered, each restarting
    the numbering from its own header."""
    _write_entity(repo, "alpha", _numbered([f"l{i}" for i in range(1, 41)]))
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    body = [f"l{i}" for i in range(1, 41)]
    body[2] = "TOP"
    body[34] = "BOTTOM"
    _write_entity(repo, "alpha", _numbered(body))
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    lines = run(git_service.get_entity_commit_diff("alpha", sha, repo)).lines
    hunk_positions = [i for i, ln in enumerate(lines) if ln.kind == "hunk"]
    assert len(hunk_positions) == 2, "two distant changes must not coalesce"
    assert hunk_positions[0] == 0
    assert all(ln.text.startswith("@@ ") for ln in lines if ln.kind == "hunk")

    top = next(ln for ln in lines if ln.text == "TOP")
    bottom = next(ln for ln in lines if ln.text == "BOTTOM")
    assert top.new_line == 3 and bottom.new_line == 35
    # order preserved: everything in hunk 1 precedes everything in hunk 2
    assert lines.index(top) < hunk_positions[1] < lines.index(bottom)


def test_first_commit_of_a_file_is_all_additions_with_no_parent(repo):
    """A ROOT commit has no `^` parent — `git show` diffs it against the empty
    tree, so the file's first commit comes back as all-adds, not an error."""
    _write_entity(repo, "alpha", _numbered(["one", "two", "three"]))
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    assert _git(repo, "rev-list", "--count", sha).strip() == "1", "must be a root commit"

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    kinds = [ln.kind for ln in diff.lines]
    assert kinds == ["hunk", "add", "add", "add"]
    assert [ln.new_line for ln in diff.lines[1:]] == [1, 2, 3]
    assert all(ln.old_line is None for ln in diff.lines[1:])
    assert diff.lines[0].text.startswith("@@ -0,0 +1,3 @@")


def test_a_file_added_in_a_later_non_root_commit_is_also_all_additions(repo):
    _write_entity(repo, "seed", "seed\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/seed.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", _numbered(["one", "two"]))
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    assert [ln.kind for ln in diff.lines] == ["hunk", "add", "add"]
    assert diff.added == "one\ntwo" and diff.removed == ""


def test_a_merge_commit_renders_a_real_diff_not_an_empty_one(repo):
    """Fix round 1 / M2. Left to itself ``git show`` emits a COMBINED (``--cc``)
    diff for a merge, whose ``@@@ … @@@`` headers the hunk regex cannot match —
    the endpoint would return an empty diff and the app would say "no line
    changes" for a commit that plainly changed the file. ``--first-parent``
    makes it a two-sided diff against parent 1, like any ordinary commit."""
    _write_entity(repo, "alpha", _numbered(["l1", "l2", "l3", "l4", "l5", "l6"]))
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    # A side branch and the trunk edit the SAME line -> the merge must be
    # resolved by hand, so the merge commit itself carries content.
    _git(repo, "checkout", "-q", "-b", "side")
    _write_entity(repo, "alpha", _numbered(["l1", "l2", "SIDE", "l4", "l5", "l6"]))
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )
    _git(repo, "checkout", "-q", "-")
    _write_entity(repo, "alpha", _numbered(["l1", "l2", "MAIN", "l4", "l5", "l6"]))
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )
    subprocess.run(  # conflicts on purpose -> non-zero exit, resolved below
        ["git", "merge", "side", "-q"], cwd=str(repo), capture_output=True, text=True
    )
    _write_entity(repo, "alpha", _numbered(["l1", "l2", "RESOLVED", "l4", "l5", "l6"]))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-edit")
    sha = _git(repo, "rev-parse", "HEAD").strip()
    assert len(_git(repo, "rev-list", "--parents", "-n1", sha).split()) - 1 == 2, "not a merge"

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))

    assert diff.lines, "a merge commit must not render as an empty diff"
    # Two-sided against the FIRST parent (trunk): MAIN -> RESOLVED.
    assert [ln.kind for ln in diff.lines] == [
        "hunk", "context", "context", "remove", "add", "context", "context", "context",
    ]
    removed = next(ln for ln in diff.lines if ln.kind == "remove")
    added = next(ln for ln in diff.lines if ln.kind == "add")
    assert (removed.text, removed.old_line, removed.new_line) == ("MAIN", 3, None)
    assert (added.text, added.old_line, added.new_line) == ("RESOLVED", None, 3)
    # No `@@@`-shaped row leaked through as content.
    assert not any(ln.text.startswith("@@@") for ln in diff.lines)
    # ...and the flat back-compat blocks agree.
    assert diff.added == "RESOLVED" and diff.removed == "MAIN"


def test_first_parent_leaves_ordinary_and_root_commits_untouched(repo):
    """`--first-parent` is inert outside merges — the root-commit all-adds path
    and a plain single-parent commit must be byte-identical to before."""
    _write_entity(repo, "alpha", _numbered(["one", "two"]))
    root = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", _numbered(["one", "TWO"]))
    plain = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    root_diff = run(git_service.get_entity_commit_diff("alpha", root, repo))
    assert [ln.kind for ln in root_diff.lines] == ["hunk", "add", "add"]
    assert [ln.new_line for ln in root_diff.lines[1:]] == [1, 2]

    plain_diff = run(git_service.get_entity_commit_diff("alpha", plain, repo))
    assert [ln.kind for ln in plain_diff.lines] == ["hunk", "context", "remove", "add"]
    assert plain_diff.added == "TWO" and plain_diff.removed == "two"


def test_diff_lines_are_bounded_and_flag_truncated(repo):
    _write_entity(repo, "alpha", "seed\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", "\n".join(f"line {i}" for i in range(5000)) + "\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    assert len(diff.lines) <= git_service.DIFF_MAX_CONTEXT_LINES
    assert diff.truncated is True
    assert diff.lines_truncated is True
    # back-compat side is still capped by its own, smaller bound
    assert len(diff.added.splitlines()) <= git_service.DIFF_MAX_LINES + 1


def test_clipping_only_the_flat_sides_does_not_flag_lines_truncated(repo):
    """Fix round 1 / M1. Between the two caps there is a band — a commit big
    enough to clip the 400-line flat sides but small enough that the ordered
    2000-row list is COMPLETE. The app renders `lines`, so a "diff clipped"
    banner driven by the union flag would sit above a whole diff. The union
    `truncated` still goes true (the flat blocks really were clipped); the
    ordered-path flag must not."""
    _write_entity(repo, "alpha", "seed\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    # 500 additions: over DIFF_MAX_LINES (400), far under DIFF_MAX_CONTEXT_LINES.
    _write_entity(repo, "alpha", "\n".join(f"line {i}" for i in range(500)) + "\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))

    assert git_service.DIFF_MAX_LINES < len(diff.lines) < git_service.DIFF_MAX_CONTEXT_LINES
    assert diff.lines_truncated is False, "the ordered list was complete"
    assert diff.truncated is True, "the flat blocks WERE clipped — union stays true"
    assert diff.added.splitlines()[-1] == git_service._DIFF_TRUNCATION_MARKER
    # Every one of the 500 new lines is present in the ordered list.
    assert sum(1 for ln in diff.lines if ln.kind == "add") == 500


def test_a_small_diff_flags_neither_truncation_field(repo):
    _write_entity(repo, "alpha", "v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", "v2\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    assert diff.truncated is False and diff.lines_truncated is False


def test_back_compat_keys_are_still_present_alongside_lines(repo):
    """An older app build decodes `added`/`removed`/`truncated` only. They must
    keep meaning exactly what they meant pre-G69: the changed lines, no context,
    removals and additions separated."""
    _write_entity(repo, "alpha", _numbered(["keep", "old", "tail"]))
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    _write_entity(repo, "alpha", _numbered(["keep", "new", "tail"]))
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: updated"], authors=["gpt-5.4-mini"]
        ),
    )

    diff = run(git_service.get_entity_commit_diff("alpha", sha, repo))
    payload = diff.model_dump(by_alias=True)
    assert set(payload) >= {"added", "removed", "truncated", "lines", "linesTruncated"}
    assert diff.added == "new"
    assert diff.removed == "old"
    # context never leaks into the flat blocks
    assert "keep" not in diff.added and "keep" not in diff.removed
    # ...but it IS in the ordered list
    assert any(ln.kind == "context" and ln.text == "keep" for ln in diff.lines)
    # camelCase on the wire, matching the Swift decoder
    first = payload["lines"][1]
    assert set(first) == {"kind", "oldLine", "newLine", "text"}


def test_a_rejected_commit_hash_yields_an_empty_lines_list(repo):
    _write_entity(repo, "alpha", "v1\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    for bad in ["HEAD", "--output=/tmp/pwned", "zzzzzzz"]:
        diff = run(git_service.get_entity_commit_diff("alpha", bad, repo))
        assert diff.lines == [] and diff.added == "" and diff.removed == "", bad


def test_parse_unified_diff_treats_plus_prefixed_content_inside_a_hunk_as_content():
    """The pre-hunk `+++`/`---` file headers are skipped by position, not by
    prefix — a markdown line that genuinely starts with `+++` or `---` (YAML
    frontmatter!) must survive as content."""
    out = (
        "diff --git a/entities/alpha.md b/entities/alpha.md\n"
        "index 1111111..2222222 100644\n"
        "--- a/entities/alpha.md\n"
        "+++ b/entities/alpha.md\n"
        "@@ -1,3 +1,3 @@\n"
        "+++ frontmatter fence\n"
        "--- old fence\n"
        " context row\n"
    )
    lines, added, removed, truncated, _ = git_service._parse_unified_diff(out)

    assert [ln.kind for ln in lines] == ["hunk", "add", "remove", "context"]
    assert added == ["++ frontmatter fence"]
    assert removed == ["-- old fence"]
    assert lines[3].text == "context row"
    assert truncated is False


def test_parse_unified_diff_ignores_the_no_newline_marker():
    """`\\ No newline at end of file` annotates the previous row — it is not a
    line of the file and must not consume a line number."""
    out = (
        "@@ -1,2 +1,2 @@\n"
        " first\n"
        "-second\n"
        "\\ No newline at end of file\n"
        "+second!\n"
        "\\ No newline at end of file\n"
    )
    lines, _, _, _, _ = git_service._parse_unified_diff(out)

    assert [ln.kind for ln in lines] == ["hunk", "context", "remove", "add"]
    assert lines[2].old_line == 2 and lines[3].new_line == 2


def test_parse_unified_diff_preserves_a_blank_context_line():
    out = "@@ -1,3 +1,3 @@\n a\n \n-b\n+c\n"
    lines, _, _, _, _ = git_service._parse_unified_diff(out)

    assert [ln.kind for ln in lines] == ["hunk", "context", "context", "remove", "add"]
    assert lines[2].text == "" and lines[2].old_line == 2 and lines[2].new_line == 2


# --- OPTIONAL #3: non-UTF-8 file degrades gracefully (no 500) ----------------


def test_entity_history_non_utf8_file_does_not_raise(repo):
    """A non-UTF-8 entity file must not blow up blame parsing with a 500."""
    (repo / "entities" / "bin.md").write_bytes(b"valid line\n\xff\xfe binary\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/bin.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    # Must not raise UnicodeDecodeError.
    history = run(git_service.get_entity_history("bin", repo))
    assert isinstance(history, list)
    assert history and history[0].author == "gpt-5.4-mini"


def test_entity_history_include_diff_populates_diff_field(repo):
    _write_entity(repo, "alpha", "first\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    history = run(git_service.get_entity_history("alpha", repo, include_diff=True))
    assert history
    assert any(e.diff is not None and "first" in e.diff.added for e in history)


# --- router wiring (endpoint functions called directly, no live app) ---------


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


class _FakeRequest:
    """Minimal stand-in for ``fastapi.Request`` — only ``.headers.get`` is used
    by ``sync_service.conditional`` when a router is called directly (no live
    app), bypassing FastAPI's dependency injection."""

    def __init__(self):
        self.headers: dict[str, str] = {}


def test_contributors_router_returns_response(repo):
    from fastapi import Response

    from api.routers import contributors as contributors_router

    _write_entity(repo, "alpha", "v1")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    resp = run(
        contributors_router.get_contributors(
            request=_FakeRequest(), response=Response(), settings=_FakeSettings(repo)
        )
    )
    assert [c.author for c in resp.contributors] == ["gpt-5.4-mini"]


def test_entities_history_router_include_diff(repo):
    from api.routers import entities as entities_router

    _write_entity(repo, "alpha", "first\n")
    _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    history = run(
        entities_router.get_entity_history(
            "alpha", include_diff=True, settings=_FakeSettings(repo)
        )
    )
    assert history
    assert history[0].author == "gpt-5.4-mini"
    assert history[0].diff is not None and "first" in history[0].diff.added


def test_entities_commit_diff_router(repo):
    from api.routers import entities as entities_router

    _write_entity(repo, "alpha", "first\n")
    sha = _commit(
        repo,
        git_service.build_commit_message(
            "Sleep cycle", body_lines=["entities/alpha.md: created"], authors=["gpt-5.4-mini"]
        ),
    )
    diff = run(
        entities_router.get_entity_commit_diff(
            "alpha", sha, settings=_FakeSettings(repo)
        )
    )
    assert "first" in diff.added
