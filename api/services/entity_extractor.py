"""Stage 1: Entity & Relationship Extraction via litellm."""

import asyncio
import hashlib
import re
import sys
from datetime import date
from pathlib import Path
from typing import Callable

import litellm
from loguru import logger
from tqdm import tqdm

from api.config import Settings
from api.services import (act_object, authorship, turn_signals, correspondents, decay_policy, engine_errors, entity_types, episode_time,
                          evidence, fact_policy, participation, project_birth, promotion, section_provenance, source_dates)
from api.services.json_parse import parse_json_object

EXTRACTION_SYSTEM_PROMPT = """You are an entity extraction system for a personal knowledge graph.
Given a conversation transcript, extract meaningful entities and the relationships between them.

Output valid JSON with this exact structure:
{
  "entities": [
    {
      "name": "Entity Name",
      "type": "person|project|company|concept|tool|skill|location|directory",
      "aliases": ["Mongo"],
      "summary": "1-3 sentence orientation. See SUMMARY below.",
      "key_facts": ["atomic fact", "another atomic fact"],
      "history_entries": [
        {"date": "YYYY-MM-DD", "event": "What happened"}
      ],
      "links": [
        {"url": "https://...", "title": "Human title", "note": "what it is / why it came up"}
      ],
      "open_questions": ["unresolved point about this entity"],
      "tags": ["relevant", "tags"],
      "confidence": 0.7,
      "decay_class": "durable|active|volatile",
      "website": "https://example.com   (optional; company, tool or project only)",
      "application": {"status": "drafted|filled|sent|registered|accepted|rejected|attended", "by": "user|assistant"},
      "description": "Optional. Same content as summary; kept only for backward compatibility."
    }
  ],
  "relationships": [
    {
      "source": "Entity Name A",
      "target": "Entity Name B",
      "label": "specific relationship verb phrase",
      "evidence_quote": "the exact words from the transcript this relationship rests on (verbatim, at most 240 characters)",
      "starts": "YYYY-MM-DD   (optional; see STARTS below)",
      "ends": "YYYY-MM-DD   (optional; see ENDS below)",
      "at": "Organisation Name   (optional; reports to / managed by / manages only; see AT below)"
    }
  ],
  "values": [
    {
      "entity": "Entity Name",
      "attribute": "what is measured, in a few plain words",
      "value": "the value as stated",
      "evidence_quote": "the exact words from the transcript that state the value (verbatim, at most 240 characters)"
    }
  ]
}

The entity body is rendered as ordered markdown sections: ## Summary, ## Key Facts,
## History, ## Links, ## Open Questions. The fields above map directly onto those
sections. ## Related is generated from `relationships` — do NOT emit a related field.

WHAT A PAGE IS FOR: each entity becomes a wiki article about the thing AS IT FIGURES IN THE USER'S
LIFE — what it is, what it is to them (they built it, use it, work with them, are deciding about it,
visited it), where it stands, and the facts worth remembering, once each. The article is written from
what you extract here, so its length follows yours: a thing the user worked through at length deserves
every fact the conversation established, a passing mention one or two. Every line must earn its place:
if the user would never ask about it months later, leave it out.

SUMMARY (## Summary) — one paragraph, at most 600 characters:
- What it is, then what it is to the user and where it stands in this conversation.
- skill: 1 sentence, written as an instruction. person, tool, concept, location, directory: 1-2
  sentences. project, company: 2-3 sentences.
- Introduce the thing once. Atomic facts belong in key_facts, not in the summary.
- A sentence about something other than the entity names it ("is applying to [[<event>]]; its form
  was filled in on …"), never "the form", "the event" or "it" left for the sentence before to explain.

KEY FACTS (## Key Facts) — facts about the thing worth remembering:
- First the user's relation to it: what they built, chose, use it for, decided, plan, think of it.
- Then durable facts about the thing that this conversation established: roles, components the
  user relies on, dates-as-facts, identifiers, quantities, prices, versions the user chose,
  locations, affiliations, contact handles.
- Every fact stands alone: it is read without the facts around it, on a page that may hold thousands.
  Name what it is about — "the [[<event>]] application form", never "the application form",
  "the event", "the trip" or "it" when the thing has a name — on whichever entity it sits, the user's
  own included.
- Write each fact about the thing, not about the conversation: never "the assistant suggested /
  said / recommended / explained …", "was described as …", "was mentioned / discussed in a
  conversation", "the user asked about …".
- WHO DID IT. What the user did, decided, has or plans comes only from the user's own lines, or from a
  record the conversation shows (a confirmation, a receipt, an order or booking number). An assistant's
  explanation, suggestion or instruction ("the link is for registering", "register soon") is never
  written as the user's act: "registered", "booked", "applied", "sent", "paid" need the user's own
  words or such a record. A stated plan stays a plan ("planned to register"). When the user says they
  acted on a suggestion, write what they did; a suggestion nobody took up is not a fact about the thing.
- TAKING PART NEEDS A ROLE IN THE TEXT. "competed in", "took part in", "won", "attended", "worked at", "interned
  at", "studied at" and "graduated from" are written only when the text says that role in those words or plainly
  equivalent ones ("we competed", "I was on the team", "my internship at"). A mention, "the <event> story", "a story
  about <event>", "the topic of", "an essay on" or a thing someone else did (coached, helped, watched, organised) is
  never taking part: write what the text says ("<user> coached <person> for <event>", "<user>'s application essay
  was about <event>"), or "mentioned". An assistant's summary or memory note compresses: read it for what it states,
  never for what its shorthand could imply.
- An act the assistant did itself in the user's tools — filled in a form, drafted, booked, uploaded,
  sent — is the assistant's: write it with the assistant's name as the note before the conversation
  gives it ("[[<agent>]] filled in the [[<event>]] application form on <date>"), never as the
  user's, and never as "the assistant". A step it left to the user (submit, send, pay, confirm) is not
  done: say so on the thing it belongs to ("the request to join had not been sent as of <date>"), add
  an open question there ("Has <user> sent the [[<event>]] request to join?"), and give that
  thing a status value (VALUES).
- Leave out implementation trivia of a single debugging or how-to session — an artifact or file
  name, an action or package version, an error message, a command, a line of code — unless the user
  said it matters beyond that session.
- One fact per bullet, said once: never restate the summary, and never two bullets that say the
  same thing in different words.
- No fixed number: as many facts as the conversation establishes about the thing — the decisions and
  their reasons, what was tried and how it went, the parts, people and numbers involved. A minor thing
  may have one or none. Never pad.

HISTORY ENTRIES (## History):
- Include dated events extracted from the conversation, one sentence each.
- Always emit history_entries for project and company when any dated event
  is present. Never silently drop a date you saw.
- For person entities, include key interaction dates when present.
- For concept/tool/skill/location/directory: only when the conversation contains
  specific dated events. Otherwise leave history_entries as an empty array.

LINKS (## Links):
- Extract EVERY URL mentioned in connection with this entity into links[] with a human
  title and a one-line note (what it is / why it came up). Never drop a URL into prose only.
- For tool entities, links is REQUIRED when any URL (docs, repo, homepage) appears.

OPEN QUESTIONS (## Open Questions):
- Capture unresolved points the user or system still needs to settle about this entity
  (an unconfirmed identity, an undecided choice, a missing date). Leave empty if none.

DECAY CLASS (optional, per entity) — how fast this belief should fade if it stops
being mentioned:
- volatile: a fact you expect to change within weeks (a current role, a status, a
  current focus, an in-flight decision).
- durable: a stable preference, a skill, or a long-lived concept that rarely moves.
- active: everything else — the default. Omit the field when unsure.
- NEVER EVERGREEN a belief here: "evergreen" is reserved for ingested artifacts
  (bookmarks, saved media) and the user — an extraction may only propose
  durable|active|volatile.

WEBSITE (optional, company, tool or project ONLY) — the entity's own official site:
- Emit it ONLY when the transcript states it, or you are certain it is that entity's own site.
- An origin URL only ("https://example.com"): never a profile, an article, a repository host or a social page.
- Omit it when unsure. A guess is worse than nothing: it is checked against the site itself and removed when wrong.

APPLICATION (optional, per entity) — only on a SPECIFIC event, program, hackathon, fellowship, course or job
opening the user acted on in this conversation: applied to it, registered or signed up for it, filled in its form —
or the assistant did one of those for them in their tools ("by": "assistant").
- status: where it stands at the end of the conversation — drafted, filled (form filled in, not sent), sent,
  registered, accepted, rejected, attended.
- The entity is the event or program itself (its own name), never the user, and never the place it is held or who
  runs it: "I signed up for a <workshop> at the <venue>" is "<user> signed up for <workshop>" and "<workshop> held at
  <venue>" — never "<user> signed up for <venue>". Its facts — the form, the dates, the
  status, what is left to do — go on it, not on the user's own entity; the user keeps only the relationship
  ("<user> applied to <event>").
- Never for a bookmark, a link saved for later, a thing only mentioned or considered, or an assistant only
  explaining how to apply. Omit the field otherwise.

TIME (every conversation is written up as of its own date):
- A note before the conversation gives the date it took place and today's date. Write what it says as of the
  conversation's date, never as of today.
- When the note says the conversation is older than 90 days, every statement that can change (a role, a status,
  a plan, a current focus, an intention) names its month and year — "In February 2025, the user was considering …"
  — and is never presented as current.
- Plans, intentions and states of mind ("considering", "planning", "interested in", "wants", "hopes") always name
  the month and year they were stated, whatever the conversation's age.
- Never write words that only make sense relative to when the page is read: "currently", "now", "recently",
  "this week", "soon", "next month".
- Resolve a relative time phrase against the conversation's date, in the direction the sentence states it: a
  past-tense "met on Monday" is the Monday before the conversation. When the day or the direction is unclear, name
  the conversation's month and year instead of guessing a day.
- Keep every explicit date the conversation states exactly as stated: the date something happened is not the date
  of the conversation, and one never replaces the other.
- history_entries: the date the event happened when it is stated, otherwise the conversation's date.

VALUES (values[]) — a value of something about an entity that a later conversation can replace with a new one:
a count ("korean restaurants tried": "4"), a time, score or personal best ("charity 5k personal best": "25:50"),
a price or amount, a size, a version or plan in use, a current status — an application, booking, order or
message the conversation leaves part-done included ("application status": "form filled in, not sent"), so a
later conversation's "sent" or "accepted" replaces it. One entry per value the conversation
states as true at the time; when it states two for the same thing, the later one.
- attribute: the thing measured, in plain lowercase words, without the entity's name and without the value — the
  words someone would use for it again next time ("personal best 5k time", not "new record set last spring").
- value: as stated, with its unit ("25:50", "4", "$1,200 a month"). Never a guess, never a list (several things
  held at once are relationships), never the date something happened (that is history).
- evidence_quote: as for relationships below. The value stays in key_facts too.

EXTRACTION GUIDELINES:
- The agent's own runtime (its working directory, platform, shell, git status, the date of the session)
  is never conversation content: extract nothing from it, and never an entity for a path it shows you.
- Extract entities that are meaningful to the user's life, work, or goals. Skip trivial mentions.
- A detail of the assistant's answer is not an entity: a function or variable in a code example, a
  command, a library, tool or place the assistant only suggested or listed. Extract it only when the
  user engaged with it — used it, asked about it by name, chose it, built it, went there.
- ATTACHMENTS ARE NOT THE USER'S WORDS. A turn written `attachment [<file name>]:` (its lines quoted
  with "> ") is the text of a document the user shared — a CV, contract, paper, article. Never
  attribute a document's contents to the user (no "user works at / lives in / is ..." taken from a
  CV or contract), and do not create a page for a person or company that appears only inside a
  document unless the conversation itself discusses them.
- MEMORY EPISODES ARE OLDER SUMMARIES. When the input opens with a "[Source: claude_memory ...]"
  note, it is the assistant's own earlier summary about the user, possibly outdated. Use it as
  dated, lower-trust background (lower confidence) and prefer a conversation's newer statement.
- Confidence reflects how certain you are about the entity's attributes, not how important it is.
- If an entity is mentioned but you lack context to classify it confidently (e.g., a bare name
  with no role), still extract it but set confidence below 0.5.
- aliases: other NAMES the same thing goes by ("Mongo" for MongoDB, an acronym, a nickname). Never a
  reference that only makes sense inside this conversation ("the database", "this project", "my app",
  "the new format"), and never the name of a part, product, dataset, file format or version of the
  entity — that is a different thing. Leave empty if there is only one name.
- Use wikilinks `[[Entity Name]]` inside summary and key_facts to reference other entities.
  Do NOT fabricate links bullets — those come only from real URLs in the source.
- Entity types must be exactly one of: person, project, company, concept, tool, skill, location, directory.
- DUE-DATES ARE NOT ENTITIES. Do NOT create a standalone entity for a deadline or a bare date.
  When something is due by a date, attach it as a relationship whose source is the thing that is
  due (the project/task), label is "due", and target is the date literal (e.g. "2026-06-30"). You
  may also note the date as a key_fact on that entity. Never emit a `deadline`-typed entity.
- DIRECTORY vs LOCATION. Classify a filesystem PATH — anything that looks like `/Users/...`, a
  `~/...` home-relative path, a repo/folder path, or a drive path — as type `directory`. Classify a
  physical, real-world place (a city, an office, a campus, a venue) as type `location`. When in doubt
  and the string is a slash/tilde path, prefer `directory`.
- Relationships are critical — capture every meaningful connection between entities with a specific
  verb phrase in the active voice, source first (e.g. "works at", "built with", "supervised by", "depends on",
  "evaluated against", "dropped", "due"). Use short verb phrases, not full sentences or generic "related to".
- "works at" says the place is CURRENT. A job or role that ended is labelled by its ending — "left",
  "previously worked at" — never "works at". Two places at once (a job and a lab, a day job and a side
  project) are two "works at" relationships; one never replaces the other.
- The same holds for where someone lives, studies and who they report to: "lives in", "studies at" and
  "reports to" say it is CURRENT; one that ended is "previously lived in", "studied at", "graduated from",
  "previously reported to". A job, home or school someone had before — a public figure's earlier employers
  included, whether the conversation says it or you know it — is never written in the present tense.
  A job that began ("joined", "started at", "was hired by") is "works at", a home someone moved to "lives in",
  each with STARTS when the day is said; joining a club, a team, a course or a university is never "works at".
- A SWITCH IS SAID ABOUT WHAT SWITCHED. When the user's words say they dropped, stopped using, moved off,
  moved from or switched away from something — "moved from A to B", "replaced A with B" included — FOR A PROJECT (the project is named in that turn, or is plainly what that turn is
  about), the source is the PROJECT: "<project> dropped <old thing>", and what takes its place is "<project> uses
  <new thing>". Never write a project's switch only on the user ("<user> dropped <old thing>"), and never label it
  "replaces" or "replaced by" — those say which thing took whose place, and read backwards.
- ENDS (optional): the day a relationship stops or stopped being true, when the conversation states that day —
  a last day at a job, a contract's end, the day something was dropped. Always an absolute YYYY-MM-DD resolved
  from the conversation's date as TIME says: said on 2026-03-04, "my last day is a week from today" is
  2026-03-11; "yesterday was my last day" is 2026-03-03. On an ending ("left", "dropped") it is the day it ended;
  on any other relationship ("works at" with a last day ahead) it is the day it will stop. Omit it when no day is
  stated, or when the day is unclear — never a relative phrase, never a guess.
- STARTS (optional): the day a relationship began, when the conversation states that day — a first day at a
  job, the day someone joined or moved. An absolute YYYY-MM-DD resolved from the conversation's date as TIME
  says: said on 2026-05-20, "as of yesterday, joined" is 2026-05-19. Omit it when no day is stated or it is
  unclear, and on an ending or a past tense ("left", "worked at") — never a relative phrase, never a guess.
- AT (optional, only on "reports to", "managed by" and "manages"): the organisation that working relationship
  belongs to, when the conversation says it (the user's manager at the company they work at: "at" is that
  company).
  Omit it when the conversation does not say where. Write the user's own working relationships from the user's
  side, the user as the source: "<user> reports to <manager>", never "<manager> manages <user>".
- EVIDENCE QUOTE (required on every relationship): copy the shortest passage of the transcript,
  VERBATIM and at most 240 characters, that states this relationship — the sentence the user or
  assistant actually wrote, not your paraphrase. If the relationship is your own inference across
  several passages and no single passage states it, omit evidence_quote entirely. Never invent one:
  a quote that is not in the transcript is discarded and the relationship is recorded as inference."""

