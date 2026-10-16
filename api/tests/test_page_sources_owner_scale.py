"""Review B1 (sources-view): the overview's per-app tally must never be O(conversations x claims).

An owner-sized page — 5,900 current claims over 3,000 one-episode conversations, 2,000 Related links — answers the
overview in under 500 ms warm. Synthetic bank under tmp_path.
"""
from __future__ import annotations

import time
from pathlib import Path

from api.services import bank_index, page_sources
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


def test_owner_sized_overview_answers_under_half_a_second_warm(tmp_path: Path):
    memory = tmp_path / "memory"
    page = _owner_page(memory)
    bank_index.invalidate()
    page_sources.overview(memory, page)          # warm the episode index
    started = time.perf_counter()
    result = page_sources.overview(memory, page)
    elapsed = time.perf_counter() - started
    assert result.conversations.total == N_CONVERSATIONS
    assert elapsed < 0.5, f"warm overview took {elapsed * 1000:.0f} ms"
