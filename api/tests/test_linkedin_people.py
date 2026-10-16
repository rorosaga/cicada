"""LinkedIn connections (owner 2026-10-16, G154's pattern): the person's ``Connections.csv`` ENRICHES the people Cicada
already knows — exactly one person page per connection, never a new page, the profile link as a source, company,
position and the day connected as dated ``external:linkedin`` claims (newest export wins), the email column never
stored anywhere — and the rest waits in a directory outside the bank for a person who gets a page later. The
``linkedin-people`` skill's ``cicada_record_profile`` records one profile the person's agent read. Synthetic people
and placeholder links only; nothing reads a real bank, ``~/.cicada`` or the network."""
from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import reading  # noqa: F401 — a fixture
from _synthetic_bank import _bank, _entity
from api import config, main
from api.services import bank_index, demo_guard, fact_sources, linkedin_people, markdown_parser, sleep_cycle
from api.services.claims import parse_claims

EMAIL = "bob@bob-example.org"

#: LinkedIn's own shape: notes above the header, blank emails, a credential after a comma, duplicate names, unicode.
CSV_2026_01 = f"""Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing. You will only see email addresses for connections who have allowed their connections to see or download their email address using this setting https://www.linkedin.com/psettings/privacy/email. You can learn more here."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Bob,"Example, PhD",https://www.linkedin.com/in/bob-example,{EMAIL},Acme Labs,Staff Engineer,04 Mar 2021
Carol,Example,https://www.linkedin.com/in/carol-example-1a2b3c,,Beta Corp,Designer,12 Jan 2020
Dana,Twin,https://www.linkedin.com/in/dana-twin-1,,Gamma,Analyst,01 Feb 2022
Erin,Repeat,https://www.linkedin.com/in/erin-repeat-1,,One Co,PM,01 Feb 2022
Erin,Repeat,https://www.linkedin.com/in/erin-repeat-2,,Two Co,PM,02 Feb 2022
José,Ñúñez,https://www.linkedin.com/in/jose-nunez-ex,,Delta SA,Founder,15 Jun 2019
Frank,Stranger,https://www.linkedin.com/in/frank-stranger,,Omega,CTO,10 Oct 2023
,,,,,,
"""


