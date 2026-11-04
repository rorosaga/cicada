"""What in a conversation is likely a credential, a card, a bank account or an ID number (G235, owner 2026-11-04).

`episode_scrub` replaces known secret SHAPES before anything is stored; it is permanent, so it only takes what cannot be
anything else ("false negatives over lost words", #502). Ordinary wording gets past it: "my password is <short>" reaches
the bank and then whichever engine Sleep runs on. This module finds that wording so the person can be told. It changes
nothing: it answers offsets (:class:`Hit`), never the words. Pure and engine-free: no model reads text to decide whether
a model may read it.

**Crying wolf is the design risk.** "password" as a word is everywhere in anyone's coding sessions, so each kind rests on
something a sentence about passwords does not have:

* ``card``: the number's own checksum (Luhn) and issuer range, written the way a card is written or beside a card word.
* ``bank``: an IBAN's mod-97 and its country's length, a CLABE's check digit, or an account number announced as one.
* ``id``: a named national ID beside a value that has the ID's form; a US SSN or Spanish DNI needs the word too.
* ``key``: vendor prefixes (the ones `episode_scrub` also knows, for a body older than it, plus ones it does not), a
  whole PEM block, a password inside a connection URL, and an UPPER_CASE_SECRET=value line the person pasted.
* ``password``: a statement that gives one. The word alone never counts: the value must be a single token that reads
  like a password and unlike a property of passwords, code, a placeholder or a test fixture (:func:`_password_value`).

**Who said it matters** (:class:`Context`). A person's line, or a chat member's, is read for every kind. An agent's reply
(the bulk of every coding session) is read only for validated numbers and vendor shapes, plus "your password is <strong
value>"; a harness session's person turns need "my"/"mi" or a named system ("the wifi password is"); a line inside a code
fence is read only for the shapes. A saved page, a feed item and a media line are someone else's public words: never read.

**Not detected, on purpose:** medical and legal details. They have no shape, they are what a life is made of, and a
person telling an agent about a diagnosis is the record working; every health conversation would be an alarm. Also not
detected: one-time codes and PINs (`episode_scrub` already takes them, and they expire).

A :class:`Hit` holds offsets and a kind. Nothing here returns, logs or hashes a value: a hash of a short password is the
password, to anyone with a wordlist."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

from api.services import authorship, evidence

PASSWORD, KEY, CARD, BANK, ID = "password", "key", "card", "bank", "id"
#: The order a row names them in. Telemetry and the wire carry these enums, never a value.
KINDS: tuple[str, ...] = (PASSWORD, KEY, CARD, BANK, ID)

#: One typed mark per kind, in what an engine reads when a confident hit is held back (:func:`held_text`) and in a body
#: after the person removed it. Neither ever carries anything of the value.
HELD_MARK = "[held back: {kind}]"
REMOVED_MARK = "[removed: {kind}]"


@dataclass(frozen=True)
class Hit:
    """A likely value: where it is, what kind, and how sure. Never the value.

    ``sure`` decides whether an engine reads it (ruling 60): a confident hit is held back, an unsure one only reported.
    Confident: a number that passed its own checksum, a vendor shape, a value in a connection URL or a secret's env line,
    a statement giving a password that reads like one. Unsure: a password of letters only, or of digits only that no one
    claimed; an account or ID number announced in words with nothing to check it against."""
    kind: str
    start: int
    end: int
    sure: bool = True


@dataclass(frozen=True)
class Context:
    """How a line is read. ``speaker``: ``person`` (the person or a chat member), ``agent``, or ``skip``."""
    speaker: str = "person"
    harness: bool = False
    fenced: bool = False


# ---- password ------------------------------------------------------------------------------------------------------

# The word for a password, per language. "clave" is also Spanish for "key" in every sense ("la clave es ser constante"),
# "contra" Spanish for "against", and "pass" an English word: WEAK, needing a value with a digit whatever else the
# sentence says ("contra" a named system too).
_STRONG_WORD = (r"passwords?|passphrase|passcode|pwd|contrase[nñ]as?|senha|mot de passe|passwort|kennwort")
_WEAK_WORD = r"clave|contra|pass|pw"
_WORD = rf"(?:{_STRONG_WORD}|{_WEAK_WORD})"
#: "my"/"mi": a statement about the speaker's own password.
_MINE = r"my|our|mi|mis|nuestra|nuestro|minha|nossa|mon|ma|mein|meine"
_YOURS = r"your|tu|su|sua|tua|votre|dein|deine|ihr"
#: Things a real password belongs to. "the wifi password is x" is a statement even in a coding session.
_SYSTEM = (r"wi-?fi|router|network|sudo|root|ssh|server|vpn|email|e-?mail|gmail|icloud|bank|banco|login|laptop|phone|"
           r"mac|computer|netflix|hbo|disney|spotify|amazon|account|cuenta|correo|red|internet|cajero|tel[eé]fono|"
           r"computadora|ordenador|celular|m[oó]vil|casa|home|office|oficina")
_LINK = (r"(?:\s(?:is going to be|is|was|would be|will be|es|era|ser[ií]a|sera|será|va a ser|[eé]|est|ist|lautet)\b\s*:?"
         r"|'s\b|\s*(?:=|:|->))")
# "<qualifier> <word> [for/de <thing>] <link> <value>": the qualifier is optional, read by the caller.
_STATEMENT_RE = re.compile(
    rf"(?P<before>\b(?:{_MINE}|{_YOURS}|the|la|el|a|o|le|das|die|new|nueva|nuevo)\b(?:\s+[\w-]+){{0,3}}?\s+)?"
    rf"(?P<word>\b{_WORD}\b)"
    rf"(?P<of>\s+(?:for|to|of|de|del|da|do|para|von|f[uü]r|on|en)(?:\s+[\w.-]+){{1,4}}?)?"
    rf"(?P<system>\s+[\w-]+)??"
    rf"(?P<link>{_LINK})\s*"
    rf"(?P<rest>\S.*)", re.IGNORECASE)

#: A line that gives a login: "user: x / password: y", "contraseña: y".
_LABEL_RE = re.compile(rf"(?:^|[\s/|,;(])(?P<word>{_WORD})\s*[:=]\s*(?P<rest>\S.*)", re.IGNORECASE)

_QUOTES = {'"': '"', "'": "'", "`": "`", "“": "”", "‘": "’", "«": "»"}
_TRAIL = ".,;:!?)]}>…"

#: What follows "password is" when it is a property of the password, in the languages above. Only a letters-only value
#: from a person's "my password is <word>." needs this: a value with a digit never reads as one of these.
_NOT_A_VALUE = frozenset("""
    a an the this that it its my your our his her their not no none null nil empty blank missing required optional
    needed necessary incorrect wrong invalid correct right valid good bad weak strong long short simple easy hard
    difficult complex complicated secure insecure safe unsafe stored saved hashed encrypted salted set reset changed
    updated expired stolen leaked hacked compromised rejected accepted protected shared known unknown new old same
    different random generated autogenerated manual temporary temp default ok okay fine great terrible awful horrible
    stupid dumb silly ridiculous too very so really also still always never just only now here there what which where
    how why when because and or but if then on in at to for of from with by as is was be being been true false yes
    case sensitive already actually probably here's literally basically something anything nothing everything
    requerida requerido obligatoria obligatorio necesaria necesario incorrecta incorrecto mala malo buena bueno correcta
    correcto valida valido válida válido inválida inválido segura seguro insegura inseguro debil débil fuerte larga
    largo corta corto facil fácil dificil difícil simple compleja complejo guardada guardado cifrada cifrado encriptada
    encriptado cambiada cambiado nueva nuevo vieja viejo misma mismo otra otro distinta distinto vacia vacía vacio vacío
    temporal aleatoria aleatorio robada robado expirada expirado caducada caducado una un la el lo mi tu su muy
    demasiado tan siempre nunca solo sólo aqui aquí alli allí que qué cual cuál donde dónde como cómo porque cuando
    sí si no ya tambien también algo nada todo
    fraca forte errada certa segura vazia nova velha mesma faible forte fausse vide nouvelle falsch richtig leer neu
