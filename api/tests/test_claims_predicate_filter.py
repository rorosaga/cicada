"""Owner 2026-10-09 — the entity card opens on the page and reads a person's "Works at" / "Role" beliefs alone
(`?predicate=`), never every belief on an owner-sized page (6 MB of claims in a synthetic bank of the measured size).
Placeholder names only."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, markdown_parser
from api.services.claims import Claim, write_claims


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    claims = [Claim(id=f"clm_use_{i}", text=f"Bob uses thing {i}", subject="bob-example", predicate="uses",
                    object=f"thing-{i}", valid_from="2024-01-01") for i in range(50)]
    claims += [
        Claim(id="clm_work_old", text="Bob works at Alpha", subject="bob-example", predicate="works-at",
              object="alpha-company", valid_from="2023-01-01", valid_to="2024-01-01", superseded_by="clm_work"),
        Claim(id="clm_work", text="Bob works at Beta", subject="bob-example", predicate="works-at",
              object="beta-company", valid_from="2024-01-01"),
        Claim(id="clm_role", text="Bob is an engineer", subject="bob-example", predicate="role", object="engineer",
              object_kind="literal", valid_from="2024-01-01"),
    ]
    body = write_claims("## Summary\nBob.\n", claims)
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "created": "2024-01-01",
                           "last_referenced": "2026-10-01"}, body)
    return TestClient(main.app)


def test_a_predicate_filter_returns_only_those_beliefs(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        facts = client.get("/entities/bob-example/claims",
                           params=[("predicate", "works-at"), ("predicate", "role"), ("predicate", "job-title")])
        everything = client.get("/entities/bob-example/claims")
        history = client.get("/entities/bob-example/claims",
                             params={"predicate": "works-at", "include_superseded": "true"})
        missing = client.get("/entities/no-such-page/claims", params={"predicate": "role"})
    assert facts.status_code == 200
    assert sorted(c["id"] for c in facts.json()["claims"]) == ["clm_role", "clm_work"], "current beliefs only"
    assert len(everything.json()["claims"]) == 52, "no filter is every current belief, as before"
    assert sorted(c["id"] for c in history.json()["claims"]) == ["clm_work", "clm_work_old"]
    assert len(facts.content) * 10 < len(everything.content)
    assert missing.status_code == 404
