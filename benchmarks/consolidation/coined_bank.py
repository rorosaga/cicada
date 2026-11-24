"""Names nobody said, in a real bank: counts only, nothing written, no model. (2026-11-25, G148/G98)

    api/.venv/bin/python -m benchmarks.consolidation.coined_bank --bank PATH/TO/memory [--json]

Reads the bank's held lines (`pending_entities.jsonl`), its pages, its episodes and its open questions, and prints how many
carry a name that no text of the conversation they came from says (`coined_names.said_in`, the one reading `name_revisit.unsaid`
and Stage 1's mark share). It opens files to read, never writes one, never calls a model, never opens `~/.claude` or any path a
file names, and prints no name, no title, no quote and no id: only counts, and kinds (`session`, `agent_note`, a type, a number
of conversations). Run it under a scratch `HOME`; it reads only the bank it is given.

Sections:

* held lines: by where the name is said (``person`` in a turn of the person's own, ``others`` only in an assistant's turn, an agent's
  note or a record's own text, ``nowhere``, ``unreadable`` when a cited conversation could not be read); for the ``nowhere`` ones, by
  the kind of conversation, the type, how many of the name's words the conversation says, how many conversations they cite, how many
  claims and key facts they hold, and how many sit beside a page that bears the name.
* pages (skills left out: Sleep names them as instructions): the same for a page resting on conversations (`source_episodes`) that say neither its name nor an alias anywhere.
* open "same as?" questions about a name with no page: the same split, and how many questions each target page holds (a pile-up).
* co-mention (what a tending step could stand on): of the claims a ``nowhere`` line holds, how many have their located words in a
  sentence that names exactly one existing page of another kind than a person (a whole-word name or alias no other page shares).
  Nothing is moved by this script; the number is what a move would rest on.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from api.services import authorship, coined_names, evidence, markdown_parser, pending_store, promotion, text_fold

_SENTENCE = re.compile(r"[^.!?\n]+")
_WORD = re.compile(r"[^\W_]+", re.U)


def kind_of(fm: dict) -> str:
    """The kind of conversation an episode is, from its own record."""
    if str(fm.get("source") or "") == promotion.AGENT_MEMORY_SOURCE:
        return "agent_memory"
    if authorship.agent_saved(fm):
        return "agent_note"
    if fm.get("capture_kind") == "transcript":
        return "session"
    if fm.get("meeting"):
        return "meeting"
    if isinstance(fm.get("correspondent"), dict) or fm.get("group"):
        return "ticked_chat"
    if authorship.is_saved(fm):
        return "save"
    if str(fm.get("source") or "") in ("import", "chatgpt", "claude", "claude_project", "gemini_export") or \
            str(fm.get("origin") or "").endswith("-export"):
        return "chat_export"
    return "other"


class Episodes:
    """Episode bodies read once, each by its id; ``None`` for one that cannot be read."""

    def __init__(self, bank: Path) -> None:
        self.bank, self._seen = bank, {}

    def get(self, episode: str):
        if episode not in self._seen:
            doc = evidence.source_document(self.bank, episode) if episode.startswith("ep_") else None
            self._seen[episode] = doc
        return self._seen[episode]


def where_said(names: list[str], episodes: list[str], eps: Episodes) -> str:
    """``person`` / ``others`` / ``nowhere`` over every cited conversation, the nearest first; ``unreadable`` when none says it
    and one could not be read; ``no_conversation`` when none is cited."""
    best, unread = coined_names.NOWHERE, False
    rank = {coined_names.NOWHERE: 0, coined_names.OTHERS: 1, coined_names.PERSON: 2}
    if not episodes:
        return "no_conversation"
    for ep in episodes:
        doc = eps.get(ep)
        if doc is None:
            unread = True
            continue
        fm, body = doc
        got = coined_names.said_in(names, body, override=authorship.of(fm), gaps=evidence.gap_ranges(fm, body),
                                   persons=promotion.person_kinds(fm), extra=str(fm.get("title") or ""))
        if rank[got] > rank[best]:
            best = got
    return "unreadable" if best == coined_names.NOWHERE and unread else best


class PageNames:
    """Whole-word names and aliases of the bank's non-person pages that no other page shares, to find which one a sentence names."""

    def __init__(self, pages: list[dict]) -> None:
        owners: dict[tuple, set[str]] = defaultdict(set)
        for p in pages:
            for n in [p["name"], *p["aliases"]]:
                key = tuple(text_fold.fold(w) for w in _WORD.findall(n))
                if key and sum(len(w) for w in key) >= 3:
                    owners[key].add(p["id"])
        self.by_first: dict[str, list[tuple[tuple, str]]] = defaultdict(list)
        for key, ids in owners.items():
            if len(ids) == 1:
                self.by_first[key[0]].append((key, next(iter(ids))))

    def named_in(self, sentence: str) -> set[str]:
        words = [text_fold.fold(w) for w in _WORD.findall(sentence)]
        found: set[str] = set()
        for i, w in enumerate(words):
            for key, page in self.by_first.get(w, ()):
                if tuple(words[i:i + len(key)]) == key:
                    found.add(page)
        return found


