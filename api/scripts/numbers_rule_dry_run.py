"""Proposed ruling 55, read-only and count-only: what the number rule would do on a bank, for the person to read before a yes.

`python -m api.scripts.numbers_rule_dry_run <bank path>`. It writes nothing, mints nothing and calls nothing; it prints
counts and never a word or a digit of what it read.

* ``mentions``: files holding the literal ``[number:`` shape; ``real tokens``: what `phone_numbers.bank_token_ids` counts
  as a token (a session that talks about this feature is a mention, not a token).
* In the person's own lines of ticked chats, how many would become tokens, and how many digit runs of 7 to 15 would stay in
  the words. The second count is the rule's false negatives and true negatives together: reading them is the owner's.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from api.services import markdown_parser, phone_numbers


def run(bank: Path) -> dict[str, int]:
    counts = dict.fromkeys(("chat_episodes", "person_lines", "lines_with_digit_run", "would_token", "digit_runs_left",
                            "other_lines_would_redact", "mentions", "real_tokens"), 0)
    for sub in ("episodes", "entities"):
        folder = bank / sub
        if folder.is_dir():
            counts["mentions"] += sum(1 for f in folder.iterdir() if f.is_file()
                                      and "[number:" in f.read_text(encoding="utf-8", errors="ignore"))
    counts["real_tokens"] = len(phone_numbers.bank_token_ids(bank))
    for file in sorted((bank / "episodes").glob("*.md")) if (bank / "episodes").is_dir() else ():
        parsed = markdown_parser.parse(file)
        if str(parsed.frontmatter.get("origin") or "") not in phone_numbers._CHAT_ORIGINS:
            continue
        counts["chat_episodes"] += 1
        for line in parsed.body.split("\n"):
            marker, _sep, words = line.partition(": ")
            if marker != "user":
                counts["other_lines_would_redact"] += 1 if phone_numbers._spans(words, bank, person=False) else 0
                continue
            spans = phone_numbers._spans(words, bank)
            counts["person_lines"] += 1
            counts["would_token"] += len(spans)
            taken = [(a, b) for a, b, _raw in spans]
            runs = [m for m in re.finditer(r"\d[\d .\-()]{5,20}\d", words) if 7 <= len(re.sub(r"\D", "", m.group(0))) <= 15]
            counts["lines_with_digit_run"] += 1 if runs else 0
            counts["digit_runs_left"] += sum(1 for m in runs if not any(a < m.end() and m.start() < b for a, b in taken))
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m api.scripts.numbers_rule_dry_run <bank path>")
    for key, value in run(Path(sys.argv[1])).items():
        print(f"{key}: {value}")
