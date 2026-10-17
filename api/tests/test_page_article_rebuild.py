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
    _resolves_to(monkeypatch, "local")   # an engine that resolves: the Sleep check is what refuses
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


# --------------------------------------------------------------------------- the engine (orchestrator blocker)


def _resolves_to(monkeypatch, mode, why="synthetic"):
    """`engine_select.resolve_settings` as a person-started Sleep would see it: the given mode."""
    from api.services import engine_select

    seen = []

    async def resolve(settings, registry=None, *, user_triggered=True):
        seen.append(user_triggered)
        return settings.model_copy(update={"llm_mode": mode}), why

    monkeypatch.setattr(engine_select, "resolve_settings", resolve)
    return seen


def _capture_engine(monkeypatch, calls):
    """The provider seam: records the engine each call was routed to, answers like `_fake`."""
    from api.services import providers

    def resolve_llm_fn(settings, *, model=None, completion=None, stage=None, **kwargs):
        async def call(**call_kwargs):
            calls.append(settings.llm_mode)
            text = call_kwargs["messages"][-1]["content"]
            data = json.loads(text.partition("\nDATA:\n")[2])
            facts = [i["id"] for i in data["INPUT"] if i["kind"] == "fact"]
            earlier = [i["id"] for i in data["INPUT"] if i["kind"] in ("earlier", "history")]
            answer = {"summary": {"text": f"{data['NAME']} is part of the owner's work, dated March 2026.",
                                  "from": earlier},
                      "sections": [{"title": "What it is", "paragraphs": [
                          {"text": "It uses SQLite and runs on a laptop.", "from": facts}]}]}
            return SimpleNamespace(model="plan-model", choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps(answer)))])
        return call

    monkeypatch.setattr(providers, "resolve_llm_fn", resolve_llm_fn)


def test_the_plan_the_person_chose_is_the_engine_used(tmp_path, monkeypatch, capsys):
    bank = _bank(tmp_path)
    seen = _resolves_to(monkeypatch, "agent", "Sleep engine set to 'agent' in Settings")
    calls = []
    _capture_engine(monkeypatch, calls)
    assert script.main(["--bank", str(bank), "--entity", "alpha-project", "--preview-dir",
                        str(tmp_path / "out")]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert seen == [True]                      # resolved as a person-started run
    assert calls == ["agent"] and out["engine"] == "claude-cli" and out["written"] == 1
    assert "sk-" not in json.dumps(out)


def test_nothing_connected_is_refused_before_a_call(tmp_path, monkeypatch, capsys):
    bank = _bank(tmp_path)
    _resolves_to(monkeypatch, "byok", "no Sleep engine chosen")
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    calls = []
    _capture_engine(monkeypatch, calls)
    for extra in ([], ["--allow-metered"]):
        assert script.main(["--bank", str(bank), "--limit", "1", "--preview-dir", str(tmp_path / "out"),
                            *extra]) == 4
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert "No engine is connected" in out["refused"] and out["engine"] == "litellm"
    assert script.main(["--bank", str(bank), "--apply"]) == 4
    assert calls == [] and not (tmp_path / "out").exists()
    assert _git(bank, "status", "--porcelain") == ""


def test_a_metered_key_is_refused_without_the_flag_and_used_with_it(tmp_path, monkeypatch, capsys):
    bank = _bank(tmp_path)
    _resolves_to(monkeypatch, "byok", "no Sleep engine chosen — using the configured API model")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-key")
    monkeypatch.setenv("CICADA_LITELLM_MODEL", "gpt-5.4-nano")
    monkeypatch.delenv("CICADA_CONSOLIDATION_MODEL", raising=False)
    calls = []
    _capture_engine(monkeypatch, calls)
    assert script.main(["--bank", str(bank), "--limit", "1", "--preview-dir", str(tmp_path / "out")]) == 4
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "--allow-metered" in out["refused"] and "billed per call" in out["refused"]
    assert calls == [] and "synthetic-not-a-key" not in json.dumps(out)
    # The dry run names the engine and why a call would be refused, and calls nothing.
    assert script.main(["--bank", str(bank)]) == 0
    dry = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert dry["engine"] == "litellm" and dry["engine_reason"].startswith("refused:") and calls == []
    assert script.main(["--bank", str(bank), "--limit", "1", "--preview-dir", str(tmp_path / "out"),
                        "--allow-metered"]) == 0
    assert calls == ["byok"]


# --------------------------------------------------------------------------- uncapped (owner 2026-10-17)


def _one_conversation_page(bank, said="2026-04-01"):
    md.write(bank / "entities/rich-tool.md",
             {"name": "rich-tool", "type": "tool", "source_episodes": ["ep_2026-04-01_001"], "last_referenced": said},
             "## Summary\nrich-tool is a sync tool the owner set up.\n\n## Key Facts\n- Syncs every hour.\n"
             "- Runs on the laptop.\n- Keeps 30 days of history.\n\n## History\n- 2026-04-01: Set up.")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "one conversation, rich")