""".split())

#: Code words a value can be without being a value.
_CODE_VALUE = frozenset("""
    string str text varchar char int integer bool boolean bytes byte object dict list any type hash bcrypt argon2 sha256
    md5 undefined nil none null true false self this required optional env input field value values form param params
    arg args user username name email login auth credentials creds config settings prompt stdin getpass mask
""".split())

#: A fixture, an example or a placeholder rather than anyone's password. A miss is the cheap side of this.
_PLACEHOLDER_RE = re.compile(
    r"pass(?:word)?|passw0rd|p@ss|secret|changeme|change[_-]?me|example|sample|dummy|fake|test|demo|foo|bar\b|baz|^admin\d{0,4}$|"
    r"your|my[_-]|xxx|\*\*\*|•|hunter|letmein|qwerty|123456|abc123|abcd|asdf|redacted|\[|placeholder|contrase|clave|"
    r"token|mock|stub|fixture|tu[_-]|mi[_-]|abcdef|zyxwvu|12345", re.IGNORECASE)

#: A harness session's person line that is plainly about logging in somewhere.
_SHELL_RE = re.compile(r"\b(?:ssh|sudo)\b", re.IGNORECASE)
_WEAK = frozenset({"clave", "contra", "pass", "pw"})
#: "I changed my password to <value>", "cambié mi contraseña a <value>".
_CHANGED_RE = re.compile(
    rf"\b(?:chang(?:ed|ing)|updated?|reset|set|cambi[eé]|actualic[eé]|puse)\s+(?:{_MINE}|the|la|el)\s+"
    rf"(?:[\w-]+\s+)?(?P<word>{_WORD})\s+(?:to|a|as|como)\s+(?P<rest>\S.*)", re.IGNORECASE)
#: "login <handle>, password <value>": a login spelled out, with no "is".
_LOGIN_RE = re.compile(
    rf"\b(?:login|user(?:name)?|usuario)\b.{{1,40}}?\b(?P<word>{_WORD})\s+(?P<rest>\S.*)", re.IGNORECASE)
#: A date is a date, whatever word stands before it ("pw: 2024-11-01", "checking account 2024-11-04").
_DATE_RE = re.compile(r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})$")
#: Where a password is kept, not what it is: "my password is Bitwarden", "my password is 1Password".
_PASSWORD_MANAGERS = frozenset({"bitwarden", "1password", "lastpass", "dashlane", "keychain", "nordpass", "keepass",
                                "protonpass", "enpass"})
#: What may stand right before a bare "pass" or "pw" and still mean a password. Anything else makes it another kind of
#: pass: a season pass, a mountain pass, a boarding pass.
_PASS_MAY_FOLLOW = rf"(?:{_MINE}|{_YOURS}|{_SYSTEM}|the|la|el|a|o|le|das|die|new|old|current|nueva|nuevo|vieja|viejo|actual|y|and|or|o)"
_CODE_CHARS_RE = re.compile(r"[(){}<>\[\]$%\\|;,^]|=>|->|::|\.\.|^[.\-/~@]|/.*/|\.(?:py|js|ts|md|env|json|ya?ml|txt|sh|swift|html?|com|org|net)$",
                            re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"^[a-z]+(?:[A-Z][a-z]+)+$|^[A-Z][a-z]+(?:[A-Z][a-z]+)+$|^[A-Za-z]+_[A-Za-z_]+$|^[A-Z_]+$|^[a-z]+\.[a-z_.]+$")
_CODE_LINE_RE = re.compile(r"""^\s{4,}\S|[{}();]\s*$|\bdef\s|\bfunction\b|\bclass\s|\bconst\s|\blet\s|\bvar\s|\breturn\b|\bimport\b|\bself\.|=>|^\s*["'][\w-]+["']\s*:|^\s*[-*]?\s*`""")


def _value_after(rest: str) -> tuple[int, int, bool] | None:
    """``(start, end, quoted)`` of the value opening ``rest``, or ``None``."""
    if not rest:
        return None
    close = _QUOTES.get(rest[0])
    if close:
        end = rest.find(close, 1)
        if end <= 1:
            return None
        return 1, end, True
    m = re.match(r"\S+", rest)
    if not m:
        return None
    end = m.end()
    while end > 0 and rest[end - 1] in _TRAIL:
        end -= 1
    return (0, end, False) if end else None


def _password_value(value: str, *, quoted: bool, mine: bool, weak: bool, ends: bool, agent: bool) -> bool:
    """Does this read as a password rather than a property of one, code, a placeholder or a test fixture?"""
    if not 4 <= len(value) <= 64 or _DATE_RE.match(value) or value.casefold() in _PASSWORD_MANAGERS:
        return False
    if quoted and any(c.isspace() for c in value) and len(value.split()) > 5:
        return False  # a sentence in quotes
    if _CODE_CHARS_RE.search(value) or value.casefold() in _CODE_VALUE or _PLACEHOLDER_RE.search(value):
        return False
    if _IDENTIFIER_RE.match(value) and not any(c.isdigit() for c in value):
        return False
    has_digit = any(c.isdigit() for c in value)
    has_alpha = any(c.isalpha() for c in value)
    if agent:
        return has_digit and has_alpha  # an agent's "your password is …": only a value no sentence could be
    if weak:
        return has_digit and not _year(value)   # "la clave es ser constante", "the pass is valid", "la clave es 2024"
    if has_digit or quoted:
        if value.isdigit():
            return len(value) >= 4 and not _year(value) and (mine or quoted)
        return True
    if any(not c.isalnum() for c in value) and has_alpha and value.casefold() != value.upper().casefold():
        return True                     # "blue-Moon!"
    # Letters only: "my password is sunshine." A statement of one's own, whole to the end of the sentence, and not a
    # word that describes passwords. The open class of adjectives is the risk; it needs "my" and the sentence's end.
    return mine and ends and value.casefold() not in _NOT_A_VALUE


def _sure_password(value: str, *, claimed: bool, weak: bool) -> bool:
    """Letters and digits together are a password however it is said; digits alone only when someone's or something's;
    letters alone never (it may be a word), nor a weak word's value no one claimed."""
    digits, letters = any(c.isdigit() for c in value), any(c.isalpha() for c in value)
    if weak and not claimed:
        return False
    if digits and letters:
        return True
    if digits:
        return claimed
    return any(not c.isalnum() and not c.isspace() for c in value)


def _year(value: str) -> bool:
    return len(value) == 4 and value[:2] in ("19", "20")


def _ends_sentence(rest: str, end: int) -> bool:
    tail = rest[end:].lstrip(_TRAIL + "\"'`”’»")
    return not tail.strip() or bool(re.match(r"\s*(?:[.!?…]|$)", rest[end:]))


def _another_pass(line: str, start: int, word: str) -> bool:
    """A bare "pass" or "pw" right after a noun that is not a system: a season pass, a mountain pass, a boarding pass."""
    if word not in ("pass", "pw"):
        return False
    before = re.search(r"([\w-]+)\s+$", line[:start])
    return before is not None and re.fullmatch(_PASS_MAY_FOLLOW, before.group(1), re.IGNORECASE) is None


def _passwords(line: str, base: int, ctx: Context) -> Iterable[Hit]:
    agent = ctx.speaker == "agent"
    for m in _STATEMENT_RE.finditer(line):
        before = (m.group("before") or "").strip().casefold()
        word = m.group("word").casefold()
        weak = word in _WEAK
        if _another_pass(line, m.start("word"), word):
            continue
        if m.start("word") and re.search(r"(?:palabra|frase|llave|primary|foreign)\s+$", line[:m.start("word")], re.I):
            continue                    # "palabra clave: …" is a keyword, "clave primaria" sits on the other side
        first = before.split()[0] if before else ""
        mine = bool(re.fullmatch(_MINE, first, re.IGNORECASE)) if first else False
        yours = bool(re.fullmatch(_YOURS, first, re.IGNORECASE)) if first else False
        about = f"{before} {m.group('of') or ''} {m.group('system') or ''}"
        system = bool(re.search(rf"\b(?:{_SYSTEM})\b", about, re.IGNORECASE))
        if word == "contra" and not system:
            continue                    # "contra" is "against" unless it belongs to something
        link = m.group("link").casefold().strip(": ") or ":"
        if m.group("word")[-1:].casefold() == "s" and word not in ("pass", "contraseñas"):
            continue  # "passwords: …" heads a list, "passwords is" is not a sentence
        if agent and not (yours and link in ("is", ":", "es")):
            continue
        if ctx.harness and not agent and not (mine or system or _SHELL_RE.search(line)):
            continue
        if not agent and not ctx.harness and link in ("=", ":", "->") and not (mine or system) and _CODE_LINE_RE.search(line):
            continue
        got = _value_after(m.group("rest"))
        if got is None:
            continue
        start, end, quoted = got
        if quoted and link == "=":
            continue  # password = "x" is how code writes it
        value = m.group("rest")[start:end]
        ends = _ends_sentence(m.group("rest"), end)
        if not _password_value(value, quoted=quoted, mine=mine or yours, weak=weak, ends=ends, agent=agent):
            continue
        at = m.start("rest") + start
        yield Hit(PASSWORD, base + at, base + at + len(value), _sure_password(value, claimed=mine or yours or system, weak=weak))
    if agent or _CODE_LINE_RE.search(line):
        return
    for rx in (_CHANGED_RE, _LOGIN_RE):
        for m in rx.finditer(line):
            got = _value_after(m.group("rest"))
            if got is None:
                continue
            start, end, quoted = got
            value = m.group("rest")[start:end]
            # A value with no "is" in front of it has to read as a password on its own: letters and digits together.
            if (any(c.isdigit() for c in value) and any(c.isalpha() for c in value)
                    and _password_value(value, quoted=quoted, mine=True, weak=False, ends=False, agent=False)):
                at = m.start("rest") + start
                yield Hit(PASSWORD, base + at, base + at + len(value))
    if ctx.harness:
        return
    for m in _LABEL_RE.finditer(line):
        word = m.group("word").casefold()
        got = _value_after(m.group("rest"))
        if got is None:
            continue
        start, end, quoted = got
        value = m.group("rest")[start:end]
        if quoted:
            continue  # password="x" is how code writes it; a person's note does not quote its own login
        if _another_pass(line, m.start("word"), word):
            continue
        if m.start("word") and re.search(r"(?:palabra|frase|llave|primary|foreign)\s+$", line[:m.start("word")], re.I):
            continue
        if not _password_value(value, quoted=False, mine=False, weak=word in _WEAK, ends=False, agent=False):
            continue
        at = m.start("rest") + start
        yield Hit(PASSWORD, base + at, base + at + len(value), _sure_password(value, claimed=False, weak=word in _WEAK))


# ---- key -----------------------------------------------------------------------------------------------------------

#: Vendor shapes. The first group `episode_scrub` already replaces at capture, so a hit means a body older than it; the
#: rest it does not know (and a scrub is permanent, so they are reported here rather than added there unasked).
_VENDOR_RES: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in (
    r"\bsk-(?:ant-|proj-|or-)?[A-Za-z0-9_-]{20,}",
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bxox[abopr]s?-[A-Za-z0-9-]{10,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bAIza[0-9A-Za-z_-]{30,}",
    r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    # Not scrubbed today:
    r"\b[sr]k_live_[A-Za-z0-9]{16,}",
    r"\bglpat-[A-Za-z0-9_-]{16,}",
    r"\bnpm_[A-Za-z0-9]{30,}",
    r"\bhf_[A-Za-z0-9]{30,}",
    r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}",
    r"\bxai-[A-Za-z0-9]{30,}",
    r"\bgsk_[A-Za-z0-9]{30,}",
    r"\bpplx-[A-Za-z0-9]{30,}",
))
#: A whole PEM block: the header alone is every TLS tutorial.
_PEM_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=\s]{64,}?-----END [A-Z ]*PRIVATE KEY-----")
_URL_CRED_RE = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss|amqps?|ftp|sftp|ssh|smb|https?)"
    r"://[^\s:/@]+:(?P<value>[^\s:/@]{4,})@[^\s/]+", re.IGNORECASE)
