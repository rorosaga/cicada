"""A merge or rename keeps what the person gave the page (2026-10-21): their *keep* answers (G147, `kept_on`) and their
own picture choice with its file (G146, `picture:` + `assets/pictures/<id>.<ext>`).

Before this, a merge unioned `source_episodes` but dropped the absorbed page's `kept_on`, and the upload's file — whose
path is derived from the id — stayed at the loser's id (merge) or the old id (rename), so the picture 404'd or was lost.
Every door shares the two primitives (`entity_merge.merge_entities`, `entity_merge.rename_references`), and the dedup
sweep's transaction only lets a merge write inside `merge_footprint`, so the footprint is asserted too. Synthetic banks.
"""
from __future__ import annotations

import struct
import subprocess
import zlib
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.services import decay_policy, entity_picture, markdown_parser
from api.services import dedup_sweep as ds
from api.services.entity_merge import merge_entities, merge_footprint, rename_references
from api.tests import test_merge_edges as merge_doors


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * 32 for _ in range(32))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _page(memory: Path, eid: str, name: str, **fm) -> None:
    front = {"name": name, "type": "person", "status": "active", "confidence": 0.6, "source_episodes": ["ep_1"], **fm}
    ents = memory / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    (ents / f"{eid}.md").write_text("---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n## Summary\nx\n")


