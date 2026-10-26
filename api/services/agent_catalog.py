"""The one table of who connects to Cicada, grouped by provider (G217, ruling 36 D3; the owner, 2026-10-22: "one
umbrella per provider, no duplicate logos").

Before this module three hard-coded lists named the agents — ``agent_live.LIVE_AGENTS`` (with its ``clientInfo``
rules and the connector-app map), ``agent_wiring.AGENTS`` (skill folders) and the app's own ``AgentCatalog`` — and
the intelligence cards lived in a fourth (``byok.PROVIDERS`` plus the two plan adapters). Each of those now derives
from, or is checked against, this table; ``GET /providers`` serves it to the app so a new row is one change here.

Shape: an :class:`Umbrella` per provider (Anthropic, OpenAI, Google, xAI, Meta, then one per independent agent or
model host) with one logo slug — a mark in the shared logo set (``logos/manifest.json``; one mark per umbrella, never a
second mark for a sub-product) — and beneath it:

* ``ways`` — each product a person connects to Cicada (Claude Code, Claude Desktop, Codex, ChatGPT, Grok Build…),
  with how it connects (``stdio`` MCP on this machine, ``hooks`` that capture its turns, ``remote`` through the G135
  connector, ``rest`` through the HTTP API for agents that cannot do MCP, ``messages`` for a texted agent, ``export``
  for an import), its ``GET /agents/setup`` ids, the G135 connector app it uses, and the ``clientInfo.name`` words
  that recognise it (display only, never a security decision — the MCP spec's own rule).
* ``intelligence`` — the connection ids (``GET /connections``) that consolidate the person's memory with this
  provider: a plan (``claude-plan``, ``chatgpt-plan``) or a key (``byok-<id>``).

Tiers (ruling 36 D3): ``1`` first-class (a mark, a setup prompt, live detection); ``2`` recognised by ``clientInfo``
and connected with the generic prompt; ``3`` watched — a product the owner named whose way in is not settled (Dots,
Muse, Grok Bot): listed so the app can say how it would connect, never offered a setup that does not exist.

Only a product that can actually reach Cicada is listed (owner, 2026-10-26: "do your due diligence to know what we're
connecting with"). Cline, Goose, Kiro and Poke left the table that day; a person who had connected one still lights
the ``other`` pill (``agent_live._fold_other``) and an old sign-in request still reads "An agent", so nothing they
set up stops working — only the named row is gone.

Ids are wire values. A way's ``id`` is what ``/agents/live`` and ``/agents/setup`` already answer with; the eleven the
app pins (``LIVE_PILLS``, ``api/tests/fixtures/agent_catalog.json``) keep their order and spelling.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: How a way reaches Cicada. ``rest`` is G213's HTTP API (the ``agentapi`` slice), named here so the table can say
#: which agents need it before it ships.
CONNECTS = ("stdio", "hooks", "remote", "rest", "messages", "export")


@dataclass(frozen=True)
class Way:
    id: str
    label: str
    connects: tuple[str, ...]
    tier: int = 1
    #: ``clientInfo.name`` words, matched as whole words (``_words``) — a multi-word needle as a phrase. Checked
    #: across every way in table order, so a specific product precedes its family (Claude Code before Claude).
    clients: tuple[str, ...] = ()
    #: ``GET /agents/setup?harness=`` ids that connect this way, in the order the app offers them.
    setup: tuple[str, ...] = ()
    #: The G135 connector app (``api.remote.catalog.APPS``) a link for this way is made for.
    remote_app: str | None = None
    #: One of the eleven pills the app draws today (R-AG1). Every other way is tracked too, and lights the
    #: ``other`` pill until the app draws it.
    pill: bool = False
    #: One honest sentence about how this way connects, for a tier-3 row or a caveat (provider-neutral where it
    #: describes Cicada's step).
    note: str | None = None
    #: The user-level skills folder its own docs name, and others it also reads (``agent_wiring.AGENTS``).
    home: str | None = None
    skills: str | None = None
    reads: tuple[str, ...] = ()
    #: The name this way goes by where it reaches Cicada through the remote connector or its account's export, when
    #: that is not the local app (ruling 39, 2026-10-24): Claude Desktop on this Mac, claude.ai on the web and the
    #: phone. ``label`` never names the remote surface for such a way; ``None`` means one name fits every surface.
    remote_label: str | None = None

    def name_for(self, via: str | None) -> str | None:
        """This way's name for one surface: ``"remote"`` → ``remote_label``, ``"local"`` → ``label``. ``None`` when
        the surface is unknown and the two differ, so a caller never names one surface by the other's name."""
        if self.remote_label is None:
            return self.label
        return {"remote": self.remote_label, "local": self.label}.get(via or "")

    def wire(self) -> dict:
        return {"id": self.id, "label": self.label, "connects": list(self.connects), "tier": self.tier,
                "clients": list(self.clients), "setup": list(self.setup), "remoteApp": self.remote_app,
                "pill": self.pill, "note": self.note, "remoteLabel": self.remote_label}


