"""scripts/dev/auto-update.sh must not move code or restart the backend under a running Sleep,
and must restart the backend only when backend runtime code moved.

Every test runs a COPY of the script inside a scratch git repo, with stub `launchctl`, `curl`,
`uv`, `pgrep`, `lsof`, `ss` and installer executables first on PATH that record their calls. The real script,
launchctl and installer are never run.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "auto-update.sh"
INSTALLER = SCRIPT.parent / "install-auto-update.sh"
UNAME_STUB = '[ "$1" = "-s" ] && { echo "$UNAME_S"; exit 0; }\nexec /usr/bin/uname "$@"\n'


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


class Rig:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.repo = tmp / "repo"
        self.bin = tmp / "bin"
        self.home = tmp / "home"
        self.calls = tmp / "calls.log"
        self.status_file = tmp / "status.json"
        self.curl_exit = ""
        self.http_500 = False
        self.now = 1_800_000_000          # the rig's clock (epoch seconds): the script reads `date +%s` through a stub
        self.backend_pid = ""             # what launchd / systemd report as the backend's own pid
        self.holders: list[str] | None = None   # "pid:port" listeners the port tools see; None = the backend pid on the asked port
        self.port_tool = "lsof"           # lsof | ss | none (both absent: exit 127) | blind (ss shows no process column)
        self.print_ok_first = ""          # launchctl print succeeds only this many times per run ("" = always)
        self.bin.mkdir()
        self.home.mkdir()
        self.calls.write_text("")
        _git(tmp, "init", "-q", "--bare", "-b", "dev", str(self.origin))
        _git(tmp, "clone", "-q", str(self.origin), str(self.repo))
        _git(self.repo, "checkout", "-q", "-b", "dev")
        (self.repo / "scripts/dev").mkdir(parents=True)
        shutil.copy(SCRIPT, self.repo / "scripts/dev/auto-update.sh")
        for rel in ("api/app.py", "api/tests/test_x.py", "mcp/server.py", "benchmarks/b.py", "docs/a.md",
                    "app/CicadaApp/x.swift"):
            self.write(rel, "v1")
        (self.repo / "logs").mkdir()
        (self.repo / "logs/.gitignore").write_text("*\n")
        _stub(self.repo / "app/CicadaApp/install_app.sh", 'echo "install_app $*" >> "$CALLS"\n')
        _stub(self.repo / "scripts/sync-server-env.sh",
              'echo "sync-server-env $*" >> "$CALLS"\n[ -z "$SYNC_FAILS" ] || exit 1\n')
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "base")
        _git(self.repo, "push", "-q", "origin", "dev")
        self.base = _git(self.repo, "rev-parse", "HEAD")
        (self.repo / "logs/.auto-update-installed").write_text(self.base + "\n")
        # `launchctl print` reports the service's pid the way launchd does (a tab-indented `pid = N` line).
        _stub(self.bin / "launchctl", 'echo "launchctl $*" >> "$CALLS"\n'
                                      'case "$1" in print)\n'
                                      '  if [ -n "$PRINT_OK_FIRST" ]; then n=$(cat "$CALLS.print" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$CALLS.print"\n'
                                      '    [ "$n" -le "$PRINT_OK_FIRST" ] || exit 113; fi\n'
                                      '  printf \'gui/501/com.cicada.backend = {\\n\\tstate = running\\n\'\n'
                                      '  [ -z "$BACKEND_PID" ] || printf \'\\tpid = %s\\n\' "$BACKEND_PID"; echo "}" ;; esac\n'
                                      'exit 0\n')
        # The clock is the rig's, and a wait is only recorded: no test sleeps for real.
        _stub(self.bin / "date", '[ "$1" = "+%s" ] && [ -n "$FAKE_NOW" ] && { echo "$FAKE_NOW"; exit 0; }\nexec /bin/date "$@"\n')
        _stub(self.bin / "sleep", 'echo "sleep $*" >> "$CALLS"\nexit 0\n')
        _stub(self.bin / "uv", 'echo "uv $*" >> "$CALLS"\nexit 0\n')
        _stub(self.bin / "pgrep", "exit 1\n")
        # The port tools answer from the rig's table of listeners (PORT_HOLDERS: "pid:port ..."), in their real shapes.
        _stub(self.bin / "lsof", '''
            echo "lsof $*" >> "$CALLS"
            [ "$PORT_TOOL" = none ] && exit 127
            pid=""; port=""
            while [ $# -gt 0 ]; do
              case "$1" in -p) pid="$2"; shift ;; -iTCP:*) port="${1#-iTCP:}" ;; esac
              shift
            done
            case " $PORT_HOLDERS " in *" $pid:$port "*) echo "$pid"; exit 0 ;; esac
            exit 1
            ''')
        _stub(self.bin / "ss", '''
            echo "ss $*" >> "$CALLS"
            [ "$PORT_TOOL" = lsof ] && exit 127
            [ "$PORT_TOOL" = none ] && exit 127
            for a; do port="$a"; done; port="${port#*:}"
            for h in $PORT_HOLDERS; do
              [ "${h#*:}" = "$port" ] || continue
              if [ "$PORT_TOOL" = blind ]; then echo "LISTEN 0 2048 127.0.0.1:$port 0.0.0.0:*"
              else echo "LISTEN 0 2048 127.0.0.1:$port 0.0.0.0:* users:((\\"python3\\",pid=${h%%:*},fd=7))"; fi
            done
            exit 0
            ''')
        # The OS is the rig's choice, not the runner's: CI runs these on Linux.
        self.os_name = "Darwin"
        _stub(self.bin / "uname", UNAME_STUB)
        self.unit_loaded = True
        # `systemctl --user cat` prints the unit install-backend-service.sh writes (its port and home); a
        # restart fails when RESTART_FAILS is set; a sync stub fails when SYNC_FAILS is set.
        _stub(self.bin / "systemctl", 'echo "systemctl $*" >> "$CALLS"\n'
                                      'case " $* " in *" cat "*) [ -n "$UNIT_LOADED" ] || exit 1\n'
                                      '  printf \'# unit\\nExecStart="/v/python" -m uvicorn api.main:app'
                                      ' --host 127.0.0.1 --port %s\\nEnvironment="CICADA_HOME=%s"\\n\' '
                                      '"$UNIT_PORT" "$UNIT_HOME" ;;\n'
                                      '*" restart "*) [ -z "$RESTART_FAILS" ] || exit 1 ;;\n'
                                      '*" show "*) echo "MainPID=${BACKEND_PID:-0}" ;; esac\n'
                                      'exit 0\n')
        _stub(self.bin / "curl", '''
            echo "curl $*" >> "$CALLS"
            [ -n "$CURL_EXIT" ] && exit "$CURL_EXIT"
            if [ -n "$HTTP_500" ]; then
              case " $* " in *" -sf "*|*" -fs "*|*" -f "*) exit 22 ;; esac
              echo "internal error"; exit 0
            fi
            [ -f "$STATUS_FILE" ] || exit 7
            cat "$STATUS_FILE"
            ''')

    def write(self, rel: str, text: str) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def push_change(self, rel: str) -> str:
        """Commit a change to `rel` on origin/dev only (a second clone), leaving this checkout behind."""
        other = self.tmp / "other"
        if not other.exists():
            _git(self.tmp, "clone", "-q", "-b", "dev", str(self.origin), str(other))
        p = other / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("v2-" + rel)
        _git(other, "add", "-A")
        _git(other, "commit", "-q", "-m", f"change {rel}")
        _git(other, "push", "-q", "origin", "dev")
        return _git(other, "rev-parse", "HEAD")

    def sleep_status(self, **body) -> None:
        self.status_file.write_text(json.dumps({"status": "idle", "writing": False, **body}))
        (self.home / "api_token").write_text("tok\n")

    def run(self, **extra_env: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin:{os.environ['PATH']}",
               "CALLS": str(self.calls), "STATUS_FILE": str(self.status_file), "CICADA_HOME": str(self.home),
               "CICADA_PORT": "49177", "CURL_EXIT": self.curl_exit,
               "HTTP_500": "1" if self.http_500 else "", "UNAME_S": self.os_name,
               "UNIT_LOADED": "1" if self.unit_loaded else "", "UNIT_PORT": "49177",
               "UNIT_HOME": str(self.home), "FAKE_NOW": str(self.now), "BACKEND_PID": self.backend_pid,
               "PORT_TOOL": self.port_tool, "PRINT_OK_FIRST": self.print_ok_first,
               "PORT_HOLDERS": " ".join(self.holders if self.holders is not None
                                        else ([f"{self.backend_pid}:49177"] if self.backend_pid else [])),
               **extra_env}
        Path(f"{self.calls}.print").unlink(missing_ok=True)
        env.pop("CICADA_AUTOUPDATE_FORCE", None) if "CICADA_AUTOUPDATE_FORCE" not in extra_env else None
        for k in [k for k, v in env.items() if v is None]:   # run(CICADA_PORT=None) unsets it
            del env[k]
        return subprocess.run(["bash", str(self.repo / "scripts/dev/auto-update.sh")], cwd=self.repo, env=env,
                              capture_output=True, text=True, timeout=60)

    def called(self) -> str:
        return self.calls.read_text()

    def log(self) -> str:
        return (self.repo / "logs/auto-update.log").read_text()

    def head(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD")

    def stamp(self) -> str:
        return (self.repo / "logs/.auto-update-installed").read_text().strip()


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def _assert_deferred(rig: Rig) -> None:
    out = rig.run()
    assert out.returncode == 0, out.stderr
    assert "deferred: Sleep is running" in rig.log()
    assert rig.head() == rig.base, "the checkout must not move under a running Sleep"
    assert rig.stamp() == rig.base
    assert "kickstart" not in rig.called()
    assert "install_app" not in rig.called()


def test_busy_running_defers_everything(rig):
    rig.push_change("api/app.py")
    rig.sleep_status(status="running")
    _assert_deferred(rig)


def test_a_running_inbox_tidy_defers_everything(rig):
    # 2026-10-17: a restart 285 settles into a real tidy cut it short and lost its counts.
    rig.push_change("api/app.py")
    rig.sleep_status(inboxTidy=True)
    _assert_deferred(rig)


# The real route shape of a paused run (api/routers/sleep.py, test_sleep_paused.py): idle, not writing,
# an inactive unfinished drain (or none after a restart) and a top-level `paused` block.
PAUSED = {"runId": "sleep_pz", "reason": "engine", "engineKind": "needs_fix", "filed": 0, "frozen": 9,
          "canContinue": True}


def test_active_unfinished_drain_defers(rig):
    rig.push_change("api/app.py")
    rig.sleep_status(drain={"active": True, "finished": False})
    _assert_deferred(rig)


# 2026-10-17: a scheduled run paused on its engine at 03:00 and every tick until 15:09 logged "deferred". A paused
# run holds nothing in flight: its record is a sidecar a restart leaves alone (test_sleep_paused's
# test_a_paused_record_outlives_a_restart), so the update goes ahead under it.
@pytest.mark.parametrize("drain", [{"active": False, "finished": False}, None])
def test_a_paused_run_with_nothing_in_flight_does_not_hold_the_update(rig, drain):
    new = rig.push_change("api/app.py")
    rig.sleep_status(drain=drain, paused=PAUSED)
    assert rig.run().returncode == 0
    assert "deferred" not in (rig.log() if (rig.repo / "logs/auto-update.log").exists() else "")
    assert rig.head() == new
    assert "kickstart -k" in rig.called()


def test_a_paused_runs_upkeep_tail_still_defers(rig):
    """A paused run's upkeep tail (a scheduled tick's `tail_only`) reports status running: that is in flight."""
    rig.push_change("api/app.py")
    rig.sleep_status(status="running", drain={"active": False, "finished": False}, paused=PAUSED)
    _assert_deferred(rig)


@pytest.mark.parametrize("drain", [{"active": False, "finished": True}, {"active": False, "finished": False}, None])
def test_finished_or_failed_run_without_a_pause_is_eligible(rig, drain):
    new = rig.push_change("api/app.py")
    rig.sleep_status(drain=drain, paused=None)
    assert rig.run().returncode == 0
    assert rig.head() == new


def test_writing_defers(rig):
    rig.push_change("api/app.py")
    rig.sleep_status(writing=True)
    _assert_deferred(rig)


def test_finished_drain_is_not_busy(rig):
    new = rig.push_change("api/app.py")
    rig.sleep_status(drain={"active": True, "finished": True})
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert "kickstart" in rig.called()


def test_status_call_is_bounded_and_authenticated(rig):
    rig.sleep_status()
    rig.run()
    curl = [ln for ln in rig.called().splitlines() if ln.startswith("curl")][0]
    assert "-m 10" in curl and "127.0.0.1:49177/sleep/status" in curl and "Bearer tok" in curl


def test_idle_proceeds_and_restarts_for_api_runtime_change(rig):
    new = rig.push_change("api/app.py")
    rig.sleep_status()
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert "kickstart -k" in rig.called()
    assert "backend restarted" in rig.log()


def test_unreachable_backend_proceeds(rig):
    new = rig.push_change("api/app.py")
    (rig.home / "api_token").write_text("tok\n")   # a token, but no status file: the curl stub exits 7
    assert rig.run().returncode == 0
    assert "curl" in rig.called()
    assert rig.head() == new
    assert "kickstart -k" in rig.called()


def test_unparseable_status_defers(rig):
    rig.push_change("api/app.py")
    rig.status_file.write_text("<html>not json")
    (rig.home / "api_token").write_text("tok\n")
    _assert_deferred(rig)


def test_timeout_defers(rig):
    rig.push_change("api/app.py")
    (rig.home / "api_token").write_text("tok\n")
    rig.curl_exit = "28"   # a busy backend that did not answer in time
    _assert_deferred(rig)


def test_other_curl_failure_defers(rig):
    rig.push_change("api/app.py")
    (rig.home / "api_token").write_text("tok\n")
    rig.curl_exit = "56"
    _assert_deferred(rig)


def test_connection_refused_proceeds(rig):
    new = rig.push_change("api/app.py")
    (rig.home / "api_token").write_text("tok\n")
    rig.curl_exit = "7"
    assert rig.run().returncode == 0
    assert rig.head() == new


def test_http_500_defers(rig):
    rig.push_change("api/app.py")
    (rig.home / "api_token").write_text("tok\n")
    rig.http_500 = True
    _assert_deferred(rig)


def test_missing_token_file_proceeds_without_asking(rig):
    new = rig.push_change("api/app.py")
    rig.status_file.write_text(json.dumps({"status": "running"}))   # busy, but we cannot ask
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert "curl" not in rig.called()


def test_force_skips_the_check(rig):
    new = rig.push_change("api/app.py")
    rig.sleep_status(status="running")
    assert rig.run(CICADA_AUTOUPDATE_FORCE="1").returncode == 0
    assert rig.head() == new
    assert "kickstart -k" in rig.called()


@pytest.mark.parametrize("rel", ["api/tests/test_y.py", "benchmarks/b2.py", "docs/b.md"])
def test_non_runtime_merge_never_restarts_the_backend(rig, rel):
    new = rig.push_change(rel)
    rig.sleep_status()
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert "kickstart" not in rig.called()
    assert rig.stamp() == new


def test_mcp_change_restarts(rig):
    rig.push_change("mcp/server.py")
    rig.sleep_status()
    rig.run()
    assert "kickstart -k" in rig.called()


def test_dependency_file_change_restarts(rig):
    rig.push_change("api/uv.lock")
    rig.sleep_status()
    rig.run()
    assert "uv sync" in rig.called()
    assert "kickstart -k" in rig.called()


# --- Linux (a headless server, G181): the systemd user unit, no app -----------------------------------------------


@pytest.fixture
def linux(rig):
    rig.os_name = "Linux"
    return rig


def test_linux_restarts_the_systemd_unit_not_launchd(linux):
    new = linux.push_change("api/app.py")
    linux.sleep_status()
    assert linux.run().returncode == 0
    assert linux.head() == new
    called = linux.called()
    assert "systemctl --user restart cicada-backend.service" in called
    assert "launchctl" not in called
    assert "backend restarted" in linux.log()
    assert linux.stamp() == new


def test_linux_never_builds_the_app(linux):
    new = linux.push_change("app/CicadaApp/x.swift")
    linux.sleep_status()
    assert linux.run().returncode == 0
    assert "install_app" not in linux.called()
    assert "systemctl --user restart" not in linux.called()
    assert linux.stamp() == new
    assert "no app on Linux" in linux.log()


def test_linux_names_the_unit_from_the_environment(linux):
    linux.push_change("mcp/server.py")
    linux.sleep_status()
    linux.run(CICADA_BACKEND_UNIT="other.service")
    assert "systemctl --user restart other.service" in linux.called()


def test_linux_without_the_unit_restarts_nothing(linux):
    new = linux.push_change("api/app.py")
    linux.unit_loaded = False
    linux.sleep_status()
    assert linux.run().returncode == 0
    assert "restart" not in linux.called()
    assert linux.stamp() == new


def test_linux_server_venv_keeps_its_shape(linux):
    """A venv without sentence-transformers (install-server.sh's) re-syncs through sync-server-env.sh."""
    linux.push_change("api/uv.lock")
    linux.sleep_status()
    linux.run()
    assert "sync-server-env -q" in linux.called()
    assert "uv sync" not in linux.called()


def test_linux_full_venv_uses_uv_sync(linux):
    (linux.repo / "api/.venv/lib/python3.12/site-packages/sentence_transformers").mkdir(parents=True)
    linux.push_change("api/uv.lock")
    linux.sleep_status()
    linux.run()
    assert "uv sync -q" in linux.called()
    assert "sync-server-env" not in linux.called()


def test_linux_still_waits_out_sleep(linux):
    linux.push_change("api/app.py")
    linux.sleep_status(status="running")
    _assert_deferred(linux)
    assert "systemctl --user restart" not in linux.called()


def test_linux_non_runtime_merge_never_restarts(linux):
    new = linux.push_change("docs/b.md")
    linux.sleep_status()
    assert linux.run().returncode == 0
    assert "systemctl --user restart" not in linux.called()
    assert linux.stamp() == new


def _curl_line(rig: Rig) -> str:
    return [ln for ln in rig.called().splitlines() if ln.startswith("curl")][0]


def test_linux_asks_the_port_and_home_the_backend_unit_names(linux, tmp_path):
    """A server on another port must be asked on that port, or a running Sleep reads as 'nothing listening'."""
    other_home = tmp_path / "unit-home"
    other_home.mkdir()
    (other_home / "api_token").write_text("unit-tok\n")
    linux.sleep_status(status="running")
    linux.push_change("api/app.py")
    linux.run(CICADA_PORT=None, CICADA_HOME=None, UNIT_PORT="18123", UNIT_HOME=str(other_home))
    curl = _curl_line(linux)
    assert "127.0.0.1:18123/sleep/status" in curl and "Bearer unit-tok" in curl
    assert "deferred: Sleep is running" in linux.log()
    assert linux.head() == linux.base


def test_linux_environment_port_wins_over_the_unit(linux):
    linux.sleep_status()
    linux.run(UNIT_PORT="18123")
    assert "127.0.0.1:49177/sleep/status" in _curl_line(linux)


def test_a_mac_never_reads_a_unit(rig):
    rig.sleep_status()
    rig.run(CICADA_PORT=None)
    assert "systemctl" not in rig.called()
    assert "127.0.0.1:8000/sleep/status" in _curl_line(rig)


def test_linux_failed_sync_keeps_the_stamp_and_the_next_tick_retries(linux):
    new = linux.push_change("api/uv.lock")
    linux.sleep_status()
    out = linux.run(SYNC_FAILS="1")
    assert out.returncode == 1
    assert linux.head() == new, "the code still fast-forwards"
    assert linux.stamp() == linux.base
    assert "systemctl --user restart" not in linux.called(), "new code on old dependencies is not started"
    assert "fail: sync-server-env.sh" in linux.log() and "the next tick retries" in linux.log()
    assert linux.run().returncode == 0
    assert linux.called().count("sync-server-env -q") == 2
    assert "systemctl --user restart cicada-backend.service" in linux.called()
    assert linux.stamp() == new


def test_linux_failed_restart_keeps_the_stamp(linux):
    new = linux.push_change("api/app.py")
    linux.sleep_status()
    assert linux.run(RESTART_FAILS="1").returncode == 1
    assert linux.stamp() == linux.base
    assert "fail: restart cicada-backend.service" in linux.log()
    assert linux.run().returncode == 0
    assert linux.stamp() == new


# --- the installer: launchd on a Mac, a systemd user timer on Linux -----------------------------------------------


def _installer(tmp_path: Path, os_name: str, *args: str) -> tuple[subprocess.CompletedProcess, Path, Path]:
    repo = tmp_path / "repo"
    (repo / "scripts/dev").mkdir(parents=True, exist_ok=True)
    shutil.copy(INSTALLER, repo / "scripts/dev/install-auto-update.sh")
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    calls = tmp_path / "calls.log"
    for tool in ("systemctl", "launchctl"):
        _stub(bin_ / tool, f'echo "{tool} $*" >> "$CALLS"\nexit 0\n')
    _stub(bin_ / "uname", UNAME_STUB)
    _stub(bin_ / "uv", "exit 0\n")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    units = tmp_path / "units"
    env = {**os.environ, "PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(home), "CALLS": str(calls),
           "UNAME_S": os_name, "SYSTEMD_USER_DIR": str(units)}
    out = subprocess.run(["bash", str(repo / "scripts/dev/install-auto-update.sh"), *args], env=env,
                         capture_output=True, text=True, timeout=30)
    return out, units, calls


def test_installer_on_linux_writes_a_five_minute_persistent_user_timer(tmp_path):
    out, units, calls = _installer(tmp_path, "Linux")
    assert out.returncode == 0, out.stderr
    timer = (units / "cicada-dev-autoupdate.timer").read_text()
    service = (units / "cicada-dev-autoupdate.service").read_text()
    assert "OnCalendar=*:0/5" in timer and "Persistent=true" in timer and "WantedBy=timers.target" in timer
    repo = (tmp_path / "repo").resolve()
    assert "Type=oneshot" in service
    assert f"ExecStart=/bin/bash {repo}/scripts/dev/auto-update.sh" in service
    assert f"PATH={tmp_path / 'bin'}:/usr/local/bin" in service   # uv's folder is on the job's PATH
    log = calls.read_text()
    assert "systemctl --user enable --now cicada-dev-autoupdate.timer" in log
    assert "launchctl" not in log
    assert not (tmp_path / "home/Library").exists()


def test_installer_on_linux_uninstalls(tmp_path):
    _installer(tmp_path, "Linux")
    out, units, calls = _installer(tmp_path, "Linux", "--uninstall")
    assert out.returncode == 0, out.stderr
    assert not (units / "cicada-dev-autoupdate.timer").exists()
    assert not (units / "cicada-dev-autoupdate.service").exists()
    assert "systemctl --user disable --now cicada-dev-autoupdate.timer" in calls.read_text()


def test_installer_on_a_mac_keeps_the_launchd_job(tmp_path):
    out, units, calls = _installer(tmp_path, "Darwin")
    assert out.returncode == 0, out.stderr
    plist = (tmp_path / "home/Library/LaunchAgents/com.cicada.dev-autoupdate.plist").read_text()
    assert "<integer>300</integer>" in plist
    assert "launchctl bootstrap" in calls.read_text()
    assert "systemctl" not in calls.read_text()
    assert not units.exists()
    out, _, _ = _installer(tmp_path, "Darwin", "--uninstall")
    assert out.returncode == 0
    assert not (tmp_path / "home/Library/LaunchAgents/com.cicada.dev-autoupdate.plist").exists()


# --- a backend that answers NOTHING is frozen, not busy (2026-11-26) ---------------------------------------------
#
# A Sleep run spun on the event loop for about 100 minutes until a restart by hand; the frozen process refused or
# timed out every ask, and nothing would have restarted it. Silence is counted across ticks that really asked and got
# no HTTP response from the service's own process; the
# rig's clock (`rig.now`) and a recording `sleep` stand in for real time, and the signal goes to a real process.

MIN = 60
CLOCK_GAP_TICK = 5     # the timer's own interval, in minutes


def _silent(rig: Rig) -> Rig:
    """A backend that never answers: a token exists and every ask times out (curl exit 28)."""
    (rig.home / "api_token").write_text("tok\n")
    rig.curl_exit = "28"
    return rig


def _tick(rig: Rig, minutes: float = CLOCK_GAP_TICK, **env: str) -> subprocess.CompletedProcess:
    rig.now += int(minutes * MIN)
    return rig.run(**env)


def _tick_until(rig: Rig, minutes: int, step: int = CLOCK_GAP_TICK) -> None:
    for _ in range(minutes // step):
        assert _tick(rig, step).returncode == 0


def _log_lines(rig: Rig, needle: str) -> list[str]:
    path = rig.repo / "logs/auto-update.log"
    return [ln for ln in path.read_text().splitlines() if needle in ln] if path.exists() else []


def _restarts(rig: Rig) -> int:
    return rig.called().count("kickstart -k") + rig.called().count("systemctl --user restart")


class Listener:
    """A real process that records SIGUSR1, standing in for a backend (or a decoy scratch backend)."""

    def __init__(self, tmp: Path, name: str):
        self.got = tmp / f"{name}.sigusr1"
        code = ("import signal, sys, time\n"
                f"signal.signal(signal.SIGUSR1, lambda *a: open({str(self.got)!r}, 'a').write('x'))\n"
                "print('ready', flush=True)\n"
                "time.sleep(60)\n")
        self.proc = subprocess.Popen([os.sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        assert self.proc.stdout.readline().strip() == "ready"

    @property
    def pid(self) -> str:
        return str(self.proc.pid)

    def signalled(self, wait: float = 2.0) -> bool:
        import time
        end = time.time() + wait
        while time.time() < end:
            if self.got.exists():
                return True
            time.sleep(0.05)
        return False

    def never_signalled(self) -> bool:
        import time
        time.sleep(0.3)
        return not self.got.exists()


@pytest.fixture
def backends(tmp_path):
    made: list[Listener] = []

    def make(name: str) -> Listener:
        made.append(Listener(tmp_path, name))
        return made[-1]

    yield make
    for b in made:
        b.proc.kill()
        b.proc.wait()


def test_silence_shorter_than_the_limit_defers_and_restarts_nothing(rig, backends):
    rig.push_change("api/app.py")
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 25)          # ticks at 0, 5, ... 25 minutes of silence: still under the 30
    assert "deferred: Sleep is running" in rig.log()
    assert rig.head() == rig.base and rig.stamp() == rig.base
    assert _restarts(rig) == 0 and "install_app" not in rig.called()
    assert backend.never_signalled()
    assert (rig.repo / "logs/.auto-update-silent").exists()


@pytest.mark.parametrize("os_name", ["Darwin", "Linux"])
def test_silence_past_the_limit_signals_the_backends_own_pid_and_restarts_with_no_code_moved(rig, backends, os_name):
    rig.os_name = os_name
    backend, decoy = backends("backend"), backends("decoy")   # the decoy is a scratch backend: never signalled
    rig.backend_pid = backend.pid
    _silent(rig)
    _tick(rig, 0)                                  # first unanswered tick: minute 0
    _tick_until(rig, 25)                           # minute 25: still waiting
    assert _restarts(rig) == 0
    assert _tick(rig, 5).returncode == 0           # minute 30
    called = rig.called()
    assert backend.signalled(), "the backend's own pid gets SIGUSR1"
    assert decoy.never_signalled()
    restart = "systemctl --user restart cicada-backend.service" if os_name == "Linux" else "kickstart -k"
    assert called.count(restart) == 1
    assert called.index("sleep 2") < called.index(restart), "a couple of seconds for the dump, then the restart"
    assert rig.head() == rig.base, "no code moved"
    assert "launchctl" not in called if os_name == "Linux" else "systemctl" not in called
    assert not (rig.repo / "logs/.auto-update-silent").exists(), "the restart clears the silence record"
    assert len(_log_lines(rig, "backend restarted")) == 1
    assert "backend restarted: it had been silent for 30 minutes" in rig.log()


def test_the_pid_comes_from_the_service_manager_never_a_name(rig, backends):
    """With no pid reported there is no backend of ours to call frozen: nothing restarts, nobody is signalled."""
    decoy = backends("decoy")
    rig.backend_pid = ""
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 40)
    assert _restarts(rig) == 0
    assert decoy.never_signalled()
    assert not (rig.repo / "logs/.auto-update-silent").exists()


def test_silence_past_the_limit_also_updates_when_code_moved(rig, backends):
    new = rig.push_change("api/app.py")
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 30)
    assert rig.head() == new and rig.stamp() == new
    assert rig.called().count("kickstart -k") == 1, "one restart, not one for the freeze and one for the code"
    assert backend.signalled()
    assert "backend restarted: it had been silent for 30 minutes" in rig.log()


def test_an_app_change_still_builds_after_a_frozen_restart(rig, backends):
    rig.push_change("app/CicadaApp/x.swift")
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 30)
    assert "install_app" in rig.called()
    assert rig.called().count("kickstart -k") == 1, "the app change alone moves no backend code"


