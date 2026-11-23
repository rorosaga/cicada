"""Meeting transcripts from a watched folder — Hex, any recorder's export, a folder of transcripts (G95, 2026-11-03).

A meeting folder is a G133 watched folder of ``kind: meetings``: the APP holds its bookmark, watches it and posts the
bytes of changed files (the backend never opens it); this module is the one parser — pure, fixture-tested — that turns
one posted file into one meeting episode through the G20 stager (``episode_staging``): the same bytes skip, an edited
transcript is rewritten in place and re-queued, a renamed file keeps its episode by content hash, a deleted one is
tombstoned. Every body is scrubbed by the stager (R-N3).

Owner, 2026-11-03: "Meetings ofc should also be consolidated in memory." A meeting transcript is an episode Sleep
reads like any conversation (``queue_for_sleep``) — unlike a recording the person adds as a media file
(``media_files``), whose words stay outside every bank and are never read by Sleep.

Whose words (ruling 52a, decided 2026-11-03 under the meetings ruling): a line the recorder labels as the person's own
— ``You`` (Hex's microphone track; its docs: "You (microphone)", "Them (system audio)") or ``Me``, the same
convention in other recorders' exports — is a ``user:`` line, the person's own words, counted for promotion like any
turn of theirs. Every other utterance is ``speaker:<label>: text`` (evidence kind ``speaker``, G134's seam) — someone
else in the meeting, never the person (``Them`` is ``speaker:them``); a line with no speaker is ``speaker:unknown``,
never the person's. A recorder's model-written summary is an ``assistant:`` line, never the person's words and never
an exchange. Nothing in a meeting body is unmarked, so R4's default never credits the person with an unlabelled line.
A name is never guessed to be the person's: only those two labels.

Formats read (by content, never by trusting the extension alone):

* **Hex** (anoma.ly/hex, MIT): ``<folder>/<YYYY-MM-DD HHMM> <title>.md`` — ``# title``, ``- **Date:**`` /
  ``- **Duration:**`` (and ``- **Attendees:**`` from a calendar) bullets, an optional ``<!-- hex:notes -->`` summary
  block, then ``## Transcript`` with ``**You** · 00:00`` / ``**Them** · 00:05`` headers and the words beneath; the
  older ``**[mm:ss] You:** text`` lines too. The file name's time is local wall time, read in the zone the app posts.
* **WebVTT / SRT** subtitles: cue times, a ``<v Name>`` voice tag or a ``Name:`` prefix; same-speaker cues merge.
* **JSON**: a list of segments, or ``segments`` / ``utterances`` / ``transcript`` / ``results`` holding one —
  ``text``, an optional speaker (``speaker``, ``speaker_label``, ``name``, ``source``) and start (seconds, or ``*_ms``).
* **Text / Markdown**: ``Name: text``, ``[00:01:02] Name: text``, ``Name (00:01:02): text``, ``**Name:** text``, and a
  ``Name  0:00`` header line over its words (Otter's export). A file with no speaker grammar is one unknown speaker
  per paragraph.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from api.services import episode_ids, when
from api.services.episode_staging import EpisodeDraft, Turn
from api.services.id_utils import sanitize_id

KIND = "meetings"
SOURCE_PREFIX = "meetings:"
WRITER = "meeting-transcript"
#: What a meeting folder reads by default — the transcript formats the module parses, never audio.
DEFAULT_INCLUDE = ("**/*.md", "**/*.markdown", "**/*.txt", "**/*.vtt", "**/*.srt", "**/*.json")
#: Hex keeps a per-meeting bundle under ``audio/`` beside its Markdown (WAVs, ``manifest.json``, duplicate transcripts
#: and translations): the Markdown copy is the meeting, so the bundle is never read.
RECORDER_EXCLUDE = {"hex": ("audio/**",)}
#: The recorders a meeting folder can be set up for, as the app names them. ``None`` is a plain folder of transcripts.
RECORDERS = {"hex": "Hex"}
#: The labels a recorder gives the person's own lines (ruling 52a): Hex's ``You``, and ``Me`` — the same convention in
#: other recorders' exports. Compared case-folded; nothing else, never a name, is ever read as the person.
OWN_LABELS = frozenset({"you", "me"})
UNKNOWN = "unknown"
MAX_TURNS = 5000
MAX_LABELS = 40
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"
_HEX_HEADER = re.compile(rf"^\*\*(?P<label>[^*\n]{{1,64}}?)\*\*\s*[·•|-]\s*(?P<t>{_TIME})\s*$")
_HEX_INLINE = re.compile(rf"^\*\*\[(?P<t>{_TIME})\]\s+(?P<label>[^*:\n]{{1,64}}?):\*\*\s*(?P<text>.*)$")
_BOLD_TIMED = re.compile(rf"^\*\*(?P<t>{_TIME})\s+(?P<label>[^*\n]{{1,64}}?)\*\*\s*(?P<text>.*)$")
_TIMED_LABEL = re.compile(rf"^\[?(?P<t>{_TIME})\]?\s*[-–]?\s*(?P<label>[^:\[\]\n]{{1,48}}?):\s+(?P<text>.+)$")
_LABEL_TIMED = re.compile(rf"^(?P<label>[^:\n(\[]{{1,48}}?)\s*[(\[](?P<t>{_TIME})[)\]]\s*:\s*(?P<text>.*)$")
_BOLD_LABEL = re.compile(r"^\*\*(?P<label>[^*\n]{1,48}?):?\*\*:?\s+(?P<text>.+)$")
_PLAIN_LABEL = re.compile(r"^(?P<label>[A-Z0-9][^:\n]{0,47}?):\s+(?P<text>.+)$")
_HEADER_ONLY = re.compile(rf"^(?:\*\*)?(?P<label>[^*\n]{{1,48}}?)(?:\*\*)?(?:\s{{2,}}|\s*[·•|]\s*)(?P<t>{_TIME})\s*$")
_CUE_TIME = re.compile(r"^(?P<a>(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<b>(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})")
_VOICE = re.compile(r"<v(?:\.[^\s>]+)*\s+([^>]+)>")
_TAG = re.compile(r"<[^>]+>")
_META = re.compile(r"^(?:[-*]\s+)?(?:\*\*)?(?P<key>Date|When|Duration|Length|App|Attendees|Participants)(?:\*\*)?"
                   r"\s*:\s*(?:\*\*)?\s*(?P<value>.+?)\s*$", re.IGNORECASE)
_FILE_STAMP = re.compile(r"^(?P<d>\d{4}-\d{2}-\d{2})(?:[ T_]+(?P<h>\d{2})[:.\-h]?(?P<m>\d{2}))?(?:\s+|[-_]\s*|$)")
#: Words that are a section heading or a field name, never a speaker (``Summary: …`` in a notes block).
_NOT_SPEAKERS = frozenset({"summary", "notes", "note", "action items", "decisions", "agenda", "date", "duration",
                           "attendees", "participants", "app", "title", "transcript", "http", "https", "tl;dr"})


@dataclass
class Line:
    label: str
    text: str
    offset: float | None = None


@dataclass
class Transcript:
    format: str
    title: str = ""
    lines: list[Line] = field(default_factory=list)
    summary: str = ""
    summary_writer: str = ""
    date_text: str = ""
    duration_s: int | None = None
    attendees: list[str] = field(default_factory=list)
    app: str = ""
    #: Italic lines a recorder or a tool left between the heading and the first speaker (``_Remote speakers split on
    #: this Mac with … (2 voices)._``): metadata about the recording, never a turn and never anyone's words.
    notes: list[str] = field(default_factory=list)
    #: What a note says split the remote voices, and into how many — from the note's own words (:func:`_voices_note`).
    voices_split_by: str = ""
    voices: int | None = None


# --- Small readers -------------------------------------------------------------------------------------------------


def _seconds(stamp: str | None) -> float | None:
    """``01:02:03.5`` / ``02:03`` / ``2:03,500`` as seconds."""
    if not stamp:
        return None
    parts = stamp.replace(",", ".").split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def _offset_text(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def clean_label(raw) -> str:
    """A speaker's label as the recorder wrote it: one line, no email, at most 64 characters."""
    label = " ".join(_TAG.sub("", "" if raw is None else str(raw)).split()).strip(" *:[]")[:64]
    return "" if _EMAIL_RE.search(label) else label


