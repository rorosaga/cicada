"""What has come up lately weighs more on recall's page order (Rodrigo, 2026-11-06). Synthetic ids."""
from __future__ import annotations

from datetime import date

from api.services import markdown_parser, page_use, search_service


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


def test_lately_of_reads_only_the_pages_it_is_asked_about_and_counts_only_mentions(tmp_path, monkeypatch):
    for sub in ("entities", "episodes"):
        (tmp_path / sub).mkdir()
    (tmp_path / "episodes" / "ep_2026-11-04_001.md").write_text("---\nsource: claude_memory\n---\nx\n")
    for page, said in {"said-lately": ["ep_2026-11-05_001"], "an-export-said-it": ["ep_2026-11-04_001"],
                       "long-ago": ["ep_2020-01-01_001"], "untouched": ["ep_2026-11-05_001"]}.items():
        markdown_parser.write(tmp_path / "entities" / f"{page}.md", {"name": page, "source_episodes": said}, "x")
    read: list[str] = []
    real = markdown_parser.header
    monkeypatch.setattr(markdown_parser, "header", lambda path, *a, **k: (read.append(path.name), real(path, *a, **k))[1])
    out = page_use.lately_of(tmp_path, ["said-lately", "an-export-said-it", "long-ago", "absent"], today=date(2026, 11, 6))
    assert list(out) == ["said-lately"] and 0 < out["said-lately"] < 1
    assert "untouched.md" not in read
