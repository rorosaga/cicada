import SwiftUI

/// the Agents page → "Editing pages" (G198, owner ruling 2026-10-14: "a list of trusted models or agents that we give
/// permission to write into the page directly"). One row per agent on this Mac with a switch: an agent that is on
/// fixes a page's words or aliases at once, its reason in the page's history; any other agent's edit waits in the
/// inbox for one tap (UX principle 3). Until the person changes the list, the backend's defaults are on (owner,
/// 2026-10-14: Claude Code and Codex) and a note under the header says so, naming them from the response. The list lives outside every bank (`GET/PUT /settings/editors`); it is read
/// when the page appears and each switch is written optimistically, put back with the server's sentence on refusal.
///
/// Its own file plus one line in `ConnectView`, like `AutoRecallGroup`. Marks are the shared Track L marks (DR-52),
/// the switch is the system switch with its label hidden and spoken (DR-40/DR-41), copy names only the agent's app.
struct PageEditorsGroup: View {
    @State private var model = PageEditorsModel()
    @Environment(Store.self) private var store

    var body: some View {
        SettingsGroupCard(header: Copy.PageEdits.groupHeader) {
            SettingsRow(.agentsEditors, title: Copy.PageEdits.rowTitle, detail: Copy.PageEdits.rowDetail)
            if let editors = model.editors {
                if !editors.customized, let text = Copy.PageEdits.defaultsNote(editors.defaults.map(\.label)) {
                    SettingsDivider()
                    note(text)
                }
                if editors.rows.isEmpty {
                    SettingsDivider()
                    note(Copy.PageEdits.noAgents)
                }
                ForEach(editors.rows) { agent in
                    SettingsDivider()
                    row(agent, editors: editors)
                }
            } else {
                SettingsDivider()
                note(model.loadFailed ? Copy.PageEdits.unavailable : Copy.PageEdits.loading)
            }
            if let message = model.note {
                SettingsDivider()
                note(message, warning: true)
            }
        }
        // The SSE reachability flip asks again, like the page's other groups: no poller of its own.
        .task(id: store.isConnected) { await model.load() }
    }

    private func row(_ agent: PageEditor, editors: PageEditorsResponse) -> some View {
        let on = editors.isTrusted(agent.harness)
        return HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            LogoImage.platformTile(name: OriginIconography.logoName(for: agent.harness) ?? "",
                                   size: CicadaTheme.scaled(20), systemFallback: "terminal")
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(agent.label)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(PageEditorsWords.detail(agent.harness, in: editors))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer(minLength: CicadaTheme.scaled(16))
            Toggle(Copy.PageEdits.switchLabel(agent.label), isOn: Binding(
                get: { on },
                set: { value in Task { await model.set(agent.harness, on: value) } }))
                .toggleStyle(.switch)
                .labelsHidden()
                .disabled(model.busy.contains(agent.harness))
        }
        .padding(.vertical, CicadaTheme.spacingSM + CicadaTheme.scaled(2))
        .padding(.horizontal, CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func note(_ text: String, warning: Bool = false) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(warning ? CicadaTheme.warning : CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, CicadaTheme.spacingSM)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The words beside each agent's switch — pure and tested.
enum PageEditorsWords {
    static func detail(_ harness: String, in editors: PageEditorsResponse,
                       locale: Locale = .autoupdatingCurrent) -> String {
        guard let trusted = editors.trusted.first(where: { $0.harness == harness }) else {
            return Copy.PageEdits.asksFirst
        }
        guard let day = EntityDates.shortDay(trusted.since, locale: locale) else {
            // A default the person never set has no day it was granted on.
            return editors.isDefault(harness) ? Copy.PageEdits.onByDefault : Copy.PageEdits.allowed
        }
        return Copy.PageEdits.allowedSince(day)
    }
}
