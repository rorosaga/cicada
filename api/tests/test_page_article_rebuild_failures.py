"""One page's bad answer never costs the rebuild (G194 follow-up): a malformed, empty or failed answer skips that page;
a plan limit stops the run cleanly and keeps what was written."""
import json
import subprocess
from types import SimpleNamespace

from api.config import Settings
from api.scripts import rebuild_page_articles as script
from api.services import conflict_resolver as cr, engine_errors, entity_article, entity_body as body
from api.services import markdown_parser as md, page_article_rebuild as rebuild

PAGES = ("alpha-project", "beta-tool", "gamma-place")


def _git(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout


def _bank(tmp_path):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    for name in PAGES:
        md.write(bank / "entities" / f"{name}.md",
                 {"name": name, "type": "project", "status": "active",
                  "source_episodes": ["ep_2026-01-10_001", "ep_2026-03-02_001"]},
                 f"## Summary\n{name} is a synthetic thing.\n\n## Key Facts\n- {name} runs on a laptop.\n\n"
                 "## History\n- 2026-01-10: First prototype.")
    _git(bank, "init", "-q")
    _git(bank, "config", "user.name", "Synthetic")
    _git(bank, "config", "user.email", "synthetic@example.com")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "seed")
    return bank


def _engine(monkeypatch, behave):
    """``behave(name)`` returns the answer text for that page, or raises."""
    calls = []

    async def fake(**kwargs):
        text = kwargs["messages"][-1]["content"]
        data = json.loads(text.partition("\nDATA:\n")[2])
        calls.append(data["NAME"])
        content = behave(data["NAME"], data)
        return SimpleNamespace(model="synthetic", choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(cr.litellm, "acompletion", fake)
    return calls


def _good(name, data):
    ids = [i["id"] for i in data["INPUT"] if i["kind"] in ("earlier", "history", "fact")]
    return json.dumps({"summary": {"text": f"{name} is a synthetic thing, first prototyped in January 2026.",
                                   "from": ids}})


def _settings(concurrency=1):
    return Settings(_env_file=None, llm_mode="local", agent_max_concurrency=concurrency)


def test_a_malformed_answer_for_one_of_three_pages_skips_only_that_page(tmp_path, monkeypatch, capsys):
    bank = _bank(tmp_path)
    calls = _engine(monkeypatch, lambda name, data: '{"summary": {"text": "unbalanced' if name == "beta-tool"
                    else _good(name, data))
    result = rebuild.run(bank, _settings(3), mode="apply", sleep_running=lambda: False)
    assert sorted(calls) == sorted(PAGES)
    assert result.page_failures == {"unparsed": 1} and result.stopped is None and result.not_attempted == 0
    assert result.written == 2 and result.committed
    stamped = {n: entity_article.stamped((p := md.parse(bank / "entities" / f"{n}.md")).frontmatter,
                                         body.parse_sections(p.body)) for n in PAGES}
    assert stamped == {"alpha-project": True, "beta-tool": False, "gamma-place": True}
    assert "unbalanced" not in rebuild.dumps(result)


def test_empty_answers_timeouts_and_failed_calls_are_one_page_each(tmp_path, monkeypatch):
    bank = _bank(tmp_path)

    def behave(name, data):
        if name == "alpha-project":
            return ""
        if name == "beta-tool":
            raise engine_errors.EngineTimeout("synthetic timeout")
        raise engine_errors.EngineFailed("synthetic refusal")

    _engine(monkeypatch, behave)
    result = rebuild.run(bank, _settings(), mode="preview", preview_dir=tmp_path / "out")
    assert result.page_failures == {"unparsed": 1, "timed_out": 1, "engine_failed": 1}
    assert result.stopped is None and result.written == 0 and result.not_attempted == 0


def test_a_plan_limit_stops_the_run_and_keeps_what_was_written(tmp_path, monkeypatch, capsys):
    bank = _bank(tmp_path)

    limit = {"on": True}

    def behave(name, data):
        if name == "beta-tool" and limit["on"]:
            raise engine_errors.EngineThrottled("synthetic plan limit")
        return _good(name, data)

    calls = _engine(monkeypatch, behave)
    result = rebuild.run(bank, _settings(1), mode="apply", sleep_running=lambda: False)
    assert calls == ["alpha-project", "beta-tool"]                 # nothing starts after the limit
    assert result.stopped.startswith("EngineThrottled") and result.not_attempted == 1
    assert result.written == 1 and result.committed
    assert len(_git(bank, "log", "--format=%H").split()) == 2 and _git(bank, "status", "--porcelain") == ""
    p = md.parse(bank / "entities/alpha-project.md")
    assert entity_article.stamped(p.frontmatter, body.parse_sections(p.body))
    # Run again after the reset: the finished page is already an article, the rest are asked.
    calls.clear()
    limit["on"] = False
    again = rebuild.run(bank, _settings(1), mode="apply", sleep_running=lambda: False)
    assert again.already_articles == 1 and sorted(calls) == ["beta-tool", "gamma-place"] and again.written == 2


def test_the_script_says_a_stop_in_its_exit_code(tmp_path, monkeypatch, capsys):
    bank = _bank(tmp_path)
    _engine(monkeypatch, lambda name, data: (_ for _ in ()).throw(engine_errors.EngineExhausted("spent")))
    monkeypatch.setattr(rebuild, "resolve_engine",
                        lambda settings, allow_metered=False: _resolved(settings))
    assert script.main(["--bank", str(bank), "--preview-dir", str(tmp_path / "out")]) == 5
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["stopped"].startswith("EngineExhausted") and out["written"] == 0


async def _resolved(settings):
    return settings.model_copy(update={"llm_mode": "local"}), "ollama", "synthetic"


def test_pages_failing_in_a_row_stop_the_run(tmp_path, monkeypatch):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    for i in range(8):
        md.write(bank / "entities" / f"page-{i}.md", {"name": f"page-{i}", "type": "concept", "status": "active",
                                                      "source_episodes": ["ep_1", "ep_2"]},
                 f"## Summary\npage-{i} is synthetic.\n\n## Key Facts\n- page-{i} is a test.")
    calls = _engine(monkeypatch, lambda name, data: (_ for _ in ()).throw(engine_errors.EngineTimeout("slow")))
    result = rebuild.run(bank, _settings(1), mode="preview", preview_dir=tmp_path / "out")
    assert len(calls) == rebuild.MAX_FAILURES_IN_A_ROW and result.page_failures == {"timed_out": 5}
    assert result.stopped.startswith("5 pages in a row") and result.not_attempted == 3


def test_sleeps_article_path_falls_back_on_a_malformed_answer(tmp_path, monkeypatch):
    """The same ValueError in Stage 3 is caught per page: the page keeps the deterministic merge."""
    import test_page_articles_sleep as sleep_tests

    calls = []

    async def malformed(**kwargs):
        calls.append(1)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary": {"text": "x'))])

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    import asyncio

    settings = Settings(_env_file=None, page_articles_enabled=True)
    existing = [{"id": "alpha-project", "frontmatter": {"name": "alpha-project", "type": "project",
                                                         "source_episodes": ["ep_2026-01-10_001"]},
                 "body": sleep_tests.PAGE}]
    (tmp_path / "entities").mkdir(exist_ok=True)
    md.write(tmp_path / "entities/alpha-project.md", existing[0]["frontmatter"], sleep_tests.PAGE)
    monkeypatch.setattr(cr.litellm, "acompletion", malformed)
    change = {"id": "alpha-project", "action": "update", "entity": sleep_tests._fields(),
              "source_episodes": ["ep_2026-03-02_001"], "source_episode_timestamps": ["2026-03-02T10:00:00+00:00"]}
    changes = asyncio.run(cr.resolve_and_prune([change], existing, settings, decay=False))
    assert calls == [1] and "article" not in changes[0]
    cr.apply_changes(changes, tmp_path)
    sections = body.parse_sections(md.parse(tmp_path / "entities/alpha-project.md").body)
    assert "Article" not in sections and "- Runs on a laptop." in sections["Key Facts"]
