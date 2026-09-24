"""Round 4 C3/C4 on the wire: a harness claim names the model and effort of the
turn it was written in; an assistant span names its turn's; a harness
contributor lists its models; the Reader's text names each agent turn's; every
read that now carries a model moves its ETag with `AUTHOR_SHAPE`. Synthetic."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, evidence, git_service, handshake, markdown_parser, search_index
from api.services import transclusion_resolver
from api.services.claims import Claim, Evidence, parse_claims, write_claims

SID = "22222222-3333-4444-8555-666666666666"
EP = "ep_2026-09-03_001"
BODY = ("user: Should alpha-project move to sqlite-vec?\n"
        "assistant: Yes — bob-example agreed last week.\n"
        "user: Then ship it.\n"
        "assistant: Shipped to example.com.")
STARTS = [0] + [i + 1 for i, ch in enumerate(BODY) if ch == "\n"]
SIDECAR = [
    {"offset": STARTS[0], "ts": "2026-09-03T10:00:00+00:00", "speaker": "user"},
    {"offset": STARTS[1], "ts": "2026-09-03T10:00:05+00:00", "speaker": "assistant",
     "model": "claude-opus-5-5", "effort": "xhigh"},
    {"offset": STARTS[2], "ts": "2026-09-03T10:05:00+00:00", "speaker": "user"},
    {"offset": STARTS[3], "ts": "2026-09-03T10:05:30+00:00", "speaker": "assistant",
     "model": "claude-sonnet-5", "effort": "low"},
]
QUOTE = "Yes — bob-example agreed last week."


def _span() -> Evidence:
    start = BODY.index(QUOTE)
    return Evidence(episode=EP, start=start, end=start + len(QUOTE), kind="assistant", hash=evidence.body_hash(BODY))


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "episodes" / f"{EP}.md", {
        "id": EP, "timestamp": "2026-09-03T10:00:00+00:00", "source": "claude-code", "origin": "claude-code",
        "title": "Sync race", "session_id": SID, "harness": "claude-code", "capture_kind": "transcript",
        "processed": True, "turns": SIDECAR}, BODY)
    page = memory / "entities" / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    claims = parse_claims(parsed.body) + [
        Claim(id="clm_alpha_agent", text="alpha-project uses sqlite-vec", subject="alpha-project", predicate="uses",
              object="sqlite-vec", observer="agent", valid_from="2026-09-03", recorded_at="2026-09-03",
              authored_by="claude-code", origin="mcp", session_id=SID, recorded_ts="2026-09-03T10:05:10Z",
              evidence=[_span()], source_episodes=[EP]),
        Claim(id="clm_alpha_sleep", text="alpha-project decided to ship", subject="alpha-project",
              predicate="decided", object="ship", observer="agent", valid_from="2026-09-03",
              recorded_at="2026-09-03", authored_by="gpt-5.4-mini", evidence=[_span()], source_episodes=[EP]),
    ]
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    bank_index.invalidate()
    search_index.ensure_fresh(memory, wait=True, max_age_s=0)  # `/projects` pins an ETag only when ready
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def test_the_claim_wire_names_the_turn_a_harness_write_happened_in(client):
    c, _ = client
    claims = {x["id"]: x for x in c.get("/entities/alpha-project/claims").json()["claims"]}
    agent, sleep = claims["clm_alpha_agent"], claims["clm_alpha_sleep"]
    assert (agent["authorKind"], agent["authorModel"], agent["authorEffort"], agent["recordedTs"]) == (
        "harness", "claude-sonnet-5", "low", "2026-09-03T10:05:10Z")
    assert (agent["evidence"][0]["model"], agent["evidence"][0]["effort"]) == ("claude-opus-5-5", "xhigh")
    assert (sleep["authorKind"], sleep["authorModel"], sleep["authorEffort"]) == ("model", None, None)
    assert sleep["evidence"][0]["model"] == "claude-opus-5-5"  # a span is its turn's, whoever cited it


def test_timeline_and_transclusion_serve_the_same_fields(client):
    c, _ = client
    [row] = c.get("/entities/alpha-project/timeline?predicate=uses&context=general").json()["claims"]
    assert (row["authorModel"], row["authorEffort"]) == ("claude-sonnet-5", "low")
    [tr] = c.get("/transclude?ref=claim:clm_alpha_agent").json()["claims"]
    assert (tr["authorModel"], tr["evidence"][0]["model"]) == ("claude-sonnet-5", "claude-opus-5-5")


def test_a_harness_contributor_lists_its_models(client):
    c, _ = client
    rows = {r["author"]: r for r in c.get("/entities/alpha-project/provenance").json()["contributors"]}
    assert rows["claude-code"]["models"] == [{"model": "claude-sonnet-5", "effort": "low", "beliefs": 1}]
    assert rows["gpt-5.4-mini"]["models"] == []


def test_the_reader_text_names_each_agent_turn(client):
    c, _ = client
    body = c.get(f"/episodes/{EP}/text").json()
    assert body["agent"] == {"model": "claude-sonnet-5", "effort": "low"}
    assert [(t["role"], t["model"], t["effort"]) for t in body["turns"]] == [
        ("user", None, None), ("assistant", "claude-opus-5-5", "xhigh"),
        ("user", None, None), ("assistant", "claude-sonnet-5", "low")]


def test_citations_carry_the_span_model(client):
    c, _ = client
    rows = c.get(f"/episodes/{EP}/citations").json()["citations"]
    assert {r["evidence"]["model"] for r in rows if r["kind"] == "assistant"} == {"claude-opus-5-5"}


def test_every_read_that_carries_a_model_moves_with_the_author_shape(client, monkeypatch):
    c, _ = client
    urls = (f"/episodes/{EP}/text", f"/episodes/{EP}/citations", "/entities/alpha-project/provenance",
            "/projects", "/projects/alpha-project/timeline")
    tags = {}
    for url in urls:
        tags[url] = c.get(url).headers.get("etag")
        assert tags[url], url
        assert c.get(url, headers={"If-None-Match": tags[url]}).status_code == 304, url
    monkeypatch.setattr(git_service, "AUTHOR_SHAPE", "shape-test")
    for url in urls:
        assert c.get(url, headers={"If-None-Match": tags[url]}).status_code == 200, url


def test_claim_to_model_cannot_forget_the_join():
    with pytest.raises(TypeError):
        transclusion_resolver.claim_to_model(Claim(id="c", text="t"))
