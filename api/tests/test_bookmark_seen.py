"""G129 slice 2: the per-channel seen-set + its diff — both correctness rails."""
from __future__ import annotations

from pathlib import Path

from api.services import bookmark_seen


def test_diff_removed_none_with_no_previous_seen_set():
    assert bookmark_seen.diff_removed(
        None, ["a"], previous_folders=None, current_folders=None
    ) is None


def test_diff_removed_finds_dropped_hashes():
    previous = {"hashes": ["a", "b", "c"], "folders": None}
    assert bookmark_seen.diff_removed(
        previous, ["a", "c"], previous_folders=None, current_folders=None
    ) == ["b"]


def test_diff_removed_empty_when_nothing_dropped():
    previous = {"hashes": ["a", "b"], "folders": None}
    assert bookmark_seen.diff_removed(
        previous, ["a", "b", "z"], previous_folders=None, current_folders=None
    ) == []


def test_diff_removed_refuses_on_folder_scope_change():
    previous = {"hashes": ["a", "b"], "folders": ["Reading"]}
    assert bookmark_seen.diff_removed(
        previous, ["a"], previous_folders=["Reading"], current_folders=["Other"]
    ) is None


def test_diff_removed_none_and_empty_list_and_blank_string_folders_are_equivalent():
    previous = {"hashes": ["a"], "folders": None}
    for current in (None, [], [""]):
        assert bookmark_seen.diff_removed(
            previous, ["a"], previous_folders=None, current_folders=current
        ) == []


def test_diff_removed_folder_order_does_not_matter():
    previous = {"hashes": ["a"], "folders": ["B", "A"]}
    assert bookmark_seen.diff_removed(
        previous, ["a"], previous_folders=["B", "A"], current_folders=["A", "B"]
    ) == []


def test_write_and_read_channel_seen_round_trip(tmp_path: Path):
    memory = tmp_path / "memory"
    bookmark_seen.write_channel_seen(
        memory, "chrome-bookmarks", folders=["Reading"], hashes=["b", "a"], at="2026-09-05T10:00:00Z"
    )
    state = bookmark_seen.read_seen(memory)
    assert state["chrome-bookmarks"] == {
        "folders": ["Reading"], "hashes": ["a", "b"], "at": "2026-09-05T10:00:00Z",
    }
    assert (memory / "sources" / "bookmark_seen.json").exists()


def test_write_channel_seen_channels_are_independent(tmp_path: Path):
    memory = tmp_path / "memory"
    bookmark_seen.write_channel_seen(memory, "chrome-bookmarks", folders=None, hashes=["a"], at="t1")
    bookmark_seen.write_channel_seen(memory, "safari-bookmarks", folders=None, hashes=["b"], at="t2")
    state = bookmark_seen.read_seen(memory)
    assert set(state) == {"chrome-bookmarks", "safari-bookmarks"}
    assert state["chrome-bookmarks"]["hashes"] == ["a"]


def test_read_seen_corrupt_file_degrades_to_empty(tmp_path: Path):
    memory = tmp_path / "memory"
    (memory / "sources").mkdir(parents=True)
    (memory / "sources" / "bookmark_seen.json").write_text("not json", encoding="utf-8")
    assert bookmark_seen.read_seen(memory) == {}
