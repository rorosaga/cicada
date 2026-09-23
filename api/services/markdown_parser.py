import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The fences `write` emits: `---` alone on the first line, then `---` alone on a
# later line. L final review (finding 2): the old `content.split("---", 2)` cut
# at the first two `---` ANYWHERE, so a frontmatter value holding one — a folder
# file's relpath or H2 heading, a meeting title, a chat title — split mid-scalar
# and raised a YAML ScannerError. `bank_index` then skipped the episode as
# malformed, the stager never saw it, and every later edit minted another
# unreadable copy. Anchored to whole lines, the split is exact for every writer.
# The frontmatter group is optional so an empty block (`---\n---`) still parses.
_FENCED = re.compile(r"---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|$)(.*)", re.S)


@dataclass
class ParsedMarkdown:
    frontmatter: dict = field(default_factory=dict)
    body: str = ""


def split_frontmatter(content: str) -> tuple[str, str] | None:
    """`(frontmatter_text, body)` for a fenced document, else None.

    Line-anchored fences first (`_FENCED`); a file that starts with `---` but
    has no closing fence on its own line — hand-written, never ours — keeps the
    old first-two-`---` split, so nothing that parsed before stops parsing.
    """
    if not content.startswith("---"):
        return None
    m = _FENCED.match(content)
    if m:
        return (m.group(1) or ""), m.group(2)
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


def parse(filepath: Path) -> ParsedMarkdown:
    """Parse a markdown file with YAML frontmatter delimited by --- fences."""
    content = filepath.read_text(encoding="utf-8")
    split = split_frontmatter(content)
    if split is None:
        return ParsedMarkdown(body=content)

    fm = yaml.safe_load(split[0].strip()) or {}
    _normalize_dates(fm)
    return ParsedMarkdown(frontmatter=fm, body=split[1].strip())


def write(filepath: Path, frontmatter: dict, body: str) -> None:
    """Write a markdown file with YAML frontmatter."""
    fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    filepath.write_text(f"---\n{fm_str}\n---\n\n{body}\n", encoding="utf-8")


def _normalize_dates(fm: dict) -> None:
    """Convert datetime.date values to strings (PyYAML auto-parses dates)."""
    for key, value in fm.items():
        if isinstance(value, (datetime.date, datetime.datetime)):
            fm[key] = str(value)
