"""M5f: claim-reconciler nudges fold into the inbox alongside legacy nudges.

``inbox_generator.write_claim_nudges`` is the additive seam that turns the
Stage-3 claim nudges (``conflict_nudge`` / ``divergence_nudge`` /
``normalization_audit`` / ``decay_nudge`` — the claim-reconciler change shape)
into companion-app inbox items, reusing the same ``inbox-NNN`` id allocator so
ids never collide with the legacy entity-path nudges written earlier in Stage 5.
"""

from __future__ import annotations

from pathlib import Path

from api.services import inbox_generator, markdown_parser


def _read_inbox(memory: Path) -> list[dict]:
    items = []
    for fp in sorted((memory / "inbox").glob("inbox-*.md")):
        parsed = markdown_parser.parse(fp)
        items.append({"stem": fp.stem, "fm": parsed.frontmatter, "body": parsed.body})
    return items


def test_divergence_and_normalization_nudges_written(tmp_path):
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    nudges = [
        {
            "id": "rodrigo",
            "action": "divergence_nudge",
            "entity": {"name": "Rodrigo"},
            "conflict_context": "You said X; I'm now reading Y. Keep your statement?",
            "options": ["Keep X", "Update to Y", "Both true"],
            "trigger": "sleep/conflict_resolution",
            "claim_id": "clm_1",
        },
        {
            "id": "cicada",
            "action": "normalization_audit",
            "entity": {"name": "Cicada"},
            "conflict_context": "Predicate 'built with' was folded to 'uses'. Confirm.",
            "options": ["Correct fold", "Wrong fold"],
            "trigger": "sleep/conflict_resolution",
            "claim_id": "clm_2",
        },
    ]

    inbox_generator.write_claim_nudges(nudges, memory)

    items = _read_inbox(memory)
    kinds = {it["fm"].get("kind") for it in items}
    assert "divergence" in kinds
    assert "normalization" in kinds
    # entity_id is carried so the companion app can route the nudge to a page.
    assert any(it["fm"].get("entity_id") == "rodrigo" for it in items)


def test_claim_nudge_ids_do_not_collide_with_existing(tmp_path):
    memory = tmp_path / "memory"
    inbox = memory / "inbox"
    inbox.mkdir(parents=True)
    # Pretend Stage 5 already wrote inbox-001 from the legacy entity path.
    markdown_parser.write(
        inbox / "inbox-001.md",
        {"kind": "decay", "status": "pending", "entity_id": "x"},
        "legacy",
    )

    inbox_generator.write_claim_nudges(
        [
            {
                "id": "rodrigo",
                "action": "conflict_nudge",
                "entity": {"name": "Rodrigo"},
                "conflict_context": "A vs B",
                "options": ["A", "B"],
                "claim_id": "clm_9",
            }
        ],
        memory,
    )
    stems = {it["stem"] for it in _read_inbox(memory)}
    assert "inbox-001" in stems  # legacy preserved
    assert "inbox-002" in stems  # claim nudge got the next free id, no clobber


def test_write_claim_nudges_empty_is_noop(tmp_path):
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    inbox_generator.write_claim_nudges([], memory)
    assert list((memory / "inbox").glob("inbox-*.md")) == []
