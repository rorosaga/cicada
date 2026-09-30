"""G162 A8 — Track V's rail as a test: Cicada never downloads a video or derives a stream.

Two scans. (a) The NEW video modules contain none of the four strings that mean "fetch a stream"
(`yt-dlp`, `googlevideo`, `.m3u8`, `timedtext`). (b) The whole Python tree (and the app's sources) contains
none of the strings that appear nowhere today — `timedtext`, `youtube_transcript_api`, `import yt_dlp`, or a
`subprocess` argv naming `yt-dlp` — with a named allowlist for the files that must mention them. A planted
string fails the scan."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NEW_MODULES = ("api/services/video_state.py", "api/services/video_queue.py", "api/services/video_prompt.py",
               "api/routers/videos.py")
STREAM_STRINGS = ("yt-dlp", "googlevideo", ".m3u8", "timedtext")
TREE_PATTERNS = (re.compile(r"timedtext"), re.compile(r"youtube_transcript_api"), re.compile(r"import\s+yt_dlp"),
                 re.compile(r"subprocess\.[a-z_]+\(\s*\[[^\]]*yt-dlp"))
#: Files that legitimately talk ABOUT these strings, each with its reason. Empty on purpose: today nothing does.
ALLOWLIST: dict[str, str] = {}
SKIP_DIRS = {".venv", "node_modules", ".git", ".build", "tests", "Tests", "__pycache__"}


def scan(paths, needles) -> list[tuple[str, str]]:
    hits = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        for needle in needles:
            if (needle.search(text) if hasattr(needle, "search") else needle in text):
                hits.append((str(path), getattr(needle, "pattern", needle)))
    return hits


def tree_files():
    for sub, suffixes in (("api", {".py"}), ("mcp", {".py"}), ("scripts", {".py", ".sh"}),
                          ("app/CicadaApp/Sources", {".swift"})):
        for path in (ROOT / sub).rglob("*"):
            if path.is_file() and path.suffix in suffixes and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
                if path.relative_to(ROOT).as_posix() not in ALLOWLIST:
                    yield path


def test_the_new_modules_never_name_a_stream():
    assert scan([ROOT / m for m in NEW_MODULES], STREAM_STRINGS) == []


def test_the_whole_tree_never_downloads_or_scrapes():
    assert scan(tree_files(), TREE_PATTERNS) == []


@pytest.mark.parametrize("planted", ["url = 'https://example.com/api/timedtext?v=x'",
                                     "from youtube_transcript_api import YouTubeTranscriptApi",
                                     "import yt_dlp",
                                     "subprocess.run(['yt-dlp', url])"])
def test_a_planted_string_fails_the_scan(tmp_path, planted):
    path = tmp_path / "planted.py"
    path.write_text(planted + "\n", encoding="utf-8")
    assert scan([path], TREE_PATTERNS)
    assert scan([path], STREAM_STRINGS) or "yt_dlp" in planted or "youtube_transcript_api" in planted
