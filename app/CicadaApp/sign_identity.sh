# Which identity install_app.sh signs Cicada.app with. Sourced, never run:
# it only defines `cicada_sign_identity`, which sets two variables —
#   SIGN_IDENTITY  what goes to `codesign --sign` (a SHA-1 hash, a name, or `-`)
#   SIGN_LABEL     the words the install prints for it
#
# Why it matters: macOS keeps a privacy grant (Documents, Contacts, Calendar,
# Apple Events) against the app's designated requirement. An ad-hoc signature's
# requirement is the build's own code hash, so every rebuild looks like a new
# app and asks again. A certificate-signed build's requirement is "this bundle
# id, signed by this certificate", which a rebuild keeps.
#
# The ladder, first hit wins:
#   1. CICADA_SIGN_IDENTITY, when set and non-empty — used as given.
#   2. A code-signing identity named exactly "Cicada Local" (the self-signed
#      certificate scripts/dev/README.md walks through), by its SHA-1 hash so a
#      second certificate with the same name can never make codesign refuse as
#      ambiguous. A valid identity (`-v`) is preferred; a self-signed one macOS
#      does not trust yet is listed only without `-v`, and codesign signs with
#      it all the same — an expired or revoked one is never picked.
#   3. Ad hoc (`-`), what every build did before.
#
# Tests run it with a fake `security` first on PATH (api/tests/test_sign_identity.py).

CICADA_SIGN_NAME="Cicada Local"

# Prints the hash of the first "Cicada Local" line in `security find-identity`
# output read from stdin. With $1 = strict, only a line carrying no complaint
# counts; otherwise a line whose one complaint is "not trusted" counts too.
_cicada_pick_identity() {
  local mode="$1" line hash name tail
  local re='^[[:space:]]*[0-9]+\)[[:space:]]+([0-9A-Fa-f]{40})[[:space:]]+"(.*)"(.*)$'
  while IFS= read -r line; do
    [[ $line =~ $re ]] || continue
    hash="${BASH_REMATCH[1]}"
    name="${BASH_REMATCH[2]}"
    tail="${BASH_REMATCH[3]//[[:space:]]/}"
    [ "$name" = "$CICADA_SIGN_NAME" ] || continue
    if [ -z "$tail" ] || { [ "$mode" != strict ] && [ "$tail" = "(CSSMERR_TP_NOT_TRUSTED)" ]; }; then
      printf '%s\n' "$hash"
      return 0
    fi
  done
  return 1
}

cicada_sign_identity() {
  local hash
  if [ -n "${CICADA_SIGN_IDENTITY:-}" ]; then
    SIGN_IDENTITY="$CICADA_SIGN_IDENTITY"
    if [ "$SIGN_IDENTITY" = "-" ]; then
      SIGN_LABEL="ad hoc, from CICADA_SIGN_IDENTITY"
    else
      SIGN_LABEL="\"$SIGN_IDENTITY\", from CICADA_SIGN_IDENTITY"
    fi
    return 0
  fi
  if command -v security >/dev/null 2>&1; then
    hash="$(security find-identity -v -p codesigning 2>/dev/null | _cicada_pick_identity strict)" \
      || hash="$(security find-identity -p codesigning 2>/dev/null | _cicada_pick_identity lenient)" \
      || hash=""
    if [ -n "$hash" ]; then
      SIGN_IDENTITY="$hash"
      SIGN_LABEL="\"$CICADA_SIGN_NAME\" ($hash)"
      return 0
    fi
  fi
  SIGN_IDENTITY="-"
  SIGN_LABEL="ad hoc"
}
