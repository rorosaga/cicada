"""G182 / TODO ruling 19 — `scripts/release/publish.sh`, the only step that advertises a release.

Run against a fake `gh` that keeps releases (by id, like GitHub) in a JSON file, from a checkout whose origin is a
bare repo with real commits and tags. The release is created as a draft at the run's commit, every asset is checked,
and only then is it published (which is when GitHub creates the tag). Only the commit at main's tip may publish: a run
whose commit was superseded publishes nothing and deletes only the draft it made. Any failure deletes this run's draft,
so nothing is advertised; a published release is never touched again.
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
REPO = "owner-example/cicada"

FAKE_GH = r'''#!PYTHON
"""A fake `gh` for the release calls publish.sh makes. Releases live in $FAKE_GH_STATE as a list (GitHub allows two
drafts with one tag name, so they are addressed by id). $FAKE_GH_FAIL names a step to fail: list|upload|verify|edit.
$FAKE_GH_MOVE_MAIN (a checkout path) pushes a new commit to its origin's main right after `release create`."""
import json, os, subprocess, sys
from pathlib import Path

state_file = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_file.read_text()) if state_file.exists() else {"next_id": 1, "releases": []}
fail = os.environ.get("FAKE_GH_FAIL", "")
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")

def save():
    state_file.write_text(json.dumps(state))

def find(rid):
    return next((r for r in state["releases"] if r["id"] == rid), None)

if args[:2] == ["release", "create"]:
    tag, rest = args[2], args[3:]
    takes_value = {"--target", "--title", "--notes-file", "--notes-start-tag"}
    files = [a for i, a in enumerate(rest) if not a.startswith("-") and rest[i - 1] not in takes_value]
    assets = [{"name": os.path.basename(f), "size": os.path.getsize(f)} for f in files]
    if fail == "verify":
        assets = assets[:-1]
    release = {"id": state["next_id"], "tag_name": tag, "draft": "--draft" in rest,
               "target_commitish": rest[rest.index("--target") + 1], "make_latest": None,
               "assets": assets[:1] if fail == "upload" else assets}
    state["next_id"] += 1
    state["releases"].append(release)
    save()
    if os.environ.get("FAKE_GH_MOVE_MAIN"):
        co = os.environ["FAKE_GH_MOVE_MAIN"]
        subprocess.run(["git", "-C", co, "commit", "-q", "--allow-empty", "-m", "newer"], check=True)
        subprocess.run(["git", "-C", co, "push", "-q", "origin", "HEAD:main"], check=True)
    sys.exit(1 if fail == "upload" else 0)

if args[0] == "api":
    method, path, fields, i = "GET", None, {}, 1
    while i < len(args):
        a = args[i]
        if a == "-X":
            method = args[i + 1]; i += 2; continue
        if a in ("-F", "-f"):
            k, v = args[i + 1].split("=", 1); fields[k] = v; i += 2; continue
        if a.startswith("-"):
            i += 1; continue
        path = a; i += 1
    assert path.startswith("repos/" + os.environ["GH_REPO"] + "/releases"), path
    tail = path.split("/releases", 1)[1]
    if tail.startswith("?") or tail == "":
        if fail == "list":
            print("HTTP 502: Bad Gateway", file=sys.stderr); sys.exit(1)
        assert "--paginate" in args and "--slurp" in args
        print(json.dumps([state["releases"]])); sys.exit(0)
    release = find(int(tail.strip("/")))
    if release is None:
        print("HTTP 404: Not Found", file=sys.stderr); sys.exit(1)
    if method == "GET":
        print(json.dumps(release)); sys.exit(0)
    if method == "PATCH":
        if fail == "edit":
            print("HTTP 500", file=sys.stderr); sys.exit(1)
        assert fields == {"draft": "false", "make_latest": fields.get("make_latest")}, fields
        release["draft"] = False
        release["make_latest"] = fields["make_latest"]
        save(); print(json.dumps(release)); sys.exit(0)
    if method == "DELETE":
        assert release["draft"] is True, "a published release must never be deleted"
        state["releases"].remove(release); save(); sys.exit(0)
