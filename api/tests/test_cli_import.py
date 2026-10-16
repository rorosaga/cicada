"""`cicada import` — a platform's data export from the command line, with no app.

Through the real entry point (a subprocess with an isolated HOME and no backend).
Fixtures are synthetic X archives (whose items never touch the network at import)
and, for previews only, a synthetic Instagram archive."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from _cli import cli_env, envelope, run_cli
from _synthetic_bank import _bank

LIKES = "window.YTD.like.part0 = " + json.dumps([
    {"like": {"tweetId": "1000000000000000011", "fullText": "alpha-project ships"}},
    {"like": {"tweetId": "1000000000000000012", "fullText": "bob-example writes"}},
])
DMS = 'window.YTD.dm.part0 = [{"dmConversation": {"messages": [{"text": "https://example.com/private"}]}}]'
IG = {"saved_saved_collections": [
    {"title": "Collection", "string_map_data": {"Name": {"value": "alpha-project"}}},
    {"string_map_data": {"Name": {"value": "bob-example", "href": "https://www.instagram.com/p/AAA111/"}}},
]}


def _zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def setup(tmp_path):
    memory = _bank(tmp_path, git=False)
    work = tmp_path / "work"
    work.mkdir()
    return cli_env(tmp_path, memory), work, memory


def _pages(memory):
    return sorted(p.name for p in (memory / "entities").glob("media-*.md"))


def test_import_a_zip_then_again_is_idempotent(setup):
    env, work, memory = setup
    (work / "twitter-archive.zip").write_bytes(_zip({"data/like.js": LIKES, "data/direct-messages.js": DMS}))
    first = envelope(run_cli(["--json", "import", "twitter-archive.zip"], env, cwd=work))
    assert first["ok"] is True and first["command"] == "import"
    assert first["data"]["created"] == 2 and first["data"]["duplicates"] == 0
    assert first["data"]["source"] == "X Archive"
    assert len(_pages(memory)) == 2
    again = envelope(run_cli(["--json", "import", "twitter-archive.zip"], env, cwd=work))
    assert again["data"]["created"] == 0 and again["data"]["duplicates"] == 2
    assert len(_pages(memory)) == 2


def test_import_an_unzipped_folder(setup):
    env, work, memory = setup
    data = work / "twitter-archive" / "data"
    data.mkdir(parents=True)
    (data / "like.js").write_text(LIKES)
    (data / "direct-messages.js").write_text(DMS)
    proc = run_cli(["import", str(work / "twitter-archive")], env, cwd=work)
    assert proc.returncode == 0, proc.stderr
    assert "2 new" in proc.stdout
    assert len(_pages(memory)) == 2
    assert not any("example.com/private" in (memory / "entities" / p).read_text() for p in _pages(memory))


def test_preview_writes_nothing_and_names_the_collections(setup):
    env, work, memory = setup
    (work / "instagram.zip").write_bytes(_zip({"your_instagram_activity/saved/saved_collections.json":
                                               json.dumps(IG)}))
    env_ = envelope(run_cli(["--json", "import", "instagram.zip", "--preview"], env, cwd=work))
    assert env_["ok"] is True
    assert env_["data"]["platform"] == "instagram" and env_["data"]["total"] == 1
    assert env_["data"]["collections"] == [{"name": "alpha-project", "kind": "collection", "count": 1}]
    assert _pages(memory) == [] and not (memory / "sources" / "url_index.json").exists()


def test_import_into_a_demo_bank_is_refused_and_writes_nothing(setup):
    from api.services import demo_guard

    env, work, memory = setup
    demo_guard.write_manifest(memory)
    (work / "twitter-archive.zip").write_bytes(_zip({"data/like.js": LIKES}))
    proc = run_cli(["--json", "import", "twitter-archive.zip"], env, cwd=work)
    assert proc.returncode == 4 and envelope(proc)["code"] == "demo_bank"
    assert _pages(memory) == []


def test_a_missing_path_is_a_usage_error(setup):
    env, work, _ = setup
    proc = run_cli(["--json", "import", "nope.zip"], env, cwd=work)
    assert proc.returncode == 2 and envelope(proc)["code"] == "usage"


def test_a_file_that_is_no_export_is_refused_without_writing(setup):
    env, work, memory = setup
    (work / "notes.js").write_text("console.log(1)")
    proc = run_cli(["--json", "import", "notes.js"], env, cwd=work)
    assert proc.returncode == 1 and envelope(proc)["code"] == "not_an_export"
    assert _pages(memory) == []