def is_own(label: str) -> bool:
    """Whether the recorder labelled the line as the person's own (:data:`OWN_LABELS`, ruling 52a)."""
    return bool(label) and label.strip().casefold() in OWN_LABELS


#: A label a recorder or a diarizer gives someone it could not name (ROR-142): Hex's ``Them`` (everything the call's
#: audio carried), ``Speaker 1``/``SPEAKER_00``/``Speaker A`` from a diarizer, Otter's ``Unknown Speaker``, ``Guest 3``,
#: AssemblyAI's bare ``A``, a numbered JSON speaker, and the Spanish words a Spanish recorder writes (``Hablante 1``). A
#: role word alone or followed by one number or one separated letter, matched whole, so a name that merely contains one
#: never is.
_PLACEHOLDER = re.compile(
    r"(?:(?:them|others?|other (?:side|speaker)|remote|caller|(?:unknown|unidentified|unnamed) speaker|unknown"
    r"|unidentified|unnamed|speaker|spk|guest|participant|attendee|person|voice"
    r"|hablante|orador|oradora|desconocid[oa]|invitad[oa]|participante|interlocutora?|otra persona|otros)"
    r"(?:[\s_-]*\d{1,3}|[\s_-]+[a-z])?|[A-Z]|\d{1,3})", re.IGNORECASE)
#: The placeholders that may stand for several people at once — one recorder track, not one voice.
_GROUP_PLACEHOLDERS = frozenset({"them", "others", "other", "other side", "remote", "otros"})