def owner_block(name: str | None) -> str:
    """G169 — appended to :data:`EXTRACTION_SYSTEM_PROMPT` when the bank has an
    ``owner: true`` page: the prompt's "the user" is that person, and everything
    the model writes calls them by the page's ``name``. Without an owner page the
    prompt is unchanged (Stage 2 still never makes a page of a self-reference)."""
    if not name:
        return ""
    from api.services.owner_identity import self_reference_list

    return (
        "\n\nTHE OWNER OF THIS MEMORY:\n"
        f'- "the user" in these instructions is the person this memory belongs to: "{name}". In the transcript\n'
        "  they write the user turns and speak of themselves in the first person, in any language.\n"
        f"- In everything you write — entity names, relationship sources and targets, summaries, key_facts,\n"
        f'  history entries, open questions — call them "{name}". When you mean them, never write\n'
        f'  {self_reference_list()}; write "{name}" in a conversation in any language.\n'
        f'- Their own facts go on one entity named exactly "{name}" (type person); never a second entity for them.\n'
        "- A real company, product, tool or concept that happens to be called one of those words keeps its own\n"
        "  name and type.\n"
        f"- A person the conversation names only by their relation to {name} (a partner, a parent, a friend, a\n"
        '  teacher) and never by a name: name the entity by the relation followed by "(unnamed)" — "Partner (unnamed)",\n'
        f'  "Father (unnamed)", "Former roommate (unnamed)" — never "{name}\'s partner". When the conversation gives\n'
        "  their name, use the name and keep the relation as a key fact."
    )


