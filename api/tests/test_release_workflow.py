"""G182 phase 4 — the release workflow's pieces, exercised without publishing anything.

`sign_update.py` signs a release zip with Ed25519 and verifies against the committed
public key; `latest_json.py` writes what the updater reads; `release.sh` opens the two PRs a
release takes (exercised here against a throwaway bare repo and a fake `gh`, never the real remote);
the workflows are read as data.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"


def _load(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, RELEASE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_public_key_is_a_raw_ed25519_key():
    raw = base64.b64decode((RELEASE / "update-public-key.txt").read_text().strip())
    assert len(raw) == 32


def test_sign_and_verify_round_trip(tmp_path, monkeypatch, capsys):
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    su = _load("sign_update")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = tmp_path / "pub.txt"
    pub.write_text(base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())
    monkeypatch.setattr(su, "PUBLIC_KEY_FILE", pub)
    monkeypatch.setenv("CICADA_UPDATE_SIGNING_KEY", pem)
    archive = tmp_path / "Cicada-9.9.9.zip"
    archive.write_bytes(b"zip bytes")
    assert su.main(["sign", str(archive)]) == 0
    sig = capsys.readouterr().out.strip()
    assert len(base64.b64decode(sig)) == 64
    assert su.main(["verify", str(archive), sig]) == 0
    archive.write_bytes(b"zip bytes, tampered")
    assert su.main(["verify", str(archive), sig]) == 1
    assert su.main(["public-key"]) == 0
    assert capsys.readouterr().out.strip().endswith(pub.read_text()), "never prints the private key"


def test_latest_json_names_the_versioned_asset(tmp_path):
    lj = _load("latest_json")
    archive = tmp_path / "Cicada-0.3.0.zip"
    archive.write_bytes(b"abc")
    doc = lj.build("0.3.0", "1530", archive, "c2ln\n", "https://github.com/example/cicada/")
    assert doc["url"] == "https://github.com/example/cicada/releases/download/v0.3.0/Cicada-0.3.0.zip"
    assert doc["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert doc["build"] == 1530 and doc["size"] == 3 and doc["signature"] == "c2ln"
    assert doc["notes_url"].endswith("/releases/tag/v0.3.0")
    with pytest.raises(ValueError):
        lj.build("0.3", "1", archive, "x", "https://x")


def _workflow(name="release.yml"):
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    return wf, (wf[True] if True in wf else wf["on"])  # PyYAML reads the bare key `on` as True


def test_a_push_to_main_releases_and_no_tag_ever_starts_a_run():
    """Ruling 19: merging the release PR is the release; nobody tags by hand, so a tag triggers nothing."""
    wf, on = _workflow()
    assert on["push"]["branches"] == ["main", "ci/release-dry-run"]
    assert "tags" not in on["push"]
    assert "workflow_dispatch" in on, "a manual run on main is the recovery path after a failed run"
    assert wf["concurrency"] == {"group": "release", "cancel-in-progress": False}
    assert wf["permissions"] == {"contents": "read"}, "only the publish job may write"


def test_the_plan_job_judges_the_version_before_any_mac_is_used():
    wf, _ = _workflow()
    plan = wf["jobs"]["plan"]
    assert plan["runs-on"] == "ubuntu-latest"
    script = "\n".join(s.get("run", "") for s in plan["steps"])
    assert "check_version.py agree" in script
    assert "git ls-remote --tags --refs origin 'refs/tags/v*'" in script, "the remote's tags, not a stale checkout's"
    assert "check_version.py plan <" in script and "check_version.py plan --dry-run" in script
    assert 'refs/heads/main' in script and "already released" in script
    build = wf["jobs"]["build"]
    assert build["needs"] == "plan" and build["if"] == "needs.plan.outputs.build == 'true'"


def test_the_build_job_builds_signs_and_checks_every_stamp():
    wf, _ = _workflow()
    job = wf["jobs"]["build"]
    assert job["runs-on"].startswith("macos-26")
    assert "permissions" not in job, "the Mac that builds never holds a write token"
    steps = {s.get("name", s.get("uses", "")): s for s in job["steps"]}
    assert "--info-plist app/CicadaApp/.build/release/Cicada.app/Contents/Info.plist" in steps["The app's version agrees"]["run"]
    package = steps["Package and sign the update"]["run"]
    assert "check_version.py agree --latest-json dist/latest.json" in package
    assert 'cp "$zip" dist/Cicada-macos-arm64.zip' in package, "the stable name the website links"
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "--with-backend" in text and "smoke-test.sh" in text and "ditto -c -k --keepParent" in text
    assert "secrets.CICADA_UPDATE_SIGNING_KEY" in text
    assert "fetch-depth: 0" in text, "the build number is the commit count"


def test_only_the_publish_job_advertises_and_only_from_main():
    wf, _ = _workflow()
    job = wf["jobs"]["publish"]
    assert job["needs"] == ["plan", "build"] and job["if"] == "needs.plan.outputs.publish == 'true'"
    assert job["permissions"] == {"contents": "write"}
    run = job["steps"][-1]["run"]
    assert run.startswith("scripts/release/publish.sh") and '"$GITHUB_SHA"' in run, "the tag lands on the merged commit"
    env = job["steps"][-1]["env"]
    assert env["LATEST"] == "${{ needs.plan.outputs.latest }}" and env["PREVIOUS"] == "${{ needs.plan.outputs.previous }}"
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for banned in ("git push", "git tag", "--force", "--clobber", "gh release create"):
        assert banned not in text, f"{banned}: publication goes through publish.sh only"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


FAKE_GH = """#!/bin/sh
{ printf '%s' "$*" | tr '\\n' ' '; echo; } >> "$FAKE_GH_LOG"
case "$1 $2" in
  "pr list") printf '%s' "${FAKE_GH_OPEN_PR:-}" ;;
  "pr create") echo "https://github.com/owner-example/cicada/pull/1" ;;
  *) echo "unexpected: $*" >&2; exit 2 ;;