def is_placeholder(label: str) -> bool:
    """Whether ``label`` is a stand-in for an unnamed speaker rather than a name (ROR-142)."""
    return bool(label) and not is_own(label) and _PLACEHOLDER.fullmatch(" ".join(label.split())) is not None


def is_group_placeholder(label: str) -> bool:
    """A placeholder that names a recording track, so its lines may be several different people (Hex's ``Them``)."""
    return is_placeholder(label) and " ".join(label.split()).casefold() in _GROUP_PLACEHOLDERS


def marker(label: str) -> str:
    """``user`` for a line the recorder labels as the person's own (``You``/``Me``), else ``speaker:<slug>`` — never
    containing ``:`` so ``evidence._SPEAKER_RE`` reads it back."""
    if is_own(label):
        return "user"
    slug = sanitize_id(label)[:48].strip("-") if label else ""
    return f"speaker:{slug if slug and slug != 'unnamed' else UNKNOWN}"


def _names(value: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[,;]| and ", value or ""):
        name = clean_label(raw)
        if name and name not in out:
            out.append(name)
    return out[:MAX_LABELS]


def _duration(value: str) -> int | None:
    value = (value or "").strip()
    if re.fullmatch(_TIME, value):
        secs = _seconds(value)
        return int(secs) if secs is not None else None
    hours = re.search(r"(\d+)\s*h", value)
    minutes = re.search(r"(\d+)\s*m", value)
    seconds = re.search(r"(\d+)\s*s\b", value)
    if not (hours or minutes or seconds):
        return None
    return sum(int(m.group(1)) * k for m, k in ((hours, 3600), (minutes, 60), (seconds, 1)) if m)


#: A line that is only an HTML comment (``<!-- hex-speakers -->``, ``<!-- hex:notes -->``): a marker for a tool, never words.
_COMMENT_LINE = re.compile(r"^(?:<!--.*?-->\s*)+$")
#: An italic-only line (``_note_`` or ``*note*``) — how a recorder and the tools around it write a note about the file.
_ITALIC_LINE = re.compile(r"^(?:_(?P<u>[^_].*?)_|\*(?P<s>[^*].*?)\*)$")
#: "… split on this Mac with <tool> (N voices)": which tool told the voices apart and how many it found. The tool is
#: read from the sentence, never matched by name.
_VOICES_NOTE = re.compile(r"\bsplit\b.*?\bwith\s+(?P<tool>[^()]{2,80}?)\s*\((?P<n>\d{1,3})\s+(?:voices?|speakers?)\)", re.IGNORECASE)
MAX_NOTES = 5


def _note_text(value: str) -> str:
    """A note as kept: one line, 240 characters, and without any sentence holding a code span (a command to run, which
    carries ids and paths: "Rename with `…`.")."""
    kept = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(value.split())) if "`" not in s]
    return " ".join(kept)[:240].strip(" _*")


def _voices_note(t: "Transcript", note: str) -> None:
    m = _VOICES_NOTE.search(note)
    if m and not t.voices_split_by:
        t.voices_split_by = " ".join(m.group("tool").split())[:80]
        t.voices = int(m.group("n"))


def _append(lines: list[Line], label: str, text: str, offset: float | None) -> None:
    text = " ".join(text.split())
    if not text:
        return
    lines.append(Line(label, text, offset))


def _meta(t: Transcript, line: str) -> bool:
    m = _META.match(line)
    if not m:
        return False
    key, value = m.group("key").lower(), m.group("value").strip()
    if key in ("date", "when"):
        t.date_text = value
    elif key in ("duration", "length"):
        t.duration_s = _duration(value)
    elif key == "app":
        t.app = " ".join(value.split())[:64]
    else:
        t.attendees = _names(value)
    return True


# --- Formats -------------------------------------------------------------------------------------------------------


def _parse_cues(text: str, fmt: str) -> Transcript:
    """WebVTT or SRT: one turn per run of same-speaker cues, timed by its first cue."""
    t = Transcript(format=fmt)
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        rows = [r.strip() for r in block.strip().split("\n") if r.strip()]
        timing = next((i for i, r in enumerate(rows) if _CUE_TIME.match(r)), None)
        if timing is None:
            continue
        start = _seconds(_CUE_TIME.match(rows[timing]).group("a"))
        words = " ".join(rows[timing + 1:])
        label = ""
        voice = _VOICE.search(words)
        if voice:
            label = clean_label(voice.group(1))
        words = " ".join(_TAG.sub("", words).split())
        if not label:
            m = _PLAIN_LABEL.match(words) or _BOLD_LABEL.match(words)
            if m and m.group("label").strip().lower() not in _NOT_SPEAKERS:
                label, words = clean_label(m.group("label")), m.group("text")
            elif words.startswith("[") and "]" in words[:50]:
                label, words = clean_label(words[1:words.index("]")]), words[words.index("]") + 1:]
        if not words.strip():
            continue
        if t.lines and t.lines[-1].label == label:
            t.lines[-1].text = f"{t.lines[-1].text} {' '.join(words.split())}"
        else:
            _append(t.lines, label, words, start)
    return t


