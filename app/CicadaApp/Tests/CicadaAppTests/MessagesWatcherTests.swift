import XCTest
@testable import CicadaApp

@MainActor
final class FakeMessagesAPI: MessagesAPI {
    var ticked: Set<String> = []
    var kinds: [String: String] = [:]
    var waitingItems: [MessagesWaitingItem] = []
    var refuseSync: Error?
    private(set) var posts: [[String: Any]] = []
    private(set) var updates: [(id: String, ticked: Bool?, mark: MessagesMark?)] = []

    func fetchMessagesSettings() async throws -> MessagesSettingsAnswer {
        try JSONDecoder().decode(MessagesSettingsAnswer.self, from: JSONSerialization.data(withJSONObject: [
            "conversations": Dictionary(uniqueKeysWithValues: ticked.map { ($0, ["ticked": true]) })]))
    }

    func describeMessagesConversations(_ conversations: [MessagesConversationPayload]) async throws
        -> MessagesConversationsAnswer {
        // The backend's own wire shape (`messages_source.describe`): `actor` is `Actor.to_dict()`, a free-form block
        // whose keys stay snake_case, and `marked` is the person's stored mark. Decoded, never built in Swift, so a
        // key the app reads wrong fails here as it would live.
        let rows: [[String: Any]] = conversations.map { c in
            let detected = c.name == "Instinct" && c.fromThem >= 2 * max(c.fromMe, 1)
            let kind = kinds[c.id] ?? (detected ? "agent" : "unknown")
            let decidedBy = kinds[c.id] != nil ? "person" : (detected ? "detector" : "none")
            var row: [String: Any] = [
                "id": c.id, "ticked": ticked.contains(c.id), "group": false,
                "actor": ["name": c.name, "kind": kind, "decided_by": decidedBy],
                "suggestion": ["outcome": detected ? "identified" : "unknown"],
            ]
            row["marked"] = kinds[c.id].map { ["kind": $0] } ?? NSNull()
            return row
        }
        return try JSONDecoder().decode(MessagesConversationsAnswer.self, from: JSONSerialization.data(
            withJSONObject: ["suggestAgents": suggest, "conversations": rows]))
    }

    func updateMessagesConversation(id: String, name: String?, ticked: Bool?, mark: MessagesMark?) async throws
        -> MessagesSettingsAnswer {
        updates.append((id, ticked, mark))
        if let ticked { if ticked { self.ticked.insert(id) } else { self.ticked.remove(id) } }
        switch mark {
        case .agent?: kinds[id] = "agent"
        case .person?: kinds[id] = "person"
        case .clear?: kinds[id] = nil
        case nil: break
        }
        return try await fetchMessagesSettings()
    }

    var suggest = true
    func setMessagesSuggestAgents(_ on: Bool) async throws -> MessagesSettingsAnswer {
        suggest = on
        return try await fetchMessagesSettings()
    }

    func postMessages(_ json: Data) async throws -> MessagesSyncResult {
        if let refuseSync { throw refuseSync }
        posts.append(try XCTUnwrap(JSONSerialization.jsonObject(with: json) as? [String: Any]))
        return MessagesSyncResult(created: 1)
    }

    func fetchMessagesWaiting() async throws -> MessagesWaitingAnswer { MessagesWaitingAnswer(conversations: waitingItems) }
}

/// G179 — nothing is read before a tick; a tick reads that conversation only; the cursor is per memory; unticking
/// stops reading and posts nothing; a refused read shows the Full Disk Access fix; the bubbles' names.
@MainActor
final class MessagesWatcherTests: XCTestCase {
    private var synthetic: SyntheticChatDB!
    private var defaults: UserDefaults!
    private var instinct: Int64 = 0
    private var bank = "alpha"

    override func setUp() async throws {
        synthetic = try SyntheticChatDB()
        defaults = UserDefaults(suiteName: "Messages-\(UUID().uuidString)")!
        instinct = synthetic.chat("+15550000001")
        let other = synthetic.chat("+15550000003")
        synthetic.message(instinct, minute: 0, fromMe: true, text: "Plan the alpha-project launch?")
        synthetic.message(instinct, minute: 1, fromMe: false, text: "Sure.", bodyOnly: true)
        synthetic.message(instinct, minute: 2, fromMe: false, text: "Step one: list the tasks.")
        synthetic.message(other, minute: 3, fromMe: false, text: "CANARY-other")
    }

    override func tearDown() async throws { synthetic.close() }

    private func watcher(_ api: FakeMessagesAPI, cards: [String: MessagesContactCard] = [:]) -> MessagesWatcher {
        MessagesWatcher(api: api, reader: MessagesReader(database: synthetic.url), defaults: defaults,
                        folder: synthetic.dir, debounce: .milliseconds(10), minimumInterval: .zero,
                        makeWatch: { _, _ in nil }, bank: { [unowned self] in self.bank },
                        lookUpCards: { handles in cards.filter { handles.contains($0.key) } })
    }

