
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path


def load_answers(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text())
    return {item["id"]: item for item in payload["answers"]}


def merge_sheet(sheet_path: Path, answers_by_id: dict[str, dict], baseline_label: str, out_path: Path) -> list[dict]:
    rows = list(csv.DictReader(sheet_path.open()))
    for row in rows:
        if row["condition"] == "C_commercial_manual":
            ans = answers_by_id.get(row["question_id"])
            if ans:
                row["final_answer"] = ans.get("final_answer", "")
                note = ans.get("notes", "") or ""
                row["notes"] = f"commercial_baseline={baseline_label}" + (f" | {note}" if note else "")
        else:
            row["notes"] = row.get("notes", "") or ""
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def blind_rows(rows: list[dict], blind_out: Path, key_out: Path, seed: int) -> None:
    kept = []
    key = []
    for idx, row in enumerate(rows, start=1):
        blind_id = f"B{idx:03d}"
        kept.append({
            "blind_id": blind_id,
            "question_id": row["question_id"],
            "category": row["category"],
            "question_text": row["question_text"],
            "expected_answer": row["expected_answer"],
            "final_answer": row["final_answer"],
            "factual_accuracy": "",
            "relational_depth": "",
            "proactive_recall": "",
            "actionability": "",
            "notes": "",
        })
        key.append({
            "blind_id": blind_id,
            "question_id": row["question_id"],
            "condition": row["condition"],
            "source_notes": row.get("notes", ""),
        })
    rng = random.Random(seed)
    paired = list(zip(kept, key))
    rng.shuffle(paired)
    kept, key = zip(*paired)
    kept = list(kept)
    key = list(key)
    with blind_out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=kept[0].keys())
        writer.writeheader()
        writer.writerows(kept)
    with key_out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=key[0].keys())
        writer.writeheader()
        writer.writerows(key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge a commercial baseline into Cicada Table 1 scoring and emit a blinded sheet.")
    parser.add_argument("--scoring-sheet", required=True)
    parser.add_argument("--commercial-json", required=True)
    parser.add_argument("--baseline-label", default="claude_relevant")
    parser.add_argument("--seed", type=int, default=20260410)
    args = parser.parse_args()

    sheet_path = Path(args.scoring_sheet)
    commercial_path = Path(args.commercial_json)
    stem = sheet_path.stem
    merged_out = sheet_path.with_name(stem + "_with_commercial.csv")
    blind_out = sheet_path.with_name(stem + "_blind.csv")
    key_out = sheet_path.with_name(stem + "_blind_key.csv")

    answers = load_answers(commercial_path)
    rows = merge_sheet(sheet_path, answers, args.baseline_label, merged_out)
    blind_rows(rows, blind_out, key_out, args.seed)

    print(f"wrote {merged_out}")
    print(f"wrote {blind_out}")
    print(f"wrote {key_out}")


if __name__ == "__main__":
    main()
