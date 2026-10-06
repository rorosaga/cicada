"""G182 / TODO ruling 19 — `scripts/release/check_version.py`, the one place a release's version is judged.

`agree` holds every file that stamps a version to `VERSION`; `plan` reads the remote's `v*` tags and decides what a
run on `main` does: publish nothing when `VERSION` is already tagged, publish when it is greater than every tag, and
fail loudly otherwise.
"""
from __future__ import annotations

import importlib.util
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "check_version.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_version", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cv = _module()


def _repo(tmp_path: Path, version="0.4.0", pyproject=None, lock=None) -> Path:
    (tmp_path / "api").mkdir()
    (tmp_path / "VERSION").write_text(f"{version}\n")
    (tmp_path / "api" / "pyproject.toml").write_text(
        f'[project]\nname = "cicada-api"\nversion = "{pyproject or version}"\n\n[tool.x]\nversion = "9.9.9"\n')
    (tmp_path / "api" / "uv.lock").write_text(
        '[[package]]\nname = "anyio"\nversion = "4.4.0"\n\n'
        f'[[package]]\nname = "cicada-api"\nversion = "{lock or version}"\nsource = {{ virtual = "." }}\n')
    return tmp_path


LS_REMOTE = "\n".join([
    "1111111111111111111111111111111111111111\trefs/tags/v0.3.0",
    "2222222222222222222222222222222222222222\trefs/tags/v0.10.1",
    "3333333333333333333333333333333333333333\trefs/tags/v0.9.0",
    "4444444444444444444444444444444444444444\trefs/tags/v0.10.1^{}",
    "5555555555555555555555555555555555555555\trefs/tags/vnext",
    "6666666666666666666666666666666666666666\trefs/tags/v1.0.0-rc.1",
])


def test_tags_are_read_from_ls_remote_or_plain_names_and_ordered_by_semver_not_text():
    assert cv.parse_tags(LS_REMOTE) == ["v0.3.0", "v0.9.0", "v0.10.1"]
    assert cv.parse_tags("v0.2.0\nv0.11.0\n\n") == ["v0.2.0", "v0.11.0"]
    assert cv.parse_tags("") == []


@pytest.mark.parametrize("version, tags, status, latest, previous", [
    ("0.3.0", [], "new", True, ""),
    ("0.10.2", ["v0.3.0", "v0.10.1"], "new", True, "v0.10.1"),
    ("1.0.0", ["v0.9.0", "v0.10.1"], "new", True, "v0.10.1"),
    ("0.10.1", ["v0.3.0", "v0.10.1"], "released", False, ""),
    ("0.3.0", ["v0.3.0", "v0.10.1"], "released", False, ""),
])
def test_plan_publishes_only_an_untagged_version_greater_than_every_tag(version, tags, status, latest, previous):
    p = cv.plan(version, tags)
    assert (p.status, p.latest, p.previous) == (status, latest, previous)


@pytest.mark.parametrize("version, tags", [
    ("0.9.5", ["v0.3.0", "v0.10.1"]),   # an older line: never published by CI, never "latest"
    ("0.2.0", ["v0.3.0"]),
])
def test_an_untagged_version_not_greater_than_the_latest_tag_fails_loudly(version, tags):
    with pytest.raises(cv.VersionError, match="not greater"):
        cv.plan(version, tags)
    dry = cv.plan(version, tags, dry_run=True)
    assert dry.status == "behind" and dry.latest is False, "a dry run builds anyway and says why it would not publish"


def test_plan_refuses_a_version_that_is_not_plain_semver():
    for bad in ("0.3", "v0.3.0", "0.3.0-rc.1", ""):
        with pytest.raises(cv.VersionError):
            cv.plan(bad, [])


def test_agree_passes_when_every_stamp_matches(tmp_path):
    root = _repo(tmp_path)
    assert cv.agree(root) == "0.4.0"


@pytest.mark.parametrize("kwargs, culprit", [
    ({"pyproject": "0.3.9"}, "api/pyproject.toml"),
    ({"lock": "0.3.9"}, "api/uv.lock"),
])
def test_agree_names_the_file_that_disagrees(tmp_path, kwargs, culprit):
    root = _repo(tmp_path, **kwargs)
    with pytest.raises(cv.VersionError, match=culprit.replace(".", r"\.")):
        cv.agree(root)


def test_agree_checks_the_built_app_and_latest_json_when_given(tmp_path):
    root = _repo(tmp_path)
    plist = tmp_path / "Info.plist"
    plist.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.4.0", "CFBundleVersion": "1600"}))
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({"version": "0.4.0", "url": "https://example.com/v0.4.0/Cicada-0.4.0.zip"}))
    assert cv.agree(root, info_plist=plist, latest_json=manifest) == "0.4.0"
    plist.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.3.0"}))
    with pytest.raises(cv.VersionError, match="CFBundleShortVersionString"):
        cv.agree(root, info_plist=plist)
    manifest.write_text(json.dumps({"version": "0.3.0"}))
    with pytest.raises(cv.VersionError, match="latest.json"):
        cv.agree(root, latest_json=manifest)


def _run(*args, stdin=""):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True)


def test_the_cli_writes_github_outputs_and_exits_non_zero_on_a_bad_version(tmp_path):
    def repo(name, **kw):
        (tmp_path / name).mkdir()
        return str(_repo(tmp_path / name, **kw))

    ok = _run("plan", "--root", repo("a", version="0.10.2"), stdin=LS_REMOTE)
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.splitlines() == ["version=0.10.2", "status=new", "latest=true", "previous=v0.10.1"]
    released = _run("plan", "--root", repo("b", version="0.9.0"), stdin=LS_REMOTE)
    assert released.returncode == 0 and "status=released" in released.stdout
    behind = _run("plan", "--root", repo("c", version="0.4.0"), stdin=LS_REMOTE)
    assert behind.returncode == 1 and "not greater than v0.10.1" in behind.stderr
    dry = _run("plan", "--dry-run", "--root", repo("e", version="0.4.0"), stdin=LS_REMOTE)
    assert dry.returncode == 0 and "status=behind" in dry.stdout
    agree_bad = _run("agree", "--root", repo("d", lock="0.0.1"))
    assert agree_bad.returncode == 1 and "api/uv.lock" in agree_bad.stderr


def test_the_script_runs_on_the_system_python():
    """CI and `make release` call it with whatever python3 is first on PATH — stdlib only, no 3.11-only modules."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "import tomllib" not in text and "match " not in text.replace("re.match", "").replace("fullmatch", "")
