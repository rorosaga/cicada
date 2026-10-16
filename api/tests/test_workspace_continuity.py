"""G110 B2: supplied git identity; synthetic repositories and banks only."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from _continuity_fixtures import sid
from api.services import continuity, continuity_sessions, markdown_parser
from test_continuity_on_demand import env  # noqa: F401
import test_continuity_on_demand as a1


@pytest.fixture
def repos(tmp_path):
    root = tmp_path / "alpha-project"
    git_env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(tmp_path),
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args):
        return subprocess.run(["git", *map(str, args)], env=git_env, check=True, capture_output=True)

    git("init", root)
    git("-C", root, "-c", "user.name=example", "-c", "user.email=example@example.com",
        "commit", "--allow-empty", "-m", "synthetic initial")
    worker = tmp_path / "elsewhere" / "worker-a"
    worker.parent.mkdir()
    git("-C", root, "worktree", "add", "--detach", worker)
    lexical = root / ".worktrees" / "worker-b"
    git("-C", root, "worktree", "add", "--detach", lexical)
    sub = root / "src"
    sub.mkdir()
    return {"root": root, "worker": worker, "lexical": lexical, "sub": sub,
            "common": root / ".git", "git": git}


def observation(cwd, root, common, *, scope="a" * 16, when=None):
    return {"repo_root": str(root), "common_dir": str(common), "scope_hash": scope,
            "cwd_hash": continuity_sessions.cwd_hash(str(cwd)),
            "observed_at": when or datetime.now(timezone.utc).isoformat()}


def start(env, harness, cwd, workspace, *, session=77):
    response = env["client"].post("/capture/hook-context", json={
        "event": "session_start", "harness": harness, "session_id": sid(session),
        "cwd": str(cwd), "source": "startup", "workspace": workspace})
    assert response.status_code == 200, response.text
    return response.json()["additionalContext"]


def stop(env, harness, session, cwd, workspace, *, age=60, role="root role sentinel"):
    lines = []
    if harness == "codex":
        lines.append({"type": "session_meta", "payload": {"id": sid(session), "cwd": str(cwd)}})
    for i, (speaker, text) in enumerate([("user", role), ("assistant", "State: next alpha checks")]):
        ts = (env["now"] - timedelta(minutes=age) + timedelta(seconds=i)).isoformat()
        if harness == "claude-code":
            lines.append({"type": speaker, "sessionId": sid(session), "cwd": str(cwd), "timestamp": ts,
                          "message": {"role": speaker, "content": [{"type": "text", "text": text}]}})
        else:
            lines.append({"type": "response_item", "timestamp": ts, "payload": {
                "type": "message", "role": speaker, "channel": "final" if speaker == "assistant" else None,
                "content": [{"type": "input_text" if speaker == "user" else "output_text", "text": text}]}})
    path = env["roots"][harness] / f"{sid(session)}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    response = env["client"].post("/capture/transcript", json={
        "harness": harness, "session_id": sid(session), "cwd": str(cwd), "transcript_path": str(path),
        "workspace": workspace})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("source,destination", [("claude-code", "codex"), ("codex", "claude-code")])
def test_subfolder_selects_root_checkout_before_newer_workers(env, repos, source, destination, monkeypatch):
    root = stop(env, source, 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    for i, key in enumerate(["worker", "lexical"], 2):
        stop(env, destination, i, repos[key], observation(repos[key], repos[key], repos["common"]),
             age=2, role="worker role sentinel")
    parsed = []
    real_parse = markdown_parser.parse

    def parse(path):
        if path.parent == env["memory"] / "episodes":
            parsed.append(path.stem)
        return real_parse(path)

    monkeypatch.setattr(markdown_parser, "parse", parse)
    note = start(env, destination, repos["sub"], observation(repos["sub"], repos["root"], repos["common"]))
    assert root["episodeId"] in note
    assert "root role sentinel" not in note and "worker role sentinel" not in note
    assert parsed == [root["episodeId"]]
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness=None, session_id=None,
                              cwd=str(repos["sub"]))
    assert ctx.chosen.episode_id == root["episodeId"]
    text = continuity.full_text(ctx)
    assert "root role sentinel" in text and "worker role sentinel" not in text
    assert "harness-observed" in text


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_related_checkouts_offer_ids_without_adopting_worker_role(env, repos, harness, monkeypatch):
    source = stop(env, harness, 1, repos["worker"], observation(repos["worker"], repos["worker"], repos["common"]),
                  role="worker role sentinel")
    note = start(env, harness, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    assert "related" in note.lower() and "worker role sentinel" not in note
    reg = continuity_sessions.get(env["memory"], harness, sid(77), bank_paths=(env["memory"],))
    assert "continues" not in reg
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness=None, session_id=None,
                              cwd=str(repos["root"]))
    assert ctx.selection.reason == "related_checkouts" and ctx.chosen is None
    monkeypatch.setattr(markdown_parser, "parse", lambda p: pytest.fail("related choices must not read worker bodies"))
    text = continuity.full_text(ctx)
    assert source["episodeId"] in text and "worker role sentinel" not in text


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_same_checkout_keeps_task_ambiguity_and_explicit_mismatch(env, repos, harness):
    root = stop(env, harness, 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]), age=3)
    stop(env, harness, 2, repos["sub"], observation(repos["sub"], repos["root"], repos["common"]), age=2)
    elsewhere = repos["root"] / "other-sub"
    elsewhere.mkdir()
    note = start(env, harness, elsewhere, observation(elsewhere, repos["root"], repos["common"]))
    assert "Several histories" in note or "History:" in note
    start(env, harness, repos["worker"], observation(repos["worker"], repos["worker"], repos["common"]), session=78)
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness=None, session_id=None,
                              cwd=str(repos["worker"]), session=root["episodeId"])
    assert "different observed checkout" in continuity.full_text(ctx)


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_identity_metadata_only_is_cwd_bound_and_outside_files_are_hashes(env, repos, harness):
    result = stop(env, harness, 1, repos["root"], None)
    path = env["memory"] / "episodes" / f'{result["episodeId"]}.md'
    before = markdown_parser.parse(path)
    fm = dict(before.frontmatter, processed=True, processed_by="sleep")
    markdown_parser.write(path, fm, before.body)
    updated = stop(env, harness, 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    assert updated["status"] == "metadata"
    after = markdown_parser.parse(path)
    assert after.body == before.body and after.frontmatter["content_hash"] == fm["content_hash"]
    assert after.frontmatter["processed"] and after.frontmatter["processed_by"] == "sleep"
    identity = after.frontmatter["workspace_identity"]
    assert set(identity) == {"family_hash", "checkout_hash", "cwd_hash", "observed_at"}
    continuity.reset()
    continuity.refresh_index(env["memory"], bank_paths=(env["memory"],), deadline=None)
    for file in (env["home"] / "continuity").iterdir():
        if file.is_file():
            data = file.read_text()
            assert str(repos["root"]) not in data and "sentinel" not in data
    wrong = observation(repos["sub"], repos["root"], repos["common"])
    stop(env, harness, 1, repos["root"], wrong)
    # A supplied observation for another cwd cannot replace an already validated identity.
    assert markdown_parser.parse(path).frontmatter["workspace_identity"] == identity


def test_no_lexical_worktree_family_without_observation(env, repos):
    source = stop(env, "claude-code", 1, repos["lexical"], None)
    note = start(env, "codex", repos["root"], None)
    assert source["episodeId"] not in note


def test_backend_only_parses_supplied_values(env, repos, monkeypatch):
    def forbidden(*a, **k):
        pytest.fail("backend must not run git")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    real_stat, real_open = os.stat, __import__("builtins").open

    def guard(fn):
        def wrapped(path, *a, **k):
            if isinstance(path, (str, os.PathLike)) and str(path).startswith(str(repos["root"])):
                pytest.fail("backend must not read/stat a declared workspace")
            return fn(path, *a, **k)
        return wrapped

    monkeypatch.setattr(os, "stat", guard(real_stat))
    monkeypatch.setattr("builtins.open", guard(real_open))
    for name in ("lstat", "scandir", "open"):
        monkeypatch.setattr(os, name, guard(getattr(os, name)))
    import io
    monkeypatch.setattr(io, "open", guard(io.open))
    stop(env, "claude-code", 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    note = start(env, "codex", repos["sub"], observation(repos["sub"], repos["root"], repos["common"]))
    assert "captured history" in note


@pytest.mark.parametrize("source,destination", [("claude-code", "codex"), ("codex", "claude-code")])
def test_real_hooks_subfolder_read_after_first_stop_keeps_source(env, repos, monkeypatch, source, destination):
    monkeypatch.setattr(a1, "CWD", str(repos["root"]))
    root = a1._stop(env, source, a1.A, [("user", "root role sentinel"), ("assistant", "State: next alpha checks")])
    monkeypatch.setattr(a1, "CWD", str(repos["sub"]))
    note = a1._start(env, destination)
    assert root["episodeId"] in note and "root role sentinel" not in note
    a1._stop(env, destination, a1.B, [("user", "small talk sentinel"), ("assistant", "hello")])
    server = env["server"]
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity(
        harness=destination, session_id="unknown-session", project_dir=str(repos["sub"])))
    text = server.handle_tool("cicada_continue", {})
    assert root["episodeId"] in text and "current conversation" in text
    assert "small talk sentinel" not in text
    assert "root role sentinel" in server.handle_tool("cicada_continue", {"session": root["episodeId"]})
    assert len(list((env["memory"] / "episodes").glob("*.md"))) == 2
    hints = list((env["home"] / "continuity-hook-hints").glob("*.json"))
    assert len(hints) == 2
    for path in hints:
        assert set(json.loads(path.read_text())) == {"cwd_hash", "observed_at"}
        assert str(repos["root"]) not in path.read_text() and path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("malformed", [False, True])
def test_newer_failed_observation_does_not_resurrect_another_sessions_success(env, repos, malformed):
    root = stop(env, "claude-code", 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    older = datetime.now(timezone.utc) - timedelta(seconds=2)
    start(env, "codex", repos["sub"], observation(repos["sub"], repos["root"], repos["common"], when=older.isoformat()))
    failed = {"cwd_hash": continuity_sessions.cwd_hash(str(repos["sub"])),
              "observed_at": datetime.now(timezone.utc).isoformat()}
    if malformed:
        failed.update(repo_root="relative", common_dir=str(repos["common"]), scope_hash="a" * 16)
    note = start(env, "codex", repos["sub"], failed, session=78)
    assert root["episodeId"] not in note
    reg = continuity_sessions.get(env["memory"], "codex", sid(78), bank_paths=(env["memory"],))
    assert "continues" not in reg


@pytest.mark.parametrize("identity", [("claude-code", sid(2)), ("codex", "unknown-session")])
def test_newer_uncaptured_caller_in_same_checkout_defeats_current_inference(env, repos, identity):
    stop(env, "claude-code", 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    start(env, "claude-code", repos["sub"], observation(repos["sub"], repos["root"], repos["common"]), session=2)
    stop(env, "claude-code", 2, repos["sub"], observation(repos["sub"], repos["root"], repos["common"]), age=5)
    start(env, "codex", repos["root"], observation(repos["root"], repos["root"], repos["common"]), session=3)
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness=None, session_id=None,
                              cwd=str(repos["sub"]), continue_identity=identity)
    assert ctx.selection.reason != "current_conversation"


def test_forged_cached_checkout_is_revalidated_against_bank_episode(env, repos):
    result = stop(env, "claude-code", 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    snap = continuity.refresh_index(env["memory"], bank_paths=(env["memory"],), deadline=None)
    name, row = next(iter(snap.rows.items()))
    forged = {**row, "workspace_identity": {**row["workspace_identity"], "checkout_hash": "f" * 16}}
    assert continuity.view(env["memory"], (name, forged)) is None


def test_stale_hint_keeps_exact_cwd_only(env, repos):
    root = stop(env, "claude-code", 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    start(env, "codex", repos["sub"], observation(repos["sub"], repos["root"], repos["common"]))
    rows = continuity_sessions.all_rows(env["memory"], bank_paths=(env["memory"],))
    value = rows[f"codex:{sid(77)}"]["workspace_identity"]
    value["observed_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    # Persist an expired hint directly: an actual stale wire observation is rejected earlier.
    path = env["home"] / "continuity" / f'{continuity_sessions.bank_file_id(env["memory"])}.json'
    path.write_text(json.dumps({"schema": 1, "rows": rows}))
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness=None, session_id=None,
                              cwd=str(repos["sub"]))
    assert ctx.chosen is None and root["episodeId"] not in continuity.full_text(ctx)


def test_exact_folder_beats_a_newer_task_in_the_same_checkout(env, repos):
    root = stop(env, "claude-code", 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    stop(env, "codex", 2, repos["sub"], observation(repos["sub"], repos["root"], repos["common"]), age=1)
    note = start(env, "codex", repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    assert root["episodeId"] in note


@pytest.mark.parametrize("checkout", ["worker", "lexical"])
def test_worker_subfolder_retrieves_its_own_task_not_root_role(env, repos, checkout):
    root = stop(env, "claude-code", 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    worker = stop(env, "codex", 2, repos[checkout], observation(repos[checkout], repos[checkout], repos["common"]),
                  role="worker role sentinel")
    child = repos[checkout] / "src"
    child.mkdir()
    note = start(env, "claude-code", child, observation(child, repos[checkout], repos["common"]))
    assert worker["episodeId"] in note and root["episodeId"] not in note
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness=None, session_id=None, cwd=str(child))
    text = continuity.full_text(ctx)
    assert "worker role sentinel" in text and "root role sentinel" not in text


def test_related_choices_do_not_claim_absence_when_root_head_is_unreadable(env, repos):
    root = stop(env, "claude-code", 1, repos["root"], observation(repos["root"], repos["root"], repos["common"]))
    path = env["memory"] / "episodes" / f'{root["episodeId"]}.md'
    doc = markdown_parser.parse(path)
    fm = {k: v for k, v in doc.frontmatter.items() if k != "turns"}
    fm["zz_note"] = "x" * 17000
    fm["turns"] = doc.frontmatter["turns"]
    markdown_parser.write(path, fm, doc.body)
    stop(env, "codex", 2, repos["worker"], observation(repos["worker"], repos["worker"], repos["common"]))
    start(env, "codex", repos["sub"], observation(repos["sub"], repos["root"], repos["common"]))
    ctx = continuity.assemble(env["memory"], bank_paths=(env["memory"],), harness=None, session_id=None,
                              cwd=str(repos["sub"]))
    assert not ctx.complete and ctx.selection.reason == "related_checkouts"
    text = continuity.full_text(ctx)
    assert "Only other" not in text and "incomplete" in text.lower()
