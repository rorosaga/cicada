"""Pure backend observation validation and monotone registry hints."""
from datetime import datetime, timedelta, timezone

import pytest

from _continuity_fixtures import sid
from api.services import continuity_sessions as sessions, workspace_identity as wi
from test_workspace_continuity import observation


@pytest.mark.parametrize("cwd", ["relative/path", "/alpha\nproject", "/" + "x" * 4097])
def test_invalid_declared_cwd_falls_back_without_error(cwd):
    assert wi.parse(cwd, observation(cwd, "/alpha", "/alpha/.git")) is None


@pytest.mark.parametrize("change", [{"repo_root": "relative"}, {"common_dir": "/a\n/b"},
                                   {"repo_root": "/other"}, {"scope_hash": "wrong"},
                                   {"cwd_hash": "f" * 16}, {"observed_at": "2026-10-07"},
                                   {"common_dir": None}])
def test_malformed_values_are_ignored_not_persisted(change):
    raw = observation("/alpha/src", "/alpha", "/metadata")
    value = wi.parse("/alpha/src", {**raw, **change})
    if "cwd_hash" in change or "observed_at" in change:
        assert value is None  # Cannot establish binding or freshness.
    else:
        assert value == {"cwd_hash": raw["cwd_hash"], "observed_at": raw["observed_at"]}


def test_plain_paths_become_only_scoped_hashes_and_timestamp():
    raw = observation("/alpha/src", "/alpha", "/metadata")
    value = wi.parse("/alpha/src", {**raw, "title": "must not persist"})
    assert set(value) == set(wi.KEYS)
    assert all("/" not in str(v) and "persist" not in str(v) for v in value.values())
    other = wi.parse("/alpha/src", {**raw, "scope_hash": "b" * 16})
    assert value["family_hash"] != other["family_hash"] and not wi.same_checkout(value, other)
    stale = dict(value, observed_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    assert wi.current(stale, "/alpha/src") is None
    assert wi.current(value, "/alpha/other") is None


def test_registry_keeps_newest_observation_and_failed_hint_without_paths(tmp_path):
    bank = tmp_path / "bank"
    bank.mkdir()
    now = datetime.now(timezone.utc)
    old = wi.parse("/alpha", observation("/alpha", "/alpha", "/metadata", when=(now - timedelta(seconds=2)).isoformat()))
    failed = {"cwd_hash": wi.digest("/alpha"), "observed_at": now.isoformat()}
    for value in (failed, old):
        assert sessions.apply(bank, bank_paths=(bank,), harness="codex", session_id=sid(1),
                              events={"workspace_identity": value}, deadline=None) == "ok"
    row = sessions.get(bank, "codex", sid(1), bank_paths=(bank,))
    assert row["workspace_identity"] == failed and "started_at" not in row