def test_a_one_conversation_page_with_material_is_selected_and_a_stub_is_not(tmp_path):
    bank = _bank(tmp_path)
    _one_conversation_page(bank)
    result = rebuild.survey(bank, _settings())
    assert result.selected == 3 and result.one_conversation_selected == 1
    assert result.one_conversation == 1          # stub-tool: one line, nothing to connect
    assert result.estimated_calls == 3 and result.batches == 1
    floor = rebuild.survey(bank, Settings(_env_file=None, llm_mode="local", page_article_min_material=50))
    assert floor.selected == 2 and floor.one_conversation == 2


def test_pages_go_newest_mentioned_first(tmp_path):
    bank = _bank(tmp_path)
    _one_conversation_page(bank, said="2026-05-01")
    order = [job.path.stem for job in rebuild.survey(bank, _settings())._jobs]
    assert order == ["rich-tool", "alpha-project", "bob-example"]   # bob-example has no mention date: last
    assert [j.path.stem for j in rebuild.survey(bank, _settings(), limit=1)._jobs] == ["rich-tool"]


def test_apply_commits_a_batch_at_a_time(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    _one_conversation_page(bank)
    calls = []
    _fake(monkeypatch, calls)
    result = rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: False, batch_size=1)
    assert result.written == 3 and result.commits == 3 and len(calls) == 3
    assert _git(bank, "log", "--format=%s", "-3").splitlines() == ["Pages rebuilt as articles: 1 page(s)"] * 3
    assert _git(bank, "status", "--porcelain") == ""


def test_sleep_starting_between_batches_stops_and_a_rerun_continues(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    _one_conversation_page(bank)
    calls = []
    _fake(monkeypatch, calls)
    checks = iter([False, False, True])   # idle before the run and its first batch; Sleep starts before the second
    result = rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: next(checks, True), batch_size=1)
    assert result.written == 1 and result.commits == 1 and result.stopped and result.not_attempted == 2
    again = rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: False, batch_size=2)
    assert again.already_articles == 1 and again.written == 2 and again.commits == 1
    assert rebuild.survey(bank, _settings()).selected == 0


def test_a_slow_backend_between_batches_is_named_as_such_not_as_sleep(tmp_path, monkeypatch):
    """2026-10-17: a long rebuild stopped with "Sleep started" while Sleep was idle — the backend was only slow."""
    bank = _bank(tmp_path)
    _one_conversation_page(bank)
    _fake(monkeypatch, [])
    checks = iter([False, False, True])
    problem = "the backend did not answer within 8 s (3 tries), so Sleep could not be confirmed idle"
    result = rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: next(checks, True), batch_size=1,
                         backend_problem=lambda: problem)
    assert result.written == 1 and result.stopped.startswith(problem)
    assert "Sleep started" not in result.stopped and "batches before it are committed" in result.stopped


def test_a_backend_that_never_answers_refuses_with_that_reason(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    _one_conversation_page(bank)
    calls = []
    _fake(monkeypatch, calls)
    with pytest.raises(rebuild.SleepRunning, match="not reachable"):
        rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: True,
                    backend_problem=lambda: "the backend is not reachable (3 tries)")
    assert calls == [], "refused before any call"


def test_a_real_sleep_between_batches_still_says_sleep_started(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    _one_conversation_page(bank)
    _fake(monkeypatch, [])
    checks = iter([False, False, True])
    result = rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: next(checks, True), batch_size=1,
                         backend_problem=lambda: None)
    assert result.stopped.startswith("Sleep started")


def test_rewrite_counts_a_page_written_today_as_done(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    calls = []
    _fake(monkeypatch, calls)
    rebuild.run(bank, _settings(), mode="apply", sleep_running=lambda: False)
    assert rebuild.survey(bank, _settings(), rewrite=True).selected == 0
    assert rebuild.survey(bank, _settings(), rewrite=True, today="2099-01-01").selected == 2


def test_the_script_takes_a_batch_size(tmp_path, monkeypatch, capsys):
    bank = _bank(tmp_path)
    calls = []
    _fake(monkeypatch, calls)
    _resolves_to(monkeypatch, "local")
    monkeypatch.setattr(script, "backend_running", lambda: False)
    assert script.main(["--bank", str(bank), "--apply", "--batch-size", "1"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["commits"] == 2 and out["written"] == 2 and out["batch_size"] == 1
