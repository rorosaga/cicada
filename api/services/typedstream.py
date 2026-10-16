"""The text of a Messages ``attributedBody`` blob (G179) — pure, bounded, never raising.

Recent macOS often leaves ``message.text`` empty and keeps a message's words only in ``attributedBody``: an
``NSMutableAttributedString`` archived with ``NSArchiver``, i.e. Apple's old *typedstream* format (measured on the
owner's conversation: 208 of 907 rows, about 23 %). The app reads the bytes (it holds Full Disk Access) and posts them;
this module, on the backend, decodes them — the Awake rail ("the app reads ``~/Library``, the backend parses bytes"),
one decoder for every client, and one that runs headless and under test. ``NSUnarchiver`` in the app was the other
choice: it is deprecated, it instantiates whatever classes a blob names (an attack surface for a file another
process writes), and it would put a second parser beside the Python one the tests pin.

The shape, as ``NSArchiver`` writes it on macOS 26 (``api/tests/fixtures/imessage_attributed_bodies.json`` holds
blobs built that way): a ``\\x04\\x0bstreamtyped`` header and a version, the root object's class chain
(``NSMutableAttributedString`` → ``NSAttributedString`` → ``NSObject``), then the string object — class
``NSMutableString``/``NSString`` — whose characters follow as one typed ``+`` (bytes) value: the type tag
``\\x84\\x01+``, a length, then that many UTF-8 bytes. A length below 0x80 is one byte; ``\\x81`` prefixes a
little-endian int16 and ``\\x82`` an int32 (measured at 128 and 40,000 characters). The attribute runs and the
dictionaries after it are skipped: only the words cross.

Not a general typedstream reader — the first string object's bytes are all Messages keeps a message's words in.
"""

from __future__ import annotations

HEADER = b"\x04\x0bstreamtyped"
#: The string object's class names, newest first; the first one found after the header opens the string object.
_STRING_CLASSES = (b"NSMutableString", b"NSString")
#: A newly declared type string of one character, ``+`` — a C byte string.
_BYTES_TAG = b"\x84\x01+"
#: A blob larger than this is not a message (an attachment's payload would be elsewhere); refused unread.
MAX_BLOB_BYTES = 4_000_000
OBJECT_REPLACEMENT = "￼"


def _length(blob: bytes, at: int) -> tuple[int, int] | None:
    """``(length, first byte after it)`` for the typedstream integer at ``at``, or ``None``."""
    if at >= len(blob):
        return None
    tag = blob[at]
    if tag == 0x81:
        raw = blob[at + 1:at + 3]
        return (int.from_bytes(raw, "little", signed=False), at + 3) if len(raw) == 2 else None
    if tag == 0x82:
        raw = blob[at + 1:at + 5]
        return (int.from_bytes(raw, "little", signed=False), at + 5) if len(raw) == 4 else None
    if tag < 0x80:
        return tag, at + 1
    return None


def decode(blob: bytes | bytearray | memoryview | None) -> str | None:
    """The message's words, or ``None`` when ``blob`` is not an archived string this module can read.

    The words come back as stored — U+FFFC object-replacement characters included (an attachment's place in the
    text); :func:`visible_text` removes them."""
    if not blob:
        return None
    data = bytes(blob)
    if len(data) > MAX_BLOB_BYTES or not data.startswith(HEADER):
        return None
    starts = [i for i in (data.find(name, len(HEADER)) for name in _STRING_CLASSES) if i >= 0]
    if not starts:
        return None
    tag = data.find(_BYTES_TAG, min(starts))
    if tag < 0:
        return None
    found = _length(data, tag + len(_BYTES_TAG))
    if found is None:
        return None
    size, begin = found
    raw = data[begin:begin + size]
    if len(raw) != size:
        return None
    return raw.decode("utf-8", errors="replace")


def visible_text(text: str | None) -> str:
    """``text`` without the attachment placeholders, trimmed — what a person sees as the message's words."""
    return (text or "").replace(OBJECT_REPLACEMENT, "").strip()
