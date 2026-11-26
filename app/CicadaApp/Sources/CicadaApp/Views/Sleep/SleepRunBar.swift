import SwiftUI

// MARK: - The run bar (owner 2026-11-24: "make it look like an impressive designer UI that keeps it minimal with only
// whats needed, and with the logos of providers and such")
//
// What will run, when, and the go button, as ONE object under the headline — a chat composer's bar. Left to right: the
// engine (its real mark and the name the engine menu uses), the schedule (a moon, a few words, the lamp's switch), the
// reading options as a slider mark, a spring, and the page's one primary. Inside the bar the three quiet controls wear
// no ring of their own (a hover fill only); the bar's ring is the only one. The primary lives in `SleepControlRow`
// (`SleepHero.swift`, the one file that starts a run); this file holds the quiet parts and their words.

/// How much of the bar's labels fit: `ViewThatFits` tries them in order. The engine is what the person asked to see,
/// so its full label survives longest: the schedule gives way first, then the primary's word, the engine last. The
/// primary itself never goes (owner 2026-11-24).
enum RunBarLevel: CaseIterable, Equatable {
    /// Every label in full: "Claude plan · haiku", "Daily at 3:00 AM", "Consolidate now".
    case full
    /// The schedule as its moon and its switch only (its words move to `.help`).
    case scheduleGlyph
    /// Also the primary in its shorter word ("Consolidate").
    case primaryShort
    /// Last: the engine as its mark and model only.
    case engineShort

    var schedule: Bool { self == .full }
    var primaryIsShort: Bool { self == .primaryShort || self == .engineShort }
    var engineIsShort: Bool { self == .engineShort }
}

/// The bar's words, pure (`SleepRunBarTests`). The full sentence the schedule used to be a row for is its `.help` and
/// the popover's, never a line.
enum RunBarText {
    /// "Off" while the lamp is off, else the rhythm in a few words: "Daily at 3:00 AM", "Hourly", "Every 6 h".
    static func schedule(_ schedule: ScheduleConfig, locale: Locale = .current) -> String {
        guard schedule.enabled else { return Copy.SleepPage.scheduleOff }
        switch schedule.mode {
        case "daily":
            var parts = DateComponents()
            parts.hour = schedule.hour
            parts.minute = schedule.minute
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
            guard let date = calendar.date(from: parts) else {
                return Copy.SleepPage.scheduleDaily(String(format: "%02d:%02d", schedule.hour, schedule.minute))
            }
            return Copy.SleepPage.scheduleDaily(clockTime(date, locale: locale, timeZone: calendar.timeZone))
        case "interval":
            return schedule.intervalHours == 1 ? Copy.SleepPage.scheduleHourly : Copy.SleepPage.scheduleEvery(schedule.intervalHours)
        case "after_import": return Copy.SleepPage.scheduleAfterImports
        default: return Copy.SleepPage.scheduleOff
        }
    }

    /// The engine's label: the menu's own ("Claude plan · haiku", "Auto · …"), or just the model when the bar is short.
    static func engine(_ response: SleepEngineResponse?, short: Bool) -> String? {
        guard let response, let label = EngineQuickMenuModel.buttonLabel(response) else { return nil }
        guard short, let model = response.preview?.manual.model, !model.isEmpty else { return label }
        return model
    }
}

/// The engine label's tooltip. While a run reads, a choice made since (here, in Settings, or by an agent) waits for the
/// next start or Continue, and the label already names the new choice, so the tooltip says the run is not using it yet —
/// the line that used to sit under the controls (2026-11-26; the engine menu's own run note says it too).
enum EngineLabelHelp {
    static func text(runKeepsEngine: Bool) -> String {
        runKeepsEngine ? Copy.EngineMenu.runKeepsEngine : Copy.EngineMenu.moreInSettings
    }
}

/// The engine, plain: its mark and name, opening Settings → Intelligence (as the label always did).
struct RunBarEngine: View {
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(AppRouter.self) private var router
    var short = false

    var body: some View {
        if let response = engineVM.response, let label = RunBarText.engine(response, short: short) {
            let full = EngineQuickMenuModel.buttonLabel(response) ?? label
            HugWidth(maxWidth: CicadaTheme.scaled(EngineQuickMenu.buttonMaxWidth)) {
                NeutralButton(title: label,
                              leading: AnyView(EngineMark(engine: response.preview?.manual.engine ?? "",
                                                          size: CicadaTheme.scaled(16),
                                                          model: response.preview?.manual.model)),
                              size: .compact,
                              help: EngineLabelHelp.text(runKeepsEngine: sleepVM.isRunning && response.runKeepsEngine),
                              quiet: true) {
                    router.openSettings(.intelligence, row: .engineChoice)
                }
                .accessibilityLabel(Copy.EngineMenu.buttonAccessibility(full))
            }
        }
    }
}

/// The schedule, plain: a moon and its few words, then the lamp's switch. The words open the lamp's popover (the same
/// one the room's lamp opens); the full sentence — the rhythm, when it next reads, or that it reads when asked — is the
/// `.help`.
struct RunBarSchedule: View {
    let page: SleepPageModel
    let room: RoomModel
    var glyphOnly = false

    private var sentence: String {
        whisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText, lampLit: page.lampLit)
    }

    private var help: String { page.nextRunText.hasSuffix("—") && page.lampLit ? Copy.nextRunUnknownReason : sentence }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Group {
                if glyphOnly {
                    IconButton(systemName: "moon.zzz", help: help, accessibilityLabel: sentence) { room.lampPopover = .whisper }
                } else {
                    NeutralButton(title: RunBarText.schedule(page.schedule), systemImage: "moon.zzz", size: .compact,
                                  help: help, quiet: true) { room.lampPopover = .whisper }
                        .accessibilityLabel(sentence)
                }
            }
            .roomLinkCursor()
            .accessibilityHint(Copy.lampHint)
            .popover(isPresented: Binding(get: { room.lampPopover == .whisper },
                                          set: { if !$0 { room.lampPopover = nil } }),
                     arrowEdge: .bottom) { LampPopover(page: page) }
            LampSwitch()
        }
    }
}
