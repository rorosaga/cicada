"""G66 — the one decay resolver: class vocabulary, precedence, rail, lookup."""

from __future__ import annotations

from api.models.schemas import (
    AGENT_PRODUCIBLE_DECAY_CLASSES,
    CLAIM_DECAY_MULTIPLIERS,
    DECAY_CLASS_RATES,
    DecayClass,
)
from api.services import decay_policy, markdown_parser


# --- vocabulary -------------------------------------------------------------


def test_rates_and_multipliers_cover_every_class():
    assert set(DECAY_CLASS_RATES) == set(DecayClass)
    assert set(CLAIM_DECAY_MULTIPLIERS) == set(DecayClass)
    assert DECAY_CLASS_RATES == {
        DecayClass.evergreen: 0.0,
        DecayClass.durable: 0.02,
        DecayClass.active: 0.05,
        DecayClass.volatile: 0.15,
    }
    assert CLAIM_DECAY_MULTIPLIERS == {
        DecayClass.evergreen: 0.0,
        DecayClass.durable: 0.5,
        DecayClass.active: 1.0,
        DecayClass.volatile: 2.0,
    }


def test_agent_producible_set_excludes_evergreen():
    assert AGENT_PRODUCIBLE_DECAY_CLASSES == frozenset(
        {DecayClass.durable, DecayClass.active, DecayClass.volatile}
    )


# --- coerce / agent_class ---------------------------------------------------


def test_coerce_accepts_exact_values_and_sloppy_casing():
    assert decay_policy.coerce("evergreen") is DecayClass.evergreen
    assert decay_policy.coerce("  Durable ") is DecayClass.durable
    assert decay_policy.coerce(DecayClass.volatile) is DecayClass.volatile


def test_coerce_rejects_junk_silently():
    for bad in [None, "", "forever", "0.05", 3, "unlimited"]:
        assert decay_policy.coerce(bad) is None, bad


def test_agent_class_drops_evergreen_but_keeps_the_other_three():
    assert decay_policy.agent_class("evergreen") is None
    assert decay_policy.agent_class("EVERGREEN") is None
    assert decay_policy.agent_class("volatile") is DecayClass.volatile
    assert decay_policy.agent_class("durable") is DecayClass.durable
    assert decay_policy.agent_class("active") is DecayClass.active
    assert decay_policy.agent_class("nonsense") is None


# --- resolve ----------------------------------------------------------------


def test_explicit_class_wins_over_legacy_type_inference():
    cls, rate = decay_policy.resolve({"type": "media", "decay_class": "volatile"})
    assert cls is DecayClass.volatile
    assert rate == 0.15


def test_explicit_numeric_rate_wins_over_the_class_map_for_decaying_classes():
    cls, rate = decay_policy.resolve(
        {"type": "concept", "decay_class": "durable", "decay_rate": 0.07}
    )
    assert cls is DecayClass.durable, "the class stays as the label"
    assert rate == 0.07, "an explicit numeric that differs from the map wins"


def test_evergreen_always_resolves_to_a_zero_rate():
    # An evergreen page carrying a stale legacy numeric must still never fade:
    # the class contract is absolute, so it pins the rate.
    cls, rate = decay_policy.resolve(
        {"type": "media", "decay_class": "evergreen", "decay_rate": 0.03}
    )
    assert (cls, rate) == (DecayClass.evergreen, 0.0)


def test_legacy_media_page_infers_evergreen():
    cls, rate = decay_policy.resolve({"type": "media", "decay_rate": 0.03})
    assert (cls, rate) == (DecayClass.evergreen, 0.0)


def test_legacy_skill_page_infers_durable_keeping_its_own_rate():
    cls, rate = decay_policy.resolve({"type": "skill", "decay_rate": 0.02})
    assert (cls, rate) == (DecayClass.durable, 0.02)


def test_everything_else_infers_active_with_the_pages_existing_rate():
    assert decay_policy.resolve({"type": "person", "decay_rate": 0.05}) == (
        DecayClass.active,
        0.05,
    )
    assert decay_policy.resolve({"type": "project", "decay_rate": 0.09}) == (
        DecayClass.active,
        0.09,
    )


def test_missing_rate_falls_back_to_the_default():
    assert decay_policy.resolve({"type": "tool"}) == (DecayClass.active, 0.05)
    assert decay_policy.resolve({}) == (DecayClass.active, 0.05)


def test_unparseable_rate_never_raises():
    assert decay_policy.resolve({"type": "tool", "decay_rate": "fast"}) == (
        DecayClass.active,
        0.05,
    )


# --- default_class_for ------------------------------------------------------


def test_ingest_writers_default_to_evergreen():
    for source in ["media", "bookmark", "rss", "pdf", "ingest"]:
        assert decay_policy.default_class_for("media", source) is DecayClass.evergreen


def test_skill_defaults_to_durable_and_media_type_to_evergreen():
    assert decay_policy.default_class_for("skill") is DecayClass.durable
    assert decay_policy.default_class_for("media") is DecayClass.evergreen


def test_everything_else_defaults_to_active():
    for t in ["person", "project", "company", "concept", "tool", "location", "directory"]:
        assert decay_policy.default_class_for(t) is DecayClass.active
    assert decay_policy.default_class_for(None) is DecayClass.active


def test_volatile_is_never_a_default():
    assert DecayClass.volatile not in {
        decay_policy.default_class_for(t)
        for t in ["person", "project", "skill", "media", "tool", None]
    }


# --- frontmatter_fields -----------------------------------------------------


def test_frontmatter_fields_pairs_the_label_with_its_mapped_rate():
    assert decay_policy.frontmatter_fields(DecayClass.evergreen) == {
        "decay_class": "evergreen",
        "decay_rate": 0.0,
    }
    assert decay_policy.frontmatter_fields(DecayClass.durable) == {
        "decay_class": "durable",
        "decay_rate": 0.02,
    }


# --- class_lookup -----------------------------------------------------------


def _page(memory, entity_id: str, fm_extra: dict) -> None:
    ents = memory / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    fm = {"name": entity_id, "type": "concept", "status": "active", "confidence": 0.7}
    fm.update(fm_extra)
    markdown_parser.write(ents / f"{entity_id}.md", fm, "Body.")


def test_class_lookup_reads_pages_and_defaults_unknown_ids_to_active(tmp_path):
    _page(tmp_path, "bookmark", {"type": "media"})
    _page(tmp_path, "preference", {"type": "skill"})
    _page(tmp_path, "job", {"decay_class": "volatile"})

    lookup = decay_policy.class_lookup(tmp_path)

    assert lookup("bookmark") is DecayClass.evergreen
    assert lookup("preference") is DecayClass.durable
    assert lookup("job") is DecayClass.volatile
    assert lookup("never-heard-of-it") is DecayClass.active


def test_class_lookup_memoises_so_one_sleep_cycle_reads_a_page_once(tmp_path, monkeypatch):
    _page(tmp_path, "job", {"decay_class": "volatile"})
    calls: list[str] = []
    real_parse = markdown_parser.parse

    def counting_parse(path):
        calls.append(str(path))
        return real_parse(path)

    monkeypatch.setattr(decay_policy.markdown_parser, "parse", counting_parse)
    lookup = decay_policy.class_lookup(tmp_path)
    assert lookup("job") is DecayClass.volatile
    assert lookup("job") is DecayClass.volatile
    assert len(calls) == 1


def test_class_lookup_on_a_missing_entities_dir_never_raises(tmp_path):
    lookup = decay_policy.class_lookup(tmp_path / "nope")
    assert lookup("anything") is DecayClass.active
