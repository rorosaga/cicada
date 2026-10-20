"""Hard questions drafted from your own bank, for ``answer_eval`` (G148).

    api/.venv/bin/python -m benchmarks.hard_questions --bank <bank dir> --limit 40            # draft
    # open benchmarks/answer_eval.hard.review.local.md, tick "- [x] accept" on the ones that hold up
    api/.venv/bin/python -m benchmarks.hard_questions --accept                                 # keep the ticked ones
    api/.venv/bin/python -m benchmarks.answer_eval --bank <bank dir> \\
        --questions benchmarks/answer_eval.hard.accepted.local.yaml

The hand-written eval is mostly single-conversation recall. This samples the shapes it lacks from the bank's own
claims, evidence spans and pages — deterministically, by ``--seed`` — and asks the plan to draft ONE question per
sample in ``answer_eval``'s YAML shape:

- ``update`` — a claim a later claim superseded: the later value is expected, the stale one forbidden;
- ``temporal`` — one subject in two conversations far apart: what changed, what came first;
- ``multi-hop`` — a link from one page to another, each side with its own evidence: the answer needs both;
- ``count`` — a subject in 3+ conversations: list or count what those conversations said;
- ``event`` — two or more dated happenings on one page: their order, or the time between them;
- ``abstention`` — a plausible question about a sampled subject whose answer is in none of the evidence shown;
  the drafter must say why, and the item is ``abstain: true``;
- ``es`` — about a quarter of the samples (seeded) are drafted in Spanish, on top of their own kind.

**Privacy and the bank.** The bank is only read: pages through ``markdown_parser.parse``, conversations through
``evidence.source_document``; nothing is written into it and ``--out``/``--review`` may not point inside it. The
questions go to the YAML and the evidence each was drafted from goes to the review sheet — both gitignored
(``benchmarks/*.local.*``) and written 0600. The terminal shows ids, kinds and counts only. Each draft is one plan
call (``claude -p`` through Cicada's plan engine, ``--model`` sonnet by default); ``--dry-run`` samples and writes
the sheet with no call. A rerun keeps every question already in the YAML for the same sample (``--fresh`` redrafts).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "benchmarks" / "answer_eval.hard.local.yaml"
DEFAULT_REVIEW = REPO / "benchmarks" / "answer_eval.hard.review.local.md"
DEFAULT_ACCEPTED = REPO / "benchmarks" / "answer_eval.hard.accepted.local.yaml"

KINDS = ("update", "temporal", "multi-hop", "count", "event", "abstention")
TAGS = frozenset({*KINDS, "es"})
#: One cycle of the default mix (20 slots): a kind with no candidates gives its slot to the next kind that has one.
MIX = ("update", "temporal", "multi-hop", "count", "abstention", "update", "temporal", "multi-hop", "event",
       "abstention", "update", "temporal", "multi-hop", "count", "abstention", "update", "temporal", "multi-hop",
       "count", "event")
SPANISH_SHARE = 0.25
MIN_GAP_DAYS = 14
SNIPPET_CHARS = 520
MAX_SNIPPETS = 6
MAX_CLAIMS = 14
SKIP_SUBJECT_TYPES = frozenset({"media"})

_EP_DAY_RE = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_")
ACCEPT_RE = re.compile(r"^\s*-\s*\[[xX]\]\s*accept\s+(\S+)")


# ---------------------------------------------------------------------------------------------- reading the bank

@dataclass
class Conversation:
    id: str
    day: str
    title: str
    body: str


@dataclass
class Page:
    id: str
    name: str
    type: str
    names: list[str]
    claims: list            # claims.Claim
    episodes: list[str]     # conversation ids that mention it, oldest first


@dataclass
class Sample:
    kind: str
    key: str                # stable across runs: the kind plus the claim/page/conversation ids it was drawn from
    page: str
    spanish: bool
    sources: list[str]
    claims: list[str]       # display lines for the drafter
    snippets: list[dict]    # {episode, day, title, text}
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"hq-{self.kind}-{hashlib.sha256(self.key.encode()).hexdigest()[:8]}"

    @property
    def tags(self) -> list[str]:
        return [self.kind, *(["es"] if self.spanish else [])]


class Bank:
    """A read-only view of one bank: its pages (owner page left out) and the conversations they cite."""

    def __init__(self, root: Path):
        from api.services import markdown_parser
        from api.services.claims import parse_claims

        self.root = root
        self._docs: dict[str, Conversation | None] = {}
        self.pages: dict[str, Page] = {}
        for path in sorted((root / "entities").glob("*.md")):
            try:
                head = markdown_parser.parse(path, ledger=False)
            except Exception:  # noqa: BLE001 — an unreadable page is skipped, never fatal
                continue
            fm = head.frontmatter or {}
            if fm.get("owner") is True or str(fm.get("status") or "") in ("dropped",):
                continue
            try:
                parsed = markdown_parser.parse(path) if fm.get("claims_ledger") else head
                claims = parse_claims(parsed.body)
            except Exception:  # noqa: BLE001
                claims = []
            eid = path.stem
            name = str(fm.get("name") or eid)
            aliases = [str(a) for a in (fm.get("aliases") or []) if isinstance(a, (str, int))]
            names = sorted({n for n in [name, eid.replace("-", " "), *aliases] if len(str(n).strip()) >= 3},
                           key=lambda n: (-len(n), n))
            cited: set[str] = {str(e) for e in (fm.get("source_episodes") or []) if isinstance(e, str)}
            for c in claims:
                cited.update(str(e) for e in c.source_episodes or [])
                cited.update(ev.episode for ev in c.evidence or [] if ev.episode)
            episodes = sorted((e for e in cited if self.conversation(e) is not None),
                              key=lambda e: (self.conversation(e).day, e))
            self.pages[eid] = Page(eid, name, str(fm.get("type") or ""), names, claims, episodes)

    def conversation(self, doc_id: str) -> Conversation | None:
        """A dated conversation by id, or ``None`` (not an episode, missing, untimed, or an indexed-only record)."""
        if doc_id in self._docs:
            return self._docs[doc_id]
        from api.services import episode_time, evidence, history_index

        conv = None
        if evidence.is_episode_id(doc_id):
            doc = evidence.source_document(self.root, doc_id)
            if doc is not None:
                fm, body = doc
                if episode_time.counts_as_activity(fm) and history_index.kind(fm) is None:
                    day = str(fm.get("timestamp") or "")[:10]
                    if not _is_day(day):
                        m = _EP_DAY_RE.match(doc_id)
                        day = m.group(1) if m else ""
                    if _is_day(day):
                        conv = Conversation(doc_id, day, str(fm.get("title") or ""), body)
        self._docs[doc_id] = conv
        return conv


def _is_day(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _days_between(a: str, b: str) -> int:
    return abs((date.fromisoformat(b) - date.fromisoformat(a)).days)


# ---------------------------------------------------------------------------------------------- evidence snippets

def _window(text: str, start: int, end: int, chars: int = SNIPPET_CHARS) -> str:
    """About ``chars`` of text around the span, snapped outward to whole lines where they fit, else to words."""
    end = max(end, start)
    pad = max(0, (chars - (end - start)) // 2)
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    if hi - lo < chars:  # near an edge: give the room to the other side
        lo, hi = max(0, min(lo, hi - chars)), min(len(text), max(hi, lo + chars))
    line_lo = text.rfind("\n", 0, lo) + 1
    if lo - line_lo < 120:
        lo = line_lo
    elif (sp := text.find(" ", lo, start)) >= 0:
        lo = sp + 1
    line_hi = text.find("\n", hi)
    line_hi = len(text) if line_hi < 0 else line_hi
    if line_hi - hi < 120:
        hi = line_hi
    elif (sp := text.rfind(" ", end, hi)) >= 0:
        hi = sp
    out = text[lo:hi].strip()
    return ("… " if lo > 0 else "") + out + (" …" if hi < len(text) else "")


def snippet(bank: Bank, page: Page, episode: str, claim_ids: set[str] | None = None) -> dict | None:
    """What ``episode`` says about ``page``: a claim's evidence span there, else the first mention of a name, else
    the conversation's opening."""
    conv = bank.conversation(episode)
    if conv is None:
        return None
    text = conv.body
    for c in page.claims:
        if claim_ids is not None and c.id not in claim_ids:
            continue
        for ev in c.evidence or []:
            if ev.episode == episode and ev.is_span() and ev.end <= len(text):
                return {"episode": episode, "day": conv.day, "title": conv.title,
                        "text": _window(text, ev.start, ev.end)}
    low = text.lower()
    for name in page.names:
        at = low.find(name.lower())
        if at >= 0:
            return {"episode": episode, "day": conv.day, "title": conv.title,
                    "text": _window(text, at, at + len(name))}
    return {"episode": episode, "day": conv.day, "title": conv.title, "text": _window(text, 0, 0)}


