"""G113 — remembered "these are NOT the same entity" rulings.

``<memory>/_merge_rejected.yaml`` holds sorted ``[a, b]`` slug pairs. A pair the
user rejected is never re-proposed by ``clarification_manager.create`` (Sleep's
duplicate clarifications) or ``dedup_sweep`` (the maintenance sweep). Fuzzy
mention resolution in ``entity_resolver`` is deliberately NOT consulted here —
it resolves mentions to pages, it does not propose merges.
"""
from __future__ import annotations

from pathlib import Path

import yaml

FILE = "_merge_rejected.yaml"


def _pair(a: str, b: str) -> tuple[str, str]:
    x, y = sorted((str(a or "").strip(), str(b or "").strip()))
    return x, y


#: G227 follow-up (owner 2026-10-29): two PAGES the person split apart. Kept beside ``rejected`` and read apart from
#: it, because a ``rejected`` pair is also read as "this NAME is not that page" (`entity_resolver._rejected_pair`): a
#: split leaves two pages under one title, and the name must still be able to reach either of them. A split pair keeps
#: the PAGES apart — never proposed, swept or settled as duplicates (`kept_apart`) — and nothing else.
SPLIT_KEY = "split"


#: G245 (arrival join, 2026-11-24): the person said "Not them" to a first name joined to someone who had no page. The pair
#: cannot be two pages, so it is keyed by the holder page and a HASH of the folded full name (never the name):
#: ``[{holder, key, on}]``. Kept beside the page pairs, read by `arrival_join`, and promoted into ``rejected`` the night a page
#: of that full name exists (`arrival_join_write.promote_refusals`), so every other joiner — ruling 74's, 74a's, 74b's — holds.
ARRIVAL_KEY = "arrival_joins"


