"""G48 — grouping episodes into conversations.

Hermetic: throwaway banks under tmp_path, a fake transcript root under tmp_path,
and an injected `transcript_exists`. The real ~/.claude is never touched, and no
transcript is ever opened — this module only ever calls os.path.isfile.
"""

from __future__ import annotations

import pytest

from api.services import bank_index, session_stats

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
UUID_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def _episode(memory, episode_id, *, timestamp, session_id=None, source_id=None,
             harness=None, project_dir=None, origin=None, title="Untitled"):
    episodes_dir = memory / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {episode_id}", f"timestamp: '{timestamp}'",
             f"title: {title}", "processed: true"]
    for key, value in (("session_id", session_id), ("source_id", source_id),
                       ("harness", harness), ("project_dir", project_dir),
                       ("origin", origin)):
        if value is not None:
            lines.append(f"{key}: {value}")
    lines += ["---", "", "body"]
    (episodes_dir / f"{episode_id}.md").write_text("\n".join(lines), encoding="utf-8")


def _entity(memory, entity_id, source_episodes, *, claim_session_id=None):
    entities_dir = memory / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    eps = ("\n" + "\n".join(f"- {e}" for e in source_episodes)) if source_episodes else " []"
    body = f"---\nid: {entity_id}\ntype: concept\nstatus: active\n" \
           f"source_episodes:{eps}\n---\n\n# {entity_id}\n"
    if claim_session_id is not None:
        # A direct `cicada_write_claim` against an EXISTING entity: the claim
        # carries the writing session, but frontmatter source_episodes is
        # untouched (mirrors agentic_write.write_claim's real behavior).
        body += (
            "\n```claims\n"
            f"- id: clm_{entity_id}_test\n"
            f"  text: \"{entity_id} test claim\"\n"
            f"  subject: {entity_id}\n"
            f"  session_id: {claim_session_id}\n"
            "```\n"
        )
    (entities_dir / f"{entity_id}.md").write_text(body, encoding="utf-8")


@pytest.fixture(autouse=True)
def _fresh_index():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


def _never(_project_dir, _session_id, *, root=None):
    return False


# --- grouping ----------------------------------------------------------------


def test_no_episodes_dir_is_an_empty_list(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    assert session_stats.aggregate_conversations(memory, transcript_exists=_never) == []


def test_episodes_group_by_session_id_and_count(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A, title="First")
    _episode(memory, "ep_2", timestamp="2026-08-30T12:00:00Z", session_id=UUID_A, title="Second")
    _episode(memory, "ep_3", timestamp="2026-08-29T09:00:00Z", session_id=UUID_B, title="Other")

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=_never)}

    assert rows[UUID_A]["episode_count"] == 2
    assert rows[UUID_A]["kind"] == "mcp"
    assert rows[UUID_A]["title"] == "First", "title comes from the EARLIEST episode"
    assert rows[UUID_A]["first_seen"] == "2026-08-30T10:00:00Z"
    assert rows[UUID_A]["last_seen"] == "2026-08-30T12:00:00Z"


def test_an_import_thread_groups_on_source_id_and_is_kind_import(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", source_id="uuid-abc",
             origin="claude-export", title="Thesis planning")

    row = session_stats.aggregate_conversations(memory, transcript_exists=_never)[0]
    assert row["conversation_id"] == "uuid-abc"
    assert row["kind"] == "import"
    assert row["origin"] == "claude-export"
    assert row["resumable"] is False


def test_session_id_wins_when_an_episode_carries_both_keys(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z",
             session_id=UUID_A, source_id="uuid-abc")

    rows = session_stats.aggregate_conversations(memory, transcript_exists=_never)
    assert [r["conversation_id"] for r in rows] == [UUID_A]
    assert rows[0]["kind"] == "mcp"


