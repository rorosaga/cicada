"""Which conversations are with an AI agent — an opt-in, replaceable detector registry (G188; Instinct first, G179).

A texted agent is not a Cicada engine and not a transport: the registry is its own seam, separate from the message
reader (``messages_source``) and from the inference providers (G50). A detector reads only metadata the person's
listed conversation already shows — the contact's or chat's name and how many messages each side sent — never a
message's words, never a phone number or an address.

A result is ``identified`` | ``uncertain`` | ``unknown``, with the detector id and version and the signal that matched
(the spec's acceptance: "a synthetic Instinct match is recognized when enabled; a similarly named human is not
confidently classified; ambiguous cases are surfaced"). **A name alone is never proof:** an exact name is
``uncertain`` until the conversation also has an agent's cadence — the other side writing at least twice as many
messages as the person, over enough of them to mean something (the owner's real conversation, measured by the
coordinator: 716 from the agent to 191 from the person, the agent answering in bursts). A human friend who happens to
be called that writes about as much as the person, so stays ``uncertain`` — surfaced as a question, never applied.

What detection may never do (G188): select a conversation, widen what is read, raise trust, or make an agent's words
the person's. It only suggests the actor kind of a conversation the person already sees; the person's own choice
(:func:`resolve_actor`) always wins, and with detection off every conversation is ``unknown`` until the person says.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

IDENTIFIED = "identified"
UNCERTAIN = "uncertain"
UNKNOWN = "unknown"
OUTCOMES = (IDENTIFIED, UNCERTAIN, UNKNOWN)

#: The actor kinds a conversation's other side can have.
AGENT = "agent"
PERSON = "person"
ACTOR_KINDS = (AGENT, PERSON)

#: An agent's cadence: the other side wrote at least this many messages…
MIN_AGENT_MESSAGES = 20
#: …and at least this many times as many as the person did.
AGENT_RATIO = 2.0


@dataclass(frozen=True)
class ConversationMeta:
    """What a detector may look at — the names and counts the Settings list already shows."""

    name: str = ""
    display_name: str = ""
    group: bool = False
    from_me: int = 0
    from_them: int = 0


@dataclass(frozen=True)
class Detection:
    outcome: str = UNKNOWN
    detector: str | None = None
    version: int | None = None
    signal: str | None = None
    label: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def fold(name: str) -> str:
    """A name as compared: accents, case, emoji and punctuation gone, spaces collapsed."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


def agent_cadence(meta: ConversationMeta) -> bool:
    them, me = max(int(meta.from_them or 0), 0), max(int(meta.from_me or 0), 0)
    return them >= MIN_AGENT_MESSAGES and them >= AGENT_RATIO * max(me, 1)


class InstinctDetector:
    """Instinct, the agent the owner texts over iMessage (owner, 2026-10-15). Signals: the conversation's own name —
    the contact's or the chat's — folded, plus the agent cadence above. Nothing else is known about how Instinct
    presents itself, and nothing is invented (the spec: verify signals, don't make them up)."""

    id = "instinct"
    version = 1
    label = "Instinct"
    #: Names that ARE this agent, folded. "Instinct AI" is how a person might save the contact.
    exact = frozenset({"instinct", "instinct ai", "instinct agent"})

    def detect(self, meta: ConversationMeta) -> Detection:
        names = [n for n in (fold(meta.name), fold(meta.display_name)) if n]
        if meta.group or not names:
            return Detection()
        exact = any(n in self.exact for n in names)
        partial = not exact and any("instinct" in n.split() for n in names)
        cadence = agent_cadence(meta)
        if exact and cadence:
            return self._hit(IDENTIFIED, "name+cadence")
        if exact:
            return self._hit(UNCERTAIN, "name")
        if partial and cadence:
            return self._hit(UNCERTAIN, "partial-name+cadence")
        return Detection()

    def _hit(self, outcome: str, signal: str) -> Detection:
        return Detection(outcome=outcome, detector=self.id, version=self.version, signal=signal, label=self.label)


#: The registry, in the order detectors are asked. Adding one is a class here; removing one removes its suggestions
#: and nothing else — a person's own choice and every saved conversation are untouched.
DETECTORS: tuple = (InstinctDetector(),)


def detect(meta: ConversationMeta, *, enabled: bool = True, detectors: tuple | None = None) -> Detection:
    """The strongest suggestion any detector makes — ``identified`` over ``uncertain`` — or ``unknown``."""
    if not enabled:
        return Detection()
    best = Detection()
    for detector in DETECTORS if detectors is None else detectors:
        found = detector.detect(meta)
        if found.outcome == IDENTIFIED:
            return found
        if found.outcome == UNCERTAIN and best.outcome == UNKNOWN:
            best = found
    return best


@dataclass(frozen=True)
class Actor:
    """Who the other side of a conversation is, and who decided it."""

    kind: str | None          # agent | person | None (unknown)
    label: str                # the name its turns carry
    decided_by: str           # person | detector | none
    detection: Detection

    def to_dict(self) -> dict:
        out = {"name": self.label, "kind": self.kind or UNKNOWN, "decided_by": self.decided_by}
        if self.detection.detector:
            out["detector"] = f"{self.detection.detector}@{self.detection.version}"
            out["detection"] = self.detection.outcome
            out["signal"] = self.detection.signal
        return out


def resolve_actor(name: str, override: dict | None, detection: Detection) -> Actor:
    """The person's choice, else an ``identified`` detection, else unknown. An ``uncertain`` detection is a question
    the app asks, never an answer applied here."""
    label = " ".join(str(name or "").split())[:80] or "Unnamed conversation"
    override = override if isinstance(override, dict) else {}
    if override.get("kind") in ACTOR_KINDS:
        custom = " ".join(str(override.get("label") or "").split())[:80]
        return Actor(kind=override["kind"], label=custom or label, decided_by="person", detection=detection)
    if detection.outcome == IDENTIFIED:
        return Actor(kind=AGENT, label=label, decided_by="detector", detection=detection)
    return Actor(kind=None, label=label, decided_by="none", detection=detection)
