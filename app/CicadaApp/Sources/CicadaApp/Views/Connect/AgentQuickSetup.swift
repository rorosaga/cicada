import SwiftUI

/// Round-4 D5 (R-FA15) — the one-click paths on an agent's row, decided purely: Connect for me (Cicada runs the
/// wiring commands after the click, the Found row's Turn on), Copy setup prompt (the agent runs them itself),
/// Open in Cursor (the catalog's own deeplink), Set up Claude (a config merge the app performs).
enum AgentQuickAction: Equatable {
    case connectForMe([AgentWiringStep])
    case copyPrompt(String)
    case openCursor
    case setUpClaude
}

enum AgentQuickSetup {
    /// What an agent's open row offers. Connect for me only while the backend says the agent is installed, has
    /// steps, and is not already fully wired (a wired agent re-running `mcp add` fails, R-IA15). Copy setup prompt
    /// only for C5's harnesses and only a `kind: prompt` answer with text — against today's backend (a 404) there
    /// is no `setup`, so nothing new shows. Cursor and Claude desktop need nothing off the wire: their paths are
    /// computed by the app itself (R-FA15).
    static func actions(catalogId: String, setup: AgentSetupPrompt?, wiring: AgentWiring?) -> [AgentQuickAction] {
        var out: [AgentQuickAction] = []
        if let wiring, wiring.id == catalogId, wiring.installed, !wiring.connect.isEmpty,
           !(wiring.recall == "on" && wiring.autosave == "on") {
            out.append(.connectForMe(wiring.connect))
        }
        if AgentSetupCatalog.setupHarnesses.contains(catalogId), setup?.kind == "prompt",
           let prompt = setup?.prompt, !prompt.isEmpty {
            out.append(.copyPrompt(prompt))
        }
        if catalogId == "cursor" { out.append(.openCursor) }
        if catalogId == "claude-desktop" { out.append(.setUpClaude) }
        return out
    }

    /// The caption each Set up Claude outcome reads as — plain words, never the file's path (the row's manual
    /// step below already names it).
    static func caption(_ outcome: ClaudeDesktopConfig.Outcome) -> String {
        switch outcome {
        case .done: Copy.agentClaudeDone
        case .alreadySetUp: Copy.agentClaudeAlready
        case .claudeNotSetUp: Copy.agentClaudeNotSetUp
        case .leftUntouched: Copy.agentClaudeUnreadable
        case .failed(let why): why
        }
    }
}

/// The one-click block drawn first in an OPEN agent row, above the manual steps (which stay: they are the
/// fallback every action's failure points at). Buttons are `NeutralButton`s (DR-40, DR-44 — the brand-tinted
/// Cursor capsule is gone); a named service wears its real mark (DR-52).
struct AgentQuickSetupView: View {
    let agent: AgentSetup
    let actions: [AgentQuickAction]
    /// `Set(wiring.agents.compactMap(\.binary))` from the ONE `/agents/wiring` answer the page holds —
    /// `FoundTurnOn`'s argument. Never the steps' own argv[0]s, which would let any `…/claude` through the
    /// policy's binary check (R-FA15).
    let binaries: Set<String>
    let home: String
    let memoryRoot: String?
    let onConnected: () -> Void

    @State private var running = false
    @State private var connectCaption: (text: String, isProblem: Bool)?
    @State private var claudeCaption: (text: String, isProblem: Bool)?
    @State private var copied = false