# Max concurrent LLM calls — stay under rate limits
MAX_CONCURRENCY = 10

# Chunk size in chars (~3K tokens). Long conversations get split into chunks
# so no information is lost. Each chunk gets its own extraction call. Kept small
# so no single call is enormous — with reasoning disabled (below) GLM 5.2 returns
# a chunk this size in ~5s, so smaller chunks are cheap and bound worst-case
# latency. (Was 24_000, which made big April threads time out at 600s.)
CHUNK_SIZE = 12_000
CHUNK_OVERLAP = 500  # Overlap to avoid splitting mid-sentence

# Hard wall-clock cap per extraction call. A hung/over-long generation fails
# fast and the episode requeues, rather than burning 10-20 min (litellm's 600s
# default let timed-out reasoning generations run to ~1300s).
EXTRACTION_TIMEOUT_S = 300

# Disable provider-side "reasoning"/thinking for extraction. Structured entity
# extraction does not benefit from chain-of-thought, and on GLM 5.2 reasoning
# was the cause of timeouts + empty/non-JSON responses. OpenRouter forwards this
# unified field to the model; passed via litellm's extra_body. Empirically: 21s
# -> 5s, 905 -> 284 completion tokens, JSON still valid. Override with
# ``settings.extraction_extra_body`` is intentionally NOT wired — reasoning-off
# is the right default for all extraction backends (no-op for non-reasoning ones).
EXTRACTION_EXTRA_BODY = {"reasoning": {"enabled": False}}

# Errors worth one retry inside a single chunk call: transient rate limits,
# timeouts, and a malformed/empty response (``_parse_json_lenient`` raises
# ValueError; ``json.JSONDecodeError`` is a ValueError subclass).
#
# G74(a): the tuple was litellm-exception-typed ONLY, so under
# ``llm_mode="agent"`` a CLI failure matched nothing and got zero retries.
# ``engine_errors.RETRYABLE`` adds the three subprocess failures worth one more
# attempt — deliberately NOT ``EngineThrottled`` (the breaker handles it; a
# retry would just spawn again), ``EngineUnavailable``, ``EngineExhausted`` or
# ``EngineModelNotFound``, all of which need a human rather than a retry.
_EXTRACT_RETRYABLE = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.Timeout,
    ValueError,
    *engine_errors.RETRYABLE,
)


# Historical name: the parser now lives in ``json_parse`` (six other call
# sites needed it). Kept as an alias — ``api/tests/test_extractor_robustness.py``
# and every reader of this module still reach for it here.
_parse_json_lenient = parse_json_object


def sanitize_decay_class(entity: dict) -> None:
    """Stage-1 anti-pollution rail, applied to ONE extracted entity dict.

    The extractor may PROPOSE ``durable|active|volatile``. Anything else — junk,
    a missing key, or ``evergreen`` (reserved for the ingest writers and the
    user) — is removed so the downstream writer falls back to its own default.
    Mutates in place; never raises.
    """
    if "decay_class" not in entity:
        return
    cls = decay_policy.agent_class(entity.pop("decay_class"))
    if cls is not None:
        entity["decay_class"] = cls.value


def sanitize_entity_type(entity: dict) -> None:
    """The closed-type rail, applied to ONE extracted entity dict (2026-10-17): the type becomes one Stage 1 may
    produce (``entity_types.producible``: ``organization`` → ``company``, ``product`` → ``tool``, anything unknown →
    ``concept``). A plain-JSON engine is held only by the prompt's list. Mutates in place; never raises."""
    entity["type"] = entity_types.producible(entity.get("type"))


def sanitize_website(entity: dict) -> None:
    """G61 S3-b rail (``site_sources.sanitize_website``): keep an entity's proposed ``website`` only as an https origin
    of a public, non-platform host for a company, tool or project; drop it otherwise. Mutates in place; never raises."""
    from api.services import site_sources

    site_sources.sanitize_website(entity)


def _chunk_spans(content: str) -> list[tuple[int, int]]:
    """Chunk boundaries as ``(start, end)`` offsets into ``content``.

    Boundaries are unchanged from the original ``_chunk_content``; exposing
    them is what lets G118's evidence verification prefer a quote's
    occurrence inside the chunk the model actually saw (R11) while recording
    offsets into the WHOLE body — the stored text a viewer will slice.
    """
    if len(content) <= CHUNK_SIZE:
        return [(0, len(content))]
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(content):
        end = start + CHUNK_SIZE
        # Try to break at a newline near the boundary
        if end < len(content):
            newline_pos = content.rfind("\n", end - 200, end)
            if newline_pos > start:
                end = newline_pos + 1
        spans.append((start, end))
        start = end - CHUNK_OVERLAP
    return spans


def _chunk_content(content: str) -> list[str]:
    """Split long content into overlapping chunks."""
    return [content[s:e] for s, e in _chunk_spans(content)]


#: Prepended to the user message of a `claude_memory` episode (the model sees only
#: the chunk, never the frontmatter). Chunk offsets are unaffected: evidence spans
#: are computed against the episode body, not against this message.
MEMORY_SOURCE_NOTE = (
    "[Source: claude_memory — the assistant's own older summary about the user; "
    "dated, possibly outdated, lower trust.]\n\n"
)
#: Episode sources that get :data:`MEMORY_SOURCE_NOTE`: a chat export's memory entry and (ruling 43) an agent's own
#: memory note — both the assistant's summary, dated when last edited, so a conversation's newer statement wins.
MEMORY_SOURCES = frozenset({"claude_memory", "agent-memory"})


#: G179: a message conversation's other side, told to the model before the conversation (the model sees the chunk,
#: never the frontmatter). An agent's turns are `assistant:` lines and a person's `speaker:<label>:` lines; either way
#: their "I" is theirs and what they say about the person is their statement, never the person's own words.
SOURCE_NOTE_PREFIX = "[Source: a text-message conversation."


def correspondent_note(correspondent: dict | None) -> str | None:
    """The note for an episode whose ``correspondent`` record names the other side, else ``None``."""
    if not isinstance(correspondent, dict):
        return None
    name = " ".join(str(correspondent.get("name") or "").split())[:80] or "the other side"
    own = 'Lines starting "user:" are the person\'s own messages.'
    if correspondent.get("kind") == "agent":
        return (f'{SOURCE_NOTE_PREFIX} {own} Lines starting "assistant:" are messages from {name}, an AI agent the '
                f'person texts: {name}\'s words, never the person\'s. "I", "me" or "my" in an assistant line is {name}; '
                f"what {name} says about the person is {name}'s statement, not something the person said. Attribute a "
                "fact to the person only from their own lines.]\n\n")
    return (f'{SOURCE_NOTE_PREFIX} {own} Lines starting "speaker:" are messages from {name}, someone else: their words, '
            f'never the person\'s. "I", "me" or "my" in such a line is {name}.]\n\n')


