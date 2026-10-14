"""A captured session's title is the person's own words, never a wrapper tag (2026-10-14; ``episode_title``,
``transcript_capture._title``, ``api/scripts/retitle_wrapped_episodes.py``). Synthetic transcripts and banks only."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from api.scripts import retitle_wrapped_episodes as script
from api.services import episode_title, markdown_parser, transcript_capture as tc
from api.services.episode_title import title_for, title_from_text

SID = "11111111-2222-4333-8444-555555555555"
PASTE = '<pasted_content id="ab12">'


# --- the rule ------------------------------------------------------------------------


def test_a_pasted_only_message_is_titled_by_its_first_line_inside_the_paste():
    text = f"{PASTE}\nQuarterly plan for alpha-project\nSecond line of the paste\n</pasted_content>"
    assert title_from_text(text) == "Quarterly plan for alpha-project"


def test_a_paste_cut_off_by_the_turn_cap_before_its_close_is_still_read_inside():
    assert title_from_text(f"{PASTE}\n\nNotes from the alpha-project kickoff\nmore") == "Notes from the alpha-project kickoff"


def test_a_wrapper_followed_by_text_is_titled_by_the_persons_own_line_after_it():
    text = f"{PASTE}\nlong pasted log line\n</pasted_content>\n\nCan you summarize this for bob-example?"
    assert title_from_text(text) == "Can you summarize this for bob-example?"


def test_text_on_the_line_a_wrapper_closes_counts_as_outside():
    assert title_from_text(f"{PASTE}pasted words</pasted_content> what does this mean?") == "what does this mean?"


def test_nested_wrappers_are_read_through_to_the_first_real_line():
    text = f"{PASTE}\n<document>\n<title>\nA design note\n</title>\nbody\n</document>\n</pasted_content>"
    assert title_from_text(text) == "A design note"
    # A harness block wrapping a paste is the harness talking: the person's line after it names the session.
    text = "<system-reminder>\n" + f"{PASTE}reminder words</pasted_content>\n</system-reminder>\nHello alpha-project"
    assert title_from_text(text) == "Hello alpha-project"


def test_a_message_that_is_only_a_command_tag_has_no_title_and_the_next_turn_names_the_session():
    command = "<command-name>/review</command-name>\n<command-message>review</command-message>\n<command-args></command-args>"
    assert title_from_text(command) is None
    assert title_for([command, "Review the alpha-project branch"], "claude-code") == "Review the alpha-project branch"
    assert title_for([command], "claude-code") == "Claude Code session"
    assert title_for([f"{PASTE}\n\n</pasted_content>"], "codex") == "Codex session"


def test_angle_brackets_inside_a_sentence_are_words_not_wrappers():
    assert title_from_text("Why does Vec<String> not implement Copy?") == "Why does Vec<String> not implement Copy?"
    assert title_from_text("a < b, and <3") == "a < b, and <3"
    assert title_from_text("[code omitted]\nWhy does this fail?") == "Why does this fail?"


def test_a_long_line_is_clipped_and_never_empty():
    title = title_from_text(f"{PASTE}\n{'x' * 200}\n</pasted_content>")
    assert len(title) == tc.TITLE_MAX and title.endswith("…")
    assert title_from_text("") is None and title_from_text("   \n<br/>\n") is None


@pytest.mark.parametrize("message", [
    "<word" + " " * 16_000,                    # an open tag and a long run of whitespace with no `>`
    "<pasted_content" + " \t" * 8_000,
    "<a " + "x" * 16_000,
    "x" + "<b>" * 5_333,                       # thousands of mid-line tags, each skipped as words
    "x" + " <b>" * 4_000,
    "<a>\n" * 4_000,                           # thousands of wrappers open at once
    "<a>\n" * 2_000 + "</a>" * 2_000,
    "<" * 16_000,
    "<system-reminder>\n" * 888,
])
def test_a_16k_adversarial_message_titles_in_linear_time(message):
    started = time.perf_counter()
    title = title_from_text(message)
    assert (time.perf_counter() - started) < 0.05
    assert title is None or not episode_title.is_wrapper_title(title)


def test_a_tag_left_open_or_past_the_attribute_bound_is_never_the_title():
    assert title_from_text("<word   \nWhat is this?") == "What is this?"
    assert title_from_text(f'<pasted_content id="{"x" * 600}">\nThe paste\n</pasted_content>') == "The paste"


# --- the capture writes it -----------------------------------------------------------


def _line(typ, content, ts="2026-09-03T10:00:00.000Z"):
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID, "cwd": "/home/example/alpha-project",
                       "message": {"role": typ, "content": content}})


@pytest.fixture
def capture(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})
    claude = tmp_path / "claude-projects" / "-home-example-alpha-project"
    claude.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: claude.parent)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)

    def run(*user_messages: str) -> dict:
        lines = []
        for text in user_messages:
            lines += [_line("user", text), _line("assistant", [{"type": "text", "text": "Done."}])]
        path = claude / f"{SID}.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path), cwd=None,
                                  keep_assistant=True)
        return markdown_parser.parse(memory / "episodes" / f"{r.episode_id}.md")

    return run


def test_a_pasted_first_message_is_captured_with_its_body_untouched_and_a_real_title(capture):
    message = f"{PASTE}\nThe alpha-project error log\n</pasted_content>\nWhat broke here?"
    parsed = capture(message)
    assert parsed.frontmatter["title"] == "What broke here?"
    assert parsed.body.startswith(f"user: {message}\n")   # title only: the person's words are kept as captured


def test_a_command_only_first_message_leaves_the_title_to_the_persons_next_words(capture):
    parsed = capture("<command-name>/clear</command-name>", f"{PASTE}\nPlan for bob-example\n</pasted_content>")
    assert parsed.frontmatter["title"] == "Plan for bob-example"


# --- the one-off retitle -------------------------------------------------------------


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True,
                          env={**os.environ}).stdout


def _episode(bank: Path, n: int, title: str, first: str, *, kind: str = "transcript", sidecar: bool = True,
             later: str = "A later question") -> Path:
    body = f"user: {first}\nassistant: Done.\nuser: {later}"
    fm = {"id": f"ep_2026-09-03_{n:03d}", "timestamp": "2026-09-03T10:00:00+00:00", "source": "claude-code",
          "title": title, "processed": True, "processed_by": "sleep", "content_hash": "abc123abc123", "session_id": SID,
          "harness": "claude-code"}
    if kind:
        fm["capture_kind"] = kind
    if sidecar:
        second = len(f"user: {first}\n")
        fm["turns"] = [{"offset": 0, "speaker": "user"}, {"offset": second, "speaker": "assistant"},
                       {"offset": second + len("assistant: Done.\n"), "speaker": "user"}]
    path = bank / "episodes" / f"ep_2026-09-03_{n:03d}.md"
    markdown_parser.write(path, fm, body)
    return path


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    root = tmp_path / "bank"
    (root / "episodes").mkdir(parents=True)
    _episode(root, 1, PASTE, f"{PASTE}\nNotes on alpha-project\n</pasted_content>\nWhat should change?")
    _episode(root, 2, PASTE, f"{PASTE}\nA pasted spec for bob-example\n</pasted_content>", sidecar=False)
    _episode(root, 3, "Plain question", "Plain question")                         # already fine: untouched
    _episode(root, 4, PASTE, f"{PASTE}\n\n</pasted_content>", later=PASTE)        # nothing but tags: `<Product> session`
    _episode(root, 5, PASTE, f"{PASTE}\nhand edit pending\n</pasted_content>")    # dirty in git: skipped
    _episode(root, 6, PASTE, "x", kind="")                                         # not a transcript episode
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Synthetic")
    _git(root, "config", "user.email", "synthetic@example.com")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    path = root / "episodes" / "ep_2026-09-03_005.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    return root


def test_the_dry_run_counts_only_and_writes_nothing(bank, capsys):
    before = {p.name: p.read_bytes() for p in (bank / "episodes").iterdir()}
    assert script.main(["--bank", str(bank)]) == 0
    counts = json.loads(capsys.readouterr().out)
    assert counts == {"transcripts": 5, "wrapper_titles": 4, "would_retitle": 3, "dirty": 1,
                      "written": 0, "committed": False}
    assert {p.name: p.read_bytes() for p in (bank / "episodes").iterdir()} == before


def test_apply_retitles_in_one_cicada_commit_and_requeues_nothing(bank):
    result = episode_title.apply(bank, sleep_running=lambda: False)
    assert result.written == 3 and result.committed
    assert len(_git(bank, "log", "--format=%H").split()) == 2
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%b")
    assert _git(bank, "status", "--porcelain").strip() == "M episodes/ep_2026-09-03_005.md"
    one = markdown_parser.parse(bank / "episodes" / "ep_2026-09-03_001.md").frontmatter
    two = markdown_parser.parse(bank / "episodes" / "ep_2026-09-03_002.md").frontmatter
    assert one["title"] == "What should change?" and two["title"] == "A pasted spec for bob-example"
    assert markdown_parser.parse(bank / "episodes" / "ep_2026-09-03_004.md").frontmatter["title"] == "Claude Code session"
    assert one["processed"] is True and one["content_hash"] == "abc123abc123"   # the title is outside the hash
    assert episode_title.apply(bank, sleep_running=lambda: False).written == 0   # a second run changes nothing


def test_apply_is_refused_while_sleep_runs(bank, monkeypatch, capsys):
    with pytest.raises(episode_title.SleepRunning):
        episode_title.apply(bank, sleep_running=lambda: True)
    monkeypatch.setattr(script, "backend_running", lambda: True)
    assert script.main(["--bank", str(bank), "--apply"]) == 3
    assert "refused" in json.loads(capsys.readouterr().out)
    assert len(_git(bank, "log", "--format=%H").split()) == 1


def test_the_script_refuses_a_directory_that_is_not_a_bank(tmp_path, capsys):
    assert script.main(["--bank", str(tmp_path)]) == 2


def test_a_run_that_fails_midway_puts_back_what_it_rewrote(bank, monkeypatch):
    before = {p.name: p.read_bytes() for p in (bank / "episodes").iterdir()}
    real_write, calls = markdown_parser.write, []

    def flaky(path, fm, body):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        real_write(path, fm, body)

    monkeypatch.setattr(markdown_parser, "write", flaky)
    with pytest.raises(OSError):
        episode_title.apply(bank, sleep_running=lambda: False)
    assert {p.name: p.read_bytes() for p in (bank / "episodes").iterdir()} == before
    assert _git(bank, "status", "--porcelain").strip() == "M episodes/ep_2026-09-03_005.md"
    assert len(_git(bank, "log", "--format=%H").split()) == 1


def test_a_commit_that_fails_after_staging_leaves_neither_files_nor_index_changed(bank, monkeypatch):
    from api.services import git_service

    before = {p.name: p.read_bytes() for p in (bank / "episodes").iterdir()}

    def staged_then_failed(memory_path, message, paths):
        _git(memory_path, "add", "--", *paths)
        raise git_service.GitError("commit failed")

    monkeypatch.setattr(git_service, "commit_paths_sync", staged_then_failed)
    with pytest.raises(git_service.GitError):
        episode_title.apply(bank, sleep_running=lambda: False)
    assert {p.name: p.read_bytes() for p in (bank / "episodes").iterdir()} == before
    assert _git(bank, "status", "--porcelain").strip() == "M episodes/ep_2026-09-03_005.md"
    monkeypatch.undo()
    assert episode_title.apply(bank, sleep_running=lambda: False).written == 3   # the next run starts over cleanly
