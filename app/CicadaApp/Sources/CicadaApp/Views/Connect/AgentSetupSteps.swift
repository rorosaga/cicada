import SwiftUI
import AppKit

/// Round 4 C8 — the selected agent's numbered steps: a header ("Connect <name>", found on this Mac or in the
/// cloud, "● Connected" once Cicada has seen it), one row per `AgentStep`, then the autosave honesty line and an
/// optional footer. A renderer only: what each step says and offers is `AgentSteps.steps`, a pure table
/// (`AgentStepsTests`), so Settings → Agents and phase B's onboarding read one source of words.
///
/// R-AG17 — the four one-click actions that lived in `AgentQuickSetupView` live here, unchanged in behaviour:
/// Connect for me shows its exact commands before the click that runs them (spec decision 14, D-1) and runs only
/// through `AgentConnect.run` with the ONE wiring answer's binaries (R-FA15); Copy setup prompt shows the prompt
/// before it is copied; Open in Cursor opens the app's own catalog link, never one off the wire; Set up Claude
/// merges a server entry the app computed itself. Every service a button acts on wears its real mark (DR-52);
/// buttons are `NeutralButton` / `TextButton` (DR-40) and the one pill is `Tag` (DR-44).
struct AgentSetupSteps: View {
    let entry: AgentCatalogEntry
    let steps: [AgentStep]
    let header: String?
    let honesty: String?
    let connected: Bool
    var footer: String? = nil
    /// `Set(wiring.agents.compactMap(\.binary))` from the one `/agents/wiring` answer the host holds —
    /// `AgentConnect.run`'s policy argument, never the steps' own argv[0]s (R-FA15).
    let binaries: Set<String>
    let home: String
    let memoryRoot: String?
    /// The app's own Cursor install link (`AgentSetupCatalog`), never a URL off the wire.
    let deeplink: URL?
    let onConnected: () -> Void
    let onOpenFromAnywhere: () -> Void
    let onCreateLink: (RemoteApp) -> Void

    @State private var running = false
    @State private var connectCaption: Outcome?
    @State private var claudeCaption: Outcome?
    @State private var copied = false

    private struct Outcome: Equatable {
        let text: String
        let isProblem: Bool
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            headerRow
            ForEach(steps) { step in stepRow(step) }
            if honesty != nil || footer != nil {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    if let honesty { caption(honesty) }
                    if let footer { caption(footer) }
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        // A new agent starts from a clean slate: last agent's "Copied" or failure caption is not this one's.
        .onChange(of: entry.id) { _, _ in
            running = false; connectCaption = nil; claudeCaption = nil; copied = false
        }
    }

    // MARK: Header