print("unexpected: " + " ".join(args), file=sys.stderr)
sys.exit(2)
'''


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}).stdout.strip()


@pytest.fixture
def env(tmp_path):
    """dist/ with the four assets; a checkout at the run's commit whose origin (bare) has main there and v0.3.0."""
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
    remote, checkout = tmp_path / "remote.git", tmp_path / "checkout"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(tmp_path, "init", "-q", "-b", "main", str(checkout))
    _git(checkout, "config", "user.name", "t")   # the fake's own commits need an identity
    _git(checkout, "config", "user.email", "t@example.com")
    _git(checkout, "commit", "-q", "--allow-empty", "-m", "released 0.3.0")
    _git(checkout, "remote", "add", "origin", str(remote))
    _git(checkout, "tag", "v0.3.0")
    _git(checkout, "commit", "-q", "--allow-empty", "-m", "merge the 0.4.0 release PR")
    _git(checkout, "push", "-q", "origin", "main", "v0.3.0")
    sha = _git(checkout, "rev-parse", "HEAD")

    def tag(name):
        _git(checkout, "tag", name)
        _git(checkout, "push", "-q", "origin", name)

    def advance_main():
        """A newer release merge lands on main (same untagged VERSION or not — publish.sh only sees the SHA)."""
        _git(checkout, "commit", "-q", "--allow-empty", "-m", "a newer release merge")
        _git(checkout, "push", "-q", "origin", "HEAD:main")
        return _git(checkout, "rev-parse", "HEAD")

    return {
        "dist": dist, "checkout": checkout, "sha": sha, "tag": tag, "advance_main": advance_main,
        "state": tmp_path / "state.json", "log": tmp_path / "gh.log",
        "env": {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_REPO": REPO,
                "FAKE_GH_STATE": str(tmp_path / "state.json"), "FAKE_GH_LOG": str(tmp_path / "gh.log")},
    }


def _publish(env, **extra):
    return subprocess.run([str(SCRIPT), "0.4.0", env["sha"], str(env["dist"])], env={**env["env"], **extra},
                          cwd=env["checkout"], capture_output=True, text=True)


def _calls(env):
    return [json.loads(line) for line in env["log"].read_text().splitlines()] if env["log"].exists() else []


def _releases(env):
    return json.loads(env["state"].read_text())["releases"] if env["state"].exists() else []


def _seed(env, *releases):
    env["state"].write_text(json.dumps({"next_id": 100, "releases": list(releases)}))


def _kinds(env):
    """Each gh call as create / list / get / publish / delete."""
    out = []
    for c in _calls(env):
        if c[:2] == ["release", "create"]:
            out.append("create")
        elif "-X" in c:
            out.append({"PATCH": "publish", "DELETE": "delete"}[c[c.index("-X") + 1]])
        else:
            out.append("list" if "--paginate" in c else "get")
    return out


def test_a_release_is_drafted_at_the_merged_commit_verified_then_published_as_latest(env):
    done = _publish(env)
    assert done.returncode == 0, done.stderr
    [release] = _releases(env)
    assert release["draft"] is False and release["make_latest"] == "true"
    assert release["tag_name"] == "v0.4.0" and release["target_commitish"] == env["sha"]
    assert sorted(a["name"] for a in release["assets"]) == [
        "Cicada-0.4.0.zip", "Cicada-0.4.0.zip.sig", "Cicada-macos-arm64.zip", "latest.json"]
    create = next(c for c in _calls(env) if c[:2] == ["release", "create"])
    flag = lambda name: create[create.index(name) + 1]  # noqa: E731
    assert "--draft" in create and flag("--target") == env["sha"] and flag("--title") == "Cicada 0.4.0"
    assert "--generate-notes" in create and flag("--notes-start-tag") == "v0.3.0"
    assert "--clobber" not in create, "a released asset is never overwritten"
    assert flag("--notes-file").endswith("release-notes-header.md"), "generated notes follow the fixed header"
    assert _kinds(env) == ["list", "create", "list", "get", "publish", "get"]


def test_the_version_is_judged_again_against_the_live_tags_not_the_plan_s(env):
    """\"Re-run failed jobs\" reuses the plan job's outputs: a newer release since then must stop an older publish."""
    env["tag"]("v0.5.0")
    done = _publish(env)
    assert done.returncode == 1 and "not greater than v0.5.0" in done.stderr
    assert _kinds(env) == ["list"], "nothing is created, nothing becomes latest"


def test_a_tag_that_already_exists_publishes_nothing_and_stays_green(env):
    env["tag"]("v0.4.0")
    done = _publish(env)
    assert done.returncode == 0 and "already released" in done.stdout
    assert "create" not in _kinds(env)


def test_a_superseded_run_creates_and_publishes_nothing(env):
    """Review blocker: an old run whose commit is no longer main's tip, with the same VERSION still untagged, must
    not release the old code — the run for the newer commit releases main."""
    newer = env["advance_main"]()
    done = _publish(env)
    assert done.returncode == 0, done.stderr
    assert f"superseded by {newer[:12]}" in done.stdout and "that run releases main" in done.stdout
    assert "create" not in _kinds(env) and "publish" not in _kinds(env)
    assert _releases(env) == []


def test_main_moving_between_draft_and_publish_deletes_only_this_run_s_draft(env):
    done = _publish(env, FAKE_GH_MOVE_MAIN=str(env["checkout"]))
    assert done.returncode == 0, done.stderr
    assert "superseded by" in done.stdout
    assert "publish" not in _kinds(env) and "delete" in _kinds(env)
    assert _releases(env) == [], "the draft it made is gone; nothing was advertised"


def test_a_superseded_run_never_touches_the_newer_run_s_draft(env):
    """Runs for different commits may overlap: the newer commit's draft (same tag, other target) is not this run's."""
    newer = env["advance_main"]()
    theirs = {"id": 7, "tag_name": "v0.4.0", "draft": True, "target_commitish": newer, "make_latest": None, "assets": []}
    _seed(env, theirs)
    assert _publish(env).returncode == 0
    assert _releases(env) == [theirs] and "delete" not in _kinds(env)


def test_a_run_at_the_tip_leaves_an_older_commit_s_draft_alone_and_publishes_its_own(env):
    stale = {"id": 7, "tag_name": "v0.4.0", "draft": True, "target_commitish": "0" * 40, "make_latest": None,
             "assets": []}
    _seed(env, stale)
    assert _publish(env).returncode == 0
    mine = [r for r in _releases(env) if r["target_commitish"] == env["sha"]]
    assert len(mine) == 1 and mine[0]["draft"] is False
    assert stale in _releases(env), "another commit's draft is its own run's business (it is private either way)"


def test_a_draft_this_commit_left_in_an_earlier_failed_run_is_replaced(env):
    _seed(env, {"id": 7, "tag_name": "v0.4.0", "draft": True, "target_commitish": env["sha"], "make_latest": None,
                "assets": []})
    assert _publish(env).returncode == 0
    assert _kinds(env)[:3] == ["list", "delete", "create"]
    [release] = _releases(env)
    assert release["id"] != 7 and release["draft"] is False


def test_the_first_release_has_no_previous_tag_for_its_notes(env):
    _git(env["checkout"], "push", "-q", "origin", ":refs/tags/v0.3.0")
    assert _publish(env).returncode == 0
    create = next(c for c in _calls(env) if c[:2] == ["release", "create"])
    assert "--notes-start-tag" not in create


def test_a_failed_lookup_is_never_read_as_no_release(env):
    done = _publish(env, FAKE_GH_FAIL="list")
    assert done.returncode != 0 and "502" in done.stderr
    assert "create" not in _kinds(env)


@pytest.mark.parametrize("step", ["upload", "verify", "edit"])
def test_any_failure_deletes_the_draft_it_made(env, step):
    done = _publish(env, FAKE_GH_FAIL=step)
    assert done.returncode != 0
    assert _releases(env) == [], "nothing is advertised"
    assert "delete" in _kinds(env)


def test_the_stable_asset_must_be_the_same_bytes_as_the_versioned_zip(env):
    (env["dist"] / "Cicada-macos-arm64.zip").write_bytes(b"other bytes")
    done = _publish(env)
    assert done.returncode != 0 and "Cicada-macos-arm64.zip" in done.stderr
    assert _calls(env) == [], "nothing is created when the files are wrong"


def test_an_already_published_release_is_left_alone_and_the_run_is_green(env):
    published = {"id": 7, "tag_name": "v0.4.0", "draft": False, "target_commitish": env["sha"], "make_latest": "true",
                 "assets": []}
    _seed(env, published)
    done = _publish(env)
    assert done.returncode == 0 and "already released" in done.stdout
    assert _kinds(env) == ["list"] and _releases(env) == [published]


def test_the_notes_header_names_the_platform_and_the_unnotarized_first_open():
    header = (ROOT / "scripts" / "release" / "release-notes-header.md").read_text(encoding="utf-8")
    assert "Apple silicon" in header and "macOS 14" in header
    assert "not notarized" in header and "Open Anyway" in header
    assert "install-release.sh" in header


def test_publish_never_pushes_tags_or_forces_and_addresses_releases_by_id():
    text = SCRIPT.read_text(encoding="utf-8")
    for banned in ("git push", "git tag", "--force", "--clobber", "--cleanup-tag", "gh release edit",
                   "gh release delete", "gh release view"):
        assert banned not in text, f"{banned}: a tag may name two drafts; releases are addressed by id"
    assert "git ls-remote \"$REMOTE\" refs/heads/main" in text
