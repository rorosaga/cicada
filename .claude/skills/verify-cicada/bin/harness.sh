# Source this file (`. <skill>/bin/harness.sh`) in the same Bash call as vh/vclick; never run it. macos-harness keeps
# its element numbers per calling shell, so these are shell functions, not a script. Each call targets the verify copy
# by path, and `cv app path` fails unless this run's own instance is running, so nothing here can reach another Cicada.
CV="${CV:-$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)/cv}"
vh() {
  [ -n "${CICADA_VERIFY_RUN:-}" ] || { echo "vh: set CICADA_VERIFY_RUN in this same call" >&2; return 1; }
  local app; app="$("$CV" app path --run "$CICADA_VERIFY_RUN")" || return 1
  macos-harness "$1" --app "$app" "${@:2}"
}
vidx() { vh get_app_state --disableDiff | grep -E "$1" | head -1 | awk '{print $1}'; }
# Refuses an element that reads like Connect, Disconnect, Sign in/out, Install, Set up, Turn on or Get started
# (`cv deny`): those write the real account. --allow-forbidden skips the check; nothing makes such a press safe.
vclick() {
  local allow=""; [ "$1" = "--allow-forbidden" ] && { allow=1; shift; }
  local line; line="$(vh get_app_state --disableDiff | grep -E "$1" | head -1)"
  [ -n "$line" ] || { echo "vclick: no element matches $1" >&2; return 1; }
  [ -n "$allow" ] || "$CV" deny "$line" || return 1
  vh click --element_index "$(echo "$line" | awk '{print $1}')"
}
