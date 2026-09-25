"""G141 PJ-1 — the two FTS readers the project read model leans on: reverse
claims naming a project (§6.4) and pages co-citing an episode (R-PJB20).

Built on `day_one`, never `demo`, so the later event writers (T5+) can never
change these lists."""
from __future__ import annotations

import pytest

from _demo_scenario import day_one
from api.services import search_index


@pytest.fixture
def bank(tmp_path):
    return day_one(tmp_path)


def _s7(bank):
    return next(p.stem for p in (bank / "episodes").glob("*.md") if "Yesterday Hana" in p.read_text())


def test_claims_about_finds_the_reverse_claims_naming_a_project(bank):
    hits = search_index.claims_about(bank, ["rover-arm-project", "Rover Arm Project"])
    assert hits is not None
    assert any(ref == "bob-example" and p["predicate"] == "works-on" for ref, p in hits)
    assert any(ref == "pick-and-place-demo" and p["predicate"] == "part-of" for ref, p in hits)


def test_pages_citing_lists_every_page_with_a_span_into_the_episode(bank):
    assert search_index.pages_citing(bank, _s7(bank)) == [
        "bob-example", "hana-example", "media-example-cluster-guide", "pick-and-place-demo"]


def test_both_answer_none_while_no_usable_index_exists(bank, monkeypatch):
    s7 = _s7(bank)
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "building")
    assert search_index.claims_about(bank, ["rover-arm-project"]) is None
    assert search_index.pages_citing(bank, s7) is None


def test_no_usable_name_is_an_empty_list(bank):
    assert search_index.claims_about(bank, ["", "  "]) == []


def test_pages_citing_many_agrees_with_one_at_a_time(bank, monkeypatch):
    """R-PJB9's batch read: one reader for every moment's episode must answer
    exactly what `pages_citing` answers per episode — an uncited one is []."""
    eps = sorted(p.stem for p in (bank / "episodes").glob("*.md"))
    many = search_index.pages_citing_many(bank, eps + ["ep_1999-01-01_001"])
    assert {ep: many[ep] for ep in eps} == {ep: search_index.pages_citing(bank, ep) for ep in eps}
    assert many["ep_1999-01-01_001"] == [] and any(many.values())
    assert search_index.pages_citing_many(bank, []) == {}
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "building")
    assert search_index.pages_citing_many(bank, eps) is None