def test_linux_frozen_restart_follows_a_dependency_sync(linux, backends):
    new = linux.push_change("api/uv.lock")
    linux.backend_pid = backends("backend").pid
    _silent(linux)
    _tick(linux, 0)
    _tick_until(linux, 30)
    called = linux.called()
    assert called.index("sync-server-env -q") < called.index("systemctl --user restart"), "deps first, then the restart"
    assert called.count("systemctl --user restart") == 1
    assert linux.stamp() == new


@pytest.mark.parametrize("answer", ["running", "http_500", "nothing_listening", "unreadable", "other_curl_failure"])
def test_an_answered_tick_in_between_resets_the_stretch(rig, backends, answer):
    rig.push_change("api/app.py")
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 20)                           # 20 minutes of silence
    # one tick on which the backend answered (or nothing was listening): the stretch ends
    rig.curl_exit = ""
    rig.http_500 = answer == "http_500"
    if answer == "running":
        rig.sleep_status(status="running")
    elif answer == "unreadable":
        rig.status_file.write_text("<html>not json")
    elif answer == "nothing_listening":
        rig.curl_exit = "7"
        rig.holders = []                           # the pid holds no port: refused because nothing listens
    elif answer == "other_curl_failure":
        rig.curl_exit = "35"                       # not a silence-class failure (a TLS error)
    _tick(rig)
    assert not (rig.repo / "logs/.auto-update-silent").exists(), "the record is gone once the backend answers"
    rig.holders = None
    rig.curl_exit = "28"
    rig.http_500 = False
    rig.status_file.unlink(missing_ok=True)
    before = _restarts(rig)
    _tick_until(rig, 30)                           # first unanswered tick +5: 25 minutes of silence at +30
    assert _restarts(rig) == before
    _tick(rig, 5)                                  # 30 minutes of silence
    assert _restarts(rig) == before + 1