def _csv(rows: str = CSV_2026_01) -> bytes:
    return rows.encode("utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)   # has `bob-example` (person, "Bob Example") and `alpha-project`
    _entity(memory, "carol-example", type="person", name="Carolina Example", aliases=["Carol Example"])
    _entity(memory, "dana-one", type="person", name="Dana Twin")
    _entity(memory, "dana-two", type="person", name="Dana Twin")
    _entity(memory, "erin-repeat", type="person", name="Erin Repeat")
    _entity(memory, "jose-nunez", type="person", name="Jose Nunez")
    _entity(memory, "owner-page", type="person", name="Frank Stranger", owner=True)
    _entity(memory, "acme-labs", type="company", name="Acme Labs")
    subprocess.run(["git", "-C", str(memory), "add", "entities"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "fixtures"], check=True, capture_output=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _post(c, data=None, *, route="import", filename="Connections.csv", exported_on=None):
    params = {"exported_on": exported_on} if exported_on else {}
    return c.post(f"/sources/linkedin-connections/{route}", params=params,
                  files={"file": (filename, data if data is not None else _csv(), "text/csv")})


def _page(memory, eid):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md")


def _claims(memory, eid):
    return parse_claims(_page(memory, eid).body)


def _li(memory, eid, predicate=None):
    return [c for c in _claims(memory, eid) if c.observer == linkedin_people.OBSERVER
            and (predicate is None or c.predicate == predicate)]


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def _people(memory):
    return sorted(p.name for p in (memory / "entities").glob("*"))


# --- reading the file -------------------------------------------------------------------------------------------


def test_the_reader_skips_linkedins_notes_and_never_reads_the_email_column():
    parsed = linkedin_people.parse(_csv())
    names = [c.name for c in parsed.connections]
    assert names[0] == "Bob Example"                      # ", PhD" is a credential, not the name
    assert "José Ñúñez" in names and len(names) == 7      # the empty row is not a connection
    bob = parsed.connections[0]
    assert (bob.url, bob.company, bob.position, bob.connected_on) == (
        "https://www.linkedin.com/in/bob-example", "Acme Labs", "Staff Engineer", "2021-03-04")
    assert EMAIL not in json.dumps([c.to_dict() for c in parsed.connections])


def test_a_file_that_is_not_the_export_is_refused_in_words():
    with pytest.raises(linkedin_people.PayloadError):
        linkedin_people.parse(b"Title,URL\nA thing,https://example.com\n")


def test_the_export_zip_is_read_and_dated_by_its_own_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("Basic_LinkedInDataExport/Connections.csv", date_time=(2026, 9, 30, 12, 0, 0))
        z.writestr(info, _csv())
        z.writestr("Basic_LinkedInDataExport/messages.csv", "never,read\n")
    parsed = linkedin_people.parse(buf.getvalue(), "export.zip")
    assert parsed.exported_on == "2026-09-30" and len(parsed.connections) == 7
    assert linkedin_people.as_of(None, parsed) == "2026-09-30"
    assert linkedin_people.as_of("2026-10-01", parsed) == "2026-10-01"      # the caller's date wins
    assert linkedin_people.as_of("2999-01-01", parsed) == "2026-09-30"      # never a future day


def test_only_member_profiles_are_kept_as_links():
    assert linkedin_people.profile_url("https://linkedin.com/in/bob-example/") == \
        "https://www.linkedin.com/in/bob-example"
    for not_a_profile in ("https://www.linkedin.com/company/acme", "https://www.linkedin.com/in/bob/details",
                          "https://example.com/in/bob", "bob-example", ""):
        assert linkedin_people.profile_url(not_a_profile) is None


# --- the preview ------------------------------------------------------------------------------------------------


def test_the_preview_counts_matches_and_writes_nothing(client):
    c, memory = client
    head = _git(memory, "rev-parse", "HEAD")
    r = _post(c, route="preview", exported_on="2026-01-15")
    assert r.status_code == 200, r.text
    body = r.json()
    # Bob, Carol (by alias) and José (accents fold: "Ñúñez" is "nunez") match; Dana's name is on two pages and Erin is
    # two connections (ambiguous, 3); Frank's name is only the owner's page, which is never matched.
    assert (body["connections"], body["matched"], body["ambiguous"], body["unmatched"]) == (7, 3, 3, 1)
    assert body["exportedOn"] == "2026-01-15"
    assert _git(memory, "rev-parse", "HEAD") == head and not _git(memory, "status", "--porcelain")
    assert not linkedin_people.directory_path(memory.name).exists()


# --- the import -------------------------------------------------------------------------------------------------


def test_an_import_enriches_exactly_the_pages_it_matches_and_commits_once_as_the_person(client):
    c, memory = client
    before = _people(memory)
    r = _post(c, exported_on="2026-01-15")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["matched"], body["sourcesAdded"]) == (3, 3)
    assert _people(memory) == before                                  # never a new page
    bob = _page(memory, "bob-example").frontmatter
    (src,) = [s for s in bob["sources"] if s["predicate"] == "linkedin"]
    assert src == {"ref": "https://www.linkedin.com/in/bob-example", "kind": "url", "predicate": "linkedin",
                   "added_by": "cicada", "added_at": src["added_at"]}
    works, role, connected = (_li(memory, "bob-example", p)[0] for p in ("works-at", "role", "connected-on"))
    assert works.object == "acme-labs" and works.object_kind == "node"   # the company page Cicada already has
    assert role.object == "Staff Engineer" and role.object_kind == "literal"
    assert connected.object == "2021-03-04" and connected.valid_from == "2021-03-04"
    for claim in (works, role, connected):
        assert claim.source_trust == "external" and claim.origin == "linkedin/connections"
        assert claim.authored_by == "cicada" and claim.valid_to is None
    assert works.valid_from == "2026-01-15" and "as LinkedIn listed on 2026-01-15" in works.text
    for untouched in ("dana-one", "dana-two", "erin-repeat", "owner-page", "alpha-project"):
        assert not _li(memory, untouched) and "linkedin" not in json.dumps(_page(memory, untouched).frontmatter)
    log = _git(memory, "log", "-1", "--format=%s%n%b")
    assert log.startswith("LinkedIn connections") and "capture/linkedin-connections" in log
    assert "Cicada-Author: user" in log
    assert not _git(memory, "status", "--porcelain")
    assert set(_git(memory, "show", "--name-only", "--format=", "HEAD").split()) == {
        "entities/bob-example.md", "entities/carol-example.md", "entities/jose-nunez.md"}


def test_an_email_address_is_never_stored_in_the_bank_or_the_directory(client):
    c, memory = client
    assert _post(c).status_code == 200
    for root in (memory, linkedin_people.directory_path(memory.name).parent):
        for dirpath, _, files in os.walk(root):
            if ".git" in dirpath:
                continue
            for name in files:
                assert EMAIL not in open(os.path.join(dirpath, name), encoding="utf-8", errors="ignore").read()


def test_the_directory_lives_outside_the_bank_readable_only_by_the_person(client):
    c, memory = client
    assert _post(c, exported_on="2026-01-15").status_code == 200
    path = linkedin_people.directory_path(memory.name)
    assert memory not in path.parents and oct(path.stat().st_mode & 0o777) == "0o600"
    held = json.loads(path.read_text())
    assert held["exported_on"] == "2026-01-15" and len(held["connections"]) == 7
    status = c.get("/sources/linkedin-connections").json()
    assert (status["connections"], status["exportedOn"]) == (7, "2026-01-15")


def test_a_reimport_writes_nothing(client):
    c, memory = client
    assert _post(c, exported_on="2026-01-15").status_code == 200
    head = _git(memory, "rev-parse", "HEAD")
    r = _post(c, exported_on="2026-01-15")
    assert r.json()["sourcesAdded"] == 0 and r.json()["claimsWritten"] == 0
    assert _git(memory, "rev-parse", "HEAD") == head and not _git(memory, "status", "--porcelain")


def test_a_newer_export_wins_and_an_older_one_changes_nothing(client):
    c, memory = client
    assert _post(c, exported_on="2026-01-15").status_code == 200
    newer = CSV_2026_01.replace("Acme Labs,Staff Engineer", "Zeta Inc,Principal Engineer")
    r = _post(c, _csv(newer), exported_on="2026-09-01")
    assert r.json()["claimsClosed"] == 2
    works = _li(memory, "bob-example", "works-at")
    old = next(w for w in works if w.object == "acme-labs")
    new = next(w for w in works if w.object == "Zeta Inc")
    assert old.valid_to == "2026-09-01" and old.superseded_by == new.id and new.supersedes == old.id
    assert new.valid_to is None and new.valid_from == "2026-09-01"
    assert len(_li(memory, "bob-example", "connected-on")) == 1        # the same day connected: nothing new
    head = _git(memory, "rev-parse", "HEAD")
    r = _post(c, exported_on="2026-01-15")                               # the old file again
    assert r.json()["claimsWritten"] == 0 and r.json()["older"] >= 2
    assert _git(memory, "rev-parse", "HEAD") == head
    assert json.loads(linkedin_people.directory_path(memory.name).read_text())["exported_on"] == "2026-09-01"


def test_a_link_the_person_removed_is_never_put_back(client):
    c, memory = client
    assert _post(c).status_code == 200
    r = c.post("/entities/bob-example/sources/change",
               json={"ref": "https://www.linkedin.com/in/bob-example", "predicate": "linkedin", "action": "remove"})
    assert r.status_code == 200, r.text
    assert not [s for s in _page(memory, "bob-example").frontmatter.get("sources") or [] if s["predicate"] == "linkedin"]
    before = len(_li(memory, "bob-example"))
    newer = CSV_2026_01.replace("Acme Labs,Staff Engineer", "Zeta Inc,Principal Engineer")
    r = _post(c, _csv(newer), exported_on="2026-09-01")
    assert r.json()["sourcesAdded"] == 0 and r.json()["removedKeptOut"] == 1
    assert not [s for s in _page(memory, "bob-example").frontmatter.get("sources") or [] if s["predicate"] == "linkedin"]
    assert len(_li(memory, "bob-example")) == before            # the person said it is not Bob: no new facts either


def test_a_page_listing_the_link_matches_by_it_and_a_page_naming_another_profile_is_left_alone(client):
    c, memory = client
    fact_sources.add_source(memory, "dana-one", "https://www.linkedin.com/in/dana-twin-1", predicate="linkedin")
    fact_sources.add_source(memory, "erin-repeat", "https://www.linkedin.com/in/someone-else", predicate="linkedin")
    subprocess.run(["git", "-C", str(memory), "commit", "-qam", "links"], check=True, capture_output=True)
    bank_index.invalidate()
    assert _post(c).status_code == 200
    assert _li(memory, "dana-one", "works-at")[0].object == "Gamma"    # the person's own link settles which Dana
    assert not _li(memory, "dana-two") and not _li(memory, "erin-repeat")


def test_the_demo_bank_takes_no_connections(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(demo_guard, "is_demo", lambda *_a, **_k: True)
    assert _post(c).status_code == 409
    assert _post(c, route="preview").status_code == 409
    assert not _li(memory, "bob-example")


def test_the_save_list_importer_still_refuses_connections_and_points_at_their_own_door(client):
    c, _ = client
    r = c.post("/sources/upload", files={"file": ("Connections.csv", _csv(), "text/csv")})
    assert r.status_code == 422 and "Connections" in r.json()["detail"]


# --- a person who gets a page later -------------------------------------------------------------------------------


def test_sleeps_tail_matches_a_page_made_since_the_import_in_its_own_cicada_commit(client):
    c, memory = client
    assert _post(c, exported_on="2026-01-15").status_code == 200
    _entity(memory, "dana-later", type="person", name="Erin Repeat-Not")   # still not a match: exact names only
    _entity(memory, "dana-two", type="person", name="Dana Other")           # now one Dana page is left
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "sleep"], check=True, capture_output=True)
    bank_index.invalidate()
    asyncio.run(sleep_cycle._rematch_linkedin_safely(memory))
    assert _li(memory, "dana-one", "works-at")[0].object == "Gamma"
    assert not _li(memory, "dana-later") and not _li(memory, "dana-two")
    log = _git(memory, "log", "-1", "--format=%s%n%b")
    assert log.startswith("LinkedIn connections") and "Cicada-Author: cicada" in log
    assert not _git(memory, "status", "--porcelain")
    head = _git(memory, "rev-parse", "HEAD")
    asyncio.run(sleep_cycle._rematch_linkedin_safely(memory))               # nothing new: no commit
    assert _git(memory, "rev-parse", "HEAD") == head


