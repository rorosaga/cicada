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
nothing else), the first real line inside it. A real line is not empty, not only tags, does not still open like
a tag (one left unterminated, or past the attribute bound), and is not the extractor's ``[code omitted]`` marker.
Nothing qualifies → ``None``, and :func:`title_for` moves to the next person turn, then to ``<Product> session``.
Never a tag, never empty. Title only: the body is the person's words as captured. The scan is linear in the message
(it runs in the Stop hook): a 16k adversarial message titles in well under 50 ms.

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
PRODUCT = {"claude-code": "Claude Code", "codex": "Codex", "cursor": "Cursor", "gemini-cli": "Gemini CLI"}
#: A chat export's origin -> the app whose assistant lines it holds (`entity_extractor.assistant_observer`).
CHAT_EXPORTS = {"chatgpt-export": "chatgpt", "claude-export": "claude", "gemini-export": "gemini"}


def assistant_of(origin: str | None) -> str | None:
    """The agent whose ``assistant:`` lines an episode or claim of this origin holds: a harness, or a chat export's
    app. ``None`` for every other origin (a texted agent is named by its correspondent, a source by itself)."""
    origin = str(origin or "").strip().lower()
    return origin if origin in PRODUCT else CHAT_EXPORTS.get(origin)
HARNESS_TAGS = CLAUDE_HARNESS_TAGS | CODEX_HARNESS_TAGS
TRIGGER = "maintenance/episode-titles"

# One tag: `<name attrs>`, `</name>` or `<name/>`. Names start with a letter or `_` (so `<3` and `a < b` are words).
# Linear by construction (it runs in the Stop hook): the name and the attribute run are bounded, the attribute run
# stops at the next `<`, and nothing after it can match the same characters twice.
_TAG_RE = re.compile(r"<(/?)([A-Za-z_][A-Za-z0-9_.:-]{0,63})(\s[^<>]{0,512}|/)?>")
_LEADS_WITH_TAG_RE = re.compile(r"^\s*</?[A-Za-z_]")


def _segments(text: str) -> list[tuple[str, int]]:
    """``(text, depth)`` pieces in order; ``depth`` 0 is outside every wrapper. Text inside a harness wrapper is
    dropped. A tag piece is never returned. One pass: every slice and scan covers characters no other one does."""
    out: list[tuple[str, int]] = []
    stack: list[str] = []
    open_count: dict[str, int] = {}
    harness_open = 0
    pos = 0
    line_start = True  # `pos` is at the start of a line, or only whitespace/tags since it

    def emit(piece: str) -> None:
        nonlocal line_start
        if not piece:
            return
        if not harness_open:
            out.append((piece, len(stack)))
        head, nl, tail = piece.rpartition("\n")
        line_start = (bool(nl) and not tail.strip()) or (line_start and not piece.strip())

    def pop() -> str:
        nonlocal harness_open
        name = stack.pop()
        open_count[name] -= 1
        harness_open -= name in HARNESS_TAGS
        return name

    for m in _TAG_RE.finditer(text):
        closing, name = m.group(1) == "/", m.group(2).lower()
        self_closing = (m.group(3) or "").rstrip().endswith("/")
        # Only the spaces and tabs right before this tag are scanned back over.
        j = m.start()
        while j > pos and text[j - 1] in " \t":
            j -= 1
        at_line_start = (line_start if j == pos else text[j - 1] == "\n")
        is_open = open_count.get(name, 0) > 0
        if closing:
            if not is_open and not at_line_start:
                continue  # a stray closing tag mid-line is words
            emit(text[pos:m.start()])
            if is_open:
                while pop() != name:
                    pass
        elif at_line_start:
            emit(text[pos:m.start()])
            if not self_closing:
                stack.append(name)
                open_count[name] = open_count.get(name, 0) + 1
                harness_open += name in HARNESS_TAGS
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
            if not line or line == CODE_OMITTED:
                continue
            words = _TAG_RE.sub("", line).strip()
            # Only tags, or a line that still opens like one (a tag left open, or past the attribute bound).
            if words and not _LEADS_WITH_TAG_RE.match(words):
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
            raw = path.read_bytes()
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
        result._todo[path] = (raw, new)
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Retitle what :func:`survey` found and commit it in ONE commit authored ``cicada``. Raises
    :class:`SleepRunning` before writing anything when Sleep holds the pages or a run is in progress.

    All or nothing: if anything raises after the first rewrite — a write, or the commit itself — every episode
    already rewritten is put back byte for byte, its index entry too (unless something else wrote it since), so a
    failed run leaves no uncommitted retitle behind and the next run starts from the same survey."""
    from api.services import episode_ids, git_service, markdown_parser, page_lock, write_admission

    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    written: list[tuple[Path, bytes, bytes]] = []   # (path, as surveyed, as rewritten)
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; retitle after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            try:
                for path, (surveyed, title) in result._todo.items():
                    with episode_ids.episode_lock(episodes_dir):
                        if path.read_bytes() != surveyed:  # captured again since the survey
                            result.dirty += 1
                            result.would_retitle -= 1
                            continue
                        parsed = markdown_parser.parse(path)
                        fm = dict(parsed.frontmatter)
                        fm["title"] = title
                        markdown_parser.write(path, fm, parsed.body)
                        written.append((path, surveyed, path.read_bytes()))
                rels = [f"episodes/{p.name}" for p, _, _ in written]
                if rels and (memory_path / ".git").exists():
                    message = git_service.build_commit_message(
                        f"Episode titles: {len(rels)} episode(s) named by the person's words, not a wrapper tag",
                        [f"{rel}: title (trigger: {TRIGGER})" for rel in rels],
                        authors=["cicada"],
                    )
                    git_service.commit_paths_sync(memory_path, message, rels)
                    result.committed = True
            except BaseException:
                if not result.committed:
                    _restore(memory_path, written)
                raise
            result.written = len(written)
    if written:
        logger.info(f"episode retitle: {len(written)} episode(s)")
    return result


def _restore(memory_path: Path, written: list[tuple[Path, bytes, bytes]]) -> None:
    """Put back what a failed :func:`apply` rewrote — the file, and the index if the commit failed after staging; an
    episode written again since (a capture) is left to its writer."""
    from api.services import episode_ids, git_service, markdown_parser

    episodes_dir = memory_path / "episodes"
    if written and (memory_path / ".git").exists():
        try:   # the surveyed files were clean, so their index entry is HEAD's
            rels = [f"episodes/{p.name}" for p, _, _ in written]
            git_service.run_git_write_sync(memory_path, "reset", "-q", "--", *rels)
        except Exception as exc:  # noqa: BLE001 — restore the files regardless
            logger.warning(f"episode retitle: could not unstage ({type(exc).__name__})")
    for path, before, after in reversed(written):
        try:
            with episode_ids.episode_lock(episodes_dir):
                if path.read_bytes() == after:
                    markdown_parser._replace(path, before)
        except Exception as exc:  # noqa: BLE001 — restore the rest; the original error is what is raised
            logger.warning(f"episode retitle: could not restore one episode ({type(exc).__name__})")