def test_a_long_gap_between_two_unanswered_ticks_is_not_silence(rig, backends):
    """One tick before an 8-hour lid-close and one after is not 8 hours (or any minutes) of silence."""
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 25)                           # 25 minutes of silence seen
    assert _tick(rig, 8 * 60).returncode == 0      # the Mac wakes: the backend still times out
    assert _restarts(rig) == 0
    assert "has not answered for 0 of 30 minutes" in rig.log().splitlines()[-1]
    _tick_until(rig, 25)
    assert _restarts(rig) == 0, "the stretch counts from the first tick after the gap"
    _tick(rig, 5)
    assert _restarts(rig) == 1


def test_a_gap_of_two_missed_ticks_still_counts_but_not_a_third(rig, backends):
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0)
    _tick(rig, 15)                                 # two ticks missed (15 minutes): still one stretch
    assert "has not answered for 15 of 30 minutes" in rig.log().splitlines()[-1]
    _tick(rig, 16)                                 # over the bound: a new stretch
    assert "has not answered for 0 of 30 minutes" in rig.log().splitlines()[-1]


def test_a_clock_that_went_backwards_starts_over(rig, backends):
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 20)
    rig.now -= 3600
    _tick(rig, 0)
    assert "has not answered for 0 of 30 minutes" in rig.log().splitlines()[-1]


