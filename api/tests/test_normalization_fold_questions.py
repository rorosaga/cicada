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


def test_twelve_conversations_before_and_after(tmp_path):
    """The trial's shape: ten conversations of long-tail labels plus two real
    folds of one pair. Before the fix every multi-word long-tail label raised a
    question (9 here: eight long-tail labels and the pair); now only the real
    pair does, once."""
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


# ---------------------------------------------------------------- the migration


def _write_item(memory, num, entity_id, claim_id, raw, canonical, status="pending"):
    markdown_parser.write(memory / "inbox" / f"inbox-{num:03d}.md", {
        "kind": "normalization", "required_input": "choice", "status": status, "priority": 0.3,
        "entity_id": entity_id, "entity_name": entity_id, "title": f"Confirm a predicate fold for {entity_id}",
        "created_date": "2026-10-07", "options": ["Correct fold", "Wrong fold — keep separate"],
        "claim_id": claim_id, "raw_predicate": raw, "canonical_predicate": canonical,
        "trigger": "sleep/conflict_resolution",
    }, f"Predicate '{raw}' was auto-folded to canonical '{canonical}'. Confirm this fold is correct.")


def test_migration_retires_slug_only_items_and_collapses_pairs(tmp_path):
    from api.services.inbox_migration import dedup_normalization_items

    memory = _bank(tmp_path)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.com")
    _git(memory, "config", "user.name", "t")
    _write_item(memory, 1, "alpha-project", "clm_1", "uses dataset", "uses-dataset")
    _write_item(memory, 2, "alpha-project", "clm_2", "built with", "uses")
    _write_item(memory, 3, "bob-example", "clm_3", "Trained On", "trained-on")
    _write_item(memory, 4, "beta-baseline", "clm_4", "Built With", "uses")
    _write_item(memory, 5, "gamma-store", "clm_5", "used", "uses")
    markdown_parser.write(memory / "inbox" / "inbox-006.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project"}, "x")

    removed = dedup_normalization_items(memory)
    stems = sorted(p.stem for p in (memory / "inbox").glob("inbox-*.md"))
    assert removed == 3
    assert stems == ["inbox-002", "inbox-005", "inbox-006"]
    fm = markdown_parser.parse(memory / "inbox" / "inbox-002.md").frontmatter
    assert fm["covered_claims"] == [{"entity_id": "beta-baseline", "claim_id": "clm_4"}]
    assert (memory / "inbox" / ".deduped_normalization").exists()
    # committed, scoped to inbox/ only — the unrelated bank files stay untracked
    assert _git(memory, "ls-files").split() == [f"inbox/{s}.md" for s in stems]
    # marker-guarded: a second run is free and touches nothing
    _write_item(memory, 7, "delta-paper", "clm_7", "uses dataset", "uses-dataset")
    assert dedup_normalization_items(memory) == 0
    assert (memory / "inbox" / "inbox-007.md").exists()


def test_bank_migrations_run_the_fold_cleanup(tmp_path):
    from api.services.bank_migrations import run_bank_migrations

    memory = _bank(tmp_path)
    _write_item(memory, 1, "alpha-project", "clm_1", "uses dataset", "uses-dataset")
    run_bank_migrations(memory)
    assert not (memory / "inbox" / "inbox-001.md").exists()


# ---------------------------------------------------------------- same-batch coverage (review round 1, #1)

_OLD_CLAIM_PAGE = """---
name: Alpha Project
type: project
status: active
version: 1
---
# Alpha Project

```claims
- id: clm_old
  subject: alpha-project
  predicate: uses
  object: example-lib
  observer: agent
  context: general
  source_trust: agent_extracted
  epistemic: explicit
  confidence: 0.6
  valid_from: '2025-12-01'
  recorded_at: '2025-12-01'
  authored_by: test-model
```
"""


