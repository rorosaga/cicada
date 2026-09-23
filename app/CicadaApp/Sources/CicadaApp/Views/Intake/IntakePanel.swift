import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Track I T5 (design §5.2) — the one intake panel. One component, many hosts:
/// the window overlay, each `+` chat tile, the `+` root's drop zone (and, in part
/// b, the Welcome and Home). It renders the router's `phase` and owns no import
/// logic, so a Dock drop and a `+` tile cannot behave differently.
struct IntakePanel: View {
    /// nil: every vendor (the overlay, the `+` root); set: one tile's vendor.
    var vendor: ChatVendor? = nil
    /// Where this panel's own drops and file picks say they came from.
    var origin: IntakeOrigin
    /// The `+` root: the drop zone alone, no "how to get it".
    var compact = false

    @Environment(IntakeRouter.self) private var intake
    @Environment(BanksViewModel.self) private var banksVM
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var dropTargeted = false
    @State private var filter = ""
    /// The new memory's name as typed — a draft only. Whether the panel is
    /// creating one is the ROUTER's `target`, never local state: a panel-held
    /// flag survived Cancel and a fresh drop (`accept` resets the target to
    /// `.active`), so the picker read "New memory" while the import went to the
    /// active bank — G87's one lie (Track I final review, finding 3).
    @State private var newMemoryName = ""

    private var vendors: [ChatVendor] { vendor.map { [$0] } ?? ChatVendor.allCases }
    /// A panel shows the router's phase only when it is the host that phase belongs to.
    private var phase: IntakePhase { intake.host == origin.host ? intake.phase : .idle }

    var body: some View {
        Group {
            switch phase {
            case .idle: idle
            case .reading(let names): reading(names)
            case .preview(let preview): self.preview(preview)
            case .importing(let progress): importing(progress)
            case .done(let outcome): IntakeDoneCard(outcome: outcome) { intake.finish() }
            case .failed(let reason): failed(reason)
            }
        }
        .animation(CicadaMotion.morph(reduceMotion: reduceMotion), value: phase)
    }

    // MARK: Idle