#: A database's own name doubling as its dev password: every local connection string in every README.
_URL_DEFAULTS = frozenset({"postgres", "postgresql", "mysql", "root", "redis", "mongo", "mongodb", "guest", "rabbitmq",
                           "localhost", "pass", "pwd", "user"})
_ENV_LINE_RE = re.compile(
    r"^\s*(?:export\s+)?[A-Z][A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY|AUTH_TOKEN|ACCESS_TOKEN)"
    r"\s*=\s*['\"]?(?P<value>[^\s'\"#]{8,})['\"]?\s*$")


#: "api key: <value>", said in words: `episode_scrub` wants ``api_key`` and 12+ characters joined by ``=``/``:``, which a
#: spaced "api key" and "is" get past.
_SAID_KEY_RE = re.compile(
    r"\b(?:api\s+key|api\s+token|access\s+token|auth\s+token|clave\s+(?:de\s+)?(?:la\s+)?api|bearer)\b"
    r"(?:\s*[:=]|\s+(?:is|es))?\s*(?P<value>[A-Za-z0-9._~+/=-]{16,})", re.IGNORECASE)


def _keys(line: str, base: int, ctx: Context) -> Iterable[Hit]:
    for rx in _VENDOR_RES:
        for m in rx.finditer(line):
            value = m.group(0)
            if not (any(c.isdigit() for c in value) and any(c.isalpha() for c in value)):
                continue  # "sk-learn-contrib-something": a name, not a key
            if value.startswith("sk-") and value == value.lower() and value.count("-") >= 2:
                continue  # "sk-kogptv2-kormath-causal": a model's name
            if _PLACEHOLDER_RE.search(value[3:]):
                continue
            yield Hit(KEY, base + m.start(), base + m.end())
    if ctx.speaker == "agent":
        return
    for m in _URL_CRED_RE.finditer(line):
        value = m.group("value")
        if value.casefold() in _URL_DEFAULTS:
            continue
        if not _CODE_CHARS_RE.search(value) and not _PLACEHOLDER_RE.search(value) and value.casefold() not in _CODE_VALUE:
            yield Hit(KEY, base + m.start("value"), base + m.end("value"))
    if not ctx.fenced:
        for m in _SAID_KEY_RE.finditer(line):
            value = m.group("value")
            if (any(c.isdigit() for c in value) and any(c.isalpha() for c in value) and not value.endswith("...")
                    and not _IDENTIFIER_RE.match(value) and not _PLACEHOLDER_RE.search(value)):
                yield Hit(KEY, base + m.start("value"), base + m.end("value"))
    m = _ENV_LINE_RE.match(line)
    if m:
        value = m.group("value")
        if (any(c.isdigit() for c in value) and any(c.isalpha() for c in value)
                and not _CODE_CHARS_RE.search(value) and not _PLACEHOLDER_RE.search(value)):
            yield Hit(KEY, base + m.start("value"), base + m.end("value"))