esac
"""


@pytest.fixture
def repo(tmp_path):
    """A throwaway origin (bare) with main and dev at VERSION 0.3.0, a clone on main, and a fake gh on PATH."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_GH_LOG": str(tmp_path / "gh.log")}
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    (work / "api").mkdir()
    (work / "scripts" / "release").mkdir(parents=True)
    (work / "VERSION").write_text("0.3.0\n")
    (work / "api" / "pyproject.toml").write_text('[project]\nname = "cicada-api"\nversion = "0.3.0"\n')
    (work / "api" / "uv.lock").write_text('[[package]]\nname = "cicada-api"\nversion = "0.3.0"\nsource = { virtual = "." }\n')
    for name in ("release.sh", "check_version.py"):
        (work / "scripts" / "release" / name).write_text((RELEASE / name).read_text(encoding="utf-8"))
        (work / "scripts" / "release" / name).chmod(0o755)
    for args in (["add", "-A"], ["commit", "-qm", "init"], ["branch", "dev"], ["remote", "add", "origin", str(remote)],
                 ["push", "-q", "origin", "main", "dev"]):
        subprocess.run(["git", *args], cwd=work, check=True, env=env)

    def run(*args, **extra):
        return subprocess.run([str(work / "scripts" / "release" / "release.sh"), *args], cwd=work,
                              env={**env, **extra}, capture_output=True, text=True)

    def gh_calls():
        log = tmp_path / "gh.log"
        return log.read_text().splitlines() if log.exists() else []

    def tag(name):
        subprocess.run(["git", "tag", name], cwd=work, check=True, env=env)
        subprocess.run(["git", "push", "-q", "origin", name], cwd=work, check=True, env=env)

    return {"remote": remote, "work": work, "run": run, "gh_calls": gh_calls, "tag": tag}


