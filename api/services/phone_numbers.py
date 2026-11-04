"""A number the person gives for someone: consolidated, kept out of every bank (G81, PROPOSED ruling 55, 2026-11-04).

The owner texted an agent the numbers of two people and expected memory to file each on the right page and follow it
when it changes. A chat's scrub (`episode_scrub.scrub_phones`) destroys a ``+`` number before it is stored, so whether
that worked depended on how it was typed; a bare digit run reached the bank and the engine in clear.

**The design: a token in the bank, the digits in a vault on this Mac.** In the person's own lines of a ticked chat, a
number becomes ``[number:<ten letters>]`` before the stager sees it; every written form goes to
``$CICADA_HOME/people/<bank>/numbers.json`` (0600, outside every bank and git, `people_directory`). The token is an HMAC
of the number's last nine digits under a key that lives only in that vault, so the same number written two ways is one
token, and an unsalted hash's trivial brute force (a phone number has about 10^10 values) is not open to whoever holds
the bank. Two different numbers sharing their last nine digits (two country codes) never share a token
(:func:`_token_for`). Everything downstream handles the token: Stage 1 reads it, the claim's object is it, git holds it,
every door serves it. **Only :func:`reveal` turns a token back into digits**, and only the app's route calls it. Any
process running as this user can still read the vault file: it is private to the user, not to the app.

**The switch.** One file, ``$CICADA_HOME/numbers_switch.json`` (:func:`enabled`), which every process on this Mac reads:
the backend, a stdio MCP server, the CLI. Never an environment variable, which only some of them load. Off (no file),
nothing is minted and every path is byte for byte what it was. A bank that already holds tokens keeps being read right
(the note and the conversion follow the token, not the switch), so turning it off never strands them.

**What counts as a number.** A token replaces the digits in the stored words, so a bare digit run needs a positive signal
that it is a phone: a phone word right before it ("phone:", "su celular es"), a number word owned by someone ("her number
is", "Ana's new number is", not "my order number is"), or a call to reach them ("call Ana at"). Absence of a negative is
not a signal. The shapes the chat scrub already destroys count too: a token loses less than ``[redacted]``. A bare run
with none of these stays in the words, exactly as today: false negatives over lost words (#502).

**Why old chats are not re-read.** A stored sitting is rebuilt from its own body, so a stored line never passes through
here; and a line a reader posts again keeps its stored words when they are what the old scrub or this one makes of it
(:func:`tokenise_batch`). Only a new message, or a real edit, can hold a new token. Numbers already ``[redacted]`` stay
redacted: the app could re-post them, but that is a person-started read for the owner to ask for, not what a switch does.

**Whose words.** Only the person's own lines are tokenised. An agent's reply and another speaker's line keep today's
redaction: the agent's echo is not evidence, and a correspondent's "my new number is X" is exactly the shape of the
"hi, it's me, new number" fraud, so it never reaches a page. A forwarded message is someone else's words too.

**A vault that cannot be read is never replaced.** Damaged, unreadable, or gone while the bank holds tokens:
:class:`VaultUnavailable`, in words (:func:`problem`), the file kept, no new key. New numbers are redacted as they are
today until the person restores the file or asks for a new vault (:func:`new_vault`, which keeps the old one aside).

**Contacts.** The app posts a card's numbers as this same keyed hash (never the digits, R-SR8 holds) to a file beside
the vault. It can confirm a page's one-word name and flag a number that belongs to another page's card; it never writes
or closes a claim, because the person did not say it.

Engine-free. Nothing here logs a number or a token.
"""
from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from loguru import logger

from api.services import episode_scrub, people_directory

#: The claim predicate a number lands under: the one `contacts_local.FACT_PREDICATES` already names for a card's fact.
PREDICATE = "phone"
VAULT_FILE = "numbers.json"
CARDS_FILE = "contact_numbers.json"
SWITCH_FILE = "numbers_switch.json"
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
#: How a person's line relates a number to the ones the page holds (:func:`read_line`).
CHANGED, ADDITIONAL, PAST, UNKNOWN = "changed", "additional", "past", "unknown"
#: Why a question is about the name rather than the number (`annotate`).
ASK_NAME = "name"
ASK_CARD = "card"

#: The words that make a value a phone (:func:`is_phone_label`); the rest of a label may only qualify it.
_PHONE_WORDS = frozenset("phone telephone tel cell cellphone mobile whatsapp movil móvil celular telefono teléfono "
                         "telefon téléphone telephon portable handy wsp".split())
_LABEL_FILLER = frozenset("has have the his her their is a an of at value number numbers no num nr contact work home "
                          "personal office new current main private business second other old previous former".split())
_ONLY_DIGITS = re.compile(r"^(?:tel:)?[+()\d][\d .\-()]{5,22}\d$", re.IGNORECASE)


class VaultUnavailable(Exception):
    """The vault exists in principle and cannot be used now. ``str(e)`` is the sentence for the person, no number in it."""


def _name(bank) -> str:
    return bank.name if isinstance(bank, Path) else str(bank or "default")


