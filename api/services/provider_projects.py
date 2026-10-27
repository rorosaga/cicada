"""Projects the person already made in Claude, read from a Claude export (TODO ruling 45 addendum, 2026-10-27).

Claude's export holds ``projects.json``: each project's ``uuid``, ``name``, ``description``, its instructions
(``prompt_template``) and its knowledge files (``docs``). Its ``conversations.json`` has **no field linking a
conversation to a project**, so nothing here ties a conversation; a future Claude field, like ChatGPT's ``g-p-`` id
today, would ride as the episode's ``provider_project`` (``project_conversations``' fifth signal).

Each non-starter project makes or matches one project page, with no model (file I/O, like a folder the person named):

* a page that already records the project's id (``provider_projects``) is updated — its description seeded only when
  the person's is empty, its documents' names and its instructions' span refreshed — and **never re-created**: a
  project id seen once is kept in the bank's ``project_groupings.yaml`` (``imported``), so a page the person deleted
  or marked not theirs stays that way on every re-import;
* else a live project page whose name folds the same takes the id;
* else a new page: ``born: {origin: created, via: claude-export}``, the person's own (``mine: {via: import}``) while
  :data:`project_ownership.CLAUDE_EXPORT_MINE` holds, else a suggestion.

The instructions live in the project's knowledge episode (``parse_anthropic_projects``, staged through
``episode_staging`` and idempotent by ``source_id``); the page records a span into it (offsets and the body's hash,
never a copy, G118), and the Projects page shows it while the episode still holds those bytes. Documents are listed by
name: the import reads none of their contents. Everything written commits alone under the person
(``trigger: user/claude-export``).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, evidence, markdown_parser, page_lock, project_birth, project_ownership

PROVIDER = "claude"
TRIGGER = "user/claude-export"
_INSTRUCTIONS_LEAD = "Prompt template: "


def _imported(memory_path: Path) -> set[tuple[str, str]]:
    path = Path(memory_path) / project_ownership.GROUPINGS_FILE
    try:
        data = markdown_parser.load_yaml(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return set()
    return {(str(r.get("provider")), str(r.get("id"))) for r in data.get("imported") or [] if isinstance(r, dict)}


def _remember(memory_path: Path, keys: set[tuple[str, str]]) -> list[str]:
    path = Path(memory_path) / project_ownership.GROUPINGS_FILE
    try:
        data = markdown_parser.load_yaml(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        data = {}
    have = {(str(r.get("provider")), str(r.get("id"))) for r in data.get("imported") or [] if isinstance(r, dict)}
    if keys <= have:
        return []
    data["imported"] = [{"provider": p, "id": i} for p, i in sorted(have | keys)]
    markdown_parser.write_yaml(path, data)
    return [project_ownership.GROUPINGS_FILE]


def _instructions_span(memory_path: Path, episode: str | None) -> dict | None:
    """Where the instructions sit in the knowledge episode: after ``Prompt template: `` to the body's end."""
    if not episode:
        return None
    body = evidence.source_text(memory_path, episode)
    if not body:
        return None
    at = body.find(_INSTRUCTIONS_LEAD)
    if at < 0:
        return None
    start = at + len(_INSTRUCTIONS_LEAD)
    end = len(body.rstrip())
    return {"start": start, "end": end, "hash": evidence.body_hash(body)} if end > start else None


def _day(raw) -> str | None:
    text = str(raw or "")
    return text[:10] if len(text) >= 10 and text[4] == "-" else None


