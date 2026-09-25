"""G138 / R-O28 — the handshake gains a line only for an installed, active
bridge; the cache key moves when that set moves; remote never gets one."""
from __future__ import annotations

from pathlib import Path

from _synthetic_bank import _bank, _ok_repo, _settings

from api.services import handshake, skill_catalog, state_dictionary


def _install(home: Path, name: str):
    (home / ".claude" / "skills" / name).mkdir(parents=True)
    (home / ".claude" / "skills" / name / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")


def test_build_appends_bridges_to_capabilities_and_stays_in_budget(tmp_path):
    lines = ("- bridge-one", "- bridge-two", "- bridge-three", "- bridge-four")
    text = handshake.build(None, variant="claude-code", bank="memory", bridges=lines)
    assert "- bridge-three" in text and "- bridge-four" not in text, "at most three"
    assert len(text) // 4 <= handshake.MAX_TOKENS


def test_installing_a_bridge_skill_invalidates_the_cache(tmp_path):
    memory = _bank(tmp_path)
    cache = tmp_path / "cache"
    first, _ = handshake.load_or_build(memory, "claude-code", cache_dir=cache)
    assert "cicada_save_url(url)" not in first
    _install(skill_catalog.agent_home(), "paper-lookup")
    second, meta = handshake.load_or_build(memory, "claude-code", cache_dir=cache)
    assert meta["cached"] is False and "`paper-lookup` is installed" in second
    generic, _ = handshake.load_or_build(memory, "cursor", cache_dir=cache)
    assert "paper-lookup" not in generic


def test_remote_never_carries_a_bridge(tmp_path):
    memory = _bank(tmp_path)
    _install(skill_catalog.agent_home(), "paper-lookup")
    text, _ = handshake.load_or_build(memory, variant="remote",
                                      tools=frozenset({"cicada_recall", "cicada_save_url"}), cache_dir=tmp_path / "c")
    assert "paper-lookup" not in text


def test_all_three_real_bridge_lines_fit_the_budget(tmp_path, monkeypatch):
    """R-B14 makes three keys live; the primer must still carry all three."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    lines = tuple(text.format(names="`example-skill` is") for text in skill_catalog.BRIDGE_TEXT.values())
    text = handshake.build(state_dictionary.read_state(memory), variant="claude-code", bank="memory",
                           tz="Europe/Madrid", bridges=lines)
    assert len(lines) == 3 and all(line in text for line in lines)
    assert len(text) // 4 <= handshake.MAX_TOKENS
