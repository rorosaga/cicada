"""R-PJB9 — §6.6's latency budgets on a 2,500-page synthetic bank, opt-in
(the `bench` marker, `make test-bench`): a p95 assertion in the always-on suite is flaky on a loaded
machine and would teach the team to ignore a red. Placeholder names only."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import _bench

from _synthetic_bank import _entity
from api.services import bank_index, evidence, markdown_parser, predicates, project_timeline, search_index
from api.services.claims import Claim, Evidence, write_claims

#: R-PJB9: a wall-clock budget is the `bench` tier (`make test-bench`, and `make test` before a release).
pytestmark = pytest.mark.bench
DAY0 = date(2026, 3, 1)


def _p95(fn, runs: int = 20) -> _bench.Samples:
    """Warm once (bank_index, the FTS reader, imports), then ``runs`` timed: CPU p95 against a budget, wall p95 under
    4× it (`_bench`; a busy Mac failed the wall clock alone)."""
    return _bench.measure(fn, runs)


def _within(label: str, took: _bench.Samples, budget: float) -> None:
    print(f"\n{label}: CPU p95 {took.cpu_p95 * 1000:.1f} ms, wall p95 {took.wall_p95 * 1000:.1f} ms "
          f"(budget {budget * 1000:.0f} ms)")
    _bench.within(took.cpu_p95, took.wall_p95, budget, label)


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
    # The list is remembered while nothing it reads moved (speed 2026-10-29): this budget is the build's, every run.
    listing = _p95(lambda: (project_timeline._LISTS.clear(), project_timeline.list_projects(big, tz_name="UTC")))
    _within("project detail", detail, 0.150)
    _within("project list", listing, 0.080)


def test_the_conversations_read_fits_the_timelines_budget(big):
    """Ruling 45: the FTS-backed conversation scan (the person naming the project, checked in their own turns), at the
    same p95 as `/timeline`."""
    from api.services import project_conversations

    convs = _p95(lambda: project_conversations.build(big, "proj-00", tz_name="UTC"))
    detail = _p95(lambda: project_timeline.build(big, "proj-00", tz_name="UTC"))
    _within("project conversations", convs, 0.150)
    _within("project detail", detail, 0.150)