    private var instinctId: String { MessagesReader.conversationId(chatGuid: "iMessage;-;+15550000001") }

    func testNothingIsReadOrPostedBeforeATick() async throws {
        let api = FakeMessagesAPI()
        let w = watcher(api)
        await w.bankChanged()
        XCTAssertTrue(api.posts.isEmpty)
        await w.loadList()
        XCTAssertEqual(w.conversations.count, 2)
        XCTAssertTrue(api.posts.isEmpty, "listing reads names and counts, never posts a message")
        XCTAssertEqual(w.status, .idle)
    }

    func testATickReadsThatConversationOnlyAndTheCursorHolds() async throws {
        let api = FakeMessagesAPI()
        let w = watcher(api, cards: ["+15550000001": MessagesContactCard(name: "Instinct", thumbnail: nil)])
        await w.loadList()
        let conversation = try XCTUnwrap(w.conversations.first { $0.id == instinctId })
        XCTAssertEqual(w.name(of: conversation), "Instinct")
        XCTAssertEqual(w.states[instinctId]?.isAgent, true)
        try await w.setTicked(conversation, true)
        XCTAssertEqual(api.posts.count, 1)
        let posted = try XCTUnwrap(api.posts.first)
        XCTAssertEqual((posted["conversation"] as? [String: Any])?["id"] as? String, instinctId)
        XCTAssertEqual((posted["messages"] as? [Any])?.count, 3)
        XCTAssertFalse(String(describing: posted).contains("CANARY"))
        XCTAssertGreaterThan(w.cursor(bank: "alpha", id: instinctId).rowid, 0)
        XCTAssertEqual(w.cursor(bank: "beta", id: instinctId), MessagesCursor(), "the cursor is per memory")
        // Nothing new: a pass posts nothing.
        _ = try await w.syncNow()
        XCTAssertEqual(api.posts.count, 1)
        // A new message: only it is posted.
        synthetic.message(instinct, minute: 9, fromMe: true, text: "Thanks!")
        _ = try await w.syncNow()
        XCTAssertEqual((api.posts.last?["messages"] as? [Any])?.count, 1)
    }

    /// 250 chats, the ticked one the oldest: the Settings list stops at 200, the pass reads it by its own id anyway.
    func testATickedChatBelowTheListCapStillSyncs() async throws {
        for i in 0..<248 {
            let chat = synthetic.chat(String(format: "+1555100%04d", i))
            synthetic.message(chat, minute: 100 + i, fromMe: false, text: "Filler \(i)")
        }
        let reader = MessagesReader(database: synthetic.url)
        XCTAssertFalse(try reader.conversations().contains { $0.id == instinctId }, "the picker's list is capped")
        let api = FakeMessagesAPI()
        api.ticked = [instinctId]
        let w = watcher(api)
        await w.bankChanged()
        XCTAssertEqual(api.posts.count, 1)
        XCTAssertEqual((api.posts.first?["conversation"] as? [String: Any])?["id"] as? String, instinctId)
        XCTAssertEqual((api.posts.first?["messages"] as? [Any])?.count, 3)
        // Still the oldest after a new message: it keeps syncing.
        synthetic.message(instinct, minute: 50, fromMe: true, text: "Thanks!")
        _ = try await w.syncNow()
        XCTAssertEqual(api.posts.count, 2)
        XCTAssertEqual((api.posts.last?["messages"] as? [Any])?.count, 1)
        XCTAssertFalse(api.posts.contains { String(describing: $0).contains("Filler") || String(describing: $0).contains("CANARY") })
        // The picker still shows it, so it can be unticked.
        await w.loadList()
        XCTAssertEqual(w.conversations.count, 201)
        XCTAssertTrue(w.conversations.contains { $0.id == instinctId })
    }

    func testTheHandleIsNeverSentAsAName() async throws {
        let api = FakeMessagesAPI()
        let w = watcher(api)   // no Contacts card, no chat name
        await w.loadList()
        let conversation = try XCTUnwrap(w.conversations.first { $0.id == instinctId })
        XCTAssertEqual(w.name(of: conversation), "+15550000001", "the app may show it to the person")
        XCTAssertEqual(w.postedName(of: conversation), "")
        try await w.setTicked(conversation, true)
        let posted = try XCTUnwrap(api.posts.first)
        XCTAssertEqual((posted["conversation"] as? [String: Any])?["name"] as? String, "")
        XCTAssertFalse(String(describing: posted).contains("5550000001"))
    }