def correspondent_observer(correspondent: dict | None) -> str | None:
    """``external:<slug>`` — the observer of a claim drawn only from the other side's words (G95's speaker → observer
    rule, G179's "a claim drawn only from the agent's message says the agent said it")."""
    if not isinstance(correspondent, dict):
        return None
    from api.services.id_utils import sanitize_id

    slug = sanitize_id(str(correspondent.get("name") or ""))
    return f"external:{slug}" if slug and slug != "unnamed" else None


def _agent_name(episode: dict) -> str | None:
    """The agent whose words are an episode's ``assistant:`` lines, from the episode's own record: the harness that
    captured the session (``claude-code``, ``codex``…), else a chat export's app (``chatgpt-export`` → ``chatgpt``).
    ``None`` for a message conversation (its correspondent says who), a relayed one (``evidence_kind``: stored as
    relayed, its own rail) and anything else."""
    if isinstance(episode.get("correspondent"), dict) or episode.get("evidence_kind"):
        return None
    from api.services.episode_title import assistant_of

    harness = str(episode.get("harness") or "").strip().lower()
    return assistant_of(harness) or assistant_of(episode.get("origin"))


def agent_session_note(episode: dict) -> str | None:
    """The note for a harness-captured session: its ``assistant:`` lines are that agent, acting in the person's tools
    (its acts are its own, a step it left to the person is not done). ``None`` for every other episode."""
    harness = str(episode.get("harness") or "").strip().lower()
    if not harness or episode.get("capture_kind") != "transcript" or _agent_name(episode) is None:
        return None
    from api.services.episode_title import PRODUCT

    name = PRODUCT.get(harness, harness)
    return (f'[Source: a {name} session. Lines starting "user:" are the person\'s own messages; lines starting '
            f'"assistant:" are {name}, an AI agent working for the person in their tools. What {name} says it did '
            f"(filled in a form, wrote or sent something, booked) is {name}'s act, never the person's; a step it left "
            "to the person (submit, send, pay, confirm) is not done.]\n\n")


def project_note(episode: dict) -> str | None:
    """Ruling 45 addendum: the provider's own project grouping (a ChatGPT ``g-p-`` id) or the relaying app's word on the
    project, told to the model as context — the conversation sits in a project the person made there. Never a claim by
    itself; ``None`` for every other episode."""
    grouping = episode.get("provider_project")
    relay = episode.get("relay") if isinstance(episode.get("relay"), dict) else {}
    said = relay.get("project") if isinstance(relay.get("project"), str) else None
    if isinstance(grouping, dict) and grouping.get("provider"):
        app = {"chatgpt": "ChatGPT", "claude": "Claude"}.get(str(grouping["provider"]), str(grouping["provider"]))
        name = str(grouping.get("name") or "").strip()
        where = f'the person\'s {app} project "{name}"' if name else f"one of the person's {app} projects"
        return f"[Context: this conversation was held inside {where}.]\n\n"
    if said:
        return f'[Context: the app that relayed this conversation said it belongs to the project "{said[:120]}".]\n\n'
    return None


def assistant_observer(episode: dict) -> str | None:
    """``external:<name>`` — the observer of a claim drawn only from the other side's words: a message conversation's
    correspondent (G179), else the agent whose ``assistant:`` lines they are (:func:`_agent_name`). ``None`` when the
    episode names neither."""
    observer = correspondent_observer(episode.get("correspondent"))
    if observer:
        return observer
    from api.services.id_utils import sanitize_id

    agent = _agent_name(episode)
    slug = sanitize_id(agent) if agent else ""
    return f"external:{slug}" if slug and slug != "unnamed" else None


def _is_owner(entity: dict, owner: str | None) -> bool:
    from api.services.owner_identity import is_self_reference
    from api.services.text_fold import fold

    name = " ".join(str(entity.get("name") or "").split())
    return bool(name) and ((bool(owner) and fold(name) == fold(owner)) or is_self_reference(name))


def _application_pages(entities: list, episode: dict, episode_id: str, content: str, *, owner: str | None,
                       day: str | None, gaps=()) -> list[tuple[dict, bool]]:
    """Ruling 42 at Stage 1 (`application_page`): mark each entity this conversation shows the person (or a harness
    agent, for them) acted on, write its application onto it, and move what the owner's extraction says about it
    there. The model's ``application`` field is consumed here and never reaches a page. Returns the status values to
    add, each with whether an agent acted."""
    from api.services import application_page

    marked = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity.pop(application_page.KEY, None)  # never the model's to set
        birth = None
        if not _is_owner(entity, owner):
            birth = application_page.at_extraction(entity, episode_id=episode_id, frontmatter=episode, text=content,
                                                   day=day, override=authorship.of_episode(episode), gaps=gaps)
        entity.pop("application", None)
        if birth is not None:
            entity[application_page.KEY] = birth
            marked.append(entity)
    if not marked:
        return []
    owners = [e for e in entities if isinstance(e, dict) and _is_owner(e, owner)]
    values = []
    for entity in marked:
        for owner_entity in owners:
            application_page.move_from_owner(owner_entity, entity)
        value = application_page.record_facts(entity, entity[application_page.KEY], owner=owner)
        if value is not None:
            values.append((value, entity[application_page.KEY]["by"] != "user"))
    return values


#: How the person's own reaction on the turn a claim rests on moves its confidence: agreement a little up (a 👍 often
#: only means "got it"), doubt (❓, 👎) by half.
AGREE_BONUS = 0.1
AGREE_CAP = 0.95
DOUBT_FACTOR = 0.5


def _weigh_reaction(item: dict, episode: dict, content: str, episode_id: str) -> None:
    """The person's own reaction on the one turn a claim rests on, read from the stored extras (`turn_signals`), never
    from the model's word: it adjusts confidence and is recorded on the claim (``reactions``: who, stance, kind, and the
    reacted turn's offset in the episode — the reaction's own key in ``turn_extras``, so its evidence by turn id). It
    never changes the observer (#499 review): a texted agent's claim stays ``external:<agent>`` whatever the person
    tapped. Never a claim by itself."""
    found = turn_signals.person_stance(episode, content, item)
    if found is None:
        return
    try:
        confidence = float(item.get("confidence", 0.6) or 0.6)
    except (TypeError, ValueError):
        confidence = 0.6
    if found["stance"] == "agree":
        item["confidence"] = round(min(AGREE_CAP, max(confidence, confidence + AGREE_BONUS)), 2)
    else:
        item["confidence"] = round(confidence * DOUBT_FACTOR, 2)
    item["reactions"] = [{**found, "episode": episode_id}]


def group_members(episode: dict) -> list[dict]:
    """A group chat's members as its episode records them (``participants``: ``[{marker, name?, kind?}]``), the
    person excluded; ``[]`` for anything that is not a group."""
    if not episode.get("group"):
        return []
    out = []
    for p in episode.get("participants") or []:
        if isinstance(p, dict) and str(p.get("marker") or "").startswith(("speaker:", "assistant")):
            out.append({"marker": str(p["marker"]), "name": " ".join(str(p.get("name") or "").split())[:80],
                        "kind": str(p.get("kind") or "person")})
    return out


def group_note(members: list[dict]) -> str:
    """G179 groups: who each line's speaker is — each member's words are their own, never the person's."""
    who = "; ".join(f'"{m["marker"]}:" is {m["name"] or "a member Cicada has no name for"}'
                    + (", an AI agent" if m["kind"] == "agent" else "") for m in members[:30])
    return (f"{SOURCE_NOTE_PREFIX[:-1]} with several people (a group chat). Lines starting \"user:\" are the "
            f"person's own messages; every other line is another member's: {who}. A member's words, and their "
            "\"I\", are theirs, never the person's. Attribute a fact to the person only from their own lines.]\n\n")


def _member_of(content: str, start: int) -> str | None:
    """The marker of the last turn opened at or before ``start``."""
    hit = None
    for turn in evidence.turns(content):
        if turn.start > start:
            break
        if turn.marker is not None:
            hit = turn.marker
    return hit