# ---- card ----------------------------------------------------------------------------------------------------------

_CARD_RE = re.compile(r"(?<![\w.,/+-])(?:\d[ -]?){12,18}\d(?![\w/+-]|[.,]\d)")
_CARD_WORD_RE = re.compile(
    r"\b(?:card|credit|debit|visa|master\s?card|amex|american express|discover|tarjeta|cr[eé]dito|d[eé]bito|cart[aã]o|"
    r"carte|kreditkarte|cvv|cvc)\b", re.IGNORECASE)
_CVV_RE = re.compile(r"\b(?:cvv2?|cvc2?|c[oó]digo de seguridad)\b\s*(?:is|es|:|=)?\s*(?P<value>\d{3,4})\b", re.IGNORECASE)
#: Issuers' published test numbers, in every payments integration ever discussed.
_TEST_CARDS = frozenset({
    "4242424242424242", "4000056655665556", "4111111111111111", "4012888888881881", "4222222222222", "5555555555554444",
    "5200828282828210", "5105105105105100", "378282246310005", "371449635398431", "6011111111111117", "6011000990139424",
    "3056930009020004", "30569309025904", "38520000023237", "3566002020360505", "3530111333300000", "6200000000000005",
    "4000000000000002", "4000000000009995", "4000000000000069", "4000000000000127", "4000000000000119",
    "2223003122003222", "5425233430109903", "4917610000000000", "378734493671000", "6250941006528599",
})


