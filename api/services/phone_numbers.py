"""A number the person gives for someone: consolidated, kept out of every bank (G81, ruling 55, owner 2026-11-05).

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

**What counts as a number.** A token replaces the digits in the stored words for good, so only what is explicit counts. In
the person's own line: (a) a phone word tied to the digits ("her number is N", "su teléfono es N", "mi celular N"); (b) an
"add"/"save" and a capitalised name before nine digits or more ("add Ana, N", "guarda a Ana N"); (c) a change said with a
phone word ("changed her number to N"); (d) a run of nine digits or more the vault already holds, standing alone
(:func:`_known_runs`). In anyone else's line: only (a) with a phone word somebody owns, and (d). A bare "Ana N" is no signal:
a miss costs digits in clear, which is what today does; a wrong match is a person's words rewritten for good. A ``+`` or a
bracketed shape counts only inside (a) or (b); elsewhere the chat scrub takes it, as it always has.

**Why old chats are not re-read.** A stored sitting is rebuilt from its own body, so a stored line never passes through
here; and a line a reader posts again keeps its stored words when they are what the old scrub or this one makes of it
(:func:`tokenise_batch`). Only a new message, or a real edit, can hold a new token. Numbers already ``[redacted]`` stay
redacted: the app could re-post them, but that is a person-started read for the owner to ask for, not what a switch does.

**Whose words.** Only the person's own lines are tokenised. An agent's reply and another speaker's line are redacted by
their narrower rule: the agent's echo is not evidence, and a correspondent's "my new number is X" is exactly
the shape of the "hi, it's me, new number" fraud, so it never reaches a page. A forwarded message is someone else's words
too.

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
#: On a Stage 1 person mention: the waiting card whose number the person gave (`entity_resolver`, ruling 55, 2026-11-05).
CARD_KEY = "number_card"
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
                         "telefon téléphone telephon portable handy wsp sms signal".split())
_LABEL_FILLER = frozenset("has have the his her their is a an of at value number numbers no num nr contact reachable work "
                          "home personal office new current main private business second other old previous former".split())
_ONLY_DIGITS = re.compile(r"^(?:tel:)?[+()\d][\d .\-()]{5,22}\d$", re.IGNORECASE)


class VaultUnavailable(Exception):
    """The vault exists in principle and cannot be used now. ``str(e)`` is the sentence for the person, no number in it."""


def _name(bank) -> str:
    return bank.name if isinstance(bank, Path) else str(bank or "default")


# ---- the switch: one file every process reads ------------------------------------------------------------------------

def _switch_path() -> Path:
    root = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(root).expanduser() / SWITCH_FILE


_switch_memo: tuple[tuple[str, int, int], bool] | None = None


def enabled() -> bool:
    """OFF until the owner rules on ruling 55. The answer is :data:`SWITCH_FILE`'s, read again whenever the file
    moves: the backend, a stdio MCP server and the CLI can never disagree. No file, or a damaged one, is off."""
    global _switch_memo
    path = _switch_path()
    try:
        st = path.stat()
    except OSError:
        return False
    key = (str(path), st.st_mtime_ns, st.st_size)
    if _switch_memo is not None and _switch_memo[0] == key:
        return _switch_memo[1]
    try:
        on = json.loads(path.read_text(encoding="utf-8")).get("on") is True
    except (OSError, ValueError, AttributeError):
        on = False
    _switch_memo = (key, on)
    return on


def set_enabled(on: bool, *, by: str = "api-token") -> dict:
    """The one writer of the switch (`PUT /people/numbers/switch`, `cicada numbers switch`). The record says when and by
    what: **the route cannot tell the person from anything else holding this Mac's API token**, so it records the token,
    never "person". The CLI refuses from an agent's own shell; a process calling the route directly is not stopped."""
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
    """Whether a claim's label says phone: "phone", "phone_number", "mobile number", "has_phone", "tel", "sms", "signal",
    "reachable_at", "contact", a bare "number" or "contact number" (a caller also requires the value to be digits). Never
    "membership number", "order number" or "mobile app version": every word must be a phone word or only qualify one."""
    words = [w for w in re.split(r"[\s_\-/:]+", str(label or "").strip().casefold()) if w]
    if not words:
        return False
    rest = [w for w in words if w not in _LABEL_FILLER]
    if rest:
        return all(w in _PHONE_WORDS for w in rest)
    return bool({"number", "numbers", "contact", "reachable"} & set(words))


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


_CHAT_ORIGINS = ("imessage", "whatsapp", "telegram-chats")
_FM_ORIGIN = re.compile(r"^(?:origin|source): *['\"]?([\w-]+)", re.MULTILINE)
_PERSON_LINE = re.compile(r"^user: .*$", re.MULTILINE)


