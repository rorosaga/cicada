"""`bank_index` caches an episode's header without its `turns` sidecar (2026-10-16 perf).

On 3,850 synthetic episodes the sidecar was 99,844 rows: 53 MB of the cache and 3.6 s of a cold parse (the slow first
`/status`), against 5.5 MB and 0.5 s without it. `markdown_parser.header` parses everything but the sidecar; the
readers that place a span in its turn read it whole through `bank_index.with_turns`.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from api.services import agent_turns, bank_index, markdown_parser, turn_authorship

TURNS = [{"offset": 0, "ts": "2026-10-05T10:00:00+00:00", "speaker": "user"},
         {"offset": 40, "ts": "2026-10-05T10:01:00+00:00", "speaker": "assistant", "model": "model-a"}]


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    bank_index._TURNS.clear()
    yield
    bank_index.invalidate()


def _doc(front: str, body: str = "user: hello\n\nassistant: hi there") -> str:
    return f"---\n{front.strip()}\n---\n\n{body}\n"


@pytest.mark.parametrize("front", [
    # as every writer leaves it: the sidecar last (R-PB4)
    "id: ep_2026-10-05_001\ntimestamp: 2026-10-05\nprocessed: false\nturns:\n- offset: 0\n  ts: '2026-10-05T10:00:00'\n"
    "  speaker: user\n- offset: 40\n  ts: null\n  speaker: assistant",
    # hand-edited: a key after it, and a blank line inside it
    "id: ep_2026-10-05_002\nturns:\n  - offset: 0\n\n    speaker: user\ntitle: After the sidecar\ntags:\n- a\n- b",
    # the pre-PJ-4 count, and a flow list
    "id: ep_2026-10-05_003\nturns: 4\nprocessed: true",
    "id: ep_2026-10-05_004\nturns: [{offset: 0, speaker: user},\n  {offset: 9, speaker: assistant}]\nsource: chat",
    # a `turns:` line inside a block scalar is the scalar's text, not the key
    "id: ep_2026-10-05_005\nnote: |\n  turns: not a key\n  more\nprocessed: false",
    # no sidecar at all
    "id: ep_2026-10-05_006\ntimestamp: 2026-10-05T10:00:00+00:00",
])
def test_the_header_is_the_whole_frontmatter_but_the_sidecar(tmp_path, front):
    path = tmp_path / "episodes" / "ep.md"
    path.parent.mkdir()
    path.write_text(_doc(front), encoding="utf-8")
    full = markdown_parser.parse(path, ledger=False).frontmatter
    header, had = markdown_parser.header(path)
    assert header == {k: v for k, v in full.items() if k != "turns"}
    assert had == ("turns" in full)


def _episode(bank: Path, n: int, turns=TURNS) -> Path:
    fm = {"id": f"ep_2026-10-05_{n:03d}", "timestamp": "2026-10-05T10:00:00+00:00", "processed": False}
    if turns is not None:
        fm["turns"] = turns
    path = bank / "episodes" / f"ep_2026-10-05_{n:03d}.md"
    markdown_parser.write(path, fm, "user: hello there\n\nassistant: hi, a reply")
    return path


def test_the_cache_holds_no_sidecar_and_hands_it_back_whole(tmp_path):
    (tmp_path / "episodes").mkdir()
    _episode(tmp_path, 1)
    _episode(tmp_path, 2, turns=None)
    one, two = bank_index.files(tmp_path, "episodes")
    assert "turns" not in one.frontmatter and one.has_turns
    assert not two.has_turns and bank_index.with_turns(two) is two.frontmatter
    assert bank_index.with_turns(one)["turns"] == TURNS
    assert bank_index.with_turns(one)["id"] == "ep_2026-10-05_001"
    assert "turns" not in one.frontmatter, "handing it back never adds it to the cached header"
    assert bank_index.with_turns(None) == {}


def test_a_rewritten_sidecar_is_read_afresh(tmp_path):
    (tmp_path / "episodes").mkdir()
    path = _episode(tmp_path, 1)
    [f] = bank_index.files(tmp_path, "episodes")
    assert len(bank_index.with_turns(f)["turns"]) == 2
    _episode(tmp_path, 1, turns=TURNS[:1])
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000))
    [f] = bank_index.files(tmp_path, "episodes")
    assert len(bank_index.with_turns(f)["turns"]) == 1


def test_a_single_file_read_never_caches_the_sidecar_either(tmp_path):
    (tmp_path / "episodes").mkdir()
    _episode(tmp_path, 1)
    f = bank_index.file(tmp_path, "episodes", "ep_2026-10-05_001.md")
    assert f is not None and "turns" not in f.frontmatter and f.has_turns
    assert bank_index.with_turns(f)["turns"] == TURNS


def test_turn_authorship_reads_the_sidecar_through_the_cache(tmp_path):
    (tmp_path / "episodes").mkdir()
    _episode(tmp_path, 1)
    stamps = turn_authorship.TurnAuthorship(tmp_path).stamps("ep_2026-10-05_001")
    assert stamps == agent_turns.stamps({"turns": TURNS})
    assert [s.model for s in stamps] == [None, "model-a"]
