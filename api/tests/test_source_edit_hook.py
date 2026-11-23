"""G244 / ruling 76: the PostToolUse hook that records an agent's edit of a watched source file.

Everything is injected (the folder list, the post, the clock); no network, no real home. It pins: a file inside a
folder posts its hash and no words, outside posts nothing, the longest root wins, a symlink is never followed, the
folder list is cached (an edit outside costs no request), ``CICADA_CAPTURE=off`` stops it, and a backend that is down
never makes the hook fail, print or log a path.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from api.hooks import source_edit as hook

SID = "11111111-2222-4333-8444-555555555555"


class Backend:
    """A folder list and a recorder of what was asked and posted."""

    def __init__(self, folders, *, get_status=200, post_answer=None, post_status=200):
        self.folders = folders
        self.get_status = get_status
        self.post_answer = post_answer or {"status": "attached", "episodes": ["ep_2026-11-23_001"]}
        self.post_status = post_status
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict, str, float]] = []

    def get(self, url, token, timeout):
        self.gets.append(url)
        if self.get_status is None:
            return None, ""
        return self.get_status, json.dumps({"folders": self.folders})

    def post(self, url, body, token, timeout):
        self.posts.append((url, json.loads(body), token, timeout))
        if self.post_status is None:
            return None, ""
        return self.post_status, json.dumps(self.post_answer)


@pytest.fixture
def home(tmp_path):
    cicada_home = tmp_path / "cicada-home"
    cicada_home.mkdir()
    (cicada_home / "api_token").write_text("tok-123")
    return cicada_home


def _env(home: Path, **extra) -> dict:
    return {"HOME": str(home.parent), "CICADA_HOME": str(home), "CICADA_PORT": "8123", **extra}


def _folder(root: Path, fid="f-a1b2c3", **extra) -> dict:
    return {"id": fid, "label": "notes", "path": str(root), "device": "this-mac", "include": ["**/*.md"],
            "exclude": [".git/**"], **extra}


def _payload(path, **extra) -> dict:
    return {"session_id": SID, "transcript_path": f"/home/example/.claude/projects/x/{SID}.jsonl",
            "cwd": "/home/example/alpha-project", "hook_event_name": "PostToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": str(path)}, **extra}


def _fire(home, payload, backend, *, environ=None, argv=("--harness", "claude-code"), now=1_000_000.0):
    stdout = io.StringIO()
    rc = hook.main(list(argv), stdin=io.StringIO(json.dumps(payload)), environ=environ or _env(home),
                   get=backend.get, post=backend.post, now=now)
    return rc


def _log(home: Path) -> str:
    path = home / "logs" / "capture.log"
    return path.read_text() if path.exists() else ""


def test_an_edit_inside_a_folder_posts_the_hash_and_never_a_word(tmp_path, home, capsys):
    root = tmp_path / "vault"
    (root / "meetings").mkdir(parents=True)
    note = root / "meetings" / "2026-11-20 0900 standup.md"
    note.write_bytes(b"secret words of the file\n")
    backend = Backend([_folder(root)])
    assert _fire(home, _payload(note), backend) == 0
    (url, body, token, timeout), = backend.posts
    assert url == "http://127.0.0.1:8123/capture/source-edit" and token == "tok-123" and timeout <= 3
    assert body == {"folder_id": "f-a1b2c3", "relpath": "meetings/2026-11-20 0900 standup.md",
                    "sha256": hashlib.sha256(b"secret words of the file\n").hexdigest(), "harness": "claude-code",
                    "session_id": SID, "transcript_path": f"/home/example/.claude/projects/x/{SID}.jsonl",
                    "tool": "Edit", "at": body["at"]}
    assert body["at"].startswith("1970-01-12T") and body["at"].endswith("+00:00")
    assert "secret words" not in json.dumps(body)
    assert capsys.readouterr().out == "", "a PostToolUse hook's stdout is the agent's"
    line = _log(home)
    assert "source-edit attached: 1 episode" in line
    assert str(note) not in line and "standup" not in line and "vault" not in line, "the log never names a path"


def test_an_edit_outside_every_folder_posts_nothing_and_logs_nothing(tmp_path, home):
    root, elsewhere = tmp_path / "vault", tmp_path / "other"
    root.mkdir(), elsewhere.mkdir()
    stray = elsewhere / "a.md"
    stray.write_text("x")
    backend = Backend([_folder(root)])
    assert _fire(home, _payload(stray), backend) == 0
    assert backend.posts == [] and _log(home) == ""


def test_a_file_a_folder_would_never_sync_posts_nothing(tmp_path, home):
    root = tmp_path / "vault"
    (root / ".git").mkdir(parents=True)
    for rel in ("image.png", ".git/config.md"):
        (root / rel).write_text("x")
    backend = Backend([_folder(root)])
    for rel in ("image.png", ".git/config.md"):
        _fire(home, _payload(root / rel), backend)
    assert backend.posts == []


def test_the_longest_root_wins_when_a_folder_sits_inside_another(tmp_path, home):
    outer, inner = tmp_path / "vault", tmp_path / "vault" / "meetings"
    inner.mkdir(parents=True)
    note = inner / "a.md"
    note.write_text("x")
    backend = Backend([_folder(outer, "f-outer"), _folder(inner, "f-inner")])
    _fire(home, _payload(note), backend)
    assert backend.posts[0][1]["folder_id"] == "f-inner" and backend.posts[0][1]["relpath"] == "a.md"
    backend2 = Backend([_folder(inner, "f-inner"), _folder(outer, "f-outer")])   # the order of the list never decides
    _fire(home, _payload(note), backend2, now=2_000_000.0)
    assert backend2.posts[0][1]["folder_id"] == "f-inner"


def test_a_relative_path_is_read_against_the_hook_s_cwd(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "a.md").write_text("x")
    backend = Backend([_folder(root)])
    payload = {**_payload("a.md"), "cwd": str(root)}
    _fire(home, payload, backend)
    assert backend.posts[0][1]["relpath"] == "a.md"


def test_a_notebook_edit_names_its_notebook_path(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "n.ipynb").write_text("{}")
    backend = Backend([_folder(root, include=["**/*.ipynb"])])
    payload = {**_payload(""), "tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(root / "n.ipynb")}}
    _fire(home, payload, backend)
    assert backend.posts[0][1]["tool"] == "NotebookEdit" and backend.posts[0][1]["relpath"] == "n.ipynb"


def test_a_symlink_is_never_followed(tmp_path, home):
    root, outside = tmp_path / "vault", tmp_path / "outside"
    root.mkdir(), outside.mkdir()
    target_in, target_out = root / "real.md", outside / "secret.md"
    target_in.write_text("x"), target_out.write_text("y")
    (root / "link-in.md").symlink_to(target_in)      # a link to a file in the folder: refused all the same
    (root / "link-out.md").symlink_to(target_out)    # a link out of the folder
    (outside / "dir-link").symlink_to(root, target_is_directory=True)
    backend = Backend([_folder(root)])
    for path in (root / "link-in.md", root / "link-out.md"):
        _fire(home, _payload(path), backend)
    assert backend.posts == []
    # A path through a linked directory resolves to the real file under the root: that is the file, not a trick.
    _fire(home, _payload(outside / "dir-link" / "real.md"), backend)
    assert [p[1]["relpath"] for p in backend.posts] == ["real.md"]
    # And the folder's own link out of itself is never a way in.
    backend2 = Backend([_folder(outside / "dir-link", "f-link")])
    (root / "sub").mkdir()
    (root / "sub" / "z.md").write_text("z")
    _fire(home, _payload(root / "sub" / "z.md"), backend2, now=3_000_000.0)
    assert backend2.posts[0][1]["relpath"] == "sub/z.md"


def test_a_directory_or_a_missing_file_posts_nothing(tmp_path, home):
    root = tmp_path / "vault"
    (root / "d.md").mkdir(parents=True)
    backend = Backend([_folder(root)])
    _fire(home, _payload(root / "d.md"), backend)
    _fire(home, _payload(root / "gone.md"), backend)
    assert backend.posts == []


def test_a_file_over_the_app_s_sync_cap_is_skipped(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    big = root / "big.md"
    big.write_bytes(b"x" * (hook.MAX_FILE_BYTES + 1))
    backend = Backend([_folder(root)])
    _fire(home, _payload(big), backend)
    assert backend.posts == [] and "size cap" in _log(home)


def test_another_tool_or_a_missing_session_does_nothing(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "a.md"
    note.write_text("x")
    backend = Backend([_folder(root)])
    _fire(home, {**_payload(note), "tool_name": "Bash"}, backend)
    _fire(home, {**_payload(note), "session_id": ""}, backend)
    _fire(home, {"hook_event_name": "PostToolUse", "tool_name": "Edit", "session_id": SID, "tool_input": {}}, backend)
    assert backend.posts == [] and backend.gets == []


def test_the_folder_list_is_cached_so_an_edit_outside_costs_no_request(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    note, stray = root / "a.md", tmp_path / "stray.md"
    note.write_text("x"), stray.write_text("y")
    backend = Backend([_folder(root)])
    _fire(home, _payload(stray), backend, now=1000.0)
    _fire(home, _payload(stray), backend, now=1000.0 + hook.TTL_S - 1)
    _fire(home, _payload(note), backend, now=1000.0 + hook.TTL_S - 1)
    assert len(backend.gets) == 1, "one lookup for the whole minute"
    assert len(backend.posts) == 1
    _fire(home, _payload(stray), backend, now=1000.0 + hook.TTL_S + 1)
    assert len(backend.gets) == 2, "refreshed once the TTL passes"
    assert not list((home / "state").glob("*.tmp"))


def test_a_new_folder_is_seen_after_the_cache_expires(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "a.md"
    note.write_text("x")
    backend = Backend([])
    _fire(home, _payload(note), backend, now=1000.0)
    assert backend.posts == []
    backend.folders = [_folder(root)]
    _fire(home, _payload(note), backend, now=1000.0 + hook.TTL_S + 1)
    assert len(backend.posts) == 1


def test_capture_off_does_nothing_at_all(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "a.md"
    note.write_text("x")
    backend = Backend([_folder(root)])
    assert _fire(home, _payload(note), backend, environ=_env(home, CICADA_CAPTURE="off")) == 0
    assert backend.gets == [] and backend.posts == [] and _log(home) == ""
    assert not (home / "state").exists()


@pytest.mark.parametrize("get_status,post_status", [(None, None), (500, 200), (200, None), (200, 500), (200, 409)])
def test_a_backend_that_is_down_never_makes_the_hook_fail(tmp_path, home, capsys, get_status, post_status):
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "a.md"
    note.write_text("x")
    backend = Backend([_folder(root)], get_status=get_status, post_status=post_status)
    assert _fire(home, _payload(note), backend) == 0
    assert capsys.readouterr().out == ""
    assert str(note) not in _log(home)


def test_a_failed_folder_lookup_keeps_the_last_list_and_is_not_repeated_on_every_edit(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "a.md"
    note.write_text("x")
    up = Backend([_folder(root)])
    _fire(home, _payload(note), up, now=1000.0)
    down = Backend([], get_status=None)
    _fire(home, _payload(note), down, now=1000.0 + hook.TTL_S + 1)       # refresh fails: stale list still works
    assert len(down.gets) == 1 and len(down.posts) == 1
    _fire(home, _payload(note), down, now=1000.0 + hook.TTL_S + 2)       # and is not asked again straight away
    assert len(down.gets) == 1 and len(down.posts) == 2


def test_a_garbled_stdin_and_a_bare_environment_never_raise(tmp_path, home):
    for raw in ("", "not json", "[1, 2]", json.dumps({"tool_name": "Edit", "tool_input": "x"})):
        rc = hook.main([], stdin=io.StringIO(raw), environ=_env(home), get=lambda *a: (None, ""),
                       post=lambda *a: (None, ""))
        assert rc == 0
    assert hook.main([], stdin=io.StringIO("{}"), environ={}) == 0


def test_a_refused_answer_is_logged_as_an_enum_with_its_count(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "a.md"
    note.write_text("x")
    backend = Backend([_folder(root)], post_answer={"status": "refused", "episodes": [], "reason": "unknown_folder"})
    _fire(home, _payload(note), backend)
    assert "source-edit refused: 0 episodes (unknown_folder)" in _log(home)
    held = Backend([_folder(root)], post_answer={"status": "held", "episodes": []})
    _fire(home, _payload(note), held, now=9_000_000.0)
    assert "source-edit held: 0 episodes" in _log(home)


def test_a_client_of_a_server_elsewhere_posts_there_with_its_device_token(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "a.md"
    note.write_text("x")
    (home / "device_token").write_text("device-tok")
    environ = _env(home, CICADA_API_BASE="https://home.example.test", CICADA_API_TOKEN="device-tok")
    backend = Backend([_folder(root)])
    _fire(home, _payload(note), backend, environ=environ)
    assert backend.gets == ["https://home.example.test/sources/folders"]
    assert backend.posts[0][0] == "https://home.example.test/capture/source-edit" and backend.posts[0][2] == "device-tok"


def test_the_harness_flag_names_the_post(tmp_path, home):
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "a.md"
    note.write_text("x")
    backend = Backend([_folder(root)])
    _fire(home, _payload(note), backend, argv=("--harness", "codex"))
    assert backend.posts[0][1]["harness"] == "codex"


def test_the_hook_imports_nothing_heavy_on_the_fast_path(tmp_path, home):
    """An edit outside every folder with a fresh cache must not pull urllib in (the interpreter's own start is the
    whole cost)."""
    import subprocess
    import sys

    (home / "state").mkdir()
    (home / "state" / hook.STATE_FILE).write_text(json.dumps({"at": 4_000_000_000.0, "ok": True, "folders": []}))
    stray = tmp_path / "x.md"
    stray.write_text("x")
    code = ("import sys, io, json; sys.path.insert(0, %r); import source_edit as s; "
            "s.main([], stdin=io.StringIO(%r), environ={'CICADA_HOME': %r, 'HOME': %r}, now=4000000000.0); "
            "print('urllib.request' in sys.modules, 'hook_client' in sys.modules)"
            % (str(Path(hook.__file__).parent), json.dumps(_payload(stray)), str(home), str(tmp_path)))
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
                          env={"PATH": os.environ.get("PATH", "")})
    assert done.stdout.strip() == "False False", done.stdout + done.stderr