def bank_token_ids(memory_path: Path) -> set[str]:
    """The tokens this bank really holds: a ``phone`` claim's object, a person's own line in a ticked chat, a held claim.
    Never a mere mention: a harness session or a page that talks about this feature can quote ``[number:<letters>]``, and
    that points at no vault. Read only when the vault file is missing, so once per bank at first use."""
    found: set[str] = set()

    def claims_in(text: str) -> None:
        for line in text.splitlines():
            if '"predicate": "phone"' in line or '"predicate":"phone"' in line:
                m = re.search(r'"object": ?"\[number:([a-z]{10})\]"', line)
                if m:
                    found.add(m.group(1))

    entities = memory_path / "entities"
    if entities.is_dir():
        for file in entities.iterdir():
            try:
                if file.is_file():
                    text = file.read_text(encoding="utf-8", errors="ignore")
                    if "[number:" in text:
                        claims_in(text)
            except OSError:
                continue
    episodes = memory_path / "episodes"
    if episodes.is_dir():
        for file in episodes.iterdir():
            try:
                text = file.read_text(encoding="utf-8", errors="ignore") if file.is_file() else ""
            except OSError:
                continue
            if "[number:" not in text or not text.startswith("---"):
                continue
            head, _sep, body = text[3:].partition("\n---")
            if not any(o in _CHAT_ORIGINS for o in _FM_ORIGIN.findall(head)):
                continue
            for line in _PERSON_LINE.findall(body):
                found.update(TOKEN_RE.findall(line))
    pending = memory_path / "pending_entities.jsonl"
    try:
        if pending.is_file():
            text = pending.read_text(encoding="utf-8", errors="ignore")
            if "[number:" in text:
                found.update(re.findall(r'"predicate": ?"phone"[^}]*?"object": ?"\[number:([a-z]{10})\]"', text))
    except OSError:
        pass
    return found


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
    """A bank back from the trash finds its OWN vault there (:func:`park_for_trash`). Own means: the file is stamped for
    exactly this name (``work`` never reads ``work-old``'s) and it holds tokens this bank holds. A new bank that merely
    reuses a trashed name holds none of them, so it inherits nothing, and the trashed vault stays for the bank it belongs
    to. Newest first."""
    held = bank_token_ids(memory_path)
    if not held:
        return False
    stamped = re.compile(re.escape(memory_path.name) + r"-\d{8}T\d{6}Z\.numbers\.json")
    for root in (memory_path.parent, memory_path.parent.parent):
        trash = root / ".trash"
        if not trash.is_dir():
            continue
        for parked in sorted((p for p in trash.iterdir() if stamped.fullmatch(p.name)), reverse=True):
            try:
                data = json.loads(parked.read_text(encoding="utf-8"))
                numbers = data.get("numbers") if isinstance(data, dict) else None
            except (OSError, ValueError):
                continue
            if isinstance(numbers, dict) and held & set(numbers):
                people_directory.ensure(memory_path.name)
                target = people_directory.path(memory_path.name, VAULT_FILE)
                os.replace(parked, target)
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
        if bank_token_ids(bank):
            raise VaultUnavailable(_GONE)
    return {"key": base64.b64encode(secrets.token_bytes(32)).decode("ascii"), "numbers": {}}


def problem(bank) -> str | None:
    """The sentence to show when the vault can't be used, for this bank, in words; ``None`` when it can."""
    try:
        with _vault_lock(bank):
            if _read(_name(bank)) is None and isinstance(bank, Path) and bank_token_ids(bank):
                if not _restore_parked(bank):
                    return _GONE
    except VaultUnavailable as exc:
        return str(exc)
    return None


class VaultHealthy(Exception):
    """A new vault was asked for while this one works: nothing was touched."""


def new_vault(bank) -> dict:
    """The person's own act, when a vault is lost: a damaged or unreadable file is set aside whole, never deleted, and a
    new key begins. Old tokens stay in memory and read "a number"; a number said again reads as a new one and asks.
    :class:`VaultHealthy`, changing nothing, while the vault can be used: setting aside a working one would make every
    number on every page unreadable."""
    name = _name(bank)
    if problem(bank) is None:
        raise VaultHealthy("The private file that holds your numbers is fine, so nothing was changed.")
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


def discard_unused(bank, tid: str) -> None:
    """A number minted for a write that was then refused: out of the vault unless the bank already points at it."""
    root = Path(bank) if isinstance(bank, Path) else None
    needle = token(tid)
    with _vault_lock(bank):
        data = _read(_name(bank))
        if not data or tid not in data["numbers"]:
            return
        if root is not None:
            for sub in ("entities", "episodes"):
                folder = root / sub
                if folder.is_dir() and any(needle in f.read_text(encoding="utf-8", errors="ignore")
                                           for f in folder.iterdir() if f.is_file()):
                    return
            pending = root / "pending_entities.jsonl"
            if pending.is_file() and needle in pending.read_text(encoding="utf-8", errors="ignore"):
                return
        del data["numbers"][tid]
        people_directory.save_json(_name(bank), VAULT_FILE, data)


def known_id(bank, raw: str | None) -> str | None:
    """The token id of a number the vault holds, minting nothing; ``None`` for one it does not hold."""
    digits = _digits(raw)
    if not match_digits(digits):
        return None
    with _vault_lock(bank):
        data = _read(_name(bank))
    if not data:
        return None
    tid = _token_for(data, digits)
    return tid if tid in data["numbers"] else None


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

_PHONE_WORD = r"phone|telephone|cell(?:phone)?|mobile|m[oó]vil|celular|cel|tel[eé]fono|t[eé]l[eé]phone|telefon|whatsapp|wsp|tel\.?"
_NUMBER_WORD = r"numbers?|n[uú]meros?|num[eé]ros?|nummer"
_QUALIFIER = (r"new|old|current|work|home|personal|second|other|former|previous|private|nuevo|nueva|viejo|vieja|antiguo|"
              r"antigua|otro|otra|actual|nouveau|nouvelle|ancien|ancienne|autre|novo|nova|neue?|alte?")
#: Who owns a number word: without one, "number 123456789" is an order, a seat, a flight, anything. A possessive only on a
#: capital, never "this year's", and never a contraction ("it's number 1500000") or a day ("Today's number").
_WHOSE = (r"(?!(?:it|that|he|she|here|there|what|who|let|today|yesterday|tomorrow)['’]s)(?-i:[A-ZÀ-ÖØ-Þ])[^\W\d_]*['’]s|"
          r"my|his|her|their|your|mi|su|tu|sa|son|ma|meu|seu|mein|sein|ihre?")
_DIGITS = r"\+?\(?\d[\d .\-()]{5,20}\d"
#: No dot: a decimal, a version or a coordinate is not how a number after an "add" is written.
_BARE = r"\+?\(?\d[\d \-()]{5,20}\d"
#: What ties the word to the digits: a verb of being and nothing else. "de", "a" and "por" are how a sum is said
#: ("mi celular por 1500000"), and "at" and "on" how a place is.
_LINK = r"\s*[:=\-–→]?\s*(?:(?:['’]s|it['’]?s|it is|that['’]?s|is|was|are|were|es|son|era|est|ist|é|now|ahora)[:=]?\s+){0,3}"
_OWNED = (rf"(?:{_WHOSE})\s+(?:(?:{_QUALIFIER}|{_PHONE_WORD})\s+){{0,2}}(?:{_NUMBER_WORD}|{_PHONE_WORD})"
          rf"(?:\s+de\s+(?:{_PHONE_WORD}|contacto))?")
