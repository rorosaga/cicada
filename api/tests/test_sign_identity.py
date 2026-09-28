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
