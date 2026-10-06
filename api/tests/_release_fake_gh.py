"""A fake `gh api` for scripts/release/publish.sh's tests (G182), modelling GitHub's REST behaviour honestly.

Installed on PATH as `gh` by test_release_publish.py. It models:

- releases addressed by id (GitHub lets two drafts share a tag name);
- a PATCH that omits `tag_name` dropping the release's tag (it becomes `untagged-…`), as the GitHub CLI documents
  and guards against;
- publication of a draft creating its tag at `target_commitish` in the bare repo `$FAKE_GH_REMOTE`, unless the tag
  already exists (an existing tag wins);
- an eventually consistent list: with `$FAKE_GH_LIST_LAG` set, drafts created during the run are missing from it;
- asset uploads to `https://uploads.github.com/repos/<repo>/releases/<id>/assets?name=…`.

`$FAKE_GH_FAIL` names a step to fail: `list` | `upload` (the second asset) | `size` (the last asset lands one byte
short) | `edit` | `wrongtag` (the published release comes back under another tag). `$FAKE_GH_TAG_AT` makes publication
create the tag at that commit instead (a tag racing in). `$FAKE_GH_MOVE_MAIN` (a checkout) pushes a new commit to
its origin's main right after the release is created. Every call is appended to `$FAKE_GH_LOG` as a JSON argv.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main(args: list[str]) -> int:
    state_file = Path(os.environ["FAKE_GH_STATE"])
    state = json.loads(state_file.read_text()) if state_file.exists() else {"next_id": 1, "releases": []}
    fail = os.environ.get("FAKE_GH_FAIL", "")
    repo = os.environ["GH_REPO"]
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(json.dumps(args) + "\n")

    def save():
        state_file.write_text(json.dumps(state))

    def out(obj) -> int:
        print(json.dumps(obj))
        return 0

    def err(msg: str, code: int = 1) -> int:
        print(msg, file=sys.stderr)
        return code

    assert args[0] == "api", args
    method, path, fields, body_file, i = "GET", None, {}, None, 1
    while i < len(args):
        a = args[i]
        if a == "-X":
            method = args[i + 1]
            i += 2
        elif a in ("-F", "-f"):
            k, v = args[i + 1].split("=", 1)
            fields[k] = {"false": False, "true": True}.get(v, v) if a == "-F" else v
            i += 2
        elif a == "--input":
            body_file = args[i + 1]
            i += 2
        elif a == "-H":
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            path = a
            i += 1

    def find(rid: int):
        return next((r for r in state["releases"] if r["id"] == rid), None)

    uploads = f"https://uploads.github.com/repos/{repo}/releases/"
    if path.startswith(uploads):
        assert method == "POST" and body_file, args
        rid, name = path[len(uploads):].split("/assets?name=")
        release = find(int(rid))
        if release is None:
            return err("HTTP 404: Not Found")
        n = len(release["assets"])
        if fail == "upload" and n == 1:
            return err("HTTP 502: upload failed")
        size = os.path.getsize(body_file) - (1 if fail == "size" and n == 3 else 0)
        release["assets"].append({"name": name, "size": size, "state": "uploaded"})
        save()
        return out(release["assets"][-1])

    api = f"repos/{repo}/releases"
    assert path.startswith(api), path
    tail = path[len(api):]
    if tail.startswith("?"):
        if fail == "list":
            return err("HTTP 502: Bad Gateway")
        assert method == "GET" and "--paginate" in args and "--slurp" in args, args
        lag = bool(os.environ.get("FAKE_GH_LIST_LAG"))
        return out([[r for r in state["releases"] if not (lag and r.get("fresh"))]])
    if tail == "/generate-notes":
        assert method == "POST" and fields.get("tag_name") and fields.get("target_commitish"), fields
        state.setdefault("notes_requests", []).append(fields)
        save()
        return out({"name": fields["tag_name"], "body": "## What's Changed\n* example change"})
    if tail == "":
        assert method == "POST" and body_file, args
        payload = json.loads(Path(body_file).read_text())
        rid = state["next_id"]
        state["next_id"] += 1
        release = {"id": rid, "tag_name": payload["tag_name"], "target_commitish": payload["target_commitish"],
                   "name": payload["name"], "body": payload["body"], "draft": payload["draft"],
                   "make_latest": None, "assets": [], "fresh": True,
                   "upload_url": f"https://uploads.github.com/repos/{repo}/releases/{rid}/assets{{?name,label}}"}
        state["releases"].append(release)
        save()
        if os.environ.get("FAKE_GH_MOVE_MAIN"):
            co = os.environ["FAKE_GH_MOVE_MAIN"]
            subprocess.run(["git", "-C", co, "commit", "-q", "--allow-empty", "-m", "newer"], check=True)
            subprocess.run(["git", "-C", co, "push", "-q", "origin", "HEAD:main"], check=True)
        return out(release)

    release = find(int(tail.strip("/")))
    if release is None:
        return err("HTTP 404: Not Found")
    if method == "GET":
        return out(release)
    if method == "PATCH":
        if fail == "edit":
            return err("HTTP 500")
        state.setdefault("patches", []).append(fields)
        release["tag_name"] = fields.get("tag_name") or "untagged-0a1b2c3d"   # omission drops the tag
        if fail == "wrongtag":
            release["tag_name"] = "untagged-0a1b2c3d"
        release["target_commitish"] = fields.get("target_commitish", release["target_commitish"])
        release["draft"] = fields.get("draft", release["draft"])
        release["make_latest"] = fields.get("make_latest")
        if release["draft"] is False and release["tag_name"].startswith("v"):
            ref = "refs/tags/" + release["tag_name"]
            remote = os.environ["FAKE_GH_REMOTE"]
            exists = subprocess.run(["git", "--git-dir", remote, "rev-parse", "-q", "--verify", ref],
                                    capture_output=True).returncode == 0
            if not exists:
                at = os.environ.get("FAKE_GH_TAG_AT") or release["target_commitish"]
                subprocess.run(["git", "--git-dir", remote, "update-ref", ref, at], check=True)
        save()
        return out(release)
    if method == "DELETE":
        assert release["draft"] is True, "a published release must never be deleted"
        state["releases"].remove(release)
        save()
        return 0
    return err("unexpected: " + " ".join(args), 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