    var body: some View {
        if !actions.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                ForEach(Array(actions.enumerated()), id: \.offset) { _, action in
                    view(for: action)
                }
            }
        }
    }

    @ViewBuilder
    private func view(for action: AgentQuickAction) -> some View {
        switch action {
        case .connectForMe(let steps): connectForMe(steps)
        case .copyPrompt(let text): copyPrompt(text)
        case .openCursor: openCursor
        case .setUpClaude: setUpClaude
        }
    }

    // MARK: Connect for me

    /// Spec decision 14 (D-1): the exact commands are on screen before the click that runs them.
    private func connectForMe(_ steps: [AgentWiringStep]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            caption(Copy.agentConnectHow)
            ForEach(steps, id: \.self) { step in CommandBox(command: step.display) }
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: running ? Copy.agentConnecting : Copy.agentConnectForMe,
                              leading: mark, isDisabled: running) {
                    run(steps)
                }
                if let connectCaption { outcome(connectCaption) }
            }
        }
    }

    private func run(_ steps: [AgentWiringStep]) {
        running = true
        connectCaption = nil
        Task { @MainActor in
            let result = await AgentConnect.run(steps, installRoot: BackendProcess.installRoot(), binaries: binaries)
            running = false
            switch result {
            case .done:
                connectCaption = (Copy.agentConnected, false)
                // Fetch the wiring again so a now-wired agent drops this action (R-FA15).
                onConnected()
            case .refused: connectCaption = (Copy.agentRefused, true)
            case .failed(let why): connectCaption = (why, true)
            }
        }
    }

    // MARK: Copy setup prompt

    /// The prompt is read before it is copied (R-FA15): a read-only box in the body face, so the person sees
    /// exactly what their agent will be asked to run.
    private func copyPrompt(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            ScrollView {
                Text(text)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(CicadaTheme.spacingSM)
            }
            .frame(maxHeight: CicadaTheme.scaled(180))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: copied ? Copy.agentCopied : Copy.agentCopyPrompt,
                              systemImage: copied ? "checkmark" : "doc.on.doc") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(text, forType: .string)
                    copied = true
                    Task { @MainActor in
                        try? await Task.sleep(for: .seconds(CicadaTiming.copiedConfirmation))
                        copied = false
                    }
                }
                caption(Copy.agentPromptHow(agent.name))
            }
        }
    }

    // MARK: Open in Cursor

    /// The catalog's own deeplink, never a URL off the wire (`AgentConnectPolicy`'s precedent). `URL(string:)`
    /// can fail on an odd home path, so a missing link draws nothing rather than crash.
    @ViewBuilder
    private var openCursor: some View {
        if let deeplink = agent.deeplink {
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.agentOpenInCursor, leading: mark) {
                    NSWorkspace.shared.open(deeplink.url)
                }
                caption(Copy.agentOpenInCursorHow)
            }
        }
    }

    // MARK: Set up Claude

    /// Built from the same python / server / memory root as `AgentSetupCatalog` — the wire's `config` is never
    /// trusted for a path or a value (R-FA15).
    private var setUpClaude: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.agentSetUpClaude, leading: mark) {
                    let memory = memoryRoot.flatMap { $0.isEmpty ? nil : $0 } ?? home + "/memory"
                    let server = ClaudeDesktopConfig.server(python: home + "/api/.venv/bin/python",
                                                            script: home + "/mcp/server.py", memory: memory)
                    let result = ClaudeDesktopConfig.apply(server: server, at: ClaudeDesktopConfig.configURL())
                    let problem: Bool = switch result {
                    case .done, .alreadySetUp: false
                    case .claudeNotSetUp, .leftUntouched, .failed: true
                    }
                    claudeCaption = (AgentQuickSetup.caption(result), problem)
                }
                if let claudeCaption { outcome(claudeCaption) } else { caption(Copy.agentSetUpClaudeHow) }
            }
        }
    }

    // MARK: Pieces

    /// DR-52 — the service a button acts on wears its real mark, clipped for the full-bleed plates
    /// (`claude-desktop`) the way `AgentTile` clips them.
    private var mark: AnyView? {
        guard LogoImage.exists(name: agent.id) else { return nil }
        return AnyView(LogoImage(name: agent.id, size: 14)
            .clipShape(CicadaTheme.shape(CicadaTheme.scaled(3))))
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func outcome(_ line: (text: String, isProblem: Bool)) -> some View {
        Text(line.text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(line.isProblem ? CicadaTheme.warning : CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}