def _claim_line(c) -> str:
    when = f"from {c.valid_from}" if c.valid_from else ""
    if c.valid_to:
        when += f" until {c.valid_to}"
    if getattr(c, "status", None):
        when += f" ({c.status})"
    state = "closed" if c.valid_to or c.superseded_by else "current"
    return f"[{state}{', ' + when.strip() if when.strip() else ''}] {c.text}".strip()


def _claim_days(c, bank: Bank) -> list[str]:
    days = [bank.conversation(e).day for e in (c.source_episodes or []) if bank.conversation(e)]
    return sorted(days)


def _claim_episodes(c, bank: Bank) -> list[str]:
    eps = {*(c.source_episodes or []), *(ev.episode for ev in c.evidence or [] if ev.episode)}
    return sorted((e for e in eps if bank.conversation(e)), key=lambda e: (bank.conversation(e).day, e))


def _claims_for(page: Page, limit: int = MAX_CLAIMS) -> list[str]:
    from api.services.claims import is_record

    lines = [_claim_line(c) for c in page.claims if (c.text or "").strip() and not is_record(c)]
    return lines[:limit]


# ---------------------------------------------------------------------------------------------- samplers

def _subjects(bank: Bank):
    """Pages a question can be about: a saved link or video (``media``) is a thing kept, not a subject talked over."""
    return (p for p in bank.pages.values() if p.type not in SKIP_SUBJECT_TYPES)


