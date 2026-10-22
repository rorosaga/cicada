"""The new-user benchmark's fixture (benchmarks/newuser): deterministic, placeholder-only, and in the shapes the real
doors parse — so a release check that loads it measures memory, not a fixture that no longer imports."""
from __future__ import annotations

import json
import re
import zipfile

from benchmarks.newuser import ask, persona

from api.services import transcript_extract


def test_build_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    persona.build(a)
    persona.build(b)
    for f in sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file()):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_links_and_addresses_are_placeholders(tmp_path):
    persona.build(tmp_path)
    blob = "".join(p.read_bytes().decode("utf-8", "replace") for p in tmp_path.rglob("*")
                   if p.is_file() and p.suffix != ".zip")
    for z in tmp_path.glob("*.zip"):
        with zipfile.ZipFile(z) as zf:
            blob += "".join(zf.read(n).decode() for n in zf.namelist())
    hosts = set(re.findall(r"https?://([^/\"'\s<]+)", blob))
    assert hosts == {"example.com"}, hosts
    assert set(re.findall(r"[\w.]+@([\w.]+)", blob)) <= {"example.invalid"}


def test_exports_parse_through_the_real_intake(tmp_path):
    from api.routers import intake

    persona.build(tmp_path)
    gpt = intake.parse_export((tmp_path / "chatgpt-export.zip").read_bytes(), "chatgpt-export.zip")
    claude = intake.parse_export((tmp_path / "claude-export.zip").read_bytes(), "claude-export.zip")
    assert (gpt.format, len(gpt.episodes)) == ("chatgpt", len(persona.CHATGPT))
    assert (claude.format, len(claude.episodes)) == ("claude", len(persona.CLAUDE_AI))


def test_transcripts_keep_the_persons_turns_and_final_replies(tmp_path):
    for i, sess in enumerate(persona.CLAUDE_CODE):
        conv = transcript_extract.extract("claude-code", persona.claude_code_transcript(i).splitlines())
        users = [t for t in sess["turns"] if t[0] == "user"]
        assert [t.text for t in conv.turns if t.role == "user"] == [u[1] for u in users]
        assert conv.cwd == sess["cwd"]


def test_grade_reads_expect_forbid_and_abstain():
    q = {"expect": [["Reyes"]], "forbid": ["Okafor is her climbing"]}
    assert ask.grade(q, "Sam Reyes leads.", False)[0] == "correct"
    assert ask.grade(q, "Okafor is her climbing partner, not Reyes", False)[0] == "wrong"
    assert ask.grade({"expect": [["a"], ["b"]]}, "a only", False)[0] == "partial"
    assert ask.grade({"abstain": True, "forbid": ["$"]}, "The record doesn't say.", False)[0] == "correct"
    assert ask.grade({"abstain": True, "forbid": ["$"]}, "About $90k.", False)[0] == "wrong"
    assert ask.grade({"expect": [["x"]]}, "", True)[0] == "refused"


def test_questions_file_is_well_formed():
    data = json.loads((persona.Path(ask.HERE) / "questions.json").read_text())
    ids = [q["id"] for q in data["questions"]]
    assert len(ids) == 25 == len(set(ids))
    tools = {"cicada_ask", "cicada_recall", "cicada_timeline", "cicada_project", "cicada_continue"}
    assert {q["tool"] for q in data["questions"]} == tools
