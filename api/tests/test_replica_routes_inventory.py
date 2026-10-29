"""G132 phase 1 B — every write a replica could be asked for is classified, by hand (ruling 51a): every non-GET REST
route in `replica_routes` (forward / capture / refuse / local), every cli_map tool row by its `replica` column (home /
local). A new route or row fails here until someone decides where it runs on a copy. No catch-all."""
from __future__ import annotations

from fastapi.routing import APIRoute

from api.services import cli_map, replica_routes


def _routes() -> set[str]:
    from api.main import app

    return {f"{m} {r.path}" for r in app.routes if isinstance(r, APIRoute) for m in r.methods
            if m not in ("GET", "HEAD")}


def test_every_non_get_route_is_classified_and_none_is_stale():
    routes = _routes()
    assert sorted(routes - set(replica_routes.ROUTES)) == [], "classify the new route in replica_routes.ROUTES"
    assert sorted(set(replica_routes.ROUTES) - routes) == [], "a stale replica_routes entry"
    assert set(replica_routes.ROUTES.values()) <= replica_routes.CLASSES


def test_the_classes_follow_their_rules():
    r = replica_routes.ROUTES
    # Bank lifecycle, devices, the remote listener and publishing are never done by a copy.
    for key, cls in r.items():
        if key.split(" ", 1)[1].startswith(("/banks", "/devices", "/remote", "/agent-api", "/sync/publish", "/v1")):
            assert cls == replica_routes.REFUSE, key
    # Sleep's controls are the home's ("Sleep now" pressed anywhere is a transaction to the home).
    assert all(cls == replica_routes.FORWARD for key, cls in r.items() if key.split(" ", 1)[1].startswith("/sleep"))
    # What is captured waits in the outbox while the home is away.
    for key in ("POST /capture/note", "POST /capture/file", "POST /capture/session", "POST /capture/turn",
                "POST /sources/save"):
        assert r[key] == replica_routes.CAPTURE
    # A credential for a source the home holds is never sent across.
    assert all(cls == replica_routes.REFUSE for key, cls in r.items() if "/credentials" in key)
    assert replica_routes.GET_FROM_HOME == {"GET /sleep/status"}


def test_every_tool_row_says_where_it_runs_on_a_copy():
    for row in cli_map.ROWS:
        if not row.tool:
            continue
        assert row.replica_side in ("home", "local"), row.tool
        if row.mutates:
            assert row.replica_side == "home", f"{row.tool} writes: it must go to the home"
    # Reads of the stores the home keeps outside every bank go there too.
    by_tool = cli_map.by_tool()
    for tool in ("cicada_video_queue", "cicada_reading_queue", "cicada_explore_queue"):
        assert by_tool[tool].replica_side == "home"
    for tool in ("cicada_recall", "cicada_recall_detail", "cicada_handshake", "cicada_ask", "cicada_timeline"):
        assert by_tool[tool].replica_side == "local"
