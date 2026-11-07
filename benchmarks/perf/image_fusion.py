"""How should a picture's score meet a sentence's? A measured comparison on synthetic vectors (vision item 3,
2026-10-28):

    api/.venv/bin/python -m benchmarks.perf.image_fusion [--seeds 3] [--json] [--all]

EmbeddingGemma 2 puts a picture and a sentence in one 768-wide space, but not on one scale: a text query's cosine to a
matching screenshot sits well below its cosine to an unrelated passage (the modality gap; the design board measured
text–image ≈ 0.2–0.35 against text–text ≈ 0.5–0.8). So a merged list ordered by raw cosine never shows a picture, and
one ordered by reciprocal rank always shows one — the best picture for "quarterly tax deadline" is ranked first among
pictures whether or not any picture is about it.

The corpus reproduces that geometry with no real data: ``CONCEPTS`` topics in ``CLUSTERS`` families (a sibling topic is
a hard negative); a text document is its topic plus noise plus a shared "text" offset; a picture is its topic at a
weaker weight plus noise plus a shared "image" offset (pictures sit in their own cone, as real image embeddings do); a
query is its topic plus noise plus the text offset. A query is about one topic; every item of that topic is relevant.
Four query sets: ``image`` (the topic has only pictures), ``text`` (only documents), ``both``, and ``none`` (a topic
with nothing in the corpus). Every method is scored on the one merged list a reader would see:

* ``cosine`` — raw cosine, both kinds together;
* ``rrf`` — reciprocal rank (k = 60) of the two per-kind lists, Cicada's fusion everywhere else;
* ``z_own`` — each kind's cosine minus that kind's mean for this query, over that kind's spread for this query
  (both exact from each kind's mean and covariance, ``moments``);
* ``z_shared`` — the same with one spread for both kinds (DigUp's recipe, G195);
* ``lift`` — each kind's cosine minus that kind's mean for this query, not divided (``image_index``'s choice).

and, for the pictures group on its own (how ``/search`` and recall show them), a floor: ``z_own@z2`` is DigUp's fixed
``z ≥ 2``; ``z_own@+m`` the best of ``n`` unrelated pictures (``√(2 ln n)``) plus ``m``; ``lift@x`` a lift of ``x``.
Columns: ``image.r1`` (the merged list's first row is right), ``pics_shown`` (the group shows anything),
``first_pic_right`` (it does and its first picture is right), ``both.ndcg10``, ``text.pic_in_top5`` (a picture pushed
into the merged top 5 of a documents-only query) and ``none.*``.

**What it settles, and what it cannot.** Raw cosine never shows a picture, and RRF puts one in the merged top 5 of
every documents-only query — so a kind's own mean must come off (``z_own`` and ``lift`` both keep pictures out of
documents-only lists). Isotropic noise cannot model the floor: here every query's spread over pictures is alike, so a
z floor looks usable. On the real encoder it is not (``benchmarks.perf.image_index_build``): a query about nothing
drawn has a tiny spread (σ ≈ 0.011 against ≈ 0.047), so dividing by it lifts the best unrelated picture to the same z as
a right one (2.6 against 2.2–3.3), while the undivided lift separates them (≤ 0.03 against 0.10–0.15). The floor is
therefore calibrated on the real encoder, and this file decides only the merged-list question.
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np

from api.services import image_index

DIM = 768
CONCEPTS = 400
CLUSTERS = 40
TEXT_NOISE = 1.3
IMAGE_NOISE = 1.3
QUERY_NOISE = 1.1
TEXT_PER = 6
IMAGES_PER = 3
QUERIES_PER_SET = 150
RRF_K = 60
TOP = 10
Z_MARGIN = 0.5
#: The columns the decision reads (``--all`` prints every one).
SHOWN = ("image.r1", "image.pictures_shown", "image.first_picture_right", "both.ndcg10", "text.picture_in_top5",
         "none.pictures_shown", "none.picture_in_top5")


def moments(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(mean, covariance)`` of a kind's unit vectors: a query's exact mean cosine over the kind is ``q·mean`` and its
    spread ``√(qᵀΣq)`` (``image_index`` stores only the mean: it scores by lift)."""
    x = np.asarray(vectors, dtype=np.float64)
    mu = x.mean(axis=0)
    centred = x - mu
    return mu.astype(np.float32), (centred.T @ centred / max(1, x.shape[0])).astype(np.float32)


