"""G98/G115: a predicate fold is asked about only when it is a real fold, once per pair per bank.

The trial evidence (2026-10-07, generic): ten imported conversations raised 24
"Confirm a predicate fold" items, every one a formatting change — ``uses dataset``
"folded" to ``uses-dataset``, the label's own slug. A slug is the normalizer's
keep-as-is fallback, not a fold, so it is never a question. A real fold (a synonym
in ``_predicates.yaml`` mapping onto a DIFFERENT predicate) is still asked — the D2
audit — but once per ``(raw, canonical)`` pair per bank, not once per claim.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import yaml

from api.models.schemas import InboxResolveRequest
from api.services import inbox_generator, inbox_service, markdown_parser, predicates
from api.services.claims import parse_claims
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


# ---------------------------------------------------------------- the writer


def _fold(entity_id, claim_id, raw="built with", canonical="uses"):
    return {
        "id": entity_id, "action": "normalization_audit", "entity": {"name": entity_id},
        "conflict_context": f"Predicate '{raw}' was auto-folded to canonical '{canonical}'. Confirm this fold is correct.",
        "options": ["Correct fold", "Wrong fold — keep separate"],
        "source_episode": "2026-01-01-001", "trigger": "sleep/conflict_resolution",
        "claim_id": claim_id, "raw_predicate": raw, "canonical_predicate": canonical,
    }


def _items(memory, kind="normalization"):
    out = []
    for p in sorted((memory / "inbox").glob("inbox-*.md")):
        fm = markdown_parser.parse(p).frontmatter
        if fm.get("kind") == kind:
            out.append((p, fm))
    return out


def test_one_question_per_pair_across_claims_entities_and_runs(tmp_path):
    memory = _bank(tmp_path)
    first = inbox_generator.write_claim_nudges(
        [_fold("alpha-project", "clm_a"), _fold("beta-baseline", "clm_b"),
         # same pair, the raw label spelled differently — still one pair
         _fold("gamma-store", "clm_c", raw="Built  With")],
        memory,
    )
    # a later batch / a later Sleep: the open item covers it, no new file
    second = inbox_generator.write_claim_nudges([_fold("delta-paper", "clm_d")], memory)
    items = _items(memory)
    assert len(items) == 1
    assert first["written"] == 1 and second["written"] == 0
    _, fm = items[0]
    assert fm["entity_id"] == "alpha-project" and fm["claim_id"] == "clm_a"
    assert fm["covered_claims"] == [
        {"entity_id": "beta-baseline", "claim_id": "clm_b"},
        {"entity_id": "gamma-store", "claim_id": "clm_c"},
        {"entity_id": "delta-paper", "claim_id": "clm_d"},
    ]


def test_a_different_pair_is_its_own_question(tmp_path):
    memory = _bank(tmp_path)
    inbox_generator.write_claim_nudges(
        [_fold("alpha-project", "clm_a"), _fold("alpha-project", "clm_b", raw="used")], memory,
    )
    assert len(_items(memory)) == 2


def test_a_confirmed_fold_is_never_asked_again(tmp_path):
    memory = _bank(tmp_path)
    data = yaml.safe_load((memory / predicates.RUNTIME_FILE).read_text())
    data["confirmed_folds"] = {"built-with": "uses"}
    (memory / predicates.RUNTIME_FILE).write_text(yaml.safe_dump(data, sort_keys=False))
    out = inbox_generator.write_claim_nudges([_fold("alpha-project", "clm_a")], memory)
    assert _items(memory) == []
    assert out["written"] == 0 and out["skipped_confirmed_folds"] == 1


def test_an_answered_pair_is_asked_again_only_if_it_was_not_confirmed(tmp_path):
    """A resolved item is gone from disk; only a confirmation is remembered."""
    memory = _bank(tmp_path)
    inbox_generator.write_claim_nudges([_fold("alpha-project", "clm_a")], memory)
    (path, _), = _items(memory)
    path.unlink()  # answered without confirming (e.g. an old build's resolve)
    inbox_generator.write_claim_nudges([_fold("beta-baseline", "clm_b")], memory)
    assert len(_items(memory)) == 1


# ---------------------------------------------------------------- the resolve

_PAGE = """---
type: project
status: active
confidence: 0.7
created: 2026-01-01
last_referenced: 2026-06-01
decay_rate: 0.05
source_episodes: []
tags: []
related: []
version: 1
---
# {name}

```claims
- id: {cid}
  subject: {eid}
  predicate: uses
  object: example-lib
  observer: agent
  source_trust: agent_extracted
  epistemic: explicit
  confidence: 0.6
  valid_from: '2026-01-01'
  recorded_at: '2026-01-01'
  authored_by: test-model
```
"""


class _ResolveSettings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _resolvable_bank(tmp_path):
    memory = _bank(tmp_path)
    for eid, name, cid in (("alpha-project", "Alpha Project", "clm_a"), ("beta-baseline", "Beta Baseline", "clm_b")):
        (memory / "entities" / f"{eid}.md").write_text(_PAGE.format(name=name, eid=eid, cid=cid))
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.com")
    _git(memory, "config", "user.name", "t")
    _git(memory, "add", ".")
    _git(memory, "commit", "-q", "-m", "seed")
    inbox_generator.write_claim_nudges([_fold("alpha-project", "clm_a"), _fold("beta-baseline", "clm_b")], memory)
    _git(memory, "add", ".")
    _git(memory, "commit", "-q", "-m", "sleep")
    (path, _), = _items(memory)
    return memory, path.stem


def _predicate(memory, eid, cid):
    page = (memory / "entities" / f"{eid}.md").read_text()
    return next(c.predicate for c in parse_claims(page) if c.id == cid)


def test_correct_fold_is_remembered_and_never_asked_again(tmp_path):
    memory, item_id = _resolvable_bank(tmp_path)
    before = yaml.safe_load((memory / predicates.RUNTIME_FILE).read_text())
    asyncio.run(inbox_service.resolve(item_id, InboxResolveRequest(action="resolve", option_key="0"),
                                      _ResolveSettings(memory)))
    after = yaml.safe_load((memory / predicates.RUNTIME_FILE).read_text())
    assert after["confirmed_folds"] == {"built-with": "uses"}
    assert after["synonyms"] == before["synonyms"] and after["canonical"] == before["canonical"]
    assert predicates.confirmed_folds(memory) == {"built-with": "uses"}
    # committed with the answer, not left dirty
    assert _git(memory, "status", "--porcelain", predicates.RUNTIME_FILE).strip() == ""
    inbox_generator.write_claim_nudges([_fold("gamma-store", "clm_c")], memory)
    assert _items(memory) == []


def test_wrong_fold_repoints_every_covered_claim(tmp_path):
    memory, item_id = _resolvable_bank(tmp_path)
    asyncio.run(inbox_service.resolve(item_id, InboxResolveRequest(action="resolve", option_key="1"),
                                      _ResolveSettings(memory)))
    assert _predicate(memory, "alpha-project", "clm_a") == "built-with"
    assert _predicate(memory, "beta-baseline", "clm_b") == "built-with"
    assert predicates.load_normalizer(memory)("built with") == "built-with"
    assert _git(memory, "status", "--porcelain").strip() == ""