_JSON_TEXT = ("text", "content", "transcript", "words_text", "utterance")
_JSON_SPEAKER = ("speaker", "speaker_label", "speakerLabel", "speaker_name", "speakerName", "name", "source", "role")
_JSON_START = ("start", "start_time", "startTime", "start_ms", "startMs", "offset", "timestamp")
_JSON_LISTS = ("segments", "utterances", "transcript", "results", "entries", "turns", "items")


def _segments(data) -> list | None:
    if isinstance(data, list):
        return data if any(isinstance(x, dict) for x in data) else None
    if isinstance(data, dict):
        for key in _JSON_LISTS:
            found = _segments(data.get(key))
            if found:
                return found
    return None


def _parse_json(text: str) -> Transcript | None:
    try:
        data = json.loads(text)
    except ValueError:
        # One JSON object per line (Hex's own transcript.ndjson, if someone points a folder at it).
        rows = []
        for raw in text.splitlines():
            raw = raw.strip()
            if raw.startswith("{"):
                try:
                    rows.append(json.loads(raw))
                except ValueError:
                    return None
        data = rows or None
    segments = _segments(data)
    if not segments:
        return None
    t = Transcript(format="json")
    if isinstance(data, dict):
        t.title = " ".join(str(data.get("title") or "").split())[:200]
    for seg in segments[:MAX_TURNS]:
        if not isinstance(seg, dict):
            continue
        words = next((seg[k] for k in _JSON_TEXT if isinstance(seg.get(k), str) and seg[k].strip()), "")
        if not words:
            continue
        raw_speaker = next((seg[k] for k in _JSON_SPEAKER if seg.get(k) not in (None, "")), "")
        if isinstance(raw_speaker, dict):
            raw_speaker = raw_speaker.get("name") or raw_speaker.get("source") or raw_speaker.get("id") or ""
        label = clean_label(raw_speaker)
        start = None
        for k in _JSON_START:
            v = seg.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                start = v / 1000 if k.lower().endswith("ms") else float(v)
                break
            if isinstance(v, str) and re.fullmatch(_TIME, v.strip()):
                start = _seconds(v.strip())
                break
        if t.lines and t.lines[-1].label == label:
            t.lines[-1].text = f"{t.lines[-1].text} {' '.join(words.split())}"
        else:
            _append(t.lines, label, words, start)
    return t if t.lines else None


def _speaker_line(line: str, *, plain: bool) -> tuple[str, str, float | None] | None:
    """``(label, text, offset)`` when ``line`` opens a turn with its words on the same line."""
    for pattern in (_HEX_INLINE, _BOLD_TIMED, _TIMED_LABEL, _LABEL_TIMED, _BOLD_LABEL) + ((_PLAIN_LABEL,) if plain else ()):
        m = pattern.match(line)
        if m and m.group("label").strip().lower() not in _NOT_SPEAKERS and not m.group("label").strip().isdigit():
            return clean_label(m.group("label")), m.group("text"), _seconds(m.groupdict().get("t"))
    return None


def _header_line(line: str) -> tuple[str, float | None] | None:
    """``(label, offset)`` when ``line`` is a speaker header whose words follow (Hex ``**You** · 00:00``, Otter)."""
    m = _HEX_HEADER.match(line) or _HEADER_ONLY.match(line)
    if not m or m.group("label").strip().lower() in _NOT_SPEAKERS:
        return None
    return clean_label(m.group("label")), _seconds(m.group("t"))


