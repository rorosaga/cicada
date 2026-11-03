import Foundation

/// G231 (owner 2026-11-03: "when you enter an app they support a connection for, they suggest from the notch to connect
/// to it … with our own aesthetic") — which apps Cicada can suggest connecting, and when a suggestion is allowed. Pure:
/// every input is a value and the clock is a parameter, so the respect rules are tested without a panel, a workspace or
/// the time of day.
///
/// **The trigger is the person's own act:** the frontmost app changed (`NSWorkspace.didActivateApplicationNotification`
/// carries a bundle id and needs no permission) to an app below whose source is not set up in the active memory. A
/// website in the front tab is not a trigger: the only permission-free read of a tab is the star-click prefill (owner
/// ruling 2026-10-19, Automation already allowed, the star clicked), and reading the tab on every activation would be
/// watching browsing without the person's act — activity traces' ground (G218, off by default).
enum ConnectSuggestApps {
    /// What the panel says about a kind of source: two or three concrete things Cicada does with it, and one line on
    /// what is read (`Copy.ConnectSuggest`).
    enum Kind: String, Codable, CaseIterable, Sendable {
        case chats, notes, calendar, reminders, contacts, browser, meetings, dictation, notion
    }

    struct Target: Equatable, Sendable {
        /// The Sources catalogue entry this app's source is (`SourceCatalog`), and the key the memory keeps: one answer
        /// per source, so Telegram's two Mac clients share one "No".
        let entryId: String
        let kind: Kind
    }

    /// Bundle id → source. Browsers come from `BrowserInventory.catalog` (only the ones Cicada reads); Hex is the
    /// meeting recorders' entry (#579). Readwise is gone from Sources and is not here.
    static let fixed: [String: Target] = [
        "net.whatsapp.WhatsApp": Target(entryId: "whatsapp", kind: .chats),
        "ru.keepcoder.Telegram": Target(entryId: "telegram-chats", kind: .chats),
        "org.telegram.desktop": Target(entryId: "telegram-chats", kind: .chats),
        "com.apple.MobileSMS": Target(entryId: "imessage", kind: .chats),
        "com.apple.Notes": Target(entryId: "notes", kind: .notes),
        "com.apple.iCal": Target(entryId: "calendar-local", kind: .calendar),
        "com.apple.reminders": Target(entryId: "reminders-local", kind: .reminders),
        "com.apple.AddressBook": Target(entryId: "contacts-local", kind: .contacts),
        "anomaly.hex": Target(entryId: "hex", kind: .meetings),
        "com.electron.wispr-flow": Target(entryId: "wispr-flow", kind: .dictation),
        "notion.id": Target(entryId: "notion", kind: .notion),
    ]

    static func target(bundleId: String?) -> Target? {
        guard let bundleId else { return nil }
        if let target = fixed[bundleId] { return target }
        if let spec = browser(bundleId: bundleId) {
            return Target(entryId: SourceCatalog.browserPrefix + spec.id, kind: .browser)
        }
        return nil
    }

    /// A browser Cicada reads bookmarks from (Arc, Firefox, Edge and Opera are listed but not read: never suggested).
    static func browser(bundleId: String) -> BrowserSpec? {
        BrowserInventory.catalog.first { $0.bundleId == bundleId && $0.supported }
    }

    /// The macOS permission a source cannot be read without and that no button of its own asks for: Full Disk Access
    /// (a list Cicada is dragged into) for Messages, WhatsApp and Safari. Contacts, Calendar, Reminders and Notes ask
    /// macOS's own prompt from their Connect, so their Yes goes straight to the source.
    static func dragPermission(entryId: String) -> MacPermission? {
        switch entryId {
        case "imessage", "whatsapp", SourceCatalog.browserPrefix + "safari": .fullDiskAccess
        default: nil
        }
    }

