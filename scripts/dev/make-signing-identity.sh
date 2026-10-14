#!/usr/bin/env bash
# Create the "Cicada Local" code-signing identity once, so every local build of Cicada.app
# (`make install-app`, `make dev`, the dev auto-update) is signed by the same certificate
# and macOS keeps its privacy grants — Full Disk Access, Contacts, Calendar, Automation,
# Screen Recording — across rebuilds.
#
# Why (measured 2026-10-14): an ad-hoc signature's designated requirement is the build's own
# code hash (cdhash). TCC files every grant against that requirement, so each new build is a
# new app to it: Full Disk Access granted at one build read "Needs Full Disk Access" again
# after the next auto-update. A certificate-signed build's requirement is "this bundle id,
# signed by this certificate", which every rebuild keeps. `install_app.sh` already signs with
# "Cicada Local" when the keychain has it (`app/CicadaApp/sign_identity.sh`); this makes it.
#
# Free: a self-signed certificate made here, with no Apple account. It is not a Developer ID —
# Gatekeeper does not trust it and it signs nothing for anyone else's Mac (docs/RELEASING.md).
#
# Run it yourself, at the keyboard, once per Mac. Three steps, each safe to repeat:
#   1. create — the certificate and key in the login keychain, unless "Cicada Local" is there;
#   2. authorise — `security set-key-partition-list -S apple-tool:,apple: -s -l "Cicada Local"`,
#      so codesign may use the key without a dialog. `-l` limits it to that one key; macOS asks
#      for the login keychain's password once. `-T /usr/bin/codesign` on import alone does not
#      stop the dialog on current macOS, and the unattended auto-update must never meet it;
#   3. trial — sign a throwaway copy of /usr/bin/true with the identity under a time limit, and
#      fail with the reason if it does not sign unattended.
# Each failure says which step and why. `install_app.sh` also bounds codesign when unattended,
# so even an unauthorised key skips an update instead of hanging it.
#
#   make signing-identity           (or scripts/dev/make-signing-identity.sh)
#
# Env (tests point these at fakes and a scratch keychain; nobody else needs them):
#   CICADA_KEYCHAIN       the keychain to use (default: the login keychain)
#   SECURITY              the security(1) to call (default: security on PATH)
#   OPENSSL               the openssl to call (default: /usr/bin/openssl, macOS's LibreSSL)
#   CODESIGN              the codesign the trial runs (default: codesign on PATH)
#   CICADA_TRIAL_TIMEOUT  seconds the trial signature may take (default 30)
set -euo pipefail

NAME="Cicada Local"
SECURITY="${SECURITY:-security}"
OPENSSL="${OPENSSL:-/usr/bin/openssl}"
KEYCHAIN="${CICADA_KEYCHAIN:-$HOME/Library/Keychains/login.keychain-db}"
DAYS="${CICADA_SIGN_DAYS:-3650}"
TRIAL_TIMEOUT="${CICADA_TRIAL_TIMEOUT:-30}"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../../app/CicadaApp/sign_identity.sh
. "$HERE/../../app/CicadaApp/sign_identity.sh"   # cicada_codesign_bounded

STEP="starting"
fail() { echo "make-signing-identity: failed while $STEP: $*" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cicada-sign.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
chmod 700 "$WORK"

identity_hash() {
  "$SECURITY" find-identity -p codesigning "$KEYCHAIN" 2>/dev/null \
    | sed -nE "s/^[[:space:]]*[0-9]+\)[[:space:]]+([0-9A-Fa-f]{40})[[:space:]]+\"$NAME\".*/\1/p" | head -n 1
}

# --- 1. create ------------------------------------------------------------------------------------
STEP="looking for \"$NAME\" in $(basename "$KEYCHAIN")"
HASH="$(identity_hash || true)"
if [ -n "$HASH" ]; then
  echo "1/3 \"$NAME\" is already in $(basename "$KEYCHAIN") ($HASH) — kept."
else
  STEP="writing the certificate request"
  cat > "$WORK/cert.cnf" <<CNF
[ req ]
distinguished_name = dn
prompt = no
x509_extensions = ext
[ dn ]
CN = $NAME
[ ext ]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
subjectKeyIdentifier = hash
CNF
  STEP="making the key and self-signed certificate with $OPENSSL"
  "$OPENSSL" req -x509 -newkey rsa:2048 -nodes -sha256 -days "$DAYS" \
    -config "$WORK/cert.cnf" -keyout "$WORK/key.pem" -out "$WORK/cert.pem" >"$WORK/openssl.log" 2>&1 \
    || fail "$(tail -n 3 "$WORK/openssl.log")"
  # A one-time password only for the hand-off to `security import`; the folder is deleted on exit.
  PASS="$("$OPENSSL" rand -hex 16)"
  STEP="packaging the identity as PKCS#12"
  # LibreSSL writes the PKCS#12 algorithms `security import` reads; OpenSSL 3 needs -legacy for that.
  p12_args=(pkcs12 -export -inkey "$WORK/key.pem" -in "$WORK/cert.pem" -name "$NAME" -out "$WORK/id.p12"
            -passout "pass:$PASS")
  if "$OPENSSL" version 2>/dev/null | grep -q '^OpenSSL 3'; then p12_args+=(-legacy); fi
  "$OPENSSL" "${p12_args[@]}" >"$WORK/openssl.log" 2>&1 || fail "$(tail -n 3 "$WORK/openssl.log")"
  STEP="importing it into $(basename "$KEYCHAIN")"
  # -T: codesign may use the private key; nothing else is pre-approved.
  "$SECURITY" import "$WORK/id.p12" -k "$KEYCHAIN" -P "$PASS" -f pkcs12 -T /usr/bin/codesign >"$WORK/import.log" 2>&1 \
    || fail "$(tail -n 3 "$WORK/import.log") — is the keychain locked or missing?"
  HASH="$(identity_hash || true)"
  [ -n "$HASH" ] || fail "imported, but \"$NAME\" is not listed as a code-signing identity — check Keychain Access."
  echo "1/3 Created \"$NAME\" in $(basename "$KEYCHAIN") ($HASH; self-signed, $DAYS days)."
fi

# --- 2. authorise ---------------------------------------------------------------------------------
STEP="authorising codesign to use the \"$NAME\" key (security set-key-partition-list)"
echo "2/3 Letting codesign use the \"$NAME\" key without a dialog — macOS asks for your login password once."
# -l limits the change to the key with this label; no other key in the keychain is touched.
"$SECURITY" set-key-partition-list -S apple-tool:,apple: -s -l "$NAME" "$KEYCHAIN" >"$WORK/partition.log" 2>&1 \
  || fail "$(tail -n 3 "$WORK/partition.log") — the password was refused, or no key is labelled \"$NAME\"."

# --- 3. trial -------------------------------------------------------------------------------------
STEP="signing a throwaway copy of /usr/bin/true with \"$NAME\""
cp /usr/bin/true "$WORK/trial"
trial=0
cicada_codesign_bounded "$TRIAL_TIMEOUT" --force --sign "$HASH" --timestamp=none "$WORK/trial" \
  >"$WORK/trial.log" 2>&1 || trial=$?
if [ "$trial" -eq 124 ]; then
  fail "codesign was still waiting after ${TRIAL_TIMEOUT} s — a key prompt is up. Answer it with Always Allow, then run this again."
elif [ "$trial" -ne 0 ]; then
  fail "$(tail -n 3 "$WORK/trial.log")"
fi
echo "3/3 codesign signs with \"$NAME\" without asking."
echo "Next: make install-app, then grant Full Disk Access (and any other permission) one last time; later builds keep it."
