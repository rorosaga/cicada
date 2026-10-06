"""G182 phase 4 — the release workflow's pieces, exercised without publishing anything.

`sign_update.py` signs a release zip with Ed25519 and verifies against the committed
public key; `latest_json.py` writes what the updater reads; `release.sh` is the owner's
one command (exercised here against a throwaway bare repo, never the real remote).
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


def test_release_sh_bumps_merges_tags_and_pushes_atomically(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    (work / "api").mkdir()
    (work / "scripts" / "release").mkdir(parents=True)
    (work / "VERSION").write_text("0.3.0\n")
    (work / "api" / "pyproject.toml").write_text('[project]\nname = "cicada-api"\nversion = "0.3.0"\n')
    (work / "api" / "uv.lock").write_text('[[package]]\nname = "cicada-api"\nversion = "0.3.0"\nsource = { virtual = "." }\n')
    script = work / "scripts" / "release" / "release.sh"
    script.write_text((RELEASE / "release.sh").read_text(encoding="utf-8"))
    script.chmod(0o755)
    for args in (["add", "-A"], ["commit", "-qm", "init"], ["branch", "dev"], ["remote", "add", "origin", str(remote)],
                 ["push", "-q", "origin", "main", "dev"]):
        subprocess.run(["git", *args], cwd=work, check=True, env=env)
    done = subprocess.run([str(script), "0.2.0", "--yes"], cwd=work, env=env, capture_output=True, text=True)
    assert done.returncode == 1 and "older" in done.stderr
    dry = subprocess.run([str(script), "0.4.0", "--dry-run"], cwd=work, env=env, capture_output=True, text=True)
    assert dry.returncode == 0, dry.stderr
    assert _git(remote, "tag") == "" and _git(work, "tag") == ""
    done = subprocess.run([str(script), "0.4.0", "--yes"], cwd=work, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert _git(remote, "show", "dev:VERSION") == "0.4.0"
    assert 'version = "0.4.0"' in _git(remote, "show", "dev:api/uv.lock")
    assert _git(remote, "tag") == "v0.4.0"
    assert _git(remote, "log", "-1", "--format=%s", "main") == "Release v0.4.0"
    assert _git(remote, "rev-parse", "v0.4.0^{commit}") == _git(remote, "rev-parse", "main")
    assert _git(work, "rev-parse", "--abbrev-ref", "HEAD") == "main", "the checkout it ran from is never switched"
    again = subprocess.run([str(script), "0.4.0", "--yes"], cwd=work, env=env, capture_output=True, text=True)
    assert again.returncode == 1 and "already exists" in again.stderr


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
