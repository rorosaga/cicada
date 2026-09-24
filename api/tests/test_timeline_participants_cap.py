"""Round 4 D6 — a big project never beachballs. One happening that cites 600
documents used to ship every participant three times (the item, its embedded
claim, and `now.last`) plus 600 "not a page yet" cluster rows, and the app drew a
chip for each. The wire now carries the first 12 in the sentence's own order and
an honest `participantsTotal`; the body grows with the cap, not the count.
Synthetic: the G141 demo scenario, every URL on example.com."""
from __future__ import annotations

from pathlib import Path

from _demo_scenario import T, d, day_one
from api.services import bank_index, markdown_parser, project_text, project_timeline
from api.services.claims import HAPPENED, Claim, parse_claims, write_claims

PROJECT = "rover-arm-project"
CLAIM_ID = "clm_rover_read_papers"


def _papers(n: int) -> list[dict]:
    return [{"role": "document", "surface": f"Paper {i:03d}", "url": f"https://example.com/papers/{i:03d}"}
            for i in range(n)]


def _add_happening(bank: Path, n: int) -> None:
    page = bank / "entities" / f"{PROJECT}.md"
    parsed = markdown_parser.parse(page)
    claims = [c for c in parse_claims(parsed.body) if c.id != CLAIM_ID]
    claims.append(Claim(
        id=CLAIM_ID, text="Read the cited papers for the arm controller", subject=PROJECT, predicate=HAPPENED,
        object="read the cited papers for the arm controller", object_kind="literal", observer="agent",
        status="done", valid_from=d(-1), valid_to=d(-1), recorded_at=d(-1), participants=_papers(n),
        date_basis="stated", authored_by="claude-code", origin="mcp"))
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    bank_index.invalidate()


def _bank(root: Path, n: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    bank = day_one(root, index=False)
    _add_happening(bank, n)
    return bank


def _build(bank: Path):
    return project_timeline.build(bank, PROJECT, tz_name="UTC")


def _item(timeline):
    return next(i for i in timeline.items if i.id == CLAIM_ID)


def test_an_item_carries_the_first_twelve_in_order_and_the_honest_total(tmp_path):
    timeline = _build(_bank(tmp_path, 600))
    item = _item(timeline)
    assert project_timeline.PARTICIPANTS_SHOWN == 12
    assert [p.surface for p in item.participants] == [f"Paper {i:03d}" for i in range(12)]
    assert item.participants_total == 600
    assert len(item.claim.participants) == 12          # the embedded claim is capped the same way
    assert timeline.now.last is not None and timeline.now.last.id == CLAIM_ID
    assert len(timeline.now.last.participants) == 12 and timeline.now.last.participants_total == 600
    wire = timeline.model_dump(by_alias=True)
    assert all("participantsTotal" in i for i in wire["items"]), "always present, 0 when there are none"


def test_the_body_grows_with_the_cap_not_the_count(tmp_path):
    small = len(_build(_bank(tmp_path / "a", 13)).model_dump_json(by_alias=True))
    big = len(_build(_bank(tmp_path / "b", 600)).model_dump_json(by_alias=True))
    assert big - small < 1_000, (small, big)


def test_names_no_page_holds_are_capped_like_pages(tmp_path):
    docs = next(g for g in _build(_bank(tmp_path, 600)).cluster.groups if g.label == "Documents")
    assert len([m for m in docs.members if m.pending]) == project_timeline.GROUP_CAP


def test_the_agents_reading_says_how_many_more(tmp_path):
    bank = _bank(tmp_path, 600)
    timeline = _build(bank)
    line = project_text._happening_line(timeline, _item(timeline), memory_path=bank, today=T, raw=False, texts={})
    assert "(+588 more)" in line
    assert line.count("https://example.com/papers/") == 12