def _luhn(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        d = ord(c) - 48
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _issuer_length(digits: str) -> bool:
    n, a, b, c, d = len(digits), digits[:1], digits[:2], digits[:3], digits[:4]
    if a == "4":
        return n in (13, 16, 19)                                     # Visa
    if "51" <= b <= "55" or "2221" <= d <= "2720":
        return n == 16                                               # Mastercard
    if b in ("34", "37"):
        return n == 15                                               # American Express
    if d == "6011" or b == "65" or "644" <= c <= "649":
        return n in (16, 19)                                         # Discover
    if b in ("36", "38") or "300" <= c <= "305":
        return n == 14                                               # Diners
    if "3528" <= d <= "3589":
        return n in (16, 19)                                         # JCB
    if b == "62":
        return 16 <= n <= 19                                         # UnionPay
    return False


def _card_layout(raw: str, digits: str) -> bool:
    """Written the way a card is printed: 4-4-4-4, or Amex's 4-6-5, with a separator."""
    groups = [g for g in re.split(r"[ -]", raw) if g]
    lengths = [len(g) for g in groups]
    return lengths in ([4, 4, 4, 4], [4, 6, 5], [4, 6, 4], [4, 4, 4, 4, 3], [4, 4, 4, 1])


def _cards(line: str, base: int, ctx: Context) -> Iterable[Hit]:
    word = _CARD_WORD_RE.search(line) is not None
    for m in _CARD_RE.finditer(line):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if not 13 <= len(digits) <= 19 or digits in _TEST_CARDS or len(set(digits)) < 4:
            continue
        if not _issuer_length(digits) or not _luhn(digits):
            continue
        if word or _card_layout(raw, digits):
            yield Hit(CARD, base + m.start(), base + m.end())
    if ctx.speaker != "agent":
        for m in _CVV_RE.finditer(line):
            yield Hit(CARD, base + m.start("value"), base + m.end("value"))


# ---- bank ----------------------------------------------------------------------------------------------------------

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){11,30}\b")
_IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29, "BY": 28,
    "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18,
    "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22,
    "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20,
    "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SC": 31, "SE": 24, "SI": 19,
    "SK": 24, "SM": 27, "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}
