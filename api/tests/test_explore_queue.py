"""G166 exploring — the explore queue: claims, leases, one live lease per site, pacing, expiry, release, the
idempotent record and the three-try failure. Synthetic keys only; the queue file lives in the test's CICADA_HOME."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from api.services import explore_queue as eq
from api.services import media_ingestor

T0 = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


def _at(minutes: float = 0, seconds: float = 0) -> datetime:
    return T0 + timedelta(minutes=minutes, seconds=seconds)


def _key(url: str) -> str:
    return media_ingestor.url_hash(url)


A1, A2, B1, C1 = (f"https://{h}" for h in ("alpha.example.com/", "alpha.example.com/pricing", "beta.example.com/",
                                           "gamma.example.com/"))
SITES = [{"key": _key(A1), "site": "example.com", "depth": "capture"},
         {"key": _key(A2), "site": "example.com", "depth": "look"},
         {"key": _key(B1), "site": "beta.example.org", "depth": "capture"},
         {"key": _key(C1), "site": "gamma.example.net", "depth": "product"}]


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    return memory


def _start(bank, now=T0, sites=SITES, **kw):
    return eq.start(bank, sites, started_by=kw.pop("started_by", {"kind": "person"}), now=now, **kw)


def test_start_stores_keys_only_and_stamps_who_started(bank):
    batch = _start(bank, started_by={"kind": "agent", "harness": "claude-code", "session": "s1"})
    assert batch["total"] == 4 and batch["queued"] == 4 and batch["startedBy"]["kind"] == "agent"
    raw = eq.path_for(bank).read_text()
    assert "example.com/" not in raw and "pricing" not in raw, "no URL is ever stored in the queue"
    assert eq.path_for(bank).stat().st_mode & 0o777 == 0o600
    view = eq.batch_view(eq.view(bank, T0), T0)
    assert view["startedBy"] == {"kind": "agent", "harness": "claude-code", "session": "s1"}
    assert not (bank / "explore_queue").exists(), "the queue lives outside the bank"


def test_a_malformed_selection_writes_nothing(bank):
    with pytest.raises(eq.QueueError):
        eq.start(bank, [{"key": "nothex", "site": "example.com"}], started_by={"kind": "person"}, now=T0)
    with pytest.raises(eq.QueueError):
        eq.start(bank, [], started_by={"kind": "person"}, now=T0)
    assert not eq.path_for(bank).exists()


def test_one_live_lease_per_site_across_sessions(bank):
    _start(bank)
    first = eq.claim(bank, session="s1", harness="claude-code", limit=5, now=T0)
    sites = [r["site"] for r in first]
    assert len(sites) == len(set(sites)) == 3, "two pages of one site are never leased at once"
    second = eq.claim(bank, session="s2", harness="claude-code", limit=5, now=T0)
    assert second == [], "every free site is held; the second page of example.com waits for its site"
    assert all(len(r["lease_token"]) == 32 for r in first)


def test_default_claim_is_one_and_the_cap_is_five(bank):
    _start(bank)
    assert len(eq.claim(bank, session="s1", harness="h", now=T0)) == 1
    assert len(eq.claim(bank, session="s2", harness="h", limit=99, now=T0)) <= eq.CLAIM_MAX


def test_pacing_holds_a_site_for_eight_seconds_after_a_page(bank):
    _start(bank, sites=SITES[:2])
    (row,) = eq.claim(bank, session="s1", harness="h", now=T0)
    eq.complete(bank, row["key"], row["lease_token"], outcome="captured", capture_id="c", session="s1", now=_at(0, 30))
    assert eq.claim(bank, session="s2", harness="h", now=_at(0, 33)) == [], "8 s between pages of one site"
    (nxt,) = eq.claim(bank, session="s2", harness="h", now=_at(0, 39))
    assert nxt["site"] == "example.com"


def test_loads_an_hour_are_capped(bank):
    many = [{"key": f"{i:012x}", "site": "example.com"} for i in range(eq.MAX_LOADS_HOUR + 2)]
    _start(bank, sites=many)
    now = T0
    for _ in range(eq.MAX_LOADS_HOUR):
        (row,) = eq.claim(bank, session="s", harness="h", now=now)
        eq.complete(bank, row["key"], row["lease_token"], outcome="captured", session="s", now=now)
        now += timedelta(seconds=eq.PACE_SECONDS + 1)
    assert eq.claim(bank, session="s", harness="h", now=now) == [], "30 loads an hour on one site, at most"
    assert eq.claim(bank, session="s", harness="h", now=T0 + timedelta(hours=1, minutes=1))


def test_a_lease_lapses_after_fifteen_minutes_and_three_lapses_fail_the_row(bank):
    _start(bank, sites=SITES[:1])
    for attempt in range(1, 4):
        (row,) = eq.claim(bank, session=f"s{attempt}", harness="h", now=_at(20 * (attempt - 1)))
        assert row["attempts"] == attempt - 1
    data = eq.view(bank, _at(60), holding=lambda: False)
    (row,) = data["items"]
    assert row["state"] == "failed" and row["failed"]["code"] == "failed" and row["attempts"] == 3
    assert eq.claim(bank, session="s9", harness="h", now=_at(61)) == []


def test_a_lapse_is_not_judged_while_sleep_holds_the_pages(bank):
    _start(bank, sites=SITES[:1])
    eq.claim(bank, session="s1", harness="h", now=T0)
    data = eq.view(bank, _at(30), holding=lambda: True)
    assert data["items"][0]["state"] == "claimed", "a long drain never burns a site's attempts (P5)"


def test_any_call_from_a_session_extends_its_leases(bank):
    _start(bank)
    (row,) = eq.claim(bank, session="s1", harness="h", now=T0)
    eq.claim(bank, session="s1", harness="h", now=_at(14))
    status, _ = eq.lease_status(bank, row["key"], row["lease_token"], session="s1", now=_at(20))
    assert status == "ok"


def test_a_record_is_idempotent_on_its_lease_token(bank):
    _start(bank, sites=SITES[:1])
    (row,) = eq.claim(bank, session="s1", harness="h", now=T0)
    assert eq.lease_status(bank, row["key"], row["lease_token"], session="s1", now=_at(1))[0] == "ok"
    first = eq.complete(bank, row["key"], row["lease_token"], outcome="captured", capture_id="c1", session="s1",
                        now=_at(2))
    before = eq.path_for(bank).read_bytes()
    again = eq.complete(bank, row["key"], row["lease_token"], outcome="captured", capture_id="c2", session="s1",
                        now=_at(3))
    assert again == first and again["capture_id"] == "c1"
    status, result = eq.lease_status(bank, row["key"], row["lease_token"], session="s1", now=_at(4))
    assert status == "duplicate" and result["capture_id"] == "c1"
    assert json.loads(before)["results"] == json.loads(eq.path_for(bank).read_bytes())["results"]
    batch = eq.batch_view(eq.view(bank, _at(4)), _at(4))
    assert batch["done"] == 1 and batch["outcomes"] == {"captured": 1}


def test_a_late_record_is_accepted_unless_another_agent_holds_the_site(bank):
    _start(bank, sites=SITES[:1])
    (row,) = eq.claim(bank, session="s1", harness="h", now=T0)
    status, _ = eq.lease_status(bank, row["key"], row["lease_token"], session="s1", now=_at(16))
    assert status == "late", "the lease lapsed and nobody else holds it: the work is not wasted"
    (other,) = eq.claim(bank, session="s2", harness="h", now=_at(17))
    assert eq.lease_status(bank, row["key"], row["lease_token"], session="s1", now=_at(18))[0] == "taken"
    assert eq.lease_status(bank, row["key"], "f" * 32, session="s1", now=_at(18))[0] == "unknown"
    assert eq.lease_status(bank, row["key"], other["lease_token"], session="s2", now=_at(18))[0] == "ok"


def test_a_wall_pauses_the_whole_site_for_seven_days(bank):
    _start(bank)
    (row,) = [r for r in eq.claim(bank, session="s1", harness="h", limit=5, now=T0) if r["site"] == "example.com"]
    url = A1 if row["key"] == _key(A1) else A2
    out = eq.release(bank, [{"url": url, "code": "needs_login", "reason": "a sign-in page"}], session="s1", now=_at(1),
                     key_of=_key)
    assert out == [(url, "paused")]
    data = eq.view(bank, _at(2))
    paused = [r for r in data["items"] if r["site"] == "example.com"]
    assert {r["state"] for r in paused} == {"paused"} and len(paused) == 2
    assert eq.claim(bank, session="s2", harness="h", limit=5, now=_at(3)) == []
    assert eq.batch_view(data, _at(2))["needsLogin"] == 2
    back = eq.view(bank, _at(60 * 24 * 7 + 1))
    assert {r["state"] for r in back["items"] if r["site"] == "example.com"} == {"queued"}


def test_the_person_asking_again_lifts_a_pause(bank):
    _start(bank, sites=SITES[:2])
    (row,) = eq.claim(bank, session="s1", harness="h", now=T0)
    eq.release(bank, [{"url": A1 if row["key"] == _key(A1) else A2, "code": "blocked"}], session="s1", now=_at(1),
               key_of=_key)
    assert eq.resume_site(bank, "example.com", now=_at(2)) == 2
    assert eq.claim(bank, session="s1", harness="h", now=_at(3))


def test_release_only_by_the_holder_and_other_codes_fail_the_row(bank):
    _start(bank, sites=SITES[2:3])
    eq.claim(bank, session="s1", harness="h", now=T0)
    assert eq.release(bank, [{"url": B1, "code": "gone"}], session="s2", now=_at(1), key_of=_key) == \
        [(B1, "not_yours")]
    assert eq.release(bank, [{"url": B1, "code": "gone", "reason": "sk-" + "A1b2C3d4E5f6G7h8J9k0"}], session="s1",
                      now=_at(1), key_of=_key) == [(B1, "released")]
    (row,) = eq.view(bank, _at(2))["items"]
    assert row["state"] == "failed" and row["failed"]["code"] == "gone"
    assert "A1b2C3d4" not in row["failed"]["reason"], "a release reason is scrubbed"
    assert eq.retry(bank, row["key"], now=_at(3))["state"] == "queued"


def test_stop_drops_waiting_sites_and_lets_a_held_one_finish(bank):
    _start(bank)
    (held,) = eq.claim(bank, session="s1", harness="h", now=T0)
    out = eq.stop(bank, now=_at(1))
    assert out == {"stopped": True, "dropped": 3, "finishing": 1}
    data = eq.view(bank, _at(1))
    assert [r["key"] for r in data["items"]] == [held["key"]]
    assert eq.batch_view(data, _at(1))["stoppedAt"]


def test_stamp_moves_when_a_lease_lapses_with_nothing_written(bank):
    _start(bank, sites=SITES[:1])
    eq.claim(bank, session="s1", harness="h", now=T0)
    before = eq.stamp(bank, _at(1))
    after = eq.stamp(bank, _at(16), holding=lambda: False)
    assert before != after and after.endswith(":1:0")
    assert eq.next_change_at(bank, _at(1)) == "2026-10-14T12:15:00Z"


def test_the_eta_counts_the_agents_working(bank):
    _start(bank, sites=[{"key": f"{i:012x}", "site": f"s{i}.example.com"} for i in range(9)])
    rows = eq.claim(bank, session="s1", harness="h", limit=1, now=T0)
    eq.complete(bank, rows[0]["key"], rows[0]["lease_token"], outcome="captured", session="s1", now=_at(1))
    eq.claim(bank, session="s1", harness="h", limit=1, now=_at(1))
    eq.claim(bank, session="s2", harness="h", limit=1, now=_at(1))
    view = eq.batch_view(eq.view(bank, _at(1)), _at(1))
    assert view["agents"] == 2 and view["claimed"] == 2 and view["waiting"] == 6
    assert view["etaMinutes"] == 4, "60 s a site × 8 sites ÷ 2 agents"


def test_a_waiting_site_that_stopped_being_eligible_leaves_the_run_as_skipped(bank):
    _start(bank)
    eligible = {_key(B1), _key(C1)}
    rows = eq.claim(bank, session="s1", harness="h", limit=5, saved=eligible, now=T0)
    assert {r["key"] for r in rows} == eligible
    data = eq.view(bank, T0)
    assert {r["key"] for r in data["items"]} == eligible, "the example.com pages left the queue"
    assert eq.batch_view(data, T0)["outcomes"] == {"skipped": 2}
    assert eq.claim(bank, session="s2", harness="h", saved=set(), now=T0) == [], "an empty index never wipes the run"


@pytest.mark.parametrize("code", ["failed", "not_found", "gone", "skipped", "needs_login"])
def test_a_hand_back_paces_the_site_like_a_record(bank, code):
    many = [{"key": f"{i:012x}", "site": "example.com"} for i in range(3)]
    _start(bank, sites=many)
    (row,) = eq.claim(bank, session="s1", harness="h", now=T0)
    url = "https://example.com/handed-back"
    out = eq.release(bank, [{"url": url, "code": code}], session="s1", now=_at(0, 1), key_of=lambda u: row["key"])
    assert out[0][1] in ("released", "skipped", "paused")
    info = eq.view(bank, _at(0, 2))["sites"]["example.com"]
    assert len(info["loads"]) == 1, "the hand-back counts a page load"
    if code != "needs_login":
        assert eq.claim(bank, session="s2", harness="h", now=_at(0, 5)) == [], "8 s before the next page of the site"
        assert eq.claim(bank, session="s2", harness="h", now=_at(0, 10))


def test_a_late_record_never_removes_another_agents_live_reclaim(bank):
    _start(bank, sites=SITES[:1])
    (first,) = eq.claim(bank, session="a", harness="h", now=T0)
    (second,) = eq.claim(bank, session="b", harness="h", now=_at(16))   # A's lease lapsed; B re-claimed
    late = eq.complete(bank, first["key"], first["lease_token"], outcome="captured", capture_id="cA", session="a",
                       now=_at(17))
    assert late["capture_id"] == "cA"
    (row,) = eq.view(bank, _at(17))["items"]
    assert row["state"] == "claimed" and row["lease_token"] == second["lease_token"], "B keeps its live lease"
    assert eq.lease_status(bank, second["key"], second["lease_token"], session="b", now=_at(18))[0] == "ok"
    eq.complete(bank, second["key"], second["lease_token"], outcome="captured", capture_id="cB", session="b",
                now=_at(30))
    assert eq.view(bank, _at(30))["items"] == [], "B's own record completes the row"


def test_concurrent_late_and_live_records_keep_the_live_lease(bank):
    import threading

    _start(bank, sites=SITES[:1])
    (first,) = eq.claim(bank, session="a", harness="h", now=T0)
    (second,) = eq.claim(bank, session="b", harness="h", now=_at(16))
    barrier = threading.Barrier(2)

    def late():
        barrier.wait()
        eq.complete(bank, first["key"], first["lease_token"], outcome="captured", session="a", now=_at(17))

    def refresh():
        barrier.wait()
        eq.lease_status(bank, second["key"], second["lease_token"], session="b", now=_at(17))

    threads = [threading.Thread(target=late), threading.Thread(target=refresh)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    (row,) = eq.view(bank, _at(18))["items"]
    assert row["lease_token"] == second["lease_token"] and row["state"] == "claimed"