_PHONE_TERM = rf"(?:{_PHONE_WORD})(?:\s+(?:{_NUMBER_WORD}|no\.?|\#))?"
#: (a) in the person's own line.
_SAID_RE = re.compile(rf"(?i)(?<!\w)(?:{_OWNED}|{_PHONE_TERM}|(?:{_NUMBER_WORD})\s+de\s+contacto){_LINK}(?P<num>{_DIGITS})")
#: (a) in anyone else's: the phone word must be somebody's.
_OWNED_RE = re.compile(rf"(?i)(?<!\w){_OWNED}{_LINK}(?P<num>{_DIGITS})")
_CHANGE_VERB = r"(?:chang\w+|updat\w+|switch\w+|replac\w+|cambi\w+|actualiz\w+|mudou|ge[aä]ndert)"
#: (c) "changed her number to N", "changed Ana Diaz's number to N", "su número cambió a N", "updated her phone from N to M".
_CHANGE_RE = re.compile(rf"(?i)(?<!\w)(?:{_CHANGE_VERB}\s+(?:[^\W\d_]+\s+){{0,2}}(?:{_OWNED}|{_PHONE_TERM})"
                        rf"|(?:{_OWNED}|{_PHONE_TERM})\s+(?:has\s+|just\s+)?{_CHANGE_VERB})"
                        rf"\s*(?:to|a|por|from|de|desde|von|:|=|,\s*(?:it['’]?s|now|ahora))?\s*(?P<num>{_DIGITS})")
_CHANGE_NEXT_RE = re.compile(rf"(?i)\s*(?:to|a|por|→|->)\s*(?P<num>{_DIGITS})")
#: (b) the word right before the digits, read with :data:`_ADD_BEFORE`: "add Ana, N", "add Bob Example N".
_NAMED_RE = re.compile(rf"(?P<name>[^\W\d_][\w'’\-]*)(?:\s*[:,\-–]\s*|\s+)(?P<num>{_BARE})")
_ADD_BEFORE = re.compile(r"(?i)(?<!\w)(?:add|added|save|saved|añade|añadir|agrega|agregar|guarda|guardar|apunta|apuntar|ajoute|"
                         r"enregistre)\s+(?:[^\W\d_]+\s+){0,2}$")
#: After the digits of (b) the clause must end: "add Bob 1500000 dollars" is not a phone.
_CLAUSE_ENDS = re.compile(r"(?i)\s*(?:$|[,.;!?)\n]|(?:and|y|thanks|thank you|please|pls|gracias|por favor|merci|danke)\b)")
#: After a phone word the clause may go on, but not into a unit.
_UNIT_AFTER = re.compile(r"(?i)\s*(?:%|\$|€|£|usd|eur|gbp|mxn|dollars?|euros?|pesos?|pounds?|km|kg|miles|users|people|"
                         r"followers|views|times|visits|items|is the\b|are the\b|was the\b)")
#: A veto only, it never makes a number: the word before that says this is not somebody's phone, whatever else is near.
_NOT_A_PHONE = frozenset(
    "order orders tracking account invoice flight booking reservation reference ref case ticket confirmation serial "
    "card room rooms seat table page pages version model part sku item id code zip postcode price cost total paid pay "
    "budget amount salary rent balance year years date membership passport license licence member customer pedido vuelo "
    "cuenta factura reserva habitación precio pagado pasaporte commande vol facture bestellung konto rechnung "
    "isbn iban vin nit rfc dni ssn pin otp tax lot batch receipt chapter gate bus train route product policy claim user client "
    "sold bought raised earned spent worth grew lost gained made owes owed "
    "loan debt fee fine presupuesto préstamo prestamo deuda renta alquiler sueldo salario monto cantidad saldo multa pago "
    "password passcode contraseña clave "
    "monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september "
    "october november december lunes martes miércoles jueves viernes sábado domingo enero febrero marzo abril mayo "
    "junio julio agosto septiembre octubre noviembre diciembre".split())
#: A date, alone or with a time after it, only when it holds a real year: "12 03 2026 14 30" is a date, and "06 12 34 56 78"
#: and "0612 34 56 78" are a number's usual spellings. A two-digit year counts only when it ends the run.
_DATEISH = re.compile(r"^(?:(?:19|20)\d{2}[-/. ]\d{1,2}[-/. ]\d{1,2}(?:\D|$)"
                      r"|\d{1,2}[-/. ]\d{1,2}[-/. ](?:(?:19|20)\d{2}(?:\D|$)|\d{2}$))")
_YEAR_GROUP = re.compile(r"^(?:19|20)\d{2}$")


def _plausible(raw: str) -> bool:
    """A digit run after a positive signal, still never a date, an IP address, a year list, a range of times or a price."""
    text = raw.strip()
    if _DATEISH.match(text) or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", text):
        return False
    groups = [g for g in re.split(r"[ .\-()]+", text) if g]
    if len(groups) > 1 and all(_YEAR_GROUP.match(g) for g in groups):
        return False
    if len(groups) == 2 and all(3 <= len(g) <= 4 and int(g) <= 2400 for g in groups):
        return False      # "1030 1100": a time and a time
    if len(groups) > 2 and len(groups[0]) <= 2 and all(len(g) == 3 for g in groups[1:]) and groups[0] != "0":
        return False      # "1 299 000 000": a price. "612 345 678" keeps three digits in front, and "06 12 34" two in each
    return MIN_DIGITS <= len(_digits(text)) <= MAX_DIGITS


def _stands_alone(text: str, start: int, end: int) -> bool:
    """Whether the digits are a word of their own: never a piece of a link, an address, a file name or a key=value."""
    left = text[max(text.rfind(" ", 0, start), text.rfind("\n", 0, start)) + 1:start]
    right_end = min((i for i in (text.find(" ", end), text.find("\n", end)) if i != -1), default=len(text))
    right = text[end:right_end]
    return bool(re.fullmatch(r"[\w'’]*:?|\(", left)) and bool(re.fullmatch(r"[,.;:!?)]*", right))


