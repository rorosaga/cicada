import AppKit
import SwiftUI

/// Every sentence the local-source rows say, as pure functions (`LocalSourcesSurfaceTests`).
/// Plain and friendly (the owner's rule for app copy): no jargon, no prices,
/// every number through `UsageFormat.count`.
enum LocalSourceRowText {
    static func folderLine(_ channel: SourceChannel, onThisMac: Bool) -> String {
        onThisMac ? IntegrationRowState.line(channel) : LocalSourceCopy.folderMissing
    }

    static func wisprLine(_ channel: SourceChannel?, settings: WisprFlowSettings) -> String {
        guard settings.enabled else { return "Your meetings and notes from Wispr Flow on this Mac." }
        guard let channel else { return "On — the first sync is on its way" }
        return IntegrationRowState.line(channel)
    }

    /// "Found 12 notes · 3 written by an agent · 1,200 papers".
    static func previewSummary(_ r: FolderSyncResult, locale: Locale = .autoupdatingCurrent) -> String {
        let files = r.filesNew + r.filesChanged + r.filesUnchanged
        var parts = ["\(UsageFormat.count(files, locale: locale)) \(files == 1 ? "note" : "notes")"]
        if r.agentFiles > 0 { parts.append("\(UsageFormat.count(r.agentFiles, locale: locale)) written by an agent") }
        if r.papersFound > 0 {
            parts.append("\(UsageFormat.count(r.papersFound, locale: locale)) \(r.papersFound == 1 ? "paper" : "papers")")
        }
        return "Found " + parts.joined(separator: " · ")
    }

    /// How much of it Sleep will read — a count, never a price (the 2026-09-03 ruling).
    static func sleepLine(_ r: FolderSyncResult, locale: Locale = .autoupdatingCurrent) -> String {
        guard r.stage1Passes > 0 else { return "Nothing here for Sleep to read yet — an agent's notes are kept, not read." }
        let n = UsageFormat.count(r.stage1Passes, locale: locale)
        return "Sleep will read your own notes in about \(n) \(r.stage1Passes == 1 ? "step" : "steps")."
    }

    /// Comma or newline separated names → a clean list (Wispr Flow's meeting names; the
    /// agent-folder rules are a checklist now, R-HS17).
    static func list(_ text: String) -> [String] {
        text.split(whereSeparator: { $0 == "," || $0 == "\n" })
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }
}

/// A folder the person picked, waiting for the add sheet.
struct PickedFolder: Identifiable {
    let url: URL
    var id: String { url.path }
}

/// G133 — one watched folder in Settings → Integrations → Notes & files.
struct FolderChannelRow: View {
    let channel: SourceChannel
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var showManage = false

    private var folder: FolderRegistration? { localSources.folders.first { $0.channelId == channel.id } }

    var body: some View {
        let onThisMac = folder.map { localSources.isOnThisMac($0) } ?? false
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoImage.platformTile(name: "", size: CicadaTheme.scaled(28), systemFallback: OriginIconography.symbol(for: "folder"))
                VStack(alignment: .leading, spacing: 2) {
                    Text(channel.label)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(LocalSourceRowText.folderLine(channel, onThisMac: onThisMac))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(channel.lastError != nil ? CicadaTheme.danger : CicadaTheme.textSecondary)
                }
                Spacer()
                if let folder {
                    Button("Sync now") { Task { await localSources.syncNow(folder) } }
                        .buttonStyle(.bordered)
                        .disabled(!onThisMac || localSources.syncing.contains(channel.id))
                    Button("Manage") { showManage = true }
                        .buttonStyle(.bordered)
                }
            }
            // R-HS16 — a sheet, not a popover anchored to the row: at the panel's edge the
            // popover opened past the screen (the owner's report).
            .sheet(isPresented: $showManage) {
                if let folder {
                    FolderManagePanel(folder: folder) { showManage = false }
                }
            }
            if let folder, let error = localSources.folderErrors[folder.id] {
                Text(error)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
    }
}

