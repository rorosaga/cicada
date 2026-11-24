import XCTest
@testable import CicadaApp

/// The opened Past sleeps card (owner 2026-11-24: "an easy view to see the pages affected per source, if it was an
/// update, creation or deletion of entity pages"): which source fed which conversation, which conversation fed which
/// page, and what the read did to it — pure, from the SHARED fixture the backend writes
/// (`test_sleep_v5_app_fixtures.py`), so the app reads the server's own shapes.
final class RunItemsModelTests: XCTestCase {
    private static let fixtures = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("fixtures")

    private func items() throws -> SleepConsolidated {
        try JSONDecoder().decode(SleepConsolidated.self,
                                 from: Data(contentsOf: Self.fixtures.appendingPathComponent("sleep-run-items.json")))
    }

    private let us = Locale(identifier: "en_US")

    // MARK: The wire

    func testTheFixtureDecodesEveryNewField() throws {
        let items = try items()
        let device = try XCTUnwrap(items.conversations.first { $0.id == "ep_2026-10-01_001" })
        XCTAssertEqual(device.device, "device-a")
        XCTAssertEqual(device.pages, ["new-two", "upd-one"])
        let site = try XCTUnwrap(items.conversations.first { $0.id == "ep_2026-10-01_002" })
        XCTAssertEqual(site.site, "docs.example.com")
        let meeting = try XCTUnwrap(items.conversations.first { $0.id == "ep_2026-10-01_003" })
        XCTAssertEqual(meeting.meeting?.app, "call-app")
        XCTAssertEqual(meeting.meeting?.durationS, 1800)
        XCTAssertEqual(items.pages.map(\.change), [.created, .created, .created, .updated, .updated, .updated,
                                                   .archived, .archived, .archived, .removed, .removed])
        XCTAssertEqual(items.created.first { $0.id == "new-two" }?.episodes, ["ep_2026-10-01_000", "ep_2026-10-01_001"])
        XCTAssertTrue(items.removed.allSatisfy(\.gone))
    }

    func testAnOlderBackendDecodesWithNoneOfItAndTheListsSayTheChange() throws {
        let old = try JSONDecoder().decode(SleepConsolidated.self, from: Data("""
        {"commits": ["a"], "conversations": [{"id": "ep1", "origin": "claude-code", "title": "T"}],
         "created": [{"id": "p1"}], "updated": [{"id": "p2"}], "counts": {"conversations": 1}}
        """.utf8))
        XCTAssertEqual(old.conversations[0].pages, [])
        XCTAssertNil(old.conversations[0].device)
        XCTAssertEqual(old.archived, [])
        XCTAssertEqual(old.pages.map(\.change), [.created, .updated], "no change of its own: the list it sits in")
        XCTAssertFalse(RunItemsModel.isAttributed(old))
    }

