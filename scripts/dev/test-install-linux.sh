#!/usr/bin/env bash
#
# End-to-end test of the one-line Linux server install (scripts/install-server.sh, G181) in Docker, on real systemd.
#
#   scripts/dev/test-install-linux.sh [ubuntu|fedora ...]      (default: ubuntu fedora)
#
# For each distro it builds a throwaway image with systemd as PID 1 and a plain user, serves THIS checkout's
# committed HEAD from a local bare repo (tagged as a newer release than any real one), and, as that user:
#   1. runs the curl line with no uv: it must name uv and the fix, and install nothing;
#   2. installs uv the way the message says, then runs the curl line: the unit is active, /healthz answers on
#      127.0.0.1 only, the `cicada` command works, the token file exists 0600 and its value was never printed;
#   3. runs it again: the backend keeps its PID (a no-op);
#   4. publishes a newer tag and runs it again: the code moves and the backend restarts on it;
#   5. --uninstall: unit, hooks, command and code are gone; the memory folder and ~/.cicada stay.
# Lingering is turned on by the harness as root (the installer never does). GitHub is never asked for the code;
# PyPI, the uv installer and the search model's host are. Every container and image it creates is removed on exit.
# Commit first: the bare repo is cloned from HEAD, not the working tree.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DISTROS=("$@")
[ "${#DISTROS[@]}" -gt 0 ] || DISTROS=(ubuntu fedora)
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cicada-install-linux.XXXXXX")"
CACHE="${CICADA_TEST_CACHE:-$WORK/cache}"   # uv's and the model's downloads, shared by the distros
mkdir -p "$CACHE"
chmod 777 "$CACHE"
CREATED=()

