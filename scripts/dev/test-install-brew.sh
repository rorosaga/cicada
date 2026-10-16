#!/usr/bin/env bash
#
# End-to-end test of the Homebrew formula (Formula/cicada.rb, G181) on Linuxbrew, in Docker, with real systemd.
#
#   scripts/dev/test-install-brew.sh
#
# The image is homebrew/brew plus systemd as PID 1. This checkout's committed HEAD is served from a local bare repo
# and tapped the way a person taps the real one (`brew tap rorosaga/cicada <url>`), then, as the linuxbrew user:
#   1. `brew style` and `brew audit --new --strict` on the formula exactly as committed;
#   2. the tap's formula is pointed at the local repo (url and head only; a test tag at HEAD stands in for the
#      release) and `brew install` builds it; `brew test` passes; `brew services` has no service to offer;
#   3. `cicada-setup`: memory folder, hooks and the systemd unit, all naming Homebrew's opt path (never the Cellar);
#      /healthz answers on loopback; `cicada status` works; api/.env is the one in $(brew --prefix)/etc/cicada;
#   4. a newer tag, `brew upgrade cicada`, `cicada-setup` again: the backend restarts on the new keg and the
#      settings file survived the upgrade;
#   5. `cicada-setup --uninstall` and `brew uninstall cicada`: unit and hooks gone, the memory stays.
# Lingering is turned on by the harness as root. GitHub is never asked for the code; Homebrew's bottles, PyPI and
# the search model's host are. The container and image it creates are removed on exit (the base image stays
# pulled unless CICADA_TEST_RMI_BASE=1).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cicada-install-brew.XXXXXX")"
NAME="cicada-it-brew"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rmi -f "$NAME:test" >/dev/null 2>&1 || true
  [ "${CICADA_TEST_RMI_BASE:-0}" = 1 ] && docker rmi homebrew/brew:latest >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

git clone -q --bare --no-local --no-tags "$REPO" "$WORK/srv/cicada.git"
BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
TAG_NOW="$(sed -n 's/^ *url "[^"]*", tag: "\(v[^"]*\)"/\1/p' "$REPO/Formula/cicada.rb")"
git -C "$WORK/srv/cicada.git" tag "$TAG_NOW" HEAD          # stands in for the release the formula names
git clone -q "$WORK/srv/cicada.git" "$WORK/next"
git -C "$WORK/next" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "the next release"
git -C "$WORK/next" push -q origin HEAD:refs/heads/next-release
chmod -R a+rwX "$WORK/srv"

