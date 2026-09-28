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


# --- Which Mac a declared device names (the one rule) ------------------------


def test_a_device_name_folds_case_dot_local_and_punctuation():
    from api.services.local_refs import fold_device

    assert fold_device("alex-mbp.local") == fold_device("Alex-MBP") == "alexmbp"
    assert fold_device("Alex’s MacBook Pro") == fold_device("Alexs-MacBook-Pro") == "alexsmacbookpro"
    assert fold_device(None) == fold_device("  ") == ""


def test_no_device_or_a_generic_word_is_this_mac(monkeypatch):
    from api.services import local_refs

    monkeypatch.setattr(local_refs, "this_device_names", lambda: frozenset({"alexmbp"}))
    for device in (None, "", "Mac", "this Mac", "my-mac", "localhost", "Laptop"):
        assert local_refs.is_this_device(device), device


def test_any_of_this_macs_names_matches_and_another_mac_does_not(monkeypatch):
    from api.services import local_refs

    monkeypatch.setattr(local_refs, "this_device_names", lambda: frozenset({"alexmbp", "alexsmacbookpro"}))
    assert local_refs.is_this_device("alex-mbp.local")
    assert local_refs.is_this_device("Alex’s MacBook Pro"), "the computer name, not only the host name"
    assert not local_refs.is_this_device("bob-example-mini")


def test_a_pinned_device_is_honoured_and_the_real_one_keeps_its_other_names(monkeypatch):
    from api.services import local_refs

    monkeypatch.setattr(local_refs, "current_device_id", lambda: "alex-mbp.local")
    monkeypatch.setattr(local_refs, "this_device_names", lambda: frozenset({"alexmbp", "alexsmacbookpro"}))
    assert local_refs.is_this_device("fake-host", "fake-host")
    assert not local_refs.is_this_device("alex-mbp", "fake-host"), "a test's pinned host is the only name"
    assert local_refs.is_this_device("Alex's MacBook Pro", "alex-mbp.local")


def test_same_device_compares_stamped_names_folded():
    from api.services.local_refs import same_device

    assert same_device("alex-mbp.local", "Alex-MBP")
    assert not same_device("alex-mbp", "bob-example-mini")