# ---- the switch: one file every process reads ------------------------------------------------------------------------

def _switch_path() -> Path:
    root = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(root).expanduser() / SWITCH_FILE


_switch_memo: tuple[tuple[int, int], bool] | None = None


def enabled() -> bool:
    """OFF until the owner rules on proposed ruling 55. The answer is :data:`SWITCH_FILE`'s, read again whenever the file
    moves: the backend, a stdio MCP server and the CLI can never disagree. No file, or a damaged one, is off."""
    global _switch_memo
    path = _switch_path()
    try:
        st = path.stat()
    except OSError:
        return False
    key = (st.st_mtime_ns, st.st_size)
    if _switch_memo is not None and _switch_memo[0] == key:
        return _switch_memo[1]
    try:
        on = json.loads(path.read_text(encoding="utf-8")).get("on") is True
    except (OSError, ValueError, AttributeError):
        on = False
    _switch_memo = (key, on)
    return on


def set_enabled(on: bool, *, by: str = "person") -> dict:
    """The one writer of the switch (`PUT /people/numbers/switch`, `cicada numbers`). The record says who and when: this
    file is where a person's yes lives on their own Mac."""
    global _switch_memo
    record = {"on": bool(on), "at": datetime.now(timezone.utc).isoformat(), "by": by}
    path = _switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{SWITCH_FILE}.{os.getpid()}")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    _switch_memo = None
    return record


# ---- tokens --------------------------------------------------------------------------------------------------------

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
    if not path:
        return False
    try:
        return known_id(Path(path), held) in token_ids(new_token)
    except VaultUnavailable:
        return False


def is_phone_label(label: str | None) -> bool:
    """Whether a claim's label says phone: "phone", "phone_number", "mobile number", "has_phone", "tel", a bare
    "number" or "contact number". Never "membership number", "order number" or "mobile app version": every word must be a
    phone word or a word that only qualifies one."""
    words = [w for w in re.split(r"[\s_\-/:]+", str(label or "").strip().casefold()) if w]
    if not words:
        return False
    rest = [w for w in words if w not in _LABEL_FILLER]
    if rest:
        return all(w in _PHONE_WORDS for w in rest)
    return "number" in words or "numbers" in words


def _digits(raw: str | None) -> str:
    return re.sub(r"[^0-9]", "", str(raw or ""))   # ASCII only: the app's hash reads the same digits


def match_digits(raw: str | None) -> str | None:
    """What identifies a number however it was written, or ``None`` for what is not a number's length."""
    digits = _digits(raw)
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
    return " ".join(re.sub(r"(?i)^tel:|^wa\.me/", "", str(raw).strip()).split())


def _token_id(key_b64: str, digits: str) -> str:
    return _letters(hmac.new(base64.b64decode(key_b64), digits.encode("ascii"), hashlib.sha256).digest())


# ---- the vault ---------------------------------------------------------------------------------------------------

_DAMAGED = ("The private file that holds your numbers can't be read, so it was left as it is and no new number is being "
            "kept. Restore it from a backup, or start a new one.")
_GONE = ("The private file that holds your numbers is gone, and your memory still points at it, so no new number is "
         "being kept. Restore it from a backup, or start a new one.")


@contextmanager
def _vault_lock(bank):
    """The vault is one read-modify-write across the backend and any other process on this Mac."""
    name = _name(bank)
    people_directory.ensure(name)
    with _LOCK:
        with open(people_directory.path(name, f".{VAULT_FILE}.lock"), "a") as handle:
            os.chmod(handle.name, 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _read(name: str) -> dict | None:
    """The vault, ``None`` when there is no file, :class:`VaultUnavailable` when there is one this cannot trust. Never
    `people_directory.load_json`, whose ``{}`` on any error would read as "no vault" and mint a new key over the file."""
    path = people_directory.path(name, VAULT_FILE)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise VaultUnavailable(_DAMAGED) from exc
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("numbers"), dict):
            raise ValueError("shape")
        if len(base64.b64decode(str(data.get("key") or ""), validate=True)) != 32:
            raise ValueError("key")
    except (ValueError, binascii.Error) as exc:
        raise VaultUnavailable(_DAMAGED) from exc
    return data


def _holds_tokens(memory_path: Path) -> bool:
    """Whether this bank points at a vault. Read only when the vault file is missing, so once per bank at first use."""
    for sub in ("entities", "episodes"):
        folder = memory_path / sub
        if not folder.is_dir():
            continue
        for file in folder.iterdir():
            try:
                if file.is_file() and "[number:" in file.read_text(encoding="utf-8", errors="ignore"):
                    return True
            except OSError:
                continue
    pending = memory_path / "pending_entities.jsonl"
    try:
        return pending.is_file() and "[number:" in pending.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def park_for_trash(name: str, trashed_to: Path) -> None:
    """A bank moved to the trash takes its vault with it, beside it (`<root>/.trash/<bank>-<stamp>.numbers.json`). Trash
    is not deletion: every word of the bank waits there, and a bank restored by hand gets its numbers back
    (:func:`_restore_parked`). Emptying the trash removes both. The digits stay outside the bank and outside git:
    ``.trash/`` is excluded, and a file there is never a bank. Never raises: the bank has already moved."""
    source = people_directory.path(name, VAULT_FILE)
    if not source.is_file():
        return
    target = Path(trashed_to).with_name(f"{Path(trashed_to).name}.numbers.json")
    try:
        os.replace(source, target)
        os.chmod(target, 0o600)
    except OSError as exc:
        logger.warning(f"The trashed bank's number vault was not moved with it ({type(exc).__name__})")


