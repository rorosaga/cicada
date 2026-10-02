"""A new bank starts with its owner's page (round 5, track A).

Created with the bank, "(you)" at display (the app renders it from `owner: true`), the
plain name kept as `name` so Stage 2 still matches the person's own name in a
conversation; adopted, never duplicated, when the name is said later; never the
demo's. Hermetic: a tmp memory root and a tmp CICADA_HOME (placeholder names only).
"""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, bank_registry, claim_pipeline, entity_resolver, markdown_parser, owner_identity


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _owner_pages(bank) -> list:
    out = []
    for f in sorted((bank / "entities").glob("*.md")):
        if markdown_parser.parse(f).frontmatter.get("owner") is True:
            out.append(f)
    return out


def _git(bank, *args) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout



# --- creation ------------------------------------------------------------------


def test_a_new_bank_starts_with_a_neutral_owner_page(tmp_path):
    slug = bank_registry.create_bank(tmp_path, "Research")
    bank = tmp_path / "banks" / slug
    (page,) = _owner_pages(bank)
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter
    assert page.stem == "owner"  # the id resolve_observer answers with for a fresh bank
    assert (fm["name"], fm["type"], fm["owner"], fm["decay_class"]) == ("Owner", "person", True, "evergreen")
    assert "(you)" not in fm["name"]  # rendered at display, never stored in the name
    assert "The main person this memory belongs to." in parsed.body
    assert owner_identity.resolve_observer(bank, None) == page.stem


def test_the_seed_page_is_committed_alone_as_cicada(tmp_path, monkeypatch):
    # A test machine may have no global git identity; an install's git does.
    for k, v in {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
                 "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}.items():
        monkeypatch.setenv(k, v)
    slug = bank_registry.create_bank(tmp_path, "Research")
    bank = tmp_path / "banks" / slug
    # The page is tracked (nothing of it left for a `git add -A` writer to smear under its own author)...
    assert "entities/owner.md" not in _git(bank, "status", "--porcelain")
    log = _git(bank, "log", "--format=%B---END---", "--", "entities/owner.md")
    # ...in one commit of its own, by the system: no model wrote it and no person's words are in it.
    assert log.count("---END---") == 1 and "Cicada-Author: cicada" in log and "entities/owner.md: created" in log
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["entities/owner.md"]


def test_a_name_saved_on_this_machine_names_the_page_and_no_other_bank_is_read(tmp_path):
    owner_identity.save_owner({"name": "Bob Example", "entity_id": "bob-example"})
    other = tmp_path / "banks" / "elsewhere"
    (other / "entities").mkdir(parents=True)
    markdown_parser.write(other / "entities" / "secret.md", {"name": "Secret", "type": "concept"}, "Body.")
    slug = bank_registry.create_bank(tmp_path, "Fresh")
    bank = tmp_path / "banks" / slug
    assert [p.stem for p in (bank / "entities").glob("*.md")] == ["bob-example"]  # only the person, no knowledge
    fm = markdown_parser.parse(bank / "entities" / "bob-example.md").frontmatter
    assert fm["name"] == "Bob Example" and fm["owner"] is True and "owner_placeholder" not in fm
    assert owner_identity.resolve_observer(bank, None) == "bob-example"


def test_it_is_idempotent_and_an_existing_owner_page_is_untouched(tmp_path):
    slug = bank_registry.create_bank(tmp_path, "Research")
    bank = tmp_path / "banks" / slug
    before = (bank / "entities" / "owner.md").read_text(encoding="utf-8")
    assert owner_identity.ensure_default_owner(bank) is None
    assert (bank / "entities" / "owner.md").read_text(encoding="utf-8") == before
    assert len(_owner_pages(bank)) == 1

    # A bank whose owner page is someone else's id and hand-written stays exactly as it is.
    mine = tmp_path / "mine"
    (mine / "entities").mkdir(parents=True)
    markdown_parser.write(mine / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "owner": True}, "Hand-written.")
    assert owner_identity.ensure_default_owner(mine) is None
    assert [p.stem for p in (mine / "entities").glob("*.md")] == ["bob-example"]
    assert "Hand-written." in (mine / "entities" / "bob-example.md").read_text(encoding="utf-8")


