"""Fuzzy subject pre-check in the agentic write path (reconsolidation pilot
blocker #2, 2026-07-13): ``write_claim`` with a subject that resolves to no
exact page but NEAR-matches existing entities must refuse to create a
duplicate stub — return ``ambiguous_subject`` with candidates instead of
guessing ("Raul" landing on a fresh raul.md while raul-perez-pelaez.md
exists). ``force_new_entity=True`` overrides after an explicit decision.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from api.services import agentic_write

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _page(tmp_path, entity_id, name=None, type_="person"):
    ents = tmp_path / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    (ents / f"{entity_id}.md").write_text(
        f"---\nname: {name or entity_id}\ntype: {type_}\nstatus: active\nconfidence: 0.8\n---\n\n## Summary\nx\n",
        encoding="utf-8",
    )


def test_near_match_returns_ambiguous_and_writes_nothing(tmp_path):
    _page(tmp_path, "raul-perez-pelaez", "Raul Perez Pelaez")

    result = agentic_write.write_claim(
        tmp_path, "Raul", "supervises", "the capstone", observer="agent"
    )

    assert result["action"] == "ambiguous_subject"
    assert [c["entity_id"] for c in result["candidates"]] == ["raul-perez-pelaez"]
    assert not (tmp_path / "entities" / "raul.md").exists()


def test_containment_both_directions(tmp_path):
    _page(tmp_path, "francesco", "Francesco")

    result = agentic_write.write_claim(
        tmp_path, "Francesco Baldissera", "works-with", "Rodrigo", observer="agent"
    )

    assert result["action"] == "ambiguous_subject"
    assert result["candidates"][0]["entity_id"] == "francesco"


def test_force_new_entity_creates_despite_near_match(tmp_path):
    _page(tmp_path, "tumi-robotics", "Tumi Robotics", type_="company")

    result = agentic_write.write_claim(
        tmp_path, "Tumi", "hosted", "a guest talk", observer="agent",
        force_new_entity=True,
    )

    assert result["action"] in ("written", "coexist")
    assert (tmp_path / "entities" / "tumi.md").exists()


def test_exact_match_still_writes_directly(tmp_path):
    _page(tmp_path, "tumi-robotics", "Tumi Robotics", type_="company")

    result = agentic_write.write_claim(
        tmp_path, "tumi-robotics", "hosted", "a guest talk", observer="agent"
    )

    assert result["action"] == "written"
    assert result["entity_id"] == "tumi-robotics"


def test_novel_subject_creates_stub_as_before(tmp_path):
    _page(tmp_path, "raul-perez-pelaez", "Raul Perez Pelaez")

    result = agentic_write.write_claim(
        tmp_path, "HallBayes", "verifies", "sleep output", observer="agent"
    )

    assert result["action"] == "written"
    assert (tmp_path / "entities" / "hallbayes.md").exists()


def test_mcp_handler_renders_candidates_and_passes_force_flag(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "cicada_mcp_server_subject_res", _REPO_ROOT / "mcp" / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server_subject_res"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "get_memory_path", lambda: tmp_path)

    _page(tmp_path, "raul-perez-pelaez", "Raul Perez Pelaez")

    rendered = mod.handle_write_claim(
        "Raul", "supervises", "the capstone", "agent", None, None, None
    )
    assert "ambiguous subject" in rendered
    assert "raul-perez-pelaez" in rendered
    assert "force_new_entity" in rendered

    forced = mod.handle_write_claim(
        "Raul", "supervises", "the capstone", "agent", None, None, None, True
    )
    assert "Recorded" in forced
    assert (tmp_path / "entities" / "raul.md").exists()