#: A group claim resting on several members' lines (#499 re-check). One stable observer rather than the members'
#: names joined: a joined name would mint a new observer for every combination and split one belief across them,
#: while the evidence spans already say exactly who said what. It is never the person's.
GROUP_OBSERVER = "external:group"


def _observer_for(item: dict, their_observer: str | None, members: list[dict], content: str) -> str | None:
    """Who a claim is ``external:`` to, or ``None`` for the default reading. In a group, a claim with no span in the
    person's own lines is never the default: one member's lines make it that member's, several members' (or a member
    Cicada cannot name) :data:`GROUP_OBSERVER`. Otherwise the other side's when only their words carry it. A reaction
    never changes it (`_weigh_reaction`)."""
    if members:
        spans = [e for e in item.get("evidence") or [] if isinstance(e, dict) and e.get("kind") != "reasoning"]
        if not spans or any(e.get("kind") not in ("assistant", "speaker") for e in spans):
            return None   # unlocated, or the person's own words back it
        markers = {_member_of(content, int(e.get("start", 0))) for e in spans}
        member = next((m for m in members if m["marker"] == next(iter(markers))), None) if len(markers) == 1 else None
        if member is None:
            return GROUP_OBSERVER
        from api.services.id_utils import sanitize_id

        slug = sanitize_id(member["name"] or member["marker"].partition(":")[2] or member["marker"])
        return f"external:{slug}" if slug and slug != "unnamed" else GROUP_OBSERVER
    if their_observer and _only_their_words(item):
        return their_observer
    return None


def _only_their_words(rel: dict) -> bool:
    """Every located span of ``rel`` sits in the other side's turns (``assistant`` or ``speaker``), and there is one."""
    spans = [e for e in rel.get("evidence") or [] if isinstance(e, dict) and e.get("kind") != "reasoning"]
    return bool(spans) and all(e.get("kind") in ("assistant", "speaker") for e in spans)


#: G110 gate B2: a captured session's dropped-middle marker never reaches the
#: model as conversation text. The episode's own gap range (``episode["gaps"]``)
#: is blanked on the WHOLE body before the chunker slices it — offsets kept, so
#: evidence still lands in the stored body and no chunk can start inside the
#: marker with an unlabelled fragment — and each chunk that touches it is told
#: about the gap in a note placed apart from, and before, the conversation.
GAP_NOTE_PREFIX = "[Cicada's note, not part of the conversation and nobody's words:"


def _gap_note(gaps, start: int, end: int) -> str | None:
    if not evidence.touches_gap(start, end, gaps):
        return None
    return (f"{GAP_NOTE_PREFIX} some conversation text (turns or parts of replies) was not captured; "
            "the blank line marks where. Never quote or attribute it.]\n\n")


async def _extract_chunk(
    ep_id: str,
    chunk: str,
    chunk_idx: int,
    total_chunks: int,
    settings: Settings,
    *,
    source: str | None = None,
    gap_note: str | None = None,
    date_note: str | None = None,
    owner: str | None = None,
    source_note: str | None = None,
    stage: str = "extraction",
    _attempt: int = 0,
) -> dict:
    """Extract entities from a single chunk via LLM.

    Reasoning is disabled and a hard timeout is set (see module constants). On a
    transient failure (rate limit / timeout / malformed-or-empty response) the
    call is retried ONCE with a short backoff; a second failure propagates so the
    episode is counted failed and requeued. JSON parsing is lenient to tolerate a
    reasoning model that wraps the object in fences or prose.
    """
    try:
        from api.services.providers import resolve_llm_fn

        llm_fn = resolve_llm_fn(
            settings, model=settings.litellm_model, completion=litellm.acompletion, stage=stage
        )
        response = await llm_fn(
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT + owner_block(owner)},
                # Cicada's notes first (the gap, then the date — G194 A1), the conversation last. The model sees
                # this message only; evidence is verified against the stored body, so offsets never move.
                {"role": "user", "content": (gap_note or "") + (date_note or "") + (source_note or "")
                 + ((MEMORY_SOURCE_NOTE + chunk) if source == "claude_memory" else chunk)},
            ],
            response_format={"type": "json_object"},
            extra_body=EXTRACTION_EXTRA_BODY,
            timeout=EXTRACTION_TIMEOUT_S,
        )
        raw = response.choices[0].message.content
        return _parse_json_lenient(raw)
    except _EXTRACT_RETRYABLE as e:
        if _attempt >= 1:
            raise
        # Rate limits need a real cooldown; timeouts/parse failures retry fast.
        slow = isinstance(e, (litellm.exceptions.RateLimitError, engine_errors.EngineTimeout))
        backoff = 10 if slow else 2
        logger.warning(
            f"  {ep_id} chunk {chunk_idx + 1}/{total_chunks} — "
            f"{type(e).__name__}, retrying in {backoff}s..."
        )
        await asyncio.sleep(backoff)
        return await _extract_chunk(
            ep_id, chunk, chunk_idx, total_chunks, settings, source=source, gap_note=gap_note, date_note=date_note,
            owner=owner, source_note=source_note, stage=stage,
            _attempt=_attempt + 1,
        )


