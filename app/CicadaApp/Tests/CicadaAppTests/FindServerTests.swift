import XCTest
@testable import CicadaApp

/// A `FindSearchAPI` that never touches a network. Every call is recorded.
final class FakeFindSearch: FindSearchAPI, @unchecked Sendable {
    struct Call: Equatable { let query: String; let mode: String; let kinds: [String]; let perKind: Int }
    var calls: [Call] = []
    var response = MemorySearchResponse()
    var error: Error?

    func searchMemory(_ query: String, kinds: [String], mode: String, perKind: Int) async throws -> MemorySearchResponse {
        calls.append(Call(query: query, mode: mode, kinds: kinds, perKind: perKind))
        if let error { throw error }
        return response
    }

    static func decode(_ json: String) -> MemorySearchResponse {
        try! JSONDecoder().decode(MemorySearchResponse.self, from: Data(json.utf8))
    }
}

/// G136 S4 — the wire, hits → rows, the counts, and the debounced passes.
final class FindServerTests: XCTestCase {
    /// "The wire" (`2026-09-23-search-backend.md`), one hit per kind plus a
    /// second passage of one conversation and a superseded claim.
    static let wire = """
    {"results": [
      {"id": "alpha-project", "name": "alpha-project", "type": "project", "status": "active", "confidence": 0.8,
       "score": 4, "snippet": "", "kind": "entity", "subtitle": "alpha", "snippetOffsets": [], "matchedField": "alias"},
      {"id": "ep_2026-09-03_001", "name": "Planning notes", "type": "episode", "status": "active", "confidence": 0,
       "score": 3, "snippet": "we moved the index to sqlite-vec", "kind": "episode", "snippetOffsets": [[22, 32]],
       "matchedField": "body", "episodeId": "ep_2026-09-03_001", "conversationId": "ses_a", "harness": "claude-code",
       "timestamp": "2026-09-03T10:00:00+00:00", "start": 120, "end": 180, "hash": "abcdef123456", "evidenceKind": "user"},
      {"id": "ep_2026-09-03_002", "name": "Planning notes", "type": "episode", "status": "active", "confidence": 0,
       "score": 2, "snippet": "sqlite-vec again", "kind": "episode", "snippetOffsets": [[0, 10]], "matchedField": "body",
       "episodeId": "ep_2026-09-03_002", "conversationId": "ses_a", "harness": "claude-code"},
      {"id": "clm_1", "name": "alpha-project uses sqlite-vec", "type": "project", "status": "active", "confidence": 0.7,
       "score": 2, "snippet": "alpha-project uses sqlite-vec", "kind": "claim", "subtitle": "alpha-project",
       "subjectId": "alpha-project", "episodeId": "ep_2026-09-03_001", "start": 120, "end": 150,
       "hash": "abcdef123456", "evidenceKind": "user"},
      {"id": "clm_0", "name": "alpha-project uses FAISS", "type": "project", "status": "active", "confidence": 0.4,
       "score": 1, "snippet": "", "kind": "claim", "subtitle": "alpha-project", "subjectId": "alpha-project",
       "validTo": "2026-09-03", "supersededBy": "clm_1"},
      {"id": "media-alpha", "name": "Alpha paper notes", "type": "media", "status": "active", "confidence": 0.5,
       "score": 1, "snippet": "", "kind": "media", "subtitle": "Ada Example, Bob Example", "timestamp": "2025-01-02"},
      {"id": "inbox-001", "name": "Still tracking alpha-project?", "type": "decay", "status": "active",
       "confidence": 0, "score": 1, "snippet": "", "kind": "inbox", "subjectId": "alpha-project"}
    ],
    "totals": {"entity": 1, "episode": 2, "claim": 2, "media": 1}, "mode": "prefix", "indexState": "ready"}
    """

    private var context: FindServerRows.Context {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        var context = FindServerRows.Context()
        context.now = ISO8601DateFormatter().date(from: "2026-09-23T12:00:00Z")!
        context.locale = Locale(identifier: "en_GB")
        context.calendar = calendar
        context.mediaURL = { $0 == "media-alpha" ? "https://example.com/alpha" : nil }
        context.readerAvailable = false
        return context
    }

