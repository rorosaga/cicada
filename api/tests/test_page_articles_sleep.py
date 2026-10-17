"""The article writer in Sleep (G194, owner 2026-10-09): Stage 3's one call, Stage 5's page, the rails."""
import asyncio
import json
from types import SimpleNamespace

from api.config import Settings
from api.services import conflict_resolver as cr, entity_article, entity_body as body, markdown_parser as md
from api.services import section_provenance as sp
from api.services.claims import Claim, Evidence, parse_claims, write_claims

PAGE = ("## Summary\nalpha-project is a notes app.\n\n## Key Facts\n- Uses SQLite for sync.\n\n"
        "## History\n- 2026-01-10: First prototype.")
ARTICLE_MARK = "You are writing a page of a personal wiki"


def _answer(prompt: str) -> dict:
    data = json.loads(prompt.partition("\nDATA:\n")[2])
    ids = {i["kind"]: [] for i in data["INPUT"]}
    for item in data["INPUT"]:
        ids[item["kind"]].append(item["id"])
    return {
        "summary": {"text": "alpha-project is a notes app bob-example builds, first prototyped in January 2026.",
                    "from": ids.get("earlier", []) + ids.get("history", [])},
        "sections": [{"title": "How it works", "paragraphs": [
            {"text": "It syncs through [[SQLite]] and runs on a laptop.", "from": ids.get("fact", [])}]}],
    }


def run(tmp_path, monkeypatch, *, fields, articles=True, synthesis=False, page=PAGE, fm=None, reply=None,
        sources=("ep_2026-03-02_001",), max_chars=60000, extra_pages=(), min_material=4):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    settings = Settings(_env_file=None, page_articles_enabled=articles, summary_synthesis_enabled=synthesis,
                        page_article_max_input_chars=max_chars, page_article_min_material=min_material)
    calls = []

    async def fake(**kwargs):
        text = "\n\n".join(m["content"] for m in kwargs["messages"])
        calls.append(text)
        if ARTICLE_MARK in text:
            content = json.dumps(reply(text) if callable(reply) else reply) if reply is not None else json.dumps(
                _answer(text))
        elif "checking whether two descriptions" in text:
            content = json.dumps({"has_unresolvable_contradiction": False})
        elif "SECTION-AWARE ORIENTATION" in text:
            content = json.dumps({"summary": "A notes application."})
        else:
            content = "## Summary\nLegacy prose."
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(cr.litellm, "acompletion", fake)
    frontmatter = {"name": "alpha-project", "type": "project", "source_episodes": ["ep_2026-01-10_001"],
                   "last_referenced": "2026-01-10", **(fm or {})}
    (tmp_path / "entities").mkdir(parents=True, exist_ok=True)
    md.write(tmp_path / "entities/alpha-project.md", frontmatter, page)
    existing = [{"id": "alpha-project", "frontmatter": frontmatter, "body": page},
                {"id": "sqlite", "frontmatter": {"name": "SQLite", "type": "tool"}, "body": "## Summary\nA database."},
                *extra_pages]
    change = {"id": "alpha-project", "action": "update", "entity": fields, "source_episodes": list(sources),
              "source_episode_timestamps": ["2026-03-02T10:00:00+00:00"]}
    changes = asyncio.run(cr.resolve_and_prune([change], existing, settings, decay=False, now=None))
    cr.apply_changes([c for c in changes if c["id"] == "alpha-project"], tmp_path)
    written = md.parse(tmp_path / "entities/alpha-project.md")
    return changes[0], calls, written


def _fields(**over):
    fields = {"key_facts": ["Runs on a laptop."], "history_entries": [{"date": "2026-03-02", "event": "Beta."}]}
    sp.attach(fields, "ep_2026-03-02_001", "user: synthetic")
    fields.update(over)
    return fields


def test_the_setting_is_off_by_default():
    assert Settings(_env_file=None).page_articles_enabled is False


