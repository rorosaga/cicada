"""G141 R-PJ6 / R-PJB15 — the closed table of time words (`when.resolve`, `split_phrase`)."""
from datetime import date, datetime, timezone

import pytest

from api.services import when

A = when.Anchor(datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc), "turn", when.zone("Europe/Madrid"))


@pytest.mark.parametrize("text,direction,expected", [
    ("today", "past", "2026-09-23"), ("this morning", "past", "2026-09-23"), ("tonight", "past", "2026-09-23"),
    ("yesterday", "past", "2026-09-22"), ("last night", "past", "2026-09-22"), ("tomorrow", "future", "2026-09-24"),
    ("3 days ago", "past", "2026-09-20"), ("three days ago", "past", "2026-09-20"), ("a week ago", "past", "2026-09-16"),
    ("last Tuesday", "past", "2026-09-22"), ("last Wednesday", "past", "2026-09-16"),
    ("on Monday", "past", "2026-09-21"), ("on Wednesday", "past", "2026-09-23"), ("on Friday", "future", "2026-09-25"),
    ("on Wednesday", "future", "2026-09-30"), ("last week", "past", "2026-09-16"), ("next week", "future", "2026-09-30"),
    ("2026-09-01", "past", "2026-09-01"), ("Oct 5", "future", "2026-10-05"), ("5 October", "future", "2026-10-05"),
    ("Sep 30", "past", "2025-09-30"), ("by Oct 5, 2026", "future", "2026-10-05"),
])
def test_the_closed_table(text, direction, expected):
    day, basis = when.resolve(text, A, direction=direction)
    assert (day.isoformat(), basis) == (expected, "stated")


def test_anything_else_is_the_anchor_day_with_the_anchor_basis():
    assert when.resolve("soonish", A) == (date(2026, 9, 23), "turn")
    assert when.resolve(None, A) == (date(2026, 9, 23), "turn")


def test_the_window_refuses_a_future_happening_and_a_far_target():
    assert when.resolve("tomorrow", A, direction="past") == (None, "stated")
    assert when.resolve("2029-01-01", A, direction="future") == (None, "stated")
    assert when.resolve("2024-01-01", A, direction="past") == (None, "stated")


def test_a_utc_ts_near_midnight_is_the_local_date_and_dst_holds():
    late = when.Anchor(datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc), "turn", when.zone("Europe/Madrid"))
    assert when.resolve("today", late)[0] == date(2026, 9, 23)          # 01:30 in Madrid
    dst = when.Anchor(datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc), "turn", when.zone("Europe/Madrid"))
    assert when.resolve("yesterday", dst)[0] == date(2026, 10, 24)


def test_split_phrase_cuts_one_phrase_anywhere_and_refuses_two():
    assert when.split_phrase("Yesterday Hana sent me the guide") == ("Yesterday", "Hana sent me the guide")
    assert when.split_phrase("got the guide from Hana yesterday.") == ("yesterday", "got the guide from Hana.")
    assert when.split_phrase("got the guide yesterday and started") == ("yesterday", "got the guide and started")
    assert when.split_phrase("fixed the arm") == (None, "fixed the arm")
    with pytest.raises(when.TwoDates):
        when.split_phrase("yesterday I planned it for tomorrow")


def test_has_relative():
    assert when.has_relative("Bob is connecting today") and not when.has_relative("Bob is connecting")
