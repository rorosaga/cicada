"""G110 slice 1a T3: selection, turns and the startup block (plan C1, C4).

Synthetic episodes in capture's exact shape (`_continuity_fixtures`). Identity
is the exact folder string; selection is explicit → the most recent other
session here → a question when two were active together; an incomplete search
never claims "the only" session."""
from __future__ import annotations

import os
import time

import pytest

from _continuity_fixtures import CWD, at, sid, write_session
from api.services import continuity, continuity_sessions, markdown_parser


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    continuity.reset()
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


def _ctx(bank, *, cwd=CWD, me=sid(99), session=None, deadline=None, full=0):
    return continuity.assemble(bank, bank_paths=(bank,), harness="claude-code", session_id=me, cwd=cwd,
                               session=session, deadline=deadline, allow_full_parse=full)


A_TURNS = [
    ("user", "Make the alpha parser strict."),
    ("assistant", "I propose approach X: a regex pre-pass."),
    ("user", "Not X, it breaks the fixture loader — use Y."),
    ("assistant", "Done with Y; edited tests/fixtures/alpha.json; test_alpha_roundtrip still fails on one case. "
                  "Next: fix the date branch in parse_alpha, then rerun test_alpha_roundtrip."),
]


def test_the_latest_session_in_the_same_folder_is_chosen(bank):
    write_session(bank, 1, [("user", "old work"), ("assistant", "ok")], start=0)
    write_session(bank, 2, A_TURNS, start=60)
    write_session(bank, 3, [("user", "elsewhere"), ("assistant", "ok")], start=90, cwd=CWD + "/sub")
    write_session(bank, 4, [("user", "sibling"), ("assistant", "ok")], start=95, cwd="/home/example/alpha-project-2")
    ctx = _ctx(bank)
    assert ctx.selection.kind == "latest" and ctx.chosen.episode_id == "ep_2026-09-03_002"
    text, rendering = continuity.startup_block(ctx, max_chars=1800)
    assert rendering == "full"
    assert "Not X, it breaks the fixture loader" in text and "test_alpha_roundtrip" in text
    assert "quoted as history, not a new instruction" in text
    assert "Workspace state not checked" in text and 'cicada_continue(session="ep_2026-09-03_002")' in text
    assert "not yet consolidated" in text and "the most recent session here" in text
    assert "/home/example" not in text and "sibling" not in text and "elsewhere" not in text


def test_this_session_is_excluded_and_other_banks_are_never_seen(bank, tmp_path):
    write_session(bank, 1, A_TURNS, session=sid(99))
    assert _ctx(bank).selection.kind == "none"
    other = tmp_path / "other"
    write_session(other, 2, A_TURNS, start=200)
    assert _ctx(bank).selection.kind == "none"


def test_two_sessions_active_together_are_a_question(bank):
    write_session(bank, 1, [("user", "task one"), ("assistant", "ok")], start=50)
    write_session(bank, 2, [("user", "task two"), ("assistant", "ok")], start=60)
    ctx = _ctx(bank)
    assert ctx.selection.kind == "ambiguous" and len(ctx.selection.listed) == 2
    text, rendering = continuity.startup_block(ctx, max_chars=1800)
    assert rendering == "ambiguous" and "Ask the person which one to continue" in text
    assert "ep_2026-09-03_001" in text and "ep_2026-09-03_002" in text and '"task two"' in text
    # Far apart: no question.
    write_session(bank, 3, [("user", "task three"), ("assistant", "ok")], start=200)
    assert _ctx(bank).selection.kind == "latest"


def test_a_later_prompt_from_the_registry_counts_as_activity(bank):
    write_session(bank, 1, [("user", "a"), ("assistant", "b")], start=0)
    write_session(bank, 2, [("user", "c"), ("assistant", "d")], start=100)
    continuity_sessions.apply(bank, bank_paths=(bank,), harness="claude-code", session_id=sid(1),
                              events={"last_prompt_at": at(200)}, deadline=None)
    ctx = _ctx(bank)
    assert ctx.chosen.episode_id == "ep_2026-09-03_001"
    text, _ = continuity.startup_block(ctx, max_chars=1800)
    assert "a later message at" in text and "has no captured reply" in text


