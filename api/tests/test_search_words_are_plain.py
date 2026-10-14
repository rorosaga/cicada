"""Search & files (owner 2026-10-14): the backend writes some of the person's words — the catalog's labels and
details, a download's steps and its errors — and the app shows them verbatim, so they are held here to the same bar
as the page: no model, embedding, index, vector, token, runtime or checksum, no family, vendor or hardware name, and
never a repo path. The one exemption is the larger version's account flow, which names the person's own Hugging Face
account and its key (it sits behind Advanced).

Also: the one install job says which part it is downloading and how many bytes it has, so Settings puts a step on
the right row and draws a real progress bar; and the image part's size says whether it includes the text part.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from api.services import embedding_models as em
from api.services import model_fetch

API = Path(__file__).resolve().parents[1]
BANNED = re.compile(r"\b(models?|embeddings?|index(es)?|vectors?|tokens?|runtimes?|checksums?)\b", re.I)
NAMES = ("Neural Engine", "Gemma", "Google", "Core ML", "FluidInference", "api/", ".json")


def _plain(sentence: str) -> None:
    assert not BANNED.search(sentence), sentence
    for name in NAMES:
        assert name not in sentence, f"{sentence!r} names {name}"


def _literals(path: Path, call: str) -> list[str]:
    """Every string literal passed as the first argument (or `detail=`) of ``call(...)`` in ``path``."""
    out: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != call:
            continue
        args = list(node.args[:1]) + [k.value for k in node.keywords if k.arg == "detail"]
        for arg in args:
            parts = [arg] if not isinstance(arg, ast.JoinedStr) else arg.values
            text = "".join(p.value for p in parts if isinstance(p, ast.Constant) and isinstance(p.value, str))
            if text:
                out.append(text)
    return out


def test_the_catalog_reads_as_what_each_version_does():
    labels = {m.id: m.label for m in em.CATALOG}
    assert labels[em.PREFERRED_ID] == "Sharper" and labels[em.SMALL_ID] == "Built in" and labels[em.LARGE_ID] == "Larger"
    for m in em.CATALOG:
        _plain(m.label)
        _plain(m.detail)
    assert "585 MB" in next(m.detail for m in em.CATALOG if m.id == em.PREFERRED_ID), "the size before the click"


def test_every_step_is_plain_and_the_image_download_never_says_search():
    steps = [em.STEP_STARTING, em.STEP_CHECKING, em.STEP_SETTING_UP, em.STEP_LARGER_RUNTIME, em.STEP_LARGER_DOWNLOAD,
             em.step_downloading(312_000_000, 585_000_000)]
    for step in steps:
        _plain(step)
    assert em.step_downloading(312_000_000, 585_000_000) == "Downloading — 312 of 585 MB"


@pytest.mark.parametrize("path,call", [
    (API / "services" / "model_fetch.py", "FetchError"),
    (API / "services" / "embedding_models.py", "RuntimeError"),
    (API / "routers" / "embeddings.py", "HTTPException"),
    (API / "routers" / "embeddings.py", "SleepWriting"),
])
def test_every_error_the_person_reads_is_plain(path, call):
    sentences = _literals(path, call)
    assert sentences, f"no {call} sentence found in {path.name}: the scan is reading nothing"
    for sentence in sentences:
        if "Hugging Face" in sentence:
            # The larger version's account flow (Advanced): it names the person's own account and its key, and
            # still never says token, model or license.
            assert not re.search(r"\b(tokens?|models?|license)\b", sentence, re.I), sentence
            continue
        _plain(sentence)


def test_a_missing_pins_file_never_shows_a_repo_path(tmp_path, monkeypatch):
    monkeypatch.setattr(model_fetch, "PINS", tmp_path / "missing.lock.json")
    with pytest.raises(model_fetch.FetchError) as caught:
        model_fetch.pins()
    _plain(str(caught.value))


def _reset():
    em.JOB._set(state="idle", step="", error="", part="", done=0, total=0)


def test_the_job_says_which_part_and_how_many_bytes(tmp_path, monkeypatch):
    seen: list[dict] = []

    def fake_install_vision(models_dir, progress=None, **kw):
        progress("download", 100_000_000, 309_000_000)
        seen.append(em.JOB.snapshot())
        progress("prepare", 0, 0)
        seen.append(em.JOB.snapshot())
        progress("warm", 0, 0)
        seen.append(em.JOB.snapshot())

    monkeypatch.setattr(model_fetch, "install_vision", fake_install_vision)
    try:
        em._run_vision_download({"CICADA_HOME": str(tmp_path)})
        assert seen[0] == {"state": "installing", "step": "Downloading — 100 of 309 MB", "error": "",
                           "part": em.PART_VISION, "done": 100_000_000, "total": 309_000_000}
        assert seen[1]["step"] == em.STEP_CHECKING and seen[1]["total"] == 0
        assert seen[2]["step"] == em.STEP_SETTING_UP, "the image download names no other part (was 'search model')"
        assert em.JOB.snapshot()["state"] == "done" and em.JOB.snapshot()["part"] == em.PART_VISION
    finally:
        _reset()


def test_the_text_and_larger_downloads_say_their_part(tmp_path, monkeypatch):
    monkeypatch.setattr(model_fetch, "install", lambda models_dir, progress=None, **kw: progress("download", 1, 2))
    try:
        em._run_download(None, None, {"CICADA_HOME": str(tmp_path)})
        assert em.JOB.snapshot()["part"] == em.PART_TEXT
        monkeypatch.setattr(em, "sentence_transformers_available", lambda: True)
        monkeypatch.setattr(em, "_download_model", lambda token, environ: str(tmp_path / "m"))
        em._run_install("hf_" + "x" * 30, {"CICADA_HOME": str(tmp_path)})
        snap = em.JOB.snapshot()
        assert snap["part"] == em.PART_LARGER and snap["state"] == "done"
        assert "hf_" not in json.dumps(snap)
    finally:
        _reset()


def test_the_image_size_says_whether_it_includes_the_text_part(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    pins = {"id": "x", "revision": "r1", "dir_name": "eg2",
            "files": [{"path": "a", "size": 500, "sha256": "0"}],
            "vision_files": [{"path": "v", "size": 300, "sha256": "0"}]}
    monkeypatch.setattr(model_fetch, "pins", lambda: pins)
    monkeypatch.setattr(model_fetch, "vision_installed", lambda folder, p=None: False)
    monkeypatch.setattr(em, "neural_engine_supported", lambda: True)
    monkeypatch.setattr(model_fetch, "installed_revision", lambda folder: None)
    both = em.vision_status()
    assert both["download_bytes"] == 800 and both["includes_text"] is True
    monkeypatch.setattr(model_fetch, "installed_revision", lambda folder: "r1")
    alone = em.vision_status()
    assert alone["download_bytes"] == 300 and alone["includes_text"] is False
    monkeypatch.setattr(model_fetch, "vision_installed", lambda folder, p=None: True)
    assert em.vision_status()["includes_text"] is False, "nothing to download includes nothing"


def test_the_status_route_carries_the_part_and_the_combined_size(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    bank = tmp_path / "bank"
    bank.mkdir()
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(em, "vision_status", lambda environ=None: {
        "supported": True, "installed": False, "download_bytes": 894, "includes_text": True})
    config.get_settings.cache_clear()
    em.JOB._set(state="installing", step="Downloading — 1 of 2 MB", part=em.PART_TEXT, done=1, total=2)
    try:
        with TestClient(main.app) as client:
            body = client.get("/embeddings").json()
        assert body["install"]["part"] == "text" and body["install"]["done"] == 1 and body["install"]["total"] == 2
        assert body["vision"] == {"supported": True, "installed": False, "downloadBytes": 894, "includesText": True}
    finally:
        _reset()
        config.get_settings.cache_clear()


def test_the_sharper_option_states_its_download_size(tmp_path, monkeypatch):
    monkeypatch.setattr(model_fetch, "total_bytes", lambda p=None: 585_000_000)
    assert em._download_bytes(em.PREFERRED_ID) == 585_000_000
    assert em._download_bytes(em.SMALL_ID) == 0 and em._download_bytes(em.LARGE_ID) == 0

    def broken(p=None):
        raise model_fetch.FetchError("x")

    monkeypatch.setattr(model_fetch, "total_bytes", broken)
    assert em._download_bytes(em.PREFERRED_ID) == 0, "no pins: no size, never a guess"
