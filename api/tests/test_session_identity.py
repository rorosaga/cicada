"""G48 — the MCP server mints ONE conversation identity per process and stamps
it onto everything it writes. Hermetic: env is a plain dict, banks live under
tmp_path, and the real ~/.claude is never touched.
"""

from __future__ import annotations

import importlib
import re

server = importlib.import_module("mcp.server")


# --- resolve_session_identity (pure) ----------------------------------------


def test_claude_code_env_wins_and_carries_the_project_dir():
    ident = server.resolve_session_identity({
        "CLAUDE_CODE_SESSION_ID": "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
        "CLAUDE_PROJECT_DIR": "/Users/x/Documents/roros_lab/cicada",
    })
    assert ident.session_id == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert ident.harness == "claude-code"
    assert ident.project_dir == "/Users/x/Documents/roros_lab/cicada"


def test_a_non_uuid_claude_session_id_is_refused_and_falls_through():
    ident = server.resolve_session_identity({"CLAUDE_CODE_SESSION_ID": "not-a-uuid"})
    assert ident.session_id.startswith("ses_")
    assert ident.harness == "unknown"


def test_explicit_override_is_used_when_no_claude_session_id():
    ident = server.resolve_session_identity({
        "CICADA_SESSION_ID": "my-cursor-thread-7",
        "CICADA_SESSION_HARNESS": "cursor",
    })
    assert ident.session_id == "my-cursor-thread-7"
    assert ident.harness == "cursor"


def test_claude_session_id_beats_the_explicit_override():
    ident = server.resolve_session_identity({
        "CLAUDE_CODE_SESSION_ID": "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
        "CICADA_SESSION_ID": "loser",
    })
    assert ident.session_id == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"


def test_mint_shape_groups_but_never_resumes():
    ident = server.resolve_session_identity({})
    assert re.match(r"^ses_\d{4}-\d{2}-\d{2}_[0-9a-f]{8}$", ident.session_id)
    assert ident.harness == "unknown"
    assert ident.project_dir is None


def test_two_mints_are_distinct():
    a = server.resolve_session_identity({})
    b = server.resolve_session_identity({})
    assert a.session_id != b.session_id


# --- frontmatter projection --------------------------------------------------


def test_frontmatter_omits_unknown_harness_and_absent_project_dir(monkeypatch):
    monkeypatch.setattr(
        server, "SESSION", server.SessionIdentity("ses_2026-08-31_deadbeef", "unknown", None)
    )
    assert server._session_frontmatter() == {"session_id": "ses_2026-08-31_deadbeef"}


def test_frontmatter_carries_harness_and_project_dir_when_known(monkeypatch):
    monkeypatch.setattr(
        server,
        "SESSION",
        server.SessionIdentity("0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b", "claude-code", "/tmp/p"),
    )
    assert server._session_frontmatter() == {
        "session_id": "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
        "harness": "claude-code",
        "project_dir": "/tmp/p",
    }


# --- handle_save_episode stamps ---------------------------------------------

import pytest

from api.services import markdown_parser


@pytest.fixture
def mcp_bank(tmp_path, monkeypatch):
    """A throwaway memory root the MCP handlers write into."""
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(
        server,
        "SESSION",
        server.SessionIdentity("0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b", "claude-code", "/tmp/p"),
    )
    return memory


def test_save_episode_stamps_the_session(mcp_bank):
    out = server.handle_save_episode("we picked sqlite-vec over LEANN", "Index choice")
    assert "Episode saved" in out

    written = list((mcp_bank / "episodes").glob("*.md"))
    assert len(written) == 1
    fm = markdown_parser.parse(written[0]).frontmatter
    assert fm["session_id"] == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert fm["harness"] == "claude-code"
    assert fm["project_dir"] == "/tmp/p"
    # Pre-existing keys are untouched.
    assert fm["origin"] == "mcp" and fm["processed"] is False


def test_a_minted_session_stamps_only_the_id(mcp_bank, monkeypatch):
    monkeypatch.setattr(
        server, "SESSION", server.SessionIdentity("ses_2026-08-31_deadbeef", "unknown", None)
    )
    server.handle_save_episode("a note", "Note")
    fm = markdown_parser.parse(next((mcp_bank / "episodes").glob("*.md"))).frontmatter
    assert fm["session_id"] == "ses_2026-08-31_deadbeef"
    assert "harness" not in fm and "project_dir" not in fm


def test_the_stamp_survives_the_sleep_loader_and_the_processed_rewrite(mcp_bank):
    from api.services import bank_index, sleep_cycle

    server.handle_save_episode("we picked sqlite-vec", "Index choice")
    bank_index.invalidate()

    queued = sleep_cycle._get_unprocessed_episodes(mcp_bank)
    assert len(queued) == 1
    assert queued[0]["session_id"] == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert queued[0]["source_id"] is None

    sleep_cycle._mark_episodes_processed(queued)
    fm = markdown_parser.parse(queued[0]["filepath"]).frontmatter
    assert fm["processed"] is True
    assert fm["session_id"] == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert fm["harness"] == "claude-code"


def test_an_imported_episode_reports_its_source_id_to_the_loader(mcp_bank):
    from api.services import bank_index, sleep_cycle

    (mcp_bank / "episodes" / "ep_2026-01-01_001.md").write_text(
        "---\nid: ep_2026-01-01_001\ntimestamp: '2026-01-01T00:00:00Z'\n"
        "processed: false\nsource_id: uuid-abc\n---\n\nimported\n",
        encoding="utf-8",
    )
    bank_index.invalidate()

    queued = {e["id"]: e for e in sleep_cycle._get_unprocessed_episodes(mcp_bank)}
    assert queued["ep_2026-01-01_001"]["source_id"] == "uuid-abc"
    assert queued["ep_2026-01-01_001"]["session_id"] is None


# --- write_media_episode stamps (the cicada_save_url path) -------------------


def test_media_episode_stamps_the_session_when_the_caller_supplies_one(tmp_path):
    from api.services.media_ingestor import MediaMeta, RawItem, write_media_episode

    item = RawItem(
        url="https://example.com/a",
        session_id="0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b",
        harness="claude-code",
        project_dir="/tmp/p",
    )
    meta = MediaMeta(title="A", media_type="url")
    ep_id = write_media_episode(tmp_path / "episodes", item, meta, "media-a")

    fm = markdown_parser.parse(tmp_path / "episodes" / f"{ep_id}.md").frontmatter
    assert fm["session_id"] == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert fm["harness"] == "claude-code"
    assert fm["project_dir"] == "/tmp/p"


def test_media_episode_without_a_session_is_byte_identical_to_before(tmp_path):
    from api.services.media_ingestor import MediaMeta, RawItem, write_media_episode

    ep_id = write_media_episode(
        tmp_path / "episodes", RawItem(url="https://example.com/a"),
        MediaMeta(title="A", media_type="url"), "media-a",
    )
    fm = markdown_parser.parse(tmp_path / "episodes" / f"{ep_id}.md").frontmatter
    assert "session_id" not in fm and "harness" not in fm and "project_dir" not in fm