def test_a_two_conversation_page_gets_one_article_call_and_keeps_every_record_item(tmp_path, monkeypatch):
    change, calls, page = run(tmp_path, monkeypatch, fields=_fields())
    assert sum(ARTICLE_MARK in c for c in calls) == 1 and len(calls) == 1   # facts-only: no contradiction call
    sections = body.parse_sections(page.body)
    assert sections["Summary"].startswith("alpha-project is a notes app bob-example builds")
    assert sections["Article"] == "### How it works\n\nIt syncs through [[SQLite]] and runs on a laptop."
    assert body._bullet_lines(sections["Key Facts"])[:2] == ["Uses SQLite for sync.", "Runs on a laptop."]
    assert body._bullet_lines(sections["History"]) == ["2026-01-10: First prototype.", "2026-03-02: Beta."]
    assert entity_article.stamped(page.frontmatter, sections)
    assert not body.has_human_prose(page.frontmatter, sections)
    # The paragraph is one click from the conversation its cited facts came from (G118).
    matched = sp.matched(page.frontmatter, page.body)
    (guard, rows), = matched["article"].values()
    assert {ev.episode for ev in rows} == {"ep_2026-03-02_001"}


def test_old_summary_the_article_does_not_carry_is_kept_as_a_key_fact(tmp_path, monkeypatch):
    def reply(text):
        answer = _answer(text)
        answer["summary"]["from"] = [i for i in answer["summary"]["from"] if i.startswith("h")]
        return answer

    _, _, page = run(tmp_path, monkeypatch, fields=_fields(), reply=reply)
    assert "alpha-project is a notes app." in body._bullet_lines(body.parse_sections(page.body)["Key Facts"])


def test_a_summary_update_still_gets_its_contradiction_check(tmp_path, monkeypatch):
    _, calls, _ = run(tmp_path, monkeypatch, fields=_fields(summary="alpha-project moved to a beta in March.",
                                                            description="alpha-project moved to a beta in March."))
    assert sum(ARTICLE_MARK in c for c in calls) == 1
    assert sum("checking whether two descriptions" in c for c in calls) == 1


def test_a_one_conversation_stub_stays_a_stub_with_no_write_call(tmp_path, monkeypatch):
    # Two facts and one dated line: less than the writer's floor (`MIN_MATERIAL`), so an article would only restate.
    _, calls, page = run(tmp_path, monkeypatch, fields=_fields(history_entries=[]), sources=("ep_2026-01-10_001",),
                         fm={"source_episodes": []})
    assert calls == []
    sections = body.parse_sections(page.body)
    assert "Article" not in sections and "- Runs on a laptop." in sections["Key Facts"]
    assert "article" not in page.frontmatter


def test_a_one_conversation_page_with_material_gets_its_article(tmp_path, monkeypatch):
    # Owner 2026-10-17, "uncap what the agents can write to": one conversation is no cap when the record holds
    # enough to connect (two facts, two dated lines).
    _, calls, page = run(tmp_path, monkeypatch, fields=_fields(), sources=("ep_2026-01-10_001",),
                         fm={"source_episodes": []})
    assert sum(ARTICLE_MARK in c for c in calls) == 1 and len(calls) == 1
    sections = body.parse_sections(page.body)
    assert sections["Article"] and entity_article.stamped(page.frontmatter, sections)
    assert body._bullet_lines(sections["Key Facts"])[:2] == ["Uses SQLite for sync.", "Runs on a laptop."]


def test_the_material_floor_is_the_persons_setting(tmp_path, monkeypatch):
    _, calls, page = run(tmp_path, monkeypatch, fields=_fields(), sources=("ep_2026-01-10_001",),
                         fm={"source_episodes": []}, min_material=10)
    assert calls == [] and "article" not in page.frontmatter


def test_a_human_page_gets_no_call_and_keeps_its_prose(tmp_path, monkeypatch):
    _, calls, page = run(tmp_path, monkeypatch, fields=_fields(), fm={"human_edited": True})
    assert calls == [] and body.parse_sections(page.body)["Summary"] == "alpha-project is a notes app."


