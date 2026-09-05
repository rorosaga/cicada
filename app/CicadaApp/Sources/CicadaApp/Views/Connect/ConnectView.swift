import SwiftUI
import AppKit

// MARK: - Setup catalog model

/// One AI harness that can be wired to Cicada's MCP server. `id` doubles as the
/// optional bundled-logo resource name (`Resources/logos/<id>.png`); when no
/// logo ships, the square tile renders the brand-colored monogram instead so
/// the page never shows an empty box.
struct AgentSetup: Identifiable {
    let id: String
    let name: String
    let monogram: String
    let brand: Color
    let blurb: String
    let steps: [SetupStep]
    var deeplink: Deeplink? = nil

    struct SetupStep: Identifiable {
        let id = UUID()
        let label: String
        var command: String? = nil
        var note: String? = nil
    }

    struct Deeplink {
        let label: String
        let url: URL
    }
}

/// Builds the setup catalog with real absolute paths so every command is
/// copy-paste runnable on this machine — no `<path/to/cicada>` placeholders.
/// Commands verified against each tool's docs (July 2026); config-file tools
/// (Desktop, Cursor, Hermes) get literal paths baked in because GUI-launched
/// apps don't expand shell variables.
enum AgentSetupCatalog {
    /// `memoryRoot`, when given, is the LIVE backend's own configured
    /// `CICADA_MEMORY_PATH` (from `GET /healthz`) and always wins over the
    /// `<home>/memory` guess — see `ConnectView.refreshLiveMemoryRoot()`.
    /// `home` (the checkout root, from `BackendProcess.installRoot()`)
    /// still drives the python/server executable paths regardless, since
    /// there's no live equivalent to ask "where is my own source code" and
    /// a wrong value there fails loudly (file not found) rather than
    /// silently registering the wrong bank.
    static func all(home: String, memoryRoot: String? = nil) -> [AgentSetup] {
        let python = "\(home)/api/.venv/bin/python"
        let server = "\(home)/mcp/server.py"
        let memory = (memoryRoot?.isEmpty == false) ? memoryRoot! : "\(home)/memory"

        // Every path below is escaped for the format of the snippet it
        // lands in (`SnippetEscape`) — a home with a space or a quote must
        // paste as the exact path, never as a broken command or config.
        let mcpJSON = """
        {
          "mcpServers": {
            "cicada": {
              "command": "\(SnippetEscape.json(python))",
              "args": ["\(SnippetEscape.json(server))"],
              "env": { "CICADA_MEMORY_PATH": "\(SnippetEscape.json(memory))" }
            }
          }
        }
        """

        // Cursor one-click install deeplink: base64 of the INNER server object.
        let cursorInner = #"{"command":"\#(SnippetEscape.json(python))","args":["\#(SnippetEscape.json(server))"],"env":{"CICADA_MEMORY_PATH":"\#(SnippetEscape.json(memory))"}}"#
        let cursorB64 = Data(cursorInner.utf8).base64EncodedString()
            .addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? ""
        let cursorDeeplink = URL(string: "cursor://anysphere.cursor-deeplink/mcp/install?name=cicada&config=\(cursorB64)")

        return [
            AgentSetup(
                id: "claude-code",
                name: "Claude Code",
                monogram: "CC",
                brand: Color(hex: 0xD97757),
                blurb: "Anthropic's terminal agent — Cicada's primary deployment target. One command, available in every project.",
                steps: [
                    .init(
                        label: "Register the MCP server (user scope = all projects)",
                        command: "claude mcp add cicada --scope user --env CICADA_MEMORY_PATH=\(SnippetEscape.shell(memory)) -- \(SnippetEscape.shell(python)) \(SnippetEscape.shell(server))",
                        note: "Verify with `claude mcp list` or `/mcp` inside a session. New sessions pick it up automatically."
                    ),
                    .init(
                        label: "Optional: install the Cicada skill so Claude knows when to recall and save",
                        command: "mkdir -p ~/.claude/skills/cicada && cp \(SnippetEscape.shell("\(home)/SKILL.md")) ~/.claude/skills/cicada/SKILL.md"
                    ),
                ]
            ),
            AgentSetup(
                id: "cursor",
                name: "Cursor",
                monogram: "Cu",
                brand: Color(hex: 0x5C6AC4),
                blurb: "The AI code editor. Use the one-click install, or merge the JSON into your global config.",
                steps: [
                    .init(
                        label: "Merge this into ~/.cursor/mcp.json (global) or .cursor/mcp.json (per-project)",
                        command: mcpJSON,
                        note: "Enable it under Cursor Settings → MCP, then restart Cursor. Heads-up: Cursor caps active tools at ~40 across all servers."
                    ),
                ],
                deeplink: cursorDeeplink.map { AgentSetup.Deeplink(label: "Add to Cursor", url: $0) }
            ),
            AgentSetup(
                id: "openclaw",
                name: "OpenClaw",
                monogram: "OC",
                brand: Color(hex: 0xE0623D),
                blurb: "The open-source personal agent. Native MCP support with hot-reload — no restart needed.",
                steps: [
                    .init(
                        label: "Register with the CLI (changes hot-apply)",
                        command: "openclaw mcp add cicada --command \"\(SnippetEscape.shellDoubleQuoted(python))\" --arg \"\(SnippetEscape.shellDoubleQuoted(server))\" --env CICADA_MEMORY_PATH=\"\(SnippetEscape.shellDoubleQuoted(memory))\"",
                        note: "Verify with `openclaw mcp doctor cicada --probe`. Don't add an explicit transport field in openclaw.json — stdio is inferred from `command`."
                    ),
                ]
            ),
            AgentSetup(
                id: "codex",
                name: "OpenAI Codex",
                monogram: "OA",
                brand: Color(hex: 0x10A37F),
                blurb: "OpenAI's terminal coding agent. Registers via the codex CLI or config.toml.",
                steps: [
                    .init(
                        label: "Register with the CLI",
                        command: "codex mcp add cicada --env CICADA_MEMORY_PATH=\"\(SnippetEscape.shellDoubleQuoted(memory))\" -- \"\(SnippetEscape.shellDoubleQuoted(python))\" \"\(SnippetEscape.shellDoubleQuoted(server))\""
                    ),
                    .init(
                        label: "…or add to ~/.codex/config.toml",
                        command: """
                        [mcp_servers.cicada]
                        command = "\(SnippetEscape.toml(python))"
                        args = ["\(SnippetEscape.toml(server))"]
                        env = { CICADA_MEMORY_PATH = "\(SnippetEscape.toml(memory))" }
                        """,
                        note: "Loads at session start. If the venv is slow to boot, raise startup_timeout_sec (default 10s)."
                    ),
                ]
            ),
            AgentSetup(
                id: "claude-desktop",
                name: "Claude Desktop",
                monogram: "C",
                brand: Color(hex: 0xC96442),
                blurb: "The Claude macOS app — covers everyday chat, not just coding.",
                steps: [
                    .init(
                        label: "Merge this into ~/Library/Application Support/Claude/claude_desktop_config.json",
                        command: mcpJSON,
                        note: "Or open it via Claude menu → Settings → Developer → Edit Config. Fully quit and reopen Claude Desktop; the tools appear behind the connectors icon under the input box."
                    ),
                ]
            ),
            AgentSetup(
                id: "hermes",
                name: "Hermes (Nous)",
                monogram: "H",
                brand: Color(hex: 0xB8A88F),
                blurb: "Nous Research's agent. Native MCP via YAML config with in-session reload.",
                steps: [
                    .init(
                        label: "Add to ~/.hermes/config.yaml, then run /reload-mcp in a session",
                        command: """
                        mcp_servers:
                          cicada:
                            command: "\(SnippetEscape.yaml(python))"
                            args: ["\(SnippetEscape.yaml(server))"]
                            env:
                              CICADA_MEMORY_PATH: "\(SnippetEscape.yaml(memory))"
                        """,
                        note: "Hermes sanitizes subprocess environments — the env var must live in this config; a shell export won't reach the server."
                    ),
                ]
            ),
            AgentSetup(
                id: "gemini-cli",
                name: "Gemini CLI",
                monogram: "G",
                brand: Color(hex: 0x4796E3),
                blurb: "Google's terminal agent. One command with user scope makes it global.",
                steps: [
                    .init(
                        label: "Register with the CLI",
                        command: "gemini mcp add -s user -e CICADA_MEMORY_PATH=\"\(SnippetEscape.shellDoubleQuoted(memory))\" cicada \"\(SnippetEscape.shellDoubleQuoted(python))\" \"\(SnippetEscape.shellDoubleQuoted(server))\"",
                        note: "Restart the CLI, then check /mcp list. Default scope is per-project; -s user makes it global."
                    ),
                ]
            ),
        ]
    }
}

