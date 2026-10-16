#!/usr/bin/env bash
#
# Install Cicada on a Linux server, headless — no app (G181). One line:
#
#   curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-server.sh | bash
#
# It checks what it needs and names every missing piece at once; fetches Cicada at a pinned ref (the latest release
# by default) into ~/.local/share/cicada; syncs its Python environment without the optional larger model's runtime
# (scripts/sync-server-env.sh); then runs the checkout's own ./install.sh --cli, which creates the memory folder,
# links the `cicada` command into ~/.local/bin and installs the systemd user unit bound to 127.0.0.1
# (scripts/install-backend-service.sh). Safe to run again: the same ref changes nothing; a newer ref updates the code
# and restarts the service.
#
# What it never does: create, copy or print a credential (the backend writes its own token, and this script only
# says where), open a port beyond this machine, turn on lingering (`sudo loginctl enable-linger` is the person's
# step), run as root, or touch the memory folder on --uninstall.
#
#   curl -fsSL …/install-server.sh | CICADA_REF=dev bash        a branch, a tag or a commit, for testers
#   curl -fsSL …/install-server.sh | bash -s -- --uninstall     remove the service, the hooks, the command and the code
#
# Env: CICADA_REF       branch, tag or commit to install (default: the newest vX.Y.Z tag, i.e. the latest release)
#      CICADA_DIR       where the code goes (default: ${XDG_DATA_HOME:-~/.local/share}/cicada)
#      CICADA_GIT_URL   where it is fetched from (default: https://github.com/rorosaga/cicada.git; tests serve their own)
#      CICADA_MEMORY_PATH, CICADA_RECALL   passed to install.sh (memory folder default: ~/cicada/memory)
# Exit: 0 done · 1 failed · 2 a prerequisite or a flag is wrong
#
# The whole script is one function called on the last line, so `curl | bash` runs nothing until every byte has
# arrived, and every child reads /dev/null: nothing can swallow the rest of the script from the pipe.
set -euo pipefail

MARK="cicada-install-server"   # in <dir>/.git: this script cloned <dir>, so --uninstall may delete it

