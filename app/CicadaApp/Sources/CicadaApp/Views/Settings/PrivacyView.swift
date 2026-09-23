import AppKit
import SwiftUI
import UniformTypeIdentifiers   // `UTType.zip` for the save panel

/// Settings → Privacy & data (G139, design §2.2): where the memory lives, its
/// banks and how to take one away or put one in the trash (R-O18…R-O20), what
/// reaches the internet (the three gates, R-O21), the usage ledger, keys,
/// access from other apps, and the transcript rail stated as a fact.
///
/// It exports and deletes; it never switches (R-O18). Switch, new, copy and
/// rename stay in the Graph page's `BankSwitcher`, whose switch reloads the
/// graph through a main-window object — a second switcher here would be the
/// bank split-brain class.
struct PrivacyView: View {
    @Environment(Store.self) private var store
    @Environment(ConnectionsViewModel.self) private var connectionsVM
    @State private var memoryRoot: String?
    @State private var remoteLine: String?
    @State private var pendingDelete: MemoryBank?
    @State private var confirmRemoveKeys = false
    @State private var exporting: String?
    @State private var exportNote: String?
    @State private var deleteProblem: String?

    private var banks: [MemoryBank] { store.banks.value?.banks ?? [] }
    /// The active bank and the one that IS the memory folder are never
    /// offered; the backend 409s on both anyway (R-O18).
    private var deletable: [MemoryBank] { banks.filter { !$0.active && !$0.legacy } }
    private var status: StatusSnapshot? { store.status.value }
    private var keyed: [ConnectionStatus] { (store.connections.value ?? []).filter { $0.isKeyBased && $0.connected } }

