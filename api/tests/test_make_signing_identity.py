"""scripts/dev/make-signing-identity.sh, end to end, against a real scratch keychain (2026-10-15).

The script's step 2 used to run `security set-key-partition-list -S apple-tool:,apple: -s -l "Cicada Local"`, and on
the owner's Mac it failed with "SecItemCopyMatching: The specified item could not be found in the keychain":
`security import` labels every private key "Imported Private Key" — only the certificate is "Cicada Local" — so the
label matched no key, after step 1 had already made the identity. Step 2 now finds the key by its application label
(the certificate's public-key hash) and sets that one key's partition list through `authorise-signing-key.swift`.

These cases run the real script, the real `security`, `swiftc` and `codesign`, on a keychain made in tmp_path:

* HOME is tmp_path's own, in every subprocess, so the keychain search list `security` and codesign read is a scratch
  one holding only the scratch keychain — the person's login keychain and their real search list are never read or
  changed (the fixture checks the real search list is the same afterwards).
* A key `security import` puts into such a keychain gets the partition list `apple-tool:`, as in the login keychain,
  and codesign is then asked about it in a dialog — the very failure step 2 exists to prevent. Each case asserts that
  precondition before relying on it, and the trial signature runs under a time limit.
* `CICADA_KEYCHAIN_PASSWORD` hands the helper the scratch keychain's password (test-only; at the keyboard it asks).

Skipped off macOS, or when security, codesign, swiftc or /usr/bin/openssl is missing.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dev" / "make-signing-identity.sh"
OPENSSL = "/usr/bin/openssl"
PASSWORD = "scratch-keychain-pw"
P12_PASSWORD = "p12pass"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin"
    or not all(shutil.which(tool) for tool in ("security", "codesign", "swiftc"))
    or not Path(OPENSSL).exists(),
    reason="needs macOS with security, codesign, swiftc and /usr/bin/openssl",
)


def _real_search_list() -> str:
    """The person's own keychain search list, read only — to prove the tests never change it."""
    return subprocess.run(["security", "list-keychains", "-d", "user"], capture_output=True, text=True,
                          timeout=30).stdout