main() {
  local GIT_URL="${CICADA_GIT_URL:-https://github.com/rorosaga/cicada.git}"
  local DIR="${CICADA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/cicada}"
  local REF="${CICADA_REF:-}"
  local RELEASE=0   # REF is the latest release's tag: resolved as a tag only, never a branch of the same name
  local UNIT="cicada-backend.service"
  local PORT=8000
  local UNINSTALL=0

  for arg in "$@"; do
    case "$arg" in
      --uninstall) UNINSTALL=1 ;;
      -h|--help) usage; return 0 ;;
      *) err "Unknown flag: $arg (try --help)"; return 2 ;;
    esac
  done

  if [ "$UNINSTALL" -eq 1 ]; then
    uninstall "$DIR"
    return
  fi

  hdr "Installing Cicada (headless server)"
  preflight || return 2

  # --- the code, at a pinned ref ---
  if [ -z "$REF" ]; then
    REF="$(latest_release "$GIT_URL")" || return 1
    RELEASE=1
    step "Latest release: $REF"
  fi
  case "$REF" in
    -*|*[!A-Za-z0-9._/-]*) err "CICADA_REF must be a branch, tag or commit name, not '$REF'."; return 2 ;;
  esac

  local before=""
  if [ -e "$DIR" ]; then
    is_our_checkout "$DIR" "$GIT_URL" || return 1
    before="$(git -C "$DIR" rev-parse HEAD)"
    if [ -n "$(git -C "$DIR" status --porcelain --untracked-files=no)" ]; then
      err "$DIR has changes of its own; Cicada won't overwrite them. Commit or discard them, then run this again."
      return 1
    fi
    step "Fetching $REF"
    git -C "$DIR" fetch --quiet --tags --force origin '+refs/heads/*:refs/remotes/origin/*' </dev/null \
      || { err "Couldn't fetch from $GIT_URL."; return 1; }
  else
    step "Fetching Cicada into $DIR"
    mkdir -p "$(dirname "$DIR")"
    git clone --quiet --no-checkout --filter=blob:none "$GIT_URL" "$DIR" </dev/null 2>/dev/null \
      || git clone --quiet --no-checkout "$GIT_URL" "$DIR" </dev/null \
      || { err "Couldn't clone $GIT_URL."; return 1; }
    # The mark --uninstall needs before it deletes this folder: only a folder this script cloned is ever removed.
    : > "$DIR/.git/$MARK"
  fi
  local sha
  sha="$(resolve_ref "$DIR" "$REF" "$RELEASE")" || { err "$GIT_URL has no branch, tag or commit called '$REF'."; return 1; }
  if [ "$sha" != "$before" ]; then
    git -C "$DIR" -c advice.detachedHead=false checkout --quiet --detach "$sha" </dev/null
  fi
  if [ ! -f "$DIR/scripts/sync-server-env.sh" ]; then
    err "$REF is older than the server install (it arrived after Cicada 0.3.1). Install a newer release, or CICADA_REF=dev."
    return 1
  fi
  ok "Cicada $(tr -d '[:space:]' < "$DIR/VERSION") at ${sha:0:12} ($REF)"

  # --- Python, without the optional larger model's runtime ---
  step "Syncing Python (the first run downloads ~0.5 GB)"
  bash "$DIR/scripts/sync-server-env.sh" --quiet </dev/null || { err "The Python environment didn't sync (above)."; return 1; }
  ok "Python environment ready ($DIR/api/.venv)"

  # --- everything else: install.sh, the same installer a clone runs ---
  CICADA_REPO="$DIR" bash "$DIR/install.sh" --cli </dev/null || { err "install.sh stopped (above)."; return 1; }

  # A client of a server elsewhere (CICADA_API_BASE, or $CICADA_HOME/api_base: install.sh's own rule) runs no backend:
  # install.sh installed no unit, an update starts none, and the check below asks the server instead.
  if [ -n "$(client_of)" ]; then
    client_done "$DIR" "$REF" "$(client_of)"
    return
  fi

  # An update: the unit may have changed and the running backend still has the old code loaded. The unit's own
  # script rewrites it and restarts it (install.sh skips a backend that already answers).
  if [ -n "$before" ] && [ "$before" != "$sha" ]; then
    step "Restarting the backend on the new code"
    CICADA_REPO="$DIR" bash "$DIR/scripts/install-backend-service.sh" </dev/null || warn "The service didn't restart (above)."
  fi

  # --- check it ---
  hdr "Checking"
  local healthy=0
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" 2>/dev/null | grep -q '"status"'; then healthy=1; break; fi
    sleep 1
  done
  if [ "$healthy" -eq 1 ]; then
    ok "The backend answers on 127.0.0.1:$PORT (systemctl --user status $UNIT)"
  else
    err "The backend isn't answering yet — see $DIR/logs/backend.err.log or: journalctl --user -u $UNIT"
    return 1
  fi
  if "$DIR/scripts/cicada" status </dev/null >/dev/null 2>&1; then
    ok "The cicada command works ($HOME/.local/bin/cicada)"
  else
    warn "'cicada status' didn't succeed — run it to see why"
  fi

  hdr "Done"
  echo "  code:     $DIR (at $REF)"
  echo "  service:  $UNIT, systemd --user, 127.0.0.1:$PORT only"
  echo "  token:    the backend keeps its own in ${CICADA_HOME:-$HOME/.cicada}/api_token (0600); it never leaves this machine"
  echo "  devices:  give another machine its own token with: cicada device add <name>"
  echo "  reach:    from elsewhere through an overlay you run (e.g. tailscale serve); see docs/architecture/headless.md"
  if command -v loginctl >/dev/null 2>&1 \
      && [ "$(loginctl show-user "$(id -un)" --property=Linger --value 2>/dev/null || true)" != "yes" ]; then
    echo "  linger:   off — the backend stops when you log out; to keep it running: sudo loginctl enable-linger $(id -un)"
  fi
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  PATH:     add ~/.local/bin to your PATH to run 'cicada' (export PATH=\"\$HOME/.local/bin:\$PATH\")" ;; esac
  echo "  update:   run the same line again;  remove:  … | bash -s -- --uninstall"
}