    private var headerRow: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            AgentMark(entry: entry, size: 24)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(Copy.agentConnectTitle(entry.name))
                    .font(CicadaTheme.font(size: 14, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                if let header { caption(header, color: CicadaTheme.textSecondary) }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if connected {
                HStack(spacing: CicadaTheme.scaled(5)) {
                    Circle().fill(CicadaTheme.success)
                        .frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
                    Text(Copy.agentConnectedBadge)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .accessibilityElement(children: .combine)
            }
        }
    }

    // MARK: A step

    private func stepRow(_ step: AgentStep) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                number(step)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Text(step.title)
                            .font(CicadaTheme.font(size: 13, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary)
                        if step.advanced { Tag(text: Copy.agentStepAdvanced) }
                    }
                    caption(step.detail, color: CicadaTheme.textSecondary)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if step.isConfirm, let trailing = step.trailing {
                    Text(trailing)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(step.done ? CicadaTheme.success : CicadaTheme.textTertiary)
                        .multilineTextAlignment(.trailing)
                } else if !step.actions.isEmpty {
                    VStack(alignment: .trailing, spacing: CicadaTheme.spacingXS) {
                        ForEach(Array(step.actions.enumerated()), id: \.offset) { _, action in actionView(action) }
                    }
                }
            }
            if let snippet = step.snippet { promptBox(snippet) }
            if let steps = connectSteps(step) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    caption(Copy.agentConnectHow)
                    ForEach(steps, id: \.self) { CommandBox(command: $0.display) }
                    if let connectCaption { outcome(connectCaption) }
                }
                .padding(.leading, CicadaTheme.scaled(28))
            }
            if step.actions.contains(.setUpClaude) {
                Group {
                    if let claudeCaption { outcome(claudeCaption) } else { caption(Copy.agentSetUpClaudeHow) }
                }
                .padding(.leading, CicadaTheme.scaled(28))
            }
        }
    }

    /// The numbered 20 pt ring, or the green ✓ once the step is done.
    @ViewBuilder
    private func number(_ step: AgentStep) -> some View {
        let side = CicadaTheme.scaled(20)
        if step.done {
            Image(systemName: "checkmark.circle.fill")
                .font(CicadaTheme.font(size: 18))
                .foregroundStyle(CicadaTheme.success)
                .frame(width: side, height: side)
                .accessibilityLabel("\(step.id)")
        } else {
            Text("\(step.id)")
                .font(CicadaTheme.font(size: 11, weight: .medium))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: side, height: side)
                .overlay(Circle().strokeBorder(CicadaTheme.textTertiary, lineWidth: 1))
        }
    }

    private func connectSteps(_ step: AgentStep) -> [AgentWiringStep]? {
        for action in step.actions { if case .connectForMe(let steps) = action { return steps } }
        return nil
    }

    // MARK: Actions

    @ViewBuilder
    private func actionView(_ action: AgentStep.Action) -> some View {
        switch action {
        case .connectForMe(let steps):
            NeutralButton(title: running ? Copy.agentConnecting : Copy.agentConnectForMe,
                          leading: mark(of: entry), isDisabled: running) { run(steps) }
        case .copy(let text):
            NeutralButton(title: copied ? Copy.agentCopied : Copy.agentCopyPrompt,
                          systemImage: copied ? "checkmark" : "doc.on.doc") { copy(text) }
        case .openCursor:
            if let deeplink {
                NeutralButton(title: Copy.agentOpenInCursor, leading: mark(of: entry)) {
                    NSWorkspace.shared.open(deeplink)
                }
            }
        case .setUpClaude:
            NeutralButton(title: Copy.agentSetUpClaude, leading: mark(of: entry)) { setUpClaude() }
        case .openFromAnywhere:
            TextButton(title: Copy.agentOpenFromAnywhere, action: onOpenFromAnywhere)
        case .createLink(let app, let enabled):
            NeutralButton(title: Copy.agentCreateLink, leading: mark(of: entry), isDisabled: !enabled,
                          disabledHelp: Copy.agentNeedsReach) { onCreateLink(app) }
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
                connectCaption = Outcome(text: Copy.agentConnected, isProblem: false)
                // Fetch the wiring again so a now-wired agent drops this action (R-FA15).
                onConnected()
            case .refused: connectCaption = Outcome(text: Copy.agentRefused, isProblem: true)
            case .failed(let why): connectCaption = Outcome(text: why, isProblem: true)
            }
        }
    }

    private func copy(_ text: String) {
        AppPasteboard.copy(text)
        copied = true
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(CicadaTiming.copiedConfirmation))
            copied = false
        }
    }

    /// Built from the same python / server / memory root as `AgentSetupCatalog` — the wire's `config` is never
    /// trusted for a path or a value (R-FA15).
    private func setUpClaude() {
        let memory = memoryRoot.flatMap { $0.isEmpty ? nil : $0 } ?? home + "/memory"
        let server = ClaudeDesktopConfig.server(python: home + "/api/.venv/bin/python",
                                                script: home + "/mcp/server.py", memory: memory)
        let result = ClaudeDesktopConfig.apply(server: server, at: ClaudeDesktopConfig.configURL())
        let problem: Bool = switch result {
        case .done, .alreadySetUp: false
        case .claudeNotSetUp, .leftUntouched, .failed: true
        }
        claudeCaption = Outcome(text: AgentQuickSetup.caption(result), isProblem: problem)
    }

    // MARK: Pieces

    /// The prompt, read before it is copied (R-FA15): a read-only box in the body face, so the person sees exactly
    /// what their agent will be asked to do. Private to screen captures — it carries this Mac's paths.
    private func promptBox(_ text: String) -> some View {
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
        .privacySensitive()
        .padding(.leading, CicadaTheme.scaled(28))
    }

    /// DR-52 — the service a button acts on wears its real mark, 14 pt; nil when it has none (Grok's glyph is
    /// already beside the header, and a glyph inside a button would read as an icon, not a brand).
    private func mark(of entry: AgentCatalogEntry) -> AnyView? {
        guard let name = entry.mark, LogoImage.exists(name: name) else { return nil }
        return AnyView(AgentMark(entry: entry, size: 14))
    }

    private func caption(_ text: String, color: Color = CicadaTheme.textTertiary) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func outcome(_ line: Outcome) -> some View {
        Text(line.text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(line.isProblem ? CicadaTheme.warning : CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}
