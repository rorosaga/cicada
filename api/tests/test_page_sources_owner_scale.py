"""Review B1 (sources-view): the overview's per-app tally must never be O(conversations x claims).

An owner-sized page — 5,900 current claims over 3,000 one-episode conversations, 2,000 Related links — answers the
overview with each claim's conversations read once, and in under 500 ms warm (the `bench` tier).
Synthetic bank under tmp_path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import _bench

from api.services import bank_index, page_sources, provenance
from api.services import markdown_parser as md
from api.services.claims import Claim, Evidence, write_claims

N_CONVERSATIONS = 3000
N_CLAIMS = 5900
PREDICATES = ["works-on", "likes", "uses", "knows", "lives-in", "employs", "website", "prefers"]


def _owner_page(memory: Path) -> Path:
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    eps = []
    for i in range(N_CONVERSATIONS):
        day = f"2026-{1 + i % 9:02d}-{1 + i % 28:02d}"
        ep = f"ep_{day}_{i:03d}"
        eps.append(ep)
        md.write(memory / "episodes" / f"{ep}.md",
                 {"id": ep, "timestamp": f"{day}T10:00:00+00:00", "title": f"Synthetic {i}",
                  "source_id": f"conv-{i}", "origin": "chatgpt-export"},
                 f"user: owner-example talked about topic {i}.\nassistant: ok.")
    claims = [Claim(id=f"clm_{i}", text=f"owner-example {PREDICATES[i % 8]} thing-{i}", subject="owner-example",
                    predicate=PREDICATES[i % 8], object=f"thing-{i}", recorded_at="2026-09-01",
                    source_episodes=[eps[i % N_CONVERSATIONS]],
                    evidence=[Evidence(episode=eps[i % N_CONVERSATIONS], start=6, end=19, kind="user",
                                       hash="x" * 16)])
              for i in range(N_CLAIMS)]
    body = ("## Summary\nThe owner.\n\n## Related\n" + "".join(f"- [[entity-{i}]]\n" for i in range(2000))
            + "\n## Links\n" + "".join(f"- [Link {i}](https://site{i}.example.com/)\n" for i in range(150)))
    sources = [{"ref": f"https://src{i}.example.org/", "kind": "url", "predicate": p, "added_by": "agent",
                "verified": {"at": "2026-10-02", "how": "name+content"}} for i, p in enumerate(PREDICATES)]
    page = memory / "entities" / "owner-example.md"
    md.write(page, {"name": "Owner Example", "type": "person", "sources": sources, "source_episodes": eps},
             write_claims(body, claims))
    return page


@pytest.fixture(scope="module")
def owner_bank(tmp_path_factory):
    memory = tmp_path_factory.mktemp("owner") / "memory"
    return memory, _owner_page(memory)


def test_owner_sized_overview_inverts_the_claims_once_and_tallies_exactly(owner_bank, monkeypatch):
    """The deterministic half of review B1, for the default run and CI: the overview reads each current claim's
    conversations exactly once (the episode -> beliefs inversion), never once per conversation, and its tallies are
    exact at owner scale. The wall-clock budget below is the `bench` tier's (a busy Mac measured 565 ms)."""
    memory, page = owner_bank
    bank_index.invalidate()
    calls = []
    real = provenance.cited_episodes
    monkeypatch.setattr(provenance, "cited_episodes", lambda claim: calls.append(claim.id) or real(claim))
    result = page_sources.overview(memory, page)
    assert len(calls) == len(set(calls)) == N_CLAIMS
    assert result.conversations.total == N_CONVERSATIONS
    assert result.facts_total == N_CLAIMS
    [app] = result.conversations.apps
    assert (app.conversations, app.facts) == (N_CONVERSATIONS, N_CLAIMS)


@pytest.mark.bench   # a wall-clock budget: `make test-bench` and `make test`, never the default run
def test_owner_sized_overview_answers_under_half_a_second_warm(owner_bank):
    memory, page = owner_bank
    bank_index.invalidate()
    page_sources.overview(memory, page)          # warm the episode index
    result = page_sources.overview(memory, page)
    assert result.conversations.total == N_CONVERSATIONS
    # CPU time against the budget, the wall clock under 4× it (`_bench`): a busy Mac failed the wall clock alone.
    took = _bench.measure(lambda: page_sources.overview(memory, page), runs=5, warm=False)
    print(f"\nwarm owner-sized overview: {took.cpu_min * 1000:.0f} ms CPU, {took.wall_min * 1000:.0f} ms wall (min of 5)")
    _bench.within(took.cpu_min, took.wall_min, 0.5, "warm overview")