class Scratch:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        for sub in ("Library/Preferences", "Library/Keychains"):
            (self.home / sub).mkdir(parents=True)
        (tmp_path / "tmp").mkdir()
        self.keychain = self.home / "Library" / "Keychains" / "scratch.keychain-db"
        self.env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.home),
            "TMPDIR": str(tmp_path / "tmp"),
            "CICADA_KEYCHAIN": str(self.keychain),
            "CICADA_KEYCHAIN_PASSWORD": PASSWORD,
            "CICADA_TRIAL_TIMEOUT": "15",
        }

    def run(self, *args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
        done = subprocess.run(list(args), env=self.env, capture_output=True, text=True, timeout=timeout)
        if check:
            assert done.returncode == 0, f"{args}: {done.stdout}\n{done.stderr}"
        return done

    def security(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.run("security", *args, check=check)

    def make_keychain(self) -> None:
        self.security("create-keychain", "-p", PASSWORD, str(self.keychain))
        self.security("unlock-keychain", "-p", PASSWORD, str(self.keychain))
        self.security("set-keychain-settings", str(self.keychain))          # no auto-lock: no unlock prompt mid-test
        self.security("list-keychains", "-d", "user", "-s", str(self.keychain))   # the scratch HOME's list only

    def make_p12(self, name: str, cn: str) -> Path:
        """A self-signed code-signing certificate and key, packaged the way the old script did."""
        folder = self.tmp / name
        folder.mkdir()
        (folder / "cert.cnf").write_text(
            "[ req ]\ndistinguished_name = dn\nprompt = no\nx509_extensions = ext\n"
            f"[ dn ]\nCN = {cn}\n"
            "[ ext ]\nbasicConstraints = critical, CA:false\nkeyUsage = critical, digitalSignature\n"
            "extendedKeyUsage = critical, codeSigning\nsubjectKeyIdentifier = hash\n"
        )
        self.run(OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "30",
                 "-config", str(folder / "cert.cnf"), "-keyout", str(folder / "key.pem"), "-out", str(folder / "cert.pem"))
        self.run(OPENSSL, "pkcs12", "-export", "-inkey", str(folder / "key.pem"), "-in", str(folder / "cert.pem"),
                 "-name", cn, "-out", str(folder / "id.p12"), "-passout", f"pass:{P12_PASSWORD}")
        return folder / "id.p12"

    def import_p12(self, p12: Path, *trusted: str) -> None:
        args = ["import", str(p12), "-k", str(self.keychain), "-P", P12_PASSWORD, "-f", "pkcs12"]
        for app in trusted:
            args += ["-T", app]
        self.security(*args)

    def identities(self, name: str = "Cicada Local") -> list[str]:
        """Hashes of the code-signing identities called `name`, from the all-identities section."""
        out = self.security("find-identity", "-p", "codesigning", str(self.keychain)).stdout
        listed = out.split("Valid identities only")[0]
        return re.findall(rf'^\s*\d+\)\s+([0-9A-F]{{40}})\s+"{re.escape(name)}"', listed, re.M)

    def public_key_hash(self, cert_hash: str) -> str:
        out = self.security("find-certificate", "-a", "-Z", str(self.keychain)).stdout
        for block in out.split("SHA-256 hash:")[1:]:
            if f"SHA-1 hash: {cert_hash}" in block:
                return re.search(r'"hpky"<blob>=0x([0-9A-F]{40})', block).group(1)
        raise AssertionError(f"no certificate {cert_hash}")

    def private_keys(self) -> dict[str, str]:
        """Every private key's whole `dump-keychain -a` record (attributes and access), by application label."""
        out = self.security("dump-keychain", "-a", str(self.keychain)).stdout
        keys = {}
        for record in re.split(r'(?m)^(?=keychain: ")', out):
            if "class: 0x00000010" not in record:
                continue
            label = re.search(r"0x00000006 <blob>=0x([0-9A-F]{40})", record).group(1)
            keys[label] = record
        return keys

    def partitions(self, app_label: str) -> list[str]:
        record = self.private_keys()[app_label]
        found = re.search(r"authorizations \(1\): partition_id\n(?:.*\n)*?\s+description: (.*)\n", record)
        assert found, f"no partition list on {app_label}:\n{record}"
        return [p.strip() for p in found.group(1).split(",")]

    def key_label(self, app_label: str) -> str:
        return re.search(r'0x00000001 <blob>="(.*)"', self.private_keys()[app_label]).group(1)

    def make_identity(self) -> subprocess.CompletedProcess:
        return self.run("/bin/bash", str(SCRIPT), check=False, timeout=180)


@pytest.fixture
def scratch(tmp_path):
    before = _real_search_list()
    box = Scratch(tmp_path)
    box.make_keychain()
    try:
        yield box
    finally:
        box.security("delete-keychain", str(box.keychain), check=False)
        assert _real_search_list() == before, "the person's own keychain search list was changed"


def _old_style_identity(scratch: Scratch) -> tuple[str, str]:
    """"Cicada Local" made the way the old script's step 1 made it — its key labelled "Imported Private Key" and in
    the `apple-tool:` partition only. Returns (certificate hash, public-key hash)."""
    scratch.import_p12(scratch.make_p12("cicada", "Cicada Local"), "/usr/bin/codesign")
    (cert_hash,) = scratch.identities()
    key = scratch.public_key_hash(cert_hash)
    assert scratch.key_label(key) == "Imported Private Key"
    assert scratch.partitions(key) == ["apple-tool:"], "precondition: the key is not yet codesign's (apple:)"
    return cert_hash, key


def _signs_unattended(scratch: Scratch, cert_hash: str) -> None:
    target = scratch.tmp / "signed"
    shutil.copy("/usr/bin/true", target)
    scratch.run("codesign", "--force", "--sign", cert_hash, "--keychain", str(scratch.keychain), "--timestamp=none",
                str(target), timeout=20)
    shown = scratch.run("codesign", "-dvv", str(target)).stderr
    assert "Authority=Cicada Local" in shown


def test_a_fresh_keychain_gets_one_identity_authorised_and_proven(scratch):
    done = scratch.make_identity()
    assert done.returncode == 0, done.stderr
    assert "1/3 Created" in done.stdout and "2/3" in done.stdout and "3/3 codesign signs" in done.stdout
    (cert_hash,) = scratch.identities()
    assert cert_hash in done.stdout
    key = scratch.public_key_hash(cert_hash)
    assert scratch.partitions(key) == ["apple-tool:", "apple:"]
    assert not list((scratch.tmp / "tmp").glob("cicada-sign.*")), "the folder with the key is gone"
    _signs_unattended(scratch, cert_hash)


def test_a_rerun_after_the_old_step_2_failure_reuses_the_identity(scratch):
    cert_hash, key = _old_style_identity(scratch)
    # The owner's failure, reproduced: the old step 2 finds no key labelled "Cicada Local".
    old = scratch.security("set-key-partition-list", "-S", "apple-tool:,apple:", "-s", "-l", "Cicada Local",
                           "-k", PASSWORD, str(scratch.keychain), check=False)
    assert old.returncode != 0 and "could not be found" in old.stderr
    for _ in range(2):   # and once more: a second re-run changes nothing either
        done = scratch.make_identity()
        assert done.returncode == 0, done.stderr
        assert f"({cert_hash}) — kept" in done.stdout and "3/3 codesign signs" in done.stdout
        assert scratch.identities() == [cert_hash], "never a second identity"
        assert scratch.partitions(key) == ["apple-tool:", "apple:"]
    assert "Created" not in done.stdout
    _signs_unattended(scratch, cert_hash)


def test_an_unrelated_imported_private_key_is_left_exactly_as_it_was(scratch):
    scratch.import_p12(scratch.make_p12("other", "Other Tool"), "/usr/bin/codesign")
    (other_cert,) = scratch.identities("Other Tool")
    other_key = scratch.public_key_hash(other_cert)
    cert_hash, key = _old_style_identity(scratch)
    # Same label on both keys: no label could have told them apart.
    assert scratch.key_label(other_key) == scratch.key_label(key) == "Imported Private Key"
    before = scratch.private_keys()[other_key]
    assert scratch.partitions(other_key) == ["apple-tool:"]

    done = scratch.make_identity()
    assert done.returncode == 0, done.stderr
    assert scratch.private_keys()[other_key] == before, "label, attributes, access and partition list unchanged"
    assert scratch.partitions(other_key) == ["apple-tool:"]
    assert scratch.partitions(key) == ["apple-tool:", "apple:"]


def test_with_two_cicada_local_identities_only_the_chosen_ones_key_is_authorised(scratch):
    scratch.import_p12(scratch.make_p12("first", "Cicada Local"), "/usr/bin/codesign")
    scratch.import_p12(scratch.make_p12("second", "Cicada Local"), "/usr/bin/codesign")
    hashes = scratch.identities()
    assert len(hashes) == 2
    done = scratch.make_identity()
    assert done.returncode == 0, done.stderr
    chosen = re.search(r"\(([0-9A-F]{40})\) — kept", done.stdout).group(1)
    (other,) = [h for h in hashes if h != chosen]
    assert scratch.partitions(scratch.public_key_hash(chosen)) == ["apple-tool:", "apple:"]
    assert scratch.partitions(scratch.public_key_hash(other)) == ["apple-tool:"], "the other one is not touched"
    assert sorted(scratch.identities()) == sorted(hashes), "nothing created, nothing removed"
    _signs_unattended(scratch, chosen)


def test_a_refused_password_stops_at_step_2_and_names_it(scratch):
    _cert_hash, key = _old_style_identity(scratch)
    scratch.env["CICADA_KEYCHAIN_PASSWORD"] = "not-the-password"
    done = scratch.make_identity()
    assert done.returncode != 0
    assert "failed while authorising codesign" in done.stderr and "password was refused" in done.stderr
    assert "3/3" not in done.stdout, "no trial after a failed step — it would only meet the dialog"
    assert scratch.partitions(key) == ["apple-tool:"]