    func testUntickingStopsReadingAndKeepsTheCursor() async throws {
        let api = FakeMessagesAPI()
        let w = watcher(api)
        await w.loadList()
        let conversation = try XCTUnwrap(w.conversations.first { $0.id == instinctId })
        try await w.setTicked(conversation, true)
        let cursor = w.cursor(bank: "alpha", id: instinctId)
        try await w.setTicked(conversation, false)
        synthetic.message(instinct, minute: 9, fromMe: true, text: "Thanks!")
        await w.run(force: true)
        XCTAssertEqual(api.posts.count, 1, "an unticked conversation is never read")
        XCTAssertEqual(w.cursor(bank: "alpha", id: instinctId), cursor)
        XCTAssertEqual(api.updates.last?.ticked, false)
    }

    func testTheMarkIsTheBackendsToKeep() async throws {
        let api = FakeMessagesAPI()
        let w = watcher(api, cards: ["+15550000001": MessagesContactCard(name: "Instinct", thumbnail: nil)])
        await w.loadList()
        let conversation = try XCTUnwrap(w.conversations.first { $0.id == instinctId })
        XCTAssertEqual(MessagesConversationText.tag(w.states[instinctId]), Copy.Messages.agentTagSuggested,
                       "before the person says, the detector's answer is a suggestion")
        try await w.mark(conversation, as: .agent)
        XCTAssertEqual(api.updates.last?.mark, .agent)
        XCTAssertEqual(w.states[instinctId]?.actor.decidedBy, "person")
        XCTAssertEqual(MessagesConversationText.tag(w.states[instinctId]), Copy.Messages.agentTag)
        try await w.mark(conversation, as: .person)
        XCTAssertEqual(MessagesConversationText.tag(w.states[instinctId]), Copy.Messages.personTag)
        try await w.mark(conversation, as: .clear)
        XCTAssertEqual(MessagesConversationText.tag(w.states[instinctId]), Copy.Messages.agentTagSuggested)
    }

