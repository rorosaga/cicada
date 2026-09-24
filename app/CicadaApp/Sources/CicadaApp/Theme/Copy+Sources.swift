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

    // MARK: Browsers (C9)
    static func browserReads(_ what: BrowserReadable) -> String {
        switch what {
        case .bookmarks: "Bookmarks"
        case .readingList: "Reading List"
        case .favorites: "Favorites"
        case .recentlySaved: "recently saved first"
        case .tabGroups: "open tab groups"
        }
    }
    static let browserOffLine = "Found on this Mac — turn it on to bring your bookmarks in"
    static func browserNothingYet(_ name: String) -> String { "\(name) has no bookmarks in its main profile yet" }
    static let browserTurnOn = "Turn on"
    /// Not "main profile": a Safari that looks empty is usually one macOS is hiding until Full Disk Access is on.
    static let safariNothingYet = "Nothing from Safari yet — turn it on to bring your bookmarks in"
    static let browserTryAgain = "Try again"
    static let browserSyncNow = "Sync now"
    static func browsersUnsupported(_ names: [String]) -> String {
        switch names.count {
        case 0: ""
        case 1: "\(names[0]) isn't supported yet"
        default: "\(names.dropLast().joined(separator: ", ")) and \(names[names.count - 1]) aren't supported yet"
        }
    }
    static let safariRecentlySaved = "Recently saved"
    static let safariFavorites = "Favorites"
    static let safariOtherBookmarks = "Other bookmarks"
}