cat > "$WORK/srv/checks.sh" <<CHECKS
#!/bin/bash
set -uo pipefail
TAG_NOW="$TAG_NOW"
BRANCH="$BRANCH"
CHECKS
cat >> "$WORK/srv/checks.sh" <<'CHECKS'
export XDG_RUNTIME_DIR="/run/user/$(id -u)" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_ENV_HINTS=1 HOMEBREW_NO_INSTALL_CLEANUP=1
export PATH="/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:/usr/local/bin:/usr/bin:/bin"
cd ~
fail() { echo "FAIL: $*"; exit 1; }
pass() { echo "PASS: $*"; }
pid() { systemctl --user show -p MainPID --value cicada-backend.service; }
healthy() { for _ in $(seq 1 60); do curl -fsS http://127.0.0.1:8000/healthz 2>/dev/null | grep -q '"status"' && return 0; sleep 1; done; return 1; }

brew update --quiet >/dev/null 2>&1 || fail "brew update"    # the image's Homebrew can be older than its bottles
brew tap rorosaga/cicada /srv/cicada.git >/dev/null 2>&1 || fail "brew tap"
TAP="$(brew --repo rorosaga/cicada)"
git -C "$TAP" checkout -q "$BRANCH" 2>/dev/null || true

# 1. style and audit, on the formula as committed
brew style rorosaga/cicada/cicada || fail "brew style"
brew audit --new --strict rorosaga/cicada/cicada || fail "brew audit --new --strict"
pass "brew style and brew audit --new --strict"

# 2. point the tap at the local repo (url and head only) and install
F="$TAP/Formula/cicada.rb"
sed -i -e 's#url "https://github.com/rorosaga/cicada.git"#url "file:///srv/cicada.git", using: :git#' \
       -e 's#head "https://github.com/rorosaga/cicada.git", branch: "dev"#head "file:///srv/cicada.git", using: :git, branch: "next-release"#' "$F"
grep -q 'file:///srv/cicada.git' "$F" || fail "could not point the formula at the local repo"
start=$(date +%s)
brew install rorosaga/cicada/cicada > ~/brew-install.log 2>&1 || { tail -60 ~/brew-install.log; fail "brew install"; }
echo "brew install took $(( $(date +%s) - start )) s; keg: $(du -sh "$(brew --prefix cicada)/" | cut -f1)"
brew test rorosaga/cicada/cicada || fail "brew test"
command -v cicada >/dev/null && command -v cicada-setup >/dev/null || fail "commands not linked"
# A formula with a `service do` block gets homebrew.cicada.service / homebrew.mxcl.cicada.plist in its keg.
ls "$(brew --prefix cicada)"/homebrew.* >/dev/null 2>&1 && fail "the keg carries a brew service file"
brew services list 2>/dev/null | grep -q '^cicada ' && fail "brew services lists cicada"
OPT="$(brew --prefix)/opt/cicada/libexec"
ls "$OPT/api/.venv/lib/python3.12/site-packages" | grep -qi '^torch$' && fail "torch was installed"
pass "brew install, brew test; no brew service; no torch"

# 3. cicada-setup
cicada-setup > ~/setup1.log 2>&1 || { tail -60 ~/setup1.log; fail "cicada-setup"; }
healthy || { tail -30 "$(brew --prefix)/var/log/cicada/backend.err.log"; fail "/healthz after cicada-setup"; }
systemctl --user is-active --quiet cicada-backend.service || fail "unit not active"
UNIT=~/.config/systemd/user/cicada-backend.service
grep -qF "$OPT/api/.venv/bin/python" "$UNIT" || fail "unit does not name the opt path"
grep -q "/Cellar/" "$UNIT" && fail "unit names a Cellar path"
grep -q "/Cellar/" ~/.claude/settings.json && fail "hooks name a Cellar path"
grep -qF "$OPT/api/hooks/capture.py" ~/.claude/settings.json || fail "capture hook missing"
listen="$(awk '$4 == "0A" && $2 ~ /:1F40$/ {print $2}' /proc/net/tcp /proc/net/tcp6 | sort -u | tr '\n' ' ')"
[ "$listen" = "0100007F:1F40 " ] || fail "port 8000 listens on '$listen'"
cicada status > ~/status.txt 2>&1 || { cat ~/status.txt; fail "cicada status"; }
[ "$(readlink -f "$OPT/api/.env")" = "$(brew --prefix)/etc/cicada/api.env" ] || fail "api/.env is not the etc one"
grep -q '^CICADA_MEMORY_PATH=' "$(brew --prefix)/etc/cicada/api.env" || fail "settings not written to etc"
grep -qF -e "$(cat ~/.cicada/api_token)" ~/setup1.log ~/brew-install.log ~/status.txt && fail "the token was printed"
[ -d ~/cicada/memory/.git ] || fail "no memory folder"
[ -s "$(brew --prefix)/var/log/cicada/backend.err.log" ] || fail "logs are not in var/log/cicada"
pass "cicada-setup: unit and hooks name the opt path, loopback only, CLI works, settings in etc, logs in var"

# 3b. cicada-setup again on a running backend of this install: a restart, nothing else
p1="$(pid)"
cicada-setup > ~/setup2.log 2>&1 || { tail -40 ~/setup2.log; fail "cicada-setup again"; }
healthy || fail "/healthz after the second cicada-setup"
[ "$(pid)" != "$p1" ] || fail "the second cicada-setup did not restart the backend"
pass "cicada-setup again restarts this install's backend"

# 4. a newer release: brew upgrade, cicada-setup, the backend on the new keg
git -C /srv/cicada.git tag v90.0.1 next-release
sed -i "s#tag: \"$TAG_NOW\"#tag: \"v90.0.1\"#" "$F"
brew upgrade rorosaga/cicada/cicada > ~/brew-upgrade.log 2>&1 || { tail -40 ~/brew-upgrade.log; fail "brew upgrade"; }
[ "$(brew list --versions cicada)" = "cicada 90.0.1 ${TAG_NOW#v}" ] || [ "$(brew list --versions cicada)" = "cicada ${TAG_NOW#v} 90.0.1" ] || echo "versions: $(brew list --versions cicada)"
p2="$(pid)"
cicada-setup > ~/setup3.log 2>&1 || { tail -40 ~/setup3.log; fail "cicada-setup after upgrade"; }
healthy || fail "/healthz after upgrade"
[ "$(pid)" != "$p2" ] || fail "the backend did not restart after the upgrade"
cell="$(readlink -f "/proc/$(pid)/cwd")"
case "$cell" in */Cellar/cicada/90.0.1/*) ;; *) fail "the backend runs from $cell, not the new keg" ;; esac
grep -q '^CICADA_MEMORY_PATH=' "$OPT/api/.env" || fail "settings lost in the upgrade"
pass "brew upgrade + cicada-setup: the backend runs the new keg, settings kept"

# 5. uninstall
cicada-setup --uninstall > ~/uninstall.log 2>&1 || { cat ~/uninstall.log; fail "cicada-setup --uninstall"; }
brew uninstall cicada >/dev/null 2>&1 || fail "brew uninstall"
[ ! -e "$UNIT" ] || fail "unit left"
systemctl --user is-active --quiet cicada-backend.service && fail "unit still active"
grep -q "capture.py\|recall.py" ~/.claude/settings.json 2>/dev/null && fail "hooks left"
[ -d ~/cicada/memory/.git ] || fail "memory removed"
pass "cicada-setup --uninstall + brew uninstall: unit and hooks gone, memory kept"
mkdir -p /srv/logs && cp ~/*.log /srv/logs/ 2>/dev/null
echo "ALL PASSED"
CHECKS
chmod 755 "$WORK/srv/checks.sh"

docker build -q -t "$NAME:test" - >/dev/null <<'DF'
FROM homebrew/brew:latest
USER root
# The image's own GitHub CLI apt source can carry an expired key, which fails every apt-get update; it isn't needed.
RUN rm -f /etc/apt/sources.list.d/*github* && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq systemd systemd-sysv dbus dbus-user-session >/dev/null && apt-get clean && rm -rf /var/lib/apt/lists/*
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
DF
docker run -d --name "$NAME" --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  --tmpfs /run --tmpfs /run/lock -v "$WORK/srv:/srv" "$NAME:test" >/dev/null
for _ in $(seq 1 30); do
  docker exec "$NAME" systemctl is-system-running 2>/dev/null | grep -qE 'running|degraded' && break
  sleep 1
done
docker exec "$NAME" loginctl enable-linger linuxbrew
uid="$(docker exec "$NAME" id -u linuxbrew)"
for _ in $(seq 1 20); do docker exec "$NAME" test -S "/run/user/$uid/bus" && break; sleep 1; done
docker exec "$NAME" git config --system --add safe.directory '*'
status=0
docker exec -u linuxbrew "$NAME" /srv/checks.sh || status=1
if [ -n "${CICADA_TEST_LOGS:-}" ]; then mkdir -p "$CICADA_TEST_LOGS" && cp -R "$WORK/srv/logs/." "$CICADA_TEST_LOGS/" 2>/dev/null || true; fi
exit "$status"