    /// Where Yes lands: the permission's row in Settings → Privacy & data (with its drag helper, #584's component)
    /// while that permission is missing, else the source's own entry on Sources.
    enum Landing: Equatable {
        case permission(MacPermission)
        case source(String)
    }

    static func landing(entryId: String, permissionGranted: (MacPermission) -> Bool) -> Landing {
        if let permission = dragPermission(entryId: entryId), !permissionGranted(permission) {
            return .permission(permission)
        }
        return .source(entryId)
    }

    /// The source's status in the active memory — the Sources catalogue's own (`SourceCatalog.status`), so the notch
    /// and the source's row never disagree. Every supported browser and Wispr Flow are offered as entries: the app in
    /// front is running, so it is here — Hex too (`hexPresent`), whose status is its meeting folders' (#579), so a Hex
    /// already set up never reads Off. Nil when the catalogue has no such entry.
    static func status(of entryId: String, channels: [SourceChannel], overview: [SourceOverview],
                       localReaders: [String: Bool],
                       meetingFolders: [FolderRegistration] = []) -> SourceCatalogStatus? {
        let entries = SourceCatalog.entries(browsers: BrowserInventory.catalog.filter(\.supported), wisprPresent: true,
                                            hexPresent: true, meetingFolders: meetingFolders, overview: overview)
        guard let entry = entries.first(where: { $0.id == entryId }) else { return nil }
        return SourceCatalog.status(for: entry, channels: channels, overview: overview, readableSites: [],
                                    localReaders: localReaders)
    }
}

/// What this Mac remembers about suggestions — per viewer, in the app's defaults (`ConnectSuggestStore`), never in a
/// bank: it is about the apps on this Mac and the person in front of it, and a memory handed to someone else must not
/// carry "never suggest WhatsApp". Whether a source is connected is never stored here; it is read live from the active
/// memory each time.
struct ConnectSuggestMemory: Codable, Equatable, Sendable {
    enum Answer: String, Codable, Sendable {
        /// Yes: the source's page opened. Never suggested again — the page is where it is finished.
        case yes
        /// No: never again for that source, until Settings undoes it.
        case no
        /// Not now (or the panel left on its own): once more, no sooner than `ConnectSuggestPolicy.snooze`.
        case notNow
    }

    struct Source: Codable, Equatable, Sendable {
        /// The app's name as macOS showed it, for Settings' list (an app's name, never anything read from it).
        var name: String?
        var shown = 0
        var lastShown: Date?
        var answer: Answer?
        var answeredAt: Date?
    }

    var sources: [String: Source] = [:]
    /// The last suggestion of any source: at most one a day overall.
    var lastShown: Date?

    /// The sources the person said No to, oldest first — Settings' undo list.
    var declined: [String] {
        sources.filter { $0.value.answer == .no }
            .sorted { ($0.value.answeredAt ?? .distantPast) < ($1.value.answeredAt ?? .distantPast) }
            .map(\.key)
    }
}

