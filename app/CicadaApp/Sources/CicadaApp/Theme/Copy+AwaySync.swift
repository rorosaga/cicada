import Foundation

/// G229 — the sync the app does when it opens after being closed (`AwaySyncWords` composes the line from these).
/// Counts carry their noun (DR-21): what the bank counts are conversations waiting to be read, the Sleep page's unit.
extension Copy {
    enum AwaySync {
        /// "Syncing Messages and Notes" / "studio is syncing Messages" / "Syncing" while no reader has started yet.
        static func syncing(_ names: String, machine: String?) -> String {
            let what = names.isEmpty ? "" : " \(names)"
            return machine.map { "\($0) is syncing\(what)" } ?? "Syncing\(what)"
        }
        /// "Synced Messages and Notes" / "studio synced Messages" / "Synced".
        static func synced(_ names: String, machine: String?) -> String {
            let what = names.isEmpty ? "" : " \(names)"
            return machine.map { "\($0) synced\(what)" } ?? "Synced\(what)"
        }
        static func newSoFar(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(newConversations(n, locale)) so far."
        }
        static func new(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "\(newConversations(n, locale))." }
        static let nothingNew = "nothing new."
        /// "9 conversations came in while you were away." — captured while the app was closed (a harness's own hook).
        static func whileAway(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(Copy.SleepV5.conversations(n, locale)) came in while you were away."
        }
        /// The same for another machine, named before it: its app was closed, not the person away.
        static func whileClosed(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(Copy.SleepV5.conversations(n, locale)) came in while its app was closed."
        }
        /// A failed source's first clause, the one part in `warning` (DR-7).
        static func couldNotRead(_ label: String) -> String { "\(label) couldn't be read." }
        /// A light that failed with no sentence of its own: its row says the fix.
        static let seeItsRow = "Its row on Sources says what to do."
        static let openSourcesHelp = "Open Sources"
        static let openSleepHelp = "Open Sleep"

        private static func newConversations(_ n: Int, _ locale: Locale) -> String {
            "\(UsageFormat.count(n, locale: locale)) new \(n == 1 ? "conversation" : "conversations")"
        }
    }
}
