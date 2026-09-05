import SwiftUI

/// Settings → Schedule (G106 amendment): the Sleep cycle's auto-run schedule,
/// moved here from the Sleep page proper — this IS settings-shaped
/// configuration ("visit once, then never again"), matching the pattern the
/// Agents/Plans & keys tabs already establish. The Sleep page itself keeps
/// only a quick Pause/Resume toggle on the SAME `enabled` flag (one of its
/// three controls — run, pause, cancel); the full hour/minute editor lives
/// here, once, so the two never drift into disagreeing about what "the
/// schedule" is.
///
/// Engine selection (which model powers Sleep) already lives in
/// \(Copy.settingsPlansAndKeys) — the "Use for Sleep" toggle on the Claude
/// plan's connection card (`ConnectionsView`, G74(a)) — so this tab points
/// there rather than duplicating it.
struct SettingsSleepView: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @State private var scheduleDate: Date = Self.defaultDate()
    @State private var scheduleEnabled: Bool = false
    @State private var loadedOnce = false

    private static func defaultDate() -> Date {
        var comps = DateComponents()
        comps.hour = 3
        comps.minute = 0
        return Calendar.current.date(from: comps) ?? Date()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(title: Copy.schedule, subtitle: Copy.scheduleSubtitle) {}

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
        scheduleEnabled = sleepVM.schedule.enabled
        var comps = DateComponents()
        comps.hour = sleepVM.schedule.hour
        comps.minute = sleepVM.schedule.minute
        if let d = Calendar.current.date(from: comps) {
            scheduleDate = d
        }
    }

    private var scheduleCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("AUTO-RUN")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            Toggle(isOn: Binding(
                get: { scheduleEnabled },
                set: { newValue in
                    scheduleEnabled = newValue
                    commitSchedule()
                }
            )) {
                Text("Auto-run Sleep cycle daily")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            .toggleStyle(.switch)

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
                .disabled(!scheduleEnabled)
                Spacer()
            }

            if scheduleEnabled {
                Text("Next run: \(formattedTime(scheduleDate))")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textSecondary)
            } else {
                Text("Manual triggers only. Use Pause on the Sleep page to toggle this quickly.")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var engineCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("ENGINE")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
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
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func commitSchedule() {
        let comps = Calendar.current.dateComponents([.hour, .minute], from: scheduleDate)
        let new = ScheduleConfig(
            mode: scheduleEnabled ? "daily" : "manual",
            hour: comps.hour ?? 3,
            minute: comps.minute ?? 0
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
