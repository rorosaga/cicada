"""G141 PJ-0b (R-HP1, R-HP3, R-HP4, R-HP9, R-HP11): the pending store — names
Sleep parked, and since PJ-0b the claims it heard about them — as one module
that owns `pending_entities.jsonl`. A holding line leaves the store only
through `release`; promotion keeps it, a re-park carries it, nothing expires
it. Synthetic names only."""
from __future__ import annotations

import pytest

from api.services import pending_store
from api.services.claims import Claim, Evidence
from api.services.pending_store import HoldOutcome, PendingEntity
from api.services.vector_index import SqliteVecIndexer

EP = "ep_2026-09-20_001"
LEGACY = ('{"name": "Zed Unknown", "type": "person", "description": "Mentioned once.", '
          '"source_episode": "ep_2026-09-20_001", "confidence": 0.6, "tags": [], "history_entries": []}\n')


def _pending(name: str, **overrides) -> PendingEntity:
    fields = dict(name=name, type="person", description="Mentioned once.", source_episode=EP,
                  confidence=0.6, tags=[], history_entries=[])
    fields.update(overrides)
    return PendingEntity(**fields)


def _claim(cid: str, subject: str = "zed-unknown", obj: str = "gamma-board", *, start: int = 6) -> Claim:
    return Claim(id=cid, text=f"{subject} recommends {obj}", subject=subject, predicate="recommends",
                 object=obj, valid_from="2026-09-20", source_episodes=[EP],
                 evidence=[Evidence(episode=EP, start=start, end=start + 10, kind="user", hash="abc123def456")])


def _store_text(tmp_path) -> str:
    return (tmp_path / pending_store.PENDING_STORE_FILE).read_text(encoding="utf-8")


def test_a_line_written_before_pj0b_round_trips_byte_for_byte(tmp_path):
    (tmp_path / pending_store.PENDING_STORE_FILE).write_text(LEGACY, encoding="utf-8")
    (line,) = pending_store.load(tmp_path)
    assert line.held_claims == [] and "held_claims" not in line.to_dict()
    pending_store.save(tmp_path, [line])
    assert _store_text(tmp_path) == LEGACY


def test_held_claims_round_trip_as_the_claims_they_were(tmp_path):
    claim = _claim("clm_a")
    pending_store.save(tmp_path, [_pending("Zed Unknown", held_claims=[claim.to_dict()])])
    (line,) = pending_store.load(tmp_path)
    assert Claim.from_dict(line.held_claims[0]) == claim


def test_hold_goes_to_the_line_whose_slug_is_the_subject(tmp_path):
    pending_store.upsert(tmp_path, _pending("Zed Unknown"))
    pending_store.upsert(tmp_path, _pending("Gamma Board", type="tool"))
    out = pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")], "nobody-here": [_claim("clm_b")]})
    assert out == {"zed-unknown": HoldOutcome(1, 0), "nobody-here": HoldOutcome(0, 0)}
    held = {e.name: [d["id"] for d in e.held_claims] for e in pending_store.load(tmp_path)}
    assert held == {"Zed Unknown": ["clm_a"], "Gamma Board": []}


def test_hold_writes_nothing_when_no_line_matches(tmp_path):
    assert pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")]}) == {"zed-unknown": HoldOutcome(0, 0)}
    assert pending_store.hold(tmp_path, {"zed-unknown": []}) == {}
    assert not (tmp_path / pending_store.PENDING_STORE_FILE).exists()


def test_a_claim_heard_again_merges_its_evidence_by_id(tmp_path):
    pending_store.upsert(tmp_path, _pending("Zed Unknown"))
    pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a", start=6)]})
    again = _claim("clm_a", start=40)
    again.source_episodes = ["ep_2026-09-21_001"]
    assert pending_store.hold(tmp_path, {"zed-unknown": [again]}) == {"zed-unknown": HoldOutcome(1, 0)}
    (line,) = pending_store.load(tmp_path)
    (held,) = line.held_claims
    assert [e["start"] for e in held["evidence"]] == [6, 40]
    assert held["source_episodes"] == [EP, "ep_2026-09-21_001"]


def test_the_cap_is_head_stable_and_counts_what_it_refuses(tmp_path):
    pending_store.upsert(tmp_path, _pending("Zed Unknown"))
    first = pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a"), _claim("clm_b"), _claim("clm_c")]}, cap=2)
    assert first == {"zed-unknown": HoldOutcome(2, 1)}
    later = pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_d"), _claim("clm_a")]}, cap=2)
    assert later == {"zed-unknown": HoldOutcome(1, 1)}  # clm_a merges; clm_d is refused
    (line,) = pending_store.load(tmp_path)
    assert [d["id"] for d in line.held_claims] == ["clm_a", "clm_b"]
    assert pending_store.MAX_HELD_CLAIMS == 50


def test_a_same_name_re_park_carries_the_hold(tmp_path):
    pending_store.upsert(tmp_path, _pending("Zed Unknown"))
    pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")]})
    SqliteVecIndexer(tmp_path).index_pending_entity(_pending("zed unknown", description="Parked again."))
    (line,) = pending_store.load(tmp_path)
    assert line.description == "Parked again." and [d["id"] for d in line.held_claims] == ["clm_a"]


