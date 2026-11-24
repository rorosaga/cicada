import Foundation

// G245 — the app's overlay on `GET /sources/streams` (plan 2.1 `owner`, 3.3; critic app6). A stream the backend marks
// `owner: app` is one whose truth only this Mac holds: the reader's own on/off switch, a permission macOS gave or did
// not, the per-Mac flag the notch's Yes sets (`SiteSavePrefs`). The overlay overwrites the stream's `state`, `health`
// and `why` from those and leaves `count` and `lastReadAt` the backend's. A backend-owned stream passes through.
//
// **One truth** (plan 3.1): this never decides a card's state word, the eyebrow's count or the needs-you split — those
// come from `SourceCatalogRow` unchanged. The overlay only says what each stream under a card reads.

/// The one word a stream rests in or a check ends in (plan 3.3). The first six are a check's words.
enum StreamWord: Equatable, Sendable {
    case read, signedOut, couldntRead, needsAccess, yourAIAppReadsNext, notInstalled
    case notReadYet, paused, off, unavailable

    var text: String {
        switch self {
        case .read: Copy.Streams.read
        case .signedOut: Copy.Streams.signedOut
        case .couldntRead: Copy.Streams.couldntRead
        case .needsAccess: Copy.Streams.needsAccess
        case .yourAIAppReadsNext: Copy.Streams.yourAIAppReadsNext
        case .notInstalled: Copy.Streams.notInstalled
        case .notReadYet: Copy.Streams.notReadYet
        case .paused: Copy.Streams.paused
        case .off: Copy.Streams.off
        case .unavailable: Copy.Streams.unavailable
        }
    }

    /// The words a check can end in: a stream that is on always ends a check in one of these.
    var isCheckWord: Bool {
        switch self {
        case .read, .signedOut, .couldntRead, .needsAccess, .yourAIAppReadsNext, .notInstalled: true
        default: false
        }
    }

    /// Blue for a healthy read through the person's own browser (ROR-114, DR-5/DR-8: a data hue, never the accent), the
    /// connection's green for any other healthy read, amber when the person has something to do, grey at rest.
    func tone(how: StreamHow) -> StatusWord.Tone {
        switch self {
        case .read: how == .browser ? .browser : .on
        case .signedOut, .couldntRead, .needsAccess: .attention
        case .yourAIAppReadsNext: .browser
        case .notReadYet, .paused, .off, .unavailable, .notInstalled: .off
        }
    }

    /// What a stream that is on reads as, from what the backend (or the overlay) says of its last read.
    static func resting(_ stream: SourceStream, now: Date = Date()) -> StreamWord {
        switch stream.state {
        case .off: return .off
        case .unavailable: return .unavailable
        case .on: break
        }
        // A check never lifts a pause: a signed-out list keeps saying so, whatever was asked since.
        if stream.health == .signedOut { return .signedOut }
        if stream.how == .browser, stream.checkRequestedAt != nil { return .yourAIAppReadsNext }
        if stream.health == .paused || (stream.pausedUntil.map { $0 > now } ?? false) {
            return stream.health == .couldntRead ? .couldntRead : .paused
        }
        switch stream.health {
        case .couldntRead?: return .couldntRead
        case .read?: return .read
        case .notRead?: return .notReadYet
        default: return stream.lastReadAt == nil ? .notReadYet : .read
        }
    }
}

/// What this Mac itself knows, handed in as values so the overlay is tested with no reader, no defaults and no macOS.
struct StreamAppState: Equatable, Sendable {
    /// `LocalReaders.on`, by channel id: whether each reader on this Mac is turned on (and, for a permissioned one,
    /// allowed). A channel absent from it is one this Mac has no switch for.
    var readers: [String: Bool] = [:]
    /// By catalogue entry id: a reader that cannot read and says why (`LocalReaders.waitingOnAccess`, or the page's
    /// problem line). `Copy.sourceNeedsAccess` is a missing permission; any other sentence is a failed read.
    var waitingOn: [String: String] = [:]
    /// By catalogue entry id: the app was removed from this Mac.
    var notInstalled: Set<String> = []
    /// `SiteSavePrefs().noticedKeys`: the sites whose saves are noticed on this Mac.
    var siteSavesOn: Set<String> = []
    /// `SiteSavePrefs().turnedOff`: the sites the person turned "Saves you make" off for, so the row says that is why.
    var siteSavesOff: Set<String> = []
    /// Preflights only, never a prompt; a permission absent here is unknown and counts as given.
    var permissions: [MacPermission: Bool] = [:]