def test_bump_opens_a_release_branch_pr_to_dev_and_touches_nothing_else(repo):
    remote = repo["remote"]
    main_before, dev_before = _git(remote, "rev-parse", "main"), _git(remote, "rev-parse", "dev")
    dry = repo["run"]("bump", "0.4.0", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "release/v0.4.0" in dry.stdout and repo["gh_calls"]() == []
    assert _git(remote, "branch", "--list", "release/*") == "", "a dry run pushes nothing"

    done = repo["run"]("bump", "0.4.0", "--yes")
    assert done.returncode == 0, done.stderr
    assert _git(remote, "show", "release/v0.4.0:VERSION") == "0.4.0"
    assert 'version = "0.4.0"' in _git(remote, "show", "release/v0.4.0:api/pyproject.toml")
    assert 'version = "0.4.0"' in _git(remote, "show", "release/v0.4.0:api/uv.lock")
    assert _git(remote, "log", "-1", "--format=%s", "release/v0.4.0") == "chore(release): 0.4.0"
    assert _git(remote, "rev-parse", "release/v0.4.0~1") == dev_before, "branched off dev"
    assert (_git(remote, "rev-parse", "main"), _git(remote, "rev-parse", "dev")) == (main_before, dev_before)
    assert _git(remote, "tag") == "", "never tags"
    assert any(c.startswith("pr create --base dev --head release/v0.4.0 --title chore(release): 0.4.0")
               for c in repo["gh_calls"]())
    assert "make release-pr" in done.stdout, "says the next step"
    assert _git(repo["work"], "rev-parse", "--abbrev-ref", "HEAD") == "main", "the checkout it ran from is never switched"


def test_bump_refuses_a_tagged_or_older_version_and_needs_no_bump_for_dev_s_own(repo):
    repo["tag"]("v0.3.0")
    again = repo["run"]("bump", "0.3.0", "--yes")
    assert again.returncode == 1 and "already released" in again.stderr
    older = repo["run"]("bump", "0.2.9", "--yes")
    assert older.returncode == 1 and "not greater than v0.3.0" in older.stderr
    assert repo["gh_calls"]() == []
    bad = repo["run"]("bump", "0.4", "--yes")
    assert bad.returncode == 2


def test_bump_to_the_version_dev_already_says_is_a_no_op_pointing_at_release_pr(repo):
    same = repo["run"]("bump", "0.3.0", "--yes")
    assert same.returncode == 0 and "make release-pr" in same.stdout
    assert repo["gh_calls"]() == [] and _git(repo["remote"], "branch", "--list", "release/*") == ""


def test_release_pr_opens_dev_to_main_for_the_untagged_version_with_no_bump(repo):
    """dev says 0.3.0 and nothing is tagged: `make release-pr` alone releases it."""
    remote = repo["remote"]
    dry = repo["run"]("pr", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "Release v0.3.0" in dry.stdout
    assert not any(c.startswith("pr create") for c in repo["gh_calls"]())
    done = repo["run"]("pr", "--yes")
    assert done.returncode == 0, done.stderr
    create = next(c for c in repo["gh_calls"]() if c.startswith("pr create"))
    assert create.startswith("pr create --base main --head dev --title Release v0.3.0")
    assert "merge commit" in create, "a squash would fork main from dev"
    assert _git(remote, "tag") == "" and _git(remote, "log", "-1", "--format=%s", "main") == "init"


def test_release_pr_refuses_a_released_version(repo):
    repo["tag"]("v0.3.0")
    done = repo["run"]("pr", "--yes")
    assert done.returncode == 1 and "already released" in done.stderr and "make release VERSION=" in done.stderr
    assert not any(c.startswith("pr create") for c in repo["gh_calls"]())


def test_release_pr_with_one_already_open_says_where_it_is(repo):
    done = repo["run"]("pr", "--yes", FAKE_GH_OPEN_PR="https://github.com/owner-example/cicada/pull/7")
    assert done.returncode == 0 and "pull/7" in done.stdout
    assert not any(c.startswith("pr create") for c in repo["gh_calls"]())


def test_release_sh_never_pushes_main_tags_or_forces():
    text = (RELEASE / "release.sh").read_text(encoding="utf-8")
    for banned in ("push origin main", "refs/heads/main", "git tag", "--atomic", "merge --no-ff", "--force-with-lease"):
        assert banned not in text, banned
    pushes = [line for line in text.splitlines() if " push " in line and not line.lstrip().startswith("#")]
    assert pushes and all("--force" not in line and " -f " not in line for line in pushes), pushes
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "scripts/release/release.sh bump $(VERSION)" in makefile and "scripts/release/release.sh pr" in makefile


def test_a_pr_to_main_must_come_from_dev_and_carry_an_untagged_greater_version():
    """Nothing but a release reaches main: the PR check fails any other head branch, or a VERSION CI would not publish."""
    wf, on = _workflow("release-check.yml")
    assert on["pull_request"]["branches"] == ["main"]
    assert "push" not in on, "only the release PR is checked here; release.yml owns main"
    assert wf["permissions"] == {"contents": "read"}
    job = wf["jobs"]["release-pr"]
    assert job["runs-on"] == "ubuntu-latest", "cheap"
    script = "\n".join(s.get("run", "") for s in job["steps"])
    env = {k: v for s in job["steps"] for k, v in (s.get("env") or {}).items()}
    assert env["HEAD_REF"] == "${{ github.head_ref }}" and env["HEAD_REPO"] == "${{ github.event.pull_request.head.repo.full_name }}"
    assert '[ "$HEAD_REF" = "dev" ]' in script and '[ "$HEAD_REPO" = "$GITHUB_REPOSITORY" ]' in script
    assert "check_version.py agree" in script
    assert "git ls-remote --tags --refs origin 'refs/tags/v*'" in script and "check_version.py plan <" in script
    assert '[ "$status" = "new" ]' in script, "an already-released VERSION is refused at the PR, not discovered at merge"


def test_the_pr_check_head_branch_rule_runs_as_written(tmp_path):
    """Execute the head-branch step's shell with the values GitHub would pass."""
    wf, _ = _workflow("release-check.yml")
    step = next(s for s in wf["jobs"]["release-pr"]["steps"] if s.get("name") == "The head branch is dev")
    def run(head, repo):
        env = {**os.environ, "HEAD_REF": head, "HEAD_REPO": repo, "GITHUB_REPOSITORY": "owner-example/cicada"}
        return subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True)
    assert run("dev", "owner-example/cicada").returncode == 0
    assert run("feat/alpha-project", "owner-example/cicada").returncode != 0
    assert run("dev", "bob-example/cicada").returncode != 0, "a fork's dev is not this repo's dev"