def _before(text: str, at: int) -> set[str]:
    """The four words before ``at`` ("Order's number is" is four): an order's whichever of them the rule read."""
    return {w.lower() for w in re.findall(r"[^\W\d_]+", text[:at])[-4:]}


def _added(text: str, m: re.Match[str]) -> bool:
    """(b): nine digits or more ending the clause, right after a capitalised word an "add" or "save" stands before."""
    word = m.group("name")
    return (word[0].isupper() and len(_digits(m.group("num"))) >= MATCH_DIGITS
            and word.casefold() not in _NOT_A_PHONE and word.casefold().rstrip("'’s") not in _NOT_A_PHONE
            and not _before(text, m.start("num")) & _NOT_A_PHONE
            and bool(_ADD_BEFORE.search(text[:m.start("name")])) and bool(_CLAUSE_ENDS.match(text, m.end("num"))))


def _whole_number(raw: str) -> bool:
    """Whether a written run is one phone number and nothing more. Only the last nine digits identify a number, so what a
    run holds in front of them is read here: "+", or "00" and a country code; a trunk zero; the "1" and ten digits or the
    bare ten of a national form. Anything longer is an id, an account or a date whose tail happens to match. Ten digits
    can't be told from a stray digit in front of a nine-digit number, since a card posts only that hash; a lone first
    digit ("3 612345678") and a decimal ("6123456.78") can, and don't count."""
    text = raw.strip()
    digits = _digits(text)
    if text.startswith("+"):
        return True
    if re.fullmatch(r"\d+\.\d+", text):
        return False
    if digits.startswith("00"):
        return digits[2] != "0" and len(digits) > MATCH_DIGITS + 2
    if digits.startswith("0"):
        return len(digits) <= MATCH_DIGITS + 3
    if len(digits) == 11:
        return digits[0] == "1"
    return len(digits) <= MATCH_DIGITS or (len(digits) == 10 and bool(re.match(r"\(?\d{2}", text)))


def _known_runs(text: str, bank) -> list[tuple[int, int, str]]:
    """Every run of nine digits or more the vault holds, standing alone: an agent's "Updated Ana to 2025550144." is that
    number with no signal needed. Shorter runs never match by value, because a vault entry of 1500000 would otherwise blank
    "mi renta es 1500000" in anyone's line for good; the cost is that an agent's echo of a 7- or 8-digit number stays in
    clear. Never a piece of a link, a date, a price shape, after a word that says it is something else, or before a unit.
    A vault that can't be read adds nothing here (:func:`tokenise` then redacts what the rule found)."""
    if not bank:
        return []

    def stands(m: re.Match[str]) -> bool:
        return (len(_digits(m.group(0))) >= MATCH_DIGITS and _whole_number(m.group(0)) and _plausible(m.group(0))
                and _stands_alone(text, m.start(), m.end())
                and not _before(text, m.start()) & _NOT_A_PHONE and not _UNIT_AFTER.match(text, m.end()))

    runs = [m for m in re.finditer(rf"(?<![\w.]){_DIGITS}(?!\w)", text) if stands(m)]
    if not runs:
        return []
    try:
        data = _read(_name(bank))   # no lock: a read creates nothing (the dry run promises that) and writes are atomic
    except VaultUnavailable:
        return []
    if not data:
        return []
    return [(m.start(), m.end(), m.group(0)) for m in runs if _token_for(data, _digits(m.group(0))) in data["numbers"]]


#: Any stretch of digits and separators, longer than one number can be: a card's number is looked for inside it.
_RUN = re.compile(r"(?<![\w.+])\+?\(?\d[\d .\-()]{5,60}\d(?!\w)")


def _windows(m: re.Match[str]) -> Iterable[tuple[int, int]]:
    """The space-separated stretches of a run, earliest then longest: "+1 202 555 0143 202 555 0177" holds two numbers;
    a dash never splits one, so a piece of "202-555-0143-77" is no number."""
    pieces = [(p.start() + m.start(), p.end() + m.start()) for p in re.finditer(r"\S+", m.group(0))]
    for i, (start, _end) in enumerate(pieces):
        for j in range(len(pieces) - 1, i - 1, -1):
            yield start, pieces[j][1]


def _alone_on_its_line(text: str, start: int, end: int) -> bool:
    line_end = text.find("\n", end)
    return (not text[text.rfind("\n", 0, start) + 1:start].strip()
            and not text[end:len(text) if line_end == -1 else line_end].strip())


def _card_runs(text: str, bank) -> list[tuple[int, int, str]]:
    """Every number in the person's own line a Contacts card holds, by value: the keyed hash the app posted, against the
    same hash of these digits. A miss leaves digits as they are and a wrong match rewrites someone's words for good, so a
    run counts only when ALL of it is card numbers (:func:`_whole_number`; "+1 202 555 0143 202 555 0177" holds two, the
    end of a grouped card number none; a dash never splits one), each plausible, standing alone, with no word before it
    saying it is something else and no unit after. Under nine digits it also needs a "+" or a line of its own."""
    if not bank:
        return []
    cards = cards_of(bank)
    if not cards:
        return []
    try:
        data = _read(_name(bank))
    except VaultUnavailable:
        return []
    if not data:
        return []

    def counts(start: int, end: int) -> bool:
        raw = text[start:end]
        digits = match_digits(raw)
        return bool(digits) and _token_id(data["key"], digits) in cards and _whole_number(raw) and _plausible(raw) \
            and _stands_alone(text, start, end) and not _before(text, start) & _NOT_A_PHONE \
            and not _UNIT_AFTER.match(text, end) \
            and (len(_digits(raw)) >= MATCH_DIGITS or raw.startswith("+") or _alone_on_its_line(text, start, end))

    found: list[tuple[int, int, str]] = []
    for m in _RUN.finditer(text):
        pieces = [(p.start() + m.start(), p.end() + m.start()) for p in re.finditer(r"\S*\d\S*", m.group(0))]
        spans, i = [], 0
        while i < len(pieces):
            j = next((j for j in range(len(pieces) - 1, i - 1, -1) if counts(pieces[i][0], pieces[j][1])), None)
            if j is None:
                spans = []
                break
            spans.append((pieces[i][0], pieces[j][1], text[pieces[i][0]:pieces[j][1]]))
            i = j + 1
        found += spans
    return found


