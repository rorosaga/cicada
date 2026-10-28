"""Sleep asks whether a quiet fact about the person still holds (vision item 10, S5 and the stale-interest case).

The owner (2026-10-28): "'are you still working at <org>?' is a valid question … if I haven't mentioned anything
about that fact, and my LinkedIn looks stale", and "'are you still interested in learning about <topic>? You
mentioned it one time like 2 months ago, and I don't want to push you on that'". Both are the same move: an **open
claim on the person's own page** whose predicate describes a state that ends — a role (:data:`ROLE`) or an interest
(:data:`INTEREST`) — that nobody has said again for a while. Engine-free, so it runs on every drain's tail and on
idle nights without a plan (ruling 4), in its own ``cicada`` commit, the follow-ups' pattern.

**When it asks** (each is a rule, never a guess):

* the claim is open, not an event (G141), and a dated conversation said it — a memory export entry or an import is
  no mention (the decay rail: age counts from when it was said, ``claim_reconciler._said``);
* it was last said at least :data:`ROLE_QUIET_DAYS` (a role) or :data:`INTEREST_QUIET_DAYS` (an interest — and at
  most :data:`INTEREST_MAX_DAYS`: an interest unsaid for over a year is history, not a question) ago, and
  the thing it names has not been said since either (its own page's ``last_referenced``) — a topic still alive in
  other words is not asked about;
* for a role, no tracked source on the page re-read it within its own cadence (ruling 26: a fresh re-check keeps
  the fact current by itself, so asking would be noise). A stale or dead source is the question's human reason
  ("your LinkedIn seems a bit stale", ``inbox_wording.source_cue``) — read from its stored ``refresh`` state, never
  fetched: a walled profile is only ever read by the person's own agent;
* for an interest, the page it names holds no open decay question (that one already asks "still interested?");
* the person did not answer this very claim within :data:`ANSWER_QUIET_DAYS` (``_still_answered.yaml``, written by
  the resolver — the G113 ``_merge_rejected.yaml`` pattern: a question answered is not asked again next week).

**Never pushy (UX principle 4, the volume rail):** at most :data:`MAX_OPEN` open in the bank, at most one per
``(page, predicate)`` (the conflict kind's own dedup key), and each drain writes only what the shared per-Sleep
budget leaves (``inbox_catchup.Budget``). Only the person's own page: a third party's job is not this module's to
ask about (Needs the owner, vision item 10 S5).

**What it writes** is an ordinary ``conflict`` question marked ``asks: still`` (additive — an older app draws it as a
one-choice conflict): option ``a`` is the claim ("still"), ``neither`` is "not anymore", free text is "something
else". The person's own conflict resolver answers it: ``a`` reinforces the claim, ``neither`` closes it today, an
answer writes their words as a new claim and closes the old one. Sleep's tending never settles one by rule or by
judge (only the person's own located words, ruling 29 part 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml
from loguru import logger

from api.services import bank_index, git_service, inbox_wording, markdown_parser

TRIGGER = "sleep/still-questions"
AUTHOR = "cicada"
ASKS = "still"
FILE = "_still_answered.yaml"

ROLE = ("works-at", "employed-by", "studies-at", "lives-in", "reports-to")
INTEREST = tuple(sorted(inbox_wording.INTEREST_PREDICATES))
ROLE_QUIET_DAYS = 180
INTEREST_QUIET_DAYS = 60
INTEREST_MAX_DAYS = 365
ANSWER_QUIET_DAYS = {"role": 180, "interest": 120}
MAX_OPEN = 4
PRIORITY = {"role": 0.7, "interest": 0.45}
NOT_ANYMORE = {"key": "neither", "label": "Not anymore",
               "description": "Close it — say what's true now if you like", "claim_id": None}


def family(predicate: str) -> str | None:
    p = str(predicate or "").strip().lower()
    if p in ROLE:
        return "role"
    if p in INTEREST:
        return "interest"
    return None


# --------------------------------------------------------------------------- the answers store


def _store(memory_path: Path) -> Path:
    return Path(memory_path) / FILE


def load_answers(memory_path: Path) -> dict[str, dict]:
    """``{claim id: {"on": day, "answer": enum}}``. A missing or unreadable file is no answers."""
    path = _store(memory_path)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    rows = data.get("answered") if isinstance(data, dict) else None
    return {str(k): dict(v) for k, v in (rows or {}).items() if isinstance(v, dict)}


#: The answer enum the store keeps (never a label or the person's words).
ANSWERS = ("still", "ended", "other", "dismissed")


def record_answer(memory_path: Path, claim_id: str, answer: str, today: str) -> Path | None:
    """Remember that the person answered the "still?" question on ``claim_id`` (an enum and a day). The caller
    commits the file with the answer. None when there is no claim id."""
    claim_id = str(claim_id or "").strip()
    if not claim_id:
        return None
    rows = load_answers(memory_path)
    rows[claim_id] = {"on": str(today)[:10], "answer": answer if answer in ANSWERS else "other"}
    path = _store(memory_path)
    path.write_text(yaml.safe_dump({"answered": dict(sorted(rows.items()))}, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path


#: "Not anymore", said of the one value a "still?" question asked about. ``{name}`` the page, ``{obj}`` the value.
ENDED = {
    "works-at": "{name} no longer works at {obj}", "employed-by": "{name} no longer works at {obj}",
    "studies-at": "{name} no longer studies at {obj}", "lives-in": "{name} no longer lives in {obj}",
    "reports-to": "{name} no longer reports to {obj}",
    "is-interested-in": "{name} is no longer interested in {obj}",
    "interested-in": "{name} is no longer interested in {obj}",
    "wants-to-learn": "{name} no longer wants to learn about {obj}",
    "is-learning": "{name} is no longer learning about {obj}", "learning": "{name} is no longer learning about {obj}",
    "studies": "{name} no longer studies {obj}",
}


def ended_sentence(predicate: str, name: str, label: str, today: str) -> str:
    """The answer's sentence for "Not anymore": it names only the value that ended, so the page's prose rewrite can
    never read it as every value of the predicate ending (a multi-valued interest or role beside it stays)."""
    template = ENDED.get(str(predicate or "").strip().lower(), "{name} — {obj} no longer holds")
    return f"{template.format(name=name, obj=label or 'it')} (said on {today})."


def answer_enum(label: str) -> str:
    """The resolver's action label as the store's enum."""
    if label.startswith("pick:"):
        return "still"
    if label == "neither":
        return "ended"
    if label == "dismiss":
        return "dismissed"
    return "other"


# --------------------------------------------------------------------------- candidates


@dataclass(frozen=True)
class Candidate:
    claim_id: str
    predicate: str
    family: str
    label: str
    object_id: str
    last_said: str
    said_in: int
    episode: str
    cue: str | None          # inbox_wording.source_cue's state, a role's only
    use: float


@dataclass
class Report:
    written: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _open_decay_pages(memory_path: Path) -> set[str]:
    out = set()
    for f in bank_index.files(memory_path, "inbox"):
        fm = f.frontmatter or {}
        if str(fm.get("kind") or "") == "decay" and str(fm.get("status") or "pending") == "pending":
            out.add(str(fm.get("entity_id") or ""))
    return out


def candidates(memory_path: Path, today: date, report: Report | None = None) -> list[Candidate]:
    """Every claim on the person's own page this module would ask about today, most-used first. Read-only."""
    from api.services import claim_reconciler, episode_time, everyday_names, page_use
    from api.services.claims import is_event, parse_claims
    from api.services.id_utils import resolve_entity_file

    report = report if report is not None else Report()
    memory_path = Path(memory_path)
    owner = everyday_names.owner_id(memory_path)
    if not owner:
        report.skip("no_owner_page")
        return []
    page_path = memory_path / "entities" / f"{owner}.md"
    if not page_path.exists():
        report.skip("no_owner_page")
        return []
    page = markdown_parser.parse(page_path)
    try:
        claims = parse_claims(page.body)
    except Exception:  # noqa: BLE001 — an unreadable page is asked nothing tonight
        report.skip("unreadable_page")
        return []
    untimed = episode_time.untimed_ids(memory_path)
    answers = load_answers(memory_path)
    decaying = _open_decay_pages(memory_path)
    use = page_use.scores(memory_path, today=today)
    out: list[Candidate] = []
    for c in claims:
        fam = family(c.predicate)
        if fam is None or c.valid_to is not None:
            continue
        if is_event(c):
            report.skip("event")
            continue
        said = claim_reconciler._said(c, untimed)
        said_day = _day(said)
        if said_day is None:
            report.skip("never_said_in_a_conversation")
            continue
        quiet = ROLE_QUIET_DAYS if fam == "role" else INTEREST_QUIET_DAYS
        if (today - said_day).days < quiet:
            report.skip("said_recently")
            continue
        if fam == "interest" and (today - said_day).days > INTEREST_MAX_DAYS:
            report.skip("long_past")   # an interest unsaid for over a year is history, not a question
            continue
        answered = answers.get(c.id)
        if answered:
            on = _day(answered.get("on"))
            if on is not None and (today - on).days < ANSWER_QUIET_DAYS[fam]:
                report.skip("answered_recently")
                continue
        obj_path = resolve_entity_file(memory_path, c.object) if c.object_kind == "node" and c.object else None
        obj_fm = markdown_parser.parse(obj_path).frontmatter if obj_path is not None else {}
        obj_said = _day(obj_fm.get("last_referenced"))
        if obj_said is not None and (today - obj_said).days < quiet:
            report.skip("topic_still_said")
            continue
        obj_id = obj_path.stem if obj_path is not None else ""
        if fam == "interest" and obj_id and obj_id in decaying:
            report.skip("decay_question_open")
            continue
        cue = None
        if fam == "role":
            cue, _phrase = inbox_wording.source_cue(page.frontmatter, c.predicate, today, own=True)
            if cue == inbox_wording.FRESH:
                report.skip("source_fresh")
                continue
        refs = claim_reconciler._said_refs(c)
        dated = sorted((r for r in refs if r.startswith("ep_") and r not in untimed), reverse=True)
        label = str(obj_fm.get("name") or c.object or "").strip()
        if not label:
            report.skip("no_object")
            continue
        out.append(Candidate(claim_id=c.id, predicate=c.predicate, family=fam, label=label, object_id=obj_id,
                             last_said=said_day.isoformat(), said_in=max(1, len(set(dated))),
                             episode=dated[0] if dated else "", cue=cue, use=use.get(obj_id, 0.0)))
    # Roles first (a stale job is the costlier mistake), then the most-used topic, then the most recently quiet —
    # the interest the person may still hold, not the one long gone.
    out.sort(key=lambda k: (0 if k.family == "role" else 1, -k.use, _neg(k.last_said), k.claim_id))
    report.candidates = list(out)
    return out


