"""A repository keeps its identity across a rename, a move and a fresh clone — by its git remote, hashed (G110 D2 as
amended by the owner 2026-10-29: "Yes, hashed only"). Synthetic repositories, banks and names only."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import subprocess

import pytest

from _continuity_fixtures import sid
from api.services import (agent_memory_notes, continuity, entity_resolver, episode_staging, markdown_parser,
                          project_birth, project_timeline, workspace_identity)
from api.tests.test_sleep_cycle_hold import _bank, _entity, _settings
from test_continuity_on_demand import env  # noqa: F401
from test_workspace_continuity import start, stop

ORIGIN = "git@example.com:Example/alpha-project.git"


def observer():
    spec = importlib.util.spec_from_file_location("remote_identity_observer", "api/hooks/workspace_identity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(tmp_path, *args):
    git_env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(tmp_path),
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", *map(str, args)], env=git_env, check=True, capture_output=True)


def _repo(tmp_path, path, origin=ORIGIN):
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init", path)
    if origin:
        _git(tmp_path, "-C", path, "remote", "add", "origin", origin)
    return path


# --- the hook: one more fixed read, a salted hash, never the URL ------------------------------------------------------


@pytest.mark.parametrize("url", [
    "git@example.com:Example/alpha-project.git", "ssh://git@example.com:22/example/alpha-project",
    "https://someone@EXAMPLE.com/example/alpha-project/", "https://example.com/example/alpha-project.git",
    "ssh://example.com/example//alpha-project.git/"])
def test_every_spelling_of_one_remote_normalises_the_same(url):
    assert observer().normalise_remote(url.encode() + b"\n") == "example.com/example/alpha-project"


@pytest.mark.parametrize("raw", [None, b"", b"\n", b"a\nb\n", b"x\x00y", b"\xff", b"h" * 5000])
def test_anything_but_one_url_line_is_no_remote(raw):
    assert observer().normalise_remote(raw) is None


def test_the_hook_sends_a_salted_hash_and_never_the_url(tmp_path):
    mod = observer()
    repo = _repo(tmp_path, tmp_path / "work" / "alpha-project")
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    home = tmp_path / "hook-home"
    value = mod.observe(str(repo), home=home, environ=env)
    assert set(value) == {"cwd_hash", "observed_at", "repo_root", "common_dir", "scope_hash", "remote_hash"}
    assert "example" not in repr(value).replace(str(tmp_path), "")
    salt = (home / mod.SALT_FILE)
    assert oct(salt.stat().st_mode & 0o777) == "0o600" and len(salt.read_text()) == 32
    assert value["remote_hash"] == mod.remote_hash("example.com/example/alpha-project", salt.read_text())
    # Another install salts differently: the same public repository is not one recognisable hash everywhere.
    other = mod.observe(str(repo), home=tmp_path / "other-home", environ=env)
    assert other["remote_hash"] != value["remote_hash"]
    # The hint cache still keeps only the cwd hash and time.
    mod.remember(home, "claude-code", sid(1), value, environ=env)
    (hint,) = (home / "continuity-hook-hints").iterdir()
    assert "remote" not in hint.read_text()


def test_no_origin_or_no_salt_keeps_the_pair_without_a_remote(tmp_path):
    mod = observer()
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    bare = _repo(tmp_path, tmp_path / "no-origin", origin=None)
    assert {"repo_root", "common_dir"} <= set(value := mod.observe(str(bare), home=tmp_path / "h", environ=env))
    assert "remote_hash" not in value
    blocked = tmp_path / "blocked-home"
    blocked.mkdir()
    (blocked / mod.SALT_FILE).symlink_to(tmp_path / "elsewhere")   # never followed, never hashed unsalted
    value = mod.observe(str(_repo(tmp_path, tmp_path / "with-origin")), home=blocked, environ=env)
    assert "repo_root" in value and "remote_hash" not in value


def test_the_third_read_is_fixed_and_shares_the_pairs_deadline(tmp_path, monkeypatch):
    mod = observer()
    monkeypatch.setattr(mod, "_executable", lambda env: "/synthetic/git")
    calls, now = [], [10.0]

    def run(argv, cwd, env, deadline):
        calls.append((argv, deadline))
        now[0] += 0.02
        return {"--git-common-dir": b"/synthetic/root/.git\n", "--show-toplevel": b"/synthetic/root\n",
                "remote.origin.url": b"https://example.com/example/alpha\n"}[argv[-1]]

    value = mod.observe("/synthetic/root", home=tmp_path, environ={}, run=run, clock=lambda: now[0])
    assert [c[0][1:] for c in calls][-1] == ["-c", "core.fsmonitor=false", "config", "--get", "remote.origin.url"]
    assert all(c[1] == pytest.approx(10.1) for c in calls) and len(calls) == 3 and "remote_hash" in value
    # Past the deadline the remote is skipped, the pair's observation kept.
    calls.clear()
    now[0] = 10.0

    def slow(argv, cwd, env, deadline):
        now[0] += 0.025   # the pair ends at 10.09; the remote's read lands past the 10.1 deadline
        return run(argv, cwd, env, deadline)

    value = mod.observe("/synthetic/root", home=tmp_path, environ={}, run=slow, clock=lambda: now[0])
    assert "repo_root" in value and "remote_hash" not in value


# --- the parser: either key ------------------------------------------------------------------------------------------


def _parsed(cwd, root, common, remote=None, scope="a" * 16):
    raw = {"repo_root": root, "common_dir": common, "scope_hash": scope, "cwd_hash": workspace_identity.digest(cwd),
           "observed_at": continuity.datetime.now(continuity.timezone.utc).isoformat()}
    if remote:
        raw["remote_hash"] = remote
    return workspace_identity.parse(cwd, raw)


def test_the_parser_keys_a_checkout_by_its_place_in_the_remote():
    r = "c" * 16
    old = _parsed("/w/alpha-project", "/w/alpha-project", "/w/alpha-project/.git", r)
    moved = _parsed("/x/y/alpha-renamed", "/x/y/alpha-renamed", "/x/y/alpha-renamed/.git", r)
    worker = _parsed("/x/y/alpha-renamed/.worktrees/fix", "/x/y/alpha-renamed/.worktrees/fix",
                     "/x/y/alpha-renamed/.git", r)
    other = _parsed("/w/beta", "/w/beta", "/w/beta/.git", "d" * 16)
    legacy = {k: v for k, v in old.items() if k not in workspace_identity.REMOTE_KEYS}
    assert workspace_identity.same_checkout(old, moved) and not workspace_identity.same_path_checkout(old, moved)
    assert not workspace_identity.same_checkout(old, worker) and workspace_identity.same_family(old, worker)
    assert not workspace_identity.same_family(old, other)
    assert workspace_identity.same_checkout(old, legacy) and not workspace_identity.same_checkout(moved, legacy)
    assert workspace_identity.clean(moved) == moved
    assert workspace_identity.clean({**moved, "remote_hash": "not-a-hash"}) == {
        k: v for k, v in moved.items() if k not in workspace_identity.REMOTE_KEYS}
    assert not set(_parsed("/w/a", "/w/a", "/w/a/.git", "nothex" * 3)) & set(workspace_identity.REMOTE_KEYS)


# --- continuity: the pointer survives a rename, a move and a fresh clone ---------------------------------------------


def _moved(tmp_path, repo, how):
    if how == "rename":
        return repo.rename(repo.with_name("alpha-renamed"))
    if how == "move":
        target = tmp_path / "elsewhere" / "deeper" / "alpha-project"
        target.parent.mkdir(parents=True)
        return shutil.move(str(repo), str(target)) and target
    shutil.rmtree(repo)   # cloned again elsewhere, under another spelling of the same remote
    return _repo(tmp_path, tmp_path / "clones" / "alpha-project", origin="https://example.com/example/alpha-project")


@pytest.mark.parametrize("how", ["rename", "move", "reclone"])
def test_the_startup_pointer_follows_the_repository(env, tmp_path, how):
    mod = observer()
    git_env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    hook_home = tmp_path / "hook-home"
    repo = _repo(tmp_path, tmp_path / "work" / "alpha-project")
    source = stop(env, "claude-code", 1, repo, mod.observe(str(repo), home=hook_home, environ=git_env))
    new = _moved(tmp_path, repo, how)
    note = start(env, "claude-code", new, mod.observe(str(new), home=hook_home, environ=git_env))
    assert source["episodeId"] in note
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness=None, session_id=None, cwd=str(new))
    assert ctx.chosen.episode_id == source["episodeId"]
    assert "renamed, moved or cloned again" in continuity.full_text(ctx)


def test_a_worker_worktree_of_the_moved_repository_is_still_only_a_choice(env, tmp_path):
    mod = observer()
    git_env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    hook_home = tmp_path / "hook-home"
    repo = _repo(tmp_path, tmp_path / "work" / "alpha-project")
    _git(tmp_path, "-C", repo, "-c", "user.name=example", "-c", "user.email=example@example.com",
         "commit", "--allow-empty", "-m", "synthetic")
    worker = repo / ".worktrees" / "worker-a"
    _git(tmp_path, "-C", repo, "worktree", "add", "--detach", worker)
    stop(env, "claude-code", 1, worker, mod.observe(str(worker), home=hook_home, environ=git_env),
         role="worker role sentinel")
    clone = _repo(tmp_path, tmp_path / "clones" / "alpha-project")
    note = start(env, "claude-code", clone, mod.observe(str(clone), home=hook_home, environ=git_env))
    assert "related" in note.lower() and "worker role sentinel" not in note


# --- projects: one page per repository ---------------------------------------------------------------------------


EP_A, TS_A = "ep_2026-10-20_001", "2026-10-20T10:00:00+00:00"
EP_B, TS_B = "ep_2026-10-21_001", "2026-10-21T10:00:00+00:00"
REMOTE = "e" * 16


def _repo_birth(name, family, remote=REMOTE, ep=EP_B):
    return {"origin": "repo", "day": ep[3:13], "episode": ep,
            "repo": {"name": name, "family": family, **({"remote": remote} if remote else {})}}


def _page(eid, name, born):
    return {"id": eid, "frontmatter": {"name": name, "type": "project", "status": "active", "confidence": 0.8,
                                       "born": born}, "body": f"## Summary\n{name} is a synthetic project."}


def _resolve(memory, mention, pages, monkeypatch):
    async def judge(*_a, **_k):
        return "different"

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return ["different" for _ in entries]
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    return asyncio.run(entity_resolver.resolve([{"episode_id": EP_B, "entities": [mention], "relationships": []}],
                                               pages, _settings(memory)))


def _mention(name, birth):
    entity = _entity(name, "project", EP_B, TS_B)
    entity["project_birth"] = birth
    return entity


def test_a_renamed_repository_is_the_project_page_it_already_has(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    page = _page("alpha-project", "alpha-project", _repo_birth("alpha-project", "a" * 16, ep=EP_A))
    out = _resolve(memory, _mention("alpha-renamed", _repo_birth("alpha-renamed", "b" * 16)), [page], monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", "alpha-project")]


def test_a_page_born_before_the_remote_was_read_is_found_through_a_later_session(tmp_path, monkeypatch):
    """The page's birth holds a family only; a later session in that same checkout carried family and remote."""
    memory = _bank(tmp_path)
    cwd = "/home/someone/code/alpha-project"
    markdown_parser.write(memory / "episodes" / f"{EP_A}.md", {
        "id": EP_A, "harness": "claude-code", "timestamp": TS_A, "project_dir": cwd,
        "workspace_identity": {"cwd_hash": workspace_identity.digest(cwd), "family_hash": "a" * 16,
                               "checkout_hash": "f" * 16, "observed_at": TS_A, "remote_hash": REMOTE,
                               "remote_checkout_hash": "9" * 16}}, "user: synthetic")
    page = _page("alpha-project", "alpha-project", _repo_birth("alpha-project", "a" * 16, remote=None, ep=EP_A))
    out = _resolve(memory, _mention("alpha-renamed", _repo_birth("alpha-renamed", "b" * 16)), [page], monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", "alpha-project")]


@pytest.mark.parametrize("other", [
    {"remote": "1" * 16},                                   # another repository
    {"remote": None},                                       # no remote read: the old behaviour, a page of its own
])
def test_without_the_same_remote_a_birth_is_its_own_page(tmp_path, monkeypatch, other):
    memory = _bank(tmp_path)
    page = _page("alpha-project", "alpha-project", _repo_birth("alpha-project", "a" * 16, ep=EP_A))
    out = _resolve(memory, _mention("beta-tool", _repo_birth("beta-tool", "b" * 16, **other)), [page], monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("create", "beta-tool")]


def test_two_pages_on_one_remote_join_neither(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    pages = [_page("alpha-project", "alpha-project", _repo_birth("alpha-project", "a" * 16, ep=EP_A)),
             _page("alpha-two", "alpha-two", _repo_birth("alpha-two", "c" * 16, ep=EP_A))]
    out = _resolve(memory, _mention("alpha-renamed", _repo_birth("alpha-renamed", "b" * 16)), pages, monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("create", "alpha-renamed")]


def test_a_birth_records_the_remote_and_the_repository_keeps_its_activity(tmp_path):
    memory = _bank(tmp_path)
    old_dir, new_dir = "/home/someone/code/alpha-project", "/home/someone/elsewhere/alpha-renamed"
    for ep, ts, cwd, family in ((EP_A, TS_A, old_dir, "a" * 16), (EP_B, TS_B, new_dir, "b" * 16)):
        markdown_parser.write(memory / "episodes" / f"{ep}.md", {
            "id": ep, "harness": "claude-code", "source": "claude-code", "timestamp": ts, "project_dir": cwd,
            "workspace_identity": {"cwd_hash": workspace_identity.digest(cwd), "family_hash": family,
                                   "checkout_hash": "f" * 16, "observed_at": ts, "remote_hash": REMOTE,
                                   "remote_checkout_hash": "9" * 16}}, "user: synthetic")
    fm_a = markdown_parser.parse(memory / "episodes" / f"{EP_A}.md").frontmatter
    born = project_birth.at_extraction({"name": "alpha-project"}, episode_id=EP_A, frontmatter=fm_a, text="",
                                       day="2026-10-20")
    assert born["repo"] == {"name": "alpha-project", "family": "a" * 16, "remote": REMOTE}
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "status": "active", "born": born}, "")
    bank = project_timeline._Bank(memory, None)
    assert len(bank.page_repo_sessions("alpha-project", bank.fm("alpha-project"))) == 2
    assert project_timeline._repo_days(bank, ["alpha-project"]) == {"2026-10-20", "2026-10-21"}


