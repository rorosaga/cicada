import Foundation

/// The connect sheets' shared words (DESIGN_RULES §9, 2026-10-29). Provider-neutral: a service is named only as itself.
extension Copy {
    enum Connect {
        static let cancel = "Cancel"
        static let back = "Back"
        static let continueStep = "Continue"
        static let connect = "Connect"
        static let done = "Done"
        static let whatItReads = "What Cicada reads"
        static let phonePrompt = "Phone number"
        static let countrySearch = "Search countries or codes"
        static func countryHelp(_ name: String) -> String { "\(name) — choose another country" }
        static func countryAccessibility(_ name: String, _ dial: String) -> String { "Country: \(name), \(dial)" }
        static func codeAccessibility(_ length: Int) -> String { "\(length)-digit code" }
    }
}
