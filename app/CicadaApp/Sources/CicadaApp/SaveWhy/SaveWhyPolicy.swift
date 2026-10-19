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
/// - **One save, one question** (G191 live, owner 2026-10-14: "shouldn't it be immediate?" — bookmarking several
///   sites in a row, every one after the first was silenced by the old three-minute limit). Each single fresh bookmark
///   asks, even in a row; a new one replaces the open panel (`SaveWhyCenter`). Flood protection is structural — the
///   rules above — plus `repeatGuard` against the double events of one save, and the same save is never asked twice
///   within `sameLinkGuard`. Never while the person is writing in the panel's field.
/// - **A re-save asks** (G191 v3, owner 2026-10-15: "If I remove the bookmark and bookmark it again, the prompt doesn't
///   appear. Is that on purpose?"). The backend now reports a link saved again (`FreshBookmark.resave`), and the same
///   link within `sameLinkGuard` is held only when it is the same save: the same browser instant, or none recorded
///   (Safari). A bookmark removed and made again carries a new `date_added`, so it asks.
enum SaveWhyPolicy {
    /// How old (by the browser's own clock) a bookmark may be and still be asked about.
    static let recentWindow: TimeInterval = 5 * 60
    /// A clock-skew allowance: a bookmark stamped slightly in the future is still now.
    static let futureSkew: TimeInterval = 60
    /// The least time between two questions: one save can report twice (a swap's two names, an owed re-read), and two
    /// deliberate bookmarks take longer than this to make.
    static let repeatGuard: TimeInterval = 3
    /// The same save is not asked about again within this (G191 v3: a re-save with its own instant is another save).
    static let sameLinkGuard: TimeInterval = 60
    /// How long an unanswered question stays before it leaves on its own.
    static let askTimeout: TimeInterval = 12
    /// (G191 v3's `answerIdle`/`writingIdle` are gone, owner 2026-10-19: once the person touches the panel no timer
    /// closes it — dictation types nothing for many seconds, then everything at once.)
    /// G191 v3 — how long a pending panel (opened on Chrome's bookmark bubble) waits for the bookmark: Chrome writes
    /// 2.5 s after the click, the watch settles 0.3 s, the read and the look take well under a second. Past this,
    /// no bookmark came (the bubble was another one), and the panel withdraws, keeping nothing.
    static let pendingBound: TimeInterval = 6
    /// And how long a panel the app's own diff named waits for the backend to agree before it withdraws.
    static let confirmBound: TimeInterval = 15
    /// G191 live — how long after the panel appears a click on it still counts as aimed at what was beneath it
    /// (`SaveWhyCenter.input`). Inside the grow (`CicadaMotion`'s notch spring) and well under a deliberate reach.
    static let armDelay: TimeInterval = 0.5
    /// 2026-10-19 — after the person's click inside Chrome's bookmark bubble, when to look (once) whether it closed:
    /// Done closes it, and the panel leaves with it; a click in its name field keeps both.
    static let bubbleCloseCheck: TimeInterval = 0.25
    /// G191 live — the budget from the browser writing its bookmark file to the panel on screen.
    static let showBudget: TimeInterval = 2

    struct Inputs {
        var enabled: Bool
        var live: Bool
        var result: BookmarkSyncResult
        var now: Date
        var lastAsked: Date?
        var mutedHosts: Set<String>
        /// The person is typing in the open panel's "Something else…" — never interrupted.
        var writing: Bool
        /// The link last asked about (with `lastAsked`).
        var lastURL: String? = nil
        /// That save's browser instant (G191 v3): the same link with another instant is another save.
        var lastAddedAt: String? = nil
    }

    enum Decision: Equatable {
        case ask(FreshBookmark)
        case skip(Reason)
    }

    enum Reason: String, Equatable {
        case off, notLive, firstSync, noneNew, bulk, notRecent, muted, repeated, writing, noHost
    }

    static func decide(_ i: Inputs) -> Decision {
        guard i.enabled else { return .skip(.off) }
        guard i.live else { return .skip(.notLive) }
        guard !i.writing else { return .skip(.writing) }
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
        if let last = i.lastAsked {
            let since = i.now.timeIntervalSince(last)
            if since >= 0, since < repeatGuard { return .skip(.repeated) }
            if since >= 0, since < sameLinkGuard, i.lastURL == item.url,
               item.addedAt == nil || i.lastAddedAt == nil || item.addedAt == i.lastAddedAt { return .skip(.repeated) }
        }
        return .ask(item)
    }
}

/// G191 — what the app remembers between questions: the switch, the last time it asked and the muted sites. Per Mac
/// (`UserDefaults`), beside the bookmark watch's own consent flags — the browser files it reacts to are this Mac's.
struct SaveWhyPrefs {
    static let enabledKey = "cicada.saveWhy.enabled"
    static let lastAskedKey = "cicada.saveWhy.lastAsked"
    static let lastURLKey = "cicada.saveWhy.lastURL"
    static let lastAddedAtKey = "cicada.saveWhy.lastAddedAt"
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

    /// The link last asked about — for `SaveWhyPolicy.sameLinkGuard`.
    var lastURL: String? {
        get { defaults.string(forKey: Self.lastURLKey) }
        nonmutating set { defaults.set(newValue, forKey: Self.lastURLKey) }
    }

    /// That link's browser instant — for `SaveWhyPolicy.sameLinkGuard` (G191 v3).
    var lastAddedAt: String? {
        get { defaults.string(forKey: Self.lastAddedAtKey) }
        nonmutating set { defaults.set(newValue, forKey: Self.lastAddedAtKey) }
    }

    var mutedHosts: Set<String> {
        get { Set(defaults.stringArray(forKey: Self.mutedKey) ?? []) }
        nonmutating set { defaults.set(newValue.sorted(), forKey: Self.mutedKey) }
    }

    func mute(_ host: String) { mutedHosts = mutedHosts.union([host]) }
}
