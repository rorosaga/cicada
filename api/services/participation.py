"""A relationship that says someone took part in something needs the text to say their role (G118, ruling 43).

2026-10-27 trace: an agent's memory note said the person's application answer was "the <competition> story". The
source says they never took part in it. An agent reading the note
said the person "has" the competition, and Sleep, reading the same line, could write "<person> competed in
<competition>". A mention, "a story about", "the topic of" is not taking part — least of all in an agent's summary,
which compresses.

So a relationship whose label claims participation or achievement — competed in, took part in, won, attended,
worked at, interned at, studied at, graduated from — is read against its own located evidence (the G118 span the
extractor verified), widened to the span's sentence and one sentence either side:

- **An agent's or a summary's words** (any evidence kind but the person's own ``user`` turns — where the trace's
  misread came from): kept only when the window says a role of that family, a word of the family not negated ("did
  not compete"). Otherwise re-labelled ``mentioned``.
- **The person's own words**: kept unless the window positively shows a topic marker ("story", "about", "essay on",
  "topic") and no role word. People say their roles every way ("my new gig at …", "I'm at … since June"); only a
  topic is evidence against them.
- **No located span**: kept. G118 — an unlocatable quote becomes reasoning and the claim is still written;
  provenance never blocks memory.

A relabel keeps the link between the two and drops the claim of taking part with the days it carried (STARTS, ENDS,
AT). Pure: no I/O, no model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MENTIONED = "mentioned"


@dataclass(frozen=True)
class Family:
    name: str
    label: re.Pattern
    role: re.Pattern


def _rx(words: str) -> re.Pattern:
    return re.compile(rf"\b(?:{words})", re.IGNORECASE)


def _lead(words: str) -> re.Pattern:
    """A label that STARTS with the claim of taking part: "competed in", never "competes with" or "planned to
    attend" (a plan, a rivalry and a topic are not taking part, and they are not this rule's to judge)."""
    return re.compile(rf"^\s*(?:{words})", re.IGNORECASE)


#: Each family: the label that claims it (anchored at its start), and the words that say that role in the source text
#: (English and Spanish, the languages the person writes in). A role word is matched at a word start, so "compet"
#: covers compete, competed, competing, competition, competitor.
FAMILIES: tuple[Family, ...] = (
    Family("won", _lead(r"(?:won|wins|winner of|awarded|placed (?:first|second|third|\d+\w*) (?:in|at)|"
                        r"finalist (?:in|at|of)|champion of|medal(?:led|ed)? (?:in|at))\b"),
           _rx(r"won\b|win|winner|award|prize|placed|place\b|finalist|champion|medal|podium|ranked|runner.up|"
               r"gan[oóa]|premio|campe[oó]n|(?:got|came|finished|took) (?:first|second|third|1st|2nd|3rd)\b")),
    Family("competed", _lead(r"(?:competed|competes|competing|took part|takes part|taking part|participated|"
                             r"participates|participating|raced|played) (?:in|at)\b"),
           _rx(r"compet|took part|take part|taking part|participa|played|race|raced|racing|entered|enter\b|"
               r"qualified\b|qualifying for|team\b|contestant|finalist|placed|won\b|win|medal|submitted|submission|pitched|"
               r"presented|hacked|did the\b|doing the\b|(?:i|we) did\b|joined|joining|our team|my team|compit|concurs")),
    Family("attended", _lead(r"(?:attended|attends|attending)\b"),
           _rx(r"attend|went|go(?:es|ing)? to|visit|was at|were at|been to|came to|joined|there\b|arrived|"
               r"spoke at|presented at|registered|ticket|participa|took part|talk|workshop|session|keynote|"
               r"asist|fui\b|fuimos|fuimos a|estuve|estuvimos|estoy en|estaba en|(?:i|we) did\b|trip\b")),
    Family("worked", _lead(r"(?:works|worked|working|interns|interned|interning|employed|is employed|was employed)"
                           r" (?:at|for|by)\b|(?:researcher|engineer|employee|intern) at\b|hired by\b"),
           _rx(r"work|job|employ|intern|hired|hire\b|joined|join\b|role|position|staff|team\b|offer|contract|"
               r"engineer|researcher|developer|manager|founder|co.?founded|founded|lead\b|head of|as an?\b|"
               r"started at|starting at|start at|onboard|colleague|boss|salary|advisor|adviser|coordinator|"
               r"assistant|specialist|director|officer|analyst|consultant|scientist|professor|lecturer|ceo\b|"
               r"cto\b|software|designer|architect|associate|fellow\b|yrs?\b|mos\b|@|trabaj|empleo|becari|"
               r"pr[aá]cticas|puesto|collaborat|gig\b|i'?m at\b|i am at\b|since\b|"
               r"\(\s*\d{4}\s*[-–]\s*(?:\d{4}|present|now|today)\s*\)")),
    Family("studied", _lead(r"(?:studies|studied|studying|is a student|was a student|student|enrolled|is enrolled|"
                            r"was enrolled) (?:at|in)\b|graduated from\b|alumn(?:us|a|i) of\b"),
           _rx(r"stud(?:y|ies|ied|ying|ent)|enrol|graduat|degree|bachelor|master|phd|class of|major|course|"
               r"thesis|semester|campus|alumn|diploma|scholarship|admitted|admission|\bgpa\b|year at|"
               r"estudi|matricul|grado|carrera|curso|universidad|gradu[eé]|\(\s*\d{4}\s*[-–]\s*\d{4}\s*\)")),
)

