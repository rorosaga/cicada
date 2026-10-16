"""Read on time (owner ruling 2026-10-16): a conversation read late counts as if read the day it was said.

A newly connected source's history, or an export imported after a page was known, used to add its source and its week
and move nothing else, so a page decay had lowered stayed faded as if its topic had been silent all along. Now the
mention is placed on its day — revived then, charged the silence since — so when a conversation is read never changes
where a page or claim ends; only when it was said does. Synthetic pages only.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from api.models.schemas import DecayClass
from api.scripts import recompute_read_on_time as script
from api.services import decay_policy, markdown_parser
from api.services import read_on_time_recompute as recompute
from api.services.claims import parse_claims
from test_decay_age_counts import _bank, _batch, _change, _claim, _drain, _f, _fm, _reconcile

PAGE = "alpha-project"
FIRST = "2026-09-01"


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day + "T03:00:00")


def _daily(bank: Path, start: str, end: str) -> list[dict]:
    """A decay pass each day from ``start`` to ``end``, inclusive. Returns every change for the page."""
    out, day = [], _at(start)
    while day <= _at(end):
        out += [c for c in _batch(bank, [], decay=True, now=day) if c["id"] == PAGE]
        day += timedelta(days=1)
    return out


def _known_page(bank: Path, through: str = "2026-10-15") -> dict:
    """A page heard once on 2026-09-01, read that day, and charged by a decay pass every day since: decaying."""
    _batch(bank, [_change(PAGE, "create", FIRST, confidence=0.6)], decay=True, now=_at(FIRST))
    _daily(bank, "2026-09-02", through)
    fm = _fm(bank, PAGE)
    assert fm["status"] == "decaying" and str(fm["decayed_through"]) == through
    return fm


def _same(a: dict, b: dict) -> None:
    assert math.isclose(a["confidence"], b["confidence"], abs_tol=1e-9), (a["confidence"], b["confidence"])
    assert a["status"] == b["status"]
    assert str(a["decayed_through"]) == str(b["decayed_through"])
    assert bool(a.get("faded_by_age")) == bool(b.get("faded_by_age"))
    assert decay_policy.READ_LATE_KEY not in a and decay_policy.READ_LATE_KEY not in b


# --- the brief's example -------------------------------------------------------


def test_a_recent_mention_read_late_revives_the_page_as_if_read_when_said(tmp_path):
    late, on_time = _bank(tmp_path / "late"), _bank(tmp_path / "on-time")
    _known_page(late)
    # Cicada reads a newly connected chat on 10-16 that mentioned the page on 10-13 — before its watermark (10-15).
    _drain(late, [[_change(PAGE, "update", "2026-10-13")], []], now=_at("2026-10-16"))
    # Read on time: the same chat read on 10-13, then a pass each day.
    _known_page(on_time, through="2026-10-12")
    _batch(on_time, [_change(PAGE, "update", "2026-10-13")], decay=True, now=_at("2026-10-13"))
    _daily(on_time, "2026-10-14", "2026-10-16")

    fm = _fm(late, PAGE)
    # Revived on 10-13 and faded for the three days since, at the pace of a page heard in two weeks.
    expected = 0.6 - 0.05 * _f(2) * 3 / 7
    assert math.isclose(fm["confidence"], expected, abs_tol=1e-9) and fm["status"] == "active"
    assert str(fm["last_referenced"]) == "2026-10-13" and not fm.get("faded_by_age")
    _same(fm, _fm(on_time, PAGE))


def test_a_mention_read_late_mid_drain_is_placed_by_the_decay_pass(tmp_path):
    bank = _bank(tmp_path)
    _known_page(bank)
    # Read in the first batch; the last batch, which charges decay, does not reference the page.
    _batch(bank, [_change(PAGE, "update", "2026-10-13")], decay=False, now=_at("2026-10-16"))
    assert _fm(bank, PAGE)[decay_policy.READ_LATE_KEY] == "2026-10-13"   # nothing charged mid-drain
    assert _fm(bank, PAGE)["status"] == "decaying"
    _batch(bank, [], decay=True, now=_at("2026-10-16"))
    fm = _fm(bank, PAGE)
    assert math.isclose(fm["confidence"], 0.6 - 0.05 * _f(2) * 3 / 7, abs_tol=1e-9) and fm["status"] == "active"
    assert decay_policy.READ_LATE_KEY not in fm


def test_a_page_lifted_back_above_the_line_is_asked_when_live_silence_carries_it_across(tmp_path):
    bank = _bank(tmp_path)
    _known_page(bank)
    _drain(bank, [[_change(PAGE, "update", "2026-10-13")], []], now=_at("2026-10-16"))
    actions = [c["action"] for c in _daily(bank, "2026-10-17", "2026-12-31")]
    assert "decay_nudge" in actions


# --- old stays old -------------------------------------------------------------


def test_a_2024_mention_read_today_revives_nothing(tmp_path):
    bank = _bank(tmp_path)
    before = _known_page(bank)
    _drain(bank, [[_change(PAGE, "update", "2024-05-14")], []], now=_at("2026-10-16"))
    fm = _fm(bank, PAGE)
    # Nothing lifted: only the one live day the last pass charges every silent page (at its two-week pace now).
    assert math.isclose(fm["confidence"], before["confidence"] - 0.05 * _f(2) / 7, abs_tol=1e-9)
    assert fm["status"] == "decaying" and str(fm["last_referenced"]) == FIRST
    assert "ep_2024-05-14_001" in fm["source_episodes"]
    assert decay_policy.READ_LATE_KEY not in fm and not fm.get("faded_by_age")


def test_a_late_mention_its_age_carries_below_the_line_is_faded_and_never_asked(tmp_path):
    bank = _bank(tmp_path)
    before = _known_page(bank)
    # Said three days after the first mention (the same week), read six weeks later: lifted, but under 0.4.
    _drain(bank, [[_change(PAGE, "update", "2026-09-04")], []], now=_at("2026-10-16"))
    fm = _fm(bank, PAGE)
    expected = 0.6 - 0.05 * 42 / 7
    assert before["confidence"] < expected < 0.4
    assert math.isclose(fm["confidence"], expected, abs_tol=1e-9) and fm["status"] == "decaying"
    assert fm["faded_by_age"] == "2026-10-16"
    actions = [c["action"] for c in _daily(bank, "2026-10-17", "2026-12-31")]
    assert "decay_nudge" not in actions and _fm(bank, PAGE)["status"] == "archived"


def test_an_archived_page_a_recent_late_mention_revives_comes_back(tmp_path):
    bank = _bank(tmp_path)
    _batch(bank, [_change(PAGE, "create", "2024-03-05")], decay=True, now=_at("2026-10-09"))
    assert _fm(bank, PAGE)["status"] == "archived"
    # A chat said on 10-08 — the day before Cicada read the page and archived it by its age — read on 10-16.
    _drain(bank, [[_change(PAGE, "update", "2026-10-08")], []], now=_at("2026-10-16"))
    fm = _fm(bank, PAGE)
    # Proven silence floors the repeat at 0.39 only before the day Cicada read the page (10-09); 10-08 -> 10-09 is
    # proven, 10-09 -> 10-16 live, charged in full on time.
    expected = 0.6 - 0.05 * _f(2) * 8 / 7
    assert math.isclose(fm["confidence"], expected, abs_tol=1e-9) and fm["status"] == "active"
    assert str(fm["decayed_through"]) == "2026-10-16" and not fm.get("faded_by_age")


# --- what the ruling leaves alone --------------------------------------------


def test_evergreen_and_owner_pages_and_memory_entries_are_untouched(tmp_path):
    bank = _bank(tmp_path)
    for page_id, extra in (("owner-example", {"owner": True}), ("saved-article", {})):
        markdown_parser.write(bank / "entities" / f"{page_id}.md", {
            "name": page_id, "type": "person" if extra else "concept", "status": "active", "confidence": 0.5,
            "created": FIRST, "last_referenced": FIRST, "decayed_through": "2026-10-15", "learned_on": FIRST,
            **decay_policy.frontmatter_fields(DecayClass.evergreen), "source_episodes": [f"ep_{FIRST}_001"], **extra,
        }, "## Summary\n\nA synthetic thing.\n")
    _known_page(bank)
    markdown_parser.write(bank / "episodes" / "ep_2026-10-13_002.md",
                          {"id": "ep_2026-10-13_002", "source": "claude_memory", "processed": True}, "Facts.\n")
    memory = _change(PAGE, "update", "2026-10-13", untimed=True)
    memory["source_episodes"], memory["source_episode"] = ["ep_2026-10-13_002"], "ep_2026-10-13_002"
    before = _fm(bank, PAGE)
    _drain(bank, [[_change("owner-example", "update", "2026-10-13"), _change("saved-article", "update", "2026-10-13"),
                   memory], []], now=_at("2026-10-16"))
    for page_id in ("owner-example", "saved-article"):
        fm = _fm(bank, page_id)
        assert fm["confidence"] == 0.5 and decay_policy.READ_LATE_KEY not in fm
    # A memory export entry is no mention: nothing is lifted.
    fm = _fm(bank, PAGE)
    assert fm["confidence"] <= before["confidence"] and fm["status"] == "decaying"
    assert decay_policy.READ_LATE_KEY not in fm


def test_an_archived_evergreen_page_mentioned_again_is_revived_as_before(tmp_path):
    # G66 §1.6, unchanged by read on time: a hand-archived evergreen page a new conversation mentions comes back at
    # 0.6; an active evergreen page keeps its confidence.
    bank = _bank(tmp_path)
    for page_id, status in (("saved-archived", "archived"), ("saved-active", "active")):
        markdown_parser.write(bank / "entities" / f"{page_id}.md", {
            "name": page_id, "type": "concept", "status": status, "confidence": 0.1 if status == "archived" else 0.5,
            "created": FIRST, "last_referenced": FIRST, "decayed_through": FIRST, "learned_on": FIRST,
            **decay_policy.frontmatter_fields(DecayClass.evergreen), "source_episodes": [f"ep_{FIRST}_001"],
        }, "## Summary\n\nA synthetic thing.\n")
    _batch(bank, [_change("saved-archived", "update", "2026-10-16"), _change("saved-active", "update", "2026-10-16")],
           decay=True, now=_at("2026-10-16"))
    revived = _fm(bank, "saved-archived")
    assert revived["status"] == "active" and revived["confidence"] == 0.6
    assert _fm(bank, "saved-active")["confidence"] == 0.5


# --- order independence --------------------------------------------------------


@pytest.mark.parametrize("layout", ["one_batch", "older_first", "newer_first", "both_then_empty"])
def test_late_conversations_land_the_same_whatever_the_batches_and_as_if_read_on_time(tmp_path, layout):
    bank, on_time = _bank(tmp_path / "late"), _bank(tmp_path / "on-time")
    _known_page(bank)
    older, newer = _change(PAGE, "update", "2026-10-05"), _change(PAGE, "update", "2026-10-13")
    batches = {
        "one_batch": [[older, newer]],
        "older_first": [[older], [newer]],
        "newer_first": [[newer], [older]],
        "both_then_empty": [[older], [newer], []],
    }[layout]
    _drain(bank, batches, now=_at("2026-10-16"))
    _known_page(on_time, through="2026-10-04")
    _batch(on_time, [_change(PAGE, "update", "2026-10-05")], decay=True, now=_at("2026-10-05"))
    _daily(on_time, "2026-10-06", "2026-10-12")
    _batch(on_time, [_change(PAGE, "update", "2026-10-13")], decay=True, now=_at("2026-10-13"))
    _daily(on_time, "2026-10-14", "2026-10-16")
    fm = _fm(bank, PAGE)
    assert math.isclose(fm["confidence"], 0.6 - 0.05 * _f(3) * 3 / 7, abs_tol=1e-9)
    _same(fm, _fm(on_time, PAGE))


def test_late_conversations_split_across_runs_land_the_same_in_either_order(tmp_path):
    a, b = _bank(tmp_path / "a"), _bank(tmp_path / "b")
    _known_page(a)
    _known_page(b)
    # Two chats from one week, read on two days in opposite orders.
    _batch(a, [_change(PAGE, "update", "2026-10-12")], decay=True, now=_at("2026-10-16"))
    _batch(a, [_change(PAGE, "update", "2026-10-14")], decay=True, now=_at("2026-10-17"))
    _batch(b, [_change(PAGE, "update", "2026-10-14")], decay=True, now=_at("2026-10-16"))
    _batch(b, [_change(PAGE, "update", "2026-10-12")], decay=True, now=_at("2026-10-17"))
    _daily(a, "2026-10-18", "2026-10-18")
    _daily(b, "2026-10-18", "2026-10-18")
    _same(_fm(a, PAGE), _fm(b, PAGE))
    assert math.isclose(_fm(a, PAGE)["confidence"], 0.6 - 0.05 * _f(2) * 4 / 7, abs_tol=1e-9)


# --- claims follow the same rule ----------------------------------------------


def _known_claim(through: str = "2026-10-15", subject: str = "topic"):
    state, _, _ = _reconcile({}, [_claim("clm_a", FIRST, subject=subject, conf=0.6)], decay=True, today=FIRST)
    day = date.fromisoformat("2026-09-02")
    while day <= date.fromisoformat(through):
        state, _, _ = _reconcile(state, [], decay=True, today=day.isoformat())
        day += timedelta(days=1)
    return state


def _claim_days(state, start: str, end: str):
    day = date.fromisoformat(start)
    while day <= date.fromisoformat(end):
        state, _, _ = _reconcile(state, [], decay=True, today=day.isoformat())
        day += timedelta(days=1)
    return state


def test_a_claim_restated_late_lands_where_reading_it_on_time_would_have_like_its_page(tmp_path):
    late = _known_claim()
    late, _, _ = _reconcile(late, [_claim("clm_b", "2026-10-13", conf=0.6)], decay=True, today="2026-10-16")
    on_time = _known_claim(through="2026-10-12")
    on_time, _, _ = _reconcile(on_time, [_claim("clm_b", "2026-10-13", conf=0.6)], decay=True, today="2026-10-13")
    on_time = _claim_days(on_time, "2026-10-14", "2026-10-16")
    (claim,), (twin,) = late["topic"], on_time["topic"]
    claim_expected = 0.6 - 0.02 * _f(2) * 3 / 7
    assert math.isclose(claim.confidence, claim_expected, abs_tol=1e-9)
    assert math.isclose(twin.confidence, claim.confidence, abs_tol=1e-9)
    assert claim.decayed_through == twin.decayed_through == "2026-10-16" and not claim.read_late
    # Its page, read the same late day, is placed on the same day by the same rule.
    bank = _bank(tmp_path)
    _known_page(bank)
    _drain(bank, [[_change(PAGE, "update", "2026-10-13")], []], now=_at("2026-10-16"))
    page = _fm(bank, PAGE)
    assert math.isclose(1 - (0.6 - page["confidence"]) / (0.05 * _f(2) * 3 / 7),
                        1 - (0.6 - claim.confidence) / (0.02 * _f(2) * 3 / 7), abs_tol=1e-9)


def test_a_capture_read_late_after_the_watermark_charges_page_and_claim_alike(tmp_path):
    # Charged through 10-10 (no pass since: a paused schedule); a chat said 10-13 read on 10-16.
    state = _known_claim(through="2026-10-10")
    state, _, _ = _reconcile(state, [_claim("clm_b", "2026-10-13", conf=0.6)], decay=True, today="2026-10-16")
    (claim,) = state["topic"]
    bank = _bank(tmp_path)
    _known_page(bank, through="2026-10-10")
    _drain(bank, [[_change(PAGE, "update", "2026-10-13")], []], now=_at("2026-10-16"))
    page = _fm(bank, PAGE)
    # Both revived on 10-13 and charged the three days since — the claim no longer restarts on the day it is read.
    assert math.isclose(claim.confidence, 0.6 - 0.02 * _f(2) * 3 / 7, abs_tol=1e-9)
    assert math.isclose(page["confidence"], 0.6 - 0.05 * _f(2) * 3 / 7, abs_tol=1e-9)


def test_a_2024_restatement_read_today_lifts_no_claim():
    state = _known_claim()
    before = state["topic"][0].confidence
    state, _, _ = _reconcile(state, [_claim("clm_b", "2024-05-14", conf=0.9)], decay=True, today="2026-10-16")
    assert state["topic"][0].confidence <= before + 1e-12 and not state["topic"][0].read_late


@pytest.mark.parametrize("order", ["older_first", "newer_first", "same_batch"])
def test_late_restatements_land_a_claim_the_same_whatever_the_batches(order):
    older, newer = _claim("clm_b", "2026-10-05", conf=0.6), _claim("clm_c", "2026-10-13", conf=0.6)
    state = _known_claim()
    if order == "same_batch":
        state, _, _ = _reconcile(state, [older, newer], decay=True, today="2026-10-16")
    else:
        first, second = (older, newer) if order == "older_first" else (newer, older)
        state, _, _ = _reconcile(state, [first], decay=False, today="2026-10-16")
        assert state["topic"][0].read_late   # nothing charged mid-drain
        state, _, _ = _reconcile(state, [second], decay=True, today="2026-10-16")
    (claim,) = state["topic"]
    assert math.isclose(claim.confidence, 0.6 - 0.02 * _f(3) * 3 / 7, abs_tol=1e-9) and not claim.read_late


def test_a_claims_pending_restatement_survives_the_fence():
    state = _known_claim()
    state, _, _ = _reconcile(state, [_claim("clm_b", "2026-10-13", conf=0.6)], decay=False, today="2026-10-16")
    (claim,) = state["topic"]
    from api.services.claims import Claim

    again = Claim.from_dict(json.loads(json.dumps(claim.to_dict())))
    assert again.read_late == [["2026-10-13", 0.6]]
    assert "read_late" not in _claim("clm_x", FIRST).to_dict()


# --- the one-shot recompute for existing banks ---------------------------------


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True,
                          env={**os.environ}).stdout


CLAIM_LINES = [
    # Restated late under the old rule: its latest conversation (10-13) after the day it was read (09-01).
    {"id": "clm_late", "text": "late fact", "subject": "old-rule-project", "predicate": "uses", "object": "postgres",
     "confidence": 0.3, "recorded_at": FIRST, "decayed_through": "2026-10-15",
     "source_episodes": [f"ep_{FIRST}_001", "ep_2026-10-13_001"]},
    # Read the day it was said: untouched.
    {"id": "clm_live", "text": "live fact", "subject": "old-rule-project", "predicate": "uses", "object": "sqlite",
     "confidence": 0.3, "recorded_at": FIRST, "decayed_through": "2026-10-15", "source_episodes": [f"ep_{FIRST}_001"]},
]


def _old_page(bank: Path, page_id: str, said: str, *, kind: str = "project", conf: float = 0.29,
              status: str = "decaying", body: str = "## Summary\nA synthetic thing.\n", **extra) -> None:
    markdown_parser.write(bank / "entities" / f"{page_id}.md", {
        "name": page_id, "type": kind, "status": status, "confidence": conf, "created": FIRST,
        "last_referenced": said, "decayed_through": "2026-10-15", "learned_on": FIRST,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for(kind)),
        "source_episodes": sorted({f"ep_{FIRST}_001", f"ep_{said}_001"}), **extra,
    }, body)


@pytest.fixture
def old_bank(tmp_path: Path) -> Path:
    root = _bank(tmp_path / "bank")
    claims_body = ("## Summary\nA synthetic thing.\n\n```claims\n"
                   + "\n".join(json.dumps(line) for line in CLAIM_LINES) + "\n```\n")
    # The brief's example as the old rule left it: a 10-13 mention read on 10-16 moved nothing.
    _old_page(root, "old-rule-project", "2026-10-13", body=claims_body)
    _old_page(root, "old-rule-person", "2026-10-13", kind="person")
    _old_page(root, "faded-mention", "2026-09-04", kind="concept")           # lifted, but below 0.4
    _old_page(root, "read-live", FIRST, kind="concept")                     # newest mention read the day it was said
    _old_page(root, "evergreen-page", "2026-10-13", kind="concept",
              **decay_policy.frontmatter_fields(DecayClass.evergreen))
    _old_page(root, "dismissed", "2026-10-13", status="dropped")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Synthetic")
    _git(root, "config", "user.email", "synthetic@example.com")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def test_the_recompute_dry_run_counts_what_reading_on_time_would_lift(old_bank):
    before = {p.name: p.read_text() for p in (old_bank / "entities").glob("*.md")}
    counts = recompute.survey(old_bank, today=date(2026, 10, 16)).counts()
    assert counts["read_late"] == 3 and counts["lifted"] == 3
    assert counts["to_active"] == 2 and counts["to_decaying"] == 1 and counts["faded_by_age"] == 1
    assert counts["claims_read_late"] == 1 and counts["claims_lifted"] == 1
    assert counts["by_type"]["project"]["lifted"] == 1 and counts["by_type"]["project"]["claims_lifted"] == 1
    assert counts["by_type"]["person"]["to_active"] == 1 and counts["by_type"]["concept"]["to_decaying"] == 1
    assert set(counts["by_type"]) == {"concept", "person", "project"}
    # Read-only, counts only.
    assert {p.name: p.read_text() for p in (old_bank / "entities").glob("*.md")} == before
    assert "old-rule" not in json.dumps(counts)


def test_the_recompute_dry_run_never_touches_git_index(old_bank):
    index = old_bank / ".git" / "index"
    (old_bank / "entities" / "read-live.md").touch()   # a stale stat entry a plain `git status` would refresh
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    recompute.survey(old_bank, today=date(2026, 10, 16))
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before


def test_the_recompute_leaves_a_page_whose_newest_mention_is_no_conversation(old_bank):
    # An agent's progress note (or a decay answer) moved `last_referenced` past every conversation the page credits
    # and left `learned_on`: the same mark as a late read, but no conversation was read late.
    _old_page(old_bank, "progress-noted", "2026-10-13", source_episodes=[f"ep_{FIRST}_001", f"ep_{FIRST}_002"])
    _git(old_bank, "add", "-A")
    _git(old_bank, "commit", "-qm", "progress note")
    counts = recompute.survey(old_bank, today=date(2026, 10, 16)).counts()
    assert counts["read_late"] == 3 and counts["lifted"] == 3
    result = recompute.apply(old_bank, sleep_running=lambda: False, today=date(2026, 10, 16))
    assert _fm(old_bank, "progress-noted")["confidence"] == 0.29
    assert _fm(old_bank, "progress-noted")["status"] == "decaying" and result.written == 3


def test_the_recompute_applies_in_one_cicada_commit_and_a_second_run_is_a_no_op(old_bank, monkeypatch):
    monkeypatch.setattr(script, "backend_running", lambda: False)
    result = recompute.apply(old_bank, sleep_running=lambda: False, today=date(2026, 10, 16))
    assert result.committed and result.written == 3
    fm = _fm(old_bank, "old-rule-project")
    assert math.isclose(fm["confidence"], 0.6 - 0.05 * _f(2) * 3 / 7, abs_tol=1e-9)
    assert fm["status"] == "active" and str(fm["decayed_through"]) == "2026-10-16"
    faded = _fm(old_bank, "faded-mention")
    assert faded["status"] == "decaying" and faded["faded_by_age"] == "2026-10-16"
    assert _fm(old_bank, "read-live")["confidence"] == 0.29
    assert _fm(old_bank, "evergreen-page")["confidence"] == 0.29 and _fm(old_bank, "dismissed")["status"] == "dropped"
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(old_bank / "entities/old-rule-project.md").body)}
    assert math.isclose(claims["clm_late"].confidence, 0.6 - 0.02 * _f(2) * 3 / 7, abs_tol=1e-9)
    assert claims["clm_live"].confidence == 0.3
    assert "Cicada-Author: cicada" in _git(old_bank, "log", "-1", "--format=%b")
    assert "maintenance/read-on-time" in _git(old_bank, "log", "-1", "--format=%B")
    assert _git(old_bank, "status", "--porcelain") == ""
    assert len(_git(old_bank, "log", "--format=%h").split()) == 2
    again = recompute.apply(old_bank, sleep_running=lambda: False, today=date(2026, 10, 16))
    assert again.written == 0 and not again.committed


def test_the_recompute_script_reports_counts_and_refuses_while_sleep_runs(old_bank, monkeypatch, capsys):
    assert script.main(["--bank", str(old_bank)]) == 0
    assert json.loads(capsys.readouterr().out)["read_late"] == 3
    monkeypatch.setattr(script, "backend_running", lambda: True)
    assert script.main(["--bank", str(old_bank), "--apply"]) == 3
    assert "refused" in json.loads(capsys.readouterr().out)
    assert script.main(["--bank", str(old_bank / "nope")]) == 2