    var body: some View {
        SettingsPage(section: .privacy) {
            SettingsGroupCard {
                SettingsRow(.memoryLocation, title: Copy.memoryLocationTitle, detail: memoryRoot) {
                    Button(Copy.showInFinder) {
                        if let root = memoryRoot { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: root)]) }
                    }
                    .disabled(memoryRoot == nil)
                }
                .privacySensitive()
            }
            SettingsGroupCard(header: Copy.banksTitle) {
                SettingsRow(.banks, title: Copy.banksTitle, detail: Copy.banksDetail) { EmptyView() } below: {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        ForEach(banks) { bank in
                            HStack(spacing: CicadaTheme.spacingSM) {
                                Text(bank.name).font(CicadaTheme.bodyFont)
                                if bank.active {
                                    Text(Copy.bankActive).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.accent)
                                }
                                Spacer()
                                Text(Copy.bankCounts(entities: bank.entityCount, episodes: bank.episodeCount))
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textTertiary)
                            }
                        }
                    }
                }
                SettingsDivider()
                SettingsRow(.bankExport, title: Copy.bankExportTitle, detail: exporting ?? exportNote ?? Copy.bankExportDetail) {
                    Menu(Copy.exportMenu) {
                        ForEach(banks) { bank in Button(bank.name) { export(bank) } }
                    }
                    .fixedSize()
                    .disabled(exporting != nil || banks.isEmpty)
                }
                SettingsDivider()
                SettingsRow(.bankDelete, title: Copy.bankDeleteTitle, detail: deleteProblem ?? Copy.bankDeleteDetail) {
                    Menu(Copy.deleteMenu) {
                        ForEach(deletable) { bank in Button(bank.name, role: .destructive) { pendingDelete = bank } }
                    }
                    .fixedSize()
                    .disabled(deletable.isEmpty)
                }
            }
            SettingsGroupCard(header: Copy.reachingTheInternet) {
                // Spelled out, not through a helper: `SettingsRowLintTests` finds a
                // row by its literal `SettingsRow(.<id>,`.
                SettingsRow(.outboundConnectors, title: Copy.outboundConnectorsTitle, detail: Copy.outboundConnectorsDetail) {
                    gateValue(status?.gates?.connectorFetch)
                }
                SettingsDivider()
                SettingsRow(.outboundFeeds, title: Copy.outboundFeedsTitle, detail: Copy.outboundFeedsDetail) {
                    gateValue(status?.gates?.feedFetch)
                }
                SettingsDivider()
                SettingsRow(.outboundLogos, title: Copy.outboundLogosTitle, detail: Copy.outboundLogosDetail) {
                    gateValue(status?.gates?.logoFetch)
                }
            }
            SettingsGroupCard {
                SettingsRow(.telemetry, title: Copy.telemetryTitle,
                            detail: status?.telemetry.map { $0 == "off" ? Copy.telemetryOff : "\(Copy.telemetryOn) \(Copy.telemetryHow)" })
                SettingsDivider()
                SettingsRow(.credentials, title: Copy.credentialsTitle, detail: Copy.credentialsDetail) {
                    Button(Copy.removeAllKeys, role: .destructive) { confirmRemoveKeys = true }
                        .disabled(keyed.isEmpty)
                }
                SettingsDivider()
                SettingsRow(.remoteAccess, title: Copy.remoteAccessTitle, detail: remoteLine) {
                    SettingsInlineLink(section: .remote, label: Copy.fromAnywhere)
                }
                SettingsDivider()
                SettingsRow(.transcripts, title: Copy.transcriptsTitle, detail: Copy.transcriptsFact)
            }
        }
        .task { await load() }
        .sheet(item: $pendingDelete) { bank in
            BankDeleteSheet(bank: bank) { pendingDelete = nil } onDelete: { trash(bank) }
        }
        .confirmationDialog(Copy.removeAllKeys, isPresented: $confirmRemoveKeys) {
            Button(Copy.removeAllKeys, role: .destructive) {
                let ids = keyed.map(\.id)
                Task { for id in ids { await connectionsVM.removeKey(id) } }
            }
        } message: {
            Text(keyed.map(\.label).joined(separator: ", "))
        }
    }

    /// "—" until the status snapshot says (a value with no guess behind it).
    private func gateValue(_ on: Bool?) -> some View {
        Text(on.map { $0 ? Copy.gateOn : Copy.gateOff } ?? Copy.notKnownYet)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
    }

    private func load() async {
        // A status snapshot cached before the gates existed would read "—"
        // until the next sync tick; one refresh on open costs a single request.
        await store.refresh([.status, .banks])
        memoryRoot = (try? await APIClient.shared.fetchHealth())?.memoryRoot
        if let remote = try? await APIClient.shared.fetchRemoteStatus() {
            if remote.enabled {
                let live = (try? await APIClient.shared.fetchRemoteConnectors())?.filter(\.isActive).count ?? 0
                remoteLine = Copy.remoteOn(live)
            } else {
                remoteLine = Copy.remoteOff
            }
        }
    }

    /// R-O20: choose where it goes first, so a cancel costs nothing.
    private func export(_ bank: MemoryBank) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "cicada-\(bank.name).zip"
        panel.allowedContentTypes = [.zip]
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        exporting = Copy.exportingBank(bank.name)
        exportNote = nil
        Task { @MainActor in
            defer { exporting = nil }
            do {
                let tmp = try await APIClient.shared.exportBank(name: bank.name)
                // The save panel already asked "Replace?" for an existing file.
                if FileManager.default.fileExists(atPath: destination.path) { try FileManager.default.removeItem(at: destination) }
                try FileManager.default.moveItem(at: tmp, to: destination)
                exportNote = Copy.exportedBank(bank.name)
                NSWorkspace.shared.activateFileViewerSelecting([destination])
            } catch {
                exportNote = AddSourceSheet.friendlyError(error)
            }
        }
    }

    private func trash(_ bank: MemoryBank) {
        pendingDelete = nil
        Task { @MainActor in
            do {
                _ = try await APIClient.shared.deleteBank(name: bank.name)
                deleteProblem = nil
            } catch {
                deleteProblem = AddSourceSheet.friendlyError(error)
            }
            await store.refresh([.banks])
        }
    }
}

/// Type the bank's name to confirm (design §2.5): the button stays disabled
/// until it matches, and the sheet says exactly what happens.
private struct BankDeleteSheet: View {
    let bank: MemoryBank
    let onCancel: () -> Void
    let onDelete: () -> Void
    @State private var typed = ""

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.bankDeleteSheetTitle(bank.name)).font(CicadaTheme.headingFont)
            Text(Copy.bankDeleteSheetBody(bank.name))
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField(Copy.bankDeleteTypeToConfirm(bank.name), text: $typed).textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Button(Copy.cancelAction, role: .cancel, action: onCancel).keyboardShortcut(.cancelAction)
                Button(Copy.deleteAction, role: .destructive, action: onDelete)
                    .disabled(typed.trimmingCharacters(in: .whitespaces) != bank.name)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(420))
    }
}
