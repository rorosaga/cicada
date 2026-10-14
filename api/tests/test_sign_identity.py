"""app/CicadaApp/sign_identity.sh — which identity install_app.sh signs Cicada.app with.

An ad-hoc signature ties macOS's privacy grants to one build's hash, so the helper prefers a self-signed
"Cicada Local" certificate. Each case sources the helper under a fake `security` first on PATH that prints canned
`find-identity` output — the real keychain is never read.
"""
from __future__ import annotations

import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "app" / "CicadaApp" / "sign_identity.sh"
INSTALL = ROOT / "app" / "CicadaApp" / "install_app.sh"

HASH_A = "A" * 40
HASH_B = "B" * 40
HASH_C = "C" * 40


def _listing(rows: list[str], *, valid: bool) -> str:
    """The shape `security find-identity -p codesigning` prints; without -v it lists both sections."""
    body = "".join(f"  {i}) {row}\n" for i, row in enumerate(rows, 1))
    if valid:
        return f"{body}     {len(rows)} valid identities found\n"
    return (
        "Policy: Code Signing\n  Matching identities\n"
        f"{body}     {len(rows)} identities found\n\n"
        "  Valid identities only\n     0 valid identities found\n"
    )


def _fake_security(bin_dir: Path, *, valid: list[str], all_rows: list[str] | None = None) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "valid.txt").write_text(_listing(valid, valid=True))
    (bin_dir / "all.txt").write_text(_listing(all_rows if all_rows is not None else valid, valid=False))
    log = bin_dir / "security.log"
    script = bin_dir / "security"
    script.write_text(f"""#!/bin/bash
echo "$@" >> "{log}"
for a in "$@"; do [ "$a" = "-v" ] && {{ cat "{bin_dir}/valid.txt"; exit 0; }}; done
cat "{bin_dir}/all.txt"
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return log


def _pick(tmp_path: Path, *, override: str | None = None, **fake) -> tuple[str, str]:
    bin_dir = tmp_path / "bin"
    _fake_security(bin_dir, **fake)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    if override is not None:
        env["CICADA_SIGN_IDENTITY"] = override
    done = subprocess.run(
        ["/bin/bash", "-c", 'set -euo pipefail; . "$0"; cicada_sign_identity; printf "%s\\n%s\\n" "$SIGN_IDENTITY" "$SIGN_LABEL"',
         str(HELPER)],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stderr
    identity, label = done.stdout.splitlines()
    return identity, label


def test_no_identity_signs_ad_hoc(tmp_path):
    assert _pick(tmp_path, valid=[]) == ("-", "ad hoc")


def test_one_cicada_local_is_used_by_its_hash(tmp_path):
    identity, label = _pick(tmp_path, valid=[f'{HASH_A} "Cicada Local"'])
    assert identity == HASH_A
    assert "Cicada Local" in label and HASH_A in label


def test_only_the_identity_named_exactly_cicada_local_is_picked(tmp_path):
    rows = [f'{HASH_A} "Apple Development: Someone (TEAM123456)"', f'{HASH_B} "Cicada Local"']
    assert _pick(tmp_path, valid=rows)[0] == HASH_B


def test_a_similar_name_is_not_cicada_local(tmp_path):
    rows = [f'{HASH_A} "Cicada Local 2"', f'{HASH_B} "Old Cicada Local"']
    assert _pick(tmp_path, valid=rows) == ("-", "ad hoc")


def test_a_duplicate_name_resolves_to_the_first_hash(tmp_path):
    rows = [f'{HASH_A} "Cicada Local"', f'{HASH_B} "Cicada Local"']
    assert _pick(tmp_path, valid=rows)[0] == HASH_A


def test_an_untrusted_self_signed_certificate_listed_only_without_v_is_used(tmp_path):
    identity, _ = _pick(tmp_path, valid=[], all_rows=[f'{HASH_C} "Cicada Local" (CSSMERR_TP_NOT_TRUSTED)'])
    assert identity == HASH_C


def test_an_expired_or_revoked_certificate_is_never_picked(tmp_path):
    rows = [f'{HASH_A} "Cicada Local" (CSSMERR_TP_CERT_EXPIRED)', f'{HASH_B} "Cicada Local" (CSSMERR_TP_CERT_REVOKED)']
    assert _pick(tmp_path, valid=[], all_rows=rows) == ("-", "ad hoc")


def test_a_valid_identity_wins_over_an_untrusted_one(tmp_path):
    identity, _ = _pick(
        tmp_path,
        valid=[f'{HASH_B} "Cicada Local"'],
        all_rows=[f'{HASH_A} "Cicada Local" (CSSMERR_TP_NOT_TRUSTED)', f'{HASH_B} "Cicada Local"'],
    )
    assert identity == HASH_B


def test_the_override_wins_and_the_keychain_is_not_asked(tmp_path):
    identity, label = _pick(tmp_path, override="Some Other Cert", valid=[f'{HASH_A} "Cicada Local"'])
    assert identity == "Some Other Cert"
    assert "CICADA_SIGN_IDENTITY" in label
    assert not (tmp_path / "bin" / "security.log").exists()


def test_the_override_can_force_ad_hoc(tmp_path):
    assert _pick(tmp_path, override="-", valid=[f'{HASH_A} "Cicada Local"'])[0] == "-"


def test_an_empty_override_is_treated_as_unset(tmp_path):
    assert _pick(tmp_path, override="", valid=[f'{HASH_A} "Cicada Local"'])[0] == HASH_A


def test_no_security_tool_signs_ad_hoc(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    done = subprocess.run(
        ["/bin/bash", "-c", '. "$0"; PATH="$1"; cicada_sign_identity; echo "$SIGN_IDENTITY"', str(HELPER), str(empty)],
        capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "-"


def test_install_app_signs_with_the_chosen_identity_and_still_verifies_before_the_swap():
    text = INSTALL.read_text()
    assert ". ./sign_identity.sh" in text and "cicada_sign_identity" in text
    assert 'codesign "${sign_args[@]}" "$STAGING"' in text
    assert "--sign -" not in text
    sign = text.index('codesign "${sign_args[@]}"')
    verify = text.index("if ! codesign --verify --deep --strict")
    swap = text.index('if mv "$STAGING" "$DEST"')
    assert sign < verify < swap


# --- make-signing-identity.sh: the one-time "Cicada Local" setup (2026-10-14) ------------------------------------------
# An ad-hoc build's privacy grants are keyed to its cdhash, so every update dropped Full Disk Access. The script makes the
# certificate the chooser above already prefers. Run here with a fake `security` that records the import and a scratch
# keychain path — the real keychain is never touched; the certificate itself is made by the real openssl.

MAKE_IDENTITY = ROOT / "scripts" / "dev" / "make-signing-identity.sh"


def _fake_keychain_security(bin_dir: Path, *, has_identity: bool) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / "security.log"
    state = bin_dir / "imported"
    if has_identity:
        state.write_text("yes")
    script = bin_dir / "security"
    script.write_text(f"""#!/bin/bash
echo "$@" >> "{log}"
case "$1" in
  find-identity)
    if [ -f "{state}" ]; then echo '  1) {HASH_A} "Cicada Local" (CSSMERR_TP_NOT_TRUSTED)'; fi
    echo '     1 identities found' ;;
  import)
    cp "$2" "{bin_dir}/imported.p12"; echo yes > "{state}" ;;
