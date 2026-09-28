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
    /// A 409 from the bookmark route: the last sync (perhaps one just stopped) is still saving on this Mac.
    static let bookmarkSyncBusy = "Your last bookmark sync is still finishing. Try again in a minute."
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

    // MARK: Tab groups (G160)
    static let tabGroupsTitle = "Open tab groups"
    static let tabGroupsLive = "Live"
    static let tabGroupsSwitch = "Read Chrome's open tab groups"
    static let tabGroupsOffLine = "Off — turn it on to bring in each group's name, colour and its tabs' titles and links"
    static let tabGroupsNoneYet = "Chrome hasn't saved any open windows on this Mac yet"
    static let tabGroupsNoneOpen = "No open tab groups right now"
    static func tabGroupsCount(_ groups: Int, tabs: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(groups, locale: locale)) open \(groups == 1 ? "group" : "groups") · \(tabsCount(tabs, locale: locale))"
    }
    static let tabGroupsReading = "Reading Chrome's open tabs"
    static func tabGroupsSending(_ groups: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Bringing in \(UsageFormat.count(groups, locale: locale)) \(groups == 1 ? "group" : "groups")"
    }
    static func tabGroupsSynced(groups: Int, tabs: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Synced · " + tabGroupsCount(groups, tabs: tabs, locale: locale)
    }
    static let tabGroupsUpToDate = "Already up to date"
    static let tabGroupsUnreadable = "Chrome keeps its open tabs in a form Cicada can't read yet."
    static let tabGroupsSyncFailed = "Couldn't bring your tab groups in. Cicada will try again."
    static let tabGroupsTurnOnFirst = "Turn on Chrome's open tab groups in Settings → Integrations first — Cicada reads them only after you do."
    static let tabGroupUnnamed = "Unnamed group"
    static let sourceBackendDown = "Cicada's background service isn't answering."
    static let sourceNeedsUpdate = "This version of Cicada's background service can't read this yet — update Cicada."

    // MARK: Contacts (G154)
    static let contactsTitle = "Contacts"
    static let contactsMeta = "Enriches people Cicada already knows"
    static let contactsOff = "Not connected — Connect asks macOS to share your contacts. Nobody new is ever added."
    static let contactsDenied = "Contacts access is off for Cicada — turn it on in System Settings → Privacy & Security → Contacts, then Connect again."
    static let contactsEmpty = "No contacts to read yet"
    static let contactsReading = "Reading your contacts"
    static func contactsMatching(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Matching \(UsageFormat.count(n, locale: locale)) \(n == 1 ? "contact" : "contacts")"
    }
    static func contactsSyncedSummary(contacts: Int, people: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(contacts, locale: locale)) \(contacts == 1 ? "contact" : "contacts") · " + matchedPeople(people, locale: locale)
    }
    static let contactsConnect = "Connect"
    static let contactsSyncNow = "Sync now"
    static let contactsDisconnect = "Disconnect"
    static let contactsStopTitle = "Stop reading your contacts?"
    static let contactsStopDetail = "What Cicada already learned about people stays."
    static let contactsStop = "Stop reading"
    static let contactsConnectFirst = "Connect Contacts in Settings → Integrations first — Cicada reads them only after you do."
    static let contactsSyncFailed = "Couldn't sync your contacts. Cicada will try again."
    static let contactsCardRef = "Their card in Contacts"

    // MARK: What came in, by name (G161)
    static let capturedTitle = "What came in"
    static let capturedHelp = "Each thing this source brought in, by its own title, newest first"
    static let capturedLoading = "Reading what came in…"
    static let capturedNone = "Nothing has come in from this source yet."
    /// Contacts lists the people Cicada knows that a card matched — never a card itself.
    static let capturedNoPeople = "No one in your contacts matched a person Cicada knows yet."
    static let capturedLoadFailed = "Couldn't read what came in. Cicada will try again when you open it."
    static let capturedShowMore = "Show more"
    /// "20 of 229 notes" — `noun` is `CapturedItems.noun`'s pair, so the unit is always said (DR-21).
    static func capturedShown(_ shown: Int, of total: Int, noun: (one: String, many: String),
                              locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(shown, locale: locale)) of \(UsageFormat.count(total, locale: locale)) "
            + (total == 1 ? noun.one : noun.many)
    }
    static func capturedOpenHelp(_ kind: ChannelItem.Kind) -> String {
        switch kind {
        case .episode: "Open in the Reader"
        case .media: "Open in the Feed"
        case .page: "Open their card"
        case .unknown: ""
        }
    }
    static func capturedRowLabel(_ title: String, age: String?) -> String {
        [title, age].compactMap { $0 }.joined(separator: ", ")
    }
}