    func testTheWireDecodesAndAnOldBackendStillDecodes() {
        let response = FakeFindSearch.decode(Self.wire)
        XCTAssertEqual(response.results.count, 7)
        XCTAssertEqual(response.totals["episode"], 2)
        XCTAssertEqual(response.results[1].snippetOffsets, [[22, 32]])
        XCTAssertEqual(response.results[4].validTo, "2026-09-03")
        let old = FakeFindSearch.decode(#"{"results": [{"id": "a", "name": "A", "type": "concept", "status": "active", "confidence": 0.5, "score": 1, "snippet": ""}]}"#)
        XCTAssertEqual(old.results.first?.kind, "entity", "pre-G136 rows were all entities")
        XCTAssertEqual(old.totals, [:])
        XCTAssertEqual(old.indexState, "ready")
    }

    func testHitsBecomeRowsGroupedByConversationWithHistoryAndSpeakers() {
        let rows = FindServerRows.rows(FakeFindSearch.decode(Self.wire), query: "sqlite", context: context)
        XCTAssertEqual(rows.map(\.group), [.entities, .conversations, .beliefs, .beliefs, .sources], "inbox is the local tier's")
        XCTAssertEqual(rows[0].detail, "Also called alpha")
        let conversation = rows[1]
        XCTAssertEqual(conversation.key, FindRowKey(kind: .conversation, id: "ses_a"))
        XCTAssertEqual(conversation.detail, "2 matches")
        XCTAssertEqual(conversation.speaker, "You said")
        XCTAssertEqual(conversation.trailing, "3 Sep")
        XCTAssertEqual(conversation.mark, .origin("claude-code"))
        XCTAssertEqual(conversation.snippetRanges, [[22, 32]])
        XCTAssertEqual(conversation.secondary, .conversations(harness: "claude-code", origin: nil, query: nil))
        guard case .conversation(let target) = conversation.destination else { return XCTFail("a conversation opens a conversation") }
        XCTAssertEqual(target.span, ReaderSpan(doc: "ep_2026-09-03_001", start: 120, end: 180, hash: "abcdef123456", claimId: nil))
        XCTAssertEqual(rows[2].detail, "alpha-project · You said")
        XCTAssertNil(rows[2].history)
        XCTAssertNil(rows[2].secondary, "R-SU18: no Reader, no 'where it was said'")
        XCTAssertEqual(rows[3].history, "until 3 Sep", "R-SU19: a superseded belief is history")
        XCTAssertEqual(rows[4].trailing, "2 Jan 2025")
        XCTAssertEqual(rows[4].secondary, .openURL("https://example.com/alpha"))
    }

    func testTotalsAreHonest() {
        let response = FakeFindSearch.decode(Self.wire)
        let rows = FindServerRows.rows(response, query: "sqlite", context: context)
        let totals = FindServerRows.totals(response, rows: rows, kinds: FindServerRows.kinds, perKind: 5)
        XCTAssertEqual(totals[.entities], .exact(1))
        XCTAssertEqual(totals[.beliefs], .exact(2))
        XCTAssertEqual(totals[.conversations], .atLeast, "two episodes merged into one row: not a row count")
        let semantic = FakeFindSearch.decode(#"{"results": [{"id": "a", "name": "A", "type": "concept", "status": "active", "confidence": 0.5, "score": 1, "snippet": "", "kind": "entity", "matchedField": "semantic"}], "totals": {"entity": 0}, "mode": "hybrid"}"#)
        XCTAssertEqual(FindServerRows.totals(semantic, rows: [], kinds: ["entity"], perKind: 5)[.entities], .atLeast)
        let capped = MemorySearchResponse(results: Array(repeating: response.results[0], count: 5))
        XCTAssertEqual(FindServerRows.totals(capped, rows: [], kinds: ["entity"], perKind: 5)[.entities], .atLeast)
    }

    func testDatesSpeakTheReadersLocaleAndOnlyNameAnotherYear() {
        let c = context
        XCTAssertEqual(FindDates.short("2026-09-03T10:00:00+00:00", now: c.now, locale: c.locale, calendar: c.calendar), "3 Sep")
        XCTAssertEqual(FindDates.short("2026-09-03T10:00:00.123Z", now: c.now, locale: c.locale, calendar: c.calendar), "3 Sep")
        XCTAssertEqual(FindDates.short("2025-01-02", now: c.now, locale: c.locale, calendar: c.calendar), "2 Jan 2025")
        XCTAssertEqual(FindDates.short("2026-09-03", now: c.now, locale: Locale(identifier: "en_US"), calendar: c.calendar), "Sep 3")
        XCTAssertNil(FindDates.short(nil, now: c.now, locale: c.locale, calendar: c.calendar))
        XCTAssertNil(FindDates.short("soon", now: c.now, locale: c.locale, calendar: c.calendar))
    }

    func testOnlyARealConnectionFailureReadsAsUnreachable() {
        XCTAssertTrue(FindServerPhase.isUnreachable(APIError.serverUnreachable))
        XCTAssertTrue(FindServerPhase.isUnreachable(URLError(.cannotConnectToHost)))
        XCTAssertFalse(FindServerPhase.isUnreachable(URLError(.cancelled)))
        XCTAssertFalse(FindServerPhase.isUnreachable(APIError.httpError(500, "")))
    }

    func testASpanLandsOnItsWordsAndAnythingLessOpensAtTheTop() {
        let exact = FindReaderRoute.target(for: ReaderSpan(doc: "ep_1", start: 120, end: 180, hash: "abcdef123456", claimId: nil))
        XCTAssertEqual(exact.episode, "ep_1")
        XCTAssertEqual(exact.focus, ReaderTarget.Focus.span(start: 120, end: 180, hash: "abcdef123456", derived: false))
        let bare = FindReaderRoute.target(for: ReaderSpan(doc: "ep_2", start: nil, end: nil, hash: nil, claimId: nil))
        XCTAssertEqual(bare.focus, ReaderTarget.Focus.none)
    }

    func testTheClientAsksForTheFourKindsAndEncodesTheQuery() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/search")
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("q=sqlite%20vec%26more"), query)
            XCTAssertTrue(query.contains("kinds=entity,claim,episode,media"), query)
            XCTAssertTrue(query.contains("mode=prefix"), query)
            XCTAssertTrue(query.contains("per_kind=5"), query)
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data(#"{"results": [], "totals": {}, "mode": "prefix", "indexState": "ready"}"#.utf8))
        }
        let result = try await APIClient(session: MockURLProtocol.makeSession())
            .searchMemory("sqlite vec&more", kinds: FindServerRows.kinds, mode: "prefix", perKind: 5)
        XCTAssertEqual(result.indexState, "ready")
    }

