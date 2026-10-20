"""Looks live on the page of the thing they show (owner rulings 2026-10-20).

"The Looks page might be better not to have; this should be ingrained in the markdown of a specific thing, and we can
filter looks inside the entities page." A look record stays one file in ``design/`` (one writer, ``design_refs``); its
``entity:`` is the page it shows, and that page's markdown carries a ``## Looks`` section the writer renders. These
tests hold: the section's shape and its surgical write, the deterministic subject rule (never a page invented), the
moves between pages, Sleep's writers carrying the section, a merge moving looks, the one-time migration (idempotent,
one ``cicada`` commit), the routes, the MCP tool's ``subject`` and the explore ask's subject.

Synthetic only: made-up pages drawn by ``demo_pictures.website``, example.com links, placeholder names."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import pytest

from _synthetic_bank import _bank, _entity
from api.services import (claims, demo_pictures, design_index, design_refs, entity_body, entity_merge,
                          explore_queue, looks_attach, markdown_parser, media_ingestor)

NOW = datetime(2026, 10, 20, 9, 0, 0, tzinfo=timezone.utc)
DARK = demo_pictures.website((20, 22, 28), (29, 32, 41), (226, 230, 240), (124, 156, 255))
LIGHT = demo_pictures.website((255, 255, 255), (242, 244, 255), (17, 24, 39), (59, 91, 253), dense=True)
WARM = demo_pictures.website((246, 241, 231), (237, 229, 214), (43, 38, 32), (200, 85, 61), rounded=2)
LOOK = ([{"hex": "#14161c", "share": 0.7}], ["dark", "muted"])
SITE = [{"ref": "https://dashboard.example.com", "kind": "url", "predicate": "website", "added_by": "user"}]


@pytest.fixture
def bank(tmp_path):
    memory = _bank(tmp_path, git=False)
    _entity(memory, "dash-tool", type="tool", sources=SITE,
            body="## Summary\nDash Tool is a synthetic dashboard.\n\n## Key Facts\n- It has panels.\n\n"
                 "## Open Questions\n- Which plan?\n")
    return memory


def _add(bank, image=DARK, **kw):
    kw.setdefault("url", "https://dashboard.example.com/overview")
    kw.setdefault("note", "Calm dark panels.")
    kw.setdefault("now", NOW)
    kw.setdefault("look", LOOK)
    return design_refs.add_ref(bank, image=image, **kw)


def _body(bank, eid):
    return markdown_parser.parse(bank / "entities" / f"{eid}.md", ledger=False).body


def _git(bank, *args) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], capture_output=True, text=True, check=True).stdout


# --------------------------------------------------------------------------- the section


def test_a_look_on_a_page_is_a_looks_section_linking_the_record_and_its_screenshot(bank):
    out = _add(bank, entity="alpha-project", title="Quiet [dark] dashboard")
    ref = out["ref"]
    assert out["attached"] == "given" and "entities/alpha-project.md" in out["paths"]
    sections = entity_body.parse_sections(_body(bank, "alpha-project"))
    assert sections["Looks"] == (f"- [Quiet dark dashboard](../design/{ref.id}.md) · dashboard.example.com · "
                                 f"2026-10-20\n  ![Quiet dark dashboard](../assets/design/{ref.id}.png)")
    # The record still holds everything the look is; the page only renders it.
    assert design_refs.get_ref(bank, ref.id).entity == "alpha-project"


def test_the_section_is_a_surgical_edit_in_its_canonical_place(bank):
    page = bank / "entities" / "dash-tool.md"
    fm = markdown_parser.parse(page).frontmatter
    fence = claims.write_claims("", [claims.Claim(id="c1", text="Dash Tool uses panels.", subject="dash-tool",
                                                  predicate="uses", object="panels", valid_from="2026-09-01",
                                                  recorded_at="2026-09-01")])
    markdown_parser.write(page, fm, _body(bank, "dash-tool").rstrip() + "\n\n" + fence)
    before = _body(bank, "dash-tool")
    _add(bank, entity="dash-tool")
    after = _body(bank, "dash-tool")
    heads = [h for h in after.splitlines() if h.startswith("## ")]
    assert heads == ["## Summary", "## Key Facts", "## Looks", "## Open Questions"]
    assert after[after.index("```claims"):] == before[before.index("```claims"):], "the fence is put back as it was"
    assert after.replace(after[after.index("## Looks"):after.index("## Open Questions")], "") == before
    # Newest first, one bullet each; removing the last one takes the section away again.
    second = _add(bank, image=LIGHT, entity="dash-tool", now=NOW.replace(day=21))["ref"]
    looks = entity_body.parse_sections(_body(bank, "dash-tool"))["Looks"]
    assert looks.index(second.id) < looks.index("2026-10-20-dashboard-example-com")
    for ref in design_refs.list_refs(bank):
        design_refs.remove_ref(bank, ref.id)
    assert "## Looks" not in _body(bank, "dash-tool")
    assert _body(bank, "dash-tool") == before


def test_looks_is_a_canonical_record_section_sleep_carries_and_never_reads_as_a_hand_edit(bank):
    from api.services import entity_article

    _add(bank, entity="dash-tool")
    body = claims.strip_claims_block(_body(bank, "dash-tool"))
    sections = entity_body.parse_sections(body)
    assert not entity_body.has_human_prose({}, sections), "the section must not freeze the page as hand-edited"
    assert entity_body.parse_sections(entity_body.render_sections(sections))["Looks"] == sections["Looks"]
    merged = entity_body.merge_sections_fallback(sections, {"key_facts": ["A new fact."], "summary": ""})
    assert merged["Looks"] == sections["Looks"]
    record = entity_article.record_sections(body, "tool", {"key_facts": ["Another fact."]})
    assert record["Looks"] == sections["Looks"], "the article writer's record keeps it"
    assert "Looks" in entity_body.summarize_for_recall(body, max_chars=10_000)


# --------------------------------------------------------------------------- the subject rule


def test_a_look_goes_on_the_one_page_whose_trusted_site_it_is(bank):
    out = _add(bank)
    assert out["attached"] == "site" and out["ref"].entity == "dash-tool"
    assert "## Looks" in _body(bank, "dash-tool")


def test_an_untrusted_site_or_two_claimants_attach_nothing(bank):
    _entity(bank, "dash-copy", type="company", sources=SITE)
    ref = _add(bank)["ref"]
    assert ref.entity is None
    assert design_refs.subject_for(bank, "https://dashboard.example.com")[1] == "ambiguous"
    proposed = [{**SITE[0], "added_by": "agent"}]
    _entity(bank, "dash-copy", type="company", sources=proposed)
    assert design_refs.subject_for(bank, "https://www.dashboard.example.com/x") == ("dash-tool", "site")


def test_else_the_saved_links_own_page_and_never_a_page_invented(bank):
    _entity(bank, "saved-journal", type="media")
    url = "https://journal.example.com/essays/slow"
    media_ingestor.save_url_index(bank, {media_ingestor.url_hash(url): {"url": url,
                                                                        "media_entity_id": "saved-journal"}})
    assert _add(bank, image=WARM, url=url)["ref"].entity == "saved-journal"
    before = sorted(p.name for p in (bank / "entities").iterdir())
    ref = _add(bank, image=LIGHT, url="https://nowhere.example.org/")["ref"]
    assert ref.entity is None and sorted(p.name for p in (bank / "entities").iterdir()) == before
    assert _add(bank, image=DARK, url=None)["ref"].entity is None


def test_a_look_moves_between_pages_and_an_agent_moves_only_its_own(bank):
    ref = _add(bank, entity="alpha-project")["ref"]
    out = design_refs.attach(bank, ref.id, "dash-tool")
    assert out["action"] == "attached"
    assert set(out["paths"]) == {ref.path, "entities/alpha-project.md", "entities/dash-tool.md"}
    assert "## Looks" not in _body(bank, "alpha-project") and ref.id in _body(bank, "dash-tool")
    assert design_refs.attach(bank, ref.id, "no-such-page")["action"] == "error"
    assert design_refs.attach(bank, ref.id, "alpha-project", author="claude-code")["action"] == "error"
    assert design_refs.attach(bank, ref.id, None)["action"] == "detached"
    assert "## Looks" not in _body(bank, "dash-tool") and design_refs.get_ref(bank, ref.id).entity is None
    # The record's body — the note — is never rewritten by a move.
    assert design_refs.get_ref(bank, ref.id).note == "Calm dark panels."


def test_a_merge_moves_the_losers_looks_to_the_winner(bank):
    ref = _add(bank, entity="beta-project")["ref"]
    footprint = entity_merge.merge_footprint(bank, "beta-project", "alpha-project")
    assert ref.path in footprint
    out = entity_merge.merge_entities(bank, "beta-project", "alpha-project")
    assert ref.path in out["paths"] and design_refs.get_ref(bank, ref.id).entity == "alpha-project"
    assert ref.id in entity_body.parse_sections(_body(bank, "alpha-project"))["Looks"]


# --------------------------------------------------------------------------- the migration


def _legacy(bank, image, url, entity=None):
    """A look saved before 2026-10-20: a record whose page (if any) has no section."""
    ref = _add(bank, image=image, url=url, attach_auto=False)["ref"]
    if entity:
        design_refs._set_entity(bank, ref, entity)
    return ref


def test_the_migration_places_what_it_can_lists_the_rest_and_runs_once(tmp_path):
    from api.scripts import attach_looks

    bank = _bank(tmp_path)
    _entity(bank, "dash-tool", type="tool", sources=SITE)
    subprocess.run(["git", "-C", str(bank), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(bank), "commit", "-qm", "seed"], check=True)
    on_site = _legacy(bank, DARK, "https://dashboard.example.com/a")
    named = _legacy(bank, LIGHT, "https://other.example.net/", entity="alpha-project")
    gone = _legacy(bank, WARM, "https://studio.example.org/", entity="no-longer-here")
    subprocess.run(["git", "-C", str(bank), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(bank), "commit", "-qm", "looks"], check=True)
    dry = looks_attach.survey(bank)
    assert dry.counts() | {} == {"looks": 3, "on_page": 1, "by_site": 1, "by_link": 0, "unattached": 1,
                                 "ambiguous": 0, "page_gone": 1, "pages_to_write": 2, "written": 0,
                                 "committed": False}
    assert dry.listing()["unattached"] == [{"id": gone.id, "site": "studio.example.org", "why": "none"}]
    assert design_refs.get_ref(bank, on_site.id).entity is None, "a dry run writes nothing"
    result = looks_attach.apply(bank, sleep_running=lambda: False)
    assert result.committed and result.written == 3
    head = _git(bank, "log", "-1", "--format=%B")
    assert head.startswith("Looks attached to their pages") and "Cicada-Author: cicada" in head
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        [on_site.path, "entities/alpha-project.md", "entities/dash-tool.md"])
    assert named.id in _body(bank, "alpha-project") and on_site.id in _body(bank, "dash-tool")
    again = looks_attach.survey(bank)
    assert again.pages_to_write == 0 and not again._moves
    assert looks_attach.apply(bank, sleep_running=lambda: False).written == 0
    assert attach_looks.main(["--bank", str(bank)]) == 0
    with pytest.raises(looks_attach.SleepRunning):
        looks_attach.apply(bank, sleep_running=lambda: True)


# --------------------------------------------------------------------------- the routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _bank(tmp_path)
    _entity(memory, "dash-tool", type="tool", sources=SITE)
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    monkeypatch.setattr(design_index, "default_embedders", lambda environ=None: None)
    monkeypatch.setattr(design_index, "refresh_in_background", lambda mp, **kw: False)
    with TestClient(main.app) as c:
        yield c, memory
    config.get_settings.cache_clear()


def test_an_image_dropped_on_a_page_lands_there_and_commits_with_the_page(client):
    c, bank = client
    r = c.post("/design", files={"image": ("shot.png", WARM, "image/png")},
               data={"entity": "alpha-project", "via": "drop"})
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["entity"] == "alpha-project"
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        [f"assets/design/{ref['id']}.png", f"design/{ref['id']}.md", "entities/alpha-project.md"])
    assert "entities/alpha-project.md: updated" in _git(bank, "log", "-1", "--format=%B")
    assert c.post("/design", files={"image": ("s.png", DARK, "image/png")},
                  data={"entity": "no-such-page"}).status_code == 404


def test_the_person_moves_a_look_and_a_page_gone_reads_as_unattached(client):
    c, bank = client
    ref = c.post("/design", files={"image": ("shot.png", DARK, "image/png")},
                 data={"url": "https://dashboard.example.com/"}).json()
    assert ref["entity"] == "dash-tool"
    r = c.put(f"/design/{ref['id']}/entity", json={"entity": "alpha-project"})
    assert r.status_code == 200 and r.json()["entity"] == "alpha-project"
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        [f"design/{ref['id']}.md", "entities/alpha-project.md", "entities/dash-tool.md"])
    assert c.put(f"/design/{ref['id']}/entity", json={"entity": "nope"}).status_code == 422
    assert c.put("/design/2026-01-01-none/entity", json={"entity": None}).status_code == 404
    (bank / "entities" / "alpha-project.md").unlink()
    assert c.get("/design").json()["refs"][0]["entity"] is None


def test_similar_looks_leave_the_look_itself_out(client):
    c, bank = client
    a = c.post("/design", files={"image": ("a.png", DARK, "image/png")}).json()
    design_refs.add_ref(bank, image=LIGHT, look=([], ["dark", "vivid"]), now=NOW)
    design_refs.add_ref(bank, image=WARM, look=([], ["light", "warm"]), now=NOW)
    r = c.get(f"/design/{a['id']}/similar")
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["results"]]
    assert a["id"] not in ids and ids and "model" in r.json()["missing"]
    assert c.get("/design/2026-01-01-none/similar").status_code == 404


# --------------------------------------------------------------------------- the agent's door and the explore ask


@pytest.fixture
def server(tmp_path, monkeypatch):
    from _stdio_server import stdio_server

    srv = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_2026-10-20_c0ffee00", "claude-code", None))
    monkeypatch.setattr(design_index, "default_embedders", lambda environ=None: None)
    return srv, memory


def test_an_agent_names_the_page_a_look_shows(server, tmp_path):
    srv, bank = server
    shot = tmp_path / "shots" / "page.png"
    shot.parent.mkdir()
    shot.write_bytes(DARK)
    out = srv.handle_tool("cicada_save_design", {"image_path": str(shot), "url": "https://studio.example.org",
                                                  "note": "They like the type.", "subject": "alpha-project"})
    assert "on the page `alpha-project`" in out
    assert "## Looks" in _body(bank, "alpha-project")
    head = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: claude-code" in head and "entities/alpha-project.md: updated" in head
    shot.write_bytes(LIGHT)
    refused = srv.handle_tool("cicada_save_design", {"image_path": str(shot), "note": "x", "subject": "nope"})
    assert refused.startswith("Not saved") and len(design_refs.list_refs(bank)) == 1
    found = srv.handle_tool("cicada_design_search", {})
    assert "on page alpha-project" in found


def test_a_save_its_look_ask_keeps_the_page_it_came_from(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    bank = _bank(tmp_path, git=False)
    out = explore_queue.ask(bank, [{"key": "a" * 12, "site": "dashboard.example.com", "subject": "alpha-project"}],
                            asked="look", started_by={"kind": "person"})
    assert out["queued"] == 1
    row = next(r for r in explore_queue.view(bank)["items"] if r["key"] == "a" * 12)
    assert row.get("subject") == "alpha-project"
    explore_queue.ask(bank, [{"key": "b" * 12, "site": "other.example.com", "subject": "../etc"}],
                      asked="look", started_by={"kind": "person"})
    row = next(r for r in explore_queue.view(bank)["items"] if r["key"] == "b" * 12)
    assert "subject" not in row, "only a page id is kept, never a path"
    assert json.dumps(row)