// MARK: - Connect page

/// The "Connect your AI" page: how to wire any MCP-capable agent to this
/// machine's Cicada memory. Doubles as the first-launch onboarding step when
/// presented as a sheet (`isOnboarding` adds the intro + done affordances).
struct ConnectView: View {
    var isOnboarding = false
    var onDone: (() -> Void)? = nil

    private let home = BackendProcess.installRoot().path
    @State private var agents: [AgentSetup] = []
    /// The live backend's own configured memory root, once `/healthz`
    /// answers (G88 follow-up). This is the single source of truth for
    /// "which bank does the app actually use" — the app and any agent
    /// registered from a copy-pasted command on this page must always
    /// agree, and the only way to guarantee that regardless of install
    /// layout is to ask the backend rather than re-derive the answer
    /// independently (installRoot()'s checkout-relative guess is used only
    /// until this arrives, or if the backend never answers). The probe
    /// owns the retry/never-regress rules — see `LiveMemoryRootProbe`.
    @State private var probe = LiveMemoryRootProbe()
    /// `isConnected` is the app's one backend-reachability signal (the SSE
    /// stream). Keyed into `.task(id:)` below so a backend that comes up
    /// after this page did re-runs the probe — no second poller.
    @Environment(Store.self) private var store

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(
                title: isOnboarding ? "Welcome to Cicada" : Copy.agents,
                subtitle: Copy.agentsSubtitle
            ) {
                if isOnboarding {
                    Button {
                        onDone?()
                    } label: {
                        Text("Get started")
                            .font(CicadaTheme.font(size: 13, weight: .semibold))
                            .padding(.horizontal, CicadaTheme.spacingLG)
                            .padding(.vertical, CicadaTheme.spacingSM)
                            .background(CicadaTheme.accent.opacity(0.9))
                            .foregroundStyle(.white)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.cicadaPlain)
                }
            }

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    if isOnboarding {
                        introCard
                    }
                    prereqCard

