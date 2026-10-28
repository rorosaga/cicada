import Foundation

/// Meaning index 2 — the words for a recording or video the person adds to search (`MediaFileIndexer`). DR-59:
/// sentence case, plain verbs. Provider-neutral (owner 2026-09-30): the step is described ("on this Mac"), never a
/// framework's or a model's name. One toast per drop, the existing toast — no new visual pattern.
extension Copy {
    static func mediaAdding(_ n: Int) -> String {
        n == 1 ? "Reading the recording on this Mac so you can search what it says…"
            : "Reading \(n) recordings on this Mac so you can search what they say…"
    }

    static func mediaAdded(_ outcomes: [MediaFileIndexer.AddOutcome]) -> String {
        let added = outcomes.filter { if case .added = $0 { return true }; return false }.count
        let words = outcomes.compactMap { o -> String? in if case .noWords(let r) = o { return r }; return nil }
        if added == 0, let reason = words.first { return reason }
        if outcomes.contains(.failed) && added == 0 { return "That recording couldn't be read." }
        let base = added == 1 ? "Added to search. Its words are the recording's, not yours."
            : "\(added) added to search. Their words are the recordings', not yours."
        return words.isEmpty ? base : base + " " + (words.first ?? "")
    }

    static let mediaSpeechDenied =
        "Kept without its words: speech recognition is off for Cicada (System Settings → Privacy & Security → Speech Recognition)."
    static let mediaNoSpeechModel =
        "Kept without its words: this Mac has no speech model for your language yet (turn on Dictation in System Settings → Keyboard)."
    static let mediaNoWords = "Kept without its words: no speech could be read from it on this Mac."
}
