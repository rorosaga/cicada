"""Hermetic tests for the device id (backlog G27) and the rail around it.

Covers:
- ``current_device_id``: always a non-empty string;
- ``local_refs`` stays a device-id module: the existence oracle
  (``resolve_local_ref``) and the body parser (``extract_local_refs``) had no
  caller and are gone, so nothing here can stat a declared path;
- ``GET /local-ref`` staying unmounted (no route stats a path the request
  names).

No real user paths. No network, no live ``memory/``.
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


def test_the_existence_oracle_is_gone():
    """The backend never stats a folder the person declared; the app does."""
    assert not hasattr(local_refs, "resolve_local_ref")
    assert not hasattr(local_refs, "extract_local_refs")


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