def _parse_text(text: str) -> Transcript:
    """Markdown or plain text — Hex's export, any ``Name: words`` transcript, else paragraphs."""
    t = Transcript(format="text")
    body = text.replace("\r\n", "\n")
    if "<!-- hex:notes -->" in body or re.search(r"^## Transcript\s*$", body, re.MULTILINE) and _HEX_HEADER.search(
            body.split("## Transcript", 1)[-1].lstrip().split("\n", 1)[0]):
        t.format = "hex"
    notes = re.search(r"<!-- hex:notes -->(.*?)<!-- /hex:notes -->", body, re.DOTALL)
    if notes:
        block = notes.group(1)
        writer = re.search(r"^_(.+)_\s*$", block, re.MULTILINE)
        t.summary_writer = " ".join(writer.group(1).split())[:200] if writer else ""
        kept = [ln for ln in block.split("\n") if ln.strip() and not ln.startswith("#") and not re.match(r"^_.+_\s*$", ln)]
        t.summary = "\n".join(ln.strip() for ln in kept).strip()
        body = body[:notes.start()] + body[notes.end():]
    rows = body.split("\n")
    # A plain "Name: words" line is a speaker only in a file where several lines say so — a note's "Next step: …"
    # is not a meeting.
    plain_hits = [m.group("label") for r in rows if (m := _PLAIN_LABEL.match(r.strip()))
                  and m.group("label").strip().lower() not in _NOT_SPEAKERS and not _META.match(r.strip())]
    plain = len(plain_hits) >= 3 and len(set(plain_hits)) <= 12
    current: Line | None = None
    in_turns = False
    preamble: list[str] = []
    for raw in rows:
        line = raw.strip()
        if not line:
            # A paragraph that opens no turn goes back to the speaker before it (`evidence.turns`' own rule).
            continue
        if _COMMENT_LINE.match(line):
            continue   # a tool's marker, never words — whether or not a turn is open
        if line.startswith("# ") and not t.title and not in_turns:
            t.title = line[2:].strip()
            continue
        if not in_turns and _meta(t, line):
            continue
        if re.match(r"^#{2,6}\s", line):
            current = None
            continue
        head = _header_line(line)
        if head is not None:
            current = Line(head[0], "", head[1])
            t.lines.append(current)
            in_turns = True
            continue
        spoke = _speaker_line(line, plain=plain)
        if spoke is not None:
            current = Line(spoke[0], " ".join(spoke[1].split()), spoke[2])
            t.lines.append(current)
            in_turns = True
            continue
        if current is not None:
            current.text = f"{current.text} {line}".strip()
        elif not in_turns:
            preamble.append(line)
        else:
            current = Line("", line, None)
            t.lines.append(current)
    t.lines = [ln for ln in t.lines if ln.text.strip()]
    if t.lines:
        # Before the first speaker, an italic line is a note about the recording (a tool that split the voices, the
        # recorder's own remark), not a turn: metadata, never anyone's words. With no speaker at all the preamble is
        # the file's only text and stays so.
        rest = []
        for ln in preamble:
            m = _ITALIC_LINE.match(ln)
            note = _note_text(m.group("u") or m.group("s")) if m else ""
            if m and note:
                if len(t.notes) < MAX_NOTES:
                    t.notes.append(note)
                _voices_note(t, m.group("u") or m.group("s"))
            elif not m:
                rest.append(ln)
        preamble = rest
    if not t.lines and preamble:
        # No speaker grammar at all: each paragraph is one unknown speaker's — never the person's own words.
        for para in re.split(r"\n\s*\n", body):
            kept = [r for r in para.split("\n") if r.strip() and not r.startswith("#") and not _META.match(r.strip())
                    and not _COMMENT_LINE.match(r.strip())]
            _append(t.lines, "", " ".join(kept), None)
    elif preamble:
        t.lines.insert(0, Line("", " ".join(preamble)))
    if t.title:
        t.title = re.sub(r"\s+[—–-]\s+\d{4}-\d{2}-\d{2}.*$", "", t.title).strip()
    return t


def parse(text: str, relpath: str) -> Transcript | None:
    """The transcript a file holds, or ``None`` when it holds none (an empty file, a JSON that is not a transcript)."""
    text = (text or "").lstrip("﻿")
    if not text.strip():
        return None
    lower = relpath.lower()
    head = text.lstrip()[:16]
    if head.startswith("WEBVTT") or lower.endswith(".vtt"):
        t = _parse_cues(text, "webvtt")
    elif lower.endswith(".srt") or _CUE_TIME.search(text[:400] or ""):
        t = _parse_cues(text, "srt")
    elif lower.endswith((".json", ".ndjson")) or head[:1] in ("{", "["):
        t = _parse_json(text)
    else:
        t = _parse_text(text)
    if t is None or not t.lines:
        return None
    t.lines = t.lines[:MAX_TURNS]
    return t


# --- Dates ---------------------------------------------------------------------------------------------------------


_DATE_FORMATS = ("%A, %B %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p", "%A, %B %d, %Y at %I:%M %p",
                 "%B %d, %Y at %I:%M %p", "%A, %B %d, %Y", "%B %d, %Y", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
                 "%d/%m/%Y %H:%M", "%Y-%m-%d")


def _from_name(relpath: str) -> tuple[datetime | None, bool]:
    """The local moment a file name starts with (``2026-11-03 1601 Title.md``) and whether it carried a time."""
    name = relpath.rsplit("/", 1)[-1]
    m = _FILE_STAMP.match(name)
    if not m:
        return None, False
    try:
        day = date.fromisoformat(m.group("d"))
        if m.group("h") and m.group("m"):
            return datetime(day.year, day.month, day.day, int(m.group("h")), int(m.group("m"))), True
        return datetime(day.year, day.month, day.day), False
    except ValueError:
        return None, False


