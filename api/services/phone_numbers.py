"""A number the person gives for someone: consolidated, kept out of every bank (G81, PROPOSED ruling 55, 2026-11-04).

The owner texted an agent the numbers of two people and expected memory to file each on the right page and follow it
when it changes. A chat's scrub (`episode_scrub.scrub_phones`) destroys a ``+`` number before it is stored, so whether
that worked depended on how it was typed; a bare digit run reached the bank and the engine in clear.

**The design: a token in the bank, the digits in a vault on this Mac.** In the person's own lines of a ticked chat, a
number becomes ``[number:<ten letters>]`` before the stager sees it; the digits go to
``$CICADA_HOME/people/<bank>/numbers.json`` (0600, outside every bank and git, `people_directory`). The token is an HMAC
of the number's last nine digits under a key that lives only in that vault, so the same number written two ways is one
token, and an unsalted hash's trivial brute force (a phone number has about 10^10 values) is not open to whoever holds
the bank. Everything downstream handles the token: Stage 1 reads it, the claim's object is it, git holds it, every door
serves it. **Only :func:`reveal` turns a token back into digits**, and only the app's route calls it.

**What stays off.** OFF until the owner rules (``CICADA_PHONE_NUMBERS=on``, :func:`enabled`). Off, nothing is minted and
every path is byte for byte what it was: bodies, prompts and hashes. A bank that already holds tokens keeps being read
right (the note and the conversion follow the token, not the switch), so turning it off never strands them.

**Why old chats are not re-read.** A stored sitting is rebuilt from its own body, so a stored line never passes through
here; and a line a reader posts again (*Read again*) keeps its stored words when they are what the old scrub or this
one would make of it (:func:`tokenise_batch`). Only a new message, or a real edit, can hold a new token. Numbers
already ``[redacted]`` stay redacted: the app could re-post them, but that is a person-started read for the owner to
ask for, not something a switch does.

**Whose words.** Only the person's own lines are tokenised. An agent's reply and another speaker's line keep today's
redaction: the agent's echo is not evidence, and a correspondent's "my new number is X" is exactly the shape of the
"hi, it's me, new number" fraud, so it never reaches a page. A forwarded message is someone else's words too.

**Contacts.** The app posts a card's numbers as this same keyed hash (never the digits, R-SR8 holds) to a file beside
the vault. It can confirm a page's one-word name and flag a number that belongs to another page's card; it never writes
or closes a claim, because the person did not say it.

Pure over its files and engine-free. Nothing here logs a number or a token.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import os
import re
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from api.services import episode_scrub, people_directory

#: The claim predicate a number lands under: the one `contacts_local.FACT_PREDICATES` already names for a card's fact.
PREDICATE = "phone"
VAULT_FILE = "numbers.json"
CARDS_FILE = "contact_numbers.json"
TOKEN_RE = re.compile(r"\[number:([a-z]{10})\]")
TOKEN_ID_RE = re.compile(r"^[a-z]{10}$")
#: How many trailing digits identify a number: a country code and a trunk zero fall off the front ("+34 612 345 678" and
#: "612 345 678", "+33 6 12 34 56 78" and "06 12 34 56 78"). A shorter number is compared as written, so the same
#: 8-digit number with and without its country code reads as two numbers: then Sleep asks, it never assumes.
MATCH_DIGITS = 9
MIN_DIGITS, MAX_DIGITS = 7, 15
_LOCK = threading.RLock()

#: A value item's key on an extraction (`take`): the token this entry files (`entity_extractor._value_claim`).
ITEM_KEY = "number_token"
#: A claim's ``context`` while it waits on the person: closed, so no reader takes it for current, and kept on the page,
#: so the answer has something to reopen and a restatement finds it instead of asking again.
ASKED = "number_asked"
REFUSED = "number_refused"
#: How a person's line relates a number to the ones the page holds (:func:`classify`).
CHANGED, ADDITIONAL, PAST, UNKNOWN = "changed", "additional", "past", "unknown"
#: Why a question is about the name rather than the number (`annotate`).
ASK_NAME = "name"
ASK_CARD = "card"


_PHONE_LABEL = re.compile(r"(?i)\b(phone|cell|mobile|m[oó]vil|celular|tel[eé]fono|telephone|whatsapp|contact number|"
                          r"number|n[uú]mero|num[eé]ro)\b")
_ONLY_DIGITS = re.compile(r"^[+()\d][\d .\-()]{5,22}\d$")


def enabled() -> bool:
    """OFF until the owner rules on proposed ruling 55; ``CICADA_PHONE_NUMBERS=on`` turns it on."""
    return os.environ.get("CICADA_PHONE_NUMBERS", "off").strip().lower() in ("on", "1", "true", "yes")


def token(token_id: str) -> str:
    return f"[number:{token_id}]"


def token_ids(text: str | None) -> list[str]:
    return TOKEN_RE.findall(text or "")


def has_token(text: str | None) -> bool:
    return bool(TOKEN_RE.search(text or ""))


def is_number_claim(claim) -> bool:
    return getattr(claim, "predicate", None) == PREDICATE and bool(TOKEN_RE.fullmatch(str(getattr(claim, "object", ""))))


def same_number(held: str | None, new_token: str, settings) -> bool:
    """Whether a ``phone`` claim's object is this token: as a token, or as digits a model wrote there before this rule
    (compared under the vault's key, minting nothing)."""
    if held == new_token:
        return True
    if not held or has_token(held):
        return False
    path = getattr(settings, "memory_path", None)
    return bool(path) and known_id(Path(path).name, held) in token_ids(new_token)


# ---- one number, one fact ----------------------------------------------------------------------------------------

def match_digits(raw: str | None) -> str | None:
    """What identifies a number however it was written, or ``None`` for what is not a number's length."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if not MIN_DIGITS <= len(digits) <= MAX_DIGITS:
        return None
    return digits[-MATCH_DIGITS:]


def _letters(digest: bytes) -> str:
    """The first eight bytes of a digest as ten lowercase letters: nothing a digit rule (`episode_scrub`) can ever read
    as a number, and the same in the app's Swift (`PhoneNumberKeys`)."""
    value = int.from_bytes(digest[:8], "big")
    out = []
    for _ in range(10):
        value, rest = divmod(value, 26)
        out.append(chr(ord("a") + rest))
    return "".join(out)


def _display(raw: str) -> str:
    return " ".join(str(raw).replace("tel:", "").replace("TEL:", "").replace("wa.me/", "").split())


@contextmanager
def _vault_lock(bank: str):
    """The vault is one read-modify-write across the backend and any other process on this Mac."""
    people_directory.ensure(bank)
    with _LOCK:
        with open(people_directory.path(bank, f".{VAULT_FILE}.lock"), "a") as handle:
            os.chmod(handle.name, 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _load(bank: str) -> dict:
    data = people_directory.load_json(bank, VAULT_FILE)
    if not isinstance(data.get("numbers"), dict):
        data["numbers"] = {}
    if not data.get("key"):
        data["key"] = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    return data


def _token_id(key_b64: str, digits: str) -> str:
    return _letters(hmac.new(base64.b64decode(key_b64), digits.encode("ascii"), hashlib.sha256).digest())


def match_key(bank: str) -> str:
    """The vault's key, for the app alone: it hashes a card's numbers on this Mac so no digit crosses the wire."""
    with _vault_lock(bank):
        data = _load(bank)
        people_directory.save_json(bank, VAULT_FILE, data)
        return str(data["key"])


def mint_many(bank: str, raws: Iterable[str]) -> dict[str, str]:
    """``{raw: token id}``, one vault write for all of them. A written form with a ``+`` replaces one without, because
    it says more; a raw that is no number's length is left out."""
    wanted = [(raw, digits) for raw in raws if (digits := match_digits(raw))]
    if not wanted:
        return {}
    out: dict[str, str] = {}
    with _vault_lock(bank):
        data = _load(bank)
        before = dict(data["numbers"])
        for raw, digits in wanted:
            tid = _token_id(data["key"], digits)
            out[raw] = tid
            shown = _display(raw)
            held = data["numbers"].get(tid)
            if held is None or (shown.startswith("+") and not str(held).startswith("+")):
                data["numbers"][tid] = shown
        if data["numbers"] != before or not people_directory.path(bank, VAULT_FILE).exists():
            people_directory.save_json(bank, VAULT_FILE, data)
    return out


def claim_value(bank: str, label: str | None, stated: str | None) -> str | None:
    """A phone-labelled value in digits as its token, when the feature is on; ``None`` for everything else."""
    if not enabled() or not _PHONE_LABEL.search(str(label or "").replace("-", " ")):
        return None
    stated = (stated or "").strip()
    if not _ONLY_DIGITS.match(stated):
        return None
    minted = mint_many(bank, [stated])
    return token(minted[stated]) if stated in minted else None


def known_id(bank: str, raw: str | None) -> str | None:
    """The token id ``raw`` would get, minting nothing: for comparing a number a page already holds in clear."""
    digits = match_digits(raw)
    if not digits:
        return None
    with _vault_lock(bank):
        data = people_directory.load_json(bank, VAULT_FILE)
    return _token_id(data["key"], digits) if data.get("key") else None


def reveal(bank: str, token_ids_wanted: Iterable[str]) -> dict[str, str]:
    """THE door from a token to its digits: ``{token id: number as written}`` for those the vault holds. Called only by
    the app's route (`routers/sources`), which refuses every device token and is on no remote listener."""
    held = people_directory.load_json(bank, VAULT_FILE).get("numbers")
    if not isinstance(held, dict):
        return {}
    return {t: str(held[t]) for t in token_ids_wanted if t in held}


# ---- the person's own lines --------------------------------------------------------------------------------------

_KEYWORD = (r"phone|cell(?:phone)?|mobile|m[oó]vil|celular|cel|tel[eé]fono|telefono|t[eé]l[eé]phone|portable|telefon|"
            r"handy|whatsapp|wsp|contact")
_NUMBER_WORD = r"numbers?|n[uú]mero|num[eé]ro|nummer|no\.?|\#"
_DIGITS = r"\+?\(?\d[\d .\-()]{5,20}\d"
#: "her number is 555…", "phone: 555…", "cell 555…", "call him at 555…", "llámala al 555…".
_SAID_RE = re.compile(
    rf"(?i)(?:(?<![\w])(?:{_KEYWORD})(?:\s+(?:{_NUMBER_WORD}))?|(?<![\w])(?:{_NUMBER_WORD})"
    r"|(?<![\w])(?:call|text|ring|message|reach|llam\w*|escr[ií]b\w*)\s+(?:\w+\s+)?(?:at|on|al|en)"
    rf")\s*(?:is|es|est|ist|[:=\-→])?\s*(?P<num>{_DIGITS})(?![\w])")
#: "Ana 5550100000", "Ana Diaz: 555 010 0000": a word, then what can only be a long number.
_NAMED_RE = re.compile(r"(?P<word>[^\W\d_]{2,})['’]?s?\s*[:,\-]?\s*(?P<num>\d[\d .\-()]{7,20}\d)(?![\w])")
#: The word before a digit run that says it is not somebody's phone: "order number 123456789", "invoice 123456789".
_NOT_A_PHONE = frozenset(
    "order orders tracking account invoice flight booking reservation reference ref case ticket confirmation serial "
    "card room rooms seat table page pages version model part sku item id code zip postcode price cost total paid pay "
    "budget amount salary rent balance year years date from to between pedido vuelo cuenta factura reserva habitación "
    "precio total pagado commande vol facture bestellung konto rechnung".split())
_DATEISH = re.compile(r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})(?:\D|$)")
_YEAR_GROUP = re.compile(r"^(?:19|20)\d{2}$")


def _plausible_bare(raw: str) -> bool:
    """A run with no ``+`` or bracket, after a word or keyword: never a date, a year list or a price's shape."""
    text = raw.strip()
    if _DATEISH.match(text) or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", text):
        return False
    groups = re.split(r"[ .\-()]+", text)
    if len(groups) > 1 and all(_YEAR_GROUP.match(g) for g in groups if g):
        return False
    return True


def _before(text: str, at: int) -> set[str]:
    """The two words before ``at``: "order number 123456789" is an order's whichever of them the rule read."""
    return {w.lower() for w in re.findall(r"[^\W\d_]+", text[:at])[-2:]}


def _spans(text: str) -> list[tuple[int, int, str]]:
    """Every number in the person's line: ``(start, end, raw)``, earliest first, none overlapping."""
    found: list[tuple[int, int, str]] = []

    def add(start: int, end: int, raw: str) -> None:
        if not any(start < e and s < end for s, e, _ in found):
            found.append((start, end, raw))

    for rx in episode_scrub.PHONE_SHAPES:   # the shapes the chat scrub already calls a phone, the mention aside
        for m in rx.finditer(text):
            if episode_scrub.phone_shaped(m):
                add(m.start(), m.end(), m.group(0))
    for rx in (_SAID_RE, _NAMED_RE):
        for m in rx.finditer(text):
            raw = m.group("num")
            start = m.start("num")
            before = _before(text, start)
            digits = sum(c.isdigit() for c in raw)
            least = MIN_DIGITS if rx is _SAID_RE else MATCH_DIGITS
            if least <= digits <= MAX_DIGITS and not before & _NOT_A_PHONE and _plausible_bare(raw):
                # A currency sign just before it, or a word glued after it, is not a phone.
                if start and text[start - 1] in "$€£¥":
                    continue
                add(start, m.end("num"), raw)
    return sorted(found)


def tokenise(text: str, bank: str) -> tuple[str, int]:
    """The person's own line with each number replaced by its token; ``(text, how many)``."""
    spans = _spans(text or "")
    if not spans:
        return text, 0
    ids = mint_many(bank, [raw for _s, _e, raw in spans])
    out, last, count = [], 0, 0
    for start, end, raw in spans:
        tid = ids.get(raw)
        if tid is None:
            continue
        out += [text[last:start], token(tid)]
        last = end
        count += 1
    return "".join(out) + text[last:], count


def tokenise_batch(messages: list, stored: dict, *, writer: str, bank: str) -> int:
    """Incoming chat messages, before the stager (`messages_source.ingest`, `chat_live.ingest`). Only the person's own
    new or edited words are tokenised. A message posted again keeps its stored words whenever they are what the old
    scrub or this one makes of what was posted, so an old sitting's body, its hash and the Sleep queue do not move
    (the owner's rule that an edit in place reads as a revision: a re-read of old chats would cost a model call each).
    ``stored``: ``{message key: stored message}``. Returns how many numbers were tokenised."""
    if not enabled() and not any(has_token(getattr(m, "text", "")) for m in stored.values()):
        return 0
    count = 0
    for m in messages:
        if m.unsent or not m.text:
            continue
        mine = m.from_me and not getattr(m, "forwarded_from", None)
        old = stored.get(m.key)
        if old is not None:
            cleaned = episode_scrub.scrub_for(m.text, writer)[0]
            if cleaned == old.text:
                m.text = old.text
                continue
            if not mine:
                continue
            if enabled():
                tokened, _ = tokenise(m.text, bank)
                if episode_scrub.scrub_for(tokened, writer)[0] == old.text:
                    m.text = old.text
                    continue
            elif has_token(old.text):
                # Switched off with tokens stored: a line whose digits are gone either way is the stored line.
                if TOKEN_RE.sub(episode_scrub.REDACTED, old.text) == cleaned:
                    m.text = old.text
                    continue
        if enabled() and mine:
            m.text, n = tokenise(m.text, bank)
            count += n
    return count


# ---- Stage 1 -----------------------------------------------------------------------------------------------------

NOTE = (
    "[Cicada's note, not part of the conversation: [number:<letters>] stands for a phone number the user typed; its "
    "digits are kept out of this text on purpose. When the user's own line says whose number it is, add one entry to "
    'values: entity = that person\'s name as the user gave it ("the user" for their own number), attribute = "phone '
    'number", value = the whole token, brackets included, exactly as written, evidence_quote = the user\'s words. One entry per person and '
    "number. Never guess whose it is: with no name in the user's words, leave it out. Never put the token in a summary, "
    "a key fact, a history entry, a link or an open question: a page's prose does not carry it.]\n\n")



def _person_span(content: str, tid: str, episode_id: str, *, override, gaps) -> dict | None:
    """The first of the person's own lines holding this token, as a located span: a token is unique in the body, so
    this does not depend on what the model quoted."""
    from api.services import evidence

    needle = token(tid)
    at = content.find(needle)
    while at != -1:
        if evidence.kind_for(episode_id, content, at, override, gaps) == "user":
            head = max(content.rfind("\n", 0, at) + 1, at - 100)
            tail = content.find("\n", at)
            tail = min(tail if tail != -1 else len(content), at + len(needle) + 100)
            start = head + (len(content[head:at]) - len(content[head:at].lstrip()))
            if content[start:].startswith("user: "):
                start += len("user: ")
            quote = content[start:tail].rstrip()
            ev = evidence.verify(None, episode_id, quote, text=content, window=(start, tail), kind_override=override,
                                 gaps=gaps)
            if ev.kind == "user":
                return ev.to_dict()
        at = content.find(needle, at + 1)
    return None


def _raw_person_span(content: str, raw: str, episode_id: str, *, override, gaps) -> dict | None:
    """The first of the person's lines holding these digits, however grouped (a writer with no chat scrub: a harness
    session, a note). The body keeps them as it always has; the claim does not."""
    from api.services import evidence

    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    pattern = re.compile(r"[ .\-()]*".join(re.escape(d) for d in digits))
    for m in pattern.finditer(content):
        if evidence.kind_for(episode_id, content, m.start(), override, gaps) != "user":
            continue
        head = max(content.rfind("\n", 0, m.start()) + 1, m.start() - 100)
        tail = content.find("\n", m.end())
        tail = min(tail if tail != -1 else len(content), m.end() + 100)
        start = head + (len("user: ") if content[head:].startswith("user: ") else 0)
        ev = evidence.verify(None, episode_id, content[start:tail].rstrip(), text=content, window=(start, tail),
                             kind_override=override, gaps=gaps)
        if ev.kind == "user":
            return ev.to_dict()
    return None


def _clean_strings(value, loose: re.Pattern[str] | None = None):
    """A page's prose never carries a token: a fact holding one is dropped, any other string says "a number"."""
    def holds(text: str) -> bool:
        return has_token(text) or bool(loose and loose.search(text))

    if isinstance(value, str):
        text = TOKEN_RE.sub("a number", value)
        return loose.sub("a number", text) if loose else text
    if isinstance(value, list):
        return [_clean_strings(v, loose) for v in value if not (isinstance(v, str) and holds(v))]
    if isinstance(value, dict):
        return {k: _clean_strings(v, loose) for k, v in value.items()}
    return value


def take(entities: list, relationships: list, values: list, content: str, episode_id: str, *, bank: str,
         override: str | None = None, gaps=()) -> int:
    """What Stage 1 made of the numbers in this conversation, in place, before anything downstream reads it.

    Each is one value entry (:data:`ITEM_KEY`), resting on the person's own located line or dropped: a number only an
    agent or another speaker gave never lands, whatever the model wrote. On a writer that keeps digits in its body, a
    model's ``phone``-shaped relationship or value is minted here when the feature is on, so no claim stores digits.
    Every token leaves the prose. Returns how many entries were kept."""
    mine = has_token(content)
    if not mine and not enabled():
        return 0
    # A model copies a token loosely (measured at haiku: the ten letters alone, no brackets), so what it wrote is read
    # against the tokens this conversation actually holds, never against the token's shape alone.
    here = set(token_ids(content))
    loose = re.compile(r"(?<![a-z])(" + "|".join(sorted(here)) + r")(?![a-z])") if here else None

    def strip(value):
        return _clean_strings(value, loose)

    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def file(name: str, tid: str | None, raw: str | None, confidence=None) -> None:
        name = (name or "").strip()
        if not name or not tid:
            return
        key = (name.casefold(), tid)
        if key in seen:
            return
        span = (_person_span(content, tid, episode_id, override=override, gaps=gaps) if raw is None
                else _raw_person_span(content, raw, episode_id, override=override, gaps=gaps))
        if span is None:
            return
        seen.add(key)
        entries.append({"entity": name, "attribute": "phone number", "value": token(tid), ITEM_KEY: tid,
                        "evidence": [span]})

    def read(name: str, label: str, stated: str) -> bool:
        ids = (loose.findall(stated) if loose else []) or token_ids(stated)
        if ids:
            for tid in ids:
                file(name, tid, None)
            return True
        if enabled() and _PHONE_LABEL.search(label or "") and _ONLY_DIGITS.match((stated or "").strip()):
            minted = mint_many(bank, [stated.strip()])
            file(name, minted.get(stated.strip()), stated.strip())
            return bool(minted)
        return False

    rest = [r for r in relationships
            if not read(str(r.get("source") or ""), str(r.get("label") or ""), str(r.get("target") or ""))]
    relationships[:] = rest
    rest = [v for v in values
            if not read(str(v.get("entity") or ""), str(v.get("attribute") or ""), str(v.get("value") or ""))]
    values[:] = rest + entries
    if mine:
        for i, entity in enumerate(entities):
            if isinstance(entity, dict):
                entities[i] = strip(entity)
    named = {str(e.get("name") or "").casefold() for e in entities if isinstance(e, dict)}
    for entry in entries:
        # What is held for a name waits on its pending line, so the name must be one Stage 2 parks.
        if entry["entity"].casefold() not in named:
            named.add(entry["entity"].casefold())
            entities.append({"name": entry["entity"], "type": "person", "confidence": 0.6, "key_facts": [],
                             "summary": ""})
    return len(entries)


# ---- what the person's line says ---------------------------------------------------------------------------------

_CHANGED_RE = re.compile(
    r"(?i)\b(new|changed|changes|updated|update|switched|replaced|instead|now|no longer|not anymore|"
    r"nuev[oa]|cambi\w+|ahora|ya no|actualiz\w+|nouveau|nouvelle|chang[eé]\w*|novo|nova|mudou|neue?|ge[aä]ndert)\b")
_ADDITIONAL_RE = re.compile(
    r"(?i)\b(also|another|second|other|work|office|home|landline|too|as well|personal|business|"
    r"tambi[eé]n|otro|otra|segundo|segunda|trabajo|oficina|casa|fijo|aussi|autre|travail|auch|arbeit|zweite)\b")
_PAST_RE = re.compile(
    r"(?i)\b(old|former|previous|used to|was|antiguo|antigua|viejo|vieja|anterior|ancien|ancienne|alte|alter)\b")


def classify(line: str) -> str:
    """How the person's line relates this number to what the page holds. A word for it, or :data:`UNKNOWN`, which asks:
    a miss costs one question, a wrong close would lose nothing but be wrong."""
    text = TOKEN_RE.sub(" ", line or "")
    if _CHANGED_RE.search(text):
        return CHANGED
    if _PAST_RE.search(text):
        return PAST
    if _ADDITIONAL_RE.search(text):
        return ADDITIONAL
    return UNKNOWN


def _line_of(memory_path: Path, claim) -> str | None:
    from api.services import evidence

    for ev in claim.evidence or []:
        if not ev.is_span() or ev.kind != "user":
            continue
        text = evidence.source_text(memory_path, ev.episode)
        if not text or ev.end > len(text):
            continue
        start = text.rfind("\n", 0, ev.start) + 1
        end = text.find("\n", ev.end)
        return text[start:end if end != -1 else len(text)]
    return None


def _page_of(memory_path: Path, subject: str) -> dict | None:
    from api.services import markdown_parser
    from api.services.id_utils import bank_file

    path = bank_file(Path(memory_path) / "entities", subject) if subject else None
    if path is None or not path.is_file():
        return None
    try:
        return dict(markdown_parser.parse(path).frontmatter or {})
    except Exception:  # noqa: BLE001 - an unreadable page reads as a page we know nothing about
        return {}


def cards_of(bank: str) -> dict[str, list[str]]:
    """``{token id: [card ids]}`` from the app's last Contacts sync; a card marked the person's own is ``me``."""
    data = people_directory.load_json(bank, CARDS_FILE).get("numbers")
    return data if isinstance(data, dict) else {}


def save_cards(bank: str, cards: dict[str, list[str]]) -> None:
    """Rewritten whole by every Contacts sync (`contacts_local.sync`), like the waiting cards beside it: keyed hashes
    and opaque card ids, never a digit. A value not shaped like a token id is refused at the door."""
    clean = {k: sorted(set(v)) for k, v in cards.items() if TOKEN_ID_RE.match(str(k))}
    people_directory.save_json(bank, CARDS_FILE, {"numbers": clean})


def _carried_cards(fm: dict) -> set[str]:
    from api.services.contact_identity import REF_SCHEME

    out: set[str] = set()
    for source in fm.get("sources") or []:
        ref = str(source.get("ref") or "") if isinstance(source, dict) else ""
        if ref.startswith(REF_SCHEME):
            out.add(ref[len(REF_SCHEME):])
    return out


def annotate(incoming: list, memory_path: Path, owner_id: str | None) -> tuple[list, list[dict]]:
    """Before Stage 3, on every number claim (a held one released too): what the person's line says (``number_change``,
    in memory only, read again whenever the claim is), and whether its page may take it. Returns the claims to place
    and audit rows.

    Dropped: a claim on a page that is no person, or with no located line of the person's. Asked: a one-word name that
    is not the owner's and not a relation's (`role_people`'s ``unnamed``), since two people can answer to it. A card
    holding this number and carried by that page settles the name; a card carried by a DIFFERENT page asks."""
    memory_path = Path(memory_path)
    kept: list = []
    audit: list[dict] = []
    cards: dict[str, list[str]] | None = None
    for claim in incoming:
        if not is_number_claim(claim):
            kept.append(claim)
            continue
        line = _line_of(memory_path, claim)
        if line is None:
            audit.append({"action": "number_no_line", "dropped": claim.id})
            continue
        claim.number_change = classify(line)
        ids = token_ids(line)
        tid = token_ids(claim.object)[0]
        claim.number_replaces = [t for t in ids[:ids.index(tid)]] if tid in ids else []
        fm = _page_of(memory_path, claim.subject)
        if fm is None:      # no page yet: Stage 5's write-back holds it on the name's pending line
            kept.append(claim)
            continue
        if fm and str(fm.get("type") or "person") != "person":
            audit.append({"action": "number_not_a_person", "dropped": claim.id})
            continue
        if claim.subject == owner_id:
            kept.append(claim)
            continue
        if cards is None:
            cards = cards_of(memory_path.name)
        held_by = set(cards.get(tid) or [])
        carried = _carried_cards(fm)
        name = str(fm.get("name") or "").strip()
        if held_by and carried and not held_by & carried:
            claim.number_ask = ASK_CARD
        elif len(name.split()) < 2 and not fm.get("unnamed") and not (held_by & carried):
            claim.number_ask = ASK_NAME
        kept.append(claim)
    return kept, audit


def shared_pairs(reconciled: dict[str, list], touched: Iterable[str], *, owner_id: str | None) -> list[tuple[str, str]]:
    """Person pages holding the same current number as a page this pass touched: a duplicate-people signal (G209). A
    question, never a merge: a household shares a line. Never the owner: a number the owner gave out is not who they
    are (`pair_evidence`'s rule)."""
    wanted = set(touched)
    if not wanted:
        return []
    holders: dict[str, set[str]] = {}
    for subject, claims in reconciled.items():
        for claim in claims:
            if is_number_claim(claim) and claim.valid_to is None:
                holders.setdefault(claim.object, set()).add(subject)
    pairs: set[tuple[str, str]] = set()
    for obj in wanted:
        pages = sorted(p for p in holders.get(obj, ()) if p != owner_id)
        pairs.update((a, b) for i, a in enumerate(pages) for b in pages[i + 1:])
    return sorted(pairs)
