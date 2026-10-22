"""G159 amendment (owner 2026-10-09) — a person's photo from a public profile, keyed only by an identifier the page or
the person's own record already holds: the owner's email (hashed) and a GitHub profile link among the page's sources.

Fake HTTP only: no test here, and no probe, ever asks the real services."""
from __future__ import annotations

import asyncio
import hashlib
import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api.services import logo_service, markdown_parser, net_guard, person_photo
from api.services.logo_service import FetchResult


def png_bytes(width: int = 64, height: int = 64) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


def jpeg_bytes(width: int = 64, height: int = 64) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


GITHUB_SOURCE = {"ref": "https://github.com/bob-example", "kind": "url", "added_by": "user"}


@pytest.fixture
def gates_on(monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "on")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    memory = tmp_path / "default"
    (memory / "entities").mkdir(parents=True)
    return memory


def write_page(memory: Path, entity_id: str, fm: dict) -> Path:
    path = memory / "entities" / f"{entity_id}.md"
    markdown_parser.write(path, {"name": entity_id, "type": "person", **fm}, "")
    return path


class FakeHTTP:
    """Answers by URL prefix; records every URL asked."""

    def __init__(self, answers: dict[str, FetchResult]):
        self.answers = answers
        self.asked: list[str] = []

    async def __call__(self, url: str) -> FetchResult:
        self.asked.append(url)
        for prefix, result in self.answers.items():
            if url.startswith(prefix):
                return result
        return FetchResult(status=404, body=b"", content_type="text/plain")


# --- identifiers: never guessed ---------------------------------------------------------------------------------


def test_the_email_hash_is_sha256_of_the_trimmed_lowercased_address():
    expected = hashlib.sha256(b"bob@example.com").hexdigest()
    assert person_photo.gravatar_hash("  Bob@Example.COM \n") == expected
    assert person_photo.gravatar_hash("bob@example.com") == expected
    for junk in ("", "   ", "bob", "bob@", "@example.com", "bob@example", "b ob@example.com", "a@b@example.com", None, 5):
        assert person_photo.gravatar_hash(junk) is None, junk


def test_a_github_username_comes_only_from_a_profile_url():
    assert person_photo.github_username("https://github.com/bob-example") == "bob-example"
    assert person_photo.github_username("https://www.github.com/bob-example/") == "bob-example"
    assert person_photo.github_username("https://github.com/bob-example?tab=repositories") == "bob-example"
    for not_a_profile in ("https://github.com/bob-example/alpha-project", "https://github.com/orgs/acme",
                          "https://github.com/features", "https://github.com/", "https://gitlab.com/bob-example",
                          "https://github.com.evil.example/bob-example", "github.com/bob-example",
                          "ftp://github.com/bob-example", "https://github.com/-bad", "https://github.com/bad--name",
                          "https://github.com/" + "a" * 40, "bob-example", "", None):
        assert person_photo.github_username(not_a_profile) is None, not_a_profile


def test_candidates_never_guess_from_a_name():
    # A name, an alias, a claim, a website source: none of them is an identifier.
    fm = {"type": "person", "name": "Bob Example", "aliases": ["bob-example"],
          "sources": [{"ref": "https://example.com/bob-example", "kind": "url", "predicate": "website"},
                      {"ref": "addressbook://card-1", "kind": "app", "predicate": "email", "added_by": "cicada"}]}
    assert person_photo.candidates(fm, owner={"email": "owner@example.com"}) == []


def test_the_owner_email_is_used_only_on_the_owners_page():
    owner = {"email": "Owner@Example.com", "entity_id": "owner-example"}
    expected = person_photo.Candidate("gravatar", hashlib.sha256(b"owner@example.com").hexdigest())
    assert person_photo.candidates({"type": "person", "owner": True}, owner=owner) == [expected]
    assert person_photo.candidates({"type": "person"}, owner=owner) == []
    assert person_photo.candidates({"type": "company", "owner": True}, owner=owner) == []


