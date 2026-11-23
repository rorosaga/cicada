"""The people Sleep holds in doubt, and the names it has yet to look at again (2026-11-23).

Two people who share a first name are told apart on a located contrast (`same_name_people`). When the record shows two
different kinds of person but nothing that says both cannot be one, the second is held apart in doubt: on a person of its
own, never blended into the first's page, and the pair is recorded here, **not** in `merge_rejections` (a split pair is
never joined again; a doubt may be, by the person). `same_name_tend` settles a doubt as two people on a located contrast
or, only once the whole record has been read and cannot tell, asks the person once (a located link is said in that
question; Sleep itself joins no one, ruling 74).

``<bank>/_same_name_doubts.yaml``, tracked in the bank's git and committed with the batch or the tail step that changed it
(it sits beside ``_merge_rejected.yaml``, which it never replaces): ``pairs`` (``a``, ``b`` page or line ids, ``since``,
and ``asked`` the day the person was asked about the pair, once), and ``review`` (the pages that may hold two people, the
pairs that may be one, written by Stage 2 and taken by the tail). Ids and dates only, never a name's words.

Two more lists keep the person's own word standing against the tail's page split (`same_name_tend`):

* ``one``: person pages another person's page was folded into on the person's word (`entity_merge.merge_entities`:
  their own merge, an agent's on their ask, an answered question; never Sleep's own dedup join, which does not bind
  Sleep), and pages whose split by Sleep the person took back. Sleep never splits such a page; only the person does.
* ``splits``: the commit of the tail's own split of a page. It is written **after** that commit and never inside it, so
  undoing the split (`page_join.undo` reverses the split's commit, nothing else) leaves it here; the tail reads it,
  finds the commit taken back, and puts the page in ``one``.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import yaml

FILE = "_same_name_doubts.yaml"


def _pair(a: str, b: str) -> tuple[str, str]:
    x, y = sorted((str(a or "").strip(), str(b or "").strip()))
    return x, y


def _read(memory_path) -> dict:
    p = Path(memory_path) / FILE
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _normal(data: dict) -> dict:
    """What the file holds for ``data``, in the one order it is written in; ``{}`` for nothing to keep."""
    pairs = [row for row in data.get("pairs") or [] if isinstance(row, dict) and row.get("a") and row.get("b")]
    review = data.get("review") if isinstance(data.get("review"), dict) else {}
    out: dict = {}
    if pairs:
        out["pairs"] = sorted(pairs, key=lambda r: (r["a"], r["b"]))
    pages, prs = sorted({str(x) for x in review.get("pages") or []}), review.get("pairs") or []
    prs = sorted({tuple(_pair(*r)) for r in prs if isinstance(r, (list, tuple)) and len(r) == 2})
    if pages or prs:
        out["review"] = {**({"pages": pages} if pages else {}), **({"pairs": [list(r) for r in prs]} if prs else {})}
    joined = sorted({str(x) for x in data.get("one") or [] if x})
    if joined:
        out["one"] = joined
    done = data.get("splits") if isinstance(data.get("splits"), dict) else {}
    done = {str(k): str(v) for k, v in sorted(done.items()) if k and v}
    if done:
        out["splits"] = done
    return out


def _write(memory_path, data: dict) -> Path:
    p = Path(memory_path) / FILE
    out = _normal(data)
    if not out:
        p.unlink(missing_ok=True)
        return p
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".same-name-doubts-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(yaml.safe_dump(out, allow_unicode=True, sort_keys=False))
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p


def pairs(memory_path) -> dict[tuple[str, str], dict]:
    """Every pair held in doubt: ``{(a, b): {"since": ..., "asked": ...}}``."""
    out: dict[tuple[str, str], dict] = {}
    for row in _read(memory_path).get("pairs") or []:
        if isinstance(row, dict) and row.get("a") and row.get("b"):
            out[_pair(row["a"], row["b"])] = {k: row[k] for k in ("since", "asked") if row.get(k)}
    return out


def doubts_of(memory_path, ref: str) -> frozenset[str]:
    """The people held in doubt against ``ref``."""
    return frozenset(b if a == ref else a for (a, b) in pairs(memory_path) if ref in (a, b))


def add_pairs(memory_path, new: list[tuple[str, str]], *, today: str | None = None) -> bool:
    """Hold these pairs in doubt; only what is new is written. Returns whether the file changed."""
    data = _read(memory_path)
    have = pairs(memory_path)
    fresh = [_pair(a, b) for a, b in new if a != b and _pair(a, b) not in have]
    if not fresh:
        return False
    rows = [dict(a=a, b=b, **meta) for (a, b), meta in have.items()]
    rows += [{"a": a, "b": b, "since": today or date.today().isoformat()} for a, b in fresh]
    data["pairs"] = rows
    _write(memory_path, data)
    return True


def remove_pairs(memory_path, gone: list[tuple[str, str]]) -> bool:
    """These pairs are no longer in doubt (settled one way or the other, or a page is gone)."""
    data = _read(memory_path)
    have = pairs(memory_path)
    drop = {_pair(a, b) for a, b in gone} & set(have)
    if not drop:
        return False
    data["pairs"] = [dict(a=a, b=b, **meta) for (a, b), meta in have.items() if (a, b) not in drop]
    _write(memory_path, data)
    return True


def mark_asked(memory_path, a: str, b: str, *, today: str | None = None) -> bool:
    """The person was asked about this pair: never again (a skip or a dismiss is no answer to ask for)."""
    data = _read(memory_path)
    have = pairs(memory_path)
    key = _pair(a, b)
    if key not in have:
        return False
    have[key] = {**have[key], "asked": today or date.today().isoformat()}
    data["pairs"] = [dict(a=x, b=y, **meta) for (x, y), meta in have.items()]
    _write(memory_path, data)
    return True


def flag(memory_path, *, pages=(), pairs_=()) -> bool:
    """Stage 2's re-read found pages that may hold two people and pairs that may be one: the tail looks at them."""
    data = _read(memory_path)
    review = data.get("review") if isinstance(data.get("review"), dict) else {}
    pg = {str(p) for p in review.get("pages") or []} | {str(p) for p in pages}
    pr = {_pair(*r) for r in review.get("pairs") or [] if isinstance(r, (list, tuple)) and len(r) == 2}
    pr |= {_pair(a, b) for a, b in pairs_}
    before = (sorted(review.get("pages") or []), sorted(tuple(r) for r in review.get("pairs") or []))
    if before == (sorted(pg), sorted(pr)):
        return False
    data["review"] = {"pages": sorted(pg), "pairs": [list(r) for r in sorted(pr)]}
    _write(memory_path, data)
    return True