    private var idle: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            dropZone
            if !compact {
                Text(Copy.intakeNoExportYet).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                ForEach(vendors) { ExportAskRow(vendor: $0, startsOpen: vendor != nil) }
            }
            // The overlay's idle state needs its own way out for the keyboard and
            // VoiceOver (design I9); in the `+` sheet the sheet's back control is it.
            if origin.host == .overlay {
                HStack {
                    Spacer()
                    Button(Copy.intakeCancel) { intake.dismiss() }
                        .buttonStyle(.cicadaPlain)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .keyboardShortcut(.cancelAction)
                }
            }
        }
    }

    private var dropZone: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ForEach(vendors) { VendorMark(vendor: $0, size: CicadaTheme.scaled(28)) }
            }
            Text(Copy.intakeDropTitle).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.intakeDropSubtitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                .multilineTextAlignment(.center)
            Button(Copy.intakeChooseFile) { chooseFile() }
                .buttonStyle(.bordered)
                // Overlay only: in the `+` sheet a default action here would take
                // Return away from the tile grid's own Enter-opens-tile (R10).
                .keyboardShortcut(origin.host == .overlay ? KeyboardShortcut.defaultAction : nil)
        }
        .frame(maxWidth: .infinity)
        .padding(CicadaTheme.spacingLG)
        .background(dropTargeted ? CicadaTheme.meadowWash.opacity(0.4) : CicadaTheme.surface,
                    in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius, style: .continuous)
            .strokeBorder(dropTargeted ? CicadaTheme.meadow : CicadaTheme.border,
                          style: StrokeStyle(lineWidth: dropTargeted ? 2 : 1, dash: [6, 4])))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: dropTargeted)
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            IntakeDrop.load(providers) { intake.accept(urls: $0, from: origin) }
            return true
        }
    }

    private func chooseFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.zip, .json, .html, .folder, .commaSeparatedText, .plainText, .xml, .propertyList]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = Copy.intakeDropTitle
        guard panel.runModal() == .OK else { return }
        intake.accept(urls: panel.urls, from: origin)
    }

    // MARK: Reading / importing / failed

    private func reading(_ names: [String]) -> some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            BookwormView(state: .reading, pointSize: 48)
            Text(Copy.intakeReading(names)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            Button(Copy.intakeCancel) { intake.cancel() }.buttonStyle(.bordered).keyboardShortcut(.cancelAction)
        }
        .frame(maxWidth: .infinity)
    }

    private func importing(_ progress: IntakeProgress) -> some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            BookwormView(state: .reading, pointSize: 48)
            Text(IntakeSummary.importingLine(progress, vendor: intake.previewVendor))
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            if let staged = progress.staged {
                ProgressView(value: Double(staged), total: Double(max(progress.total, 1)))
                    .frame(maxWidth: CicadaTheme.scaled(280))
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func failed(_ reason: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(reason).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.danger)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(Copy.intakeChooseAnother) { chooseFile() }.buttonStyle(.bordered)
                Spacer()
                Button(Copy.intakeCancel) { intake.cancel() }.buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .onAppear { AccessibilityNotification.Announcement(reason).post() }
    }

    // MARK: Preview

    private func preview(_ p: IntakePreview) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                VendorMark(origin: p.origin, size: CicadaTheme.scaled(32)).markHover()
                VStack(alignment: .leading, spacing: 2) {
                    Text(IntakeSummary.previewTitle(p)).font(CicadaTheme.titleFont)
                        .foregroundStyle(CicadaTheme.textPrimary).accessibilityAddTraits(.isHeader)
                    Text(IntakeSummary.countsLine(p)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            if !p.chatFiles.isEmpty {
                Text(IntakeSummary.previewDelta(p.delta)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            }
            if !p.titles.isEmpty { titleList(p) }
            ForEach(Array(p.skipped.enumerated()), id: \.offset) { _, s in
                Text(Copy.intakeSkipped(s.name, s.reason)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(p.warnings, id: \.self) {
                Text($0).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            // `/sources/upload` has no bank parameter, so a drop that mixes saved
            // content in would split across memories behind the picker's back —
            // offer Into only when everything in the drop can follow it.
            if !p.chatFiles.isEmpty && p.savedFiles.isEmpty { intoPicker }
            if p.importCount == 0 {
                Text(Copy.intakeNothingNewLine).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            HStack {
                Spacer()
                Button(Copy.intakeCancel) { intake.cancel() }.buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.textSecondary).keyboardShortcut(.cancelAction)
                MeadowPill(title: p.importCount == 0 ? Copy.intakeNothingNew : Copy.intakeImportButton(p.importCount)) {
                    intake.confirm(createBank: { name in await banksVM.create(name: name) })
                }
                .disabled(p.importCount == 0 || newBankName.map { $0.trimmingCharacters(in: .whitespaces).isEmpty } == true)
            }
        }
    }

    private func titleList(_ p: IntakePreview) -> some View {
        let shown = filter.isEmpty ? p.titles : p.titles.filter { $0.title.localizedCaseInsensitiveContains(filter) }
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack {
                TextField(Copy.intakeFilterPlaceholder, text: $filter)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel(Copy.intakeFilterLabel)
                Text(IntakeSummary.filterCount(shown: shown.count, total: p.titles.count))
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(shown.enumerated()), id: \.offset) { _, t in
                        HStack {
                            Text(t.title).font(CicadaTheme.bodyFont).lineLimit(1)
                            Spacer()
                            if let date = t.date { Text(date).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary) }
                        }
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(200))
            if p.titlesTruncated {
                Text(Copy.intakeTitlesCapped(IntakePreview.maxTitles)).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    /// Into (G87): this memory, another, or a new one — the upload overlay's
    /// project mode, absorbed.
    private var intoPicker: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(Copy.intakeInto).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            Picker(Copy.intakeInto, selection: Binding(
                get: { creatingNew ? "__new__" : (targetSlug ?? banksVM.activeName ?? "") },
                set: { value in
                    if value == "__new__" {
                        intake.retarget(.newBank(newMemoryName))
                    } else {
                        intake.retarget(value == banksVM.activeName ? .active : .bank(value))
                    }
                })) {
                ForEach(banksVM.banks) { bank in
                    Text(bank.name == banksVM.activeName ? "\(bank.name) \(Copy.intakeActiveSuffix)" : bank.name).tag(bank.name)
                }
                Divider()
                Text(Copy.intakeNewMemory).tag("__new__")
            }
            .labelsHidden()
            .pickerStyle(.menu)
            if creatingNew {
                TextField(Copy.intakeNewMemoryPlaceholder, text: $newMemoryName)
                    .textFieldStyle(.roundedBorder)
                    .onChange(of: newMemoryName) { _, name in
                        if creatingNew { intake.retarget(.newBank(name)) }
                    }
            }
        }
        .task { await banksVM.load() }
        // A target that stops being a new memory (Cancel, a new drop) drops
        // the draft too, so the next "New memory" starts empty.
        .onChange(of: intake.target) { _, target in
            if case .newBank = target { return }
            newMemoryName = ""
        }
    }

    private var targetSlug: String? {
        if case .bank(let slug) = intake.target { return slug }
        return nil
    }

    /// The name the router will create, when its target is a new memory.
    private var newBankName: String? {
        if case .newBank(let name) = intake.target { return name }
        return nil
    }

    private var creatingNew: Bool { newBankName != nil }
}
