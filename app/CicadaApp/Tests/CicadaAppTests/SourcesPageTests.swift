import XCTest
@testable import CicadaApp

/// G124 — the Sources page: wire model tolerance, grid order, the count lines
/// a card shows per kind, the harness title filter, and folder grouping.
final class SourcesPageTests: XCTestCase {

    func testSourceOverviewDecodesTheCamelCaseWireAndToleratesMissing() throws {
        let json = """
        {"sources":[{"id":"harness:claude-code","label":"Claude Code","kind":"harness","mark":"claude-code",
                     "conversations":12,"episodes":40,"entities":31,"items":0,
                     "lastActivityAt":"2026-09-01T10:00:00+00:00","connected":true,"lastError":null,
                     "actions":[],"channelId":null,"origins":[],"harness":"claude-code"},
                    {"id":"safari-bookmarks","label":"Safari bookmarks","kind":"browser","mark":"safari-bookmark"},
                    {"id":"origin:mystery","label":"mystery","kind":"space-elevator","mark":"mystery"}]}
        """.data(using: .utf8)!
        let rows = try JSONDecoder().decode(SourceOverviewResponse.self, from: json).sources
        XCTAssertEqual(rows.count, 3)
        XCTAssertEqual(rows[0].kind, .harness); XCTAssertEqual(rows[0].conversations, 12); XCTAssertTrue(rows[0].connected)
        XCTAssertEqual(rows[1].kind, .browser); XCTAssertEqual(rows[1].items, 0); XCTAssertFalse(rows[1].connected)
        XCTAssertNil(rows[1].lastActivityAt); XCTAssertEqual(rows[1].actions, [])
        XCTAssertEqual(rows[2].kind, .unknown, "an unknown kind never drops the whole grid")
    }

