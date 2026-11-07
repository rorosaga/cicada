"""A synthetic bank at the owner's scale for Stage 2 (2026-11-05 stall): ~8,500 pages, ~9,500 episodes, ~21,000 claims,
and a pending store of parked names, plus one batch of extractions that hits every lookup Stage 2 makes. Never
collected by pytest (underscore prefix). Placeholder names only; nothing reads a real bank, ``~/.cicada`` or the
network. The same seed writes the same bank, so a before and an after run read one input."""
from __future__ import annotations

import json
import random
from pathlib import Path

from api.services import claims as claims_mod
from api.services import markdown_parser, pending_store, predicates

GIVEN = [f"{a}{b}" for a in ("Al", "Be", "Ca", "Do", "El", "Fa", "Go", "Ha", "Ir", "Jo", "Ka", "Lu", "Mi", "No")
         for b in ("na", "ro", "mi", "lo", "ta", "vi")]
SURNAME = [f"{a}{b}son" for a in ("Bar", "Cor", "Del", "Fen", "Gar", "Hol", "Jen", "Kel", "Lor", "Mar", "Nor", "Pel")
           for b in ("ek", "in", "ad", "um", "ov", "ar", "en", "is", "ot", "ul")]
WORD = [f"{a}{b}{c}" for a in ("ze", "qua", "tri", "plo", "mer", "vas", "nob", "fli", "gra", "sto")
        for b in ("n", "r", "l", "st", "mb")
        for c in ("ine", "ora", "ex", "ium", "ade", "ist", "ock", "ura")]
TYPES = ("person", "concept", "tool", "organization", "project", "place", "person", "concept")


def page_name(n: int) -> tuple[str, str]:
    """The ``n``th page's (name, type): the same for the bank and for a batch that mentions it."""
    kind = TYPES[n % len(TYPES)]
    if kind == "person":
        return f"{GIVEN[n % len(GIVEN)]} {SURNAME[(n // 3) % len(SURNAME)]} {n}", kind
    return f"{WORD[n % len(WORD)].title()} {WORD[(n * 7) % len(WORD)].title()} {n}", kind


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def _episode_id(i: int) -> str:
    return f"ep_2026-{1 + i % 10:02d}-{1 + i % 28:02d}_{i:05d}"


def _held_name(p: int) -> str:
    return f"{WORD[p % len(WORD)].title()} {GIVEN[p % len(GIVEN)]} Held {p}"


def _claim(slug: str, name: str, n: int, episode: str) -> claims_mod.Claim:
    return claims_mod.Claim(id=f"c-{slug[:20]}-{n}", text=f"{name} has synthetic property {n}.", subject=slug,
                            predicate="related_to", object=f"thing {n}", object_kind="literal",
                            source_episodes=[episode], recorded_at="2026-09-01", valid_from="2026-09-01",
                            confidence=0.7)


