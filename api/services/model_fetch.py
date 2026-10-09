"""Fetch EmbeddingGemma 2 for the Neural Engine once, into ``$CICADA_HOME/models`` (owner 2026-10-09).

One implementation for every door: Settings → Memory → Search model in a release app (``embedding_models``'
install job), ``make embedding-model-gemma2`` and ``install.sh`` in a checkout (``python -m
api.services.model_fetch``). It reads the pins in ``api/data/embeddinggemma-2.lock.json`` — one revision of
``FluidInference/embeddinggemma-2-coreml``, every file's size and sha256 — and nothing else is fetched: no
other URL, no other revision, never the audio or vision encoders.

**Not bundled.** The model is about 585 MB to download (≈ 340 MB more in the release zip) and runs only on
macOS 15 and later; the release keeps the small multilingual model bundled as the floor that runs everywhere.

**Steps, each leaving nothing half-done** (``.<dir>.partial`` beside the destination, swapped in whole):
download and verify every file (a mismatch drops the file and stops); write ``cicada-model.json`` (``"runtime":
"coreml"``, the widths, the task prefixes from the verified ``config.json``) and ``NOTICE.txt``; compile the
``.mlpackage`` to ``.mlmodelc`` (about 2 s) and drop the package; swap the folder in; then **warm** it from its
final path — the Neural Engine compile, about 90 s once, cached by macOS against that path — so nobody's first
search pays it. A fetch onto a folder already at the pinned revision does nothing.

**The network.** Only after a person's click or command — never on its own. 30 s to connect, 60 s between bytes,
three tries a file; the person's credentials are never sent. The license is Apache 2.0, and deployments must
follow the Gemma Prohibited Use Policy; ``NOTICE.txt`` says both beside the files.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

PINS = Path(__file__).resolve().parents[1] / "data" / "embeddinggemma-2.lock.json"
CHUNK = 1 << 20
CONNECT_TIMEOUT_S = 30.0
READ_TIMEOUT_S = 60.0
TRIES = 3

Progress = Callable[[str, int, int], None]   # (phase, done bytes, total bytes)

NOTICE = """EmbeddingGemma 2 — text encoder, Core ML export for the Apple Neural Engine.

Source: https://huggingface.co/{repo} at revision {revision}
Base model: https://huggingface.co/{base_model} (Google DeepMind)
License: Apache License 2.0 — https://www.apache.org/licenses/LICENSE-2.0
Use of this model must follow the Gemma Prohibited Use Policy:
https://ai.google.dev/gemma/prohibited_use_policy

