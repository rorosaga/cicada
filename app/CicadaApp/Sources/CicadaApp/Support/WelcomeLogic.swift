import Foundation

/// Design §4.1.5 — the name is required (G117 R1: it is the observer), prefilled
/// from what the person already told Cicada, else the Mac account (no Contacts prompt).
enum WelcomeName {
    static func initial(saved: String?, fullUserName: String) -> String {
        let saved = (saved ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return saved.isEmpty ? fullUserName.trimmingCharacters(in: .whitespacesAndNewlines) : saved
    }

    static func firstWord(_ name: String) -> String {
        name.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: " ").first.map(String.init) ?? ""
    }
}

/// R-IB13 — the one line under the engine cards. The server's preview cannot
/// know a local pick, so a pick says only that Start will save it; an untouched
/// chooser with nothing that can run says so; otherwise ScheduleHonesty speaks.
enum EngineChoiceLine {
    static func text(pickLabel: String?, readiness: EngineReadiness, inputs: HonestyInputs) -> String {
        if let pickLabel { return Copy.welcomePickSaved(pickLabel) }
        if readiness == .needsChoice { return Copy.welcomeNotChosen }
        return ScheduleHonesty.engineLine(inputs)
    }
}