def _fm(memory: Path, eid: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _upload(memory: Path, eid: str) -> dict:
    """Store a picture the way the app's upload does, and return the mark it left."""
    entity_picture.write_upload(memory, eid, _png(), "png", today=date(2026, 10, 1))
    return _fm(memory, eid)["picture"]


# --- kept_on (G147) ------------------------------------------------------------------------------------------------


def test_a_merge_keeps_both_pages_keep_answers(tmp_path):
    _page(tmp_path, "alpha-project", "alpha-project", kept_on=["2026-09-01", "2026-09-20"])
    _page(tmp_path, "alpha", "alpha", kept_on=["2026-08-03", "2026-09-01"])
    weeks_before = decay_policy.effective(_fm(tmp_path, "alpha-project")).mention_weeks

    merge_entities(tmp_path, loser_id="alpha", winner_id="alpha-project")

    fm = _fm(tmp_path, "alpha-project")
    assert fm["kept_on"] == ["2026-08-03", "2026-09-01", "2026-09-20"]
    assert decay_policy.effective(fm).mention_weeks == weeks_before + 1, "the absorbed keep counts as a week"


def test_a_merge_takes_the_loser_keeps_when_the_winner_has_none_and_caps_them(tmp_path):
    days = [f"2025-{m:02d}-{d:02d}" for m in range(1, 13) for d in (1, 8, 15, 22, 28)][:60]
    _page(tmp_path, "bob-example", "bob-example")
    _page(tmp_path, "bob", "bob", kept_on=days)

    merge_entities(tmp_path, loser_id="bob", winner_id="bob-example")

    kept = _fm(tmp_path, "bob-example")["kept_on"]
    assert kept == sorted(days)[-decay_policy.KEPT_ON_CAP:], "the newest keeps, oldest first"


def test_a_merge_with_no_keeps_writes_no_kept_on(tmp_path):
    _page(tmp_path, "bob-example", "bob-example")
    _page(tmp_path, "bob", "bob")

    merge_entities(tmp_path, loser_id="bob", winner_id="bob-example")

    assert "kept_on" not in _fm(tmp_path, "bob-example")


# --- the person's picture (G146) -----------------------------------------------------------------------------------


def test_a_merge_moves_the_loser_upload_to_a_winner_without_a_choice(tmp_path):
    _page(tmp_path, "bob-example", "bob-example")
    _page(tmp_path, "bob", "bob")
    mark = _upload(tmp_path, "bob")
    predicted = merge_footprint(tmp_path, "bob", "bob-example")

    out = merge_entities(tmp_path, loser_id="bob", winner_id="bob-example")

    pictures = tmp_path / "assets" / "pictures"
    assert not (pictures / "bob.png").exists()
    assert (pictures / "bob-example.png").read_bytes() == _png()
    assert _fm(tmp_path, "bob-example")["picture"] == mark
    served = entity_picture.picture_file(tmp_path, "bob-example", _fm(tmp_path, "bob-example"))
    assert served is not None and served[0].name == "bob-example.png"
    assert {"assets/pictures/bob.png", "assets/pictures/bob-example.png"} <= set(out["paths"])
    assert set(out["paths"]) <= set(predicted), "the merge writes only inside its footprint"


def test_the_winner_own_choice_stands_and_the_loser_upload_goes(tmp_path):
    _page(tmp_path, "bob-example", "bob-example")
    _page(tmp_path, "bob", "bob")
    winner_mark = _upload(tmp_path, "bob-example")
    _upload(tmp_path, "bob")
    predicted = merge_footprint(tmp_path, "bob", "bob-example")

    out = merge_entities(tmp_path, loser_id="bob", winner_id="bob-example")

    assert _fm(tmp_path, "bob-example")["picture"] == winner_mark
    assert not (tmp_path / "assets" / "pictures" / "bob.png").exists(), "no file nothing names is left behind"
    assert (tmp_path / "assets" / "pictures" / "bob-example.png").exists()
    assert "assets/pictures/bob.png" in out["paths"]
    assert "assets/pictures/bob-example.png" not in out["paths"]
    assert set(out["paths"]) <= set(predicted)


def test_initials_travel_to_a_winner_without_a_choice(tmp_path):
    _page(tmp_path, "bob-example", "bob-example")
    _page(tmp_path, "bob", "bob", picture={"kind": "initials", "added": "2026-10-01"})

    out = merge_entities(tmp_path, loser_id="bob", winner_id="bob-example")

    assert _fm(tmp_path, "bob-example")["picture"] == {"kind": "initials", "added": "2026-10-01"}
    assert not [p for p in out["paths"] if p.startswith("assets/")]


def test_an_upload_mark_whose_file_is_gone_does_not_travel(tmp_path):
    _page(tmp_path, "bob-example", "bob-example")
    _page(tmp_path, "bob", "bob", picture={"kind": "upload", "sha": "0123456789ab", "ext": "png", "added": "2026-10-01"})

    out = merge_entities(tmp_path, loser_id="bob", winner_id="bob-example")

    assert "picture" not in _fm(tmp_path, "bob-example"), "a mark with no file would only 404"
    assert not [p for p in out["paths"] if p.startswith("assets/")]


def test_a_rename_moves_the_upload_with_the_page(tmp_path):
    _page(tmp_path, "bob", "bob")
    mark = _upload(tmp_path, "bob")
    (tmp_path / "entities" / "bob.md").replace(tmp_path / "entities" / "bob-example.md")

    paths = rename_references(tmp_path, "bob", "bob", "bob-example", "bob-example")

    pictures = tmp_path / "assets" / "pictures"
    assert not (pictures / "bob.png").exists()
    assert (pictures / "bob-example.png").read_bytes() == _png()
    assert _fm(tmp_path, "bob-example")["picture"] == mark
    assert entity_picture.picture_file(tmp_path, "bob-example", _fm(tmp_path, "bob-example")) is not None
    assert {"assets/pictures/bob.png", "assets/pictures/bob-example.png"} <= set(paths)


def test_the_placeholder_rename_footprint_names_the_picture(tmp_path):
    from api.services import role_people

    _page(tmp_path, "your-sister", "Your sister")
    _upload(tmp_path, "your-sister")

    footprint = role_people._rename_footprint(tmp_path, "your-sister", "Carol Example")

    assert "assets/pictures/your-sister.png" in footprint
    assert f"assets/pictures/{role_people.sanitize_id('Carol Example')}.png" in footprint


# --- the dedup sweep's transaction commits the move ----------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def test_a_dedup_sweep_merge_commits_the_picture_move(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    memory = tmp_path / "memory"
    _page(memory, "esa", "ESA", kept_on=["2026-09-01"])
    _page(memory, "esta", "ESTA", kept_on=["2026-08-03"])
    _upload(memory, "esta")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")

    out = ds.dedup_sweep(memory, SimpleNamespace(), seed_pairs=[("esa", "esta")],
                         judge_fn=lambda *_a: {"verdict": "same", "confidence": 0.95, "winner": "esa"})

    assert out["merged"] == [("esta", "esa")] and not out["recovery_failed"]
    assert _git(memory, "status", "--porcelain").strip() == "", "the move is committed, nothing left behind"
    tracked = set(_git(memory, "ls-files").split())
    assert "assets/pictures/esa.png" in tracked and "assets/pictures/esta.png" not in tracked
    assert _fm(memory, "esa")["kept_on"] == ["2026-08-03", "2026-09-01"]


# --- every door that merges or renames a page (the edge test's doors, `test_merge_edges.DOORS`) ---------------------


@pytest.mark.parametrize("door", merge_doors.DOORS, ids=[d.__name__[6:] for d in merge_doors.DOORS])
def test_every_merge_door_keeps_the_picture_and_the_keeps(tmp_path, monkeypatch, door):
    seed = merge_doors._bank

    def bank_with_marks(tmp, old, new, *, old_fm, new_fm):
        memory = seed(tmp, old, new, old_fm={**old_fm, "kept_on": ["2026-08-03"]}, new_fm=new_fm)
        _upload(memory, old)
        merge_doors._git(memory, "add", "-A")
        merge_doors._git(memory, "commit", "-q", "-m", "marks")
        return memory

    monkeypatch.setattr(merge_doors, "_bank", bank_with_marks)
    monkeypatch.setenv("CICADA_TELEMETRY", "off")

    memory, old, new = door(tmp_path)

    fm = _fm(memory, new)
    assert fm["picture"]["kind"] == "upload"
    served = entity_picture.picture_file(memory, new, fm)
    assert served is not None and served[0].name == f"{new}.png"
    assert not (memory / "assets" / "pictures" / f"{old}.png").exists()
    assert "2026-08-03" in fm.get("kept_on", [])
    if door not in (merge_doors._door_merge_entities, merge_doors._door_rename_references):
        assert merge_doors._git(memory, "status", "--porcelain", "--", "assets") == "", "the move is committed"
