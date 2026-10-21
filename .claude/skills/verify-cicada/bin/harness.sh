# Source this file (`. <skill>/bin/harness.sh`); never run it. macos-harness keeps its element numbers per
# calling shell, so these are shell functions, not a script. Each call targets the verify copy by path, and
# `cv app path` fails unless this run's own instance is running, so nothing here can reach another Cicada.
CV="${CV:-$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)/cv}"
vh() { local app; app="$("$CV" app path)" || return 1; macos-harness "$1" --app "$app" "${@:2}"; }
vidx() { vh get_app_state --disableDiff | grep -E "$1" | head -1 | awk '{print $1}'; }
vclick() {
  local i; i="$(vidx "$1")"
  [ -n "$i" ] || { echo "vclick: no element matches $1" >&2; return 1; }
  vh click --element_index "$i"
}
