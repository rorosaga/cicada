"""G182 / TODO ruling 19 — `scripts/release/publish.sh`, the only step that advertises a release.

Run against a fake `gh` that keeps the release's state in a JSON file: the release is created as a draft at the
merged commit, every asset is checked, and only then is it published (which is when GitHub creates the tag). Any
failure deletes the draft it created, so nothing is advertised; a published release is never touched again.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "publish.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"

FAKE_GH = r'''#!PYTHON
"""A fake `gh release` with state in $FAKE_GH_STATE; $FAKE_GH_FAIL names a step to fail (upload|edit|verify)."""
import json, os, sys
from pathlib import Path

state_file = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_file.read_text()) if state_file.exists() else {}
fail = os.environ.get("FAKE_GH_FAIL", "")
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
assert args[0] == "release", args
cmd, tag, rest = args[1], args[2], args[3:]

def save():
    state_file.write_text(json.dumps(state))

if cmd == "view":
    if tag not in state:
        print("release not found", file=sys.stderr); sys.exit(1)
    print(json.dumps(state[tag])); sys.exit(0)
if cmd == "create":
    takes_value = {"--target", "--title", "--notes-file", "--notes-start-tag"}
    files = [a for i, a in enumerate(rest) if not a.startswith("-") and rest[i - 1] not in takes_value]
    assets = [{"name": os.path.basename(f), "size": os.path.getsize(f)} for f in files]
    if fail == "verify":
        assets = assets[:-1]
    state[tag] = {"tagName": tag, "isDraft": True, "assets": assets[:1] if fail == "upload" else assets}
    save()
    sys.exit(1 if fail == "upload" else 0)
if cmd == "edit":
    if fail == "edit":
        print("HTTP 500", file=sys.stderr); sys.exit(1)
    state[tag]["isDraft"] = False
    state[tag]["latest"] = "--latest=true" in rest
    save(); sys.exit(0)
if cmd == "delete":
    assert state[tag]["isDraft"] is True, "a published release must never be deleted"
    del state[tag]; save(); sys.exit(0)
sys.exit(2)
'''


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH.replace("PYTHON", sys.executable))
    gh.chmod(0o755)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "Cicada-0.4.0.zip").write_bytes(b"zip bytes")
    (dist / "Cicada-0.4.0.zip.sig").write_text("c2ln\n")
    (dist / "latest.json").write_text(json.dumps({"version": "0.4.0"}))
    (dist / "Cicada-macos-arm64.zip").write_bytes(b"zip bytes")
    return {
        "dist": dist,
        "state": tmp_path / "state.json",
        "log": tmp_path / "gh.log",
        "env": {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_GH_STATE": str(tmp_path / "state.json"),
                "FAKE_GH_LOG": str(tmp_path / "gh.log"), "LATEST": "true", "PREVIOUS": "v0.3.0"},
    }


def _publish(env, **extra):
    return subprocess.run([str(SCRIPT), "0.4.0", SHA, str(env["dist"])], env={**env["env"], **extra},
                          capture_output=True, text=True)


def _calls(env):
    return [json.loads(line) for line in env["log"].read_text().splitlines()] if env["log"].exists() else []


def _state(env):
    return json.loads(env["state"].read_text()) if env["state"].exists() else {}


def test_a_release_is_drafted_at_the_merged_commit_verified_then_published_as_latest(env):
    done = _publish(env)
    assert done.returncode == 0, done.stderr
    release = _state(env)["v0.4.0"]
    assert release["isDraft"] is False and release["latest"] is True
    assert sorted(a["name"] for a in release["assets"]) == [
        "Cicada-0.4.0.zip", "Cicada-0.4.0.zip.sig", "Cicada-macos-arm64.zip", "latest.json"]
    create = next(c for c in _calls(env) if c[1] == "create")
    flag = lambda name: create[create.index(name) + 1]  # noqa: E731
    assert "--draft" in create and flag("--target") == SHA and flag("--title") == "Cicada 0.4.0"
    assert "--generate-notes" in create and flag("--notes-start-tag") == "v0.3.0"
    assert "--clobber" not in create, "a released asset is never overwritten"
    assert flag("--notes-file").endswith("release-notes-header.md"), "generated notes follow the fixed header"
    edit = next(c for c in _calls(env) if c[1] == "edit")
    assert "--draft=false" in edit and "--latest=true" in edit


def test_a_release_that_is_not_the_highest_is_never_marked_latest(env):
    assert _publish(env, LATEST="false", PREVIOUS="").returncode == 0
    assert _state(env)["v0.4.0"]["latest"] is False
    create = next(c for c in _calls(env) if c[1] == "create")
    assert "--notes-start-tag" not in create, "the first release has no previous tag"


@pytest.mark.parametrize("step", ["upload", "verify", "edit"])
def test_any_failure_deletes_the_draft_it_made_and_with_it_the_tag(env, step):
    done = _publish(env, FAKE_GH_FAIL=step)
    assert done.returncode != 0
    assert _state(env) == {}, "nothing is advertised"
    delete = next(c for c in _calls(env) if c[1] == "delete")
    assert "--cleanup-tag" in delete and "--yes" in delete


def test_the_stable_asset_must_be_the_same_bytes_as_the_versioned_zip(env):
    (env["dist"] / "Cicada-macos-arm64.zip").write_bytes(b"other bytes")
    done = _publish(env)
    assert done.returncode != 0 and "Cicada-macos-arm64.zip" in done.stderr
    assert _calls(env) == [], "nothing is created when the files are wrong"


def test_an_already_published_release_is_left_alone_and_the_run_is_green(env):
    env["state"].write_text(json.dumps({"v0.4.0": {"tagName": "v0.4.0", "isDraft": False, "assets": []}}))
    done = _publish(env)
    assert done.returncode == 0 and "already released" in done.stdout
    assert [c[1] for c in _calls(env)] == ["view"]


def test_a_draft_left_by_a_failed_run_is_replaced(env):
    env["state"].write_text(json.dumps({"v0.4.0": {"tagName": "v0.4.0", "isDraft": True, "assets": []}}))
    assert _publish(env).returncode == 0
    assert [c[1] for c in _calls(env)][:3] == ["view", "delete", "create"]
    assert _state(env)["v0.4.0"]["isDraft"] is False


def test_the_notes_header_names_the_platform_and_the_unnotarized_first_open():
    header = (ROOT / "scripts" / "release" / "release-notes-header.md").read_text(encoding="utf-8")
    assert "Apple silicon" in header and "macOS 14" in header
    assert "not notarized" in header and "Open Anyway" in header
    assert "install-release.sh" in header


def test_publish_never_pushes_tags_or_forces():
    text = SCRIPT.read_text(encoding="utf-8")
    for banned in ("git push", "git tag", "--force", "--clobber"):
        assert banned not in text, banned