def flagged(memory_path) -> tuple[set[str], set[tuple[str, str]]]:
    review = _read(memory_path).get("review")
    review = review if isinstance(review, dict) else {}
    return ({str(p) for p in review.get("pages") or []},
            {_pair(*r) for r in review.get("pairs") or [] if isinstance(r, (list, tuple)) and len(r) == 2})


def clear_flags(memory_path, *, pages=(), pairs_=()) -> bool:
    """The tail looked at these: they leave the review list."""
    data = _read(memory_path)
    pg, pr = flagged(memory_path)
    pg2, pr2 = pg - {str(p) for p in pages}, pr - {_pair(a, b) for a, b in pairs_}
    if (pg, pr) == (pg2, pr2):
        return False
    data["review"] = {"pages": sorted(pg2), "pairs": [list(r) for r in sorted(pr2)]}
    _write(memory_path, data)
    return True


def one(memory_path) -> set[str]:
    """The person pages Sleep never splits: something was folded into them, or the person took Sleep's split back."""
    return {str(x) for x in _read(memory_path).get("one") or [] if x}


def mark_one(memory_path, page: str) -> bool:
    data = _read(memory_path)
    have = {str(x) for x in data.get("one") or [] if x}
    if page in have:
        return False
    data["one"] = sorted(have | {str(page)})
    _write(memory_path, data)
    return True


def splits(memory_path) -> dict[str, str]:
    """``{page: the commit of the tail's own split of it}``."""
    done = _read(memory_path).get("splits")
    return {str(k): str(v) for k, v in done.items() if k and v} if isinstance(done, dict) else {}


def note_split(memory_path, page: str, commit: str | None) -> bool:
    """The tail split ``page`` in ``commit``: remembered outside that commit, so an undo of it can be seen."""
    if not commit:
        return False
    data = _read(memory_path)
    done = dict(data.get("splits")) if isinstance(data.get("splits"), dict) else {}
    if done.get(page) == commit:
        return False
    done[str(page)] = str(commit)
    data["splits"] = done
    _write(memory_path, data)
    return True


def fold(memory_path, loser: str, winner: str, *, people: bool = False, dry: bool = False) -> bool:
    """``loser`` was merged into ``winner``: the pair between them is settled, and the loser's other doubts, flags and
    marks are the winner's. ``people``: both are person pages, so the winner is one Sleep never splits (``one``).
    Returns whether the file changes; ``dry`` only says so (`entity_merge.merge_footprint`)."""
    data = _read(memory_path)
    before = _normal(data)
    out: dict[tuple[str, str], dict] = {}
    for (a, b), meta in pairs(memory_path).items():
        a, b = (winner if a == loser else a), (winner if b == loser else b)
        if a != b:
            out.setdefault(_pair(a, b), meta)
    data["pairs"] = [dict(a=a, b=b, **meta) for (a, b), meta in out.items()]
    pg, pr = flagged(memory_path)
    pg = {winner if p == loser else p for p in pg}
    pr = {_pair(winner if a == loser else a, winner if b == loser else b) for a, b in pr}
    data["review"] = {"pages": sorted(pg), "pairs": [list(r) for r in sorted(pr) if r[0] != r[1]]}
    joined = {str(x) for x in data.get("one") or [] if x}
    if people or loser in joined:
        joined = (joined - {loser}) | {winner}
    data["one"] = sorted(joined)
    done = dict(data.get("splits")) if isinstance(data.get("splits"), dict) else {}
    done.pop(loser, None)
    data["splits"] = done
    if _normal(data) == before:
        return False
    if not dry:
        _write(memory_path, data)
    return True
