"""Hermetic tests for the G99d saved-at normalizer (`api/services/saved_at.py`).

One format per parser feeding `RawItem.added`: Netscape bookmark `add_date`
(Unix epoch seconds, as a string), Chrome `date_added` (WebKit microseconds
since 1601-01-01), Google Takeout `time` (ISO-8601), TikTok's export `Date`
(`"YYYY-MM-DD HH:MM:SS"`), and LinkedIn's free-form saved-date column.

The contract under test: a value that parses cleanly returns an ISO
`YYYY-MM-DD` date; anything that can't be parsed confidently — junk, an
out-of-range timestamp, wrong types — returns `None` rather than a guess.
"""

from __future__ import annotations

from datetime import datetime, timezone

from api.services import saved_at


# --- Netscape bookmark `add_date` (Unix epoch seconds, as a string) --------


def test_netscape_epoch_parses_a_known_timestamp():
    # 2023-06-15 12:00:00 UTC.
    assert saved_at.from_netscape_epoch("1686830400") == "2023-06-15"


def test_netscape_epoch_accepts_an_int_too():
    assert saved_at.from_netscape_epoch(1686830400) == "2023-06-15"


def test_netscape_epoch_none_or_empty_is_none():
    assert saved_at.from_netscape_epoch(None) is None
    assert saved_at.from_netscape_epoch("") is None


def test_netscape_epoch_junk_is_none():
    assert saved_at.from_netscape_epoch("not-a-number") is None
    assert saved_at.from_netscape_epoch("12.5.6") is None


def test_netscape_epoch_out_of_sane_range_is_none():
    # A wildly out-of-range epoch (year ~5138) reads as a scale/unit error,
    # not a real bookmark from the far future.
    assert saved_at.from_netscape_epoch("99999999999") is None
    # Negative (pre-1970) is also outside the sane window.
    assert saved_at.from_netscape_epoch("-1000") is None


# --- Chrome `date_added` (WebKit microseconds since 1601-01-01) -----------


def test_webkit_micros_parses_a_known_timestamp():
    # Same instant as the Netscape case above, expressed as WebKit micros.
    assert saved_at.from_webkit_micros("13331304000000000") == "2023-06-15"


def test_webkit_micros_accepts_an_int_too():
    assert saved_at.from_webkit_micros(13331304000000000) == "2023-06-15"


def test_webkit_micros_none_or_empty_is_none():
    assert saved_at.from_webkit_micros(None) is None
    assert saved_at.from_webkit_micros("") is None


def test_webkit_micros_junk_is_none():
    assert saved_at.from_webkit_micros("not-a-number") is None


def test_webkit_micros_out_of_sane_range_is_none():
    # 0 is the WebKit epoch itself (1601-01-01) — nowhere near sane.
    assert saved_at.from_webkit_micros("0") is None


# --- Google Takeout `time` (ISO-8601) --------------------------------------


def test_iso8601_parses_a_trailing_z():
    assert saved_at.from_iso8601("2023-06-15T12:34:56.000Z") == "2023-06-15"


def test_iso8601_parses_an_explicit_offset():
    assert saved_at.from_iso8601("2023-06-15T12:34:56+00:00") == "2023-06-15"


def test_iso8601_parses_a_bare_date():
    assert saved_at.from_iso8601("2023-06-15") == "2023-06-15"


def test_iso8601_non_string_or_empty_is_none():
    assert saved_at.from_iso8601(None) is None
    assert saved_at.from_iso8601("") is None
    assert saved_at.from_iso8601(1686830400) is None


def test_iso8601_junk_is_none():
    assert saved_at.from_iso8601("not a date") is None
    assert saved_at.from_iso8601("2023-13-99T00:00:00Z") is None


def test_iso8601_future_date_is_none():
    assert saved_at.from_iso8601("2999-01-01T00:00:00Z") is None


# --- TikTok export `Date` (`"YYYY-MM-DD HH:MM:SS"`) ------------------------


def test_tiktok_date_parses_the_datetime_shape():
    assert saved_at.from_tiktok("2023-06-15 12:34:56") == "2023-06-15"


def test_tiktok_date_parses_a_bare_date():
    assert saved_at.from_tiktok("2023-06-15") == "2023-06-15"


def test_tiktok_date_non_string_or_empty_is_none():
    assert saved_at.from_tiktok(None) is None
    assert saved_at.from_tiktok("") is None


