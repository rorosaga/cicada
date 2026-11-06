"""What has come up lately weighs more on recall's page order (Rodrigo, 2026-11-06). Synthetic ids."""
from __future__ import annotations

from api.services import search_service


def test_fusion_lifts_a_page_said_lately_and_only_reorders_what_was_found():
    legs = [{"id": "quiet"}, {"id": "lately"}]
    assert [h["id"] for h in search_service.rrf_fuse(legs)] == ["quiet", "lately"]
    fused = search_service.rrf_fuse(legs, lately={"lately": 1.0, "not-found": 1.0})
    assert [h["id"] for h in fused] == ["lately", "quiet"]


def test_a_far_better_page_stays_ahead():
    first = [{"id": "far-better"}, {"id": "other"}]
    fused = search_service.rrf_fuse(first, first, first, [{"id": "lately"}], lately={"lately": 1.0})
    assert fused[0]["id"] == "far-better"


def test_a_named_page_keeps_its_place_and_lately_picks_between_two_of_one_name():
    legs = [{"id": "named"}, {"id": "said-lately"}]
    assert search_service.rrf_fuse(legs, lately={"said-lately": 1.0})[0]["id"] == "said-lately"
    lift = search_service.lately_lift({"said-lately": 1.0}, ["named"])
    assert search_service.rrf_fuse(legs, lately=lift)[0]["id"] == "named"
    both = search_service.lately_lift({"second": 0.5}, ["first", "second"])
    assert search_service.rrf_fuse([{"id": "first"}, {"id": "second"}], lately=both)[0]["id"] == "second"