def _spans(text: str, bank="", *, person: bool = True, own: bool = False) -> list[tuple[int, int, str]]:
    """Every number in a line, ``(start, end, raw)``, earliest first, none overlapping. ``person=False`` is anyone else's
    line: only a phone word somebody owns, and a number the vault holds. ``own``: a line the person typed in a ticked chat,
    so a number on one of their Contacts cards and a "+" number count too (ruling 55, 2026-11-05)."""
    found: list[tuple[int, int, str]] = []

    def add(start: int, end: int, raw: str) -> None:
        if not any(start < e and s < end for s, e, _ in found):
            found.append((start, end, raw))

    if own:
        for start, end, raw in _card_runs(text, bank):
            add(start, end, raw)

    def good(m: re.Match[str]) -> bool:
        return _plausible(m.group("num")) and _stands_alone(text, m.start("num"), m.end("num"))

    def tied(m: re.Match[str]) -> bool:
        return (good(m) and not _UNIT_AFTER.match(text, m.end("num"))
                and not (_before(text, m.start()) | _before(text, m.start("num"))) & _NOT_A_PHONE)

    for m in (_SAID_RE if person else _OWNED_RE).finditer(text):
        if tied(m):
            add(m.start("num"), m.end("num"), m.group("num"))
    if person:
        for m in _CHANGE_RE.finditer(text):
            if tied(m):
                add(m.start("num"), m.end("num"), m.group("num"))
                follow = _CHANGE_NEXT_RE.match(text, m.end("num"))
                if follow and good(follow) and not _UNIT_AFTER.match(text, follow.end("num")):
                    add(follow.start("num"), follow.end("num"), follow.group("num"))
        for m in _NAMED_RE.finditer(text):
            if good(m) and _added(text, m):
                add(m.start("num"), m.end("num"), m.group("num"))
    for start, end, raw in _known_runs(text, bank):
        add(start, end, raw)
    if own:
        for start, end in episode_scrub.plus_numbers(text):
            add(start, end, text[start:end])
    return sorted(found)


def tokenise(text: str, bank) -> tuple[str, int]:
    """The person's own line with each number replaced by its token; ``(text, how many)``. With a vault that can't be
    used, the numbers are redacted, as the scrub does today, and it says so: no digit reaches the bank by a failure."""
    spans = _spans(text or "", bank, own=True)
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


def redact(text: str, bank) -> str:
    """Somebody else's line: a phone word they own, or a number the vault holds, redacted. Never in the vault: it is not the
    person's word."""
    spans = _spans(text or "", bank, person=False)
    out, last = [], 0
    for start, end, _raw in spans:
        out += [text[last:start], episode_scrub.REDACTED]
        last = end
    return "".join(out) + text[last:]


def _shape(text: str) -> str:
    """A line with its numbers, tokens and redactions all blanked: what is left to compare when the vault can't answer."""
    masked = TOKEN_RE.sub("#", text or "").replace(episode_scrub.REDACTED, "#")
    return re.sub(_DIGITS, "#", masked)


def _vault_knows(tokens: list[str], bank) -> bool:
    try:
        data = _read(_name(bank))
    except VaultUnavailable:
        return False
    return bool(data) and all(t in data["numbers"] for t in tokens)


def _is_stored_line(posted: str, stored: str, writer: str, bank) -> bool:
    """Whether a line posted again is the line already stored. Never the rule run again: the rule rests on a vault that grows,
    so the comparison rests only on the stored line's own tokens, by value. The token of an EDITED number differs, so a real
    edit is never read as a re-post while the vault knows the stored line's numbers. While it doesn't (damaged, missing, or a
    new one begun), the line's words decide: a stored line is never rewritten for a lost vault, in any direction. The cost:
    an edit to only the digits of a number waits for a vault to be readable."""
    cleaned = episode_scrub.scrub_for(posted, writer)[0]
    if cleaned == stored:
        return True
    tokens = token_ids(stored)
    if tokens:
        if _vault_knows(tokens, bank):
            return episode_scrub.scrub_for(_retoken_any(posted, bank, only=set(tokens)), writer)[0] == stored
        return _shape(cleaned) == _shape(stored)
    # A number once redacted: somebody else's line, or a lost vault. What it redacted may rest on a vault that is gone
    # now, so the words decide here too; the line was, and stays, redacted.
    return episode_scrub.REDACTED in stored and _shape(cleaned) == _shape(stored)


def _ever_switched() -> bool:
    """Whether the switch was ever written. Off writes the file too, so "off after on" is this and "never on" is not."""
    return _switch_path().exists()


def tokenise_batch(messages: list, stored: dict, *, writer: str, bank) -> int:
    """Incoming chat messages, before the stager (`messages_source.ingest`, `chat_live.ingest`). The person's own new or
    edited words are tokenised; anyone else's are redacted by the same rule. A message posted again keeps its stored words
    (:func:`_is_stored_line`), so an old sitting's body, its hash and the Sleep queue do not move: an edit in place reads
    as a revision, and a re-read of old chats would cost a model call each. ``stored``: ``{message key: stored message}``.
    Returns how many were tokenised. A never-on install is a true no-op; after on, off still keeps a stored line, a
    redacted one included, since nothing but this rule put that redaction there and a stored line never moves back."""
    on = enabled()
    if not on and not _ever_switched() and not any(has_token(getattr(m, "text", "")) for m in stored.values()):
        return 0
    count = 0
    fresh = []
    for m in messages:
        if m.unsent or not m.text:
            continue
        old = stored.get(m.key)
        if old is not None and _is_stored_line(m.text, old.text, writer, bank):
            m.text = old.text
        elif on:
            fresh.append(m)
    others = []
    for m in fresh:   # the person's first: an echo in this same post is then a number the vault holds
        if m.from_me and not getattr(m, "forwarded_from", None):
            m.text, n = tokenise(m.text, bank)
            count += n
        else:
            others.append(m)
    for m in others:
        m.text = redact(m.text, bank)
    return count