def test_promotion_keeps_a_holding_line_and_removes_a_plain_one(tmp_path, monkeypatch):
    rebuilt: list[list[str]] = []
    monkeypatch.setattr(SqliteVecIndexer, "_rebuild_pending_index",
                        lambda self, entries: rebuilt.append([e.name for e in entries]))
    indexer = SqliteVecIndexer(tmp_path)
    indexer.index_pending_entity(_pending("Gamma Board", type="tool"))
    indexer.index_pending_entity(_pending("Zed Unknown"))
    pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")]})

    holding = indexer.promote_from_pending("zed unknown")
    assert holding is not None and [d["id"] for d in holding.held_claims] == ["clm_a"]
    assert indexer.pending_by_name("Zed Unknown") is not None and rebuilt == []

    plain = indexer.promote_from_pending("Gamma Board")
    assert plain is not None and plain.name == "Gamma Board"
    assert indexer.pending_by_name("Gamma Board") is None and rebuilt == [["Zed Unknown"]]
    assert indexer.promote_from_pending("Nobody Here") is None


def test_no_path_but_release_lets_a_held_claim_go(tmp_path, monkeypatch):
    """R-HP4/R-HP9 — the brief's "expired or dropped" case: nothing expires a
    pending line today, so the guarantee is structural. Every path that can
    rewrite or remove a line keeps or carries its hold; `release` is the only
    exit, and Stage 5.56 calls it only after the page write succeeded."""
    monkeypatch.setattr(SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    indexer = SqliteVecIndexer(tmp_path)
    indexer.index_pending_entity(_pending("Zed Unknown"))
    pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")]})
    indexer.index_pending_entity(_pending("Zed Unknown"))            # re-parked
    indexer.promote_from_pending("Zed Unknown")                        # promoted
    indexer.index_pending_entity(_pending("Gamma Board", type="tool"))  # another name parked
    assert pending_store.waiting(tmp_path) == (1, 1)
    assert pending_store.release(tmp_path, []) == 0
    assert pending_store.release(tmp_path, ["zed unknown"]) == 1
    assert pending_store.waiting(tmp_path) == (0, 0)
    assert [e.name for e in pending_store.load(tmp_path)] == ["Gamma Board"]


def test_ready_offers_only_lines_whose_page_exists_and_follows_stage2(tmp_path):
    (tmp_path / "entities").mkdir()
    for name in ("Zed Unknown", "Delta Unknown", "Echo Unknown"):
        pending_store.upsert(tmp_path, _pending(name))
    pending_store.hold(tmp_path, {
        "zed-unknown": [_claim("clm_z", "zed-unknown")],
        "delta-unknown": [_claim("clm_d", "delta-unknown")],
        "echo-unknown": [_claim("clm_e", "echo-unknown")],
    })
    (tmp_path / "entities" / "zed-unknown.md").write_text("---\nname: Zed Unknown\n---\n\nx\n", encoding="utf-8")
    (tmp_path / "entities" / "echo-example.md").write_text("---\nname: Echo Example\n---\n\nx\n", encoding="utf-8")
    verdicts = {"echo unknown": "echo-example"}  # Stage 2 matched this name to an existing page

    out = pending_store.ready(tmp_path, lambda name, subject: verdicts.get(name.lower()) or subject)
    assert sorted((r.name, r.target, [c.subject for c in r.claims], [c.id for c in r.claims]) for r in out) == [
        ("Echo Unknown", "echo-example", ["echo-example"], ["clm_e"]),
        ("Zed Unknown", "zed-unknown", ["zed-unknown"], ["clm_z"]),
    ]
    assert pending_store.waiting(tmp_path) == (3, 3)  # ready() never writes


def test_ready_skips_a_held_claim_that_no_longer_parses(tmp_path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "zed-unknown.md").write_text("---\nname: Zed Unknown\n---\n\nx\n", encoding="utf-8")
    bad = {"id": "clm_bad", "text": "t", "subject": "zed-unknown", "confidence": "not-a-number"}
    pending_store.save(tmp_path, [_pending("Zed Unknown", held_claims=[_claim("clm_a").to_dict(), bad])])
    (release,) = pending_store.ready(tmp_path, lambda name, subject: subject)
    assert [c.id for c in release.claims] == ["clm_a"]


def test_a_failed_save_leaves_the_old_file_and_no_temp_file(tmp_path, monkeypatch):
    (tmp_path / pending_store.PENDING_STORE_FILE).write_text(LEGACY, encoding="utf-8")

    def boom(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(pending_store.os, "replace", boom)
    with pytest.raises(OSError):
        pending_store.save(tmp_path, [])
    assert _store_text(tmp_path) == LEGACY
    assert sorted(p.name for p in tmp_path.iterdir()) == [pending_store.PENDING_STORE_FILE]


def test_vector_index_still_exports_the_store_names():
    from api.services import vector_index

    assert vector_index.PendingEntity is pending_store.PendingEntity
    assert vector_index.PENDING_STORE_FILE == pending_store.PENDING_STORE_FILE == "pending_entities.jsonl"