def test_a_github_link_on_the_page_is_a_candidate_after_the_email():
    fm = {"type": "person", "owner": True, "sources": [GITHUB_SOURCE]}
    found = person_photo.candidates(fm, owner={"email": "owner@example.com"})
    assert [c.provider for c in found] == ["gravatar", "github"]
    assert found[1].value == "bob-example"
    # An agent's link counts (the owner's ruling); an "Only I know" note never does.
    agent = {**GITHUB_SOURCE, "added_by": "claude-code"}
    assert person_photo.candidates({"type": "person", "sources": [agent]}, owner={})[0].value == "bob-example"
    hidden = {**GITHUB_SOURCE, "only_me": True}
    assert person_photo.candidates({"type": "person", "sources": [hidden]}, owner={}) == []
    # The person's own link outranks an agent's.
    two = [{"ref": "https://github.com/agent-guess", "kind": "url", "added_by": "claude-code"}, GITHUB_SOURCE]
    assert person_photo.candidates({"type": "person", "sources": two}, owner={})[0].value == "bob-example"


def test_the_email_never_reaches_a_provider_url_or_the_cache_key():
    email = "owner@example.com"
    cands = person_photo.candidates({"type": "person", "owner": True}, owner={"email": email})
    url = person_photo.provider_url(cands[0])
    assert email not in url and "owner" not in url
    assert url == f"https://gravatar.com/avatar/{hashlib.sha256(email.encode()).hexdigest()}?s=256&d=404"
    key = person_photo.identity_key(cands)
    assert key and cands[0].value not in key
    assert person_photo.provider_url(person_photo.Candidate("github", "bob-example")) == \
        "https://github.com/bob-example.png?size=256"


# --- the fetch ---------------------------------------------------------------------------------------------------


def test_both_gates_must_be_on(monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "on")
    assert person_photo.fetch_allowed()
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "off")
    assert not person_photo.fetch_allowed()
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    assert not person_photo.fetch_allowed()
    monkeypatch.delenv("CICADA_ALLOW_PERSON_PHOTO_FETCH")
    monkeypatch.delenv("CICADA_ALLOW_LOGO_FETCH")
    assert person_photo.fetch_allowed(), "on by default, as the owner allowed it"


def test_the_suite_runs_with_both_gates_off():
    import os

    assert os.environ["CICADA_ALLOW_PERSON_PHOTO_FETCH"] == "off" and not person_photo.fetch_allowed()


@pytest.mark.parametrize("gate", ["CICADA_ALLOW_LOGO_FETCH", "CICADA_ALLOW_PERSON_PHOTO_FETCH"])
def test_a_gate_off_asks_nobody_and_records_no_miss(bank, gates_on, monkeypatch, gate):
    monkeypatch.setenv(gate, "off")
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    http = FakeHTTP({"https://github.com/": FetchResult(200, png_bytes(), "image/png")})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http)) is None
    assert http.asked == []
    assert person_photo.read_meta("default") == {}, "never asked is not a miss"


def test_a_hit_is_stored_once_outside_the_bank_and_served_from_then_on(bank, gates_on):
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    http = FakeHTTP({"https://github.com/bob-example.png": FetchResult(200, png_bytes(), "image/png")})
    path = asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http))
    assert path is not None and path.read_bytes() == png_bytes()
    assert bank not in path.parents, "never inside a bank"
    assert path.parent.name == "people" and path.name == "bob-example.png"
    again = asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http))
    assert again == path and len(http.asked) == 1, "checked once per person"
    entry = person_photo.read_meta("default")["bob-example"]
    assert entry["miss"] is False and entry["ext"] == "png" and len(entry["sha"]) == 12


def test_the_email_is_asked_first_and_a_404_falls_through_to_github(bank, gates_on, monkeypatch):
    from api.services import owner_identity

    monkeypatch.setattr(owner_identity, "load_owner", lambda: {"email": "owner@example.com"})
    write_page(bank, "owner-example", {"owner": True, "sources": [GITHUB_SOURCE]})
    http = FakeHTTP({"https://gravatar.com/": FetchResult(404, b"", "text/plain"),
                     "https://github.com/bob-example.png": FetchResult(200, jpeg_bytes(), "image/jpeg")})
    path = asyncio.run(person_photo.ensure_photo(bank, "owner-example", fetcher=http))
    assert path is not None and path.suffix == ".jpg"
    assert http.asked[0].startswith("https://gravatar.com/avatar/") and http.asked[0].endswith("&d=404")
    assert http.asked[1].startswith("https://github.com/bob-example.png")
    assert all("owner@example.com" not in u for u in http.asked)


