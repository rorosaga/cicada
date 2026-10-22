"""Render a TLC counterexample from VideoQueue.tla as numbered steps in the code's own words.

Usage: python3 trace.py <tlc-output-file>
Reads TLC's plain-text trace; needs nothing beyond the standard library."""
from __future__ import annotations

import re
import sys

TOKEN = re.compile(r'\s*(<<|>>|:>|@@|\|->|"[^"]*"|[{}\[\](),]|[A-Za-z_][A-Za-z0-9_]*|-?\d+)')


def tokens(text: str) -> list[str]:
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"cannot read the trace near: {text[pos:pos + 40]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


class HDict(dict):
    """A TLC record or function, hashable so a set of records parses."""

    def __hash__(self):
        return hash(tuple(sorted(self.items(), key=str)))


class Parser:
    def __init__(self, toks: list[str]):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want=None):
        tok = self.t[self.i]
        if want is not None and tok != want:
            raise ValueError(f"expected {want!r}, got {tok!r}")
        self.i += 1
        return tok

    def expr(self):
        left = self.atom()
        if self.peek() != ":>":
            return left
        out = HDict()
        while True:
            self.take(":>")
            out[left] = self.atom()
            if self.peek() != "@@":
                return out
            self.take("@@")
            left = self.atom()

    def seq(self, close):
        items = []
        while self.peek() != close:
            items.append(self.expr())
            if self.peek() == ",":
                self.take(",")
        self.take(close)
        return items

    def atom(self):
        tok = self.take()
        if tok == "(":
            value = self.expr()
            self.take(")")
            return value
        if tok == "{":
            return frozenset(self.seq("}"))
        if tok == "<<":
            return tuple(self.seq(">>"))
        if tok == "[":
            rec = HDict()
            while self.peek() != "]":
                name = self.take()
                self.take("|->")
                rec[name] = self.expr()
                if self.peek() == ",":
                    self.take(",")
            self.take("]")
            return rec
        if tok.startswith('"'):
            return tok[1:-1]
        if tok in ("TRUE", "FALSE"):
            return tok == "TRUE"
        if re.fullmatch(r"-?\d+", tok):
            return int(tok)
        return tok


def states(text: str):
    """Yield (header, {var: value}) for each state of the first trace in TLC's output."""
    blocks = re.split(r"^(State \d+: .*|Back to state \d+: .*)$", text, flags=re.M)
    if len(blocks) > 1 and "Stuttering" in blocks[-2]:
        blocks[-1] = ""
    for head, body in zip(blocks[1::2], blocks[2::2]):
        body = body.split("\n\n")[0]
        assigns = re.split(r"^/\\ (\w+) = ", body, flags=re.M)
        env = {}
        for name, value in zip(assigns[1::2], assigns[2::2]):
            env[name] = Parser(tokens(value)).expr()
        yield head, env


def ident(value) -> str:
    if value in ((), "nobody", None):
        return "none"
    if isinstance(value, tuple):
        return f"{value[0]}#{value[1]}" if value[1] else str(value[0])
    return str(value)


def row_words(r: dict, holder: str) -> str:
    st = r["st"]
    if st == "absent":
        return "not queued"
    if st == "claimed":
        lease = "lease lapsed" if r["left"] == 0 else f"lease {r['left']} tick(s) left"
        token = f", token of {r['tok']}" if r["tok"] != "nobody" else ""
        return (f"leased to {holder} (stored session id {ident(r['ses'])}{token}; {lease}, attempts {r['att']}, "
                f"wants {r['want']})")
    if st == "failed":
        return f"failed (attempts {r['att']}, ages out in {r['fleft']} tick(s))"
    return f"queued (attempts {r['att']}, wants {r['want']})"


PLACE = {"A1": "newer than any request, this second", "A0": "newer than any request",
         "S1": "written before the request, in its second (this one)", "S0": "written before the request, in its second",
         "B0": "written before the request"}
FACT = {"T": "transcript", "F": "frames"}


def recs_words(rs) -> str:
    if not rs:
        return "none"
    return "; ".join(sorted(f"{FACT[r['f']]} record {PLACE[r['st']]}" for r in rs))


