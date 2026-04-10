"""Table 1 benchmark harness — three-condition recall evaluation.

Reads a question set from a local YAML file and runs each question
through:

  - **Condition A** (Cicada with Sleep): the full MCP ``handle_recall``
    path — entities, keyword fallback, wikilink hops, episode excerpts,
    nudges, and clarifications.
  - **Condition B** (Cicada without Sleep): raw episode LEANN only.
  - **Condition C** (commercial baseline): stub rows you fill in manually
    from ChatGPT or Claude.

Each retrieved context is fed to the same answerer LLM with the same
prompt so the only thing that differs between A and B is the retrieval
path.

Outputs (timestamped so multiple runs don't clobber each other):

  - ``runs_{ts}.jsonl``           — one line per (question, condition),
                                    full retrieved context + final
                                    answer + latency + metadata.
  - ``scoring_sheet_{ts}.csv``    — human scoring sheet: one row per
                                    (question, condition), with blank
                                    columns for the four rubric
                                    dimensions (factual_accuracy,
                                    relational_depth, proactive_recall,
                                    actionability) and a notes column.

Open the scoring sheet in a spreadsheet, fill in integers 0-3 for each
rubric dimension (following experiments.tex), save, and the filled CSV
becomes the raw data for ``tab:question_scores`` in results.tex.

Run:

    cd /path/to/cicada
    api/.venv/bin/python -m benchmarks.run_table1 \\
        --questions benchmarks/questions.example.yaml \\
        --memory memory \\
        --out benchmark_results/table1
"""
from __future__ import annotations

# Must be first so sys.path + env are ready before any api/litellm imports.
from benchmarks import _bootstrap  # noqa: F401

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from benchmarks._bootstrap import BENCHMARK_RESULTS, LIVE_MEMORY_PATH
from benchmarks.answerer import synthesize_answer
from benchmarks.retrieval import retrieve_episodes_only, retrieve_full

from api.config import Settings


CSV_HEADER = [
    "question_id",
    "category",
    "condition",
    "question_text",
    "expected_answer",
    "final_answer",
    "factual_accuracy",
    "relational_depth",
    "proactive_recall",
    "actionability",
    "notes",
]


def _load_questions(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a YAML mapping with a 'questions' key")
    questions = data.get("questions") or []
    if not questions:
        raise SystemExit(f"{path}: no questions found under the 'questions' key")
    return questions


def _run(questions_path: Path, out_dir: Path, memory_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(memory_path=memory_path)
    model = settings.litellm_model
    print(f"model        : {model}", file=sys.stderr)
    print(f"memory path  : {memory_path}", file=sys.stderr)
    print(f"questions    : {questions_path}", file=sys.stderr)
    print(f"out dir      : {out_dir}", file=sys.stderr)

    questions = _load_questions(questions_path)
    print(f"loaded       : {len(questions)} questions", file=sys.stderr)
    print("", file=sys.stderr)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = out_dir / f"runs_{ts}.jsonl"
    csv_path = out_dir / f"scoring_sheet_{ts}.csv"

    with open(jsonl_path, "w", encoding="utf-8") as jsonl, \
         open(csv_path, "w", encoding="utf-8", newline="") as sheet:
        writer = csv.writer(sheet)
        writer.writerow(CSV_HEADER)

        for i, q in enumerate(questions, 1):
            qid = str(q.get("id", f"Q{i:02d}"))
            category = str(q.get("category", ""))
            text = str(q.get("text", "")).strip()
            expected = str(q.get("expected_answer", "")).strip()

            if not text:
                print(f"  {qid}: empty question text — skipping", file=sys.stderr)
                continue

            # --- Condition A: full Cicada ---------------------------------
            t0 = time.perf_counter()
            ret_a = retrieve_full(memory_path, text)
            retrieve_a_seconds = time.perf_counter() - t0
            t0 = time.perf_counter()
            ans_a = synthesize_answer(text, ret_a.context, model=model)
            synth_a_seconds = time.perf_counter() - t0

            record_a = {
                "question_id": qid,
                "category": category,
                "condition": "A_cicada_full",
                "question_text": text,
                "expected_answer": expected,
                "retrieved_context": ret_a.context,
                "final_answer": ans_a,
                "retrieve_seconds": round(retrieve_a_seconds, 3),
                "synthesize_seconds": round(synth_a_seconds, 3),
                "retrieval_notes": ret_a.notes,
            }
            jsonl.write(json.dumps(record_a, ensure_ascii=False) + "\n")
            writer.writerow([
                qid, category, "A_cicada_full", text, expected, ans_a,
                "", "", "", "", "",
            ])

            # --- Condition B: raw episode LEANN only ----------------------
            t0 = time.perf_counter()
            ret_b = retrieve_episodes_only(memory_path, text)
            retrieve_b_seconds = time.perf_counter() - t0
            t0 = time.perf_counter()
            ans_b = synthesize_answer(text, ret_b.context, model=model)
            synth_b_seconds = time.perf_counter() - t0

            record_b = {
                "question_id": qid,
                "category": category,
                "condition": "B_cicada_no_sleep",
                "question_text": text,
                "expected_answer": expected,
                "retrieved_context": ret_b.context,
                "final_answer": ans_b,
                "retrieve_seconds": round(retrieve_b_seconds, 3),
                "synthesize_seconds": round(synth_b_seconds, 3),
                "retrieval_notes": ret_b.notes,
            }
            jsonl.write(json.dumps(record_b, ensure_ascii=False) + "\n")
            writer.writerow([
                qid, category, "B_cicada_no_sleep", text, expected, ans_b,
                "", "", "", "", "",
            ])

            # --- Condition C: commercial baseline (stub for manual fill) --
            record_c = {
                "question_id": qid,
                "category": category,
                "condition": "C_commercial_manual",
                "question_text": text,
                "expected_answer": expected,
                "retrieved_context": (
                    "(manual — paste the commercial-system answer into "
                    "final_answer before scoring)"
                ),
                "final_answer": "",
                "retrieve_seconds": None,
                "synthesize_seconds": None,
                "retrieval_notes": "manual/commercial_baseline",
            }
            jsonl.write(json.dumps(record_c, ensure_ascii=False) + "\n")
            writer.writerow([
                qid, category, "C_commercial_manual", text, expected, "",
                "", "", "", "", "",
            ])

            print(
                f"  {qid:6s} {category:20s} A={retrieve_a_seconds + synth_a_seconds:5.1f}s "
                f"B={retrieve_b_seconds + synth_b_seconds:5.1f}s",
                file=sys.stderr,
            )

    print("", file=sys.stderr)
    print(f"wrote {jsonl_path}", file=sys.stderr)
    print(f"wrote {csv_path}", file=sys.stderr)
    print(
        "\nNext step: open the scoring sheet, fill in 0-3 for each of the four "
        "rubric columns per row, save. That filled CSV is the raw data for "
        "Table 1 in results.tex.",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cicada Table 1 benchmark — three-condition recall eval."
    )
    parser.add_argument(
        "--questions",
        type=Path,
        required=True,
        help="Path to YAML question file (see benchmarks/questions.example.yaml).",
    )
    parser.add_argument(
        "--memory",
        type=Path,
        default=LIVE_MEMORY_PATH,
        help="Path to the Cicada memory directory (default: repo_root/memory).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=BENCHMARK_RESULTS / "table1",
        help="Output directory (default: benchmark_results/table1).",
    )
    args = parser.parse_args()
    _run(args.questions, args.out, args.memory)


if __name__ == "__main__":
    main()