def _distinct(snips) -> list[dict]:
    seen, out = set(), []
    for s in snips:
        if s and (s["episode"], s["text"]) not in seen:
            seen.add((s["episode"], s["text"]))
            out.append(s)
    return out


def _update_candidates(bank: Bank) -> list[Sample]:
    from api.services.claims import is_record

    out = []
    for page in _subjects(bank):
        by_id = {c.id: c for c in page.claims}
        for old in page.claims:
            new = by_id.get(old.superseded_by or "")
            if (new is None or new.valid_to or new.superseded_by or not (old.text and new.text)
                    or is_record(old) or is_record(new)):  # a withdrawal is no new value
                continue
            eps = _claim_episodes(old, bank) + [e for e in _claim_episodes(new, bank) if e not in _claim_episodes(old, bank)]
            if not eps:
                continue
            snips = _distinct(snippet(bank, page, e, {old.id, new.id}) for e in eps[:MAX_SNIPPETS])
            out.append(Sample("update", f"update:{page.id}:{old.id}:{new.id}", page.id, False, eps, [
                f"EARLIER (superseded): {_claim_line(old)}", f"LATER (current): {_claim_line(new)}"], snips,
                {"stale": old.text}))
    return out


def _temporal_candidates(bank: Bank) -> list[Sample]:
    out = []
    for page in _subjects(bank):
        if len(page.episodes) < 2:
            continue
        first, last = page.episodes[0], page.episodes[-1]
        gap = _days_between(bank.conversation(first).day, bank.conversation(last).day)
        if gap < MIN_GAP_DAYS:
            continue
        snips = _distinct(snippet(bank, page, e) for e in (first, last))
        out.append(Sample("temporal", f"temporal:{page.id}:{first}:{last}", page.id, False, [first, last],
                          _claims_for(page), snips, {"gap_days": gap}))
    return out