def sentence_at(text: str, start: int) -> str:
    for m in _SENTENCE.finditer(text):
        if m.start() <= start < m.end():
            return m.group(0)
    return ""


def _pct(n: int, d: int) -> str:
    return f"{n} of {d}" + (f" ({100 * n // d}%)" if d else "")


def report(bank: Path) -> dict:
    eps = Episodes(bank)
    pages = []
    for path in sorted((bank / "entities").glob("*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter or {}
        except Exception:  # noqa: BLE001 - a page that does not parse is skipped, as every reader does
            continue
        pages.append({"id": path.stem, "name": str(fm.get("name") or path.stem), "type": str(fm.get("type") or ""),
                      "owner": bool(fm.get("owner")), "status": str(fm.get("status") or ""),
                      "aliases": [str(a) for a in fm.get("aliases") or [] if isinstance(a, str)],
                      "episodes": [str(e) for e in fm.get("source_episodes") or [] if e]})
    page_ids = {p["id"] for p in pages}
    non_person = [p for p in pages if p["type"] != "person" and not p["owner"] and p["status"] not in ("archived", "dropped")]
    names = PageNames(non_person)

    out: dict = {"held": {}, "pages": {}, "questions": {}, "comention": {}}
    # ---- held lines
    lines = pending_store.load(bank)
    held_where = Counter()
    nowhere: list[tuple] = []
    for line in lines:
        if line.correspondent or line.type == "person":
            held_where["person_line"] += 1
            continue
        w = where_said([line.name, *line.aliases], line.episodes(), eps)
        held_where[w] += 1
        if w == coined_names.NOWHERE:
            nowhere.append((line, w))
    held = out["held"]
    held["lines"] = len(lines)
    held["where_said"] = dict(held_where)
    kinds, types, words, cites = Counter(), Counter(), Counter(), Counter()
    claims = facts = beside_page = 0
    for line, _w in nowhere:
        first = eps.get(line.source_episode) if line.source_episode else None
        kinds[kind_of(first[0]) if first else "unreadable"] += 1
        types[line.type or "?"] += 1
        text = "\n".join(eps.get(e)[1] for e in line.episodes() if eps.get(e))
        words[coined_names.words_of(line.name, text)] += 1
        cites["1" if len(promotion.conversation_keys(line.episodes(), bank)) <= 1 else "2+"] += 1
        claims += len(line.held_claims)
        facts += len(line.key_facts)
        beside_page += 1 if line.held_against else 0
    held.update(nowhere_by_kind=dict(kinds), nowhere_by_type=dict(types), nowhere_by_words=dict(words),
                nowhere_by_conversations=dict(cites), nowhere_claims=claims, nowhere_key_facts=facts,
                nowhere_beside_a_page=beside_page)
    # ---- co-mention: a held claim's located words in a sentence naming exactly one page
    lines_with, pages_named, claims_named, claims_total, person_words = 0, Counter(), 0, 0, 0
    for line, _w in nowhere:
        hit = False
        for c in line.held_claims:
            claims_total += 1
            found: set[str] = set()
            own = False
            for ev in c.get("evidence") or []:
                if not isinstance(ev, dict) or int(ev.get("start", -1)) < 0:
                    continue
                doc = eps.get(str(ev.get("episode") or ""))
                if doc is None:
                    continue
                found |= names.named_in(sentence_at(doc[1], int(ev["start"])))
                own = own or str(ev.get("kind") or "") in promotion.PERSON_KINDS
            found.discard("")
            if len(found) == 1:
                claims_named += 1
                person_words += 1 if own else 0
                pages_named[next(iter(found))] += 1
                hit = True
        lines_with += 1 if hit else 0
    out["comention"] = {"nowhere_lines_with_a_claim_naming_exactly_one_page": lines_with, "claims": claims_named,
                        "of_which_in_the_persons_own_turn": person_words, "claims_held_by_nowhere_lines": claims_total,
                        "distinct_pages_named": len(pages_named),
                        "most_claims_on_one_page": max(pages_named.values(), default=0)}
    # ---- pages
    # A skill is named by Sleep as an instruction (G112), never by what anyone said: left out of this count.
    resting = [p for p in non_person if p["episodes"] and p["type"] != "skill"]
    pw, pk, pt, pn = Counter(), Counter(), Counter(), Counter()
    for p in resting:
        w = where_said([p["name"], *p["aliases"]], p["episodes"], eps)
        pw[w] += 1
        if w == coined_names.NOWHERE:
            first = eps.get(p["episodes"][0])
            pk[kind_of(first[0]) if first else "unreadable"] += 1
            pt[p["type"] or "?"] += 1
            pn["1" if len(promotion.conversation_keys(p["episodes"], bank)) <= 1 else "2+"] += 1
    out["pages"] = {"non_person_pages_resting_on_conversations": len(resting), "where_said": dict(pw),
                    "nowhere_by_kind": dict(pk), "nowhere_by_type": dict(pt), "nowhere_by_conversations": dict(pn)}
    # ---- open "same as?" questions about a name with no page
    qw, qk, per_target = Counter(), Counter(), Counter()
    total_q = 0
    for path in sorted((bank / "inbox").glob("*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter or {}
        except Exception:  # noqa: BLE001
            continue
        if str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("status") or "pending") != "pending":
            continue
        total_q += 1
        entity_id = str(fm.get("entity_id") or "").strip()
        if entity_id in page_ids:
            continue
        name = " ".join(str(fm.get("entity_name") or fm.get("entity_mention") or "").split())
        if not name:
            continue
        line = pending_store.held_line(bank, name)
        cited = [str(fm.get("source_episode") or ""), *(line.episodes() if line else [])]
        w = where_said([name, *(line.aliases if line else [])], [e for e in dict.fromkeys(cited) if e], eps)
        qw[w] += 1
        if w == coined_names.NOWHERE:
            first = eps.get(cited[0]) if cited[0] else None
            qk[kind_of(first[0]) if first else "unreadable"] += 1
            per_target[str(fm.get("merge_target_hint") or "")] += 1
    out["questions"] = {"open_same_as_questions": total_q, "about_a_name_with_no_page_where_said": dict(qw),
                        "nowhere_by_kind": dict(qk), "targets_of_nowhere_questions": len(per_target),
                        "most_on_one_target": max(per_target.values(), default=0),
                        "targets_with_5_or_more": sum(1 for v in per_target.values() if v >= 5)}
    return out


def render(r: dict) -> str:
    h, p, q, c = r["held"], r["pages"], r["questions"], r["comention"]
    lines = ["Names nobody said (counts only; nothing was written)",
             f"held lines {h['lines']}: said where -> " + ", ".join(f"{k} {v}" for k, v in sorted(h["where_said"].items())),
             f"  the 'nowhere' lines, by conversation kind: {h['nowhere_by_kind']}",
             f"  by type: {h['nowhere_by_type']}; the name's words said by the conversation: {h['nowhere_by_words']}",
             f"  citing 1 conversation / 2+: {h['nowhere_by_conversations']}; claims held {h['nowhere_claims']}, key facts {h['nowhere_key_facts']}, "
             f"beside a page bearing the name {h['nowhere_beside_a_page']}",
             f"pages: {p['non_person_pages_resting_on_conversations']} non-person pages rest on conversations; said where -> {p['where_said']}",
             f"  the 'nowhere' pages: by kind {p['nowhere_by_kind']}, by type {p['nowhere_by_type']}, conversations {p['nowhere_by_conversations']}",
             f"open same-as questions {q['open_same_as_questions']}; about a name with no page, said where -> {q['about_a_name_with_no_page_where_said']}",
             f"  the 'nowhere' ones by kind {q['nowhere_by_kind']}; on {q['targets_of_nowhere_questions']} target pages, most on one {q['most_on_one_target']}, "
             f"targets with 5+ {q['targets_with_5_or_more']}",
             f"co-mention: {c['nowhere_lines_with_a_claim_naming_exactly_one_page']} 'nowhere' lines hold a claim whose located words sit in a sentence "
             f"naming exactly one page ({c['claims']} of {c['claims_held_by_nowhere_lines']} claims, {c['of_which_in_the_persons_own_turn']} in the person's own turn; "
             f"{c['distinct_pages_named']} pages, most on one page {c['most_claims_on_one_page']})"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--bank", type=Path, required=True, help="a bank folder (read only)")
    parser.add_argument("--json", action="store_true")
    a = parser.parse_args()
    if not (a.bank / "entities").is_dir():
        parser.error(f"{a.bank} is not a bank (no entities folder)")
    result = report(a.bank)
    print(json.dumps(result, indent=1) if a.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
