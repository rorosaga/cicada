"""G113 slice 4: the feedback ledger becomes numbers on /consumption/feedback."""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import consumption_stats as cs
from api.services import telemetry as tm
from api.services.connections import registry

TODAY = date(2026, 9, 2)


def _res(ts: str, kind: str, action: str, verdict: str, conf: float | None = None) -> None:
    tm.record(tm.UsageEvent(ts=ts, kind="resolution", stage="feedback", bank="memory", invocations=0, billing="free",
                            refs={"item_id": "inbox-001", "kind": kind, "predicate": "works-at", "entity_id": "alpha-project",
                                  "action": action, "option_key": None, "verdict": verdict,
                                  "winner_claim_id": None, "loser_claim_ids": [],
                                  "extractor_confidence": conf, "extractor_model": "gpt-5.4-mini", "item_age_days": 3}))


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _res("2026-09-01T10:00:00.000Z", "conflict", "pick:1", "agreed", 0.92)
    _res("2026-09-01T10:01:00.000Z", "conflict", "pick:0", "overruled", 0.55)
    _res("2026-09-01T10:02:00.000Z", "conflict", "defer", "neutral", 0.55)
    _res("2026-09-01T10:03:00.000Z", "decay", "archive", "agreed")
    _res("2026-09-01T10:04:00.000Z", "decay", "keep_active", "overruled")
    _res("2026-08-01T10:00:00.000Z", "clarification", "answer", "agreed", 0.3)  # outside "month"
    tm.record(tm.UsageEvent(ts="2026-09-01T11:00:00.000Z", kind="audit", stage="reconcile", bank="memory", invocations=0,
                            billing="free", refs={"action": "supersede", "subject": "alpha-project", "closed": "c1", "by": "c2"}))
    tm.record(tm.UsageEvent(ts="2026-09-01T11:00:01.000Z", kind="audit", stage="reconcile", bank="memory", invocations=0,
                            billing="free", refs={"action": "rejected", "subject": "alpha-project", "kept": "c1", "dropped": "c3"}))
    tm.record(tm.UsageEvent(ts="2026-09-01T12:00:00.000Z", kind="dedup_verdict", stage="dedup", bank="memory", invocations=0,
                            billing="free", refs={"a": "a", "b": "b", "verdict": "same", "confidence": 0.9, "winner": "a", "applied": "merged"}))
    tm.record(tm.UsageEvent(ts="2026-09-01T12:00:01.000Z", kind="dedup_verdict", stage="dedup", bank="memory", invocations=0,
                            billing="free", refs={"a": "c", "b": "d", "verdict": "unsure", "confidence": 0.4, "winner": None, "applied": "nudged"}))
    # an LLM call in range must not leak into any feedback number
    tm.record(tm.UsageEvent(ts="2026-09-01T09:00:00.000Z", kind="llm_call", stage="extraction", model="gpt-5.4-mini",
                            connection="byok-openai", input_tokens=10, output_tokens=5, cost_usd=0.01, equiv_cost_usd=0.01))
    return repo


def test_feedback_counts_and_rate(ledger: Path):
    fb = asyncio.run(cs.feedback(ledger, range_="month", today=TODAY))
    assert fb["range"] == "month" and fb["since"] == "2026-09-01"
    assert fb["resolutions"] == 5          # the August one is out of range; neutral is counted
    assert fb["corrections"] == 2
    assert fb["rate"] == pytest.approx(2 / 4)   # 2 agreed / (2 agreed + 2 overruled); neutral excluded


def test_feedback_agreement_per_kind(ledger: Path):
    fb = asyncio.run(cs.feedback(ledger, range_="month", today=TODAY))
    rows = {r["kind"]: r for r in fb["agreement"]}
    assert set(rows) == {"conflict", "decay"}
    assert rows["conflict"] == {"kind": "conflict", "total": 3, "agreed": 1, "overruled": 1, "rate": pytest.approx(0.5)}
    assert rows["decay"]["rate"] == pytest.approx(0.5)
    assert [r["kind"] for r in fb["agreement"]] == ["conflict", "decay"]   # sorted by total desc


def test_feedback_calibration_buckets(ledger: Path):
    fb = asyncio.run(cs.feedback(ledger, range_="month", today=TODAY))
    buckets = {b["bucket"]: b for b in fb["calibration"]}
    assert [b["bucket"] for b in fb["calibration"]] == ["<0.5", "0.5–0.7", "0.7–0.9", "≥0.9"]
    assert buckets["≥0.9"] == {"bucket": "≥0.9", "n": 1, "agreed_rate": pytest.approx(1.0)}
    assert buckets["0.5–0.7"] == {"bucket": "0.5–0.7", "n": 1, "agreed_rate": pytest.approx(0.0)}  # the deferral is neutral: not counted
    assert buckets["<0.5"] == {"bucket": "<0.5", "n": 0, "agreed_rate": None}


def test_feedback_actions_audits_dedup(ledger: Path):
    fb = asyncio.run(cs.feedback(ledger, range_="month", today=TODAY))
    assert fb["by_action"][0]["n"] == 1 and {r["action"] for r in fb["by_action"]} == {"pick:1", "pick:0", "defer", "archive", "keep_active"}
    assert fb["audits"] == {"supersede": 1, "rejected": 1}
    assert fb["dedup"] == {"same": 1, "different": 0, "unsure": 1, "merged": 1}


def test_feedback_all_range_and_empty(ledger: Path, tmp_path):
    fb = asyncio.run(cs.feedback(ledger, range_="all", today=TODAY))
    assert fb["resolutions"] == 6 and fb["since"] is None
    empty = asyncio.run(cs.feedback(ledger, range_="1d", today=date(2020, 1, 1)))
    assert empty["resolutions"] == 0 and empty["rate"] is None and empty["agreement"] == []
    assert [b["n"] for b in empty["calibration"]] == [0, 0, 0, 0]
    assert empty["audits"] == {"supersede": 0, "rejected": 0}
    assert empty["dedup"] == {"same": 0, "different": 0, "unsure": 0, "merged": 0}


@pytest.fixture
def client(ledger, tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(ledger))
    config.get_settings.cache_clear()
    registry.reset_registry()
    yield TestClient(main.app)
    registry.reset_registry()
    config.get_settings.cache_clear()


def test_feedback_endpoint_camel_and_etag(client):
    r = client.get("/consumption/feedback?range=all")
    assert r.status_code == 200
    body = r.json()
    assert body["resolutions"] == 6 and body["corrections"] == 2
    assert body["agreement"][0]["kind"] == "conflict"
    assert body["calibration"][3]["agreedRate"] == pytest.approx(1.0)   # rows are camelCased like /stats
    assert body["byAction"] and "n" in body["byAction"][0]
    etag = r.headers["ETag"]
    assert client.get("/consumption/feedback?range=all", headers={"If-None-Match": etag}).status_code == 304
    assert client.get("/consumption/feedback?range=bogus").status_code == 422