def test_one_batch_two_pages_and_a_reinforced_claim_are_all_covered_and_all_repointed(tmp_path):
    from types import SimpleNamespace

    from api.services import claim_pipeline

    memory = _bank(tmp_path)
    (memory / "entities" / "alpha-project.md").write_text(_OLD_CLAIM_PAGE)
    markdown_parser.write(memory / "entities" / "beta-baseline.md",
                          {"name": "Beta Baseline", "type": "project", "status": "active", "version": 1},
                          "# Beta Baseline\n")
    extracted = [
        # restates the claim already on the page: reinforced, the incoming id is discarded
        {"episode_id": "2026-02-01-001", "origin": "chatgpt", "relationships": [
            {**_rel("Alpha Project", "built with", "Example Lib", "2026-02-01-001"),
             "source_episode_timestamp": "2026-02-01T10:00:00"}]},
        {"episode_id": "2026-02-02-001", "origin": "chatgpt", "relationships": [
            {**_rel("Alpha Project", "Built  With", "Other Lib", "2026-02-02-001"),
             "source_episode_timestamp": "2026-02-02T10:00:00"},
            {**_rel("Beta Baseline", "built with", "Example Lib", "2026-02-02-001"),
             "source_episode_timestamp": "2026-02-02T10:00:00"}]},
    ]
    settings = SimpleNamespace(memory_path=memory, litellm_model="test-model", archive_threshold=0.2,
                               decay_nudge_threshold=0.4)
    result = claim_pipeline.run_claim_pipeline(extracted, [], memory, settings, now_date="2026-02-03", decay=False)
    folds = _fold_nudges(result["nudges"])
    assert len(folds) == 1

    def retained(eid):
        page = (memory / "entities" / f"{eid}.md").read_text()
        return {c.id for c in parse_claims(page) if c.predicate == "uses"}

    alpha, beta = retained("alpha-project"), retained("beta-baseline")
    assert "clm_old" in alpha and len(alpha) == 2 and len(beta) == 1
    refs = [(folds[0]["id"], folds[0]["claim_id"])] + [
        (r["entity_id"], r["claim_id"]) for r in folds[0].get("covered_claims") or []]
    assert sorted(refs) == sorted([("alpha-project", c) for c in alpha] + [("beta-baseline", c) for c in beta])

    inbox_generator.write_claim_nudges(result["nudges"], memory)
    (path, _), = _items(memory)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.com")
    _git(memory, "config", "user.name", "t")
    _git(memory, "add", ".")
    _git(memory, "commit", "-q", "-m", "sleep")
    asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="resolve", option_key="1"),
                                      _ResolveSettings(memory)))
    assert retained("alpha-project") == set() and retained("beta-baseline") == set()
    for eid, ids in (("alpha-project", alpha), ("beta-baseline", beta)):
        page = (memory / "entities" / f"{eid}.md").read_text()
        assert {c.id for c in parse_claims(page) if c.predicate == "built-with"} == ids


# ---------------------------------------------------------------- the answer is one critical section (review round 1, #2)

import threading  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402


def _two_pair_bank(tmp_path):
    memory, first = _resolvable_bank(tmp_path)
    inbox_generator.write_claim_nudges(
        [_fold("bob-example", "clm_w", raw="worked at", canonical="works-at")], memory)
    _git(memory, "add", ".")
    _git(memory, "commit", "-q", "-m", "sleep 2")
    second = next(p.stem for p, fm in _items(memory) if fm["raw_predicate"] == "worked at")
    return memory, first, second


def test_two_confirmations_at_once_both_survive(tmp_path, monkeypatch):
    memory, first, second = _two_pair_bank(tmp_path)
    real_read = predicates._read_runtime_map

    def slow_read(memory_path):
        data = real_read(memory_path)
        time.sleep(0.2)   # both answers would have read the map before either wrote it
        return data

    monkeypatch.setattr(predicates, "_read_runtime_map", slow_read)

    errors: list[BaseException] = []

    def answer(item_id):   # each on its own thread and event loop, like two processes
        try:
            asyncio.run(inbox_service.resolve(item_id, InboxResolveRequest(action="resolve", option_key="0"),
                                              _ResolveSettings(memory)))
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=answer, args=(i,)) for i in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert errors == []
    assert predicates.confirmed_folds(memory) == {"built-with": "uses", "worked-at": "works-at"}
    assert _git(memory, "status", "--porcelain").strip() == ""


def test_a_competing_page_writer_never_commits_the_persons_repoint(tmp_path, monkeypatch):
    from api.services import git_service, page_lock

    memory, item_id = _resolvable_bank(tmp_path)
    beta = memory / "entities" / "beta-baseline.md"
    real_commit = git_service.commit_touched_sync
    competitor: list[threading.Thread] = []

    def other_writer():
        with page_lock.page_lock(memory):
            beta.write_text(beta.read_text() + "\nAn agent's note.\n")
            real_commit(memory, git_service.build_commit_message(
                "Agent write", ["entities/beta-baseline.md: updated (trigger: agent)"], authors=["claude-code"]),
                ["entities/beta-baseline.md"])

    def commit_with_a_rival(memory_path, message, paths, **kw):
        if "Inbox resolution" in message and not competitor:
            t = threading.Thread(target=other_writer)
            competitor.append(t)
            t.start()
            time.sleep(0.3)   # the rival is at the page lock while the answer is still uncommitted
        return real_commit(memory_path, message, paths, **kw)

    monkeypatch.setattr(git_service, "commit_touched_sync", commit_with_a_rival)
    asyncio.run(inbox_service.resolve(item_id, InboxResolveRequest(action="resolve", option_key="1"),
                                      _ResolveSettings(memory)))
    competitor[0].join(5)
    agent_commit = _git(memory, "log", "-1", "--format=%H", "--grep=^Agent write").strip()
    assert agent_commit
    assert "predicate: built-with" not in _git(memory, "show", agent_commit)
    person = _git(memory, "log", "-1", "--format=%H", "--grep=^Inbox resolution").strip()
    shown = _git(memory, "show", person)
    assert "Cicada-Author: user" in shown and "beta-baseline.md" in shown