    /// The live report (2026-10-16): the person chose "This is an AI agent", the backend stored it (`decided_by:
    /// person`), and the pill still read "AI agent · suggested" — the app read `decidedBy` from a block whose keys the
    /// backend never camelCases. This is the exact answer `POST /sources/messages/conversations` gives after a mark.
    func testAPersonsMarkReadsAsTheirsOffTheWire() throws {
        let wire = #"""
        {"suggestAgents": true, "conversations": [
          {"id": "aaaaaaaaaaaaaaaaaaaaaaaa", "ticked": true, "group": false,
           "actor": {"name": "Instinct", "kind": "agent", "decided_by": "person",
                     "detector": "instinct@1", "detection": "identified", "signal": "name+cadence"},
           "suggestion": {"outcome": "identified", "detector": "instinct", "version": 1, "signal": "name+cadence"},
           "marked": {"kind": "agent"}},
          {"id": "bbbbbbbbbbbbbbbbbbbbbbbb", "ticked": false, "group": false,
           "actor": {"name": "Instinct", "kind": "agent", "decided_by": "detector"},
           "suggestion": {"outcome": "identified"}, "marked": null},
          {"id": "cccccccccccccccccccccccc", "ticked": false, "group": false,
           "actor": {"name": "alice-example", "kind": "person", "decided_by": "person"},
           "suggestion": {"outcome": "unknown"}, "marked": {"kind": "person"}}]}
        """#
        let answer = try JSONDecoder().decode(MessagesConversationsAnswer.self, from: Data(wire.utf8))
        XCTAssertEqual(answer.conversations.map(\.actor.decidedBy), ["person", "detector", "person"])
        XCTAssertEqual(answer.conversations.map { MessagesConversationText.tag($0) },
                       [Copy.Messages.agentTag, Copy.Messages.agentTagSuggested, Copy.Messages.personTag])
    }

    func testARefusedReadShowsTheFullDiskAccessFix() async throws {
        let api = FakeMessagesAPI()
        api.ticked = [instinctId]
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: synthetic.url.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: synthetic.url.path) }
        let w = watcher(api)
        await w.bankChanged()
        guard case .needsAccess(let error) = w.status, case .notReadable(.messagesDatabase, _) = error else {
            return XCTFail("expected the Full Disk Access fix, got \(w.status)")
        }
        XCTAssertTrue(api.posts.isEmpty)
    }

    func testABackendRefusalSaysTheServersSentence() async throws {
        let api = FakeMessagesAPI()
        api.ticked = [instinctId]
        api.refuseSync = APIError.httpError(409, #"{"detail":"This conversation isn't ticked."}"#)
        let w = watcher(api)
        await w.bankChanged()
        XCTAssertEqual(w.status, .failed("This conversation isn't ticked."))
    }

    func testWaitingNamesComeFromContactsWhenThereIsACard() async throws {
        let api = FakeMessagesAPI()
        api.waitingItems = [MessagesWaitingItem(conversation: instinctId, name: "Instinct", kind: "agent", messages: 34)]
        let w = watcher(api, cards: ["+15550000001": MessagesContactCard(name: "Instinct Contact", thumbnail: nil)])
        await w.refreshWaiting()
        XCTAssertEqual(w.waiting.count, 1)
        XCTAssertEqual(w.name(ofWaiting: w.waiting[0]), "Instinct Contact")
    }
}

/// G179 — the bubbles, pure.
final class MessageBubblesTests: XCTestCase {
    private func item(_ id: String, _ name: String, _ messages: Int, kind: String = "agent") -> MessagesWaitingItem {
        MessagesWaitingItem(conversation: id, name: name, kind: kind, messages: messages)
    }

    func testNothingWaitingDrawsNothing() {
        XCTAssertNil(MessageBubbles.model([], name: { $0.name }))
        XCTAssertNil(MessageBubbles.model([item("a", "Instinct", 0)], name: { $0.name }))
    }

    func testOneConversationIsOneBubbleWithItsCount() throws {
        let model = try XCTUnwrap(MessageBubbles.model([item("a", "Instinct", 34)], name: { $0.name }))
        XCTAssertEqual(model.shown.map(\.name), ["Instinct"])
        XCTAssertEqual(model.shown[0].initials, "I")
        XCTAssertTrue(model.shown[0].isAgent)
        XCTAssertEqual(model.hidden, 0)
        XCTAssertEqual(model.label, "34 messages")
        XCTAssertEqual(model.shown[0].help, "Instinct · 34 messages waiting to be read")
        XCTAssertEqual(model.accessibility, "Instinct · 34 messages waiting to be read")
    }

    func testMostMessagesFirstAndTheRestFoldIntoACount() throws {
        let items = [item("a", "Alice Example", 2, kind: "person"), item("b", "Instinct", 40), item("c", "Bob Example", 5),
                     item("d", "Carol Example", 1)]
        let model = try XCTUnwrap(MessageBubbles.model(items, name: { $0.name }))
        XCTAssertEqual(model.shown.map(\.name), ["Instinct", "Bob Example", "Alice Example"])
        XCTAssertEqual(model.hidden, 1)
        XCTAssertEqual(model.messages, 48)
        XCTAssertEqual(model.label, "48 messages")
        XCTAssertEqual(model.shown[1].initials, "BE")
    }

    func testTheNameIsThePersonsOwnWhenTheyHaveOne() throws {
        let model = try XCTUnwrap(MessageBubbles.model([item("a", "Instinct", 1)], name: { _ in "My agent" }))
        XCTAssertEqual(model.shown[0].name, "My agent")
        XCTAssertEqual(model.label, "1 message")
    }
}

/// G179 — who is who where the person reads it: the Reader's speaker line and an evidence chip name the texted agent;
/// the person's own turns stay "You"; the Sources card's Sync now reaches the Messages reader, never a first read.
@MainActor
final class MessagesWhoIsWhoTests: XCTestCase {
    private func turn(_ role: String, marker: String? = nil) -> EpisodeTurn {
        EpisodeTurn(index: 0, start: 0, contentStart: 0, end: 1, role: role, marker: marker)
    }

    func testTheReaderNamesTheAgentAndThePerson() {
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn("assistant", marker: "assistant"), harness: nil, origin: "imessage",
                                                   correspondent: "Instinct"), "Instinct")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn("speaker", marker: "speaker:alice-example"), harness: nil,
                                                   origin: "imessage", correspondent: "Alice Example"), "Alice Example")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn("user", marker: "user"), harness: nil, origin: "imessage",
                                                   correspondent: "Instinct"), Copy.you)
        // Without a correspondent nothing changes for any other episode.
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn("assistant", marker: "assistant"), harness: nil, origin: "imessage"),
                       Copy.Provenance.theAgent)
    }

    func testAChipSaysTheAgentReplied() {
        let meta = EvidenceDocMeta(title: nil, harness: nil, origin: "imessage", source: "imessage", correspondent: "Instinct")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .assistant, agent: EvidenceLabel.agent(meta)),
                       Copy.Provenance.replied("Instinct"))
    }

    func testTheSourcesCardRoutesToTheMessagesReader() {
        XCTAssertEqual(ChannelActions.syncRoute(for: MessagesWatcher.channel), .messages)
        XCTAssertTrue(ChannelActions.managesInIntegrations(MessagesWatcher.channel))
        XCTAssertEqual(IntegrationCategory.of(channelId: MessagesWatcher.channel), .messaging)
    }

    func testTheEpisodeTextCarriesTheCorrespondent() throws {
        let json = #"{"episode":"ep_2026-09-03_001","text":"user: hi\nassistant: hello","correspondent":"Instinct"}"#
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(json.utf8))
        XCTAssertEqual(doc.correspondent, "Instinct")
    }
}
