"""G166 — the `read_agent` ledger kind: ids, enums and numbers only, filed beside
`read` (so it never ticks the consumption domain), absent from every usage view."""
from __future__ import annotations

import json
from datetime import date

import pytest

from _reading_fixtures import PUBLIC, WALLED, ask, reading, record  # noqa: F401
from api.services import consumption_stats, telemetry


@pytest.fixture(autouse=True)
def _telemetry_on(monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")


def _rows():
    month = f"{date.today():%Y-%m}"
    path = telemetry.ledger_file(month, kind="read_agent")
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_read_row_carries_no_url_no_tool_no_note_no_text(reading):
    server, memory = reading
    ask(memory, PUBLIC)
    record(server, via="a secret-sounding tool name", note="a note the ledger must not keep")
    rows = [r for r in _rows() if r["kind"] == "read_agent"]
    assert len(rows) == 1
    (row,) = rows
    assert set(row["refs"]) == {"entity_id", "outcome", "host_class", "harness"}
    assert row["refs"]["outcome"] == "read" and row["refs"]["host_class"] == "public"
    text = json.dumps(row)
    for leak in ("bob-example", "http", "secret-sounding", "must not keep", "sqlite-vec"):
        assert leak not in text


def test_a_walled_needs_login_row_says_walled_and_names_no_host(reading):
    server, memory = reading
    ask(memory, WALLED)
    record(server, url=WALLED, outcome="needs_login")
    (row,) = [r for r in _rows() if r["kind"] == "read_agent"]
    assert row["refs"]["outcome"] == "needs_login" and row["refs"]["host_class"] == "walled"
    assert "x.com" not in json.dumps(row)


def test_the_kind_is_filed_beside_read_and_never_moves_the_consumption_component(reading, tmp_path):
    server, memory = reading
    from api.services import sync_service

    ask(memory, PUBLIC)
    before = sync_service.components(memory)["telemetry"]
    record(server)
    assert sync_service.components(memory)["telemetry"] == before
    assert telemetry.ledger_file("2026-09", kind="read_agent").name.startswith("reads-")
    assert "read_agent" in telemetry.KINDS and "read_agent" in telemetry.NON_SPEND_KINDS
    assert "read_agent" in telemetry.SIBLING_KINDS


def test_the_row_is_kept_out_of_every_usage_view(reading):
    server, memory = reading
    ask(memory, PUBLIC)
    record(server)
    events = telemetry.read_events()
    assert any(e.kind == "read_agent" for e in events)
    assert all(e.kind != "read_agent" for e in consumption_stats._activity(events))


def test_a_remote_row_carries_the_connector_id_and_still_no_url(reading):
    _, memory = reading
    from api.remote import catalog
    from api.remote.runtime import RemoteRuntime

    ask(memory, PUBLIC)
    runtime = RemoteRuntime(memory_path=lambda: memory, post=lambda p, d: {}, sleep_running=lambda: False)
    phone = catalog.Connector(id="aaaaaaaa", label="Phone", app="chatgpt", scopes=catalog.DEFAULT_SCOPES,
                              created_at="2026-09-01T00:00:00+00:00")
    runtime.call(phone, "cicada_record_read", {"url": PUBLIC, "outcome": "blocked"})
    row = next(r for r in _rows() if r["kind"] == "read_agent")
    assert row["refs"]["connector_id"] == "aaaaaaaa" and row["refs"]["harness"] == "chatgpt"
    assert "bob-example" not in json.dumps(row)
