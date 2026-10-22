import XCTest
@testable import CicadaApp

/// marks-2 (owner 2026-10-20) — "none of the YouTube stuff shows thumbnails, just low-res YouTube logos", and "I don't
/// like, app-wide, when we show a picture that has a letter when we can get something specific to the site."
final class MarksThatAppearTests: XCTestCase {
    private func item(_ json: [String: Any]) throws -> ChannelItem {
        try JSONDecoder().decode(ChannelItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    func testASavedYouTubeVideoDrawsItsStillAskedByItsPage() throws {
        let video = try item(["kind": "media", "id": "media-v1", "title": "A video", "host": "youtube.com",
                              "site": "youtube.com", "video": true])
        XCTAssertEqual(SavedItemText.stillPath(video), "/sources/saved/media-v1/still")
        let page = try item(["kind": "media", "id": "media-p1", "title": "A page", "host": "paperfold.io",
                             "site": "paperfold.io"])
        XCTAssertNil(SavedItemText.stillPath(page), "a page keeps its site's mark")
        let older = try item(["kind": "media", "id": "media-v2", "title": "A video", "video": "yes"])
        XCTAssertNil(older.video, "a malformed field drops the field, never the row")
        let notMedia = try item(["kind": "episode", "id": "ep_2026-10-20_001", "title": "x", "video": true])
        XCTAssertNil(SavedItemText.stillPath(notMedia))
    }

    func testAStillPathNeverReshapesTheRoute() {
        XCTAssertEqual(SourcePictures.savedStillPath(mediaId: "media-abc_1"), "/sources/saved/media-abc_1/still")
        XCTAssertNil(SourcePictures.savedStillPath(mediaId: "../etc"))
        XCTAssertNil(SourcePictures.savedStillPath(mediaId: "a/b"))
        XCTAssertNil(SourcePictures.savedStillPath(mediaId: ""))
    }

    /// A saved link still waiting for Sleep names its site now: its row asks by the episode's id, not a letter.
    func testAWaitingSavedLinkInAListAsksByItsEpisode() throws {
        let waiting = try item(["kind": "episode", "id": "ep_2026-10-20_001", "title": "A page",
                                "host": "paperfold.io", "site": "paperfold.io"])
        XCTAssertEqual(SavedItemText.mark(waiting),
                       .site(key: "paperfold.io", label: "paperfold.io", door: .episode("ep_2026-10-20_001")))
        let page = try item(["kind": "media", "id": "media-p1", "title": "A page", "host": "paperfold.io",
                             "site": "paperfold.io"])
        XCTAssertEqual(SavedItemText.mark(page),
                       .site(key: "paperfold.io", label: "paperfold.io", door: .media("media-p1")))
    }

    /// A 404 is believed for `missTTL` only: a window left open across a backend update asks once more.
    func testAMissIsAskedAgainOnlyAfterItsTTL() async {
        let asks = Counter()
        let clock = Clock()
        let store = SiteIconStore(fetch: { _ in nil }, fetchForSaved: { _ in await asks.bump(); return nil },
                                  missTTL: 600, now: { clock.now })
        _ = await store.image(site: "paperfold.io", bank: "b", saved: .media("m1"))
        _ = await store.image(site: "paperfold.io", bank: "b", saved: .media("m1"))
        var n = await asks.n
        XCTAssertEqual(n, 1, "a fresh miss is believed")
        clock.now = clock.now.addingTimeInterval(601)
        _ = await store.image(site: "paperfold.io", bank: "b", saved: .media("m1"))
        n = await asks.n
        XCTAssertEqual(n, 2, "an expired miss is asked again")
    }
}

private actor Counter {
    var n = 0
    func bump() { n += 1 }
}

private final class Clock: @unchecked Sendable {
    var now = Date(timeIntervalSince1970: 1_800_000_000)
}