    /// G150 (R-B25) — a backlog hit is a row of its own group that lands on Projects with the item open.
    func testABacklogHitLandsOnProjectsWithTheItemOpen() {
        let response = FakeFindSearch.decode(#"""
        {"results": [{"id": "RAP3", "name": "Swap the gripper camera for a global-shutter one", "type": "research",
          "status": "open", "confidence": 0, "score": 3, "snippet": "", "kind": "backlog",
          "subjectId": "rover-arm-project", "timestamp": "2026-09-20"}],
         "totals": {"backlog": 1}, "mode": "prefix", "indexState": "ready"}
        """#)
        var c = context
        c.projectName = { $0 == "rover-arm-project" ? "Rover Arm Project" : nil }
        let rows = FindServerRows.rows(response, query: "camera", context: c)
        XCTAssertEqual(rows.count, 1)
        let row = rows[0]
        XCTAssertEqual(row.group, .backlog)
        XCTAssertEqual(row.key, FindRowKey(kind: .backlog, id: "rover-arm-project/RAP3"))
        XCTAssertEqual(row.detail, "RAP3 · Rover Arm Project · Open")
        XCTAssertEqual(row.badge, "Research")
        XCTAssertEqual(row.destination, .backlogItem(project: "rover-arm-project", id: "RAP3"))
        XCTAssertEqual(FindServerRows.totals(response, rows: rows, kinds: FindServerRows.kinds, perKind: 5)[.backlog],
                       .exact(1))
        XCTAssertTrue(FindServerRows.kinds.contains("backlog"))
        XCTAssertTrue(FindGroupID.inbox < FindGroupID.backlog && FindGroupID.backlog < FindGroupID.settings)
        XCTAssertEqual(FindRowText.primaryVerb(row.destination), "Open in Projects")
        XCTAssertEqual(FindRowText.kindLabel(row), "Backlog item")
    }
}

/// The debounced passes against a fake (design §3.10 `PaletteDebounceTests`).
/// The sleeper only checks cancellation, so a cancelled pass never calls out.
@MainActor
final class PaletteServerTierTests: XCTestCase {
    private func model(_ api: FakeFindSearch) -> FindPaletteModel {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let model = FindPaletteModel(store: store, api: api, sleeper: { _ in try Task.checkCancellation() })
        model.install(QuickIndex.build(FindFixtures.inputs()))
        return model
    }

    func testUnderTwoCharactersNothingIsAsked() async {
        let api = FakeFindSearch()
        let m = model(api)
        m.setQuery("a")
        await m.serverTask?.value
        XCTAssertTrue(api.calls.isEmpty)
        XCTAssertEqual(m.serverPhase, .idle)
    }

    func testAKeystrokeCancelsThePassInFlight() async {
        let api = FakeFindSearch()
        let m = model(api)
        m.setQuery("al")
        m.setQuery("alp")
        await m.serverTask?.value
        XCTAssertEqual(api.calls.map(\.query), ["alp", "alp"])
        XCTAssertEqual(api.calls.map(\.mode), ["prefix", "hybrid"])
        XCTAssertEqual(api.calls.first?.kinds, FindServerRows.kinds)
        XCTAssertEqual(api.calls.first?.perKind, SearchTiming.perKind)
    }

    func testServerRowsAppendBelowAndNothingShownMoves() async {
        let api = FakeFindSearch()
        api.response = FakeFindSearch.decode(FindServerTests.wire)
        let m = model(api)
        m.setQuery("alpha")
        let top = m.results.topHit?.key
        let selected = m.selection
        await m.serverTask?.value
        XCTAssertEqual(m.results.topHit?.key, top)
        XCTAssertEqual(m.selection, selected)
        XCTAssertNil(m.results.groups[.entities], "the server's alpha-project is the local top hit: not repeated")
        XCTAssertEqual(m.results.groups[.conversations]?.count, 1)
        XCTAssertEqual(m.results.groups[.beliefs]?.count, 2)
        XCTAssertEqual(m.results.groups[.sources]?.map(\.key.id), ["media-alpha"], "local media-alpha is not repeated")
        XCTAssertEqual(m.serverPhase, .done)
    }

    func testAnOldBackendHidesConversationsAndBeliefs() async {
        let api = FakeFindSearch()
        api.response = FakeFindSearch.decode(#"{"results": [{"id": "bob-example", "name": "bob-example", "type": "person", "status": "active", "confidence": 0.5, "score": 1, "snippet": ""}]}"#)
        let m = model(api)
        m.setQuery("alpha")
        await m.serverTask?.value
        XCTAssertNil(m.results.groups[.conversations])
        XCTAssertNil(m.results.groups[.beliefs])
        XCTAssertEqual(m.results.groups[.entities]?.map(\.key.id), ["bob-example"])
    }

    func testAnUnreachableBackendKeepsTheLocalRowsAndSaysSo() async {
        let api = FakeFindSearch()
        api.error = URLError(.cannotConnectToHost)
        let m = model(api)
        m.setQuery("alpha")
        await m.serverTask?.value
        XCTAssertEqual(m.serverPhase, .unreachable)
        XCTAssertEqual(m.results.topHit?.key.id, "alpha-project")
        XCTAssertTrue(m.footerText.contains("isn't answering"))
    }

    func testShowAllReasksOneKindAtTheServersCap() async {
        let api = FakeFindSearch()
        api.response = FakeFindSearch.decode(FindServerTests.wire)
        let m = model(api)
        m.setQuery("alpha")
        await m.serverTask?.value
        m.toggleExpanded(.conversations)
        await m.expandTask?.value
        XCTAssertEqual(api.calls.last, FakeFindSearch.Call(query: "alpha", mode: "prefix", kinds: ["episode"],
                                                           perKind: SearchTiming.expandedPerKind))
    }

    func testSearchDeeperRunsTheHybridPassNow() async {
        let api = FakeFindSearch()
        let m = model(api)
        m.setQuery("zeta")
        await m.serverTask?.value
        XCTAssertTrue(m.offersSearchDeeper, "nothing matched")
        api.calls = []
        m.searchDeeper()
        await m.serverTask?.value
        XCTAssertEqual(api.calls.map(\.mode), ["hybrid"])
    }
}