# Where this machine's memory lives when it is a client (install.sh step 6's rule), or nothing.
client_of() {
  if [ -n "$(printf '%s' "${CICADA_API_BASE:-}" | tr -d '[:space:]')" ]; then
    echo "CICADA_API_BASE"
  elif [ -s "${CICADA_HOME:-$HOME/.cicada}/api_base" ] \
      && [ -n "$(tr -d '[:space:]' < "${CICADA_HOME:-$HOME/.cicada}/api_base" 2>/dev/null)" ]; then
    echo "${CICADA_HOME:-$HOME/.cicada}/api_base"
  fi
}

# The end of a client install: the server is asked through the command (its address, this device's token), never
# 127.0.0.1:8000; a server that is not reachable yet, or a token not copied yet, is a warning with the fix.
client_done() {
  local dir="$1" ref="$2" where="$3"
  hdr "Checking"
  if "$dir/scripts/cicada" status --json </dev/null 2>/dev/null | grep -q '"state": "confirmed"'; then
    ok "The server answers and accepts this device's token (cicada status)"
  else
    warn "The server did not confirm yet — run 'cicada status' to see why (its address: $where; this device's token: ${CICADA_HOME:-$HOME/.cicada}/device_token or CICADA_API_TOKEN, from 'cicada device add <name>' on the server)"
  fi
  hdr "Done"
  echo "  code:     $dir (at $ref)"
  echo "  memory:   on the server ($where) — this machine runs no backend of its own"
  echo "  token:    this device's own, in ${CICADA_HOME:-$HOME/.cicada}/device_token (0600) or CICADA_API_TOKEN"
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  PATH:     add ~/.local/bin to your PATH to run 'cicada' (export PATH=\"\$HOME/.local/bin:\$PATH\")" ;; esac
  echo "  update:   run the same line again;  remove:  … | bash -s -- --uninstall"
}

usage() {
  cat <<'EOF'
Install Cicada on this Linux server, headless (G181):
  curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-server.sh | bash
  … | CICADA_REF=dev bash          a branch, tag or commit instead of the latest release
  … | bash -s -- --uninstall       remove the service, the hooks, the command and the code (never the memory)
Env: CICADA_REF, CICADA_DIR (default ~/.local/share/cicada), CICADA_GIT_URL, CICADA_MEMORY_PATH, CICADA_RECALL
EOF
}

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
step() { printf '  \033[36m→\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

# Every prerequisite, checked together, each missing one named with the line that fixes it.
preflight() {
  local missing=0 os
  os="$(uname -s)"
  if [ "$os" != "Linux" ]; then
    if [ "$os" = "Darwin" ]; then
      err "This installs the Linux server. On a Mac: the app (scripts/install-release.sh), or Homebrew — brew tap rorosaga/cicada https://github.com/rorosaga/cicada && brew install rorosaga/cicada/cicada"
    else
      err "Cicada's server install runs on Linux (this is $os)."
    fi
    return 1
  fi
  if [ "$(id -u)" -eq 0 ]; then
    err "Run this as the user who will own the memory, not as root (the service is that user's systemd unit)."
    return 1
  fi
  # uv's own installer puts it here, and a fresh `curl | bash` shell may not have it on PATH yet.
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    if ! command -v uv >/dev/null 2>&1 && [ -x "$d/uv" ]; then PATH="$d:$PATH"; export PATH; fi
  done
  command -v git  >/dev/null 2>&1 || { err "git is missing — install it with your package manager (e.g. sudo apt install git)"; missing=1; }
  command -v curl >/dev/null 2>&1 || { err "curl is missing — install it with your package manager (e.g. sudo apt install curl)"; missing=1; }
  command -v uv   >/dev/null 2>&1 || { err "uv is missing — install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"; missing=1; }
  if ! command -v systemctl >/dev/null 2>&1; then
    err "systemd is missing — Cicada's server runs as a systemd user service"
    missing=1
  elif ! systemctl --user show-environment >/dev/null 2>&1; then
    err "systemd's user manager isn't reachable from this shell. Log in as $(id -un) directly (SSH, not su/sudo); or have an admin run 'sudo loginctl enable-linger $(id -un)' and then: export XDG_RUNTIME_DIR=/run/user/$(id -u)"
    missing=1
  fi
  [ "$missing" -eq 0 ] && ok "git, curl, uv and a systemd user session are here"
  return "$missing"
}

# The newest vX.Y.Z tag: CI creates the tag only when it publishes a release, so this is the latest release.
latest_release() {
  local tag
  tag="$(git ls-remote --tags --refs "$1" 'v*' </dev/null 2>/dev/null \
    | sed -n 's#.*refs/tags/v\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)$#\1#p' \
    | sort -t. -k1,1n -k2,2n -k3,3n | tail -n1)"
  if [ -z "$tag" ]; then
    err "No release found at $1. To install a branch instead: CICADA_REF=dev"
    return 1
  fi
  printf 'v%s' "$tag"
}

# A branch follows its tip on each run; a tag or a commit stays put. The latest release is its tag and nothing else:
# a branch that happens to be called v1.2.3 never stands in for the release.
resolve_ref() {
  local dir="$1" ref="$2" release="${3:-0}"
  if [ "$release" -eq 1 ]; then
    git -C "$dir" rev-parse --verify --quiet "refs/tags/$ref^{commit}"
    return
  fi
  git -C "$dir" rev-parse --verify --quiet "refs/remotes/origin/$ref^{commit}" \
    || git -C "$dir" rev-parse --verify --quiet "refs/tags/$ref^{commit}" \
    || git -C "$dir" rev-parse --verify --quiet "$ref^{commit}"
}

# Only a Cicada checkout this installer made (same origin) is updated or removed; anything else is left alone.
is_our_checkout() {
  local dir="$1" url="$2" origin
  origin="$(git -C "$dir" config --get remote.origin.url 2>/dev/null || true)"
  if [ ! -d "$dir/.git" ] || [ ! -f "$dir/install.sh" ] || [ "$origin" != "$url" ]; then
    err "$dir exists and isn't a Cicada checkout from $url — left alone. Move it, or set CICADA_DIR."
    return 1
  fi
}

# The service is ours only when it runs this folder's Python; another Cicada's unit (a clone's) is left alone.
unit_is_ours() {
  local unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/cicada-backend.service"
  [ ! -e "$unit" ] || grep -qF "$1/api/.venv/bin/python" "$unit"
}

uninstall() {
  local dir="$1" link="$HOME/.local/bin/cicada"
  hdr "Removing Cicada (the memory folder and ~/.cicada stay)"
  # Nothing is removed from a folder this installer did not make.
  case "$dir" in
    ""|/|"$HOME"|"$HOME/") err "CICADA_DIR='$dir' can't be Cicada's code folder — nothing removed."; return 1 ;;
  esac
  if [ -e "$dir" ]; then
    is_our_checkout "$dir" "${CICADA_GIT_URL:-https://github.com/rorosaga/cicada.git}" || return 1
    if [ ! -f "$dir/.git/$MARK" ]; then
      err "$dir wasn't cloned by this installer — left alone (remove it yourself if you mean to)."
      return 1
    fi
    if unit_is_ours "$dir"; then
      CICADA_REPO="$dir" bash "$dir/install.sh" --uninstall </dev/null || warn "install.sh --uninstall reported a problem (above)"
    else
      warn "The background service, hooks and MCP entry belong to another Cicada install — left alone"
    fi
  elif command -v systemctl >/dev/null 2>&1 && [ -e "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/cicada-backend.service" ]; then
    if unit_is_ours "$dir"; then
      systemctl --user disable --now cicada-backend.service >/dev/null 2>&1 || true
      rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/cicada-backend.service"
      systemctl --user daemon-reload >/dev/null 2>&1 || true
    else
      warn "The background service belongs to another Cicada install — left alone"
    fi
  fi
  if [ -L "$link" ]; then
    case "$(readlink "$link")" in
      "$dir"/*) rm -f "$link"; ok "Removed $link" ;;
      *) warn "$link points elsewhere — left alone" ;;
    esac
  fi
  if [ -d "$dir" ]; then
    rm -rf -- "$dir"
    ok "Removed the code, its Python environment and its logs ($dir)"
  else
    ok "No code at $dir"
  fi
  echo "  Kept: the memory folder (${CICADA_MEMORY_PATH:-$HOME/cicada/memory}) and ${CICADA_HOME:-$HOME/.cicada} (the token, settings, models)."
  echo "  Delete them yourself only if you want the memory gone too."
}

main "$@"
