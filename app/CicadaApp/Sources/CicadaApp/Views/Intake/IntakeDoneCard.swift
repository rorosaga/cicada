import SwiftUI

/// Track I T5 (design §5.2) — "what happens next". It never closes on its own:
/// the upload overlay's 1.5 s auto-dismiss took the one sentence that says when
/// these will be read away before anyone could read it (D6). The when-line is
/// `ScheduleHonesty.afterImportLine` (A/B/C — ruling 4 shown, never promised
/// away); Read now is G125 R10's first narrow amendment (R-IA31): a user
/// trigger, shown only when an engine can run it (`EngineReadiness`, else a link
/// to choose one — R-IA23) and only when the import landed in the bank a read
/// consolidates.
struct IntakeDoneCard: View {
    let outcome: IntakeOutcome
    let onDone: () -> Void

    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(BanksViewModel.self) private var banksVM
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var readingNow = false
    @State private var switchedTo: String?
    @State private var switching = false
    /// Flips once on appear: the one-shot ✓ (design I6) — scale 0.8 → 1 over
    /// `CicadaMotion.success`, an instant cut under Reduce Motion.
    @State private var landed = false

    private var inputs: HonestyInputs {
        HonestyInputs.from(schedule: sleepVM.schedule, response: engineVM.response,
                           connections: store.connections.value ?? [])
    }

    private var readiness: EngineReadiness {
        EngineReadiness.resolve(candidates: engineVM.response?.candidates ?? [],
                                connections: store.connections.value ?? [],
                                preview: engineVM.response?.preview)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "checkmark.circle.fill")
                    .font(CicadaTheme.font(size: 22))
                    .foregroundStyle(CicadaTheme.success)
                    .scaleEffect(landed ? 1 : 0.8)
                    .animation(CicadaMotion.success(reduceMotion: reduceMotion), value: landed)
                    .accessibilityHidden(true)
                Text(IntakeSummary.headline(outcome)).font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary).accessibilityAddTraits(.isHeader)
            }
            if let detail = IntakeSummary.doneDetail(outcome) {
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            ForEach(outcome.failures, id: \.self) {
                Text($0).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            if let bank = outcome.inactiveBank, switchedTo == nil {
                Text(Copy.intakeInactiveBank(bank)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.warning)
                Button(Copy.intakeSwitchTo(bank)) { switchTo(bank) }.buttonStyle(.bordered).disabled(switching)
            } else if outcome.total > 0 {
                Text(ScheduleHonesty.afterImportLine(inputs)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                readRow
            }
            HStack {
                Button(Copy.whatNextShowsIn(IntakeSummary.sourcesName(origin: outcome.origin))) {
                    router.pendingTab = .sources
                    onDone()
                }
                .buttonStyle(.link)
                Spacer()
                Button(Copy.intakeDone, action: onDone).keyboardShortcut(.defaultAction)
            }
        }
        .task {
            landed = true
            AccessibilityNotification.Announcement(IntakeSummary.headline(outcome)).post()
            await engineVM.load()
            await sleepVM.load()
        }
    }

    @ViewBuilder private var readRow: some View {
        if readingNow {
            Text(Copy.intakeReadingNow).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
        } else if case .ready = readiness, let preview = engineVM.response?.preview {
            HStack(spacing: CicadaTheme.spacingSM) {
                MeadowPill(title: Copy.intakeReadNow) {
                    readingNow = true
                    Task { await sleepVM.triggerManually() }
                }
                Text(Copy.engineLabel(preview.manual.engine)).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        } else {
            SettingsSectionLink(section: .sleep, label: Copy.intakeChooseWhoReads)
        }
    }

    /// G87's one-click remedy, moved from the upload overlay unchanged.
    private func switchTo(_ bank: String) {
        switching = true
        Task {
            if await banksVM.activate(bank) {
                await graphVM.loadGraph()
                switchedTo = bank
            }
            switching = false
        }
    }
}