def test_an_episode_with_neither_key_simply_does_not_appear(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z")
    assert session_stats.aggregate_conversations(memory, transcript_exists=_never) == []


def test_rows_are_sorted_by_last_seen_descending(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-28T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-31T10:00:00Z", session_id=UUID_B)

    rows = session_stats.aggregate_conversations(memory, transcript_exists=_never)
    assert [r["conversation_id"] for r in rows] == [UUID_B, UUID_A]


def test_limit_truncates_after_sorting(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-28T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-31T10:00:00Z", session_id=UUID_B)

    rows = session_stats.aggregate_conversations(memory, limit=1, transcript_exists=_never)
    assert [r["conversation_id"] for r in rows] == [UUID_B]


def test_harness_and_project_dir_come_from_the_stamped_episodes(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p", origin="mcp")

    row = session_stats.aggregate_conversations(memory, transcript_exists=_never)[0]
    assert row["harness"] == "claude-code"
    assert row["origin"] == "mcp"
    assert "project_dir" not in row, "project_dir never crosses /conversations/recent"


# --- entity credit -----------------------------------------------------------


def test_entities_are_credited_transitively_through_source_episodes(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-30T11:00:00Z", session_id=UUID_B)
    _entity(memory, "sqlite-vec", ["ep_1", "ep_2"])
    _entity(memory, "cicada", ["ep_1"])
    _entity(memory, "ghost", ["ep_missing"])

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=_never)}

    assert rows[UUID_A]["entity_ids"] == ["cicada", "sqlite-vec"]
    assert rows[UUID_A]["entity_count"] == 2
    assert rows[UUID_B]["entity_ids"] == ["sqlite-vec"]


# --- PR #20 review fix: episode-less direct writes still credit the entity --


def test_a_claims_session_id_credits_the_entity_with_no_source_episode(tmp_path):
    # A direct cicada_write_claim against an EXISTING entity: no source
    # episode, so frontmatter source_episodes stays empty — only the claim's
    # own session_id records which conversation touched it.
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    _entity(memory, "mongodb", [], claim_session_id=UUID_A)

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=_never)}

    assert rows[UUID_A]["entity_ids"] == ["mongodb"]
    assert rows[UUID_A]["entity_count"] == 1


def test_source_episodes_and_claim_session_credit_the_same_entity_once(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    _entity(memory, "mongodb", ["ep_1"], claim_session_id=UUID_A)

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=_never)}

    assert rows[UUID_A]["entity_ids"] == ["mongodb"], "no duplicate credit for the same conversation"


def test_a_claim_session_id_from_an_unknown_conversation_credits_nothing(tmp_path):
    # No episode anywhere carries this session, so there is no conversation
    # row to attach the entity to — never manufacture a phantom row from a
    # claim alone.
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    _entity(memory, "mongodb", [], claim_session_id=UUID_B)

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=_never)}

    assert rows[UUID_A]["entity_ids"] == []
    assert UUID_B not in rows


def test_entity_ids_are_capped_with_an_honest_total(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    for i in range(30):
        _entity(memory, f"e{i:02d}", ["ep_1"])

    row = session_stats.aggregate_conversations(memory, transcript_exists=_never)[0]
    assert len(row["entity_ids"]) == session_stats.MAX_CONVERSATION_ENTITIES
    assert row["entity_count"] == 30


# --- slug + resumable --------------------------------------------------------


def test_project_slug_maps_every_non_alphanumeric_char_to_a_dash():
    assert session_stats.project_slug("/Users/rorosaga/Documents/roros_lab/cicada") == \
        "-Users-rorosaga-Documents-roros-lab-cicada"


def test_project_slug_handles_a_path_containing_a_dot():
    # Asserted from the "every non-alphanumeric -> '-'" rule. VERIFIED LIVE in
    # Task 6 of this plan; if the observation differs, Task 6 corrects BOTH
    # project_slug and this test.
    assert session_stats.project_slug("/Users/x/a.b/c") == "-Users-x-a-b-c"


def test_transcript_exists_is_isfile_only_under_the_injected_root(tmp_path):
    root = tmp_path / "projects"
    slug_dir = root / "-Users-x-p"
    slug_dir.mkdir(parents=True)
    (slug_dir / f"{UUID_A}.jsonl").write_text("", encoding="utf-8")

    assert session_stats.default_transcript_exists("/Users/x/p", UUID_A, root=root) is True
    assert session_stats.default_transcript_exists("/Users/x/p", UUID_B, root=root) is False
    assert session_stats.default_transcript_exists(None, UUID_A, root=root) is False


def test_a_subagent_transcript_directory_is_not_a_session(tmp_path):
    root = tmp_path / "projects"
    (root / "-Users-x-p" / f"{UUID_A}" / "subagents").mkdir(parents=True)
    assert session_stats.default_transcript_exists("/Users/x/p", UUID_A, root=root) is False


def test_a_minted_ses_id_is_never_resumable_even_with_a_file_present(tmp_path):
    root = tmp_path / "projects"
    slug_dir = root / "-Users-x-p"
    slug_dir.mkdir(parents=True)
    (slug_dir / "ses_2026-08-31_deadbeef.jsonl").write_text("", encoding="utf-8")

    assert session_stats.default_transcript_exists(
        "/Users/x/p", "ses_2026-08-31_deadbeef", root=root
    ) is False


def test_resumable_uses_the_injected_probe(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p")
    _episode(memory, "ep_2", timestamp="2026-08-30T10:00:00Z", session_id=UUID_B,
             harness="claude-code", project_dir="/Users/x/p")

    def only_a(project_dir, session_id, *, root=None):
        return session_id == UUID_A

    rows = {r["conversation_id"]: r
            for r in session_stats.aggregate_conversations(memory, transcript_exists=only_a)}
    assert rows[UUID_A]["resumable"] is True
    assert rows[UUID_B]["resumable"] is False


# --- model (reserved) --------------------------------------------------------


def test_model_is_reserved_and_always_none(tmp_path):
    # Nothing records a model against a conversation id yet, so the row must
    # say so honestly rather than joining a ledger that can't answer. The key
    # stays present so the app's decode is unchanged.
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)

    row = session_stats.aggregate_conversations(memory, transcript_exists=_never)[0]
    assert "model" in row
    assert row["model"] is None


def test_aggregating_reads_no_telemetry_ledger(tmp_path, monkeypatch):
    # Guards the M1 fix: a per-request 90-day ledger scan for a structurally
    # null field is exactly what was removed.
    from api.services import telemetry

    def _boom(*_a, **_kw):
        raise AssertionError("conversation rows must not read the telemetry ledger")

    monkeypatch.setattr(telemetry, "read_events", _boom)
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)

    assert session_stats.aggregate_conversations(memory, transcript_exists=_never)


