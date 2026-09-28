"""Hermetic tests for device-aware local file/folder references (backlog G27).

Covers:
- ``resolve_local_ref``: present file, missing file, present dir (``is_dir``),
  an "other device" reference (not stat'd, always ``exists=False``);
- ``extract_local_refs``: parses both documented syntaxes
  (``![[file:...|device:...]]`` and ``[label](file://...)``) out of an entity
  markdown body;
- ``GET /local-ref`` staying unmounted (no route stats a path the request
  names).

No real user paths — every filesystem check runs against ``tmp_path``. No
network, no live ``memory/``.
"""

from __future__ import annotations


from fastapi.testclient import TestClient

from api import config, main
from api.services import local_refs


# --- current_device_id -------------------------------------------------------


def test_current_device_id_is_nonempty_string():
    device = local_refs.current_device_id()
    assert isinstance(device, str)
    assert device


# --- resolve_local_ref --------------------------------------------------------


def test_resolve_present_file(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello", encoding="utf-8")

    result = local_refs.resolve_local_ref(str(f), None)

    assert result["path"] == str(f)
    assert result["exists"] is True
    assert result["is_dir"] is False
    assert result["status"] == "present"
    assert result["resolved_path"] == str(f)
    assert result["device"] == local_refs.current_device_id()


def test_resolve_missing_file(tmp_path):
    ghost = tmp_path / "does-not-exist.txt"

    result = local_refs.resolve_local_ref(str(ghost), None)

    assert result["exists"] is False
    assert result["is_dir"] is False
    assert result["status"] == "moved_or_missing"
    assert result["resolved_path"] is None


def test_resolve_present_directory(tmp_path):
    d = tmp_path / "some_folder"
    d.mkdir()

    result = local_refs.resolve_local_ref(str(d), None)

    assert result["exists"] is True
    assert result["is_dir"] is True
    assert result["status"] == "present"


def test_resolve_matching_device_is_stat_checked(tmp_path):
    f = tmp_path / "on-this-machine.txt"
    f.write_text("hi", encoding="utf-8")
    current = local_refs.current_device_id()

    result = local_refs.resolve_local_ref(str(f), current)

    assert result["status"] == "present"
    assert result["device"] == current


def test_resolve_other_device_not_stat_checked(tmp_path):
    # Even a real, existing path must NOT be reported as present when it's
    # tagged for a different device — we have no business stat'ing it.
    f = tmp_path / "exists-but-elsewhere.txt"
    f.write_text("hi", encoding="utf-8")

    result = local_refs.resolve_local_ref(str(f), "some-other-machine")

    assert result["status"] == "other_device"
    assert result["exists"] is False
    assert result["is_dir"] is False
    assert result["resolved_path"] is None
    assert result["device"] == "some-other-machine"


# --- extract_local_refs -------------------------------------------------------


def test_extract_wikilink_with_device():
    body = "See the writeup: ![[file:/Users/alice/thesis.pdf|device:alices-mbp]]"

    refs = local_refs.extract_local_refs(body)

    assert refs == [{"path": "/Users/alice/thesis.pdf", "device": "alices-mbp"}]


def test_extract_wikilink_without_device():
    body = "Local copy: ![[file:/Users/bob/notes.md]]"

    refs = local_refs.extract_local_refs(body)

    assert refs == [{"path": "/Users/bob/notes.md", "device": None}]


def test_extract_markdown_file_url_link():
    body = "The [PDF](file:///Users/carol/report.pdf) has details."

    refs = local_refs.extract_local_refs(body)

    assert refs == [{"path": "/Users/carol/report.pdf", "device": None}]


def test_extract_multiple_mixed_refs():
    body = (
        "First: ![[file:/a/b.txt|device:desktop]]\n"
        "Second: [link](file:///c/d.txt)\n"
        "Third: ![[file:/e/f.txt]]\n"
    )

    refs = local_refs.extract_local_refs(body)

    assert refs == [
        {"path": "/a/b.txt", "device": "desktop"},
        {"path": "/e/f.txt", "device": None},
        {"path": "/c/d.txt", "device": None},
    ]


def test_extract_no_refs_returns_empty_list():
    assert local_refs.extract_local_refs("Just a plain note, nothing local here.") == []


# --- no route stats a path the request names -------------------------------


def test_no_route_stats_a_path_the_request_names(tmp_path, monkeypatch):
    """`GET /local-ref?path=` stat'd any path a caller supplied and had no
    caller in the app; it is gone. Only the app reads the person's Mac."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    f = tmp_path / "present.txt"
    f.write_text("hi", encoding="utf-8")

    resp = TestClient(main.app).get("/local-ref", params={"path": str(f)})

    assert resp.status_code == 404