def query_moments_many(queries: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    q = np.asarray(queries, dtype=np.float32)
    return q @ mu, np.sqrt(np.maximum(np.einsum("nd,nd->n", q @ cov, q), 1e-12))


def zscores(sims, mean: float, sd: float) -> np.ndarray:
    return (np.asarray(sims, dtype=np.float32) - mean) / max(sd, 1e-6)


def z_floor(n: int, margin: float = Z_MARGIN) -> float:
    """The best z of ``n`` unrelated items by chance, ``√(2 ln n)``, plus ``margin``."""
    return math.sqrt(2.0 * math.log(max(2, int(n)))) + margin


def _unit(m: np.ndarray) -> np.ndarray:
    return m / np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12)


def corpus(seed: int, *, image_weight: float = 0.55, gap: float = 1.6):
    """``(texts, text_topic, images, image_topic, queries)`` — queries as ``{set: [(vector, topic)]}``."""
    rng = np.random.default_rng(seed)
    # Topics come in families (CLUSTERS), so a near-miss topic is a hard negative, as "tax deadline" is to "tax form".
    families = _unit(rng.standard_normal((CLUSTERS, DIM)))
    family_of = rng.integers(0, CLUSTERS, size=CONCEPTS)
    topics = _unit(families[family_of] * 0.75 + _unit(rng.standard_normal((CONCEPTS, DIM))) * 0.66)
    text_off = _unit(rng.standard_normal(DIM)) * gap
    image_off = _unit(rng.standard_normal(DIM)) * gap
    # Which topics carry which kind: pictures only, documents only, both, and some with nothing (the "none" set).
    order = rng.permutation(CONCEPTS)
    image_only, text_only, both, absent = np.array_split(order, 4)
    with_text = np.concatenate([text_only, both])
    with_images = np.concatenate([image_only, both])

    def items(owner_topics, per, weight, offset, noise):
        topic_of = np.repeat(owner_topics, per)
        raw = (topics[topic_of] * weight + offset
               + _unit(rng.standard_normal((topic_of.size, DIM))) * noise)
        return _unit(raw), topic_of

    texts, text_topic = items(with_text, TEXT_PER, 1.0, text_off, TEXT_NOISE)
    images, image_topic = items(with_images, IMAGES_PER, image_weight, image_off, IMAGE_NOISE)

    def queries(pool):
        picked = rng.choice(pool, size=QUERIES_PER_SET, replace=True)
        raw = topics[picked] + text_off * 0.8 + _unit(rng.standard_normal((picked.size, DIM))) * QUERY_NOISE
        return list(zip(_unit(raw), picked))

    return texts, text_topic, images, image_topic, {"image": queries(image_only), "text": queries(text_only),
                                                    "both": queries(both), "none": queries(absent)}


def _ndcg(relevant: list[bool]) -> float:
    gains = sum(1.0 / math.log2(i + 2) for i, r in enumerate(relevant[:TOP]) if r)
    ideal_n = min(TOP, sum(relevant)) or 1
    ideal = sum(1.0 / math.log2(i + 2) for i in range(ideal_n))
    return gains / ideal


def _merged(method: str, ts: np.ndarray, is_: np.ndarray, tm, im, z_min: float | None):
    """``(kinds, indexes)`` of the top ``TOP`` for one query, best first (kind 0 = document, 1 = picture):
    ``ts``/``is_`` are its cosines to documents and pictures, ``tm``/``im`` the two kinds' ``(mean, sd)`` for it."""
    if method == "rrf":
        t_rank = np.empty(ts.size); t_rank[np.argsort(-ts, kind="stable")] = np.arange(ts.size)
        i_rank = np.empty(is_.size); i_rank[np.argsort(-is_, kind="stable")] = np.arange(is_.size)
        t_score, i_score = 1.0 / (RRF_K + t_rank + 1), 1.0 / (RRF_K + i_rank + 1)
    elif method == "cosine":
        t_score, i_score = ts, is_.copy()
    elif method == "lift":
        t_score, i_score = ts - tm[0], is_ - im[0]
        if z_min is not None:
            i_score = np.where(i_score >= z_min, i_score, -np.inf)
    else:
        if method == "z_shared":
            shared = math.sqrt((tm[1] ** 2 + im[1] ** 2) / 2)
            tm, im = (tm[0], shared), (im[0], shared)
        t_score, i_score = zscores(ts, *tm), zscores(is_, *im)
        if z_min is not None:
            i_score = np.where(i_score >= z_min, i_score, -np.inf)
    scores = np.concatenate([t_score, i_score])
    kinds = np.concatenate([np.zeros(ts.size, dtype=np.int8), np.ones(is_.size, dtype=np.int8)])
    idx = np.concatenate([np.arange(ts.size), np.arange(is_.size)])
    top = np.argpartition(-scores, TOP)[:TOP]
    top = top[np.argsort(-scores[top], kind="stable")]
    top = top[np.isfinite(scores[top])]
    return kinds[top], idx[top]


