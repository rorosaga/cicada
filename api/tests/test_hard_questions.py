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
            "question": f"What did the synthetic record say, case {self.calls}?", "expect": ["a synthetic fact"],
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
    assert "synthetic record" not in printed and "sqlite-example" not in printed   # ids and counts only


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
            return {"question": "What did the ticket cost me?", "abstain": True, "why": "", "skip": False}
        if "KNOWLEDGE UPDATE" in prompt:
            return {"question": "Which database does it use now?", "expect": ["new value"], "forbid": [],
                    "skip": False}
        if "EVENTS" in prompt:
            return "not json at all"
        return {"skip": True, "why": "evidence too thin"}

    import yaml

    def drafted(kinds):
        out, review = tmp_path / f"{kinds[0]}.yaml", tmp_path / f"{kinds[0]}.md"
        hq.run(bank, limit=3, seed=2, out=out, review=review, dry_run=False, fresh=False, kinds=kinds,
               llm=FakeEngine(reply))
        return yaml.safe_load(out.read_text())["questions"] or [], review.read_text()

    for kinds, reason in ((("abstention",), "abstention without a reason"), (("event",), "unparseable reply"),
                          (("count",), "drafter skipped: evidence too thin"),
                          # An update the drafter forbids nothing on is one it judged both-true: skipped, never
                          # filled in from the stale claim (2026-10-20 review: 4 of 5 updates forbade a true value).
                          (("update",), "update with nothing the later evidence replaces")):
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


# ---------------------------------------------------------------------------------- 2026-10-20 review: the rejections
# The first run on a real bank (40 samples, 27 accepted) rejected drafts in five shapes; each test below rebuilds one
# shape with placeholder names and checks it no longer reaches the sheet as a question.

W = _hard_questions_bank.write_episode
P = _hard_questions_bank.write_page


def _row(cid, text, subj, pred, obj, kind, vfrom, ep, quote, *, vto=None, sup_by=None, **more):
    return (cid, text, subj, pred, obj, kind, vfrom, vto, sup_by, ep, quote, more)


