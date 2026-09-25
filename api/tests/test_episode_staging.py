"""The G20 stager as a service (R-F1 seam; R-LS1 … R-LS4, R-LS10)."""
from __future__ import annotations

from api.routers import conversations as conv
from api.services import episode_staging as st
from api.services import markdown_parser


def _draft(sid, text, *, sha=None, extra=None, queue=True, ts="2026-09-01T10:00:00+00:00"):
    return st.EpisodeDraft(
        title="alpha-project › notes.md", source_id=sid, source_updated_at=ts, timestamp=ts,
        original_date=ts[:10], source="folder", origin="folder", body=text,
        extra=dict(extra or {}), queue_for_sleep=queue, content_sha=sha, writer="folder",
    )


def _only(ep_dir):
    (path,) = sorted(ep_dir.glob("ep_*.md"))
    return path, markdown_parser.parse(path)


def test_turns_render_the_g20_body_and_stamp_every_timed_turn(tmp_path):
    ep_dir = tmp_path / "episodes"
    draft = st.EpisodeDraft(title="T", source_id="uuid-1", timestamp="2026-09-01T10:00:00+00:00",
                            original_date="2026-09-01", turns=[
                                st.Turn("First question", "user", "2026-09-01T10:00:00Z"),
                                st.Turn("An answer", "assistant", "2026-09-01T10:00:05Z"),
                                st.Turn("Thanks", "speaker:2", None)])
    assert st.stage([draft], ep_dir).as_tuple() == (1, 0, 0)
    _, parsed = _only(ep_dir)
    assert parsed.body == "user: First question\nassistant: An answer\nspeaker:2: Thanks"
    # G118 R-PB4's one shape (the merge kept it over this track's `turn_index`):
    # an entry only for a timed turn, aware-UTC, the last frontmatter key.
    stamps = parsed.frontmatter["turns"]
    assert stamps == [{"offset": 0, "ts": "2026-09-01T10:00:00+00:00", "speaker": "user"},
                      {"offset": 21, "ts": "2026-09-01T10:00:05+00:00", "speaker": "assistant"}]
    for entry in stamps:
        assert tuple(entry)[:3] == st.TURN_STAMP_REQUIRED and set(entry) <= set(st.TURN_STAMP_KEYS)
        assert parsed.body[entry["offset"]:].startswith(f"{entry['speaker']}: ")
    assert list(parsed.frontmatter)[-1] == "turns"
    assert "turn_index" not in parsed.frontmatter


def test_the_sidecar_is_capped_head_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "MAX_TURN_STAMPS", 2)
    draft = st.EpisodeDraft(title="T", source_id="s", original_date="2026-09-01",
                            turns=[st.Turn(str(i), "user", f"2026-09-01T10:00:0{i}+00:00") for i in range(3)])
    st.stage([draft], tmp_path / "episodes")
    assert [t["offset"] for t in _only(tmp_path / "episodes")[1].frontmatter["turns"]] == [0, 8]


def test_every_turn_is_scrubbed_before_its_offset_is_taken(tmp_path):
    key = "sk-" + "A" * 24
    ts = "2026-09-01T10:00:00+00:00"
    draft = st.EpisodeDraft(title="T", source_id="s-1", original_date="2026-09-01", turns=[
        st.Turn(f"my key is {key}", "user", ts), st.Turn("Your verification code is 482913", "assistant", ts)])
    result = st.stage([draft], tmp_path / "episodes")
    _, parsed = _only(tmp_path / "episodes")
    assert key not in parsed.body and "482913" not in parsed.body and result.scrubbed == 2
    assert len(parsed.frontmatter["turns"]) == 2
    for entry in parsed.frontmatter["turns"]:
        assert parsed.body[entry["offset"]:].startswith(f"{entry['speaker']}: ")


def test_a_legacy_unscrubbed_hash_counts_as_unchanged(tmp_path):
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()
    key = "sk-" + "B" * 24
    raw = f"user: here is {key}"
    markdown_parser.write(ep_dir / "ep_2026-09-01_001.md", {
        "id": "ep_2026-09-01_001", "timestamp": "2026-09-01T10:00:00+00:00", "source": "claude",
        "title": "T", "processed": True, "content_hash": st.content_hash(raw),
        "source_id": "uuid-9", "source_updated_at": "x"}, raw)
    draft = st.EpisodeDraft(title="T", source_id="uuid-9", original_date="2026-09-01",
                            turns=[st.Turn(f"here is {key}", "user")])
    assert st.stage([draft], ep_dir).as_tuple() == (0, 0, 1)  # R-LS4


