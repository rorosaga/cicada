"""The one-time heal of repeated facts (`fact_fold_heal`, G148). Invented names; a scripted judge, no model.

What matters: the plan replays a page in small asks and costs nothing where nothing resembles anything; every fold passes
the live guard whatever the judge says; a bullet no G118 row proves Sleep wrote, a pinned one and a person's page are never
touched; apply writes exactly the plan (sources moved, everything else byte for byte), skips a page that changed and
never calls a model; one `cicada` commit, undone by a plain revert."""
import asyncio
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from api.config import Settings
from api.services import conflict_resolver as cr
from api.services import (
    demo_guard, fact_fold, fact_fold_heal as heal, link_names, markdown_parser, section_provenance,
)

PAGE = "taylor-brooks"


def _entity(facts, episode, name="Taylor Brooks"):
    entity = {"name": name, "type": "person", "summary": "", "key_facts": list(facts), "aliases": []}
    section_provenance.attach(entity, episode, "the conversation")
    return entity


def _bank(tmp_path: Path, conversations, *, git=False) -> Path:
    """A bank whose page was written conversation by conversation, as Sleep writes it (rows and all)."""
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    settings = Settings(_env_file=None, llm_mode="agent", agent_model="haiku", agent_disambiguation_model="haiku",
                        CICADA_MEMORY_PATH=str(bank))
    for i, (episode, facts) in enumerate(conversations):
        change = {"id": PAGE, "action": "create" if i == 0 else "update", "source_episode": episode,
                  "entity": _entity(facts, episode)}
        if i == 0:
            cr.apply_changes([change], bank)
            continue
        pages = [_page(bank, p) for p in sorted((bank / "entities").glob("*.md"))]
        out = asyncio.run(cr.resolve_and_prune([change], pages, settings, decay=False, now=datetime(2026, 11, 20)))
        cr.apply_changes(out, bank)
    if git:
        for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"],
                    ["add", "-A"], ["commit", "-qm", "seed"]):
            subprocess.run(["git", *cmd], cwd=bank, check=True, capture_output=True)
    return bank