# ---- Stage 1 -----------------------------------------------------------------------------------------------------

NOTE = (
    "[Cicada's note, not part of the conversation: [number:<letters>] stands for a phone number the user typed; its "
    "digits are kept out of this text on purpose. When the user's own line says whose number it is, add one entry to "
    'values: entity = that person\'s name as the user gave it ("the user" for their own number), attribute = "phone '
    'number", value = the whole token, brackets included, exactly as written, evidence_quote = the user\'s words. One '
    "entry per person and number. Never guess whose it is: with no name in the user's words or a note below, leave it out. Never put the "
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


_LINK_TARGET = re.compile(r"\]\([^)\n]*\)|<[a-z]+:[^>\n]*>|\b(?:https?://|www\.)\S+", re.IGNORECASE)


def clean_prose(text: str, bank, *, keep: bool = True) -> str:
    """Prose with no number, while the feature is on: each kept in the vault, so nothing is lost, and said as "a number".
    A link's target is never touched. With the vault unavailable the words stay: a damaged file never costs a page words.
    ``keep=False`` is Stage 1's prose and an agent's claim sentence: resting on a conversation that still holds what it
    holds, so nothing in them enters the vault."""
    text = text or ""
    if not enabled():
        return text
    links = [m.span() for m in _LINK_TARGET.finditer(text)]
    spans = [s for s in _spans(text, bank) if not any(a <= s[0] < b for a, b in links)]
    if not spans:
        return text
    if keep:
        try:
            mint_many(bank, [raw for _s, _e, raw in spans])
        except VaultUnavailable:
            logger.warning("A number stayed in a page's text: the private number file can't be used")
            return text
    out, last = [], 0
    for start, end, _raw in spans:
        out += [text[last:start], "a number"]
        last = end
    return "".join(out) + text[last:]


def clean_page(body: str, bank) -> str:
    """A person's page as it may be written (`markdown_parser`, every page writer). **Off: not one byte changes.** On: a
    token this vault minted is said as "a number", and a number becomes one, outside the claims fence and outside a link's
    target. Only a person's page: a company's public phone, a link or a count on any other page is not this rule's."""
    if not enabled():
        return body
    from api.services.claims import _CLAIMS_BLOCK_RE

    try:
        data = _read(_name(bank)) or {}
    except VaultUnavailable:
        data = {}
    minted = data.get("numbers") or {}

    def prose(text: str) -> str:
        return clean_prose(TOKEN_RE.sub(lambda m: "a number" if m.group(1) in minted else m.group(0), text), bank)

    parts, last = [], 0
    for m in _CLAIMS_BLOCK_RE.finditer(body):
        parts += [prose(body[last:m.start()]), m.group(0)]
        last = m.end()
    parts.append(prose(body[last:]))
    return "".join(parts)


def _clean_strings(value, loose: re.Pattern[str] | None, bank, on: bool, person: bool):
    """Stage 1's prose: a fact holding one of this conversation's tokens is dropped, any other string says "a number". On
    a person's entity, while on, the same for a number in digits. Another entity's digits are not this rule's."""
    def holds(text: str) -> bool:
        return bool(loose and loose.search(text)) or has_token(text) or (on and person and bool(_spans(text, bank)))

    if isinstance(value, str):
        text = TOKEN_RE.sub("a number", value)
        text = loose.sub("a number", text) if loose else text
        return clean_prose(text, bank, keep=False) if on and person else text
    if isinstance(value, list):
        return [_clean_strings(v, loose, bank, on, person) for v in value if not (isinstance(v, str) and holds(v))]
    if isinstance(value, dict):
        return {k: _clean_strings(v, loose, bank, on, person) for k, v in value.items()}
    return value


def _named_apart(content: str, tid: str, said: str, card_name: str) -> bool:
    """Whether the person's words name someone else beside this number: "Bob's number is N", with N on Ana's card, stays
    Bob's, and `annotate` asks when a page says otherwise. A name made only of the card's words is the card's person (one
    word in common is not: two of a family share a surname), and a model's reading the person's line doesn't spell as a name ("my brothers": a chat message is stored as one line, so
    that line may well hold the word) is outranked by the card."""
    words = set(re.findall(r"[^\W\d_]{2,}", said))
    if words and {w.casefold() for w in words} <= {w.casefold() for w in re.findall(r"[^\W\d_]{2,}", card_name)}:
        return False
    names = {w for w in words if w[0].isupper()}
    needle = token(tid)
    return any(needle in line and names & set(re.findall(r"[^\W\d_]{2,}", line)) for line in content.splitlines())


def take(entities: list, relationships: list, values: list, content: str, episode_id: str, *, bank,
         override: str | None = None, gaps=()) -> int:
    """What Stage 1 made of the numbers in this conversation, in place, before anything downstream reads it.

    Each is one value entry (:data:`ITEM_KEY`), resting on the person's own located line or dropped: a number only an
    agent or another speaker gave never lands, whatever the model wrote, and never enters the vault. On a writer that
    keeps digits in its body, a model's phone-labelled relationship or value resting on the person's line is minted here
    when the feature is on, so no claim stores digits. Every token and, while on, every number leaves the prose. Returns
    how many entries were kept."""
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
    links = card_links(bank, here) if on else {}

    def file(name: str, tid: str | None, raw: str | None) -> None:
        name = (name or "").strip()
        link = links.get(tid) or {}
        if name and link.get("kind") in ("page", "card") and not _named_apart(content, tid, name, link["name"]):
            name = link["name"]     # the card says who, whatever the model called them
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
            if match_digits(stated) and _raw_person_span(content, stated, episode_id, override=override, gaps=gaps) is None:
                return True      # not the person's word: dropped, and the vault never holds it
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
                 ]
    # A number on a card needs no name in the words. Only the person's own line can file it, as for any other (`file`).
    for tid, link in links.items():
        if link["kind"] != "me" and not any(t == tid for _n, t in seen):
            file(link["name"], tid, None)
    values += entries
    for i, entity in enumerate(entities):
        if isinstance(entity, dict):
            entities[i] = _clean_strings(entity, loose, bank, on, str(entity.get("type") or "person") == "person")
    named = {str(e.get("name") or "").casefold() for e in entities if isinstance(e, dict)}
    birth = {link["name"].casefold(): link["card"] for link in links.values() if link["kind"] == "card"}
    for entry in entries:
        # What is held for a name waits on its pending line, so the name must be one Stage 2 parks.
        if entry["entity"].casefold() not in named:
            named.add(entry["entity"].casefold())
            entities.append({"name": entry["entity"], "type": "person", "confidence": 0.6, "key_facts": [],
                             "summary": ""})
    for entity in entities:     # the person gave this one waiting card's number: that names it (Stage 2's Contacts rail)
        if isinstance(entity, dict) and (card := birth.get(str(entity.get("name") or "").casefold())):
            entity[CARD_KEY] = card
    return len(entries)


