import Foundation

/// G132 phase 2 (ruling 51a) — the words for the memory's home: the one device that runs consolidation and keeps every
/// change in order, and moving it (the Sleep page's strip). Not the Home page (`Copy+Home.swift`). DR-59: sentence
/// case, plain verbs. Provider-neutral (owner 2026-09-30): a device is the name the person gave it.
extension Copy {
    enum MemoryHome {
        static func runsOn(_ name: String) -> String { "Sleep runs on \(name)" }
        static let thisComputer = "this computer"
        static let notAnswering = "not answering"
        static let sleepIdle = "idle"
        static let sleepRunning = "consolidating"
        static func sleepStage(_ stage: Int, _ total: Int) -> String { "consolidating, stage \(stage) of \(total)" }
        static let online = "online"
        static let offline = "offline"
        static let noCopy = "keeps no copy"
        static let lagUnknown = "how far behind not known yet"
        static let upToDate = "up to date"
        static func behind(_ n: Int) -> String { n == 1 ? "1 change behind" : "\(n) changes behind" }

        static let makeHome = "Make this the home"
        static func makeHomeHelp(_ name: String) -> String {
            "Move consolidation to \(name): it runs Sleep and keeps every change in order from then on"
        }
        static func moveTitle(_ name: String) -> String { "Make \(name) the home?" }
        static func moveMessage(_ name: String) -> String {
            "\(name) runs Sleep and keeps every change in order from then on, and this memory's other devices follow "
                + "it. If Sleep is running it stops at a safe point first; what it filed stays filed. Changes wait a "
                + "few seconds while it moves."
        }
        static func move(_ name: String) -> String { "Move to \(name)" }

        static let takeOver = "Take over on this computer…"
        static let takeOverHelp = "Only if the computer that held your memory is lost; you see how far behind this one "
            + "is first"
        static let takeOverTitle = "Take over on this computer?"
        static let takeOverConfirm = "Take over"
        static let cancel = "Cancel"
        static let failed = "That did not work just now; nothing was changed."
    }
}
