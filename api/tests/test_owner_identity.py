"""G117 — the owner-observer resolution precedence (R1) and the entity page
it creates. No LLM, no network: pure file I/O over a tmp bank + a tmp
CICADA_HOME.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from api.services import markdown_parser, owner_identity, predicates


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _bank(tmp_path) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def test_resolve_prefers_env_over_everything(tmp_path):
    from types import SimpleNamespace

    owner_identity.save_owner({"name": "Bob Example", "entity_id": "bob-example"})
    settings = SimpleNamespace(observer_owner="carol-example")
    assert owner_identity.resolve_observer(_bank(tmp_path), settings) == "carol-example"


def test_resolve_prefers_owner_json_over_legacy_and_default(tmp_path):
    memory = _bank(tmp_path)
    (memory / "entities" / "rodrigo.md").write_text("---\nname: Rodrigo\n---\n\nBody.\n")
    owner_identity.save_owner({"name": "Bob Example", "entity_id": "bob-example"})
    assert owner_identity.resolve_observer(memory, None) == "bob-example"


def test_resolve_falls_back_to_legacy_rodrigo_only_if_the_page_exists(tmp_path):
    memory = _bank(tmp_path)
    assert owner_identity.resolve_observer(memory, None) == "owner"  # no owner.json, no legacy page
    (memory / "entities" / "rodrigo.md").write_text("---\nname: Rodrigo\n---\n\nBody.\n")
    assert owner_identity.resolve_observer(memory, None) == "rodrigo"


def test_owner_json_is_0600_and_holds_no_secret(tmp_path):
    owner_identity.save_owner({"name": "Bob Example", "handle": "@bob", "entity_id": "bob-example"})
    path = owner_identity.owner_json_path()
    assert oct(path.stat().st_mode)[-3:] == "600"
    data = owner_identity.load_owner()
    assert data == {"name": "Bob Example", "handle": "@bob", "entity_id": "bob-example"}
    assert "key" not in data and "token" not in data and "secret" not in data


def test_ensure_owner_entity_creates_an_evergreen_person_page(tmp_path):
    memory = _bank(tmp_path)
    entity_id, created = owner_identity.ensure_owner_entity(memory, "Bob Example")
    assert (entity_id, created) == ("bob-example", True)
    parsed = markdown_parser.parse(memory / "entities" / "bob-example.md")
    assert parsed.frontmatter["type"] == "person"
    assert parsed.frontmatter["owner"] is True
    assert parsed.frontmatter["decay_class"] == "evergreen"
    assert parsed.frontmatter["decay_rate"] == 0.0

    # Re-run: updates in place, never a second page, never re-created.
    entity_id2, created2 = owner_identity.ensure_owner_entity(memory, "Bob Example")
    assert (entity_id2, created2) == ("bob-example", False)
    assert len(list((memory / "entities").glob("*.md"))) == 1


def test_ensure_owner_entity_never_touches_a_page_under_a_different_slug(tmp_path):
    memory = _bank(tmp_path)
    (memory / "entities" / "rodrigo.md").write_text(
        "---\nname: Rodrigo\ntype: person\nstatus: active\nconfidence: 0.9\n---\n\nBody.\n"
    )
    entity_id, created = owner_identity.ensure_owner_entity(memory, "Bob Example")
    assert entity_id == "bob-example" and created is True
    # R3: the pre-existing page is untouched.
    old = markdown_parser.parse(memory / "entities" / "rodrigo.md")
    assert "owner" not in old.frontmatter