def run(seed: int, *, z_margin: float = Z_MARGIN, lift_min: float = image_index.LIFT_MIN, **geometry) -> dict:
    texts, text_topic, images, image_topic, qsets = corpus(seed, **geometry)
    t_mom, i_mom = moments(texts), moments(images)
    methods = {"cosine": None, "rrf": None, "z_own": None, "z_shared": None, "z_own@z2": 2.0}
    n_images = int(images.shape[0])
    for margin in sorted({0.0, 0.5, 1.0, 1.5, z_margin}):
        methods[f"z_own@+{margin:g}"] = z_floor(n_images, margin)
    methods["lift"] = None
    for bar in (0.04, 0.06, 0.08, lift_min):
        methods[f"lift@{bar:g}"] = bar
    # Every query's cosines and per-kind moments once (one matrix product per set), then each method ranks them.
    prepared = {}
    for qset, qs in qsets.items():
        q = np.stack([v for v, _t in qs]).astype(np.float32)
        prepared[qset] = (q @ texts.T, q @ images.T, query_moments_many(q, *t_mom),
                          query_moments_many(q, *i_mom), [t for _v, t in qs])
    out: dict = {}
    for name, floor in methods.items():
        base = name.split("@")[0]
        res = {}
        for qset, (tsims, isims, tmo, imo, topics) in prepared.items():
            r1 = nd = intrude = shown = top_ok = 0.0
            for j, topic in enumerate(topics):
                im = (float(imo[0][j]), float(imo[1][j]))
                kinds, idx = _merged(base, tsims[j], isims[j], (float(tmo[0][j]), float(tmo[1][j])), im, floor)
                rel = [bool((image_topic if k else text_topic)[i] == topic) for k, i in zip(kinds, idx)]
                r1 += rel[0] if rel else 0
                nd += _ndcg(rel)
                intrude += bool(kinds[:5].any())
                # The pictures group on its own (how /search and recall show them): is it shown, and is its first
                # picture right? Without a floor it is always shown.
                best = int(np.argmax(isims[j]))
                top_score = (float(isims[j][best]) - im[0] if base == "lift"
                             else float(zscores(isims[j][best], *im)))
                passes = floor is None or top_score >= floor
                shown += passes
                top_ok += passes and bool(image_topic[best] == topic)
            n = len(topics)
            res[qset] = {"r1": r1 / n, "ndcg10": nd / n, "picture_in_top5": intrude / n,
                         "pictures_shown": shown / n, "first_picture_right": top_ok / n}
        out[name] = res
    probe_q, probe_t = qsets["image"][0]
    out["_cosines"] = {"query_to_matching_picture": round(float(np.mean(images[image_topic == probe_t] @ probe_q)), 3),
                       "query_to_any_picture": round(float(np.mean(images @ probe_q)), 3),
                       "query_to_any_text": round(float(np.mean(texts @ probe_q)), 3)}
    return out


def summarize(runs: list[dict]) -> dict:
    names = [k for k in runs[0] if not k.startswith("_")]
    table = {}
    for name in names:
        table[name] = {}
        for qset in runs[0][name]:
            for metric in runs[0][name][qset]:
                vals = [r[name][qset][metric] for r in runs]
                table[name][f"{qset}.{metric}"] = round(float(np.mean(vals)), 3)
    return table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--margin", type=float, default=Z_MARGIN)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="every metric, not only the ones the decision reads")
    a = ap.parse_args()
    report = {}
    for label, geometry in (("gap 1.6 (default)", {}), ("gap 1.0", {"gap": 1.0}), ("gap 2.4", {"gap": 2.4}),
                            ("weak pictures 0.4", {"image_weight": 0.4})):
        runs = [run(seed, z_margin=a.margin, **geometry) for seed in range(a.seeds)]
        report[label] = {"cosines(seed 0)": runs[0]["_cosines"], "methods": summarize(runs)}
    if a.json:
        print(json.dumps(report, indent=2))
        return
    for label, body in report.items():
        print(f"\n== {label}  cosines: {body['cosines(seed 0)']}")
        cols = list(next(iter(body["methods"].values())))
        if not a.all:
            cols = [c for c in cols if c in SHOWN]
        print(f"{'method':<14}" + "".join(f"{c.replace('picture', 'pic'):>21}" for c in cols))
        for name, row in body["methods"].items():
            print(f"{name:<14}" + "".join(f"{row[c]:>21.3f}" for c in cols))


if __name__ == "__main__":
    main()