@dataclass(frozen=True)
class Intelligence:
    """One way this provider can run Sleep: a plan the person already pays for, or a key they bring."""
    connection: str
    label: str
    kind: str            # plan | key | local
    note: str | None = None

    def wire(self) -> dict:
        return {"connection": self.connection, "label": self.label, "kind": self.kind, "note": self.note}


@dataclass(frozen=True)
class Umbrella:
    id: str
    label: str
    #: A slug in the shared logo set; ``None`` draws the monogram (CLAUDE.md's picture precedence ends there).
    logo: str | None
    tier: int
    ways: tuple[Way, ...] = ()
    intelligence: tuple[Intelligence, ...] = ()
    #: Sub-products this umbrella names that are not ways yet (Vertex), shown as "later" — never offered.
    later: tuple[str, ...] = field(default=())

    def wire(self) -> dict:
        return {"id": self.id, "label": self.label, "logo": self.logo, "tier": self.tier,
                "ways": [w.wire() for w in self.ways], "intelligence": [i.wire() for i in self.intelligence],
                "later": list(self.later)}


_REST_NOTE = ("It cannot add an MCP server, so it reaches Cicada through the HTTP API with a token you give it.")

UMBRELLAS: tuple[Umbrella, ...] = (
    Umbrella("anthropic", "Anthropic", "claude", 1, ways=(
        Way("claude-code", "Claude Code", ("stdio", "hooks", "remote"), clients=("claude-code", "claude code"),
            setup=("claude-code",), remote_app="claude-code", pill=True, home=".claude", skills=".claude/skills"),
        Way("claude", "Claude Desktop", ("stdio", "remote", "export"), clients=("claude",),
            setup=("claude-desktop", "claude"), remote_app="claude", pill=True, remote_label="claude.ai"),
    ), intelligence=(
        Intelligence("claude-plan", "Use my Claude plan", "plan"),
        Intelligence("byok-anthropic", "Anthropic API key", "key"),
    )),
    Umbrella("openai", "OpenAI", "openai", 1, ways=(
        Way("codex", "Codex", ("stdio", "hooks", "remote"), clients=("codex",), setup=("codex",),
            remote_app="codex", pill=True, home=".codex", skills=".codex/skills", reads=(".agents/skills",)),
        Way("chatgpt", "ChatGPT", ("remote", "export"), clients=("chatgpt",), setup=("chatgpt",),
            remote_app="chatgpt", pill=True),
        Way("dots", "Dots", ("remote",), tier=3, clients=("dots",),
            note="Dots works through ChatGPT's plugins, so connecting ChatGPT is its way in."),
    ), intelligence=(
        Intelligence("chatgpt-plan", "Use my ChatGPT plan", "plan"),
        Intelligence("byok-openai", "OpenAI API key", "key"),
    )),
    Umbrella("google", "Google Gemini", "gemini", 1, ways=(
        Way("gemini-cli", "Gemini CLI / Antigravity", ("stdio", "hooks", "remote"),
            clients=("gemini", "antigravity", "agy"), setup=("gemini-cli",), remote_app="gemini-cli", pill=True,
            home=".gemini", skills=".gemini/skills", reads=(".agents/skills",)),
        Way("gemini-app", "Gemini app", ("remote",), tier=3,
            note="Added on the web, it shows on the phone too; it needs Cicada reachable from the internet."),
    ), intelligence=(
        Intelligence("byok-gemini", "Gemini API key", "key",
                     note="Turn on billing for this key's project. Google's free tier lets people at Google read "
                          "what is sent."),
    ), later=("Google Cloud (Vertex)",)),
    # Three xAI products reach an MCP server, each its own way (checked 2026-10-26): Grok Build, the terminal agent
    # (``grok mcp add``); the Grok app (grok.com → Connectors → Custom, a public URL); Grok Bot, the personal agent
    # in xAI's cloud (asked in chat to add a server, no settings field).
    Umbrella("xai", "xAI Grok", "grok", 1, ways=(
        # Grok Build before the Grok app: its client names itself with the family word too.
        Way("grok-build", "Grok Build", ("stdio", "remote"), tier=2, clients=("grok build", "grok-build",
                                                                             "grok-cli"),
            note="The terminal agent adds Cicada as a local MCP server."),
        Way("grok", "Grok app", ("remote",), clients=("grok",), setup=("grok",), remote_app="grok", pill=True),
        Way("grok-bot", "Grok Bot", ("remote",), tier=3, clients=("grok bot", "grok-bot"),
            note="You ask it in chat to add Cicada's link. It runs in xAI's cloud, so it needs Cicada reachable "
                 "from the internet."),
    ), intelligence=(
        Intelligence("byok-xai", "xAI API key", "key"),
    ), later=("Use my Grok plan (Grok Build), beta",)),
    # Meta's agent is Muse ("Muse from Meta", 2026-09-08). Its connector list is Meta's own; for anything else it
    # writes and saves its own client from a link and a token, on a machine in Meta's cloud.
    Umbrella("meta", "Muse", "muse", 3, ways=(
        Way("muse", "Muse", ("rest", "remote"), tier=3, clients=("muse",),
            note="Muse builds its own connector from a link and a token; it runs in Meta's cloud, so it needs "
                 "Cicada reachable from the internet."),
    )),
    Umbrella("cursor", "Cursor", "cursor", 1, ways=(
        Way("cursor", "Cursor", ("stdio", "hooks", "remote"), clients=("cursor",), setup=("cursor",),
            remote_app="cursor", pill=True, home=".cursor", skills=".cursor/skills",
            reads=(".agents/skills", ".claude/skills", ".codex/skills")),
    )),
    Umbrella("opencode", "OpenCode", "opencode", 1, ways=(
        Way("opencode", "OpenCode", ("stdio", "remote"), clients=("opencode",), setup=("opencode",), pill=True,
            home=".config/opencode", skills=".config/opencode/skills", reads=(".claude/skills", ".agents/skills")),
    )),
    Umbrella("hermes", "Hermes Agent", "hermes", 1, ways=(
        Way("hermes", "Hermes", ("stdio", "remote"), clients=("hermes",), setup=("hermes",), pill=True,
            home=".hermes", skills=".hermes/skills"),
    )),
    Umbrella("openclaw", "OpenClaw", "openclaw", 1, ways=(
        Way("openclaw", "OpenClaw", ("stdio", "remote"), clients=("openclaw",), setup=("openclaw",), pill=True,
            home=".openclaw", skills=".openclaw/skills"),
    )),
    # The id stays ``vscode`` (a wire value: live sightings, the G135 connector app); the product is GitHub Copilot,
    # in VS Code's agent mode or the Copilot CLI (owner, 2026-10-26).
    Umbrella("vscode", "GitHub Copilot", "copilot", 2, ways=(
        Way("vscode", "GitHub Copilot", ("stdio", "remote"), tier=2,
            clients=("copilot", "visual studio code", "vscode"), setup=("other",), remote_app="vscode"),
    )),
    Umbrella("zed", "Zed", "zed", 2, ways=(Way("zed", "Zed", ("stdio", "remote"), tier=2, clients=("zed",),
                                                setup=("other",)),)),
    # Cognition ships one brand now: Windsurf became Devin Desktop on 2026-06-02 (same editor, MCP config unchanged
    # under ~/.codeium), beside the Devin CLI and cloud Devin. The way id stays ``windsurf`` (a wire value).
    Umbrella("devin", "Devin", "devin", 2, ways=(
        Way("windsurf", "Devin", ("stdio", "remote"), tier=2, clients=("devin", "windsurf", "cascade"),
            setup=("other",),
            note="Devin Desktop and the Devin CLI add Cicada as a local MCP server; cloud Devin needs Cicada "
                 "reachable from the internet."),
    )),
    Umbrella("warp", "Warp", "warp", 2, ways=(Way("warp", "Warp", ("stdio",), tier=2, clients=("warp",),
                                                  setup=("other",)),)),
    Umbrella("amp", "Amp", "amp", 2, ways=(Way("amp", "Amp", ("stdio", "remote"), tier=2, clients=("amp",),
                                               setup=("other",)),)),
    Umbrella("instinct", "Instinct", "instinct", 3, ways=(
        Way("instinct", "Instinct", ("messages", "rest"), tier=3,
            note="You text it, so Cicada reads it from the Messages chats you tick; it can also use the HTTP API. "
                 + _REST_NOTE),
    )),
    # Model hosts: intelligence only.
    Umbrella("openrouter", "OpenRouter", "openrouter", 1,
             intelligence=(Intelligence("byok-openrouter", "OpenRouter", "key"),)),
    Umbrella("fireworks", "Fireworks", "fireworks", 2,
             intelligence=(Intelligence("byok-fireworks", "Fireworks API key", "key"),)),
    Umbrella("deepinfra", "DeepInfra", "deepinfra", 2,
             intelligence=(Intelligence("byok-deepinfra", "DeepInfra API key", "key"),)),
    Umbrella("together", "Together AI", "together", 2,
             intelligence=(Intelligence("byok-together", "Together AI API key", "key",
                                        note="Together keeps prompts and replies unless zero data retention is "
                                             "turned on for your account."),)),
    Umbrella("groq", "Groq", "groq", 2, intelligence=(Intelligence("byok-groq", "Groq API key", "key"),)),
    Umbrella("mistral", "Mistral", "mistral", 2,
             intelligence=(Intelligence("byok-mistral", "Mistral API key", "key"),)),
    Umbrella("local", "This machine", None, 3,
             intelligence=(Intelligence("ollama", "A model on this machine", "local",
                                        note="Only when you choose it; never a default (ruling 36 D1)."),)),
    # Any agent the table does not name: the generic prompt, no mark.
    Umbrella("other", "Another agent", None, 2, ways=(
        Way("other", "Another agent", ("stdio", "remote", "rest"), tier=2, setup=("other",), pill=True,
            remote_app="other"),
    )),
)