def _restore_parked(memory_path: Path) -> bool:
    """A bank back from the trash finds its vault there (:func:`park_for_trash`), the newest for its name."""
    for root in (memory_path.parent, memory_path.parent.parent):
        trash = root / ".trash"
        if not trash.is_dir():
            continue
        parked = sorted(trash.glob(f"{memory_path.name}-*.numbers.json"))
        if parked:
            people_directory.ensure(memory_path.name)
            target = people_directory.path(memory_path.name, VAULT_FILE)
            os.replace(parked[-1], target)
            os.chmod(target, 0o600)
            return True
    return False


def _load(bank) -> dict:
    """The vault to write to: an existing one, a parked one, or a brand new one only for a bank that points at none."""
    name = _name(bank)
    data = _read(name)
    if data is not None:
        return data
    if isinstance(bank, Path):
        if _restore_parked(bank):
            data = _read(name)
            if data is not None:
                return data
        if _holds_tokens(bank):
            raise VaultUnavailable(_GONE)
    return {"key": base64.b64encode(secrets.token_bytes(32)).decode("ascii"), "numbers": {}}


def problem(bank) -> str | None:
    """The sentence to show when the vault can't be used, for this bank, in words; ``None`` when it can."""
    try:
        with _vault_lock(bank):
            if _read(_name(bank)) is None and isinstance(bank, Path) and _holds_tokens(bank):
                if not _restore_parked(bank):
                    return _GONE
    except VaultUnavailable as exc:
        return str(exc)
    return None


def new_vault(bank) -> dict:
    """The person's own act, when a vault is lost: a damaged or unreadable file is set aside whole, never deleted, and a
    new key begins. Old tokens stay in memory and show nothing; a number said again reads as a new one and asks."""
    name = _name(bank)
    with _vault_lock(bank):
        current = people_directory.path(name, VAULT_FILE)
        kept = None
        if current.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            kept = current.with_name(f"numbers.set-aside-{stamp}.json")
            os.replace(current, kept)
        people_directory.save_json(name, VAULT_FILE, {
            "key": base64.b64encode(secrets.token_bytes(32)).decode("ascii"), "numbers": {}})
    return {"set_aside": kept.name if kept else None}


def match_key(bank) -> str:
    """The vault's key, for the app alone: it hashes a card's numbers on this Mac so no digit crosses the wire."""
    with _vault_lock(bank):
        data = _load(bank)
        if not people_directory.path(_name(bank), VAULT_FILE).exists():
            people_directory.save_json(_name(bank), VAULT_FILE, data)
        return str(data["key"])


def _compatible(a: str, b: str) -> bool:
    """Whether two digit strings can be one number: one is the other with a country code or a trunk zero in front."""
    a, b = a.lstrip("0"), b.lstrip("0")
    return a.endswith(b) or b.endswith(a)


def _token_for(data: dict, digits: str) -> str:
    """The token of these digits. By their last nine, unless that token is already another number's: two country codes
    with the same last nine digits are two numbers, so the second is keyed on all of its digits. Lossless: every written
    form stays in the vault under its own number."""
    base = _token_id(data["key"], digits[-MATCH_DIGITS:])
    held = data["numbers"].get(base)
    forms = held.get("forms") if isinstance(held, dict) else None
    if not forms or all(_compatible(_digits(form), digits) for form in forms):
        return base
    return _token_id(data["key"], digits)


def _shown(forms: list[str]) -> str:
    """The form to show: one that says its country code, else the first the person wrote."""
    return next((f for f in forms if f.startswith("+")), forms[0])


def mint_many(bank, raws: Iterable[str]) -> dict[str, str]:
    """``{raw: token id}``, one vault write for all of them. Every written form is kept. A raw that is no number's length
    is left out. :class:`VaultUnavailable` when the vault can't be trusted: never a new key over it."""
    wanted = [(raw, digits) for raw in raws if match_digits(digits := _digits(raw))]
    if not wanted:
        return {}
    out: dict[str, str] = {}
    name = _name(bank)
    with _vault_lock(bank):
        data = _load(bank)
        before = json.dumps(data["numbers"], sort_keys=True)
        for raw, digits in wanted:
            tid = _token_for(data, digits)
            out[raw] = tid
            forms = (data["numbers"].get(tid) or {}).get("forms") or []
            shown = _display(raw)
            if shown not in forms:
                data["numbers"][tid] = {"forms": [*forms, shown]}
        if json.dumps(data["numbers"], sort_keys=True) != before or not people_directory.path(name, VAULT_FILE).exists():
            people_directory.save_json(name, VAULT_FILE, data)
    return out