def test_a_redirect_is_followed_only_to_the_providers_own_hosts(bank, gates_on):
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    good = FakeHTTP({
        "https://github.com/bob-example.png": FetchResult(302, b"", "", location="https://avatars.githubusercontent.com/u/1?s=256"),
        "https://avatars.githubusercontent.com/": FetchResult(200, png_bytes(), "image/png")})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=good)) is not None
    write_page(bank, "carol-example", {"sources": [{**GITHUB_SOURCE, "ref": "https://github.com/carol-example"}]})
    bad = FakeHTTP({"https://github.com/carol-example.png": FetchResult(302, b"", "", location="https://tracker.example.com/x.png"),
                    "https://tracker.example.com/": FetchResult(200, png_bytes(), "image/png")})
    assert asyncio.run(person_photo.ensure_photo(bank, "carol-example", fetcher=bad)) is None
    assert bad.asked == ["https://github.com/carol-example.png?size=256"], "the stranger's host is never asked"


def test_net_guard_refuses_a_provider_host_that_resolves_inward(bank, gates_on, monkeypatch):
    monkeypatch.setattr(net_guard, "_resolve_host", lambda host: ["127.0.0.1"])
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    http = FakeHTTP({"https://github.com/": FetchResult(200, png_bytes(), "image/png")})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http)) is None
    assert http.asked == []


@pytest.mark.parametrize("result", [
    FetchResult(200, b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/png"),
    FetchResult(200, b"<svg onload='x'></svg>", "image/svg+xml"),
    FetchResult(200, png_bytes(8, 8), "image/png"),
    FetchResult(200, png_bytes() + b"\x00" * (512 * 1024), "image/png"),
    FetchResult(200, b"GIF89a\x40\x00\x40\x00", "image/gif"),
    FetchResult(200, b"<html>not an image</html>", "text/html"),
], ids=["svg-behind-png", "svg", "tiny", "oversize", "gif", "html"])
def test_only_a_png_or_jpeg_within_bounds_is_kept(result):
    assert person_photo.accept(result) is None


def test_a_miss_is_remembered_and_retried_after_its_window(bank, gates_on):
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    http = FakeHTTP({})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http)) is None
    assert len(http.asked) == 1
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http)) is None
    assert len(http.asked) == 1, "a fresh miss asks nobody"
    meta = person_photo.read_meta("default")
    old = (datetime.now(timezone.utc) - person_photo.MISS_TTL - timedelta(hours=1)).isoformat()
    meta["bob-example"]["fetched_at"] = old
    person_photo.write_meta("default", meta)
    asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http))
    assert len(http.asked) == 2, "past the window it is asked again"


def test_a_failed_connection_is_retried_sooner_than_a_real_miss(bank, gates_on):
    async def down(url):
        raise OSError("offline")

    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=down)) is None
    entry = person_photo.read_meta("default")["bob-example"]
    assert entry["miss"] is True and entry["transient"] is True
    assert person_photo.TRANSIENT_TTL < person_photo.MISS_TTL


def test_a_changed_identifier_is_asked_again(bank, gates_on):
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    http = FakeHTTP({})
    asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http))
    write_page(bank, "bob-example", {"sources": [{**GITHUB_SOURCE, "ref": "https://github.com/bob-other"}]})
    asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http))
    assert http.asked[-1].startswith("https://github.com/bob-other.png")


def test_a_removed_link_drops_the_stored_photo(bank, gates_on):
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    http = FakeHTTP({"https://github.com/bob-example.png": FetchResult(200, png_bytes(), "image/png")})
    path = asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http))
    write_page(bank, "bob-example", {})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http)) is None
    assert not path.exists() and "bob-example" not in person_photo.read_meta("default")


def test_the_persons_choice_and_contacts_photo_mean_no_fetch(bank, gates_on):
    http = FakeHTTP({"https://github.com/": FetchResult(200, png_bytes(), "image/png")})
    write_page(bank, "a-example", {"sources": [GITHUB_SOURCE], "picture": {"kind": "initials"}})
    write_page(bank, "b-example", {"sources": [GITHUB_SOURCE], "contacts_photo": {"sha": "0a1b2c3d4e5f", "ext": "jpg"}})
    write_page(bank, "c-example", {"type": "company", "sources": [GITHUB_SOURCE]})
    for eid in ("a-example", "b-example", "c-example", "missing-example"):
        assert asyncio.run(person_photo.ensure_photo(bank, eid, fetcher=http)) is None
    assert http.asked == []