def test_the_tail_step_does_nothing_without_a_kept_export(client):
    _, memory = client
    head = _git(memory, "rev-parse", "HEAD")
    asyncio.run(sleep_cycle._rematch_linkedin_safely(memory))
    assert _git(memory, "rev-parse", "HEAD") == head


# --- a profile the person's agent read (the linkedin-people skill) ---------------------------------------------------

PROFILE = "https://www.linkedin.com/in/bob-example"


def _profile(server, **kw):
    args = {"entity_id": "bob-example", "url": PROFILE, "outcome": "read", "company": "Zeta Inc",
            "position": "Principal Engineer", "quotes": [{"quote": "Principal Engineer at Zeta Inc"}],
            "summary": "Bob moved to Zeta Inc.", "via": "browser-harness", **kw}
    return server.handle_tool("cicada_record_profile", args)


def _seed_link(memory):
    fact_sources.add_source(memory, "bob-example", PROFILE, predicate="linkedin", added_by="cicada")
    subprocess.run(["git", "-C", str(memory), "commit", "-qam", "link"], check=True, capture_output=True)


def test_a_profile_read_writes_the_newest_dated_facts_with_page_spans_as_the_harness(reading):
    server, memory = reading
    _seed_link(memory)
    out = _profile(server)
    assert out.startswith("Recorded Bob Example's LinkedIn profile"), out
    works = _li(memory, "bob-example", "works-at")
    (current,) = [w for w in works if not w.valid_to]
    assert current.object == "Zeta Inc" and current.origin == "linkedin/profile"
    assert current.authored_by == "claude-code" and current.source_trust == "external"
    assert current.evidence[0].kind == "page" and current.evidence[0].is_span()
    episode = next((memory / "episodes").glob("*.md"))
    ep = markdown_parser.parse(sorted((memory / "episodes").glob("*.md"))[-1])
    assert ep.frontmatter["source"] == "profile-read" and ep.frontmatter["processed"] is True
    assert "attachment [linkedin.com]: as claude-code read it" in ep.body and episode
    log = _git(memory, "log", "-1", "--format=%b")
    assert "Cicada-Author: claude-code" in log