async def extract(
    episodes: list[dict],
    settings: Settings,
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[], None] | None = None,
    on_episode_done: Callable[[dict], None] | None = None,
    on_episode_started: Callable[[dict], None] | None = None,
    on_episode_read: Callable[[dict], None] | None = None,
    on_episode_failed: Callable[[dict, BaseException], None] | None = None,
    on_episode_skipped: Callable[[dict], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
    today: date | None = None,
    stage: str = "extraction",
) -> list[dict]:
    """Extract entities and relationships from unprocessed episodes (parallel).

    ``stage`` labels every call's usage event (G207: the quick read after capture is ``"quick_read"``); the prompt
    and everything it returns are the same.

    ``today`` (G194 A1): the day every chunk's date note calls today — fixed once for the whole fan-out, so a run
    that crosses midnight tells every conversation the same thing. ``None`` is the machine-local day
    (``claims.current_day``), the day claim readers use.

    ``cancel_check`` (sleep-control): an optional zero-arg predicate polled at
    the natural per-episode checkpoints in this fan-out — before an episode
    even queues for a semaphore slot, and again right after it acquires one
    (it may have waited a while). Once it starts returning ``True``, no
    NEW episode starts any work (no LLM call spent) — its slot in ``results``
    stays ``None``, so it comes back out of ``extract`` exactly like a failed
    episode: absent from the returned list, left ``processed: false`` by the
    caller. Episodes already mid-``_extract_chunk`` when the flag flips are
    NOT interrupted — they finish normally ("let in-flight work finish").
    ``None`` (the default, and every existing call site) means "never
    cancel" — behavior is unchanged.

    ``progress_callback`` (sleep debt, G106 amendment): an optional zero-arg
    callback fired exactly once per episode, the instant that episode is
    fully done with THIS stage — success, failure, empty-content fast path,
    or cancelled-skip all count (mirrors the existing ``tqdm`` bar's own
    ``update(1)``, which fires on every one of those paths already). This is
    what makes ``SleepStatusResponse``'s live "Progress %" during Stage 1
    possible without waiting for the whole fan-out to finish.

    ``on_episode_done`` (G125 R3): an optional one-arg callback fired with
    the episode dict itself, on every one of the same outcomes as
    ``progress_callback`` above (right after it, in ``process_one``'s
    ``finally``) — the study list's per-source countdown needs the
    episode's ``origin`` to know WHICH source just finished, which the
    zero-arg ``progress_callback`` can't carry without breaking its
    existing callers.

    Sleep page v5 — per-conversation outcomes, all optional and ``None`` by default
    so every existing caller and test is byte-identical: ``on_episode_started`` fires
    when an episode begins real work (it took a slot), ``on_episode_read`` when it
    succeeded, ``on_episode_failed(episode, exc)`` where the exception is swallowed
    below (the drain classifies it — an engine's trouble is not the conversation's),
    and ``on_episode_skipped`` for one never started because ``stop_check`` (the
    reserve line or an engine interruption) said stop starting new reads. Reads
    already running finish either way; the caller decides whether to discard the batch.
    """
    from api.services.claims import current_day

    today = today or current_day()
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results: list[dict | None] = [None] * len(episodes)
    success = 0
    failed = 0
    total = len(episodes)

    progress = tqdm(
        total=total,
        desc="Stage 1: extract",
        unit="ep",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]",
        leave=True,
    )
    # G169: read once per extraction — what every chunk's prompt calls the person.
    from api.services import owner_identity

    try:
        owner = owner_identity.owner_name(getattr(settings, "memory_path", None), settings)
    except Exception:  # noqa: BLE001 - a missing name costs the prompt line, never the read
        owner = None
    # R-E22: the per-episode reasons name the engine that actually ran.
    from api.services import engine_select

    _engine = engine_select.engine_label(settings)
    plan_name = engine_select.PLAN_NAMES.get(_engine, "Claude plan")
    from api.services import cli_engines

    _cli_spec = cli_engines.spec_for(_engine)
    tool_name = _cli_spec.name if _cli_spec else ("Codex" if _engine == "codex-cli" else "Claude Code")
    entities_so_far = 0
    # Perf report 2026-10-24, item 1: the plan account's email rides the CLI's own context. It is read once here and
    # kept only in memory; an item carrying it is dropped below unless the conversation itself says it.
    from api.services import engine_identity

    plan_ids = await engine_identity.aidentities(settings)

    def _note_failed(episode: dict, exc: BaseException) -> None:
        if on_episode_failed is not None:
            try:
                on_episode_failed(episode, exc)
            except Exception:  # a progress hook must never fail the read
                pass

    def _note_skipped(episode: dict) -> None:
        if on_episode_skipped is not None:
            try:
                on_episode_skipped(episode)
            except Exception:
                pass

    async def _do_process(i: int, episode: dict) -> None:
        nonlocal success, failed, entities_so_far
        ep_id = episode["id"]
        content = episode["content"]

        # The drain's reserve line or engine interruption stops new episode reads.
        if stop_check is not None and stop_check():
            _note_skipped(episode)
            return

        # Sleep-control checkpoint 1: before this episode even queues for a
        # semaphore slot. A cancel requested any time before this task got
        # its turn on the event loop means it never spends a call.
        if cancel_check is not None and cancel_check():
            return

        if not content.strip():
            # No LLM call needed, but record a zero-entity result so the Sleep
            # cycle marks this episode processed (done — nothing to extract)
            # instead of leaving it queued and re-scanning it every run.
            results[i] = {
                "episode_id": ep_id,
                "episode_timestamp": episode.get("timestamp"),
                "origin": episode.get("origin", "unknown"),
                "entities": [],
                "relationships": [],
            }
            success += 1
            return

        spans = _chunk_spans(content)
        # G110 gate B2: blank the episode's own gap range on the WHOLE body, then slice.
        gaps = tuple(episode.get("gaps") or ())
        masked = evidence.mask_gaps(content, gaps)
        chunks = [masked[s:e] for s, e in spans]
        # G194 A1: every chunk is told when the conversation took place and what day it is now.
        ep_day = source_dates.episode_day(episode)
        # "Facts yes, activity no" (owner 2026-10-08): a memory export entry's date is the summary's, not a
        # mention's — its pages keep the facts and the source, never its date as when the thing came up.
        untimed = not episode_time.counts_as_activity(episode)
        # Ruling 39: a feed item is untimed too (no mention by the person), but its date is its publisher's, so the
        # model is told when it was published rather than that it is an assistant's summary.
        if episode_time.is_feed_item(episode):
            date_note = source_dates.feed_note(ep_day, today)
        elif untimed:
            date_note = source_dates.summary_note(ep_day, today)
        else:
            date_note = source_dates.date_note(ep_day, today)
        # G179: a message conversation says who its other side is, before every chunk.
        # A harness session says whose its assistant lines are, and that their acts are not the person's.
        source_note = correspondent_note(episode.get("correspondent")) or agent_session_note(episode)
        # Ruling 45 addendum: the provider's project grouping, or the relaying app's word on it, as context.
        if (in_project := project_note(episode)) is not None:
            source_note = (source_note or "") + in_project
        # G179 groups: who each member is, before every chunk; a claim resting on one member's lines is theirs.
        members = group_members(episode)
        if members:
            source_note = group_note(members) + (source_note or "")
        their_observer = assistant_observer(episode)
        session_id = str(episode.get("session_id") or "").strip() or None
        # The owner, 2026-10-28: replies, reactions, forwards and unsends, told to each chunk they fall in.
        signals = list(episode.get("signals") or [])

        async with semaphore:
            # Sleep-control checkpoint 2: this task may have waited a while
            # for a slot to free up — re-check right after acquiring one, so
            # a cancel that arrived during that wait still stops it before
            # its first (real) LLM call.
            if cancel_check is not None and cancel_check():
                return
            if stop_check is not None and stop_check():
                _note_skipped(episode)
                return
            if on_episode_started is not None:
                on_episode_started(episode)
            try:
                # Extract from all chunks and merge results
                all_entities = []
                all_relationships = []
                all_values = []
                held_participation = 0
                for ci, chunk in enumerate(chunks):
                    note = _gap_note(gaps, *spans[ci])
                    signal_note = turn_signals.chunk_note(signals, *spans[ci]) if signals else None
                    chunk_note = (source_note or "") + (signal_note or "")
                    parsed = await _extract_chunk(
                        ep_id, chunk, ci, len(chunks), settings,
                        # Only a memory episode carries a note; every other call keeps its shape.
                        **({"source": "claude_memory"} if episode.get("source") in MEMORY_SOURCES else {}),
                        **({"gap_note": note} if note else {}),
                        **({"date_note": date_note} if date_note else {}),
                        **({"owner": owner} if owner else {}),
                        **({"source_note": chunk_note} if chunk_note else {}),
                        **({"stage": stage} if stage != "extraction" else {}),
                    )
                    all_entities.extend(parsed.get("entities", []))
                    chunk_rels = [r for r in (parsed.get("relationships", []) or []) if isinstance(r, dict)]
                    # G118: verify the cited passage against the body this
                    # chunk came from, preferring the chunk window (R11). The
                    # quote is consumed here — nothing downstream sees it.
                    for rel in chunk_rels:
                        # A relationship tagged with a reply or a reaction is located in that turn first (`turn_signals`).
                        window, _ = turn_signals.anchor(rel, signals, content, spans[ci])
                        evidence.attach_relationship_evidence(rel, ep_id, content, window=window, kind_override=authorship.of_episode(episode),
                                                              gaps=gaps)
                        # 2026-10-27: "competed in", "won", "worked at"… need the located words to say that role;
                        # "a story about", a topic or a mention stays a mention (`participation`).
                        if participation.hold(rel, content) is not None:
                            held_participation += 1
                    all_relationships.extend(chunk_rels)
                    chunk_values = [v for v in (parsed.get("values", []) or []) if isinstance(v, dict)]
                    for value in chunk_values:
                        window, _ = turn_signals.anchor(value, signals, content, spans[ci])
                        evidence.attach_relationship_evidence(value, ep_id, content, window=window,
                                                              kind_override=authorship.of_episode(episode), gaps=gaps)
                    all_values.extend(chunk_values)

                # 2026-10-28 (ruling 42): "signed up for an <event> at the <venue>" is an act on the event; the
                # venue or organiser gets the event's link, never the act (`act_object`).
                moved_acts = act_object.hold(all_relationships, content)
                if moved_acts:
                    logger.info(f"  {ep_id}: {moved_acts} act(s) on an application moved off its venue or organiser")
                if held_participation:
                    logger.info(f"  {ep_id}: {held_participation} relationship(s) of taking part kept as a mention: "
                                "the cited words state no such role")
                # What the model was given counts as said: the conversation, the owner's name and the source note.
                given = "\n".join(t for t in (masked, owner or "", source_note or "") if t)
                if plan_ids and engine_identity.scrub_extraction(all_entities, all_relationships, all_values,
                                                                 given, plan_ids):
                    logger.info(f"  {ep_id}: dropped what the engine took from its own account, not the conversation")

                ep_origin = episode.get("origin", "unknown")
                # The promotion rule's "more than 3 exchanges" and "the person's own words", counted on the
                # conversation itself (`promotion`), never guessed from what the model wrote about it.
                units = promotion.exchanges(content, override=authorship.of_episode(episode), gaps=gaps,
                                            persons=promotion.person_kinds(episode))
                # Ruling 42: a specific event, program or application the person (or an agent, for them) acted on
                # gets its page from this one conversation, and the application lives there, not on the owner's.
                app_values = _application_pages(all_entities, episode, ep_id, content, owner=owner,
                                                day=ep_day.isoformat() if ep_day and not untimed else None, gaps=gaps)
                narration = 0
                for entity in all_entities:
                    facts = entity.get("key_facts")
                    if isinstance(facts, list):
                        aliases = entity.get("aliases") if isinstance(entity.get("aliases"), list) else []
                        names = [entity.get("name"), *aliases]
                        kept = [f for f in facts
                                if not (isinstance(f, str) and fact_policy.about_the_conversation(f, names))]
                        narration += len(facts) - len(kept)
                        entity["key_facts"] = kept
                    entity["mention_exchanges"], entity["named_by_person"] = promotion.measure(entity, units)
                    sanitize_entity_type(entity)
                    entity.pop("project_birth", None)   # computed here from the conversation, never the model's to say
                    if entity.get("type") == "project":
                        # Ruling 36 D4: where this conversation could give the project its page (`project_birth`).
                        born = project_birth.at_extraction(
                            entity, episode_id=ep_id, frontmatter=episode, text=content,
                            day=ep_day.isoformat() if ep_day and not untimed else None,
                            override=authorship.of_episode(episode), gaps=gaps)
                        if born is not None:
                            entity["project_birth"] = born
                    section_provenance.attach(entity, ep_id, content)
                    entity["source_episode"] = ep_id
                    entity["source_episode_timestamp"] = None if untimed else episode.get("timestamp")
                    # G194 fix 1: the day the date note gave (timestamp, else the id's date) rides along for Stage
                    # 3's prompts only — never written, so no stored timestamp is invented from an id.
                    entity["source_episode_day"] = ep_day.isoformat() if ep_day and not untimed else None
                    if untimed:
                        entity["untimed"] = True
                    entity["origin"] = ep_origin
                    sanitize_entity_type(entity)
                    sanitize_decay_class(entity)
                    sanitize_website(entity)
                if narration:
                    # "X was mentioned in a conversation": the page's sources already say so.
                    logger.debug(f"  {ep_id}: {narration} fact(s) that only said the thing came up were left out")
                for rel in all_relationships:
                    rel["source_episode"] = ep_id
                    rel["source_episode_timestamp"] = episode.get("timestamp")
                    rel["origin"] = ep_origin
                    # The observer is never the model's to set; G179: a claim resting only on the other side's
                    # words is theirs (`external:<name>`), never the person's and never Cicada's own reading —
                    # a texted agent's, a harness session's agent's or a chat export's assistant's alike.
                    rel.pop("observer", None)
                    if signals:
                        _weigh_reaction(rel, episode, content, ep_id)
                    if (observer := _observer_for(rel, their_observer, members, content)) is not None:
                        rel["observer"] = observer
                for value in all_values:
                    value["source_episode"] = ep_id
                    value["source_episode_timestamp"] = episode.get("timestamp")
                    value["origin"] = ep_origin
                    value.pop("observer", None)
                    if signals:
                        _weigh_reaction(value, episode, content, ep_id)
                    if (observer := _observer_for(value, their_observer, members, content)) is not None:
                        value["observer"] = observer
                for value, by_agent in app_values:
                    value["source_episode"] = ep_id
                    value["source_episode_timestamp"] = episode.get("timestamp")
                    value["origin"] = ep_origin
                    if by_agent and their_observer:
                        value["observer"] = their_observer  # the agent's act, as the agent reported it
                    all_values.append(value)

                results[i] = {
                    "episode_id": ep_id,
                    "episode_timestamp": episode.get("timestamp"),
                    "origin": ep_origin,
                    "entities": all_entities,
                    "relationships": all_relationships,
                    "values": all_values,
                }
                if session_id:
                    # The session it was said in, from the episode's own record: every claim read from it carries
                    # it (`entities_to_claims`), so an agent's act names the session that did it.
                    results[i]["session_id"] = session_id
                # G179: the other side of a message conversation is its own page, of its own type — the entity
                # that names them is marked (and typed) here, from the episode's own record (`correspondents`).
                correspondents.mark_extraction(results[i], episode.get("correspondent"))

                success += 1
                if on_episode_read is not None:
                    on_episode_read(episode)
                entities_so_far += len(all_entities)
                progress.set_postfix_str(
                    f"ok={success} fail={failed} entities={entities_so_far}",
                    refresh=False,
                )

            # NOTE: transient failures (rate limit / timeout / malformed JSON)
            # are already retried once INSIDE _extract_chunk; anything reaching
            # here is a final failure. The episode is left out of `results`
            # (results[i] stays None) so the Sleep cycle requeues it.
            except litellm.exceptions.AuthenticationError as e:
                failed += 1
                _note_failed(episode, e)
                logger.error(f"  [{i+1}/{total}] {ep_id} — auth error (check API key): {e}")
            except litellm.exceptions.NotFoundError as e:
                failed += 1
                _note_failed(episode, e)
                logger.error(f"  [{i+1}/{total}] {ep_id} — model not found: {settings.litellm_model}")
            # G74(a): the agent rung's failures are subprocess-shaped. Each one
            # names its own fix so the Sleep page never says "check API credits"
            # for a plan that has no credits to check.
            except engine_errors.EngineThrottled as e:
                failed += 1
                _note_failed(episode, e)
                logger.error(f"  [{i+1}/{total}] {ep_id} — {plan_name} throttled: {e}")
            except engine_errors.EngineExhausted as e:
                failed += 1
                _note_failed(episode, e)
                logger.error(f"  [{i+1}/{total}] {ep_id} — {plan_name} budget exhausted: {e}")
            except engine_errors.EngineUnavailable as e:
                failed += 1
                _note_failed(episode, e)
                logger.error(f"  [{i+1}/{total}] {ep_id} — {tool_name} is signed out or missing: {e}")
            except engine_errors.EngineModelNotFound as e:
                failed += 1
                _note_failed(episode, e)
                logger.error(
                    f"  [{i+1}/{total}] {ep_id} — model not accepted by the {tool_name} CLI "
                    f"({engine_select.author_model(settings)}): {e}"
                )
            except engine_errors.EngineError as e:
                failed += 1
                _note_failed(episode, e)
                logger.error(f"  [{i+1}/{total}] {ep_id} — engine failure: {type(e).__name__}: {e}")
            except Exception as e:
                failed += 1
                _note_failed(episode, e)
                logger.error(f"  [{i+1}/{total}] {ep_id} — {type(e).__name__}: {e}")

    async def process_one(i: int, episode: dict) -> None:
        try:
            await _do_process(i, episode)
        finally:
            progress.update(1)
            if progress_callback is not None:
                progress_callback()
            if on_episode_done is not None:
                on_episode_done(episode)

    # Fire all tasks with semaphore-controlled concurrency
    try:
        tasks = [process_one(i, ep) for i, ep in enumerate(episodes)]
        await asyncio.gather(*tasks)
    finally:
        progress.close()

    all_extracted = [r for r in results if r is not None]
    logger.info(f"Extraction done: {success} succeeded, {failed} failed out of {total}")
    return all_extracted


