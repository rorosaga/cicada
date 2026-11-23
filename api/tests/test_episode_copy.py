"""What a click on a queued episode copies, and the day its row shows (owner 2026-10-05)."""
from __future__ import annotations

from api.services import episode_copy, markdown_parser


def test_a_page_copies_its_link():
    assert episode_copy.copy_target({"id": "ep_1", "url": "https://example.com/a", "origin": "safari-tab"}) == (
        "link", "https://example.com/a")


def test_a_captured_conversation_copies_its_session_id():
    fm = {"id": "ep_2", "origin": "claude-code", "session_id": "0f3c-session", "harness": "claude-code"}
    assert episode_copy.copy_target(fm) == ("conversation", "0f3c-session")


def test_a_tab_group_copies_its_links_once_each_in_order():
    body = "Group: alpha\n- Docs https://example.com/docs.\n- https://example.org/x\n- again https://example.com/docs"
    kind, text = episode_copy.copy_target({"id": "ep_3", "origin": "chrome-tab-group"}, body)
    assert kind == "links" and text == "https://example.com/docs\nhttps://example.org/x"
    assert episode_copy.copy_target({"id": "ep_4", "origin": "chrome-tab-group"},
                                    "only https://example.net/one") == ("link", "https://example.net/one")


def test_a_folder_file_copies_its_full_path_from_the_registry_or_its_relative_one():
    fm = {"id": "ep_5", "origin": "folder", "folder_id": "notes-abc123", "relpath": "plans/q4.md"}
    assert episode_copy.copy_target(fm, folder_root=lambda fid: "/tmp/notes" if fid == "notes-abc123" else None) == (
        "path", "/tmp/notes/plans/q4.md")
    assert episode_copy.copy_target(fm, folder_root=lambda fid: None) == ("path", "plans/q4.md")


def test_anything_else_copies_the_episode_id():
    assert episode_copy.copy_target({"id": "ep_6", "origin": "telegram"}) == ("episode", "ep_6")


def test_a_conversation_shows_its_last_capture_and_anything_else_when_it_was_added():
    convo = {"session_id": "s", "timestamp": "2026-09-01T10:00:00Z", "captured_at": "2026-10-04T18:30:00Z"}
    assert episode_copy.changed_at(convo) == "2026-10-04T18:30:00Z"
    assert episode_copy.changed_at({"timestamp": "2026-09-01T10:00:00Z", "captured_at": "2026-10-04T18:30:00Z"}) == (
        "2026-09-01T10:00:00Z")


def test_sleep_episodes_carries_what_a_click_copies_and_the_rows_day(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main
    from api.config import Settings

    memory = tmp_path / "bank"
    (memory / "episodes").mkdir(parents=True)
    markdown_parser.write(memory / "episodes" / "ep_2026-10-01_001.md",
                          {"id": "ep_2026-10-01_001", "timestamp": "2026-10-01T09:00:00Z", "origin": "codex",
                           "source": "codex", "session_id": "sess-42", "captured_at": "2026-10-03T12:00:00Z",
                           "processed": False}, "user: hi")
    markdown_parser.write(memory / "episodes" / "ep_2026-10-02_001.md",
                          {"id": "ep_2026-10-02_001", "timestamp": "2026-10-02T09:00:00Z", "source": "url",
                           "url": "https://example.com/read", "processed": False}, "a page")
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    rows = {row["id"]: row for row in TestClient(main.app).get("/sleep/episodes").json()}

    convo = rows["ep_2026-10-01_001"]
    assert (convo["copyKind"], convo["copyValue"], convo["changedAt"]) == ("conversation", "sess-42",
                                                                          "2026-10-03T12:00:00Z")
    page = rows["ep_2026-10-02_001"]
    assert (page["copyKind"], page["copyValue"], page["changedAt"]) == ("link", "https://example.com/read",
                                                                       "2026-10-02T09:00:00Z")


# --- where the original opens (owner 2026-11-23) ---------------------------------------------------------------

SESSION = "0f3c2a10-1111-4222-8333-444455556666"


def test_a_note_opens_in_notes_and_a_page_at_its_link():
    note = {"id": "ep_1", "origin": "apple-notes", "note_id": "x-coredata://ABC-123/ICNote/p42"}
    assert episode_copy.open_target(note) == ("note", "x-coredata://ABC-123/ICNote/p42")
    assert episode_copy.open_target({"note_id": "tell app \"Finder\""}) is None, "only Notes' own id form"
    assert episode_copy.open_target({"url": "https://example.com/a", "origin": "chrome-bookmark"}) == (
        "web", "https://example.com/a")
    assert episode_copy.open_target({"url": "file:///etc/passwd"}) is None, "only an http(s) link"


def test_only_a_claude_code_session_with_a_real_id_resumes():
    fm = {"session_id": SESSION, "harness": "claude-code", "origin": "claude-code"}
    assert episode_copy.open_target(fm) == ("session", SESSION)
    assert episode_copy.open_target({**fm, "harness": "codex"}) is None, "no launcher for another harness"
    assert episode_copy.open_target({**fm, "session_id": "ses_minted"}) is None, "a minted id resumes nothing"


def test_an_imported_conversation_opens_its_page_at_its_provider():
    assert episode_copy.open_target({"source": "chatgpt", "source_id": SESSION}) == (
        "web", f"https://chatgpt.com/c/{SESSION}")
    assert episode_copy.open_target({"source": "claude", "source_id": SESSION.upper()}) == (
        "web", f"https://claude.ai/chat/{SESSION}")
    assert episode_copy.open_target({"source": "claude", "source_id": f"claude-project:{SESSION}"}) is None
    assert episode_copy.open_target({"source": "gemini_export", "source_id": SESSION}) is None


def test_a_folder_file_opens_only_with_its_full_path_and_a_chat_names_nothing():
    fm = {"origin": "folder", "folder_id": "notes-abc123", "relpath": "plans/q4.md"}
    assert episode_copy.open_target(fm, folder_root=lambda fid: "/tmp/notes") == ("file", "/tmp/notes/plans/q4.md")
    assert episode_copy.open_target(fm, folder_root=lambda fid: None) is None, "a relative path shows nothing in Finder"
    assert episode_copy.open_target({"origin": "chrome-tab-group"}, "one https://example.net/one") == (
        "web", "https://example.net/one")
    assert episode_copy.open_target({"origin": "chrome-tab-group"}, "https://a.example/ https://b.example/") is None
    assert episode_copy.open_target({"origin": "imessage", "conversation": "ab" * 16}) is None
