"""One fact said in many conversations, under many names: what a page's Key Facts hold (G148, owner report 2026-11-23).

Run: python -m benchmarks.system.fact_fold_eval --scratch <new-empty-directory> [--scenario artist|page|big|pairs] [--variants dev,links,fold,heal] [--model haiku]

Seven invented conversations each say something about one artist, five of them the same fact ("the partner's favourite
artist") worded differently — under the partner's name, her alias, a nickname, the owner's relation to her, a
translation. The recorded Stage-1 answer of each (invented names only) goes through the production Stage 3
(`conflict_resolver.resolve_and_prune`) and Stage 5's writer (`apply_changes`) in a scratch bank, in order, and the
artist's Key Facts are read after the last.

Variants: ``dev`` (nothing: how a page was written before), ``links`` (`link_names`: a link in new text is written under
the page's own name), ``fold`` (+ `fact_fold`: Sleep's small judge on the Claude plan, ``--model`` its tier; one ask and
one check per page per conversation, so at most 12 calls here), ``raw`` (the fold alone, links left as written: a page as
it was before #791). ``dev`` and ``links`` call no model.

Variant ``heal`` (`fact_fold_heal`): the page is written as ``links`` writes it (no fold), then healed in place — planned with
the judge (`--model`, `--chunk` new lines an ask) and applied from the plan, no model — and reported before and after with the
calls the plan made and, per fold, what of the dropped line (a number, a name, a link) is missing from the kept one,
checked by a reader that shares no code with the guard. Scenario ``big``: one invented page of 60+ bullets, six facts each
said four or five ways spread across it and the rest one-off, so the 40-line cap of an ask is exercised. Scenario ``pairs``: the invented pairs as
two-bullet pages through the heal (false folds and missed folds).

Scenario ``page`` (review 2026-11-23, the reported page rebuilt with invented names): an artist page that relates to the
owner's partner, sixteen conversations each saying one line, the partner named every way (a link under her name, under an
alias, an unresolved `[[<owner>'s girlfriend]]`, a nickname, "<owner>'s girlfriend's", "<owner>'s partner's"). Reported:
Key Facts left, the facts that must stay (the favourite-artist fact, the two vinyl options, the planned gift, that he is a
musician), and the conversations whose source rows are on a kept line (all 16 must be).

Reported: Key Facts on the page, how many restate the favourite-artist fact, near-duplicate pairs (the page-quality
eval's own measure, `page_quality.near_duplicate`), the facts the conversations gave that are no longer on the page
(each has a marker that must survive: a date, a number, a name), the sources each marker keeps, and calls by stage."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from benchmarks.system.page_quality import near_duplicate

OWNER, PARTNER, ARTIST = "Owner Example", "Alice Example", "Artist Example"

#: Each conversation's recorded extraction for the artist page, in order. The fact "favourite of the partner" appears in
#: 1, 2, 3, 4, 5, 6 and 7; the others are one-off facts whose marker must stay on the page.
CONVERSATIONS = [
    ("ep_2026-11-01_001", [f"Favourite artist of [[{PARTNER}]]"]),
    ("ep_2026-11-03_001", ["Favorite artist of [[Girlfriend]]", "Toured Europe in 2025"]),
    ("ep_2026-11-05_001", ["Musical artist who is the favorite of [[Ally]].",
                           f"{OWNER} planned to buy one of his records as a gift."]),
    ("ep_2026-11-08_001", [f"{OWNER}'s girlfriend's favourite artist.", "Debut album released in 2019"]),
    ("ep_2026-11-12_001", [f"[[{OWNER}'s girlfriend]]'s favourite artist is {ARTIST}.",
                           f"{OWNER} plans to buy a vinyl copy for her birthday on 19 March"]),
    ("ep_2026-11-15_001", [f"Es el artista favorito de [[{PARTNER}]]", "Giró por Europa en 2025"]),
    ("ep_2026-11-19_001", ["Is [[Girlfriend]]'s favourite artist, noted in the gift guide.", "Won a Grammy in 2024"]),
]
#: The reported page: (episode, the one line that conversation brought).
PAGE_ARTIST, PAGE_OWNER, PAGE_PARTNER = "Sam Rivers", "Alex Example", "Mira Lund"
PAGE_LINES = [
    "Favourite artist of [[Alex's girlfriend]]",
    "Vinyl options suggested were Blue Hour or Low Tide",
    "Favorite artist of [[Mira Lund]]",
    "Musical artist who is the favorite of [[Mira Lund]].",
    "Alex's girlfriend's favourite artist.",
    "Sam Rivers is [[Alex's girlfriend]]'s favourite artist. Alex planned to buy one of his vinyl records as a gift.",
    "[[Mira Lund]]'s favourite artist is Sam Rivers.",
    "Is [[Girlfriend]]'s favourite artist",
    "A singer who is [[Girlfriend]]'s favourite artist, noted in Alex's gift guide.",
    "Sam Rivers is a musician who is Alex's girlfriend's favourite artist, according to the guide.",
    "Is [[Pip]]'s favorite artist.",
    "Sam Rivers is Alex's partner's favourite artist.",
    "Sam Rivers is a musician who is Alex's partner's favourite artist.",
    "Sam Rivers is a musical artist and is [[Pip]]'s favorite artist, according to Alex's gift notes.",
    "Sam Rivers is Pip's favorite artist.",
    "Sam Rivers is a musical artist and Pip's favorite artist, as noted in Alex's gift list.",
]
PAGE_CONVERSATIONS = [(f"ep_2026-11-{i + 1:02d}_001", [line]) for i, line in enumerate(PAGE_LINES)]
PAGE_MARKERS = {"vinyl_blue_hour": r"Blue Hour", "vinyl_low_tide": r"Low Tide", "gift_plan": r"planned to buy",
                "musician": r"musician|singer|musical artist"}

#: A long page: facts said several ways, spread through 60+ bullets (invented names only).
BIG_OWNER, BIG_PAGE = "Casey Park", "Taylor Brooks"
BIG_GROUPS = [
    ["Works as a data engineer at Northwind Labs", "Data engineer at Northwind Labs",
     "Taylor is employed by Northwind Labs as a data engineer", "Is a data engineer working at Northwind Labs.",
     "Northwind Labs employs Taylor as a data engineer"],
    ["Lives in Lisbon since March 2023", "Has lived in Lisbon since March 2023", "Moved to Lisbon in March 2023",
     "Based in Lisbon, living there since March 2023."],
    ["Plays the cello", "Plays the cello in an amateur orchestra", "Is a cellist", "Taylor plays the cello",
     "Plays cello in an amateur orchestra every Tuesday"],
    ["Is allergic to peanuts", "Has a peanut allergy", "Taylor is allergic to peanuts and carries an epinephrine pen"],
    ["Has a sister named Mara", "Taylor's sister is called Mara", "Mara is Taylor's sister",
     "Their sister Mara lives in Porto"],
    ["Runs the Lisbon marathon every October", "Runs a marathon each October", "Runs the Lisbon marathon each October."],
    ["Uses Neovim as an editor", "Taylor's editor is Neovim", "Writes code in Neovim"],
    ["Has been vegetarian since 2019", "Is vegetarian, since 2019", "Vegetarian since 2019"],
]
BIG_UNIQUE = [
    "Has a cat named Biscuit", "Drinks 3 coffees a day", "Birthday is 14 June", "Reads about 40 books a year",
    "Learning Portuguese since January 2024", "Owns a 2015 Honda Civic", "Prefers tea in the evening",
    "Studied physics at Oakfield University", "Started the job in September 2021", "Favourite film is Blue Harbor",
    "Plays chess on weekends", "Has visited 23 countries", "Wants to learn the viola in 2027",
    "Keeps a sourdough starter named Gus", "Sleeps about 7 hours a night", "Has a standing desk since 2022",
    "Volunteers at the Alfama food bank on Saturdays", "Is training for a 10 km race in May",
    "Dislikes cilantro", "Collects vintage keyboards, owns 12", "Gave a talk at DataConf in 2024",
    "Has a brother-in-law called Eli", "Cycles 15 km to the office on Mondays", "Grows tomatoes on the balcony",
    "Subscribes to 5 newsletters about databases", "Speaks English, Portuguese and Polish",
    "Is saving for a trip to Kyoto in April", "Prefers window seats on flights", "Has never owned a television",
    "Takes a weekly pottery class on Thursdays", "Wears glasses since age 9", "Painted the flat green in 2024",
    "Has an annual fitness test every February", "Keeps a paper notebook for ideas",
]
#: One distinguishing detail per group and per one-off fact: each must still be on the healed page.
BIG_MARKERS = {**{f"group{i}": m for i, m in enumerate(
    [r"Northwind Labs", r"March 2023", r"Tuesday|amateur orchestra", r"epinephrine", r"Porto", r"Lisbon marathon|October",
     r"Neovim", r"2019"])},
    **{f"one{i}": re.escape(t.split()[-1]) for i, t in enumerate(BIG_UNIQUE)}}


def _big_conversations() -> list:
    import random

    lines = [line for group in BIG_GROUPS for line in group] + BIG_UNIQUE
    random.Random(7).shuffle(lines)
    return [(f"ep_2026-{1 + i // 28:02d}-{1 + i % 28:02d}_001", [line]) for i, line in enumerate(lines)]


#: What must still be on the page after the last conversation.
MARKERS = {"tour": r"2025|Europa", "debut": r"2019", "grammy": r"Grammy", "birthday": r"19 March", "gift": r"gift"}
FAVOURITE = re.compile(r"favou?rite|favorito", re.I)


def _entity(facts, episode, name=ARTIST):
    from api.services import section_provenance

    entity = {"name": name, "type": "person", "summary": "", "key_facts": list(facts), "aliases": []}
    section_provenance.attach(entity, episode, "the conversation")
    return entity


def _pages(bank: Path) -> list[dict]:
    from api.services import markdown_parser

    out = []
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        out.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    return out


def run_variant(variant: str, scratch: Path, model: str, scenario: str = "artist", chunk: int | None = None) -> dict:
    from api.config import Settings
    from api.services import conflict_resolver as cr
    from api.services import fact_fold, link_names, markdown_parser, section_provenance

    bank = scratch / variant / "bank"
    (bank / "entities").mkdir(parents=True)
    base = {"type": "person", "status": "active", "confidence": 0.8, "source_episodes": ["ep_2026-10-01_001"]}
    page = scenario == "page"
    big = scenario == "big"
    owner, artist, conversations = ((PAGE_OWNER, PAGE_ARTIST, PAGE_CONVERSATIONS) if page else
                                    (BIG_OWNER, BIG_PAGE, _big_conversations()) if big else (OWNER, ARTIST, CONVERSATIONS))
    partner = PAGE_PARTNER if page else PARTNER
    artist_id = artist.lower().replace(" ", "-")
    markdown_parser.write(bank / "entities" / "owner-example.md", {**base, "name": owner, "owner": True, "aliases": []},
                          "## Summary\nThe person this memory belongs to.\n")
    partner_aliases = (["girlfriend", "gf", "partner", "his girlfriend", "Pip"] if page
                       else ["Girlfriend", "Ally", f"{owner}'s girlfriend"])
    partner_id = partner.lower().replace(" ", "-")
    markdown_parser.write(bank / "entities" / f"{partner_id}.md", {**base, "name": partner, "aliases": partner_aliases},
                          "## Summary\nThe owner's partner.\n")
    settings = Settings(_env_file=None, llm_mode="agent", agent_model=model, agent_disambiguation_model=model,
                        CICADA_MEMORY_PATH=str(bank))
    judge = fact_fold.judge_for(settings) if variant in ("fold", "raw") else None
    calls = {"n": 0}
    if judge is not None:
        inner = judge

        def counting(prompt: str) -> dict:
            calls["n"] += 1
            return inner(prompt)
        judge = counting
    original = link_names.rewrite_changes
    if variant in ("dev", "raw"):
        link_names.rewrite_changes = lambda changes, names: 0
    try:
        for i, (episode, facts) in enumerate(conversations):
            change = {"id": artist_id, "action": "create" if i == 0 else "update", "source_episode": episode,
                      "entity": _entity(facts, episode, artist)}
            if i == 0:
                cr.apply_changes([change], bank)
                if page:   # the page relates to her and to the owner: what a page about a gift for her has
                    parsed = markdown_parser.parse(bank / "entities" / f"{artist_id}.md")
                    markdown_parser.write(bank / "entities" / f"{artist_id}.md",
                                          {**parsed.frontmatter, "related": [partner_id, "owner-example"]}, parsed.body)
                continue
            out = asyncio.run(cr.resolve_and_prune([change], _pages(bank), settings, decay=False,
                                                   now=datetime(2026, 11, 20), fact_judge=judge))
            cr.apply_changes(out, bank)
    finally:
        link_names.rewrite_changes = original
    healed = None
    if variant == "heal":
        healed = _heal(bank, artist_id, owner, model, chunk)
    parsed = markdown_parser.parse(bank / "entities" / f"{artist_id}.md")
    scanned = section_provenance.scan(parsed.body).get("key_facts", [])
    facts = [i.text for i in scanned]
    proof = section_provenance.matched(parsed.frontmatter, parsed.body).get("key_facts", {})
    pairs = sum(near_duplicate(a, b) for k, a in enumerate(facts) for b in facts[k + 1:])
    favourite = [f for f in facts if FAVOURITE.search(f)]
    markers = PAGE_MARKERS if page else BIG_MARKERS if big else MARKERS
    lost = [name for name, pattern in markers.items() if not any(re.search(pattern, f) for f in facts)]
    if (page or big) and not favourite and page:
        lost.append("favourite_artist")
    sources = {item.text: sorted({ev.episode for ev in proof.get(item.key, (None, []))[1]}) for item in scanned}
    fav_sources = sorted({ep for f in favourite for ep in sources.get(f, [])})
    kept_sources = sorted({ep for eps in sources.values() for ep in eps})
    return {"variant": variant, "scenario": scenario, "conversations_kept": len(kept_sources),
            "conversations_total": len(conversations), "key_facts": len(facts), "favourite_bullets": len(favourite),
            "near_duplicate_pairs": pairs, "markers_lost": lost, "favourite_sources": len(fav_sources),
            "judge_calls": calls["n"], "facts": facts, **(healed or {})}


def _plain(text: str) -> str:
    return re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)


def _missing(drop: str, keep: str, same: set[str]) -> list[str]:
    """What of ``drop`` (a number, a name, a link) is not in ``keep``. Shares no code with the guard; ``same``: spellings
    (lower case) of one neighbour or of the page itself, each read as the one name ``@``."""
    def canon(text: str) -> str:
        text = _plain(text).replace("\u2019", "'")
        for spelling in sorted(same, key=len, reverse=True):
            text = re.sub(r"(?<![\w])" + re.escape(spelling) + r"(?:'s)?(?![\w])", "@", text, flags=re.I)
        return text

    d, k = canon(drop), canon(keep)
    out = [n for n in re.findall(r"\d+", d) if n not in re.findall(r"\d+", k)]
    names = [w for i, w in enumerate(re.findall(r"[^\W\d_][\w'-]*", d)) if i and w[:1].isupper()]
    out += [n for n in names if n.lower() not in k.lower()]
    out += [f"link:{m}" for m in re.findall(r"\[\[([^\]|]+)", drop)
            if m.lower() not in keep.lower() and m.lower() not in same]
    return out


def _heal(bank: Path, page_id: str, owner: str, model: str, chunk: int | None) -> dict:
    """Plan the page with the judge, apply the plan with none, and report (see the module)."""
    from api.config import Settings
    from api.services import fact_fold, fact_fold_heal as heal, link_names, markdown_parser

    parsed = markdown_parser.parse(bank / "entities" / f"{page_id}.md")
    pages = _pages(bank)
    names = link_names.Names(pages)
    settings = Settings(_env_file=None, llm_mode="agent", agent_model=model, agent_disambiguation_model=model,
                        CICADA_MEMORY_PATH=str(bank))
    judge = fact_fold.judge_for(settings)
    read = heal.read_page(page_id, parsed.frontmatter, parsed.body)
    if read.skip:
        return {"heal_skipped": read.skip}
    meter = heal.Meter()
    row = heal.plan_page(read, names, owner, judge, meter, chunk=chunk or heal.CHUNK)
    same: set[str] = set()
    for p in pages:   # every spelling of the partner and the owner reads as one name (the eval's own table)
        fm = p["frontmatter"]
        if fm.get("owner") or p["id"] != page_id and fm.get("type") == "person":
            forms = [fm.get("name"), *(fm.get("aliases") or [])]
            same |= {str(x).lower() for x in forms if x}
            if not fm.get("owner"):   # "<owner>'s girlfriend": an alias with the owner's possessive
                same |= {f"{who}'s {a}".lower() for a in (fm.get("aliases") or []) for who in (owner, owner.split()[0])}
    same |= {owner.lower(), owner.split()[0].lower(), page_id.replace("-", " ")}
    same |= {w.lower() for w in re.findall(r"\w+", page_id)} - {"a", "of"}
    lost = {f["id"]: m for f in row["folds"] if (m := _missing(f["drop"], f["into"], same))}
    import json as _json

    (bank.parent / "heal_row.json").write_text(_json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    result = heal.apply(bank, [row], sleep_running=lambda: False, names=names, owner=owner)
    return {"heal_before": row["before"], "heal_after": row["after"], "heal_calls": row["calls"], "heal_status": row["status"],
            "heal_folds": len(row["folds"]), "heal_refused": len(row["refused"]), "heal_lost_per_fold": lost,
            "heal_apply": result.counts(), "heal_rows": row}


def pairs_heal(scratch: Path, model: str, chunk: int | None) -> dict:
    """The invented pairs (`tests/fixtures/fact_fold_pairs.json`) as two-bullet pages, planned by the heal: a pair a person
    would keep that loses a bullet is a false fold, one they would let go that loses none is a miss. A page a write already
    folds by rule (a shorter line a longer one extends) counts as folded."""
    from api.config import Settings
    from api.services import conflict_resolver as cr
    from api.services import fact_fold, fact_fold_heal as heal, link_names, markdown_parser

    pairs = json.loads((Path(__file__).resolve().parents[2] / "api/tests/fixtures/fact_fold_pairs.json")
                       .read_text(encoding="utf-8"))["pairs"]
    base = {"type": "person", "status": "active", "confidence": 0.8, "source_episodes": ["ep_2026-10-01_001"]}
    calls = older_into_new = 0
    false_ids, missed_ids, blind_ids = [], [], []
    for pair in pairs:
        bank = scratch / "pairs" / pair["id"] / "bank"
        (bank / "entities").mkdir(parents=True)
        owner = pair.get("owner")
        if owner:
            markdown_parser.write(bank / "entities" / "owner.md", {**base, "name": owner, "owner": True, "aliases": []},
                                  "## Summary\nOwner.\n")
        linked = {**(pair.get("names") or {}), **(pair.get("related") or {})}
        for name, aliases in linked.items():
            markdown_parser.write(bank / "entities" / (re.sub(r"\W+", "-", name.lower()).strip("-") + ".md"),
                                  {**base, "name": name, "aliases": list(aliases)}, "## Summary\nA neighbour.\n")
        change = {"id": "page-example", "action": "create", "source_episode": "ep_2026-11-01_001",
                  "entity": _entity([pair["keep"], pair["drop"]], "ep_2026-11-01_001", "Page Example")}
        cr.apply_changes([change], bank)
        path = bank / "entities" / "page-example.md"
        parsed = markdown_parser.parse(path)
        related = [re.sub(r"\W+", "-", n.lower()).strip("-") for n in (pair.get("related") or {})]
        if related:
            markdown_parser.write(path, {**parsed.frontmatter, "related": related, "aliases": list(pair.get("own") or [])},
                                  parsed.body)
            parsed = markdown_parser.parse(path)
        read = heal.read_page("page-example", parsed.frontmatter, parsed.body)
        if read.skip == "few_facts":
            folded = True   # the writer's own rule folded it on creation
        else:
            settings = Settings(_env_file=None, llm_mode="agent", agent_model=model, agent_disambiguation_model=model,
                                CICADA_MEMORY_PATH=str(bank))
            meter = heal.Meter()
            row = heal.plan_page(read, link_names.Names(_pages(bank)), owner, fact_fold.judge_for(settings), meter,
                                 chunk=chunk or heal.CHUNK)
            calls += meter.total
            # The new fact going is the fold under test; the page's older bullet replaced by a fuller new fact loses
            # nothing the new one does not say (checked here by `_missing`), and is not one.
            older = [f for f in row["folds"] if f["drop"] == pair["keep"]]
            if not pair["fold"] and any(_missing(f["drop"], f["into"], set()) for f in older):
                false_ids.append(pair["id"] + "(older line lost something)")
            older_into_new += len(older)
            folded = any(f["drop"] == pair["drop"] for f in row["folds"]) or (pair["fold"] and bool(older))
        if folded and not pair["fold"]:
            (blind_ids if pair.get("blind") else false_ids).append(pair["id"])
        if not folded and pair["fold"]:
            missed_ids.append(pair["id"])
    return {"variant": "heal-pairs", "pairs": len(pairs), "must_not_fold": sum(not p["fold"] for p in pairs),
            "false_folds": len(false_ids), "false_ids": false_ids, "false_folds_blind_to_code": len(blind_ids),
            "blind_ids": blind_ids, "must_fold": sum(p["fold"] for p in pairs), "missed": len(missed_ids),
            "missed_ids": missed_ids, "older_bullet_into_a_fuller_new_one": older_into_new, "calls": calls}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scratch", required=True, type=Path, help="a new, empty directory (nothing real is read)")
    ap.add_argument("--scenario", choices=["artist", "page", "big", "pairs"], default="artist")
    ap.add_argument("--chunk", type=int, default=None, help="heal: new lines per ask")
    ap.add_argument("--variants", default="dev,links,fold")
    ap.add_argument("--model", default="haiku")
    args = ap.parse_args(argv)
    if args.scratch.exists() and any(args.scratch.iterdir()):
        ap.error("--scratch must be new or empty")
    args.scratch.mkdir(parents=True, exist_ok=True)
    os.environ.update({"CICADA_HOME": str(args.scratch / "home"), "CICADA_CAPTURE": "off", "CICADA_RECALL": "off",
                       "CICADA_TELEMETRY": "off", "CICADA_ALLOW_CONNECTOR_FETCH": "off"})
    if args.scenario == "pairs":
        print(json.dumps(pairs_heal(args.scratch, args.model, args.chunk)))
        return 0
    rows = [run_variant(v, args.scratch, args.model, args.scenario, args.chunk) for v in args.variants.split(",")]
    for row in rows:
        print(json.dumps({k: v for k, v in row.items() if k not in ("facts", "heal_rows")}))
    for row in rows:
        print(f"\n[{row['variant']}] Key Facts:")
        for fact in row["facts"]:
            print(f"  - {fact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
