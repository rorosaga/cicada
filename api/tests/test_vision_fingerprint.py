"""Vision item 3 (2026-10-28): the image encoder's preprocessing is fingerprinted, so a stored image vector is
re-embedded only when the recipe or the decoder really changed — never on a restart, never for nothing.

No model runs here: the fingerprint covers what happens BEFORE the model (the decode and the feed `inputs` cuts).
The one test that reads macOS's own decoder is skipped where `sips` is absent."""
from __future__ import annotations

import numpy as np
import pytest

from api.services import image_decode, vision_embedder

#: The fingerprint of the recipe with a nearest-neighbour decoder (`_nearest`): pinned so a change to `inputs`,
#: `plan_size` or any recipe constant turns this red. If you changed the preprocessing on purpose, re-pin it here AND
#: expect every stored image vector to re-embed once (the stamp moves with it; `LEGACY_FINGERPRINT` keeps describing
#: the pipeline the pre-stamp vectors were made with).
PINNED_NEAREST = "6b5115d66d24"


def _nearest(data: bytes, *, size) -> np.ndarray:
    rgb = vision_embedder.reference_rgb()
    w, h = size
    ys = (np.arange(h) * rgb.shape[0]) // h
    xs = (np.arange(w) * rgb.shape[1]) // w
    return rgb[ys][:, xs]


def test_the_reference_picture_is_deterministic_and_a_real_png():
    a, b = vision_embedder.reference_png(), vision_embedder.reference_png()
    assert a == b and image_decode.sniff(a) == "png"
    assert image_decode.dimensions(a) == vision_embedder.REFERENCE_SIZE


def test_the_recipe_is_pinned():
    assert vision_embedder.fingerprint(_nearest) == PINNED_NEAREST


def test_a_decoder_that_draws_other_pixels_moves_the_fingerprint():
    def brighter(data, *, size):
        return np.clip(_nearest(data, size=size).astype(np.int16) + 1, 0, 255).astype(np.uint8)

    assert vision_embedder.fingerprint(brighter) != vision_embedder.fingerprint(_nearest)
    assert vision_embedder.fingerprint(_nearest) == vision_embedder.fingerprint(_nearest), "stable for one decoder"


def test_a_changed_recipe_moves_the_fingerprint(monkeypatch):
    before = vision_embedder.fingerprint(_nearest)
    original = vision_embedder.recipe
    monkeypatch.setattr(vision_embedder, "recipe", lambda: {**original(), "version": 2})
    assert vision_embedder.fingerprint(_nearest) != before


def test_a_pre_stamp_vector_is_current_only_while_the_pipeline_measures_the_legacy_fingerprint():
    model = "google/embeddinggemma-2:768"
    legacy = vision_embedder.LEGACY_FINGERPRINT
    assert vision_embedder.stamp_current(model, model, legacy), "adding the stamp re-embeds nothing"
    assert not vision_embedder.stamp_current(model, model, "abcdefabcdef"), "a changed pipeline re-embeds once"
    stamped = vision_embedder.stamp_for(model, "abcdefabcdef")
    assert vision_embedder.stamp_current(stamped, model, "abcdefabcdef")
    assert not vision_embedder.stamp_current(stamped, "other/model:768", "abcdefabcdef")


@pytest.mark.skipif(not image_decode.available(), reason="macOS's sips decodes images here")
def test_this_macs_decoder_still_measures_the_pipeline_the_stored_vectors_were_made_with():
    """Red after an OS update that changed how `sips` resamples: the design index will re-embed every picture once
    (correctly). Re-pin `LEGACY_FINGERPRINT` only if the change is understood; the stamp already did the right thing."""
    vision_embedder._FINGERPRINTS.clear()
    assert vision_embedder.fingerprint() == vision_embedder.LEGACY_FINGERPRINT