def build(memory: Path, *, pages: int = 8500, episodes: int = 9500, claims: int = 21000, pending: int = 5574,
          seed: int = 7) -> Path:
    """Write the bank under ``memory`` and return it."""
    rng = random.Random(seed)
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    predicates.install_predicate_map(memory)
    per_page = max(1, claims // pages)
    extra = claims - per_page * pages
    for n in range(pages):
        name, kind = page_name(n)
        slug = _slug(name)
        sources = [_episode_id(rng.randrange(episodes)) for _ in range(rng.choice((1, 2, 3, 5, 8, 21)))]
        fm = {"name": name, "type": kind, "status": "archived" if n % 41 == 41 - 1 else "active", "confidence": 0.6,
              "created": "2026-01-01", "last_referenced": "2026-09-01", "decay_rate": 0.05,
              "source_episodes": sources, "tags": ["fixture"], "version": 2,
              "aliases": [f"{name.split()[0]} {n}x"] if n % 4 == 0 else []}
        if n == 0:
            fm["owner"] = True
        count = per_page + (1 if n < extra else 0)
        body = (f"## Summary\n{name} is a synthetic fixture page. " * 4 + "\n\n## Notes\n"
                + "- a placeholder note about the fixture\n" * 8)
        body = claims_mod.write_claims(body, [_claim(slug, name, c, sources[0]) for c in range(count)])
        markdown_parser.write(memory / "entities" / f"{slug}.md", fm, body)
    for i in range(episodes):
        eid = _episode_id(i)
        named = [page_name(rng.randrange(pages))[0] for _ in range(6)]
        body = ("## Person\n" + " ".join(f"Talked about {x} today." for x in named[:3])
                + "\n\n## Agent\n" + " ".join(f"Noted that {x} matters." for x in named[3:])
                + "\n" + "A placeholder line of a captured conversation.\n" * 40)
        markdown_parser.write(memory / "episodes" / f"{eid}.md",
                              {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00", "processed": True,
                               "origin": ("claude_code", "chatgpt_export", "imessage")[i % 3], "title": f"Chat {i}"},
                              body)
    lines = []
    for p in range(pending):
        name = _held_name(p)
        line = pending_store.PendingEntity(
            name=name, type=("concept", "person", "tool")[p % 3],
            description=f"{name} was mentioned once in a synthetic conversation.",
            source_episode=_episode_id(p % episodes), confidence=0.5, tags=["fixture"],
            history_entries=[{"date": "2026-09-01", "text": "first mention"}],
            summary=f"{name} is a synthetic held name. " * 3,
            key_facts=[f"held fact {k}" for k in range(4)],
            heard_in=[{"episode": _episode_id(p % episodes), "timestamp": "2026-09-01T10:00:00+00:00",
                       "day": "2026-09-01"}])
        if p % 3 == 0:
            line.held_claims = [_claim(_slug(name), name, c, _episode_id(p % episodes)).to_dict() for c in range(4)]
        lines.append(json.dumps(line.to_dict()))
    pending_store.store_path(memory).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for extraction in batch():   # the conversations the batch reads, waiting
        eid = extraction["episode_id"]
        names = ", ".join(e["name"] for e in extraction["entities"])
        markdown_parser.write(memory / "episodes" / f"{eid}.md",
                              {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00", "processed": False,
                               "origin": "claude_code", "session_id": f"ses_{eid[3:]}", "title": eid},
                              f"## Person\nToday I talked about {names}.\n")
    return memory


def batch(*, conversations: int = 25, entities: int = 63, unborn_projects: int = 4, pages: int = 8500,
          pending: int = 5574, seed: int = 11) -> list[dict]:
    """What Stage 1 hands Stage 2 for one batch, at the measured night's shape (25 conversations, 63 entities, 4 project
    names with no page): existing pages by exact name, a given name alone (the judge's lead), a held name heard again,
    and new names, each with a relationship to the next."""
    rng = random.Random(seed)
    out = [{"episode_id": f"ep_2026-11-04_{c:05d}", "entities": [], "relationships": [], "claims": []}
           for c in range(conversations)]
    for k in range(entities):
        extraction = out[k % conversations]
        if k < unborn_projects:
            name, kind = f"{WORD[k].title()} Unborn Build {k}", "project"
        elif k % 3 == 0:
            name, kind = page_name(rng.randrange(pages))
        elif k % 3 == 1:
            full, _ = page_name(rng.randrange(0, pages, 8))   # a person page
            name, kind = full.split()[0], "person"
        else:
            name, kind = _held_name(rng.randrange(pending)), "concept"
        ents = extraction["entities"]
        ents.append({"name": name, "type": kind, "confidence": 0.8, "summary": f"{name}, synthetic.",
                     "source_episode": extraction["episode_id"], "aliases": []})
        if len(ents) > 1:
            extraction["relationships"].append({"source": ents[-2]["name"], "target": name, "label": "related to"})
    return out