def _neg(day: str) -> str:
    return "".join(str(9 - int(ch)) if ch.isdigit() else ch for ch in day)


def _open_still(memory_path: Path) -> tuple[int, set[tuple[str, str]]]:
    """How many "still?" questions are open, and every open conflict's ``(page, predicate)`` key."""
    count, keys = 0, set()
    for f in bank_index.files(memory_path, "inbox"):
        fm = f.frontmatter or {}
        if str(fm.get("kind") or "") != "conflict" or str(fm.get("status") or "pending") != "pending":
            continue
        keys.add((str(fm.get("entity_id") or ""), str(fm.get("predicate") or "description")))
        if str(fm.get("asks") or "") == ASKS:
            count += 1
    return count, keys


def item_frontmatter(owner: str, owner_name: str, cand: Candidate, today: date) -> dict:
    question = inbox_wording.spoken(
        {"kind": "conflict", "asks": ASKS, "predicate": cand.predicate, "entity_id": owner,
         "options": [{"key": "a", "label": cand.label}]},
        today.isoformat(), owner_id=owner).question
    return {
        "kind": "conflict", "asks": ASKS, "still": cand.family, "required_input": "choice", "status": "pending",
        "priority": PRIORITY[cand.family], "entity_id": owner, "entity_name": owner_name,
        "predicate": cand.predicate, "claim_id": cand.claim_id, "title": question, "question": question,
        "options": [{"key": "a", "label": cand.label, "claim_id": cand.claim_id,
                     "observed_at": cand.last_said, "last_referenced": cand.last_said},
                    dict(NOT_ANYMORE)],
        "allow_other": True, "allow_defer": True, "created_date": today.isoformat(),
        **({"source_episode": cand.episode} if cand.episode else {}),
        "last_said": cand.last_said, "said_in": cand.said_in,
    }


