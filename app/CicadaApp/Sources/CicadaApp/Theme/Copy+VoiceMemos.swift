import Foundation

/// G43 — Voice Memos as a source. DR-59 (one line, sentence case), DR-38 (said once). Provider-neutral (owner
/// 2026-09-30): the step is described, never a framework's or a model's name.
extension Copy {
    static let voiceMemosTitle = "Voice Memos"
    static let voiceMemosConnectHelp = "What you said in each recording, to search by what it says. "
        + "Words are made on this Mac; the audio never leaves it."
    static let voiceMemosSyncing = "Reading your recordings…"
    static func voiceMemosHolds(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        n == 1 ? "1 recording" : "\(UsageFormat.count(n, locale: locale)) recordings"
    }
    static func voiceMemosWithoutWords(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) without words"
    }
    static let voiceMemosMissing = "No recordings here yet. Record one in Voice Memos, then Refresh."
    static let voiceMemosUnreadable = "Couldn't read your Voice Memos."
    static let voiceMemosSyncFailed = "Couldn't read Voice Memos. Cicada will try again."
    static let voiceMemosNeedsUpdate = "This version of Cicada's background service can't read recordings yet — update "
        + "Cicada, then Refresh."
}