/// "Add a folder" and "Obsidian vault" — the same flow: pick, name, look inside, watch.
struct AddFolderRow: View {
    let title: String
    let blurb: String
    let bundleId: String?
    let symbol: String
    let panelMessage: String
    @State private var picked: PickedFolder?
    /// A chosen folder under a refused root, said in the intake's own words.
    @State private var refused: String?

    static let obsidianBundleId = "md.obsidian"
    /// A LaunchServices lookup — a function, not a computed property, so a
    /// call site reads as work and never runs it per body evaluation
    /// (task 7 review r1). `IntegrationsView` asks once per appearance.
    static func isObsidianInstalled() -> Bool {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: obsidianBundleId) != nil
    }

    static var folder: AddFolderRow {
        AddFolderRow(title: "Add a folder of notes",
                     blurb: "Markdown notes, plans, reading lists — edits reach your memory on their own.",
                     bundleId: nil, symbol: "folder.badge.plus", panelMessage: "Choose a folder of notes to keep in memory")
    }

    static var obsidian: AddFolderRow {
        AddFolderRow(title: "Obsidian vault",
                     blurb: "A vault is a folder of notes — pick it and Cicada keeps up with your edits.",
                     bundleId: obsidianBundleId, symbol: OriginIconography.symbol(for: "obsidian"),
                     panelMessage: "Choose your Obsidian vault")
    }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            LogoImage.platformTile(name: "", bundleId: bundleId, size: CicadaTheme.scaled(28), systemFallback: symbol)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(blurb)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                if let refused {
                    Text(refused)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.warning)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer()
            Button("Choose…") { pick() }
                .buttonStyle(.bordered)
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .sheet(item: $picked) { picked in
            AddFolderSheet(url: picked.url) { self.picked = nil }
        }
    }

    private func pick() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = panelMessage
        panel.prompt = "Choose"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        refused = nil
        // The intake's refused roots (final review, finding 3): a watched
        // folder's bytes are read and posted on every change, so a folder
        // under `~/.claude`, `~/.codex` or `~/.cicada` is never watched.
        if let refusal = IntakeRouter.refusedRoot(of: [url]) {
            refused = refusal.panelText
            return
        }
        picked = PickedFolder(url: url)
    }
}

/// A label above its field, and a helper line under it when there is one. The owner's report:
/// the add-folder sheet had three placeholder-only fields and no labels, so once a field held text
/// nothing said what it was for (DR-33 — a form row names itself).
private struct LabeledField<Field: View>: View {
    let label: String
    var help: String? = nil
    @ViewBuilder let field: Field

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(label)
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            field
                .accessibilityLabel(label)
            if let help {
                Text(help)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// "Written by an agent" as a checklist of the folder's subfolders, plus "Choose a subfolder…" for
/// one deeper down (R-HS17). Nobody types a glob: each row is `<folder>/**` on the wire, and a
/// saved rule that is not one folder stays as its own ticked row, verbatim.
struct AgentFolderPicker: View {
    let root: URL?
    @Binding var rows: [AgentFolderRow]
    @Binding var message: String?

    var body: some View {
        LabeledField(label: Copy.Folders.writtenByAnAgent, help: Copy.Folders.writtenByAnAgentHelp) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if rows.isEmpty {
                    Text(Copy.Folders.noSubfolders)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                ForEach($rows) { $row in
                    Toggle(row.title, isOn: $row.isOn)
                        .toggleStyle(.checkbox)
                        .font(CicadaTheme.bodyFont)
                }
                if let root {
                    TextButton(title: Copy.Folders.chooseSubfolder) { choose(in: root) }
                }
            }
        }
    }

    /// The app reads the folder (G133); a pick outside it — or the folder itself — is refused in
    /// words rather than silently turned into a rule that matches nothing.
    private func choose(in root: URL) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        panel.directoryURL = root
        panel.prompt = "Choose"
        panel.message = Copy.Folders.chooseSubfolder
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard let path = AgentFolders.relativePath(of: url, under: root) else {
            message = Copy.Folders.pickInside(root.lastPathComponent)
            return
        }
        message = nil
        rows = AgentFolders.adding(path, to: rows)
    }
}