def test_an_update_is_sampled_only_when_the_later_value_cannot_hold_beside_the_earlier(bank):
    # Granularity: a venue, then the city the venue is in — both true, and the venue's page says so.
    W(bank, "ep_2026-03-01_101", "2026-03-01T10:00:00Z", "talk", "user: The meetup is held at venue-example.")
    W(bank, "ep_2026-05-01_101", "2026-05-01T10:00:00Z", "talk", "user: The meetup is held in city-b now.")
    P(bank, "venue-example", "venue-example", "place", {}, [
        _row("c-v1", "venue-example is in city-b", "venue-example", "located-in", "city-b", "node", "2026-03-01",
             "ep_2026-03-01_101", "held at venue-example")])
    P(bank, "city-b", "city-b", "place", {}, [
        _row("c-cb", "city-b hosts the meetup", "city-b", "hosts", "meetup-example", "node", "2026-05-01",
             "ep_2026-05-01_101", "held in city-b")])
    P(bank, "meetup-example", "meetup-example", "event", {}, [
        _row("c-m1", "meetup-example is held at venue-example", "meetup-example", "held-at", "venue-example", "node",
             "2026-03-01", "ep_2026-03-01_101", "held at venue-example", vto="2026-05-01", sup_by="c-m2"),
        _row("c-m2", "meetup-example is held in city-b", "meetup-example", "held-at", "city-b", "node",
             "2026-05-01", "ep_2026-05-01_101", "held in city-b", supersedes="c-m1")])
    # A facet: a managed VM, then the OS of that VM — the values share their head word.
    W(bank, "ep_2026-03-02_101", "2026-03-02T10:00:00Z", "infra", "user: server-example runs on a tool-x managed VM.")
    W(bank, "ep_2026-06-02_101", "2026-06-02T10:00:00Z", "infra", "user: server-example runs on an os-y VM.")
    P(bank, "server-example", "server-example", "tool", {}, [
        _row("c-s1", "server-example runs on a tool-x managed VM", "server-example", "runs-on", "tool-x managed VM",
             "literal", "2026-03-02", "ep_2026-03-02_101", "runs on a tool-x managed VM", vto="2026-06-02",
             sup_by="c-s2"),
        _row("c-s2", "server-example runs on an os-y VM", "server-example", "runs-on", "os-y VM", "literal",
             "2026-06-02", "ep_2026-06-02_101", "runs on an os-y VM", supersedes="c-s1")])
    # Two predicates: an offer at one place, then waiting on another.
    W(bank, "ep_2026-04-01_101", "2026-04-01T10:00:00Z", "jobs", "user: dave-example has a return offer at org-a.")
    W(bank, "ep_2026-07-01_101", "2026-07-01T10:00:00Z", "jobs", "user: dave-example is waiting on org-b.")
    P(bank, "dave-example", "dave-example", "person", {}, [
        _row("c-d1", "dave-example has a return offer at org-a", "dave-example", "has-offer-at", "org-a", "literal",
             "2026-04-01", "ep_2026-04-01_101", "has a return offer at org-a", vto="2026-07-01", sup_by="c-d2"),
        _row("c-d2", "dave-example is waiting on org-b", "dave-example", "waiting-on", "org-b", "literal",
             "2026-07-01", "ep_2026-07-01_101", "is waiting on org-b", supersedes="c-d1")])
    # A set-valued predicate whose later evidence never names the earlier value: both may hold.
    W(bank, "ep_2026-04-02_101", "2026-04-02T10:00:00Z", "jobs", "user: erin-example works at org-c.")
    W(bank, "ep_2026-08-02_101", "2026-08-02T10:00:00Z", "jobs", "user: erin-example started at org-d this week.")
    P(bank, "erin-example", "erin-example", "person", {}, [
        _row("c-e1", "erin-example works at org-c", "erin-example", "works-at", "org-c", "literal", "2026-04-02",
             "ep_2026-04-02_101", "works at org-c", vto="2026-08-02", sup_by="c-e2"),
        _row("c-e2", "erin-example works at org-d", "erin-example", "works-at", "org-d", "literal", "2026-08-02",
             "ep_2026-08-02_101", "started at org-d", supersedes="c-e1")])

    b = hq.Bank(bank)
    keys = {s.key for s in hq.SAMPLERS["update"](b)}
    for page in ("meetup-example", "server-example", "dave-example", "erin-example"):
        assert not any(f"update:{page}:" in k for k in keys), page
    reasons = {page: hq.exclusive_update(b, b.pages[page], *b.pages[page].claims[:2])
               for page in ("meetup-example", "server-example", "dave-example", "erin-example")}
    assert reasons == {"meetup-example": "the values' pages link each other",
                       "server-example": "the values share a word (a facet, not a replacement)",
                       "dave-example": "different predicates",
                       "erin-example": "a set-valued predicate whose later evidence never names the earlier value"}
    # The fair ones stay: a set-valued `uses` whose later evidence says "from X to Y", and a single-valued value.
    assert "update:alpha-project:c-a1:c-a2" in keys and "update:rocodromo-example:c-r2:c-r3" in keys
    # And the drafter is told to forbid only what the later evidence replaces, else skip.
    prompt = hq.draft_prompt(next(s for s in hq.SAMPLERS["update"](b) if s.page == "alpha-project"), b)
    assert "ONLY the earlier value the later evidence replaces" in prompt and "return skip" in prompt


