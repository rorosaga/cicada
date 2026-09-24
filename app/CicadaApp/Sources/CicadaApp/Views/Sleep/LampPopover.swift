import SwiftUI

/// Which control presented the lamp's popover (Z-P25) — one popover, two
/// anchors: the lamp art and its text twin, the whisper line.
enum LampAnchor: Equatable { case lamp, whisper }

/// The popover's engine line: the engine id (so it can wear its mark, Z-P26)
/// and the sentence naming it.
struct LampEngineLine: Equatable {
    let engine: String
    let text: String
}

/// The engine a scheduled run uses, and why — shown ALWAYS in the popover,
/// lit or not, before the toggle can flip (ruling 4 at the moment of choice,
/// §7.2). It replaces the whisper line's "Scheduled runs use …" note, which
/// appeared only when the two engines differed (Z-P4): at the moment someone
/// chooses to schedule, "the same engine as your click" is news too. `nil`
/// until the preview loads; never guessed. The backend's `why` is shown
/// sentence-cased, never reworded (Z-P26).
func lampEngineLine(preview: SleepEnginePreviews?, lampLit: Bool) -> LampEngineLine? {
    guard let scheduled = preview?.scheduled else { return nil }
    let lead = lampLit ? Copy.scheduledRunsOn(engine: scheduled.engine)
                       : Copy.scheduledRunsWouldUse(engine: scheduled.engine)
    let why = sentenceCase(scheduled.why).map { " \($0)" } ?? ""
    return LampEngineLine(engine: scheduled.engine, text: "\(lead).\(why)")
}

/// I8 — the lamp's VoiceOver label: its state, in words (art never carries a
/// fact alone, R-A3).
func lampAccessibilityLabel(lampLit: Bool, scheduleText: String, nextRunText: String) -> String {
    lampLit ? "Lamp, on. \(scheduleText). \(nextRunText)." : "Lamp, off. Sleep runs only when you ask."
}

/// "When I read" (§7.2). The lamp art never previews: it flips only when
/// `sleepVM.schedule` changes (P11). The toggle writes through the ONE rule
/// (`ScheduleToggle`), is disabled while its write is in flight, and on a
/// failed write snaps back to the schedule the backend still has, with a
/// caption (Z-P18). Rhythm and time stay in Settings → Sleep (G125 (4)).
/// Nothing here starts or cancels a cycle (R-Z9).
struct LampPopover: View {
    @Environment(SleepViewModel.self) private var sleepVM
    /// R-HS12 — the engine line reads the chooser's echo first, so a switch in the engine menu or
    /// Settings → Engines shows here at once.
    @Environment(SleepEngineViewModel.self) private var engineVM
    let page: SleepPageModel

    /// The value in flight, or `nil`.
    @State private var writing: Bool?
    @State private var failed = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            SectionLabel(Copy.whenIRead)
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: page.lampLit ? "circle.fill" : "circle")
                    .font(CicadaTheme.font(size: 9))
                    .foregroundStyle(page.lampLit ? CicadaTheme.accent : CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
                Text(page.lampLit ? Copy.lampOn : Copy.lampOff)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: CicadaTheme.spacingMD)
                Toggle(Copy.readOnSchedule, isOn: Binding(
                    get: { writing ?? ScheduleToggle.isOn(sleepVM.schedule) },
                    set: { write($0) }))
                    .toggleStyle(.switch)
                    .controlSize(.small)
                    .disabled(writing != nil)
            }
            Text(page.lampLit ? whisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText, lampLit: true)
                              : Copy.lampOffExplainer)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                // R-A14 — "Next run —" is a value with a reason.
                .help(page.nextRunText.hasSuffix("—") ? Copy.nextRunUnknownReason : "")
            if let line = lampEngineLine(preview: SleepEnginePreviewSource.current(chooser: engineVM.response,
                                                                                   page: sleepVM.enginePreview),
                                             lampLit: page.lampLit) {
                HStack(alignment: .top, spacing: CicadaTheme.spacingXS) {
                    EngineMark(engine: line.engine, size: 12)   // Z-P26 — a named engine wears its mark
                    Text(line.text)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if failed {
                Text(Copy.scheduleWriteFailed)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
            }
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(Copy.rhythmAndTime)
                    .foregroundStyle(CicadaTheme.textTertiary)
                SettingsSectionLink(section: .sleep, label: "\(Copy.settingsSleep) ›")
            }
            .font(CicadaTheme.captionFont)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 360, alignment: .leading)
        .background(CicadaTheme.surface)
    }

    private func write(_ on: Bool) {
        writing = on
        failed = false
        Task { @MainActor in
            let landed = await sleepVM.updateSchedule(ScheduleToggle.toggled(on: on, current: sleepVM.schedule))
            failed = !landed
            writing = nil
        }
    }
}
