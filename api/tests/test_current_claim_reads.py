"""G118/G93: synthetic history never votes as a current belief."""
from datetime import date

import numpy as np
import pytest

from api.services import claims, hook_recall, markdown_parser, search_index, search_service
from api.services.claims import Claim, write_claims
from api.services.vector_index import SqliteVecIndexer


@pytest.mark.parametrize("fields,current", [
    ({}, True),
    ({"valid_to": "2026-01-01"}, False),
    ({"valid_to": "2099-01-01"}, False),
    ({"superseded_by": "clm_new"}, False),
    ({"valid_from": "2099-01-01"}, False),
    ({"expected_end": "2026-01-01"}, False),
    ({"expected_end": "2026-10-07"}, True),
    ({"predicate": "due", "object": "2026-01-01"}, False),
    ({"predicate": "milestone", "target": "2026-01-01"}, True),
    ({"valid_from": "undated"}, True),
])
def test_current_predicate_has_one_clock_for_objects_and_index_payloads(fields, current):
    claim = Claim(id="clm_test", text="A synthetic fact", **fields)
    assert claims.is_current(claim, now=date(2026, 10, 7)) is current
    assert claims.is_current(claim.to_dict(), now=date(2026, 10, 7)) is current


def _page(bank, rows):
    (bank / "entities").mkdir(exist_ok=True)
    markdown_parser.write(bank / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project"},
                          write_claims("A synthetic project.", rows))


@pytest.mark.parametrize("predicate,status,closure", [
    ("uses", None, {"valid_to": "2026-01-01"}),
    ("uses", None, {"superseded_by": "clm_new"}),
    ("happened", "done", {"valid_to": "2026-01-01"}),
    ("milestone", "planned", {"valid_to": "2026-01-01", "superseded_by": "clm_new"}),
])
def test_closed_beliefs_do_not_vote_but_unsuperseded_events_reach_their_subject(tmp_path, predicate, status, closure):
    claim = Claim(id="clm_old", text="Retired calibration method", subject="alpha-project",
                  predicate=predicate, status=status, valid_from="2026-01-01", **closure)
    _page(tmp_path, [claim])
    search_index.rebuild(tmp_path)
    response = search_service.search(tmp_path, "calibration", kinds=("claim",), mode="prefix")
    [hit] = response.results
    assert (hit.valid_to, hit.superseded_by) == (claim.valid_to, claim.superseded_by)
    subjects = search_service.claim_subject_hits(tmp_path, "calibration")
    entities = search_service.search(tmp_path, "calibration", kinds=("entity",), mode="prefix").results
    if predicate == "happened" and not claim.superseded_by:
        assert [s["entity_id"] for s in subjects] == ["alpha-project"]
        assert [h.id for h in entities] == ["alpha-project"]
    else:
        assert subjects == [] and entities == []


def test_hook_does_not_inject_a_future_or_elapsed_claim():
    rows = [("Future method", {"valid_from": "2099-01-01"}),
            ("Elapsed method", {"expected_end": "2020-01-01"}),
            ("Current method", {})]
    assert hook_recall.current_claims(rows) == [("Current method", None)]


def _embed(texts, **_kw):
    return np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (len(texts), 1))


def test_vector_claim_search_rechecks_the_page_after_a_claim_closes(tmp_path):
    old = Claim(id="clm_old", text="Retired calibration method", subject="alpha-project")
    _page(tmp_path, [old])
    indexer = SqliteVecIndexer(tmp_path, embed_fn=_embed)
    indexer.index_claims()
    assert indexer.search_claims("calibration")
    old.valid_to = "2026-01-01"
    _page(tmp_path, [old])
    assert indexer.search_claims("calibration") == []
    assert indexer.search_kinds("calibration", {"claims": 8})["claims"] == []


def test_stale_fts_does_not_render_a_closed_claim_as_current(tmp_path, monkeypatch):
    old = Claim(id="clm_old", text="Retired calibration method", subject="alpha-project")
    _page(tmp_path, [old])
    search_index.rebuild(tmp_path)
    old.valid_to = "2026-01-01"
    _page(tmp_path, [old])
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *_a, **_k: "stale")
    [hit] = search_service.search(tmp_path, "calibration", kinds=("claim",), mode="prefix").results
    assert hit.valid_to == "2026-01-01"
    assert search_service.claim_subject_hits(tmp_path, "calibration") == []


@pytest.mark.parametrize("url", ["/entities/alpha-project/provenance", "/episodes/ep_2026-01-01_001/citations"])
def test_validity_etag_changes_with_the_read_day(tmp_path, monkeypatch, url):
    from fastapi.testclient import TestClient
    from api import config, main

    claim = Claim(id="clm_test", text="Alpha Project uses a temporary method", subject="alpha-project",
                  expected_end="2026-10-07", source_episodes=["ep_2026-01-01_001"])
    _page(tmp_path, [claim])
    (tmp_path / "episodes").mkdir()
    markdown_parser.write(tmp_path / "episodes" / "ep_2026-01-01_001.md", {}, "user: Alpha Project uses a method")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    day = [date(2026, 10, 7)]
    monkeypatch.setattr(claims, "current_day", lambda: day[0], raising=False)
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            response = client.get(url)
            assert response.status_code == 200
            etag = response.headers["etag"]
            assert client.get(url, headers={"If-None-Match": etag}).status_code == 304
            day[0] = date(2026, 10, 8)
            assert client.get(url, headers={"If-None-Match": etag}).status_code == 200
    finally:
        config.get_settings.cache_clear()