def known_id(bank, raw: str | None) -> str | None:
    """The token id ``raw`` would get, minting nothing: for comparing digits with what is stored."""
    digits = _digits(raw)
    if not match_digits(digits):
        return None
    with _vault_lock(bank):
        data = _read(_name(bank))
    return _token_for(data, digits) if data else None


def claim_value(bank, label: str | None, stated: str | None) -> str | None:
    """A phone-labelled value in digits as its token, when the feature is on; ``None`` for everything else."""
    if not enabled() or not is_phone_label(label):
        return None
    stated = (stated or "").strip()
    if not _ONLY_DIGITS.match(stated):
        return None
    minted = mint_many(bank, [stated])
    return token(minted[stated]) if stated in minted else None


def reveal(bank, token_ids_wanted: Iterable[str]) -> dict[str, str]:
    """THE door from a token to its digits: ``{token id: number as written}`` for those the vault holds. Called only by
    the app's route (`routers/local_sources`), which refuses every device token and is on no remote listener."""
    try:
        data = _read(_name(bank))
    except VaultUnavailable:
        return {}
    held = (data or {}).get("numbers") or {}
    out = {}
    for tid in token_ids_wanted:
        forms = (held.get(tid) or {}).get("forms") if isinstance(held.get(tid), dict) else None
        if forms:
            out[tid] = _shown(forms)
    return out


# ---- the person's own lines --------------------------------------------------------------------------------------

_PHONE_WORD = (r"phone|telephone|cell(?:phone)?|mobile|m[oó]vil|celular|cel|tel[eé]fono|t[eé]l[eé]phone|portable|telefon|"
               r"handy|whatsapp|wsp|tel\.?")
_NUMBER_WORD = r"numbers?|n[uú]meros?|num[eé]ros?|nummer"
_QUALIFIER = (r"new|old|current|work|home|personal|second|other|former|previous|private|nuevo|nueva|viejo|vieja|antiguo|"
              r"antigua|otro|otra|actual|nouveau|nouvelle|ancien|ancienne|autre|novo|nova|neue?|alte?")
#: Who owns a number word: without one, "number 123456789" is an order, a seat, a flight, anything.
_WHOSE = (r"[^\W\d_]+['’]s|[^\W\d_]+s['’]|my|his|her|their|your|mi|su|tu|sa|son|ma|meu|seu|mein|sein|ihre?|"
          r"(?:el|la|le|o|a)\s+(?:" + _QUALIFIER + r")?\s*(?:de|del|d['’])\s*[^\W\d_]+")
_DIGITS = r"\+?\(?\d[\d .\-()]{5,20}\d"
_LINK = (r"\s*[:=\-–→,]?\s*(?:(?:it['’]?s|it is|that['’]?s|is|was|are|were|es|son|era|est|ist|é|now|ahora|from|de|desde|von|"
         r"to|a|at|on|por|al)\s+){0,3}")
#: A positive signal, nothing less: a phone word, a number word somebody owns, or a call to reach them.
_SAID_RE = re.compile(
    r"(?i)(?<![\w])(?:"
    rf"(?:{_PHONE_WORD})(?:\s+(?:{_NUMBER_WORD}|no\.?|\#))?"
    rf"|(?:{_WHOSE})\s+(?:(?:{_QUALIFIER}|{_PHONE_WORD})\s+){{0,2}}(?:{_NUMBER_WORD})"
    rf"|(?:{_NUMBER_WORD})\s+de\s+[^\W\d_]+"
    r"|(?:call(?:ing)?|text(?:ing)?|ring|message|reach|llam\w*|escr[ií]b\w*)\s+(?:[^\W\d_]+\s+){0,2}(?:at|on|al|en)\s+"
    rf"){_LINK}(?P<num>{_DIGITS})(?![\w@])(?![.\-/]\d)")
#: "from <number> to <number>", "<number> and <number>": once one is a number, the next in the list is too.
_NEXT_RE = re.compile(rf"(?i)\s*(?:,|and|y|or|o|to|a|por|→|->|/)\s*(?P<num>{_DIGITS})(?![\w@])(?![.\-/]\d)")
#: The word before that says this is not somebody's phone, even with a phone word near: "phone order number 12345678".
_NOT_A_PHONE = frozenset(
    "order orders tracking account invoice flight booking reservation reference ref case ticket confirmation serial "
    "card room rooms seat table page pages version model part sku item id code zip postcode price cost total paid pay "
    "budget amount salary rent balance year years date membership passport license licence member customer pedido vuelo "
    "cuenta factura reserva habitación precio pagado pasaporte commande vol facture bestellung konto rechnung".split())
_DATEISH = re.compile(r"^(?:\d{4}[-/. ]\d{1,2}[-/. ]\d{1,2}|\d{1,2}[-/. ]\d{1,2}[-/. ]\d{2,4})(?:\D|$)")
_YEAR_GROUP = re.compile(r"^(?:19|20)\d{2}$")


