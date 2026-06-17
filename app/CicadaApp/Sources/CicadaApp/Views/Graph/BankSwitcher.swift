import SwiftUI

// MARK: - Bank (Projects) Switcher

/// The "Projects" dropdown that lives in the graph toolbar. Lists memory banks
/// (`GET /banks`), shows the active one, and lets the user switch (activate →
/// reload graph), create a new empty bank, and "Save as…" (duplicate). State
/// lives in `BanksViewModel`; activating reloads the graph via `GraphViewModel`.
struct BankSwitcher: View {
    @Environment(GraphViewModel.self) private var graphVM
    let banksVM: BanksViewModel

    @State private var isHovered = false
    @State private var showCreateSheet = false
    @State private var showDuplicateSheet = false

    var body: some View {
        Menu {
            if banksVM.banks.isEmpty {
                Text("No projects yet")
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

            Divider()

            Button {
                showCreateSheet = true
            } label: {
                Label("New Project…", systemImage: "plus")
            }

            Button {
                showDuplicateSheet = true
            } label: {
                Label("Save as…", systemImage: "square.on.square")
            }
            .disabled(banksVM.activeName == nil)
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: "square.stack.3d.up")
                    .font(.system(size: 12))
                Text(displayName)
                    .font(.system(size: 12, weight: .medium))
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
            }
            .foregroundStyle(isHovered ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .onHover { isHovered = $0 }
        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
        .help("Switch memory project")
        .task { await banksVM.load() }
        .sheet(isPresented: $showCreateSheet) {
            BankNameSheet(
                title: "New Project",
                message: "Creates a new, empty memory project.",
                confirmLabel: "Create",
                isPresented: $showCreateSheet
            ) { name, description in
                Task {
                    let before = banksVM.activeName
                    if await banksVM.create(name: name, description: description) != nil {
                        // Creating a bank does not auto-activate it, so only
                        // reload the graph if the active bank actually changed.
                        if banksVM.activeName != before {
                            await graphVM.loadGraph()
                        }
                    }
                }
            }
        }
        .sheet(isPresented: $showDuplicateSheet) {
            BankNameSheet(
                title: "Save Project As…",
                message: "Copies the current project under a new name.",
                confirmLabel: "Save",
                showsDescription: false,
                isPresented: $showDuplicateSheet
            ) { name, _ in
                guard let source = banksVM.activeName else { return }
                Task { await banksVM.duplicate(from: source, newName: name) }
            }
        }
    }

    private var displayName: String {
        banksVM.activeBank?.name ?? banksVM.activeName ?? "Project"
    }

    private func bankLabel(_ bank: MemoryBank) -> String {
        if bank.entityCount > 0 || bank.episodeCount > 0 {
            return "\(bank.name)  (\(bank.entityCount) entities · \(bank.episodeCount) episodes)"
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
/// "New Project" and "Save as…".
private struct BankNameSheet: View {
    let title: String
    let message: String
    let confirmLabel: String
    var showsDescription: Bool = true
    @Binding var isPresented: Bool
    let onConfirm: (String, String?) -> Void

    @State private var name = ""
    @State private var description = ""

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text(title)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)

            Text(message)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                TextField("Project name", text: $name)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                    .background(CicadaTheme.surfaceHover)
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                    .onSubmit(confirm)

                if showsDescription {
                    TextField("Description (optional)", text: $description)
                        .textFieldStyle(.plain)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .padding(.horizontal, CicadaTheme.spacingMD)
                        .padding(.vertical, CicadaTheme.spacingSM)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
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
