import Foundation
import Observation

/// G179 — the Messages conversations the person ticked, read by the APP from `chat.db` and posted per memory.
///
/// **Nothing is read before a tick.** Opening Settings → Integrations → Messages lists the one-to-one conversations
/// (names, last activity, counts — `MessagesReader.conversations`); only a ticked conversation's messages are ever
/// read, and the backend refuses any other. **When it reads:** on launch and on a bank switch when something is ticked,
/// on a tick, on Sync now, and on an FSEvents change in `~/Library/Messages` (Messages appends to `chat.db-wal` on every
/// message) — debounced 10 s and floored at 60 s, like the tab groups. **Unticking** stops the next read and keeps
/// every saved sitting. **A refused read** (Full Disk Access revoked) lights the row `blocked` with the browsers' fix.
@MainActor
@Observable
final class MessagesWatcher {
    nonisolated static let channel = "imessage"
    nonisolated static var messagesFolder: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Messages", isDirectory: true)
    }

    enum Status: Equatable {
        case idle, syncing, watching
        case needsAccess(BrowserFileError)
        case missing
        case failed(String)
    }

    private(set) var status: Status = .idle
    /// The listed one-to-one conversations — live, from this Mac, never read back from a bank.
    private(set) var conversations: [MessagesConversation] = []
    /// The backend's view of each listed conversation: tick, mark and suggestion.
    private(set) var states: [String: MessagesConversationState] = [:]
    /// Names and Contacts photos by conversation id (only when Contacts is allowed).
    private(set) var cards: [String: MessagesContactCard] = [:]
    /// The photo each TICKED conversation's other side shares through Messages ("Share Name and Photo"), small PNG
    /// bytes by conversation id — the bubble's rung after the Contacts photo (`MessagesSharedPhotos`). In memory only.
    private(set) var sharedPhotos: [String: Data] = [:]
    private(set) var tickedIds: Set<String> = []
    private(set) var listing = false
    /// The detectors' suggestions (G188) — on unless the person turned them off for this memory.
    private(set) var suggestAgents = true
    /// What Sleep has not read yet, per conversation — the bubbles.
    private(set) var waiting: [MessagesWaitingItem] = []

    @ObservationIgnored private let api: any MessagesAPI
    @ObservationIgnored private let reader: MessagesReader
    @ObservationIgnored private let lights: BrowserWatcher?
    @ObservationIgnored private let activity: SyncActivity?
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let folder: URL
    @ObservationIgnored private let debounce: Duration
    @ObservationIgnored private let minimumInterval: Duration
    @ObservationIgnored private let makeWatch: FolderWatchFactory
    @ObservationIgnored private let bank: @MainActor () -> String
    @ObservationIgnored private let lookUpCards: @Sendable ([String]) async -> [String: MessagesContactCard]
    @ObservationIgnored private let lookUpSharedPhotos: @Sendable ([String]) async -> [String: Data]
    /// Conversations whose shared photo was already looked up this session (found or not): one read per chat.
    @ObservationIgnored private var sharedLookedUp: Set<String> = []
    @ObservationIgnored private var watch: FSEventsWatch?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var running: Task<String, Error>?
    @ObservationIgnored private var lastStarted: ContinuousClock.Instant?

    init(api: any MessagesAPI = APIClient.shared, reader: MessagesReader = MessagesReader(database: MessagesReader.standardDatabase),
         lights: BrowserWatcher? = nil, activity: SyncActivity? = nil, defaults: UserDefaults = .standard,
         folder: URL = MessagesWatcher.messagesFolder, debounce: Duration = .seconds(10),
         minimumInterval: Duration = .seconds(60), makeWatch: FolderWatchFactory? = nil,
         bank: @escaping @MainActor () -> String = { "default" },
         lookUpCards: @escaping @Sendable ([String]) async -> [String: MessagesContactCard] = { await MessagesContacts.cards(for: $0) },
         lookUpSharedPhotos: (@Sendable ([String]) async -> [String: Data])? = nil) {
        self.api = api
        self.reader = reader
        self.lights = lights
        self.activity = activity
        self.defaults = defaults
        self.folder = folder
        self.debounce = debounce
        self.minimumInterval = minimumInterval
        self.makeWatch = makeWatch ?? { path, onChange in FSEventsWatch(path: path, handler: onChange) }
        self.bank = bank
        self.lookUpCards = lookUpCards
        // The shared photos live under the same Messages folder the watcher reads (a test's synthetic folder there).
        let nicknames = folder.appendingPathComponent(MessagesSharedPhotos.folderName, isDirectory: true)
        self.lookUpSharedPhotos = lookUpSharedPhotos ?? { handles in
            await Task.detached(priority: .utility) { MessagesSharedPhotos.photos(for: handles, folder: nicknames) }.value
        }
    }

    private func cursorKey(_ bank: String, _ id: String) -> String {
        ServerConnection.current.scoped("cicada.messages.cursor.\(bank).\(id)")  // per connection (G181 phase 3)
    }

    func cursor(bank: String, id: String) -> MessagesCursor {
        guard let data = defaults.data(forKey: cursorKey(bank, id)),
              let cursor = try? JSONDecoder().decode(MessagesCursor.self, from: data) else { return MessagesCursor() }
        return cursor
    }

    private func save(_ cursor: MessagesCursor, bank: String, id: String) {
        if let data = try? JSONEncoder().encode(cursor) { defaults.set(data, forKey: cursorKey(bank, id)) }
    }

    // MARK: Lifecycle

    /// On launch: learn this memory's ticks; arm and catch up only when something is ticked.
    func start() { Task { await self.bankChanged() } }

    func bankChanged() async {
        tickedIds = (try? await api.fetchMessagesSettings().tickedIds) ?? []
        waiting = []
        sharedPhotos = sharedPhotos.filter { tickedIds.contains($0.key) }
        sharedLookedUp.formIntersection(tickedIds)
        guard !tickedIds.isEmpty else {
            disarm()
            return
        }
        arm()
        await run(force: false)
        await refreshWaiting()
    }

    /// The name the person sees for a conversation: the contact's, else the chat's own, else the backend's record,
    /// else — in the app only — the handle.
    func name(of conversation: MessagesConversation) -> String {
        let posted = postedName(of: conversation)
        return posted.isEmpty ? conversation.handle : posted
    }

    /// The name the backend may keep: never the handle (a phone number or an address never leaves the app). Empty when
    /// nothing better is known — the backend then says "Unnamed conversation".
    func postedName(of conversation: MessagesConversation) -> String {
        if let card = cards[conversation.id], !card.name.isEmpty { return card.name }
        if !conversation.displayName.isEmpty { return conversation.displayName }
        if let named = states[conversation.id]?.actor.name, !named.isEmpty, named != "Unnamed conversation",
           named != conversation.handle { return named }
        return ""
    }

    /// The name a waiting conversation's bubble carries.
    func name(ofWaiting item: MessagesWaitingItem) -> String {
        if let card = cards[item.conversation], !card.name.isEmpty { return card.name }
        return item.name
    }

    // MARK: The list (Settings → Integrations → Messages)

    func loadList() async {
        listing = true
        defer { listing = false }
        let reader = self.reader
        let ticked = tickedIds
        do {
            // The picker lists the most recent chats; a ticked chat below that cap is still listed, so it can be
            // unticked.
            let found = try await Task.detached(priority: .userInitiated) { () throws -> [MessagesConversation] in
                let recent = try reader.conversations()
                let missing = ticked.subtracting(recent.map(\.id))
                return missing.isEmpty ? recent : recent + (try reader.conversations(ids: missing))
            }.value
            conversations = found
            if status == .missing || isNeedsAccess { status = tickedIds.isEmpty ? .idle : .watching }
        } catch let error as BrowserFileError {
            status = Self.status(for: error)
            publish()
            return
        } catch {
            status = .failed(Copy.Messages.unreadable)
            return
        }
        let byHandle = await lookUpCards(conversations.map(\.handle))
        var next: [String: MessagesContactCard] = [:]
        for conversation in conversations {
            if let card = byHandle[conversation.handle] { next[conversation.id] = card }
        }
        cards = next
        await describe()
    }

    /// The panel's switch: suggestions off leaves every conversation as the person marked it, else unknown; the
    /// backend re-renders the saved sittings to match.
    func setSuggestAgents(_ on: Bool) async throws {
        suggestAgents = on
        _ = try await api.setMessagesSuggestAgents(on)
        await describe()
    }

    /// "Allow Contacts" in the panel: macOS's one prompt (G154's), then the names and photos.
    func allowContacts() async {
        _ = await SystemContactStore().requestAccess()
        await loadList()
    }

    private var isNeedsAccess: Bool { if case .needsAccess = status { true } else { false } }

    private func describe() async {
        let payloads = conversations.map { MessagesConversationPayload($0, name: postedName(of: $0)) }
        guard let answer = try? await api.describeMessagesConversations(payloads) else { return }
        states = Dictionary(answer.conversations.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        suggestAgents = answer.suggestAgents
        tickedIds = Set(answer.conversations.filter(\.ticked).map(\.id)).union(
            tickedIds.subtracting(conversations.map(\.id)))
    }

    /// Tick or untick. A tick is the consent: the conversation is read now. Unticking keeps what is saved.
    func setTicked(_ conversation: MessagesConversation, _ on: Bool) async throws {
        _ = try await api.updateMessagesConversation(id: conversation.id, name: postedName(of: conversation), ticked: on,
                                                     mark: nil)
        if on {
            tickedIds.insert(conversation.id)
        } else {
            tickedIds.remove(conversation.id)
            sharedPhotos[conversation.id] = nil
            sharedLookedUp.remove(conversation.id)
        }
        await describe()
        if on {
            arm()
            await run(force: true)
        } else if tickedIds.isEmpty {
            disarm()
        }
        await refreshWaiting()
    }

    /// The person's answer to "who is this?". The backend re-renders the saved sittings in place.
    func mark(_ conversation: MessagesConversation, as mark: MessagesMark) async throws {
        _ = try await api.updateMessagesConversation(id: conversation.id, name: postedName(of: conversation), ticked: nil,
                                                     mark: mark)
        await describe()
        await refreshWaiting()
    }

    // MARK: Reading

    func syncNow() async throws -> String {
        guard !tickedIds.isEmpty else { throw BrowserImportActions.ImportActionError.failed(Copy.Messages.tickFirst) }
        return try await run(force: true).get()
    }

    func cancel() { running?.cancel() }

    @discardableResult
    func run(force: Bool) async -> Result<String, Error> {
        if let running { return await running.result }
        guard !tickedIds.isEmpty else { return .failure(CancellationError()) }
        let bank = self.bank()
        let task = Task { @MainActor [weak self] () throws -> String in
            guard let self else { throw CancellationError() }
            return try await self.perform(bank: bank)
        }
        running = task
        lastStarted = .now
        activity?.began(Self.channel, detail: Copy.Messages.reading, cancel: { [weak self] in self?.cancel() })
        status = .syncing
        publish()
        let result = await task.result
        running = nil
        activity?.ended(Self.channel)
        switch result {
        case .success:
            status = .watching
            if watch == nil { arm() }
        case .failure(let error) where SyncCancellation.isCancellation(error):
            status = .watching
        case .failure(let error as BrowserFileError):
            status = Self.status(for: error)
        case .failure(let error):
            status = .failed(Self.failureMessage(error))
        }
        publish()
        return result
    }

    /// One pass reads the ticked conversations by their own ids — never through the Settings list, which is capped at
    /// the most recent chats — so a ticked chat syncs whatever its rank.
    private func perform(bank: String) async throws -> String {
        let reader = self.reader
        let ticked = tickedIds
        let read = try await Task.detached(priority: .utility) { try reader.conversations(ids: ticked) }.value
        for fresh in read {
            if let at = conversations.firstIndex(where: { $0.id == fresh.id }) { conversations[at] = fresh }
        }
        var posted = 0
        for conversation in read {
            var cursor = self.cursor(bank: bank, id: conversation.id)
            let name = self.postedName(of: conversation)
            for _ in 0..<20 {   // bounded catch-up: at most 20 batches per pass
                let since = cursor
                let pass = try await Task.detached(priority: .utility) {
                    try reader.read(conversation, name: name, since: since)
                }.value
                try Task.checkCancellation()
                if pass.count == 0 { break }
                activity?.progressed(Self.channel, detail: Copy.Messages.sending(pass.count))
                _ = try await api.postMessages(pass.json)
                try Task.checkCancellation()
                cursor = pass.cursor
                save(cursor, bank: bank, id: conversation.id)
                posted += pass.count
                if !pass.hasMore { break }
            }
        }
        if posted > 0 { await refreshWaiting() }
        return posted > 0 ? Copy.Messages.synced(posted) : Copy.Messages.upToDate
    }

    /// The bubbles' numbers. A failure keeps the last known list (never blank).
    func refreshWaiting() async {
        guard let answer = try? await api.fetchMessagesWaiting() else { return }
        waiting = answer.conversations
        let noCard = Set(waiting.map(\.conversation).filter { cards[$0] == nil })
        // The shared photo is read only for a conversation the person ticked (G179's rule for everything under
        // ~/Library/Messages), once per chat per session.
        let noShared = Set(waiting.map(\.conversation).filter { tickedIds.contains($0) && !sharedLookedUp.contains($0) })
        let unknown = noCard.union(noShared)
        guard !unknown.isEmpty else { return }
        var handles = conversations.filter { unknown.contains($0.id) }
        let missing = unknown.subtracting(handles.map(\.id))
        if !missing.isEmpty {
            let reader = self.reader
            handles += (try? await Task.detached(priority: .utility) { try reader.conversations(ids: missing) }.value) ?? []
        }
        let carded = handles.filter { noCard.contains($0.id) }
        if !carded.isEmpty {
            let found = await lookUpCards(carded.map(\.handle))
            for conversation in carded {
                if let card = found[conversation.handle] { cards[conversation.id] = card }
            }
        }
        let shared = handles.filter { noShared.contains($0.id) && !$0.handle.isEmpty }
        if !shared.isEmpty {
            let found = await lookUpSharedPhotos(shared.map(\.handle))
            for conversation in shared {
                sharedLookedUp.insert(conversation.id)
                if let photo = found[conversation.handle] { sharedPhotos[conversation.id] = photo }
            }
        }
    }

    // MARK: Watching

    private func arm() {
        guard watch == nil else { return }
        watch = makeWatch(folder.path) { [weak self] in self?.changed() }
    }

    private func disarm() {
        watch?.stop()
        watch = nil
        pending?.cancel()
        pending = nil
        if running == nil { status = .idle }
        publish()
    }

    private func changed() {
        guard !tickedIds.isEmpty else { return }
        pending?.cancel()
        pending = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(for: self.debounce)
            guard !Task.isCancelled else { return }
            if let last = self.lastStarted {
                let elapsed = ContinuousClock.now - last
                if elapsed < self.minimumInterval { try? await Task.sleep(for: self.minimumInterval - elapsed) }
                guard !Task.isCancelled else { return }
            }
            await self.run(force: false)
        }
    }

    /// A 409's detail is the server's own sentence (not ticked here, or the demo) — `ProjectWriteFailure.detail`.
    static func failureMessage(_ error: Error) -> String {
        if error is MessagesReadError { return Copy.Messages.unreadable }
        if error is URLError { return Copy.sourceBackendDown }
        guard let api = error as? APIError else { return Copy.Messages.syncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.Messages.syncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.sourceNeedsUpdate
        case .serverUnreachable: return Copy.sourceBackendDown
        default: return Copy.Messages.syncFailed
        }
    }

    private static func status(for error: BrowserFileError) -> Status {
        if case .missing = error { return .missing }
        return .needsAccess(error)
    }

    private func publish() {
        let light: BrowserWatchState? = switch status {
        case .idle: tickedIds.isEmpty ? nil : .watching
        case .syncing: .syncing
        case .watching: .watching
        case .needsAccess: .blocked
        case .missing: .absent
        case .failed: .failed
        }
        let error: BrowserFileError? = if case .needsAccess(let e) = status { e } else { nil }
        lights?.publish(light, error: error, for: Self.channel)
    }
}