def test_an_invalid_article_keeps_the_deterministic_merge(tmp_path, monkeypatch):
    _, calls, page = run(tmp_path, monkeypatch, fields=_fields(),
                         reply={"summary": {"text": "It is now a notes app.", "from": ["f0"]}})
    assert len(calls) == 1
    sections = body.parse_sections(page.body)
    assert "Article" not in sections and sections["Summary"] == "alpha-project is a notes app."
    assert "- Runs on a laptop." in sections["Key Facts"] and "article" not in page.frontmatter


def test_over_budget_takes_todays_path(tmp_path, monkeypatch):
    _, calls, page = run(tmp_path, monkeypatch, fields=_fields(), synthesis=True, max_chars=500)
    assert calls and not any(ARTICLE_MARK in c for c in calls)
    assert any("SECTION-AWARE ORIENTATION" in c for c in calls)


def test_the_claims_fence_survives_the_article(tmp_path, monkeypatch):
    claim = Claim(id="clm_1", text="alpha-project uses SQLite.", subject="alpha-project", predicate="uses",
                  object="sqlite", valid_from="2026-01-10",
                  evidence=[Evidence(episode="ep_2026-01-10_001", hash="0123456789ab", start=0, end=4, kind="user")])
    _, calls, page = run(tmp_path, monkeypatch, fields=_fields(), page=write_claims(PAGE, [claim]))
    assert [c.id for c in parse_claims(page.body)] == ["clm_1"]
    assert '"kind": "claim"' in calls[0].replace(" ", "").replace('"kind":"claim"', '"kind": "claim"')


def _article_page(tmp_path, monkeypatch):
    _, _, page = run(tmp_path, monkeypatch, fields=_fields())
    return page


def test_an_article_page_is_rewritten_when_it_gains_material(tmp_path, monkeypatch):
    first = _article_page(tmp_path, monkeypatch)
    fields = _fields(key_facts=["Has 40 users."])
    second_change, calls, page = run(tmp_path, monkeypatch, fields=fields, page=first.body, fm=first.frontmatter,
                                     sources=("ep_2026-04-01_001",))
    assert sum(ARTICLE_MARK in c for c in calls) == 1
    assert "Has 40 users." in calls[0]
    # The earlier article is an input to rewrite, not text to keep.
    assert "It syncs through [[SQLite]] and runs on a laptop." in calls[0]
    assert "- Has 40 users." in body.parse_sections(page.body)["Key Facts"]


def test_an_edited_article_is_the_persons_no_call_and_kept(tmp_path, monkeypatch):
    first = _article_page(tmp_path, monkeypatch)
    edited = first.body.replace("runs on a laptop", "runs on an old laptop")
    _, calls, page = run(tmp_path, monkeypatch, fields=_fields(key_facts=["Has 40 users."]), page=edited,
                         fm=first.frontmatter, sources=("ep_2026-04-01_001",))
    assert calls == []
    sections = body.parse_sections(page.body)
    assert "runs on an old laptop" in sections["Article"] and "- Has 40 users." in sections["Key Facts"]


def test_an_article_page_is_never_handed_to_the_summary_rewrite(tmp_path, monkeypatch):
    first = _article_page(tmp_path, monkeypatch)
    for synthesis in (True, False):
        _, calls, page = run(tmp_path / str(synthesis), monkeypatch, articles=False, synthesis=synthesis,
                             fields=_fields(key_facts=["Has 40 users."], summary="A different orientation."),
                             page=first.body, fm=first.frontmatter, sources=("ep_2026-04-01_001",))
        assert not any("SECTION-AWARE" in c or "updating an entity page" in c for c in calls)
        sections = body.parse_sections(page.body)
        assert sections["Summary"] == body.parse_sections(first.body)["Summary"]
        assert entity_article.stamped(page.frontmatter, sections)
        assert "- A different orientation." in sections["Key Facts"]


