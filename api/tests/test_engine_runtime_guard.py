"""The engine's own runtime is never conversation content.

`claude -p` still hands the model its working directory, platform and shell
despite `--system-prompt`; an extractor once turned that into a `directory`
entity. Stage 2 drops any entity named for the engine's scratch dir or a path
under `$CICADA_HOME`, silently, with a log line that carries no text.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from loguru import logger

from api.services import agent_engine, entity_extractor, entity_resolver


def _settings(memory):
    return SimpleNamespace(memory_path=memory, litellm_model="m", litellm_disambiguation_model="m",
                           sleep_promotion_threshold=2)


def _entity(name, etype="directory"):
    return {"name": name, "type": etype, "confidence": 0.95, "source_episode": "ep1",
            "summary": "A folder.", "key_facts": ["a fact"]}


def _resolve(tmp_path, names):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    # Two conversations, so a real entity clears the promotion threshold.
    extracted = [{"episode_id": f"ep{i}", "entities": [_entity(n) for n in names], "relationships": [
        {"source": names[0], "target": "alpha-project", "label": "holds"}]} for i in (1, 2)]
    return asyncio.run(entity_resolver.resolve(extracted, [], _settings(memory)))


def _names(result):
    return {str(c.get("name") or c.get("entity", {}).get("name") or "") for c in result["changes"]}


def test_runtime_paths_are_recognised(tmp_path, monkeypatch):
    home = tmp_path / "home" / ".cicada"
    monkeypatch.setenv("CICADA_HOME", str(home))
    assert agent_engine.is_runtime_path(str(home / "engine-scratch"))
    assert agent_engine.is_runtime_path(str(home / "engine-scratch") + "/")
    assert agent_engine.is_runtime_path(str(home / "secrets" / "x"))
    assert agent_engine.is_runtime_path(str(home))
    assert not agent_engine.is_runtime_path(str(tmp_path / "home" / "projects"))
    assert not agent_engine.is_runtime_path(str(tmp_path / "home" / ".cicada-notes"))
    assert not agent_engine.is_runtime_path("alpha-project")
    assert not agent_engine.is_runtime_path("")


def test_stage_two_drops_the_scratch_directory_entity(tmp_path, monkeypatch):
    home = tmp_path / "home" / ".cicada"
    monkeypatch.setenv("CICADA_HOME", str(home))
    scratch = str(home / "engine-scratch")
    result = _resolve(tmp_path, [scratch, "bob-example"])
    names = _names(result)
    assert "bob-example" in names, result["changes"]
    assert scratch not in names
    assert not any(".cicada" in n for n in names)
    assert not any(r.get("source", "").endswith("engine-scratch") for r in result.get("relationships", []))


def test_stage_two_drops_a_tilde_form_and_a_path_under_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "h"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CICADA_HOME", str(fake_home / ".cicada"))
    result = _resolve(tmp_path, ["~/.cicada/engine-scratch", str(fake_home / ".cicada" / "codex"), "bob-example"])
    assert not any(".cicada" in n for n in _names(result))


def test_the_drop_logs_no_text(tmp_path, monkeypatch):
    home = tmp_path / "home" / ".cicada"
    monkeypatch.setenv("CICADA_HOME", str(home))
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        _resolve(tmp_path, [str(home / "engine-scratch")])
    finally:
        logger.remove(sink)
    assert any("engine runtime" in line for line in lines)
    assert not any("engine-scratch" in line for line in lines)


def test_the_extraction_prompt_says_the_runtime_is_not_content():
    assert "never conversation content" in entity_extractor.EXTRACTION_SYSTEM_PROMPT


def test_an_existing_runtime_page_is_never_a_merge_target(tmp_path, monkeypatch):
    from api.services import markdown_parser

    home = tmp_path / "state"
    monkeypatch.setenv("CICADA_HOME", str(home))
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    leaked = str(home / "engine-scratch")
    fp = memory / "entities" / "leaked-scratch.md"
    markdown_parser.write(fp, {"id": "leaked-scratch", "name": leaked, "type": "directory", "confidence": 0.8}, "body")
    existing = [{"id": "leaked-scratch", "frontmatter": {"name": leaked, "confidence": 0.8}, "body": "body", "filepath": fp}]
    legit = str(tmp_path / "state-notes" / "engine-scratch")
    assert not agent_engine.is_runtime_path(legit)
    extracted = [{"episode_id": f"ep{i}", "entities": [_entity(legit)], "relationships": []} for i in (1, 2)]
    result = asyncio.run(entity_resolver.resolve(extracted, existing, _settings(memory)))
    assert not any(c.get("id") == "leaked-scratch" or c.get("entity_id") == "leaked-scratch" for c in result["changes"]), result["changes"]
