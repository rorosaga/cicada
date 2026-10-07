"""Pure parsing/hashing of the hook's supplied workspace observation (G110 B2).

No workspace I/O, resolution or subprocess. All persisted values are hashes/times.
Observed git identity associates repositories, never establishes task authority.
"""
from __future__ import annotations

import hashlib
import posixpath
import re
from datetime import datetime, timezone

HASH = re.compile(r"^[0-9a-f]{16}$")
HINT_AGE_S = 86400
KEYS = ("family_hash", "checkout_hash", "cwd_hash", "observed_at")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()[:16]


def stamp(value) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else None
    except ValueError:
        return None


def clean(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    at = stamp(raw.get("observed_at"))
    cwd = raw.get("cwd_hash")
    if not at or not isinstance(cwd, str) or not HASH.fullmatch(cwd):
        return None
    out = {"cwd_hash": cwd, "observed_at": at}
    family, checkout = raw.get("family_hash"), raw.get("checkout_hash")
    if family is None and checkout is None:
        return out  # A failed observation supersedes an older success.
    if not all(isinstance(v, str) and HASH.fullmatch(v) for v in (family, checkout)):
        return None
    return {**out, "family_hash": family, "checkout_hash": checkout}


def _path(value) -> str | None:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 4096 \
            or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return posixpath.normpath(value)


def parse(cwd, raw, *, now=None) -> dict | None:
    """A fresh cwd-bound observation; malformed git values record a failed hint."""
    if not _path(cwd) or not isinstance(raw, dict) or raw.get("cwd_hash") != digest(cwd):
        return None
    at = stamp(raw.get("observed_at"))
    now = now or datetime.now(timezone.utc)
    if not at or not -5 <= (now - datetime.fromisoformat(at)).total_seconds() <= 300:
        return None
    base = {"cwd_hash": digest(cwd), "observed_at": at}
    if "repo_root" not in raw and "common_dir" not in raw:
        return base
    root, common, scope = _path(raw.get("repo_root")), _path(raw.get("common_dir")), raw.get("scope_hash")
    if not root or not common or not isinstance(scope, str) or not HASH.fullmatch(scope):
        return base
    if posixpath.commonpath([posixpath.normpath(cwd), root]) != root:
        return base
    return {**base, "family_hash": digest(scope + "\0" + common), "checkout_hash": digest(scope + "\0" + root)}


def current(raw, cwd, *, now=None) -> dict | None:
    value = clean(raw)
    if not value or not cwd or value["cwd_hash"] != digest(cwd) or "family_hash" not in value:
        return None
    age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(value["observed_at"])).total_seconds()
    return value if -5 <= age <= HINT_AGE_S else None


def same_checkout(left, right) -> bool:
    a, b = clean(left), clean(right)
    return bool(a and b and a.get("family_hash") and a.get("family_hash") == b.get("family_hash")
                and a.get("checkout_hash") == b.get("checkout_hash"))