                    ForEach(agents) { agent in
                        AgentSetupCard(agent: agent)
                    }

                    webNoteCard
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXXL)
            }
        }
        .background(CicadaTheme.background)
        .onAppear {
            if agents.isEmpty { agents = AgentSetupCatalog.all(home: home, memoryRoot: probe.liveRoot) }
        }
        // Restarts (cancelling the previous loop) whenever the SSE stream
        // connects or drops, and runs once on appearance.
        .task(id: store.isConnected) { await refreshLiveMemoryRoot() }
    }

    /// Ask the backend what memory root it's actually configured with
    /// (`GET /healthz`, auth-exempt) and rebuild the setup commands against
    /// that instead of the local `installRoot()` guess whenever it differs
    /// (G88 follow-up). Renders instantly either way — this only refines an
    /// already-visible page, never blocks it. A backend that isn't listening
    /// yet — the usual case on first paint, since the app has only just
    /// spawned it — is retried with backoff until it answers (Devin PR #28
    /// round 2); the loop is also restarted by the reachability flip in
    /// `.task(id:)` above, and the guess is never re-applied once a live
    /// root has been seen (`LiveMemoryRootProbe`).
    private func refreshLiveMemoryRoot() async {
        // A flip to *disconnected* has nothing new to ask once a live root
        // is known; the initial appearance and a flip to connected do.
        if probe.liveRoot != nil && !store.isConnected { return }
        probe.beginAttempts()
        while !Task.isCancelled {
            let outcome: LiveMemoryRootProbe.Outcome
            do {
                outcome = .answered(try await APIClient.shared.fetchHealth().memoryRoot)
            } catch {
                outcome = .unreachable
            }
            if Task.isCancelled { return }
            if probe.observe(outcome) {
                agents = AgentSetupCatalog.all(home: home, memoryRoot: probe.liveRoot)
            }
            guard let delay = probe.nextDelay else { return }
            try? await Task.sleep(for: .seconds(delay))
        }
    }

    private var introCard: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            BookwormView(state: .happy, pointSize: 48)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("Your agents share one memory")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Conversations become episodes; the nightly Sleep cycle consolidates them into the knowledge graph you see here. Connect the tools you use below — each one gets recall, save, and nudge tools automatically.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var prereqCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("STEP 0 — ONE-TIME INSTALL")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
            Text("Sets up the Python environment, registers the backend service, and schedules the nightly Sleep cycle. Skip if you've already run it.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            CommandBox(command: "cd \(SnippetEscape.shell(home)) && make install")
            Text("Cicada home: \(home) — commands below use this path; adjust if your checkout lives elsewhere.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var webNoteCard: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Image(systemName: "globe")
                .font(CicadaTheme.font(size: 16))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: 44, height: 44)
                .background(RoundedRectangle(cornerRadius: 10).fill(CicadaTheme.surfaceElevated))
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("claude.ai / ChatGPT on the web")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Web apps only reach hosted (remote) MCP connectors served from the public internet — they can't launch the local Cicada server on your Mac. Use Claude Desktop or a terminal agent instead, or import your web conversations with the Upload button on the Graph page: exports from claude.ai, ChatGPT, and Gemini consolidate into the same memory. (A hosted Cicada connector — Streamable HTTP behind a tunnel with OAuth — is possible future work.)")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }
}

