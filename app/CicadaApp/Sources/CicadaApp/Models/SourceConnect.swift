import Foundation

// G245 (plan section 7; critic app2, gaps7) — **one connect plan**. Three doors turn a source on: the page's switch, the
// root card's Connect and (a later track) the notch's Yes. Before this each had its own idea of what "connect" does —
// the notch only set a per-Mac flag the page never read, the page raised its first-use sheet from per-view state a caller
// outside it could not reach. `SourceConnect.plan` is the one decision, pure over the catalogue entry and a snapshot of
// what this Mac knows; `SourceConnectRunner` carries it out through injected closures, so every outcome is tested
// without a window, a reader or the network.
//
// The rules it holds (plan 7):
// - A site's Yes turns on the site's existing saved list (never a stream that is new) and, where the site has a save
//   control, noticing saves on this Mac — but only when agent reading is on with a current acknowledgement. Without it
//   nothing is turned on silently: noticing saves alone is done now, and the first-use sheet is asked for on the source's
//   page (`needsConsent`).
// - A Mac app's Yes starts its reader when one click can (macOS's own prompt follows), and opens its page only when a
//   choice is needed (`needsChoice`) — chats to tick, a folder, a sign-in, a permission macOS asks for in Settings.
// - What is already on, or has nothing one click can start, opens the page (`openPage`).

/// The first-use acknowledgement a list's switch asks for before agent reading turns on: which list, and whose page
/// raises it. Held at the app level (`AppRouter.pendingConsent`) so a caller outside the source's page — the notch, the
/// card — can ask for it; the page mounts the sheet.
struct ReadingConsent: Equatable, Hashable, Identifiable, Sendable {
    /// The catalogue entry whose page raises the sheet.
    var entryId: String
    /// `savedLists`, `youtubeLists` or `substackLists` (the `PUT /reading/settings` patches), and the key inside.
    var setting: String
    var key: String

    var id: String { "\(entryId)|\(setting).\(key)" }

    /// The typed forms the sheet's modes still speak (`ReadingFirstUseSheet`).
    var savedListKey: String? { setting == "savedLists" ? key : nil }
    var youtubeList: YouTubeList? { setting == "youtubeLists" ? YouTubeList(rawValue: key) : nil }
    var substackList: SubstackList? { setting == "substackLists" ? SubstackList(rawValue: key) : nil }
}

enum SourceConnect {
    /// What this Mac and the memory know, as values: the plan is a function of these and the entry.
    struct State: Equatable, Sendable {
        /// The catalogue's own status word for the entry (`SourceCatalogRow.status`): never recomputed here.
        var status: SourceCatalogStatus = .off
        /// `ReadingAgentModel`: agent reading is on, and its acknowledgement is current.
        var agentEnabled = false
        var ackCurrent = false
        /// Lists already turned on (`ReadingAgentModel.savedListsOn`).
        var savedListsOn: Set<String> = []
        /// Sites whose saves are already noticed on this Mac (`SiteSavePrefs.noticed`).
        var siteSavesOn: Set<String> = []
        /// Readers already on, by channel (`LocalReaders.on`).
        var readersOn: [String: Bool] = [:]
        /// Preflights only; a permission absent here is unknown and counts as given.
        var permissions: [MacPermission: Bool] = [:]

        var listsReady: Bool { agentEnabled && ackCurrent }
        func granted(_ permission: MacPermission) -> Bool { permissions[permission] ?? true }
    }

    /// One thing to do now.
    enum Step: Equatable, Sendable {
        /// A list's switch, by the contract's own words (`SourceStream.switchRef`).
        case list(setting: String, key: String, on: Bool)
        /// Notice the person's saves on a site, on this Mac (`SiteSavePrefs`).
        case noticeSaves(site: String)
        /// Start the Mac reader the entry owns (the entry's id; macOS's own prompt follows).
        case startReader(entry: String)
    }

    /// Why a page must open: what the person has to choose or do there.
    enum Choice: Equatable, Sendable {
        case chats
        case lists
        case folder
        case signIn
        case feedAddress
        case key
        case consentSheet
        case other
        /// macOS gives it in Settings (a Privacy list Cicada is dragged into): the page's permission row.
        case permission(MacPermission)
    }

    enum Plan: Equatable, Sendable {
        /// Do these now, in order. `thenOpen`: the source's page is also needed (an account to connect after).
        case start([Step], thenOpen: Bool)
        /// Agent reading needs the first-use acknowledgement first. `now` is done at once (noticing saves); the page
        /// opens with the acknowledgement sheet raised for `consent`. Nothing about the list is turned on silently.
        case needsConsent(ReadingConsent, now: [Step])
        /// Open the page: the person chooses or grants something there.
        case needsChoice(Choice)
        /// Open the page: nothing one click can start, or already on.
        case openPage
    }

    // MARK: - The entry's plan

    /// The lists a Yes on a source turns on: the source's existing saved list, never a stream that is new, and never a
    /// history (YouTube's Watch later, Substack's Saved).
    static func defaultLists(_ entry: SourceCatalogEntry) -> [(setting: String, key: String)] {
        if let key = entry.savedListKey { return [("savedLists", key)] }
        switch entry.id {
        case "youtube": return [("youtubeLists", YouTubeList.watchLater.rawValue)]
        case SourceCatalog.substackId: return [("substackLists", SubstackList.saved.rawValue)]
        default: return []
        }
    }

    /// The Mac readers one click starts (the readers' own Connect). Safari's Full Disk Access and every other
    /// permission macOS asks for in Settings is checked first.
    static func startsInOneClick(_ entry: SourceCatalogEntry) -> Bool {
        if entry.id.hasPrefix(SourceCatalog.browserPrefix) { return true }
        switch entry.id {
        case "calendar-local", ContactsReader.channel, AppleNotesWatcher.channel, VoiceMemosReader.channel,
             AppleBooksReader.channel: return true
        default: return false
        }
    }

