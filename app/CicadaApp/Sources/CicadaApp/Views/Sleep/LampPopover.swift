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
    /// Settings → Intelligence shows here at once.
    @Environment(SleepEngineViewModel.self) private var engineVM
    let page: SleepPageModel

    /// The value in flight, or `nil`.
    @State private var writing: Bool?
    @State private var failed = false
    /// The closed-lid warning on screen, waiting for the person's click; never stored.
    @State private var confirmingClosedLid: ClosedLidInfo?

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
            if page.lampLit, let scheduled = SleepEnginePreviewSource.current(chooser: engineVM.response,
                                                                              page: sleepVM.enginePreview)?.scheduled {
                Text(Copy.scheduledReadsAll(engine: scheduled.engine, billing: scheduled.billing))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            keepAwakeRow
            closedLidRow
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

    /// G243 — one machine-wide switch, off by default, beside the schedule; it holds an assertion only while a run
    /// reads and changes nothing about what may run. Hidden until the reading options have loaded.
    @ViewBuilder private var keepAwakeRow: some View {
        if let options = sleepVM.runOptions {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Toggle(Copy.keepAwakeSwitch, isOn: Binding(
                    get: { options.keepAwake },
                    set: { on in sleepVM.bankTask { await sleepVM.updateRunOptions(.keepAwake(on)) } }))
                    .toggleStyle(.switch)
                    .controlSize(.small)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                Text(sleepVM.runOptionsWriteFailed ? Copy.keepAwakeWriteFailed : Copy.keepAwakeCaption)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(sleepVM.runOptionsWriteFailed ? CicadaTheme.danger : CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// G243 part 3 — the closed-lid BETA, only offered beside an on keep-awake switch, off by default. Turning it on shows
    /// the server's warning in place (sheet-free, DR-77's popover row; no fold, DR-81) and needs a click on "Turn on the
    /// beta" every time. Once on, the exact admin command is shown until the person has run it.
    @ViewBuilder private var closedLidRow: some View {
        if let options = sleepVM.runOptions, options.keepAwake {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Toggle(Copy.closedLidSwitch, isOn: Binding(
                    get: { options.closedLidBeta || confirmingClosedLid != nil },
                    set: { on in
                        if on {
                            sleepVM.bankTask {
                                if await sleepVM.loadClosedLid() { confirmingClosedLid = sleepVM.closedLid }
                                else { sleepVM.runOptionsWriteFailed = true }
                            }
                        } else {
                            confirmingClosedLid = nil
                            if options.closedLidBeta { sleepVM.bankTask { await sleepVM.updateRunOptions(.closedLidBeta(false)) } }
                        }
                    }))
                    .toggleStyle(.switch)
                    .controlSize(.small)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                if let asking = confirmingClosedLid {
                    Text(asking.warning)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: CicadaTheme.spacingMD) {
                        Button(Copy.closedLidConfirm) {
                            confirmingClosedLid = nil
                            sleepVM.bankTask {
                                await sleepVM.updateRunOptions(.closedLidBeta(true))
                                await sleepVM.loadClosedLid()
                            }
                        }
                        Button(Copy.closedLidCancel) { confirmingClosedLid = nil }
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont.weight(.semibold))
                } else if options.closedLidBeta {
                    if let info = sleepVM.closedLid, !info.ruleInstalled, let command = info.installCommand {
                        Text(Copy.closedLidAdminStep)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                        CommandBox(command: command)
                    } else {
                        Text(Copy.closedLidReady)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    if let info = sleepVM.closedLid {
                        Text(Copy.closedLidRemove(info.removeCommand))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                } else {
                    Text(Copy.closedLidCaption)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .task(id: options.closedLidBeta) { if options.closedLidBeta { await sleepVM.loadClosedLid() } }
        }
    }

    private func write(_ on: Bool) {
        writing = on
        failed = false
        sleepVM.bankTask {
            let landed = await sleepVM.updateSchedule(ScheduleToggle.toggled(on: on, current: sleepVM.schedule))
            failed = !landed
            writing = nil
        }
    }
}
