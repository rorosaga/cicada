import Foundation

/// The connect sheets' shared words (DESIGN_RULES §9, 2026-10-29). Provider-neutral: a service is named only as itself.
extension Copy {
    enum Connect {
        static let cancel = "Cancel"
        static let back = "Back"
        static let continueStep = "Continue"
        static let connect = "Connect"
        static func connect(_ label: String) -> String { "Connect \(label)" }
        /// Where a source with no sign-in comes in instead (owner 2026-11-05: no token, key or password is asked for).
        static let noSignIn = "No sign-in here. Use your browser or a file."
        static let done = "Done"
        static let whatItReads = "What Cicada reads"
        /// Choosing what a sign-in may read (owner 2026-11-09): right after connecting, and from the same panel later.
        static let chooseTitle = "Choose what Cicada reads"
        static let chooseNothingYet = "Nothing is read until you choose."
        static let chooseStart = "Start reading"
        static let chooseSave = "Save"
        static let chooseChange = "Change"
        static let chooseLoading = "Looking at what you can choose…"
        static let chooseNothingFound = "Nothing found."
        static func chooseSearch(_ noun: String) -> String { "Search \(noun)" }
        static func chooseCount(_ n: Int, noun: String) -> String { n == 0 ? "None chosen" : "\(n) chosen" }
        static let chooseMore = "Search to find more."
        static let readingEverything = "Reading everything."
        static func readingChosen(_ n: Int, noun: String) -> String { "Reading \(n) you chose." }
        static let waitingToChoose = "Waiting for you to choose what to read."
        static let phonePrompt = "Phone number"
        static let countrySearch = "Search countries or codes"
        static func countryHelp(_ name: String) -> String { "\(name) — choose another country" }
        static func countryAccessibility(_ name: String, _ dial: String) -> String { "Country: \(name), \(dial)" }
        static func codeAccessibility(_ length: Int) -> String { "\(length)-digit code" }
    }
}