#: The examples in every IBAN explainer and library's tests.
_DOC_IBANS = frozenset({
    "GB82WEST12345698765432", "GB29NWBK60161331926819", "DE89370400440532013000", "FR1420041010050500013M02606",
    "ES9121000418450200051332", "NL91ABNA0417164300", "IT60X0542811101000000123456", "BE68539007547034",
    "CH9300762011623852957", "AT611904300234573201", "PL61109010140000071219812874", "PT50000201231234567890154",
})
_CLABE_RE = re.compile(r"\bclabe\b[^\d\n]{0,30}(?P<value>\d{18})\b", re.IGNORECASE)
_ACCOUNT_RE = re.compile(
    r"\b(?:(?:bank\s+)?account\s+(?:number|no\.?|#)|routing\s+number|n[uú]mero\s+de\s+cuenta|no\.?\s+de\s+cuenta|"
    r"cuenta\s+(?:bancaria|corriente|de\s+ahorros?|monetaria)|n[uú]mero\s+de\s+la\s+cuenta|conta\s+banc[aá]ria|"
    r"checking\s+account(?:\s+number)?|savings\s+account(?:\s+number)?)\b(?:\s+(?:del?|en)\s+\w+){0,2}"
    r"(?:\s+(?:is|es|era|was|:|=))?\s*:?\s*(?P<value>\d[\d -]{5,24}\d)\b", re.IGNORECASE)


def _iban_ok(raw: str) -> bool:
    iban = re.sub(r"[ -]", "", raw)
    if iban in _DOC_IBANS or _IBAN_LENGTHS.get(iban[:2]) != len(iban):
        return False
    moved = iban[4:] + iban[:4]
    try:
        return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1
    except ValueError:
        return False


def _clabe_ok(digits: str) -> bool:
    weights = (3, 7, 1) * 6
    total = sum(int(d) * weights[i] % 10 for i, d in enumerate(digits[:17]))
    return (10 - total % 10) % 10 == int(digits[17])


def _banks(line: str, base: int, ctx: Context) -> Iterable[Hit]:
    for m in _IBAN_RE.finditer(line):
        if _iban_ok(m.group(0)):
            yield Hit(BANK, base + m.start(), base + m.end())
    if ctx.speaker == "agent":
        return
    for m in _CLABE_RE.finditer(line):
        if _clabe_ok(m.group("value")):
            yield Hit(BANK, base + m.start("value"), base + m.end("value"))
    for m in _ACCOUNT_RE.finditer(line):
        digits = re.sub(r"\D", "", m.group("value"))
        if _DATE_RE.match(m.group("value").strip()):
            continue
        if 6 <= len(digits) <= 24 and len(set(digits)) >= 3 and not digits.startswith("1234567"):
            yield Hit(BANK, base + m.start("value"), base + m.end("value"), False)   # nothing to check it against


# ---- id ------------------------------------------------------------------------------------------------------------

_SSN_RE = re.compile(r"\b(?:ssn|my\s+social|social\s+security(?:\s+(?:number|no\.?|#))?)\b[^\d\n]{0,24}(?P<value>\d{3}-?\d{2}-?\d{4})\b", re.IGNORECASE)
_DNI_RE = re.compile(r"\b(?:dni|nie|nif)\b[^\w\n]{0,4}(?:\b(?:es|is|:)\b)?[^\w\n]{0,4}(?P<value>[XYZ]?\d{7,8}-?[A-Z])\b", re.IGNORECASE)
_CURP_RE = re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b")
_NAMED_ID_RE = re.compile(
    r"\b(?:pass?port(?:\s+(?:number|no\.?|#))?|pasaporte|passaporte|reisepass|"
    r"(?:my|mi)\s+(?:dpi|cui|c[eé]dula|curp|rfc|nss|nit|rut|cuil|cuit|ine)|"
    r"(?:dpi|cui|c[eé]dula(?:\s+de\s+identidad)?|curp|rfc|nss|nit|rut|cuil|cuit)"
    r"(?:\s+de\s+[\w\s]{1,24}?)?\s+(?:number|n[uú]mero|no\.?|es|is|:)|"
    r"driver'?s?\s+licen[cs]e(?:\s+(?:number|no\.?|#))?|licencia\s+de\s+conducir|tax\s+id|n[uú]mero\s+de\s+identidad|"
    r"documento\s+de\s+identidad|national\s+id(?:\s+number)?)\b"
    r"(?:\s+(?:number|n[uú]mero|no\.?|is|es|was|era|:|=)){0,3}\s*:?\s*(?P<value>[A-Z0-9][A-Z0-9 -]{4,22}[A-Z0-9])\b",
    re.IGNORECASE)
_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def _dni_ok(raw: str) -> bool:
    raw = raw.upper().replace("-", "")
    number = raw[:-1].replace("X", "0").replace("Y", "1").replace("Z", "2")
    return number.isdigit() and _DNI_LETTERS[int(number) % 23] == raw[-1]


def _ssn_ok(raw: str) -> bool:
    d = raw.replace("-", "")
    return d[:3] not in ("000", "666") and d[0] != "9" and d[3:5] != "00" and d[5:] != "0000" and d != "123456789"