def _multi_hop_candidates(bank: Bank) -> list[Sample]:
    out = []
    for page in _subjects(bank):
        for c in page.claims:
            target = bank.pages.get(c.object or "") if c.object_kind == "node" else None
            if target is None or target.id == page.id or c.valid_to or not c.text:
                continue
            eps_a = _claim_episodes(c, bank)
            # The second hop must come from a conversation the first did not: the answer needs both.
            onward = [(d, [e for e in _claim_episodes(d, bank) if e not in eps_a]) for d in target.claims
                      if not d.valid_to and d.text and d.object != page.id]
            onward = [(d, eps) for d, eps in onward if eps]
            if not eps_a or not onward:
                continue
            d, eps_b = onward[0]
            sa = snippet(bank, page, eps_a[0], {c.id})
            sb = snippet(bank, target, eps_b[0], {d.id})
            sources = [eps_a[0], eps_b[0]]
            out.append(Sample("multi-hop", f"multi-hop:{page.id}:{c.id}:{target.id}:{d.id}", page.id, False, sources,
                              [f"HOP 1 ({page.name}): {_claim_line(c)}", f"HOP 2 ({target.name}): {_claim_line(d)}"],
                              _distinct((sa, sb)), {"bridge": target.id}))
            break  # one bridge per page keeps the pool diverse
    return out


def _count_candidates(bank: Bank) -> list[Sample]:
    out = []
    for page in _subjects(bank):
        if len(page.episodes) < 3:
            continue
        eps = page.episodes[:MAX_SNIPPETS]
        snips = _distinct(snippet(bank, page, e) for e in eps)
        out.append(Sample("count", f"count:{page.id}:{len(page.episodes)}", page.id, False, eps, _claims_for(page),
                          snips, {"conversations": len(page.episodes), "shown": len(eps)}))
    return out


def _event_candidates(bank: Bank) -> list[Sample]:
    from api.services.claims import is_event

    out = []
    for page in _subjects(bank):
        events = sorted((c for c in page.claims if is_event(c) and c.valid_from and c.text),
                        key=lambda c: (str(c.valid_from), c.id))
        if len({str(c.valid_from)[:10] for c in events}) < 2:
            continue
        events = events[:MAX_CLAIMS]
        eps = list(dict.fromkeys(e for c in events for e in _claim_episodes(c, bank)))
        snips = _distinct(snippet(bank, page, e, {c.id for c in events}) for e in eps[:MAX_SNIPPETS])
        out.append(Sample("event", f"event:{page.id}:{','.join(c.id for c in events)}", page.id, False, eps,
                          [_claim_line(c) for c in events], snips))
    return out


def _abstention_candidates(bank: Bank) -> list[Sample]:
    out = []
    for page in _subjects(bank):
        if len(page.episodes) < 2 or not page.claims:
            continue
        eps = page.episodes[:MAX_SNIPPETS]
        snips = _distinct(snippet(bank, page, e) for e in eps)
        out.append(Sample("abstention", f"abstention:{page.id}", page.id, False, eps, _claims_for(page), snips))
    return out


SAMPLERS: dict[str, Callable[[Bank], list[Sample]]] = {
    "update": _update_candidates, "temporal": _temporal_candidates, "multi-hop": _multi_hop_candidates,
    "count": _count_candidates, "event": _event_candidates, "abstention": _abstention_candidates,
}


def draw(bank: Bank, limit: int, seed: int, kinds: tuple[str, ...] = KINDS) -> list[Sample]:
    """``limit`` samples, the same ones for the same bank and seed: each kind's pool shuffled by its own seeded
    generator, filled slot by slot from ``MIX``, one sample per page."""
    pools: dict[str, list[Sample]] = {}
    for kind in kinds:
        pool = sorted(SAMPLERS[kind](bank), key=lambda s: s.key)
        random.Random(f"{seed}:{kind}").shuffle(pool)
        pools[kind] = pool
    lang = random.Random(f"{seed}:es")
    mix = [k for k in MIX if k in kinds] or list(kinds)
    used_pages: set[str] = set()
    out: list[Sample] = []
    slot = 0
    while len(out) < limit and any(pools.values()):
        order = [mix[(slot + i) % len(mix)] for i in range(len(mix))]
        slot += 1
        for kind in order:
            pool = pools.get(kind) or []
            while pool and pool[0].page in used_pages:
                pool.pop(0)
            if pool:
                s = pool.pop(0)
                used_pages.add(s.page)
                s.spanish = lang.random() < SPANISH_SHARE
                out.append(s)
                break
    return out