def _read(memory_path: Path) -> dict:
    p = Path(memory_path) / FILE
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _pairs(data: dict, key: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in data.get(key) or []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            out.add(_pair(row[0], row[1]))
    return out


def _write(memory_path: Path, data: dict) -> Path:
    p = Path(memory_path) / FILE
    out = {"rejected": [list(x) for x in sorted(_pairs(data, "rejected"))]}
    split = sorted(_pairs(data, SPLIT_KEY))
    if split:
        out[SPLIT_KEY] = [list(x) for x in split]
    for key, value in data.items():   # anything another writer keeps here stays
        if key not in out and key not in ("rejected", SPLIT_KEY):
            out[key] = value
    text = yaml.safe_dump(out, allow_unicode=True, sort_keys=False)
    from api.services import settle_guard

    settle_guard.writing(p)   # inside a Sleep settle: what the file holds now is its picture (a no-op anywhere else)
    p.write_text(text, encoding="utf-8")
    settle_guard.wrote(p, text.encode("utf-8"))
    return p


def arrival_refusals(memory_path: Path) -> list[dict]:
    """Every "Not them" the person said to an arrival join whose full-name side had no page: ``[{holder, key, on}]``."""
    out: list[dict] = []
    for row in _read(memory_path).get(ARRIVAL_KEY) or []:
        if isinstance(row, dict) and row.get("holder") and row.get("key"):
            out.append({"holder": str(row["holder"]), "key": str(row["key"]), "on": str(row.get("on") or "")})
    return out


def add_arrival_refusal(memory_path: Path, holder: str, key: str, *, on: str) -> Path:
    data = _read(memory_path)
    rows = arrival_refusals(memory_path)
    if not any(r["holder"] == holder and r["key"] == key for r in rows):
        rows.append({"holder": holder, "key": key, "on": on})
    data[ARRIVAL_KEY] = rows
    return _write(memory_path, data)


def drop_arrival_refusal(memory_path: Path, holder: str, key: str) -> bool:
    """The person joined them after all, or the refusal became a page pair: it leaves the list."""
    data = _read(memory_path)
    rows = arrival_refusals(memory_path)
    kept = [r for r in rows if not (r["holder"] == holder and r["key"] == key)]
    if len(kept) == len(rows):
        return False
    if kept:
        data[ARRIVAL_KEY] = kept
    else:
        data.pop(ARRIVAL_KEY, None)
    _write(memory_path, data)
    return True


def refused_by_name(memory_path: Path, holder: str, full_name: str) -> bool:
    """Did the person say a first name page (``holder``) is NOT the person called ``full_name``? The public reader every
    joiner may ask before it proposes or settles that pair, whether or not a page of that name exists yet."""
    from api.services import arrival_join, people_directory

    key = arrival_join.key_hash(people_directory.fold(full_name))
    return any(r["holder"] == holder and r["key"] == key for r in arrival_refusals(memory_path))


def load_rejected(memory_path: Path) -> set[tuple[str, str]]:
    return _pairs(_read(memory_path), "rejected")


def load_split(memory_path: Path) -> set[tuple[str, str]]:
    return _pairs(_read(memory_path), SPLIT_KEY)


def kept_apart(memory_path: Path) -> set[tuple[str, str]]:
    """Every pair of PAGES never to be joined as duplicates: the person's "different" answers and their splits, and (never
    proposed, swept or asked about as duplicates by anything else) the people two of one first name Sleep holds in doubt
    (`same_name_doubts`), which only `same_name_tend` settles or asks about, once."""
    from api.services import same_name_doubts

    data = _read(memory_path)
    return _pairs(data, "rejected") | _pairs(data, SPLIT_KEY) | same_name_doubts.kept(memory_path)


def is_rejected(memory_path: Path, a: str, b: str) -> bool:
    return _pair(a, b) in load_rejected(memory_path)


def is_split(memory_path: Path, a: str, b: str) -> bool:
    return _pair(a, b) in load_split(memory_path)


def add_rejected(memory_path: Path, a: str, b: str) -> Path:
    data = _read(memory_path)
    data["rejected"] = [list(x) for x in _pairs(data, "rejected") | {_pair(a, b)}]
    return _write(memory_path, data)


def add_split(memory_path: Path, a: str, b: str) -> Path:
    data = _read(memory_path)
    data[SPLIT_KEY] = [list(x) for x in _pairs(data, SPLIT_KEY) | {_pair(a, b)}]
    return _write(memory_path, data)


def clear_pairs(memory_path: Path, pairs) -> bool:
    """The person joined these: every listed pair leaves both lists. Returns whether the file changed."""
    gone = {_pair(a, b) for a, b in pairs}
    data = _read(memory_path)
    rejected, split = _pairs(data, "rejected"), _pairs(data, SPLIT_KEY)
    if not (gone & rejected or gone & split):
        return False
    data["rejected"] = [list(x) for x in rejected - gone]
    data[SPLIT_KEY] = [list(x) for x in split - gone]
    _write(memory_path, data)
    return True


def uncross_aliases(memory_path: Path, a: str, b: str, *, author: str = "user") -> list[str]:
    """The person said ``a`` and ``b`` are two people: an alias on one that names the other (its name, its id, or one of
    its own aliases) is wrong and leaves the page, recorded in ``aliases_removed`` so no automatic writer adds it back.
    Only person pages. Returns the memory-relative paths written.

    Owner 2026-11-06: a page listed "<other's name>" as its own alias since a Sleep extraction read two co-applicants
    named in one sentence as one person; the guard against a crossed alias (`alias_policy.names_another_page`) came
    three weeks later and does not reach one already written. Answering "two people" is the person's word on it."""
    from datetime import date

    from api.services import markdown_parser, page_edits
    from api.services.id_utils import sanitize_id

    memory_path = Path(memory_path)
    pages = {pid: memory_path / "entities" / f"{pid}.md" for pid in (a, b)}
    if not all(p.is_file() for p in pages.values()):
        return []
    parsed = {pid: markdown_parser.parse(p) for pid, p in pages.items()}
    if any(str(x.frontmatter.get("type") or "") != "person" for x in parsed.values()):
        return []

    def spellings(pid: str) -> set[str]:
        fm = parsed[pid].frontmatter
        names = [pid, str(fm.get("name") or ""), *[x for x in fm.get("aliases") or () if isinstance(x, str)]]
        return {" ".join(n.split()).casefold() for n in names if n and n.strip()} | {sanitize_id(n) for n in names if n}

    written: list[str] = []
    for pid, other in ((a, b), (b, a)):
        fm = dict(parsed[pid].frontmatter)
        aliases = [x for x in fm.get("aliases") or () if isinstance(x, str)]
        theirs = spellings(other)
        crossed = [x for x in aliases if " ".join(x.split()).casefold() in theirs or sanitize_id(x) in theirs]
        if not crossed:
            continue
        fm["aliases"] = [x for x in aliases if x not in crossed]
        if not fm["aliases"]:
            fm.pop("aliases")
        rows = list(fm.get(page_edits.ALIASES_REMOVED) or []) if isinstance(fm.get(page_edits.ALIASES_REMOVED), list) else []
        rows += [{"alias": x, "by": author, "on": date.today().isoformat()} for x in crossed]
        fm[page_edits.ALIASES_REMOVED] = rows[-page_edits.MAX_ALIASES_REMOVED:]
        markdown_parser.write(pages[pid], fm, parsed[pid].body)
        written.append(f"entities/{pid}.md")
    return written
