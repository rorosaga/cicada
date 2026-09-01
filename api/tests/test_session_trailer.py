"""G48 — the `Cicada-Session:` commit trailer.

A twin of the `Cicada-Author:` machinery (git_service.py:25-110), and inert to
the entity-line parsing by the same contract: it carries no entity id. These
tests are the regression net for "extend it, don't break it".
"""

from __future__ import annotations

from api.services import git_service, sleep_cycle


# --- build_commit_message ----------------------------------------------------


def test_sessions_emit_one_trailer_line_each_after_the_authors():
    msg = git_service.build_commit_message(
        "Sleep cycle 2026-08-31",
        ["entities/cicada.md: updated (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"],
        sessions=["0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b", "uuid-abc"],
    )
    lines = msg.splitlines()
    assert lines[-3] == "Cicada-Author: gpt-5.4-mini"
    assert lines[-2] == "Cicada-Session: 0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    assert lines[-1] == "Cicada-Session: uuid-abc"


def test_sessions_are_deduped_in_caller_order_and_blanks_dropped():
    msg = git_service.build_commit_message(
        "s", [], sessions=["b", "a", "b", "", "  ", "a"]
    )
    assert git_service._parse_sessions(msg) == ["b", "a"]


def test_no_sessions_means_a_byte_identical_message_to_before():
    with_none = git_service.build_commit_message("s", ["x: updated"], authors=["m"])
    with_empty = git_service.build_commit_message(
        "s", ["x: updated"], authors=["m"], sessions=[]
    )
    assert with_none == with_empty
    assert "Cicada-Session" not in with_none


def test_an_id_shared_between_an_author_and_a_session_is_not_swallowed():
    msg = git_service.build_commit_message("s", [], authors=["user"], sessions=["user"])
    assert git_service._parse_authors(msg) == ["user"]
    assert git_service._parse_sessions(msg) == ["user"]


# --- _parse_sessions ---------------------------------------------------------


def test_parse_sessions_is_empty_for_a_legacy_untrailered_body():
    assert git_service._parse_sessions("Sleep cycle 2026-01-01\n\nentities/a.md: updated") == []


def test_parse_sessions_dedups_and_preserves_order():
    body = "Cicada-Session: b\nCicada-Session: a\nCicada-Session: b\n"
    assert git_service._parse_sessions(body) == ["b", "a"]


# --- _parse_entity_sessions (PR #20 review fix) ------------------------------


def test_parse_entity_sessions_reads_only_the_matching_entitys_line():
    body = (
        "entities/postgres.md: created (source: ep_1, trigger: sleep/extraction, sessions: sess-a)\n"
        "entities/sqlite.md: created (source: ep_2, trigger: sleep/extraction, sessions: sess-b)\n"
        "Cicada-Session: sess-a\n"
        "Cicada-Session: sess-b\n"
    )
    assert git_service._parse_entity_sessions(body, "postgres") == ["sess-a"]
    assert git_service._parse_entity_sessions(body, "sqlite") == ["sess-b"]


def test_parse_entity_sessions_supports_multiple_sessions_on_one_line():
    body = "entities/x.md: updated (source: ep_1, trigger: sleep/extraction, sessions: a,b)\n"
    assert git_service._parse_entity_sessions(body, "x") == ["a", "b"]


def test_parse_entity_sessions_is_empty_with_no_sessions_clause():
    body = "entities/x.md: updated (source: ep_1, trigger: sleep/extraction)\n"
    assert git_service._parse_entity_sessions(body, "x") == []


def test_parse_entity_sessions_ignores_a_different_entitys_clause():
    body = "entities/other.md: updated (source: ep_1, trigger: sleep/extraction, sessions: sess-a)\n"
    assert git_service._parse_entity_sessions(body, "x") == []


# --- regression: both trailers coexist, entity parsing unaffected ------------


def test_a_commit_with_both_trailers_still_parses_authors_and_entity_lines():
    body_lines = ["entities/mongodb.md: created (source: ep_1, trigger: sleep/extraction)"]
    msg = git_service.build_commit_message(
        "Sleep cycle 2026-08-31", body_lines,
        authors=["gpt-5.4-mini", "gpt-5.4-nano"],
        sessions=["0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"],
    )
    subject, _, body = msg.partition("\n\n")

    assert git_service._parse_authors(body) == ["gpt-5.4-mini", "gpt-5.4-nano"]
    assert git_service._infer_change_type(subject, body, "mongodb") == "created"
    description = git_service._build_description(subject, body, "mongodb")
    assert "Cicada-Session" not in description


# --- _collect_session_ids ----------------------------------------------------


def test_collect_prefers_session_id_falls_back_to_source_id_and_skips_neither():
    ids = sleep_cycle._collect_session_ids([
        {"id": "ep_1", "session_id": "sess-b", "source_id": None},
        {"id": "ep_2", "session_id": None, "source_id": "uuid-a"},
        {"id": "ep_3", "session_id": "sess-b", "source_id": "uuid-z"},
        {"id": "ep_4", "session_id": None, "source_id": None},
        {"id": "ep_5"},
    ])
    assert ids == ["sess-b", "uuid-a"]


def test_collect_is_sorted_for_a_deterministic_commit_message():
    ids = sleep_cycle._collect_session_ids([
        {"session_id": "z"}, {"session_id": "a"}, {"session_id": "m"},
    ])
    assert ids == ["a", "m", "z"]


