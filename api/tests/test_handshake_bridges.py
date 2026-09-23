"""G138 / R-O28 — the handshake gains a line only for an installed, active
bridge; the cache key moves when that set moves; remote never gets one."""
from __future__ import annotations

from pathlib import Path

from _synthetic_bank import _bank

from api.services import handshake, skill_catalog


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