# --- ruling 43's notes: a moved notes folder is the same notes -------------------------------------------------------


NOTE = "---\nname: Tests\ndescription: run targeted tests\nmetadata:\n  type: feedback\n---\nRun the touched tests.\n"
OLD, NEW = "-home-someone-code-alpha-project", "-home-someone-code-alpha-renamed"


def _snap(*projects, text=NOTE):
    return [{"project": p, "file": "feedback_tests.md", "text": text, "modified_at": TS_A} for p in projects]


def _live(memory):
    index, _ = episode_staging.scan(memory / "episodes")
    return sorted((sid, e.path.name) for sid, e in index.items() if not e.fm.get("source_deleted_at"))


def _ingest(memory, notes, complete=True):
    return agent_memory_notes.ingest(memory, notes, harness="claude-code", device=None, complete=complete)


def test_a_moved_notes_folder_keeps_its_episodes(tmp_path):
    memory = _bank(tmp_path)
    _ingest(memory, _snap(OLD))
    (before,) = _live(memory)
    path = memory / "episodes" / before[1]
    fm = dict(markdown_parser.parse(path).frontmatter, processed=True, processed_by="sleep")
    markdown_parser.write(path, fm, markdown_parser.parse(path).body)
    out = _ingest(memory, _snap(NEW))
    assert (out["created"], out["moved"], out["tombstoned"]) == (0, 1, 0)
    (after,) = _live(memory)
    assert after[1] == before[1] and after[0].endswith(NEW + "/feedback_tests.md")
    fm = markdown_parser.parse(path).frontmatter
    assert fm["processed"] is True and fm["agent_memory"]["project"] == NEW   # not re-read by Sleep


@pytest.mark.parametrize("complete", [True, False])
def test_a_copied_notes_folder_is_no_second_episode(tmp_path, complete):
    memory = _bank(tmp_path)
    _ingest(memory, _snap(OLD))
    out = _ingest(memory, _snap(OLD, NEW), complete=complete)
    assert (out["created"], out["copies"]) == (0, 1) and len(_live(memory)) == 1


def test_a_note_held_before_its_hash_was_kept_is_stamped_then_moves(tmp_path):
    memory = _bank(tmp_path)
    _ingest(memory, _snap(OLD))
    (held,) = _live(memory)
    path = memory / "episodes" / held[1]
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {k: v for k, v in parsed.frontmatter.items() if k != "content_sha"}, parsed.body)
    assert _ingest(memory, _snap(OLD))["created"] == 0          # restamped, frontmatter only
    assert _ingest(memory, _snap(NEW))["moved"] == 1 and len(_live(memory)) == 1


def test_a_changed_note_in_a_new_folder_is_still_new(tmp_path):
    memory = _bank(tmp_path)
    _ingest(memory, _snap(OLD))
    out = _ingest(memory, _snap(NEW, text=NOTE + "Edited.\n"))
    assert (out["created"], out["tombstoned"]) == (1, 1)