def file_key(relpath: str) -> str | None:
    """The recorder's stamp a file's name starts with — ``YYYY-MM-DD HH:MM``, the date AND the time — or ``None`` when
    the name carries no time (a date alone never names a meeting). ``1601``, ``16.01`` and ``T1601`` are one key: it is
    the moment ``_from_name`` reads, not the spelling. Two files of one folder with one key are copies of one meeting
    (G104 slice 3): a recorder's corrected export lands as a new file with the same stamp."""
    moment, timed = _from_name(relpath)
    return moment.strftime("%Y-%m-%d %H:%M") if moment is not None and timed else None


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
#: How many other copies of a meeting an episode remembers (`episode_staging.MAX_REPLACED`).
MAX_REPLACED = 20


def mtime_us(iso: str | None) -> int:
    """A file time as whole microseconds since the epoch — the precision ``episode_ids.to_utc_iso`` keeps — so a time
    posted as a float and the same time read back from the episode's frontmatter compare equal. ``0`` when unreadable."""
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - _EPOCH) // timedelta(microseconds=1)


@dataclass(frozen=True)
class FileRec:
    """One copy of a meeting's file as the episode records it: where, which bytes, when it was last modified (UTC ISO)."""
    rel: str
    sha: str
    mtime: str

    @property
    def order(self) -> tuple[int, str]:
        """Newest first: the time, the path only as the tie-break."""
        return mtime_us(self.mtime), self.rel

    def as_dict(self) -> dict:
        return {"relpath": self.rel, "content_sha": self.sha, "mtime": self.mtime}

    @classmethod
    def from_dict(cls, raw) -> "FileRec | None":
        if not isinstance(raw, dict) or not raw.get("relpath") or not raw.get("content_sha"):
            return None
        return cls(str(raw["relpath"]), str(raw["content_sha"]), str(raw.get("mtime") or ""))


def newest(files) -> "FileRec | None":
    return max(files, key=lambda f: f.order, default=None)


def winner(posted: list[FileRec], held: "FileRec | None", replaced: list[FileRec]) -> "FileRec | None":
    """Which copy of one meeting the episode holds: the newest, by ``(mtime, relpath)``.

    ``posted`` are the copies in this batch, ``held`` the file the episode holds now (``None`` when it is gone or was
    deleted in this batch), ``replaced`` the copies it already knows. While the held file stands, a copy whose
    ``(relpath, sha)`` is already in ``replaced`` never wins again whatever its mtime — a rescan after the app lost its
    manifest, or a sync tool that touched the old file, must not turn a correction back into the words it replaced;
    only the same path with CHANGED bytes (the person edited it) can win, by the same rule. With no held file there is
    nothing to turn back: every posted copy competes. The held file's own path, posted again, stands for the held file
    (its bytes are the ones that count)."""
    barred = {(r.rel, r.sha) for r in replaced} if held is not None else set()
    pool = [p for p in posted if (p.rel, p.sha) not in barred]
    if held is not None and all(p.rel != held.rel for p in posted):
        pool.append(held)
    return newest(pool)


def record(replaced: list[FileRec], losers: list[FileRec], chosen: "FileRec | None",
           dropped=()) -> list[FileRec]:
    """The copies an episode remembers after a batch: what it knew, plus the copies that lost, minus the one it holds
    now and any path deleted. A copy already known with the same bytes keeps its recorded time (a touch never
    rewrites a record); the newest :data:`MAX_REPLACED` stay."""
    known = {r.rel: r for r in replaced}
    for lost in losers:
        if lost.rel not in known or known[lost.rel].sha != lost.sha:
            known[lost.rel] = lost
    for rel in (chosen.rel if chosen is not None else None, *dropped):
        known.pop(rel, None)
    return sorted(known.values(), key=lambda r: r.order, reverse=True)[:MAX_REPLACED]


def _from_text(value: str) -> tuple[datetime | None, bool]:
    value = " ".join((value or "").split())
    if not value:
        return None, False
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return moment, len(value) > 10
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt), "%H" in fmt or "%I" in fmt
        except ValueError:
            continue
    return None, False


def started_at(t: Transcript, relpath: str, tz_name: str | None, mtime_iso: str | None = None) -> datetime | None:
    """When the meeting began, aware, from the file's own record: its name's time, its Date line, then either's day.
    ``None`` when neither says (the caller falls back to the file's time). Naive moments are the person's wall time,
    read in the zone the app posted (``tz_name``), else this machine's. A day with no time is the file's own time when
    that falls on the same day (a transcript is saved as its meeting ends), else that day's midday — never its
    midnight, which a reader in another zone would show as the day before."""
    by_name, name_timed = _from_name(relpath)
    by_text, text_timed = _from_text(t.date_text)
    timed = [m for m, has_time in ((by_name, name_timed), (by_text, text_timed)) if m is not None and has_time]
    moment = (timed or [m for m in (by_name, by_text) if m is not None] or [None])[0]
    if moment is None:
        return None
    # A posted zone this machine cannot read (a typo, a directory of the zone database) is this machine's zone instead.
    known = tz_name if tz_name and episode_ids.zone_offset_minutes(tz_name) is not None else None
    zone = moment.tzinfo or when.zone(known or _machine_zone())
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    if not timed:
        saved = None
        try:
            saved = datetime.fromisoformat(str(mtime_iso).replace("Z", "+00:00")).astimezone(zone) if mtime_iso else None
        except ValueError:
            saved = None
        moment = saved if saved is not None and saved.date() == moment.date() else moment.replace(hour=12, minute=0)
    return moment


