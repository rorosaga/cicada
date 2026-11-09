import SwiftUI

/// The pure decisions of choosing what a sign-in may read (owner 2026-11-09), hoisted so they are testable without
/// SwiftUI. The choice itself lives behind the backend (`/sources/connectors/{id}/scope`); the app is one client.
enum ConnectorScopeState {
    static let everything = "everything"
    static let chosen = "chosen"

    /// Just connected, nothing chosen yet: the backend reads nothing until the person picks.
    static func isPending(_ status: ConnectorStatus) -> Bool {
        status.connected && status.chooses == true && status.scope == "pending"
    }

    /// The one line a connected, choosable source shows beside "Change".
    static func summaryLine(_ status: ConnectorStatus) -> String? {
        guard status.connected, status.chooses == true else { return nil }
        switch status.scope {
        case "pending": return Copy.Connect.waitingToChoose
        case "chosen": return Copy.Connect.readingChosen(status.scopeCount ?? 0, noun: status.chooseNoun ?? "")
        default: return Copy.Connect.readingEverything
        }
    }

    /// Everything can always be saved; a chosen list needs at least one item (choosing nothing is not a choice).
    static func canSave(mode: String, picked: [ConnectorScopeItem]) -> Bool {
        mode == everything || !picked.isEmpty
    }

    static func toggled(_ picked: [ConnectorScopeItem], _ item: ConnectorScopeItem) -> [ConnectorScopeItem] {
        picked.contains(where: { $0.id == item.id }) ? picked.filter { $0.id != item.id } : picked + [item]
    }

    /// The list on screen: what is picked first (narrowed by the typed words), then the service's results.
    static func displayed(picked: [ConnectorScopeItem], results: [ConnectorScopeItem],
                          query: String) -> [ConnectorScopeItem] {
        let needle = query.trimmingCharacters(in: .whitespaces).lowercased()
        let mine = needle.isEmpty ? picked : picked.filter { $0.title.lowercased().contains(needle) }
        let ids = Set(mine.map(\.id))
        return mine + results.filter { !ids.contains($0.id) }
    }
}

/// The picker: Everything, or specific containers, searchable. Shown in place of "Refresh" right after a sign-in
/// (nothing is read before it is answered) and from "Change" later.
///
/// DR-42 (radio rows, one tap), DR-44 (`Tag` for the kind), DR-46/DR-76 (`cicadaField` search), DR-48 (`rowHover` rows),
/// DR-40 (one `PrimaryActionButton`), DR-5 (selection is a neutral check, never the accent).
struct ConnectorScopePicker: View {
    let status: ConnectorStatus
    /// Nil while pending: the sign-in cannot be left unanswered, so there is nothing to cancel back to.
    var onCancel: (() -> Void)? = nil
    /// Called once the choice is saved; the caller starts the first read.
    let onSaved: () async -> Void

    @State private var mode = ConnectorScopeState.chosen
    @State private var picked: [ConnectorScopeItem] = []
    @State private var results: [ConnectorScopeItem] = []
    @State private var more = false
    @State private var query = ""
    @State private var loading = true
    @State private var saving = false
    @State private var unchooseWords = ""
    @State private var error: String?
    @State private var searchTask: Task<Void, Never>?