/// When a suggestion may show, and what an answer leaves behind.
///
/// - **On by default, one switch** (Settings → General): the suggestion is the person's way to learn what Cicada can
///   read without a tour, it only ever names an app they just chose to open, and the caps below keep it to a handful
///   a month. Off silences every suggestion at once.
/// - **Once per source, ever**, unless the person says Not now: then once more, no sooner than 14 days later, and that
///   is the last (`maxShows`). The panel leaving on its own counts as Not now, so someone who never looks at it sees
///   each app at most twice, at least two weeks apart. 14 days: long enough that "not now" is honoured as "not this
///   fortnight", short enough that a person who meant "after this deadline" is asked again while the app still matters.
/// - **No is never again** for that source; Settings lists it with Suggest again.
/// - **At most one a day**, all sources together (a rolling 24 h, so no day boundary or zone decides it).
/// - **Never in the first minute** after the app launched (it is still opening windows, restoring, asking for
///   things), nor in the first minute after Cicada launched (the memory's sources are not read yet). A suggestion is
///   never deferred to later: it belongs to the moment the person entered the app, so a refused one waits for the next
///   time they bring it forward.
/// - **Never over the ask-why panel**, never twice at once, never in a demo memory, never before the active memory is
///   known or before its setup ran or was skipped (setup's own Sources step offers every source — found live: the
///   offer's Yes landed behind the Welcome), and never for a source that is set up (connected, waiting on a sign-in
///   or on an agent).
enum ConnectSuggestPolicy {
    static let snooze: TimeInterval = 14 * 24 * 3600
    static let maxShows = 2
    static let dailyGap: TimeInterval = 24 * 3600
    static let launchQuiet: TimeInterval = 60
    /// How long the app must stay in front before the panel shows: a ⌘-Tab that passes through it is not entering it.
    static let dwell: TimeInterval = 1.5
    /// How long an untouched panel stays (the ask-why question's own patience, `SaveWhyPolicy.askTimeout`); the
    /// pointer resting on the panel holds it.
    static let timeout: TimeInterval = SaveWhyPolicy.askTimeout
    /// A click on the panel this soon after it shows was aimed at what was beneath it (`SaveWhyPolicy.armDelay`).
    static let armDelay: TimeInterval = SaveWhyPolicy.armDelay

    struct Context: Equatable {
        var now: Date
        var enabled: Bool
        /// The active memory is known (the roster has loaded and `Store.bank` names it).
        var memoryKnown: Bool
        /// Setup ran (or was skipped) for the active memory: its own Sources step offers every source, so the notch
        /// never offers one over the Welcome or mid-way through it.
        var setUp: Bool
        var isDemo: Bool
        /// The source's status in the active memory, from the Sources catalogue; nil when the catalogue has no such
        /// entry here (Hex before #579, a browser not installed) or the memory's sources are not read yet.
        var status: SourceCatalogStatus?
        var appLaunchedAt: Date?
        var cicadaLaunchedAt: Date
        var saveWhyOpen: Bool
        var showing: Bool
    }

    enum Skip: String, Equatable, Sendable {
        case off, showing, saveWhyOpen, memoryUnknown, inSetup, demo, noEntry, setUp, declined, answered, shownEnough, snoozed,
             dailyCap, appJustLaunched, cicadaJustLaunched
    }

    enum Decision: Equatable {
        case suggest
        case skip(Skip)
    }

    static func decide(_ target: ConnectSuggestApps.Target, memory: ConnectSuggestMemory,
                       context c: Context) -> Decision {
        guard c.enabled else { return .skip(.off) }
        guard !c.showing else { return .skip(.showing) }
        guard !c.saveWhyOpen else { return .skip(.saveWhyOpen) }
        guard c.memoryKnown else { return .skip(.memoryUnknown) }
        guard !c.isDemo else { return .skip(.demo) }
        guard c.setUp else { return .skip(.inSetup) }
        guard let status = c.status else { return .skip(.noEntry) }
        guard status == .off else { return .skip(.setUp) }
        let source = memory.sources[target.entryId] ?? .init()
        switch source.answer {
        case .no: return .skip(.declined)
        case .yes: return .skip(.answered)
        case .notNow, nil: break
        }
        guard source.shown < maxShows else { return .skip(.shownEnough) }
        if source.shown > 0 {
            // Shown before and not answered Yes or No: only after a Not now, and not before the snooze ends. A record
            // with a show but no answer (the app quit while it showed) counts as Not now from when it showed.
            let since = source.answeredAt ?? source.lastShown ?? .distantPast
            guard c.now.timeIntervalSince(since) >= snooze else { return .skip(.snoozed) }
        }
        if let last = memory.lastShown, c.now.timeIntervalSince(last) < dailyGap { return .skip(.dailyCap) }
        if c.now.timeIntervalSince(c.cicadaLaunchedAt) < launchQuiet { return .skip(.cicadaJustLaunched) }
        if let launched = c.appLaunchedAt, c.now.timeIntervalSince(launched) < launchQuiet {
            return .skip(.appJustLaunched)
        }
        return .suggest
    }

