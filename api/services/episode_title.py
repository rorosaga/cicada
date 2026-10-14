"""A captured session's title, from the person's own words — never a wrapper tag (2026-10-14).

The Stop hook titles a session by its first person message (G105 R12). That message can open with a wrapper the
harness put around the person's text — ``<pasted_content id="…">`` around a paste, or a ``<system-reminder>`` /
``<command-name>`` block that arrived inside the person's own text (G110 gate C keeps those in the body) — and the
title became the bare opening tag, shown as the conversation's name in the inbox, Home, the Sleep queue and recall.

:func:`title_from_text` reads a message as wrappers and text. A tag opens a wrapper only at the start of a line (or
right after another tag), so a mid-sentence ``Vec<String>`` is just words; a closing tag closes the innermost open
wrapper of its name wherever it sits; a wrapper the per-turn cap cut off before its close runs to the end. Text inside
a harness wrapper (the extractor's own ``CLAUDE_HARNESS_TAGS`` / ``CODEX_HARNESS_TAGS``) is the harness talking, never
a title. The title is the first real line OUTSIDE every wrapper; when the message is only wrapped text (a paste and
nothing else), the first real line inside it. A real line is not empty, not only tags, and not the extractor's
``[code omitted]`` marker. Nothing qualifies → ``None``, and :func:`title_for` moves to the next person turn, then to
``<Product> session``. Never a tag, never empty. Title only: the body is the person's words as captured.

:func:`survey` / :func:`apply` are the one-off retitle for episodes captured before this (``api.scripts.
retitle_wrapped_episodes``): a transcript episode whose stored title opens with a tag is retitled from its own stored
body — the transcript is never re-read — in one ``cicada`` commit, refused while Sleep runs or holds the pages. The
title is outside ``content_hash``, so nothing is re-queued for Sleep.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from loguru import logger

from api.services.transcript_extract import CLAUDE_HARNESS_TAGS, CODE_OMITTED, CODEX_HARNESS_TAGS

TITLE_MAX = 72
PRODUCT = {"claude-code": "Claude Code", "codex": "Codex"}
HARNESS_TAGS = CLAUDE_HARNESS_TAGS | CODEX_HARNESS_TAGS
TRIGGER = "maintenance/episode-titles"

# One tag: `<name attrs>`, `</name>` or `<name/>`. Names start with a letter or `_` (so `<3` and `a < b` are words).
_TAG_RE = re.compile(r"<(/?)([A-Za-z_][A-Za-z0-9_.:-]*)((?:\s[^<>]*?)?)\s*(/?)>")
_TAG_ONLY_LINE_RE = re.compile(r"^\s*(?:" + _TAG_RE.pattern + r"\s*)+$")
_LEADS_WITH_TAG_RE = re.compile(r"^\s*</?[A-Za-z_]")


def _segments(text: str) -> list[tuple[str, int]]:
    """``(text, depth)`` pieces in order; ``depth`` 0 is outside every wrapper. Text inside a harness wrapper is
    dropped. A tag piece is never returned."""
    out: list[tuple[str, int]] = []
    stack: list[str] = []
    pos = 0
    line_start = True  # at the start of a line, or only whitespace/tags since it

    def emit(piece: str) -> None:
        nonlocal line_start
        if not piece:
            return
        if not any(name in HARNESS_TAGS for name in stack):
            out.append((piece, len(stack)))
        tail = piece.rsplit("\n", 1)
        line_start = (len(tail) == 2 and not tail[1].strip()) or (line_start and not piece.strip())

    for m in _TAG_RE.finditer(text):
        closing, name = m.group(1) == "/", m.group(2).lower()
        self_closing = m.group(4) == "/"
        between = text[pos:m.start()]
        at_line_start = (line_start and not between.strip()) or bool(re.search(r"\n[ \t]*\Z", between))
        if closing:
            if name not in stack and not at_line_start:
                continue  # a stray closing tag mid-line is words
            emit(between)
            if name in stack:
                while stack and stack.pop() != name:
                    pass
        elif at_line_start:
            emit(between)
            if not self_closing:
                stack.append(name)
        else:
            continue  # a tag mid-line is words (`Vec<String>`)
        pos = m.end()
        line_start = True
    emit(text[pos:])
    return out


def _real_lines(pieces: Iterable[str]) -> Iterable[str]:
    for piece in pieces:
        for line in piece.splitlines():
            line = line.strip()
            if line and line != CODE_OMITTED and not _TAG_ONLY_LINE_RE.match(line):
                yield line


def _clip(line: str) -> str:
    return line if len(line) <= TITLE_MAX else line[: TITLE_MAX - 1] + "…"


def title_from_text(text: str) -> str | None:
    """The person's own first line, outside any wrapper first, else inside one; ``None`` when there is none."""
    segments = _segments(text or "")
    for line in _real_lines(t for t, depth in segments if depth == 0):
        return _clip(line)
    for line in _real_lines(t for t, depth in segments if depth > 0):
        return _clip(line)
    return None


