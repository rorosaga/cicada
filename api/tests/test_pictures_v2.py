"""Pictures v2 (owner 2026-10-28, vision item 2): a public figure's encyclopedia portrait (C) and a project's mark (E).

C: only a person ruling 44's full public test called public — the local test, then exactly one human with an
encyclopedia article on Wikidata — gets the item's image (P18), asked by item and file name, never by name again; the
local test runs once more just before the ask; failing it later drops the match. E: a project draws its trusted site's
mark, else its repository owner's avatar only when an ORGANISATION owns the repository; never a personal account's,
never a proposal's. Fake HTTP only, placeholder names; nothing here asks a real service."""
from __future__ import annotations

import asyncio
import json
import struct
from datetime import date

import pytest

from api.services import (coverage_report, entity_picture, logo_service, markdown_parser, person_photo,
                          web_context)
from api.services.logo_service import FetchResult

TODAY = date(2026, 10, 28)
ITEM = "Q4200001"
FILE = "Jules Example 2024.jpg"


def png(side: int = 256) -> bytes:
    ihdr = struct.pack(">II", side, side) + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00" * 4 + b"\x00\x00\x00\x00IEND\xaeB`\x82"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "on")
    memory = tmp_path / "banks" / "b"
    (memory / "entities").mkdir(parents=True)
    from api.services import bank_index

    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def page(memory, entity_id: str, **fm):
    markdown_parser.write(memory / "entities" / f"{entity_id}.md", {"name": entity_id, **fm}, fm.pop("body", ""))


def public_figure(memory, entity_id="jules-example", item=ITEM):
    memo = web_context.load_memo(memory)
    memo["wd"][entity_id] = {"v": "encyclopedia_match", "at": TODAY.isoformat(), "item": item}
    web_context.save_memo(memory, memo)


class FakeHTTP:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    async def __call__(self, url):
        self.asked.append(url)
        for prefix, result in self.answers.items():
            if url.startswith(prefix):
                return result
        return FetchResult(status=404, body=b"", content_type="text/plain")


class FakeWikidata:
    def __init__(self, files=None):
        self.files, self.asked = files or {}, []

    async def __call__(self, params):
        self.asked.append(dict(params))
        if params.get("property") != "P18":
            return None
        value = self.files.get(params.get("entity"))
        rows = [{"mainsnak": {"datavalue": {"value": value}}, "rank": "normal"}] if value else []
        return {"claims": {"P18": rows} if rows else {}}


COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/"
UPLOAD = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Jules_Example_2024.jpg/256px-x.jpg"


def portrait_http(body=None):
    return FakeHTTP({COMMONS: FetchResult(status=302, body=b"", content_type="", location=UPLOAD),
                     UPLOAD: FetchResult(status=200, body=body or png(), content_type="image/png")})


# --- C: the public figure's portrait ----------------------------------------------------------------------------


def test_the_verdict_keeps_the_matched_item_and_a_private_page_loses_it(bank):
    v = web_context.Verdict(True, "encyclopedia_match", ITEM)
    assert v == web_context.Verdict(True, "encyclopedia_match"), "the item never changes what a verdict says"
    public_figure(bank)
    assert web_context.public_items(bank) == {"jules-example": ITEM}
    memo = web_context.load_memo(bank)
    memo["wd"]["tove-example"] = {"v": "ambiguous", "at": TODAY.isoformat()}
    memo["wd"]["kai-example"] = {"v": "encyclopedia_match", "at": TODAY.isoformat(), "item": "not-an-item"}
    web_context.save_memo(bank, memo)
    assert web_context.public_items(bank) == {"jules-example": ITEM}


def test_failing_the_local_test_later_drops_the_cached_match(bank, monkeypatch):
    public_figure(bank)
    memo = web_context.load_memo(bank)
    monkeypatch.setattr(web_context, "local_verdict", lambda *a, **k: web_context.Verdict(False, "personal_relation"))
    pg = web_context.Page.__new__(web_context.Page)
    pg.entity_id, pg.type = "jules-example", "person"
    v = asyncio.run(web_context.verdict(bank, pg, None, memo, get=None, today=TODAY))
    assert v.public is False and "jules-example" not in memo["wd"]


def test_the_item_is_an_identifier_only_for_a_person_and_never_the_owners_page(bank):
    person = {"type": "person", "name": "Jules Example"}
    assert person_photo.candidates(person, public=ITEM, proxy=False) == [person_photo.Candidate("wikidata", ITEM)]
    github = dict(person, sources=[{"ref": "https://github.com/jules-example", "kind": "url", "added_by": "user"}])
    assert [c.provider for c in person_photo.candidates(github, public=ITEM, proxy=False)] == ["github", "wikidata"]
    assert person_photo.candidates(dict(person, owner=True), owner={}, public=ITEM, proxy=False) == []
    assert person_photo.candidates({"type": "company", "name": "Acme"}, public=ITEM) == []
    assert person_photo.candidates(person, public="Jules Example", proxy=False) == [], "a name is never an item"
    page(bank, "jules-example", type="person")
    page(bank, "acme", type="company")
    public_figure(bank)
    public_figure(bank, "acme", "Q4200002")
    assert person_photo.public_item(bank, "jules-example", {"type": "person"}) == ITEM
    assert person_photo.public_item(bank, "acme", {"type": "company"}) is None
    assert person_photo.public_item(bank, "jules-example", {"type": "person", "owner": True}) is None


def test_a_public_figure_is_offered_the_portrait_rung_with_no_other_identifier(bank):
    page(bank, "jules-example", type="person", name="Jules Example")
    fm = markdown_parser.parse(bank / "entities" / "jules-example.md").frontmatter
    before, _ = entity_picture.resolve_page(bank, "jules-example", fm, "", page_mtime=0.0, cached=set(), missed={})
    assert before.source is None
    public_figure(bank)
    after, inputs = entity_picture.resolve_page(bank, "jules-example", fm, "", page_mtime=0.0, cached=set(),
                                                missed={})
    assert after.source == "profile" and inputs.profile and inputs.profile_key
    report = coverage_report.pictures(bank)
    assert report["by_type"]["person"]["rungs"] == {"profile:offered": 1}


def test_the_portrait_is_asked_by_item_and_file_and_stored(bank):
    page(bank, "jules-example", type="person", name="Jules Example")
    public_figure(bank)
    wd, http = FakeWikidata({ITEM: FILE}), portrait_http()
    path = asyncio.run(person_photo.ensure_photo(bank, "jules-example", fetcher=http, wikidata=wd,
                                                 still_public=lambda *_: True))
    assert path is not None and path.read_bytes() == png()
    assert wd.asked == [{"action": "wbgetclaims", "entity": ITEM, "property": "P18"}]
    assert http.asked[0] == COMMONS + "Jules_Example_2024.jpg?width=256" and http.asked[1] == UPLOAD
    sent = json.dumps(wd.asked) + " ".join(http.asked)
    assert "Jules Example" not in sent and "jules-example" not in sent, "the person's name is never sent again"
    again = asyncio.run(person_photo.ensure_photo(bank, "jules-example", fetcher=http, wikidata=wd,
                                                  still_public=lambda *_: True))
    assert again == path and len(http.asked) == 2, "fetched once, then served from the store"


def test_err_private_the_local_test_runs_again_before_anything_is_asked(bank):
    page(bank, "jules-example", type="person", name="Jules Example")
    public_figure(bank)
    wd, http = FakeWikidata({ITEM: FILE}), portrait_http()
    assert asyncio.run(person_photo.ensure_photo(bank, "jules-example", fetcher=http, wikidata=wd,
                                                 still_public=lambda *_: False)) is None
    assert wd.asked == [] and http.asked == []


def test_no_image_a_bad_file_name_or_a_hop_off_wikimedia_is_a_miss(bank):
    page(bank, "jules-example", type="person", name="Jules Example")
    public_figure(bank)
    for files, http in (({}, portrait_http()),
                        ({ITEM: "../../etc/passwd"}, portrait_http()),
                        ({ITEM: "https://elsewhere.example/a.jpg"}, portrait_http()),
                        ({ITEM: FILE}, FakeHTTP({COMMONS: FetchResult(status=302, body=b"", content_type="",
                                                                      location="https://elsewhere.example/a.png")}))):
        person_photo.write_meta("b", {})
        wd = FakeWikidata(files)
        assert asyncio.run(person_photo.ensure_photo(bank, "jules-example", fetcher=http, wikidata=wd,
                                                     still_public=lambda *_: True)) is None
        assert not [u for u in http.asked if "elsewhere.example" in u], "nothing off Wikimedia is ever asked"
        assert all(u.startswith(COMMONS) for u in http.asked)


def test_a_demo_bank_never_offers_or_asks_a_portrait(bank):
    from api.services import demo_guard

    demo_guard.manifest_path(bank).write_text(f"kind: {demo_guard.DEMO_KIND}\n", encoding="utf-8")
    assert demo_guard.is_demo(bank)
    page(bank, "jules-example", type="person", name="Jules Example")
    public_figure(bank)
    assert person_photo.public_item(bank, "jules-example", {"type": "person"}) is None
    wd, http = FakeWikidata({ITEM: FILE}), portrait_http()
    assert asyncio.run(person_photo.ensure_photo(bank, "jules-example", fetcher=http, wikidata=wd,
                                                 still_public=lambda *_: True)) is None
    assert wd.asked == [] and http.asked == []


def test_the_gates_close_the_portrait(bank, monkeypatch):
    page(bank, "jules-example", type="person", name="Jules Example")
    public_figure(bank)
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    wd, http = FakeWikidata({ITEM: FILE}), portrait_http()
    assert asyncio.run(person_photo.ensure_photo(bank, "jules-example", fetcher=http, wikidata=wd,
                                                 still_public=lambda *_: True)) is None
    assert wd.asked == [] and http.asked == []


# --- E: a project's mark ----------------------------------------------------------------------------------------

REPO = {"ref": "https://github.com/acme-org/alpha", "kind": "repo", "predicate": "repo", "added_by": "user"}


def test_a_projects_repository_owner_comes_only_from_a_trusted_repository():
    proj = {"type": "project", "name": "alpha-project"}
    assert logo_service.repo_owner(dict(proj, sources=[REPO])) == "acme-org"
    assert logo_service.repo_owner(dict(proj, sources=[dict(REPO, ref="https://github.com/acme-org/alpha.git/")])) \
        == "acme-org"
    proposed = dict(REPO, added_by="cicada", proposed=True, evidence={"page": True})
    assert logo_service.repo_owner(dict(proj, sources=[proposed])) is None, "a proposal is never drawn (D5)"
    assert logo_service.repo_owner(dict(proj, sources=[dict(REPO, added_by="cicada")])) is None, "unconfirmed"
    assert logo_service.repo_owner(dict(proj, sources=[dict(REPO, ref="https://github.com/acme-org")])) is None
    assert logo_service.repo_owner(dict(proj, sources=[dict(REPO, ref="https://github.com/orgs/x")])) is None
    assert logo_service.repo_owner(dict(proj, repos=["https://github.com/acme-org/alpha"])) == "acme-org"
    assert logo_service.repo_owner(dict(proj, repos=["alpha"])) is None, "a checkout's folder name is no repository"
    assert logo_service.repo_owner({"type": "person", "sources": [REPO]}) is None
    assert logo_service.target_for(dict(proj, sources=[REPO])) == "github-org:acme-org"
    site = {"ref": "https://alpha.example", "kind": "url", "predicate": "website", "added_by": "user"}
    assert logo_service.target_for(dict(proj, sources=[REPO, site])) == "alpha.example", "a trusted site wins"
    assert logo_service.draws_logo(dict(proj, sources=[REPO])) and not logo_service.draws_logo(proj)
    assert entity_picture.logo_eligible(dict(proj, sources=[site]))
    assert logo_service.target_for({"type": "person", "sources": [REPO, site]}) is None, "a person never gets a logo"


API = "https://api.github.com/users/acme-org"
AVATAR = "https://avatars.githubusercontent.com/u/9000001?v=4"


def github(kind="Organization", avatar=AVATAR, login="acme-org"):
    record = json.dumps({"login": login, "type": kind, "avatar_url": avatar}).encode()
    return FakeHTTP({API: FetchResult(status=200, body=record, content_type="application/json"),
                     "https://avatars.githubusercontent.com/": FetchResult(status=200, body=png(),
                                                                           content_type="image/png")})


def test_only_an_organisations_avatar_is_asked():
    http = github()
    body, ext, _ = asyncio.run(logo_service.fetch_org_avatar("acme-org", fetcher=http))
    assert body == png() and ext == "png" and http.asked == [API, AVATAR + "&s=256"]
    for kind, avatar, login in (("User", AVATAR, "acme-org"), ("Organization", "https://elsewhere.example/a.png",
                                                               "acme-org"), ("Organization", AVATAR, "other-org")):
        http = github(kind, avatar, login)
        assert asyncio.run(logo_service.fetch_org_avatar("acme-org", fetcher=http)) is None
        assert http.asked == [API], "a personal account's (or a stranger's) avatar is never asked"


def test_a_redirect_off_githubs_hosts_is_never_followed():
    http = FakeHTTP({API: FetchResult(status=302, body=b"", content_type="", location="https://elsewhere.example/")})
    assert asyncio.run(logo_service.fetch_org_avatar("acme-org", fetcher=http)) is None
    assert http.asked == [API]


def test_a_project_card_draws_and_caches_its_organisations_avatar(bank):
    page(bank, "alpha-project", type="project", sources=[REPO])
    http = github()
    path = asyncio.run(logo_service.ensure_logo(bank, "alpha-project", fetcher=http))
    assert path is not None and path.read_bytes() == png()
    assert logo_service.read_meta("b")["alpha-project"]["domain"] == "github-org:acme-org"
    fm = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter
    pic, _ = entity_picture.resolve_page(bank, "alpha-project", fm, "", page_mtime=0.0,
                                         cached=logo_service.cached_ids("b"), missed={})
    assert pic.source == "logo"
    # A personal account's repository: a miss, never an avatar.
    page(bank, "beta-project", type="project", sources=[dict(REPO, ref="https://github.com/bob-example/beta")])
    person = FakeHTTP({"https://api.github.com/users/bob-example": FetchResult(
        status=200, body=json.dumps({"login": "bob-example", "type": "User", "avatar_url": AVATAR}).encode(),
        content_type="application/json")})
    assert asyncio.run(logo_service.ensure_logo(bank, "beta-project", fetcher=person)) is None
    assert logo_service.read_meta("b")["beta-project"]["miss"] is True


def test_a_project_with_only_a_proposed_repository_says_so(bank):
    page(bank, "gamma-project", type="project",
         sources=[dict(REPO, added_by="cicada", proposed=True, evidence={"page": True})])
    page(bank, "delta-project", type="project")
    t = coverage_report.pictures(bank)["by_type"]["project"]
    assert t["none"] == {"no_site": 1, "repo_proposed": 1}