def _plausible(raw: str) -> bool:
    """A digit run after a positive signal, still never a date, an IP address or a year list."""
    text = raw.strip()
    if _DATEISH.match(text) or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", text):
        return False
    groups = [g for g in re.split(r"[ .\-()]+", text) if g]
    if len(groups) > 1 and all(_YEAR_GROUP.match(g) for g in groups):
        return False
    return MIN_DIGITS <= len(_digits(text)) <= MAX_DIGITS


def _before(text: str, at: int) -> set[str]:
    """The three words before ``at``: "my order number is 123456789" is an order's whichever of them the rule read."""
    return {w.lower() for w in re.findall(r"[^\W\d_]+", text[:at])[-3:]}


def _spans(text: str) -> list[tuple[int, int, str]]:
    """Every number in the person's line: ``(start, end, raw)``, earliest first, none overlapping."""
    found: list[tuple[int, int, str]] = []

    def add(start: int, end: int, raw: str) -> None:
        if not any(start < e and s < end for s, e, _ in found):
            found.append((start, end, raw))

    for rx in episode_scrub.PHONE_SHAPES:   # the shapes the chat scrub already destroys: a token loses less
        for m in rx.finditer(text):
            if episode_scrub.phone_shaped(m):
                add(m.start(), m.end(), m.group(0))
    for m in _SAID_RE.finditer(text):
        raw, start = m.group("num"), m.start("num")
        if not _plausible(raw) or _before(text, m.start()) & _NOT_A_PHONE or _before(text, start) & _NOT_A_PHONE:
            continue
        add(start, m.end("num"), raw)
        end = m.end("num")
        while (follow := _NEXT_RE.match(text, end)) and _plausible(follow.group("num")):
            add(follow.start("num"), follow.end("num"), follow.group("num"))
            end = follow.end("num")
    return sorted(found)


def tokenise(text: str, bank) -> tuple[str, int]:
    """The person's own line with each number replaced by its token; ``(text, how many)``. With a vault that can't be
    used, the numbers are redacted, as the scrub does today, and it says so: no digit reaches the bank by a failure."""
    spans = _spans(text or "")
    if not spans:
        return text, 0
    try:
        ids = mint_many(bank, [raw for _s, _e, raw in spans])
    except VaultUnavailable:
        logger.warning("A number in a chat was redacted: the private number file can't be used")
        ids = None
    out, last, count = [], 0, 0
    for start, end, raw in spans:
        tid = None if ids is None else ids.get(raw)
        if ids is not None and tid is None:
            continue
        out += [text[last:start], episode_scrub.REDACTED if tid is None else token(tid)]
        last = end
        count += 1
    return "".join(out) + text[last:], count


def _retoken(text: str, bank) -> str:
    """The line as this rule would store it, minting nothing: a number the vault doesn't know stays as digits."""
    out, last = [], 0
    for start, end, raw in _spans(text or ""):
        tid = known_id(bank, raw)
        if tid:
            out += [text[last:start], token(tid)]
            last = end
    return "".join(out) + text[last:]


def _shape(text: str) -> str:
    """A line with its numbers, tokens and redactions all blanked: what is left to compare when the vault can't be read."""
    masked = TOKEN_RE.sub("#", text or "").replace(episode_scrub.REDACTED, "#")
    return re.sub(_DIGITS, "#", masked)


def _is_stored_line(posted: str, stored: str, writer: str, bank) -> bool:
    """Whether a line posted again is the line already stored: what today's scrub, or this rule, makes of it. The token of
    an EDITED number differs, so a real edit is never read as a re-post while the vault can be read."""
    cleaned = episode_scrub.scrub_for(posted, writer)[0]
    if cleaned == stored:
        return True
    if not has_token(stored):
        return False
    try:
        return episode_scrub.scrub_for(_retoken(posted, bank), writer)[0] == stored
    except VaultUnavailable:
        return _shape(cleaned) == _shape(stored)


def tokenise_batch(messages: list, stored: dict, *, writer: str, bank) -> int:
    """Incoming chat messages, before the stager (`messages_source.ingest`, `chat_live.ingest`). Only the person's own
    new or edited words are tokenised. A message posted again keeps its stored words (:func:`_is_stored_line`), so an old
    sitting's body, its hash and the Sleep queue do not move: an edit in place reads as a revision, and a re-read of old
    chats would cost a model call each. ``stored``: ``{message key: stored message}``. Returns how many were tokenised."""
    on = enabled()
    if not on and not any(has_token(getattr(m, "text", "")) for m in stored.values()):
        return 0
    count = 0
    for m in messages:
        if m.unsent or not m.text:
            continue
        old = stored.get(m.key)
        if old is not None and _is_stored_line(m.text, old.text, writer, bank):
            m.text = old.text
            continue
        if on and m.from_me and not getattr(m, "forwarded_from", None):
            m.text, n = tokenise(m.text, bank)
            count += n
    return count