def test_a_window_opening_while_the_answer_waited_refuses_and_writes_nothing(tmp_path, monkeypatch):
    from api.services import page_lock, sleep_cycle
    from api.services.sleep_refusal import SleepWriting

    memory, item_id = _resolvable_bank(tmp_path)
    before = {p: p.read_bytes() for p in memory.rglob("*") if p.is_file() and ".git" not in p.parts}
    # Sleep's window opens after the answer's first checks, while it waits for the page lock.
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: page_lock.held(memory))
    with pytest.raises(SleepWriting):
        asyncio.run(inbox_service.resolve(item_id, InboxResolveRequest(action="resolve", option_key="1"),
                                          _ResolveSettings(memory)))
    after = {p: p.read_bytes() for p in memory.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == before


# ---------------------------------------------------------------- rejecting a pair rejects its spellings (review round 1, #3)


def test_wrong_fold_on_one_spelling_stops_every_spelling_of_the_pair(tmp_path):
    memory, _ = _resolvable_bank(tmp_path)

    def add_spellings(data):
        data["synonyms"]["built-with"] = "uses"          # a slug-shaped key: "Built With!" resolves through it
        data["synonyms"]["built  with"] = "uses"         # a stray double-space key
        data["synonyms"]["is built with"] = "uses"       # a different label: not this pair, stays
        return True

    predicates.update_runtime_map(memory, add_spellings)
    _git(memory, "commit", "-qam", "spellings")
    for p, _ in _items(memory):
        p.unlink()
    inbox_generator.write_claim_nudges([_fold("alpha-project", "clm_a", raw="Built  With")], memory)
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "ask")
    (path, _), = _items(memory)
    asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="resolve", option_key="1"),
                                      _ResolveSettings(memory)))
    normalize = predicates.load_normalizer(memory)
    for spelling in ("built with", "Built  With", "BUILT WITH", "built-with", "Built With!", "built_with"):
        assert normalize(spelling) == "built-with", spelling
    assert normalize("is built with") == "uses"
    # the next extraction neither folds it nor asks
    claims = entities_to_claims(_extracted([("Gamma Store", "Built  With", "Example Lib")]), memory)
    assert claims[0].predicate == "built-with"
    _, nudges, _ = reconcile_stage3(claims, {}, _Settings(memory), decay=False)
    assert _fold_nudges(nudges) == []


# ---------------------------------------------------------------- a shared question stays visible (review round 1, #7)


@pytest.mark.parametrize("opener_fate", ["archived", "gone"])
def test_a_pair_question_stays_visible_when_its_opener_is_archived_or_gone(tmp_path, opener_fate):
    memory = _bank(tmp_path)
    for eid, name in (("alpha-project", "Alpha Project"), ("beta-baseline", "Beta Baseline")):
        markdown_parser.write(memory / "entities" / f"{eid}.md",
                              {"name": name, "type": "project", "status": "active", "version": 1}, f"# {name}\n")
    inbox_generator.write_claim_nudges([_fold("alpha-project", "clm_a")], memory)
    assert inbox_service.served_counts(memory) == (1, {"normalization": 1})
    alpha = memory / "entities" / "alpha-project.md"
    if opener_fate == "archived":
        parsed = markdown_parser.parse(alpha)
        markdown_parser.write(alpha, {**parsed.frontmatter, "status": "archived"}, parsed.body)
    else:
        alpha.unlink()
    out = inbox_generator.write_claim_nudges([_fold("beta-baseline", "clm_b")], memory)
    assert out["written"] == 0 and out["merged"] == 1
    items = [i for i in inbox_service.load_inbox(memory) if i.kind.value == "normalization"]
    assert len(items) == 1
    assert items[0].entity_id == "beta-baseline" and items[0].entity_name == "Beta Baseline"
    assert "Beta Baseline" in items[0].title
    assert inbox_service.served_counts(memory) == (1, {"normalization": 1})


def test_a_pair_question_is_hidden_once_every_covered_page_is_gone(tmp_path):
    memory = _bank(tmp_path)
    inbox_generator.write_claim_nudges([_fold("alpha-project", "clm_a"), _fold("beta-baseline", "clm_b")], memory)
    assert inbox_service.served_counts(memory) == (0, {})
    assert [i for i in inbox_service.load_inbox(memory) if i.kind.value == "normalization"] == []