/// Name it, say which project it is, tick the parts an agent wrote, look
/// inside (counts only), then start watching.
struct AddFolderSheet: View {
    let url: URL
    let onDone: () -> Void
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var label: String
    @State private var projectName: String
    @State private var agentRows: [AgentFolderRow]
    @State private var folder: FolderRegistration?
    @State private var preview: FolderSyncResult?
    @State private var busy = false
    @State private var message: String?

    init(url: URL, onDone: @escaping () -> Void) {
        self.url = url
        self.onDone = onDone
        _label = State(initialValue: url.lastPathComponent)
        _projectName = State(initialValue: url.lastPathComponent)
        // R-HS17 — the app reads the folder it was just handed (G133: the backend never opens it);
        // `archive` is pre-ticked only when the folder has one, the old default glob's effect.
        _agentRows = State(initialValue: AgentFolders.initialRows(subfolders: AgentFolders.subfolders(in: url)))
    }

    var body: some View {
        SettingsSheet(title: Copy.Folders.addTitle, onClose: { Task { await cancel() } }) {
            Text(url.path)
                .font(CicadaTheme.font(size: 11, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            LabeledField(label: Copy.Folders.name) {
                TextField(Copy.Folders.name, text: $label, prompt: Text(url.lastPathComponent))
            }
            LabeledField(label: Copy.Folders.project, help: Copy.Folders.projectHelp) {
                TextField(Copy.Folders.project, text: $projectName)
            }
            AgentFolderPicker(root: url, rows: $agentRows, message: $message)
                .disabled(folder != nil)
            if let preview {
                Text(LocalSourceRowText.previewSummary(preview))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(LocalSourceRowText.sleepLine(preview))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            if let message {
                Text(message)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            // DR-40 — the sheet's one prominent action; the × is Cancel (it still removes a
            // looked-inside registration through `cancel()`).
            HStack {
                Spacer()
                PrimaryActionButton(title: preview == nil ? "Look inside" : "Start watching") {
                    Task { if preview == nil { await look() } else { await start() } }
                }
            }
        }
        .textFieldStyle(.roundedBorder)
        .disabled(busy)
    }

    /// Registers WITHOUT a project name (`projectName: ""`): the preview needs a
    /// folder id, but a person who looks inside and then cancels must not leave
    /// a new `project` page behind (R-LS13 creates one only on their say-so).
    private func look() async {
        busy = true
        defer { busy = false }
        do {
            let registered = try await localSources.addFolder(
                url: url, label: label, projectName: "", agentGlobs: AgentFolders.globs(agentRows))
            folder = registered
            preview = try await localSources.preview(registered, root: url)
            message = nil
        } catch {
            message = AddSourceSheet.friendlyError(error)
        }
    }

    /// "Start watching" is the say-so: the same `POST /sources/folders` again is
    /// an upsert on (device, path) (R-LS9) — same id — that now anchors the
    /// project by name (R-LS13) and takes any edit to the name fields.
    private func start() async {
        guard folder != nil else { return }
        busy = true
        defer { busy = false }
        do {
            let anchored = try await localSources.addFolder(
                url: url, label: label, projectName: projectName, agentGlobs: AgentFolders.globs(agentRows))
            await localSources.startWatching(anchored)
            onDone()
        } catch {
            message = AddSourceSheet.friendlyError(error)
        }
    }

    private func cancel() async {
        if let folder { try? await localSources.removeFolder(folder) }
        onDone()
    }
}

/// Which parts an agent wrote, and "Stop watching" (which keeps what was learned).
struct FolderManagePanel: View {
    let folder: FolderRegistration
    let onDone: () -> Void
    @Environment(LocalSourceWatcher.self) private var localSources
    /// Seeded on appear from the folder on disk and its saved rules (R-HS17): the listing needs
    /// the watcher's bookmark, which `init` cannot reach.
    @State private var rows: [AgentFolderRow] = []
    @State private var root: URL?
    @State private var confirmStop = false
    @State private var busy = false
    @State private var message: String?

    var body: some View {
        SettingsSheet(title: folder.label, onClose: onDone) {
            Text(folder.path)
                .font(CicadaTheme.font(size: 11, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            AgentFolderPicker(root: root, rows: $rows, message: $message)
            Text(Copy.Folders.manageHelp)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let message {
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            HStack {
                Button("Stop watching", role: .destructive) { confirmStop = true }
                Spacer()
                Button("Save") {
                    Task {
                        busy = true
                        defer { busy = false }
                        do {
                            try await localSources.updateAgentGlobs(folder, globs: AgentFolders.globs(rows))
                            message = nil
                            onDone()
                        } catch {
                            message = AddSourceSheet.friendlyError(error)
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .disabled(busy)
        .onAppear {
            root = localSources.root(of: folder)
            rows = AgentFolders.rows(subfolders: localSources.subfolders(of: folder), globs: folder.agentGlobs)
        }
        .confirmationDialog("Stop watching \(folder.label)?", isPresented: $confirmStop) {
            Button("Stop watching", role: .destructive) {
                Task {
                    try? await localSources.removeFolder(folder)
                    onDone()
                }
            }
        } message: {
            Text("Everything Cicada already learned from this folder stays in your memory.")
        }
    }
}

/// G134 — Wispr Flow in Settings → Integrations → Voice & meetings.
struct WisprFlowRow: View {
    let channel: SourceChannel?
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var showPanel = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoImage.platformTile(name: OriginIconography.logoName(for: "wispr-flow") ?? "",
                                       bundleId: OriginIconography.appBundleId(for: "wispr-flow"),
                                       size: CicadaTheme.scaled(28),
                                       systemFallback: OriginIconography.symbol(for: "wispr-flow"))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Wispr Flow")
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(LocalSourceRowText.wisprLine(channel, settings: localSources.wisprSettings))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(channel?.lastError != nil ? CicadaTheme.danger : CicadaTheme.textSecondary)
                }
                Spacer()
                if localSources.wisprSettings.enabled {
                    Button("Sync now") { Task { await localSources.syncWisprNow() } }
                        .buttonStyle(.bordered)
                        .disabled(localSources.syncing.contains(LocalSourceWatcher.wisprChannel))
                    Button("Manage") { showPanel = true }
                        .buttonStyle(.bordered)
                } else {
                    Button("Connect") { showPanel = true }
                        .buttonStyle(.bordered)
                }
            }
            // R-HS16 — a sheet, never a popover at the panel's edge.
            .sheet(isPresented: $showPanel) {
                WisprFlowPanel { showPanel = false }
            }
            if let error = localSources.wisprError, case .notReadable = error {
                FullDiskAccessHint(error: error)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
    }
}

/// Turn Wispr Flow on or off; dictation is opt-in; "your name in meetings" is
/// the only way a speaker is ever counted as the person (R-LS22, R-LS23).
struct WisprFlowPanel: View {
    let onDone: () -> Void
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var includeDictation = false
    @State private var names = ""
    @State private var busy = false
    @State private var message: String?

    var body: some View {
        SettingsSheet(title: "Wispr Flow", onClose: onDone) {
            Text("Your meetings — with who said what — and your Scratchpad notes come in on their own.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Toggle("Also include my dictation history", isOn: $includeDictation)
            Text("Everything you've dictated into other apps, one entry per day. Password managers are always left out.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField("Your name in meetings", text: $names)
                .textFieldStyle(.roundedBorder)
            Text("So your own words are credited to you — everyone else's stay theirs.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let message {
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            HStack {
                if localSources.wisprSettings.enabled {
                    Button("Turn off", role: .destructive) { save(enabled: false) }
                }
                Spacer()
                Button(localSources.wisprSettings.enabled ? "Save" : "Turn on") { save(enabled: true) }
                    .buttonStyle(.borderedProminent)
            }
        }
        .disabled(busy)
        .onAppear {
            includeDictation = localSources.wisprSettings.includeDictation
            names = localSources.wisprSettings.ownerSpeakerNames.joined(separator: ", ")
        }
    }

    private func save(enabled: Bool) {
        Task {
            busy = true
            defer { busy = false }
            do {
                try await localSources.setWispr(WisprFlowSettings(
                    enabled: enabled, includeDictation: includeDictation,
                    ownerSpeakerNames: LocalSourceRowText.list(names)))
                message = nil
                onDone()
            } catch {
                message = AddSourceSheet.friendlyError(error)
            }
        }
    }
}
