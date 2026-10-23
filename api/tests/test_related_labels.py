"""A page's ``## Related`` names each link by what is true now (benchmarks/newuser, 2026-10-23).

Measured on the synthetic new user (real values are placeholders): after a job change the person's page read
"<old-employer> — works at" and "<new-employer> — interviewing with", and the old employer's page "<person> — works
at". ``graph_edges.yaml`` keeps every relationship ever extracted and never closes one, and the first edge to a page
named the link for good, although the claims had closed the old job and opened the new one. The page body, a recall
of it and the app's entity card all show this block.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from api.services import conflict_resolver, markdown_parser
from api.services.claims import Claim, write_claims

PAGES = {"owner": ("Bob Example", "person"), "old-co": ("Old Example Co", "company"),
         "new-co": ("New Example Co", "company"), "gone-co": ("Gone Example Co", "company"),
         "carol-example": ("Carol Example", "person")}


def _claim(subject, predicate, obj, since, until=None):
    return Claim(id=f"clm_{since}_{predicate}_{obj}", text=f"{subject} {predicate} {obj}", subject=subject,
                 predicate=predicate, object=obj, valid_from=since, valid_to=until, source_episodes=[f"ep_{since}_001"])


def _bank(tmp_path: Path, edges: list[dict], claims: dict[str, list[Claim]]) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    for eid, (name, kind) in PAGES.items():
        body = write_claims("## Summary\nA synthetic page.\n", claims.get(eid, []))
        markdown_parser.write(bank / "entities" / f"{eid}.md", {"name": name, "type": kind, "related": []}, body)
    (bank / "graph_edges.yaml").write_text(yaml.dump({"edges": edges}, sort_keys=False), encoding="utf-8")
    return bank


def _related(bank: Path, eid: str) -> list[str]:
    fm = markdown_parser.parse(bank / "entities" / f"{eid}.md").frontmatter
    block = conflict_resolver._reconcile_related(eid, fm, bank, conflict_resolver._edges_by_entity(bank))
    return block.splitlines()


JOB_CHANGE = [
    {"source": "owner", "target": "old-co", "label": "works at"},
    {"source": "owner", "target": "new-co", "label": "interviewing with"},
    {"source": "owner", "target": "old-co", "label": "previously worked at"},
    {"source": "owner", "target": "new-co", "label": "works at"},
    {"source": "owner", "target": "gone-co", "label": "works at"},
    {"source": "owner", "target": "carol-example", "label": "knows"},
    {"source": "owner", "target": "old-co", "label": "left"},
]
CLAIMS = {"owner": [
    _claim("owner", "works-at", "old-co", "2026-08-25", until="2026-09-04"),
    _claim("owner", "works-at", "old-co", "2026-09-12", until="2026-09-12"),
    _claim("owner", "interviewing-with", "new-co", "2026-08-25"),
    _claim("owner", "works-at", "new-co", "2026-09-22"),
    _claim("owner", "left", "old-co", "2026-09-10"),
    _claim("owner", "works-at", "gone-co", "2025-01-10", until="2025-06-30"),
]}


def test_the_persons_page_names_the_current_job_and_not_the_old_one(tmp_path):
    bank = _bank(tmp_path, JOB_CHANGE, CLAIMS)
    assert _related(bank, "owner") == [
        "- [[Old Example Co]] — left",               # the closed "works at" no longer names it
        "- [[New Example Co]] — works at",           # the newest open claim, not the first edge
        "- [[Carol Example]] — knows",               # no claim speaks to it: as before
        "- [[Gone Example Co]] — works at (until 2025-06-30)",   # every label ended: kept, marked, last
    ]


def test_an_inbound_link_is_read_against_the_claims_of_the_page_it_starts_from(tmp_path):
    bank = _bank(tmp_path, JOB_CHANGE, CLAIMS)
    assert _related(bank, "old-co") == ["- [[Bob Example]] — left"]
    assert _related(bank, "new-co") == ["- [[Bob Example]] — works at"]


def test_a_page_with_no_claims_keeps_its_first_label(tmp_path):
    bank = _bank(tmp_path, JOB_CHANGE, {})
    assert _related(bank, "owner") == ["- [[Old Example Co]] — works at", "- [[New Example Co]] — interviewing with",
                                       "- [[Gone Example Co]] — works at", "- [[Carol Example]] — knows"]


def test_confidence_never_picks_the_label(tmp_path):
    claims = {"owner": [_claim("owner", "works-at", "new-co", "2026-09-22"),
                        _claim("owner", "interviewing-with", "new-co", "2026-08-25")]}
    claims["owner"][0].confidence, claims["owner"][1].confidence = 0.3, 0.95
    bank = _bank(tmp_path, JOB_CHANGE[1:4:2], claims)
    assert _related(bank, "owner") == ["- [[New Example Co]] — works at"]