def test_after_the_restart_a_backend_that_comes_back_frozen_waits_a_full_stretch(rig, backends):
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 30)
    assert _restarts(rig) == 1
    assert not (rig.repo / "logs/.auto-update-silent").exists()
    _tick_until(rig, 30)                           # no restart loop every 5 minutes: 25 minutes of fresh silence
    assert _restarts(rig) == 1
    _tick(rig, 5)                                  # 30 minutes since the first tick that followed the restart
    assert _restarts(rig) == 2


def test_a_running_answer_is_never_interrupted_however_long_the_run(rig, backends):
    new = rig.push_change("api/app.py")
    backend = backends("backend")
    rig.backend_pid = backend.pid
    rig.sleep_status(status="running")
    for _ in range(36):                            # six hours of ticks, every ten minutes
        assert _tick(rig, 10).returncode == 0
    assert _restarts(rig) == 0 and rig.head() == rig.base and rig.stamp() == rig.base
    assert backend.never_signalled()
    assert not (rig.repo / "logs/.auto-update-silent").exists()
    assert "silent for" not in rig.log()
    rig.sleep_status(status="idle")                # the run ends: the update goes through as before
    assert _tick(rig, 10).returncode == 0
    assert rig.head() == new


def test_a_single_timeout_still_defers(rig, backends):
    new = rig.push_change("api/app.py")
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _assert_deferred(rig)
    assert rig.head() != new and _restarts(rig) == 0


