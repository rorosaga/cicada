"""G104 (owner 2026-11-03): a conversation Sleep read, edited in place, read again as a revision — end to end.

Real: Sleep's episode loader, the git read of the version Sleep last read, Stage 1's real ``extract`` (windows, the
revision note, the G118 locate, the unchanged-lines filter), and Stage 3 + write-back of claims. Fake: the model's
answer (``litellm.acompletion``, a rule per line so a re-read gives the same claims), Stage 2's legacy pass, Stage 4,
the vector index and Sleep's own commit (the test commits the bank as Sleep's commit would).

The four edits the owner's question names: (a) a fact changed, (b) a line added, (c) a line removed, (d) only
whitespace. Before this, the second read re-extracted all four in full, left (c)'s claim open on a span that no longer
locates, asked a conflict question for (a), and doubled every unchanged claim's evidence."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from types import SimpleNamespace

from api.config import Settings
from api.services import bank_index, entity_extractor, evidence, markdown_parser, sleep_cycle
from api.services.claims import is_record, parse_claims
from api.tests.test_sleep_cycle_hold import _bank, _patch, _settings

HEAD = "user: Meeting notes for alpha-project."
V1 = {
    "a": f"{HEAD}\nThe alpha-project design review meeting is on Friday.\nalpha-project will use rustfft.",
    "b": f"{HEAD}\nalpha-project stores its spectrograms in SQLite.",
    "c": f"{HEAD}\nalpha-project uses tokio for async work.\nalpha-project targets Linux only.",
    "d": f"{HEAD}\nalpha-project is licensed under the MIT license.",
}
V2 = {
    "a": f"{HEAD}\nThe alpha-project design review meeting is on Thursday.\nalpha-project will use rustfft.",
    "b": f"{HEAD}\nalpha-project stores its spectrograms in SQLite.\nalpha-project ships its first release in December.",
    "c": f"{HEAD}\nalpha-project uses tokio for async work.",
    "d": f"{HEAD}\n\nalpha-project is licensed under  the MIT license.",
}
EP = {k: f"ep_2026-11-0{i + 1}_001" for i, k in enumerate("abcd")}


def _answer(chunk: str) -> dict:
    """One rule per line, so the model is deterministic: what a line says is always the same claim."""
    ents = {"alpha-project": {"name": "alpha-project", "type": "project", "confidence": 0.9, "summary": "A project."}}
    rels, vals = [], []
    for line in chunk.splitlines():
        if m := re.search(r"design review meeting is on (\w+)", line):
            vals.append({"entity": "alpha-project", "attribute": "design review day", "value": m[1],
                         "evidence_quote": m[0]})
        if m := re.search(r"(uses tokio|use rustfft|stores its spectrograms in SQLite)", line):
            target = {"uses tokio": "tokio", "use rustfft": "rustfft"}.get(m[1], "SQLite")
            ents[target] = {"name": target, "type": "tool", "confidence": 0.7, "summary": "A tool."}
            rels.append({"source": "alpha-project", "target": target, "label": "uses", "evidence_quote": m[0]})
        if m := re.search(r"targets (Linux only)", line):
            vals.append({"entity": "alpha-project", "attribute": "platform", "value": m[1], "evidence_quote": m[0]})
        if m := re.search(r"licensed under\s+the MIT license", line):
            vals.append({"entity": "alpha-project", "attribute": "license", "value": "MIT", "evidence_quote": m[0]})
        if m := re.search(r"first release in (\w+)", line):
            vals.append({"entity": "alpha-project", "attribute": "first release", "value": m[1],
                         "evidence_quote": m[0]})
    return {"entities": list(ents.values()), "relationships": rels, "values": vals}


def _git(memory, *args):
    subprocess.run(["git", *args], cwd=memory, check=True, capture_output=True)


def _digest(body: str) -> str:
    return "sha256:" + evidence.body_hash(body)


def _write(memory, k, body, processed=False, revised=None):
    """The stager's write: ``content_hash`` over the body; an edit in place also writes G95's ``revised`` record."""
    fm = {"id": EP[k], "processed": processed, "source": "note", "origin": "note", "source_id": f"note:test:{k}",
          "timestamp": f"{EP[k][3:13]}T10:00:00Z", "content_hash": _digest(body)}
    if revised:
        fm["revised"] = revised
    markdown_parser.write(memory / "episodes" / f"{EP[k]}.md", fm, body)


def _claims(memory):
    out = []
    for page in (memory / "entities").glob("*.md"):
        out += parse_claims(markdown_parser.parse(page).body)
    return out


def _run(memory, monkeypatch, prompts):
    async def fake_acompletion(**kw):
        content = kw["messages"][1]["content"]
        prompts.append(content)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_answer(content))))])

    real_extract = entity_extractor.extract
    _patch(monkeypatch, [])

    async def extract_with_fake_engine(episodes, settings, **kw):
        return await real_extract(episodes, Settings(litellm_model="fake-engine", memory_path=memory), **kw)

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr("api.services.entity_extractor.extract", extract_with_fake_engine)
    bank_index.invalidate()
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="g104_revision"))
    bank_index.invalidate()


def _setup(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "status": "active", "confidence": 0.9},
                          "## Summary\nalpha-project is a synthetic project.\n")
    for k, body in V1.items():
        _write(memory, k, body)
    _git(memory, "init", "-q")
    _git(memory, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A")
    _git(memory, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "capture")
    first: list[str] = []
    _run(memory, monkeypatch, first)
    assert all(markdown_parser.parse(memory / "episodes" / f"{EP[k]}.md").frontmatter["processed"] for k in EP)
    # Sleep's own commit (stubbed in `_patch`): the processed versions are what git holds.
    _git(memory, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A")
    _git(memory, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "Sleep cycle")
    before = {c.id: c for c in _claims(memory)}
    for k, body in V2.items():   # the stager's in-place edit: same file and id, `processed: false`, a `revised` record
        _write(memory, k, body, revised={"count": 1, "at": "2026-11-03T12:00:00Z", "previous_hash": _digest(V1[k]),
                                         "consolidated_hash": _digest(V1[k])})
    return memory, first, before


def test_four_edits_are_read_as_revisions(tmp_path, monkeypatch):
    memory, first, before = _setup(tmp_path, monkeypatch)
    assert len(first) == 4
    prompts: list[str] = []
    _run(memory, monkeypatch, prompts)
    claims = _claims(memory)
    by = {(c.predicate, c.object): c for c in claims if not is_record(c)}
    body = {k: evidence.source_text(memory, EP[k]) for k in EP}

    # Only the two episodes with new words cost a call: (c) only removed a line, (d) only moved whitespace.
    assert len(prompts) == 2
    assert all(entity_extractor.episode_revision.REVISION_NOTE in p for p in prompts)
    assert not any("licensed" in p or "tokio" in p for p in prompts)

    # (a) the changed value closes the old one: superseded by the revision's, no conflict question.
    friday, thursday = by[("value-of-design-review-day", "Friday")], by[("value-of-design-review-day", "Thursday")]
    assert friday.valid_to is not None and friday.superseded_by == thursday.id and thursday.supersedes == friday.id
    assert thursday.valid_to is None
    (ev,) = thursday.evidence
    assert body["a"][ev.start:ev.end] == "design review meeting is on Thursday"
    assert not list((memory / "inbox").rglob("*.md"))

    # (a)/(b) an unchanged line's claim is re-anchored, never re-read into a second span.
    for key, k, words in ((("uses", "rustfft"), "a", "use rustfft"),
                          (("uses", "sqlite"), "b", "stores its spectrograms in SQLite"),
                          (("uses", "tokio"), "c", "uses tokio")):
        assert by[key].id in before
        (ev,) = by[key].evidence
        assert evidence.span_status(body[k], end=ev.end, hash=ev.hash) == evidence.SPAN_CURRENT
        assert body[k][ev.start:ev.end] == words
    # (b) the added line is a new claim on the new body.
    (ev,) = by[("value-of-first-release", "December")].evidence
    assert body["b"][ev.start:ev.end] == "first release in December"

    # (c) the removed line's claim is withdrawn, not deleted: a `retracts` record naming the revision.
    linux = by[("value-of-platform", "Linux only")]
    assert linux.valid_to is not None
    (record,) = [c for c in claims if is_record(c) and c.object == linux.id]
    assert linux.superseded_by == record.id and record.authored_by == "cicada"
    (rev,) = record.evidence
    assert rev.episode == EP["c"] and rev.kind == "reasoning" and rev.hash == evidence.body_hash(body["c"])

    # (d) whitespace only: no call, the span re-anchored through the whitespace rung, nothing asked.
    (ev,) = by[("value-of-license", "MIT")].evidence
    assert body["d"][ev.start:ev.end] == "licensed under  the MIT license"
    assert ev.hash == evidence.body_hash(body["d"])

    # Every revision is still the one conversation it was: no claim cites a second episode, all four retired.
    assert all(set(c.source_episodes) <= set(EP.values()) and len(c.source_episodes) <= 1 for c in claims)
    for k in EP:
        fm = markdown_parser.parse(memory / "episodes" / f"{EP[k]}.md").frontmatter
        # Retired, and G95's record now names the body Sleep just read as the consolidated one.
        assert fm["processed"] is True and fm["revised"]["consolidated_hash"] == _digest(V2[k])
        assert fm["revised"]["count"] == 1 and fm["revised"]["previous_hash"] == _digest(V1[k])


def test_without_git_an_edit_is_read_whole_as_before(tmp_path, monkeypatch):
    memory, _, _ = _setup(tmp_path, monkeypatch)
    subprocess.run(["rm", "-rf", str(memory / ".git")], check=True)
    prompts: list[str] = []
    _run(memory, monkeypatch, prompts)
    assert len(prompts) == 4 and not any(entity_extractor.episode_revision.REVISION_NOTE in p for p in prompts)
    # The behaviour before G104's revision read, kept as the fallback: nothing knows the line went, the same source's
    # changed value is a question, and an unchanged line's claim gains a second span beside its stale one.
    claims = _claims(memory)
    linux = next(c for c in claims if c.object == "Linux only")
    assert linux.valid_to is None
    assert [markdown_parser.parse(f).frontmatter.get("kind") for f in (memory / "inbox").rglob("*.md")] == ["conflict"]
    tokio = next(c for c in claims if c.object == "tokio")
    assert len(tokio.evidence) == 2