def _machine_zone() -> str | None:
    from api.services import handshake

    return handshake.local_timezone()


# --- The draft -----------------------------------------------------------------------------------------------------


def source_id(folder_id: str, relpath: str) -> str:
    return f"{SOURCE_PREFIX}{folder_id}:{relpath}"


def _title(t: Transcript, relpath: str) -> str:
    if t.title:
        return " ".join(t.title.split())[:200]
    stem = relpath.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = _FILE_STAMP.sub("", stem).strip(" -_") or stem
    return " ".join(stem.split())[:200] or "Meeting"


def summary_text(summary: str, who: str, *, heading: str | None = None) -> str:
    """The recorder's summary as one ``assistant:`` turn's text, every line of it quoted (``> ``, the chat importer's
    attachment convention), so no line of the model's text can open a turn: a summary line reading ``User: …`` or
    ``speaker:x: …`` would otherwise be read back as the person's words, or another speaker's (`evidence.turns`).
    ``heading`` replaces ``Summary (written by <who>)`` (Wispr Flow's ``Notes (Wispr Flow)`` block)."""
    lines = [line.rstrip() for line in summary.replace("\r\n", "\n").split("\n")]
    quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in lines).strip("\n")
    return f"{heading or f'Summary (written by {who})'}\n{quoted}"


def draft_for_file(folder: dict, relpath: str, text: str, *, mtime_iso: str, sha: str,
                   tz_name: str | None = None, speaker_names: dict[str, str] | None = None) -> EpisodeDraft | None:
    """One meeting file as one episode, or ``None`` when the file holds no transcript.

    ``speaker_names`` (ROR-142): the person's answers for this file, placeholder label → name
    (``meeting_speakers.names_for``), applied before any marker is made, so a re-sync renders the body they named."""
    t = parse(text, relpath)
    if t is None:
        return None
    named = {label: name for label, name in (speaker_names or {}).items()
             if name and is_placeholder(label) and any(line.label == label for line in t.lines)}
    for line in t.lines:
        line.label = named.get(line.label, line.label)
    recorder = folder.get("recorder") if folder.get("recorder") in RECORDERS else None
    if t.format == "hex":
        recorder = "hex"
    start = started_at(t, relpath, tz_name, mtime_iso)
    # A turn's absolute time only from a start the file states to the minute; a day alone keeps the offsets.
    timed = start is not None and (_from_name(relpath)[1] or _from_text(t.date_text)[1])
    stamp = episode_ids.to_utc_iso(start) if start is not None else mtime_iso
    if start is not None:
        day = start.date().isoformat()   # ruling 34: the meeting's own local day
    else:
        day = episode_ids.id_day(stamp, utc_offset_minutes=episode_ids.zone_offset_minutes(tz_name))
    turns: list[Turn] = []
    if t.summary:
        who = RECORDERS.get(recorder or "", "the recorder")
        turns.append(Turn(summary_text(t.summary, who), "assistant"))
    labels: list[str] = []
    for line in t.lines:
        if line.label and line.label not in labels and len(labels) < MAX_LABELS:
            labels.append(line.label)
        ts = (episode_ids.to_utc_iso(start + timedelta(seconds=line.offset))
              if timed and line.offset is not None else _offset_text(line.offset))
        turns.append(Turn(line.text, marker(line.label), ts))
    meeting = {"recorder": recorder, "format": t.format, "speakers": labels}
    own = [label for label in labels if is_own(label)]
    if own:
        # Ruling 52a: the labels whose lines were written as the person's own (`user:`), so a reader can say why.
        meeting["own_labels"] = own
    if t.duration_s is not None:
        meeting["duration_s"] = t.duration_s
    if t.app:
        meeting["app"] = t.app
    if t.summary_writer:
        meeting["summary_writer"] = t.summary_writer
    if t.notes:
        meeting["notes"] = list(t.notes)
    if t.voices_split_by:
        meeting["voices_split_by"] = t.voices_split_by
        meeting["voices"] = t.voices
    if named:
        # ROR-142: the placeholders the person named, so a reader can say where each name came from.
        meeting["named_by_person"] = dict(named)
    if t.attendees:
        # A calendar's invitees as the file lists them — inside the meeting record, never ``participants`` (G179's
        # ``[{key, marker, name, kind}]`` rows for a chat's members, a shape these plain names are not).
        meeting["attendees"] = t.attendees
    return EpisodeDraft(
        title=_title(t, relpath), source_id=source_id(folder["id"], relpath),
        source_updated_at=mtime_iso, timestamp=stamp, original_date=day, source="folder", origin="folder",
        turns=turns, redate=start is not None, content_sha=sha, writer=WRITER,
        extra={"folder_id": folder["id"], "relpath": relpath, "folder_kind": KIND, "meeting": meeting,
               "consent": "unknown"},
    )