# --- what /graph reads (no I/O beyond the index) ------------------------------------------------------------------


def test_availability_is_offered_until_known_to_miss(bank, gates_on):
    fm = {"type": "person", "sources": [GITHUB_SOURCE]}
    key = person_photo.identity_key(person_photo.candidates(fm, owner={}))
    assert key and len(key) == 16
    assert person_photo.available("bob-example", fm, {}, owner={}) == (True, None, key), "never asked: the card may ask"
    assert person_photo.available("bob-example", {"type": "person"}, {}, owner={}) == (False, None, None)
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    http = FakeHTTP({"https://github.com/bob-example.png": FetchResult(200, png_bytes(), "image/png")})
    asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http))
    meta = person_photo.read_meta("default")
    offered, sha, got = person_photo.available("bob-example", fm, meta, owner={}, bank="default")
    assert offered and sha == meta["bob-example"]["sha"] and got == key
    miss = {"bob-example": {**meta["bob-example"], "miss": True, "ext": None, "sha": None}}
    assert person_photo.available("bob-example", fm, miss, owner={}) == (False, None, key)
    other = {"type": "person", "sources": [{**GITHUB_SOURCE, "ref": "https://github.com/bob-other"}]}
    offered, sha, other_key = person_photo.available("bob-example", other, miss, owner={})
    assert offered and sha is None and other_key != key, "a new identifier is asked, under a new key"


def test_the_stamp_moves_on_a_write_and_on_an_expiry(bank, gates_on):
    before = person_photo.stamp("default")
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=FakeHTTP({})))
    after = person_photo.stamp("default")
    assert after != before
    meta = person_photo.read_meta("default")
    meta["bob-example"]["fetched_at"] = (datetime.now(timezone.utc) - person_photo.MISS_TTL * 2).isoformat()
    person_photo.meta_path("default").write_text(json.dumps(meta), encoding="utf-8")
    assert person_photo.stamp("default").split(":")[-1] == "1"


def test_reading_never_creates_the_cache_folder(bank):
    assert person_photo.read_meta("default") == {}
    person_photo.stamp("default")
    assert not (Path(logo_service.meta_path("default")).parents[2] / "pictures").exists()


def test_a_demo_bank_asks_nobody_and_never_offers_the_owners_email(bank, gates_on, monkeypatch):
    """A demo is synthetic and made for screenshots: the real owner's email must not draw its owner page."""
    from api.services import demo_guard, entity_picture, owner_identity

    monkeypatch.setattr(owner_identity, "load_owner", lambda: {"email": "owner@example.com"})
    demo_guard.write_manifest(bank)
    write_page(bank, "owner-example", {"owner": True})
    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE]})
    http = FakeHTTP({"https://": FetchResult(200, png_bytes(), "image/png")})
    for eid in ("owner-example", "bob-example"):
        assert asyncio.run(person_photo.ensure_photo(bank, eid, fetcher=http)) is None
    assert http.asked == []
    fm = markdown_parser.parse(bank / "entities" / "owner-example.md").frontmatter
    resolved, inputs = entity_picture.resolve_page(bank, "owner-example", fm, "", page_mtime=0.0)
    assert resolved.source is None and inputs.profile is False


# --- the avatar proxy for X and LinkedIn (owner 2026-10-09: its own gate, off by default) ---------------------------


X_SOURCE = {"ref": "https://x.com/bob_example", "kind": "url", "added_by": "user"}
LINKEDIN_SOURCE = {"ref": "https://www.linkedin.com/in/bob-example/", "kind": "url", "added_by": "user"}