cleanup() {
  for c in "${CREATED[@]+"${CREATED[@]}"}"; do
    docker rm -f "cicada-it-$c" >/dev/null 2>&1 || true
    docker rmi -f "cicada-it-$c:test" >/dev/null 2>&1 || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

# --- the code, served from a local bare repo -----------------------------------------------------------------------
git clone -q --bare --no-local --no-tags "$REPO" "$WORK/cicada.git"
git -C "$WORK/cicada.git" tag v90.0.0 HEAD                 # "the latest release" for this run only; never pushed
# The next release, for the update step: one more commit on top, tagged higher.
git clone -q "$WORK/cicada.git" "$WORK/next"
git -C "$WORK/next" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "the next release"
git -C "$WORK/next" push -q origin HEAD:refs/heads/next-release
cp "$REPO/scripts/install-server.sh" "$WORK/install-server.sh"

# --- the checks, run inside the container as the user -------------------------------------------------------------
cat > "$WORK/checks.sh" <<'CHECKS'
#!/bin/bash
# As alice-example, with a systemd user session.
set -uo pipefail
export XDG_RUNTIME_DIR="/run/user/$(id -u)" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
export CICADA_GIT_URL=/srv/cicada.git UV_CACHE_DIR=/cache/uv CICADA_RELEASE_CACHE=/cache/model
export PATH="/usr/local/bin:/usr/bin:/bin"
fail() { echo "FAIL: $*"; exit 1; }
pass() { echo "PASS: $*"; }
line() { curl -fsSL file:///srv/install-server.sh | bash -s -- "$@"; }
pid() { systemctl --user show -p MainPID --value cicada-backend.service; }

# 1. no uv: named with its fix, nothing installed
out="$(line 2>&1)"; rc=$?
[ $rc -eq 2 ] || fail "without uv the installer should exit 2, got $rc"
grep -q "uv is missing — install it with: curl -LsSf https://astral.sh/uv/install.sh | sh" <<<"$out" || fail "uv's fix not named: $out"
[ ! -e ~/.local/share/cicada ] || fail "something was installed without uv"
pass "a missing prerequisite is named with its fix and nothing is installed"

# 2. install uv the way the message says, then the one line
curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || fail "uv's installer"
start=$(date +%s)
line > ~/install1.log 2>&1 || { tail -40 ~/install1.log; fail "first install"; }
echo "first install took $(( $(date +%s) - start )) s"
grep -q "Latest release: v90.0.0" ~/install1.log || fail "did not pick the latest release tag"
systemctl --user is-active --quiet cicada-backend.service || fail "unit not active"
curl -fsS http://127.0.0.1:8000/healthz | grep -q '"status"' || fail "/healthz"
# Every listening socket on port 8000 (0x1F40), from the kernel's own tables: only 127.0.0.1 (0100007F) may appear.
listen="$(awk '$4 == "0A" && $2 ~ /:1F40$/ {print $2}' /proc/net/tcp /proc/net/tcp6 | sort -u | tr '\n' ' ')"
[ "$listen" = "0100007F:1F40 " ] || fail "port 8000 listens on '$listen', not 127.0.0.1 only"
~/.local/bin/cicada status > ~/status.txt 2>&1 || { cat ~/status.txt; fail "cicada status"; }
token=~/.cicada/api_token
[ -f "$token" ] || fail "no backend token"
[ "$(stat -c %a "$token")" = "600" ] || fail "token mode $(stat -c %a "$token")"
grep -qF -e "$(cat "$token")" ~/install1.log ~/status.txt && fail "the token value was printed"
grep -q "api_token" ~/install1.log || fail "the install did not say where the token lives"
[ -d ~/cicada/memory/.git ] || fail "memory folder is not a git repo"
python_pkgs="$(ls ~/.local/share/cicada/api/.venv/lib/python3.12/site-packages)"
grep -qi '^torch$' <<<"$python_pkgs" && fail "torch was installed"
echo "venv: $(du -sh ~/.local/share/cicada/api/.venv | cut -f1)"
loginctl show-user "$(id -un)" -p Linger | grep -q yes || fail "harness lingering missing"
pass "installed: unit active, loopback only, CLI works, token 0600 and never printed, no torch"

# 3. again, same ref: a no-op
p1="$(pid)"
line > ~/install2.log 2>&1 || { tail -40 ~/install2.log; fail "re-run"; }
[ "$(pid)" = "$p1" ] || fail "re-run restarted the backend"
grep -q "skipping the service install" ~/install2.log || fail "re-run did not skip the service"
pass "re-run is a no-op (backend PID $p1 kept)"

# 4. a newer release: the code moves, the backend restarts on it
git -C /srv/cicada.git tag v90.0.1 next-release
line > ~/install3.log 2>&1 || { tail -40 ~/install3.log; fail "update"; }
[ "$(git -C ~/.local/share/cicada rev-parse HEAD)" = "$(git -C /srv/cicada.git rev-parse v90.0.1)" ] || fail "code did not move"
for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1 && break; sleep 1; done
[ "$(pid)" != "$p1" ] || fail "update did not restart the backend"
pass "update to v90.0.1 restarted the backend on the new code"

# 4b. a branch for testers
CICADA_REF=next-release line > ~/install4.log 2>&1 || { tail -40 ~/install4.log; fail "CICADA_REF=branch"; }
pass "CICADA_REF names a branch"

# 5. uninstall: everything but the memory and ~/.cicada
line --uninstall > ~/uninstall.log 2>&1 || { cat ~/uninstall.log; fail "uninstall"; }
systemctl --user is-active --quiet cicada-backend.service && fail "unit still active"
[ ! -e ~/.config/systemd/user/cicada-backend.service ] || fail "unit file left"
[ ! -e ~/.local/share/cicada ] || fail "code left"
[ ! -L ~/.local/bin/cicada ] || fail "command left"
grep -q "capture.py\|recall.py" ~/.claude/settings.json 2>/dev/null && fail "hooks left"
[ -d ~/cicada/memory/.git ] || fail "memory removed"
[ -f ~/.cicada/api_token ] || fail "~/.cicada removed"
curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1 && fail "backend still answering"
pass "uninstall removed service, hooks, command and code; kept the memory and ~/.cicada"
mkdir -p "/cache/logs/$(. /etc/os-release; echo "$ID")" && cp ~/install*.log ~/uninstall.log "/cache/logs/$(. /etc/os-release; echo "$ID")/"
echo "ALL PASSED"
CHECKS
chmod 755 "$WORK/checks.sh"

dockerfile() {
  case "$1" in
    ubuntu) cat <<'DF'
FROM ubuntu:24.04
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq systemd systemd-sysv dbus dbus-user-session git curl ca-certificates >/dev/null && apt-get clean && rm -rf /var/lib/apt/lists/*
DF
    ;;
    fedora) cat <<'DF'
FROM fedora:41
RUN dnf -y -q install systemd git-core curl ca-certificates procps-ng >/dev/null && dnf clean all
DF
    ;;
    *) echo "unknown distro $1" >&2; exit 2 ;;
  esac
  cat <<'DF'
RUN useradd -m -s /bin/bash alice-example
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
DF
}

status=0
for d in "${DISTROS[@]}"; do
  echo "=== $d ==="
  CREATED+=("$d")
  dockerfile "$d" | docker build -q -t "cicada-it-$d:test" - >/dev/null
  # Each distro gets its own copy of the served repo: step 4 adds a tag to it.
  rm -rf "$WORK/srv-$d"; mkdir -p "$WORK/srv-$d"
  cp -R "$WORK/cicada.git" "$WORK/srv-$d/cicada.git"
  cp "$WORK/install-server.sh" "$WORK/checks.sh" "$WORK/srv-$d/"
  chmod -R a+rwX "$WORK/srv-$d"
  docker run -d --name "cicada-it-$d" --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --tmpfs /run --tmpfs /run/lock -v "$WORK/srv-$d:/srv" -v "$CACHE:/cache" "cicada-it-$d:test" >/dev/null
  for _ in $(seq 1 30); do
    docker exec "cicada-it-$d" systemctl is-system-running 2>/dev/null | grep -qE 'running|degraded' && break
    sleep 1
  done
  docker exec "cicada-it-$d" loginctl enable-linger alice-example
  uid="$(docker exec "cicada-it-$d" id -u alice-example)"
  for _ in $(seq 1 20); do
    docker exec "cicada-it-$d" test -S "/run/user/$uid/bus" && break
    sleep 1
  done
  docker exec "cicada-it-$d" git config --system --add safe.directory '*'
  if docker exec -u alice-example -w /home/alice-example "cicada-it-$d" /srv/checks.sh; then
    echo "=== $d: passed ==="
  else
    echo "=== $d: FAILED ==="
    docker exec -u alice-example "cicada-it-$d" bash -c 'tail -30 ~/.local/share/cicada/logs/backend.err.log 2>/dev/null' || true
    status=1
  fi
done
exit "$status"