def title_for(user_texts: Iterable[str], harness: str) -> str:
    """The first person turn that holds a real line names the session; else ``<Product> session``."""
    for text in user_texts:
        title = title_from_text(text)
        if title:
            return title
    return f"{PRODUCT.get(harness, harness)} session"


def is_wrapper_title(title) -> bool:
    """A stored title that opens with a tag — what the old first-line rule wrote for a wrapped message."""
    return isinstance(title, str) and bool(_LEADS_WITH_TAG_RE.match(title))


def user_texts_from_body(body: str, frontmatter: dict | None) -> list[str]:
    """The person's turns of a stored transcript episode, from its turn sidecar (offsets into the body, G141 PJ-4,
    read through its one reader ``evidence.turn_stamps``). Without one: the body's first ``user:`` turn up to the
    first ``assistant:`` line."""
    from api.services import evidence

    offsets = sorted((at, e["speaker"]) for at, e in evidence.turn_stamps(frontmatter).items() if at <= len(body))
    out = []
    for i, (at, speaker) in enumerate(offsets):
        if speaker != "user":
            continue
        end = offsets[i + 1][0] if i + 1 < len(offsets) else len(body)
        chunk = body[at:end]
        if chunk.startswith("user: "):
            out.append(chunk[len("user: "):])
    if out:
        return out
    if not body.startswith("user: "):
        return []
    lines = body[len("user: "):].split("\n")
    kept = []
    for line in lines:
        if line.startswith("assistant: "):
            break
        kept.append(line)
    return ["\n".join(kept)]


# --- the one-off retitle ---------------------------------------------------------


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: change nothing."""


@dataclass
class Survey:
    transcripts: int = 0      # transcript episodes read
    wrapper_titles: int = 0   # of them, titled by a tag
    would_retitle: int = 0    # wrapper-titled, clean: retitled (the person's line, else `<Product> session`)
    dirty: int = 0            # wrapper-titled but dirty in git or written since the survey: its writer's to commit
    written: int = 0
    committed: bool = False
    _todo: dict = field(default_factory=dict, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def survey(memory_path) -> Survey:
    """What :func:`apply` would change. Read-only; counts only."""
    from api.services import git_service, markdown_parser

    memory_path = Path(memory_path)
    result = Survey()
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "episodes")
        except git_service.GitError:
            dirty = frozenset()
    for path in sorted((memory_path / "episodes").glob("ep_*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — a malformed episode is skipped, never fatal
            continue
        fm = parsed.frontmatter
        if not isinstance(fm, dict) or fm.get("capture_kind") != "transcript":
            continue
        result.transcripts += 1
        if not is_wrapper_title(fm.get("title")):
            continue
        result.wrapper_titles += 1
        harness = str(fm.get("harness") or fm.get("source") or "")
        texts = user_texts_from_body(parsed.body, fm)
        new = title_for(texts, harness)   # never a tag, so always a change
        if f"episodes/{path.name}" in dirty:
            result.dirty += 1
            continue
        result.would_retitle += 1
        result._todo[path] = (text, new)
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Retitle what :func:`survey` found and commit it in ONE commit authored ``cicada``. Raises
    :class:`SleepRunning` before writing anything when Sleep holds the pages or a run is in progress."""
    from api.services import episode_ids, git_service, markdown_parser, page_lock, write_admission

    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    written: list[Path] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; retitle after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            for path, (surveyed, title) in result._todo.items():
                with episode_ids.episode_lock(episodes_dir):
                    if path.read_text(encoding="utf-8") != surveyed:  # captured again since the survey
                        result.dirty += 1
                        result.would_retitle -= 1
                        continue
                    parsed = markdown_parser.parse(path)
                    fm = dict(parsed.frontmatter)
                    fm["title"] = title
                    markdown_parser.write(path, fm, parsed.body)
                written.append(path)
            rels = [f"episodes/{p.name}" for p in written]
            result.written = len(rels)
            if rels and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Episode titles: {len(rels)} episode(s) named by the person's words, not a wrapper tag",
                    [f"{rel}: title (trigger: {TRIGGER})" for rel in rels],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if written:
        logger.info(f"episode retitle: {len(written)} episode(s)")
    return result
