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
# Idempotent: an existing "Cicada Local" identity is left as it is. Run it yourself, once per
# Mac, then `make install-app` once by hand and answer macOS's "codesign wants to use the key"
# with Always Allow — the unattended auto-update would otherwise wait on that dialog.
#
#   make signing-identity           (or scripts/dev/make-signing-identity.sh)
#
# Env (tests point these at fakes and a scratch keychain; nobody else needs them):
#   CICADA_KEYCHAIN   the keychain to import into (default: the login keychain)
#   SECURITY          the security(1) to call (default: security on PATH)
#   OPENSSL           the openssl to call (default: /usr/bin/openssl, macOS's LibreSSL)
set -euo pipefail

NAME="Cicada Local"
SECURITY="${SECURITY:-security}"
OPENSSL="${OPENSSL:-/usr/bin/openssl}"
KEYCHAIN="${CICADA_KEYCHAIN:-$HOME/Library/Keychains/login.keychain-db}"
DAYS="${CICADA_SIGN_DAYS:-3650}"

# Already there (valid, or self-signed and not trusted — both sign): nothing to do.
if "$SECURITY" find-identity -p codesigning "$KEYCHAIN" 2>/dev/null | grep -q "\"$NAME\""; then
  echo "\"$NAME\" is already in $(basename "$KEYCHAIN") — nothing to do."
  echo "make install-app signs with it; privacy grants carry across rebuilds."
  exit 0
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cicada-sign.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
chmod 700 "$WORK"

cat > "$WORK/cert.cnf" <<EOF
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
EOF

"$OPENSSL" req -x509 -newkey rsa:2048 -nodes -sha256 -days "$DAYS" \
  -config "$WORK/cert.cnf" -keyout "$WORK/key.pem" -out "$WORK/cert.pem" >/dev/null 2>&1

# A one-time password only for the hand-off to `security import`; the file is deleted on exit.
PASS="$("$OPENSSL" rand -hex 16)"
# LibreSSL writes the PKCS#12 algorithms `security import` reads; OpenSSL 3 needs -legacy for that.
p12_args=(pkcs12 -export -inkey "$WORK/key.pem" -in "$WORK/cert.pem" -name "$NAME" -out "$WORK/id.p12" -passout "pass:$PASS")
if "$OPENSSL" version 2>/dev/null | grep -q '^OpenSSL 3'; then p12_args+=(-legacy); fi
"$OPENSSL" "${p12_args[@]}" >/dev/null 2>&1

# -T: codesign may use the private key; nothing else is pre-approved.
"$SECURITY" import "$WORK/id.p12" -k "$KEYCHAIN" -P "$PASS" -f pkcs12 -T /usr/bin/codesign >/dev/null

if ! "$SECURITY" find-identity -p codesigning "$KEYCHAIN" 2>/dev/null | grep -q "\"$NAME\""; then
  echo "Imported, but \"$NAME\" is not listed as a code-signing identity — check Keychain Access." >&2
  exit 1
fi
echo "Created \"$NAME\" in $(basename "$KEYCHAIN") (self-signed, $DAYS days)."
echo "Next, once and by hand: make install-app — answer \"Always Allow\" when macOS asks whether codesign may use the key."
echo "Then grant Full Disk Access (and any other permission) one last time; later builds keep it."