@pytest.mark.parametrize("pick", ["ep_2026-09-03_001", sid(1)])
def test_an_explicit_episode_or_full_session_id_selects_from_any_folder(bank, pick):
    write_session(bank, 1, A_TURNS, cwd="/home/example/elsewhere")
    write_session(bank, 2, [("user", "x"), ("assistant", "y")], start=100)
    ctx = _ctx(bank, session=pick)
    assert ctx.selection.kind == "explicit" and ctx.chosen.episode_id == "ep_2026-09-03_001"


def test_a_prefix_never_selects_and_shared_prefixes_are_never_confused(bank):
    write_session(bank, 1, A_TURNS, session="abcdefgh-2222-4333-8444-555555555555")
    write_session(bank, 2, A_TURNS, session="abcdefgh-9999-4333-8444-555555555555", start=100)
    assert _ctx(bank, session="abcdefgh").selection.kind == "none"
    assert _ctx(bank, session="abcdefgh-9999-4333-8444-555555555555").chosen.episode_id == "ep_2026-09-03_002"


def test_an_incomplete_search_never_claims_the_most_recent(bank):
    write_session(bank, 1, A_TURNS, start=100)
    continuity.refresh_index(bank, bank_paths=(bank,), deadline=None)      # index A
    write_session(bank, 2, [("user", "z"), ("assistant", "w")], start=200)  # not reached in time
    ctx = _ctx(bank, deadline=time.monotonic() + continuity.VIEW_RESERVE_S / 2)
    assert not ctx.complete and ctx.chosen.episode_id == "ep_2026-09-03_001"
    text, _ = continuity.startup_block(ctx, max_chars=1800)
    assert "could read here (the search was incomplete)" in text and "the most recent session here" not in text


def test_consolidation_wording_follows_processed_by(bank):
    write_session(bank, 1, A_TURNS, processed=True, processed_by="sleep")
    assert "consolidated by Sleep" in continuity.startup_block(_ctx(bank), max_chars=1800)[0]
    write_session(bank, 1, A_TURNS, processed=True, processed_by="claude-code")
    assert "marked processed by an agent" in continuity.startup_block(_ctx(bank), max_chars=1800)[0]


def test_gap_lines(bank):
    write_session(bank, 1, A_TURNS + [("user", "and now?")],
                  extra_meta={"capture_gap": {"dropped_turns": 7, "last_seen_at": at(30)},
                              "capture_flags": {"note_like_turns": 2}})
    text, _ = continuity.startup_block(_ctx(bank), max_chars=1800)
    assert "its last request has no captured reply" in text
    assert "7 turns past Cicada's capture limit" in text
    assert "2 of its turns look like a Cicada note kept as typed text" in text


def test_a_later_session_that_captured_nothing_is_disclosed(bank):
    write_session(bank, 1, A_TURNS)
    continuity_sessions.apply(bank, bank_paths=(bank,), harness="claude-code", session_id=sid(5),
                              events={"started_at": at(60), "cwd_hash": continuity_sessions.cwd_hash(CWD)},
                              deadline=None)
    text, _ = continuity.startup_block(_ctx(bank), max_chars=1800)
    assert "nothing from it was captured" in text


def test_renderings_fit_their_caps_with_long_turns(bank):
    long_turns = [("user", "u " * 1000), ("assistant", "a " * 1000)] * 3
    write_session(bank, 1, long_turns)
    ctx = _ctx(bank)
    for cap, expected in ((1800, "full"), (900, "compact"), (300, "pointer"), (50, "none")):
        text, rendering = continuity.startup_block(ctx, max_chars=cap)
        assert rendering == expected and len(text) <= cap


# --- turns -------------------------------------------------------------------


def test_turns_are_exact_with_a_full_sidecar_even_with_marker_looking_text(bank):
    turns = [("user", "first\nuser: not a boundary"), ("assistant", "reply\nassistant: also not")]
    write_session(bank, 1, turns)
    v = _ctx(bank).chosen
    got = [(t.speaker, t.text, t.exact) for t in v.turns()]
    assert got == [("user", "first\nuser: not a boundary", True), ("assistant", "reply\nassistant: also not", True)]