def test_a_profile_read_beats_the_export_and_the_export_never_undoes_it(reading):
    server, memory = reading
    _seed_link(memory)
    linkedin_people.apply(memory, linkedin_people.parse(_csv()).connections, day="2026-01-15")
    _profile(server)
    (current,) = [w for w in _li(memory, "bob-example", "works-at") if not w.valid_to]
    assert current.object == "Zeta Inc"
    linkedin_people.apply(memory, linkedin_people.parse(_csv()).connections, day="2026-01-15")
    (current,) = [w for w in _li(memory, "bob-example", "works-at") if not w.valid_to]
    assert current.object == "Zeta Inc"


def test_only_the_link_the_page_lists_can_be_recorded(reading):
    server, memory = reading
    _seed_link(memory)
    head = _git(memory, "rev-parse", "HEAD")
    for args in ({"url": "https://www.linkedin.com/in/someone-else"}, {"entity_id": "alpha-project"},
                 {"entity_id": "carol-example"}):
        assert _profile(server, **args).startswith("Not recorded")
    assert _git(memory, "rev-parse", "HEAD") == head


def test_a_wall_writes_nothing_and_says_never_sign_in(reading):
    server, memory = reading
    _seed_link(memory)
    head = _git(memory, "rev-parse", "HEAD")
    out = _profile(server, outcome="needs_login")
    assert "never sign in" in out and _git(memory, "rev-parse", "HEAD") == head


