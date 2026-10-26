"""Report a problem (tester readiness, 2026-10-26): the diagnostics text never carries the home path, an email, a URL,
a bank's name, a page's name or a conversation's words — only versions, an engine enum, source ids and redacted logs.

Synthetic values only (made-up names, ``example.com`` hosts, a scratch HOME under tmp_path)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api import config, main
from api.services import diagnostics as dx

HOME = "/Users/ada-example"


def r(text: str, **kw) -> str:
    return dx.redact(text, **{"home": HOME, "bank_names": ["chats-alpha", "work"], **kw})


def test_the_home_path_becomes_a_tilde_and_another_accounts_home_is_withheld():
    assert r(f"open {HOME}/cicada/memory/settings.yaml failed") == "open ~/cicada/memory/settings.yaml failed"
    assert "ada-example" not in r(f"cwd={HOME}")
    assert r("read /Users/bob-example/notes.txt") == "read /Users/[user]/notes.txt"
    assert r("read /home/bob-example/x") == "read /home/[user]/x"


def test_the_resolved_and_private_forms_of_a_scratch_home_are_redacted_too(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    resolved = str(home.resolve())
    out = dx.redact(f"a {resolved}/x b /private{resolved.removeprefix('/private')}/y", home=home)
    assert resolved not in out and "~/x" in out and "~/y" in out


def test_emails_and_urls_are_withheld():
    out = r("sent to ada@example.com, fetched https://example.com/p/ada?token=1 and www.example.org/me")
    assert "@" not in out and "example.com" not in out and "example.org" not in out
    assert out.count(dx.URL) == 2 and dx.EMAIL in out


def test_bank_names_are_withheld_as_whole_words_only():
    out = r("switched to chats-alpha; work bank ok; network fine; chats-alpha-2 stays")
    assert "chats-alpha;" not in out and out.startswith("switched to [bank];")
    assert "[bank] bank ok" in out
    assert "network fine" in out, "a bank name inside another word is left alone"
    assert "chats-alpha-2" in out, "a longer id is another thing"


def test_page_names_conversation_words_and_bank_paths_are_withheld():
    out = r("promoted 'Bob Example' from \"we met at the cafe\" → [[bob-example]] wrote entities/bob-example.md "
            "and episodes/ep_2026-10-26_001.md")
    for leak in ("Bob Example", "we met", "bob-example", "ep_2026-10-26_001"):
        assert leak not in out, leak
    assert "entities/…" in out and "episodes/…" in out and "[[…]]" in out


def test_a_request_line_keeps_its_route_and_drops_the_id():
    line = 'INFO:     127.0.0.1:52345 - "GET /entities/bob-example/card HTTP/1.1" 200 OK'
    assert r(line) == 'INFO:     127.0.0.1:52345 - "GET /entities/… HTTP/1.1" 200 OK'
    assert r('"GET /healthz HTTP/1.1" 200') == '"GET /healthz HTTP/1.1" 200'


def test_secrets_go_through_the_one_scrubber():
    out = r("key sk-abcdefghijklmnopqrstuvwx and code: 482913")
    assert "sk-abc" not in out and "482913" not in out


def _logs(tmp_path: Path) -> Path:
    logs = tmp_path / "home" / ".cicada" / "logs"
    logs.mkdir(parents=True)
    (logs / "backend.log").write_text("\n".join([
        "10:00:00 | INFO    | api.main — started",
        f"10:00:01 | WARNING | api.services.x — could not read {tmp_path}/home/cicada/memory/entities/bob-example.md",
        "10:00:02 | ERROR   | api.services.y — fetch https://example.com/ada failed for 'Bob Example'",
        'INFO:     127.0.0.1:1 - "GET /episodes/ep_2026-10-26_001 HTTP/1.1" 200 OK',
    ]) + "\n")
    (logs / "update.log").write_text("checked for updates: none\n")
    return logs


def test_the_report_names_versions_the_engine_and_source_ids_and_carries_redacted_logs(tmp_path):
    logs = _logs(tmp_path)
    text = dx.build(version="9.9.9", engine_mode="auto", sources_on=["x", "calendar-local", "x"], bank_count=2,
                    bank_names=["chats-alpha"], home=tmp_path / "home", dirs=[logs])
    assert "Backend: 9.9.9" in text and "Engine mode: auto" in text
    assert "Sources on: calendar-local, x" in text and "Memories (banks): 2" in text
    assert "Recent warnings and errors (2):" in text
    assert "checked for updates: none" in text
    for leak in (str(tmp_path), "bob-example", "Bob Example", "example.com", "ep_2026-10-26_001", "chats-alpha"):
        assert leak not in text, leak


def test_the_report_bounds_the_lines_and_survives_missing_logs(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "backend.log").write_text("".join(f"line {i}\n" for i in range(50)))
    text = dx.build(version="1", engine_mode="", sources_on=[], bank_count=0, bank_names=[], home=None, dirs=[logs],
                    lines=5)
    assert "line 44" not in text and "line 49" in text and "last 5 lines" in text
    empty = dx.build(version="1", engine_mode="", sources_on=[], bank_count=0, bank_names=[], home=None,
                     dirs=[tmp_path / "none"])
    assert "not found" in empty and "Sources on: none" in empty and "Engine mode: unknown" in empty


def test_the_endpoint_serves_the_text_with_no_store(tmp_path, monkeypatch):
    from _synthetic_bank import _bank

    memory = _bank(tmp_path, git=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))   # the log's paths sit under the person's home, as they do live
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home" / ".cicada"))
    monkeypatch.setenv("CICADA_LOG_DIR", str(_logs(tmp_path)))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            resp = client.get("/diagnostics/report", params={"lines": 10})
            too_many = client.get("/diagnostics/report", params={"lines": dx.MAX_LINES + 1})
    finally:
        config.get_settings.cache_clear()
    assert resp.status_code == 200 and resp.headers["cache-control"] == "no-store"
    assert resp.text.startswith("Backend: ") and "Engine mode: " in resp.text
    assert "bob-example" not in resp.text and str(tmp_path) not in resp.text
    assert too_many.status_code == 422
