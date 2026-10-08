"""Build a synthetic bank shaped like a mid-drain real one: one owner page carrying thousands of claims, ~2,000 other
pages, ~1,500 episodes, and a git history in which the owner page is rewritten by every Sleep batch.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.synth --bank <dir>/bank --claims 3500

Every name, id and sentence is synthetic (``alpha-project``-style); nothing is read from a real bank.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import subprocess
import time
from pathlib import Path

from . import isolate

OWNER_NAME = "Owner Example"
PREDICATES = [
    "works-on", "uses", "prefers", "decided", "plans", "learned", "built", "maintains", "reads", "attends",
    "lives-in", "studies", "owns", "dislikes", "evaluates", "migrated-to", "wrote", "presented", "manages",
    "collaborates-with", "follows", "subscribed-to", "interested-in", "visited", "bought", "watched", "fixed",
    "researched", "launched", "paused", "abandoned", "scheduled", "drafted", "reviewed", "benchmarked",
    "deployed", "configured", "installed", "tested", "debugged", "sketched", "funded", "joined", "left",
    "recommends", "asked-about", "compared", "measured", "documented", "taught",
]
CONTEXTS = ["engineering", "general", "work", "study", "health", "travel", "finance", "hobby", "family", "cross"]
WORDS = ("signal graph memory sleep decay claim span evidence vector index lexical prose fence batch drain resolve "
         "ledger trailer session harness backend frontend render decode parse serialize cache page bank owner").split()


def git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], text=True, capture_output=True, check=True).stdout


def sentence(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)).capitalize() + "."


def make_episodes(bank: Path, rng: random.Random, n: int, processed: int) -> list[str]:
    from api.services import episode_staging
    from api.services.episode_staging import EpisodeDraft, Turn

    drafts = []
    for i in range(n):
        day = f"2026-{1 + (i * 9) // n:02d}-{1 + i % 28:02d}"
        project = f"{rng.choice(['alpha', 'beta', 'gamma', 'delta', 'epsilon'])}{i % 97}-project"
        tool = f"tool{rng.randrange(400)}"
        turns = []
        for t in range(rng.randint(6, 18)):
            text = sentence(rng, rng.randint(25, 120))
            if t == 0:
                text = f"{project} uses {tool}. " + text
            turns.append(Turn(text=text, speaker="user" if t % 2 == 0 else "assistant",
                              ts=f"{day}T10:{t:02d}:00+00:00"))
        drafts.append(EpisodeDraft(
            title=f"Synthetic conversation {i}", source_id=f"synthetic:{i}", timestamp=f"{day}T10:00:00+00:00",
            original_date=day, source="import", origin="chatgpt", turns=turns,
            extra={"session_id": f"ses_synth_{i:05d}"}, queue_for_sleep=i >= processed,
        ))
    result = episode_staging.stage(drafts, bank / "episodes")
    return [result.episode_ids[d.source_id] for d in drafts]


def claim_dict(rng: random.Random, cid: str, subject: str, objects: list[str], episodes: list[str],
               day: str, closed: bool) -> dict:
    from api.services.claims import Claim, Evidence

    obj = rng.choice(objects)
    pred = rng.choice(PREDICATES)
    eps = rng.sample(episodes, rng.choice((1, 1, 1, 2)))
    evidence = []
    for ep in eps:
        start = rng.randrange(40, 9000)
        evidence.append(Evidence(episode=ep, start=start, end=start + rng.randrange(40, 260), kind="user",
                                 hash=hashlib.sha256(f"{ep}{start}".encode()).hexdigest()[:12]))
    sessions = [f"ses_synth_{rng.randrange(1500):05d}" for _ in range(rng.choice((1, 1, 2, 3)))]
    claim = Claim(
        id=cid, text=f"{subject} {pred} {obj}: " + sentence(rng, rng.randint(8, 22)), subject=subject,
        predicate=pred, object=obj, observer="agent", context=rng.choice(CONTEXTS),
        confidence=round(rng.uniform(0.5, 0.95), 2), valid_from=day, recorded_at=day,
        source_episodes=eps, authored_by=rng.choice(("claude-code", "codex", "cicada")), origin="chatgpt",
        session_id=sessions[0], session_ids=sessions, decayed_through=day, evidence=evidence,
    )
    if closed:
        claim.valid_to = day
        claim.superseded_by = cid + "_next"
    return claim.to_dict()


def render_entries(entries: list[dict]) -> str:
    """One item at a time, so a history of growing fences costs one dump per claim (the concatenation equals
    ``claims._render_claims_block``'s list dump; ``build`` asserts it on the final page)."""
    import yaml
    return "".join(yaml.dump([e], default_flow_style=False, sort_keys=False, allow_unicode=True) for e in entries)


def page_document(fm: dict, prose: str, claims_yaml: str) -> str:
    import yaml
    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
    fence = f"```claims\n{claims_yaml.strip() or '[]'}\n```"
    return f"---\n{fm_str}\n---\n\n{prose.strip()}\n\n{fence}\n"


def entity_fm(eid: str, name: str, kind: str, eps: list[str], related: list[str], day: str) -> dict:
    return {"id": eid, "name": name, "type": kind, "status": "active", "confidence": 0.7, "created": day,
            "last_referenced": day, "decay_rate": 0.02, "decay_class": "active", "source_episodes": eps,
            "tags": ["synthetic"], "related": related, "version": 3, "aliases": [], "mention_weeks": 3}


def prose_for(rng: random.Random, name: str, facts: int, history: int) -> str:
    out = [f"## Summary\n\n{name} — " + sentence(rng, 60), "## Key Facts\n"]
    out += [f"- {sentence(rng, rng.randint(12, 24))}" for _ in range(facts)]
    out.append("\n## History\n")
    out += [f"- **2026-0{1 + h % 9}-{1 + h % 28:02d}**: {sentence(rng, rng.randint(12, 24))}" for h in range(history)]
    return "\n".join(out)


def build(bank: Path, n_claims: int, n_pages: int, n_episodes: int, processed: int, commits: int, seed: int) -> dict:
    isolate.pin_bank(bank)
    from api.services import bank_registry, claims as claims_mod, markdown_parser, owner_identity

    started = time.perf_counter()
    rng = random.Random(seed)
    if bank.exists() and any(bank.iterdir()):
        raise SystemExit(f"{bank} is not empty")
    bank.mkdir(parents=True, exist_ok=True)
    bank_registry.scaffold_bank(bank)
    git(bank, "config", "user.name", "Cicada Scale Probe")
    git(bank, "config", "user.email", "probe@example.com")
    owner_identity.save_owner({"name": OWNER_NAME})
    owner_id, _ = owner_identity.ensure_owner_entity(bank, OWNER_NAME)

    episodes = make_episodes(bank, rng, n_episodes, processed)
    done = episodes[:processed]
    page_ids = [f"{rng.choice(['alpha', 'beta', 'gamma', 'delta', 'tool', 'topic'])}-{i:04d}" for i in range(n_pages)]
    kinds = ["project", "tool", "concept", "person", "company", "location", "skill"]

    # 2,000 other pages: most small, a long tail up to ~60 KB (the next-largest real pages are 46-67 KB).
    for i, eid in enumerate(page_ids):
        n = min(int(rng.paretovariate(1.3) * 3), 90)
        day = f"2026-0{1 + i % 9}-{1 + i % 28:02d}"
        eps = rng.sample(done, min(len(done), 1 + n // 3))
        entries = [claim_dict(rng, f"clm_{eid}_{k:03d}", eid, page_ids, eps, day, rng.random() < 0.2)
                   for k in range(n)]
        fm = entity_fm(eid, eid.replace("-", " ").title(), rng.choice(kinds), eps, rng.sample(page_ids, 3), day)
        (bank / "entities" / f"{eid}.md").write_text(
            page_document(fm, prose_for(rng, eid, 3 + n // 2, 1 + n // 3), render_entries(entries)), encoding="utf-8")

    owner_path = bank / "entities" / f"{owner_id}.md"
    owner = markdown_parser.parse(owner_path)
    owner_fm = dict(owner.frontmatter)
    owner_fm.update({"source_episodes": done, "related": page_ids[:250],
                     "aliases": [f"alias-{k}" for k in range(12)]})
    owner_prose = prose_for(rng, OWNER_NAME, 320, 160)
    owner_entries = []
    for k in range(n_claims):
        day = f"2026-0{1 + (k * 9) // n_claims}-{1 + k % 28:02d}"
        owner_entries.append(claim_dict(rng, f"clm_{day}_{k:05d}", owner_id, page_ids, done, day, rng.random() < 0.3))
    rendered = [render_entries([e]) for e in owner_entries]

    git(bank, "add", "-A")
    git(bank, "commit", "-q", "-m", "Synthetic seed\n\nCicada-Author: cicada")
    # The owner page grows through `commits` Sleep batches, each one rewriting the whole file and touching ~60 other
    # pages' frontmatter, with a manifest body like a real Sleep commit.
    per = max(1, n_claims // commits)
    for c in range(commits):
        upto = n_claims if c == commits - 1 else per * (c + 1)
        owner_fm["last_referenced"] = f"2026-09-{1 + c % 28:02d}"
        owner_path.write_text(page_document(owner_fm, owner_prose, "".join(rendered[:upto])), encoding="utf-8")
        touched = rng.sample(page_ids, 60)
        for eid in touched:
            p = bank / "entities" / f"{eid}.md"
            text = p.read_text(encoding="utf-8")
            p.write_text(text.replace("mention_weeks: ", f"mention_weeks: {c}", 1) if c == 0 else
                         text.replace(f"mention_weeks: {c - 1}", f"mention_weeks: {c}", 1), encoding="utf-8")
        body = "\n".join(f"- {eid}: updated (sessions: ses_synth_{rng.randrange(1500):05d})"
                         for eid in [owner_id, *touched])
        message = (f"Sleep cycle sleep_synth_{c:03d}: 25 episodes\n\n{body}\n\nCicada-Author: claude-code\n"
                   f"Cicada-Engine: deterministic\nCicada-Session: ses_synth_{c:05d}")
        git(bank, "add", "-A")
        git(bank, "commit", "-q", "-m", message)

    # The incremental rendering is byte-identical to the production writer's.
    final = owner_path.read_text(encoding="utf-8")
    parsed = markdown_parser.parse(owner_path)
    production = claims_mod.write_claims(claims_mod.strip_claims_block(parsed.body),
                                         claims_mod.parse_claims(parsed.body, strict=True))
    assert claims_mod.strip_claims_block(production) == claims_mod.strip_claims_block(parsed.body)
    assert claims_mod._render_claims_block(claims_mod.parse_claims(parsed.body)) in production
    assert claims_mod._render_claims_block(claims_mod.parse_claims(parsed.body)) in final, "render drift"
    fm_end = final.index("\n---\n", 4) + 5
    fence = final.index("```claims")
    return {"bank": str(bank), "owner_id": owner_id, "owner_bytes": len(final.encode()),
            "owner_lines": final.count("\n"), "frontmatter_bytes": fm_end, "prose_bytes": fence - fm_end,
            "fence_bytes": len(final) - fence, "owner_claims": n_claims, "pages": n_pages + 1,
            "episodes": n_episodes, "processed": processed, "owner_commits": commits,
            "build_seconds": round(time.perf_counter() - started, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--claims", type=int, default=3500)
    ap.add_argument("--pages", type=int, default=2000)
    ap.add_argument("--episodes", type=int, default=1500)
    ap.add_argument("--processed", type=int, default=975)
    ap.add_argument("--commits", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    import json
    print(json.dumps(build(a.bank.resolve(), a.claims, a.pages, a.episodes, a.processed, a.commits, a.seed)))


if __name__ == "__main__":
    main()
