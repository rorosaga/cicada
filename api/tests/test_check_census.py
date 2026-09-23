"""G61 phase 2 S2 — the census (spec §15's coverage gate, plan R-AC41): counts
only, the same numbers from the service, the endpoint and the script."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, bank_registry, demo_bank, fact_sources, markdown_parser, source_check

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check-census.sh"


@pytest.fixture
def demo(tmp_path):
    bank_dir = tmp_path / "demo"
    bank_registry.scaffold_bank(bank_dir)
    demo_bank.populate(bank_dir)
    bank_index.invalidate()
    return bank_dir


def test_a_fresh_demo_banks_census(demo):
    """inbox-003 (works-at, the person's example.com source, access unverified);
    inbox-005 (a clarification with no page); two decays; the `uses` conflict;
    the merge suggestion's subject has no page, so it is not served; and G141
    PJ-6's one follow-up (the quiet camera thread): only the person knows how it
    went, so it is never checked (person_locus)."""
    c = source_check.census(demo)
    assert c["total"] == 6 and c["deferred"] == 0
    assert c["by_state"] == {"checkable": 1, "needs_source": 1, "inform_only": 0, "never": 4}
    assert c["by_reason"] == {"checkable/access_unverified": 1, "needs_source/no_source": 1,
                              "never/informational": 1, "never/not_a_question": 2, "never/person_locus": 1}
    assert c["by_rung"] == {"fetch": 1, "agent": 1, "agent_local": 0}
    assert c["targets_by_access"] == {"public": 0, "signed_in": 0, "local": 0, "unknown": 1}
    assert c["settle_eligible"] == 0 and c["checkable_share"] == 0.167


def test_the_census_names_nothing(tmp_path):
    memory = _bank(tmp_path)
    fact_sources.add_source(memory, "alpha-project", "https://example.com/alpha/status", predicate="runs-on")
    markdown_parser.write(memory / "inbox" / "inbox-003.md", {
        "kind": "conflict", "status": "pending", "entity_id": "alpha-project", "entity_name": "Alpha Project",
        "title": "What does Alpha Project run on now?", "predicate": "runs-on", "claim_id": "clm_x",
        "created_date": "2026-08-01", "options": [{"key": "a", "label": "tool-a"}, {"key": "b", "label": "tool-b"}],
    }, "ctx")
    text = json.dumps(source_check.census(memory))
    for needle in ("alpha", "beta", "bob", "inbox-", "example.com", "tool-", "runs-on"):
        assert needle not in text, needle


def test_the_endpoint_serves_the_same_counts(demo, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(demo))
    monkeypatch.setenv("CICADA_HOME", str(demo.parent / "home"))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            body = client.get("/inbox/check-census").json()
    finally:
        config.get_settings.cache_clear()
    assert body["byState"] == source_check.census(demo)["by_state"]
    assert body["checkableShare"] == 0.167


def test_the_script_prints_the_census_and_refuses_a_non_bank(demo, tmp_path):
    env = {**os.environ, "CICADA_HOME": str(tmp_path / "home")}
    out = subprocess.run(["bash", str(SCRIPT), str(demo)], check=True, capture_output=True, text=True, env=env)
    assert json.loads(out.stdout) == source_check.census(demo)
    bad = subprocess.run(["bash", str(SCRIPT), str(tmp_path)], capture_output=True, text=True, env=env)
    assert bad.returncode == 2 and "usage" in bad.stderr
