"""G98/G115: a predicate fold is asked about only when it is a real fold, once per pair per bank.

The trial evidence (2026-10-07, generic): ten imported conversations raised 24
"Confirm a predicate fold" items, every one a formatting change — ``uses dataset``
"folded" to ``uses-dataset``, the label's own slug. A slug is the normalizer's
keep-as-is fallback, not a fold, so it is never a question. A real fold (a synonym
in ``_predicates.yaml`` mapping onto a DIFFERENT predicate) is still asked — the D2
audit — but once per ``(raw, canonical)`` pair per bank, not once per claim.
"""

from __future__ import annotations

from pathlib import Path

from api.services import predicates
from api.services.claim_reconciler import reconcile_stage3
from api.services.entity_extractor import entities_to_claims


class _Settings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.litellm_model = "test-model"
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "inbox").mkdir()
    predicates.install_predicate_map(memory)
    return memory


def _rel(source, label, target, ep):
    return {"source": source, "target": target, "label": label, "source_episode": ep}


# Ten synthetic conversations whose relation labels are long-tail phrasings —
# multi-word, mixed case, punctuation — none of them a synonym in the seed map.
_SLUG_ONLY = [
    ("Alpha Project", "uses dataset", "Example Corpus"),
    ("Alpha Project", "Trained On", "Example Corpus"),
    ("Bob Example", "maintains", "Alpha Project"),
    ("Alpha Project", "evaluated   against", "Beta Baseline"),
    ("Alpha Project", "exports_to", "Gamma Store"),
    ("Bob Example", "co-authored", "Delta Paper"),
    ("Alpha Project", "is benchmarked with", "Beta Baseline"),
    ("Delta Paper", "cites (directly)", "Epsilon Paper"),
    ("Alpha Project", "deployed via", "Gamma Store"),
    ("Bob Example", "presented at", "Zeta Meetup"),
]


def _extracted(rows):
    return [
        {"episode_id": f"2026-01-{i + 1:02d}-001", "origin": "chatgpt",
         "relationships": [_rel(s, label, t, f"2026-01-{i + 1:02d}-001")]}
        for i, (s, label, t) in enumerate(rows)
    ]


def _fold_nudges(nudges):
    return [n for n in nudges if n.get("action") == "normalization_audit"]


# ---------------------------------------------------------------- reconciler


def test_a_slug_of_the_raw_label_is_never_a_fold_question(tmp_path):
    memory = _bank(tmp_path)
    claims = entities_to_claims(_extracted(_SLUG_ONLY), memory)
    assert len(claims) == 10
    # every canonical is the raw label's own slug — nothing was folded
    assert all(c.predicate == predicates._slugify_predicate(c.predicate_raw) for c in claims)
    _, nudges, _ = reconcile_stage3(claims, {}, _Settings(memory), decay=False)
    assert _fold_nudges(nudges) == []


def test_a_real_fold_is_still_asked(tmp_path):
    memory = _bank(tmp_path)
    # "built with" is a seed synonym of `uses` — a different predicate
    claims = entities_to_claims(_extracted([("Alpha Project", "Built With", "Example Lib")]), memory)
    assert claims[0].predicate == "uses"
    _, nudges, _ = reconcile_stage3(claims, {}, _Settings(memory), decay=False)
    folds = _fold_nudges(nudges)
    assert len(folds) == 1
    assert folds[0]["raw_predicate"] == "Built With"
    assert folds[0]["canonical_predicate"] == "uses"


def test_a_canonical_label_written_as_words_is_not_a_fold(tmp_path):
    memory = _bank(tmp_path)
    # "works at" slugs to the canonical `works-at` — the same predicate
    claims = entities_to_claims(_extracted([("Bob Example", "Works  At", "Alpha Corp")]), memory)
    assert claims[0].predicate == "works-at"
    _, nudges, _ = reconcile_stage3(claims, {}, _Settings(memory), decay=False)
    assert _fold_nudges(nudges) == []


def test_ten_conversations_before_and_after(tmp_path):
    """The trial's shape: ten conversations of long-tail labels plus two real
    folds of one pair. Before the fix every long-tail label raised a question;
    now only the real pair does, once."""
    memory = _bank(tmp_path)
    rows = _SLUG_ONLY + [
        ("Alpha Project", "built with", "Example Lib"),
        ("Beta Baseline", "built with", "Example Lib"),
    ]
    claims = entities_to_claims(_extracted(rows), memory)
    _, nudges, _ = reconcile_stage3(claims, {}, _Settings(memory), decay=False)
    folds = _fold_nudges(nudges)
    assert [(n["raw_predicate"], n["canonical_predicate"]) for n in folds] == [("built with", "uses")]