# --- find_conversation -------------------------------------------------------


def test_find_conversation_returns_the_project_dir(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p")

    found = session_stats.find_conversation(memory, UUID_A)
    assert found is not None and found["project_dir"] == "/Users/x/p"
    assert session_stats.find_conversation(memory, UUID_B) is None


# --- GET /conversations/recent ----------------------------------------------


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.routers import conversations as conv

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(conv, "transcript_exists", _never)
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_recent_endpoint_returns_camel_case_rows(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p", title="Index choice")
    _entity(memory, "sqlite-vec", ["ep_1"])
    bank_index.invalidate()

    resp = client.get("/conversations/recent")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list) and len(body) == 1
    row = body[0]
    assert row["conversationId"] == UUID_A
    assert row["kind"] == "mcp"
    assert row["harness"] == "claude-code"
    assert row["title"] == "Index choice"
    assert row["episodeCount"] == 1
    assert row["entityIds"] == ["sqlite-vec"]
    assert row["entityCount"] == 1
    assert row["resumable"] is False
    assert "projectDir" not in row, "project_dir must never cross this endpoint"


def test_recent_endpoint_honours_limit(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-28T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-31T10:00:00Z", session_id=UUID_B)
    bank_index.invalidate()

    body = client.get("/conversations/recent?limit=1").json()
    assert [r["conversationId"] for r in body] == [UUID_B]


def test_recent_endpoint_304s_on_an_unchanged_bank(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    bank_index.invalidate()

    first = client.get("/conversations/recent")
    etag = first.headers["ETag"]
    second = client.get("/conversations/recent", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""


def test_a_different_limit_gets_a_different_etag(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    bank_index.invalidate()

    a = client.get("/conversations/recent?limit=5").headers["ETag"]
    b = client.get("/conversations/recent?limit=20").headers["ETag"]
    assert a != b


def test_recent_rows_carry_a_null_model(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    bank_index.invalidate()

    row = client.get("/conversations/recent").json()[0]
    assert "model" in row and row["model"] is None


# --- GET /conversations/{id} -------------------------------------------------


def test_by_id_returns_the_same_row_shape_as_recent(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A,
             harness="claude-code", project_dir="/Users/x/p", title="Index choice")
    _entity(memory, "sqlite-vec", ["ep_1"])
    bank_index.invalidate()

    resp = client.get(f"/conversations/{UUID_A}")
    assert resp.status_code == 200, resp.text
    row = resp.json()
    assert row == client.get("/conversations/recent").json()[0]
    assert row["conversationId"] == UUID_A
    assert row["entityIds"] == ["sqlite-vec"]
    assert "projectDir" not in row, "project_dir must never cross this endpoint"


def test_by_id_finds_a_conversation_that_recent_truncated_away(tmp_path, monkeypatch):
    # THE M2 BUG: the popover used to resolve ids inside a capped /recent page,
    # so an aged conversation looked like data loss. By-id sees the whole bank.
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-01T10:00:00Z", session_id=UUID_A)
    _episode(memory, "ep_2", timestamp="2026-08-31T10:00:00Z", session_id=UUID_B)
    bank_index.invalidate()

    recent = client.get("/conversations/recent?limit=1").json()
    assert [r["conversationId"] for r in recent] == [UUID_B]
    assert client.get(f"/conversations/{UUID_A}").json()["conversationId"] == UUID_A


def test_by_id_404s_only_when_the_bank_truly_has_nothing(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    bank_index.invalidate()

    assert client.get(f"/conversations/{UUID_B}").status_code == 404
    assert client.get("/conversations/ses_2026-08-31_deadbeef").status_code == 404


def test_by_id_does_not_shadow_the_recent_route(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    bank_index.invalidate()

    assert isinstance(client.get("/conversations/recent").json(), list)


def test_by_id_304s_on_an_unchanged_bank(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-30T10:00:00Z", session_id=UUID_A)
    bank_index.invalidate()

    etag = client.get(f"/conversations/{UUID_A}").headers["ETag"]
    second = client.get(f"/conversations/{UUID_A}", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