def test_force_is_unchanged_and_never_asks(rig, backends):
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _silent(rig)
    # nothing moved: a forced run restarts nothing (force skips the wait, it is not a restart switch)
    assert rig.run(CICADA_AUTOUPDATE_FORCE="1").returncode == 0
    assert _restarts(rig) == 0 and "curl" not in rig.called()
    new = rig.push_change("api/app.py")
    assert rig.run(CICADA_AUTOUPDATE_FORCE="1").returncode == 0
    assert rig.head() == new
    assert rig.called().count("kickstart -k") == 1
    assert "silent for" not in rig.log() and backend.never_signalled(), "force never calls a backend frozen"
    assert not (rig.repo / "logs/.auto-update-silent").exists()


def test_a_checkout_that_fails_a_guard_restarts_nothing(rig, backends):
    """Diverged from origin/dev: the update is skipped and a silent backend is left as it is (no restart, no signal)."""
    backend = backends("backend")
    rig.backend_pid = backend.pid
    rig.write("docs/local.md", "local")
    _git(rig.repo, "add", "-A")
    _git(rig.repo, "commit", "-q", "-m", "local only")
    rig.push_change("api/app.py")
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 30)
    assert "dev has diverged from origin/dev" in rig.log()
    assert _restarts(rig) == 0
    assert backend.never_signalled()


