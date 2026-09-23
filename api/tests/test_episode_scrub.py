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