@pytest.fixture
def proxy_on(gates_on, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_PROXY", "on")


def test_an_x_handle_comes_only_from_a_profile_url():
    assert person_photo.x_handle("https://x.com/bob_example") == "bob_example"
    assert person_photo.x_handle("https://twitter.com/bob_example/") == "bob_example"
    assert person_photo.x_handle("https://www.x.com/bob_example?lang=en") == "bob_example"
    for refused in ("https://x.com/bob_example/status/1234567890", "https://x.com/home", "https://x.com/i/lists/1",
                    "https://x.com/search?q=bob", "https://x.com/hashtag/alpha", "https://x.com/", "x.com/bob_example",
                    "https://x.com.evil.example/bob_example", "https://x.com/bob-example", "https://x.com/" + "a" * 16,
                    "https://mastodon.example/@bob_example", None):
        assert person_photo.x_handle(refused) is None, refused


def test_a_linkedin_slug_comes_only_from_an_in_profile_url():
    assert person_photo.linkedin_slug("https://www.linkedin.com/in/bob-example/") == "bob-example"
    assert person_photo.linkedin_slug("https://linkedin.com/in/bob-example") == "bob-example"
    for refused in ("https://www.linkedin.com/company/acme-example", "https://www.linkedin.com/posts/bob-example_x",
                    "https://www.linkedin.com/in/bob-example/details/experience", "https://www.linkedin.com/in/",
                    "https://www.linkedin.com/feed/", "https://www.linkedin.com/pub/bob-example/1/2/3",
                    "https://linkedin.com.evil.example/in/bob-example", "https://www.linkedin.com/in/a", None):
        assert person_photo.linkedin_slug(refused) is None, refused


def test_the_proxy_gate_is_on_by_default_its_off_switch_works_and_it_needs_the_others(monkeypatch):
    # Ruling 36 D5 (owner 2026-10-22: "photo gate ON"); it was off by default from 2026-10-09.
    monkeypatch.delenv("CICADA_ALLOW_PERSON_PHOTO_PROXY", raising=False)
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "on")
    assert person_photo.fetch_allowed() and person_photo.proxy_allowed(), "on by default"
    for off in ("off", "0", "false", "OFF"):
        monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_PROXY", off)
        assert not person_photo.proxy_allowed(), off
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_PROXY", "on")
    assert person_photo.proxy_allowed()
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "off")
    assert not person_photo.proxy_allowed(), "never past the people gate"


def test_with_the_proxy_gate_off_an_x_or_linkedin_link_is_no_identifier(bank, gates_on):
    fm = {"type": "person", "sources": [X_SOURCE, LINKEDIN_SOURCE]}
    assert person_photo.candidates(fm, owner={}) == []
    write_page(bank, "bob-example", {"sources": [X_SOURCE, LINKEDIN_SOURCE]})
    http = FakeHTTP({"https://unavatar.io/": FetchResult(200, png_bytes(), "image/png")})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http)) is None
    assert http.asked == []


def test_the_order_is_email_github_x_linkedin(proxy_on):
    fm = {"type": "person", "owner": True, "sources": [LINKEDIN_SOURCE, X_SOURCE, GITHUB_SOURCE]}
    found = person_photo.candidates(fm, owner={"email": "owner@example.com"})
    assert [c.provider for c in found] == ["gravatar", "github", "x", "linkedin"]
    urls = [person_photo.provider_url(c) for c in found[2:]]
    assert urls == ["https://unavatar.io/x/bob_example?fallback=false",
                    "https://unavatar.io/linkedin/user:bob-example?fallback=false"], "a miss is a 404, never a default"


def test_the_proxy_is_asked_only_after_the_direct_providers_miss(bank, proxy_on):
    write_page(bank, "bob-example", {"sources": [LINKEDIN_SOURCE, X_SOURCE, GITHUB_SOURCE]})
    http = FakeHTTP({"https://unavatar.io/linkedin/": FetchResult(200, jpeg_bytes(), "image/jpeg")})
    path = asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http))
    assert path is not None and path.suffix == ".jpg"
    assert [u.split("?")[0] for u in http.asked] == ["https://github.com/bob-example.png",
                                                     "https://unavatar.io/x/bob_example",
                                                     "https://unavatar.io/linkedin/user:bob-example"]


def test_a_proxy_redirect_off_its_own_host_is_refused(bank, proxy_on):
    write_page(bank, "bob-example", {"sources": [X_SOURCE]})
    http = FakeHTTP({"https://unavatar.io/x/": FetchResult(302, b"", "", location="https://cdn.example.com/a.jpg"),
                     "https://cdn.example.com/": FetchResult(200, jpeg_bytes(), "image/jpeg")})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=http)) is None
    assert len(http.asked) == 1


