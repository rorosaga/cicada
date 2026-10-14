import Foundation

/// G191 — when a new bookmark earns the question "What made you save this?". Pure: every input is a value, so the
/// rules are tested without a browser, a panel or a clock.
///
/// The question is worth asking only at the moment of saving — the intent is fresh, and the person is still looking at
/// the page. Everything else is a flood the person never asked for, so each rule below refuses one way a sync can
/// report a "new" bookmark that the person did not just make:
///
/// - **Off by default** (G191 (7)): the Settings switch is on only after the owner tries it.
/// - **Live only.** A sync the file watch started within a second or two of the browser writing its file. A catch-up
///   at launch, a Sync now, a Turn on or a folder import never asks — those bookmarks are minutes or months old.
/// - **Never a first sync.** A browser read for the first time reports its whole history as new.
/// - **One at a time.** Exactly one fresh bookmark in the sync. A bulk import reports many; a bookmark-bar
///   reorganisation reports none, because a moved bookmark is a URL Cicada already holds.
/// - **Made in the last minutes.** When the browser records the instant (Chrome; Safari's Reading List), it must be
///   within `recentWindow` — a bookmark another device synced in hours later is not a moment of saving.
/// - **Not a muted site** ("Don't ask for this site").
/// - **Rate-limited.** At most one question per `minimumGap`, and never while one is showing.
enum SaveWhyPolicy {
    /// How old (by the browser's own clock) a bookmark may be and still be asked about.
    static let recentWindow: TimeInterval = 5 * 60
    /// A clock-skew allowance: a bookmark stamped slightly in the future is still now.
    static let futureSkew: TimeInterval = 60
    /// The least time between two questions.
    static let minimumGap: TimeInterval = 3 * 60
    /// How long an unanswered question stays before it leaves on its own.
    static let askTimeout: TimeInterval = 12
    /// After a tap, how long the panel waits for another tap before it saves the answer (multi-select without a
    /// confirm button).
    static let linger: TimeInterval = 2.5
    /// How long a half-written "Something else…" may sit before the panel leaves (keeping the taps, dropping the
    /// unsent words).
    static let writingTimeout: TimeInterval = 60

    struct Inputs {
        var enabled: Bool
        var live: Bool
        var result: BookmarkSyncResult
        var now: Date
        var lastAsked: Date?
        var mutedHosts: Set<String>
        var showing: Bool
    }

    enum Decision: Equatable {
        case ask(FreshBookmark)
        case skip(Reason)
    }

    enum Reason: String, Equatable {
        case off, notLive, firstSync, noneNew, bulk, notRecent, muted, rateLimited, showing, noHost
    }

    static func decide(_ i: Inputs) -> Decision {
        guard i.enabled else { return .skip(.off) }
        guard i.live else { return .skip(.notLive) }
        guard !i.showing else { return .skip(.showing) }
        if i.result.sources.contains(where: { $0.firstSync == true }) { return .skip(.firstSync) }
        let total = max(i.result.freshTotal, i.result.fresh.count)
        guard total > 0, let item = i.result.fresh.first else { return .skip(.noneNew) }
        guard total == 1 else { return .skip(.bulk) }
        if let added = item.addedDate {
            let age = i.now.timeIntervalSince(added)
            guard age <= recentWindow, age >= -futureSkew else { return .skip(.notRecent) }
        }
        guard let host = item.host else { return .skip(.noHost) }
        if i.mutedHosts.contains(host) { return .skip(.muted) }
        if let last = i.lastAsked, i.now.timeIntervalSince(last) < minimumGap { return .skip(.rateLimited) }
        return .ask(item)
    }
}

/// G191 — what the app remembers between questions: the switch, the last time it asked and the muted sites. Per Mac
/// (`UserDefaults`), beside the bookmark watch's own consent flags — the browser files it reacts to are this Mac's.
struct SaveWhyPrefs {
    static let enabledKey = "cicada.saveWhy.enabled"
    static let lastAskedKey = "cicada.saveWhy.lastAsked"
    static let mutedKey = "cicada.saveWhy.mutedHosts"

    let defaults: UserDefaults

    /// Off unless the person turned it on (G191 (7)).
    var enabled: Bool {
        get { defaults.object(forKey: Self.enabledKey) as? Bool ?? false }
        nonmutating set { defaults.set(newValue, forKey: Self.enabledKey) }
    }

    var lastAsked: Date? {
        get { defaults.object(forKey: Self.lastAskedKey) as? Date }
        nonmutating set { defaults.set(newValue, forKey: Self.lastAskedKey) }
    }

    var mutedHosts: Set<String> {
        get { Set(defaults.stringArray(forKey: Self.mutedKey) ?? []) }
        nonmutating set { defaults.set(newValue.sorted(), forKey: Self.mutedKey) }
    }

    func mute(_ host: String) { mutedHosts = mutedHosts.union([host]) }
}