def test_nothing_in_bulk(reading, monkeypatch):
    server, memory = reading
    _seed_link(memory)
    monkeypatch.setattr(linkedin_people, "MAX_PROFILE_READS_PER_DAY", 1)
    assert _profile(server).startswith("Recorded")
    assert "never in bulk" in _profile(server, company="Eta", position="VP")


def test_the_profile_tool_is_never_offered_remotely():
    from api.remote import catalog

    assert "cicada_record_profile" in catalog.NEVER_REMOTE


def test_the_skill_ships_as_one_of_cicadas_own(tmp_path, monkeypatch):
    from api.services import skill_store

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    text = skill_store.own_bundle("linkedin-people").decode()
    assert text.startswith("---\nname: linkedin-people\n") and "cicada_record_profile(" in text
    assert "never sign in" in " ".join(text.lower().split())


# --- review fixes (2026-10-16) ------------------------------------------------------------------------------------


def test_a_removal_in_any_spelling_of_the_link_keeps_the_page_out(client):
    """The person removed Bob's profile as they had pasted it (a trailing slash, no predicate): the import's canonical
    link is the same profile, so neither the link nor its facts come back."""
    c, memory = client
    fact_sources.add_source(memory, "bob-example", "https://linkedin.com/in/bob-example/", added_by="user")
    fact_sources.change_source(memory, "bob-example", "https://linkedin.com/in/bob-example/", action="remove")
    subprocess.run(["git", "-C", str(memory), "commit", "-qam", "removed"], check=True, capture_output=True)
    bank_index.invalidate()
    r = _post(c)
    assert r.status_code == 200 and r.json()["removedKeptOut"] == 1
    assert not [s for s in _page(memory, "bob-example").frontmatter.get("sources") or []
                if "linkedin" in str(s.get("ref"))]
    assert not _li(memory, "bob-example")


def test_the_owners_page_is_never_matched_even_without_its_flag(client, monkeypatch):
    from api.services import owner_identity

    c, memory = client
    monkeypatch.setattr(owner_identity, "resolve_observer", lambda *_a, **_k: "bob-example")
    assert _post(c).status_code == 200
    assert not _li(memory, "bob-example")
    assert not [s for s in _page(memory, "bob-example").frontmatter.get("sources") or []
                if "linkedin" in str(s.get("ref"))]


def test_the_tail_never_matches_into_a_demo_bank(client, monkeypatch):
    c, memory = client
    assert _post(c, exported_on="2026-01-15").status_code == 200
    _entity(memory, "dana-two", type="person", name="Dana Other")
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "sleep"], check=True, capture_output=True)
    bank_index.invalidate()
    monkeypatch.setattr(demo_guard, "is_demo", lambda *_a, **_k: True)
    head = _git(memory, "rev-parse", "HEAD")
    asyncio.run(sleep_cycle._rematch_linkedin_safely(memory))
    assert _git(memory, "rev-parse", "HEAD") == head and not _li(memory, "dana-one")
