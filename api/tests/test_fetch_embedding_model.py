"""A developer checkout fetches the release's own embedding model (fix/dev-embeddings).

One source of truth: ``scripts/fetch-embedding-model.sh`` reads the pins in
``scripts/release/inputs.env`` and is the only code that downloads, checks and lays out
the model — the release build calls it too. Run here against ``file://`` copies, so
nothing touches the network.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from api.services import onnx_embedder

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fetch-embedding-model.sh"
INPUTS = ROOT / "scripts" / "release" / "inputs.env"


def _inputs(tmp_path: Path, *, corrupt: bool = False) -> Path:
    """A copy of the real inputs.env whose model base URL is a local folder of fake files."""
    upstream = tmp_path / "upstream"
    (upstream / "onnx").mkdir(parents=True, exist_ok=True)
    files = {"onnx/model_quantized.onnx": b"onnx-bytes", "tokenizer.json": b"{}", "config.json": b"{}"}
    lines = []
    for src, data in files.items():
        (upstream / src).write_bytes(data)
        sha = hashlib.sha256(b"tampered" if corrupt and src == "tokenizer.json" else data).hexdigest()
        dest = {"onnx/model_quantized.onnx": "model.onnx"}.get(src, src)
        lines.append(f"{src}:{dest}:{sha}")
    text = INPUTS.read_text(encoding="utf-8")
    text = re.sub(r'^MODEL_FILES="[^"]*"', 'MODEL_FILES="' + "\n".join(lines) + '"', text, flags=re.M)
    text += f'\nMODEL_BASE_URL="file://{upstream}"\n'
    out = tmp_path / "inputs.env"
    out.write_text(text, encoding="utf-8")
    return out


def _run(tmp_path: Path, inputs: Path, dest: Path | None) -> subprocess.CompletedProcess:
    env = {**os.environ, "CICADA_RELEASE_INPUTS": str(inputs), "CICADA_RELEASE_CACHE": str(tmp_path / "cache"),
           "HOME": str(tmp_path / "home"), "CICADA_HOME": str(tmp_path / "cicada-home")}
    args = [str(dest)] if dest is not None else []
    return subprocess.run(["/bin/bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)


def test_the_fetch_lays_out_a_model_the_embedder_finds(tmp_path):
    dest = tmp_path / "models"
    done = _run(tmp_path, _inputs(tmp_path), dest)
    assert done.returncode == 0, done.stderr
    spec = onnx_embedder.find(onnx_embedder.DEFAULT_ID, {"CICADA_BUNDLED_MODELS": str(dest)})
    assert spec is not None and spec.dimensions == 384 and spec.pooling == "mean"
    assert spec.query_prefix == "query: " and spec.document_prefix == "passage: "
    manifest = json.loads((spec.path / onnx_embedder.MANIFEST).read_text())
    assert manifest["license"].startswith("MIT")
    again = _run(tmp_path, _inputs(tmp_path), dest)
    assert again.returncode == 0, "a second run is a no-op, not an error"


def test_a_checksum_mismatch_installs_nothing(tmp_path):
    dest = tmp_path / "models"
    done = _run(tmp_path, _inputs(tmp_path, corrupt=True), dest)
    assert done.returncode != 0 and "sha256 mismatch" in done.stderr
    assert onnx_embedder.available({"CICADA_BUNDLED_MODELS": str(dest)}) == []


def test_the_default_destination_is_the_cicada_home(tmp_path):
    done = _run(tmp_path, _inputs(tmp_path), None)  # no argument
    assert done.returncode == 0, done.stderr
    assert onnx_embedder.available({"CICADA_HOME": str(tmp_path / "cicada-home")})


def test_the_release_build_and_the_checkout_share_one_copy_of_the_pins():
    build = (ROOT / "scripts/release/build-backend.sh").read_text(encoding="utf-8")
    assert "fetch-embedding-model.sh" in build, "the release build fetches through the same script"
    assert "MODEL_FILES" not in build and "cicada-model.json" not in build, "no second copy of the model's layout"
    pins = re.findall(r"[0-9a-f]{64}", INPUTS.read_text(encoding="utf-8"))
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    for rel in tracked:
        if rel == "scripts/release/inputs.env" or not rel.endswith((".sh", ".py", ".env", "Makefile", ".swift")):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        assert not [p for p in pins if p in text], f"{rel} repeats a pinned hash"


def test_make_and_install_fetch_the_model():
    assert "fetch-embedding-model.sh" in (ROOT / "Makefile").read_text(encoding="utf-8")
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "fetch-embedding-model.sh" in install
    assert 'ensure_env CICADA_EMBEDDING_MODE "openai"' not in install, "a fresh checkout embeds on this Mac"


def test_an_empty_or_unsafe_model_folder_name_deletes_nothing(tmp_path):
    """MODEL_DIR_NAME feeds `rm -rf "$MODELS/$MODEL_DIR_NAME"`: unset, empty or a path, the script stops first."""
    dest = tmp_path / "models"
    keep = dest / "google--embeddinggemma-300m" / "kept.bin"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"x")
    for bad in ('MODEL_DIR_NAME=""', 'MODEL_DIR_NAME=".."', 'MODEL_DIR_NAME="a/b"'):
        inputs = _inputs(tmp_path)
        inputs.write_text(re.sub(r'^MODEL_DIR_NAME="[^"]*"', bad, inputs.read_text(), flags=re.M))
        done = _run(tmp_path, inputs, dest)
        assert done.returncode != 0, bad
        assert keep.exists() and list(dest.iterdir()) == [keep.parent], bad
