"""M5f Stage 5.57 — link-enrichment subagent (the John→websites design).

Hermetic: NO network, NO real LLM. The summarizer is injected via ``summarize_fn``
and the candidate set comes from on-disk media entities. Covers:

* the zero-LLM reuse path (§2a): a media page with a substantive ``## Description``
  gets a ``describes`` claim promoted into its ```claims block — no fetch, no LLM;
* a ``recommends`` claim is written on a person who shares the media's source
  episode, with bidirectional ![[…]] transclusion in both pages;
* idempotency: ``enrichment_attempted`` short-circuits a second pass;
* offline / kill-switch safety: ``link_enrich_enabled=False`` is a clean no-op.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import asyncio

from api.services import link_enrichment, markdown_parser
from api.services.claims import parse_claims


def _settings(memory: Path, **over):
    base = dict(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        link_enrich_enabled=True,
        link_enrich_max_per_cycle=20,
        link_enrich_min_desc_len=120,
        link_enrich_excerpt_chars=2000,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _media(memory: Path, stem: str, name: str, url: str, *, episode: str, description: str = ""):
    fm = {
        "name": name,
        "type": "media",
        "status": "active",
        "source_episodes": [episode],
        "media": {"url": url, "media_type": "website"},
    }
    body = "## Summary\nA saved link."
    if description:
        body += f"\n\n## Description\n{description}"
    markdown_parser.write(memory / "entities" / f"{stem}.md", fm, body)


def _person(memory: Path, stem: str, name: str, *, episode: str):
    markdown_parser.write(
        memory / "entities" / f"{stem}.md",
        {"name": name, "type": "person", "source_episodes": [episode]},
        "## Summary\nA person.",
    )


def test_reuse_existing_description_promotes_to_claim(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    long_desc = (
        "A curated list of robotics conferences and workshops for graduate "
        "researchers, with submission deadlines and location details."
    )
    _media(memory, "media-robotics-conf", "Robotics Conf List",
           "https://robotics.example.com", episode="ep_2026-06-17_003",
           description=long_desc)

    n = asyncio.run(link_enrichment.enrich_media_links(
        memory, [], _settings(memory),
        summarize_fn=None,  # never called — OG description is substantive
    ))
    assert n == 1
    parsed = markdown_parser.parse(memory / "entities" / "media-robotics-conf.md")
    claims = parse_claims(parsed.body)
    desc = [c for c in claims if c.predicate == "describes"]
    assert desc and long_desc[:20] in desc[0].object
    assert desc[0].source_trust == "agent_extracted"
    assert parsed.frontmatter.get("enrichment_attempted") is True


def test_recommends_claim_and_bidirectional_transclusion(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    ep = "ep_2026-06-17_003"
    _person(memory, "john", "John", episode=ep)
    _media(memory, "media-humanoid-2026", "Humanoid Robotics 2026",
           "https://humanoid2026.example.org", episode=ep,
           description="The 2026 International Conference on Humanoid Robots in "
                       "Tokyo, with the full technical program, an invited "
                       "speaker list, workshop tracks and registration details "
                       "for graduate researchers.")

    # `changes` carries John as a person resolved this cycle, sharing the episode.
    changes = [{"id": "john", "action": "update", "source_episodes": [ep],
                "entity": {"type": "person"}}]
    n = asyncio.run(link_enrichment.enrich_media_links(
        memory, changes, _settings(memory), summarize_fn=None,
    ))
    assert n >= 1

    john = markdown_parser.parse(memory / "entities" / "john.md")
    john_claims = parse_claims(john.body)
    recs = [c for c in john_claims if c.predicate == "recommends"]
    assert recs and recs[0].object == "media-humanoid-2026"
    # Bidirectional transclusion: John embeds the site, the site embeds John.
    assert "![[media-humanoid-2026]]" in john.body
    site = markdown_parser.parse(memory / "entities" / "media-humanoid-2026.md").body
    assert "![[john]]" in site


def test_idempotent_skip_on_enrichment_attempted(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    _media(memory, "media-x", "X", "https://x.example.com",
           episode="ep_1", description="A long enough description sentence here.")
    fp = memory / "entities" / "media-x.md"
    parsed = markdown_parser.parse(fp)
    parsed.frontmatter["enrichment_attempted"] = True
    markdown_parser.write(fp, parsed.frontmatter, parsed.body)

    n = asyncio.run(link_enrichment.enrich_media_links(memory, [], _settings(memory)))
    assert n == 0  # already attempted → skipped


def test_kill_switch_is_noop(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    _media(memory, "media-y", "Y", "https://y.example.com",
           episode="ep_1", description="A long enough description sentence here.")

    n = asyncio.run(link_enrichment.enrich_media_links(
        memory, [], _settings(memory, link_enrich_enabled=False)
    ))
    assert n == 0
    parsed = markdown_parser.parse(memory / "entities" / "media-y.md")
    assert parse_claims(parsed.body) == []


def test_thin_description_uses_injected_summarizer(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    # Thin OG description (a tagline, < min_desc_len, no sentence punctuation).
    _media(memory, "media-thin", "Thin Site", "https://thin.example.com",
           episode="ep_1", description="robotics hub")

    calls = {"n": 0}

    async def fake_summarize(title, url, settings):
        calls["n"] += 1
        return "A research hub aggregating robotics labs, datasets and benchmarks."

    n = asyncio.run(link_enrichment.enrich_media_links(
        memory, [], _settings(memory), summarize_fn=fake_summarize,
    ))
    assert n == 1
    assert calls["n"] == 1  # the LLM summarizer WAS invoked for the thin desc
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "media-thin.md").body)
    assert any(c.predicate == "describes" and "robotics labs" in c.object for c in claims)


def test_no_media_entities_is_noop(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    markdown_parser.write(
        memory / "entities" / "cicada.md",
        {"name": "Cicada", "type": "project"}, "## Summary\nx",
    )
    n = asyncio.run(link_enrichment.enrich_media_links(memory, [], _settings(memory)))
    assert n == 0
