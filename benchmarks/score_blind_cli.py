#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import textwrap
from pathlib import Path

FIELDS = [
    ("factual_accuracy", "Factual accuracy"),
    ("relational_depth", "Relational depth"),
    ("proactive_recall", "Proactive recall"),
    ("actionability", "Actionability"),
]


def clear() -> None:
    os.system("clear")


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def save_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def is_scored(row: dict[str, str]) -> bool:
    return all((row.get(name) or "").strip() != "" for name, _ in FIELDS)


def ask_score(label: str, current: str) -> str:
    while True:
        prompt = f"{label} [0-3]"
        if current:
            prompt += f" (current: {current})"
        prompt += ": "
        raw = input(prompt).strip()
        if raw == "" and current:
            return current
        if raw in {"0", "1", "2", "3"}:
            return raw
        print("Enter 0, 1, 2, or 3.")


def score_row(row: dict[str, str], index: int, total: int) -> None:
    clear()
    print(f"Row {index}/{total}  |  {row['blind_id']}  |  {row['question_id']}  |  {row['category']}")
    print()
    print("Question:")
    print(textwrap.fill(row["question_text"], width=100))
    print()
    print("Expected answer:")
    print(textwrap.fill(row["expected_answer"], width=100))
    print()
    print("Answer:")
    print(textwrap.fill(row["final_answer"], width=100))
    print()
    for name, label in FIELDS:
        row[name] = ask_score(label, row.get(name, "").strip())
    existing_notes = (row.get("notes") or "").strip()
    note_prompt = "Notes"
    if existing_notes:
        note_prompt += f" (current: {existing_notes})"
    note_prompt += ": "
    note = input(note_prompt).strip()
    if note:
        row["notes"] = note
    elif existing_notes:
        row["notes"] = existing_notes
    print("Saved. Press Enter for next row, or Ctrl-C to stop.")
    input()


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a blinded Cicada benchmark CSV in the terminal.")
    parser.add_argument("csv_path", help="Path to the blind CSV")
    parser.add_argument("--all", action="store_true", help="Include already-scored rows")
    args = parser.parse_args()

    path = Path(args.csv_path)
    rows = load_rows(path)
    targets = rows if args.all else [r for r in rows if not is_scored(r)]
    if not targets:
        print("No unscored rows found.")
        return

    total = len(targets)
    try:
        for idx, target in enumerate(targets, start=1):
            score_row(target, idx, total)
            save_rows(path, rows)
    except KeyboardInterrupt:
        save_rows(path, rows)
        print("\nStopped. Progress saved.")


if __name__ == "__main__":
    main()
