import Foundation

/// The four schedule modes, spelled as the wire spells them (`ScheduleConfig.mode`).
enum ScheduleMode: String, CaseIterable, Hashable {
    case manual, daily, interval
    case afterImport = "after_import"
}

/// Everything a "when will it be read" sentence depends on (design §5.3).
struct HonestyInputs: Equatable {
    var schedule: ScheduleConfig
    var preview: SleepEnginePreviews?
    var hasKey: Bool
    var ollamaReady: Bool
    var claudeConnected: Bool
    var codexConnected: Bool = false

    /// The key comes from `Store.connections`, never from the byok candidate,
    /// which is always `connected: true` even with no key (F6).
    static func from(schedule: ScheduleConfig, response: SleepEngineResponse?,
                     connections: [ConnectionStatus]) -> HonestyInputs {
        let candidates = response?.candidates ?? []
        return HonestyInputs(schedule: schedule, preview: response?.preview,
                             hasKey: EngineReadiness.hasKey(connections),
                             ollamaReady: EngineReadiness.ollamaReady(candidates),
                             claudeConnected: EngineReadiness.connected("agent", candidates),
                             codexConnected: EngineReadiness.connected("codex", candidates))
    }
}

/// Track I T6 (design §5.3) — every sentence about WHEN imported material is
/// read, as a pure function of the schedule and the two engine previews.
/// Replaces `OnboardingSchedule` (part b retires it with its host), which read
/// the schedule alone and so promised a nightly read that a plan-only install
/// can never perform: ruling 4 sends a scheduled cycle to the key rung, and with
/// no key nothing runs (R7 F7). The ruling is shown here, never promised away.
enum ScheduleHonesty {
    static let planEngines: Set<String> = ["claude-cli", "codex-cli"]

    static func canRead(engine: String, _ i: HonestyInputs) -> Bool {
        switch engine {
        case "litellm": i.hasKey
        case "ollama": i.ollamaReady
        case "claude-cli": i.claudeConnected
        case "codex-cli": i.codexConnected
        default: false
        }
    }

    static func scheduledCanRead(_ i: HonestyInputs) -> Bool {
        guard let engine = i.preview?.scheduled.engine else { return false }
        return canRead(engine: engine, i)
    }

    /// The caption under the engine choice (Welcome, chooser).
    static func engineLine(_ i: HonestyInputs) -> String {
        guard let p = i.preview else { return Copy.afterImportWhenYouAsk }
        let manual = p.manual.engine, scheduled = p.scheduled.engine
        if planEngines.contains(manual) {
            if planEngines.contains(scheduled) { return Copy.honestyPlanBoth }
            guard canRead(engine: scheduled, i) else { return Copy.honestyPlanOnly }
            return scheduled == "ollama" ? Copy.honestyPlanThenOllama : Copy.honestyPlanThenKey
        }
        guard canRead(engine: manual, i) else { return Copy.honestyNothingYet }
        switch manual {
        case "ollama": return Copy.honestyOllama
        case "litellm": return Copy.honestyKey
        default: return Copy.afterImportWhenYouAsk
        }
    }

    static func whenPhrase(_ s: ScheduleConfig) -> String? {
        switch ScheduleMode(rawValue: s.mode) {
        case .daily:
            let time = "\(s.hour):" + String(format: "%02d", s.minute)
            return (s.hour < 6 || s.hour >= 18) ? "tonight at \(time)" : "at \(time)"
        case .interval:
            return s.intervalHours == 1 ? "within the hour" : "within \(s.intervalHours) hours"
        case .afterImport:
            return "a few minutes after imports settle"
        case .manual, nil:
            return nil
        }
    }

    /// The done card's line: A (manual), B (a schedule that can read), C (a plan
    /// waiting on ruling 4), C′ (nothing can read on a schedule yet).
    static func afterImportLine(_ i: HonestyInputs) -> String {
        if i.schedule.mode == ScheduleMode.manual.rawValue { return Copy.afterImportWhenYouAsk }
        if scheduledCanRead(i), let p = i.preview, let when = whenPhrase(i.schedule) {
            return Copy.afterImportScheduled(when: when, engine: Copy.engineUse(p.scheduled.engine))
        }
        if let p = i.preview, planEngines.contains(p.manual.engine) { return Copy.afterImportPlanWaits }
        return Copy.afterImportWaits
    }

    /// A mode that cannot deliver is not offered (design §4.2's schedule question).
    static func enabledModes(_ i: HonestyInputs) -> Set<ScheduleMode> {
        scheduledCanRead(i) ? Set(ScheduleMode.allCases) : [.manual]
    }

    /// The evening reminder is offered whenever reads happen only on request.
    static func offerEveningReminder(_ i: HonestyInputs) -> Bool {
        i.schedule.mode == ScheduleMode.manual.rawValue || !scheduledCanRead(i)
    }

    /// Track P R4: an `interval` set in Settings is shown read-only, never downgraded.
    static func preservedMode(_ i: HonestyInputs) -> ScheduleMode? {
        i.schedule.mode == ScheduleMode.interval.rawValue ? .interval : nil
    }
}
