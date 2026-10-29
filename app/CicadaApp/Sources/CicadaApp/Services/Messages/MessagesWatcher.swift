import Foundation
import Observation

/// G179 — the Messages conversations the person ticked, read by the APP from `chat.db` and posted per memory.
///
/// **Nothing is read before a tick.** Opening the Sources page → Messages lists the one-to-one conversations
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
    /// A group's members' Contacts cards, by handle (only when Contacts is allowed) — never posted, only their names.
    private(set) var memberCards: [String: MessagesContactCard] = [:]
    /// The photo each TICKED conversation's other side shares through Messages ("Share Name and Photo"), small PNG
    /// bytes by conversation id — the bubble's rung after the Contacts photo (`MessagesSharedPhotos`). Kept in memory
    /// for the bubbles and posted to the backend (2026-10-16), which draws it at the chat's page everywhere.
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
    /// Whether Contacts may be read (a test replaces it); never asks.
    @ObservationIgnored var lookUpContactsAllowed: @Sendable () -> Bool
    /// nil when the key store could not be read — never taken as "shares no photo".
    @ObservationIgnored private let lookUpSharedPhotos: @Sendable ([String]) async -> [String: Data]?
    /// When each ticked chat's shared photo was last looked up (found or not): at most once per `sharedRecheck`, so a
    /// changed photo reaches the page within that, without copying the key store on every pass.
    @ObservationIgnored private var sharedCheckedAt: [String: ContinuousClock.Instant] = [:]
    /// What was last posted per chat this session (empty = "shares none"), so an unchanged photo is not posted again.
    @ObservationIgnored private var sharedPosted: [String: Data] = [:]
    @ObservationIgnored private let sharedRecheck: Duration
    @ObservationIgnored private var watch: FSEventsWatch?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var running: Task<String, Error>?
    /// The memory `running` reads for: a run for another memory is stopped and replaced, never joined (G183(d)).
    @ObservationIgnored private var runningBank: String?
    @ObservationIgnored private var lastStarted: ContinuousClock.Instant?

    init(api: any MessagesAPI = APIClient.shared, reader: MessagesReader = MessagesReader(database: MessagesReader.standardDatabase),
         lights: BrowserWatcher? = nil, activity: SyncActivity? = nil, defaults: UserDefaults = .standard,
         folder: URL = MessagesWatcher.messagesFolder, debounce: Duration = .seconds(10),
         minimumInterval: Duration = .seconds(60), makeWatch: FolderWatchFactory? = nil,
         bank: @escaping @MainActor () -> String = { "default" },
         lookUpCards: @escaping @Sendable ([String]) async -> [String: MessagesContactCard] = { await MessagesContacts.cards(for: $0) },
         lookUpContactsAllowed: @escaping @Sendable () -> Bool = { MessagesContacts.allowed },
         lookUpSharedPhotos: (@Sendable ([String]) async -> [String: Data]?)? = nil,
         sharedRecheck: Duration = .seconds(3600)) {
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
        self.lookUpContactsAllowed = lookUpContactsAllowed
        // The shared photos live under the same Messages folder the watcher reads (a test's synthetic folder there).
        let nicknames = folder.appendingPathComponent(MessagesSharedPhotos.folderName, isDirectory: true)
        self.lookUpSharedPhotos = lookUpSharedPhotos ?? { handles in
            await Task.detached(priority: .utility) {
                MessagesSharedPhotos.photosIfReadable(for: handles, folder: nicknames)
            }.value
        }
        self.sharedRecheck = sharedRecheck
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
        // Another memory: its picture cache has none of this one's posts, so every ticked chat is looked up and posted.
        sharedCheckedAt = [:]
        sharedPosted = [:]
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
        if conversation.isGroup {
            return MessagesGroupText.title(memberNames(of: conversation), count: conversation.members.count)
        }
        if let named = states[conversation.id]?.actor.name, !named.isEmpty, named != "Unnamed conversation",
           named != conversation.handle { return named }
        return ""
    }

    /// A group's members' Contacts names, in the chat's order; a member without a card is left out (never a handle).
    func memberNames(of conversation: MessagesConversation) -> [String] {
        conversation.members.compactMap { memberCards[$0]?.name }.filter { !$0.isEmpty }
    }

    /// What a pass posts for a group's members: each one's participant key, Contacts name, and the person's own
    /// one-to-one chat with them when it is listed.
    func memberPayloads(of conversation: MessagesConversation) -> [MessagesMemberPayload] {
        guard conversation.isGroup else { return [] }
        return conversation.members.map { handle in
            MessagesMemberPayload(key: MessagesReader.memberKey(conversationId: conversation.id, handle: handle),
                                  name: memberCards[handle]?.name ?? "",
                                  direct: conversations.first { !$0.isGroup && $0.handle == handle }?.id,
                                  contact: Self.postedCard(memberCards[handle], looked: lookedUp.contains(handle)))
        }
    }

    /// The handles this session actually looked up in Contacts (#527 review B3): only for one of them can "no single
    /// card" be said. Permission alone is not a look-up — at launch a pass runs before the list or the bubbles have
    /// read any card, and sending "" then cleared every stored card.
    @ObservationIgnored private(set) var lookedUp: Set<String> = []

    /// Look these handles up, and remember them as looked up only when Contacts could really be read (the look-up
    /// itself answers nothing without permission, and an empty answer then is no "no card").
    private func lookUp(_ handles: [String]) async -> [String: MessagesContactCard] {
        guard !handles.isEmpty else { return [:] }
        let allowed = lookUpContactsAllowed()
        let found = await lookUpCards(handles)
        if allowed { lookedUp.formUnion(handles) }
        return found
    }

    /// What a pass posts as a handle's card: its id when exactly ONE card holds it; `""` when Contacts was read and
    /// none or several cards hold it (the backend clears a stored card); nil when Contacts was not read (it keeps it).
    nonisolated static func postedCard(_ card: MessagesContactCard?, looked: Bool) -> String? {
        if let id = card?.id { return id }
        return looked ? "" : nil
    }

    /// The name a waiting conversation's bubble carries.
    func name(ofWaiting item: MessagesWaitingItem) -> String {
        if let card = cards[item.conversation], !card.name.isEmpty { return card.name }
        return item.name
    }

    // MARK: The list (the Sources page → Messages)

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
        let memberHandles = conversations.filter(\.isGroup).flatMap(\.members)
        let byHandle = await lookUp(conversations.filter { !$0.isGroup }.map(\.handle) + memberHandles)
        var next: [String: MessagesContactCard] = [:]
        for conversation in conversations where !conversation.isGroup {
            if let card = byHandle[conversation.handle] { next[conversation.id] = card }
        }
        cards = next
        memberCards = byHandle.filter { memberHandles.contains($0.key) }
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
            // The backend drops the chat's posted photo with the untick (`messages_photos.forget`).
            tickedIds.remove(conversation.id)
            sharedPhotos[conversation.id] = nil
            sharedCheckedAt[conversation.id] = nil
            sharedPosted[conversation.id] = nil
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

    /// The person's "Read again" (2026-10-20): every ticked conversation of this memory from its first message, so the
    /// sittings saved before reactions, replies, edits and attachments were kept get them. The backend merges by
    /// message; where no word moved it writes beside the words only, so Sleep reads nothing again. Never automatic.
    func readAgain() async throws -> String {
        guard !tickedIds.isEmpty else { throw BrowserImportActions.ImportActionError.failed(Copy.Messages.tickFirst) }
        if let running { _ = await running.result }
        let bank = self.bank()
        for id in tickedIds { save(MessagesCursor(), bank: bank, id: id) }
        return try await run(force: true).get()
    }

    @discardableResult
    func run(force: Bool) async -> Result<String, Error> {
        let bank = self.bank()
        if let running {
            // One at a time per memory; a second caller shares the run. A run still reading for the memory the person
            // switched away from is stopped instead: its writes are bound to that memory (refused there now), and the
            // memory on screen reads past its own cursors at once rather than after the old run (G183(d)).
            if runningBank == bank { return await running.result }
            running.cancel()
        }
        guard !tickedIds.isEmpty else { return .failure(CancellationError()) }
        let task = Task { @MainActor [weak self] () throws -> String in
            guard let self else { throw CancellationError() }
            // G183(d): every batch (and the photos after it) names the memory whose cursors it reads and advances.
            return try await BankScope.bound(to: bank) { try await self.perform(bank: bank) }
        }
        running = task
        runningBank = bank
        lastStarted = .now
        activity?.began(Self.channel, detail: Copy.Messages.reading, cancel: { [weak self] in self?.cancel() })
        status = .syncing
        publish()
        let result = await task.result
        guard running == task else { return result }   // replaced by the memory on screen's own run: it owns the row
        running = nil
        runningBank = nil
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
            if conversation.isGroup, conversation.members.contains(where: { memberCards[$0] == nil }) {
                let found = await lookUp(conversation.members.filter { !lookedUp.contains($0) })
                for (handle, card) in found { memberCards[handle] = card }
            }
            if !conversation.isGroup, cards[conversation.id] == nil, !lookedUp.contains(conversation.handle) {
                // B3: a one-to-one chat looks its other side up too, so a launch pass never posts a card it never read.
                if let card = await lookUp([conversation.handle])[conversation.handle] { cards[conversation.id] = card }
            }
            let name = self.postedName(of: conversation)
            let members = self.memberPayloads(of: conversation)
            // A one-to-one chat's other side, by their one address-book card (never the handle).
            let contact = conversation.isGroup ? nil
                : Self.postedCard(cards[conversation.id], looked: lookedUp.contains(conversation.handle))
            for _ in 0..<20 {   // bounded catch-up: at most 20 batches per pass
                let since = cursor
                let pass = try await Task.detached(priority: .utility) {
                    try reader.read(conversation, name: name, members: members, contact: contact, since: since)
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
        await refreshSharedPhotos(read)
        return posted > 0 ? Copy.Messages.synced(posted) : Copy.Messages.upToDate
    }

    /// The bubbles' numbers. A failure keeps the last known list (never blank).
    func refreshWaiting() async {
        guard let answer = try? await api.fetchMessagesWaiting() else { return }
        waiting = answer.conversations
        let noCard = Set(waiting.map(\.conversation).filter { cards[$0] == nil })
        if !noCard.isEmpty {
            let carded = await handles(for: noCard)
            let found = await lookUp(carded.map(\.handle))
            for conversation in carded {
                if let card = found[conversation.handle] { cards[conversation.id] = card }
            }
        }
        await refreshSharedPhotos()
    }

    /// The listed conversations for `ids`, read by id for any the list does not hold.
    private func handles(for ids: Set<String>, known: [MessagesConversation]? = nil) async -> [MessagesConversation] {
        var found = (known ?? conversations).filter { ids.contains($0.id) }
        let missing = ids.subtracting(found.map(\.id))
        if !missing.isEmpty {
            let reader = self.reader
            found += (try? await Task.detached(priority: .utility) { try reader.conversations(ids: missing) }.value) ?? []
        }
        return found
    }

    /// The photo each ticked chat shares in Messages (2026-10-16). Read only for a conversation the person ticked
    /// (G179's rule for everything under ~/Library/Messages) — every ticked one, not only those waiting, because a chat
    /// Sleep already read still has a page to draw — at most once per `sharedRecheck`. What changed since the last post
    /// is posted (`PUT /sources/messages/photos`): the backend keeps it outside every bank and draws it at the chat's
    /// page. A key store that could not be read posts nothing, so a page never loses its picture to a revoked
    /// permission; a refused or failed post is tried again at the next look-up.
    func refreshSharedPhotos(_ known: [MessagesConversation]? = nil) async {
        let now = ContinuousClock.now
        let due = tickedIds.filter { id in sharedCheckedAt[id].map { now - $0 >= sharedRecheck } ?? true }
        guard !due.isEmpty else { return }
        let chats = await handles(for: due, known: known).filter { !$0.handle.isEmpty }
        guard !chats.isEmpty, let found = await lookUpSharedPhotos(chats.map(\.handle)) else { return }
        var changed: [MessagesPhotoPayload] = []
        for chat in chats where tickedIds.contains(chat.id) {
            sharedCheckedAt[chat.id] = now
            let photo = found[chat.handle]
            sharedPhotos[chat.id] = photo
            if sharedPosted[chat.id] != (photo ?? Data()) {
                changed.append(MessagesPhotoPayload(conversation: chat.id, photo: photo))
            }
        }
        guard !changed.isEmpty, (try? await api.putMessagesPhotos(changed)) != nil else { return }
        for payload in changed {
            sharedPosted[payload.conversation] = payload.photoB64.flatMap { Data(base64Encoded: $0) } ?? Data()
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