# --------------------------------------------------------------------------- #
# M5e Stage-1: claim emission (back-compatible projection of the extract shape)
# --------------------------------------------------------------------------- #
#
# The existing entity/relationship extraction shape is the
# ``observer=agent, context=general, epistemic=explicit, source_trust=
# agent_extracted`` special case (D2 ADDENDUM (4) + sleep-trust §1). Rather than
# rewrite the prompt, we deterministically project the already-extracted
# relationship dicts into perspectival ``Claim`` objects, with ``origin``
# propagated from the episode (origin-and-harness-sync.md). Routine extraction
# defaults to ``observer=agent``; manual-edit / clarification paths set
# ``source_trust=user_stated, origin=manual_edit|clarification`` upstream.


def _claim_date(timestamp: str | None, episode_id: str) -> str:
    """A claim's ``valid_from``: the conversation's day in the person's zone (``source_dates.episode_day``, ruling
    34) — its timestamp, falling back to the date in its id; ``""`` when neither dates it."""
    day = source_dates.episode_day({"timestamp": timestamp, "id": episode_id})
    return day.isoformat() if day is not None else ""


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _stated_day(raw) -> str | None:
    """A relationship's ``ends`` as an ISO day, or ``None``: only an absolute date that exists — nothing relative is
    stored (W7, 2026-10-23); the prompt resolves "a week from today" against the conversation's day."""
    text = str(raw or "").strip()
    if not _ISO_DAY.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _emit_claim_id(subject: str, predicate: str, obj: str, valid_from: str) -> str:
    digest = hashlib.sha1(
        f"{subject}\x00{predicate}\x00{obj}\x00{valid_from}".encode("utf-8")
    ).hexdigest()[:8]
    base = valid_from or "undated"
    return f"clm_{base}_{digest}"


