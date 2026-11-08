"""What every agent session pays in tokens, per call, with no model call (ROR-100 slice 1).

Measures, on a bank (a read-only clone, never the live one): the SessionStart note, the UserPromptSubmit injection, and
the replies of ``cicada_recall``, ``cicada_recall_detail``, ``cicada_ask`` (the prompt Ask hands its model, which is what
an agent-side read costs), ``cicada_check_nudges`` and ``cicada_timeline``. Tokens are cl100k_base (tiktoken, offline) beside
the chars/4 proxy the handshake budget uses. Each reply is also split by line into boilerplate (the same line in many
replies), ids/provenance, dates and prose, so a cut can be argued from what it removes.

Run with the scratch ``HOME``/``CICADA_HOME`` of ``benchmarks.public.run.unit_env``; ``--out`` gets the raw replies as
JSONL (they hold the bank's words: keep that file outside the repo)::

    python -m benchmarks.perf.reply_tokens --bank CLONE --prompts prompts.txt --out replies.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter
from pathlib import Path


def count(text: str, _enc=[]) -> int:
    if not _enc:
        import tiktoken

        _enc.append(tiktoken.get_encoding("cl100k_base"))
    return len(_enc[0].encode(text, disallowed_special=()))


ID_RE = re.compile(r"\b(?:ep_\d{4}-\d{2}-\d{2}_\d+|c_[0-9a-f]{6,}|[a-z0-9]+(?:-[a-z0-9]+)+)\b")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.+-]+Z?)?\b")
PROV_RE = re.compile(r"\b(?:observer|trust|evidence|source|session|author|engine|conf(?:idence)?|status|valid|since|"
                     r"said|observed)\b[:=]?", re.I)


def split_lines(replies: list[str]) -> dict[str, float]:
    """Fractions of tokens by line kind over a set of replies. A line is boilerplate when it appears, whole, in at
    least a quarter of the replies (and at least three); otherwise it is dated, provenance or prose by its tokens."""
    seen = Counter()
    for r in replies:
        seen.update(set(line.strip() for line in r.splitlines() if line.strip()))
    floor = max(3, len(replies) // 4)
    kinds: Counter = Counter()
    for r in replies:
        for line in r.splitlines():
            s = line.strip()
            if not s:
                continue
            n = count(line)
            if seen[s] >= floor:
                kinds["boilerplate"] += n
            elif PROV_RE.search(s) or ID_RE.search(s):
                kinds["ids_provenance"] += n
            elif DATE_RE.search(s):
                kinds["dated_prose"] += n
            else:
                kinds["prose"] += n
    total = sum(kinds.values()) or 1
    return {k: round(v / total, 3) for k, v in sorted(kinds.items())}


def quant(xs: list[int]) -> dict[str, float]:
    xs = sorted(xs)
    if not xs:
        return {"n": 0}
    p90 = xs[min(len(xs) - 1, int(0.9 * len(xs)))]
    return {"n": len(xs), "median": statistics.median(xs), "p90": p90, "mean": round(statistics.mean(xs), 1),
            "max": xs[-1]}


def entity_ids(bank: Path, k: int) -> list[str]:
    ents = sorted((bank / "entities").glob("*.md"))
    step = max(1, len(ents) // k)
    return [p.stem for p in ents[::step][:k]]


def measure(bank: Path, prompts: list[str], *, details: int, out: Path | None) -> dict:
    from api.services import ask_service, handshake, hook_recall, mcp_tools

    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="bench-tokens", harness="bench")
    replies: dict[str, list[str]] = {k: [] for k in
                                     ("session_start", "hook", "recall", "recall_detail", "ask_prompt",
                                      "check_nudges_ask", "timeline")}
    sink = out.open("w", encoding="utf-8") if out else None

    def keep(kind: str, text: str, label: str = "") -> None:
        replies[kind].append(text)
        if sink:
            sink.write(json.dumps({"kind": kind, "label": label, "tokens": count(text), "text": text}) + "\n")

    primer, _meta = handshake.load_or_build(bank, "claude-code", cache_dir=bank.parent / "_hs_cache")
    keep("session_start", primer)
    note = hook_recall.session_start_note(bank, harness="claude-code", session_id="bench-tokens",
                                          cwd=str(bank.parent), source="startup", bank_paths=[bank],
                                          deadline=time.monotonic() + 5.0)
    if note.text and note.text != primer:
        replies["session_start"][-1] = note.text

    for i, p in enumerate(prompts):
        errs = {}
        try:
            keep("hook", hook_recall.prompt_context(bank, p, deadline=time.monotonic() + 5.0).text or "", f"p{i}")
        except Exception as exc:  # noqa: BLE001
            errs["hook"] = type(exc).__name__
        try:
            keep("recall", mcp_tools.recall(ctx, p), f"p{i}")
        except Exception as exc:  # noqa: BLE001
            errs["recall"] = type(exc).__name__
        try:
            seen: dict = {}

            def llm(prompt: str) -> str:
                seen["p"] = prompt
                return json.dumps({"answer": "", "confidence": 0, "gaps": [], "used_entities": []})

            ask_service.answer_query(bank, p, top_k=6, llm_fn=llm, no_engine=False)
            keep("ask_prompt", seen.get("p") or "", f"p{i}")
        except Exception as exc:  # noqa: BLE001
            errs["ask"] = type(exc).__name__
        try:
            keep("check_nudges_ask", mcp_tools.check_nudges(ctx, p, None, "ask"), f"p{i}")
        except Exception as exc:  # noqa: BLE001
            errs["nudges"] = type(exc).__name__
        if errs:
            print(f"prompt {i}: {errs}", flush=True)

    for eid in entity_ids(bank, details):
        try:
            keep("recall_detail", mcp_tools.recall_detail(ctx, eid), eid)
        except Exception as exc:  # noqa: BLE001
            print(f"detail: {type(exc).__name__}")
    for since in ("7d", "30d"):
        try:
            keep("timeline", mcp_tools.timeline(ctx, since), since)
        except Exception as exc:  # noqa: BLE001
            print(f"timeline {since}: {type(exc).__name__}")
    if sink:
        sink.close()

    report = {}
    for kind, rs in replies.items():
        toks = [count(r) for r in rs]
        report[kind] = {**quant(toks), "chars_over_4_median": statistics.median([len(r) / 4 for r in rs]) if rs else 0,
                        "split": split_lines(rs) if rs else {}}
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True)
    ap.add_argument("--prompts", required=True, help="one prompt per line")
    ap.add_argument("--details", type=int, default=20)
    ap.add_argument("--out")
    ap.add_argument("--report")
    a = ap.parse_args()
    prompts = [line.strip() for line in Path(a.prompts).read_text(encoding="utf-8").splitlines() if line.strip()]
    rep = measure(Path(a.bank), prompts, details=a.details, out=Path(a.out) if a.out else None)
    text = json.dumps(rep, indent=1)
    if a.report:
        Path(a.report).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
