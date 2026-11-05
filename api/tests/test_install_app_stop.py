"""ROR-41: installing the app quits only the installed app, found by its executable's path.

`pkill -x CicadaApp` also killed a verify copy and a build run from elsewhere, which share the process name."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "install_app.sh"


def _stub(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


def test_no_signal_goes_by_the_process_name_alone():
    text = SCRIPT.read_text()
    assert not re.search(r"^\s*pkill\b", text, re.M)


def test_only_the_installed_path_is_signalled(tmp_path):
    text = SCRIPT.read_text()
    start = text.index('INSTALLED_EXEC="')
    end = text.index('if [ -n "$(installed_pids)" ]; then')
    app_dir = tmp_path / "Applications"
    app_dir.mkdir()
    installed = f"{app_dir.resolve()}/Cicada.app/Contents/MacOS/CicadaApp"
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _stub(stubs, "pgrep", "echo 101\necho 202\n")
    _stub(stubs, "ps", f'if [ "$4" = "101" ]; then echo "{installed}"; else echo "/elsewhere/Cicada.app/Contents/MacOS/CicadaApp"; fi\n')
    body = (f'set -euo pipefail\nAPP_DIR="{app_dir}"\n' + text[start:end]
            + 'kill() { echo "signal $1 $2"; }\nsignal_installed TERM\n')
    out = subprocess.run(["/bin/bash", "-c", body], capture_output=True, text=True, timeout=20,
                         env={**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.split("\n")[0] == "signal -TERM 101"
    assert "202" not in out.stdout
