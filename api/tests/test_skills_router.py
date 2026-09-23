"""G138 — GET /skills/recommended over a tmp agent home."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api import main


def test_route_serves_camel_case_and_five_at_most():
    body = TestClient(main.app).get("/skills/recommended").json()
    assert body["maxShown"] == 5 and len(body["recommended"]) <= 5
    first = body["recommended"][0]
    assert {"sourceUrl", "state", "install", "agents", "needs"} <= set(first)
    assert first["install"]["claude-code"]["steps"][0]["argv"][0] in {"claude", "npx"}
