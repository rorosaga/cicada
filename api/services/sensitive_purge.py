"""Taking a value out of a bank file by what the file IS, never as raw text (G235, ruling 60).

A mark put into YAML by a text replace can break the file or change what it says: ``name: [removed: password]`` is a
list, a colon inside a plain sentence stops it parsing, and a non-ASCII value is not even there to match because it was
written escaped. A file that stops parsing is a page the bank no longer sees. So: frontmatter and YAML are loaded, walked
and dumped; a claim fence is loaded and written back in its one encoder; a JSON line is loaded and dumped; a key or id
field is left alone; only prose is text. Every file is replaced atomically or not at all, and a file with no value is
never rewritten.

**A common word is guarded** (`sensitive_text.distinctive`): it is only ever taken from a file tied to that conversation,
and only on a line or item that speaks of a secret. A distinctive value's exact token is its own tie."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml
from loguru import logger

from api.services import claims, episode_scrub, markdown_parser, sensitive_text

#: Never a value's home: git, the conversations (each its own row), `.awake` (dropped with its row) and binaries.
_SKIP_DIRS = frozenset({"episodes", "assets", "frames", "pictures", "shots", "leann"})
#: `_state.md` is a cursor that commits alone: rebuilt after a removal, never here. The others are Cicada's own records.
_SKIP_FILES = frozenset({"_state.md", "_home.json", "_bank.yaml", "banks.yaml"})
_SUFFIXES = (".md", ".jsonl", ".yaml", ".yml", ".json")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]*)\]\]")


def in_scope(rel: str) -> bool:
    """Is this bank-relative path a file :func:`bank_files` would walk?"""
    parts = rel.split("/")
    return (rel.endswith(_SUFFIXES) and parts[-1] not in _SKIP_FILES and not parts[-1].startswith(".")
            and parts[0] not in _SKIP_DIRS and not any(p.startswith(".") for p in parts[:-1]))


def bank_files(memory_path: Path):
    """Every text file in a bank that a value may have reached, in a stable order."""
    for directory, subdirs, files in os.walk(memory_path):
        at_root = Path(directory) == Path(memory_path)
        subdirs[:] = sorted(d for d in subdirs if not d.startswith(".") and not (at_root and d in _SKIP_DIRS))
        for name in sorted(files):
            if name.endswith(_SUFFIXES) and not name.startswith(".") and name not in _SKIP_FILES:
                yield Path(directory) / name


def _walk(value, marks: dict[str, str], *, key=None, speaks: bool = False):
    """``(value, changes)`` through a loaded structure. Keys and ids stay. A list item that was nothing but the value goes
    (an alias of ``[removed: password]`` names nothing); a scalar field keeps its mark."""
    if isinstance(value, str):
        if episode_scrub._is_key_field(key):
            return value, 0
        return sensitive_text.take_out(value, marks, speaks=speaks)
    if isinstance(value, dict):
        here = speaks or any(isinstance(v, str) and sensitive_text.speaks_of_a_secret(v) for v in value.values())
        out, total = {}, 0
        for k, v in value.items():
            out[k], n = _walk(v, marks, key=k, speaks=here)
            total += n
        return out, total
    if isinstance(value, list):
        items, total = [], 0
        for v in value:
            got, n = _walk(v, marks, key=key, speaks=speaks)
            total += n
            if n and isinstance(v, str) and got in marks.values():
                continue
            items.append(got)
        return items, total
    return value, 0


def _fields(value, marks: dict[str, str]):
    """A whole file's top level: each field read by itself. A page's summary that says "account" says nothing about its
    other fields, where a claim's predicate does say something about its object."""
    if not isinstance(value, dict):
        return _walk(value, marks)
    out, total = {}, 0
    for k, v in value.items():
        out[k], n = _walk(v, marks, key=k)
        total += n
    return out, total


def _prose(text: str, marks: dict[str, str]) -> str:
    """Prose. A link whose target or label held the value becomes the mark alone: ``[[[removed: password]]]`` links nowhere
    and reads as broken."""
    def link(m: re.Match) -> str:
        whole = m.string
        line = whole[whole.rfind("\n", 0, m.start()) + 1:(whole.find("\n", m.end()) + 1 or len(whole))]
        for value, mark in marks.items():
            if sensitive_text.holds(m.group(1), value) and (sensitive_text.distinctive(value)
                                                            or sensitive_text.speaks_of_a_secret(line)):
                return mark
        return m.group(0)

    return sensitive_text.take_out(_WIKILINK_RE.sub(link, text), marks)[0]


def _body(body: str, marks: dict[str, str]) -> str:
    out: list[str] = []
    at = 0
    for m in claims._CLAIMS_BLOCK_RE.finditer(body):
        out.append(_prose(body[at:m.start("payload")], marks))
        out.append(_fence(m.group("payload"), marks))
        at = m.end("payload")
    out.append(_prose(body[at:], marks))
    return "".join(out)