def test_temporal_and_event_samples_never_anchor_on_a_save_or_a_bulk_import_day(bank):
    # A bookmark episode: its day is the sync's.
    W(bank, "ep_2026-01-10_101", "2026-01-10T10:00:00Z", "tool talk", "user: I started using gamma-tool for notes.")
    W(bank, "ep_2026-08-20_101", "2026-08-20T10:00:00Z", "gamma-tool docs", "saved gamma-tool documentation",
      source="bookmark", origin="chrome-bookmark", url="https://example.com/gamma")
    P(bank, "gamma-tool", "gamma-tool", "tool", {}, [
        _row("c-gt1", "Started using gamma-tool", "gamma-tool", "happened", "started", "literal", "2026-01-10",
             "ep_2026-01-10_101", "started using gamma-tool", vto="2026-01-10", status="done"),
        _row("c-gt2", "Saved gamma-tool documentation", "gamma-tool", "happened", "docs saved", "literal",
             "2026-08-20", "ep_2026-08-20_101", "saved gamma-tool documentation", vto="2026-08-20", status="done")])
    # A bulk import: one origin wrote more than BULK_DAY episodes on one day.
    for i in range(hq.BULK_DAY + 1):
        W(bank, f"ep_2026-09-10_{200 + i}", "2026-09-10T08:00:00Z", f"note {i}",
          f"user: imported note {i} about delta-topic.", origin="notes-import", source="apple-notes")
    W(bank, "ep_2026-02-01_101", "2026-02-01T10:00:00Z", "delta", "user: I keep thinking about delta-topic.")
    P(bank, "delta-topic", "delta-topic", "concept", {}, [
        _row("c-dt1", "Thinks about delta-topic", "delta-topic", "interested-in", "delta-topic", "literal",
             "2026-02-01", "ep_2026-02-01_101", "thinking about delta-topic"),
        _row("c-dt2", "A note about delta-topic", "delta-topic", "noted", "note", "literal", "2026-09-10",
             "ep_2026-09-10_200", "imported note 0 about delta-topic")])

    b = hq.Bank(bank)
    assert b.conversation("ep_2026-08-20_101").moment is False          # a save
    assert b.conversation("ep_2026-09-10_200").moment is False          # one of a bulk day
    assert b.conversation("ep_2026-02-01_101").moment is True
    temporal = {s.page for s in hq.SAMPLERS["temporal"](b)}
    assert "gamma-tool" not in temporal and "delta-topic" not in temporal
    assert "carol-example" in temporal                                  # two real conversations still count
    assert not any(s.page == "gamma-tool" for s in hq.SAMPLERS["event"](b))   # one dated happening left: no order
    # A live session's own captures are never a bulk day, however many there are.
    for i in range(hq.BULK_DAY + 1):
        W(bank, f"ep_2026-09-11_{300 + i}", "2026-09-11T08:00:00Z", f"s {i}", f"user: session {i}",
          session_id=f"sess-{i}")
    assert not hq.Bank(bank).bulk & {f"ep_2026-09-11_{300 + i}" for i in range(hq.BULK_DAY + 1)}


def test_two_things_sharing_a_name_are_never_one_evolving_subject(bank):
    # One "notes-file" page that Sleep tied to two conversations in two unrelated repos, months apart.
    W(bank, "ep_2026-02-03_101", "2026-02-03T10:00:00Z", "a", "user: notes-file in proj-a says to run the tests.",
      session_id="s-a", project_dir="/work/proj-a")
    W(bank, "ep_2026-07-03_101", "2026-07-03T10:00:00Z", "b", "user: notes-file in proj-b lists the deploy steps.",
      session_id="s-b", project_dir="/work/proj-b")
    P(bank, "notes-file", "notes-file", "document", {}, [
        _row("c-n1", "notes-file says to run the tests", "notes-file", "says", "run the tests", "literal",
             "2026-02-03", "ep_2026-02-03_101", "notes-file in proj-a says to run the tests", vto="2026-07-03",
             sup_by="c-n2"),
        _row("c-n2", "notes-file lists the deploy steps", "notes-file", "says", "deploy steps", "literal",
             "2026-07-03", "ep_2026-07-03_101", "notes-file in proj-b lists the deploy steps",
             supersedes="c-n1")])
    b = hq.Bank(bank)
    assert not any(s.page == "notes-file" for s in hq.SAMPLERS["temporal"](b))
    assert not any(s.page == "notes-file" for s in hq.SAMPLERS["update"](b))
    page = b.pages["notes-file"]
    assert not b.same_context("ep_2026-02-03_101", "ep_2026-07-03_101", page)

    # Two worktrees of one repo are one project; two project pages that share none are two contexts.
    W(bank, "ep_2026-02-04_101", "2026-02-04T10:00:00Z", "c", "user: tool-z setup", project_dir="/work/proj-c")
    W(bank, "ep_2026-07-04_101", "2026-07-04T10:00:00Z", "d", "user: tool-z again",
      project_dir="/work/proj-c/.worktrees/feature-x")
    b = hq.Bank(bank)
    assert b.same_context("ep_2026-02-04_101", "ep_2026-07-04_101", b.pages["notes-file"])
    b.projects_of["ep_2026-02-04_101"] = {"proj-c"}
    b.projects_of["ep_2026-07-04_101"] = {"proj-d"}
    assert not b.same_context("ep_2026-02-04_101", "ep_2026-07-04_101", b.pages["notes-file"])
    # A project page is its own context: its conversations are about it, whatever else they cite.
    assert b.same_context("ep_2026-02-04_101", "ep_2026-07-04_101", b.pages["alpha-project"]) is True


