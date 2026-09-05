import SwiftUI

/// Settings → Schedule (G106 amendment; G125 Task 7 — schedule modes): when
/// the Sleep cycle runs on its own. This IS settings-shaped configuration
/// ("visit once, then never again"), matching the pattern the Agents/Plans &
/// keys tabs already establish — the Sleep page itself only ever points here
/// (`Copy.changeInSettingsSleep`, on the study list's footer) rather than
/// duplicating a second picker.
///
/// Four modes (R6/R7): manual (no auto-run — a `daily`/`interval`/
/// `after_import` config the user turns off keeps its hour/minute/interval,
/// never resets to a default when picked back), daily at an hour/minute,
/// every N hours, or "after imports" (a probe that fires once the newest
/// unprocessed episode has sat for `AFTER_IMPORT_SETTLE_MINUTES` — the
/// backend's own R7 doc comment). `ScheduleConfig.mode` is the one source of
/// truth; `enabled` is derived (`mode != "manual"`) and sent for an older
/// reader (R6).
///
/// Engine selection (which model powers Sleep) already lives in
/// \(Copy.settingsPlansAndKeys) — the "Use for Sleep" toggle on the Claude
/// plan's connection card (`ConnectionsView`, G74(a)) — so this tab points
/// there rather than duplicating it.
struct SettingsSleepView: View {
    @Environment(SleepViewModel.self) private var sleepVM
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

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(title: Copy.sleepSettings, subtitle: Copy.sleepSettingsSubtitle) {}

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    scheduleCard
                    engineCard
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXL)
            }
        }
        .task {
            if !loadedOnce {
                loadedOnce = true
                await sleepVM.load()
                syncScheduleState()
            }
        }
        .onChange(of: sleepVM.schedule) { _, _ in
            syncScheduleState()
        }
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

    private var scheduleCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("RUNS")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            Picker("Runs", selection: Binding(
                get: { mode },
                set: { newValue in
                    mode = newValue
                    commitSchedule()
                }
            )) {
                Text("Manual").tag("manual")
                Text("Daily").tag("daily")
                Text("Every N hours").tag("interval")
                Text("After imports").tag("after_import")
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            modeDetail
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    @ViewBuilder
    private var modeDetail: some View {
        switch mode {
        case "daily":
            HStack(spacing: CicadaTheme.spacingMD) {
                Text("At")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                DatePicker(
                    "",
                    selection: Binding(
                        get: { scheduleDate },
                        set: { newDate in
                            scheduleDate = newDate
                            commitSchedule()
                        }
                    ),
                    displayedComponents: .hourAndMinute
                )
                .labelsHidden()
                Spacer()
            }
            Text("Next run: \(formattedTime(scheduleDate))")
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textSecondary)
        case "interval":
            Stepper(
                "Every \(intervalHours) hour\(intervalHours == 1 ? "" : "s")",
                value: Binding(
                    get: { intervalHours },
                    set: { newValue in
                        intervalHours = newValue
                        commitSchedule()
                    }
                ),
                in: 1...168
            )
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textPrimary)
        case "after_import":
            Text("Starts about 10 minutes after the last import lands, if nothing is running.")
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
        default:
            Text("Only when you press Consolidate now.")
                .font(CicadaTheme.font(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private var engineCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("ENGINE")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
            Text("Which model powers Sleep is set on the Claude plan's connection card.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            Text("Change it in \(Copy.settingsPlansAndKeys).")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            if let engine = sleepVM.status?.lastEngine {
                Text("Last cycle ran on \(Copy.engineLabel(engine)).")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            // The toggle this used to point at is gone (R6/R7 replaced it
            // with the mode picker above) — the Sleep page now only ever
            // reads the next run, never edits it.
            Text("The Sleep page shows the next run.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func commitSchedule() {
        let comps = Calendar.current.dateComponents([.hour, .minute], from: scheduleDate)
        let new = ScheduleConfig(
            mode: mode,
            hour: comps.hour ?? 3,
            minute: comps.minute ?? 0,
            intervalHours: intervalHours
        )
        Task { @MainActor in
            await sleepVM.updateSchedule(new)
        }
    }

    private func formattedTime(_ date: Date) -> String {
        let f = DateFormatter()
        f.timeStyle = .short
        f.dateStyle = .none
        return f.string(from: date)
    }
}