    private var noun: String { status.chooseNoun ?? "items" }
    private var pending: Bool { ConnectorScopeState.isPending(status) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.Connect.chooseTitle)
                .font(CicadaTheme.font(size: 12, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            if pending {
                Text(Copy.Connect.chooseNothingYet)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            ModeRow(label: status.chooseEverything ?? "Everything", selected: mode == ConnectorScopeState.everything) {
                mode = ConnectorScopeState.everything
            }
            ModeRow(label: status.chooseChosen ?? "Only what I pick", selected: mode == ConnectorScopeState.chosen) {
                mode = ConnectorScopeState.chosen
            }
            if mode == ConnectorScopeState.chosen { chooser }
            if !pending, !unchooseWords.isEmpty {
                Text(unchooseWords)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let error {
                Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                if mode == ConnectorScopeState.chosen {
                    Text(Copy.Connect.chooseCount(picked.count, noun: noun))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let onCancel {
                    TextButton(title: Copy.Connect.cancel) { onCancel() }.disabled(saving)
                }
                PrimaryActionButton(title: pending ? Copy.Connect.chooseStart : Copy.Connect.chooseSave) {
                    Task { await save() }
                }
                .disabled(saving || !ConnectorScopeState.canSave(mode: mode, picked: picked))
                .help(ConnectorScopeState.canSave(mode: mode, picked: picked)
                      ? "" : "Pick at least one, or choose everything.")
            }
        }
        .task { await load() }
        .onDisappear { searchTask?.cancel() }
    }

    @ViewBuilder
    private var chooser: some View {
        TextField("", text: $query)
            .textFieldStyle(.plain)
            .cicadaField(prompt: Copy.Connect.chooseSearch(noun), isEmpty: query.isEmpty)
            .onChange(of: query) { _, _ in scheduleSearch() }
        let rows = ConnectorScopeState.displayed(picked: picked, results: results, query: query)
        if loading && rows.isEmpty {
            Text(Copy.Connect.chooseLoading).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        } else if rows.isEmpty {
            Text(Copy.Connect.chooseNothingFound).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(rows) { item in
                        ItemRow(item: item, isOn: picked.contains(where: { $0.id == item.id })) {
                            picked = ConnectorScopeState.toggled(picked, item)
                        }
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(220))
        }
        if more {
            Text(Copy.Connect.chooseMore).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func load() async {
        do {
            let scope = try await APIClient.shared.connectorScope(status.id)
            unchooseWords = scope.unchooseWords
            if scope.mode == "chosen" { picked = scope.items; mode = ConnectorScopeState.chosen }
            else if scope.mode == "everything" { mode = ConnectorScopeState.everything }
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
        await search()
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            if Task.isCancelled { return }
            await search()
        }
    }

    private func search() async {
        loading = true
        defer { loading = false }
        do {
            let found = try await APIClient.shared.connectorContainers(status.id, query: query)
            results = found.items
            more = found.more
            error = nil
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            _ = try await APIClient.shared.setConnectorScope(
                status.id, mode: mode, items: mode == ConnectorScopeState.chosen ? picked : [])
            error = nil
            await onSaved()
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }
}

/// DR-42's radio row, one tap: a 16 pt ring, the label.
private struct ModeRow: View {
    let label: String
    let selected: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ZStack {
                    Circle().strokeBorder(CicadaTheme.textTertiary, lineWidth: 1.5)
                    if selected { Circle().fill(CicadaTheme.textPrimary).frame(width: 6, height: 6) }
                }
                .frame(width: CicadaTheme.scaled(16), height: CicadaTheme.scaled(16))
                Text(label)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(32))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: selected)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

private struct ItemRow: View {
    let item: ConnectorScopeItem
    let isOn: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Toggle(isOn: Binding(get: { isOn }, set: { _ in action() })) {
                Text(item.title)
                    .font(CicadaTheme.font(size: 13))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
            }
            .toggleStyle(NeutralCheckToggleStyle())
            Spacer(minLength: CicadaTheme.spacingSM)
            Tag(text: item.kind)
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .frame(height: CicadaTheme.scaled(32))
        .rowHover($hovering)
    }
}

/// The picker on a connected source's own page (owner 2026-11-09: "that should be right after connecting"): a
/// connection with nothing chosen yet shows the picker open, with nothing read behind it; a chosen one is a line and
/// "Change". Draws nothing for a source with nothing to choose from. The sign-in sheet (`ConnectorSetupPanel`) shows
/// the same picker, so the page steps aside while the sheet is up.
struct ConnectorScopeBlock: View {
    let connectorId: String
    /// Changes when the page's connection did (connected, synced), so the block reads its state again.
    let refreshID: String
    var suppressed = false

    @Environment(Store.self) private var store
    @State private var status: ConnectorStatus?
    @State private var choosing = false
    @State private var note: String?

    var body: some View {
        // A stack, not a Group: a Group with nothing in it carries no `.task`, and the block must load to know.
        VStack(alignment: .leading, spacing: 0) {
            if !suppressed, let status, status.connected, status.chooses == true {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    if ConnectorScopeState.isPending(status) || choosing {
                        ConnectorScopePicker(status: status,
                                             onCancel: ConnectorScopeState.isPending(status) ? nil : { choosing = false }) {
                            choosing = false
                            do {
                                note = ConnectorSetupState.syncSummary(try await APIClient.shared.syncConnector(connectorId))
                            } catch {
                                note = AddSourceSheet.friendlyError(error)
                            }
                            await store.refresh([.channels, .sources, .sourcesOverview, .status])
                            await load()
                        }
                    } else if let line = ConnectorScopeState.summaryLine(status) {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Text(line)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                            TextButton(title: Copy.Connect.chooseChange, inline: true) { choosing = true }
                                .accessibilityLabel("Change what \(status.label) is read for")
                        }
                    }
                    if let note {
                        Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
        }
        .task(id: refreshID + (suppressed ? "-sheet" : "")) { await load() }
    }

    private func load() async {
        status = try? await APIClient.shared.fetchConnectors().first { $0.id == connectorId }
    }
}