def _ids(line: str, base: int, ctx: Context) -> Iterable[Hit]:
    if ctx.speaker == "agent":
        return
    for m in _SSN_RE.finditer(line):
        if _ssn_ok(m.group("value")):
            yield Hit(ID, base + m.start("value"), base + m.end("value"))
    for m in _DNI_RE.finditer(line):
        if _dni_ok(m.group("value")):
            yield Hit(ID, base + m.start("value"), base + m.end("value"))
    for m in _CURP_RE.finditer(line):
        yield Hit(ID, base + m.start(), base + m.end())
    for m in _NAMED_ID_RE.finditer(line):
        value = m.group("value")
        digits = sum(c.isdigit() for c in value)
        if (digits >= 5 and digits >= len(value.replace(" ", "").replace("-", "")) / 2 and not _year(value)
                and "12345" not in value):
            # Only the token that opens the value: a following word is a sentence going on.
            first = re.match(r"[A-Z0-9-]+(?:\s\d[\d-]*)*", value, re.IGNORECASE)
            opening = first.group(0) if first else value
            # "my passport expires 2031-05-01": a word opens it, so it is a sentence about the passport, not its number.
            if not any(c.isdigit() for c in opening.split()[0]) or _DATE_RE.match(opening):
                continue
            end = m.start("value") + (first.end() if first else len(value))
            # Nothing checks these numbers; a claim on it ("my", "mi", "number") is what there is.
            claimed = re.match(r"(?:my|mi)\s|.*\b(?:number|n[uú]mero)\b", m.group(0), re.IGNORECASE) is not None
            yield Hit(ID, base + m.start("value"), base + end, claimed)


# ---- reading a body ------------------------------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*(?:(?:user|human|assistant|ai|chatgpt|claude|system|speaker:[^:]*)\s*:\s*)?(?:```|~~~)", re.IGNORECASE)
#: Quick refusal: a line none of the families could match costs one search.
_ANY_RE = re.compile(
    rf"\d{{3,}}|{_WORD}|\b(?:sk|ghp|gho|ghu|ghs|ghr|github_pat|xox|AKIA|AIza|eyJ|glpat|npm|hf|SG|xai|gsk|pplx|rk)[-_.]|://|"
    r"PASSWORD|PASSWD|SECRET|_KEY|_TOKEN|\bapi\s+(?:key|token)|\b(?:access|auth)\s+token|\bbearer\b|\bssn\b|\bcvc|\bcvv", re.IGNORECASE)


def find_in_line(line: str, base: int, ctx: Context) -> list[Hit]:
    """Every likely value on one line; ``base`` is the line's offset in its text."""
    if ctx.speaker == "skip" or not _ANY_RE.search(line):
        return []
    hits: list[Hit] = list(_keys(line, base, ctx))
    if ctx.fenced:
        return hits                 # code and logs: vendor shapes only
    hits.extend(_cards(line, base, ctx))
    hits.extend(_banks(line, base, ctx))
    hits.extend(_ids(line, base, ctx))
    hits.extend(_passwords(line, base, ctx))
    return hits


def _dedupe(hits: list[Hit]) -> list[Hit]:
    out: list[Hit] = []
    for hit in sorted(hits, key=lambda h: (h.start, -(h.end - h.start), not h.sure, KINDS.index(h.kind))):
        if out and hit.start < out[-1].end:
            continue                # the first, longest reading of a span stands
        out.append(hit)
    return out


def find(text: str, *, harness: bool = False, override: str | None = None, gaps=()) -> list[Hit]:
    """Every likely value in ``text`` (a stored body), in order, with who said each line read from its markers."""
    if not text:
        return []
    saved = override == evidence.SAVE_KIND
    hits: list[Hit] = []
    fenced = False
    offset = 0
    if "PRIVATE KEY-----" in text and not saved:
        hits.extend(Hit(KEY, m.start(), m.end()) for m in _PEM_RE.finditer(text))
    speaker = "skip" if saved else ("agent" if override in ("assistant", evidence.AGENT_KIND) else "person")
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        marker = evidence._marker(line)
        content_at = 0
        if marker is not None:
            fenced = False           # a new turn closes whatever the last one left open
            kind = marker[0]
            content_at = marker[2]
            if not saved:
                speaker = ("agent" if kind == "assistant" or override in ("assistant", evidence.AGENT_KIND)
                           else "skip" if kind in ("media", "page", "gap") else "person")
        if _FENCE_RE.match(line):
            fenced = not fenced
        elif speaker != "skip" and not evidence.touches_gap(offset, offset + len(line), gaps):
            ctx = Context(speaker=speaker, harness=harness, fenced=fenced)
            hits.extend(find_in_line(line[content_at:], offset + content_at, ctx))
        offset += len(raw)
    return _dedupe(hits)


def find_in_episode(episode: dict, text: str | None = None) -> list[Hit]:
    """:func:`find` over a Sleep episode dict: its own record says whose words these are and whether it is a session."""
    body = episode.get("content") if text is None else text
    override = episode.get(authorship.KEY)
    harness = bool(episode.get("harness") or episode.get("capture_kind") == "transcript")
    return find(str(body or ""), harness=harness, override=override, gaps=tuple(episode.get("gaps") or ()))


def values_of(text: str, hits: Iterable[Hit]) -> tuple[str, ...]:
    """The distinct words the hits cover, longest first. In-process only: for taking them back out of what a model
    wrote and of the pages they reached. Never stored, logged or returned on any wire."""
    return tuple(sorted({text[h.start:h.end] for h in hits}, key=len, reverse=True))


def replace_hits(text: str, hits: Iterable[Hit], mark: str) -> str:
    """``text`` with each hit replaced by ``mark`` (``{kind}`` filled in). Offsets move, so never for a stored span."""
    out: list[str] = []
    at = 0
    for hit in sorted(hits, key=lambda h: h.start):
        if hit.start < at:
            continue
        out.append(text[at:hit.start])
        out.append(mark.format(kind=hit.kind))
        at = hit.end
    out.append(text[at:])
    return "".join(out)


