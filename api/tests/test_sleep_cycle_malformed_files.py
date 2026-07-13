"""CQA-H2b: one malformed markdown file must not abort the whole nightly
Sleep cycle. Every ``markdown_parser.parse(...)`` loader loop in
``sleep_cycle.py`` (episode queue, episode listing, entity loading, marking
episodes processed) must log a warning naming the bad file and skip it,
leaving well-formed files processed exactly as before.

Hermetic: no LLM, no network — these hit the loader functions directly.
"""
from __future__ import annotations

from api.services import markdown_parser, sleep_cycle


def _write_good_episode(memory, ep_id, processed=False):
    episodes = memory / "episodes"
    episodes.mkdir(parents=True, exist_ok=True)
    (episodes / f"{ep_id}.md").write_text(
        f"---\nid: {ep_id}\ntimestamp: '2026-01-01T00:00:00Z'\n"
        f"processed: {str(processed).lower()}\nsource: mcp\n---\n\nsome body\n",
        encoding="utf-8",
    )


def _write_malformed(memory, subdir, name):
    d = memory / subdir
    d.mkdir(parents=True, exist_ok=True)
    # Unterminated flow sequence in the frontmatter -> yaml.safe_load raises
    # a ParserError, which markdown_parser.parse propagates unmodified.
    (d / f"{name}.md").write_text(
        "---\nid: [unterminated\nprocessed: false\n---\n\nbroken body\n",
        encoding="utf-8",
    )


def _write_good_entity(memory, entity_id):
    entities = memory / "entities"
    entities.mkdir(parents=True, exist_ok=True)
    (entities / f"{entity_id}.md").write_text(
        f"---\nname: {entity_id}\ntype: concept\nstatus: active\nconfidence: 0.6\n"
        "source_episodes: []\n---\n\n## Summary\nx\n",
        encoding="utf-8",
    )


def test_get_unprocessed_episodes_skips_malformed_file(tmp_path, caplog):
    _write_good_episode(tmp_path, "ep_2026-01-01_001", processed=False)
    _write_malformed(tmp_path, "episodes", "ep_2026-01-02_002")
    _write_good_episode(tmp_path, "ep_2026-01-03_003", processed=False)

    result = sleep_cycle._get_unprocessed_episodes(tmp_path)
    ids = {e["id"] for e in result}
    assert ids == {"ep_2026-01-01_001", "ep_2026-01-03_003"}


def test_list_all_episodes_skips_malformed_file(tmp_path):
    _write_good_episode(tmp_path, "ep_2026-01-01_001")
    _write_malformed(tmp_path, "episodes", "ep_2026-01-02_002")

    result = sleep_cycle.list_all_episodes(tmp_path)
    assert [e["id"] for e in result] == ["ep_2026-01-01_001"]


def test_load_existing_entities_skips_malformed_file(tmp_path):
    _write_good_entity(tmp_path, "alpha")
    _write_malformed(tmp_path, "entities", "broken-entity")
    _write_good_entity(tmp_path, "beta")

    result = sleep_cycle._load_existing_entities(tmp_path)
    ids = {e["id"] for e in result}
    assert ids == {"alpha", "beta"}


def test_mark_episodes_processed_skips_malformed_file(tmp_path):
    _write_good_episode(tmp_path, "ep_2026-01-01_001", processed=False)
    _write_malformed(tmp_path, "episodes", "ep_2026-01-02_002")

    episodes = [
        {"filepath": tmp_path / "episodes" / "ep_2026-01-01_001.md"},
        {"filepath": tmp_path / "episodes" / "ep_2026-01-02_002.md"},
    ]
    # Must not raise even though the second entry is malformed — the good
    # episode is still flipped to processed.
    sleep_cycle._mark_episodes_processed(episodes)

    fm = markdown_parser.parse(tmp_path / "episodes" / "ep_2026-01-01_001.md").frontmatter
    assert fm["processed"] is True
