"""Pure parsing/hashing of the hook's supplied workspace observation (G110 B2).

No workspace I/O, resolution or subprocess. All persisted values are hashes/times.
Observed git identity associates repositories, never establishes task authority.

D2 amended (owner, 2026-10-29): the hook may also send ``remote_hash`` — its origin URL, normalised and hashed with
a per-install salt; the URL never reaches the backend. It keys a repository across a rename, a move and a fresh
clone on this install: ``remote_hash`` is the repository, ``remote_checkout_hash`` one checkout's place inside it
(the checkout top level relative to the folder holding the common git directory, lexically: ``.`` for the main
checkout, ``.worktrees/x`` for a worktree inside it). Records written before carry only the path keys and keep
matching by them; every comparison reads either key.
"""
from __future__ import annotations

import hashlib
import posixpath
import re
from datetime import datetime, timezone

HASH = re.compile(r"^[0-9a-f]{16}$")
HINT_AGE_S = 86400
KEYS = ("family_hash", "checkout_hash", "cwd_hash", "observed_at", "remote_hash", "remote_checkout_hash")
REMOTE_KEYS = ("remote_hash", "remote_checkout_hash")


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
    out = {**out, "family_hash": family, "checkout_hash": checkout}
    remote = [raw.get(k) for k in REMOTE_KEYS]
    if all(isinstance(v, str) and HASH.fullmatch(v) for v in remote):
        out.update(zip(REMOTE_KEYS, remote))
    return out


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
    out = {**base, "family_hash": digest(scope + "\0" + common), "checkout_hash": digest(scope + "\0" + root)}
    remote = raw.get("remote_hash")
    if isinstance(remote, str) and HASH.fullmatch(remote):
        place = posixpath.relpath(root, posixpath.dirname(common))
        out.update(remote_hash=remote, remote_checkout_hash=digest(remote + "\0" + place))
    return out


def current(raw, cwd, *, now=None) -> dict | None:
    value = clean(raw)
    if not value or not cwd or value["cwd_hash"] != digest(cwd) or "family_hash" not in value:
        return None
    age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(value["observed_at"])).total_seconds()
    return value if -5 <= age <= HINT_AGE_S else None


def same_path_checkout(left, right) -> bool:
    """The same checkout at the same place on disk (the pair's path keys)."""
    a, b = clean(left), clean(right)
    return bool(a and b and a.get("family_hash") and a.get("family_hash") == b.get("family_hash")
                and a.get("checkout_hash") == b.get("checkout_hash"))


def same_checkout(left, right) -> bool:
    """The same checkout: at the same path, or the same place in a repository with the same hashed remote — the
    folder was renamed, moved or cloned again (D2 amended 2026-10-29)."""
    if same_path_checkout(left, right):
        return True
    a, b = clean(left), clean(right)
    return bool(a and b and a.get("remote_checkout_hash")
                and a.get("remote_checkout_hash") == b.get("remote_checkout_hash"))


def same_family(left, right) -> bool:
    """The same repository: one git common directory, or one hashed remote."""
    a, b = clean(left), clean(right)
    if not (a and b):
        return False
    return bool((a.get("family_hash") and a.get("family_hash") == b.get("family_hash"))
                or (a.get("remote_hash") and a.get("remote_hash") == b.get("remote_hash")))
