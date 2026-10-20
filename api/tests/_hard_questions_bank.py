"""A small synthetic bank with every shape ``benchmarks/hard_questions`` samples: a superseded value, one subject in
two conversations months apart, a link from one page to another with each side evidenced in its own conversation, a
subject in 3+ conversations, dated events, a Spanish-language thread, plus an owner page and a saved link that must
never be sampled. Placeholder names only; nothing reads a real bank. Never collected by pytest (underscore prefix);
the live run in the PR built its bank with :func:`build`."""
from __future__ import annotations

from pathlib import Path

from api.services import evidence, markdown_parser
from api.services.claims import Claim, Evidence, write_claims

# (id, timestamp, title, body)
EPISODES = [
    ("ep_2026-03-02_001", "2026-03-02T10:00:00Z", "Choosing a store for alpha-project",
     "user: For alpha-project I'm going with sqlite-example as the database, it is enough for one writer.\n"
     "assistant: Makes sense for a single-writer prototype."),
    ("ep_2026-06-10_001", "2026-06-10T09:30:00Z", "alpha-project migration",
     "user: We moved alpha-project from sqlite-example to postgres-example because of concurrent writes from the "
     "sync workers.\nassistant: Good call; the write lock was the bottleneck."),
    ("ep_2026-08-01_001", "2026-08-01T16:00:00Z", "alpha-project demo date",
     "user: The alpha-project demo is now on September 30, and carol-example will present the dashboard.\n"
     "assistant: Noted the date and the presenter."),
    ("ep_2026-02-14_001", "2026-02-14T12:00:00Z", "Catching up",
     "user: carol-example joined beta-lab as a researcher this week.\nassistant: Congratulations to her."),
    ("ep_2026-07-20_001", "2026-07-20T18:00:00Z", "beta-lab news",
     "user: carol-example now leads the vision team at beta-lab.\nassistant: A fast promotion."),
    ("ep_2026-05-05_001", "2026-05-05T08:00:00Z", "Visiting beta-lab",
     "user: beta-lab is located in city-a, in the old harbour district.\nassistant: Easy to reach by train."),
    ("ep_2026-04-03_001", "2026-04-03T20:00:00Z", "garden-sensor board",
     "user: I soldered the first garden-sensor board tonight.\nassistant: First board done!"),
    ("ep_2026-05-18_001", "2026-05-18T19:00:00Z", "garden-sensor deploy",
     "user: Deployed three garden-sensor units in the back garden today.\nassistant: Three units live."),
    ("ep_2026-05-02_001", "2026-05-02T19:00:00Z", "Escalada",
     "user: Hoy fui a escalar a rocodromo-example y hice mi primer 6a.\nassistant: ¡Enhorabuena por el 6a!"),
    ("ep_2026-07-11_001", "2026-07-11T19:00:00Z", "Escalada otra vez",
     "user: Volví a rocodromo-example; ya encadeno vías de 6b.\nassistant: Buen progreso."),
    ("ep_2026-09-03_001", "2026-09-03T19:00:00Z", "Mejor marca",
     "user: Mi mejor marca en rocodromo-example ahora es 6c.\nassistant: ¡Un 6c!"),
    ("ep_2026-09-04_001", "2026-09-04T10:00:00Z", "Saved a link",
     "user: saved https://example.com/a-video"),
]

