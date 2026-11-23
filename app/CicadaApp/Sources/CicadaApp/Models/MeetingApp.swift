import Foundation

/// Owner 2026-11-23: "icons instead of words for Google Meet, Teams, Zoom, etc." — the call app a recorder names (Hex's
/// `**App:**` line, `meeting.app`) as the origin id whose mark `OriginMark` draws: the installed app's own icon first,
/// else the bundled mark (`Resources/logos`), else nothing. The name stays the mark's `.help` and VoiceOver label.
enum MeetingApp {
    /// The mark's origin id for a recorder's app name, or nil when no mark is known (the name is then said in words).
    static func origin(for app: String?) -> String? {
        let name = (app ?? "").lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return nil }
        if name.contains("meet") && (name.contains("google") || name == "meet") { return "google-meet" }
        if name.contains("zoom") { return "zoom" }
        if name.contains("teams") { return "microsoft-teams" }
        if name.contains("slack") { return "slack" }
        if name.contains("discord") { return "discord" }
        if name.contains("facetime") { return "facetime" }
        if name.contains("webex") { return "webex" }
        return nil
    }

    /// "17 min", "1 h 5 min" — a meeting's length, from seconds rounded to the minute.
    static func length(seconds: Int?) -> String? {
        guard let seconds, seconds > 0 else { return nil }
        let minutes = max((seconds + 30) / 60, 1)
        return minutes >= 60 ? "\(minutes / 60) h \(minutes % 60) min" : "\(minutes) min"
    }
}
