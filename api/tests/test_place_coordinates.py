"""A place's coordinates are stored once, by the app's own geocoder or the person's click (ruling 48 part 6).

The backend never geocodes; a private place (a home, an address, the person's own thing, a name carrying a person's)
is never placed automatically — only on the person's click.
"""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser, place_coordinates
from api.services.claims import Claim, write_claims
from api.tests.test_contributors import _commit, _init_repo


def _page(memory, entity_id, fm, claims=()):
    markdown_parser.write(memory / "entities" / f"{entity_id}.md", fm,
                          write_claims("## Summary\n\nA place.\n", list(claims)) if claims else "## Summary\n\nA place.\n")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    _init_repo(memory)
    _page(memory, "owner", {"name": "Bob Tester", "type": "person", "owner": True})
    _page(memory, "example-city", {"name": "Example City", "type": "location"})
    _page(memory, "example-park", {"name": "Example Park", "type": "location", "last_referenced": "2026-10-20"},
          [Claim(id="c1", text="Example Park is in Example City.", subject="example-park", predicate="located-in",
                 object="example-city", object_kind="node")])
    _page(memory, "my-apartment", {"name": "My Apartment", "type": "location"})
    _page(memory, "twelve-example-street", {"name": "12 Example Street", "type": "location"})
    _page(memory, "launch-ramp", {"name": "Launch Ramp", "type": "location", "lat": 40.4170, "lon": -3.7040})
    _page(memory, "far-harbour", {"name": "Far Harbour", "type": "location", "lat": 41.5, "lon": 2.1})
    _page(memory, "alpha-project", {"name": "Alpha Project", "type": "project"})
    _commit(memory, "seed")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return memory


def _log(memory, n=1):
    return subprocess.run(["git", "-C", str(memory), "log", f"-n{n}", "--format=%B"], capture_output=True,
                          text=True, check=True).stdout


@pytest.mark.parametrize("name, shaped", [("12 Example Street", True), ("Calle Ejemplo 4", True),
                                          ("Rua do Exemplo 12", True), ("Example Park", False),
                                          ("Route 66 Diner", False), ("Studio 54", False)])
def test_an_address_is_never_resolved_on_its_own(name, shaped):
    assert place_coordinates.address_shaped(name) is shaped


def test_who_may_be_placed_without_asking(bank):
    assert place_coordinates.geocode_verdict(bank, "example-park") == place_coordinates.Verdict(True, "public_place")
    assert place_coordinates.geocode_verdict(bank, "my-apartment").reason == "home"
    assert place_coordinates.geocode_verdict(bank, "twelve-example-street").reason == "address"
    assert place_coordinates.geocode_verdict(bank, "alpha-project").reason == "type"


def test_the_place_state_says_what_the_app_would_ask(bank):
    client = TestClient(main.app)
    park = client.get("/entities/example-park/place").json()
    assert park["coordinates"] is None
    assert park["geocode"] == {"allowed": True, "reason": "public_place", "query": "Example Park, Example City"}
    home = client.get("/entities/my-apartment/place").json()
    assert home["geocode"]["allowed"] is False and home["geocode"]["reason"] == "home"
    # The background pass lists public places only, never one already placed.
    ids = [r["entityId"] for r in client.get("/places/unplaced").json()]
    assert "example-park" in ids and "example-city" in ids
    assert not {"my-apartment", "twelve-example-street", "launch-ramp", "alpha-project"} & set(ids)


