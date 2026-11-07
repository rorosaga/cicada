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
    assert "chats-alpha-2" not in out and "[id] stays" in out, "a longer id is not the bank, but it is an id"


# Review of #482: lines that passed through the first redact() unchanged. Synthetic names only.
KNOWN = ["alice-smith", "Alice Smith", "Ali S.", "beta-project"]


def rk(text: str) -> str:
    return dx.redact(text, home=HOME, bank_names=["chats-alpha"], names=KNOWN)


def test_bare_page_file_names_are_withheld():
    out = rk("inbox resolve aborted — unparseable claims in alice-smith.md: bad yaml")
    assert "alice-smith" not in out and "[file].md" in out
    assert "carla-example" not in rk("split carla-example.claims.jsonl and dana.yaml")
    assert "dana" not in rk("split carla-example.claims.jsonl and dana.yaml")
    assert "settings.yaml" in rk("could not read settings.yaml"), "Cicada's own files keep their name"


def test_a_known_page_id_is_withheld_wherever_it_stands():
    assert rk("ValueError: entity not found: alice-smith") == "ValueError: entity not found: [name]"
    assert "beta" not in rk("merged Beta-Project into the hub")


def test_a_pending_name_and_its_parenthesised_name_are_withheld():
    out = rk("10:00:00 | WARNING | promotion: held alice-smith (Alice Smith) 1 conversation")
    assert "alice" not in out.lower() and "Smith" not in out and "1 conversation" in out
    # Not known to the bank yet: the slug shape and the capitalised parenthesis still go.
    out = rk("promotion: held erin-example (Erin Example) 1 conversation")
    assert "erin" not in out.lower() and "([…])" in out


def test_a_url_is_cut_only_at_whitespace_and_an_encoded_email_is_decoded_first():
    out = rk("GET https://x.com/a?token=abc123secret&email=a%40b.com done")
    assert out == "GET [url] done"
    assert "@" not in rk("sent to a%40b.example.com") and dx.EMAIL in rk("sent to a%40b.example.com")


def test_another_accounts_home_with_a_space_and_a_windows_home_are_withheld():
    assert rk("open /Users/Ana Example/notes/x.txt") == "open /Users/[user]/notes/x.txt"
    assert rk(r"open C:\Users\ana.example\Documents\x.txt") == r"open C:\Users\[user]\Documents\x.txt"
    assert rk("open C:/Users/ana.example/x.txt") == "open C:/Users/[user]/x.txt"


def test_a_line_where_a_name_survives_keeps_only_its_structure():
    red = dx.Redactor(home=HOME, names=KNOWN)
    # A known full name inside a longer word survives the token rules; the line is withheld, its structure kept.
    assert red.line("10:00:00 | ERROR   | api.services.inbox_service — failed for Alice Smithson now") == \
        "10:00:00 | ERROR   | api.services.inbox_service — " + dx.WITHHELD
    assert red.line("KeyError: Alice Smithson") == "KeyError: " + dx.WITHHELD
    assert red.line("odd line about Alice Smithson") == dx.WITHHELD
    assert red.line('  File "/x/api/services/y.py", line 12, in run') == '  File "/x/api/services/y.py", line 12, in run'
    assert red.line("10:00:00 | INFO    | api.main — started") == "10:00:00 | INFO    | api.main — started"


def test_ids_on_the_keep_list_stay():
    assert dx.redact("seen claude-code and calendar-local", keep=["claude-code", "calendar-local"]) == \
        "seen claude-code and calendar-local"


def test_the_bank_names_known_are_its_pages_aliases_and_waiting_names(tmp_path):
    from _synthetic_bank import _bank
    from api.services import pending_store

    memory = _bank(tmp_path, git=False)
    pending_store.upsert(memory, pending_store.PendingEntity(name="Erin Example", type="person", description="", source_episode="ep_2026-10-26_001", confidence=0.5, tags=[], history_entries=[], aliases=["Erin E."]))
    known = dx.bank_names_known(memory)
    assert {"alpha-project", "bob-example", "Erin Example", "Erin E."} <= known


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
        "10:00:03 | ERROR   | api.services.z — Concise Summaries not found",
    ]) + "\n")
    (logs / "update.log").write_text("checked for updates: none\n")
    return logs


def test_the_report_names_versions_the_engine_and_source_ids_and_carries_redacted_logs(tmp_path):
    logs = _logs(tmp_path)
    text = dx.build(version="9.9.9", engine_mode="auto", sources_on=["x", "calendar-local", "x"], bank_count=2,
                    bank_names=["chats-alpha"], home=tmp_path / "home", dirs=[logs])
    assert "Backend: 9.9.9" in text and "Engine mode: auto" in text
    assert "Sources on: calendar-local, x" in text and "Memories (banks): 2" in text
    assert "Recent warnings and errors (3):" in text
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
    # The bank's own page names are loaded once and withheld: `concise-summaries` is the synthetic bank's skill page.
    assert "Concise Summaries" not in resp.text and "api.services.z" in resp.text
    assert too_many.status_code == 422


def test_the_coverage_reports_are_served_ids_and_enums_only(tmp_path, monkeypatch):
    """Vision items 1-2 (2026-10-28): `GET /diagnostics/coverage/{pictures|sources}` for the active bank."""
    from _synthetic_bank import _bank

    memory = _bank(tmp_path, git=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home" / ".cicada"))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            pictures = client.get("/diagnostics/coverage/pictures")
            sources = client.get("/diagnostics/coverage/sources", params={"ids": "true"})
            unknown = client.get("/diagnostics/coverage/everything")
    finally:
        config.get_settings.cache_clear()
    assert pictures.status_code == 200 and pictures.headers["cache-control"] == "no-store"
    assert pictures.json()["by_type"]["person"]["none"] == {"no_identifier": 1}
    assert "Bob Example" not in pictures.text and "ids" not in pictures.json()
    assert sources.json()["ids"]["none/person"] == ["bob-example"]
    assert unknown.status_code == 404