    /// The panel showed: counted at once, so a crash or a quit while it shows never makes it free again.
    static func shown(_ entryId: String, name: String? = nil, at now: Date,
                      in memory: ConnectSuggestMemory) -> ConnectSuggestMemory {
        var memory = memory
        var source = memory.sources[entryId] ?? .init()
        if let name { source.name = name }
        source.shown += 1
        source.lastShown = now
        memory.sources[entryId] = source
        memory.lastShown = now
        return memory
    }

    static func answered(_ entryId: String, _ answer: ConnectSuggestMemory.Answer, at now: Date,
                         in memory: ConnectSuggestMemory) -> ConnectSuggestMemory {
        var memory = memory
        var source = memory.sources[entryId] ?? .init()
        source.answer = answer
        source.answeredAt = now
        memory.sources[entryId] = source
        return memory
    }

    /// Settings' Suggest again: the source is as if never suggested (the daily cap still holds).
    static func undoDecline(_ entryId: String, in memory: ConnectSuggestMemory) -> ConnectSuggestMemory {
        var memory = memory
        memory.sources[entryId] = nil
        return memory
    }
}

/// How an open suggestion closes, and what each way records. Pure, with the clock passed in, so the timeout, the
/// hover hold and the arm delay are tested as values.
struct ConnectSuggestPanelState: Equatable {
    enum Input: Equatable {
        case yes, no, notNow
        /// The pointer entered or left the card.
        case hover(Bool)
        /// The person brought another app forward: the suggestion was about the one they left.
        case appChanged
        /// The ask-why question is about to drop from the same notch: it goes first.
        case superseded
        /// A tick of the clock.
        case tick
    }

    enum Outcome: Equatable {
        case yes, no, notNow, timedOut, leftApp, superseded

        /// What the memory keeps: the panel leaving on its own, the person leaving the app, or the ask-why question
        /// taking the notch, is Not now.
        var answer: ConnectSuggestMemory.Answer {
            switch self {
            case .yes: .yes
            case .no: .no
            case .notNow, .timedOut, .leftApp, .superseded: .notNow
            }
        }

        /// The log's name for it (an enum, never text).
        var name: String {
            switch self {
            case .yes: "yes"
            case .no: "no"
            case .notNow: "not_now"
            case .timedOut: "timed_out"
            case .leftApp: "left_app"
            case .superseded: "superseded"
            }
        }
    }

    let target: ConnectSuggestApps.Target
    /// The app's own name as macOS shows it ("WhatsApp", "Google Chrome").
    let appName: String
    let bundleId: String
    let shownAt: Date
    private(set) var hovering = false
    /// When the untouched-panel clock started: at showing, and again whenever the pointer leaves.
    private(set) var clockFrom: Date

    init(target: ConnectSuggestApps.Target, appName: String, bundleId: String, shownAt: Date) {
        self.target = target
        self.appName = appName
        self.bundleId = bundleId
        self.shownAt = shownAt
        self.clockFrom = shownAt
    }

    /// The outcome an input ends the panel with, or nil while it stays. A button pressed within the arm delay is
    /// ignored (the hand was on its way to the app beneath).
    mutating func handle(_ input: Input, at now: Date) -> Outcome? {
        switch input {
        case .yes, .no, .notNow:
            guard now.timeIntervalSince(shownAt) >= ConnectSuggestPolicy.armDelay else { return nil }
            return input == .yes ? .yes : input == .no ? .no : .notNow
        case .hover(let inside):
            hovering = inside
            if !inside { clockFrom = now }
            return nil
        case .appChanged:
            return .leftApp
        case .superseded:
            return .superseded
        case .tick:
            guard !hovering, now.timeIntervalSince(clockFrom) >= ConnectSuggestPolicy.timeout else { return nil }
            return .timedOut
        }
    }
}
