"""The key that seals activity traces (G218), and who holds it — the ONE custody seam.

Traces are encrypted at rest (AES-256-GCM, :mod:`trace_seal`). Where the 32-byte key lives is behind
:class:`KeyProvider`, so the custody can change without touching the store:

* :class:`FileKeyProvider` — **the interim custody** (G218, 2026-10-23): ``$CICADA_HOME/traces.key``, 0600 in a 0700
  home, beside ``secrets.env`` and *outside* ``traces/``, so a copy of the store, a backup or a sync folder carries
  nothing readable. It is honest about its limit: anything running as the person can read the key as it can read
  ``secrets.env``. It never raises a GUI prompt, which is why it ships first.
* The Keychain and the Secure Enclave are the candidates an owner ruling picks between (``docs/architecture/storage.md``,
  "Activity traces"; G218): a Keychain item binds to the reader's code signature, so every developer build (and the
  Python backend, which is not the app) raises an access prompt; a Secure Enclave key cannot leave the chip and Python
  cannot use it at all, so the app would unwrap the data key and hand it to the backend over its token channel. Both
  need a signed, stable app identity first. Until the ruling, :func:`provider` returns the file key.

**Crypto-shredding.** :meth:`KeyProvider.destroy` is half of Wipe: with the key gone, any sealed byte left anywhere
(a backup taken before the exclusion, a stray copy) is noise.

A key file whose mode lets anyone but the owner read it, or that another user owns, is refused (:class:`KeyRefused`)
and never used: a key that may have been read is not a key.
"""
from __future__ import annotations

import base64
import os
import secrets
import stat
from pathlib import Path
from typing import Protocol

from api.services import runtime_layout

KEY_FILE_NAME = "traces.key"
KEY_BYTES = 32
_HEADER = "cicada-traces-key v1\n"


class KeyRefused(RuntimeError):
    """The key exists but is not safe to use (readable by others, another owner, malformed)."""


class KeyProvider(Protocol):
    """Where the traces key lives. Every method is synchronous, raises no GUI prompt and never logs the key."""

    def load(self) -> bytes | None:
        """The key, or ``None`` when none was ever made (traces never turned on, or wiped)."""

    def create(self) -> bytes:
        """Make and keep a new key; refuses to replace one that exists."""

    def destroy(self) -> None:
        """Forget the key for good (Wipe). Idempotent."""

    def describe(self) -> str:
        """One plain line for the Traces page: where the key is kept."""


class FileKeyProvider:
    """INTERIM (G218): a 0600 file. See the module docstring for what it protects and what it does not."""

    def __init__(self, path: Path | None = None):
        self._path = path

    @property
    def path(self) -> Path:
        return self._path or (runtime_layout.cicada_home() / KEY_FILE_NAME)

    def load(self) -> bytes | None:
        path = self.path
        try:
            st = path.stat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(st.st_mode):
            raise KeyRefused("the traces key is not a regular file")
        if st.st_mode & 0o077:
            raise KeyRefused("the traces key can be read by other accounts on this Mac; Cicada will not use it")
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise KeyRefused("the traces key belongs to another account")
        text = path.read_text(encoding="ascii", errors="replace")
        if not text.startswith(_HEADER):
            raise KeyRefused("the traces key file is not one Cicada wrote")
        try:
            key = base64.b64decode(text[len(_HEADER):].strip(), validate=True)
        except (ValueError, TypeError):
            raise KeyRefused("the traces key file is damaged") from None
        if len(key) != KEY_BYTES:
            raise KeyRefused("the traces key file is damaged")
        return key

    def create(self) -> bytes:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        key = secrets.token_bytes(KEY_BYTES)
        data = (_HEADER + base64.b64encode(key).decode("ascii") + "\n").encode("ascii")
        # O_EXCL: never replace a key that exists (that would shred the store silently); 0600 from the first byte.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        exclude_from_backup(path)
        return key

    def destroy(self) -> None:
        path = self.path
        try:
            size = path.stat().st_size
            # Overwrite before unlinking: on APFS this is best effort (copy-on-write), the unlink is what counts.
            with open(path, "r+b") as fh:
                fh.write(b"\0" * size)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def describe(self) -> str:
        return "a key file only your account can read, kept apart from the traces"


def provider() -> KeyProvider:
    """The custody in force. INTERIM (G218): the 0600 file until the owner rules on the Keychain or Secure Enclave."""
    return FileKeyProvider()


_BACKUP_XATTR = b"com.apple.metadata:com_apple_backup_excludeItem"


def exclude_from_backup(path: Path) -> bool:
    """Ask Time Machine to skip ``path`` (the sticky exclusion ``tmutil addexclusion`` writes). macOS only, best
    effort, no subprocess and no network; ``False`` when it could not be set."""
    import sys

    if sys.platform != "darwin":
        return False
    try:
        import ctypes
        import plistlib

        libc = ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
        value = plistlib.dumps("com.apple.backupd", fmt=plistlib.FMT_BINARY)
        rc = libc.setxattr(str(path).encode("utf-8"), _BACKUP_XATTR, value, len(value), 0, 0)
        return rc == 0
    except Exception:  # noqa: BLE001 — a backup hint never fails a write
        return False