# ---- Stage 1 -----------------------------------------------------------------------------------------------------

NOTE = (
    "[Cicada's note, not part of the conversation: [number:<letters>] stands for a phone number the user typed; its "
    "digits are kept out of this text on purpose. When the user's own line says whose number it is, add one entry to "
    'values: entity = that person\'s name as the user gave it ("the user" for their own number), attribute = "phone '
    'number", value = the whole token, brackets included, exactly as written, evidence_quote = the user\'s words. One '
    "entry per person and number. Never guess whose it is: with no name in the user's words, leave it out. Never put the "
    "token in a summary, a key fact, a history entry, a link or an open question: a page's prose does not carry it.]\n\n")


def _person_span(content: str, tid: str, episode_id: str, *, override, gaps, name: str = "") -> dict | None:
    """One of the person's own lines holding this token, as a located span: the token says which number, so this does
    not depend on what the model quoted. The line naming ``name`` when one does (a number said twice, of two people,
    rests on the line about this one), else the first."""
    from api.services import evidence

    needle = token(tid)
    words = [w.casefold() for w in name.split() if len(w) > 1]
    hits = []
    at = content.find(needle)
    while at != -1:
        hits.append(at)
        at = content.find(needle, at + 1)

    def names(at: int) -> bool:
        line = content[content.rfind("\n", 0, at) + 1:(content.find("\n", at) + 1 or len(content) + 1) - 1].casefold()
        return any(w in line for w in words)

    for at in sorted(hits, key=lambda a: (not names(a), a)):
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
    return None


def _raw_person_span(content: str, raw: str, episode_id: str, *, override, gaps) -> dict | None:
    """The first of the person's lines holding these digits, however grouped (a writer with no chat scrub: a harness
    session, a note). The body keeps them as it always has; the claim does not."""
    from api.services import evidence

    digits = _digits(raw)
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


def clean_prose(text: str, bank, *, on: bool | None = None) -> str:
    """Prose with no token and, while the feature is on, no number: each kept in the vault (so nothing is lost) and said
    as "a number". With the vault unavailable the digits still leave the prose: the promise is the page."""
    text = TOKEN_RE.sub("a number", text or "")
    if not (enabled() if on is None else on):
        return text
    spans = _spans(text)
    if not spans:
        return text
    try:
        mint_many(bank, [raw for _s, _e, raw in spans])
    except VaultUnavailable:
        logger.warning("A number left a page's text without being kept: the private number file can't be used")
    out, last = [], 0
    for start, end, _raw in spans:
        out += [text[last:start], "a number"]
        last = end
    return "".join(out) + text[last:]


def clean_page(body: str, bank) -> str:
    """An entity page's body as it may be written (`markdown_parser.write`, the one place every page goes through): its
    prose cleaned, its claims fence untouched. The check is here so no writer has to remember it."""
    from api.services.claims import _CLAIMS_BLOCK_RE

    on = enabled()
    if not on and "[number:" not in (body or ""):
        return body
    parts, last = [], 0
    for m in _CLAIMS_BLOCK_RE.finditer(body):
        parts += [clean_prose(body[last:m.start()], bank, on=on), m.group(0)]
        last = m.end()
    parts.append(clean_prose(body[last:], bank, on=on))
    return "".join(parts)


def _clean_strings(value, loose: re.Pattern[str] | None, bank, on: bool):
    """Stage 1's prose: a fact holding a number is dropped, any other string says "a number"."""
    def holds(text: str) -> bool:
        return has_token(text) or bool(loose and loose.search(text)) or (on and bool(_spans(text)))

    if isinstance(value, str):
        text = clean_prose(value, bank, on=on)
        return loose.sub("a number", text) if loose else text
    if isinstance(value, list):
        return [_clean_strings(v, loose, bank, on) for v in value if not (isinstance(v, str) and holds(v))]
    if isinstance(value, dict):
        return {k: _clean_strings(v, loose, bank, on) for k, v in value.items()}
    return value