WAYS: tuple[Way, ...] = tuple(w for u in UMBRELLAS for w in u.ways)
_WAY = {w.id: w for w in WAYS}
_UMBRELLA_OF = {w.id: u for u in UMBRELLAS for w in u.ways}

#: The eleven pills the app draws (R-AG1), in the owner's order — pinned by ``api/tests/fixtures/agent_catalog.json``
#: and the app's ``AgentCatalog``. Table order is grouped by provider; this order is the app's.
LIVE_PILLS: tuple[str, ...] = ("claude-code", "codex", "claude", "chatgpt", "cursor", "opencode", "hermes",
                               "openclaw", "grok", "gemini-cli", "other")
FEATURED: tuple[str, ...] = LIVE_PILLS[:9]
OTHER = "other"
#: Every way ``/agents/live`` reports: the pills first, then the rest of the table (tier 2 and 3) in table order.
TRACKED: tuple[str, ...] = LIVE_PILLS + tuple(w.id for w in WAYS if w.id not in LIVE_PILLS)

#: Cicada's own MCP clients — never "another agent" (the release smoke test).
OWN_CLIENTS = frozenset({"smoke-test"})


def way(way_id: str) -> Way | None:
    return _WAY.get(way_id)


def umbrella_of(way_id: str) -> Umbrella | None:
    return _UMBRELLA_OF.get(way_id)


def _words(text: str) -> str:
    """Lowercase, every run of non-alphanumerics one space, padded — so a needle matches whole words only
    (``amp`` never matches "example", ``zed`` never "authorized")."""
    return f" {re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()} "


def way_for_client(client_name: str | None) -> str | None:
    """The way a ``clientInfo.name`` names, by the table's words in table order; ``other`` for a name that matches
    nothing, ``None`` for no name or one of Cicada's own clients. Display only."""
    name = (client_name or "").strip()
    if not name or name.lower() in OWN_CLIENTS:
        return None
    padded = _words(name)
    for w in WAYS:
        if any(_words(needle) in padded for needle in w.clients):
            return w.id
    return OTHER


def snapshot() -> dict:
    """``GET /providers``: the whole table. Static per release — no probe, no file read."""
    return {"providers": [u.wire() for u in UMBRELLAS], "pills": list(LIVE_PILLS), "featured": list(FEATURED)}
