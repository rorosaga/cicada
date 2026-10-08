"""`owner_name`'s fallback scan reads frontmatter through the stat-cached bank index (F8, benchmarks/scale).

When `owner.json` names no page of this bank (a fresh bank, a bank switch, an install from before `entity_id`),
every call parsed every page's frontmatter — and Sleep calls it ~21 times a batch: 42k parses on a 2,000-page
synthetic bank. Through `bank_index` an unchanged page is parsed once per process.
"""
from __future__ import annotations

from api.services import bank_index, markdown_parser, owner_identity


def test_the_fallback_scan_parses_an_unchanged_bank_once(tmp_path, monkeypatch):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    for i in range(30):
        markdown_parser.write(bank / "entities" / f"page-{i:02d}.md", {"name": f"Page {i}", "type": "concept"}, "x")
    markdown_parser.write(bank / "entities" / "owner-example.md",
                          {"name": "Owner Example", "type": "person", "owner": True}, "x")
    bank_index.invalidate()
    assert owner_identity.owner_name(bank) == "Owner Example"
    parsed = []
    original = markdown_parser.parse
    monkeypatch.setattr(markdown_parser, "parse", lambda path: parsed.append(path.name) or original(path))
    assert owner_identity.owner_name(bank) == "Owner Example"
    assert [n for n in parsed if n != "owner.md"] == []