def test_tracked_changes_restart_nothing_and_never_ask(rig, backends):
    backend = backends("backend")
    rig.backend_pid = backend.pid
    rig.write("api/app.py", "edited by the person")
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 30)
    assert "skip: tracked changes on dev" in rig.log()
    assert _restarts(rig) == 0 and "curl" not in rig.called()
    assert backend.never_signalled()


def test_ticks_that_skipped_the_ask_do_not_bridge_the_silence(rig, backends):
    """A checkout with tracked changes asks nothing, so the silence on either side of it is not one stretch."""
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0)
    _tick_until(rig, 20)
    rig.write("api/app.py", "edited")
    _tick_until(rig, 20)                           # four ticks that never asked
    _git(rig.repo, "checkout", "-q", "--", "api/app.py")
    _tick(rig, 5)
    assert _restarts(rig) == 0
    assert "has not answered for 0 of 30 minutes" in rig.log().splitlines()[-1]


def test_linux_failed_frozen_restart_keeps_the_record_and_the_next_tick_retries(linux, backends):
    linux.backend_pid = backends("backend").pid
    _silent(linux)
    _tick(linux, 0)
    for _ in range(5):
        _tick(linux, 5)
    assert _tick(linux, 5, RESTART_FAILS="1").returncode == 1
    assert "fail: restart cicada-backend.service" in linux.log()
    assert (linux.repo / "logs/.auto-update-silent").exists(), "a restart that failed is not a restart done"
    _tick(linux, 5)
    assert "backend restarted: it had been silent for 35 minutes" in linux.log()
    assert not (linux.repo / "logs/.auto-update-silent").exists()


def test_linux_frozen_backend_with_no_unit_is_said_and_nothing_restarts(linux, backends):
    linux.backend_pid = backends("backend").pid
    linux.unit_loaded = False
    _silent(linux)
    _tick(linux, 0)
    _tick_until(linux, 30)
    assert "restart" not in linux.called()
    assert "is not loaded; nothing restarted" in linux.log()


def test_the_limit_is_one_environment_variable(rig, backends):
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0, CICADA_AUTOUPDATE_SILENT_MINUTES="10")
    _tick(rig, 5, CICADA_AUTOUPDATE_SILENT_MINUTES="10")
    assert _restarts(rig) == 0
    _tick(rig, 5, CICADA_AUTOUPDATE_SILENT_MINUTES="10")
    assert _restarts(rig) == 1
    assert "silent for 10 minutes" in rig.log()


@pytest.mark.parametrize("junk", ["", "0", "-5", "abc", "1.5"])
def test_an_unusable_limit_falls_back_to_thirty_minutes(rig, backends, junk):
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _tick(rig, 0, CICADA_AUTOUPDATE_SILENT_MINUTES=junk)
    _tick_until(rig, 25)
    assert _restarts(rig) == 0
    assert "of 30 minutes" in rig.log().splitlines()[-1]


# --- the 2026-11-26 incident as measured: a frozen backend REFUSES connections ------------------------------------
#
# Its accept queue was full, so every ask failed at once with "connection refused" (curl exit 7) while the process sat
# alive at 100% CPU, and the first round read exit 7 as "nothing is listening". Silence is now "the service's own pid
# holds the port we asked and the ask got no HTTP response", whatever the failure looked like.

def _refused(rig: Rig, code: str = "7") -> Rig:
    (rig.home / "api_token").write_text("tok\n")
    rig.curl_exit = code
    return rig


def _stretch(rig: Rig) -> Path:
    return rig.repo / "logs/.auto-update-silent"


@pytest.mark.parametrize("os_name", ["Darwin", "Linux"])
def test_a_refusing_backend_that_is_alive_and_holds_the_port_is_restarted_after_the_bound(rig, backends, os_name):
    rig.os_name = os_name
    rig.port_tool = "ss" if os_name == "Linux" else "lsof"
    backend, decoy = backends("backend"), backends("decoy")
    rig.backend_pid = backend.pid
    _refused(rig)
    _tick(rig, 0)
    _tick_until(rig, 25)
    assert _restarts(rig) == 0 and not backend.signalled(0.2)
    assert _tick(rig, 5).returncode == 0
    restart = "systemctl --user restart cicada-backend.service" if os_name == "Linux" else "kickstart -k"
    assert rig.called().count(restart) == 1
    assert backend.signalled() and decoy.never_signalled(), "SIGUSR1 goes to the pid the service manager reports"
    assert "backend restarted: it had been silent for 30 minutes" in rig.log()
    tool = "ss -H -ltnp sport = :49177" if os_name == "Linux" else f"lsof -nP -a -p {backend.pid} -iTCP:49177 -sTCP:LISTEN -t"
    assert tool in rig.called(), "the holder of the port named is asked about, not the default"
    assert not _stretch(rig).exists()


@pytest.mark.parametrize("code", ["52", "56"])
def test_an_empty_or_reset_reply_from_a_port_holder_is_silence_too(rig, backends, code):
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _refused(rig, code)
    _tick(rig, 0)
    _tick_until(rig, 30)
    assert _restarts(rig) == 1 and backend.signalled()


def test_linux_with_an_ss_that_shows_no_process_column_asks_lsof(linux, backends):
    linux.port_tool = "blind"
    backend = backends("backend")
    linux.backend_pid = backend.pid
    _refused(linux)
    _tick(linux, 0)
    _tick_until(linux, 30)
    assert _restarts(linux) == 1
    assert "ss -H -ltnp" in linux.called() and "lsof -nP -a -p" in linux.called()


@pytest.mark.parametrize("why", ["no_pid", "pid_holds_nothing", "pid_holds_another_port"])
@pytest.mark.parametrize("code", ["7", "28"])
def test_a_pid_that_does_not_hold_the_port_asked_is_never_silence(rig, backends, why, code):
    """Down, still starting, or on another port than the one asked: nothing accumulates, nothing restarts."""
    decoy = backends("decoy")
    if why != "no_pid":
        rig.backend_pid = decoy.pid
        rig.holders = [] if why == "pid_holds_nothing" else [f"{decoy.pid}:50000"]
    _refused(rig, code)
    _tick(rig, 0)
    assert not _stretch(rig).exists()
    _tick_until(rig, 90)                      # three bounds' worth of ticks
    assert _restarts(rig) == 0 and decoy.never_signalled()
    assert not _stretch(rig).exists(), "a stretch is never started for a process that is not holding our port"


@pytest.mark.parametrize("why", ["no_pid", "pid_holds_nothing"])
@pytest.mark.parametrize("code", ["28", "52", "56"])
def test_a_non_refusal_failure_with_no_holder_of_ours_defers_and_never_updates(rig, backends, why, code):
    """Something is listening and not answering, and it is not our service: only a refusal is "down"."""
    new = rig.push_change("api/app.py")
    if why == "pid_holds_nothing":
        rig.backend_pid = backends("decoy").pid
        rig.holders = []
    _refused(rig, code)
    for _ in range(3):
        assert _tick(rig, 5).returncode == 0
    assert f"an ask failed (curl {code}), but no backend process of ours holds port 49177" in rig.log()
    assert "deferred: Sleep is running" in rig.log()
    assert rig.head() == rig.base and rig.head() != new and rig.stamp() == rig.base
    assert _restarts(rig) == 0 and not _stretch(rig).exists()


