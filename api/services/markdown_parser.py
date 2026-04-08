import datetime
from dataclasses import dataclass, field
from pathlib import Path

import yaml


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

    fm = yaml.safe_load(parts[1].strip()) or {}
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
