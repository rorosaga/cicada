"""G118 slice 2 — `GET /entities/{id}/provenance`: who wrote an entity's beliefs,
which conversations fed it, the best quote from each, and how many beliefs
carry an exact quote at all (design §4.5 / §4.8.4). Synthetic fixtures; git
histories are throwaway repos with hand-built trailers.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, bank_registry, demo_bank, evidence, git_service, markdown_parser, provenance
from api.services.claims import Claim, Evidence, EVIDENCE_KINDS, write_claims

SID = "33333333-4444-4555-8666-777777777777"
HOOK = ("user: Should alpha-project move to sqlite-vec?\n"
        "assistant: Yes, bob-example moved alpha-project onto sqlite-vec last week.")
FOLLOW = "user: One more thing about alpha-project."
IMPORT = "user: What does alpha-project index with?\nassistant: It uses sqlite-vec."
LEGACY = "user: Alpha Project needs a new logo."
MEDIA = "## Summary\nSaved.\n\n## Description\nA guide to sqlite-vec for alpha-project."


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _episode(memory: Path, ep_id: str, body: str, **fm) -> None:
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", {"id": ep_id, **fm}, body)


def _span(text: str, quote: str, doc: str, kind: str) -> Evidence:
    s = text.index(quote)
    return Evidence(episode=doc, start=s, end=s + len(quote), kind=kind, hash=evidence.body_hash(text))


def _build(memory: Path) -> Path:
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    _episode(memory, "ep_2026-09-01_001", HOOK, timestamp="2026-09-01T10:00:00+00:00", title="Sync race",
             session_id=SID, harness="claude-code", origin="claude-code", capture_kind="transcript", turns=2)
    _episode(memory, "ep_2026-09-02_001", FOLLOW, timestamp="2026-09-02T10:00:00+00:00", title="Later title",
             session_id=SID, origin="mcp")
    _episode(memory, "ep_2026-08-12_001", IMPORT, timestamp="2026-08-12T09:00:00+00:00", title="Planning notes",
             source_id="conv-import-1", origin="chatgpt-export")
    _episode(memory, "ep_2026-08-01_001", LEGACY, timestamp="2026-08-01T09:00:00+00:00", title="Logo")
    markdown_parser.write(memory / "entities" / "media-example-org.md",
                          {"name": "Example guide", "type": "media", "decay_class": "evergreen"},
                          write_claims(MEDIA, []))
    media_text = evidence.source_text(memory, "media-example-org")
    claims = [
        Claim(id="clm_1", text="alpha-project uses sqlite-vec", subject="alpha-project", predicate="uses",
              object="sqlite-vec", authored_by="claude-sonnet-4-5", recorded_at="2026-09-01",
              source_episodes=["ep_2026-09-01_001"], session_ids=[SID],
              evidence=[_span(HOOK, "moved alpha-project onto sqlite-vec", "ep_2026-09-01_001", "assistant")]),
        Claim(id="clm_2", text="alpha-project indexes with sqlite-vec", subject="alpha-project",
              authored_by="gpt-5.4-mini", recorded_at="2026-08-12", source_episodes=["ep_2026-08-12_001"],
              evidence=[Evidence(episode="ep_2026-08-12_001", start=46, end=62, kind="assistant",
                                 hash="deadbeefcafe")]),
        Claim(id="clm_3", text="alpha-project needs a logo", subject="alpha-project", authored_by="user",
              recorded_at="2026-08-01", source_episodes=["ep_2026-08-01_001"]),
        Claim(id="clm_4", text="alpha-project is ongoing", subject="alpha-project",
              authored_by="claude-sonnet-4-5", recorded_at="2026-09-02",
              evidence=[Evidence(episode="ep_2026-09-02_001", kind="reasoning", hash=evidence.body_hash(FOLLOW))]),
        Claim(id="clm_5", text="alpha-project used LEANN", subject="alpha-project", authored_by="gpt-5.4-mini",
              recorded_at="2026-07-01", valid_to="2026-09-01", superseded_by="clm_1",
              source_episodes=["ep_2026-08-12_001"]),
        Claim(id="clm_6", text="alpha-project has a sqlite-vec guide", subject="alpha-project",
              authored_by="gpt-5.4-mini", recorded_at="2026-08-20",
              evidence=[_span(media_text, "A guide to sqlite-vec", "media-example-org", "page")]),
    ]
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project", "status": "active",
                                 "source_episodes": ["ep_2026-08-01_001", "ep_2026-09-01_001"]},
                          write_claims("# Alpha Project\n", claims))
    return page


@pytest.fixture
def built(tmp_path: Path):
    memory = tmp_path / "memory"
    page = _build(memory)
    bank_index.invalidate()
    return memory, page


# ---------- the payload ----------


def test_counts_cover_the_current_claims_only(built):
    memory, page = built
    result = provenance.entity_provenance(memory, page)
    assert (result.entity_id, result.entity_name, result.entity_type) == ("alpha-project", "Alpha Project", "project")
    t = result.totals
    assert (t.claims, t.with_span, t.legacy, t.conversations) == (5, 3, 1, 3)  # clm_5 is superseded (R-PB6)
    assert result.inferred_count == 1
    assert [(p.entity_id, p.name, p.claim_count) for p in result.pages] == [("media-example-org", "Example guide", 1)]


def test_conversations_group_by_session_then_import_identity(built):
    memory, page = built
    rows = provenance.entity_provenance(memory, page).conversations
    assert [r.conversation_id for r in rows] == [SID, "conv-import-1", None]
    live = rows[0]
    assert live.episode_ids == ["ep_2026-09-01_001", "ep_2026-09-02_001"]
    assert live.episode_id == "ep_2026-09-02_001" and live.timestamp == "2026-09-02T10:00:00+00:00"
    assert (live.title, live.harness, live.origin, live.claim_count) == ("Sync race", "claude-code", "mcp", 2)
    assert rows[1].claim_count == 1 and rows[2].episode_ids == ["ep_2026-08-01_001"]
    assert all(r.available for r in rows)


def test_conversation_order_is_by_instant_not_by_string(tmp_path):
    """G114 R2: a bank holds `+02:00`, `Z` and `+00:00` stamps side by side and
    lexical order across them is wrong, so a conversation's first and newest
    episodes are chosen by instant (`episode_ids.timestamp_sort_key`)."""
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    # 01:00+02:00 is 23:00Z the day before: EARLIER than 23:30Z, though it sorts later as a string.
    _episode(memory, "ep_2026-09-02_001", "user: alpha-project first.", timestamp="2026-09-02T01:00:00+02:00",
             title="First", session_id=SID)
    _episode(memory, "ep_2026-09-01_001", "user: alpha-project second.", timestamp="2026-09-01T23:30:00+00:00",
             title="Second", session_id=SID)
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project",
                                 "source_episodes": ["ep_2026-09-01_001", "ep_2026-09-02_001"]}, "# A\n")
    bank_index.invalidate()
    [row] = provenance.entity_provenance(memory, page).conversations
    assert row.episode_ids == ["ep_2026-09-02_001", "ep_2026-09-01_001"]
    assert (row.title, row.episode_id, row.timestamp) == ("First", "ep_2026-09-01_001", "2026-09-01T23:30:00+00:00")


def test_the_best_quote_is_asserted_then_derived_then_stale(built):
    memory, page = built
    live, imported, legacy = provenance.entity_provenance(memory, page).conversations
    b = live.best
    assert (b.kind, b.derived, b.stale, b.grown) == ("assistant", False, False, False)
    assert HOOK[b.start:b.end] == "moved alpha-project onto sqlite-vec"
    s, e = b.mention_offsets[0]
    assert b.excerpt[s:e] == "moved alpha-project onto sqlite-vec" and b.excerpt_start + s == b.start
    # clm_2's span is stale; a name match in the same conversation outranks it (R-PB8).
    assert (imported.best.kind, imported.best.derived) == ("derived", True)
    assert IMPORT[imported.best.start:imported.best.end] == "alpha-project"
    assert legacy.best.derived is True and LEGACY[legacy.best.start:legacy.best.end] == "Alpha Project"


def test_a_stale_span_with_no_name_match_shows_words_but_no_wash(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    _episode(memory, "ep_2026-09-04_001", "user: Nothing relevant is said here.",
             timestamp="2026-09-04T09:00:00+00:00")
    page = memory / "entities" / "zeta-example.md"
    markdown_parser.write(page, {"name": "Zeta Example", "type": "person"}, write_claims("# Zeta\n", [
        Claim(id="clm_z", text="z", subject="zeta-example", source_episodes=["ep_2026-09-04_001"],
              evidence=[Evidence(episode="ep_2026-09-04_001", start=6, end=13, kind="user", hash="deadbeefcafe")])]))
    bank_index.invalidate()
    best = provenance.entity_provenance(memory, page).conversations[0].best
    assert best.stale is True and best.start is None and best.end is None  # R-PB2
    assert best.mention_offsets == [] and best.excerpt


def test_a_conversation_that_continued_keeps_its_exact_quote(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    first = "user: Should alpha-project move to sqlite-vec?"
    _episode(memory, "ep_2026-09-05_001", first, timestamp="2026-09-05T09:00:00+00:00", session_id=SID)
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project"}, write_claims("# A\n", [
        Claim(id="clm_g", text="g", subject="alpha-project", source_episodes=["ep_2026-09-05_001"],
              evidence=[_span(first, "move to sqlite-vec", "ep_2026-09-05_001", "user")])]))
    _episode(memory, "ep_2026-09-05_001", first + "\nassistant: Done.",
             timestamp="2026-09-05T09:00:00+00:00", session_id=SID)
    bank_index.invalidate()
    best = provenance.entity_provenance(memory, page).conversations[0].best
    assert (best.grown, best.stale, best.derived, best.kind) == (True, False, False, "user")
    s, e = best.mention_offsets[0]
    assert best.excerpt[s:e] == "move to sqlite-vec"


def test_a_legacy_only_entity_still_says_where_it_came_from(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    _episode(memory, "ep_2026-08-01_001", LEGACY, timestamp="2026-08-01T09:00:00+00:00")
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project",
                                 "source_episodes": ["ep_2026-08-01_001", "ep_2026-01-01_009"]}, "# Alpha\n")
    bank_index.invalidate()
    result = provenance.entity_provenance(memory, page)
    assert result.totals.claims == 0 and result.totals.conversations == 2
    found = {r.episode_id: r for r in result.conversations}
    assert found["ep_2026-08-01_001"].best.derived is True and found["ep_2026-08-01_001"].claim_count == 0
    gone = found["ep_2026-01-01_009"]
    assert gone.available is False and gone.best is None and gone.title == ""


def test_derived_is_a_read_only_kind():
    assert "derived" not in EVIDENCE_KINDS  # R-PB9: never stored
    assert Evidence.from_dict({"episode": "ep_x", "start": 1, "end": 4, "kind": "derived"}).kind == "reasoning"


def test_fifty_claims_across_twenty_episodes_stay_in_budget(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    bodies: dict[str, str] = {}
    for i in range(20):
        ep = f"ep_2026-08-{i + 1:02d}_001"
        body = f"user: note {i} about alpha-project and sqlite-vec.\nassistant: noted {i}."
        _episode(memory, ep, body, timestamp=f"2026-08-{i + 1:02d}T09:00:00+00:00", title=f"Note {i}",
                 session_id=f"ses_2026-08-{i + 1:02d}_00000000")
        bodies[ep] = body
    claims = []
    for j in range(50):
        ep = f"ep_2026-08-{j % 20 + 1:02d}_001"
        claims.append(Claim(id=f"clm_{j:03d}", text=f"claim {j}", subject="alpha-project",
                            authored_by="claude-sonnet-4-5", recorded_at=f"2026-08-{j % 20 + 1:02d}",
                            source_episodes=[ep], evidence=[_span(bodies[ep], "sqlite-vec", ep, "user")]))
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project", "source_episodes": sorted(bodies)},
                          write_claims("# Alpha Project\n", claims))
    bank_index.invalidate()
    provenance.entity_provenance(memory, page)  # warm bank_index, as a running backend is
    calls: list[str] = []
    real = markdown_parser.parse
    monkeypatch.setattr(markdown_parser, "parse", lambda p: (calls.append(Path(p).name), real(p))[1])
    t0 = time.perf_counter()
    result = provenance.entity_provenance(memory, page)
    elapsed = time.perf_counter() - t0
    assert (result.totals.claims, result.totals.with_span, result.totals.conversations) == (50, 50, 20)
    assert len(calls) <= 21, calls  # the page + at most one body read per episode; no frontmatter re-parse
    assert elapsed < 1.0  # smoke bound; the 150 ms design budget is measured by the orchestrator


def test_the_demo_bank_answers_with_an_exact_quote(tmp_path):
    bank = tmp_path / "demo"
    bank_registry.scaffold_bank(bank)
    demo_bank.populate(bank)
    bank_index.invalidate()
    counts, truncated = asyncio.run(git_service.entity_commit_authors(bank, "alpha-project"))
    result = provenance.entity_provenance(bank, bank / "entities" / "alpha-project.md",
                                          commit_authors=counts, commits_truncated=truncated)
    assert result.totals.with_span >= 1
    assert any(c.best is not None and not c.best.derived and not c.best.stale for c in result.conversations)
    assert sum(c.commits for c in result.contributors) >= 1


# ---------- contributors (git) ----------


@pytest.fixture
def repo(tmp_path: Path):
    memory = tmp_path / "memory"
    page = _build(memory)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "--", ".")
    _git(memory, "commit", "-q", "-m", git_service.build_commit_message(
        "Sleep cycle 2026-09-01",
        ["entities/alpha-project.md: created (source: ep_2026-09-01_001, trigger: sleep/extraction)"],
        authors=["claude-sonnet-4-5"]))
    with page.open("a", encoding="utf-8") as fh:
        fh.write("\nEdited by hand.\n")
    _git(memory, "commit", "-q", "-am", git_service.build_commit_message(
        "Manual edit", ["entities/alpha-project.md: updated (trigger: user/manual_edit)"], authors=["user"]))
    with page.open("a", encoding="utf-8") as fh:
        fh.write("Legacy line.\n")
    _git(memory, "commit", "-q", "-am", "legacy commit without trailers")
    with (memory / "entities" / "media-example-org.md").open("a", encoding="utf-8") as fh:
        fh.write("\nMore.\n")
    _git(memory, "commit", "-q", "-am", git_service.build_commit_message(
        "Enrich", ["entities/media-example-org.md: updated"], authors=["gpt-5.4-mini"]))
    bank_index.invalidate()
    return memory, page


def test_commit_counts_come_from_the_pages_own_trailers(repo):
    memory, _page = repo
    counts, truncated = asyncio.run(git_service.entity_commit_authors(memory, "alpha-project"))
    assert counts == {"claude-sonnet-4-5": 1, "user": 1, "unknown": 1} and truncated is False
    newest, cut = asyncio.run(git_service.entity_commit_authors(memory, "alpha-project", limit=1))
    assert newest == {"unknown": 1} and cut is True


def test_no_git_means_no_commits_not_an_error(built):
    memory, _page = built
    assert asyncio.run(git_service.entity_commit_authors(memory, "alpha-project")) == ({}, False)


def test_contributors_merge_claim_and_commit_authors(repo):
    memory, page = repo
    counts, truncated = asyncio.run(git_service.entity_commit_authors(memory, "alpha-project"))
    result = provenance.entity_provenance(memory, page, commit_authors=counts, commits_truncated=truncated)
    by = {c.author: c for c in result.contributors}
    assert (by["claude-sonnet-4-5"].claims, by["claude-sonnet-4-5"].commits) == (2, 1)
    assert (by["gpt-5.4-mini"].claims, by["gpt-5.4-mini"].commits) == (2, 0)
    assert (by["user"].claims, by["user"].commits) == (1, 1)
    assert (by["unknown"].claims, by["unknown"].commits) == (0, 1)
    assert (by["claude-sonnet-4-5"].kind, by["claude-sonnet-4-5"].provider) == ("model", "anthropic")
    assert (by["gpt-5.4-mini"].kind, by["gpt-5.4-mini"].provider) == ("model", "openai")
    assert (by["user"].kind, by["user"].provider) == ("user", None)
    assert [c.author for c in result.contributors][:2] == ["claude-sonnet-4-5", "gpt-5.4-mini"]


def test_history_rows_carry_the_same_author_identity(repo):
    memory, _page = repo
    entries = asyncio.run(git_service.get_entity_history("alpha-project", memory))
    kinds = {e.author: (e.author_kind, e.author_provider) for e in entries}
    assert kinds["claude-sonnet-4-5"] == ("model", "anthropic")
    assert kinds["user"] == ("user", None) and kinds["unknown"] == ("unknown", None)


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
        ok = client.get("/entities/alpha-project/provenance")
        missing = client.get("/entities/no-such-entity/provenance")
    assert ok.status_code == 200, ok.text
    assert missing.status_code == 404
    data = ok.json()
    assert data["entityId"] == "alpha-project" and data["inferredCount"] == 1
    assert data["totals"] == {"claims": 5, "withSpan": 3, "legacy": 1, "conversations": 3}
    assert data["conversations"][0]["claimCount"] == 2
    assert "mentionOffsets" in data["conversations"][0]["best"] and data["commitsTruncated"] is False


def test_the_route_etag_304s_and_moves_with_an_episode(client_bank):
    url = "/entities/alpha-project/provenance"
    path = client_bank / "episodes" / "ep_2026-08-12_001.md"
    with TestClient(main.app) as client:
        etag = client.get(url).headers["etag"]
        assert client.get(url, headers={"If-None-Match": etag}).status_code == 304
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.headers["etag"] != etag


def test_claims_carry_author_identity_sessions_and_recorded_at(client_bank):
    with TestClient(main.app) as client:
        claims = {c["id"]: c for c in client.get("/entities/alpha-project/claims").json()["claims"]}
    c1 = claims["clm_1"]
    assert (c1["authorKind"], c1["authorProvider"], c1["sessionIds"], c1["recordedAt"]) == (
        "model", "anthropic", [SID], "2026-09-01")
    assert (claims["clm_3"]["authorKind"], claims["clm_3"]["authorProvider"]) == ("user", None)


def test_transcluded_claims_carry_the_same_author_identity(client_bank):
    """`/transclude` builds its claims through the same function as `/claims`
    (R-PB13), so an embedded claim never ships without its author fields."""
    with TestClient(main.app) as client:
        payload = client.get("/transclude", params={"ref": "claim:clm_1"}).json()
    [c] = payload["claims"]
    assert (c["authorKind"], c["authorProvider"], c["sessionIds"], c["recordedAt"]) == (
        "model", "anthropic", [SID], "2026-09-01")
