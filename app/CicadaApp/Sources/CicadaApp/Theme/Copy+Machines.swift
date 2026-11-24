import Foundation

/// G212 — the Sleep page's machines strip.
extension Copy {
    enum Machines {
        static let local = "Local"
        static let lan = "Local network"
        static func waiting(_ n: Int) -> String { "\(UsageFormat.count(n)) waiting" }
        // 2026-11-24 — the chips' words: what the light and the house mean (`.help` and VoiceOver; the light is never alone).
        static func removedName(_ name: String) -> String { "\(name) (removed)" }
        static let runsSleep = "runs Sleep"
        static let keepsCopy = "keeps a copy"
        static func over(_ how: String) -> String { "over \(how)" }
        static let syncing = "syncing"
        static func changesBehind(_ n: Int) -> String { n == 1 ? "1 change behind" : "\(UsageFormat.count(n)) changes behind" }
        static func notSentYet(_ n: Int) -> String {
            n == 1 ? "1 conversation not sent yet" : "\(UsageFormat.count(n)) conversations not sent yet"
        }
        static let removedFact = "removed, its conversations still wait"
        static func heardFrom(_ ago: String) -> String { "heard from \(ago)" }
        static func lastHeardFrom(_ ago: String) -> String { "last heard from \(ago)" }
        static let neverHeard = "not heard from yet"
        static let chipsLabel = "Machines"
        /// The chip's VoiceOver label: its help, and whether it is the one the page is narrowed to.
        static func chipSelected(_ help: String) -> String { "\(help), showing only this machine" }
        /// One line for a machine whose queue is empty while it is the filter.
        static func nothingFrom(_ name: String) -> String { "Nothing from \(name) is waiting." }
        /// A page filtered to one machine, with the way back in `.help`.
        static let showEveryMachine = "Show every machine"
    }
}