def test_tiktok_date_junk_is_none():
    assert saved_at.from_tiktok("15/06/2023") is None
    assert saved_at.from_tiktok("not a date") is None


# --- LinkedIn's free-form saved-date column ---------------------------------


def test_freeform_parses_iso8601():
    assert saved_at.from_freeform("2023-06-15T12:34:56.000Z") == "2023-06-15"


def test_freeform_parses_the_tiktok_style_datetime():
    assert saved_at.from_freeform("2023-06-15 12:34:56") == "2023-06-15"


def test_freeform_parses_a_bare_date():
    assert saved_at.from_freeform("2023-06-15") == "2023-06-15"


def test_freeform_parses_us_style_dates():
    assert saved_at.from_freeform("06/15/2023") == "2023-06-15"
    assert saved_at.from_freeform("06/15/23") == "2023-06-15"
    assert saved_at.from_freeform("06/15/2023, 12:34 PM") == "2023-06-15"


def test_freeform_non_string_or_empty_is_none():
    assert saved_at.from_freeform(None) is None
    assert saved_at.from_freeform("") is None
    assert saved_at.from_freeform(1686830400) is None


def test_freeform_junk_is_none():
    assert saved_at.from_freeform("whenever I got around to it") is None
    assert saved_at.from_freeform("15th of June") is None


# --- sort_instant (review finding: same-day string-mixing) -----------------


def test_sort_instant_bare_date_anchors_to_midnight_utc():
    assert saved_at.sort_instant("2026-03-14") == datetime(
        2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc
    )


def test_sort_instant_full_timestamp_parses_exactly():
    assert saved_at.sort_instant("2026-03-14T09:22:00Z") == datetime(
        2026, 3, 14, 9, 22, 0, tzinfo=timezone.utc
    )
    # Microsecond precision (what the ingest-time saved_at actually emits).
    assert saved_at.sort_instant("2026-03-14T09:22:00.123456Z") == datetime(
        2026, 3, 14, 9, 22, 0, 123456, tzinfo=timezone.utc
    )


def test_sort_instant_bare_date_and_same_day_full_timestamp_are_deterministic():
    """The review finding: raw-string comparison mixed a bare date against a
    full timestamp and tie-broke by string length. A bare content_saved_at
    date on the SAME calendar day as a full-timestamp saved_at must now
    compare as real instants — the bare date (anchored to 00:00:00 UTC, the
    START of that day) sorts strictly before the same-day full timestamp,
    deterministically and for a documented reason, not by accident.
    """
    dated = saved_at.sort_instant("2026-03-14")
    same_day_timestamp = saved_at.sort_instant("2026-03-14T09:22:00Z")
    assert dated < same_day_timestamp


def test_sort_instant_none_or_empty_sorts_as_oldest():
    epoch_min = datetime.min.replace(tzinfo=timezone.utc)
    assert saved_at.sort_instant(None) == epoch_min
    assert saved_at.sort_instant("") == epoch_min
    assert saved_at.sort_instant("   ") == epoch_min


def test_sort_instant_unparseable_sorts_as_oldest_never_raises():
    assert saved_at.sort_instant("not a date") == datetime.min.replace(tzinfo=timezone.utc)


# --- validate (the write-boundary seam guard, Devin round 1 PR #26) --------


def test_validate_accepts_a_genuine_bare_date():
    assert saved_at.validate("2026-03-14") == "2026-03-14"


def test_validate_rejects_a_full_timestamp():
    """The exact shape of bug Pinterest's un-normalized `created_at` leaked
    into RawItem.added before this fix — a value that LOOKS date-shaped but
    carries a time-of-day must not pass through to a writer."""
    assert saved_at.validate("2026-03-14T09:22:00Z") is None
    assert saved_at.validate("2026-03-14T09:22:00") is None


def test_validate_rejects_other_raw_source_shapes():
    """The other four raw shapes a producer might forget to normalize."""
    assert saved_at.validate("1686830400") is None  # Netscape epoch seconds
    assert saved_at.validate("13331304000000000") is None  # WebKit micros
    assert saved_at.validate("2026-03-14 09:22:00") is None  # TikTok-style


def test_validate_none_empty_or_non_string_is_none():
    assert saved_at.validate(None) is None
    assert saved_at.validate("") is None
    assert saved_at.validate("not a date") is None