STEP = {
    "ClaimBegin": "{a} calls cicada_video_claim; video_queue.claim:668 reads the saved videos{snap}",
    "ClaimLocked": "{a}: video_queue.claim runs under the lock",
    "ClaimWrite": "{a}: the lock-free claim writes the file it read earlier (scratch break)",
    "ReleaseBegin": "{a} calls cicada_video_claim(release=[{key}]); video_queue.release:698 reads the saved videos{snap}",
    "ReleaseLocked": "{a}: video_queue.release({key}) runs under the lock",
    "RecordEpisode": "{a} calls cicada_record_watch({key}, basis={arg}); watch_record.record writes the episode "
                     "(mcp_tools.record_watch:635); the queue credit has not run yet",
    "CreditBegin": "{a}: _credit_video_queue starts; video_queue.complete:739 reads the saved videos{snap}",
    "CompleteLocked": "{a}: video_queue.complete({key}, basis={arg}) runs under the lock",
    "PutBegin": "the person queues {key} ({arg}); video_queue.put:539 reads the saved videos{snap}",
    "RemoveBegin": "the person removes {key}; video_queue.remove:555 reads the saved videos{snap}",
    "RetryBegin": "the person presses Try again on {key}; video_queue.retry:575 reads the saved videos{snap}",
    "PersonLocked": "the person's video_queue.{op}({key}) runs under the lock",
    "SaveVideo": "{key} is saved (its url-index row and page appear)",
    "HideVideo": "{key}'s page is hidden (archived, dropped or junk), so saved_videos no longer lists it",
    "SleepStart": "Sleep takes the pages (pages_held() is now True)",
    "SleepEnd": "Sleep lets go of the pages",
    "Restart": "{a}'s MCP process restarts and mints a new session id",
    "NewSecond": "the wall clock enters a new second",
    "Tick": "time passes one lease tick (leases and failed rows count down)",
    "DropCredit": "{a}: the queue credit never runs (it raised and _credit_video_queue swallowed it, or the process died)",
}


def render(text: str) -> str:
    out, prev = [], None
    for n, (head, env) in enumerate(states(text), 1):
        m = re.match(r"(State \d+|Back to state \d+): <?(\w+)", head)
        action = m.group(2) if m else head
        lines = []
        if prev is None:
            lines.append("start: nothing queued; every video saved")
        elif "Stuttering" in head:
            out.append(f"{n}. from here nothing changes any more, forever, and the property is still unmet")
            break
        elif head.startswith("Back to state"):
            lines.append(f"{head.split(':')[0].lower()} ({action}): the behaviour repeats from there forever")
        else:
            actor = next((a for a in env["pc"] if env["pc"][a]["op"] != prev["pc"][a]["op"]), None)
            if actor is None:
                actor = next((a for a in env.get("sid", {}) if env["sid"][a] != prev["sid"][a]), None)
            call = prev["pc"].get(actor) if actor else None
            if call is None or call.get("op") == "idle":
                call = env["pc"].get(actor) if actor else {}
            call = call or {}
            key = call.get("key")
            changed_saved = prev["saved"] ^ env["saved"]
            if action in ("SaveVideo", "HideVideo") and changed_saved:
                key = next(iter(changed_saved))
            snap = env["pc"].get(actor, {}).get("snap") if actor else None
            snap_words = f" ({fmt_set(snap)})" if snap else ""
            lines.append(STEP.get(action, action).format(a=actor, key=key, arg=call.get("arg"), op=call.get("op"),
                                                         snap=snap_words))
            for k in env["q"]:
                if env["q"][k] != prev["q"][k] or env["holder"][k] != prev["holder"][k]:
                    lines.append(f"   {k}: {row_words(prev['q'][k], prev['holder'][k])} -> "
                                 f"{row_words(env['q'][k], env['holder'][k])}")
            for k in env["recs"]:
                if env["recs"][k] != prev["recs"][k]:
                    lines.append(f"   {k} records: {recs_words(prev['recs'][k])} -> {recs_words(env['recs'][k])}")
            for a in env.get("sid", {}):
                if env["sid"][a] != prev["sid"][a]:
                    lines.append(f"   {a}'s session id: {ident(prev['sid'][a])} -> {ident(env['sid'][a])}")
        out.append(f"{n}. " + lines[0])
        out.extend(lines[1:])
        prev = env
    violated = re.search(r"(Invariant|Action property) (\w+) is violated", text)
    if violated:
        out.append(f"=> the last step breaks {violated.group(2)} (SKILL.md, 'The properties')")
    return "\n".join(out)


def fmt_set(s) -> str:
    return "{" + ", ".join(sorted(map(str, s))) + "}"


if __name__ == "__main__":
    print(render(open(sys.argv[1], encoding="utf-8").read()))