def take(entities: list, relationships: list, values: list, content: str, episode_id: str, *, bank,
         override: str | None = None, gaps=()) -> int:
    """What Stage 1 made of the numbers in this conversation, in place, before anything downstream reads it.

    Each is one value entry (:data:`ITEM_KEY`), resting on the person's own located line or dropped: a number only an
    agent or another speaker gave never lands, whatever the model wrote. On a writer that keeps digits in its body, a
    model's phone-labelled relationship or value is minted here when the feature is on, so no claim stores digits. Every
    token and, while on, every number leaves the prose. Returns how many entries were kept."""
    mine = has_token(content)
    on = enabled()
    if not mine and not on:
        return 0
    # A model copies a token loosely (measured at haiku: the ten letters alone, no brackets), so what it wrote is read
    # against the tokens this conversation actually holds, never against the token's shape alone.
    here = set(token_ids(content))
    loose = re.compile(r"(?<![a-z])(" + "|".join(sorted(here)) + r")(?![a-z])") if here else None
    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def file(name: str, tid: str | None, raw: str | None) -> None:
        name = (name or "").strip()
        if not name or not tid:
            return
        key = (name.casefold(), tid)
        if key in seen:
            return
        span = (_person_span(content, tid, episode_id, override=override, gaps=gaps, name=name) if raw is None
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
        stated = (stated or "").strip()
        if on and is_phone_label(label) and _ONLY_DIGITS.match(stated):
            try:
                minted = mint_many(bank, [stated])
            except VaultUnavailable:
                logger.warning("A number was not filed: the private number file can't be used")
                return True      # never a claim holding the digits; the conversation still says it
            file(name, minted.get(stated), stated)
            return bool(minted)
        return False

    relationships[:] = [r for r in relationships
                        if not read(str(r.get("source") or ""), str(r.get("label") or ""), str(r.get("target") or ""))]
    values[:] = [v for v in values
                 if not read(str(v.get("entity") or ""), str(v.get("attribute") or ""), str(v.get("value") or ""))
                 ] + entries
    for i, entity in enumerate(entities):
        if isinstance(entity, dict):
            entities[i] = _clean_strings(entity, loose, bank, on)
    named = {str(e.get("name") or "").casefold() for e in entities if isinstance(e, dict)}
    for entry in entries:
        # What is held for a name waits on its pending line, so the name must be one Stage 2 parks.
        if entry["entity"].casefold() not in named:
            named.add(entry["entity"].casefold())
            entities.append({"name": entry["entity"], "type": "person", "confidence": 0.6, "key_facts": [],
                             "summary": ""})
    return len(entries)


# ---- what the person's line says ---------------------------------------------------------------------------------

_NUM = (r"(?:numbers?|n[uú]meros?|num[eé]ros?|nummer|phone|cell(?:phone)?|mobile|m[oó]vil|celular|tel[eé]fono|telefon|"
        r"t[eé]l[eé]phone)")
_OLD = r"(?:old|former|previous|antigu[oa]|viej[oa]|anterior|ancien(?:ne)?|velho|alte[rs]?)"
_NEW = r"(?:new|nuev[oa]|nouveau|nouvelle|novo|nova|neue?[rs]?)"
_CHANGE_VERB = r"(?:chang\w+|updat\w+|switch\w+|replac\w+|cambi\w+|actualiz\w+|mudou|ge[aä]ndert)"
#: Each says it of the number word, next to it. "new job", "I was talking to Ana" and "now" alone say nothing: they ask.
_CHANGED_BEFORE = re.compile(
    rf"(?i)\b{_NEW}\s+(?:(?:phone|cell|mobile)\s+)?{_NUM}\b"
    rf"|\b{_CHANGE_VERB}\s+(?:[^\W\d_]+\s+){{0,2}}{_NUM}\b"
    rf"|\b{_NUM}\s+(?:[^\W\d_]+\s+)?{_CHANGE_VERB}\b"
    rf"|\b{_NUM}\s+(?:is|es|est)\s+(?:now|ahora|maintenant)\s*$"
    rf"|\b(?:now|ahora)\s+(?:[^\W\d_]+\s+){{0,2}}{_NUM}\s+(?:is|es)\s*$")
_CHANGED_AFTER = re.compile(rf"(?i)^\W*(?:is|es)\s+(?:[^\W\d_]+\s+)?{_NEW}\s+{_NUM}\b")
_PAST_BEFORE = re.compile(
    rf"(?i)\b{_OLD}\s+(?:[^\W\d_]+\s+)?(?:{_NUM}|one|uno|una)\s*(?:was|is|were|era|es|:|=|-)?\s*$"
    r"|\bused to be\s*$")
_PAST_AFTER = re.compile(rf"(?i)^\W*(?:was|is|era|es)\s+(?:[^\W\d_]+\s+)?{_OLD}\b")
#: "changed from <old> to <new>": the token right after one of these, on a line a change word opens.
_FROM_BEFORE = re.compile(r"(?i)\b(?:from|de|desde|instead of|en vez de|en lugar de|von|au lieu de)\s+$")
_TO_BEFORE = re.compile(r"(?i)^\W*(?:to|a|por|→|->|zu|in)\W*$")
_ADDITIONAL_BEFORE = re.compile(
    rf"(?i)\b(?:work|office|home|second|other|another|personal|business|landline|trabajo|oficina|casa|fij[oa]|otr[oa]|"
    rf"segund[oa]|travail|autre|arbeit|zweite)\s+(?:[^\W\d_]+\s+)?{_NUM}\b"
    r"|\b(?:also|too|tambi[eé]n|aussi|auch)\s+(?:has|have|uses?|tiene|usa)\b")
_ADDITIONAL_AFTER = re.compile(r"(?i)^\W*(?:too|as well|tambi[eé]n|aussi|auch)\b")
#: A clause ends at a sentence's end or an "and": what was said of someone before it says nothing of this number.
_CLAUSE_END = re.compile(r"(?i)[.;!?]\s|\s(?:and|y|et|und|e)\s")


def _clause(text: str) -> str:
    cut = 0
    for m in _CLAUSE_END.finditer(text):
        cut = m.end()
    return text[cut:]


def read_line(line: str) -> dict[str, tuple[str, list[str]]]:
    """``{token id: (how this line relates it to what the page holds, the tokens it replaces)}``, clause by clause: each
    number is read from the words around it, never from the whole line. A word for it next to the number word, or
    :data:`UNKNOWN`, which asks. A miss costs one question; a wrong close would silently make the wrong number current."""
    tokens = list(TOKEN_RE.finditer(line or ""))
    kinds: list[str] = []
    for i, m in enumerate(tokens):
        before = _clause(line[tokens[i - 1].end() if i else 0:m.start()])
        after = line[m.end():tokens[i + 1].start() if i + 1 < len(tokens) else len(line)]
        if _FROM_BEFORE.search(before) and _CHANGED_BEFORE.search(before):
            kinds.append(PAST)
        elif i and kinds[i - 1] == PAST and _TO_BEFORE.match(before):
            kinds.append(CHANGED)
        elif _PAST_BEFORE.search(before) or _PAST_AFTER.match(after):
            kinds.append(PAST)
        elif _CHANGED_BEFORE.search(before) or _CHANGED_AFTER.match(after):
            kinds.append(CHANGED)
        elif _ADDITIONAL_BEFORE.search(before) or _ADDITIONAL_AFTER.match(after):
            kinds.append(ADDITIONAL)
        else:
            kinds.append(UNKNOWN)
    past = [m.group(1) for m, kind in zip(tokens, kinds) if kind == PAST]
    return {m.group(1): (kind, [p for p in past if p != m.group(1)] if kind == CHANGED else [])
            for m, kind in zip(tokens, kinds)}


def classify(line: str) -> str:
    """:func:`read_line` for a line about one number."""
    read = read_line(line)
    return next(iter(read.values()))[0] if read else UNKNOWN


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


def cards_of(bank) -> dict[str, list[str]]:
    """``{token id: [card ids]}`` from the app's last Contacts sync; a card marked the person's own is ``me``."""
    data = people_directory.load_json(_name(bank), CARDS_FILE).get("numbers")
    return data if isinstance(data, dict) else {}


def save_cards(bank, cards: dict[str, list[str]]) -> None:
    """Rewritten whole by every Contacts sync (`contacts_local.sync`), like the waiting cards beside it: keyed hashes
    and opaque card ids, never a digit. A value not shaped like a token id is refused at the door."""
    clean = {k: sorted(set(v)) for k, v in cards.items() if TOKEN_ID_RE.match(str(k))}
    people_directory.save_json(_name(bank), CARDS_FILE, {"numbers": clean})


def forget_cards(root: Path) -> int:
    """Contacts stopped: every bank's card hashes go, with its waiting cards (`contacts_local.forget_waiting`). What the
    person said stays: a claim is their word, not the card's. Returns how many files went. Never raises."""
    gone = 0
    for path in Path(root).glob(f"*/{CARDS_FILE}"):
        try:
            path.unlink()
            gone += 1
        except OSError:
            continue
    return gone


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
    ``number_replaces``, in memory only, read again whenever the claim is), and whether its page may take it. Returns the
    claims to place and audit rows.

    Dropped: a claim on a page that is no person, or with no located line of the person's. Asked: a one-word name that
    is not the owner's and not a relation's (`role_people`'s ``unnamed``), since two people can answer to it. A card
    holding this number and carried by that page settles the name; a card carried by a DIFFERENT page asks."""
    memory_path = Path(memory_path)
    kept: list = []
    audit: list[dict] = []
    cards: dict[str, list[str]] | None = None
    for claim in incoming:
        if not is_number_claim(claim) or claim.source_trust == "user_stated":
            kept.append(claim)      # the person's own hand needs no line read
            continue
        line = _line_of(memory_path, claim)
        if line is None:
            audit.append({"action": "number_no_line", "dropped": claim.id})
            continue
        tid = token_ids(claim.object)[0]
        if not has_token(line) or token(tid) not in line:
            try:
                line = _retoken_any(line, memory_path)
            except VaultUnavailable:
                pass
        claim.number_change, claim.number_replaces = read_line(line).get(tid, (UNKNOWN, []))
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
            cards = cards_of(memory_path)
        held_by = set(cards.get(tid) or [])
        carried = _carried_cards(fm)
        name = str(fm.get("name") or "").strip()
        if held_by and carried and not held_by & carried:
            claim.number_ask = ASK_CARD
        elif len(name.split()) < 2 and not fm.get("unnamed") and not (held_by & carried):
            claim.number_ask = ASK_NAME
        kept.append(claim)
    return kept, audit


def _retoken_any(line: str, bank) -> str:
    """A line from a writer that kept its digits, with each digit run as its token if the vault knows it: so a claim
    resting on it is read clause by clause like any other."""
    def one(m: re.Match[str]) -> str:
        tid = known_id(bank, m.group(0))
        return token(tid) if tid else m.group(0)

    return re.sub(_DIGITS, one, line)


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
