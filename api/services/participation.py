"""A relationship that says someone took part in something needs the text to say their role (G118, ruling 43).

2026-10-27 trace: an agent's memory note said the person's application answer was "the <competition> story". The
source says they never took part in it. An agent reading the note
said the person "has" the competition, and Sleep, reading the same line, could write "<person> competed in
<competition>". A mention, "a story about", "the topic of" is not taking part — least of all in an agent's summary,
which compresses.

So a relationship whose label claims participation or achievement — competed in, took part in, won, attended,
worked at, interned at, studied at, graduated from — is kept only when its own located evidence (the G118 span the
extractor verified) says a role of that kind: a word of the family, not negated ("did not compete"). Otherwise it is
re-labelled ``mentioned`` — the link between the two stays, the claim of taking part does not — and its STARTS/ENDS
days go with the participation. A relationship with no located quote (the model's own inference) is held to the same
bar: an inference never supplies the role. Pure: no I/O, no model.
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
               r"gan[oóa]|premio|campe[oó]n")),
    Family("competed", _lead(r"(?:competed|competes|competing|took part|takes part|taking part|participated|"
                             r"participates|participating|raced|played) (?:in|at)\b"),
           _rx(r"compet|took part|take part|taking part|participa|played|race|raced|racing|entered|enter\b|"
               r"qualified\b|qualifying for|team\b|contestant|finalist|placed|won\b|win|medal|submitted|submission|pitched|"
               r"presented|hacked|did the\b|doing the\b|joined|joining|our team|my team|compit|concurs")),
    Family("attended", _lead(r"(?:attended|attends|attending)\b"),
           _rx(r"attend|went|go(?:es|ing)? to|visit|was at|were at|been to|came to|joined|there\b|arrived|"
               r"spoke at|presented at|registered|ticket|participa|took part|talk|workshop|session|keynote|"
               r"asist|fui\b|fuimos|estuve")),
    Family("worked", _lead(r"(?:works|worked|working|interns|interned|interning|employed|is employed|was employed)"
                           r" (?:at|for|by)\b|(?:researcher|engineer|employee|intern) at\b|hired by\b"),
           _rx(r"work|job|employ|intern|hired|hire\b|joined|join\b|role|position|staff|team\b|offer|contract|"
               r"engineer|researcher|developer|manager|founder|co.?founded|founded|lead\b|head of|as an?\b|"
               r"started at|starting at|start at|onboard|colleague|boss|salary|advisor|adviser|coordinator|"
               r"assistant|specialist|director|officer|analyst|consultant|scientist|professor|lecturer|ceo\b|"
               r"cto\b|software|designer|architect|associate|fellow\b|yrs?\b|mos\b|@|trabaj|empleo|becari|"
               r"pr[aá]cticas|puesto|collaborat")),
    Family("studied", _lead(r"(?:studies|studied|studying|is a student|was a student|student|enrolled|is enrolled|"
                            r"was enrolled) (?:at|in)\b|graduated from\b|alumn(?:us|a|i) of\b"),
           _rx(r"stud(?:y|ies|ied|ying|ent)|enrol|graduat|degree|bachelor|master|phd|class of|major|course|"
               r"thesis|semester|campus|alumn|diploma|scholarship|admitted|admission|\bgpa\b|year at|"
               r"estudi|matricul|grado|carrera|curso|universidad")),
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


def located_text(rel: dict, body: str) -> str:
    """The text of every span the extractor located for ``rel`` (its ``evidence``, G118), joined; "" for none."""
    parts = []
    for ev in rel.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        start, end = ev.get("start"), ev.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(body):
            parts.append(body[start:end])
    return "\n".join(parts)


def hold(rel: dict, body: str) -> str | None:
    """Re-label ``rel`` to :data:`MENTIONED` when it claims participation its evidence does not state, in place.

    Returns the label it had (for a count), else ``None``. The relationship keeps its endpoints, evidence and
    observer; only the claim of taking part, and the days that claim carried, go."""
    label = str(rel.get("label") or "")
    family = family_of(label)
    if family is None:
        return None
    if says_role(family, located_text(rel, body)):
        return None
    rel["label"] = MENTIONED
    for day in ("starts", "ends", "at"):
        rel.pop(day, None)
    return label
