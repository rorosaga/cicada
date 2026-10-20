"""The public datasets, pinned, and their loaders into Cicada-shaped units (standard library only).

A **unit** is what gets one throwaway bank and one Sleep: a LoCoMo conversation (all of its questions share the
bank — one bank is one life) or a LongMemEval question (each ships its own haystack). A unit is plain JSON so the
launcher (no Cicada import) can plan, checkpoint and report, and the per-unit child turns it into episodes:

    {"unit_id", "dataset", "owner": {"name"} | None, "other": {"name", "kind"} | None,
     "sessions": [{"source_id", "date" (aware ISO), "title", "turns": [{"speaker", "text", "ts"}]}],
     "questions": [{"qid", "question", "answer", "category", "abstention", "evidence", "question_date"}],
     "clock": aware ISO — the "now" Sleep and the answer run at}

Every file is fetched from one pinned revision and checked against its sha256; a mismatch is refused. Nothing is
fetched unless the person runs ``prepare`` (the network is never touched by a run).
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: name -> where the file comes from, its pin, and the licence the report must name.
SOURCES: dict[str, dict] = {
    "locomo": {
        "file": "locomo10.json",
        "url": "https://raw.githubusercontent.com/snap-research/locomo/"
               "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/data/locomo10.json",
        "sha256": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
        "licence": "CC BY-NC 4.0 (snap-research/locomo)",
        "paper": "Maharana et al., ACL 2024, arXiv:2402.17753",
    },
    "longmemeval-oracle": {
        "file": "longmemeval_oracle.json",
        "url": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/"
               "98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_oracle.json",
        "sha256": "821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c",
        "licence": "MIT (xiaowu0162/longmemeval-cleaned)",
        "paper": "Wu et al., ICLR 2025, arXiv:2410.10813",
    },
    "longmemeval-s": {
        "file": "longmemeval_s_cleaned.json",
        "url": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/"
               "98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json",
        "sha256": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
        "licence": "MIT (xiaowu0162/longmemeval-cleaned)",
        "paper": "Wu et al., ICLR 2025, arXiv:2410.10813",
    },
}

#: LoCoMo's numeric categories, as LoCoMo's own scorer treats them (``task_eval/evaluation.py``: category 1 is
#: scored as multi-answer F1, category 3 splits on ';', category 5 is the adversarial "not mentioned" check) and as
#: Mem0's paper reports them. MemoryBench's loader maps 2/3 the other way round; the report always names this map.
LOCOMO_CATEGORIES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}

CHUNK = 1 << 20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str, cache: Path) -> Path:
    """Download one pinned file into ``cache`` (once), verify it, return its path. Refuses on a hash mismatch."""
    src = SOURCES[name]
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / src["file"]
    if path.is_file() and sha256(path) == src["sha256"]:
        return path
    part = path.with_suffix(path.suffix + ".part")
    req = urllib.request.Request(src["url"], headers={"User-Agent": "cicada-benchmark"})
    with urllib.request.urlopen(req, timeout=60) as resp, part.open("wb") as out:  # noqa: S310 — pinned https URL
        for block in iter(lambda: resp.read(CHUNK), b""):
            out.write(block)
    got = sha256(part)
    if got != src["sha256"]:
        part.unlink(missing_ok=True)
        raise ValueError(f"{name}: sha256 {got} does not match the pin {src['sha256']} — refusing it")
    part.replace(path)
    return path


def dataset_path(name: str, cache: Path) -> Path:
    """The verified local copy (no network): ``prepare`` must have fetched it."""
    src = SOURCES[name]
    path = cache / src["file"]
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing — run `prepare --dataset {name}` first")
    if sha256(path) != src["sha256"]:
        raise ValueError(f"{path} does not match its pinned sha256 — fetch it again")
    return path


# --------------------------------------------------------------------------------------------------------------- #
# LoCoMo
# --------------------------------------------------------------------------------------------------------------- #

_LOCOMO_WHEN = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)\s+on\s+(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})\s*$", re.I)
_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"), 1)}


def locomo_time(text: str) -> datetime:
    """``"1:56 pm on 8 May, 2023"`` -> an aware UTC datetime (the dataset names no zone)."""
    m = _LOCOMO_WHEN.match(str(text))
    if not m:
        raise ValueError(f"unrecognised LoCoMo session time: {text!r}")
    hour, minute, half, day, month, year = m.groups()
    hour = int(hour) % 12 + (12 if half.lower() == "pm" else 0)
    month_no = _MONTHS.get(month.lower()) or _MONTHS[next(k for k in _MONTHS if k.startswith(month.lower()[:3]))]
    return datetime(int(year), month_no, int(day), hour, int(minute), tzinfo=timezone.utc)


def _locomo_text(turn: dict) -> str:
    text = " ".join(str(turn.get("text") or "").split())
    caption = " ".join(str(turn.get("blip_caption") or "").split())
    # The photo itself is not in the dataset; its generated caption is what every published run reads.
    return f"{text} [shares a photo: {caption}]" if caption else text


def locomo_units(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    units = []
    for sample in data:
        conv = sample["conversation"]
        a, b = conv["speaker_a"], conv["speaker_b"]
        numbers = sorted(int(k.split("_")[1]) for k in conv if re.fullmatch(r"session_\d+", k))
        sessions = []
        for n in numbers:
            turns = conv.get(f"session_{n}") or []
            if not turns:
                continue
            start = locomo_time(conv[f"session_{n}_date_time"])
            sessions.append({
                "source_id": f"bench:{sample['sample_id']}:session-{n}",
                "date": start.isoformat(),
                "title": f"Conversation with {b} · session {n}",
                "turns": [{"speaker": "user" if t.get("speaker") == a else "other",
                           "text": _locomo_text(t), "dia_id": str(t.get("dia_id") or ""),
                           "ts": (start + timedelta(seconds=30 * i)).isoformat()}
                          for i, t in enumerate(turns) if _locomo_text(t)],
            })
        last = max(datetime.fromisoformat(s["date"]) for s in sessions)
        questions = []
        for i, qa in enumerate(sample["qa"]):
            cat = int(qa["category"])
            gold = qa.get("answer", qa.get("adversarial_answer"))
            questions.append({
                "qid": f"{sample['sample_id']}:q{i:03d}", "question": qa["question"],
                "answer": "" if gold is None else str(gold), "category": LOCOMO_CATEGORIES.get(cat, str(cat)),
                "category_id": cat, "abstention": cat == 5, "evidence": qa.get("evidence") or [],
                "question_date": None,
            })
        units.append({
            "unit_id": sample["sample_id"], "dataset": "locomo",
            "owner": {"name": a}, "other": {"name": b, "kind": "person"},
            "sessions": sorted(sessions, key=lambda s: s["date"]), "questions": questions,
            # Asked after the last session: Sleep and the answers run on that day.
            "clock": (last + timedelta(hours=1)).isoformat(),
        })
    return units


# --------------------------------------------------------------------------------------------------------------- #
# LongMemEval
# --------------------------------------------------------------------------------------------------------------- #

_LME_WHEN = re.compile(r"^\s*(\d{4})/(\d{2})/(\d{2})\s*(?:\([A-Za-z]+\))?\s*(\d{2}):(\d{2})\s*$")


def lme_time(text: str) -> datetime:
    """``"2023/05/20 (Sat) 02:21"`` -> an aware UTC datetime."""
    m = _LME_WHEN.match(str(text))
    if not m:
        raise ValueError(f"unrecognised LongMemEval time: {text!r}")
    y, mo, d, h, mi = map(int, m.groups())
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def longmemeval_units(path: Path, variant: str) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    units = []
    for item in data:
        qid = str(item["question_id"])
        sessions = []
        for sid, when, turns in zip(item["haystack_session_ids"], item["haystack_dates"], item["haystack_sessions"]):
            start = lme_time(when)
            rows = [{"speaker": "user" if t.get("role") == "user" else "assistant",
                     "text": str(t.get("content") or "").strip(), "has_answer": bool(t.get("has_answer")),
                     "ts": (start + timedelta(seconds=30 * i)).isoformat()}
                    for i, t in enumerate(turns) if str(t.get("content") or "").strip()]
            if rows:
                sessions.append({"source_id": f"bench:{qid}:{sid}", "date": start.isoformat(),
                                 "title": f"Chat · {start.date().isoformat()}", "turns": rows})
        asked = lme_time(item["question_date"])
        units.append({
            "unit_id": qid, "dataset": f"longmemeval-{variant}",
            "owner": None, "other": None,
            "sessions": sorted(sessions, key=lambda s: s["date"]),
            "questions": [{"qid": qid, "question": item["question"], "answer": str(item["answer"]),
                           "category": item["question_type"], "category_id": None,
                           "abstention": qid.endswith("_abs"), "evidence": item.get("answer_session_ids") or [],
                           "question_date": asked.isoformat()}],
            "clock": asked.isoformat(),
        })
    return units


def load_units(name: str, cache: Path) -> list[dict]:
    path = dataset_path(name, cache)
    if name == "locomo":
        return locomo_units(path)
    if name.startswith("longmemeval-"):
        return longmemeval_units(path, name.split("-", 1)[1])
    raise ValueError(f"unknown dataset {name}")


def select(units: list[dict], *, units_limit: int | None = None, only: list[str] | None = None,
           per_category: int | None = None, limit: int | None = None,
           skip_categories: tuple[str, ...] = ()) -> list[dict]:
    """A deterministic slice: chosen units, then questions — ``per_category`` first N of each category (stratified),
    then at most ``limit`` questions overall. LongMemEval's units are questions, so its slice is taken over units."""
    if only:
        wanted = set(only)
        units = [u for u in units if u["unit_id"] in wanted]
    out = []
    if units and units[0]["dataset"].startswith("longmemeval-"):
        units = [u for u in units if u["questions"][0]["category"] not in skip_categories]
        if per_category:
            seen: dict[str, int] = {}
            kept = []
            for u in units:
                cat = u["questions"][0]["category"] + ("/abstention" if u["questions"][0]["abstention"] else "")
                if seen.get(cat, 0) < per_category:
                    seen[cat] = seen.get(cat, 0) + 1
                    kept.append(u)
            units = kept
        return units[:limit] if limit else units
    for unit in units[:units_limit] if units_limit else units:
        qs = [q for q in unit["questions"] if q["category"] not in skip_categories]
        if per_category:
            seen = {}
            kept = []
            for q in qs:
                if seen.get(q["category"], 0) < per_category:
                    seen[q["category"]] = seen.get(q["category"], 0) + 1
                    kept.append(q)
            qs = kept
        if limit:
            qs = qs[:limit]
        out.append({**unit, "questions": qs})
    return out