    func granted(_ permission: MacPermission) -> Bool { permissions[permission] ?? true }
}

/// One stream as the page draws it: the backend's row with the app's overlay on it, and the one word it rests in.
struct ResolvedStream: Equatable, Identifiable, Sendable {
    let source: String
    let stream: SourceStream
    let word: StreamWord
    /// The permission whose setting would fix a `needsAccess` word: the row's one button opens it.
    let fix: MacPermission?
    /// The reader channel this Mac runs for the stream (`ChannelActions.syncRoute`), when it has a run-now.
    let reader: String?

    var id: String { stream.id }
    var tone: StatusWord.Tone { word.tone(how: stream.how) }
}

/// Every source's resolved streams, in the order the backend sent them.
struct ResolvedStreams: Equatable, Sendable {
    var sources: [String: [ResolvedStream]] = [:]
    var accounts: [String: StreamAccount] = [:]

    var isEmpty: Bool { sources.isEmpty }

    func streams(_ source: String) -> [ResolvedStream] { sources[source] ?? [] }
    func stream(_ id: String) -> ResolvedStream? { sources.values.lazy.flatMap { $0 }.first { $0.id == id } }
    func on(_ source: String) -> [ResolvedStream] { streams(source).filter { $0.stream.state == .on } }
}

/// Main-actor because the run-now table it consults (`ChannelActions.syncRoute`) is.
@MainActor
enum SourceStreamOverlay {
    static func resolve(_ response: SourceStreamsResponse?, app: StreamAppState, entries: [SourceCatalogEntry],
                        now: Date = Date()) -> ResolvedStreams {
        guard let response else { return ResolvedStreams() }
        let entryById = Dictionary(entries.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let readerKeys = Set(app.readers.keys)
        var out = ResolvedStreams()
        for source in response.sources {
            let entry = entryById[source.id]
            out.sources[source.id] = source.streams.map { stream in
                resolve(stream, of: source.id, entry: entry, app: app, readerKeys: readerKeys, now: now)
            }
            if let account = source.account { out.accounts[source.id] = account }
        }
        return out
    }

    static func resolve(_ stream: SourceStream, of source: String, entry: SourceCatalogEntry?, app: StreamAppState,
                        readerKeys: Set<String>, now: Date) -> ResolvedStream {
        let reader = readerChannel(source: source, stream: stream, entry: entry, readerKeys: readerKeys)
        guard stream.owner == .app else {
            return ResolvedStream(source: source, stream: stream, word: .resting(stream, now: now), fix: nil,
                                  reader: reader.flatMap { ChannelActions.syncRoute(for: $0) != nil ? $0 : nil })
        }
        var s = stream
        // The app was removed from this Mac: nothing more can come from it, whatever the bank's switch says.
        if app.notInstalled.contains(source) {
            s.state = .unavailable
            s.health = nil
            s.why = Copy.Streams.notInstalled
            return ResolvedStream(source: source, stream: s, word: .notInstalled, fix: nil, reader: nil)
        }
        if stream.how == .click { return clicks(s, source: source, app: app, now: now) }
        guard let reader, let on = app.readers[reader] else {
            // A stream only the app owns, with no switch of this Mac's to read: the backend's words stand.
            return ResolvedStream(source: source, stream: s, word: .resting(s, now: now), fix: nil, reader: nil)
        }
        let run = ChannelActions.syncRoute(for: reader) != nil ? reader : nil
        if let waiting = app.waitingOn[source] {
            // The person turned it on and macOS (or the read) stopped it: on, and the fix is named.
            s.state = .on
            s.why = waiting
            if waiting == Copy.sourceNeedsAccess || waiting == Copy.Catalog.needsAccess {
                s.health = nil
                return ResolvedStream(source: source, stream: s, word: .needsAccess, fix: fix(for: source), reader: run)
            }
            s.health = .couldntRead
            return ResolvedStream(source: source, stream: s, word: .couldntRead, fix: nil, reader: run)
        }
        s.state = on ? .on : .off
        s.why = nil
        guard on else {
            s.health = nil
            return ResolvedStream(source: source, stream: s, word: .off, fix: nil, reader: run)
        }
        if let permission = ConnectSuggestApps.dragPermission(entryId: source), !app.granted(permission) {
            s.health = nil
            s.why = Copy.Streams.permissionWhy
            return ResolvedStream(source: source, stream: s, word: .needsAccess, fix: permission, reader: run)
        }
        s.health = s.lastReadAt == nil ? .notRead : .read
        return ResolvedStream(source: source, stream: s, word: .resting(s, now: now), fix: nil, reader: run)
    }

    /// "Saves you make": noticed from the person's own click on a site, on this Mac. On is the per-Mac flag; Accessibility
    /// is what lets Cicada see a site at all, and ruling 77 says it is never prompted for, so a missing grant is said.
    private static func clicks(_ stream: SourceStream, source: String, app: StreamAppState, now: Date) -> ResolvedStream {
        var s = stream
        let on = app.siteSavesOn.contains(source)
        s.state = on ? .on : .off
        s.why = nil
        guard on else {
            s.health = nil
            // The person's own word keeps a connected site quiet; the row says so rather than only "off".
            if app.siteSavesOff.contains(source) { s.why = Copy.Streams.savesTurnedOff }
            return ResolvedStream(source: source, stream: s, word: .off, fix: nil, reader: nil)
        }
        guard app.granted(.accessibility) else {
            s.health = nil
            s.why = Copy.Streams.accessibilityWhy
            return ResolvedStream(source: source, stream: s, word: .needsAccess, fix: .accessibility, reader: nil)
        }
        s.health = .read
        return ResolvedStream(source: source, stream: s, word: .read, fix: nil, reader: nil)
    }

    /// The reader channel (a key of `StreamAppState.readers`) that governs an app-owned stream, or nil.
    ///
    /// The contract names a stream `<source>.<stream>` and nothing more, so the binding reads the source's catalogue
    /// entry: its channels this Mac runs, narrowed by what the stream is. A browser entry holds three readers (bookmarks,
    /// tab groups, the YouTube history Chrome keeps); the stream's kind and the words in its id tell them apart.
    static func readerChannel(source: String, stream: SourceStream, entry: SourceCatalogEntry?,
                              readerKeys: Set<String>) -> String? {
        guard let entry else { return nil }
        let words = (stream.tail + " " + stream.label).lowercased()
        if source.hasPrefix(SourceCatalog.browserPrefix) {
            // A browser's own three readers: a stream that is the tab groups or the history is never bound to the
            // bookmarks' switch because its own reader has no entry in `readerKeys`.
            func own(_ channel: String) -> String? {
                entry.channels.contains(channel) && readerKeys.contains(channel) ? channel : nil
            }
            if stream.kind == .history || words.contains("history") { return own(WatchHistoryWatcher.channel) }
            if words.contains("tab") { return own(TabGroupWatcher.channel) }
            return entry.channels.first {
                $0 != TabGroupWatcher.channel && $0 != WatchHistoryWatcher.channel && readerKeys.contains($0)
            }
        }
        if stream.kind == .history, entry.channels.contains(WatchHistoryWatcher.channel),
           readerKeys.contains(WatchHistoryWatcher.channel) {
            return WatchHistoryWatcher.channel
        }
        return entry.channels.first { readerKeys.contains($0) }
    }

    /// The setting that fixes a read macOS refused, by entry: the person's one button names it. Full Disk Access for
    /// the readers that open files under ~/Library; each framework's own for Calendar, Contacts and Reminders.
    static func fix(for source: String) -> MacPermission? {
        if let drag = ConnectSuggestApps.dragPermission(entryId: source) { return drag }
        switch source {
        case CalendarRow.channelId: return .calendars
        case ContactsReader.channel: return .contacts
        case RemindersReader.channel: return .reminders
        case AppleNotesWatcher.channel: return .notes
        case AppleBooksReader.channel, VoiceMemosReader.channel: return .fullDiskAccess
        default: return nil
        }
    }
}
