"""R-N3 / R3 P3 — one scrub for every episode writer (R-LS5, R-LS6)."""
from __future__ import annotations

import pytest

from api.services import episode_scrub, telemetry
from api.services import transcript_extract as tx


@pytest.mark.parametrize("text, digits", [
    ("Your verification code is 482913", "482913"),
    ("PIN: 1234", "1234"),
    ("Passcode: 998877", "998877"),
    ("482913 is your login code", "482913"),
    ("otp=55501234", "55501234"),
])
def test_a_one_time_code_loses_its_digits_and_keeps_its_sentence(text, digits):
    out, n = episode_scrub.scrub(text)
    assert digits not in out and episode_scrub.REDACTED in out and n == 1
    assert out.split(episode_scrub.REDACTED)[0] == text.split(digits)[0]


@pytest.mark.parametrize("text", [
    "In 2019 I wrote code for alpha-project",
    "error code 404",
    "Meeting ID: 845 1234 5678",
    "The PIN pad has 12 keys",
])
def test_ordinary_numbers_survive(text):
    assert episode_scrub.scrub(text) == (text, 0)


def test_the_transcript_extractor_uses_the_same_rules():
    secret = "sk-" + "A" * 24
    text = f"key {secret} and code: 424242"
    assert tx.scrub_secrets(text) == episode_scrub.scrub(text)
    assert tx.REDACTED == episode_scrub.REDACTED


def test_scrub_body_records_a_count_and_a_writer_never_the_text(monkeypatch):
    seen = []
    monkeypatch.setattr(telemetry, "record", seen.append)
    out = episode_scrub.scrub_body("bearer " + "x" * 20, writer="calendar", bank="alpha")
    assert "x" * 20 not in out
    (event,) = seen
    assert event.kind == "capture" and event.invocations == 0 and event.bank == "alpha"
    assert event.refs == {"writer": "calendar", "status": "scrubbed", "scrubbed": 1}
    seen.clear()
    episode_scrub.scrub_body("nothing to hide", writer="calendar")
    assert seen == []


# --- Phone numbers in a chat source's words (2026-10-28, #502 review B2) --------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("call me +1 555 010 1234 ok", "call me [redacted] ok"),
    ("+34 600 000 000", "[redacted]"),
    ("@15550001234 can you bring the slides?", "@someone can you bring the slides?"),
    ("(555) 010-1234", "[redacted]"),
    ("call (020) 7946 0958 today", "call [redacted] today"),
    ("555.010.1234", "[redacted]"),
    ("tel:+15550001234", "tel:[redacted]"),
    ("wa.me/15550001234", "[redacted]"),
])
def test_a_phone_number_in_a_chat_is_redacted(text, expected):
    assert episode_scrub.scrub_phones(text)[0] == expected


@pytest.mark.parametrize("text", [
    "in 2026 it cost $1,299.00", "meet 2026-10-28 at 10:30", "order 1788000000 shipped", "ip 192.168.1.100",
    "version 1.45.0", "12 345 678", "room 4 at 5", "price 1 299 000", "score 3-2 then 4-1",
    "ISBN 978-0-13-468599-1", "+5 points", "@alice-example said hi",
    # The #502 re-check's examples (2026-10-29): each lost real words to a grouped-number rule, now gone.
    "2026-10-28 10:30", "2024 2025 2026", "years 1999-2003-2010", "€1 299 000 000", "SKU 123-456-789",
    "rooms 101 102 103", "code 1234 5678 9012",
    # Unbracketed national layouts are left too, by choice: false negatives over destroyed words.
    "06 12 34 56 78", "555 010 1234",
])
def test_ordinary_numbers_are_left_alone(text):
    assert episode_scrub.scrub_phones(text) == (text, 0)


def test_only_chat_writers_scrub_phones():
    line = "ring +1 555 010 1234"
    for writer in episode_scrub.PHONE_WRITERS:
        assert episode_scrub.scrub_for(line, writer) == ("ring [redacted]", 1)
    assert episode_scrub.scrub_for(line, "import") == (line, 0)
    assert {"imessage", "whatsapp"} <= episode_scrub.PHONE_WRITERS


SECRET_EXTRA = "ghp_" + "Q1w2E3r4T5y6U7i8O9p0A1s2D3"


def test_every_string_a_writer_passes_beside_the_body_is_scrubbed_by_the_stager(tmp_path):
    """Review of #560: a writer's `extra` and title reached the frontmatter raw; the stager now scrubs them for every
    writer, and a one-token id or hash stays itself."""
    from api.services import markdown_parser
    from api.services.episode_staging import EpisodeDraft, Turn, stage

    episodes = tmp_path / "episodes"
    episodes.mkdir()
    sha = "a" * 64
    draft = EpisodeDraft(title=f"About {SECRET_EXTRA}", source_id="example:1", source="import",
                         timestamp="2026-10-21T10:00:00+00:00", turns=[Turn(text="hello", speaker="user")],
                         extra={"memo": {"description": f"use {SECRET_EXTRA} now", "tags": [SECRET_EXTRA]},
                                "hash_id": sha})
    stage([draft], episodes)
    [path] = list(episodes.glob("ep_*.md"))
    assert SECRET_EXTRA not in path.read_text(encoding="utf-8")
    fm = markdown_parser.parse(path).frontmatter
    assert fm["memo"]["description"] == "use [redacted] now" and fm["memo"]["tags"] == ["[redacted]"]
    assert fm["hash_id"] == sha, "a one-token identifier is never mistaken for a secret"
    assert fm["title"] == "About [redacted]"


@pytest.mark.parametrize("title", ["Advent of Code 2024 day 3", "Pin 2025 roadmap", "OTP 2023 notes",
                                   "Page Title 0123456789abcdef0123456789abcdef"])
def test_a_title_keeps_its_year_and_its_id(title):
    """Re-check of #560: titles and extras get the named secret shapes only — never the one-time-code rule (it ate
    years) or the bare hex run (it ate Notion's file ids)."""
    assert episode_scrub.scrub_value(title, key="title") == (title, 0)
    assert episode_scrub.scrub_value({"memo": {"note": title}}) == ({"memo": {"note": title}}, 0)


def test_keys_and_paths_are_never_altered_and_a_url_loses_only_a_named_secret_in_its_query():
    rel = f"Advent of Code 2024/{SECRET_EXTRA}.md"
    value = {"relpath": rel, "message_keys": [SECRET_EXTRA], "source_id": SECRET_EXTRA,
             "url": f"https://example.com/{SECRET_EXTRA}?access_token={SECRET_EXTRA}&a=1"}
    out, _n = episode_scrub.scrub_value(value)
    assert out["relpath"] == rel and out["message_keys"] == [SECRET_EXTRA] and out["source_id"] == SECRET_EXTRA
    assert out["url"].startswith(f"https://example.com/{SECRET_EXTRA}?") and out["url"].endswith("&a=1")
    assert out["url"].count(SECRET_EXTRA) == 1
