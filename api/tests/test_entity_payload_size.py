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
    assert data["rawOmitted"] is True
    assert raw.startswith(data["rawMarkdown"]) and "```claims" not in data["rawMarkdown"] and data["rawMarkdown"]
    assert len(page.content) < 2_000, "the card's payload is the prose, not the fence"
    assert source.status_code == 200 and source.json() == {"id": "owner-example", "rawMarkdown": raw}
    assert missing.status_code == 404


def _page_with_prose_after_the_fence(memory: Path, pad: int = 0) -> Path:
    body = write_claims("## Summary\nAlpha location.\n\n## Key Facts\n- A synthetic place.\n",
                        [Claim(id="clm_example", text="A synthetic belief.", subject="alpha-location", predicate="is-a",
                               object="location")])
    body += "\n## Key Facts\n- After the claims fence.\n" + (f"\n<!-- {'x' * pad} -->\n" if pad else "")
    page = memory / "entities" / "alpha-location.md"
    markdown_parser.write(page, {"name": "Alpha Location", "type": "location", "created": "2024-01-01",
                                 "last_referenced": "2024-01-01", "lat": 10.0, "lon": 20.0}, body)
    bank_index.invalidate()
    return page


def test_provenance_hashes_and_ranges_the_body_the_card_is_served(tmp_path, monkeypatch):
    """Review r1 #1: `pageBodyHash` and every section item's `bodyRanges` describe the exact `markdownContent`
    `/entities` serves — the prose without the fence — including an item after a closed claims fence."""
    from api.services import evidence

    client, memory = _client(tmp_path, monkeypatch, claims=1)
    _page_with_prose_after_the_fence(memory)
    with client:
        page = client.get("/entities/alpha-location").json()
        prov = client.get("/entities/alpha-location/provenance").json()
    body = page["markdownContent"]
    assert "```claims" not in body
    assert prov["pageBodyHash"] == evidence.body_hash(body)
    items = [item for section in prov["sections"] for item in section["items"]]
    assert any(item["text"] == "After the claims fence." for item in items)
    for item in items:
        assert "".join(body[a:b] for a, b in item["bodyRanges"]) == item["text"], item


def test_a_withheld_file_still_carries_its_frontmatter_and_prose(tmp_path, monkeypatch):
    """Review r1 #4: a page too large to inline keeps everything before its first claims fence verbatim in
    `rawMarkdown` — frontmatter readers (a location's declared lat/lon, a media block) never lose their input."""
    monkeypatch.setattr(entities_router, "RAW_INLINE_MAX_BYTES", 2_000)
    client, memory = _client(tmp_path, monkeypatch, claims=1)
    _page_with_prose_after_the_fence(memory, pad=5_000)
    with client:
        page = client.get("/entities/alpha-location").json()
    raw = (memory / "entities" / "alpha-location.md").read_text(encoding="utf-8")
    assert page["rawOmitted"] is True
    assert raw.startswith(page["rawMarkdown"]) and "```claims" not in page["rawMarkdown"]
    assert "lat: 10.0" in page["rawMarkdown"] and "lon: 20.0" in page["rawMarkdown"]


def test_the_served_prose_map_follows_every_fence():
    from api.services.claims import served_prose, strip_claims_block

    one = "```claims\n- id: a\n```\n"
    for body in ["Alpha.\n\n" + one + "Beta after.\n", one + "\nBeta first.\n", "A\n" + one + "B\n" + one + "C tail\n",
                 "No fence at all.\n"]:
        served, to_served = served_prose(body)
        assert served == strip_claims_block(body)
        for word in ("Alpha.", "Beta after.", "Beta first.", "C tail", "No fence at all.", "A\n", "B\n"):
            at = body.find(word)
            if at < 0 or word not in served:
                continue
            start, end = to_served(at), to_served(at + len(word))
            assert served[start:end] == word.strip() or served[start:end] == word, (body, word)
        if "```claims" in body:
            assert to_served(body.index("- id: a")) is None