# ---------------------------------------------------------------------------------------------- drafting

DRAFT_SYSTEM = """You write evaluation questions for a personal memory system that answers questions about one \
person's own life from their past conversations. You see evidence drawn from that person's memory. Write ONE question \
the person could plausibly ask their memory, answerable (or, when told, deliberately NOT answerable) from the evidence \
shown and from nothing else. Address the person as "I"/"my" in the question. Expected facts are short, checkable \
statements a right answer must contain; never add a fact the evidence does not state. `forbid` holds only facts the evidence shows are stale or wrong (an earlier value that changed); never invent distractors — leave it empty otherwise. Return ONLY JSON."""

KIND_BRIEFS = {
    "update": "KNOWLEDGE UPDATE. A value changed: the LATER claim replaced the EARLIER one. Ask for the current value "
              "without hinting that it changed. `expect` holds the later value; `forbid` MUST hold the earlier value, "
              "stated as a fact (e.g. \"X is <earlier value>\").",
    "temporal": "TEMPORAL. The same subject came up in two conversations {gap_days} days apart. Ask something whose "
                "answer needs both moments: what changed between them, what came first, or how long between them. "
                "`expect` names what each conversation contributed, with its timing where it matters.",
    "multi-hop": "MULTI-HOP. HOP 1 links the subject to a second page; HOP 2 is a fact about that second page. Ask a "
                 "question about the subject whose answer needs HOP 2 without naming the second page in the question "
                 "(e.g. \"what does the tool my <project> runs on cost?\"). `expect` holds the HOP 2 fact and names "
                 "the bridge.",
    "count": "COUNT / LIST. The subject came up in {conversations} conversations; you see {shown}. Ask for a list or a "
             "count of discrete things the shown conversations state about it (options considered, places, steps, "
             "people) — never \"how many conversations\". `expect` lists each item.",
    "event": "EVENTS. These are dated happenings on one page. Ask about their order, or what happened before/after "
             "one of them, or the time between two. `expect` states the order or dates.",
    "abstention": "ABSTENTION TRAP. Ask a plausible, specific question about this subject whose answer appears in NONE "
                  "of the evidence or claims shown (something a person might expect memory to know, e.g. a date, a "
                  "price, a name, a reason that was never said). Set \"abstain\": true, leave `expect` empty, and in "
                  "`why` say what is missing and why the evidence does not answer it. Do not ask about something the "
                  "evidence touches on indirectly.",
}

DRAFT_TEMPLATE = """{brief}

SUBJECT: {name} ({type})

CLAIMS ON RECORD:
{claims}

EVIDENCE FROM CONVERSATIONS:
{snippets}

LANGUAGE: {language}

If the evidence cannot support a fair question of this kind, return {{"skip": true, "why": "<one sentence>"}}.
Otherwise return exactly:
{{"question": "...", "expect": ["..."], "forbid": ["..."], "abstain": false, "why": "one sentence: what the \
question tests and which evidence answers it (or, for an abstention, what is absent)", "skip": false}}"""


def draft_prompt(sample: Sample, bank: Bank) -> str:
    page = bank.pages[sample.page]
    brief = KIND_BRIEFS[sample.kind].format(**{"gap_days": "", "conversations": "", "shown": "", **sample.extra})
    snips = "\n\n".join(f"[{s['episode']} · {s['day']} · {s['title']}]\n{s['text']}" for s in sample.snippets)
    language = ("Write the question in natural Spanish (as a Spanish speaker would ask it); expected and forbidden "
                "facts may be in Spanish too." if sample.spanish else "Write the question in English.")
    return DRAFT_TEMPLATE.format(brief=brief, name=page.name, type=page.type or "thing",
                                 claims="\n".join(f"- {c}" for c in sample.claims) or "(none)",
                                 snippets=snips or "(none)", language=language)


def _strs(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in (value or []) if str(v).strip()][:6]


