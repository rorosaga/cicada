"""People a person spots as one at a glance (ROR-136, owner 2026-11-06).

A misspelling ("Texim" / "Tikzim"), a nickname with nothing in common with the name ("a nickname"), a first name beside the
full one ("Dana" / "Dana Example") were one person each and the inbox held no question for two of them, while
the two it did hold sat among 659. This finds the pairs from the record alone — engine-free, no network, no word lists
of any language — and the drain asks about the best few (:func:`propose`). A question only (the "Same person?" rail,
ruling 41, G209): spelling, sound and shared facts are reasons to ask, never proof, and only the person's words join
two pages. A private name goes to no service: nothing here leaves the bank's files.

Signals (``Pair.signals``, enums), each language-neutral:

* ``sound`` — the same name said two ways: every word matches by letters or by a *sound skeleton* (:func:`sound_key`:
  letter classes that spell one sound in many alphabets — ``x``/``ks``, ``z``/``s``, ``c``/``k``, ``ph``/``f`` — then
  the vowels after the first letter dropped). This is what joins a transcript's mishearing to the right spelling.
* ``spelling`` — the existing close-spelling test (``entity_resolver.close_spelling``): one or two edits apart.
* ``short_in_full`` — a one-word name that is a word of the other's longer name ("Dana" / "Dana Example"), or the
  start of one (a nickname and its long form, ``inbox_catchup.nickname_pair``).
* ``alias`` — one page lists the other's name as its own.
* ``shared_source`` — the same account, link or address in both pages' sources.
* ``shared_facts`` — the same rare belief (predicate and object) on both: a fact held by more than
  :data:`COMMON_FACT` people says nothing about which two are one.

``together`` counts the conversations that name both pages. Being named together is evidence they are two (ruling 65 c):
it lowers the score; it never raises it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from api.services import bank_index

#: A fact on more than this many people's pages is common ground, not a tie between two.
COMMON_FACT = 3
#: The lowest score a question is asked at (a list shows everything above :data:`LIST_FLOOR`).
ASK_FLOOR = 0.5
LIST_FLOOR = 0.35
#: At most this many of the drain's own questions open at once (``detected: person_duplicate``).
MAX_OPEN = 6
TRIGGER = "sleep/person-duplicate-questions"
#: Predicates that describe a page's kind, not who it is.
_GENERIC_PREDICATES = frozenset({"is-a", "type", "is", "name", "also-called", "goes-by", "mentioned-in"})
_VOWELS = set("aeiou")


def fold(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def sound_key(word: str) -> str:
    """One word as it sounds, coarsely: letters that spell one sound across alphabets are folded together, then every
    vowel after the first letter is dropped. ``texim`` and ``tikzim`` are both ``tksm``. Letter classes, never words."""
    w = fold(word).replace(" ", "")
    for old, new in (("ph", "f"), ("ck", "k"), ("sch", "sh"), ("x", "ks"), ("z", "s"), ("q", "k"), ("w", "v"),
                     ("y", "i"), ("j", "i")):
        w = w.replace(old, new)
    w = re.sub(r"c(?=[ei])", "s", w).replace("c", "k")
    w = w.replace("h", "")
    if not w:
        return ""
    out = w[0] + "".join(ch for ch in w[1:] if ch not in _VOWELS)
    return re.sub(r"(.)\1+", r"\1", out)


def _edits(a: str, b: str, limit: int) -> int:
    from api.services.entity_resolver import _edit_distance

    return _edit_distance(a, b, limit)


def _same_but_ending(a: str, b: str) -> bool:
    """Two words that share their start and differ only in a short ending that has a vowel ("daniel" / "daniela",
    "carlos" / "carlota", "luca" / "lucia"): usually two names, so only a lead, never a spelling."""
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    ta, tb = a[n:], b[n:]
    return n >= 3 and len(ta) <= 3 and len(tb) <= 3 and any(c in _VOWELS for c in ta + tb) and bool(ta + tb) \
        and (len(ta) != len(tb) or not (ta and tb))


def word_match(a: str, b: str) -> str | None:
    """How two folded words match: ``same``, ``sound`` (equal sound skeletons of 3+ letters, within three edits),
    ``spelling`` (one edit from the same first letter), ``ending`` (only a short vowel ending differs) or ``None``."""
    if a == b:
        return "same"
    if len(a) < 4 or len(b) < 4:
        return None
    if _same_but_ending(a, b):
        return "ending"
    ka, kb = sound_key(a), sound_key(b)
    if len(ka) >= 3 and ka == kb and _edits(a, b, 3) <= 3:
        return "sound"
    if a[0] == b[0] and abs(len(a) - len(b)) <= 1 and _edits(a, b, 1) <= 1:
        return "spelling"
    return None


def name_signals(a: str, b: str) -> list[str]:
    """The name-only signals between two spellings (folded or not)."""
    from api.services import inbox_catchup

    wa, wb = fold(a).split(), fold(b).split()
    if not wa or not wb or wa == wb:
        return []
    out: list[str] = []
    if len(wa) == len(wb):
        kinds = [word_match(x, y) for x, y in zip(wa, wb)]
        if all(kinds) and any(k != "same" for k in kinds):
            if "sound" in kinds:
                out.append("sound")
            elif "spelling" in kinds:
                out.append("spelling")
            elif "ending" in kinds and len(wa) > 1:
                out.append("spelling")
    short, long_ = sorted((wa, wb), key=len)
    if len(short) == 1 and len(long_) > 1 and len(short[0]) >= 3 and short[0] in long_:
        out.append("short_in_full")
    elif inbox_catchup.nickname_pair(a, b):
        out.append("short_in_full")
    return list(dict.fromkeys(out))


@dataclass
class Page:
    id: str
    name: str
    names: list[str]
    sources: set[str] = field(default_factory=set)
    facts: set[tuple[str, str]] = field(default_factory=set)
    episodes: set[str] = field(default_factory=set)
    role: bool = False          # titled by its relation to the owner ("Partner"): `role_people` owns that question


@dataclass
class Pair:
    a: str
    b: str
    score: float
    signals: list[str]
    why: str
    together: int = 0
    asked: bool = False

    @property
    def confidence(self) -> str:
        return "high" if self.score >= 0.75 else "medium" if self.score >= ASK_FLOOR else "low"


def _name_like(alias: str) -> bool:
    """An alias that is a name rather than a way of referring ("his girlfriend", "she", "<owner>'s brother", an address):
    it starts with a capital or a digit and carries no possessive or "@". Case and punctuation, never a word list."""
    a = alias.strip()
    return bool(a) and (a[0].isupper() or a[0].isdigit()) and "@" not in a and not re.search(r"['’]s\b", a)


def _source_keys(fm: dict) -> set[str]:
    out: set[str] = set()
    for s in fm.get("sources") or ():
        ref = str((s.get("ref") if isinstance(s, dict) else s) or "").strip().lower().rstrip("/")
        ref = re.sub(r"^https?://(www\.)?", "", ref)
        if ref.partition("/")[2].strip("/"):      # an account or a page, not a bare domain
            out.add(ref)
    return out


def _people(memory_path: Path) -> list[Page]:
    from api.services import entity_relations, everyday_names, role_people

    owner = everyday_names.owner_id(memory_path)
    pages: list[Page] = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "") != "person" or f.stem == owner or fm.get("owner") is True:
            continue
        if str(fm.get("status") or "") in ("archived", "dropped"):
            continue
        name = str(fm.get("name") or f.stem)
        removed = {fold(a) for a in (fm.get("aliases_removed") or ()) if isinstance(a, str)}
        names = [name, *[a for a in (fm.get("aliases") or ())
                         if isinstance(a, str) and fold(a) not in removed and _name_like(a)]]
        facts: set[tuple[str, str]] = set()
        for c in entity_relations._page_claims(memory_path, f.stem):
            pred, obj = str(c.predicate or "").lower(), fold(c.object)
            if c.valid_to is None and pred and obj and pred not in _GENERIC_PREDICATES:
                facts.add((pred, obj))
        pages.append(Page(f.stem, name, names, _source_keys(fm), facts,
                          {str(e) for e in (fm.get("source_episodes") or ()) if e}, bool(role_people.roles_of(fm))))
    return pages


def _open_pairs(memory_path: Path) -> set[tuple[str, str]]:
    out = set()
    for f in bank_index.files(memory_path, "inbox"):
        fm = f.frontmatter or {}
        if str(fm.get("kind") or "") == "merge_suggestion" and str(fm.get("status") or "pending") == "pending":
            out.add(tuple(sorted((str(fm.get("entity_id") or ""), str(fm.get("merge_target_hint") or "")))))
    return out


_BASE = {"sound": 0.65, "spelling": 0.6, "short_in_full": 0.45, "alias": 0.75}
_WHY = {
    "sound": "the names sound alike ({x} / {y})",
    "spelling": "the names are a close spelling of one another ({x} / {y})",
    "short_in_full": "one name is part of the other ({x} / {y})",
    "alias": "one page lists the other's name as its own",
    "shared_source": "both pages carry the same account or link",
    "shared_facts": "both hold the same specific belief{n}",
}


def candidates(memory_path: Path, *, floor: float = LIST_FLOOR) -> list[Pair]:
    """Every pair of people pages that may be one person, best first. Pairs the person said are two people
    (``merge_rejections``) are left out; a pair with an open question is kept and marked ``asked``."""
    from api.services import merge_rejections

    memory_path = Path(memory_path)
    pages = _people(memory_path)
    kept_apart = merge_rejections.kept_apart(memory_path)
    open_pairs = _open_pairs(memory_path)
    held_by: dict[tuple[str, str], int] = {}
    for p in pages:
        for fact in p.facts:
            held_by[fact] = held_by.get(fact, 0) + 1
    source_holders: dict[str, int] = {}
    for p in pages:
        for k in p.sources:
            source_holders[k] = source_holders.get(k, 0) + 1
    full_names: dict[str, int] = {}
    for p in pages:
        w = fold(p.name).split()
        if len(w) > 1:
            full_names[w[0]] = full_names.get(w[0], 0) + 1
    out: list[Pair] = []
    for i, pa in enumerate(pages):
        for pb in pages[i + 1:]:
            pair = tuple(sorted((pa.id, pb.id)))
            if pair in kept_apart or (pa.role and pb.role):
                continue
            signals: dict[str, tuple[str, str]] = {}
            for x in pa.names:
                for y in pb.names:
                    for s in name_signals(x, y):
                        signals.setdefault(s, (x, y))
            # Two fuller names that do not match each other are two people sharing a given name ("Chris A." / "Chris B.").
            fulls_a = [n for n in pa.names if len(fold(n).split()) > 1]
            fulls_b = [n for n in pb.names if len(fold(n).split()) > 1]
            if fulls_a and fulls_b and not any(fold(x) == fold(y) or name_signals(x, y)
                                               for x in fulls_a for y in fulls_b):
                signals.pop("short_in_full", None)
            fa, fb = {fold(n) for n in pa.names}, {fold(n) for n in pb.names}
            if fold(pb.name) in fa or fold(pa.name) in fb:
                signals["alias"] = (pa.name, pb.name)
            shared_src = {k for k in pa.sources & pb.sources if source_holders.get(k, 0) <= 2}
            rare = [f for f in pa.facts & pb.facts if held_by.get(f, 0) <= COMMON_FACT]
            together = len(pa.episodes & pb.episodes)
            name_base = max((_BASE[s] for s in signals if s in _BASE), default=0.0)
            if name_base:
                score = name_base
                if shared_src:
                    signals["shared_source"] = (pa.name, pb.name)
                    score += 0.25
                if rare:
                    signals["shared_facts"] = (pa.name, pb.name)
                    score += min(0.2, 0.1 * len(rare))
                if together:
                    score -= min(0.2, 0.1 * together)       # named together is evidence they are two (ruling 65 c)
                if "alias" not in signals and not shared_src and not rare:
                    if min(len(pa.episodes), len(pb.episodes)) <= 2:
                        score += 0.1                          # a mishearing is one thing, said once or twice
                    elif min(len(pa.episodes), len(pb.episodes)) >= 4:
                        score -= 0.15                         # two names each well established are usually two people
            elif together == 0 and shared_src:
                signals = {"shared_source": (pa.name, pb.name)}
                score = 0.55
            elif together == 0 and len(rare) >= 3:
                signals = {"shared_facts": (pa.name, pb.name)}
                score = 0.5
            else:
                continue                                      # one shared belief, or people named together, is no tie
            if "short_in_full" in signals and name_base == _BASE["short_in_full"]:
                short = min((fold(pa.name), fold(pb.name)), key=lambda n: len(n.split()))
                if full_names.get(short.split()[0] if short else "", 0) > 1:
                    score -= 0.15      # the short name could be any of several fuller ones
            score = round(max(0.0, min(score, 0.95)), 2)
            if score < floor:
                continue
            why = "; ".join(_WHY[s].format(x=signals[s][0], y=signals[s][1],
                                           n=f" ({len(rare)})" if len(rare) > 1 else "") for s in signals)
            if together:
                why += f"; named together in {together} conversation{'s' if together != 1 else ''}"
            out.append(Pair(pa.id, pb.id, score, list(signals), why, together, pair in open_pairs))
    out.sort(key=lambda p: (-p.score, p.a, p.b))
    return out


@dataclass
class Report:
    written: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def propose(memory_path: Path, today, *, budget, skip: frozenset[str] = frozenset(), dry_run: bool = False) -> Report:
    """Ask "Is A the same as B?" for the best pairs that have no question, within the drain's budget and
    :data:`MAX_OPEN`. An ordinary ``merge_suggestion`` (so the card's one-tap merge, the page's own question list and
    every undo already work), marked ``detected: person_duplicate`` with its signals. The less-used page is the one
    asked about. Files only."""
    from api.services import inbox_service, markdown_parser, page_use, pair_evidence

    memory_path = Path(memory_path)
    report = Report()
    open_count = sum(1 for f in bank_index.files(memory_path, "inbox")
                     if str((f.frontmatter or {}).get("detected") or "") == "person_duplicate")
    use = page_use.scores(memory_path, today=today)
    inbox_dir = memory_path / "inbox"
    for pair in candidates(memory_path, floor=ASK_FLOOR):
        if pair.asked:
            report.skip("question_open")
            continue
        if open_count >= MAX_OPEN:
            report.skip("max_open")
            break
        if f"entities/{pair.a}.md" in skip or f"entities/{pair.b}.md" in skip:
            report.skip("page_dirty")
            continue
        asked, target = (pair.a, pair.b) if use.get(pair.a, 0.0) <= use.get(pair.b, 0.0) else (pair.b, pair.a)
        verdict = pair_evidence.judge(memory_path, a_id=asked, a_name="", b_id=target, person=True,
                                      source_episode="", base=pair.score)
        if not verdict.ask:
            report.skip(verdict.reason or "refused")
            continue
        if not budget.take("person_duplicate"):
            report.skip("drain_budget")
            break
        open_count += 1
        report.pairs.append((asked, target))
        if dry_run:
            report.written.append("inbox/<new person duplicate>")
            continue
        fa = bank_index.file(memory_path, "entities", f"{asked}.md")
        fb = bank_index.file(memory_path, "entities", f"{target}.md")
        name_a = str((fa.frontmatter if fa else {}).get("name") or asked)
        name_b = str((fb.frontmatter if fb else {}).get("name") or target)
        inbox_dir.mkdir(parents=True, exist_ok=True)
        path = inbox_dir / f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}.md"
        guess = pair_evidence.guess(pair.score, verdict.episode is not None)
        markdown_parser.write(path, {
            "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": guess,
            "entity_id": asked, "entity_name": name_a, "title": f"Is {name_a} the same as {name_b}?",
            "uncertainty_type": f"Possible duplicate of {name_b}", "suggested_classification": "person",
            "suggested_confidence": guess, "created_date": today.isoformat(), "merge_target_hint": target,
            "detected": "person_duplicate", "signals": pair.signals,
            **({"source_episode": verdict.episode} if verdict.episode else {}),
        }, f"Why this is asked: {pair.why}. They may be one person; asked, never joined: only your answer joins them.")
        report.written.append(f"inbox/{path.name}")
    if report.written and not dry_run:
        bank_index.invalidate(memory_path)
    return report


def commit_message(paths: list[str], today) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Same-person questions {today.isoformat()}",
        [f"{p}: created (source: n/a, trigger: {TRIGGER})" for p in paths], authors=["cicada"])
