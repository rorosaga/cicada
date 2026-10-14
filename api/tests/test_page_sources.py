"""Owner 2026-10-14 (G61) — `GET /entities/{id}/sources/overview`: where a page's knowledge comes from and how fresh it
is, in one bounded read — its sources with the beliefs each backs, the links its conversations named (and which
conversation), and those conversations by app. Synthetic bank under tmp_path; no network, no engine."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, markdown_parser as md, page_sources, provenance
from api.services import section_provenance as sp
from api.services.claims import Claim, Evidence, write_claims

SID = "44444444-5555-4666-8777-888888888888"
HOOK_A = "user: alpha-co employs bob-example now.\nassistant: Noted."
HOOK_B = "user: And alpha-co shipped the launch post."
IMPORT = "user: What does alpha-co use?\nassistant: It uses sqlite-vec."
EXPORT = "alpha-co is a company the person follows."

BODY = ("## Summary\nA company the person follows.\n\n"
        "## Key Facts\n- Employs bob-example.\n- Uses sqlite-vec.\n\n"
        "## Links\n"
        "- [Alpha Co](https://alpha-co.example/) — the official site\n"
        "- [Launch post](https://blog.example.net/launch) — how the launch went\n"
        "- https://news.example.com/alpha-co\n")


def _episode(memory: Path, ep_id: str, body: str, **fm) -> None:
    md.write(memory / "episodes" / f"{ep_id}.md", {"id": ep_id, **fm}, body)


def _claim(i: int, predicate: str, obj: str, ep: str, *, recorded: str, closed: bool = False) -> Claim:
    return Claim(id=f"clm_{predicate}_{i}", text=f"alpha-co {predicate} {obj}", subject="alpha-co",
                 predicate=predicate, object=obj, recorded_at=recorded, source_episodes=[ep],
                 valid_to="2026-09-01" if closed else None, superseded_by="clm_x" if closed else None)


def _build(memory: Path, *, employs: int = 5, extra_links: int = 0) -> Path:
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    _episode(memory, "ep_2026-09-01_001", HOOK_A, timestamp="2026-09-01T10:00:00+00:00", title="Team chat",
             session_id=SID, harness="claude-code", origin="claude-code")
    _episode(memory, "ep_2026-09-03_001", HOOK_B, timestamp="2026-09-03T10:00:00+00:00", title="Later",
             session_id=SID, harness="claude-code", origin="mcp")
    _episode(memory, "ep_2026-08-12_001", IMPORT, timestamp="2026-08-12T09:00:00+00:00", title="Planning notes",
             source_id="conv-import-1", origin="chatgpt-export")
    _episode(memory, "ep_2026-07-01_001", EXPORT, timestamp="2026-10-10T09:00:00+00:00", title="Memory",
             source="claude_memory", origin="claude-export")
    claims = [_claim(i, "employs", f"person-{i}", "ep_2026-09-01_001", recorded=f"2026-09-{i + 1:02d}")
              for i in range(employs)]
    claims += [_claim(99, "employs", "gone-example", "ep_2026-09-01_001", recorded="2026-08-01", closed=True),
               _claim(0, "uses", "sqlite-vec", "ep_2026-08-12_001", recorded="2026-08-12"),
               _claim(0, "website", "https://alpha-co.example/", "ep_2026-07-01_001", recorded="2026-07-01")]
    body = BODY + "".join(f"- [Extra {i}](https://extra{i}.example.com/) — more\n" for i in range(extra_links))
    # Section provenance: the launch post came from the hook conversation; Key Facts from the import.
    hook_ev = Evidence(episode="ep_2026-09-03_001", start=6, end=30, kind="user", hash=evidence.body_hash(HOOK_B))
    import_ev = evidence.reasoning("ep_2026-08-12_001", hash=evidence.body_hash(IMPORT))
    records: dict = {}
    for key, items in sp.scan(body).items():
        if key == "links":
            records[key] = {item.key: (item.text_hash, [hook_ev]) for item in items if "launch" in item.text}
        elif key == "key_facts":
            records[key] = {item.key: (item.text_hash, [import_ev]) for item in items}
    sources = [
        {"ref": "https://alpha-co.example/", "kind": "url", "predicate": "website", "added_by": "agent",
         "added_at": "2026-09-30", "verified": {"at": "2026-10-02", "how": "name+content"}},
        {"ref": "https://example.org/alpha-co/team", "kind": "url", "predicate": "employs", "added_by": "user",
         "added_at": "2026-10-01", "checked": {"at": "2026-10-05", "outcome": "unconfirmed"}},
        {"ref": "Ask bob-example", "kind": "note", "added_by": "user", "added_at": "2026-10-03"},
    ]
    page = memory / "entities" / "alpha-co.md"
    md.write(page, {"name": "Alpha Co", "type": "company", "status": "active", "sources": sources,
                    "source_episodes": ["ep_2026-09-01_001", "ep_2026-09-03_001", "ep_2026-07-01_001"], sp.FIELD: sp.encode(records)},
             write_claims(body, claims))
    return page


@pytest.fixture
def built(tmp_path: Path):
    memory = tmp_path / "memory"
    page = _build(memory)
    bank_index.invalidate()
    return memory, page


def test_each_source_carries_the_beliefs_it_backs_and_its_freshness(built):
    memory, page = built
    result = page_sources.overview(memory, page)
    site, team, note = result.sources
    assert (site.scope, team.scope, note.scope) == ("site", "fact", "page")
    # The official site backs the page's own `website` belief; its title is the page's own `## Links` title.
    assert site.site == "alpha-co.example" and site.title == "Alpha Co" and site.trusted
    assert [f.claim_id for f in site.facts] == ["clm_website_0"] and site.fact_count == 1
    # The team page backs the five CURRENT `employs` beliefs (the closed one is history), newest first, four shown.
    assert team.fact_count == 5 and len(team.facts) == page_sources.MAX_FACTS
    assert [f.claim_id for f in team.facts] == ["clm_employs_4", "clm_employs_3", "clm_employs_2", "clm_employs_1"]
    assert team.facts[0].predicate == "employs" and team.facts[0].context == "general"
    assert team.title is None and team.checked == {"at": "2026-10-05", "outcome": "unconfirmed"}
    # A note backs the page as a whole: no site, no facts listed.
    assert note.site is None and note.facts == [] and note.fact_count == 0
    assert result.last_checked == "2026-10-05"
    assert (result.facts_total, result.facts_with_source) == (7, 6)


def test_links_leave_out_the_sources_and_say_which_conversation_named_them(built):
    memory, page = built
    result = page_sources.overview(memory, page)
    assert result.links_total == 2
    launch, news = result.links
    assert (launch.url, launch.title, launch.note, launch.site) == (
        "https://blog.example.net/launch", "Launch post", "how the launch went", "example.net")
    came = launch.came_from
    assert came.episode == "ep_2026-09-03_001" and came.title == "Later" and came.available
    assert came.said == "2026-09-03T10:00:00+00:00" and came.evidence.kind == "user"
    assert (news.title, news.note, news.came_from) == ("", None, None)


def test_conversations_are_counted_like_provenance_and_tallied_by_app(built):
    memory, page = built
    result = page_sources.overview(memory, page).conversations
    totals = provenance.entity_provenance(memory, page).totals
    assert result.total == totals.conversations == 3
    # A memory export entry is facts, not activity: it never dates when the page was last said.
    assert (result.first_said, result.last_said) == (totals.first_said, totals.last_said)
    assert result.last_said == "2026-09-03T10:00:00+00:00"
    by_app = {(a.harness, a.origin): a for a in result.apps}
    hook = by_app[("claude-code", "mcp")]
    assert (hook.conversations, hook.facts, hook.passages) == (1, 5, 0)
    imported = by_app[(None, "chatgpt-export")]
    assert (imported.conversations, imported.facts, imported.passages) == (1, 1, 2)
    assert imported.last_said == "2026-08-12T09:00:00+00:00"
    export = by_app[(None, "claude-export")]
    assert export.last_said is None and export.facts == 1


def test_a_happening_or_a_withdrawal_record_is_never_a_fact_a_source_backs(tmp_path: Path):
    memory = tmp_path / "memory"
    page = _build(memory)
    parsed = md.parse(page)
    from api.services.claims import parse_claims

    claims = parse_claims(parsed.body)
    claims += [Claim(id="clm_event", text="alpha-co shipped v2", subject="alpha-co", predicate="milestone",
                     object="v2", recorded_at="2026-09-20", source_episodes=["ep_2026-09-01_001"]),
               Claim(id="clm_retract", text="withdrawn", subject="alpha-co", predicate="retracts",
                     object="clm_x", recorded_at="2026-09-21", source_episodes=["ep_2026-09-01_001"])]
    md.write(page, parsed.frontmatter, write_claims(BODY, claims))
    bank_index.invalidate()
    result = page_sources.overview(memory, page)
    assert (result.facts_total, result.facts_with_source) == (7, 6)
    hook = next(a for a in result.conversations.apps if a.harness == "claude-code")
    assert hook.facts == 5 and result.conversations.total == 3


def test_a_page_with_nothing_answers_empty(tmp_path: Path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    page = memory / "entities" / "beta-tool.md"
    md.write(page, {"name": "Beta tool", "type": "tool"}, "## Summary\nA tool.\n")
    bank_index.invalidate()
    result = page_sources.overview(memory, page)
    assert result.sources == [] and result.links == [] and result.links_total == 0
    assert result.conversations.total == 0 and result.conversations.apps == []
    assert (result.facts_total, result.facts_with_source, result.last_checked) == (0, 0, None)


def test_an_owner_sized_page_stays_bounded(tmp_path: Path):
    memory = tmp_path / "memory"
    page = _build(memory, employs=400, extra_links=60)
    bank_index.invalidate()
    result = page_sources.overview(memory, page)
    team = result.sources[1]
    assert team.fact_count == 400 and len(team.facts) == page_sources.MAX_FACTS
    assert len(result.links) == page_sources.MAX_LINKS and result.links_total == 62
    assert len(result.model_dump_json(by_alias=True)) < 16_000


def test_the_module_is_engine_free_and_never_fetches():
    tree = ast.parse(Path(page_sources.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {f"{node.module}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
    forbidden = ("litellm", "agent_engine", "providers", "vector_index", "link_enrichment", "net_guard", "httpx",
                 "urllib", "site_sources", "logo_service")
    assert not [n for n in names if any(f in n for f in forbidden)], names


# ---------- the route ----------


@pytest.fixture
def client_bank(tmp_path: Path, monkeypatch):
    memory = tmp_path / "memory"
    _build(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


def test_the_route_serves_camel_case_and_404s_the_unknown(client_bank):
    with TestClient(main.app) as client:
        ok = client.get("/entities/alpha-co/sources/overview")
        missing = client.get("/entities/no-such-page/sources/overview")
    assert ok.status_code == 200, ok.text
    assert missing.status_code == 404
    data = ok.json()
    assert data["entityId"] == "alpha-co" and data["entityType"] == "company"
    assert data["factsTotal"] == 7 and data["factsWithSource"] == 6 and data["linksTotal"] == 2
    team = data["sources"][1]
    assert team["factCount"] == 5 and team["facts"][0]["claimId"] == "clm_employs_4"
    assert team["addedBy"] == "user" and team["effectiveAccess"] == "unknown" and team["trusted"] is True
    assert data["links"][0]["cameFrom"]["episode"] == "ep_2026-09-03_001"
    assert data["conversations"]["total"] == 3 and data["conversations"]["apps"][0]["conversations"] == 1


def test_the_route_etag_304s_and_moves_when_the_page_changes(client_bank):
    url = "/entities/alpha-co/sources/overview"
    path = client_bank / "entities" / "alpha-co.md"
    with TestClient(main.app) as client:
        etag = client.get(url).headers["etag"]
        assert client.get(url, headers={"If-None-Match": etag}).status_code == 304
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.headers["etag"] != etag


def test_the_overview_follows_a_source_the_person_adds(client_bank):
    with TestClient(main.app) as client:
        added = client.post("/entities/alpha-co/sources",
                            json={"ref": "https://example.org/alpha-co/stack", "predicate": "uses"})
        assert added.status_code == 200, added.text
        data = client.get("/entities/alpha-co/sources/overview").json()
    stack = next(s for s in data["sources"] if s["ref"] == "https://example.org/alpha-co/stack")
    assert stack["scope"] == "fact" and stack["factCount"] == 1 and stack["facts"][0]["claimId"] == "clm_uses_0"
    assert data["factsWithSource"] == 7


def test_the_wire_matches_the_apps_fixture(built):
    """`fixtures/page_sources_overview.json` is what the app's `PageSourcesTests` decode: change the wire on one side
    only and the other goes red."""
    import json

    memory, page = built
    fixture = json.loads((Path(__file__).parent / "fixtures" / "page_sources_overview.json").read_text(encoding="utf-8"))
    served = page_sources.overview(memory, page).model_dump(mode="json", by_alias=True, exclude_none=True)
    assert served == fixture