def held_text(text: str, lo: int, hi: int, hits: Iterable[Hit]) -> str:
    """``text[lo:hi]`` as an engine reads it when these are held back. A hit across the edge of the slice is covered
    for the part inside it; a value is never cut in two with half of it left showing."""
    inside = [Hit(h.kind, max(h.start, lo) - lo, min(h.end, hi) - lo, h.sure) for h in hits if h.start < hi and h.end > lo]
    return replace_hits(text[lo:hi], inside, HELD_MARK)


# ---- by value --------------------------------------------------------------------------------------------------------

#: A line that speaks of a secret. A value that could be an ordinary word or number is only ever taken out on such a line.
_SPEAKS_RE = re.compile(
    rf"\b(?:{_WORD}|login|credentials?|pin|account|cuenta|clabe|iban|routing|passport|pasaporte|dni|dpi|cui|curp|ssn|"
    r"licen[cs]e|licencia|c[eé]dula|nit|rfc|tax\s+id)\b|\[(?:held back|removed)", re.IGNORECASE)


def distinctive(value: str) -> bool:
    """Is this exact token evidence by itself? A word (``guatemala``) or a short number is not: found elsewhere, it is
    almost surely that word. Anything mixed, or a long number, is: finding it again means finding it again."""
    v = value.strip()
    if len(v) < 6 or all(c.isalpha() for c in v):
        return False
    return not (v.isdigit() and len(v) < 8)


_patterns: dict[str, re.Pattern[str]] = {}


def _pattern(value: str) -> re.Pattern[str]:
    """Whole-token, case-sensitive, never fuzzy. Also finds a value as a JSON string writes it, and a long card or account
    number whatever separates its groups (a model reformats those; nothing else about a value is loosened)."""
    found = _patterns.get(value)
    if found is not None:
        return found
    compact = re.sub(r"[ -]", "", value)
    if len(compact) >= 12 and compact.isalnum() and sum(c.isdigit() for c in compact) * 2 >= len(compact):
        core = r"[ -]?".join(re.escape(c) for c in compact)
    else:
        spelled = {value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]}
        core = "|".join(re.escape(v) for v in sorted(spelled, key=len, reverse=True))
    found = re.compile(rf"(?<![\w])(?:{core})(?![\w])")
    if len(_patterns) > 4096:
        _patterns.clear()
    _patterns[value] = found
    return found


def holds(text: str, value: str) -> bool:
    return bool(value) and _pattern(value).search(text) is not None


def occurrences(text: str, value: str, kind: str, sure: bool = True) -> list[Hit]:
    """Every whole-token place ``value`` stands in ``text``."""
    return [Hit(kind, m.start(), m.end(), sure) for m in _pattern(value).finditer(text)]


def with_echoes(text: str, hits: Iterable[Hit]) -> list[Hit]:
    """``hits`` plus everywhere else in ``text`` the same value stands: "my password is X", then an agent's "Logged in with
    X". Only for a distinctive value: a word that was called a password stays where it was called one."""
    hits = list(hits)
    seen: dict[str, Hit] = {}
    for h in hits:
        value = text[h.start:h.end]
        if distinctive(value) and (value not in seen or (h.sure and not seen[value].sure)):
            seen[value] = h
    out = list(hits)
    for value, h in seen.items():
        out.extend(occurrences(text, value, h.kind, h.sure))
    return _dedupe(out)


def take_out(text: str, marks: dict[str, str], *, speaks: bool = False) -> tuple[str, int]:
    """``text`` with each value of ``marks`` replaced by its mark, longest first. A distinctive value goes wherever it
    stands; any other only on a line that speaks of a secret (or everywhere when the caller already knows: ``speaks``)."""
    total = 0
    for value in sorted(marks, key=len, reverse=True):
        if not value:
            continue
        mark = marks[value]
        rx = _pattern(value)
        if speaks or distinctive(value):
            text, n = rx.subn(lambda _m: mark, text)
            total += n
        elif rx.search(text):
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if _SPEAKS_RE.search(line):
                    lines[i], n = rx.subn(lambda _m: mark, line)
                    total += n
            text = "\n".join(lines)
    return text, total


def speaks_of_a_secret(text: str) -> bool:
    return _SPEAKS_RE.search(text) is not None


def strip_values(text: str, values: Iterable[str], mark: str = "[removed]") -> tuple[str, int]:
    """``text`` with each exact value, as a whole token, replaced by ``mark``: case-sensitive, never fuzzy, whatever the
    value is. For a place already known to be about that value (a conversation's own title)."""
    return take_out(text, {v: mark for v in values}, speaks=True)


def strip_in(value, values: tuple[str, ...], mark: str = "[removed]") -> tuple[object, int]:
    """A model's answer about one conversation (any shape of dict, list and str) without that conversation's ``values``.
    Whatever a value is: the model read it there, and a wrong alarm costs its word on the pages until the person leaves it
    (ruling 60). Keys stay."""
    if isinstance(value, str):
        return strip_values(value, values, mark)
    if isinstance(value, dict):
        out, total = {}, 0
        for k, v in value.items():
            out[k], n = strip_in(v, values, mark)
            total += n
        return out, total
    if isinstance(value, list):
        items, total = [], 0
        for v in value:
            item, n = strip_in(v, values, mark)
            items.append(item)
            total += n
        return items, total
    return value, 0