def test_a_tombstone_and_a_new_id_with_the_same_sha_repoint_the_episode(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md", "# A\nbody", sha="s1", extra={"relpath": "a.md"})], ep_dir)
    path, before = _only(ep_dir)
    result = st.stage([_draft("folder:f1:docs/a.md", "# A\nbody", sha="s1",
                              extra={"relpath": "docs/a.md"})],
                      ep_dir, deleted_source_ids=["folder:f1:a.md"])
    assert (result.renamed, result.created, result.tombstoned) == (1, 0, 0)
    path2, after = _only(ep_dir)
    assert path2 == path and after.frontmatter["id"] == before.frontmatter["id"]
    assert after.frontmatter["source_id"] == "folder:f1:docs/a.md"
    assert after.frontmatter["previous_source_ids"] == ["folder:f1:a.md"]
    assert after.frontmatter["relpath"] == "docs/a.md"
    assert result.renamed_sources == [("folder:f1:a.md", "folder:f1:docs/a.md")]


def test_a_rename_matches_section_by_section(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md#intro", "one", sha="s1"),
              _draft("folder:f1:a.md#two", "two", sha="s1")], ep_dir)
    result = st.stage([_draft("folder:f1:b.md#intro", "one", sha="s1"),
                       _draft("folder:f1:b.md#two", "two", sha="s1")], ep_dir,
                      deleted_source_ids=["folder:f1:a.md#intro", "folder:f1:a.md#two"])
    assert result.renamed == 2 and result.created == 0 and result.tombstoned == 0
    by_sid = {markdown_parser.parse(p).frontmatter["source_id"]: markdown_parser.parse(p).body
              for p in ep_dir.glob("ep_*.md")}
    assert by_sid == {"folder:f1:b.md#intro": "one", "folder:f1:b.md#two": "two"}


def test_an_unchanged_section_of_an_edited_file_is_restamped_not_requeued(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md#one", "one", sha="s1")], ep_dir)
    path, parsed = _only(ep_dir)
    markdown_parser.write(path, dict(parsed.frontmatter, processed=True, processed_by="sleep"), parsed.body)
    result = st.stage([_draft("folder:f1:a.md#one", "one", sha="s2")], ep_dir)
    assert (result.skipped, result.restamped, result.updated) == (1, 1, 0)
    fm = _only(ep_dir)[1].frontmatter
    assert fm["content_sha"] == "s2" and fm["processed"] is True and fm["processed_by"] == "sleep"


def test_a_deleted_source_is_stamped_never_removed_and_comes_back_clean(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md", "text", sha="s1")], ep_dir)
    gone = st.stage([], ep_dir, deleted_source_ids=["folder:f1:a.md"])
    assert gone.tombstoned == 1 and list(gone.tombstoned_sources) == ["folder:f1:a.md"]
    _, parsed = _only(ep_dir)
    assert parsed.frontmatter["source_deleted_at"] and parsed.body == "text"
    back = st.stage([_draft("folder:f1:a.md", "text", sha="s1")], ep_dir)
    assert back.updated == 1
    assert "source_deleted_at" not in _only(ep_dir)[1].frontmatter


def test_a_draft_not_queued_is_parser_only_and_a_flip_requeues_it(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:archive/x.md", "sweep", sha="s1",
                     extra={"evidence_kind": "assistant"}, queue=False)], ep_dir)
    fm = _only(ep_dir)[1].frontmatter
    assert fm["processed"] is True and fm["processed_by"] == st.PARSED_ONLY  # R-LS10
    st.stage([_draft("folder:f1:archive/x.md", "sweep", sha="s1",
                     extra={"evidence_kind": "user"})], ep_dir)
    fm = _only(ep_dir)[1].frontmatter
    assert fm["processed"] is False and "processed_by" not in fm and fm["evidence_kind"] == "user"


def test_a_requeued_update_drops_a_stale_processed_by(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md", "v1", sha="s1")], ep_dir)
    path, parsed = _only(ep_dir)
    fm = dict(parsed.frontmatter, processed=True, processed_by="sleep")
    markdown_parser.write(path, fm, parsed.body)
    st.stage([_draft("folder:f1:a.md", "v2", sha="s2")], ep_dir)
    fm = _only(ep_dir)[1].frontmatter
    assert fm["processed"] is False and "processed_by" not in fm  # G114 R6


def test_the_router_names_are_compat_wrappers_over_the_service(tmp_path):
    eps = [{"title": "T", "source": "claude", "timestamp": "2026-02-24T13:00:00Z",
            "original_date": "2026-02-24", "source_id": "u-1", "source_updated_at": "a",
            "messages": [{"role": "user", "text": "Q", "timestamp": "2026-02-24T13:00:00Z"}]}]
    assert conv._stage_episodes(eps, tmp_path / "episodes") == (1, 0, 0)
    fm = _only(tmp_path / "episodes")[1].frontmatter
    assert fm["turns"] == [{"offset": 0, "ts": "2026-02-24T13:00:00+00:00", "speaker": "user"}]
    assert conv._stage_episodes(eps, tmp_path / "episodes") == (0, 0, 1)