esac
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return log


def _make_identity(tmp_path: Path, *, has_identity: bool):
    bin_dir = tmp_path / "bin"
    log = _fake_keychain_security(bin_dir, has_identity=has_identity)
    keychain = tmp_path / "scratch.keychain-db"
    done = subprocess.run(
        ["/bin/bash", str(MAKE_IDENTITY)],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
             "CICADA_KEYCHAIN": str(keychain)},
        capture_output=True, text=True, timeout=60,
    )
    return done, log, bin_dir, keychain


def test_make_signing_identity_creates_a_code_signing_certificate_once(tmp_path):
    done, log, bin_dir, keychain = _make_identity(tmp_path, has_identity=False)
    assert done.returncode == 0, done.stderr
    calls = log.read_text().splitlines()
    imports = [c for c in calls if c.startswith("import ")]
    assert len(imports) == 1
    assert f"-k {keychain}" in imports[0], "into the keychain named, never another"
    assert "-T /usr/bin/codesign" in imports[0], "only codesign is pre-approved to use the key"
    # The PKCS#12 holds a self-signed certificate named Cicada Local, for code signing only.
    password = imports[0].split(" -P ")[1].split(" ")[0]
    cert = subprocess.run(["/usr/bin/openssl", "pkcs12", "-in", str(bin_dir / "imported.p12"), "-nokeys",
                           "-passin", f"pass:{password}"], capture_output=True, text=True, check=True).stdout
    text = subprocess.run(["/usr/bin/openssl", "x509", "-noout", "-subject", "-ext", "extendedKeyUsage,basicConstraints"],
                          input=cert, capture_output=True, text=True).stdout
    if "-ext" in text or not text.strip():   # LibreSSL without -ext: print the whole text instead
        text = subprocess.run(["/usr/bin/openssl", "x509", "-noout", "-subject", "-text"],
                              input=cert, capture_output=True, text=True, check=True).stdout
    assert "Cicada Local" in text
    assert "Code Signing" in text
    assert "CA:FALSE" in text
    assert "make install-app" in done.stdout, "says the one manual step that follows"
    # The temp folder with the key is gone.
    assert not list(tmp_path.glob("cicada-sign.*"))

    # Run again: already there, nothing imported a second time.
    again = subprocess.run(["/bin/bash", str(MAKE_IDENTITY)],
                           env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
                                "CICADA_KEYCHAIN": str(keychain)}, capture_output=True, text=True, timeout=60)
    assert again.returncode == 0, again.stderr
    assert "nothing to do" in again.stdout
    assert sum(1 for c in log.read_text().splitlines() if c.startswith("import ")) == 1


def test_make_signing_identity_leaves_an_existing_identity_alone(tmp_path):
    done, log, _bin, _kc = _make_identity(tmp_path, has_identity=True)
    assert done.returncode == 0, done.stderr
    assert not any(c.startswith("import ") for c in log.read_text().splitlines())


def test_the_identity_it_makes_is_the_one_the_chooser_picks(tmp_path):
    """The script's name and the chooser's are one name — a drift would make every build ad hoc again."""
    script = MAKE_IDENTITY.read_text()
    helper = HELPER.read_text()
    assert 'NAME="Cicada Local"' in script
    assert 'CICADA_SIGN_NAME="Cicada Local"' in helper
    assert "make signing-identity" in INSTALL.read_text(), "an ad-hoc install names the fix"