def test_a_refusal_with_no_listener_is_nothing_listening_and_updates_as_before(rig):
    new = rig.push_change("api/app.py")
    _refused(rig)                              # no pid at all
    assert rig.run().returncode == 0
    assert rig.head() == new and "kickstart -k" in rig.called()
    assert "deferred" not in (rig.log() if (rig.repo / "logs/auto-update.log").exists() else "")


def test_a_refusing_backend_that_is_alive_defers_and_moves_no_code_under_the_bound(rig, backends):
    """Nothing is fast-forwarded under a process that may be running; at the bound code and restart go together."""
    new = rig.push_change("api/app.py")
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _refused(rig)
    _tick(rig, 0)
    _tick_until(rig, 25)
    assert rig.head() == rig.base and rig.stamp() == rig.base
    assert _restarts(rig) == 0 and "install_app" not in rig.called()
    assert "deferred: Sleep is running (the backend has not answered for 25 of 30 minutes)" in rig.log()
    _tick(rig, 5)
    assert rig.head() == new and rig.stamp() == new
    assert rig.called().count("kickstart -k") == 1 and backend.signalled()


def test_a_backend_that_changes_pid_starts_a_new_stretch(rig, backends):
    first, second = backends("first"), backends("second")
    rig.backend_pid = first.pid
    _refused(rig)
    _tick(rig, 0)
    _tick_until(rig, 25)
    rig.backend_pid = second.pid               # someone restarted it: the new process has not been silent for 25 minutes
    _tick(rig, 5)
    assert _restarts(rig) == 0
    assert "has not answered for 0 of 30 minutes" in rig.log().splitlines()[-1]
    assert second.never_signalled() and first.never_signalled()


# Without a tool that can tell, a refusal is NOT silence (the older reading holds) and the log says so once.
def test_no_port_tool_falls_back_to_the_older_reading_and_says_so_once(rig, backends):
    rig.port_tool = "none"
    new = rig.push_change("api/app.py")
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _refused(rig)                              # a refusal: nothing is listening, as before
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert _log_lines(rig, "cannot tell which process holds port")
    rig.curl_exit = "28"                       # a timeout is silence, as before
    rig.now += 5 * MIN
    assert rig.run().returncode == 0
    for _ in range(6):
        _tick(rig, 5)
    assert len(_log_lines(rig, "cannot tell which process holds port")) == 1
    assert _restarts(rig) == 2 and backend.signalled()      # one for the code, one for the freeze
    assert "no refusal" not in rig.log()


# --- a consolidation that is making progress is never restarted (the run record) ----------------------------------

def _run_record(rig: Rig, phase: str, age_minutes: float, at: int | None = None, bank: str = "main-ab12cd") -> Path:
    d = rig.home / "sleep" / bank
    d.mkdir(parents=True, exist_ok=True)
    f = d / "run.json"
    f.write_text(json.dumps({"run_id": "sleep_x", "phase": phase, "filed": 3}))
    stamp = (rig.now if at is None else at) - int(age_minutes * MIN)
    os.utime(f, (stamp, stamp))
    return f


def _frozen_until_the_last_tick(rig: Rig, code: str = "28") -> None:
    _refused(rig, code)
    _tick(rig, 0)
    _tick_until(rig, 25)


def test_a_running_record_written_inside_the_stretch_blocks_the_restart(rig, backends):
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _frozen_until_the_last_tick(rig, "7")
    _run_record(rig, "running", 10, at=rig.now + 5 * MIN)          # written 10 minutes before the tick that reaches the bound
    assert _tick(rig, 5).returncode == 0
    assert _restarts(rig) == 0 and backend.never_signalled()
    assert "a run record was written 10 minutes ago: not restarted" in rig.log()
    assert rig.head() == rig.base and _stretch(rig).exists(), "it keeps counting: the next stale tick restarts"
    assert _tick(rig, 5).returncode == 0                           # that record is now 15 minutes old: still inside
    assert _restarts(rig) == 0
    for _ in range(3):
        _tick(rig, 5)                                              # 30 minutes old by now: it protects nothing
    assert _restarts(rig) == 1 and backend.signalled()


def test_a_record_hours_old_does_not_protect_a_frozen_backend(rig, backends):
    """2026-11-26: the run was stuck mid-batch, so its record was hours old."""
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _frozen_until_the_last_tick(rig)
    _run_record(rig, "running", 6 * 60, at=rig.now + 5 * MIN)
    _tick(rig, 5)
    assert _restarts(rig) == 1 and backend.signalled()


def test_a_record_just_older_than_the_bound_does_not_protect(rig, backends):
    rig.backend_pid = backends("backend").pid
    _frozen_until_the_last_tick(rig)
    _run_record(rig, "running", 31, at=rig.now + 5 * MIN)
    _tick(rig, 5)
    assert _restarts(rig) == 1


@pytest.mark.parametrize("phase", ["paused", "idle", "done", ""])
def test_a_record_whose_phase_is_not_running_does_not_protect(rig, backends, phase):
    rig.backend_pid = backends("backend").pid
    _frozen_until_the_last_tick(rig)
    _run_record(rig, phase, 1, at=rig.now + 5 * MIN)
    _tick(rig, 5)
    assert _restarts(rig) == 1


def test_any_banks_running_record_counts_and_an_unreadable_one_does_not(rig, backends):
    rig.backend_pid = backends("backend").pid
    _frozen_until_the_last_tick(rig)
    _run_record(rig, "paused", 1, at=rig.now + 5 * MIN, bank="a-111111")
    junk = rig.home / "sleep/b-222222"
    junk.mkdir(parents=True)
    (junk / "run.json").write_text("{not json")
    _run_record(rig, "running", 2, at=rig.now + 5 * MIN, bank="c-333333")
    _tick(rig, 5)
    assert _restarts(rig) == 0
    rig.home.joinpath("sleep/c-333333/run.json").unlink()
    _tick(rig, 5)
    assert _restarts(rig) == 1