def is_meeting(fm: dict | None) -> bool:
    """A meeting episode, by its own record."""
    return isinstance(fm, dict) and fm.get("folder_kind") == KIND and isinstance(fm.get("meeting"), dict)


# --- The reader (derived on read, never stored) ----------------------------------------------------------------------

#: What a speaker line is, for the app to say in words: ``named`` — a name (the recorder's, or the person's own answer,
#: ROR-142); ``numbered`` — a diarized voice or a numbered guest (``Speaker 1``); ``group`` — a track that may hold
#: several people (Hex's ``Them``); ``unknown`` — nothing says who.
NAMED, NUMBERED, GROUP, UNKNOWN_KIND = "named", "numbered", "group", "unknown"
_NUMBERED = re.compile(r"(?P<role>[^\d]{2,}?)[\s_-]*(?P<n>\d{1,3}|(?<=[\s_-])[a-z])", re.IGNORECASE)
_SPEAKER_WORD = frozenset({"speaker", "spk"})
_SUMMARY_HEAD = re.compile(r"^Summary \(written by [^()\n]{1,80}\)\s*(?:\n|$)")


def _deslug(slug: str) -> str:
    """A marker's slug as words, for a speaker the meeting record does not list (``alice-example`` → ``Alice Example``)."""
    return " ".join(word.capitalize() for word in re.split(r"[-_\s]+", slug) if word)


def speaker_display(marker_text: str | None, meeting: dict | None) -> tuple[str | None, str]:
    """``(name, kind)`` for a turn's ``speaker:<slug>`` marker, the ONE place a placeholder becomes words (ROR-142).

    The label is the one the meeting record lists for that slug (what the recorder wrote, or the name the person gave),
    else the slug read back as words. A placeholder with a number is ``Speaker 1`` (``SPEAKER_01``, ``spk 1`` too);
    another numbered one keeps its role word (``Guest 3``); a group track (``Them``) and a bare placeholder
    (``Unknown Speaker``) carry no name — the app says "Others on the call" and "Someone else". Anything else is a name,
    as written. A marker that is not a ``speaker:`` one has none."""
    raw = str(marker_text or "")
    if not raw.lower().startswith("speaker:"):
        return None, UNKNOWN_KIND
    slug = raw[len("speaker:"):].strip()
    labels = {marker(str(label)): str(label) for label in (meeting or {}).get("speakers") or []}
    label = labels.get(raw) or _deslug(slug)
    if not label or slug in ("", UNKNOWN):
        return None, UNKNOWN_KIND
    if is_group_placeholder(label):
        return None, GROUP
    if is_placeholder(label):
        numbered = _NUMBERED.fullmatch(" ".join(label.split()))
        if numbered is None:
            return None, UNKNOWN_KIND
        role = numbered.group("role").strip().casefold()
        word = "Speaker" if role in _SPEAKER_WORD else " ".join(w.capitalize() for w in role.split())
        n = numbered.group("n")
        return f"{word} {int(n) if n.isdigit() else n.upper()}", NUMBERED
    return label, NAMED


def is_summary_turn(text: str | None) -> bool:
    """Whether a turn's words are the recorder's summary (:func:`summary_text`'s heading): the first line of the one
    ``assistant:`` turn a meeting body opens with."""
    return bool(text) and _SUMMARY_HEAD.match(text) is not None


def meeting_wire(fm: dict, *, summary_turn: int | None) -> dict | None:
    """The facts of a meeting episode the reader shows in its header, from the record alone (nothing is stored for it):
    duration, the app, how many attendees, the summary's writer and its turn index, and — when a tool split the voices —
    which one and how many. ``None`` for any other episode."""
    if not is_meeting(fm):
        return None
    meeting = fm["meeting"]
    out: dict = {"recorder": meeting.get("recorder") if meeting.get("recorder") in RECORDERS else None,
                 "summary_turn": summary_turn}
    if isinstance(meeting.get("duration_s"), int) and not isinstance(meeting.get("duration_s"), bool):
        out["duration_s"] = meeting["duration_s"]
    if meeting.get("app"):
        out["app"] = str(meeting["app"])[:64]
    attendees = meeting.get("attendees")
    if isinstance(attendees, list) and attendees:
        out["attendees"] = len(attendees)
    if meeting.get("summary_writer"):
        out["summary_writer"] = str(meeting["summary_writer"])[:200]
    if meeting.get("voices_split_by"):
        out["voices_split_by"] = str(meeting["voices_split_by"])[:80]
        if isinstance(meeting.get("voices"), int) and not isinstance(meeting.get("voices"), bool):
            out["voices"] = meeting["voices"]
    return out
