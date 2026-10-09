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
