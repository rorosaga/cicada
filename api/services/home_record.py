"""The home's hand-off record: which device holds the memory now (G132 phase 2, ruling 51a).

One file in the bank, ``_home.json``, committed alone as the last commit of the home it names as leaving (a move) or
as the first commit of the replica that takes over (a take-over). Every device reads it from the history it follows,
so every device learns the new home **from the commit itself**, at the same sequence number:

    {"v": 1, "bankId", "term", "kind": "move" | "take-over", "seq", "after",
     "from": {"device", "name"}, "to": {"device", "name"}, "at", "signer", "key", "sig"}

* ``term`` grows by one with every hand-off (a bank with no record is term 0, its home whoever publishes it). A device
  that sees a record of a higher term than the one it acts under stops ordering writes at once: the term is the fence
  that keeps two homes from both admitting (``home_move``).
* ``seq`` / ``after``: the sequence number and commit the record follows — the last write the old home ordered, or on a
  take-over the newest commit the taker had (the take-over point: anything the lost home ordered after it is set aside
  and offered back as transactions, never merged).
* ``signer`` / ``key`` / ``sig``: the device that wrote the record, its public key (``device_key``) and an ES256
  signature over the canonical bytes of everything else. A reader accepts the record only when the signature holds
  AND the key's thumbprint is the one the registry (``device_tokens``' ``sign_jwk``) holds for that signer.

Device ids and the names the person gave them — never an address, a token or anything from a page. The record is
written only through :func:`commit` (``git_service.commit_contents_sync``: exactly these bytes, nothing else staged
rides in), inside ``replica_guard.applying()`` — the one bank write allowed while the home is closed to writes.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

FILE = "_home.json"
KINDS = ("move", "take-over")
TRIGGER = "sync/handoff"


@dataclass(frozen=True)
class Record:
    data: dict

    @property
    def term(self) -> int:
        try:
            return int(self.data.get("term") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def to(self) -> str | None:
        return (self.data.get("to") or {}).get("device")

    @property
    def to_name(self) -> str:
        return str((self.data.get("to") or {}).get("name") or "another computer")

    @property
    def source(self) -> str | None:
        return (self.data.get("from") or {}).get("device")

    @property
    def source_name(self) -> str:
        return str((self.data.get("from") or {}).get("name") or "the last home")

    @property
    def kind(self) -> str:
        return str(self.data.get("kind") or "move")

    @property
    def bank_id(self) -> str | None:
        return self.data.get("bankId")

    @property
    def seq(self) -> int:
        try:
            return int(self.data.get("seq") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def after(self) -> str | None:
        return self.data.get("after") or None

    @property
    def signer(self) -> str | None:
        return self.data.get("signer")

    def wire(self) -> dict:
        """What a route shows: no key, no signature."""
        return {k: self.data.get(k) for k in ("term", "kind", "seq", "from", "to", "at")}


def canonical(data: dict) -> bytes:
    body = {k: v for k, v in data.items() if k != "sig"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def make(*, bank_id: str, term: int, kind: str, seq: int, after: str | None, source: dict, to: dict,
         signer: str) -> Record:
    """A signed record, by this computer's key (``device_key``)."""
    from api.services import device_key

    if kind not in KINDS:
        raise ValueError("kind")
    data = {"v": 1, "bankId": bank_id, "term": int(term), "kind": kind, "seq": int(seq), "after": after,
            "from": {"device": source.get("device"), "name": source.get("name")},
            "to": {"device": to.get("device"), "name": to.get("name")},
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "signer": signer, "key": device_key.public_jwk(create=True)}
    data["sig"] = device_key.sign(canonical(data))
    return Record(data)


def encode(record: Record) -> bytes:
    return (json.dumps(record.data, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def parse(raw: bytes | str | None) -> Record | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return Record(data) if isinstance(data, dict) and data.get("v") == 1 else None


def at(memory_path, rev: str = "HEAD") -> Record | None:
    """The record ``rev`` holds, or None (no record: term 0). A read."""
    try:
        proc = subprocess.run(["git", "cat-file", "blob", f"{rev}:{FILE}"], cwd=str(memory_path),
                              capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse(proc.stdout) if proc.returncode == 0 else None


def verify(record: Record, thumbprint: str | None) -> str | None:
    """None when the record holds: its signature checks under its key AND that key is ``thumbprint`` — the one the
    registry holds for the signer. Otherwise the reason, one of ``unsigned``, ``bad_signature``, ``unknown_signer``,
    ``wrong_key``."""
    from api.services import device_key

    key, sig = record.data.get("key"), record.data.get("sig")
    if not isinstance(key, dict) or not isinstance(sig, str):
        return "unsigned"
    if not device_key.verify(key, canonical(record.data), sig):
        return "bad_signature"
    if not thumbprint:
        return "unknown_signer"
    return None if device_key.thumbprint(key) == thumbprint else "wrong_key"


def commit(memory_path: Path, record: Record, *, subject: str) -> str:
    """Commit the record alone (``git_service.commit_contents_sync``) and put the same bytes in the working tree.
    Called inside ``replica_guard.applying()``. Returns the new HEAD."""
    from api.services import git_service

    memory_path = Path(memory_path)
    raw = encode(record)
    message = git_service.build_commit_message(
        subject, [f"{FILE}: updated (source: n/a, trigger: {TRIGGER})"], authors=[git_service.CICADA_AUTHOR])
    with git_service.write_lock(memory_path):
        git_service.commit_contents_sync(memory_path, {FILE: raw}, message)
        git_service._write_atomically(memory_path / FILE, raw)   # noqa: SLF001 — the page rule, the tree = HEAD
        return git_service._git_sync(memory_path, "rev-parse", "HEAD").strip()   # noqa: SLF001
