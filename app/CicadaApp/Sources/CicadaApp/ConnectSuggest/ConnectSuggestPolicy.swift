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
        /// G221 — a site whose save control Cicada can notice (X, Instagram, GitHub, TikTok). Owner 2026-11-23 ("a
        /// small notch notification catches when the user is on X, and says something like connect Cicada to X, with
        /// a don't ask again, or ask me later"): the one case where the page in the front tab IS the trigger, and
        /// only once the person has already given Cicada the Accessibility permission — the page's address is read
        /// when the pointer rests, kept nowhere, and used for nothing but this offer.
        case saves
        /// G245 — a site that is a source but keeps no save control Cicada can read (LinkedIn, Pinterest, Substack,
        /// Spotify, Goodreads): offered the same way, and a Yes turns on only its saved list.
        case savedList
    }

    /// The memory key of a site's offer (`site-save:x`): one answer per site, beside the apps' own.
    static let sitePrefix = "site-save:"
    static func site(_ key: String) -> Target {
        Target(entryId: sitePrefix + key, kind: SiteSaveSite.named(key) != nil ? .saves : .savedList)
    }
    static func siteKey(entryId: String) -> String? {
        entryId.hasPrefix(sitePrefix) ? String(entryId.dropFirst(sitePrefix.count)) : nil
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

    /// False only for a source that left the offer (`SourceCatalog.wisprOffered`): no suggestion, nothing to undo.
    static func offered(_ entryId: String) -> Bool {
        SourceCatalog.wisprOffered || entryId != SourceCatalog.wisprChannel
    }

    static func target(bundleId: String?) -> Target? {
        guard let bundleId else { return nil }
        if let target = fixed[bundleId] { return offered(target.entryId) ? target : nil }
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

    /// The catalogue entry a target is: the entry id itself for an app, the site's key for a site (`site-save:x` is the
    /// entry `x`). Every supported browser and Wispr Flow (while on offer) are entries: the app in front is running, so it
    /// is here — Hex too (`hexPresent`), whose status is its meeting folders' (#579). Nil when the catalogue has no such
    /// entry.
    static func entry(of entryId: String, overview: [SourceOverview],
                      meetingFolders: [FolderRegistration] = []) -> SourceCatalogEntry? {
        let id = siteKey(entryId: entryId) ?? entryId
        return SourceCatalog.entries(browsers: BrowserInventory.catalog.filter(\.supported),
                                     wisprPresent: SourceCatalog.wisprOffered,
                                     hexPresent: true, meetingFolders: meetingFolders, overview: overview)
            .first { $0.id == id }
    }

    /// What the reading model knows about the person's lists (`ReadingAgentModel`), as values: the catalogue reads a
    /// list that is on, or a site the person's agent may open, as the source's own state, and the notch must read the
    /// same (found 2026-11-24: it read them as Off and offered a source the page showed as set up).
    struct Reading: Equatable, Sendable {
        var readableSites: Set<String> = []
        var savedListsOn: Set<String> = []
        var savedListsRead: Set<String>?
    }

    /// The source's status in the active memory — the Sources catalogue's own (`SourceCatalog.status`), so the notch
    /// and the source's row never disagree. Nil when the catalogue has no such entry.
    static func status(of entryId: String, channels: [SourceChannel], overview: [SourceOverview],
                       localReaders: [String: Bool], reading: Reading = Reading(),
                       meetingFolders: [FolderRegistration] = []) -> SourceCatalogStatus? {
        guard let entry = entry(of: entryId, overview: overview, meetingFolders: meetingFolders) else { return nil }
        return SourceCatalog.status(for: entry, channels: channels, overview: overview,
                                    readableSites: reading.readableSites, localReaders: localReaders,
                                    savedListsOn: reading.savedListsOn, savedListsRead: reading.savedListsRead)
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
        /// Not now (or the panel left on its own): again after the next wait of `ConnectSuggestPolicy.waits`.
        case notNow
    }

    struct Source: Codable, Equatable, Sendable {
        /// The app's name as macOS showed it, for Settings' list (an app's name, never anything read from it).
        var name: String?
        var shown = 0
        var lastShown: Date?
        var answer: Answer?
        var answeredAt: Date?
        /// G221 — when this site's offer last showed because the person clicked its save control
        /// (`ConnectSuggestPolicy.Trigger.saveClick`): such a click may show the offer once inside a wait.
        var saveShown: Date?
    }

    var sources: [String: Source] = [:]
    /// The last suggestion of any source: at most one a day between different sources.
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
/// - **Not now waits longer each time** (`waits`; owner 2026-11-23: "14 days is a lot. maybe a progressive cooldown is
///   better. like a first a couple of hours. then a day, and so on until max 14 days"): two hours after the first, then
///   a day, three days, a week and two weeks, and the offer after the two-week wait is the last. The panel leaving on
///   its own counts as Not now, so an offer missed once is back the same afternoon, and someone who never looks at it
///   sees each source six times over about a month and then never. Found live: one untouched panel used to silence a
///   source for 14 days, which read as the feature being broken.
/// - **No is never again** for that source; Settings lists it with Suggest again.
/// - **At most one a day between different sources** (a rolling 24 h, so no day boundary or zone decides it). A
///   source's own return follows its own wait: the cap is against a pile of different offers, not against the one the
///   person put off. A site's offer (G221) is not held by the cap: it only shows on that site, whose saves do nothing
///   until it is connected.
/// - **Never in the first minute** after the app launched (it is still opening windows, restoring, asking for
///   things), nor in the first minute after Cicada launched (the memory's sources are not read yet). A suggestion is
///   never deferred to later: it belongs to the moment the person entered the app, so a refused one waits for the next
///   time they bring it forward.
/// - **A save made on a site that is not connected** (ruling 77b, owner 2026-11-24, after three saves on unconnected
///   sites passed unseen: "yes go ahead and do it") shows that site's offer at that moment, and Yes keeps the save.
///   It is the person's strongest sign that the site matters, so it may show once inside a wait (an offer that left
///   unanswered when the page opened must not silence the save that follows it); after an offer a save brought, the
///   wait holds for saves too. No, the cap on shows and every rule below hold for it as for any offer.
/// - **Never over the ask-why panel**, never twice at once, never in a demo memory, never before the active memory is
///   known or before its setup ran or was skipped (setup's own Sources step offers every source — found live: the
///   offer's Yes landed behind the Welcome), and never for a source that is set up (connected, waiting on a sign-in
///   or on an agent).
enum ConnectSuggestPolicy {
    /// How long a source waits after each Not now, by how many times it has shown; the offer after the last wait is
    /// the last one.
    static let waits: [TimeInterval] = [2 * 3600, 24 * 3600, 3 * 24 * 3600, 7 * 24 * 3600, 14 * 24 * 3600]
    static var maxShows: Int { waits.count + 1 }
    static let dailyGap: TimeInterval = 24 * 3600
    static let launchQuiet: TimeInterval = 60
    /// How long the app must stay in front before the panel shows: a ⌘-Tab that passes through it is not entering it.
    static let dwell: TimeInterval = 1.5
    /// How long an untouched panel stays (the ask-why question's own patience, `SaveWhyPolicy.askTimeout`); the
    /// pointer resting on the panel holds it. The panel shows it as a bar filling along its bottom edge, and nothing
    /// but this and the person's own answer closes it (owner 2026-11-25).
    static let timeout: TimeInterval = SaveWhyPolicy.askTimeout
    /// A click on the panel this soon after it shows was aimed at what was beneath it (`SaveWhyPolicy.armDelay`).
    static let armDelay: TimeInterval = SaveWhyPolicy.armDelay
    /// G221 — how long the panel stays after Yes once it is turned on, showing so (the ring, then the check).
    static let confirmShow: TimeInterval = 1.6
    /// G245 — how long it stays when it has something to say that the person may need to act on: a refusal, or the
    /// Accessibility a site's saves need (with the button that opens the setting). The pointer resting on it holds it.
    static let noteShow: TimeInterval = 7
    /// G245 — the longest a Yes waits for what it started (a reader's first read, macOS's own prompt) before the panel
    /// goes. What it started goes on; the source's page tells the rest.
    static let connectBound: TimeInterval = 60

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

        /// Whether this refusal is about the moment and not the source: the next look at the same page may offer, so
        /// the visit is not spent on it (found 2026-11-24: a site opened in Cicada's first minute, or while another
        /// panel was up, was never offered until the person left it and came back).
        var passes: Bool {
            switch self {
            case .showing, .saveWhyOpen, .memoryUnknown, .noEntry, .appJustLaunched, .cicadaJustLaunched: true
            case .off, .inSetup, .demo, .setUp, .declined, .answered, .shownEnough, .snoozed, .dailyCap: false
            }
        }
    }

    /// What brought the offer: the person entered the app or the site, or (G221, ruling 77b) clicked a site's save
    /// control while that site is not connected.
    enum Trigger: Equatable, Sendable { case entered, saveClick }

    /// Whether `source`'s wait is over for `trigger`. A save click passes a wait once: when the last offer was not
    /// itself brought by a save click.
    static func waited(_ source: ConnectSuggestMemory.Source, now: Date, trigger: Trigger) -> Bool {
        guard source.shown > 0 else { return true }
        if trigger == .saveClick, source.saveShown == nil || source.saveShown != source.lastShown { return true }
        let since = source.answeredAt ?? source.lastShown ?? .distantPast
        return now.timeIntervalSince(since) >= waits[min(source.shown, waits.count) - 1]
    }

    /// G221 — whether a save click on this site could still bring its offer, by what the memory holds alone: only
    /// then is a click on a site that is not connected read at all. A site answered No (or Yes), shown its last time,
    /// or inside a wait a save click cannot pass, is not read.
    static func listens(_ target: ConnectSuggestApps.Target, memory: ConnectSuggestMemory, now: Date) -> Bool {
        let source = memory.sources[target.entryId] ?? .init()
        guard source.answer != .no, source.answer != .yes, source.shown < maxShows else { return false }
        return waited(source, now: now, trigger: .saveClick)
    }

    enum Decision: Equatable {
        case suggest
        case skip(Skip)
    }

    static func decide(_ target: ConnectSuggestApps.Target, memory: ConnectSuggestMemory,
                       context c: Context, trigger: Trigger = .entered) -> Decision {
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
        // Shown before and not answered Yes or No: only after a Not now, and not before the snooze ends. A record
        // with a show but no answer (the app quit while it showed) counts as Not now from when it showed.
        guard waited(source, now: c.now, trigger: trigger) else { return .skip(.snoozed) }
        // The cap is between different sources: when the last offer of all was this source's own, its wait above
        // already decided. A site's offer is not held by it either: the person is on that site now, its saves do
        // nothing until it is connected, and nothing else says why (found live: one site's unanswered offer kept
        // three other sites silent for a day while their saves were missed).
        if target.kind != .saves, let last = memory.lastShown, last != source.lastShown,
           c.now.timeIntervalSince(last) < dailyGap {
            return .skip(.dailyCap)
        }
        if c.now.timeIntervalSince(c.cicadaLaunchedAt) < launchQuiet { return .skip(.cicadaJustLaunched) }
        if let launched = c.appLaunchedAt, c.now.timeIntervalSince(launched) < launchQuiet {
            return .skip(.appJustLaunched)
        }
        return .suggest
    }

    /// The panel showed: counted at once, so a crash or a quit while it shows never makes it free again.
    static func shown(_ entryId: String, name: String? = nil, at now: Date, trigger: Trigger = .entered,
                      in memory: ConnectSuggestMemory) -> ConnectSuggestMemory {
        var memory = memory
        var source = memory.sources[entryId] ?? .init()
        if let name { source.name = name }
        source.shown += 1
        source.lastShown = now
        if trigger == .saveClick { source.saveShown = now }
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

/// What a Yes came to (G245, plan section 7). The write returns before anything is confirmed, so the words are "Turned
/// on", never "Connected" — the page says Connected once a read is dated.
enum ConnectSuggestResult: Equatable, Sendable {
    /// Something was turned on and every write returned. `asksWhy`: the site will really ask on a save (a save control,
    /// its noticing on, Accessibility granted). `needsAccessibility`: noticing saves is on but cannot see them yet.
    case turnedOn(asksWhy: Bool, needsAccessibility: Bool)
    /// The source's page was opened (a choice, a sign-in, a permission, the first-use sheet): the page says the rest.
    case openedPage
    /// A write was refused: the backend's own sentence, or nil for the generic one.
    case failed(String?)

    var isFailure: Bool { if case .failed = self { true } else { false } }
    /// Said until the person has read it (and may press the setting's button), not for a beat.
    var needsReading: Bool {
        switch self {
        case .failed, .turnedOn(_, needsAccessibility: true): true
        default: false
        }
    }
}

/// How an open suggestion closes, and what each way records. Pure, with the clock passed in, so the timeout, the
/// hover hold and the arm delay are tested as values.
///
/// **Only the person's answer or the bar closes it (owner 2026-11-25: "the notification doesn't go away on the first
/// click, but rather when pressing no or a timer of sorts that has a bar filling up at the bottom from left to
/// right").** Until then a click into another app closed it and counted as Not now; now bringing another app forward
/// changes nothing, and the panel stays until No, Not now, Yes, or its bar has filled (`countdownFrom`).
struct ConnectSuggestPanelState: Equatable {
    enum Input: Equatable {
        case yes, no, notNow
        /// The pointer entered or left the card.
        case hover(Bool)
        /// The ask-why question is about to drop from the same notch: it goes first.
        case superseded
        /// A tick of the clock.
        case tick
        /// The one button a result may carry: the setting its words name (Accessibility). Closes the panel.
        case openSetting
    }

    enum Outcome: Equatable {
        case yes, no, notNow, timedOut, superseded

        /// What the memory keeps: the panel leaving on its own, or the ask-why question taking the notch, is Not now.
        var answer: ConnectSuggestMemory.Answer {
            switch self {
            case .yes: .yes
            case .no: .no
            case .notNow, .timedOut, .superseded: .notNow
            }
        }

        /// The log's name for it (an enum, never text).
        var name: String {
            switch self {
            case .yes: "yes"
            case .no: "no"
            case .notNow: "not_now"
            case .timedOut: "timed_out"
            case .superseded: "superseded"
            }
        }
    }

    let target: ConnectSuggestApps.Target
    /// The app's own name as macOS shows it ("WhatsApp", "Google Chrome").
    let appName: String
    let bundleId: String
    /// When it showed, on the monotonic clock (`systemUptime`, as the ask-why panel's own): a wall clock stepped back
    /// can never freeze its timeout or its arm delay.
    let shownAt: TimeInterval
    private(set) var hovering = false
    /// When the untouched-panel clock started: at showing, and again whenever the pointer leaves.
    private(set) var clockFrom: TimeInterval
    /// When Yes was pressed, on the same clock; nil before. From then on the buttons are gone and the panel says what
    /// the Yes is doing (`result` nil: still turning on) and what it came to.
    private(set) var confirmedAt: TimeInterval?
    /// What the Yes came to, once it has (`finish`); and when.
    private(set) var result: ConnectSuggestResult?
    private(set) var finishedAt: TimeInterval?
    /// G221 — the offer holds a save the person just made on this site, which Yes keeps (the line under the title
    /// says so).
    var keepsSave = false

    init(target: ConnectSuggestApps.Target, appName: String, bundleId: String, shownAt: TimeInterval) {
        self.target = target
        self.appName = appName
        self.bundleId = bundleId
        self.shownAt = shownAt
        self.clockFrom = shownAt
    }

    /// Whether the Yes has been pressed and is not yet answered.
    var isConnecting: Bool { confirmedAt != nil && result == nil }

    /// When the bar the panel shows started filling (it runs for `ConnectSuggestPolicy.timeout`): from the showing,
    /// and from empty again each time the pointer leaves the card. nil while the pointer rests on it (the panel is
    /// held, the bar gone) and once Yes was pressed (no timer of the person's runs then).
    var countdownFrom: TimeInterval? { confirmedAt == nil && !hovering ? clockFrom : nil }

    /// What Yes came to: opening the page leaves at once (the page is the answer); anything else is said first. Returns
    /// the outcome when the panel is done now.
    mutating func finish(_ result: ConnectSuggestResult, at now: TimeInterval) -> Outcome? {
        guard confirmedAt != nil, self.result == nil else { return nil }
        self.result = result
        finishedAt = now
        return result == .openedPage ? .yes : nil
    }

    /// The outcome an input ends the panel with, or nil while it stays. A button pressed within the arm delay is
    /// ignored (the hand was on its way to the app beneath). `now` is uptime seconds.
    mutating func handle(_ input: Input, at now: TimeInterval) -> Outcome? {
        switch input {
        case .yes, .no, .notNow:
            guard confirmedAt == nil, now - shownAt >= ConnectSuggestPolicy.armDelay else { return nil }
            if input == .yes {
                confirmedAt = now
                return nil
            }
            return input == .no ? .no : .notNow
        case .openSetting:
            guard let result, result.needsReading else { return nil }
            return .yes
        case .hover(let inside):
            hovering = inside
            if !inside { clockFrom = now }
            return nil
        case .superseded:
            return left(.superseded)
        case .tick:
            if let confirmedAt {
                guard let result, let finishedAt else {
                    return now - confirmedAt >= ConnectSuggestPolicy.connectBound ? .timedOut : nil
                }
                let stay = result.needsReading ? ConnectSuggestPolicy.noteShow : ConnectSuggestPolicy.confirmShow
                if result.needsReading, hovering { return nil }
                guard now - finishedAt >= stay else { return nil }
                return result.isFailure ? .notNow : .yes
            }
            guard !hovering, now - clockFrom >= ConnectSuggestPolicy.timeout else { return nil }
            return .timedOut
        }
    }

    /// The ask-why question took the notch: before a Yes that is Not now; after one the Yes stands (what it started
    /// goes on), unless it was refused.
    private func left(_ before: Outcome) -> Outcome {
        guard confirmedAt != nil else { return before }
        return result?.isFailure == true ? .notNow : .yes
    }
}
