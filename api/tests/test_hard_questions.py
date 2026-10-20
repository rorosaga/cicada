"""benchmarks/hard_questions.py: seeded sampling of hard-question shapes from a bank's claims and evidence, one draft
per sample through an injected engine, local 0600 outputs, the review-and-accept step, and the bank left untouched.
Synthetic bank only (``_hard_questions_bank``); the engine is a fake, so no plan call is made."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.tests import _hard_questions_bank
from benchmarks import answer_eval, hard_questions as hq


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    return _hard_questions_bank.build(tmp_path / "bank")


def _snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class FakeEngine:
    """Answers each draft prompt with a well-formed draft (or what ``reply`` returns), counting calls."""

    def __init__(self, reply=None):
        self.calls = 0
        self.prompts: list[str] = []
        self.reply = reply

    def __call__(self, messages, response_format=None):
        self.calls += 1
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        payload = self.reply(prompt) if self.reply else {
            "question": f"Synthetic question {self.calls}?", "expect": ["a synthetic fact"],
            "forbid": ["a stale synthetic fact"] if "KNOWLEDGE UPDATE" in prompt else [],
            "abstain": "ABSTENTION" in prompt, "why": "synthetic reason", "skip": False}
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_every_kind_is_found_and_the_owner_and_saved_links_never_are(bank):
    b = hq.Bank(bank)
    assert "bob-example" not in b.pages                      # the owner page is never a subject
    pools = {kind: sampler(b) for kind, sampler in hq.SAMPLERS.items()}
    assert all(pools.values()), {k: len(v) for k, v in pools.items()}
    every = [s for pool in pools.values() for s in pool]
    assert not any(s.page == "a-video" for s in every)       # a saved link is kept, not talked over

    updates = {s.key: s for s in pools["update"]}
    assert "update:alpha-project:c-a1:c-a2" in updates
    assert updates["update:alpha-project:c-a1:c-a2"].extra["stale"] == "alpha-project uses sqlite-example"
    # A superseded claim whose successor was itself superseded is no update question: the later value is not current.
    assert not any(":c-r1:c-r2" in k for k in updates) and any(":c-r2:c-r3" in k for k in updates)

    hop = next(s for s in pools["multi-hop"] if s.page == "carol-example")
    assert len(set(hop.sources)) == 2                          # each hop from its own conversation
    temporal = next(s for s in pools["temporal"] if s.page == "carol-example")
    assert temporal.extra["gap_days"] >= hq.MIN_GAP_DAYS
    assert all(len(s.sources) >= 3 for s in pools["count"])
    event = next(s for s in pools["event"])
    assert event.page == "garden-sensor" and len(event.claims) == 2
    # Snippets come from the claim's own evidence span, in the conversation it cites.
    snip = updates["update:alpha-project:c-a1:c-a2"].snippets[0]
    assert "going with sqlite-example as the database" in snip["text"] and snip["day"] == "2026-03-02"


def test_the_draw_is_seeded_one_sample_a_page_and_spanish_is_a_share(bank):
    b = hq.Bank(bank)
    first = [(s.id, s.spanish) for s in hq.draw(b, 10, seed=7)]
    again = [(s.id, s.spanish) for s in hq.draw(hq.Bank(bank), 10, seed=7)]
    assert first == again
    samples = hq.draw(b, 10, seed=7)
    assert len({s.page for s in samples}) == len(samples)
    assert len({s.kind for s in samples}) >= 4
    spanish = [s.spanish for seed in range(40) for s in hq.draw(hq.Bank(bank), 10, seed=seed)]
    assert 0.1 < sum(spanish) / len(spanish) < 0.4
    assert [s.id for s in hq.draw(hq.Bank(bank), 2, seed=7)] == [i for i, _ in first[:2]]   # a smaller limit is a prefix
    assert len(hq.draw(b, 0, seed=1)) == 0


def test_a_draft_run_writes_eval_ready_yaml_and_a_review_sheet_and_leaves_the_bank(bank, tmp_path, capsys):
    out, review = tmp_path / "out" / "hard.local.yaml", tmp_path / "out" / "review.local.md"
    before = _snapshot(bank)
    engine = FakeEngine()
    summary = hq.run(bank, limit=8, seed=3, out=out, review=review, dry_run=False, fresh=False, kinds=hq.KINDS,
                     llm=engine)
    assert _snapshot(bank) == before                           # never writes the bank
    assert summary["plan_calls"] == engine.calls == summary["samples"]   # one call a question, no more
    assert oct(out.stat().st_mode & 0o777) == "0o600" and oct(review.stat().st_mode & 0o777) == "0o600"

    questions = answer_eval.load_questions(out)                # the eval reads it as is
    assert len(questions) == summary["drafted"] == summary["samples"]
    for q in questions:
        assert q["id"].startswith("hq-") and set(q["tags"]) <= hq.TAGS
    import yaml
    items = yaml.safe_load(out.read_text())["questions"]
    for item in items:
        assert item["sources"] and all(s.startswith("ep_") for s in item["sources"])
        if "update" in item["tags"]:
            assert item["forbid"]
        if "abstention" in item["tags"]:
            assert item["abstain"] is True and item["expect"] == [] and item["why"]

    sheet = review.read_text()
    assert sheet.count("- [ ] accept hq-") == len(items)
    assert "Evidence shown:" in sheet
    printed = capsys.readouterr().out
    assert "Synthetic question" not in printed and "sqlite-example" not in printed   # ids and counts only


def test_spanish_samples_ask_for_spanish(bank, tmp_path):
    b = hq.Bank(bank)
    seed = next(s for s in range(50) if any(x.spanish for x in hq.draw(b, 10, seed=s)))
    sample = next(x for x in hq.draw(hq.Bank(bank), 10, seed=seed) if x.spanish)
    assert "Spanish" in hq.draft_prompt(sample, b) and "es" in sample.tags


def test_dry_run_makes_no_call_and_writes_no_questions(bank, tmp_path):
    def boom(**_):
        raise AssertionError("a dry run calls no engine")

    out, review = tmp_path / "hard.yaml", tmp_path / "review.md"
    summary = hq.run(bank, limit=6, seed=1, out=out, review=review, dry_run=True, fresh=False, kinds=hq.KINDS,
                     llm=boom)
    assert summary["plan_calls"] == 0 and not out.exists()
    assert "Sample only (dry run)" in review.read_text()


def test_unusable_drafts_are_skipped_with_a_reason(bank, tmp_path):
    def reply(prompt):
        if "ABSTENTION" in prompt:
            return {"question": "Q?", "abstain": True, "why": "", "skip": False}      # no reason: unusable
        if "KNOWLEDGE UPDATE" in prompt:
            return {"question": "Q?", "expect": ["new value"], "forbid": [], "skip": False}   # forbid filled in
        if "EVENTS" in prompt:
            return "not json at all"
        return {"skip": True, "why": "evidence too thin"}

    import yaml

    def drafted(kinds):
        out, review = tmp_path / f"{kinds[0]}.yaml", tmp_path / f"{kinds[0]}.md"
        hq.run(bank, limit=3, seed=2, out=out, review=review, dry_run=False, fresh=False, kinds=kinds,
               llm=FakeEngine(reply))
        return yaml.safe_load(out.read_text())["questions"] or [], review.read_text()

    items, _ = drafted(("update",))
    assert items and all(i["forbid"] for i in items)          # the stale claim, when the drafter gave none
    stale = {i["forbid"][0] for i in items}
    assert stale <= {"alpha-project uses sqlite-example", "Mejor grado en rocodromo-example: 6b"}
    for kinds, reason in ((("abstention",), "abstention without a reason"), (("event",), "unparseable reply"),
                          (("count",), "drafter skipped: evidence too thin")):
        items, sheet = drafted(kinds)
        assert items == [] and reason in sheet


def test_a_rerun_keeps_drafts_and_fresh_redrafts(bank, tmp_path):
    out, review = tmp_path / "hard.yaml", tmp_path / "review.md"
    kw = dict(limit=5, seed=4, out=out, review=review, dry_run=False, kinds=hq.KINDS)
    first = FakeEngine()
    hq.run(bank, fresh=False, llm=first, **kw)
    second = FakeEngine()
    summary = hq.run(bank, fresh=False, llm=second, **kw)
    assert second.calls == 0 and summary["drafted"] == first.calls
    third = FakeEngine()
    hq.run(bank, fresh=True, llm=third, **kw)
    assert third.calls == first.calls


def test_accept_keeps_only_ticked_questions(bank, tmp_path):
    out, review, accepted = tmp_path / "hard.yaml", tmp_path / "review.md", tmp_path / "accepted.yaml"
    hq.run(bank, limit=4, seed=5, out=out, review=review, dry_run=False, fresh=False, kinds=hq.KINDS,
           llm=FakeEngine())
    sheet = review.read_text()
    first_id = sheet.split("- [ ] accept ", 1)[1].split()[0]
    review.write_text(sheet.replace(f"- [ ] accept {first_id}", f"- [x] accept {first_id}"))
    assert hq.main(["--accept", "--out", str(out), "--review", str(review), "--accepted", str(accepted)]) == 0
    kept = answer_eval.load_questions(accepted)
    assert [q["id"] for q in kept] == [first_id]
    assert oct(accepted.stat().st_mode & 0o777) == "0o600"


def test_outputs_inside_the_bank_are_refused(bank, tmp_path):
    assert hq.main(["--bank", str(bank), "--dry-run", "--out", str(bank / "q.yaml"),
                    "--review", str(tmp_path / "r.md")]) == 2
    assert hq.main(["--bank", str(tmp_path / "nowhere"), "--dry-run"]) == 2
    assert not (bank / "q.yaml").exists()


def test_the_cli_dry_run_prints_counts_only(bank, tmp_path, capsys):
    review = tmp_path / "r.md"
    assert hq.main(["--bank", str(bank), "--dry-run", "--limit", "6", "--out", str(tmp_path / "q.yaml"),
                    "--review", str(review)]) == 0
    printed = capsys.readouterr().out
    assert "0 plan calls" in printed and "carol-example" not in printed and "sqlite" not in printed
    assert review.is_file() and os.stat(review).st_mode & 0o077 == 0