def _frozen_with_unreadable_records(rig: Rig, backends) -> Listener:
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _frozen_until_the_last_tick(rig)
    return backend


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
def test_a_run_record_that_cannot_be_opened_defers_and_never_restarts(rig, backends):
    """A failed read is not "no record protects": a consolidation making progress must not be cut on a guess."""
    backend = _frozen_with_unreadable_records(rig, backends)
    f = _run_record(rig, "running", 1, at=rig.now + 5 * MIN)
    f.parent.chmod(0o000)
    try:
        assert _tick(rig, 5).returncode == 0
        assert _restarts(rig) == 0 and backend.never_signalled()
        assert "the run records could not be read: not restarted" in rig.log()
        assert rig.head() == rig.base and _stretch(rig).exists()
    finally:
        f.parent.chmod(0o755)
    _tick(rig, 5)                                  # readable again: that record is only 6 minutes old, so it protects
    assert _restarts(rig) == 0
    os.utime(f, (rig.now - 40 * MIN, rig.now - 40 * MIN))
    _tick(rig, 5)
    assert _restarts(rig) == 1 and backend.signalled()


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
def test_an_unreadable_sleep_folder_defers_too(rig, backends):
    backend = _frozen_with_unreadable_records(rig, backends)
    _run_record(rig, "running", 1, at=rig.now + 5 * MIN)
    sleep_dir = rig.home / "sleep"
    sleep_dir.chmod(0o000)
    try:
        assert _tick(rig, 5).returncode == 0
        assert _restarts(rig) == 0 and backend.never_signalled()
        assert "the run records could not be read" in rig.log()
    finally:
        sleep_dir.chmod(0o755)


def test_a_missing_interpreter_for_the_record_reader_defers(rig, backends):
    backend = _frozen_with_unreadable_records(rig, backends)
    _run_record(rig, "running", 1, at=rig.now + 5 * MIN)
    script = rig.repo / "scripts/dev/auto-update.sh"
    script.write_text(script.read_text().replace("/usr/bin/python3 -c '\nimport json, os, sys", "/nonexistent/python3 -c '\nimport json, os, sys"))
    assert "/nonexistent/python3" in script.read_text()
    _git(rig.repo, "update-index", "--assume-unchanged", "scripts/dev/auto-update.sh")   # the guard reads tracked changes
    assert _tick(rig, 5).returncode == 0
    assert _restarts(rig) == 0 and backend.never_signalled()
    assert "the run records could not be read: not restarted" in rig.log()


def test_no_sleep_folder_at_all_is_no_record_and_does_not_protect(rig, backends):
    backend = _frozen_with_unreadable_records(rig, backends)
    assert not (rig.home / "sleep").exists()
    _tick(rig, 5)
    assert _restarts(rig) == 1 and backend.signalled()


def test_the_record_is_read_from_the_linux_units_home(linux, backends, tmp_path):
    unit_home = tmp_path / "unit-home"
    unit_home.mkdir()
    (unit_home / "api_token").write_text("tok\n")
    linux.port_tool = "ss"
    linux.backend_pid = backends("backend").pid
    linux.curl_exit = "7"
    env = dict(CICADA_PORT=None, CICADA_HOME=None, UNIT_PORT="49177", UNIT_HOME=str(unit_home))
    linux.holders = None
    linux.now += 0
    for _ in range(6):
        linux.now += 5 * MIN
        assert linux.run(**env).returncode == 0
    d = unit_home / "sleep/main-ab12cd"
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"phase": "running"}))
    os.utime(d / "run.json", (linux.now + 5 * MIN - 60, linux.now + 5 * MIN - 60))
    linux.now += 5 * MIN
    assert linux.run(**env).returncode == 0
    assert _restarts(linux) == 0, "the unit's own home holds the record, not the environment's default"


# --- small things from review -------------------------------------------------------------------------------------

def test_the_first_unanswered_tick_prints_nothing_to_stderr(rig, backends):
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    out = rig.run()
    assert out.returncode == 0
    assert out.stderr == "", out.stderr       # bash 3.2 printed "No such file or directory" for the missing state file


@pytest.mark.parametrize("asked, used", [("3", 10), ("9", 10), ("1", 10), ("10", 10), ("12", 12), ("030", 30), ("08", 10)])
def test_the_bound_has_a_floor_of_ten_minutes_and_is_read_as_decimal(rig, backends, asked, used):
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    out = _tick(rig, 0, CICADA_AUTOUPDATE_SILENT_MINUTES=asked)
    assert out.stderr == ""
    assert f"of {used} minutes" in rig.log().splitlines()[-1]
    while (rig.now - int(_stretch(rig).read_text().split()[0])) // MIN < used - 5:
        _tick(rig, 5, CICADA_AUTOUPDATE_SILENT_MINUTES=asked)
    assert _restarts(rig) == 0
    _tick(rig, 5, CICADA_AUTOUPDATE_SILENT_MINUTES=asked)
    assert _restarts(rig) == 1 or used % 5 != 0


def test_a_state_file_with_leading_zeros_is_decimal_not_octal(rig, backends):
    """01800000000 is not valid octal, and 0100 would be 64: neither may be read that way."""
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _silent(rig)
    first = rig.now - 600
    _stretch(rig).write_text(f"0{first} 0{rig.now} {backend.pid}\n")
    out = _tick(rig, 5)
    assert out.stderr == "", out.stderr
    assert "has not answered for 15 of 30 minutes" in rig.log().splitlines()[-1]
    assert _stretch(rig).read_text().split()[0] == str(first)


@pytest.mark.parametrize("junk", ["", "abc", "1 2", "1800000000", "x 1800000000 5", "9999999999999999 9999999999999999 1"])
def test_a_damaged_state_file_starts_a_new_stretch(rig, backends, junk):
    rig.backend_pid = backends("backend").pid
    _silent(rig)
    _stretch(rig).write_text(junk + "\n")
    out = _tick(rig, 5)
    assert out.returncode == 0
    assert "has not answered for 0 of 30 minutes" in rig.log().splitlines()[-1]


def test_a_failed_fetch_while_frozen_still_restarts_the_backend(rig, backends):
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _refused(rig)
    _tick(rig, 0)
    _tick_until(rig, 25)
    _git(rig.repo, "remote", "set-url", "origin", str(rig.tmp / "gone.git"))
    assert _tick(rig, 5).returncode == 0
    assert "skip: fetch failed" in rig.log()
    assert rig.called().count("kickstart -k") == 1 and backend.signalled()
    assert "backend restarted: it had been silent for 30 minutes" in rig.log()
    assert not _stretch(rig).exists()


def test_a_failed_fetch_while_only_under_the_bound_restarts_nothing(rig, backends):
    backend = backends("backend")
    rig.backend_pid = backend.pid
    _refused(rig)
    _git(rig.repo, "remote", "set-url", "origin", str(rig.tmp / "gone.git"))
    _tick(rig, 0)
    _tick_until(rig, 20)
    assert _restarts(rig) == 0 and backend.never_signalled()


def test_the_mac_service_not_loaded_while_frozen_is_said_and_the_next_tick_retries(rig, backends):
    """The pid was found, then the job went away before the restart: say so, restart nothing, keep the stretch."""
    backend = backends("backend")
    rig.backend_pid = backend.pid
    rig.print_ok_first = "1"                   # the pid lookup works; the restart's "is it loaded" check does not
    _refused(rig)
    _tick(rig, 0)
    _tick_until(rig, 25)
    assert _tick(rig, 5).returncode == 0
    assert "com.cicada.backend is not loaded; nothing restarted" in rig.log()
    assert "kickstart" not in rig.called() and backend.never_signalled()
    assert _stretch(rig).exists(), "nothing was restarted, so the stretch stands"
    rig.print_ok_first = ""                    # loaded again: the very next tick restarts
    _tick(rig, 5)
    assert rig.called().count("kickstart -k") == 1 and backend.signalled()