    func testGridOrderIsKindThenRecencyThenId() {
        let a = SourceOverview(id: "rss", label: "RSS", kind: .feed, lastActivityAt: "2026-09-02T00:00:00+00:00")
        let b = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, lastActivityAt: "2026-08-01T00:00:00+00:00")
        let c = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, lastActivityAt: "2026-09-01T00:00:00+00:00")
        let d = SourceOverview(id: "origin:x", label: "x", kind: .unknown)
        XCTAssertEqual(SourceOverview.gridOrder([a, b, c, d]).map(\.id), ["harness:claude-code", "harness:cursor", "rss", "origin:x"])
    }

    func testCountLinesShowOnlyWhatAppliesToTheKind() {
        let harness = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness,
                                     conversations: 3, episodes: 9, entities: 5)
        XCTAssertEqual(harness.countLines, ["3 conversations", "5 entities"])
        let browser = SourceOverview(id: "safari-bookmarks", label: "Safari", kind: .browser, entities: 2, items: 412)
        XCTAssertEqual(browser.countLines, ["412 items", "2 entities"])
        let one = SourceOverview(id: "telegram", label: "Telegram", kind: .messaging, episodes: 1, entities: 1)
        XCTAssertEqual(one.countLines, ["1 capture", "1 entity"])
        let empty = SourceOverview(id: "rss", label: "RSS", kind: .feed)
        XCTAssertEqual(empty.countLines, ["Nothing yet"])
        // R1: RSS episodes carry no origin today, so the row's only number is
        // the subscription count the channel reports — never call it "items".
        let rss = SourceOverview(id: "rss", label: "RSS", kind: .feed, items: 3)
        XCTAssertEqual(rss.countLines, ["3 subscriptions"])
        let calendar = SourceOverview(id: "calendar", label: "Calendars", kind: .feed, episodes: 7, entities: 2, items: 1)
        XCTAssertEqual(calendar.countLines, ["7 captures", "2 entities"], "captures win when the origin IS stamped")
    }

    /// A5 — a harness card must never print "capture" under a CHAT & AGENTS
    /// header. The old `case .harness where conversations > 0` fell through to
    /// `default:` when the guard failed, silently changing the unit, so
    /// "Other agents · 1 capture" sat beside "Codex · 1 conversation" under one
    /// header. The harness case is now unconditional and says WHY the number
    /// is a capture rather than quietly renaming the unit.
    func testAHarnessWithNoSessionsStillCountsInItsOwnUnit() {
        let ghost = SourceOverview(id: "harness:unknown", label: "Other agents", kind: .harness,
                                   conversations: 0, episodes: 1, entities: 0)
        XCTAssertEqual(ghost.countLines, ["1 capture (no session recorded)"])
        XCTAssertEqual(ghost.headline?.count, 1)
        XCTAssertEqual(ghost.headline?.noun, "capture")
    }

    /// R-S19 — the tile needs the number and its unit separately (different
    /// fonts, right-aligned on the sparkline's baseline), and the two must be
    /// the same fact `countLines` states in a sentence.
    func testHeadlineIsThePairBehindTheFirstCountLine() {
        let browser = SourceOverview(id: "safari-bookmarks", label: "Safari", kind: .browser,
                                     entities: 2, items: 412)
        XCTAssertEqual(browser.headline?.count, 412)
        XCTAssertEqual(browser.headline?.noun, "item")
        let rss = SourceOverview(id: "rss", label: "RSS", kind: .feed, items: 3)
        XCTAssertEqual(rss.headline?.noun, "subscription")
        XCTAssertNil(SourceOverview(id: "rss", label: "RSS", kind: .feed).headline,
                     "a row with nothing to count has no headline — the card says \"Nothing yet\"")
        // The headline is the FIRST count line's pair, never the entity line's:
        // a browser's tile shows 412 items, not 2 entities.
        let harness = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness,
                                     conversations: 3, episodes: 9, entities: 5)
        XCTAssertEqual(harness.headline?.count, 3)
        XCTAssertEqual(harness.headline?.noun, "conversation")
    }

    func testTitleFilterIsCaseInsensitiveAndKeepsOrder() {
        let rows = [
            ConversationSummary(conversationId: "a", title: "Index choice"),
            ConversationSummary(conversationId: "b", title: "Graph physics"),
            ConversationSummary(conversationId: "c", title: ""),  // "Untitled conversation"
        ]
        XCTAssertEqual(ConversationFilter.apply(rows, query: "").map(\.id), ["a", "b", "c"])
        XCTAssertEqual(ConversationFilter.apply(rows, query: "  GRAPH ").map(\.id), ["b"])
        XCTAssertEqual(ConversationFilter.apply(rows, query: "untitled").map(\.id), ["c"])
    }

    func testFolderGroupingCountsAndOrdersByCountThenName() throws {
        func item(_ id: String, folder: String?) throws -> MediaFeedItem {
            let f = folder.map { "\"folder\":\"\($0)\"," } ?? ""
            return try JSONDecoder().decode(MediaFeedItem.self, from:
                #"{"mediaEntityId":"\#(id)","url":"https://example.com/\#(id)","title":"t","mediaType":"url","savedAt":"2026-09-01T00:00:00Z","tags":[],"status":"active","relatedCount":0,"relevance":0,\#(f)"origin":"safari-bookmark"}"#.data(using: .utf8)!)
        }
        let items = [try item("1", folder: "Papers"), try item("2", folder: "Papers"), try item("3", folder: "Alpha"), try item("4", folder: nil)]
        XCTAssertEqual(items[0].origin, "safari-bookmark"); XCTAssertNil(items[3].folder)
        let groups = SourceItemsGrouping.folders(items)
        XCTAssertEqual(groups.map(\.folder), ["Papers", "Alpha", "No folder"])
        XCTAssertEqual(groups.map(\.count), [2, 1, 1])
    }

    /// The Files & links row is the one that owns pages with no `origin:` at
    /// all. Links saved before the three writers stamped `saved-link` carry
    /// none, links saved after carry it, and both belong on the same page —
    /// counted the same way the backend counts that card, so the number and
    /// the list agree.
    func testFilesRowOwnsBothStampedAndUnstampedSaves() throws {
        func item(_ id: String, origin: String?) throws -> MediaFeedItem {
            let o = origin.map { "\"origin\":\"\($0)\"," } ?? ""
            return try JSONDecoder().decode(MediaFeedItem.self, from:
                #"{"mediaEntityId":"\#(id)","url":"https://example.com/\#(id)","title":"t","mediaType":"url","savedAt":"2026-09-01T00:00:00Z","tags":[],"status":"active","relatedCount":0,"relevance":0,\#(o)"folder":null}"#.data(using: .utf8)!)
        }
        let all = [
            try item("legacy", origin: nil),
            try item("fresh", origin: "saved-link"),
            try item("bookmark", origin: "safari-bookmark"),
        ]

        let files = SourceOverview(id: "files", label: "Files & links", kind: .import, origins: ["saved-link"])
        XCTAssertEqual(Set(files.ownedItems(from: all).map(\.mediaEntityId)), ["legacy", "fresh"])

        // Every other row takes only what it is stamped with — an unstamped
        // page must never be adopted twice.
        let safari = SourceOverview(id: "safari-bookmarks", label: "Safari", kind: .browser, origins: ["safari-bookmark"])
        XCTAssertEqual(safari.ownedItems(from: all).map(\.mediaEntityId), ["bookmark"])
        XCTAssertFalse(safari.ownsUnstampedItems)
    }

    /// An older backend has no `origin`/`folder` on `/sources` items — the row
    /// still decodes, with both nil, so the Feed never blanks on upgrade skew.
    func testMediaFeedItemToleratesABackendWithoutOriginOrFolder() throws {
        let item = try JSONDecoder().decode(MediaFeedItem.self, from:
            #"{"mediaEntityId":"1","url":"https://example.com/1","title":"t","mediaType":"url","savedAt":"2026-09-01T00:00:00Z","tags":[],"status":"active","relatedCount":0,"relevance":0}"#.data(using: .utf8)!)
        XCTAssertNil(item.origin)
        XCTAssertNil(item.folder)
    }

    // MARK: - Track D: grouped grid (2026-09-05 sources redesign)

    func testSourceSectionsGroupsByKindOrderAndSkipsEmptyKinds() {
        let a = SourceOverview(id: "rss", label: "RSS", kind: .feed, lastActivityAt: "2026-09-02T00:00:00+00:00")
        let b = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, lastActivityAt: "2026-08-01T00:00:00+00:00")
        let c = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, lastActivityAt: "2026-09-01T00:00:00+00:00")
        let d = SourceOverview(id: "telegram", label: "Telegram", kind: .messaging)
        let sections = SourceSections.group([a, b, c, d])
        XCTAssertEqual(sections.map(\.kind), [.harness, .feed, .messaging],
                        "no browser/social/import rows in the input -> those headers never appear")
        XCTAssertEqual(sections.map(\.title), ["CHAT & AGENTS", "FEEDS & CALENDARS", "MESSAGING"])
        XCTAssertEqual(sections[0].rows.map(\.id), ["harness:claude-code", "harness:cursor"],
                        "within-kind order is still gridOrder — newest activity first")
    }

    func testSourceSectionsEveryKindGetsANonEmptyHeader() {
        for kind in SourceKind.allCases {
            let row = SourceOverview(id: "x-\(kind.rawValue)", label: "X", kind: kind, episodes: 1)
            XCTAssertFalse(SourceSections.group([row]).first!.title.isEmpty, "\(kind) must render a header")
        }
    }

    func testSourceSectionsOnEmptyInputIsEmpty() {
        XCTAssertTrue(SourceSections.group([]).isEmpty)
    }

    // MARK: - Track D: status light + quick action

    func testQuickActionPrefersSyncOverPollAndIsNilOtherwise() {
        XCTAssertEqual(SourceCard.quickAction(for: SourceOverview(id: "safari-bookmarks", label: "Safari", kind: .browser, actions: ["sync"])), "Sync now")
        XCTAssertEqual(SourceCard.quickAction(for: SourceOverview(id: "rss", label: "RSS", kind: .feed, actions: ["poll", "manage"])), "Poll now")
        XCTAssertNil(SourceCard.quickAction(for: SourceOverview(id: "x", label: "X", kind: .social, actions: ["connect"])))
        XCTAssertNil(SourceCard.quickAction(for: SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness)),
                     "a harness row has no channel actions at all")
    }

    /// R-S4 — the spoken label leads with the SAME brand the card prints, not
    /// the catalog's long `label` ("Safari bookmarks"). VoiceOver and the eye
    /// must name a source identically, or the page has two names for one row.
    func testCardAccessibilityLabelAppendsTheStateTitleOnlyWhenALightIsShown() {
        let row = SourceOverview(id: "safari-bookmarks", label: "Safari bookmarks", kind: .browser, items: 3)
        XCTAssertEqual(SourceCard.accessibilityLabel(for: row, watchState: nil), "Safari, 3 items")
        XCTAssertEqual(SourceCard.accessibilityLabel(for: row, watchState: .watching), "Safari, 3 items, Watching")
        XCTAssertEqual(SourceCard.accessibilityLabel(for: row, watchState: .blocked), "Safari, 3 items, Can't read")
    }

    // MARK: - Track D: per-source blurb

    func testSourceBlurbCoversEveryCatalogIdWithAShortSentence() {
        // Every id api/services/source_overview.CATALOG declares today.
        let catalogIds = [
            "chat-export:claude", "chat-export:chatgpt", "chat-export:gemini",
            "chrome-bookmarks", "safari-bookmarks", "safari-tabs",
            "pinterest", "reddit", "x", "instagram", "youtube", "linkedin", "tiktok",
            "rss", "calendar", "telegram", "notes", "files",
        ]
        for id in catalogIds {
            let row = SourceOverview(id: id, label: id, kind: .harness)  // kind is irrelevant once the id matches
            let text = SourceBlurb.text(for: row)
            XCTAssertFalse(text.isEmpty, "\(id) has no blurb")
            XCTAssertLessThanOrEqual(text.count, 110, "\(id)'s blurb is too long for a subtitle line: \(text)")
            XCTAssertFalse(text.contains("$"), "no prices in the app (G124 ruling)")
        }
    }

    func testSourceBlurbFallsBackToTheKindSentenceForAnUnrecognizedId() {
        let mystery = SourceOverview(id: "origin:mystery-app", label: "mystery-app", kind: .import)
        XCTAssertEqual(SourceBlurb.text(for: mystery), "Links or files you added through mystery-app.")
        let cursor = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness)
        XCTAssertEqual(SourceBlurb.text(for: cursor), "Conversations captured from Cursor, one episode per session.")
    }

    // MARK: - Track D: the queue strip

    private func queueItem(_ id: String, origin: String) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from:
            #"{"id":"\#(id)","timestamp":"2026-09-01T00:00:00Z","source":"x","origin":"\#(origin)","preview":"","processed":false}"#.data(using: .utf8)!)
    }

    func testOwnedQueueMatchesAHarnessByIdPlusTheLegacyMcpAliasForClaudeCodeOnly() throws {
        let all = [try queueItem("1", origin: "claude-code"), try queueItem("2", origin: "mcp"),
                   try queueItem("3", origin: "cursor"), try queueItem("4", origin: "safari-bookmark")]
        let claudeCode = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, harness: "claude-code")
        XCTAssertEqual(claudeCode.ownedQueue(from: all).map(\.id), ["1", "2"], "the legacy mcp id belongs to claude-code only")
        let cursor = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, harness: "cursor")
        XCTAssertEqual(cursor.ownedQueue(from: all).map(\.id), ["3"], "cursor never adopts a bare mcp episode")
    }

    func testOwnedQueueMatchesACatalogRowByItsExactOriginsOnlyWithNoUnstampedFallback() throws {
        let all = [try queueItem("1", origin: "safari-bookmark"), try queueItem("2", origin: "saved-link"),
                   try queueItem("3", origin: "unknown")]
        let safari = SourceOverview(id: "safari-bookmarks", label: "Safari bookmarks", kind: .browser, origins: ["safari-bookmark"])
        XCTAssertEqual(safari.ownedQueue(from: all).map(\.id), ["1"])
        let files = SourceOverview(id: "files", label: "Files & links", kind: .import, origins: ["saved-link"])
        XCTAssertEqual(files.ownedQueue(from: all).map(\.id), ["2"],
                        "R-D8: exact origins only — files does NOT also adopt \"unknown\", unlike ownedItems' nil-origin rule")
    }

    func testSourceQueueLabelsWaitingAndConsolidatedSoFar() {
        XCTAssertEqual(SourceQueueLabels.waiting(0), "Nothing waiting for Sleep")
        XCTAssertEqual(SourceQueueLabels.waiting(12), "12 waiting for Sleep")

        let harness = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, conversations: 3, entities: 5)
        XCTAssertEqual(SourceQueueLabels.consolidatedSoFar(for: harness), "Consolidated so far: 3 conversations → 5 entities")

        let one = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, conversations: 1, entities: 1)
        XCTAssertEqual(SourceQueueLabels.consolidatedSoFar(for: one), "Consolidated so far: 1 conversation → 1 entity")

        let channel = SourceOverview(id: "safari-bookmarks", label: "Safari", kind: .browser, episodes: 40, entities: 12)
        XCTAssertEqual(SourceQueueLabels.consolidatedSoFar(for: channel), "Consolidated so far: 40 captures → 12 entities")

        let empty = SourceOverview(id: "rss", label: "RSS", kind: .feed)
        XCTAssertNil(SourceQueueLabels.consolidatedSoFar(for: empty), "hidden when both counts are 0")
    }
}
