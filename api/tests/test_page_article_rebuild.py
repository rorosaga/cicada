"""The person-run rebuild of existing pages as articles (G194): dry run, sample, preview, apply — synthetic banks only."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.scripts import rebuild_page_articles as script
from api.services import conflict_resolver as cr, entity_article, entity_body as body, markdown_parser as md
from api.services import page_article_rebuild as rebuild, section_provenance as sp
from api.services.claims import Claim, Evidence, parse_claims, write_claims

RICH = ("## Summary\nalpha-project is a notes app. bob-example works on it with the owner.\n\n"
        "## Key Facts\n- Uses SQLite for sync.\n- Runs on a laptop.\n- Has 40 beta users.\n\n"
        "## History\n- 2026-01-10: First prototype.\n- 2026-03-02: Beta opened.\n\n"
        "## Related\n- [[bob-example]] — works on\n\n## Open Questions\n- Mobile app?")


def _git(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout


def _bank(tmp_path):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    claim = Claim(id="clm_1", text="alpha-project uses SQLite.", subject="alpha-project", predicate="uses",
                  object="bob-example", valid_from="2026-01-10",
                  evidence=[Evidence(episode="ep_2026-01-10_001", hash="0123456789ab", start=0, end=4, kind="user")])
    two = ["ep_2026-01-10_001", "ep_2026-03-02_001"]
    md.write(bank / "entities/alpha-project.md",
             {"name": "alpha-project", "type": "project", "source_episodes": two, "created": "2026-01-10",
              "last_referenced": "2026-03-02"}, write_claims(RICH, [claim]))
    md.write(bank / "entities/bob-example.md", {"name": "bob-example", "type": "person", "source_episodes": two},
             "## Summary\nbob-example is a friend.\n\n## Key Facts\n- Works on alpha-project.")
    md.write(bank / "entities/stub-tool.md", {"name": "stub-tool", "type": "tool", "source_episodes": two[:1]},
             "## Summary\nstub-tool is a tool.")
    md.write(bank / "entities/hand-page.md", {"name": "hand-page", "type": "concept", "source_episodes": two},
             "## Summary\nMine.\n\n## My notes\nWritten by hand.")
    md.write(bank / "entities/old-page.md", {"name": "old-page", "type": "concept", "source_episodes": two,
                                             "status": "archived"}, "## Summary\nOld.")
    md.write(bank / "entities/saved-video.md", {"name": "saved-video", "type": "media", "source_episodes": two},
             "## Summary\nA video.")
    _git(bank, "init", "-q")
    _git(bank, "config", "user.name", "Synthetic")
    _git(bank, "config", "user.email", "synthetic@example.com")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "seed")
    return bank


def _fake(monkeypatch, calls):
    async def fake(**kwargs):
        text = kwargs["messages"][-1]["content"]
        calls.append(text)
        data = json.loads(text.partition("\nDATA:\n")[2])
        ids = {}
        for item in data["INPUT"]:
            ids.setdefault(item["kind"], []).append(item["id"])
        name = data["NAME"]
        answer = {"summary": {"text": f"{name} is part of the owner's work, last dated March 2026.",
                              "from": ids.get("earlier", []) + ids.get("history", [])},
                  "sections": [{"title": "What it is", "paragraphs": [
                      {"text": f"{name} uses SQLite, runs on a laptop and has 40 beta users.",
                       "from": ids.get("fact", []) + ids.get("claim", [])}]}]}
        return SimpleNamespace(model="synthetic-model", choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(answer)))])

    monkeypatch.setattr(cr.litellm, "acompletion", fake)


def _settings():
    return Settings(_env_file=None, llm_mode="local")


def test_the_dry_run_counts_and_calls_nothing(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    calls = []
    _fake(monkeypatch, calls)
    before = {p.name: p.read_text() for p in (bank / "entities").glob("*.md")}
    result = rebuild.run(bank, _settings(), mode="dry")
    counts = result.counts()
    assert calls == []
    assert {k: counts[k] for k in ("pages", "inactive", "media", "human", "one_conversation", "selected")} == {
        "pages": 6, "inactive": 1, "media": 1, "human": 1, "one_conversation": 1, "selected": 2}
    assert counts["prompt_chars"] > 0
    assert before == {p.name: p.read_text() for p in (bank / "entities").glob("*.md")}
    assert "alpha-project" not in rebuild.dumps(result) and "SQLite" not in rebuild.dumps(result)


def test_the_sample_narrows_to_named_pages_or_n(tmp_path):
    bank = _bank(tmp_path)
    assert rebuild.survey(bank, _settings(), entity_ids=["bob-example"]).selected == 1
    assert rebuild.survey(bank, _settings(), limit=1).selected == 1


def test_preview_writes_before_and_after_outside_the_bank_and_leaves_it_alone(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    calls = []
    _fake(monkeypatch, calls)
    out = tmp_path / "preview"
    result = rebuild.run(bank, _settings(), mode="preview", entity_ids=["alpha-project"], preview_dir=out)
    assert len(calls) == 1 and result.written == 1
    assert _git(bank, "status", "--porcelain") == ""
    after = md.parse(out / "alpha-project.after.md")
    assert "## Article" in after.body and (out / "alpha-project.before.md").read_text() == (
        bank / "entities/alpha-project.md").read_text()
    assert script.main(["--bank", str(bank), "--preview-dir", str(bank / "inside")]) == 2


def test_apply_is_refused_before_any_call_unless_sleep_is_idle(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    calls = []
    _fake(monkeypatch, calls)
    with pytest.raises(rebuild.SleepRunning):
        rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: True)
    assert calls == [] and _git(bank, "status", "--porcelain") == ""
    monkeypatch.setattr(script, "backend_running", lambda: True)
    assert script.main(["--bank", str(bank), "--apply"]) == 3


def test_apply_rebuilds_losslessly_in_one_commit(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    calls = []
    _fake(monkeypatch, calls)
    old = md.parse(bank / "entities/alpha-project.md")
    old_sections = body.parse_sections(old.body)
    result = rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: False)
    assert result.written == 2 and result.committed
    assert len(_git(bank, "log", "--format=%H").split()) == 2 and _git(bank, "status", "--porcelain") == ""
    message = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: synthetic-model" in message and "maintenance/page-articles" in message
    page = md.parse(bank / "entities/alpha-project.md")
    sections = body.parse_sections(page.body)
    # The record, item for item: facts, dated lines, links out, questions, claims.
    for title in ("History", "Related", "Open Questions"):
        assert sections[title] == old_sections[title]
    facts = body._bullet_lines(sections["Key Facts"])
    assert facts[:3] == body._bullet_lines(old_sections["Key Facts"])
    assert [c.id for c in parse_claims(page.body)] == ["clm_1"]
    # The old Summary's second sentence is not carried by the new lead: it is kept as a Key Fact.
    assert "bob-example works on it with the owner." in facts
    assert entity_article.stamped(page.frontmatter, sections)
    assert sp.matched(page.frontmatter, page.body)["article"]
    # A second dry run finds nothing left to do.
    assert rebuild.survey(bank, _settings()).already_articles == 2


def test_a_page_written_since_it_was_read_is_skipped(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    calls = []
    _fake(monkeypatch, calls)
    result = rebuild.survey(bank, _settings(), entity_ids=["alpha-project"])
    import asyncio
    asyncio.run(rebuild.write(result, _settings()))
    path = bank / "entities/alpha-project.md"
    path.write_text(path.read_text() + "\n")
    rebuild.apply(bank, result, sleep_running=lambda: False)
    assert result.changed_since_read == 1 and result.written == 0