// MARK: - Agent card

private struct AgentSetupCard: View {
    let agent: AgentSetup

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingMD) {
                AgentTile(agent: agent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(agent.name)
                        .font(CicadaTheme.headingFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(agent.blurb)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                if let deeplink = agent.deeplink {
                    Button {
                        NSWorkspace.shared.open(deeplink.url)
                    } label: {
                        Text(deeplink.label)
                            .font(CicadaTheme.font(size: 11, weight: .semibold))
                            .padding(.horizontal, CicadaTheme.spacingMD)
                            .padding(.vertical, 5)
                            .background(agent.brand.opacity(0.25))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .clipShape(Capsule())
                            .overlay(Capsule().stroke(agent.brand.opacity(0.5), lineWidth: 1))
                    }
                    .buttonStyle(.cicadaPlain)
                    .help("One-click install via the Cursor deeplink")
                }
            }

            ForEach(agent.steps) { step in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(step.label)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    if let command = step.command {
                        CommandBox(command: command)
                    }
                    if let note = step.note {
                        Text(note)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }
}

// MARK: - Square identity tile

/// 44pt square brand tile. Prefers a bundled `Resources/logos/<id>.png`; falls
/// back to a brand-colored monogram so the tile is always identifiable.
///
/// The white plate this tile used to draw under the mark is gone (R-L5). It
/// existed for one asset — `codex.png` shipped as black ink on an opaque white
/// square, invisible on a dark card — and it "fixed" that by putting EVERY
/// mark, colour ones included, on a white chip in dark mode. Track L recut the
/// two opaque rasters with alpha and gave the monochrome marks a `-dark`
/// sibling `LogoImage.resolvedName(for:)` picks up, so the plate has nothing
/// left to hide and the tile keeps only its own border.
private struct AgentTile: View {
    let agent: AgentSetup

    var body: some View {
        Group {
            if LogoImage.exists(name: agent.id) {
                LogoImage(name: agent.id, size: 44)
            } else {
                Text(agent.monogram)
                    .font(CicadaTheme.font(size: 16, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(
                        RoundedRectangle(cornerRadius: 10)
                            .fill(LinearGradient(
                                colors: [agent.brand, agent.brand.opacity(0.7)],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            ))
                    )
            }
        }
        .frame(width: 44, height: 44)
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(CicadaTheme.border, lineWidth: 1))
    }
}

// `CommandBox` (the copy-paste command/config snippet) now lives in
// `Views/Common/CommandBox.swift` — shared with the Sync sources page.