def propose(memory_path: Path, today: date, *, budget, skip: frozenset[str] = frozenset(),
            dry_run: bool = False) -> Report:
    """Write at most what ``budget`` and :data:`MAX_OPEN` allow. Files only — the caller commits ``report.written``.
    ``skip`` holds memory-relative paths dirty before the run: a dirty owner page is asked nothing tonight.
    ``dry_run`` decides and reports, writing nothing."""
    from api.services import everyday_names

    memory_path = Path(memory_path)
    report = Report()
    owner = everyday_names.owner_id(memory_path)
    if not owner or f"entities/{owner}.md" in skip:
        report.skip("owner_page_dirty" if owner else "no_owner_page")
        return report
    found = candidates(memory_path, today, report)
    open_count, keys = _open_still(memory_path)
    page_fm = (bank_index.file(memory_path, "entities", f"{owner}.md") or None)
    owner_name = str((page_fm.frontmatter if page_fm else {}).get("name") or owner)
    inbox_dir = memory_path / "inbox"
    for cand in found:
        if open_count >= MAX_OPEN:
            report.skip("max_open")
            continue
        if (owner, cand.predicate) in keys:
            report.skip("question_open_on_predicate")
            continue
        if not budget.take("still"):
            report.skip("drain_budget")
            continue
        keys.add((owner, cand.predicate))
        open_count += 1
        if dry_run:
            report.written.append(f"inbox/<new {cand.family}>")
            continue
        from api.services import inbox_service   # lazy: its import graph is wide

        inbox_dir.mkdir(parents=True, exist_ok=True)
        path = inbox_dir / f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}.md"
        body = (f"Asked because nothing has said this again since {cand.last_said}"
                + (" and the page's tracked source was not re-read lately" if cand.cue else "") + ".")
        markdown_parser.write(path, item_frontmatter(owner, owner_name, cand, today), body)
        report.written.append(f"inbox/{path.name}")
    if report.written and not dry_run:
        bank_index.invalidate(memory_path)
    return report


def commit_message(paths: list[str], today: date) -> str:
    return git_service.build_commit_message(
        f"Questions to check in {today.isoformat()}",
        [f"{p}: created (source: n/a, trigger: {TRIGGER})" for p in paths], authors=[AUTHOR])


def restore(memory_path: Path, paths: list[str]) -> None:
    """Undo files a run wrote when its commit failed (they would ride another writer's commit otherwise)."""
    for rel in paths:
        try:
            (Path(memory_path) / rel).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"still-question restore skipped {rel}: {type(exc).__name__}")
    bank_index.invalidate(memory_path)


def quiet_until(day: str, fam: str) -> str:
    """The day a claim answered on ``day`` may be asked again (for the report and tests)."""
    d = _day(day) or date.today()
    return (d + timedelta(days=ANSWER_QUIET_DAYS.get(fam, 180))).isoformat()