def test_the_geocoder_places_a_public_place_once_and_nearby_places_come_with_it(bank):
    client = TestClient(main.app)
    resp = client.put("/entities/example-park/coordinates", json={"lat": 40.4168, "lon": -3.7038, "by": "geocoder"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["coordinates"]["lat"] == 40.4168 and body["coordinates"]["by"] == "geocoder"
    assert [n["id"] for n in body["nearby"]] == ["launch-ramp"]   # Far Harbour is hundreds of km away
    fm = markdown_parser.parse(bank / "entities" / "example-park.md").frontmatter
    assert fm["lat"] == 40.4168 and fm["coordinates_by"] == "geocoder"
    message = _log(bank)
    assert "trigger: sync/geocoder" in message and "Cicada-Author: cicada" in message
    # The card serves it as the page's coordinates block, and the place drops out of the background pass.
    card = client.get("/entities/example-park").json()
    assert card["blocks"]["coordinates"]["by"] == "geocoder"
    assert "example-park" not in [r["entityId"] for r in client.get("/places/unplaced").json()]


def test_a_private_place_is_placed_only_on_the_persons_click(bank):
    client = TestClient(main.app)
    refused = client.put("/entities/my-apartment/coordinates", json={"lat": 40.0, "lon": -3.0, "by": "geocoder"})
    assert refused.status_code == 409 and "private" in refused.json()["detail"]
    assert "lat" not in markdown_parser.parse(bank / "entities" / "my-apartment.md").frontmatter
    ok = client.put("/entities/my-apartment/coordinates", json={"lat": 40.0, "lon": -3.0, "by": "person"})
    assert ok.status_code == 200 and ok.json()["coordinates"]["by"] == "person"
    assert "Cicada-Author: user" in _log(bank) and "trigger: user/place" in _log(bank)


def test_taking_a_pin_back_stops_the_geocoder(bank):
    client = TestClient(main.app)
    client.put("/entities/example-park/coordinates", json={"lat": 40.4168, "lon": -3.7038, "by": "geocoder"})
    gone = client.delete("/entities/example-park/coordinates")
    assert gone.status_code == 200 and gone.json()["coordinates"] is None
    assert gone.json()["geocode"]["allowed"] is False and gone.json()["geocode"]["reason"] == "taken_back"
    fm = markdown_parser.parse(bank / "entities" / "example-park.md").frontmatter
    assert "lat" not in fm and fm["coordinates_by"] == "none"
    again = client.put("/entities/example-park/coordinates", json={"lat": 1, "lon": 1, "by": "geocoder"})
    assert again.status_code == 409
    assert client.put("/entities/example-park/coordinates",
                      json={"lat": 1, "lon": 1, "by": "person"}).status_code == 200


def test_only_a_place_stores_coordinates_and_only_in_range(bank):
    client = TestClient(main.app)
    assert client.put("/entities/alpha-project/coordinates",
                      json={"lat": 1, "lon": 1, "by": "person"}).status_code == 422
    assert client.put("/entities/example-park/coordinates",
                      json={"lat": 95, "lon": 1, "by": "person"}).status_code == 422
    assert client.put("/entities/example-park/coordinates",
                      json={"lat": 1, "lon": 1, "by": "satellite"}).status_code == 422
    assert client.put("/entities/nowhere/coordinates", json={"lat": 1, "lon": 1, "by": "person"}).status_code == 404


@pytest.mark.parametrize("name, proper", [
    ("Jardim da Estrela", True), ("Praça do Comércio", True), ("Rua dos Douradores", True),
    ("Museo di Roma", True), ("Jardin du Luxembourg", True), ("Museum van Loon", True),
    ("Schloss von Example", True), ("Haus der Kunst", True), ("Musée le Example", True),
    ("Belém riverside", False), ("the lab at my school", False), ("da van der", False),
])
def test_name_particles_read_as_part_of_a_proper_name(name, proper):
    from api.services import org_sites

    assert org_sites.proper_name(name) is proper


def test_a_place_with_a_particle_is_public_and_a_person_with_one_never_is_on_its_own(bank):
    """Owner (via the coordinator, 2026-10-29): the particles widen the name rule for places; a person whose name
    carries one still never passes as public without the encyclopedia test — the local test answers at most "ask the
    encyclopedia", never public."""
    from api.services import web_context, web_settle

    _page(bank, "jardim-da-estrela", {"name": "Jardim da Estrela", "type": "location"})
    _page(bank, "ana-da-example", {"name": "Ana da Example", "type": "person",
                                   "description": "Founder of a robotics company and author of a book."})
    _page(bank, "rui-van-example", {"name": "Rui van Example", "type": "person"})
    _commit(bank, "particles")
    assert place_coordinates.geocode_verdict(bank, "jardim-da-estrela") == \
        place_coordinates.Verdict(True, "public_place")
    facts = web_settle.bank_facts(bank)
    for person in ("ana-da-example", "rui-van-example"):
        verdict = web_context.local_verdict(bank, web_context.load_page(bank, person), facts)
        assert verdict.public is not True, (person, verdict)