    func testAnUnknownChangeWordIsNoChangeNeverAFailedDecode() throws {
        let page = try JSONDecoder().decode(SleepConsolidated.Page.self,
                                            from: Data(#"{"id": "p", "change": "teleported"}"#.utf8))
        XCTAssertNil(page.change)
    }

    // MARK: The machine filter

    func testMatchesNarrowsByMachine() {
        XCTAssertTrue(RunItemsModel.matches(device: nil, machineId: nil), "no filter: every machine")
        XCTAssertTrue(RunItemsModel.matches(device: "device-a", machineId: nil))
        XCTAssertTrue(RunItemsModel.matches(device: nil, machineId: "server"), "this server's own carry no device")
        XCTAssertFalse(RunItemsModel.matches(device: "device-a", machineId: "server"))
        XCTAssertTrue(RunItemsModel.matches(device: "device-a", machineId: "device-a"))
        XCTAssertFalse(RunItemsModel.matches(device: nil, machineId: "device-a"))
        XCTAssertFalse(RunItemsModel.matches(device: "device-b", machineId: "device-a"))
    }

    func testAMachineNarrowsConversationsAndTheirPagesAndHidesTheUpkeep() throws {
        let items = try items()
        XCTAssertEqual(RunItemsModel.conversations(items, machineId: "device-a").map(\.id), ["ep_2026-10-01_001"])
        XCTAssertEqual(RunItemsModel.pages(items, machineId: "device-a").map(\.id), ["new-two", "upd-one"])
        let body = RunItemsModel.body(items, filter: nil, machineId: "device-a")
        XCTAssertEqual(body.sources.map(\.origin), ["claude-code"])
        XCTAssertEqual(body.sources[0].rows[0].pages.map(\.id), ["new-two", "upd-one"])
        XCTAssertEqual(body.leftover, [], "pages no conversation stands behind are the memory's, not a machine's")
        XCTAssertEqual(RunItemsModel.conversationCount(items, machineId: "device-a"), 1)
        XCTAssertEqual(RunItemsModel.counts(items, machineId: "device-a"), [.created: 1, .updated: 1])
        XCTAssertTrue(RunItemsModel.hasConversations(items, machineId: "server"))
        XCTAssertFalse(RunItemsModel.hasConversations(items, machineId: "device-z"),
                       "a run that read nothing from the machine is not listed")
    }

    // MARK: Per source

    func testSourcesAreLargestFirstWithTheirConversationsAndPages() throws {
        let body = RunItemsModel.body(try items(), filter: nil, machineId: nil)
        XCTAssertTrue(body.attributed)
        XCTAssertEqual(body.sources.map(\.origin), ["claude-code", "chrome-bookmark", "hex"],
                       "the source that fed most first, ties in the read's order")
        XCTAssertEqual(body.sources[0].rows.map(\.id), ["ep_2026-10-01_000", "ep_2026-10-01_001"])
        XCTAssertEqual(body.sources[0].rows[0].pages.map(\.id), ["new-one", "new-two"])
        XCTAssertEqual(body.sources[0].rows[1].pages.map(\.id), ["new-two", "upd-one"],
                       "a page two conversations fed shows under both")
        XCTAssertEqual(body.sources[1].rows[0].pages.map(\.id), ["made-then-archived"])
        XCTAssertEqual(body.sources[1].rows[0].pages[0].change, .archived)
        XCTAssertEqual(body.leftover.map(\.id), ["solo-two", "restored", "arch-decay", "arch-batch", "gone-one", "gone-two"],
                       "no conversation of the run stands behind these, in reading order")
    }

    func testTheFilterKeepsOnePageKindAndOnlyTheConversationsThatFedOne() throws {
        let items = try items()
        let created = RunItemsModel.body(items, filter: .created, machineId: nil)
        XCTAssertEqual(created.sources.map(\.origin), ["claude-code", "hex"])
        XCTAssertEqual(created.sources[0].rows.map { $0.pages.map(\.id) }, [["new-one", "new-two"], ["new-two"]])
        XCTAssertEqual(created.leftover, [])
        let removed = RunItemsModel.body(items, filter: .removed, machineId: nil)
        XCTAssertEqual(removed.sources, [], "no conversation fed a removed page")
        XCTAssertEqual(removed.leftover.map(\.id), ["gone-one", "gone-two"])
        let archived = RunItemsModel.body(items, filter: .archived, machineId: nil)
        XCTAssertEqual(archived.sources.map(\.origin), ["chrome-bookmark"])
        XCTAssertEqual(archived.leftover.map(\.id), ["arch-decay", "arch-batch"])
    }

    func testAnOlderBackendGroupsConversationsByOriginAndListsPagesInOneGroup() throws {
        let old = SleepConsolidated(
            conversations: [.init(id: "1", origin: "chatgpt"), .init(id: "2", origin: "claude-code"),
                            .init(id: "3", origin: "claude-code")],
            created: [.init(id: "a")], updated: [.init(id: "b")])
        let body = RunItemsModel.body(old, filter: nil, machineId: nil)
        XCTAssertFalse(body.attributed)
        XCTAssertEqual(body.sources.map(\.origin), ["claude-code", "chatgpt"])
        XCTAssertTrue(body.sources.flatMap(\.rows).allSatisfy { $0.pages.isEmpty }, "it cannot say who fed what")
        XCTAssertEqual(body.leftover.map(\.id), ["a", "b"], "every page, in one group")
        XCTAssertEqual(RunItemsModel.body(old, filter: .updated, machineId: nil).sources, [],
                       "a filter needs attribution: no conversation is claimed")
    }

    // MARK: The numbers and the tabs

    func testTheCountsAreTheServersWholeCountsAndTheSummaryIsSaidOnce() throws {
        let items = try items()
        XCTAssertEqual(RunItemsModel.counts(items, machineId: nil),
                       [.created: 3, .updated: 3, .archived: 3, .removed: 2])
        XCTAssertEqual(RunItemsModel.summary(items, machineId: nil, locale: us),
                       "4 conversations · 3 new pages · 3 updated · 3 archived · 2 removed")
        XCTAssertEqual(RunItemsModel.summary(items, machineId: "device-a", locale: us),
                       "1 conversation · 1 new page · 1 updated")
    }

    func testTheFilterTabsHideAZeroKindAndAreAbsentWithOnlyOne() {
        XCTAssertEqual(RunItemsModel.filterKinds([.created: 2, .updated: 5, .archived: 0]), [.created, .updated])
        XCTAssertEqual(RunItemsModel.filterKinds([.updated: 5]), [], "one kind: nothing to choose between")
        XCTAssertEqual(RunItemsModel.filterKinds([:]), [])
        XCTAssertEqual(RunItemsModel.filterKinds([.removed: 1, .created: 1, .archived: 1, .updated: 1]),
                       [.created, .updated, .archived, .removed], "in reading order")
    }

    // MARK: Marks

    func testARowWearsASiteOrACallAppAndNeverTheSourcesOwnMark() throws {
        let items = try items()
        XCTAssertNil(RunItemsModel.rowMark(items.conversations[0]), "the source's card already wears its mark")
        XCTAssertEqual(RunItemsModel.rowMark(items.conversations[2]), .site("docs.example.com"))
        XCTAssertNil(RunItemsModel.rowMark(items.conversations[3]), "an unknown call app has no mark")
        XCTAssertEqual(RunItemsModel.rowMark(.init(id: "m", origin: "hex", meeting: EpisodeMeetingBrief(app: "Zoom"))),
                       .callApp("zoom"))
        XCTAssertEqual(RunItemsModel.rowMark(.init(id: "s", origin: "chrome-bookmark", site: "docs.example.com",
                                                   meeting: EpisodeMeetingBrief(app: "Zoom"))),
                       .site("docs.example.com"), "the Queue's priority: the site first")
    }

    func testARowsQuietLineIsTheMachineAndTheDayWhenTheyAreNotTheRuns() {
        XCTAssertEqual(RunItemsModel.rowMeta(machineName: "device-a", day: "Nov 22"), "device-a · Nov 22")
        XCTAssertEqual(RunItemsModel.rowMeta(machineName: nil, day: "Nov 22"), "Nov 22")
        XCTAssertNil(RunItemsModel.rowMeta(machineName: nil, day: nil))
    }

    func testTheOriginsAreTheNarrowedConversations() throws {
        let items = try items()
        XCTAssertEqual(RunItemsModel.origins(items), ["claude-code", "chrome-bookmark", "hex"])
        XCTAssertEqual(RunItemsModel.origins(items, machineId: "device-a"), ["claude-code"])
    }

    func testTheMachineNameIsNeverThisComputersOwn() {
        let machines = [MachineStatus(deviceId: nil, name: "saga-01", role: "server", connected: true, how: "local",
                                      queue: 0, current: true),
                        MachineStatus(deviceId: "device-a", name: "device-a", connected: true, how: nil, queue: 0)]
        XCTAssertEqual(MachinesStrip.deviceName("device-a", in: machines), "device-a")
        XCTAssertNil(MachinesStrip.deviceName(nil, in: machines), "this computer's own: no name")
        XCTAssertNil(MachinesStrip.deviceName("device-a", in: [machines[1]]), "one machine: nothing to tell apart")
    }

    // MARK: The list under a machine filter

    func testWithAMachineSelectedOnlyRunsThatReadFromItAreListed() throws {
        let entry = try JSONDecoder().decode(SleepHistoryEntry.self,
                                             from: Data(contentsOf: Self.fixtures.appendingPathComponent("sleep-history-run.json")))
        let cards = RunCardModel.cards([entry], locale: us)
        let key = try XCTUnwrap(cards.first).key
        let loaded: [SleepConsolidatedKey: SleepConsolidated] = [key: try items()]
        XCTAssertEqual(ConsolidationHistoryCard.listed(cards, items: loaded, machineId: nil).count, 1)
        XCTAssertEqual(ConsolidationHistoryCard.listed(cards, items: loaded, machineId: "device-a").count, 1)
        XCTAssertEqual(ConsolidationHistoryCard.listed(cards, items: loaded, machineId: "device-z").count, 0)
        XCTAssertEqual(ConsolidationHistoryCard.listed(cards, items: [:], machineId: "device-a").count, 0,
                       "items not here yet: not listed until they say")
        XCTAssertEqual(ConsolidationHistoryCard.listed(cards, items: [:], machineId: nil).count, 1)
    }

    func testAFailedCardIsListedUnderAFilterAndAPendingOneIsNot() throws {
        let entry = try JSONDecoder().decode(SleepHistoryEntry.self,
                                             from: Data(contentsOf: Self.fixtures.appendingPathComponent("sleep-history-run.json")))
        let cards = RunCardModel.cards([entry], locale: us)
        let key = try XCTUnwrap(cards.first).key
        XCTAssertEqual(ConsolidationHistoryCard.listed(cards, items: [:], machineId: "device-a", itemsFailed: [key]).count, 1,
                       "a card whose items could not be fetched is unknown, not empty: it is listed and asks again")
        XCTAssertEqual(ConsolidationHistoryCard.listed(cards, items: [:], machineId: "device-a", itemsFailed: []).count, 0)
        XCTAssertFalse(ConsolidationHistoryCard.settled(cards, items: [:], itemsFailed: []), "still loading")
        XCTAssertTrue(ConsolidationHistoryCard.settled(cards, items: [:], itemsFailed: [key]))
        XCTAssertTrue(ConsolidationHistoryCard.settled(cards, items: [key: try items()], itemsFailed: []))
    }

    /// A filter whose kind the narrowed card no longer has must not hold the card empty.
    func testAPickedKindThatIsGoneFallsBackToAll() throws {
        let items = try items()
        let counts = RunItemsModel.counts(items, machineId: "device-a")
        let kinds = RunItemsModel.filterKinds(counts)
        XCTAssertEqual(RunItemsModel.effectiveFilter(.created, kinds: kinds), .created)
        XCTAssertNil(RunItemsModel.effectiveFilter(.archived, kinds: kinds), "no archived page for this machine")
        XCTAssertNil(RunItemsModel.effectiveFilter(.created, kinds: []), "tabs hidden: nothing can be filtered")
        XCTAssertNil(RunItemsModel.effectiveFilter(nil, kinds: kinds))
        let all = RunItemsModel.body(items, filter: RunItemsModel.effectiveFilter(.archived, kinds: kinds),
                                     machineId: "device-a")
        XCTAssertFalse(all.isEmpty)
        XCTAssertTrue(RunItemsModel.body(items, filter: .archived, machineId: "device-a").isEmpty,
                      "the raw filter would have shown nothing")
    }

    /// A run past the server's cap: a page fed by a conversation the list lacks is no upkeep, and a machine's numbers
    /// say they are partial.
    func testAPageFedByAnUnlistedConversationIsNotUpkeep() throws {
        let capped = try JSONDecoder().decode(SleepConsolidated.self, from: Data("""
        {"commits": ["a"], "truncated": true,
         "conversations": [{"id": "ep1", "origin": "claude-code", "title": "T", "pages": ["p1"], "device": "device-a"}],
         "created": [{"id": "p1", "change": "created", "episodes": ["ep1"]},
                     {"id": "p2", "change": "created", "episodes": ["ep9"]},
                     {"id": "p3", "change": "updated", "episodes": []}],
         "counts": {"conversations": 450}}
        """.utf8))
        let body = RunItemsModel.body(capped, filter: nil, machineId: nil)
        XCTAssertEqual(body.unlisted.map(\.id), ["p2"], "fed by a conversation past the cap")
        XCTAssertEqual(body.leftover.map(\.id), ["p3"], "no conversation behind it at all: upkeep")
        XCTAssertFalse(body.isEmpty)
        XCTAssertTrue(RunItemsModel.countsArePartial(capped, machineId: "device-a"))
        XCTAssertFalse(RunItemsModel.countsArePartial(capped, machineId: nil), "every machine: the server's whole counts")
        var whole = capped
        whole.truncated = false
        XCTAssertFalse(RunItemsModel.countsArePartial(whole, machineId: "device-a"))
        XCTAssertEqual(RunItemsModel.body(whole, filter: nil, machineId: nil).unlisted, [])
    }

    func testAClosedCardNamesItsPagesAndSourcesForVoiceOver() throws {
        let entry = try JSONDecoder().decode(SleepHistoryEntry.self,
                                             from: Data(contentsOf: Self.fixtures.appendingPathComponent("sleep-history-run.json")))
        let card = try XCTUnwrap(RunCardModel.cards([entry], locale: us).first)
        let items = try items()
        let preview = RunItemsModel.preview(items)
        let spoken = try XCTUnwrap(RunPagePreview.spoken(preview.pages, total: preview.total, names: .empty))
        XCTAssertTrue(spoken.contains("new page"), "the green dot's words")
        let gone = preview.pages.filter { $0.change == .archived || $0.change == .removed }
        let goneSpoken = try XCTUnwrap(RunPagePreview.spoken(gone, total: gone.count, names: .empty))
        XCTAssertTrue(goneSpoken.contains("archived") && goneSpoken.contains("removed"), "grey and red dots in words too")
        let label = card.accessibilityLabel(summary: "S", pages: spoken, sources: ["Claude Code"], locale: us)
        XCTAssertTrue(label.contains(spoken))
        XCTAssertTrue(label.contains(Copy.RunCard.readFrom(["Claude Code"])))
        XCTAssertFalse(card.accessibilityLabel(summary: "S", locale: us).contains("new page"))
        XCTAssertNil(RunPagePreview.spoken([], total: 0, names: .empty))
    }

    // MARK: Structure

    /// What the page no longer holds, and what it must (owner 2026-11-24).
    func testThePastSleepsSourceHoldsTheNewCardsAndNoOldBlocks() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        func text(_ path: String) throws -> String { try String(contentsOf: root.appendingPathComponent(path), encoding: .utf8) }
        let card = try text("Views/Sleep/RunCard.swift")
        XCTAssertTrue(card.contains(".sourceCardChrome("), "the Queue's source-card chrome")
        XCTAssertFalse(card.contains("DisclosureHeader"), "no stacked folds on the card's head")
        let body = try text("Views/Sleep/RunCardBody.swift")
        XCTAssertEqual(body.components(separatedBy: "DisclosureHeader(title:").count - 1, 1, "ONE fold: the run's details")
        XCTAssertTrue(body.contains(".softCard(ground: .nested"), "a card per source, nested like the Queue's")
        XCTAssertFalse(body.contains("APIClient"), "the page never calls the API itself")
        let page = try text("Views/Sleep/SleepView.swift")
        let start = try XCTUnwrap(page.range(of: "case .pastReads:"))
        let end = try XCTUnwrap(page.range(of: "/// Beside an open item", range: start.upperBound..<page.endIndex))
        XCTAssertFalse(page[start.upperBound..<end.lowerBound].contains("SleepLayout.contentWidth"),
                       "Past sleeps is the Queue's column, not the 760 pt text column")
    }

    /// A run's conversation row draws a saved link's site mark only when there is a real one: its fetched icon or a
    /// bundled family mark. The letter monogram (`SiteIcon`'s last rung) is never drawn here — no slot, the title on
    /// the row's leading edge.
    func testASiteMarkDrawsOnlyARealIconNeverTheMonogram() {
        let shipped: (String) -> Bool = { _ in true }
        let none: (String) -> Bool = { _ in false }
        XCTAssertFalse(RunItemsModel.siteMarkDraws(site: "docs.example.com", favicon: false, markExists: shipped),
                       "an unknown site with no stored icon draws nothing")
        XCTAssertTrue(RunItemsModel.siteMarkDraws(site: "docs.example.com", favicon: true, markExists: shipped))
        XCTAssertTrue(RunItemsModel.siteMarkDraws(site: "reddit", favicon: false, markExists: shipped),
                      "a family whose mark ships draws it")
        XCTAssertFalse(RunItemsModel.siteMarkDraws(site: "reddit", favicon: false, markExists: none),
                       "a family whose file is missing draws nothing, not a letter")
    }
}