def test_an_empty_draft_is_skipped_with_a_reason_and_an_empty_reply_retried_once(bank, tmp_path):
    import yaml

    def run(reply, **kw):
        out, review = tmp_path / "e.yaml", tmp_path / "e.md"
        engine = FakeEngine(reply)
        summary = hq.run(bank, limit=1, seed=1, out=out, review=review, dry_run=False, fresh=True,
                         kinds=("count",), llm=engine, **kw)
        return summary, engine, (yaml.safe_load(out.read_text())["questions"] or []), review.read_text()

    good = {"question": "Which places did I mention for it?", "expect": ["a place"], "forbid": [], "skip": False}
    replies = iter(["", good])
    summary, engine, items, _ = run(lambda _p: next(replies))
    assert engine.calls == summary["plan_calls"] == 2 and summary["retries"] == 1 and len(items) == 1

    summary, engine, items, sheet = run(lambda _p: "")
    assert engine.calls == 2 and items == [] and "empty draft: the engine returned nothing twice" in sheet
    summary, engine, items, sheet = run(lambda _p: {})
    assert engine.calls == 2 and items == [] and "empty draft" in sheet

    # The template echoed back, or a blank question: never "drafted", one call (it was not empty).
    for reply in ({"question": "...", "expect": ["..."], "skip": False},
                  {"question": " ", "expect": ["a fact"], "skip": False},
                  {"question": "¿?", "expect": ["a fact"], "skip": False}):
        summary, engine, items, sheet = run(lambda _p, r=reply: r)
        assert items == [] and engine.calls == 1 and "empty draft: no usable question" in sheet
        assert "**Q:**" not in sheet

    # A blank question kept from an earlier run is redrafted, not carried forward.
    out, review = tmp_path / "keep.yaml", tmp_path / "keep.md"
    hq.run(bank, limit=1, seed=1, out=out, review=review, dry_run=False, fresh=False, kinds=("count",),
           llm=FakeEngine())
    data = yaml.safe_load(out.read_text())
    data["questions"][0]["question"] = ""
    out.write_text(yaml.safe_dump(data))
    again = FakeEngine()
    hq.run(bank, limit=1, seed=1, out=out, review=review, dry_run=False, fresh=False, kinds=("count",), llm=again)
    assert again.calls == 1 and yaml.safe_load(out.read_text())["questions"][0]["question"]


def test_an_abstention_answered_by_any_shown_snippet_is_rejected(bank):
    b = hq.Bank(bank)
    sample = hq.Sample("abstention", "abstention:x", "alpha-project", False, ["ep_2026-03-02_001"],
                       ["[current] alpha-project uses postgres-example"],
                       [{"episode": "e1", "day": "2026-03-02", "title": "t",
                         "text": "user: The demo went fine.\nuser: We upgraded the sync workers to 4.2 last night."},
                        {"episode": "e2", "day": "2026-05-02", "title": "t",
                         "text": "user: The hosting bill came to 40 euros this month."}])
    names = b.pages["alpha-project"].names

    def item(question):
        return hq.to_item(sample, {"question": question, "abstain": True, "why": "never said", "skip": False},
                          names)

    for question in ("Which version of the sync workers does alpha-project run?",
                     "¿Qué versión de los sync workers usé?",
                     "How much was the hosting bill for alpha-project?",
                     "When did I upgrade the sync workers?"):
        got, why = item(question)
        assert got is None and why.startswith("abstention answerable from a shown snippet"), question
    # Nothing shown states it: kept.
    for question in ("Who recommended postgres-example for alpha-project?",
                     "How much did the alpha-project domain name cost?"):
        got, why = item(question)
        assert got is not None and got["abstain"] is True, (question, why)
    # The drafter is told every snippet counts.
    prompt = hq.draft_prompt(next(s for s in hq.SAMPLERS["abstention"](b)), b)
    assert "EVERY claim and snippet shown counts" in prompt and "Every claim and every snippet" in hq.DRAFT_SYSTEM