# ---- what the person's line says ---------------------------------------------------------------------------------

_NUM_ONLY = r"(?:numbers?|n[uú]meros?|num[eé]ros?|nummer)"
_DEVICE = r"(?:phone|cell(?:phone)?|mobile|m[oó]vil|celular|tel[eé]fono|telefon|t[eé]l[eé]phone)"
_NUM = rf"(?:{_NUM_ONLY}|{_DEVICE})"
_OLD = r"(?:old|former|previous|antigu[oa]|viej[oa]|anterior|ancien(?:ne)?|velho|alte[rs]?)"
_NEW = r"(?:new|nuev[oa]|nouveau|nouvelle|novo|nova|neue?[rs]?)"
_IS = r"(?:is|es|est|ist|era|:|=|-)"
#: Each must lead straight to the number: "new job", "got a new phone, her number is X" and "her new number, I only have X"
#: say nothing about X, so they ask. A device word counts only when it is what is being given ("her new mobile is X").
_CHANGED_BEFORE = re.compile(
    rf"(?i)\b{_NEW}\s+(?:{_DEVICE}\s+)?{_NUM}(?:\s+de\s+[^\W\d_]+)?\s*(?:{_IS}|now|ahora)?\s*(?:now\s*|ahora\s*)?$"
    rf"|\b{_CHANGE_VERB}\s+(?:[\w'’]+\s+){{0,2}}{_NUM}\s*(?:to|a|por|,\s*it['’]?s|,\s*now|:|=)?\s*$"
    rf"|\b{_NUM}\s+(?:has\s+|just\s+)?{_CHANGE_VERB}\s*(?:to|a|por|:|=)?\s*$"
    rf"|\b{_NUM}\s+(?:is|es|est)\s+(?:now|ahora|maintenant)\s*$"
    rf"|\b(?:now|ahora)\s+(?:[^\W\d_]+\s+){{0,2}}{_NUM}\s+(?:is|es)\s*$")
_CHANGED_AFTER = re.compile(rf"(?i)^\W*(?:is|es)\s+(?:[^\W\d_]+\s+)?{_NEW}\s+{_NUM}\s*[.!]?\s*$")
_PAST_BEFORE = re.compile(
    rf"(?i)\b{_OLD}\s+(?:[^\W\d_]+\s+)?(?:{_NUM}|one|uno|una)\s*(?:was|is|were|era|es|:|=|-)?\s*$"
    r"|\bused to be\s*$")
_PAST_AFTER = re.compile(rf"(?i)^\W*(?:was|is|era|es)\s+(?:[^\W\d_]+\s+)?{_OLD}\s+{_NUM}\b")
#: "changed from <old> to <new>": the token right after one of these, on a line a change word opens.
_CHANGE_FROM = re.compile(rf"(?i)\b{_CHANGE_VERB}\s+(?:[\w'’]+\s+){{0,2}}{_NUM}\s+(?:from|de|desde|von)\s+$")
_TO_BEFORE = re.compile(r"(?i)^\W*(?:to|a|por|→|->|zu|in)\W*$")
_ADDITIONAL_BEFORE = re.compile(
    rf"(?i)\b(?:work|office|home|second|other|another|personal|business|landline|trabajo|oficina|casa|fij[oa]|otr[oa]|"
    rf"segund[oa]|travail|autre|arbeit|zweite)\s+(?:[^\W\d_]+\s+)?{_NUM}\s*(?:{_IS})?\s*$"
    r"|\b(?:also|too|tambi[eé]n|aussi|auch)\s+(?:has|have|uses?|tiene|usa)\s*$")
_ADDITIONAL_AFTER = re.compile(r"(?i)^\W*(?:too|as well|tambi[eé]n|aussi|auch)\b")
#: A line that doubts itself changes nothing: it asks. "not sure if her new number is X", "I don't have her new number".
_HEDGE = re.compile(
    r"(?i)\b(?:not sure|unsure|don['’]?t (?:have|know|think)|do not (?:have|know)|doesn['’]?t|didn['’]?t|isn['’]?t|wasn['’]?t|"
    r"not (?:her|his|their)|maybe|might|perhaps|possibly|probably|i think|i guess|i believe|i only|if|whether|wrong|"
    r"no s[eé]|no tengo|quiz[aá]s|tal vez|creo que|a lo mejor|peut[- ][eê]tre|vielleicht|\?)(?!\w)|\?")
#: A clause ends at a sentence's end or an "and": what was said of someone before it says nothing of this number.
_CLAUSE_END = re.compile(r"(?i)[.;!?]\s|\s(?:and|y|et|und|e)\s")


def _clause(text: str) -> str:
    cut = 0
    for m in _CLAUSE_END.finditer(text):
        cut = m.end()
    return text[cut:]


