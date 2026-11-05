import XCTest
@testable import CicadaApp

private actor AskedFeeds {
    var ids: [String] = []
    func add(_ id: String) { ids.append(id) }
}

/// ROR-108 — the RSS page's feeds: the words each row says, and the wire shape they are read from.
final class FeedChannelsTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    func testARowSaysHowManyItemsAFailedCheckAndNothingYet() {
        XCTAssertEqual(FeedChannelText.meta(SourceCollection(id: "a", name: "A", count: 12), locale: us), "12 items")
        XCTAssertEqual(FeedChannelText.meta(SourceCollection(id: "a", name: "A", count: 1), locale: us), "1 item")
        XCTAssertEqual(FeedChannelText.meta(SourceCollection(id: "b", name: "B", count: 0), locale: us),
                       Copy.SourceBrowser.feedNothingYet)
        let failed = "Last check failed: too many requests"
        XCTAssertEqual(FeedChannelText.meta(SourceCollection(id: "c", name: "C", count: 0, problem: failed), locale: us),
                       failed)
        XCTAssertEqual(FeedChannelText.meta(SourceCollection(id: "d", name: "D", count: 3, problem: failed), locale: us),
                       "\(failed) · 3 items")
    }

    func testTheAddressAndLastCheckRideTheHelpOnly() {
        let feed = SourceCollection(id: "a", name: "Alpha", count: 2, url: "https://a.example.com/rss",
                                    polled: "2026-11-05")
        let help = FeedChannelText.help(feed, locale: us)
        XCTAssertTrue(help.hasPrefix("Alpha, https://a.example.com/rss, checked "), help)
        XCTAssertFalse(FeedChannelText.meta(feed, locale: us).contains("example.com"))
        XCTAssertEqual(FeedChannelText.help(SourceCollection(id: "other", name: "Other", count: 2), locale: us), "Other")
    }

    func testAFeedWearsTheBackendsBundledMarkItsSitesIconOrAMonogram() {
        let substack = SourceCollection(id: "a", name: "Alpha", count: 1, mark: "substack")
        XCTAssertEqual(FeedChannelMarkModel.of(substack, markExists: { _ in true }), .bundled("substack"))
        let site = SourceCollection(id: "b", name: "Beta", count: 0, site: "b.example.com")
        XCTAssertEqual(FeedChannelMarkModel.of(site, markExists: { _ in true }),
                       .link(.site(key: "b.example.com", label: "b.example.com", door: .feed("b"))),
                       "the site's monogram when no icon comes, not the feed's name")
        let other = SourceCollection(id: "other", name: "Other", count: 2)
        XCTAssertEqual(FeedChannelMarkModel.of(other, markExists: { _ in true }), .link(.monogram("O")))
        XCTAssertEqual(FeedChannelMarkModel.of(substack, markExists: { _ in false }), .link(.monogram("A")),
                       "a mark file that does not ship still draws a mark")
        XCTAssertTrue(LogoImage.exists(name: "substack"), "the bundled mark ships")
    }

    func testAFeedsIconIsAskedByItsIdAlone() async {
        let asked = AskedFeeds()
        let store = SiteIconStore(fetch: { _ in XCTFail("never the icon-service route"); return nil },
                                  fetchForSaved: { _ in XCTFail("never the saved link's route"); return nil },
                                  fetchForFeed: { await asked.add($0); return nil })
        _ = await store.image(site: "b.example.com", bank: "bank", saved: .feed("feed-1"))
        let seen = await asked.ids
        XCTAssertEqual(seen, ["feed-1"])
    }

    func testAMarkDecodes() throws {
        let json = #"""
        {"channel": "rss", "accounts": [{"name": null, "provider": null, "count": 0, "collections": [
          {"id": "f1", "name": "Alpha", "count": 0, "mark": "substack"},
          {"id": "f2", "name": "Beta", "count": 0, "site": "b.example.com"}]}]}
        """#
        let feeds = FeedChannelText.feeds(try JSONDecoder().decode(ChannelCollections.self, from: Data(json.utf8)))
        XCTAssertEqual(feeds.map(\.mark), ["substack", nil])
        XCTAssertEqual(feeds.map(\.site), [nil, "b.example.com"])
    }

    func testTheFeedsDecodeLenientlyAndAnEmptyTreeLeavesThePlainList() throws {
        let json = #"""
        {"channel": "rss", "accounts": [{"name": null, "provider": null, "count": 3, "collections": [
          {"id": "f1", "name": "Alpha", "count": 3, "latest": "2026-11-05", "url": "https://a.example.com/rss",
           "polled": "2026-11-05", "problem": null},
          {"id": "f2", "name": "b.example.com", "count": 0, "latest": null, "url": "https://b.example.com/rss",
           "polled": "2026-11-05", "problem": "Last check failed: not found"},
          {"id": "other", "name": "Other", "count": 1, "latest": "2026-11-01"}]}]}
        """#
        let tree = try JSONDecoder().decode(ChannelCollections.self, from: Data(json.utf8))
        let feeds = FeedChannelText.feeds(tree)
        XCTAssertEqual(feeds.map(\.name), ["Alpha", "b.example.com", "Other"])
        XCTAssertEqual(feeds[1].problem, "Last check failed: not found")
        XCTAssertNil(feeds[2].url)
        XCTAssertTrue(FeedChannelText.feeds(nil).isEmpty)
        XCTAssertTrue(FeedChannelText.feeds(ChannelCollections(channel: "rss", accounts: [])).isEmpty)
    }

    func testAFeedsItemsAreItsOwnListKey() {
        let key = SourceListKey.make(FeedChannelText.channel, collection: "f1")
        XCTAssertEqual(SourceListKey.parts(key).channel, "rss")
        XCTAssertEqual(SourceListKey.parts(key).collection, "f1")
    }
}
