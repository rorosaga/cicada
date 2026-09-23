"""Track I T2 — one pipeline for every chat export (design §9.1, spec decision 13).

Synthetic exports only (``_intake_fixtures``); no network, no real bank.
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import HTTPException

from _intake_fixtures import (BOOKMARKS_HTML, CHAT_HTML, chatgpt_zip, claude_conversations,
                              claude_zip, gemini_activity_html, gemini_takeout_zip)
from api import config
from api.routers import conversations as conv
from api.routers import intake
from api.services import bank_registry, markdown_parser


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    return TestClient(main.app)


def _post(client, route, name, data, **params):
    body = data if isinstance(data, bytes) else data.encode()
    return client.post(route, params=params, files={"file": (name, body, "application/octet-stream")})


def _episodes(tmp_path):
    return {p.stem: markdown_parser.parse(p) for p in (tmp_path / "episodes").glob("*.md")}


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# --- parse_export: zips, skips, refusals (R-IA7, R-IA8) ---------------------


def test_a_claude_zip_parses_every_member_and_names_the_account_file():
    parsed = intake.parse_export(claude_zip(), "data-2026.zip")
    assert sorted(parsed.members) == ["conversations.json", "memories.json", "projects.json"]
    assert parsed.ignored == [{"name": "users.json", "reason": intake.SKIPPED_MEMBERS["users.json"]}]
    assert parsed.counts == {"conversations": 2, "memories": 2, "projects": 1}
    assert parsed.vendor == "claude" and parsed.format == "claude"
    assert {e["origin"] for e in parsed.episodes} == {"claude-export"}, "D2: every path stamps"


def test_a_chatgpt_zip_skips_its_known_extras_by_name_and_counts_the_rest():
    parsed = intake.parse_export(chatgpt_zip(), "export.zip")
    assert parsed.members == ["conversations.json"]
    assert sorted(i["name"] for i in parsed.ignored) == [
        "chat.html", "message_feedback.json", "model_comparisons.json",
        "shared_conversations.json", "user.json"]
    assert parsed.warnings == ["1 other file in the zip isn't a conversation (images, attachments, settings)."]
    assert {e["origin"] for e in parsed.episodes} == {"chatgpt-export"}


def test_a_gemini_takeout_zip_reads_only_gemini_activity():
    parsed = intake.parse_export(gemini_takeout_zip(), "takeout-2026.zip")
    assert parsed.vendor == "gemini" and parsed.counts == {"prompts": 2}
    assert {"name": "Search/MyActivity.html", "reason": intake.OTHER_ACTIVITY} in parsed.ignored
    assert {e["origin"] for e in parsed.episodes} == {"gemini-export"}


def test_chat_html_alone_is_refused_with_the_fix():
    with pytest.raises(HTTPException) as exc:
        intake.parse_export(CHAT_HTML.encode(), "chat.html")
    assert exc.value.status_code == 400 and exc.value.detail == intake.CHAT_HTML_REASON


def test_activity_for_another_product_alone_is_refused():
    page = gemini_activity_html((("example.com hours", None, "Jan 5, 2026, 9:00:00 AM PST"),),
                                product="Search", verb="Searched for")
    with pytest.raises(HTTPException) as exc:
        intake.parse_export(page.encode(), "MyActivity.html")
    assert exc.value.detail == intake.NOT_GEMINI_REASON


def test_a_bookmarks_page_is_not_a_chat_export():
    """D7: the `[soup]` fallback imported any page as role-less chat."""
    with pytest.raises(HTTPException) as exc:
        intake.parse_export(BOOKMARKS_HTML.encode(), "bookmarks.html")
    assert exc.value.detail == intake.NOT_A_CHAT_PAGE


def test_a_lone_account_file_is_a_quiet_skip():
    parsed = intake.parse_export(b'{"id": "user-1"}', "user.json")
    assert parsed.episodes == [] and parsed.ignored[0]["name"] == "user.json"


# --- Gemini (R-IA9) ----------------------------------------------------------


def test_the_gemini_parser_splits_prompt_from_reply_and_titles_by_the_prompt():
    [first, second] = sorted(conv.parse_gemini_myactivity(gemini_activity_html()),
                             key=lambda e: e["timestamp"], reverse=True)
    assert [(m["role"], m["text"]) for m in first["messages"]] == [
        ("user", "Summarize my alpha-project notes"), ("assistant", "Here is a summary of alpha-project.")]
    assert first["title"] == "Summarize my alpha-project notes"
    assert first["timestamp"] == "2026-02-24T12:39:02+00:00"
    assert [m["role"] for m in second["messages"]] == ["user"], "no reply, no assistant line"
    assert all(e["origin"] == "gemini-export" and e["legacy_hash"] for e in (first, second))


def test_a_takeout_reimported_after_the_parser_change_duplicates_nothing(tmp_path, monkeypatch):
    """R-IA9: stage the body the pre-T2 parser wrote, then import the same Takeout."""
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir(parents=True)
    for i, ep in enumerate(conv.parse_gemini_myactivity(gemini_activity_html())):
        # Takeout writes `Prompted&nbsp;` \u2014 a plain space here would hash differently.
        text = "Prompted\u00a0" + ep["messages"][0]["text"]
        if len(ep["messages"]) > 1:
            text += "\n\n" + ep["messages"][1]["text"]
        body = f"user: {text}"
        assert hashlib.sha256(body.encode()).hexdigest()[:12] == ep["legacy_hash"]
        markdown_parser.write(ep_dir / f"ep_2026-01-01_00{i + 1}.md",
                              {"id": f"ep_2026-01-01_00{i + 1}", "origin": "gemini-export", "source": "gemini_export",
                               "processed": True, "content_hash": ep["legacy_hash"]}, body)
    client = _client(tmp_path, monkeypatch)
    r = _post(client, "/intake/import", "MyActivity.html", gemini_activity_html())
    assert r.status_code == 200, r.text
    assert (r.json()["episodesStaged"], r.json()["duplicatesSkipped"]) == (0, 2)
    assert len(list(ep_dir.glob("*.md"))) == 2
    config.get_settings.cache_clear()


# --- plan() agrees with the stager (R-IA5) -----------------------------------


def test_plan_agrees_with_stage_for_new_grown_and_unchanged(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(3)), ep_dir)
    second = conv.parse_anthropic_conversations(claude_conversations(4, grown=True))
    predicted = intake.plan(second, tmp_path)
    assert (len(predicted.create), len(predicted.update), len(predicted.skip)) == (1, 1, 2)
    assert conv._stage_episodes(second, ep_dir) == (1, 1, 2), "plan and stage must never disagree"
    again = intake.plan(conv.parse_anthropic_conversations(claude_conversations(4, grown=True)), tmp_path)
    assert (len(again.create), len(again.update), len(again.skip)) == (0, 0, 4)


# --- the sniff stages nothing (G71 §4.3, R-IA11) ------------------------------


def test_the_sniff_writes_nothing_and_says_what_is_inside(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    before = _tree(tmp_path)
    r = _post(client, "/intake/sniff", "export.zip", claude_zip())
    assert r.status_code == 200, r.text
    assert _tree(tmp_path) == before, "a sniff must not write a byte"
    body = r.json()
    assert body["recognized"] and body["kind"] == "chat" and body["vendor"] == "claude"
    assert body["origin"] == "claude-export"
    assert body["counts"]["conversations"] == 2 and body["counts"]["memories"] == 2
    assert body["dateRange"] == {"from": "2026-01-10", "to": "2026-03-01"}
    assert body["delta"] == {"new": 5, "grown": 0, "unchanged": 0}
    assert body["ignored"][0]["name"] == "users.json"
    assert body["titles"][0]["date"] >= body["titles"][-1]["date"], "newest first"
    config.get_settings.cache_clear()


def test_the_sniff_caps_titles(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "MAX_SNIFF_TITLES", 1)
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "conversations.json", json.dumps(claude_conversations(3))).json()
    assert len(body["titles"]) == 1 and body["titlesTruncated"] is True
    config.get_settings.cache_clear()


def test_a_bookmarks_page_sniffs_as_saved_content(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "bookmarks.html", BOOKMARKS_HTML).json()
    assert body["recognized"] and body["kind"] == "saved" and body["counts"]["items"] == 2
    config.get_settings.cache_clear()


def test_a_lone_account_file_sniffs_as_a_quiet_skip(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "user.json", '{"id": "user-1"}').json()
    assert body["recognized"] is False and body["reason"] is None
    assert body["ignored"] == [{"name": "user.json", "reason": intake.SKIPPED_MEMBERS["user.json"]}]
    config.get_settings.cache_clear()


def test_an_unreadable_file_sniffs_with_its_reason(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "chat.html", CHAT_HTML).json()
    assert body["recognized"] is False and body["reason"] == intake.CHAT_HTML_REASON
    config.get_settings.cache_clear()


def test_another_products_activity_never_sniffs_as_saved_links(tmp_path, monkeypatch):
    """R-IA8 / FINAL_REFUSALS: a Search activity page carries <a href> links,
    which the saved-content parser would preview as bookmarks. The link below
    is what makes this test fail without the guard."""
    client = _client(tmp_path, monkeypatch)
    linked = '<a href="https://example.com/search?q=hours">example.com hours</a>'
    page = gemini_activity_html(((linked, None, "Jan 5, 2026, 9:00:00 AM PST"),),
                                product="Search", verb="Searched for")
    body = _post(client, "/intake/sniff", "MyActivity.html", page).json()
    assert body["recognized"] is False and body["kind"] == "unknown"
    assert body["reason"] == intake.NOT_GEMINI_REASON
    config.get_settings.cache_clear()


# --- import: origin, dates, no duplicates (G12, G20) --------------------------


def test_import_stamps_origin_keeps_dates_and_a_reimport_duplicates_nothing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    first = _post(client, "/intake/import", "export.zip", claude_zip()).json()
    assert (first["episodesStaged"], first["episodesUpdated"], first["duplicatesSkipped"]) == (5, 0, 0)
    assert first["vendor"] == "claude" and first["origin"] == "claude-export" and first["active"] is True
    eps = _episodes(tmp_path)
    assert {p.frontmatter["origin"] for p in eps.values()} == {"claude-export"}
    assert "ep_2026-02-01_001" in eps, "backdated to the conversation's own date"
    again = _post(client, "/intake/import", "export.zip", claude_zip()).json()
    assert (again["episodesStaged"], again["duplicatesSkipped"]) == (0, 5)
    assert len(_episodes(tmp_path)) == 5
    config.get_settings.cache_clear()


def test_a_grown_thread_is_updated_in_place(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _post(client, "/intake/import", "conversations.json", json.dumps(claude_conversations(2)))
    r = _post(client, "/intake/import", "conversations.json", json.dumps(claude_conversations(2, grown=True))).json()
    assert (r["episodesStaged"], r["episodesUpdated"], r["duplicatesSkipped"]) == (0, 1, 1)
    config.get_settings.cache_clear()


def test_import_into_an_unknown_bank_is_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert _post(client, "/intake/import", "export.zip", claude_zip(), bank="nope").status_code == 404
    config.get_settings.cache_clear()


# --- the shims (R-IA10) ------------------------------------------------------


def test_the_conversations_upload_shim_now_stamps_origin_and_is_deprecated(tmp_path, monkeypatch):
    """R7 §1.2 defect 1: a Claude export through `+` read "Unattributed"."""
    client = _client(tmp_path, monkeypatch)
    r = _post(client, "/conversations/upload", "conversations.json", json.dumps(claude_conversations(2)))
    assert r.status_code == 200 and r.headers["Deprecation"] == "true"
    assert r.json()["episodesCreated"] == 2 and r.json()["source"] == "Claude — Conversations"
    assert {p.frontmatter["origin"] for p in _episodes(tmp_path).values()} == {"claude-export"}
    zipped = _post(client, "/conversations/upload", "export.zip", chatgpt_zip())
    assert zipped.status_code == 200 and zipped.json()["episodesCreated"] == 2, "defect 3: zips accepted"
    gem = _post(client, "/conversations/upload", "MyActivity.html", gemini_activity_html())
    assert gem.json()["source"] == "Gemini — Activity", "defect 2: the Gemini parser, not ChatGPT's scraper"
    config.get_settings.cache_clear()


def test_the_banks_import_shim_keeps_its_shape_and_adds_vendor_and_origin(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Imports"})
    body = _post(client, "/banks/imports/import", "export.zip", claude_zip()).json()
    assert body["format"] == "claude" and body["episodesStaged"] == 5 and body["active"] is False
    assert body["vendor"] == "claude" and body["origin"] == "claude-export"
    config.get_settings.cache_clear()
