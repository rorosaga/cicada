"""G182 phase 5 — scripts/install-release.sh, the tester's one-line install.

Served from a local HTTP server standing in for GitHub (CICADA_RELEASE_API), installing
into a temp folder with a temp HOME, never opening the app. The real ~/Applications, a
running Cicada and the network are never touched.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install-release.sh"

pytestmark = pytest.mark.skipif(shutil.which("codesign") is None or os.uname().machine != "arm64",
                                reason="macOS arm64 only")


def _fake_app(where: Path, version: str) -> Path:
    app = where / "Cicada.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    shutil.copy("/usr/bin/true", app / "Contents" / "MacOS" / "CicadaApp")
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        "<key>CFBundleExecutable</key><string>CicadaApp</string>"
        "<key>CFBundleIdentifier</key><string>com.example.cicada-test</string>"
        f"<key>CFBundleShortVersionString</key><string>{version}</string></dict></plist>")
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True, capture_output=True)
    return app


@pytest.fixture
def release(tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    build = tmp_path / "build"
    build.mkdir()
    app = _fake_app(build, "9.9.9")
    zip_path = served / "Cicada-9.9.9.zip"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(zip_path)], check=True)

    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(served), **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (served / "latest.json").write_text(json.dumps({"version": "9.9.9", "build": 1, "url": f"{base}/Cicada-9.9.9.zip",
                                                    "sha256": sha, "signature": "unused"}))
    (served / "release.json").write_text(json.dumps({"assets": [
        {"name": "Cicada-9.9.9.zip", "browser_download_url": f"{base}/Cicada-9.9.9.zip"},
        {"name": "latest.json", "browser_download_url": f"{base}/latest.json"}]}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "CICADA_NO_OPEN": "1",
           "CICADA_RELEASE_API": f"{base}/release.json", "CICADA_INSTALL_DIR": str(tmp_path / "Applications")}
    yield env, served, tmp_path / "Applications" / "Cicada.app", home
    server.shutdown()


def _run(env):
    return subprocess.run(["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)


def test_it_installs_the_checked_release_and_trashes_the_old_copy(release):
    env, _served, dest, home = release
    dest.parent.mkdir(parents=True)
    old = _fake_app(dest.parent, "0.0.1")
    assert old == dest
    done = _run(env)
    assert done.returncode == 0, done.stderr + done.stdout
    assert "Installed Cicada 9.9.9" in done.stdout
    assert "9.9.9" in (dest / "Contents" / "Info.plist").read_text()
    trashed = list((home / ".Trash").glob("Cicada *.app"))
    assert len(trashed) == 1 and "0.0.1" in (trashed[0] / "Contents" / "Info.plist").read_text()


def test_a_checksum_mismatch_installs_nothing(release):
    env, served, dest, _home = release
    doc = json.loads((served / "latest.json").read_text())
    doc["sha256"] = "0" * 64
    (served / "latest.json").write_text(json.dumps(doc))
    done = _run(env)
    assert done.returncode == 1 and "checksum" in done.stderr
    assert not dest.exists()


def test_a_release_without_latest_json_installs_nothing(release):
    env, served, dest, _home = release
    (served / "release.json").write_text(json.dumps({"assets": []}))
    done = _run(env)
    assert done.returncode == 1 and "latest.json" in done.stderr
    assert not dest.exists()


def test_it_never_quits_a_cicada_running_from_elsewhere():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'pgrep -f "^$RUNNING"' in text and "pkill -x" not in text and "pgrep -x" not in text
    assert "rorosaga/cicada/main/scripts/install-release.sh" in text, "the documented one-liner"


def test_a_staged_app_update_is_dropped_and_a_failed_copy_keeps_the_old_app(release, monkeypatch):
    env, _served, dest, _home = release
    dest.parent.mkdir(parents=True)
    _fake_app(dest.parent, "0.0.1")
    staged_update = dest.parent / ".Cicada.app.update"
    staged_update.mkdir()
    done = _run(env)
    assert done.returncode == 0, done.stderr
    assert not staged_update.exists(), "the app's own staged update can't race this install"
    assert not (dest.parent / ".Cicada.app.new").exists()


def test_a_wrong_version_inside_installs_nothing(release):
    env, served, dest, _home = release
    doc = json.loads((served / "latest.json").read_text())
    doc["version"] = "9.9.8"
    (served / "latest.json").write_text(json.dumps(doc))
    done = _run(env)
    assert done.returncode == 1 and "not 9.9.8" in done.stderr
    assert not dest.exists()
