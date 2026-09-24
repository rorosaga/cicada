import Foundation

/// Round 4 (T-Sources) — every sentence the source rows, the browsers, tab groups and Contacts say. One file so the
/// parallel tracks never collide on `Copy+Settings.swift`. Plain words (the owner's rule), counts through
/// `UsageFormat.count` (DR-21), no prices, no ids (DR-54, DR-59).
extension Copy {
    // MARK: Source rows (R-SR12)
    static let lastSyncedJustNow = "Last synced just now"
    static func lastSynced(_ when: String) -> String { "Last synced \(when)" }
    static func importedAt(_ when: String) -> String { "Imported \(when)" }
    static let notSyncedYet = "Not synced yet"
    static let sourceNotConnected = "Not connected"
    static let syncingNow = "Syncing now"
    static let stopSyncing = "Stop syncing"
    static let stopSyncingHelp = "Stop syncing — what already came in stays"
    static let syncStopped = "Stopped — what already came in stays."
    static let sourceNeedsAccess = "Needs Full Disk Access"
    static let sourceSyncFailed = "The last sync didn't finish"

    // MARK: Channel parts (R-SR14)
    static func readingListCount(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Reading List \(UsageFormat.count(n, locale: locale))"
    }
    static func favoritesCount(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Favorites \(UsageFormat.count(n, locale: locale))"
    }
    static func tabsCount(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? "tab" : "tabs")"
    }
    static func matchedPeople(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "matched to \(UsageFormat.count(n, locale: locale)) \(n == 1 ? "person" : "people") Cicada knows"
    }
}
