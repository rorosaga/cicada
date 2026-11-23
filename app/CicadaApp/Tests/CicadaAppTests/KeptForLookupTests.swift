import XCTest
@testable import CicadaApp

/// Owner 2026-11-23 — what is kept for lookup, in order: the breakdown by source, each source's items a page at a time.
@MainActor
final class KeptForLookupTests: XCTestCase {
    private func item(_ id: String, processed: Bool = true) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: [
            "id": id, "timestamp": "2026-11-23T10:00:00Z", "source": "bookmark", "origin": "chrome-bookmark",
            "title": id, "preview": "", "processed": processed, "change": "new",
        ]))
    }

    func testOpeningReadsTheBreakdownAndASourceReadsItsPagesWithoutRepeats() async throws {
        let pages = [0: [try item("a"), try item("b")], 2: [try item("b"), try item("c")]]
        var asked: [String] = []
        let load: KeptForLookupModel.Loader = { origin, offset in
            asked.append("\(origin ?? "-"):\(offset)")
            return SleepKept(total: 3, sources: [.init(origin: "chrome-bookmark", count: 3)],
                             items: origin == nil ? [] : (pages[offset] ?? []))
        }
        let model = KeptForLookupModel()
        model.open = true
        await model.refresh(load: load)
        XCTAssertEqual(model.sources?.map(\.origin), ["chrome-bookmark"])
        XCTAssertEqual(asked, ["-:0"], "no source is open: no item is read")

        model.toggle("chrome-bookmark")
        await model.loadFirstPage("chrome-bookmark", load: load)
        XCTAssertEqual(model.items["chrome-bookmark"]?.map(\.id), ["a", "b"])
        await model.loadMore("chrome-bookmark", load: load)
        XCTAssertEqual(model.items["chrome-bookmark"]?.map(\.id), ["a", "b", "c"], "an overlapping page repeats no card")
        XCTAssertEqual(asked, ["-:0", "chrome-bookmark:0", "chrome-bookmark:2"])
    }

    func testAFailedReadSaysSoAndASourceThatLeftTheBreakdownCloses() async throws {
        struct Offline: Error {}
        let model = KeptForLookupModel()
        model.open = true
        await model.refresh(load: { _, _ in throw Offline() })
        XCTAssertTrue(model.failed)
        XCTAssertNil(model.sources)

        model.openSources = ["gone-source", "chrome-bookmark"]
        let only = try item("a")
        await model.refresh(load: { origin, _ in
            SleepKept(total: 1, sources: [.init(origin: "chrome-bookmark", count: 1)], items: origin == nil ? [] : [only])
        })
        XCTAssertFalse(model.failed)
        XCTAssertEqual(model.openSources, ["chrome-bookmark"])
        XCTAssertEqual(model.items["chrome-bookmark"]?.map(\.id), ["a"], "an open source's first page is read again")
    }

    /// A kept save neither waits nor was read by a model: its card says neither and wears no marker.
    func testAKeptCardSaysNeitherReadNorNew() throws {
        let now = Date(timeIntervalSince1970: 1_795_000_000)
        let indexed = try item("a", processed: true)
        XCTAssertFalse(EpisodeRowText.footer(indexed, target: nil, now: now, showsState: false).contains("read"))
        XCTAssertTrue(EpisodeRowText.footer(indexed, target: nil, now: now).contains("read"))
        let queued = try item("b", processed: false)
        XCTAssertFalse(EpisodeRowText.cardLabel(queued, target: nil, now: now, showsState: false).contains("new"))
        XCTAssertEqual(Copy.Kept.showMore(shown: 30, of: 1_200, Locale(identifier: "en_US")), "Show more (30 of 1,200)")
    }

    /// A saved link's record opens with its title as a heading: the card never says the title twice (DR-38).
    func testAPreviewThatOnlyRepeatsTheTitleIsNotDrawn() throws {
        func item(title: String, preview: String) throws -> EpisodeQueueItem {
            try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: [
                "id": "ep_1", "timestamp": "2026-11-23T10:00:00Z", "source": "bookmark", "origin": "chrome-bookmark",
                "title": title, "preview": preview, "processed": false,
            ]))
        }
        XCTAssertNil(EpisodeRowText.preview(try item(title: "A guide", preview: "# A guide\n\nSource: bookmark")))
        XCTAssertNil(EpisodeRowText.preview(try item(title: "A guide", preview: "  ")))
        XCTAssertEqual(EpisodeRowText.preview(try item(title: "A guide", preview: "# Another heading\nwords")),
                       "# Another heading\nwords")
        XCTAssertEqual(EpisodeRowText.preview(try item(title: "Plans", preview: "user: what is left?")),
                       "user: what is left?")
    }
}