Downloaded by Cicada from the pinned revision above; each file was checked against its sha256 before it was
installed. Cicada does not redistribute these files. README.md beside this notice is the export's own card.
"""


class FetchError(RuntimeError):
    """A sentence the person reads."""


def pins() -> dict:
    return json.loads(PINS.read_text(encoding="utf-8"))


def total_bytes(p: dict | None = None) -> int:
    return sum(int(f["size"]) for f in (p or pins())["files"])


def destination(models_dir: Path, p: dict | None = None) -> Path:
    name = str((p or pins())["dir_name"])
    if "/" in name or name.startswith("."):
        raise FetchError("The model's folder name in the pins is not a plain name.")
    return Path(models_dir) / name


def installed_revision(folder: Path) -> str | None:
    """The pinned revision a complete folder was installed from, or None."""
    from api.services import coreml_embedder, onnx_embedder

    try:
        meta = json.loads((folder / onnx_embedder.MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not coreml_embedder.files_complete(folder):
        return None
    return str(meta.get("revision") or "") or None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _url(p: dict, rel: str) -> str:
    return f"https://huggingface.co/{p['repo']}/resolve/{p['revision']}/{rel}"


def _download(url: str, dest: Path, size: int, sha: str, on_bytes: Callable[[int], None], client) -> None:
    """``url`` into ``dest`` (size and sha256 checked while streaming); retried, never kept on a mismatch."""
    last: Exception | None = None
    for attempt in range(TRIES):
        dest.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        got = 0
        try:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for block in resp.iter_bytes(CHUNK):
                        fh.write(block)
                        h.update(block)
                        got += len(block)
                        on_bytes(len(block))
                        if got > size:
                            break
        except Exception as exc:  # noqa: BLE001 — a network failure is retried, then said in words
            last = exc
            on_bytes(-got)
            dest.unlink(missing_ok=True)
            time.sleep(min(2 ** attempt, 5))
            continue
        if got != size or h.hexdigest() != sha:
            dest.unlink(missing_ok=True)
            raise FetchError("A downloaded file didn't match its checksum, so nothing was installed. Try again later.")
        return
    raise FetchError("The download stopped. Check your connection and try again.") from last


def _client():
    import httpx

    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                        headers={"User-Agent": "Cicada (search model download)"})


def _compile(stage: Path) -> None:
    import warnings

    from api.services import coreml_embedder

    ct = coreml_embedder.import_coremltools()

    package = stage / coreml_embedder.PACKAGE
    compiled = stage / coreml_embedder.COMPILED
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tmp = ct.models.utils.compile_model(str(package))
        shutil.rmtree(compiled, ignore_errors=True)
        shutil.move(str(tmp), str(compiled))
    except Exception as exc:  # noqa: BLE001
        raise FetchError("This Mac couldn't prepare the search model. Make sure macOS is up to date, "
                         "then try again.") from exc
    shutil.rmtree(package, ignore_errors=True)  # the runtime reads only the compiled model


def _manifest(stage: Path, p: dict) -> dict:
    try:
        cfg = json.loads((stage / "config.json").read_text(encoding="utf-8"))
        prompts = cfg["prompts"]
        query_prefix, document_prefix = str(prompts["search_query"]), str(prompts["document"])
    except (OSError, ValueError, KeyError) as exc:
        raise FetchError("The model's settings file couldn't be read, so nothing was installed.") from exc
    return {
        "id": p["id"],
        "runtime": "coreml",
        "dimensions": int(p["dimensions"]),
        "widths": [int(w) for w in p["widths"]],
        "max_tokens": int(p["max_tokens"]),
        "normalize": True,
        "query_prefix": query_prefix,
        "document_prefix": document_prefix,
        "source": f"https://huggingface.co/{p['repo']}/tree/{p['revision']}",
        "revision": p["revision"],
        "license": f"{p['license']} ({p['base_model']}); Gemma Prohibited Use Policy applies",
    }


def install(models_dir: Path, *, progress: Progress | None = None, client=None, compile_fn=None,
            warm: bool = True) -> Path:
    """Fetch, verify, compile and warm the pinned model into ``models_dir``; returns its folder."""
    from api.services import coreml_embedder

    p = pins()
    out = destination(models_dir, p)
    report = progress or (lambda phase, done, total: None)
    if installed_revision(out) == p["revision"]:
        if warm:
            _warm(out, report)
        return out
    if not coreml_embedder.supported() and compile_fn is None:
        raise FetchError("This search model needs macOS 15 or later on Apple silicon.")
    stage = Path(models_dir) / f".{out.name}.partial"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    total = total_bytes(p)
    done = 0

    def on_bytes(n: int) -> None:
        nonlocal done
        done += n
        report("download", done, total)

    try:
        own = client is None
        http = _client() if own else client
        try:
            for f in p["files"]:
                _download(_url(p, f["path"]), stage / f["path"], int(f["size"]), str(f["sha256"]), on_bytes, http)
        finally:
            if own:
                http.close()
        report("prepare", total, total)
        meta = _manifest(stage, p)
        (stage / "NOTICE.txt").write_text(NOTICE.format(**p), encoding="utf-8")
        (compile_fn or _compile)(stage)
        from api.services import onnx_embedder

        (stage / onnx_embedder.MANIFEST).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(out, ignore_errors=True)
        stage.rename(out)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    if warm:
        _warm(out, report)
    return out


def _warm(folder: Path, report: Progress) -> None:
    """Load every function once from its final path: the Neural Engine compile (≈ 90 s the first time)."""
    from api.services import coreml_embedder, onnx_embedder

    spec = onnx_embedder._read_spec(folder)
    if spec is None or not coreml_embedder.supported():
        return
    report("warm", 0, 0)
    try:
        coreml_embedder.CoreMLEmbedder(spec).warm()
    except Exception as exc:  # noqa: BLE001
        raise FetchError("The search model downloaded but this Mac couldn't load it. Restart Cicada and "
                         "try again.") from exc


def main(argv: list[str] | None = None) -> int:
    """``python -m api.services.model_fetch [MODELS_DIR]`` — what ``make embedding-model-gemma2`` runs."""
    from api.services import coreml_embedder, runtime_layout

    args = list(sys.argv[1:] if argv is None else argv)
    models = Path(args[0]).expanduser() if args else runtime_layout.cicada_home() / "models"
    if not coreml_embedder.supported():
        print("  EmbeddingGemma 2 needs macOS 15 or later on Apple silicon (and coremltools in this "
              "environment: uv sync --directory api). Search keeps the small model.", file=sys.stderr)
        return 2
    last = [0.0]

    def show(phase: str, done: int, total: int) -> None:
        now = time.monotonic()
        if phase == "download" and now - last[0] < 2 and done < total:
            return
        last[0] = now
        if phase == "download":
            print(f"  downloading {done / 1e6:.0f} of {total / 1e6:.0f} MB", file=sys.stderr, flush=True)
        elif phase == "prepare":
            print("  verified; compiling for this Mac", file=sys.stderr, flush=True)
        elif phase == "warm":
            print("  loading it on the Neural Engine once (about 90 s the first time)", file=sys.stderr, flush=True)

    try:
        out = install(models, progress=show)
    except FetchError as exc:
        print(f"  {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    os.environ.setdefault("CICADA_CAPTURE", "off")
    raise SystemExit(main())
