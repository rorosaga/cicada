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


# ---- the name-boundary class (2026-11-06): `\b` does not fall after an underscore ---------------------------------------
# Fake values, built from pieces so no secret scanner reads this file as a leak.
AWS_SECRET = "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCY" + "Q9z8Y7x6W5"
DB_PW = "Tr0ub4dor" + "&3xyzQ"
STRIPE_LIVE = "sk_" + "live_" + "Zq8LmXp2Rt7VnKd4Hw9Bc3Js"
URL_PW = "s3cr3t" + "Pw9x"


@pytest.mark.parametrize("line, value", [
    (f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}", AWS_SECRET),
    (f'DB_PASSWORD="{DB_PW}"', DB_PW),
    (f"export STRIPE_SECRET={DB_PW}", DB_PW),
    (f"OPENAI_API_KEY={DB_PW}", DB_PW),
    (f'{{"password": "{DB_PW}"}}', DB_PW),
    (f"docker run -e REDIS_PASSWORD={DB_PW} img", DB_PW),
    (f"postgres://admin:{URL_PW}@db.internal:5432/app", URL_PW),
    (f"redis://:{URL_PW}@cache:6379/0", URL_PW),
    (f"clone https://deploy:{URL_PW}@git.example.com/x.git", URL_PW),
    (f"key {STRIPE_LIVE} in prod", STRIPE_LIVE),
    (f"STRIPE_KEY_{STRIPE_LIVE}", STRIPE_LIVE),
])
def test_a_secret_behind_an_underscored_name_or_in_a_url_is_taken(line, value):
    out, n = episode_scrub.scrub(line)
    assert value not in out and "[redacted]" in out and n >= 1
    assert episode_scrub.scrub(out) == (out, 0), "scrubbing twice changes nothing"
    assert episode_scrub.scrub_value(line)[0] == out, "a title or extra gets the same named shapes"


def test_the_name_and_the_host_survive_so_the_line_still_says_what_was_set():
    assert episode_scrub.scrub(f"DB_PASSWORD={DB_PW}")[0] == "DB_PASSWORD=[redacted]"
    assert episode_scrub.scrub(f'"db_password": "{DB_PW}"')[0] == '"db_password": "[redacted]"'
    assert episode_scrub.scrub(f"postgres://admin:{URL_PW}@db:5432/app")[0] == "postgres://admin:[redacted]@db:5432/app"


@pytest.mark.parametrize("text", [
    "DB_PASSWORD=${DB_PASSWORD}", "DB_PASSWORD=$DB_PASSWORD_VALUE", "DB_PASSWORD=<your-password>",
    "DB_PASSWORD=your_password_here", "DB_PASSWORD=changeme123", "AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxx",
    "API_KEY=****************", 'DB_PASSWORD="[redacted]"', "OPENAI_API_KEY=process.env.OPENAI_API_KEY",
    'OPENAI_API_KEY=os.environ["OPENAI_API_KEY"]', "API_KEY=getpass()", 'password: "ask the admin please"',
    "max_tokens=4096", "TOKEN_URL=https://example.com/oauth/token", "SECRET_NAME=prod_database_credentials",
    "postgres://postgres:postgres@localhost:5432/dev", "postgres://user:password@localhost/db",
    "postgres://u:<password>@host/db", "postgres://u:${DB_PASSWORD}@host/db", "mysql://root:$PW@host/db",
    "http://localhost:8080@proxy", "ssh://git@github.com/org/repo.git",
    "sk_" + "live_" + "x" * 24, "sk-your-key-here-abcdefghijklmnop", "pk_live_publishablekeyisnotasecret1234",
])
def test_a_placeholder_a_reference_or_a_word_is_not_masked(text):
    assert episode_scrub.scrub(text) == (text, 0)


@pytest.mark.parametrize("secret", [
    "glpat-" + "aB3dE5gH7jK9mN1pQ3rS", "npm_" + "aB3dE5gH7jK9mN1pQ3rS5tU7vW9xY1z", "hf_" + "aB3dE5gH7jK9mN1pQ3rS5tU7vW9xY1z",
    "xai-" + "aB3dE5gH7jK9mN1pQ3rS5tU7vW9xY1z", "gsk_" + "aB3dE5gH7jK9mN1pQ3rS5tU7vW9xY1z",
    "SG." + "aB3dE5gH7jK9mN1pQ3rS" + "." + "tU7vW9xY1zA3bC5dE7fG",
])
def test_the_vendor_shapes_the_finder_knew_and_the_scrub_did_not_are_taken(secret):
    from api.services import sensitive_text

    assert episode_scrub.scrub(f"use {secret} now") == ("use [redacted] now", 1)
    assert sensitive_text.find(f"use {secret} now"), "the finder still reports a body stored before the scrub knew it"


def test_the_finder_agrees_on_an_env_line_with_slashes_and_on_a_url_password():
    from api.services import sensitive_text

    for line in (f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}", f'DB_PASSWORD="{DB_PW}"', f"DB_PASSWORD=hunter2hunter2",
                 f"postgres://admin:{URL_PW}@db.internal:5432/app", f"redis://:{URL_PW}@cache/0",
                 f"STRIPE_KEY_{STRIPE_LIVE}"):
        assert [h.kind for h in sensitive_text.find(line)] == ["key"], line
    for line in ("DB_PASSWORD=your_password_here", "DB_PASSWORD=${DB_PASSWORD}", "postgres://user:password@localhost/db",
                 "API_KEY=process.env.API_KEY", "postgres://postgres:postgres@localhost:5432/dev"):
        assert sensitive_text.find(line) == [], line


def test_a_url_field_loses_the_password_in_its_address_and_keeps_the_rest():
    out, n = episode_scrub.scrub_value({"url": f"https://deploy:{URL_PW}@git.example.com/x.git?a=1"})
    assert out["url"] == "https://deploy:[redacted]@git.example.com/x.git?a=1" and n == 1


def test_every_writer_that_stages_through_the_stager_takes_them(tmp_path):
    from api.services import markdown_parser
    from api.services.episode_staging import EpisodeDraft, Turn, stage

    episodes = tmp_path / "episodes"
    episodes.mkdir()
    body = f"user: my .env has AWS_SECRET_ACCESS_KEY={AWS_SECRET} and DB_PASSWORD=\"{DB_PW}\" and {STRIPE_LIVE}"
    draft = EpisodeDraft(title="env", source_id="example:2", source="import", timestamp="2026-11-06T10:00:00+00:00",
                         turns=[Turn(text=body.removeprefix("user: "), speaker="user")],
                         extra={"memo": {"description": f"postgres://admin:{URL_PW}@db/app"}})
    stage([draft], episodes)
    [path] = list(episodes.glob("ep_*.md"))
    raw = path.read_text(encoding="utf-8")
    for value in (AWS_SECRET, DB_PW, STRIPE_LIVE, URL_PW):
        assert value not in raw
    assert markdown_parser.parse(path).frontmatter["memo"]["description"] == "postgres://admin:[redacted]@db/app"
