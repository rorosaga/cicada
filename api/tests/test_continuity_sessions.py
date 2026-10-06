"""G110 slice 1a T1: the session registry outside every bank (plan C3).

Synthetic banks and ids only. The registry holds ids, a cwd hash and times;
merges are monotone so an out-of-order writer cannot move a time backwards;
nothing is ever written inside a configured bank."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import time
from datetime import datetime, timedelta, timezone

import pytest

from api.services import continuity_sessions as cs

SID = "11111111-2222-4333-8444-555555555555"
SID2 = "22222222-2222-4333-8444-555555555555"
EP = "ep_2026-10-06_001"
#: Relative to now, so no test here ever falls out of the 30-day window.
T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)


def _t(minutes: int) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    bank = root / "banks" / "alpha"
    (bank / "episodes").mkdir(parents=True)
    home = tmp_path / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    return {"root": root, "bank": bank, "home": home, "paths": (root, bank)}


def _apply(env, events, *, sid=SID, harness="claude-code", deadline=None):
    return cs.apply(env["bank"], bank_paths=env["paths"], harness=harness, session_id=sid, events=events,
                    deadline=deadline)


def _get(env, sid=SID, harness="claude-code"):
    return cs.get(env["bank"], harness, sid, bank_paths=env["paths"])


def _file(env):
    return cs.continuity_home(env["paths"]) / f"{cs.bank_file_id(env['bank'])}.json"


def test_round_trip_and_merge_rules(env):
    assert _apply(env, {"started_at": _t(5), "cwd_hash": cs.cwd_hash("/home/example/alpha")}) == "ok"
    assert _apply(env, {"started_at": _t(0)}) == "ok"          # earlier start wins
    assert _apply(env, {"last_prompt_at": _t(20)}) == "ok"
    assert _apply(env, {"last_prompt_at": _t(10)}) == "ok"      # a late, older prompt
    assert _apply(env, {"continues": EP}) == "ok"
    assert _apply(env, {"continues": "ep_2026-10-06_002", "cwd_hash": cs.cwd_hash("/elsewhere")}) == "ok"
    row = _get(env)
    assert row["started_at"] == _t(0)
    assert row["last_prompt_at"] == _t(20)
    assert row["continues"] == EP                                                      # first write wins
    assert row["cwd_hash"] == cs.cwd_hash("/home/example/alpha")
    assert row["harness"] == "claude-code"


def test_invalid_values_never_reach_the_file(env):
    sentinel = "/home/example/SENTINEL-ROOT-alpha"
    assert _apply(env, {"started_at": "yesterday", "continues": "../../etc", "cwd_hash": sentinel,
                        "last_prompt_at": _t(0).replace("+00:00", "")}) == "ok"   # naive time: dropped
    assert _apply(env, {"cwd_hash": cs.cwd_hash(sentinel), "extra": "x", "started_at": _t(1)}) == "ok"
    text = _file(env).read_text()
    assert "SENTINEL" not in text and "etc" not in text and "extra" not in text and "yesterday" not in text
    assert _get(env) == {"harness": "claude-code", "cwd_hash": cs.cwd_hash(sentinel), "started_at": _t(1)}
    assert _apply(env, {"started_at": _t(0)}, sid="../bad") == "error"
    assert _apply(env, {"started_at": _t(0)}, harness="cursor") == "error"


def test_unknown_keys_in_a_stored_file_are_dropped_on_read(env):
    _apply(env, {"started_at": _t(0)})
    data = json.loads(_file(env).read_text())
    key = f"claude-code:{SID}"
    data["rows"][key]["path"] = "/home/example/alpha"
    data["rows"]["claude-code:../x"] = {"harness": "claude-code"}
    _file(env).write_text(json.dumps(data))
    assert "path" not in _get(env)
    _apply(env, {"last_prompt_at": _t(1)})
    assert "/home" not in _file(env).read_text() and "../x" not in _file(env).read_text()


@pytest.mark.parametrize("where", ["root", "bank", "other_bank", "alias"])
def test_a_home_inside_any_configured_bank_is_refused(env, monkeypatch, tmp_path, where):
    other = env["root"] / "banks" / "beta"
    other.mkdir(parents=True)
    paths = (env["root"], env["bank"], other)
    if where == "alias":
        link = tmp_path / "alias"
        link.symlink_to(other, target_is_directory=True)
        home = link / "home"
    else:
        home = {"root": env["root"] / "h", "bank": env["bank"] / "h", "other_bank": other / "h"}[where]
    monkeypatch.setenv("CICADA_HOME", str(home))
    assert cs.continuity_home(paths) is None
    assert cs.apply(env["bank"], bank_paths=paths, harness="claude-code", session_id=SID,
                    events={"started_at": _t(0)}, deadline=None) == "unavailable"
    assert not home.exists()


def test_a_held_lock_answers_busy_within_the_deadline(env):
    _apply(env, {"started_at": _t(0)})
    lock = cs.continuity_home(env["paths"]) / f"{cs.bank_file_id(env['bank'])}.lock"
    fd = os.open(lock, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        started = time.monotonic()
        assert _apply(env, {"last_prompt_at": _t(1)}, deadline=time.monotonic() + 0.05) == "busy"
        assert time.monotonic() - started < 0.2
    finally:
        os.close(fd)
    assert _apply(env, {"last_prompt_at": _t(1)}, deadline=time.monotonic() - 1) == "skipped"


def test_same_name_banks_in_two_roots_get_two_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    a = tmp_path / "r1" / "banks" / "alpha"
    b = tmp_path / "r2" / "banks" / "alpha"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert cs.bank_file_id(a) != cs.bank_file_id(b)
    assert cs.bank_file_id(a).startswith("alpha-")


def test_file_modes(env):
    _apply(env, {"started_at": _t(0)})
    home = cs.continuity_home(env["paths"])
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    for f in home.iterdir():
        assert stat.S_IMODE(f.stat().st_mode) == 0o600, f.name
    assert not list(home.glob("*.tmp"))


def test_expiry_bounds_and_oversize(env, monkeypatch):
    _apply(env, {"started_at": (T0 - timedelta(days=31)).isoformat()}, sid=SID2)
    _apply(env, {"started_at": _t(0)})
    assert _get(env, sid=SID2) is None                                                   # expired
    monkeypatch.setattr(cs, "MAX_ROWS", 3)
    for i in range(4):
        _apply(env, {"started_at": _t(60 + i)}, sid=f"3333333{i}-2222-4333-8444-555555555555")
    rows = json.loads(_file(env).read_text())["rows"]
    assert len(rows) == 3 and f"claude-code:{SID}" not in rows                           # oldest evicted
    _file(env).write_bytes(b"x" * (cs.MAX_BYTES + 1))
    assert _get(env) is None
    assert _apply(env, {"started_at": _t(0)}) == "ok"


def test_errors_are_class_names_and_never_raise(env, monkeypatch):
    def boom(*a, **k):
        raise OSError("/home/example/secret-path")
    monkeypatch.setattr(cs, "_write", boom)
    assert _apply(env, {"started_at": _t(0)}) == "error"


def test_rows_for_cwd(env):
    h = cs.cwd_hash("/home/example/alpha")
    _apply(env, {"started_at": _t(0), "cwd_hash": h})
    _apply(env, {"started_at": _t(0), "cwd_hash": cs.cwd_hash("/x")}, sid=SID2)
    rows = cs.rows_for_cwd(env["bank"], h, bank_paths=env["paths"])
    assert [r["session_id"] for r in rows] == [SID] and rows[0]["harness"] == "claude-code"


def test_bank_paths_for_lists_the_root_and_every_bank(tmp_path):
    from api.services import bank_registry

    root = tmp_path / "memory"
    root.mkdir()
    bank_registry.create_bank(root, "beta", seed_owner=False)
    paths = cs.bank_paths_for(root)
    assert root in paths and bank_registry.bank_dir(root, "beta") in paths
