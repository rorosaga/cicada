import SwiftUI

/// Sleep page v5 (A5) — the *Reading options* sheet, centred like the Settings panel at 720 pt so no page text runs
/// along its edge. Its fields, in order: what a Consolidate does, what it reads, how often it saves, which engine it
/// runs on (the engine menu itself, the person's own choice), the reserve's pointer to the engine menu (plan engines
/// only, no figure — ruling 12), *Continue by itself when my plan resets* (ruling 15, off), the scheduled line
/// (ruling 16, spend in words from `billing`), a neutral note, and Cancel / Consolidate now.
///
/// **Not here, on purpose** (owner, 2026-09-30): no "Read faster" row, no "At once", no reading-model choice, no
/// "Stop after the first batch", no engine advice and no list of sites. Every control writes through
/// `PUT /sleep/run-options` on change (the Settings pattern); a run snapshots them when it starts.
struct ReadingOptionsSheet: View {
    static let width: CGFloat = 720

    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(SleepEngineViewModel.self) private var engineVM

    /// What a Consolidate would read now (waiting minus parked).
    let waiting: Int
    let onClose: () -> Void
    let onConsolidate: () -> Void

    private var options: SleepRunOptions { sleepVM.runOptions ?? SleepRunOptions(batchSize: sleepVM.batchSize) }
    private var preview: SleepEnginePreviews? {
        SleepEnginePreviewSource.current(chooser: engineVM.response, page: sleepVM.enginePreview)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(Copy.SleepV5.optionsTitle)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: CicadaTheme.spacingSM)
                IconButton(systemName: "xmark", help: Copy.sheetClose, accessibilityLabel: Copy.sheetClose,
                           shortcut: .cancelAction, action: onClose)
            }
            Text(Copy.SleepV5.optionsIntro(waiting: waiting, batchSize: options.batchSize))
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: 0) {
                row(title: Copy.SleepV5.whatItReads) {
                    Text(Copy.SleepV5.conversationsAndNotes(waiting))
                        .font(CicadaTheme.bodyFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                Divider()
                row(title: Copy.SleepV5.saveProgressEvery,
                    caption: waiting > 0 ? Copy.SleepV5.savesFor(saves: Self.saves(waiting: waiting, batchSize: options.batchSize),
                                                                 waiting: waiting) : nil) {
                    // R-HS10's precedent: a native menu picker.
                    Picker(Copy.SleepV5.saveProgressEvery, selection: Binding(
                        get: { options.batchSize },
                        set: { size in Task { await sleepVM.updateRunOptions(.batchSize(size)) } })) {
                        ForEach(options.batchSizeChoices, id: \.self) { Text(Copy.SleepV5.everyN($0)).tag($0) }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .fixedSize()
                }
                Divider()
                row(title: Copy.SleepV5.runsOn) { EngineQuickMenuButton() }
                if preview?.manual.billing == "plan" {
                    Divider()
                    row(title: Copy.SleepV5.leaveRoom, caption: Copy.SleepV5.leaveRoomHelp) {
                        InlineLink(title: Copy.SleepV5.setInEngineMenu, action: onClose)
                    }
                }
                if let caption = ContinueAfterResetRow.caption(for: preview?.manual) {
                Divider()
                row(title: Copy.SleepV5.continueAfterReset, caption: caption) {
                    Toggle(Copy.SleepV5.continueAfterReset, isOn: Binding(
                        get: { options.continueAfterReset },
                        set: { on in Task { await sleepVM.updateRunOptions(.continueAfterReset(on)) } }))
                        .labelsHidden()
                        .toggleStyle(.switch)
                        .controlSize(.small)
                }
                }
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))

            if let scheduled = preview?.scheduled, sleepVM.schedule.enabled {
                HStack(alignment: .top, spacing: CicadaTheme.spacingXS) {
                    EngineMark(engine: scheduled.engine, size: CicadaTheme.scaled(12), model: scheduled.model)
                    Text(Copy.scheduledReadsAll(engine: scheduled.engine, billing: scheduled.billing))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            }
            Text(Copy.SleepV5.optionsNote)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            if sleepVM.runOptionsWriteFailed {
                Text(Copy.SleepV5.optionsWriteFailed)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                Spacer(minLength: 0)
                TextButton(title: Copy.SleepV5.cancel, action: onClose)
                PrimaryActionButton(title: Copy.consolidateNow, systemImage: "moon.fill", action: onConsolidate)
                    .disabled(waiting == 0)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(Self.width), alignment: .leading)
        .background(CicadaTheme.bgBase)
        .task { await sleepVM.loadRunOptions() }
    }

    /// How many saves a run of `waiting` makes at this size (the caption under Save progress every).
    static func saves(waiting: Int, batchSize: Int) -> Int {
        guard batchSize > 0 else { return 0 }
        return (waiting + batchSize - 1) / batchSize
    }

    private func row<Trailing: View>(title: String, caption: String? = nil,
                                     @ViewBuilder trailing: () -> Trailing) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                if let caption {
                    Text(caption)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: CicadaTheme.spacingMD)
            trailing()
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
    }
}

/// Whether Reading options shows "Continue by itself when my plan resets", and with which caption (TODO ruling 15).
/// Only a run on a plan pauses at a plan's window, so the row shows only for a plan engine; a plan whose windows the
/// backend cannot classify (`sleep_autocontinue.blocked_reason` → `unknown_limit`) gets a caption that says so.
/// Pure, so `SleepV5Tests` holds it.
enum ContinueAfterResetRow {
    /// The engines whose limit windows `agent_engine.limit_kind_of` recognises.
    static let armableEngines: Set<String> = ["claude-cli"]

    static func caption(for manual: SleepEnginePreview?) -> String? {
        guard let manual, manual.billing == "plan" else { return nil }
        return armableEngines.contains(manual.engine)
            ? Copy.SleepV5.continueAfterResetCaption : Copy.SleepV5.continueAfterResetUnavailableCaption
    }
}
