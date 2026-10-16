"""Review blockers on pages as articles (G194): a person's prose and the record are never lost."""
import json
from pathlib import Path

import yaml

from api.services import entity_article, entity_body as body, markdown_parser as md

HAND = "alpha-app began as a sketch on paper; the person wrote this paragraph by hand."


def _write(ents: Path, eid: str, fm: dict, text: str):
    (ents / f"{eid}.md").write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n" + text)


# B1 --------------------------------------------------------------------------------------------------------------


def _merge_bank(tmp_path, *, loser_stamped: bool, winner_article: bool):
    ents = tmp_path / "entities"
    ents.mkdir(parents=True)
    winner_body = "## Summary\nalpha-project is a notes app.\n\n"
    if winner_article:
        winner_body += "## Article\n### What it is\n\nalpha-project keeps notes as markdown files.\n\n"
    winner_body += "## Key Facts\n- Uses SQLite."
    wfm = {"name": "alpha-project", "type": "project", "status": "active", "source_episodes": ["ep_1", "ep_2"]}
    if winner_article:
        entity_article.stamp(wfm, body.parse_sections(winner_body))
    _write(ents, "alpha-project", wfm, winner_body)
    loser_body = f"## Summary\nalpha-app is the old name.\n\n## Article\n### Origins\n\n{HAND}\n\n## Key Facts\n- Runs on a laptop."
    lfm = {"name": "alpha-app", "type": "project", "status": "active", "source_episodes": ["ep_3"]}
    if loser_stamped:
        entity_article.stamp(lfm, body.parse_sections(loser_body))
    _write(ents, "alpha-app", lfm, loser_body)
    return ents


def test_a_merge_keeps_the_losers_hand_written_article(tmp_path):
    from api.services.entity_merge import merge_entities

    for winner_article in (False, True):
        root = tmp_path / str(winner_article)
        ents = _merge_bank(root, loser_stamped=False, winner_article=winner_article)
        merge_entities(root, loser_id="alpha-app", winner_id="alpha-project")
        page = md.parse(ents / "alpha-project.md")
        sections = body.parse_sections(page.body)
        assert HAND in sections["Article"]
        if winner_article:
            assert "keeps notes as markdown files" in sections["Article"]
        assert "- Runs on a laptop." in sections["Key Facts"]
        assert page.body.index("## Summary") < page.body.index("## Article") < page.body.index("## Key Facts")
        # The person's prose makes the winner's page theirs: additive-only from now on.
        assert body.has_human_prose(page.frontmatter, sections)


def test_a_merge_does_not_carry_the_losers_machine_article(tmp_path):
    from api.services.entity_merge import merge_entities

    ents = _merge_bank(tmp_path, loser_stamped=True, winner_article=True)
    merge_entities(tmp_path, loser_id="alpha-app", winner_id="alpha-project")
    page = md.parse(ents / "alpha-project.md")
    sections = body.parse_sections(page.body)
    assert HAND not in sections["Article"] and "- Runs on a laptop." in sections["Key Facts"]
    assert entity_article.stamped(page.frontmatter, sections)   # the winner's article is still machine prose


# B2 / B3 ---------------------------------------------------------------------------------------------------------

LEGACY = ("beta-tool was chosen over gamma-tool for offline sync.\n\n## Key Facts\n"
          "The deploy target moved to example-host in 2025.\n- Uses SQLite.\n\n## History\n"
          "Free history text kept by an old writer.\n- 2026-01-10: First prototype.")


def _rebuild(tmp_path, monkeypatch, page_text):
    """The rebuild over a one-page synthetic bank, answered with a lead that carries nothing of the old prose."""
    from types import SimpleNamespace

    from api.config import Settings
    from api.services import conflict_resolver as cr, page_article_rebuild as rb

    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    md.write(bank / "entities/beta-tool.md", {"name": "beta-tool", "type": "tool", "status": "active",
                                             "source_episodes": ["ep_2026-01-10_001", "ep_2026-02-01_001"]},
             page_text)
    seen = []

    async def fake(**kwargs):
        text = kwargs["messages"][-1]["content"]
        seen.append(text)
        data = json.loads(text.partition("\nDATA:\n")[2])
        hist = [i["id"] for i in data["INPUT"] if i["kind"] == "history"]
        answer = {"summary": {"text": "beta-tool is a tool first prototyped in January 2026.", "from": hist}}
        return SimpleNamespace(model="m", choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    monkeypatch.setattr(cr.litellm, "acompletion", fake)
    out = tmp_path / "out"
    result = rb.run(bank, Settings(_env_file=None, llm_mode="local"), mode="preview", preview_dir=out)
    assert result.written == 1
    return md.parse(out / "beta-tool.after.md"), seen[0]


def test_a_legacy_lead_reaches_the_writer_and_is_kept_when_uncarried(tmp_path, monkeypatch):
    page, prompt = _rebuild(tmp_path, monkeypatch, LEGACY)
    assert "beta-tool was chosen over gamma-tool for offline sync." in prompt
    facts = body.parse_sections(page.body)["Key Facts"]
    assert "beta-tool was chosen over gamma-tool for offline sync." in facts


def test_free_text_in_list_sections_survives_the_rebuild(tmp_path, monkeypatch):
    page, prompt = _rebuild(tmp_path, monkeypatch, LEGACY)
    sections = body.parse_sections(page.body)
    assert "The deploy target moved to example-host in 2025." in sections["Key Facts"]
    assert "- Uses SQLite." in sections["Key Facts"]
    assert "Free history text kept by an old writer." in sections["History"]
    assert "The deploy target moved to example-host in 2025." in prompt     # and the writer is given it


def test_free_text_and_a_legacy_lead_survive_a_sleep_article(tmp_path, monkeypatch):
    import test_page_articles_sleep as sleep_tests

    def reply(text):
        data = json.loads(text.partition("\nDATA:\n")[2])
        hist = [i["id"] for i in data["INPUT"] if i["kind"] == "history"]
        return {"summary": {"text": "alpha-project was first prototyped in January 2026.", "from": hist}}

    _, _, page = sleep_tests.run(tmp_path, monkeypatch, fields=sleep_tests._fields(), page=LEGACY, reply=reply)
    sections = body.parse_sections(page.body)
    assert "The deploy target moved to example-host in 2025." in sections["Key Facts"]
    assert "- Runs on a laptop." in sections["Key Facts"]
    assert "Free history text kept by an old writer." in sections["History"]
    assert "beta-tool was chosen over gamma-tool for offline sync." in sections["Key Facts"]


# Also: the contradiction check on article pages -----------------------------------------------------------------


def test_a_summary_only_update_still_gets_its_contradiction_check_on_an_article_page(tmp_path, monkeypatch):
    import test_page_articles_sleep as sleep_tests

    contradiction = "checking whether two descriptions"
    _, calls, first = sleep_tests.run(tmp_path, monkeypatch,
                                      fields=sleep_tests._fields(summary="alpha-project moved to a beta in March."))
    assert sum(contradiction in c for c in calls) == 1           # writer on, summary only (no `description`)
    for articles in (True, False):                               # an article page, writer on or off
        _, calls, _ = sleep_tests.run(tmp_path / str(articles), monkeypatch, articles=articles,
                                      fields=sleep_tests._fields(summary="alpha-project left the beta in May."),
                                      page=first.body, fm=first.frontmatter, sources=("ep_2026-05-01_001",))
        assert sum(contradiction in c for c in calls) == 1
