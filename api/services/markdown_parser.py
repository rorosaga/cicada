import datetime
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# libyaml's C parser when PyYAML was built with it, else the pure-Python one.
# Both are the SAFE loader (same SafeConstructor, same output as safe_load);
# only the scanner differs. Why it matters: G118 slice 2 (R-PB4) writes a
# per-message `turns: [{offset, ts, speaker}]` list into imported episodes'
# frontmatter, and a 20-entry list costs ~1.35 ms per parse in pure Python vs
# ~0.15 ms without it. Every full episode scan pays that — measured on 2,000
# imported episodes, `sleep_cycle.list_all_episodes` went 0.41 s -> 2.88 s and
# `transcript_capture._find_session_episode` 0.38 s -> 2.99 s, against the Stop
# hook's 3 s timeout. With CSafeLoader the same scan is ~0.42 s (final review).
# `write` keeps `yaml.dump`: a different emitter would reformat pages already
# in a bank's git history, and writes are not on a scan path.
_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@dataclass
class ParsedMarkdown:
    frontmatter: dict = field(default_factory=dict)
    body: str = ""


def parse(filepath: Path) -> ParsedMarkdown:
    """Parse a markdown file with YAML frontmatter delimited by --- fences."""
    content = filepath.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return ParsedMarkdown(body=content)

    parts = content.split("---", 2)
    if len(parts) < 3:
        return ParsedMarkdown(body=content)

    fm = yaml.load(parts[1].strip(), Loader=_SAFE_LOADER) or {}
    _normalize_dates(fm)
    return ParsedMarkdown(frontmatter=fm, body=parts[2].strip())


def write(filepath: Path, frontmatter: dict, body: str) -> None:
    """Write a markdown file with YAML frontmatter."""
    fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    filepath.write_text(f"---\n{fm_str}\n---\n\n{body}\n", encoding="utf-8")


def _normalize_dates(fm: dict) -> None:
    """Convert datetime.date values to strings (PyYAML auto-parses dates)."""
    for key, value in fm.items():
        if isinstance(value, (datetime.date, datetime.datetime)):
            fm[key] = str(value)
