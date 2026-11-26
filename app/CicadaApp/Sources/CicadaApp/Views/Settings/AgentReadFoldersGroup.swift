import AppKit
import SwiftUI

/// Settings → Privacy & data → "Folders its agent may read" (ruling 84, 2026-11-26): the rule proposes, the person disposes.
/// One row per folder of the home — its name, the reason as secondary text, a switch — then "Add a folder…", which uses the
/// system folder panel and sends only the path (the app never reads the folder; the backend resolves it and refuses what can
/// never be read, in words). A folder the rule keeps closed for good (Cicada's own, too large to check) shows its switch off
/// and unavailable with the reason (DR-41); the folders macOS protects are one sentence under the list, never nine rows.
///
/// Design rules applied: DR-38 (the card's header is not repeated by a title row, one lead sentence says it once), DR-40/DR-41
/// (the system switch with its label hidden and spoken; disabled dims and keeps its words), DR-34 (a two-line row: name over
/// reason), DR-5 (no accent: the switch is the system's), DR-9 (the card's own ring, no shadow), DR-60 (a switch never animates
/// the list).
struct AgentReadFoldersGroup: View {
    @State private var model: AgentReadFoldersModel
    @Environment(Store.self) private var store

    /// A test or a render passes its own model; Settings uses the live one.
    @MainActor
    init(model: AgentReadFoldersModel? = nil) { _model = State(initialValue: model ?? AgentReadFoldersModel()) }

    var body: some View {
        SettingsGroupCard(header: Copy.AgentReadFolders.groupHeader) {
            note(Copy.AgentReadFolders.lead)
            if let list = model.list {
                ForEach(list.shown) { folder in
                    SettingsDivider()
                    row(folder)
                }
                SettingsDivider()
                addRow
                if let text = Copy.AgentReadFolders.protectedNote(list.protectedNames) {
                    SettingsDivider()
                    note(text)
                }
            } else {
                SettingsDivider()
                note(model.loadFailed ? Copy.AgentReadFolders.unavailable : Copy.AgentReadFolders.loading)
            }
            if let message = model.note {
                SettingsDivider()
                note(message, warning: true)
            }
        }
        .settingsRow(.agentReadFolders)
        // The SSE reachability flip asks again, like the page's other groups: no poller of its own.
        .task(id: store.isConnected) { await model.load() }
    }

    private func row(_ folder: AgentReadFolder) -> some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(folder.name)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(folder.reason)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: CicadaTheme.scaled(16))
            Toggle(Copy.AgentReadFolders.switchLabel(folder.name), isOn: Binding(
                get: { folder.granted },
                set: { value in Task { await model.set(folder.id, on: value) } }))
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
                .disabled(folder.locked || model.busy.contains(folder.id))
                .help(folder.locked ? folder.reason : "")
        }
        .padding(.vertical, CicadaTheme.spacingSM + CicadaTheme.scaled(2))
        .padding(.horizontal, CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .contextMenu {
            if folder.added {
                Button(Copy.AgentReadFolders.removeFolder) { Task { await model.remove(folder.id) } }
            }
        }
    }

    private var addRow: some View {
        HStack {
            NeutralButton(title: Copy.AgentReadFolders.addFolder, size: .compact) { pick() }
                .help(Copy.AgentReadFolders.addHelp)
            Spacer(minLength: 0)
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingMD)
    }

    /// The system panel opens on the home folder; the app sends the chosen path and nothing else, and never opens the folder.
    private func pick() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser
        panel.message = Copy.AgentReadFolders.panelMessage
        panel.prompt = Copy.AgentReadFolders.panelPrompt
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await model.add(path: url.path) }
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
