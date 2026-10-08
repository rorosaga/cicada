"""F4 (scale-owner plan) — the entity card's payload never carries the claims fence as prose, and a page too large to
inline is served verbatim on demand. The owner page of a bank imported from a few years of chats is ~2.6 MB, 96% of it
one ```claims fence, and `GET /entities/{id}` shipped it twice (`markdown_content` and `raw_markdown`, ~6.4 MB) while
the app strips the fence from the prose in every view and reads the claims from `/claims`. Placeholder names only."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api import config, main
from api.routers import entities as entities_router
from api.services import bank_index, markdown_parser
from api.services.claims import Claim, write_claims


def _client(tmp_path: Path, monkeypatch, claims: int) -> tuple[TestClient, Path]:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    body = write_claims("## Summary\nThe owner.\n\n## Key Facts\nLikes rovers.\n",
                        [Claim(id=f"clm_{i}", text=f"Owner uses thing {i}", subject="owner-example", predicate="uses",
                               object=f"thing-{i}", valid_from="2024-01-01") for i in range(claims)])
    markdown_parser.write(memory / "entities" / "owner-example.md",
                          {"name": "Owner Example", "type": "person", "owner": True, "created": "2026-10-07",
                           "last_referenced": "2026-10-07"}, body)
    return TestClient(main.app), memory


def test_the_prose_never_carries_the_fence(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch, claims=3)
    with client:
        page = client.get("/entities/owner-example").json()
        context = client.get("/entities/owner-example/context").json()
    for prose in (page["markdownContent"], context["markdownContent"]):
        assert "```claims" not in prose and "Likes rovers." in prose and prose.startswith("## Summary")
    # A small page still arrives verbatim, fence included: the Source view is the file as it is on disk.
    raw = (memory / "entities" / "owner-example.md").read_text(encoding="utf-8")
    assert page["rawMarkdown"] == raw and page["rawOmitted"] is False


def test_a_page_too_large_to_inline_is_served_on_demand(tmp_path, monkeypatch):
    monkeypatch.setattr(entities_router, "RAW_INLINE_MAX_BYTES", 2_000)
    client, memory = _client(tmp_path, monkeypatch, claims=200)
    with client:
        page = client.get("/entities/owner-example")
        source = client.get("/entities/owner-example/raw")
        missing = client.get("/entities/no-such-page/raw")
    raw = (memory / "entities" / "owner-example.md").read_text(encoding="utf-8")   # after the lifespan's migrations
    assert len(raw.encode()) > 2_000
    data = page.json()
    assert data["rawMarkdown"] == "" and data["rawOmitted"] is True
    assert len(page.content) < 2_000, "the card's payload is the prose, not the fence"
    assert source.status_code == 200 and source.json() == {"id": "owner-example", "rawMarkdown": raw}
    assert missing.status_code == 404