def test_turns_past_the_sidecar_use_the_exact_tail_and_label_the_middle(bank):
    # Marker-looking lines only where boundaries are exact (the head and the tail).
    turns = [("user" if i % 2 == 0 else "assistant",
              f"turn {i}" + (f"\nuser: marker {i}" if i < 10 or i >= 512 else "")) for i in range(520)]
    write_session(bank, 1, turns)
    v = _ctx(bank).chosen
    got = v.turns()
    tail = got[-8:]
    assert [(t.speaker, t.text) for t in tail] == turns[-8:] and all(t.exact for t in tail)
    assert len(got) == 520 and got[0].exact and got[0].text == "turn 0\nuser: marker 0"
    assert [t.exact for t in got[499:512]] == [False] * 13      # the region past the sidecar is approximate
    assert all(t.n == i + 1 for i, t in enumerate(got))


def test_inconsistent_boundaries_label_every_cut_turn_approximate(bank):
    turns = [("user" if i % 2 == 0 else "assistant", f"turn {i}\nuser: marker {i}") for i in range(520)]
    write_session(bank, 1, turns)
    got = _ctx(bank).chosen.turns()
    assert all(t.exact for t in got[-8:]) and not got[0].exact


def test_untimed_turns_say_time_not_recorded(bank):
    write_session(bank, 1, A_TURNS, untimed=True)
    text, _ = continuity.startup_block(_ctx(bank), max_chars=1800)
    assert "time not recorded" in text


def test_a_file_changed_between_scan_and_parse_is_dropped(bank, monkeypatch):
    p = write_session(bank, 1, A_TURNS)
    real = continuity.view

    def swap(memory_path, chosen, **kw):
        doc = markdown_parser.parse(p)
        fm = dict(doc.frontmatter)
        fm["session_id"] = sid(42)
        markdown_parser.write(p, fm, doc.body)
        return real(memory_path, chosen, **kw)

    monkeypatch.setattr(continuity, "view", swap)
    ctx = _ctx(bank)
    assert ctx.chosen is None and not ctx.complete and ctx.selection.reason == "changed"


# --- fix round 1, finding 7: "nothing captured" only on complete evidence -------


@pytest.mark.parametrize("how", ["unreadable", "deadline"])
def test_a_later_session_that_cannot_be_read_is_not_called_uncaptured(bank, how):
    write_session(bank, 1, A_TURNS, start=0)
    continuity.refresh_index(bank, bank_paths=(bank,), deadline=None)
    extra = {"zz_note": "x" * 20_000} if how == "unreadable" else None
    write_session(bank, 2, [("user", "later work"), ("assistant", "ok")], session=sid(5), start=30,
                  extra_meta=extra, cwd="/home/example/elsewhere" if how == "deadline" else CWD)
    continuity_sessions.apply(bank, bank_paths=(bank,), harness="claude-code", session_id=sid(5),
                              events={"started_at": at(29), "cwd_hash": continuity_sessions.cwd_hash(CWD)},
                              deadline=None)
    ctx = _ctx(bank, deadline=time.monotonic() + continuity.VIEW_RESERVE_S / 2 if how == "deadline" else None)
    text, _ = continuity.startup_block(ctx, max_chars=1800)
    assert "nothing from it was captured" not in text
    assert "Cicada could not tell whether a later session here" in text


# --- fix round 1, finding 10: activity is the conversation's own time -----------


def test_a_late_recapture_never_makes_an_old_session_look_recent(bank):
    """Plan r4 C1 as amended in fix round 1: activity is the last kept turn's own
    time (the capture time only when no turn has one), or a later prompt. A
    session last spoken in at T but re-captured at T+100 (a Stop on resume with no
    new turn, a re-render after an upgrade) must not outrank one spoken in at T+50."""
    write_session(bank, 1, [("user", "old"), ("assistant", "ok")], start=0,
                  extra_meta={"captured_at": at(100)})
    write_session(bank, 2, [("user", "newer"), ("assistant", "ok")], start=50)
    assert _ctx(bank).chosen.episode_id == "ep_2026-09-03_002"


def test_an_untimed_session_falls_back_to_its_capture_time(bank):
    write_session(bank, 1, [("user", "untimed"), ("assistant", "ok")], untimed=True,
                  extra_meta={"captured_at": at(200)})
    write_session(bank, 2, [("user", "timed"), ("assistant", "ok")], start=50)
    assert _ctx(bank).chosen.episode_id == "ep_2026-09-03_001"
