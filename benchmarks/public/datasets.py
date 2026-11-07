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

import ast
import csv
import hashlib
import json
import re
import subprocess
import sys
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
    # The two personalization benchmarks the Memorilla paper reports. Both are graded here against the reference answer
    # by a judge, never by the nearest of the choices (see ``judges.PERSONAL_TEMPLATE`` and the leak checks below).
    "personalizationv4": {
        # The test split: 30 evaluation users, 200 two-turn chats each. A parquet file, so ``prepare`` reads it once with
        # pyarrow and writes ``derived``, the JSON the loader reads (the standard library cannot open parquet); both
        # files are pinned, and the loader refuses a derived file whose hash differs.
        "file": "personalizationv4_test.parquet",
        "url": "https://huggingface.co/datasets/memorilla/PersonalizationV4/resolve/"
               "e2bf5499046e27ad5646f0e0f800d2b60eadfe82/data/test.parquet",
        "sha256": "168a11a105b2493d70c36fe70fdc73e465188f0794836970703abda6279db91c",
        "derived": "personalizationv4_test.json",
        "derived_sha256": "855375309ae00eb6904fe1b622902e896b2a637e8d680cace19be831d6c1fde6",
        "licence": "CC BY 4.0 (memorilla/PersonalizationV4; seed personas from Synthetic-Persona-Chat, CC BY 4.0)",
        "paper": "Memorilla, snap-stanford/memorilla (2026)",
    },
    "personamem-v2": {
        # The text benchmark (5,000 queries over 200 personas, four choices each) and, from the same commit, the 32k-token
        # chat history of the personas this harness has pinned. Another persona is added by pinning its history's hash here.
        "file": "personamem_v2_benchmark_text.csv",
        "url": "https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/resolve/"
               "ed956dea41521fc4499acbc63f966e0fd3c053ba/benchmark/text/benchmark.csv",
        "sha256": "95f2a8a324aab7baf2af937feae12731369e2abf7cad5ab3e170594cb25a3e52",
        "histories_url": "https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/resolve/"
                        "ed956dea41521fc4499acbc63f966e0fd3c053ba/",
        "histories": {
            "10": {"path": "data/chat_history_32k/chat_history_250913_163134_persona10.json",
                   "sha256": "037435a0633e16d2b1452b81b193b266173df8dc039c62d8c655ed161a1331eb"},
            "39": {"path": "data/chat_history_32k/chat_history_250913_163134_persona39.json",
                   "sha256": "79fb9facd43ae394ce0d4324cf7594966bf7d40b786059e37ec7d8779c6f61b8"},
            "55": {"path": "data/chat_history_32k/chat_history_250913_163134_persona55.json",
                   "sha256": "9475d7ba49185d5405c035727543af15d2dcda36024eb369f1c012a1390e28a6"},
        },
        "licence": "CC BY 4.0 (bowen-upenn/PersonaMem-v2)",
        "paper": "Jiang et al., arXiv:2512.06688",
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


def _download(url: str, path: Path, want: str) -> Path:
    """One pinned file into ``path`` (once), checked against ``want``. Refuses on a hash mismatch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and sha256(path) == want:
        return path
    part = path.with_suffix(path.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "cicada-benchmark"})
    with urllib.request.urlopen(req, timeout=60) as resp, part.open("wb") as out:  # noqa: S310 — pinned https URL
        for block in iter(lambda: resp.read(CHUNK), b""):
            out.write(block)
    got = sha256(part)
    if got != want:
        part.unlink(missing_ok=True)
        raise ValueError(f"{path.name}: sha256 {got} does not match the pin {want} — refusing it")
    part.replace(path)
    return path


def history_dir(cache: Path) -> Path:
    return cache / "personamem-v2-histories"


def fetch(name: str, cache: Path) -> Path:
    """Download one pinned dataset into ``cache`` (once), verify it, return the file the loader reads. Refuses on a hash
    mismatch."""
    src = SOURCES[name]
    path = _download(src["url"], cache / src["file"], src["sha256"])
    for persona, h in (src.get("histories") or {}).items():
        _download(src["histories_url"] + h["path"], history_dir(cache) / f"persona{persona}.json", h["sha256"])
    if src.get("derived"):
        derived = cache / src["derived"]
        if not (derived.is_file() and sha256(derived) == src["derived_sha256"]):
            parquet_to_json(path, derived)
            got = sha256(derived)
            if got != src["derived_sha256"]:
                derived.unlink(missing_ok=True)
                raise ValueError(f"{name}: converted file sha256 {got} does not match the pin "
                                 f"{src['derived_sha256']} — refusing it")
        return derived
    return path


def dataset_path(name: str, cache: Path) -> Path:
    """The verified local copy (no network): ``prepare`` must have fetched it."""
    src = SOURCES[name]
    path = cache / (src.get("derived") or src["file"])
    want = src.get("derived_sha256") or src["sha256"]
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing — run `prepare --dataset {name}` first")
    if sha256(path) != want:
        raise ValueError(f"{path} does not match its pinned sha256 — fetch it again")
    return path


_PARQUET_SCRIPT = r"""
import json, sys
import pyarrow.parquet as pq
rows = pq.read_table(sys.argv[1], columns=["user_id", "question", "answer", "choices", "documents", "hard"]).to_pylist()
users = {}
for r in rows:
    u = users.setdefault(str(r["user_id"]), {"documents": list(r["documents"]), "questions": []})
    if list(r["documents"]) != u["documents"]:
        raise SystemExit("user %s: rows disagree about the user's documents" % r["user_id"])
    u["questions"].append({"question": r["question"], "answer": r["answer"], "choices": list(r["choices"]),
                           "hard": bool(r["hard"])})
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump({"users": users}, fh, ensure_ascii=False, sort_keys=True)
"""


def parquet_to_json(parquet: Path, out: Path) -> None:
    """PersonalizationV4's parquet as plain JSON, once, at ``prepare``. Uses pyarrow when this interpreter has it, else
    ``uv run --with pyarrow`` (the only reason a run would touch the network here; the version does not change the
    text)."""
    try:
        import pyarrow  # noqa: F401
        cmd = [sys.executable, "-I", "-c", _PARQUET_SCRIPT, str(parquet), str(out)]
    except ImportError:
        cmd = ["uv", "run", "--no-project", "--with", "pyarrow", "python", "-I", "-c", _PARQUET_SCRIPT,
               str(parquet), str(out)]
    subprocess.run(cmd, check=True)


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


# --------------------------------------------------------------------------------------------------------------- #
# PersonalizationV4 and PersonaMem-v2 (personalization: use what a person's conversations show about them)
# --------------------------------------------------------------------------------------------------------------- #

PERSONAL_DATASETS = ("personalizationv4", "personamem-v2")
#: Neither dataset dates its conversations. They are given one every six hours from this day, in the dataset's order,
#: so a later chat is later; the question is asked an hour after the last.
_PERSONAL_START = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
_PERSONAL_STEP = timedelta(hours=6)


def _question_order(qid: str) -> str:
    """A fixed pseudo-random order for a user's questions (the files are grouped by category or topic), so "the first
    N" is a sample of all of them and a repeated slice is the same questions."""
    return hashlib.sha256(qid.encode("utf-8")).hexdigest()


def _personal_unit(unit_id: str, dataset: str, sessions: list[dict], questions: list[dict]) -> dict:
    start = _PERSONAL_START
    for i, s in enumerate(sessions):
        s["date"] = (start + i * _PERSONAL_STEP).isoformat()
        for j, t in enumerate(s["turns"]):
            t["ts"] = (start + i * _PERSONAL_STEP + timedelta(seconds=30 * j)).isoformat()
    last = start + (len(sessions) - 1) * _PERSONAL_STEP
    return {"unit_id": unit_id, "dataset": dataset, "owner": None, "other": None, "sessions": sessions,
            "questions": sorted(questions, key=lambda q: _question_order(q["qid"])),
            "clock": (last + timedelta(hours=1)).isoformat()}


def _personal_question(qid, question, answer, category, choices, evidence_texts=()):
    return {"qid": qid, "question": question, "answer": answer, "category": category, "category_id": None,
            "abstention": False, "evidence": [], "question_date": None, "choices": list(choices),
            "evidence_texts": list(evidence_texts)}


_PV4_CHAT = re.compile(r"^\s*Leo:\s*(.*?)\s*\n+\s*Assistant:\s*(.*?)\s*$", re.S)


def personalizationv4_units(path: Path) -> list[dict]:
    """One unit per evaluation user: their 200 two-turn chats (``Leo:`` is the dataset's fixed tag for the user), and
    their questions, each worded as the dataset words it (free text; the five candidate answers are kept only for the
    no-model leak check, never shown to a model). ``hard`` is the dataset's own hard-subset flag."""
    data = json.loads(path.read_text(encoding="utf-8"))["users"]
    units = []
    for uid in sorted(data, key=int):
        sessions = []
        for n, doc in enumerate(data[uid]["documents"]):
            m = _PV4_CHAT.match(doc)
            if m:
                turns = [{"speaker": "user", "text": m.group(1)}, {"speaker": "assistant", "text": m.group(2)}]
            elif doc.lstrip().startswith("Leo:"):   # 2 of 6,000 chats have no reply: the person's words stand alone
                turns = [{"speaker": "user", "text": doc.lstrip()[len("Leo:"):].strip()}]
            else:
                raise ValueError(f"PersonalizationV4 user {uid}: chat {n} is not the person's words")
            sessions.append({"source_id": f"bench:pv4-u{uid}:chat-{n:03d}", "title": f"Chat {n + 1}", "turns": turns})
        questions = [_personal_question(f"pv4-u{uid}:q{i:03d}", q["question"], q["answer"],
                                        "hard" if q["hard"] else "standard", q["choices"])
                     for i, q in enumerate(data[uid]["questions"])]
        units.append(_personal_unit(f"pv4-u{uid}", "personalizationv4", sessions, questions))
    return units


def _pm2_rows(path: Path) -> list[dict]:
    csv.field_size_limit(1 << 30)
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _pm2_choices(row: dict) -> tuple[str, list[str]]:
    """The reference answer and the question's choices (the reference first; the dataset does not keep an order)."""
    wrong = [str(x) for x in json.loads(row["incorrect_answers"])]
    return row["correct_answer"], [row["correct_answer"], *wrong]


def personamem_units(path: Path, cache: Path) -> list[dict]:
    """One unit per pinned persona (``SOURCES['personamem-v2']['histories']``): its 32k-token text chat history as
    one-exchange chats, and its queries. The history's first message is the generator's system prompt, which holds the
    persona's whole profile; it is dropped, since no assistant had it. A query is the user's last message
    (``user_query``); the rows' ``pref_type`` is the category."""
    pinned = SOURCES["personamem-v2"]["histories"]
    rows = _pm2_rows(path)
    units = []
    for persona in sorted(pinned, key=int):
        hist = history_dir(cache) / f"persona{persona}.json"
        if not hist.is_file() or sha256(hist) != pinned[persona]["sha256"]:
            raise FileNotFoundError(f"{hist} is missing or does not match its pin — run `prepare --dataset personamem-v2`")
        messages = [m for m in json.loads(hist.read_text(encoding="utf-8"))["chat_history"] if m.get("role") != "system"]
        sessions: list[dict] = []
        for m in messages:
            text = str(m.get("content") or "").strip()
            if not text:
                continue
            role = "user" if m.get("role") == "user" else "assistant"
            if role == "user" or not sessions:
                sessions.append({"source_id": f"bench:pm2-p{persona}:chat-{len(sessions):03d}",
                                 "title": f"Chat {len(sessions) + 1}", "turns": []})
            sessions[-1]["turns"].append({"speaker": role, "text": text})
        questions = []
        for i, row in enumerate(r for r in rows if r["persona_id"] == persona):
            query = ast.literal_eval(row["user_query"])
            answer, choices = _pm2_choices(row)
            snippet = json.loads(row["related_conversation_snippet"]) if row["related_conversation_snippet"] else []
            questions.append(_personal_question(
                f"pm2-p{persona}:q{i:03d}", str(query["content"] if isinstance(query, dict) else query), answer,
                row["pref_type"], choices, [str(t.get("content") or "") for t in snippet if t.get("role") == "user"]))
        units.append(_personal_unit(f"pm2-p{persona}", "personamem-v2", sessions, questions))
    return units


# --------------------------------------------------------------------------------------------------------------- #
# No-model checks: how far a question's choices give the answer away
# --------------------------------------------------------------------------------------------------------------- #

def choice_sets(name: str, cache: Path) -> list[dict]:
    """Every question of a personalization dataset as ``{"qid", "choices", "answer"}`` (all users or personas the
    dataset has, not only the pinned ones: this reads no chat history), for ``leak_check``."""
    path = dataset_path(name, cache)
    out = []
    if name == "personalizationv4":
        for uid, user in json.loads(path.read_text(encoding="utf-8"))["users"].items():
            out += [{"qid": f"pv4-u{uid}:q{i:03d}", "choices": q["choices"], "answer": q["answer"], "hard": q["hard"]}
                    for i, q in enumerate(user["questions"])]
    elif name == "personamem-v2":
        counts: dict[str, int] = {}
        for row in _pm2_rows(path):
            i = counts[row["persona_id"]] = counts.get(row["persona_id"], -1) + 1
            answer, choices = _pm2_choices(row)
            out.append({"qid": f"pm2-p{row['persona_id']}:q{i:03d}", "choices": choices, "answer": answer,
                        "hard": False})
    else:
        raise ValueError(f"{name} has no choices")
    return out


def leak_check(sets: list[dict], *, seed: int = 0, slots: bool = True) -> dict:
    """What picking an answer from the choices alone scores, with no model and no memory. A tie among the longest (or
    shortest) choices is credited 1/ties, so the figure is the expected accuracy of breaking ties at random. ``random``
    is one seeded draw per question; ``chance`` the exact expectation. The reference's slot (A-E) is counted for
    datasets that keep one."""
    import random

    rng = random.Random(seed)
    rules = {"longest": max, "shortest": min}
    score = {k: 0.0 for k in (*rules, "longest_words", "random")}
    positions: dict[int, int] = {}
    chance = 0.0
    n = 0
    for q in sets:
        choices = [c for c in q["choices"] if c]
        if q["answer"] not in choices:
            continue
        n += 1
        chance += 1 / len(choices)
        for name, pick in rules.items():
            best = pick(len(c) for c in choices)
            tied = [c for c in choices if len(c) == best]
            score[name] += (q["answer"] in tied) / len(tied)
        top = max(len(c.split()) for c in choices)
        tied = [c for c in choices if len(c.split()) == top]
        score["longest_words"] += (q["answer"] in tied) / len(tied)
        score["random"] += rng.choice(choices) == q["answer"]
        slot = q["choices"].index(q["answer"])
        positions[slot] = positions.get(slot, 0) + 1
    pct = lambda x: round(100.0 * x / n, 1) if n else None  # noqa: E731
    return {"n": n, "longest": pct(score["longest"]), "shortest": pct(score["shortest"]),
            "longest_words": pct(score["longest_words"]), "random": pct(score["random"]), "chance": pct(chance),
            "reference_slot": {str(k): pct(v) for k, v in sorted(positions.items())} if slots else None}


def load_units(name: str, cache: Path) -> list[dict]:
    path = dataset_path(name, cache)
    if name == "locomo":
        return locomo_units(path)
    if name.startswith("longmemeval-"):
        return longmemeval_units(path, name.split("-", 1)[1])
    if name == "personalizationv4":
        return personalizationv4_units(path)
    if name == "personamem-v2":
        return personamem_units(path, cache)
    raise ValueError(f"unknown dataset {name}")


def apply_questions(units: list[dict], fixture: dict, lang: str = "") -> list[dict]:
    """A question fixture (``benchmarks/public/fixtures/*.json``: ``{"lang", "questions": {qid: {lang: text, …}}}``):
    each unit keeps only the fixture's questions, worded in ``lang`` (default: the fixture's own), every category
    included. A unit with none is dropped. Gold answers and evidence stay the dataset's own."""
    lang = lang or str(fixture.get("lang") or "en")
    wanted = fixture.get("questions") or {}
    out = []
    for unit in units:
        qs = []
        for q in unit["questions"]:
            entry = wanted.get(q["qid"])
            if entry is None:
                continue
            if lang not in entry:
                raise ValueError(f"question fixture has no {lang!r} wording for {q['qid']}")
            qs.append({**q, "question": str(entry[lang]), "lang": lang})
        if qs:
            out.append({**unit, "questions": qs})
    return out


def apply_turns(units: list[dict], fixture: dict) -> list[dict]:
    """A turn fixture (``benchmarks/public/fixtures/*-turns.json``: ``{"lang", "turns": {unit_id: {session number:
    {turn index: text}}}}``): those turns reworded — e.g. translated, to ask a question over conversations held in
    another language — every other turn as the dataset has it. Sessions keep their ids, days and speakers, and each
    turn its dialogue id, so the evidence still names the (reworded) answer turns. A turn index past the session is an
    error, never a silent skip."""
    wanted = fixture.get("turns") or {}
    out = []
    for unit in units:
        mine = wanted.get(unit["unit_id"]) or {}
        if not mine:
            out.append(unit)
            continue
        sessions = []
        for s in unit["sessions"]:
            reworded = mine.get(s["source_id"].rsplit("-", 1)[-1]) or {}
            turns = [dict(t) for t in s["turns"]]
            for i, text in reworded.items():
                if not 0 <= int(i) < len(turns):
                    raise ValueError(f"turn fixture: {unit['unit_id']} {s['source_id']} has no turn {i}")
                turns[int(i)]["text"] = str(text)
            sessions.append({**s, "turns": turns})
        out.append({**unit, "sessions": sessions})
    return out


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
