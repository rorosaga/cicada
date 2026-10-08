"""The Projects list on a bank whose owner page is large: the owner page's claims are read once per request, never once
per project. On a 150-project bank with a 3,500-claim owner page the list resolved 526k references (one per owner
claim per project) and took 0.46-1.5 s cold. Placeholder names only."""
from __future__ import annotations

from datetime import date, timedelta

from _synthetic_bank import _entity
from api.services import bank_index, markdown_parser, predicates, project_timeline
from api.services.claims import Claim, write_claims

DAY0 = date(2026, 3, 1)


def _owner_bank(tmp_path, projects: int, owner_claims: int):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    names = [f"proj-{i:02d}" for i in range(projects)]
    for eid in names:
        _entity(memory, eid, type="project")
    eps = []
    for k in range(10):
        day = DAY0 + timedelta(days=k)
        ep = f"ep_{day.isoformat()}_001"
        markdown_parser.write(memory / "episodes" / f"{ep}.md",
                              {"id": ep, "timestamp": f"{day.isoformat()}T09:00:00+00:00", "processed": True}, "user: hi")
        eps.append(ep)
    claims = [Claim(id=f"clm_o_{k}", text=f"Owner works on {names[k % projects]}", subject="owner-example",
                    predicate="works-on", object=names[k % projects], valid_from=str(DAY0 + timedelta(days=k % 10)),
                    source_episodes=[eps[k % 10]])
              for k in range(owner_claims)]
    claims += [Claim(id=f"clm_ev_{k}", text=f"Shipped step {k}", subject="owner-example", predicate="happened",
                     object=f"step {k}", object_kind="literal", valid_from=str(DAY0 + timedelta(days=k)),
                     status="ongoing", participants=[{"role": "about", "surface": names[k % projects].replace("-", " ")}])
               for k in range(projects)]
    _entity(memory, "owner-example", type="person", owner=True,
            body=write_claims("## Summary\nThe owner.\n", claims))
    bank_index.invalidate()
    return memory


def test_the_owner_pages_claims_are_resolved_once_per_request_not_once_per_project(tmp_path, monkeypatch):
    memory = _owner_bank(tmp_path, projects=30, owner_claims=300)
    calls = 0
    real = project_timeline._Bank.resolve

    def counting(self, ref):
        nonlocal calls
        calls += 1
        return real(self, ref)

    monkeypatch.setattr(project_timeline._Bank, "resolve", counting)
    rows = {r.id: r for r in project_timeline.list_projects(memory, tz_name="UTC").projects}
    # Every project still sees its owner beliefs (activity) and the owner's happenings about it (threads).
    assert all(rows[f"proj-{i:02d}"].activity for i in range(30))
    assert all(len(rows[f"proj-{i:02d}"].open_threads) == 1 for i in range(30))
    # 330 owner claims + 30 event participants, read once each — not 30 x 330.
    assert calls < 2 * 330, calls
