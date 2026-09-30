"""G162 B10 / N-2 — every free-text field the queue stores is scrubbed and capped, and the ledger names its
writer. The house rule (`test_episode_writers_scrub.py`): a writer that skips the scrub fails a test."""
from __future__ import annotations

import inspect
import json

import pytest

from _video_fixtures import bank_with_videos, url_of
from api.services import episode_scrub, video_queue

SECRETS = [
    "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2",
    "ghp_" + "A" * 24,
    "Bearer " + "abcdEFGH1234abcdEFGH1234",
    "api_key=" + "Zx9Zx9Zx9Zx9Zx9Zx9",
    "0123456789abcdef0123456789abcdef",
]


def test_the_writer_is_declared_and_every_free_text_path_scrubs():
    assert "video_queue" in episode_scrub.WRITERS
    source = inspect.getsource(video_queue)
    assert "episode_scrub" in source
    for fn in (video_queue.release, ):
        assert "clean_text(" in inspect.getsource(fn), fn.__name__
    # the only stored free text is the failed reason; nothing else in a row is caller-supplied prose
    assert inspect.getsource(video_queue.clean_text).count("scrub") >= 1


@pytest.mark.parametrize("secret", SECRETS)
def test_a_secret_shaped_reason_is_redacted_one_line_and_capped(tmp_path, secret):
    memory, keys = bank_with_videos(tmp_path, 1)
    video_queue.put(memory, keys[0], "watch")
    video_queue.claim(memory, session="s", harness="h")
    video_queue.release(memory, [{"url": url_of("00"), "code": "blocked",
                                  "reason": f"first line\nsecond {secret}\t" + "z" * 500}], session="s")
    raw = video_queue.path_for(memory).read_text()
    assert secret not in raw
    reason = json.loads(raw)["items"][0]["failed"]["reason"]
    assert "\n" not in reason and "\t" not in reason and len(reason) <= video_queue.MAX_REASON_CHARS


def test_the_queue_file_holds_no_url_and_no_title(tmp_path):
    """P4: the file is machine-wide, so it stores keys — never a link the person saved or its title."""
    memory, keys = bank_with_videos(tmp_path, 1)
    video_queue.handoff(memory, [{"key": keys[0], "want": "watch"}], "auto")
    raw = video_queue.path_for(memory).read_text()
    assert "youtube" not in raw and "http" not in raw and "Video 00" not in raw
    assert oct(video_queue.path_for(memory).stat().st_mode & 0o777) == "0o600"


def test_an_unknown_code_reads_failed_and_a_known_one_survives():
    assert video_queue.clean_code("NEEDS_LOGIN") == "needs_login"
    assert video_queue.clean_code("rm -rf") == "failed" and video_queue.clean_code(None) == "failed"