def read_line(line: str) -> dict[str, tuple[str, list[str]]]:
    """``{token id: (how this line relates it to what the page holds, the tokens it replaces)}``, clause by clause: each
    number is read from the words leading straight to it, never from the whole line, and a line that hedges says nothing.
    A word for it, or :data:`UNKNOWN`, which asks. A miss costs one question; a wrong close would silently make the wrong
    number current."""
    tokens = list(TOKEN_RE.finditer(line or ""))
    if _HEDGE.search(TOKEN_RE.sub(" ", line or "")):
        return {m.group(1): (UNKNOWN, []) for m in tokens}
    kinds: list[str] = []
    for i, m in enumerate(tokens):
        before = _clause(line[tokens[i - 1].end() if i else 0:m.start()])
        after = line[m.end():tokens[i + 1].start() if i + 1 < len(tokens) else len(line)]
        if _CHANGE_FROM.search(before):
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


def card_links(bank, tids: Iterable[str]) -> dict[str, dict]:
    """Who the cards holding these tokens are, while on: ``{token id: {kind, name, ...}}``. ``page``: one card, its page.
    ``card``: one card still waiting, with its id. ``me``: the person's own. ``tie``: two cards hold it, so nobody is
    guessed; ``name`` is where the one question goes. The hashes and the waiting cards only, never the faces store
    (`contacts_book`). A card known to neither (its name shared by two pages) links to nothing."""
    if not bank or not enabled():
        return {}
    holders = cards_of(bank)
    wanted = {t: sorted(set(holders[t])) for t in tids if holders.get(t)}
    if not wanted:
        return {}
    from api.services import bank_index, contact_identity, contacts_local

    waiting = {str(c.get("id")): c for c in contacts_local.load_waiting(_name(bank)) if contacts_local.card_live(c)}
    pages: dict[str, str] = {}
    labels: dict[str, set[str]] = {}
    if Path(str(bank)).is_absolute():
        bank = Path(str(bank))
        rows = [{"id": f.stem, "frontmatter": f.frontmatter or {}} for f in bank_index.files(bank, "entities")]
        names = {r["id"]: str(r["frontmatter"].get("name") or r["id"]) for r in rows}
        pages = {cid: names[stem] for cid, stem in contact_identity.card_pages(rows).items()}
        for row in rows:
            fm = row["frontmatter"]
            if str(fm.get("type") or "") == "person" and fm.get("status") != "dropped" and fm.get("owner") is not True:
                for label in people_directory.labels(fm, row["id"]):
                    labels.setdefault(people_directory.fold(label), set()).add(names[row["id"]])

    def one(card_id: str) -> dict | None:
        if card_id in pages:
            return {"kind": "page", "name": pages[card_id]}
        card = waiting.get(card_id)
        if card is None:
            return None
        name = contacts_local.card_name(card)
        said = labels.get(people_directory.fold(name)) or set()
        if len(said) == 1:      # the card's whole name is a page's name or alias: that page, never a second one
            return {"kind": "page", "name": next(iter(said))}
        return {"kind": "card", "name": name, "card": card_id} if name and not said else None

    out: dict[str, dict] = {}
    for tid, ids in wanted.items():
        if len(ids) > 1:
            found = sorted((f for f in (one(i) for i in ids if i != "me") if f),
                           key=lambda f: (f["kind"] != "page", f["name"].casefold()))
            if found:
                out[tid] = {"kind": "tie", "name": found[0]["name"]}
        elif ids[0] == "me":
            out[tid] = {"kind": "me"}
        elif found_one := one(ids[0]):
            out[tid] = found_one
    return out


def card_note(content: str | None, bank) -> str:
    """What the model is told about the tokens a card holds: the card's whole name as the person saved it, for the model to
    judge. No rule here reads any word of it: not a bracket, not a last word as a surname. Empty with nothing to say; goes to the model only."""
    lines = []
    for tid, link in card_links(bank, set(token_ids(content))).items():
        if link["kind"] == "me":
            lines.append(f"{token(tid)} is on the user's own Contacts card: it is their own number.")
        elif link["kind"] == "tie":
            lines.append(f"{token(tid)} is on more than one Contacts card, so whose it is stays open: leave it out unless "
                         "the user's words name the person.")
        else:
            lines.append(f"{token(tid)} is on the user's Contacts card \"{link['name']}\", so it is that person's number even "
                         "when no line names them: use that whole name as the entity, as it stands. It is the label the "
                         "user saved them under, not a record of who they are: any word in it may be a nickname, a trade, "
                         "a place or where they know this person rather than a surname. Judge that yourself. No word of "
                         "it is a stated fact, a role or a title unless the conversation or your own reasoning supports "
                         "it, and then only as your reading.")
    return f"[Cicada's note, not part of the conversation: {' '.join(lines)}]\n\n" if lines else ""


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
        link = card_links(memory_path, [tid]).get(tid) if held_by else None
        if link and link["kind"] == "tie" and not held_by <= carried:
            claim.number_ask = ASK_CARD     # two cards hold it: never a guess, whichever page it was filed on
        elif held_by and carried and not held_by & carried:
            claim.number_ask = ASK_CARD
        elif (len(name.split()) < 2 and not fm.get("unnamed") and not (held_by & carried)
              and not (link and link["kind"] == "page" and link["name"] == name)):
            claim.number_ask = ASK_NAME
        kept.append(claim)
    return kept, audit


def _retoken_any(line: str, bank, *, only: set[str] | None = None) -> str:
    """A line from a writer that kept its digits, with each digit run as its token if the vault knows it: so a claim
    resting on it is read clause by clause like any other. ``only``: just these tokens, so a run the vault learned after
    the line was stored stays as digits."""
    out, last = [], 0
    for m in _RUN.finditer(line):
        at = m.start()
        for start, end in _windows(m):      # a run can hold two numbers, each stored as its own token
            if start < at:
                continue
            tid = known_id(bank, line[start:end])
            if tid and (only is None or tid in only):
                out += [line[last:start], token(tid)]
                last = at = end
    return "".join(out) + line[last:]


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