def test_a_page_already_at_the_owner_id_is_never_clobbered(tmp_path):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    markdown_parser.write(bank / "entities" / "owner.md", {"name": "Owner", "type": "concept"}, "Not a person.")
    assert owner_identity.ensure_default_owner(bank) is None
    assert "Not a person." in (bank / "entities" / "owner.md").read_text(encoding="utf-8")


def test_the_demo_bank_is_excluded(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    client = TestClient(main.app)
    assert client.post("/banks/demo").status_code == 200
    demo = root / "banks" / "demo"
    assert not (demo / "entities" / "owner.md").exists()
    assert len(_owner_pages(demo)) == 1  # the demo's own owner, not a second one
    # ...while a bank made through the route gets one.
    assert client.post("/banks", json={"name": "Mine"}).status_code == 200
    assert [p.stem for p in _owner_pages(root / "banks" / "mine")] == ["owner"]


def test_leaving_the_demo_into_a_new_memory_seeds_the_owner_too(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    slug = bank_registry.create_bank(root, bank_registry.NEW_MEMORY_NAME)
    assert [p.stem for p in _owner_pages(root / "banks" / slug)] == ["owner"]


def test_the_first_boot_default_bank_gets_the_owner_page_once_and_only_when_brand_new(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    with TestClient(main.app):  # runs the lifespan: the default bank never goes through create_bank
        pass
    assert [p.stem for p in _owner_pages(root)] == ["owner"]
    # A second boot changes nothing (the page is there, and so is never written twice).
    before = (root / "entities" / "owner.md").read_text()
    with TestClient(main.app):
        pass
    assert (root / "entities" / "owner.md").read_text() == before


def test_a_bank_with_anything_in_it_is_never_seeded_at_boot(tmp_path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "alpha-project.md").write_text("---\ntype: project\nname: Alpha\n---\nbody\n")
    assert owner_identity.seed_owner_if_brand_new(tmp_path) is None
    assert _owner_pages(tmp_path) == []
    other = tmp_path / "other"
    (other / "episodes").mkdir(parents=True)
    (other / "episodes" / "ep_2026-01-01_001.md").write_text("---\nid: ep_2026-01-01_001\n---\nhi\n")
    assert owner_identity.seed_owner_if_brand_new(other) is None
    assert not (other / "entities" / "owner.md").exists()


# --- resolution ----------------------------------------------------------------


def test_saying_the_name_later_adopts_the_page_instead_of_writing_a_second_one(tmp_path):
    slug = bank_registry.create_bank(tmp_path, "Research")
    bank = tmp_path / "banks" / slug
    path = bank / "entities" / "owner.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body + "\n\nA belief the page already holds.")

    entity_id, created = owner_identity.ensure_owner_entity(bank, "Bob Example")

    assert (entity_id, created) == ("owner", False)
    (page,) = _owner_pages(bank)
    fm = markdown_parser.parse(page).frontmatter
    assert page.stem == "owner" and fm["name"] == "Bob Example" and "owner_placeholder" not in fm
    assert "A belief the page already holds." in page.read_text(encoding="utf-8")
    assert [p.stem for p in (bank / "entities").glob("*.md")] == ["owner"]  # no bob-example.md beside it


def test_the_plain_name_still_resolves_in_stage_2_and_the_owner_words_reach_the_page(tmp_path):
    owner_identity.save_owner({"name": "Bob Example", "entity_id": "bob-example"})
    slug = bank_registry.create_bank(tmp_path, "Fresh")
    bank = tmp_path / "banks" / slug
    fm = markdown_parser.parse(bank / "entities" / "bob-example.md").frontmatter
    # Stage 2 keys an existing page by its `name`, lower-cased; a conversation's "Bob Example" lands on it.
    name_to_id = {str(fm["name"]).lower(): "bob-example"}
    assert entity_resolver.endpoint_id("Bob Example", name_to_id) == "bob-example"
    # The first person's words ("me", "the user") key to the owner page once it exists.
    existing = [{"id": "bob-example", "frontmatter": fm}]
    owner_id = claim_pipeline._owner_page_id(existing, bank, None)
    assert owner_id == "bob-example"
    resolve = claim_pipeline.subject_resolver(name_to_id, owner_id)
    assert resolve("the user") == "bob-example" and resolve("Bob Example") == "bob-example"