def test_hook_claim_lines_recheck_markdown_while_fts_is_stale(tmp_path):
    old = Claim(id="clm_old", text="Retired calibration method", subject="alpha-project")
    _page(tmp_path, [old])
    search_index.rebuild(tmp_path)
    old.valid_to = "2026-01-01"
    _page(tmp_path, [old])
    assert hook_recall.current_claims(hook_recall._live_claim_rows(tmp_path, "alpha-project")) == []


def test_short_type_recall_never_exposes_an_unlabeled_claim_fence():
    from api.services import mcp_tools
    body = write_claims("A synthetic person.", [Claim(id="clm_old", text="Retired calibration method",
                                                    valid_to="2026-01-01")])
    summary = mcp_tools._type_aware_truncate(body, "skill")
    assert "Retired calibration" not in summary and "```claims" not in summary


@pytest.mark.parametrize("projection", ["claims", "transclusion", "graph"])
def test_current_claim_projections_share_the_validity_predicate(projection):
    from api.routers import claims as claims_router
    from api.services import graph_builder, transclusion_resolver
    future = Claim(id="clm_future", text="Future calibration method", subject="alpha-project",
                   predicate="uses", object="synthetic-tool", valid_from="2099-01-01")
    read = {"claims": claims_router._is_currently_valid, "transclusion": transclusion_resolver._is_valid,
            "graph": lambda c: graph_builder._claim_edge_row(c, "alpha-project") is not None}[projection]
    assert read(future) is False


def test_perspective_history_labels_an_elapsed_stated_end_before_expiry_writes(tmp_path):
    from api.services import mcp_tools
    old = Claim(id="clm_old", text="Temporary calibration method", subject="alpha-project",
                valid_from="2020-01-01", expected_end="2020-02-01")
    _page(tmp_path, [old])
    ctx = mcp_tools.ToolContext(memory_path=lambda: tmp_path, session_id=None, harness="codex")
    out = mcp_tools.get_perspective(ctx, "alpha-project", history=True)
    assert "ended at its stated end" in out and "2020-01-01 → 2020-02-01" in out


@pytest.mark.parametrize("zone,instant", [
    ("Europe/Madrid", "2026-10-07T22:30:00+00:00"),
    ("America/Los_Angeles", "2026-10-08T01:30:00+00:00"),
])
def test_claim_read_day_matches_writer_at_local_midnight(monkeypatch, zone, instant):
    import os
    import time
    from datetime import datetime

    fixed = datetime.fromisoformat(instant)
    class LocalDate(date):
        @classmethod
        def today(cls):
            return fixed.astimezone().date()
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.astimezone().replace(tzinfo=None)

    old_zone = os.environ.get("TZ")
    monkeypatch.setenv("TZ", zone)
    time.tzset()
    try:
        monkeypatch.setattr(claims, "date", LocalDate)
        monkeypatch.setattr(claims, "datetime", FrozenDatetime)
        writer_day = LocalDate.today()
        assert writer_day != fixed.date(), "fixture must cross the UTC/local boundary"
        new = Claim(id="clm_new", text="Current calibration", valid_from=writer_day.isoformat(),
                    expected_end=writer_day.isoformat())
        old = Claim(id="clm_old", text="Earlier calibration", valid_to=writer_day.isoformat(),
                    superseded_by=new.id)
        assert claims.current_day() == writer_day
        assert claims.is_current(new) and not claims.is_current(old)
        assert claims.read_valid_to(new) is None, "stated ends include the writer's whole local day"
    finally:
        if old_zone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_zone
        time.tzset()


def test_warm_prefix_claim_search_uses_fts_stamp_without_reparsing_markdown(tmp_path, monkeypatch):
    _page(tmp_path, [Claim(id="clm_test", text="Current calibration method", subject="alpha-project")])
    search_index.rebuild(tmp_path)
    reads = []
    original = markdown_parser.parse
    def parse(path):
        reads.append(path)
        return original(path)
    monkeypatch.setattr(markdown_parser, "parse", parse)
    for _ in range(3):
        assert search_service.search(tmp_path, "calibration", kinds=("claim",), mode="prefix").results
    assert reads == [], "unchanged candidate pages already have trustworthy indexed validity"


@pytest.mark.parametrize("change", ["deleted", "dropped", "successor"])
def test_changed_fts_candidate_stamp_rechecks_page(tmp_path, monkeypatch, change):
    row = Claim(id="clm_test", text="Current calibration method", subject="alpha-project")
    _page(tmp_path, [row])
    search_index.rebuild(tmp_path)
    page = tmp_path / "entities" / "alpha-project.md"
    if change == "deleted":
        page.unlink()
    elif change == "dropped":
        markdown_parser.write(page, {"name": "Alpha Project", "status": "dropped"}, write_claims("", [row]))
    else:
        row.superseded_by = "clm_new"
        _page(tmp_path, [row])
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *_a, **_k: "stale")
    assert search_service.claim_subject_hits(tmp_path, "calibration") == []