def test_the_daily_budget_is_install_wide_and_over_it_is_a_transient_miss(bank, proxy_on, monkeypatch):
    monkeypatch.setattr(person_photo, "PROXY_DAILY_BUDGET", 2)
    http = FakeHTTP({})
    for n in range(3):
        write_page(bank, f"p{n}-example", {"sources": [{**X_SOURCE, "ref": f"https://x.com/p{n}_example"}]})
        asyncio.run(person_photo.ensure_photo(bank, f"p{n}-example", fetcher=http))
    assert len(http.asked) == 2, "the third lookup waits for tomorrow"
    meta = person_photo.read_meta("default")
    assert meta["p0-example"]["transient"] is False, "a real 404 is a real miss"
    assert meta["p2-example"]["miss"] is True and meta["p2-example"]["transient"] is True
    budget = person_photo.budget_path()
    assert bank not in budget.parents and "pictures" in budget.parts
    # Another bank on the same Mac shares the budget.
    other = bank.parent / "other"
    (other / "entities").mkdir(parents=True)
    write_page(other, "q-example", {"sources": [X_SOURCE]})
    asyncio.run(person_photo.ensure_photo(other, "q-example", fetcher=http))
    assert len(http.asked) == 2


# --- which links are the person's own account (review B2) ----------------------------------------------------------


@pytest.mark.parametrize("source, counts", [
    ({"ref": "https://github.com/bob-example", "kind": "url", "added_by": "user"}, True),
    ({"ref": "https://github.com/bob-example", "kind": "url", "added_by": "user", "predicate": "profile"}, True),
    ({"ref": "https://github.com/bob-example", "kind": "url", "added_by": "claude-code", "accepted": True,
      "predicate": "works-at"}, False),
    ({"ref": "https://github.com/bob-example", "kind": "url", "added_by": "claude-code"}, True),
    ({"ref": "https://github.com/bob-example", "kind": "url", "added_by": "claude-code", "predicate": "github"}, True),
    ({"ref": "https://github.com/acme-org", "kind": "url", "added_by": "user", "predicate": "works-at"}, False),
    ({"ref": "https://github.com/acme-org", "kind": "url", "added_by": "claude-sonnet-4-5", "predicate": "works-at"}, False),
    ({"ref": "https://github.com/bob-example", "kind": "url", "added_by": "agent"}, False),
    ({"ref": "https://github.com/bob-example", "kind": "url", "added_by": "cicada"}, False),
    ({"ref": "https://github.com/bob-example", "kind": "url", "added_by": "user", "only_me": True}, False),
], ids=["person", "person-profile", "taken-for-a-fact", "agent-no-fact", "agent-profile", "person-works-at",
        "stage-5.56-cite", "unidentified-proposal", "cicada", "only-me"])
def test_only_a_link_given_as_the_persons_own_account_counts(source, counts):
    found = person_photo.candidates({"type": "person", "sources": [source]}, owner={})
    assert bool(found) is counts


def test_no_fact_stage_5_56_can_cite_is_a_profile_predicate(tmp_path):
    """Stage 5.56 attaches a cited link under the claim's own predicate, and only one whose locus is `world` or
    `artifact`; none of those may ever read as "this is their account"."""
    from api.services import predicates

    locus_of = predicates.build_locus_fn(tmp_path)
    for predicate in person_photo.PROFILE_PREDICATES:
        assert locus_of(predicate) not in ("world", "artifact"), predicate


def test_the_whole_ladder_has_one_deadline(bank, proxy_on, monkeypatch):
    monkeypatch.setattr(person_photo, "LADDER_SECONDS", 0.05)

    async def slow(url):
        await asyncio.sleep(0.2)
        return FetchResult(404, b"", "text/plain")

    write_page(bank, "bob-example", {"sources": [GITHUB_SOURCE, X_SOURCE]})
    assert asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=slow)) is None
    entry = person_photo.read_meta("default")["bob-example"]
    assert entry["transient"] is True, "out of time is asked again soon, never a cached miss"


def test_the_proxy_budget_is_spent_only_on_a_request_that_may_go(bank, proxy_on, monkeypatch):
    monkeypatch.setattr(net_guard, "_resolve_host", lambda host: ["127.0.0.1"])
    write_page(bank, "bob-example", {"sources": [X_SOURCE]})
    asyncio.run(person_photo.ensure_photo(bank, "bob-example", fetcher=FakeHTTP({})))
    assert not person_photo.budget_path().exists(), "a refused request spends nothing"
