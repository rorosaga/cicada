import SwiftUI

// MARK: - The memory-bank selector (DR-24)

/// The one memory-bank selector (DR-24), in the command bar. Moved from the Graph page's
/// overlay (R-DS19): two switcher VIEWS is the split-brain class, so `SingleBankSwitcherTests`
/// holds it to exactly one construction. A "project" is G141's word now, so a bank is a
/// memory bank here.
///
/// Lists memory banks (`GET /banks`), shows the active one, and lets the person switch
/// (activate → reload graph), create a new empty bank, "Save as…" (duplicate) and rename.
/// State lives in `BanksViewModel`; activating reloads the graph via `GraphViewModel`.
struct BankSwitcher: View {
    @Environment(GraphViewModel.self) private var graphVM
    let banksVM: BanksViewModel

    @State private var isHovered = false
    @State private var showCreateSheet = false
    @State private var showDuplicateSheet = false
    @State private var showRenameSheet = false
    // The bank the rename sheet acts on, captured when the menu item is chosen.
    @State private var renameTarget: MemoryBank?

    var body: some View {
        Menu {
            // Two `Section`s, not a `Divider()`: the native menu draws the same separator
            // between them (the mock's "Manage memory banks" group), and the shell's files
            // carry no divider (DR-11, ShellElevationLintTests).
            Section {
                if banksVM.banks.isEmpty {
                    Text(Copy.noMemoryBanks)
                } else {
                    ForEach(banksVM.banks) { bank in
                        Button {
                            switchTo(bank.name)
                        } label: {
                            // A leading checkmark marks the active bank.
                            if bank.name == banksVM.activeName {
                                Label(bankLabel(bank), systemImage: "checkmark")
                            } else {
                                Text(bankLabel(bank))
                            }
                        }
                    }
                }
            }

            Section {
                Button {
                    showCreateSheet = true
                } label: {
                    Label(Copy.newMemoryBankItem, systemImage: "plus")
                }

                Button {
                    showDuplicateSheet = true
                } label: {
                    Label(Copy.saveMemoryBankAsItem, systemImage: "square.on.square")
                }
                .disabled(banksVM.activeName == nil)

                Button {
                    // Rename the currently-active bank. Capture it now so the sheet
                    // has a stable target even if the roster reloads underneath.
                    renameTarget = banksVM.activeBank
                    showRenameSheet = true
                } label: {
                    Label(Copy.renameMemoryBankItem, systemImage: "pencil")
                }
                .disabled(banksVM.activeName == nil)
            }
        } label: {
            HStack(spacing: CicadaTheme.scaled(5)) {
                Image(systemName: "square.stack.3d.up")
                    .font(CicadaTheme.icon(.commandBar))
                Text(displayName)
                    .font(CicadaTheme.metaMediumFont)
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(CicadaTheme.font(size: 9, weight: .semibold))
            }
            .foregroundStyle(isHovered ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.leading, CicadaTheme.spacingSM)
            .padding(.trailing, CicadaTheme.scaled(6))
            .frame(height: CicadaTheme.scaled(24))
            // A TextButton (DR-40): no fill, `bgSelected` on hover; its radius is the bar's less
            // the bar's 4 pt inset (DR-12, concentric).
            .background(CicadaTheme.shape(CicadaTheme.cornerRadius - CicadaTheme.radiusXS)
                .fill(isHovered ? CicadaTheme.bgSelected : Color.clear))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .onHover { isHovered = $0 }
        .help(Copy.switchMemoryBank)
        .accessibilityLabel("\(Copy.memoryBanks): \(displayName)")
        .task { await banksVM.load() }
        .sheet(isPresented: $showCreateSheet) {
            BankNameSheet(
                title: Copy.newMemoryBankTitle,
                message: Copy.newMemoryBankMessage,
                confirmLabel: "Create",
                isPresented: $showCreateSheet
            ) { name, description in
                Task {
                    if await banksVM.create(name: name, description: description) != nil {
                        // Always repaint after the sheet dismisses: presenting the
                        // sheet tears down the graph's WKWebView, so even though
                        // create doesn't switch the active bank, the canvas must be
                        // re-pushed or it stays blank.
                        await graphVM.loadGraph()
                    }
                }
            }
        }
        .sheet(isPresented: $showDuplicateSheet) {
            BankNameSheet(
                title: Copy.saveMemoryBankAsTitle,
                message: Copy.saveMemoryBankAsMessage,
                confirmLabel: "Save",
                showsDescription: false,
                isPresented: $showDuplicateSheet
            ) { name, _ in
                guard let source = banksVM.activeName else { return }
                Task {
                    await banksVM.duplicate(from: source, newName: name)
                    // Same sheet-teardown repaint as create.
                    await graphVM.loadGraph()
                }
            }
        }
        .sheet(isPresented: $showRenameSheet) {
            BankNameSheet(
                title: Copy.renameMemoryBankTitle,
                message: renameTarget.map { Copy.renameMemoryBankMessage($0.name) }
                    ?? Copy.renameMemoryBankFallback,
                confirmLabel: "Rename",
                showsDescription: false,
                initialName: renameTarget?.name ?? "",
                isPresented: $showRenameSheet
            ) { newName, _ in
                guard let source = renameTarget?.name else { return }
                Task {
                    await banksVM.rename(name: source, newName: newName)
                    // Presenting the sheet tore down the graph's WKWebView, so
                    // re-push the canvas regardless of whether the renamed bank
                    // was active (load() in rename already repointed `active`).
                    await graphVM.loadGraph()
                }
            }
        }
    }

    private var displayName: String {
        banksVM.activeBank?.name ?? banksVM.activeName ?? Copy.memoryBank
    }

    private func bankLabel(_ bank: MemoryBank) -> String {
        if bank.entityCount > 0 || bank.episodeCount > 0 {
            return "\(bank.name)  (\(UsageFormat.count(bank.entityCount)) entities · \(UsageFormat.count(bank.episodeCount)) episodes)"
        }
        return bank.name
    }

    private func switchTo(_ name: String) {
        guard name != banksVM.activeName else { return }
        Task {
            if await banksVM.activate(name) {
                await graphVM.loadGraph()
            }
        }
    }
}

// MARK: - Bank name entry sheet

/// Small modal for entering a bank name (and optional description). Reused by
/// "New memory bank", "Save as…" and "Rename…".
private struct BankNameSheet: View {
    let title: String
    let message: String
    let confirmLabel: String
    var showsDescription: Bool = true
    /// Pre-filled value for the name field (used by "Rename…" to seed the
    /// current name). Defaults to empty for create/duplicate.
    var initialName: String = ""
    @Binding var isPresented: Bool
    let onConfirm: (String, String?) -> Void

    @State private var name = ""
    @State private var description = ""

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text(title)
                .font(CicadaTheme.font(size: 16, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
                // Seed the field on first appearance so "Rename…" pre-fills the
                // current name; no-op for create/duplicate (empty initialName).
                .onAppear { if name.isEmpty { name = initialName } }

            Text(message)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                TextField(Copy.memoryBankName, text: $name)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                    .background(CicadaTheme.surfaceHover)
                    .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .onSubmit(confirm)

                if showsDescription {
                    TextField("Description (optional)", text: $description)
                        .textFieldStyle(.plain)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .padding(.horizontal, CicadaTheme.spacingMD)
                        .padding(.vertical, CicadaTheme.spacingSM)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                }
            }

            HStack {
                Spacer()
                Button("Cancel") { isPresented = false }
                    .keyboardShortcut(.cancelAction)
                Button(confirmLabel, action: confirm)
                    .keyboardShortcut(.defaultAction)
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: 380)
        .background(CicadaTheme.surface)
    }

    private func confirm() {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        onConfirm(trimmed, description.isEmpty ? nil : description)
        isPresented = false
    }
}