# (id, name, type, extra frontmatter, [(claim id, text, subject, predicate, object, object_kind, valid_from,
#   valid_to, superseded_by, episode, quote, extra claim fields)])
PAGES = [
    ("alpha-project", "alpha-project", "project", {}, [
        ("c-a1", "alpha-project uses sqlite-example", "alpha-project", "uses", "sqlite-example", "node",
         "2026-03-02", "2026-06-10", "c-a2", "ep_2026-03-02_001", "going with sqlite-example as the database", {}),
        ("c-a2", "alpha-project uses postgres-example", "alpha-project", "uses", "postgres-example", "node",
         "2026-06-10", None, None, "ep_2026-06-10_001", "moved alpha-project from sqlite-example to postgres-example",
         {"supersedes": "c-a1"}),
        ("c-a3", "alpha-project demo is on 2026-09-30", "alpha-project", "due", "2026-09-30", "literal",
         "2026-08-01", None, None, "ep_2026-08-01_001", "demo is now on September 30", {}),
    ]),
    ("carol-example", "carol-example", "person", {}, [
        ("c-c1", "carol-example works at beta-lab", "carol-example", "works-at", "beta-lab", "node",
         "2026-02-14", None, None, "ep_2026-02-14_001", "carol-example joined beta-lab as a researcher", {}),
        ("c-c2", "carol-example leads the vision team at beta-lab", "carol-example", "role", "vision team lead",
         "literal", "2026-07-20", None, None, "ep_2026-07-20_001", "now leads the vision team", {}),
    ]),
    ("beta-lab", "beta-lab", "organization", {}, [
        ("c-b1", "beta-lab is located in city-a", "beta-lab", "located-in", "city-a", "literal",
         "2026-05-05", None, None, "ep_2026-05-05_001", "beta-lab is located in city-a", {}),
    ]),
    ("garden-sensor", "garden-sensor", "project", {}, [
        ("c-g1", "Soldered the first garden-sensor board", "garden-sensor", "happened", "first board", "literal",
         "2026-04-03", "2026-04-03", None, "ep_2026-04-03_001", "soldered the first garden-sensor board",
         {"status": "done"}),
        ("c-g2", "Deployed three garden-sensor units", "garden-sensor", "happened", "three units deployed", "literal",
         "2026-05-18", "2026-05-18", None, "ep_2026-05-18_001", "Deployed three garden-sensor units",
         {"status": "done"}),
    ]),
    ("rocodromo-example", "rocodromo-example", "place", {}, [
        ("c-r1", "Mejor grado en rocodromo-example: 6a", "rocodromo-example", "value-of-best-grade", "6a", "literal",
         "2026-05-02", "2026-07-11", "c-r2", "ep_2026-05-02_001", "hice mi primer 6a", {}),
        ("c-r2", "Mejor grado en rocodromo-example: 6b", "rocodromo-example", "value-of-best-grade", "6b", "literal",
         "2026-07-11", "2026-09-03", "c-r3", "ep_2026-07-11_001", "ya encadeno vías de 6b", {"supersedes": "c-r1"}),
        ("c-r3", "Mejor grado en rocodromo-example: 6c", "rocodromo-example", "value-of-best-grade", "6c", "literal",
         "2026-09-03", None, None, "ep_2026-09-03_001", "Mi mejor marca en rocodromo-example ahora es 6c",
         {"supersedes": "c-r2"}),
    ]),
    ("bob-example", "bob-example", "person", {"owner": True}, [
        ("c-o1", "bob-example works on alpha-project", "bob-example", "works-on", "alpha-project", "node",
         "2026-03-02", None, None, "ep_2026-03-02_001", "For alpha-project", {}),
    ]),
    ("a-video", "A video", "media", {}, [
        ("c-m1", "A video was saved", "a-video", "saved", "example.com", "literal", "2026-09-04", None, None,
         "ep_2026-09-04_001", "saved https://example.com/a-video", {}),
    ]),
]


def write_episode(bank: Path, eid: str, ts: str, title: str, body: str, **extra) -> str:
    """One episode file (``extra`` lands in its frontmatter: ``origin``, ``url``, ``project_dir``…); its parsed body."""
    path = bank / "episodes" / f"{eid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, {"id": eid, "timestamp": ts, "title": title, "source": "claude_code",
                                 "processed": True, **extra}, body)
    return markdown_parser.parse(path).body


def write_page(bank: Path, pid: str, name: str, etype: str, extra: dict, rows: list) -> None:
    """One entity page whose claims are ``rows`` (the ``PAGES`` row shape), each with an evidence span located in
    its episode's body."""
    claims = []
    for (cid, text, subj, pred, obj, okind, vfrom, vto, sup_by, ep, quote, more) in rows:
        body = markdown_parser.parse(bank / "episodes" / f"{ep}.md").body
        at = body.find(quote)
        assert at >= 0, (cid, quote)
        ev = Evidence(episode=ep, start=at, end=at + len(quote), kind="user", hash=evidence.body_hash(body))
        claims.append(Claim(id=cid, text=text, subject=subj, predicate=pred, object=obj, object_kind=okind,
                            valid_from=vfrom, valid_to=vto, superseded_by=sup_by, recorded_at=vfrom,
                            source_episodes=[ep], evidence=[ev], **more))
    fm = {"name": name, "type": etype, "status": "active", "confidence": 0.7, "created": "2026-01-01",
          "source_episodes": sorted({r[9] for r in rows}), "aliases": [], **extra}
    prose = f"## Summary\n{name} is a synthetic fixture page.\n"
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(bank / "entities" / f"{pid}.md", fm, write_claims(prose, claims))


def build(bank: Path) -> Path:
    """Write the bank under ``bank`` (entities/ and episodes/) and return it."""
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    for eid, ts, title, body in EPISODES:
        write_episode(bank, eid, ts, title, body)
    for pid, name, etype, extra, rows in PAGES:
        write_page(bank, pid, name, etype, extra, rows)
    return bank
