"""F1 (R-FX8) — no server reader turns the claims fence into prose.

`claims.write_claims` appends the fence after a page's last section, so on a
Summary-only page it sits inside the Summary as far as a section reader can
tell. `summarize_for_recall`, `evidence.source_text` and `state_dictionary`
strip it first; these three did not."""
from __future__ import annotations

from api.routers.entities import _build_media_block
from api.services.graph_builder import summarize
from api.services.hub_builder import _one_line_summary

FENCE = "`" * 3
BLOCK = (f"{FENCE}claims\n- id: clm_alpha\n  text: alpha-project uses sqlite-vec\n"
         f"  subject: alpha-project\n{FENCE}\n")
MEDIA = {"media": {"url": "https://arxiv.org/abs/2401.00001", "media_type": "url", "kind": "paper"}}


def test_the_graph_preview_never_shows_the_fence():
    assert summarize(f"## Summary\nAlpha Project keeps notes.\n\n{BLOCK}") == "Alpha Project keeps notes."
    assert summarize(f"## Summary\n\n{BLOCK}") is None
    assert summarize(BLOCK) is None


def test_a_media_description_stops_before_the_fence():
    assert _build_media_block(MEDIA, f"## Summary\nSaved paper — Paper Alpha.\n\n{BLOCK}").description == \
        "Saved paper — Paper Alpha."
    assert _build_media_block(MEDIA, f"## Summary\n\n{BLOCK}").description is None


def test_a_hub_one_liner_never_reads_yaml():
    # An empty Summary still falls back to the heading word (a pre-existing
    # quirk of `_one_line_summary`, out of scope) — what matters is no YAML.
    assert "clm" not in _one_line_summary(f"## Summary\n\n{BLOCK}")
    assert _one_line_summary(f"## Summary\nAlpha Project keeps notes.\n\n{BLOCK}") == "Alpha Project keeps notes."