    /// What a Yes needs from the person on the page, for the sources with no one-click start.
    static func choice(_ entry: SourceCatalogEntry) -> Choice? {
        switch entry.id {
        case MessagesWatcher.channel, WhatsAppWatcher.channel, TelegramChats.channel: .chats
        case RemindersReader.channel: .lists
        case "folders", SourceCatalog.hexId, SourceCatalog.meetingFoldersId: .folder
        case "github", "linear", "notion", "telegram": .signIn
        case "rss", "calendar": .feedAddress
        case GoogleBooksKeyModel.id: .key
        case SourceCatalog.tracesId: .consentSheet
        default: nil
        }
    }

    static func plan(_ entry: SourceCatalogEntry, _ state: State) -> Plan {
        if state.status == .connected { return .openPage }

        let notice: [Step] = SiteSaveSite.named(entry.id).flatMap { site in
            state.siteSavesOn.contains(site.key) ? nil : [Step.noticeSaves(site: site.key)]
        } ?? []
        // A list already on (waiting for an agent's first read) is not turned on again.
        let lists = state.savedListsOn.contains(entry.id) ? [] : defaultLists(entry)

        if !lists.isEmpty {
            guard state.listsReady else {
                let first = lists[0]
                return .needsConsent(ReadingConsent(entryId: entry.id, setting: first.setting, key: first.key),
                                     now: notice)
            }
            return .start(lists.map { Step.list(setting: $0.setting, key: $0.key, on: true) } + notice, thenOpen: false)
        }

        if startsInOneClick(entry) {
            if let permission = ConnectSuggestApps.dragPermission(entryId: entry.id), !state.granted(permission) {
                return .needsChoice(.permission(permission))
            }
            if entry.channels.contains(where: { state.readersOn[$0] == true }) { return .openPage }
            return .start([.startReader(entry: entry.id)], thenOpen: false)
        }

        if let choice = choice(entry) {
            // A site's own save control is noticed at once even where the account itself needs a code or a sign-in.
            if !notice.isEmpty { return .start(notice, thenOpen: true) }
            if case .chats = choice, let permission = ConnectSuggestApps.dragPermission(entryId: entry.id),
               !state.granted(permission) {
                return .needsChoice(.permission(permission))
            }
            return .needsChoice(choice)
        }

        // A list read before: noticing saves alone may still be missing.
        if !notice.isEmpty { return .start(notice, thenOpen: false) }
        return .openPage
    }

    // MARK: - A stream's switch

    /// The page's switch on one stream row (`SourceStream.switchRef`): turning off is always one call; turning on needs
    /// agent reading to be on with a current acknowledgement, else the first-use sheet is asked for first.
    static func planSwitch(entry: String, setting: String, key: String, on: Bool, _ state: State) -> Plan {
        guard ["savedLists", "youtubeLists", "substackLists"].contains(setting) else { return .openPage }
        if !on || state.listsReady { return .start([.list(setting: setting, key: key, on: on)], thenOpen: false) }
        return .needsConsent(ReadingConsent(entryId: entry, setting: setting, key: key), now: [])
    }

    // MARK: - Running a plan

    /// What a plan did. `turnedOn` is said only after every step's write has returned; the page says Connected only
    /// once a read is dated, as before (plan 7, "Honest words").
    enum Outcome: Equatable, Sendable {
        case turnedOn
        /// The page was opened (and a consent raised there, when one was needed).
        case openedPage(consent: ReadingConsent?)
        /// A write was refused: the backend's sentence, or nil for the generic one.
        case failed(String?)
    }

    /// The closures a plan runs through. The live ones are built where the app's models are (`CicadaApp`); a test fakes
    /// each.
    struct Deps {
        /// A list's switch (`ReadingAgentModel.setSwitch`); false when the write was refused.
        var setList: @MainActor (_ setting: String, _ key: String, _ on: Bool) async -> Bool
        var noticeSaves: @MainActor (_ site: String) -> Void
        /// Starts a Mac reader; false when it could not start.
        var startReader: @MainActor (_ entry: String) async -> Bool
        /// Shows the source's page (`AppRouter.routeToCatalogEntry`).
        var openPage: @MainActor (_ entry: String) -> Void
        /// Shows the source's page with the first-use sheet raised (`AppRouter.routeToConsent`).
        var raiseConsent: @MainActor (_ consent: ReadingConsent) -> Void
        /// The sentence the last refused write came with.
        var lastNote: @MainActor () -> String?
    }

    @MainActor
    static func run(_ plan: Plan, entry: String, deps: Deps) async -> Outcome {
        switch plan {
        case .openPage, .needsChoice:
            deps.openPage(entry)
            return .openedPage(consent: nil)
        case .needsConsent(let consent, let now):
            for step in now { _ = await perform(step, deps: deps) }
            deps.raiseConsent(consent)
            return .openedPage(consent: consent)
        case .start(let steps, let thenOpen):
            for step in steps {
                if !(await perform(step, deps: deps)) { return .failed(deps.lastNote()) }
            }
            if thenOpen { deps.openPage(entry) }
            return thenOpen ? .openedPage(consent: nil) : .turnedOn
        }
    }

    @MainActor
    private static func perform(_ step: Step, deps: Deps) async -> Bool {
        switch step {
        case .list(let setting, let key, let on): return await deps.setList(setting, key, on)
        case .noticeSaves(let site):
            deps.noticeSaves(site)
            return true
        case .startReader(let entry): return await deps.startReader(entry)
        }
    }
}