def test_collect_caps_at_max_session_trailers():
    episodes = [{"session_id": f"s{i:04d}"} for i in range(80)]
    ids = sleep_cycle._collect_session_ids(episodes)
    assert len(ids) == git_service.MAX_SESSION_TRAILERS
    assert ids[0] == "s0000"


# --- _episode_session_map (PR #20 review fix) --------------------------------


def test_episode_session_map_prefers_session_id_falls_back_to_source_id():
    mapping = sleep_cycle._episode_session_map([
        {"id": "ep_1", "session_id": "sess-a", "source_id": None},
        {"id": "ep_2", "session_id": None, "source_id": "uuid-b"},
        {"id": "ep_3", "session_id": None, "source_id": None},
        {"id": "ep_4"},
    ])
    assert mapping == {"ep_1": "sess-a", "ep_2": "uuid-b"}


def test_episode_session_map_skips_an_episode_with_no_id():
    mapping = sleep_cycle._episode_session_map([{"session_id": "sess-a"}])
    assert mapping == {}


# --- _finalize stamps per-entity sessions onto the manifest line ------------


def test_finalize_stamps_each_entitys_own_manifest_line_with_its_sessions(monkeypatch, tmp_path):
    """G85: the decay change (``stale-thing``) is split into its OWN
    ``cicada``-authored commit (via ``commit_paths``), so its manifest line
    shows up in a DIFFERENT ``build_commit_message`` call than the two
    real (session-bearing) entity changes — every call is captured, not just
    the last."""
    import asyncio

    calls: list[dict] = []
    seen: dict = {}

    def fake_build(subject, body_lines, authors=None, sessions=None, engine=None):
        calls.append({"subject": subject, "body_lines": body_lines,
                      "authors": authors, "sessions": sessions, "engine": engine})
        return f"msg-{len(calls)}"

    async def fake_status(_mp):
        return ""

    async def fake_commit(_mp, _msg):
        return "abc1234"

    async def fake_commit_paths(_mp, message, paths):
        seen["decay_message"] = message
        seen["decay_paths"] = paths

    monkeypatch.setattr(git_service, "build_commit_message", fake_build)
    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "commit_paths", fake_commit_paths)

    changes = [
        {"id": "postgres", "action": "created", "source_episode": "ep_1",
         "source_episodes": ["ep_1"], "trigger": "sleep/extraction"},
        {"id": "sqlite", "action": "created", "source_episode": "ep_2",
         "source_episodes": ["ep_2"], "trigger": "sleep/extraction"},
        {"id": "stale-thing", "action": "archive", "new_confidence": 0.1,
         "new_status": "archived", "source_episode": "", "trigger": "sleep/decay"},
    ]
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "cycle-1", changes, None,
        sessions=["sess-a", "sess-b"],
        episode_sessions={"ep_1": "sess-a", "ep_2": "sess-b"},
    ))

    # The decay commit came first, built and committed via `commit_paths`.
    assert len(calls) == 2
    decay_call, main_call = calls
    assert decay_call["authors"] == ["cicada"]
    assert decay_call["body_lines"] == [
        "entities/stale-thing.md: archive (source: n/a, trigger: sleep/decay)"
    ]
    assert seen["decay_paths"] == ["entities/stale-thing.md"]
    assert seen["decay_message"] == "msg-1"

    lines = main_call["body_lines"]
    assert "entities/postgres.md: created (source: ep_1, trigger: sleep/extraction, sessions: sess-a)" in lines
    assert "entities/sqlite.md: created (source: ep_2, trigger: sleep/extraction, sessions: sess-b)" in lines
    # The decay-only line moved to its own commit — it must not also appear here.
    assert not any(line.startswith("entities/stale-thing.md:") for line in lines)


def test_finalize_without_episode_sessions_leaves_manifest_lines_unchanged(monkeypatch, tmp_path):
    """No ``episode_sessions`` given (e.g. an older/other caller) -> byte-identical
    manifest lines to before this fix — additive, opt-in behavior."""
    import asyncio

    seen: dict = {}

    def fake_build(subject, body_lines, authors=None, sessions=None, engine=None):
        seen["body_lines"] = body_lines
        return "msg"

    async def fake_status(_mp):
        return ""

    async def fake_commit(_mp, _msg):
        return "abc1234"

    monkeypatch.setattr(git_service, "build_commit_message", fake_build)
    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)

    changes = [{"id": "a", "action": "created", "source_episode": "ep_1", "trigger": "sleep/extraction"}]
    asyncio.run(sleep_cycle._finalize(tmp_path, "cycle-1", changes, None))

    assert seen["body_lines"] == ["entities/a.md: created (source: ep_1, trigger: sleep/extraction)"]


# --- _finalize threads them through -----------------------------------------


def test_finalize_passes_the_collected_sessions_to_build_commit_message(monkeypatch, tmp_path):
    import asyncio

    seen: dict = {}

    def fake_build(subject, body_lines, authors=None, sessions=None, engine=None):
        seen["authors"] = authors
        seen["sessions"] = sessions
        return "msg"

    async def fake_status(_mp):
        return ""

    async def fake_commit(_mp, _msg):
        return "abc1234"

    monkeypatch.setattr(git_service, "build_commit_message", fake_build)
    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)

    asyncio.run(sleep_cycle._finalize(
        tmp_path, "cycle-1", [], None, sessions=["sess-a", "sess-b"],
    ))

    assert seen["sessions"] == ["sess-a", "sess-b"]
