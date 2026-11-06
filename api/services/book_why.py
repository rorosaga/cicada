"""Why a described book may matter: one bounded model read of its public description (ruling 70 (a), G233).

A book the person added carries a description from a public source (`books._description_body`). Sleep reads that
description once, never the book's text, and keeps one short sentence on the page's record (`book.why`, with the day
and the engine's label): what the book is about in a form recall, Ask and an agent's stated reason can find. It is
`external` knowledge, not the person's words, nor a sign they read the book.

What it never does: read a book with no description; read a page twice (`why_at` is the stamp, a declined title match
never has one); ask the person anything; make a link (ruling 56: a link needs a recorded fact or an agent's stated
reason); spend a metered key nobody chose (`settings`' own engine resolution decides, as for every Sleep job). Bounded:
:data:`PER_RUN` books a run, the description cut at :data:`DESC_CHARS`, the answer at :data:`MAX_TOKENS`.
**Cost per book** is one call of roughly 250 input and 45 output tokens (:func:`estimate`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import bank_index, markdown_parser
from api.services.books import is_book

PER_RUN = 20
DESC_CHARS = 700
MAX_TOKENS = 80
WHY_CHARS = 280
STAGE = "book_why"


def candidates(memory_path: Path, *, limit: int = PER_RUN) -> list[dict]:
    """Books with a description and no read yet, newest description first, at most ``limit``."""
    out: list[dict] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        book = fm.get("book") if is_book(fm) and isinstance(fm.get("book"), dict) else None
        if not book or not book.get("description_at") or book.get("why_at") or book.get("title_match_declined"):
            continue
        if str(fm.get("status") or "active") in ("dropped", "archived"):
            continue
        out.append({"id": Path(f.path).stem, "path": str(f.path), "title": book.get("title") or fm.get("name") or "",
                    "authors": list(book.get("authors") or []), "at": str(book["description_at"])})
    out.sort(key=lambda c: c["at"], reverse=True)
    return out[:limit]


def _description(body: str) -> str:
    text = (body or "").strip()
    if text.startswith("## Summary"):
        text = text[len("## Summary"):].strip()
    return text.split("\n\nFrom ", 1)[0].strip()[:DESC_CHARS]


def prompt(title: str, authors: list[str], description: str) -> str:
    return ("A public description of a book follows. In one plain sentence (at most 40 words), say what the book is about "
            "and what kind of reader or topic it may matter to. Use only the description; do not praise it, do not say "
            "anyone read it.\n\n"
            f"Title: {title}\nAuthors: {', '.join(authors)}\nDescription: {description}\n\nSentence:")


def clean(text: str | None) -> str | None:
    one = " ".join((text or "").split()).strip("\"' ")
    return one[:WHY_CHARS] if len(one) >= 12 else None


def estimate(description_chars: int = DESC_CHARS) -> dict:
    """Tokens one book costs (characters / 4), the figure the owner reads before a backfill."""
    return {"input_tokens": (len(prompt("", [], "")) + 40 + description_chars) // 4, "output_tokens": MAX_TOKENS // 2 + 5}


async def run(memory_path: Path, settings: Any, *, llm_fn: Callable[..., Any] | None = None, today: str,
              limit: int = PER_RUN) -> list[str]:
    """Read each candidate's description once; return the written paths. Never raises."""
    todo = candidates(memory_path, limit=limit)
    if not todo:
        return []
    try:
        if llm_fn is None:
            import litellm

            from api.services.providers import resolve_llm_fn
            llm_fn = resolve_llm_fn(settings, model=getattr(settings, "litellm_model", "") or None,
                                    completion=litellm.acompletion, stage=STAGE)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Book reads skipped: {type(exc).__name__}")
        return []
    paths: list[str] = []
    for c in todo:
        path = Path(c["path"])
        try:
            parsed = markdown_parser.parse(path)
            desc = _description(parsed.body)
            if not desc:
                continue
            resp = await llm_fn(messages=[{"role": "user", "content": prompt(c["title"], c["authors"], desc)}],
                                max_tokens=MAX_TOKENS, temperature=0)
            why = clean(resp.choices[0].message.content)
            fresh = markdown_parser.parse(path)   # the page may have changed during the call
            book = dict(fresh.frontmatter.get("book") or {})
            if not why or book.get("why_at") or book.get("title_match_declined"):
                continue
            book["why"], book["why_at"] = why, today
            markdown_parser.write(path, {**fresh.frontmatter, "book": book}, fresh.body)
            paths.append(f"entities/{path.name}")
        except Exception as exc:  # noqa: BLE001 - one book never stops the rest
            if type(exc).__name__ in ("AuthenticationError", "RateLimitError"):
                logger.warning(f"Book reads stopped: {type(exc).__name__}")
                break
            logger.warning(f"Book read failed: {type(exc).__name__}")
    return paths
