"""Final review (G118 slice 2, R-PB4): `markdown_parser.parse` reads frontmatter
with libyaml's safe loader when PyYAML has it. The per-message `turns` sidecar
made the pure-Python scanner the dominant cost of every full episode scan (the
Stop hook's first-capture scan crossed its 3 s timeout at 2,000 imports); the
swap must be invisible — the same dict `yaml.safe_load` gives, still safe.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from api.services import markdown_parser


def test_parse_matches_safe_load_on_a_turns_sidecar(tmp_path: Path):
    fm = {
        "id": "ep_2026-09-01_001",
        "timestamp": "2026-09-01T10:00:00+00:00",
        "created": "2026-09-01",
        "title": "alpha-project: planning",
        "tags": ["alpha-project", "bob-example"],
        "turns": [{"offset": i * 40, "ts": f"2026-09-01T10:{i:02d}:00+00:00",
                   "speaker": "user" if i % 2 == 0 else "assistant"} for i in range(20)],
    }
    path = tmp_path / "ep.md"
    markdown_parser.write(path, fm, "user: hello\nassistant: hi")
    raw = path.read_text(encoding="utf-8").split("---", 2)[1].strip()
    expected = yaml.safe_load(raw)
    markdown_parser._normalize_dates(expected)
    parsed = markdown_parser.parse(path)
    assert parsed.frontmatter == expected
    assert parsed.frontmatter["created"] == "2026-09-01"  # dates still normalised
    assert parsed.body == "user: hello\nassistant: hi"


def test_the_loader_is_a_safe_one():
    assert markdown_parser._SAFE_LOADER in {getattr(yaml, "CSafeLoader", None), yaml.SafeLoader}


def test_a_python_tag_is_still_refused(tmp_path: Path):
    path = tmp_path / "evil.md"
    path.write_text("---\nx: !!python/object/apply:os.getcwd []\n---\n\nbody\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        markdown_parser.parse(path)