@page_lock.locked
def adopt_claude(memory_path: Path, projects: list[dict], episode_ids: dict[str, str] | None = None,
                 *, today: date | None = None) -> list[str]:
    """Make or match a page for each Claude project; returns the paths written. ``episode_ids`` maps a knowledge
    episode's ``source_id`` (``claude-project:<uuid>``) to its id, from the stager."""
    memory_path = Path(memory_path)
    episode_ids = episode_ids or {}
    seen = _imported(memory_path)
    pages = {f.stem: dict(f.frontmatter or {}) for f in bank_index.files(memory_path, "entities")}
    by_id = {(str(p["provider"]), str(p["id"])): stem for stem, fm in pages.items()
             for p in project_ownership.provider_projects(fm)}
    paths: list[str] = []
    remembered: set[tuple[str, str]] = set()
    for project in projects:
        key = (PROVIDER, project["uuid"])
        episode = episode_ids.get(f"claude-project:{project['uuid']}")
        entry = {"provider": PROVIDER, "id": project["uuid"], "name": project["name"], "episode": episode,
                 "docs": project.get("docs") or [], "instructions": _instructions_span(memory_path, episode)}
        stem = by_id.get(key)
        if stem is None and key in seen:
            continue                       # imported before; the page was deleted — never made again
        if stem is None:
            want = project_birth.fold(project["name"])
            stem = next((s for s, fm in pages.items() if project_ownership.is_project_like(fm)
                         and str(fm.get("status") or "active") != "dropped"
                         and want in project_birth.name_folds({"name": fm.get("name") or s,
                                                              "aliases": fm.get("aliases") or []})), None)
        if stem is None:
            try:
                stem, written = project_ownership.create(
                    memory_path, project["name"], project.get("description") or "", via=project_ownership.VIA_IMPORT,
                    by="user", listed=project_ownership.CLAUDE_EXPORT_MINE, born_via="claude-export",
                    provider={k: v for k, v in entry.items() if v not in (None, "", [])}, today=today)
            except project_ownership.OwnershipError as exc:
                logger.info(f"Claude export: a project was not made ({type(exc).__name__})")
                continue
            born_day = _day(project.get("created_at"))
            if born_day:
                page = memory_path / "entities" / f"{stem}.md"
                parsed = markdown_parser.parse(page, ledger=False)
                fm = dict(parsed.frontmatter)
                fm["born"] = {**fm.get("born", {}), "day": born_day}
                fm["created"] = born_day
                markdown_parser.write(page, fm, parsed.body)
            paths += written
            remembered.add(key)
            continue
        page = memory_path / "entities" / f"{stem}.md"
        parsed = markdown_parser.parse(page, ledger=False)
        fm = dict(parsed.frontmatter)
        changed = project_ownership.add_provider(fm, entry)
        if project.get("description") and not project_ownership.description(fm):
            fm[project_ownership.DESCRIPTION_KEY] = project_ownership.clean_description(project["description"])
            fm[project_ownership.DESCRIPTION_BY_KEY] = {"by": "user", "day": (today or date.today()).isoformat()}
            changed = True
        if (project_ownership.CLAUDE_EXPORT_MINE and not project_ownership.dismissed(fm)
                and not isinstance(fm.get(project_ownership.MINE_KEY), dict)):
            fm[project_ownership.MINE_KEY] = {"via": project_ownership.VIA_IMPORT,
                                              "day": (today or date.today()).isoformat(), "by": "user"}
            changed = True
        if changed:
            markdown_parser.write(page, fm, parsed.body)
            paths.append(f"entities/{page.name}")
        remembered.add(key)
    paths += _remember(memory_path, remembered)
    bank_index.invalidate()
    return list(dict.fromkeys(paths))


def commit(memory_path: Path, paths: list[str]) -> None:
    if not paths:
        return
    from api.services import git_service

    message = git_service.build_commit_message(
        "Projects from a Claude export", [f"{p}: updated (source: claude-export, trigger: {TRIGGER})" for p in paths],
        authors=["user"])
    try:
        git_service.commit_paths_sync(memory_path, message, paths)
    except Exception as exc:  # noqa: BLE001 — the pages stand; a later writer's commit picks them up
        logger.warning(f"Claude export projects: commit skipped ({type(exc).__name__})")


def after_import(memory_path: Path, projects: list[dict], staged) -> list[str]:
    """The import's last step: adopt, then commit what it wrote. Never raises into the import."""
    if not projects:
        return []
    try:
        paths = adopt_claude(memory_path, projects, getattr(staged, "episode_ids", None) or {})
    except Exception as exc:  # noqa: BLE001 — the conversations are imported either way
        logger.warning(f"Claude export projects: not adopted ({type(exc).__name__})")
        return []
    commit(memory_path, paths)
    return paths