def _page(bank, path):
    parsed = markdown_parser.parse(path)
    return {"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body}


def _convs(facts):
    return [(f"ep_2026-11-{i + 1:02d}_001", [f]) for i, f in enumerate(facts)]


def _read(bank, **kw):
    p = _page(bank, bank / "entities" / f"{PAGE}.md")
    return heal.read_page(PAGE, p["frontmatter"], p["body"], **kw), p


def _names(bank):
    return link_names.Names([_page(bank, p) for p in sorted((bank / "entities").glob("*.md"))])


class Judge:
    """Says what is told: ``pairs`` maps a line's text to the text of the line that says it in full; the check agrees."""

    def __init__(self, pairs=None, *, everything=False, miss_first=()):
        self.pairs, self.everything = dict(pairs or {}), everything
        self.miss_first, self.seen = set(miss_first), set()   # drops the judge overlooks the first time it is shown one
        self.asks = self.checks = 0
        self.shown: list[int] = []

    def __call__(self, prompt: str) -> dict:
        if "LINES:" not in prompt:
            self.checks += 1
            n = prompt.count("DROP:")
            return {"pairs": [{"pair": i, "missing": [], "same": True} for i in range(1, n + 1)]}
        self.asks += 1
        rows = [r for r in prompt.split("LINES:")[1].splitlines() if r[:1].isdigit()]
        self.shown.append(len(rows))
        number, text = {}, {}
        for row in rows:
            n, _, rest = row.partition(". ")
            rest = rest[4:] if rest.startswith("NEW ") else rest
            number[rest.strip()] = int(n)
            text[int(n)] = rest.strip()
        answers = []
        for drop, keep in self.pairs.items():
            if drop in number and keep in number:
                if drop in self.miss_first and drop not in self.seen:
                    self.seen.add(drop)
                    continue
                answers.append({"line": number[drop], "in_full_by": number[keep]})
        if self.everything:
            answers = [{"line": n, "in_full_by": 1} for n in number.values() if n != 1]
        return {"answers": answers}


FAMILY = ["Has been vegetarian since 2019", "Plays chess on weekends", "Is vegetarian, since 2019",
          "Grows tomatoes on the balcony"]


def _plan(bank, judge, **kw):
    read, _ = _read(bank)
    meter = heal.Meter()
    row = heal.plan_page(read, _names(bank), "Casey Park", judge, meter, **kw)
    return row, meter


def test_a_page_no_line_of_which_resembles_another_costs_no_call(tmp_path):
    bank = _bank(tmp_path, _convs(["Plays chess on weekends", "Grows tomatoes on the balcony", "Has a cat named Biscuit"]))
    judge = Judge(everything=True)
    row, meter = _plan(bank, judge)
    assert (judge.asks, judge.checks, meter.total) == (0, 0, 0) and row["folds"] == []
    assert heal.census(_read(bank)[0])["max_calls"] == 0


def test_a_repeat_is_replayed_one_ask_at_a_time_and_names_what_it_did(tmp_path):
    bank = _bank(tmp_path, _convs(FAMILY))
    judge = Judge({"Is vegetarian, since 2019": "Has been vegetarian since 2019"})
    row, meter = _plan(bank, judge, chunk=1)
    assert [(f["drop"], f["into"], f["how"], f["second_reader"]) for f in row["folds"]] == [
        ("Is vegetarian, since 2019", "Has been vegetarian since 2019", "judged", "agreed")]
    assert (row["before"], row["after"]) == (4, 3)
    assert row["folds"][0]["sources_move"] == ["ep_2026-11-03_001"]
    assert (judge.asks, judge.checks) == (1, 1) and row["calls"] == {"ask": 1, "total": 2}


def test_a_yes_to_everything_still_loses_no_number_date_or_name(tmp_path):
    bank = _bank(tmp_path, _convs(["Runs 5 km every Monday", "Runs 10 km every Monday", "Lives in Lisbon since March 2023",
                                   "Lives in Lisbon since March 2021", "Sister Mara lives in Porto",
                                   "Sister Ines lives in Porto", "Is not vegetarian", "Is vegetarian"]))
    row, _ = _plan(bank, Judge(everything=True), chunk=1)
    assert row["folds"] == []
    assert row["before"] == row["after"] == 8


def test_equal_and_extending_bullets_fold_by_the_rule_with_no_call():
    """A page written before the writer folded them: the rule every write applies, no judge, the rows to move named."""
    bullets = ["Moved to Berlin", "Likes jazz", "moved to berlin.", "Moved to Berlin, in March 2026", "Is [[Mira]] a friend"]
    read = heal.Read(PAGE, "Taylor Brooks", bullets=bullets, rowed=[True] * 5,
                     sources=[frozenset({f"ep_{i}"}) for i in range(5)], kf_hash="x")
    judge = Judge(everything=True)
    row = heal.plan_page(read, None, None, judge, heal.Meter())
    assert judge.asks == 0 and row["calls"]["total"] == 0
    kept = "Moved to Berlin, in March 2026"
    assert {f["drop"]: (f["into"], f["how"]) for f in row["folds"]} == {
        "Moved to Berlin": (kept, "rule-extends"), "moved to berlin.": (kept, "rule-equal")}
    assert sorted(s for f in row["folds"] for s in f["sources_move"]) == ["ep_0", "ep_2"]


def test_a_bullet_no_row_proves_sleep_wrote_is_never_dropped_and_never_held(tmp_path):
    bank = _bank(tmp_path, _convs(FAMILY))
    path = bank / "entities" / f"{PAGE}.md"
    parsed = markdown_parser.parse(path)
    # a person typed a copy of the first line: no provenance row
    body = parsed.body.replace("- Plays chess on weekends", "- Plays chess on weekends\n- Has been vegetarian since 2019, typed by hand")
    markdown_parser.write(path, parsed.frontmatter, body)
    read, _ = _read(bank)
    assert read.rowed.count(False) == 1
    row, _ = _plan(bank, Judge(everything=True), chunk=1)
    assert all("typed by hand" not in f["drop"] and "typed by hand" not in f["into"] for f in row["folds"])
    assert row["rowless_kept"] == 1


def test_a_second_sweep_asks_again_about_what_the_first_left_and_a_quiet_one_ends_it(tmp_path):
    x, y = ("Is vegetarian, since 2019", "Has been vegetarian since 2019"), ("Has lived in Lisbon since March 2023",
                                                                           "Lives in Lisbon since March 2023")
    bank = _bank(tmp_path, _convs([y[1], x[1], "Plays chess on weekends", x[0], y[0]]))
    one = _plan(bank, Judge(dict([x, y]), miss_first=[y[0]]), chunk=1, passes=1)[0]
    assert [f["drop"] for f in one["folds"]] == [x[0]]
    judge = Judge(dict([x, y]), miss_first=[y[0]])
    two = _plan(bank, judge, chunk=1, passes=2)[0]
    assert sorted(f["drop"] for f in two["folds"]) == sorted([x[0], y[0]])
    quiet = Judge()   # nothing folds in the first sweep: no second one
    _plan(bank, quiet, chunk=1, passes=2)
    assert quiet.asks == 2


def test_a_nickname_the_pages_neighbourhood_reads_as_one_name_is_asked_about_though_the_words_differ(tmp_path):
    bank = _bank(tmp_path, _convs(["Favourite artist of [[Mira Lund]]", "Is Pip's favourite artist"]))
    base = {"type": "person", "status": "active", "confidence": 0.8, "source_episodes": ["ep_2026-10-01_001"]}
    markdown_parser.write(bank / "entities" / "mira-lund.md", {**base, "name": "Mira Lund", "aliases": ["Pip"]}, "## Summary\nA friend.\n")
    path = bank / "entities" / f"{PAGE}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "related": ["mira-lund"]}, parsed.body)
    read, _ = _read(bank)
    names = _names(bank)
    assert heal.census(read, chunk=1)["candidates"] == 0
    assert heal.census(read, chunk=1, names=names)["candidates"] == 1
    judge = Judge(everything=True)
    row = heal.plan_page(read, names, None, judge, heal.Meter(), chunk=1)
    assert judge.asks >= 1 and [f["drop"] for f in row["folds"]] == ["Is Pip's favourite artist"]


def test_a_pinned_correction_is_never_dropped(tmp_path):
    bank = _bank(tmp_path, _convs(FAMILY))
    path = bank / "entities" / f"{PAGE}.md"
    parsed = markdown_parser.parse(path)
    fm = {**parsed.frontmatter, "corrections": [{"old": "x", "new": "Is vegetarian, since 2019", "by": "t", "on": "2026-11-01"}]}
    markdown_parser.write(path, fm, parsed.body)
    row, _ = _plan(bank, Judge({"Is vegetarian, since 2019": "Has been vegetarian since 2019"}), chunk=1)
    assert "Is vegetarian, since 2019" not in [f["drop"] for f in row["folds"]]


def test_a_page_a_person_edited_is_left_alone(tmp_path):
    bank = _bank(tmp_path, _convs(FAMILY))
    path = bank / "entities" / f"{PAGE}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "human_edited": True}, parsed.body)
    assert _read(bank)[0].skip == "human_page"


def test_a_page_with_free_prose_in_key_facts_is_left_alone(tmp_path):
    bank = _bank(tmp_path, _convs(FAMILY))
    path = bank / "entities" / f"{PAGE}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body.replace("## Key Facts\n", "## Key Facts\nA loose line.\n"))
    assert _read(bank)[0].skip == "format"


def test_a_long_page_asks_about_at_most_forty_lines_and_stays_inside_its_call_cap(tmp_path):
    facts = [f"Fact number {i} about item{i} in {1900 + i}" for i in range(70)]
    facts += [f"Item{i} is item{i} in {1900 + i}, restated" for i in range(0, 70, 3)]
    bank = _bank(tmp_path, _convs(facts))
    judge = Judge()
    row, meter = _plan(bank, judge, chunk=3, max_calls=10)
    assert row["status"] == "capped" and meter.total <= 10
    assert max(judge.shown) <= fact_fold.MAX_LINES
    assert row["before"] == len(facts) and row["after"] == row["before"] - len(row["folds"])


def test_the_most_calls_possible_is_what_the_census_says(tmp_path):
    bank = _bank(tmp_path, _convs(["Has been vegetarian since 2019", "Is vegetarian, since 2019",
                                   "Vegetarian since 2019 (a note)"]))
    read, _ = _read(bank)
    info = heal.census(read, chunk=1)
    judge = Judge(everything=True)
    _, meter = _plan(bank, judge, chunk=1)
    assert meter.total <= info["max_calls"]


def test_a_holder_folded_later_carries_what_it_held_to_the_new_holder(tmp_path):
    first, second = "Has been vegetarian since 2019", "Is vegetarian, since 2019"
    third = "He has been vegetarian since 2019 because of ethics"
    bank = _bank(tmp_path, _convs([first, "Plays chess on weekends", second, third]))
    judge = Judge({second: first, first: third})
    row, _ = _plan(bank, judge, chunk=1)
    held = {f["drop"]: f["into"] for f in row["folds"]}
    assert held == {second: third, first: third}
    assert sorted(s for f in row["folds"] for s in f["sources_move"]) == ["ep_2026-11-01_001", "ep_2026-11-03_001"]
    assert row["after"] == 2
    _apply(bank, row)
    page = _page(bank, bank / "entities" / f"{PAGE}.md")
    rows = section_provenance.matched(page["frontmatter"], page["body"])["key_facts"]
    scan = {i.text: i for i in section_provenance.scan(page["body"])["key_facts"]}
    assert {ev.episode for ev in rows[scan[third].key][1]} == {"ep_2026-11-01_001", "ep_2026-11-03_001", "ep_2026-11-04_001"}


def _apply(bank, row, **kw):
    return heal.apply(bank, [row], sleep_running=lambda: False, names=_names(bank), owner="Casey Park", **kw)


def _healed(tmp_path, *, git=False):
    bank = _bank(tmp_path, _convs(FAMILY), git=git)
    row, _ = _plan(bank, Judge({"Is vegetarian, since 2019": "Has been vegetarian since 2019"}), chunk=1)
    return bank, row


def test_apply_writes_exactly_the_plan_moves_the_sources_and_leaves_the_rest_byte_for_byte(tmp_path):
    bank, row = _healed(tmp_path)
    path = bank / "entities" / f"{PAGE}.md"
    before = path.read_text(encoding="utf-8")
    result = _apply(bank, row)
    after = path.read_text(encoding="utf-8")
    assert result.counts()["pages_written"] == 1 and result.committed is False
    def without_rows(text):   # the provenance rows are the one frontmatter field a fold moves
        start = text.index("section_provenance:")
        return (text[:start] + text[text.index("\n---", start):]).rstrip() + "\n"

    assert without_rows(before).replace("- Is vegetarian, since 2019\n", "") == without_rows(after)
    page = _page(bank, path)
    rows = section_provenance.matched(page["frontmatter"], page["body"])["key_facts"]
    scan = {i.text: i for i in section_provenance.scan(page["body"])["key_facts"]}
    held = {ev.episode for ev in rows[scan["Has been vegetarian since 2019"].key][1]}
    assert held == {"ep_2026-11-01_001", "ep_2026-11-03_001"}
    assert "Is vegetarian, since 2019" not in scan


def test_apply_makes_no_model_call(tmp_path, monkeypatch):
    bank, row = _healed(tmp_path)
    monkeypatch.setattr(fact_fold, "judge_for", lambda *a, **k: pytest.fail("a model was asked"))
    monkeypatch.setattr(fact_fold, "decide", lambda *a, **k: pytest.fail("a model was asked"))
    assert _apply(bank, row).written == 1


def test_a_page_whose_key_facts_changed_since_the_plan_is_skipped_never_rejudged(tmp_path):
    bank, row = _healed(tmp_path)
    path = bank / "entities" / f"{PAGE}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body.replace("- Plays chess on weekends", "- Plays chess on Sundays"))
    before = path.read_text(encoding="utf-8")
    result = _apply(bank, row)
    assert result.skipped == {"key_facts_changed": 1} and path.read_text(encoding="utf-8") == before


def test_a_struck_fold_or_page_is_not_written(tmp_path):
    bank, row = _healed(tmp_path)
    path = bank / "entities" / f"{PAGE}.md"
    before = path.read_text(encoding="utf-8")
    assert _apply(bank, row, skip_folds=[row["folds"][0]["id"]]).written == 0
    assert _apply(bank, row, skip_pages=[PAGE]).written == 0
    row["folds"][0]["strike"] = True
    assert _apply(bank, row).written == 0
    assert path.read_text(encoding="utf-8") == before
    row["folds"][0]["strike"] = False
    row["strike"] = True
    assert _apply(bank, row).written == 0 and path.read_text(encoding="utf-8") == before


def test_a_fold_the_guard_would_no_longer_pass_is_not_written(tmp_path):
    bank, row = _healed(tmp_path)
    row["folds"][0]["drop"], row["folds"][0]["into"] = "Has been vegetarian since 2019", "Plays chess on weekends"
    path = bank / "entities" / f"{PAGE}.md"
    before = path.read_text(encoding="utf-8")
    result = _apply(bank, row)
    assert result.written == 0 and path.read_text(encoding="utf-8") == before and "guard" in result.fold_skipped


def test_check_writes_nothing(tmp_path):
    bank, row = _healed(tmp_path)
    path = bank / "entities" / f"{PAGE}.md"
    before = path.read_text(encoding="utf-8")
    result = heal.apply(bank, [row], sleep_running=lambda: pytest.fail("--check asks nobody"), names=_names(bank),
                        owner=None, check=True)
    assert result.written == 1 and result.committed is False
    assert path.read_text(encoding="utf-8") == before


def test_apply_refuses_while_sleep_runs_and_writes_nothing(tmp_path):
    bank, row = _healed(tmp_path)
    path = bank / "entities" / f"{PAGE}.md"
    before = path.read_text(encoding="utf-8")
    with pytest.raises(heal.SleepRunning):
        heal.apply(bank, [row], sleep_running=lambda: True, names=_names(bank), owner=None)
    assert path.read_text(encoding="utf-8") == before


def test_one_commit_under_cicada_of_only_its_paths_and_a_plain_revert_undoes_it(tmp_path):
    bank, row = _healed(tmp_path, git=True)
    (bank / "notes.txt").write_text("another writer's uncommitted file", encoding="utf-8")
    path = bank / "entities" / f"{PAGE}.md"
    before = path.read_text(encoding="utf-8")
    assert _apply(bank, row).committed is True
    log = subprocess.run(["git", "log", "-1", "--format=%B", "--name-only"], cwd=bank, capture_output=True, text=True).stdout
    assert "Cicada-Author: cicada" in log and f"entities/{PAGE}.md" in log and "notes.txt" not in log
    assert "maintenance/fact-fold-heal" in log
    assert "Cicada-Engine" not in log   # no model ran here: never guessed
    assert path.read_text(encoding="utf-8") != before
    subprocess.run(["git", "revert", "--no-edit", "HEAD"], cwd=bank, check=True, capture_output=True)
    assert path.read_text(encoding="utf-8") == before


def test_a_page_dirty_in_git_is_skipped(tmp_path):
    bank, row = _healed(tmp_path, git=True)
    path = bank / "entities" / f"{PAGE}.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = _apply(bank, row)
    assert result.skipped == {"dirty_in_git": 1} and result.written == 0


def test_a_demo_bank_is_never_written(tmp_path, capsys):
    from api.scripts import fact_fold_heal as script

    bank, row = _healed(tmp_path)
    demo_guard.write_manifest(bank)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "pages.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    before = (bank / "entities" / f"{PAGE}.md").read_text(encoding="utf-8")
    assert script.main(["apply", "--bank", str(bank), "--plan", str(plan)]) == 4
    assert (bank / "entities" / f"{PAGE}.md").read_text(encoding="utf-8") == before


def test_the_plan_refuses_an_output_directory_inside_the_repo_or_the_bank(tmp_path, capsys):
    from api.scripts import fact_fold_heal as script

    bank, _ = _healed(tmp_path)
    assert script.main(["plan", "--bank", str(bank), "--out", str(bank / "out")]) == 2
    assert script.main(["plan", "--bank", str(bank), "--out", str(script.REPO / "out")]) == 2


def test_the_census_prints_counts_only_and_calls_no_model(tmp_path, capsys, monkeypatch):
    from api.scripts import fact_fold_heal as script

    bank, _ = _healed(tmp_path)
    monkeypatch.setattr(fact_fold, "judge_for", lambda *a, **k: pytest.fail("a model was asked"))
    out = tmp_path / "out"
    assert script.main(["plan", "--bank", str(bank), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "vegetarian" not in printed and "pages_to_ask" in printed and "most_calls_possible" in printed
    assert json.loads((out / "census.json").read_text())["summary"]["pages_to_ask"] >= 1
