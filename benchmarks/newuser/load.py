"""Load the synthetic new user into a running scratch backend through the doors a real install uses.

    api/.venv/bin/python -m benchmarks.newuser.load --run <verify-cicada run dir> [--fixture DIR]

``--run`` is a run directory ``verify-cicada``'s ``cv launch`` printed: its ``run.json`` names the port, the scratch
``HOME`` (whose ``.claude/projects`` is the backend's harness root) and ``CICADA_HOME`` (the token). Never point it at
a live install: it refuses port 8000 and a run without the verify marker.

Doors, in the order a new person meets them:

1. ``PUT /settings/owner`` — the name onboarding asks for.
2. ``POST /intake/import`` — the ChatGPT export zip, then the Claude.ai export zip (the app's import panel).
3. ``POST /capture/transcript`` — each Claude Code session, as its Stop hook posts it, after the transcript is
   copied under the scratch harness root (the hook never sends bytes; the backend reads the file there), with the
   hook's own workspace observation (a git checkout for the two repositories, :func:`workspace`).
4. ``POST /sources/upload`` — the browser bookmarks file.
5. ``POST /sources/calendar-local/sync`` — the calendar window the app reads through EventKit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from benchmarks.newuser import persona


def _run(run_dir: Path) -> dict:
    run = json.loads((run_dir / "run.json").read_text())
    if int(run["port"]) in (8000, 8765):
        raise SystemExit("refusing a live port")
    return run


def _request(run: dict, method: str, path: str, *, body: bytes | None = None, ctype: str = "application/json",
             timeout: float = 120.0) -> tuple[int, dict | str]:
    token = (Path(run["env"]["CICADA_HOME"]) / "api_token").read_text().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{run['port']}{path}", data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            code = resp.status
    except urllib.error.HTTPError as exc:
        raw, code = exc.read().decode(), exc.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw


def _json(run: dict, method: str, path: str, payload) -> tuple[int, dict | str]:
    return _request(run, method, path, body=json.dumps(payload).encode())


def _upload(run: dict, path: str, file: Path) -> tuple[int, dict | str]:
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file.name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode()
    body = head + file.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return _request(run, "POST", path, body=body, ctype=f"multipart/form-data; boundary={boundary}")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()[:16]


def workspace(cwd: str, home: str) -> dict:
    """What the Stop hook's ``workspace_identity.observe`` posts for ``cwd``: the cwd's hash, and for a git checkout
    the ``rev-parse`` pair plus the scope hash (G110 D2). The checkouts are the persona's, so the pair is synthesised
    here the way git would answer in them; ``observed_at`` is now, as the backend accepts only a fresh look."""
    from datetime import datetime, timezone

    seen = {"cwd_hash": _hash(cwd), "observed_at": datetime.now(timezone.utc).isoformat()}
    if cwd not in persona.REPO_CWDS:
        return seen
    return {**seen, "repo_root": cwd, "common_dir": f"{cwd}/.git", "scope_hash": _hash(f"{home}\0persona-host")}


def _wait_job(run: dict, answer: dict) -> dict:
    job = (answer or {}).get("job") if isinstance(answer, dict) else None
    if not job:
        return answer
    for _ in range(300):
        code, status = _request(run, "GET", f"/intake/jobs/{job['id']}")
        if code == 200 and status.get("done"):
            return status
        time.sleep(1)
    raise SystemExit(f"intake job {job['id']} did not finish")


def load(run_dir: Path, fixture: Path) -> list[dict]:
    run = _run(run_dir)
    manifest = persona.build(fixture)
    log: list[dict] = []

    def note(step: str, code: int, answer) -> None:
        log.append({"step": step, "code": code, "answer": answer})
        print(f"{code} {step}")
        if code >= 300:
            raise SystemExit(f"{step} answered {code}: {answer}")

    note("owner", *_json(run, "PUT", "/settings/owner", {"name": manifest["owner"]}))
    for key in ("chatgpt", "claude"):
        code, answer = _upload(run, "/intake/import", fixture / manifest[key])
        note(f"import {key}", code, _wait_job(run, answer) if code == 202 else answer)
    harness_root = Path(run["env"]["HOME"]) / ".claude" / "projects"
    for t in manifest["transcripts"]:
        dest = harness_root / t["rel"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture / "claude-projects" / t["rel"], dest)
        note(f"transcript {t['session_id'][:8]}", *_json(run, "POST", "/capture/transcript", {
            "harness": "claude-code", "session_id": t["session_id"], "transcript_path": str(dest),
            "cwd": t["cwd"], "hook_event": "Stop", "workspace": workspace(t["cwd"], run["env"]["HOME"])}))
    note("bookmarks", *_upload(run, "/sources/upload", fixture / manifest["bookmarks"]))
    note("calendar", *_json(run, "POST", "/sources/calendar-local/sync",
                            json.loads((fixture / manifest["calendar"]).read_text())))
    return log


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, help="where to write the fixture files (default: <run>/newuser-fixture)")
    args = ap.parse_args()
    fixture = args.fixture or args.run / "newuser-fixture"
    log = load(args.run, fixture)
    (fixture / "load-log.json").write_text(json.dumps(log, indent=1))


if __name__ == "__main__":
    main()
