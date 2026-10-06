"""G182 / TODO ruling 19 — `scripts/release/publish.sh`, the only step that advertises a release.

Run against `_release_fake_gh.py` (a fake `gh api` modelling GitHub's REST behaviour: id addressing, tag dropped by a
PATCH that omits it, eventually consistent listing, uploads by id) from a checkout whose origin is a bare repo with real
commits and tags. The release is created as a draft whose id comes from the create response, its assets are uploaded
to that id and checked, and only then is it published with its tag and target spelled out — which is when GitHub
creates the tag; the tag's real commit is then checked against the run's. Only the commit at main's tip may publish.
Any failure deletes the draft this run created, and nothing else; a public release is never touched.
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
FAKE = Path(__file__).resolve().parent / "_release_fake_gh.py"
REPO = "owner-example/cicada"
ASSETS = ["Cicada-0.4.0.zip", "Cicada-0.4.0.zip.sig", "latest.json", "Cicada-macos-arm64.zip"]


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
    gh.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
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
    before = _git(checkout, "rev-parse", "HEAD")
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
        "dist": dist, "checkout": checkout, "remote": remote, "sha": sha, "before": before, "tag": tag,
        "advance_main": advance_main, "state": tmp_path / "state.json", "log": tmp_path / "gh.log",
        "env": {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_REPO": REPO,
                "FAKE_GH_STATE": str(tmp_path / "state.json"), "FAKE_GH_LOG": str(tmp_path / "gh.log"),
                "FAKE_GH_REMOTE": str(remote), "CICADA_PUBLISH_POLL_DELAY": "0"},
    }


def _publish(env, **extra):
    return subprocess.run([str(SCRIPT), "0.4.0", env["sha"], str(env["dist"])], env={**env["env"], **extra},
                          cwd=env["checkout"], capture_output=True, text=True)


def _calls(env):
    return [json.loads(line) for line in env["log"].read_text().splitlines()] if env["log"].exists() else []


def _state(env):
    return json.loads(env["state"].read_text()) if env["state"].exists() else {"releases": []}


def _releases(env):
    return _state(env)["releases"]


def _seed(env, *releases):
    env["state"].write_text(json.dumps({"next_id": 100, "releases": list(releases)}))


def _draft(rid, target, draft=True):
    return {"id": rid, "tag_name": "v0.4.0", "target_commitish": target, "name": "Cicada 0.4.0", "body": "",
            "draft": draft, "make_latest": None, "assets": []}


def _kinds(env):
    """Each gh call as list / notes / create / upload / get / publish / delete."""
    out = []
    for c in _calls(env):
        method = c[c.index("-X") + 1] if "-X" in c else "GET"
        target = next(a for a in c[1:] if a.startswith(("repos/", "https://")))
        if target.startswith("https://uploads.github.com/"):
            out.append("upload")
        elif "?per_page" in target:
            out.append("list")
        elif target.endswith("/generate-notes"):
            out.append("notes")
        elif method == "POST":
            out.append("create")
        else:
            out.append({"GET": "get", "PATCH": "publish", "DELETE": "delete"}[method])
    return out


def _remote_tag(env, name="v0.4.0"):
    return _git(env["remote"], "rev-parse", "-q", "--verify", f"refs/tags/{name}^{{commit}}")


def test_a_release_is_drafted_by_id_uploaded_verified_then_published_with_its_tag(env):
    done = _publish(env)
    assert done.returncode == 0, done.stderr
    [release] = _releases(env)
    assert release["draft"] is False and release["make_latest"] == "true"
    assert release["tag_name"] == "v0.4.0" and release["target_commitish"] == env["sha"]
    assert release["name"] == "Cicada 0.4.0"
    assert sorted(a["name"] for a in release["assets"]) == sorted(ASSETS)
    assert "Apple silicon" in release["body"] and "example change" in release["body"], "header, then generated notes"
    assert _remote_tag(env) == env["sha"], "GitHub created the tag at the run's commit"
    assert _kinds(env) == ["list", "notes", "create", "upload", "upload", "upload", "upload", "get", "publish", "get"]
    [notes] = _state(env)["notes_requests"]
    assert notes == {"tag_name": "v0.4.0", "target_commitish": env["sha"], "previous_tag_name": "v0.3.0"}
    [patch] = _state(env)["patches"]
    assert patch == {"tag_name": "v0.4.0", "target_commitish": env["sha"], "draft": False, "make_latest": "true"}, \
        "the tag and target are spelled out: a PATCH that omits tag_name drops the tag"
    uploads = [c for c in _calls(env) if any(a.startswith("https://uploads.github.com/") for a in c)]
    assert all(f"/releases/{release['id']}/assets?name=" in " ".join(c) for c in uploads), "uploads go to its id"
    assert "--clobber" not in " ".join(" ".join(c) for c in _calls(env))


def test_the_new_draft_is_owned_by_the_create_response_so_a_lagging_list_still_publishes(env):
    done = _publish(env, FAKE_GH_LIST_LAG="1")
    assert done.returncode == 0, done.stderr
    [release] = _releases(env)
    assert release["draft"] is False and _remote_tag(env) == env["sha"]
    assert _kinds(env).count("list") == 1, "the list is read once, for leftovers — never to find this run's draft"


def test_a_published_release_under_the_wrong_tag_fails_loudly_and_is_left_alone(env):
    done = _publish(env, FAKE_GH_FAIL="wrongtag")
    assert done.returncode == 1
    assert "untagged-0a1b2c3d" in done.stderr and "by hand" in done.stderr.lower()
    [release] = _releases(env)
    assert release["draft"] is False, "a public release is never deleted, retagged or overwritten"
    assert "delete" not in _kinds(env) and _kinds(env).count("publish") == 1


def test_a_tag_that_landed_on_another_commit_fails_loudly_and_nothing_is_retagged(env):
    done = _publish(env, FAKE_GH_TAG_AT=env["before"])
    assert done.returncode == 1
    assert env["before"][:12] in done.stderr and env["sha"][:12] in done.stderr and "by hand" in done.stderr.lower()
    assert _remote_tag(env) == env["before"], "nothing moved the tag"
    assert "delete" not in _kinds(env) and _kinds(env).count("publish") == 1


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
    """An old run whose commit is no longer main's tip, with the same VERSION still untagged, must not release the
    old code — the run for the newer commit releases main."""
    newer = env["advance_main"]()
    done = _publish(env)
    assert done.returncode == 0, done.stderr
    assert f"superseded by {newer[:12]}" in done.stdout and "that run releases main" in done.stdout
    assert "create" not in _kinds(env) and "publish" not in _kinds(env)
    assert _releases(env) == []


def test_main_moving_between_draft_and_publish_deletes_only_this_run_s_draft(env):
    other = _draft(7, "0" * 40)
    _seed(env, other)
    done = _publish(env, FAKE_GH_MOVE_MAIN=str(env["checkout"]))
    assert done.returncode == 0, done.stderr
    assert "superseded by" in done.stdout
    assert "publish" not in _kinds(env) and "delete" in _kinds(env)
    assert _releases(env) == [other], "the draft it made is gone; another commit's draft is untouched"


def test_a_superseded_run_never_touches_the_newer_run_s_draft(env):
    newer = env["advance_main"]()
    theirs = _draft(7, newer)
    _seed(env, theirs)
    assert _publish(env).returncode == 0
    assert _releases(env) == [theirs] and "delete" not in _kinds(env)


def test_a_run_at_the_tip_leaves_an_older_commit_s_draft_alone_and_publishes_its_own(env):
    stale = _draft(7, "0" * 40)
    _seed(env, stale)
    assert _publish(env).returncode == 0
    mine = [r for r in _releases(env) if r["target_commitish"] == env["sha"]]
    assert len(mine) == 1 and mine[0]["draft"] is False
    assert stale in _releases(env), "another commit's draft is its own run's business (it is private either way)"


def test_a_draft_this_commit_left_in_an_earlier_failed_run_is_replaced(env):
    _seed(env, _draft(7, env["sha"]))
    assert _publish(env).returncode == 0
    assert _kinds(env)[:4] == ["list", "get", "delete", "notes"], "read back as a draft, then deleted by id"
    [release] = _releases(env)
    assert release["id"] != 7 and release["draft"] is False


def test_the_first_release_has_no_previous_tag_for_its_notes(env):
    _git(env["checkout"], "push", "-q", "origin", ":refs/tags/v0.3.0")
    assert _publish(env).returncode == 0
    [notes] = _state(env)["notes_requests"]
    assert "previous_tag_name" not in notes


def test_a_failed_lookup_is_never_read_as_no_release(env):
    done = _publish(env, FAKE_GH_FAIL="list")
    assert done.returncode != 0 and "502" in done.stderr
    assert "create" not in _kinds(env)


@pytest.mark.parametrize("step", ["upload", "size", "edit"])
def test_any_failure_before_publication_deletes_the_id_it_created_and_nothing_else(env, step):
    other = _draft(7, "0" * 40)
    _seed(env, other)
    done = _publish(env, FAKE_GH_FAIL=step)
    assert done.returncode != 0
    assert _releases(env) == [other], "this run's draft is gone, nothing is advertised, the other draft stays"
    deletes = [c for c in _calls(env) if "DELETE" in c]
    assert len(deletes) == 1 and deletes[0][-1].endswith("/releases/100")


def test_the_stable_asset_must_be_the_same_bytes_as_the_versioned_zip(env):
    (env["dist"] / "Cicada-macos-arm64.zip").write_bytes(b"other bytes")
    done = _publish(env)
    assert done.returncode != 0 and "Cicada-macos-arm64.zip" in done.stderr
    assert _calls(env) == [], "nothing is created when the files are wrong"


def test_an_already_published_release_is_left_alone_and_the_run_is_green(env):
    published = _draft(7, env["sha"], draft=False)
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
    for banned in ("git push", "git tag", "--force", "--clobber", "--cleanup-tag", "gh release "):
        assert banned not in text, f"{banned}: releases are created, uploaded and published by id through gh api"
    assert 'git ls-remote "$REMOTE" refs/heads/main' in text


def test_a_publish_patch_without_its_tag_would_be_caught(env, tmp_path):
    """GitHub drops the tag of a release patched without tag_name. Prove the read-back catches exactly that: a copy of
    publish.sh whose PATCH omits tag_name fails loudly instead of reporting success."""
    copy = tmp_path / "release-copy"
    copy.mkdir()
    for name in ("check_version.py", "release-notes-header.md"):
        (copy / name).write_text((SCRIPT.parent / name).read_text(encoding="utf-8"))
    text = SCRIPT.read_text(encoding="utf-8")
    patch_line = 'gh api -X PATCH "$API/$ID" -f tag_name="$TAG" '
    assert patch_line in text
    (copy / "publish.sh").write_text(text.replace(patch_line, 'gh api -X PATCH "$API/$ID" '))
    (copy / "publish.sh").chmod(0o755)
    done = subprocess.run([str(copy / "publish.sh"), "0.4.0", env["sha"], str(env["dist"])], env=env["env"],
                          cwd=env["checkout"], capture_output=True, text=True)
    assert done.returncode == 1 and "untagged-" in done.stderr
    assert "✓ published" not in done.stdout
