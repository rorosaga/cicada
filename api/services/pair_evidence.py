"""What a "Possible duplicate" question between two PEOPLE must rest on (owner 2026-11-04; G209, G169, ruling 29).

The owner, on "Is <handle> the same as <owner>?" (Cicada's guess 0.90, its evidence a chat with someone else that never
named either side): "why tf would <handle> be me?" Measured on a copy of the owner's bank (real values redacted): the
lead came from a link to a POST by that handle written on the owner's page (a post the owner shared), read as the
owner's own account; it was raised whenever any conversation matched the owner's page, so the evidence was that
unrelated conversation; and "Cicada's guess" was the extractor's confidence that the matched mention exists, never a
measure of the pair. Three rules follow, one module, engine-free, read by every producer through
``ClarificationManager.create`` and by Sleep's tending of the questions already open (``inbox_tend``):

* **The owner's page is never paired with another person** unless the person's own words name themselves by that
  name or handle (:func:`self_named`): a located line in one of their own turns ("I'm <h>", "my handle is <h>",
  "soy <h>", "me llamo <h>" …), or the name/handle they gave Cicada for themselves (``owner.json``). A link on their
  page, an alias Sleep wrote there, a shared word in a description: none of these is the person saying who they are.
* **The evidence names both sides** (:func:`pair_episode`): one conversation whose text names a spelling of each (the
  page's name, its aliases, the mention as said), whole words. That conversation becomes the question's
  ``source_episode``, so the card's excerpt is about the pair. For two people, no such conversation means no question:
  the mention goes on by the usual rule. A question the record itself raises with no conversation (two pages holding
  the same one-at-a-time relation, ``role_people``) carries its reason in words and is exempt.
* **"Cicada's guess" is a guess about the pair** (:func:`guess`): never above :data:`MAX_GUESS` — a question exists
  because Cicada cannot tell, and at ruling 29's act threshold (``inbox_tend.JUDGE_THRESHOLD``, 0.9) Sleep would act on
  its own — and never above :data:`UNPAIRED_GUESS` when no conversation names both.

Never a model call, never a network call; reads the bank's files and its lexical index only (``search_service``,
words, prefix mode). Nothing here writes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from api.services import text_fold

#: A question is asked because Cicada cannot tell: its guess stays below ruling 29's act threshold (0.9).
MAX_GUESS = 0.8
#: No conversation names both sides: a lead on the record alone.
UNPAIRED_GUESS = 0.4
#: The guess each producer's lead is worth when a conversation names both (its base; :func:`guess` bounds it).
BASE_GUESS = {
    "named_handle": 0.8,    # the record paired the two in one mention: "Full Name (handle)"
    "profile": 0.7,         # a page links that account as its own (its sources)
    "alias": 0.6,           # a page lists the other's name among its own
    "held_alias": 0.6,      # a conversation also called the mention by the page's name
    "given_name": 0.5,      # a full name said once; a page carries the given name alone
    "cross_source": 0.4,    # one first name, heard in two places
    "judge": 0.5,           # the judge read both and could not tell
}
#: How many conversations the lexical index is asked for, per spelling, and how many spellings per side.
SEARCH_PER_NAME = 8
MAX_NAMES = 4
#: How old the lexical index may be before a search here brings it up to date (one Sleep batch asks many questions).
FRESH_S = 30.0
#: The words a person uses to name themselves (folded: lower case, accents off, punctuation kept). The name follows
#: at once and ends the phrase: "I'm <h>." / "I'm <h>, a student" / "soy <h> y …" — never "I'm <h>'s fan" or
#: "I'm <h>-ing" or "I'm <h> mode", which is another word built on it.
_SELF_LEADS = (
    r"i\s*'?\s*a?m", r"my name(?:\s+is|\s*'s)", r"call me", r"i go by", r"i\s*'?\s*m called", r"people call me",
    r"my (?:handle|username|user\s*name|user|nick|nickname|alias|account|tag)\s+is",
    r"my (?:x|twitter|github|instagram|linkedin|telegram|discord)(?:\s+(?:handle|account|username|user))?\s+is",
    r"soy", r"me llamo", r"mi nombre es", r"me dicen", r"me llaman",
    r"mi (?:usuario|handle|nick|apodo|cuenta|alias)\s+es",
)
_END = r"(?=\s*$|\s*[,.;:!?)\]]|\s+(?:and|y|on|en|from|de|here|aqui|btw|by|a|an|un|una|the|el|la)\b)"


def _fold(text) -> list[str]:
    return text_fold.words(str(text or ""))


def spelling(text) -> str:
    """A name as compared here: folded words joined by one space."""
    return " ".join(_fold(text))


def side_names(memory_path: Path | None, entity_id: str, name: str = "") -> list[str]:
    """Every spelling of one side: the name as said, the page's name and its aliases (never one the person removed),
    its id with spaces. Folded, two letters or more, de-duplicated, the said name first."""
    from api.services import bank_index

    raw = [name]
    if memory_path is not None and entity_id:
        entry = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
        fm = (entry.frontmatter or {}) if entry is not None else {}
        removed = {spelling(a) for a in (fm.get("aliases_removed") or []) if isinstance(a, str)}
        raw += [fm.get("name"), *[a for a in (fm.get("aliases") or []) if isinstance(a, str)
                                  and spelling(a) not in removed]]
        if entry is not None:
            raw.append(entity_id.replace("-", " ").replace("_", " "))
    out: list[str] = []
    for value in raw:
        key = spelling(value)
        if len(key) >= 2 and key not in out:
            out.append(key)
    return out


def names_in(names: list[str], text: str | None) -> bool:
    """Does ``text`` say one of ``names`` as whole words?"""
    if not text or not names:
        return False
    hay = f" {spelling(text)} "
    return any(f" {n} " in hay for n in names if n)


def _text(memory_path: Path, episode_id: str) -> str:
    from api.services import evidence

    if not episode_id or not str(episode_id).startswith("ep_"):
        return ""
    return evidence.source_text(Path(memory_path), episode_id) or ""


def fresh_index(memory_path: Path) -> str:
    """Bring the lexical index up to date, inline (a new bank's may not be built yet); its state, never raises."""
    from api.services import search_index

    try:
        return search_index.ensure_fresh(Path(memory_path), wait=True, max_age_s=FRESH_S)
    except Exception:  # noqa: BLE001 — a derived index only finds less
        return "unavailable"


def _search(memory_path: Path, names: list[str], *, fresh: bool = True) -> list[str]:
    """The conversations the lexical index finds for these spellings, best first; ``[]`` when it cannot be read.
    ``fresh=False`` (a read path): the index as it is, never a wait for a build."""
    from api.services import search_service

    if fresh:
        fresh_index(memory_path)
    out: list[str] = []
    for name in names[:MAX_NAMES]:
        try:
            hits = search_service.search(Path(memory_path), name, kinds=("episode",), mode="prefix",
                                         per_kind=SEARCH_PER_NAME, vectors=False).results
        except Exception:  # noqa: BLE001 — a derived index never fails a question; it only finds less
            return out
        out += [str(h.episode_id or h.id) for h in hits if str(h.episode_id or h.id or "").startswith("ep_")]
    return list(dict.fromkeys(out))


def pair_episode(memory_path: Path | None, a_names: list[str], b_names: list[str], *, first: str = "",
                 also: tuple[str, ...] = (), fresh: bool = True) -> str | None:
    """The conversation that names both sides (a spelling of each, whole words): ``first`` when it does, then ``also``
    (the pages' own conversations), then what the lexical index finds for either side. ``None`` when none does."""
    if memory_path is None or not a_names or not b_names:
        return None
    memory_path = Path(memory_path)
    seen: set[str] = set()

    def both(eid: str) -> bool:
        if not eid or eid in seen:
            return False
        seen.add(eid)
        text = _text(memory_path, eid)
        return names_in(a_names, text) and names_in(b_names, text)

    for eid in (first, *also):
        if both(eid):
            return eid
    for eid in _search(memory_path, [*a_names[:2], *b_names[:2]], fresh=fresh):
        if both(eid):
            return eid
    return None


def owner_id(memory_path: Path | None) -> str | None:
    """The bank's ``owner: true`` page, from the frontmatter cache."""
    from api.services import bank_index

    if memory_path is None:
        return None
    try:
        for f in bank_index.files(Path(memory_path), "entities"):
            if (f.frontmatter or {}).get("owner") is True:
                return f.stem
    except Exception:  # noqa: BLE001
        return None
    return None


@dataclass(frozen=True)
class SelfNamed:
    """The person naming themselves by a name: ``episode`` and ``quote`` (a located line of their own turn), or
    ``declared`` (the name or handle they gave Cicada for themselves)."""
    episode: str = ""
    quote: str = ""
    declared: bool = False


def _declared(names: list[str]) -> bool:
    from api.services import owner_identity

    try:
        data = owner_identity.load_owner()
    except Exception:  # noqa: BLE001
        return False
    own = {spelling(data.get(k)) for k in ("name", "handle", "username", "nickname") if data.get(k)}
    own.discard("")
    return any(n in own for n in names)


def _names_self(line: str, names: list[str]) -> bool:
    """Does ``line`` (one sentence of the person's own turn) name the speaker by one of ``names``?"""
    folded = text_fold.fold(line).replace("’", "'")
    for name in names:
        core = r"[\s\-_.]+".join(re.escape(w) for w in name.split())
        if not core:
            continue
        pattern = rf"(?<![\w'])(?:{'|'.join(_SELF_LEADS)})\s+@?{core}{_END}"
        if re.search(pattern, folded):
            return True
    return False


def self_named(memory_path: Path | None, names: list[str], *, fresh: bool = True,
               episodes: tuple[str, ...] = ()) -> SelfNamed | None:
    """The person's own words naming themselves by one of ``names`` (folded spellings), or ``None``: the name or handle
    they gave Cicada for themselves, else a line of one of their own turns (``kind: user``, never an agent's words or
    someone else's) in ``episodes`` (read first, directly) or found through the lexical index. Bounded:
    :data:`SEARCH_PER_NAME` conversations per spelling."""
    from api.services import authorship, evidence, inbox_tend

    names = [n for n in names if n]
    if not names:
        return None
    if _declared(names):
        return SelfNamed(declared=True)
    if memory_path is None:
        return None
    memory_path = Path(memory_path)
    for eid in dict.fromkeys([*(e for e in episodes if e), *_search(memory_path, names, fresh=fresh)]):
        doc = evidence.source_document(memory_path, eid)
        if doc is None:
            continue
        ep_fm, text = doc
        turns = inbox_tend.person_turns({"content": text, authorship.KEY: authorship.of(ep_fm),
                                         "gaps": evidence.gap_ranges(ep_fm, text), "source": ep_fm.get("source")})
        for turn in turns:
            for line in re.split(r"(?<=[.!?])\s+|\n+", turn):
                if names_in(names, line) and _names_self(line, names):
                    return SelfNamed(episode=eid, quote=" ".join(line.split())[:240])
    return None


#: The cited claim a public-handle check writes (ruling 54, ``web_settle.settle_handle``): "<Name> goes by
#: <handle>", on the named page, its object the handle's page. While it stands, the pair is not asked again.
GOES_BY = "goes-by"


def answered_by_check(memory_path: Path | None, a_id: str, b_id: str) -> bool:
    """Does the record hold a current ``goes-by`` claim between the two pages, either way?"""
    from api.services import entity_relations
    from api.services.id_utils import sanitize_id

    if memory_path is None or not a_id or not b_id or a_id == b_id:
        return False
    for subject, other in ((a_id, b_id), (b_id, a_id)):
        for claim in entity_relations._page_claims(Path(memory_path), subject):
            if (claim.valid_to is None and str(claim.predicate or "").lower() == GOES_BY
                    and other in (str(claim.object or ""), sanitize_id(str(claim.object or "")))):
                return True
    return False


def episode_timestamp(memory_path: Path | None, episode_id: str) -> str | None:
    from api.services import bank_index

    if memory_path is None or not episode_id:
        return None
    entry = bank_index.file(Path(memory_path), "episodes", f"{episode_id}.md")
    value = (entry.frontmatter or {}).get("timestamp") if entry is not None else None
    return str(value) if value else None


def guess(base: float | None, paired: bool) -> float:
    """Cicada's guess about the pair: the lead's ``base``, never above :data:`MAX_GUESS`, never above
    :data:`UNPAIRED_GUESS` when no conversation names both."""
    try:
        value = float(base if base is not None else BASE_GUESS["judge"])
    except (TypeError, ValueError):
        value = BASE_GUESS["judge"]
    value = max(0.0, min(value, MAX_GUESS))
    return round(min(value, UNPAIRED_GUESS) if not paired else value, 2)


@dataclass(frozen=True)
class Verdict:
    """``ask`` — may the question be raised; ``reason`` — an enum when not (``owner_unsaid``, ``no_pair_evidence``);
    ``episode`` — the conversation naming both, when one does; ``guess`` — Cicada's guess for the card."""
    ask: bool
    reason: str = ""
    episode: str | None = None
    guess: float = 0.0


def _is_person_page(memory_path: Path | None, entity_id: str) -> bool:
    from api.services import bank_index

    if memory_path is None or not entity_id:
        return False
    entry = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
    fm = (entry.frontmatter or {}) if entry is not None else {}
    return str(fm.get("type") or "").strip().lower() == "person" or fm.get("owner") is True


def judge(memory_path: Path | None, *, a_id: str, a_name: str, b_id: str, b_name: str = "", person: bool,
          source_episode: str = "", base: float | None = None, owner: str | None = None,
          fresh: bool = True, two_places: bool = False) -> Verdict:
    """Whether "Is A the same as B?" may be asked, on what conversation, with what guess. ``person``: the question is
    about people (either side a person page, or the mention classified as one). ``source_episode`` empty: the record
    raised it with no conversation (``role_people``'s one-at-a-time relation) — exempt from the evidence rule, never
    from the owner rule. ``fresh=False`` (Stage 2, inside Sleep's event loop): the lexical index as it is, never a wait
    for a build — the conversations that matter most (the question's own, the pages' own) are read directly.
    ``two_places``: a first name heard in one place against a full name heard in another (owner 2026-10-28, one person
    across sources) — its evidence is the two conversations, each naming its own side, said in the question's words
    (``heard_in``); exempt from the one-conversation rule, never from the owner rule."""
    owner = owner if owner is not None else owner_id(memory_path)
    a_names = side_names(memory_path, a_id, a_name)
    b_names = side_names(memory_path, b_id, b_name)
    if owner and owner in (a_id, b_id) and (person or _is_person_page(memory_path, b_id if a_id == owner else a_id)):
        other_id, other_names = (b_id, b_names) if a_id == owner else (a_id, a_names)
        if other_id != owner and self_named(memory_path, other_names, fresh=fresh,
                                            episodes=(str(source_episode or ""),)) is None:
            return Verdict(False, "owner_unsaid")
    also: tuple[str, ...] = ()
    if memory_path is not None:
        from api.services import bank_index

        for eid in (a_id, b_id):
            entry = bank_index.file(Path(memory_path), "entities", f"{eid}.md") if eid else None
            eps = [str(e) for e in ((entry.frontmatter or {}).get("source_episodes") or [])] if entry else []
            also += tuple(eps[-SEARCH_PER_NAME:][::-1])
    episode = pair_episode(memory_path, a_names, b_names, first=source_episode, also=also, fresh=fresh)
    if person and episode is None and str(source_episode or "").strip() and not two_places:
        return Verdict(False, "no_pair_evidence")
    return Verdict(True, "", episode, guess(base, episode is not None or not str(source_episode or "").strip()))
