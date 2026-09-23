"""Tests for the MCP ``cicada_get_perspective`` Bookworm tool (M5e).

``get_perspective(subject, observer?, context?)`` returns a subject's
currently-valid claims, filtered by the optional observer / context perspective.
Hermetic: ``CICADA_MEMORY_PATH`` points at a tmp workspace; no LLM, no network.
The server module is imported by path (it lives outside the api package).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from api.services import markdown_parser
from api.services.claims import Claim, write_claims

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_server():
    spec = importlib.util.spec_from_file_location(
        "cicada_mcp_server", _REPO_ROOT / "mcp" / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def _claim(cid, subject, text, **kw):
    kw.setdefault("observer", "agent")
    kw.setdefault("context", "general")
    kw.setdefault("valid_from", "2026-01-01")
    return Claim(id=cid, text=text, subject=subject, **kw)


def _write_subject(memory_path, stem, name, claims):
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    body = write_claims("A page.", claims)
    markdown_parser.write(
        entities_dir / f"{stem}.md",
        {"name": name, "type": "person", "status": "active"},
        body,
    )


def test_get_perspective_returns_valid_claims(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    server = _load_server()
    _write_subject(
        tmp_path, "rodrigo", "Rodrigo",
        [
            _claim("clm_eng", "rodrigo", "In engineering Rodrigo values speed.",
                   context="engineering", predicate="values", object="speed"),
            _claim("clm_fam", "rodrigo", "With family Rodrigo values presence.",
                   context="family", predicate="values", object="presence"),
        ],
    )
    out = server.handle_get_perspective("rodrigo")
    assert "speed" in out
    assert "presence" in out
    assert "2 valid claim" in out


def test_get_perspective_filters_by_context(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    server = _load_server()
    _write_subject(
        tmp_path, "rodrigo", "Rodrigo",
        [
            _claim("clm_eng", "rodrigo", "In engineering Rodrigo values speed.",
                   context="engineering"),
            _claim("clm_fam", "rodrigo", "With family Rodrigo values presence.",
                   context="family"),
        ],
    )
    out = server.handle_get_perspective("rodrigo", None, "family")
    assert "presence" in out
    assert "speed" not in out


def test_get_perspective_filters_by_observer(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    server = _load_server()
    _write_subject(
        tmp_path, "rodrigo", "Rodrigo",
        [
            _claim("clm_a", "rodrigo", "Agent thinks Rodrigo uses Postgres.",
                   observer="agent"),
            _claim("clm_r", "rodrigo", "Rodrigo asserts he uses sqlite-vec.",
                   observer="rodrigo"),
        ],
    )
    out = server.handle_get_perspective("rodrigo", "rodrigo", None)
    assert "sqlite-vec" in out
    assert "Postgres" not in out


def test_get_perspective_excludes_superseded(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    server = _load_server()
    closed = _claim("clm_old", "cicada", "Cicada used Postgres.",
                    valid_to="2026-05-05", superseded_by="clm_new")
    open_ = _claim("clm_new", "cicada", "Cicada uses sqlite-vec.")
    _write_subject(tmp_path, "cicada", "Cicada", [closed, open_])
    out = server.handle_get_perspective("cicada")
    assert "sqlite-vec" in out
    assert "Postgres" not in out, "superseded claim must not appear in the perspective"


def test_get_perspective_missing_subject(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    (tmp_path / "entities").mkdir(parents=True, exist_ok=True)
    server = _load_server()
    out = server.handle_get_perspective("nonexistent")
    assert "No subject" in out


def _events():
    return [
        _claim("clm_fact", "alpha-project", "Alpha uses sqlite-vec.", predicate="uses", object="sqlite-vec"),
        _claim("clm_thread", "alpha-project", "Connecting to the lab cluster", predicate="happened",
               object="connecting to the lab cluster", object_kind="literal", valid_from="2026-09-10",
               status="ongoing"),
        _claim("clm_plan", "alpha-project", "First grasp", predicate="milestone", object="first-grasp",
               object_kind="literal", valid_from="2026-09-10", status="planned", target="2026-10-01"),
        _claim("clm_done", "alpha-project", "Got the guide from Hana Example", predicate="happened",
               object="got the guide from hana example", object_kind="literal", valid_from="2026-09-22",
               valid_to="2026-09-22", status="done"),
        _claim("clm_old", "alpha-project", "Alpha used Postgres.", predicate="uses", object="postgres",
               valid_to="2026-05-05", superseded_by="clm_fact"),
    ]


def test_get_perspective_renders_events_as_dated_lines(tmp_path, monkeypatch):
    """G141 R-PJ3: an open thread or plan reads `day · status · sentence`; a
    born-closed done happening is not current, and with history it sits in its
    own "Happened" block — never "was X until D"."""
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    server = _load_server()
    _write_subject(tmp_path, "alpha-project", "Alpha Project", _events())
    out = server.handle_get_perspective("alpha-project")
    assert "- 2026-09-10 · ongoing · Connecting to the lab cluster\n" in out
    assert "- 2026-09-10 · planned · First grasp (target 2026-10-01)\n" in out
    assert "Got the guide" not in out
    assert "3 valid claim" in out

    out = server.handle_get_perspective("alpha-project", None, None, True)
    earlier, happened = out.split("Happened, newest first (1):")
    assert "Postgres" in earlier and "Got the guide" not in earlier
    assert happened.strip() == "- 2026-09-22 · done · Got the guide from Hana Example"