_NEGATION = re.compile(r"\b(?:not|never|didn'?t|did not|no longer|wasn'?t|was not|without|nor)\b[\w\s,'-]{0,24}$",
                       re.IGNORECASE)


def family_of(label: str) -> Family | None:
    """The participation family a relationship label claims, or ``None``. ``won`` is tried first: "won" is its own
    claim, stronger than "competed"."""
    text = " " + " ".join(str(label or "").replace("-", " ").replace("_", " ").split()) + " "
    for family in FAMILIES:
        if family.label.search(text):
            return family
    return None


def says_role(family: Family, text: str) -> bool:
    """Does ``text`` say a role of ``family`` — a role word that is not negated just before it?"""
    for match in family.role.finditer(text or ""):
        if not _NEGATION.search(text[max(0, match.start() - 40):match.start()]):
            return True
    return False


#: What says a thing was the subject of words, not something taken part in.
TOPIC = re.compile(r"\b(?:stor(?:y|ies)|about|essay (?:on|about)|topic|anecdote|historia|sobre|tema)\b",
                   re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?]\s|\n")
_SPEAKER = re.compile(r"^\s*(?:assistant|user|system|speaker:[^:\n]{0,80}|attachment \[[^\]\n]*\])\s*:\s*",
                      re.IGNORECASE | re.MULTILINE)
#: The person's own turns (``evidence.kind``); every other kind is an agent's, a summary's or a document's.
PERSON_KIND = "user"


def _window(body: str, start: int, end: int) -> str:
    """The span's sentence plus one sentence either side."""
    before = [m.end() for m in _SENTENCE_END.finditer(body, 0, start)]
    after = [m.start() + 1 for m in _SENTENCE_END.finditer(body, end)]
    lo = before[-2] if len(before) >= 2 else 0
    hi = after[1] if len(after) >= 2 else len(body)
    return _SPEAKER.sub("", body[lo:hi])   # "assistant:" is who spoke, never the role word "assistant"


def located(rel: dict, body: str) -> list[tuple[str, str]]:
    """``[(window, kind)]`` for every span the extractor located for ``rel`` (its ``evidence``, G118)."""
    out = []
    for ev in rel.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        start, end = ev.get("start"), ev.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(body):
            out.append((_window(body, start, end), str(ev.get("kind") or "")))
    return out


def verdict(family: Family, spans: list[tuple[str, str]]) -> bool:
    """True when the located words do NOT support the claim of taking part (the relationship becomes a mention)."""
    if not spans:
        return False   # G118: no located quote is reasoning, and the claim is still written
    text = "\n".join(w for w, _k in spans)
    if says_role(family, text):
        return False
    if all(k == PERSON_KIND for _w, k in spans):
        return bool(TOPIC.search(text))   # the person's own words: only a topic marker speaks against them
    return True


def hold(rel: dict, body: str) -> str | None:
    """Re-label ``rel`` to :data:`MENTIONED` when it claims participation its evidence does not state, in place.

    Returns the label it had (for a count), else ``None``. The relationship keeps its endpoints, evidence and
    observer; only the claim of taking part, and the days that claim carried, go."""
    label = str(rel.get("label") or "")
    family = family_of(label)
    if family is None or not verdict(family, located(rel, body)):
        return None
    rel["label"] = MENTIONED
    for day in ("starts", "ends", "at"):
        rel.pop(day, None)
    return label
