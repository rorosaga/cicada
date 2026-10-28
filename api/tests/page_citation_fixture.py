"""A synthetic page whose lines carry write-time provenance (G118 ``section_provenance``), for the citation tests and
the shared page-blocks fixture. Placeholders only."""
from __future__ import annotations

from pathlib import Path

from api.services import evidence, markdown_parser, section_provenance
from api.services.claims import Evidence

EP_SAID = "ep_2026-10-01_001"
EP_LATER = "ep_2026-10-05_001"     # the same session as EP_SAID: one reference
EP_OTHER = "ep_2026-10-02_001"
EP_WEB = "ep_2026-10-03_001"

SAID = "Can we open the alpha-project studio there by December?"
BODY = """## Summary

A place.

## Article

### The place

Alpha Place is where the alpha-project studio is being built. It opens in December.

### Around it

It sits next to Beta City's old market.

## Key Facts

- It is in Beta City.
- Open on Saturdays.
"""

EPISODES = {
    EP_SAID: ({"title": "Studio plan", "source": "claude-code", "session_id": "sess-a",
               "timestamp": "2026-10-01T09:00:00+00:00"}, f"user: {SAID}\n\nassistant: Yes.\n"),
    EP_LATER: ({"title": "Studio plan", "source": "claude-code", "session_id": "sess-a",
                "timestamp": "2026-10-05T09:00:00+00:00"}, "user: It opens in December.\n"),
    EP_OTHER: ({"title": "Market walk", "source": "messages", "timestamp": "2026-10-02T18:00:00+00:00",
                "correspondent": {"name": "Bob Example"}}, "user: the market is next door\n"),
    EP_WEB: ({"title": "Opening hours", "source": "web-check", "timestamp": "2026-10-03T12:00:00+00:00"},
             "Open on Saturdays from 10.\n"),
}


def _stored(memory: Path, ep_id: str) -> str:
    return markdown_parser.parse(memory / "episodes" / f"{ep_id}.md").body or ""


def records(body: str, memory: Path) -> dict:
    """The write-time links: the first paragraph to the person's located words and the later episode of the same
    conversation; the second to another conversation (reasoning, no quote); the first fact to that conversation; the
    second fact to a looked-up page. Hashes are over the conversations as stored in ``memory``."""
    items = section_provenance.scan(body)
    article, facts = items["article"], items["key_facts"]
    said_body = _stored(memory, EP_SAID)
    start = said_body.index(SAID)
    quote = Evidence(episode=EP_SAID, start=start, end=start + len(SAID), kind="user",
                     hash=evidence.body_hash(said_body))
    later = Evidence(episode=EP_LATER, kind="reasoning", hash=evidence.body_hash(_stored(memory, EP_LATER)))
    other = Evidence(episode=EP_OTHER, kind="reasoning", hash=evidence.body_hash(_stored(memory, EP_OTHER)))
    web_body = _stored(memory, EP_WEB)
    web = Evidence(episode=EP_WEB, start=0, end=len(web_body.strip()), kind="page", hash=evidence.body_hash(web_body))
    return section_provenance.encode({
        "article": {article[0].key: (article[0].text_hash, [quote, later]),
                    article[1].key: (article[1].text_hash, [other])},
        "key_facts": {facts[0].key: (facts[0].text_hash, [other]),
                      facts[1].key: (facts[1].text_hash, [web])},
    })


def write_episodes(memory: Path) -> None:
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    for ep_id, (fm, text) in EPISODES.items():
        markdown_parser.write(memory / "episodes" / f"{ep_id}.md", dict(fm), text)
