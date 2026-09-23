"""R-PJB9 — §6.6's latency budgets on a 2,500-page synthetic bank, opt-in
(`CICADA_BENCH=1`): a p95 assertion in the always-on suite is flaky on a loaded
machine and would teach the team to ignore a red. Placeholder names only."""
from __future__ import annotations

import os
import time
from datetime import date, timedelta

import pytest

from _synthetic_bank import _entity
from api.services import bank_index, evidence, markdown_parser, predicates, project_timeline, search_index
from api.services.claims import Claim, Evidence, write_claims

pytestmark = pytest.mark.skipif(os.environ.get("CICADA_BENCH") != "1", reason="R-PJB9: opt-in")
DAY0 = date(2026, 3, 1)


def _p95(fn, runs: int = 20) -> float:
    fn()                                   # warm: bank_index, the FTS reader, imports
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t)
    return sorted(times)[int(0.95 * (runs - 1))]


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    memory = tmp_path_factory.mktemp("bench") / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    names = [f"proj-{p:02d}" for p in range(20)]
    names += [f"proj-{p:02d}-part-{k}" for p in range(20) for k in range(5)]
    names += [f"thing-{n:04d}" for n in range(2500 - len(names))]
    episodes = []
    for n in range(1500):                              # 10 a day over 150 days
        day = DAY0 + timedelta(days=n // 10)
        ep = f"ep_{day.isoformat()}_{n % 10 + 1:03d}"
        body = f"user: {names[n % len(names)]} and {names[(n * 7 + 3) % len(names)]} came up again"
        markdown_parser.write(memory / "episodes" / f"{ep}.md",
                              {"id": ep, "timestamp": f"{day.isoformat()}T09:00:00+00:00", "processed": True},
                              body)
        episodes.append((ep, day.isoformat(), body))
    for i, eid in enumerate(names):
        if "-part-" in eid:
            etype = "project" if eid.endswith(("-0", "-1")) else "tool"
        elif eid.startswith("proj-"):
            etype = "project"
        else:
            etype = ("concept", "tool", "person")[i % 3]
        claims = []
        for k in range(3 + i % 3):
            ep, day, body = episodes[(i * 5 + k) % len(episodes)]
            if "-part-" in eid:
                pred, obj = ("part-of" if etype == "project" else "relates-to"), eid.rsplit("-part-", 1)[0]
            elif etype == "project":
                pred, obj = "uses", f"{eid}-part-{2 + k % 3}"
            else:
                pred, obj = "relates-to", f"proj-{i % 20:02d}"
            claims.append(Claim(id=f"clm_{eid}_{k}", text=f"{eid} {pred} {obj}", subject=eid, predicate=pred,
                                object=obj, valid_from=day, source_episodes=[ep],
                                evidence=[Evidence(episode=ep, start=6, end=len(body), kind="user",
                                                   hash=evidence.body_hash(body))]))
        _entity(memory, eid, type=etype, created="2026-03-01", last_referenced="2026-07-01",
                body=write_claims(f"## Summary\n{eid} is a synthetic page.\n", claims))
    bank_index.invalidate()
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    return memory


def test_the_detail_and_the_list_fit_their_budgets(big):
    detail = _p95(lambda: project_timeline.build(big, "proj-00", tz_name="UTC"))
    listing = _p95(lambda: project_timeline.list_projects(big, tz_name="UTC"))
    print(f"\nG141 bench p95: build {detail * 1000:.1f} ms · list {listing * 1000:.1f} ms")
    assert detail <= 0.150 and listing <= 0.080
