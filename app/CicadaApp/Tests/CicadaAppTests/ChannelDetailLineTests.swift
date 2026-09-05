import XCTest
@testable import CicadaApp

/// R-S5 (backend half) — the server stopped baking `f"{n:,}"` into a channel's
/// `detail`, so the count arrives as `count` + `countNoun` + `countIsDelta` and
/// this composer puts the line back together in the READER's locale. The
/// composed string must be byte-identical to what `channel_registry` printed
/// before the move, or the change is a redesign wearing a refactor's clothes.
final class ChannelDetailLineTests: XCTestCase {

    private let enUS = Locale(identifier: "en_US")

    private func channel(count: Int = 0, noun: String? = nil, isDelta: Bool = false,
                         detail: String? = nil) -> SourceChannel {
        SourceChannel(id: "c", label: "C", connected: true, count: count,
                      lastSync: nil, detail: detail, countNoun: noun, countIsDelta: isDelta)
    }

    /// A running total (`_sync_channel`): "412 bookmarks · synced 2026-08-04".
    func testATotalReadsAsNounPhraseThenDetail() {
        let line = ChannelDetailLine.text(
            channel(count: 412, noun: "bookmark", detail: "synced 2026-08-04"), locale: enUS)
        XCTAssertEqual(line, "412 bookmarks · synced 2026-08-04")
    }

    /// A connector's `count` is "items pulled THIS run", not a total
    /// (`_connector_channel:150-153`) — the `+` and the " this sync" suffix are
    /// the words that said so, and they now live here.
    func testADeltaKeepsThePlusAndTheThisSyncSuffix() {
        let line = ChannelDetailLine.text(
            channel(count: 7, noun: "pin", isDelta: true, detail: "synced 2026-08-04"),
            locale: enUS)
        XCTAssertEqual(line, "+7 pins this sync · synced 2026-08-04")
    }

    func testOneOfSomethingIsSingularInBothShapes() {
        XCTAssertEqual(
            ChannelDetailLine.text(channel(count: 1, noun: "feed", detail: "polled 2026-08-04"),
                                   locale: enUS),
            "1 feed · polled 2026-08-04")
        XCTAssertEqual(
            ChannelDetailLine.text(channel(count: 1, noun: "pin", isDelta: true,
                                           detail: "synced 2026-08-04"), locale: enUS),
            "+1 pin this sync · synced 2026-08-04")
    }

    /// A branch with nothing to count ships no noun (R-S16), so "0 pins · Last
    /// sync failed" is unrepresentable rather than merely unlikely.
    func testANounlessChannelRendersItsDetailVerbatim() {
        XCTAssertEqual(
            ChannelDetailLine.text(channel(count: 0, detail: "Last sync failed · 401"),
                                   locale: enUS),
            "Last sync failed · 401")
    }

    /// "Files & links" has a count and no state line of its own.
    func testANounWithNoDetailIsThePhraseAlone() {
        XCTAssertEqual(ChannelDetailLine.text(channel(count: 2, noun: "saved item"), locale: enUS),
                       "2 saved items")
        XCTAssertNil(ChannelDetailLine.text(channel()))
    }

    /// The whole point of moving the number: it groups in the viewer's locale,
    /// not in the server's `en_US`.
    ///
    /// The second locale is `de_DE`, for the reason `SourcesV2Tests` records:
    /// CLDR gives `es_ES` `minimumGroupingDigits = 2`, so Spanish leaves a
    /// four-digit number ungrouped and the assertion would prove nothing here.
    func testTheCountGroupsInTheReadersLocale() {
        let ch = channel(count: 1035, noun: "bookmark", detail: "synced 2026-08-04")
        XCTAssertEqual(ChannelDetailLine.text(ch, locale: enUS), "1,035 bookmarks · synced 2026-08-04")
        XCTAssertEqual(ChannelDetailLine.text(ch, locale: Locale(identifier: "de_DE")),
                       "1.035 bookmarks · synced 2026-08-04")
    }

    /// Decode tolerance: an older backend omits both new keys, and its
    /// already-formatted `detail` must still come through untouched — never a
    /// dropped row, never a doubled count.
    func testAnOlderBackendsPayloadDecodesAndRendersItsDetailUnchanged() throws {
        let json = """
        {"id":"rss","label":"RSS feeds","connected":true,"count":3,
         "lastSync":"2026-08-30T08:12:00Z","detail":"3 feeds · polled 2026-08-30",
         "actions":["poll","manage"]}
        """
        let ch = try JSONDecoder().decode(SourceChannel.self, from: Data(json.utf8))
        XCTAssertNil(ch.countNoun)
        XCTAssertFalse(ch.countIsDelta)
        XCTAssertEqual(ChannelDetailLine.text(ch, locale: enUS), "3 feeds · polled 2026-08-30")
    }
}
