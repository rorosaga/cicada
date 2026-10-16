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
#   1. create — the certificate and key in the login keychain, unless a usable "Cicada Local" is there
#      (picked the way the install picks it: `_cicada_pick_identity` in sign_identity.sh, by SHA-1 hash);
#   2. authorise — let codesign use exactly that identity's private key without a dialog: its partition list becomes
#      `apple-tool:,apple:`, what `security set-key-partition-list -S apple-tool:,apple:` writes, asking for the
#      login keychain's password once. `-T /usr/bin/codesign` on import alone does not stop the dialog on current
#      macOS (the import leaves the key's partition list at `apple-tool:` alone, and codesign is still asked about —
#      reproduced in a scratch keychain 2026-10-15), and the unattended auto-update must never meet it;
#   3. trial — sign a throwaway copy of /usr/bin/true with the identity, from that keychain, under a time
#      limit, and fail with the reason if it does not sign unattended.
# Each failure says which step and why. `install_app.sh` also bounds codesign when unattended,
# so even an unauthorised key skips an update instead of hanging it.
#
# Why step 2 finds the key the way it does (fixed 2026-10-15): it used to run
# `security set-key-partition-list -S apple-tool:,apple: -s -l "Cicada Local"`, but `security import` labels every
# private key it imports "Imported Private Key", whatever name the PKCS#12 carries — only the certificate is
# labelled "Cicada Local". So `-l` matched no key ("SecItemCopyMatching: The specified item could not be found in
# the keychain") after step 1 had already made the identity; and `-l "Imported Private Key"` would rewrite every
# other key ever imported into the login keychain. `-a` cannot help: the key's application label is binary (the
# SHA-1 of its public key) and `security` matches `-a` only as text. Renaming the key first does not work either:
# any change to the key's attributes by another program is an access macOS asks about in a dialog. So step 2 reads
# the public-key hash from the chosen certificate itself (`hpky` in `security find-certificate -Z`, the keychain's
# own link from a certificate to its key) and `authorise-signing-key.swift`, built here with swiftc, does what
# `set-key-partition-list` does — the same Security calls, a port of security's own code — to the one private key
# in this keychain with that application label, with the keychain password. A re-run finds the identity step 1
# made and authorises it again; it never makes a second one.
#
#   make signing-identity           (or scripts/dev/make-signing-identity.sh)
#
# Env (tests point these at fakes and a scratch keychain; nobody else needs them):
#   CICADA_KEYCHAIN       the keychain to use (default: the login keychain)
#   SECURITY              the security(1) to call (default: security on PATH)
#   OPENSSL               the openssl to call (default: /usr/bin/openssl, macOS's LibreSSL)
#   SWIFTC                the Swift compiler that builds authorise-signing-key (default: swiftc on PATH)
#   CODESIGN              the codesign the trial runs (default: codesign on PATH)
#   CICADA_TRIAL_TIMEOUT  seconds the trial signature may take (default 30)
#   CICADA_KEYCHAIN_PASSWORD  TESTS ONLY: the scratch keychain's password, read by authorise-signing-key so a
#                         test runs without a prompt. Never set it for a real keychain — it would sit in the
#                         environment; at the keyboard the helper asks for it on the terminal.
set -euo pipefail

NAME="Cicada Local"
SECURITY="${SECURITY:-security}"
OPENSSL="${OPENSSL:-/usr/bin/openssl}"
SWIFTC="${SWIFTC:-swiftc}"
KEYCHAIN="${CICADA_KEYCHAIN:-$HOME/Library/Keychains/login.keychain-db}"
DAYS="${CICADA_SIGN_DAYS:-3650}"
TRIAL_TIMEOUT="${CICADA_TRIAL_TIMEOUT:-30}"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../../app/CicadaApp/sign_identity.sh
. "$HERE/../../app/CicadaApp/sign_identity.sh"   # cicada_codesign_bounded, _cicada_pick_identity

STEP="starting"
fail() { echo "make-signing-identity: failed while $STEP: $*" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cicada-sign.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
chmod 700 "$WORK"

# The "Cicada Local" identity in this keychain the install would sign with: a valid one first, else an untrusted
# self-signed one; never an expired or revoked one. By SHA-1 hash, so a second identity of the same name is never
# confused with it — steps 2 and 3 act on this hash alone.
identity_hash() {
  "$SECURITY" find-identity -v -p codesigning "$KEYCHAIN" 2>/dev/null | _cicada_pick_identity strict \
    || "$SECURITY" find-identity -p codesigning "$KEYCHAIN" 2>/dev/null | _cicada_pick_identity lenient
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
STEP="finding the private key of \"$NAME\" ($HASH)"
# The keychain records each certificate's public-key hash as "hpky"; the private key's application label is the
# same hash. Read it from the block whose SHA-1 is $HASH, never from another certificate of the same name.
APP_LABEL="$("$SECURITY" find-certificate -a -Z -c "$NAME" "$KEYCHAIN" 2>/dev/null | awk -v want="$HASH" '
  /^SHA-1 hash: / { cur = toupper($3) }
  /"hpky"<blob>=0x/ && cur == toupper(want) {
    sub(/.*"hpky"<blob>=0x/, ""); sub(/[^0-9A-Fa-f].*$/, ""); print toupper($0); exit
  }' || true)"
[ "${#APP_LABEL}" -eq 40 ] \
  || fail "the keychain lists no public-key hash for the certificate $HASH — check Keychain Access."

STEP="building the key-authorising helper with $SWIFTC"
"$SWIFTC" -o "$WORK/authorise-signing-key" "$HERE/authorise-signing-key.swift" >"$WORK/swiftc.log" 2>&1 \
  || fail "$(grep -m 3 'error' "$WORK/swiftc.log" || tail -n 3 "$WORK/swiftc.log") — install the Xcode command line tools (xcode-select --install)."

STEP="authorising codesign to use the \"$NAME\" key ($APP_LABEL)"
echo "2/3 Letting codesign use the \"$NAME\" key without a dialog — enter your login password once when asked."
# The partition list of that one private key, found by its application label; no other key is touched. The helper
# asks for the keychain password on the terminal itself (CICADA_KEYCHAIN_PASSWORD only in tests).
"$WORK/authorise-signing-key" "$KEYCHAIN" "$APP_LABEL" "apple-tool:,apple:" >"$WORK/authorise.log" 2>&1 \
  || fail "$(tail -n 3 "$WORK/authorise.log") — the password was refused, or the key is not in $(basename "$KEYCHAIN")."
echo "    $(tail -n 1 "$WORK/authorise.log")"

# --- 3. trial -------------------------------------------------------------------------------------
STEP="signing a throwaway copy of /usr/bin/true with \"$NAME\""
cp /usr/bin/true "$WORK/trial"
trial=0
# --keychain: the identity must come from the keychain just set up (codesign still needs it on the search list).
cicada_codesign_bounded "$TRIAL_TIMEOUT" --force --sign "$HASH" --keychain "$KEYCHAIN" --timestamp=none "$WORK/trial" \
  >"$WORK/trial.log" 2>&1 || trial=$?
if [ "$trial" -eq 124 ]; then
  fail "codesign was still waiting after ${TRIAL_TIMEOUT} s — a key prompt is up. Answer it with Always Allow, then run this again."
elif [ "$trial" -ne 0 ]; then
  fail "$(tail -n 3 "$WORK/trial.log")"
fi
echo "3/3 codesign signs with \"$NAME\" without asking."
echo "Next: make install-app, then grant Full Disk Access (and any other permission) one last time; later builds keep it."