def test_a_renamed_link_inside_an_article_keeps_the_stamp(tmp_path, monkeypatch):
    from api.services import entity_merge

    first = _article_page(tmp_path, monkeypatch)
    md.write(tmp_path / "entities/sqlite.md", {"name": "SQLite", "type": "tool"}, "## Summary\nA database.")
    entity_merge.repoint_references(tmp_path, "sqlite", "SQLite", "sqlite-3", "SQLite 3")
    page = md.parse(tmp_path / "entities/alpha-project.md")
    sections = body.parse_sections(page.body)
    assert "[[SQLite 3]]" in sections["Article"] and first.body != page.body
    assert entity_article.stamped(page.frontmatter, sections)


def _create(tmp_path, monkeypatch, entity, *, articles=True):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    settings = Settings(_env_file=None, page_articles_enabled=articles)
    calls = []

    async def fake(**kwargs):
        text = "\n\n".join(m["content"] for m in kwargs["messages"])
        calls.append(text)
        data = json.loads(text.partition("\nDATA:\n")[2])
        said = [i["id"] for i in data["INPUT"] if i["kind"] == "said"]
        facts = [i["id"] for i in data["INPUT"] if i["kind"] == "fact"]
        answer = {"summary": {"text": "beta-app is an iOS habit tracker bob-example started in March 2026.",
                              "from": said},
                  "sections": [{"title": "How it works", "paragraphs": [
                      {"text": "It stores data locally with SwiftData and has no server.", "from": facts}]}]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    monkeypatch.setattr(cr.litellm, "acompletion", fake)
    (tmp_path / "entities").mkdir(parents=True, exist_ok=True)
    sp.attach(entity, "ep_2026-03-04_001", "user: I started beta-app. It stores data locally with SwiftData.")
    change = {"id": "beta-app", "action": "create", "entity": entity, "source_episodes": ["ep_2026-03-04_001"],
              "source_episode_timestamps": ["2026-03-04T09:00:00+00:00"]}
    changes = asyncio.run(cr.resolve_and_prune([change], [], settings, decay=False))
    cr.apply_changes([c for c in changes if c["id"] == "beta-app"], tmp_path)
    return calls, md.parse(tmp_path / "entities/beta-app.md")


def _beta(**over):
    return {"name": "beta-app", "type": "project",
            "summary": "beta-app is an iOS habit tracker bob-example started in March 2026.",
            "key_facts": ["beta-app stores data locally with SwiftData.", "beta-app has no server.",
                          "beta-app needs time-based reminders."], **over}


def test_a_new_page_with_material_is_born_an_article(tmp_path, monkeypatch):
    calls, page = _create(tmp_path, monkeypatch, _beta())
    assert len(calls) == 1 and ARTICLE_MARK in calls[0]   # one call, no contradiction check on a create
    sections = body.parse_sections(page.body)
    assert sections["Article"].startswith("### How it works")
    assert entity_article.stamped(page.frontmatter, sections)
    # The record is the extraction's, item for item, under the article.
    assert body._bullet_lines(sections["Key Facts"]) == _beta()["key_facts"]
    matched = sp.matched(page.frontmatter, page.body)
    (guard, rows), = matched["article"].values()
    assert {ev.episode for ev in rows} == {"ep_2026-03-04_001"}


def test_a_new_stub_is_created_as_before_with_no_call(tmp_path, monkeypatch):
    calls, page = _create(tmp_path, monkeypatch, _beta(key_facts=["beta-app has no server."]))
    assert calls == []
    sections = body.parse_sections(page.body)
    assert "Article" not in sections and "article" not in page.frontmatter


def test_articles_off_creates_every_page_as_before(tmp_path, monkeypatch):
    calls, page = _create(tmp_path, monkeypatch, _beta(), articles=False)
    assert calls == [] and "Article" not in body.parse_sections(page.body)