def to_item(sample: Sample, reply: dict | None) -> tuple[dict | None, str | None]:
    """The YAML item for a draft, or ``(None, reason)`` when it is skipped or unusable."""
    if not isinstance(reply, dict):
        return None, "unparseable reply"
    if reply.get("skip") is True:
        return None, "drafter skipped: " + str(reply.get("why") or "")[:200]
    question = str(reply.get("question") or "").strip()
    if not question or len(question) > 400:
        return None, "no usable question"
    abstain = sample.kind == "abstention"
    expect = [] if abstain else _strs(reply.get("expect"))
    forbid = _strs(reply.get("forbid"))
    why = str(reply.get("why") or "").strip()[:400]
    if abstain and not why:
        return None, "abstention without a reason"
    if not abstain and not expect:
        return None, "no expected facts"
    if sample.kind == "update" and not forbid:
        forbid = [str(sample.extra.get("stale") or "")][:1]
    item = {"id": sample.id, "question": question, "expect": expect, "forbid": forbid, "abstain": abstain,
            "tags": sample.tags, "sources": list(sample.sources), "why": why, "sample": sample.key}
    return item, None


# ---------------------------------------------------------------------------------------------- files

def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def write_yaml(path: Path, items: list[dict]) -> None:
    import yaml

    head = ("# Drafted by benchmarks/hard_questions.py from your own bank — gitignored, never commit it.\n"
            "# Review each one in the review sheet before use; `--accept` keeps the ticked ones.\n")
    _write_private(path, head + yaml.safe_dump({"questions": items}, allow_unicode=True, sort_keys=False, width=110))


def _quote(text: str) -> str:
    return "\n".join("> " + line for line in (text or "").splitlines()) or "> (empty)"


def write_review(path: Path, samples: list[Sample], items: dict[str, dict], skipped: dict[str, str],
                 yaml_path: Path) -> None:
    lines = ["# Hard questions — review sheet (local, gitignored)", "",
             f"Questions: `{yaml_path.name}`. Tick `- [x] accept <id>` on each question that is fair and whose "
             "expected facts the evidence below really states (for an abstention: really does not state), then run "
             "`python -m benchmarks.hard_questions --accept`. Edit a question's wording in the YAML if it only needs "
             "a fix.", ""]
    for s in samples:
        item = items.get(s.id)
        lines.append(f"## {s.id} · {s.kind}{' · es' if s.spanish else ''}")
        lines.append("")
        if item:
            lines += [f"- [ ] accept {s.id}", "", f"**Q:** {item['question']}", ""]
            if item["abstain"]:
                lines.append("**Should abstain.**")
            for f in item["expect"]:
                lines.append(f"- expect: {f}")
            for f in item["forbid"]:
                lines.append(f"- forbid: {f}")
            if item.get("why"):
                lines += ["", f"_Why:_ {item['why']}"]
        elif s.id in skipped:
            lines.append(f"_Not drafted — {skipped[s.id]}_")
        else:
            lines.append("_Sample only (dry run)._")
        lines += ["", f"Sources: {', '.join(s.sources)}", "", "Claims shown:"]
        lines += [f"- {c}" for c in s.claims] or ["- (none)"]
        lines += ["", "Evidence shown:", ""]
        for sn in s.snippets:
            lines += [f"`{sn['episode']}` · {sn['day']} · {sn['title']}", "", _quote(sn["text"]), ""]
        lines.append("")
    _write_private(path, "\n".join(lines))


def _load_items(path: Path) -> list[dict]:
    import yaml

    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [q for q in data.get("questions") or [] if isinstance(q, dict) and q.get("id")]


def accept(yaml_path: Path, review_path: Path, accepted_path: Path) -> int:
    ticked = {m.group(1) for line in review_path.read_text(encoding="utf-8").splitlines()
              if (m := ACCEPT_RE.match(line))}
    items = [q for q in _load_items(yaml_path) if q["id"] in ticked]
    write_yaml(accepted_path, items)
    print(f"accepted {len(items)} of {len(_load_items(yaml_path))} → {accepted_path}")
    return 0


# ---------------------------------------------------------------------------------------------- main

