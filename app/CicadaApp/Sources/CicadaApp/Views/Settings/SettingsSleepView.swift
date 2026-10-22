import SwiftUI

/// Settings → Sleep (G106 amendment; G125 Task 7 — schedule modes): when
/// the Sleep cycle runs on its own. This IS settings-shaped configuration
/// ("visit once, then never again"), matching the pattern the Agents/Plans &
/// keys sections already establish — the Sleep page itself only ever points
/// here (`SettingsSectionLink(section: .sleep, …)`, on the queue card's
/// schedule row since G125 v3) rather than duplicating a second picker.
///
/// Four modes (R6/R7): manual (no auto-run — a `daily`/`interval`/
/// `after_import` config the user turns off keeps its hour/minute/interval,
/// never resets to a default when picked back), daily at an hour/minute,
/// every N hours, or "after imports" (a probe that fires once the newest
/// unprocessed episode has sat for `AFTER_IMPORT_SETTLE_MINUTES` — the
/// backend's own R7 doc comment). `ScheduleConfig.mode` is the one source of
/// truth; `enabled` is derived (`mode != "manual"`) and sent for an older
/// reader (R6). "Next run" is the server's `nextSleepAt`, never the local
/// picker's date (R-O10), and a schedule write refreshes `.status` so it
/// follows at once.
///
/// The engine moved to Settings → Intelligence (G139, A3); this page shows it
/// read-only — both ruling-4 previews, each wearing its engine's mark through
/// `EngineChooser.previewRow` (a named service shows its real mark), and a
/// pointer to where it changes.
struct SettingsSleepView: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store
    @State private var mode: String = "manual"
    @State private var scheduleDate: Date = Self.defaultDate()
    @State private var intervalHours: Int = 6
    @State private var loadedOnce = false

    private static func defaultDate() -> Date {
        var comps = DateComponents()
        comps.hour = 3
        comps.minute = 0
        return Calendar.current.date(from: comps) ?? Date()
    }

    private var mood: BookwormState {
        deriveSleepPageMood(status: sleepVM.status, debt: resolveSleepDebt(sse: nil, status: sleepVM.status),
                            justFinishedAt: nil)
    }

    var body: some View {
        SettingsPage(section: .sleep) {
            // D6 (owner brief, 2026-10-22): the study room's preview at the top, the hours below. The engine and the
            // scheduled-plan switch moved to Intelligence (ruling 4c's words unchanged there).
            ScenerySettings(mood: mood, lampLit: sleepVM.schedule.enabled, part: .preview)
            // DR-38: the card's one row is already titled Runs, so the card carries no header repeating it.
            SettingsGroupCard {
                // The four pills sit in the row's below slot, not beside the
                // detail: next to a multi-word sentence ("Starts about 10
                // minutes after…") they truncated or squeezed the title
                // column at narrow Settings widths (Task 2 review round 1).
                // `fixedSize` keeps every label whole on its own line.
                SettingsRow(.sleepRuns, title: Copy.runsTitle,
                            detail: SleepScheduleText.detail(mode: mode, nextSleepAt: store.status.value?.nextSleepAt),
                            control: { EmptyView() },
                            below: {
                    PillPicker(title: Copy.runsTitle,
                               selection: Binding(get: { mode }, set: { mode = $0; commitSchedule() }),
                               options: SleepScheduleText.modes)
                        .fixedSize()
                })
                if mode == "daily" {
                    SettingsDivider()
                    SettingsRow(.sleepTime, title: Copy.runsAt) {
                        DatePicker("", selection: Binding(get: { scheduleDate },
                                                          set: { scheduleDate = $0; commitSchedule() }),
                                   displayedComponents: .hourAndMinute)
                            .labelsHidden()
                    }
                }
                if mode == "interval" {
                    SettingsDivider()
                    SettingsRow(.sleepInterval, title: Copy.runsEvery) {
                        Stepper(SleepScheduleText.everyHours(intervalHours),
                                value: Binding(get: { intervalHours }, set: { intervalHours = $0; commitSchedule() }),
                                in: 1...168)
                            .font(CicadaTheme.bodyFont)
                    }
                }
                // Owner decision 2 (2026-10-16): a schedule with no engine it may use says so here, plan first.
                if mode != "manual",
                   let warning = Copy.ServerPlan.warningLine(sleepVM.schedule.warning, code: sleepVM.schedule.warningCode) {
                    Text(warning)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("sleep.scheduleWarning")
                }
            }
            // D6: where the scenery comes from follows the hours; the preview leads the page (above).
            ScenerySettings(mood: mood, lampLit: sleepVM.schedule.enabled, part: .source)
            MascotSettings()
        }
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await sleepVM.load()
            syncScheduleState()
        }
        .onChange(of: sleepVM.schedule) { _, _ in syncScheduleState() }
    }

    private func syncScheduleState() {
        mode = sleepVM.schedule.mode
        intervalHours = sleepVM.schedule.intervalHours
        var comps = DateComponents()
        comps.hour = sleepVM.schedule.hour
        comps.minute = sleepVM.schedule.minute
        if let d = Calendar.current.date(from: comps) {
            scheduleDate = d
        }
    }

    private func commitSchedule() {
        let comps = Calendar.current.dateComponents([.hour, .minute], from: scheduleDate)
        let new = ScheduleConfig(
            mode: mode,
            hour: comps.hour ?? 3,
            minute: comps.minute ?? 0,
            intervalHours: intervalHours
        )
        store.bankTask {   // G183(d): bound to the bank this schedule was chosen in
            await sleepVM.updateSchedule(new)
            await store.refresh([.status])   // R-O10: the next run is the server's to say
        }
    }
}