def entities_to_claims(
    extracted: list[dict], memory_path: Path | None, *, resolve_id: Callable[[str], str] | None = None,
) -> list:
    """Project Stage-1 extraction output into perspectival ``Claim`` objects.

    Each relationship ``{source, target, label}`` becomes one claim
    ``(subject=slug(source), predicate=normalize(label), object=slug(target))``
    with the agent/general/explicit/agent_extracted defaults and the episode's
    ``origin``. The raw label is carried on ``claim.predicate_raw`` so Stage 3 can
    emit the mandatory ``normalization-audit`` nudge when a fold happened.

    ``memory_path`` resolves the predicate normalizer; ``None`` slugifies labels
    deterministically (used by hermetic tests). Deterministic claim ids keep the
    projection idempotent across Sleep cycles.

    ``resolve_id`` (G141 PJ-0, R-CS1) maps an endpoint's raw name to a page id:
    Sleep passes ``claim_pipeline.subject_resolver`` over Stage 2's own
    ``name_to_id``, so a claim lands on the page its edge does. Without it the
    id is ``sanitize_id(name)`` — the pre-PJ-0 key every hermetic caller keeps.
    """
    from api.services import predicates
    from api.services.claims import Claim, Evidence, clean_reactions
    from api.services.id_utils import sanitize_id

    to_id = resolve_id or sanitize_id

    normalize = predicates.load_normalizer(memory_path) if memory_path is not None else None
    endings = predicates.build_endings_fn(memory_path)
    depends_on = getattr(endings, "depends_on", lambda _p: None)

    claims: list = []
    by_id: dict[str, Claim] = {}
    for extraction in extracted:
        episode_id = str(extraction.get("episode_id", "") or "")
        origin = str(extraction.get("origin") or "unknown")
        # The session the episode was captured in (its own record): which session said, or did, what a claim holds.
        sessions = [str(extraction["session_id"])] if extraction.get("session_id") else []
        for rel in extraction.get("relationships", []) or []:
            source = str(rel.get("source", "") or "").strip()
            target = str(rel.get("target", "") or "").strip()
            raw_label = str(rel.get("label", "") or "").strip() or "relates to"
            if not source or not target:
                continue
            # G179: an endpoint Stage 2 pinned to a message conversation's correspondent page lands there, whatever
            # page the same letters key to elsewhere (`correspondents`).
            subject = str(rel.get("source_page") or "") or to_id(source)
            obj = str(rel.get("target_page") or "") or to_id(target)
            if subject == obj:
                continue
            if normalize is not None:
                predicate = normalize(raw_label) or "relates-to"
            else:
                predicate = _slug_label(raw_label)
            ep = str(rel.get("source_episode", "") or episode_id)
            valid_from = _claim_date(rel.get("source_episode_timestamp"), ep)
            # W7 (2026-10-23): a stated day. On an ending ("left", "dropped") it is the day it ended, so the
            # belief it closes closes then, not on the day it was said; on any other label it is a stated end.
            ends = _stated_day(rel.get("ends"))
            expected_end = None
            hit = endings(raw_label)
            starts = _stated_day(rel.get("starts"))
            if starts and hit is None and (not ends or starts <= ends):
                # 2026-10-27: when it became true, as said ("as of yesterday, joined" is the day before) — never on an
                # ending or a past tense, whose record is history dated when it was said.
                valid_from = starts
            if ends:
                if hit is not None and hit.mode == predicates.ENDING_OVER:
                    valid_from = ends
                elif hit is None and (not valid_from or ends >= valid_from):
                    expected_end = ends
            cid = _emit_claim_id(subject, predicate, obj, valid_from)
            rel_evidence = [
                Evidence.from_dict(e) for e in (rel.get("evidence") or []) if isinstance(e, dict)
            ]
            raw_observer = str(rel.get("observer") or "")
            observer = raw_observer if raw_observer.startswith("external:") else "agent"
            if cid in by_id:
                # Overlapping chunks re-emit the same triple; the first claim
                # wins and only gains the later chunk's evidence (G118).
                first = by_id[cid]
                for ev in rel_evidence:
                    if ev not in first.evidence:
                        first.evidence.append(ev)
                first.reactions = clean_reactions(first.reactions + list(rel.get("reactions") or []))
                if first.observer != observer:
                    # G179: the person's own words (or Cicada's reading) back it too — no longer only theirs.
                    first.observer = "agent"
                first.expected_end = first.expected_end or expected_end
                continue
            claim = Claim(
                id=cid,
                text=f"{source} {raw_label} {target}",
                subject=subject,
                predicate=predicate,
                object=obj,
                object_kind="node",
                observer=observer,
                context="general",
                epistemic="explicit",
                source_trust="agent_extracted",
                confidence=float(rel.get("confidence", 0.6) or 0.6),
                valid_from=valid_from or None,
                source_episodes=[ep] if ep else [],
                origin=origin,
                evidence=rel_evidence,
                expected_end=expected_end,
                session_ids=list(sessions),
                reactions=clean_reactions(rel.get("reactions")),
            )
            # The pre-normalization label (for the Stage-3 normalization audit).
            setattr(claim, "predicate_raw", raw_label)
            at = str(rel.get("at", "") or "").strip()
            if at and depends_on(predicate):
                # W7: the organisation a working relationship belongs to — Stage 3 ties it to that job's claim.
                setattr(claim, "premise_at", to_id(at))
            by_id[cid] = claim
            claims.append(claim)
        for value in extraction.get("values", []) or []:
            claim = _value_claim(value, episode_id, origin, to_id)
            if claim is None:
                continue
            claim.session_ids = list(sessions)
            if claim.id in by_id:
                first = by_id[claim.id]
                for ev in claim.evidence:
                    if ev not in first.evidence:
                        first.evidence.append(ev)
                continue
            by_id[claim.id] = claim
            claims.append(claim)
    return claims


def _value_claim(value: dict, episode_id: str, origin: str, to_id: Callable[[str], str]):
    """One stated value (``values[]``, 2026-10-17) as a literal claim on its entity: predicate
    ``claims.value_predicate(attribute)``, object the value as stated. A value predicate is single-valued
    (``claims.is_value_claim``), so a later value of the same thing supersedes the earlier one in Stage 3 instead of
    sitting beside it in prose — the LongMemEval knowledge-update misses of 2026-10-17 had no claim to supersede."""
    from api.services.claims import Claim, Evidence, clean_reactions, value_predicate

    entity = str(value.get("entity", "") or "").strip()
    attribute = str(value.get("attribute", "") or "").strip()
    stated = " ".join(str(value.get("value", "") or "").split())
    predicate = value_predicate(attribute)
    if not entity or not predicate or not stated or len(stated) > 120:
        return None
    subject = str(value.get("source_page") or "") or to_id(entity)
    if not subject:
        return None
    ep = str(value.get("source_episode", "") or episode_id)
    valid_from = _claim_date(value.get("source_episode_timestamp"), ep)
    raw_observer = str(value.get("observer") or "")
    return Claim(
        id=_emit_claim_id(subject, predicate, stated, valid_from),
        text=f"{entity} {attribute}: {stated}",
        subject=subject, predicate=predicate, object=stated, object_kind="literal",
        observer=raw_observer if raw_observer.startswith("external:") else "agent",
        context="general", epistemic="explicit", source_trust="agent_extracted", confidence=0.6,
        valid_from=valid_from or None, source_episodes=[ep] if ep else [], origin=origin,
        evidence=[Evidence.from_dict(e) for e in (value.get("evidence") or []) if isinstance(e, dict)],
        reactions=clean_reactions(value.get("reactions")),
    )


def _slug_label(label: str) -> str:
    import re

    s = (label or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "relates-to"
