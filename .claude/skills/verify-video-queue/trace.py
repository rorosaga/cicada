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
        out = {}
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
            rec = {}
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


def row_words(r: dict) -> str:
    st = r["st"]
    if st == "absent":
        return "not queued"
    if st == "claimed":
        lease = "lease lapsed" if r["left"] == 0 else f"lease {r['left']} tick(s) left"
        return f"claimed by {r['ses']} ({lease}, attempts {r['att']}, wants {r['want']})"
    if st == "failed":
        return f"failed (attempts {r['att']}, ages out in {r['fleft']} tick(s))"
    return f"queued (attempts {r['att']}, wants {r['want']})"


CALLS = {
    "claim": "cicada_video_claim()",
    "claimWrite": "the second half of a lock-free claim",
    "release": "cicada_video_claim(release=[{key}])",
    "complete": "the queue credit of cicada_record_watch({key}, basis={arg})",
    "put": "PUT /videos/queue/{key} want={arg}",
    "remove": "DELETE /videos/queue/{key}",
    "retry": "POST /videos/queue/{key}/retry",
}

STEP = {
    "ClaimBegin": "{a} calls cicada_video_claim; mcp_tools.py:1204 reads the saved videos ({snap})",
    "ClaimLocked": "{a}: video_queue.claim runs under the lock (video_queue.py:624)",
    "ClaimWrite": "{a}: the lock-free claim writes the file it read earlier",
    "ReleaseBegin": "{a} calls cicada_video_claim(release=[{key}]); mcp_tools.py:1204 reads the saved videos ({snap})",
    "ReleaseLocked": "{a}: video_queue.release runs under the lock (video_queue.py:649)",
    "RecordEpisode": "{a} calls cicada_record_watch({key}, basis={arg}); watch_record.record writes the episode "
                     "(mcp_tools.py:613); the queue credit has not run yet",
    "CompleteLocked": "{a}: the queue credit video_queue.complete({key}, basis={arg}) runs (mcp_tools.py:629, "
                      "video_queue.py:685)",
    "PutBegin": "the person queues {key} ({arg}); video_queue.put reads the saved videos ({snap}) before the lock "
                "(video_queue.py:514)",
    "RemoveBegin": "the person removes {key}; video_queue.remove reads the saved videos ({snap}) before the lock",
    "RetryBegin": "the person presses Try again on {key}; video_queue.retry reads the saved videos ({snap})",
    "PersonLocked": "the person's video_queue.{op}({key}) runs under the lock",
    "PersonAbort": "the backend drops the person's request before it writes",
    "SaveVideo": "{key} is saved (its url-index row and page appear)",
    "HideVideo": "{key}'s page is hidden (archived, dropped or junk), so saved_videos no longer lists it",
    "SleepStart": "Sleep takes the pages (pages_held() is now True)",
    "SleepEnd": "Sleep lets go of the pages",
    "Tick": "time passes one tick (leases and failed rows count down)",
    "DropCredit": "{a}: the queue credit never runs (it raised and _credit_video_queue swallowed it, or the process died)",
}


def fmt_set(s) -> str:
    return "{" + ", ".join(sorted(map(str, s))) + "}"


def render(text: str) -> str:
    out, prev = [], None
    for n, (head, env) in enumerate(states(text), 1):
        m = re.match(r"(State \d+|Back to state \d+): <?(\w+)", head)
        action = m.group(2) if m else head
        lines = []
        if prev is None:
            lines.append("start: nothing queued; every video saved")
        elif "Stuttering" in head:
            lines.append("from here nothing changes any more, forever, and the property is still unmet")
            out.append(f"{n}. " + lines[0])
            break
        elif head.startswith("Back to state"):
            lines.append(f"{head.split(':')[0].lower()} ({action}): the behaviour repeats from there forever")
        else:
            actor = next((a for a in env["pc"] if env["pc"][a] != prev["pc"][a]), None)
            call = prev["pc"].get(actor) if actor else None
            if call is None or call.get("op") == "idle":
                call = env["pc"].get(actor) if actor else {}
            key = call.get("key") if call else None
            changed_saved = (prev["saved"] ^ env["saved"])
            if action in ("SaveVideo", "HideVideo") and changed_saved:
                key = next(iter(changed_saved))
            tmpl = STEP.get(action, action)
            if action == "ClaimLocked" and env["pc"].get(actor, {}).get("op") == "claimWrite":
                tmpl = "{a}: video_queue.claim reads the queue file with the lock removed (scratch break)"
            lines.append(tmpl.format(a=actor, key=key, arg=(call or {}).get("arg"), op=(call or {}).get("op"),
                                     snap=fmt_set((call or {}).get("snap", ()))))
            for k in env["q"]:
                if env["q"][k] != prev["q"][k]:
                    lines.append(f"   {k}: {row_words(prev['q'][k])} -> {row_words(env['q'][k])}")
            for k in env["recs"]:
                if env["recs"][k] != prev["recs"][k]:
                    lines.append(f"   {k}: records newer than its request {fmt_set(prev['recs'][k])} -> "
                                 f"{fmt_set(env['recs'][k])}")
            for flag, words in (("lost", "a queued video was dropped while it is still saved"),
                                ("relTrespass", "a session ended another session's lease"),
                                ("recTrespass", "a record ended another session's lease with no newer record"),
                                ("unsupported", "a row closed as done with no record newer than its request")):
                if env.get(flag) and not prev.get(flag):
                    lines.append(f"   => {words}")
        out.append(f"{n}. " + lines[0])
        out.extend(lines[1:])
        prev = env
    return "\n".join(out)


if __name__ == "__main__":
    print(render(open(sys.argv[1], encoding="utf-8").read()))