def plan_llm(model: str):
    from api.config import get_settings
    from api.services import providers

    settings = get_settings().model_copy(update={"llm_mode": "agent", "agent_model": model})
    return providers.resolve_llm_fn(settings, stage="judge", is_async=False)


def run(bank_dir: Path, *, limit: int, seed: int, out: Path, review: Path, dry_run: bool, fresh: bool,
        kinds: tuple[str, ...], llm=None, model: str = "sonnet") -> dict:
    from api.services import json_parse

    bank = Bank(bank_dir)
    samples = draw(bank, limit, seed, kinds)
    kept = {} if fresh else {q.get("sample"): q for q in _load_items(out)}
    items: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    calls = 0
    for s in samples:
        if dry_run:
            continue
        if s.key in kept:
            items[s.id] = kept[s.key]
            continue
        if llm is None:
            llm = plan_llm(model)
        calls += 1
        try:
            reply = llm(messages=[{"role": "system", "content": DRAFT_SYSTEM},
                                  {"role": "user", "content": draft_prompt(s, bank)}],
                        response_format={"type": "json_object"})
            content = reply.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 — one failed draft is reported, never fatal
            content, skipped[s.id] = "", f"draft failed: {type(exc).__name__}"
        try:
            parsed = json_parse.parse_json_object(content)
        except Exception:  # noqa: BLE001 — to_item reports it
            parsed = None
        if s.id not in skipped:
            item, why = to_item(s, parsed)
            if item:
                items[s.id] = item
            else:
                skipped[s.id] = why or "skipped"
        print(f"{s.id:24} {s.kind:10} {'es' if s.spanish else '  '}  "
              f"{'drafted' if s.id in items else 'skipped'}", flush=True)
    if not dry_run:
        write_yaml(out, [items[s.id] for s in samples if s.id in items])
    write_review(review, samples, items, skipped, out)
    by_kind: dict[str, int] = defaultdict(int)
    for s in samples:
        by_kind[s.kind] += 1
    return {"samples": len(samples), "by_kind": dict(by_kind), "spanish": sum(s.spanish for s in samples),
            "drafted": len(items), "skipped": len(skipped), "plan_calls": calls}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bank", type=Path, help="the bank folder to read (named explicitly, never guessed)")
    ap.add_argument("--limit", type=int, default=30, help="how many samples (one plan call each)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--kinds", nargs="*", choices=KINDS, help="only these kinds (default: all)")
    ap.add_argument("--model", default="sonnet", help="the plan model that drafts")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    ap.add_argument("--accepted", type=Path, default=DEFAULT_ACCEPTED)
    ap.add_argument("--dry-run", action="store_true", help="sample and write the review sheet; no plan call")
    ap.add_argument("--fresh", action="store_true", help="redraft samples already in --out")
    ap.add_argument("--accept", action="store_true", help="write --accepted from the ticked items in --review")
    a = ap.parse_args(argv)

    os.environ.setdefault("CICADA_TELEMETRY", "off")   # a measurement, not the person's use
    os.environ.setdefault("CICADA_CAPTURE", "off")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    if a.accept:
        return accept(a.out, a.review, a.accepted)
    if a.bank is None:
        ap.error("--bank is required (or --accept)")
    bank = a.bank.expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(f"no entities/ under {bank} — --bank takes a bank folder", file=sys.stderr)
        return 2
    for p in (a.out, a.review):
        rp = p.expanduser().resolve()
        if rp == bank or bank in rp.parents:
            print("--out and --review must be outside the bank", file=sys.stderr)
            return 2
    summary = run(bank, limit=max(0, a.limit), seed=a.seed, out=a.out, review=a.review, dry_run=a.dry_run,
                  fresh=a.fresh, kinds=tuple(a.kinds or KINDS), model=a.model)
    kinds = " · ".join(f"{k} {n}" for k, n in sorted(summary["by_kind"].items()))
    print(f"\n{summary['samples']} samples ({kinds}; {summary['spanish']} in Spanish) · {summary['drafted']} drafted · "
          f"{summary['skipped']} skipped · {summary['plan_calls']} plan calls")
    if not a.dry_run:
        print(f"questions: {a.out}")
    print(f"review sheet: {a.review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