def _fence(payload: str, marks: dict[str, str]) -> str:
    """A claim fence: its entries loaded, walked, and written in the one encoder, only if one changed. One that does not
    load is already broken and left for the person to see; a distinctive value still goes, as text, since no parse depends
    on it."""
    try:
        loaded = markdown_parser.load_yaml(payload)
    except Exception:  # noqa: BLE001
        loaded = None
    if not isinstance(loaded, list):
        return sensitive_text.take_out(payload, {k: v for k, v in marks.items() if sensitive_text.distinctive(k)})[0]
    entries, n = _walk(loaded, marks)
    if not n:
        return payload
    return "\n".join(claims._jsonl_line(entry) for entry in entries) + "\n"


def _markdown(text: str, marks: dict[str, str]) -> str:
    m = markdown_parser._FENCED.match(text)
    if m is None:
        return _body(text, marks)
    head, body = text[:m.start(2)], m.group(2)
    try:
        fm = markdown_parser.load_yaml(m.group(1) or "")
    except Exception:  # noqa: BLE001 - broken before us: never made worse, and the residue count says so
        fm = None
    if isinstance(fm, dict):
        kept, n = _fields(fm, marks)
        if n:
            dumped = yaml.dump(kept, default_flow_style=False, sort_keys=False).strip()
            head = f"---\n{dumped}\n---\n"
    return head + _body(body, marks)


def _jsonl(text: str, marks: dict[str, str]) -> str:
    out = []
    for line in text.split("\n"):
        try:
            loaded = json.loads(line) if line.strip() else None
        except ValueError:
            loaded = None
        if loaded is None:
            out.append(sensitive_text.take_out(line, {k: v for k, v in marks.items() if sensitive_text.distinctive(k)})[0])
            continue
        entry, n = _walk(loaded, marks)
        out.append(json.dumps(entry, ensure_ascii=False, default=str) if n else line)
    return "\n".join(out)


def _structured(path: Path, text: str, marks: dict[str, str]) -> str:
    loaded = json.loads(text) if path.suffix == ".json" else markdown_parser.load_yaml(text)
    kept, n = _fields(loaded, marks)
    if not n:
        return text
    if path.suffix == ".json":
        return json.dumps(kept, ensure_ascii=False, indent=2) + "\n"
    return yaml.dump(kept, default_flow_style=False, sort_keys=False, allow_unicode=True)


def cleaned(path: Path, text: str, marks: dict[str, str]) -> str:
    """``text``, what ``path`` holds, without the values, by what the file is. Writes nothing."""
    if path.suffix == ".md":
        return _markdown(text, marks)
    if path.suffix == ".jsonl":
        return _jsonl(text, marks)
    return _structured(path, text, marks)


def _could_hold(text: str, marks: dict[str, str]) -> bool:
    """A value a YAML writer escaped is not in the raw text: a non-ASCII value always needs the load."""
    return any(not k.isascii() or sensitive_text.holds(text, k) for k in marks)


def clean_file(path: Path, marks: dict[str, str], *, tied_ids: tuple[str, ...] | None = None) -> bool:
    """Take ``marks``' values out of one file, atomically. ``tied_ids``: the conversations it must name for a word that is
    not distinctive to be touched (``None``: the caller knows the file is theirs). Raises when the file cannot be written,
    so a removal can stop while the value is still findable. An unreadable or unparsable file is left, never damaged."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    here = marks
    if tied_ids is not None and not any(i in text for i in tied_ids):
        here = {k: v for k, v in marks.items() if sensitive_text.distinctive(k)}
    if not here or not _could_hold(text, here):
        return False
    try:
        new = cleaned(path, text, here)
    except Exception as exc:  # noqa: BLE001 - a file that does not parse is no reason to damage it
        logger.warning(f"Sensitive purge left a file it could not read: {type(exc).__name__}")
        return False
    if new == text:
        return False
    markdown_parser.write_document(path, new)
    return True


def residue(memory_path: Path, values) -> int:
    """How many files still hold one of these exact values after a purge (a key field, a file that does not parse). A
    count only. Reads files only."""
    distinct = [v for v in values if sensitive_text.distinctive(v)]
    if not distinct:
        return 0
    marks = {v: "x" for v in distinct}
    found = 0
    for path in bank_files(Path(memory_path)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(sensitive_text.holds(text, v) for v in distinct):
            found += 1
            continue
        if any(not v.isascii() for v in distinct) and path.suffix == ".md":
            try:
                if cleaned(path, text, marks) != text:
                    found += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"sensitive residue skipped one: {type(exc).__name__}")
    return found
