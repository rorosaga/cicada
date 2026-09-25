import SwiftUI

/// Settings → Agents → "Remembers automatically" (G149). The page's other
/// groups wire the MCP server, so the agent asks Cicada when it thinks to.
/// This group is the recall hooks: before the agent answers, Cicada adds a
/// short note about the people and projects the message names, so a model
/// that never thinks to ask still sees what the person already told Cicada.
///
/// Each row carries the agent's real mark (DR-52), its state in words, and one
/// neutral button (DR-40, disabled with a reason while it runs, DR-41): Turn
/// on, Update or Turn off. The button runs the backend's argv through
/// `AgentConnect` only after the click, and the exact commands are one
/// collapsed disclosure away (DR-39; spec decision 14). The group is its own
/// file plus one line in `ConnectView`, because another round-4 track owns the
/// rest of that page (R-H18).
struct AutoRecallGroup: View {
    @State private var model = AutoRecallModel()
    @AppStorage("cicada.agents.autoRecallCommands") private var showCommands = false
    @Environment(Store.self) private var store

    var body: some View {
        SettingsGroupCard(header: Copy.autoRecallGroup) {
            SettingsRow(.agentsAutoRecall, title: Copy.autoRecallTitle, detail: leadDetail)
            ForEach(model.rows) { agent in
                SettingsDivider()
                AutoRecallRow(agent: agent, model: model, showCommands: $showCommands)
            }
        }
        // The SSE reachability flip asks again, like ConnectView's own probe: no second poller.
        .task(id: store.isConnected) { await model.load() }
    }

    /// One line that changes rather than a second line (DR-38).
    private var leadDetail: String { AutoRecall.lead(loaded: model.loaded, wiring: model.wiring) }
}

private struct AutoRecallRow: View {
    let agent: AgentWiring
    let model: AutoRecallModel
    @Binding var showCommands: Bool

    var body: some View {
        let state = AutoRecall.state(of: agent)
        let action = AutoRecall.action(for: agent)
        let working = model.working.contains(agent.id)
        let failure = model.failures[agent.id]
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                // The one precedence map (Track L), so a harness id and its mark never drift.
                LogoImage.platformTile(name: OriginIconography.logoName(for: agent.id) ?? "",
                                       size: CicadaTheme.scaled(20), systemFallback: "terminal")
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(AutoRecall.name(agent.id))
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(failure ?? AutoRecall.detail(state))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(failure == nil ? CicadaTheme.textSecondary : CicadaTheme.warning)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: CicadaTheme.scaled(16))
                if let action {
                    NeutralButton(title: working ? Copy.autoRecallWorking : action.title, size: .compact,
                                  isDisabled: working, disabledHelp: Copy.autoRecallWorkingHelp) {
                        Task { await model.perform(agent) }
                    }
                }
            }
            if agent.id == "codex" && state != .unreadable {
                Text(Copy.autoRecallCodexTrust)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if model.refused[agent.id] != nil {
                Text(Copy.foundRefused)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let action {
                TextButton(title: Copy.foundWhatThisChanges) { showCommands.toggle() }
                    .accessibilityValue(showCommands ? "Expanded" : "Collapsed")
                if showCommands {
                    CommandBox(command: action.steps.map(\.display).joined(separator: "\n"))
                    Text(Copy.autoRecallChanges(action.touches))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .padding(.vertical, CicadaTheme.spacingSM + CicadaTheme.scaled(2))
        .padding(.horizontal, CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .settingsRow(.autoRecall(agent.id))
    }
}
