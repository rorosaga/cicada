import XCTest
@testable import CicadaApp

/// G221 (B) — a save inside a site, recognised from the control the person clicked: by where it sits and what changes,
/// never by a word. Synthetic rows only; the labels are deliberately in several languages and never compared to text.
final class SiteSaveTests: XCTestCase {
    private func button(_ label: String) -> SiteSaveNode { SiteSaveNode(role: "AXButton", label: label) }
    private func menu(_ label: String) -> SiteSaveNode { SiteSaveNode(role: "AXPopUpButton", label: label) }
    private func link(_ url: String) -> SiteSaveNode { SiteSaveNode(role: "AXLink", label: "v", url: url) }

    /// A timeline row: reply, repost, like, the views link, bookmark, share.
    private func timeline(save: String, counts: String, user: String = "alpha_user", id: String = "1900000000000000001",
                          clicked: Int = 4) -> SiteSaveReading {
        SiteSaveReading(row: [button("r"), menu("rp"), button("l"),
                              link("https://x.com/\(user)/status/\(id)/analytics"), button(save), menu("s")],
                        clicked: clicked, rowLabel: counts)
    }

    /// The open post's row on its own page: no views link.
    private func ownPage(save: String, counts: String, clicked: Int = 3,
                         page: String? = "https://x.com/alpha_user/status/1900000000000000002") -> SiteSaveReading {
        SiteSaveReading(row: [button("r"), menu("rp"), button("l"), button(save), menu("s")],
                        clicked: clicked, rowLabel: counts, page: page)
    }

    func testInATimelineTheSaveControlIsTheButtonAfterThePostsOwnLink() throws {
        let item = try SiteSaveRule.item(timeline(save: "Guardar", counts: "")).get()
        XCTAssertEqual(item, SiteSaveItem(site: "x", origin: "x-bookmarks",
                                          url: "https://x.com/alpha_user/status/1900000000000000001",
                                          title: "Post by @alpha_user"))
        // The older host is the same post, stored under the one spelling.
        var old = timeline(save: "b", counts: "")
        old.row[3].url = "https://twitter.com/alpha_user/status/1900000000000000001/analytics"
        XCTAssertEqual(try SiteSaveRule.item(old).get().url, item.url)
    }

    func testALikeAReplyOrAMenuIsNeverASave() {
        XCTAssertEqual(SiteSaveRule.item(timeline(save: "b", counts: "", clicked: 2)), .failure(.notTheSaveSlot))
        XCTAssertEqual(SiteSaveRule.item(timeline(save: "b", counts: "", clicked: 0)), .failure(.notTheSaveSlot))
        XCTAssertEqual(SiteSaveRule.item(timeline(save: "b", counts: "", clicked: 5)), .failure(.notAButton))
        XCTAssertEqual(SiteSaveRule.item(timeline(save: "b", counts: "", clicked: 3)), .failure(.notAButton))
        XCTAssertEqual(SiteSaveRule.item(ownPage(save: "b", counts: "", clicked: 2)), .failure(.notTheSaveSlot))
    }

    func testOnAPostsOwnPageTheSaveControlIsTheLastPlainButtonAndThePostIsThePage() throws {
        XCTAssertEqual(try SiteSaveRule.item(ownPage(save: "保存", counts: "")).get().url,
                       "https://x.com/alpha_user/status/1900000000000000002")
        // A page that is not a post, another site, or no address at all: nothing.
        XCTAssertEqual(SiteSaveRule.item(ownPage(save: "b", counts: "", page: "https://x.com/home")), .failure(.noPostLink))
        XCTAssertEqual(SiteSaveRule.item(ownPage(save: "b", counts: "", page: "https://alpha.example/a/status/12")),
                       .failure(.unknownSite))
        XCTAssertEqual(SiteSaveRule.item(ownPage(save: "b", counts: "", page: nil)), .failure(.unknownSite))
        // A row with two posts' links is not a row this rule knows.
        var two = timeline(save: "b", counts: "")
        two.row.insert(link("https://x.com/bob_example/status/1900000000000000009/analytics"), at: 0)
        two.clicked = 5
        XCTAssertEqual(SiteSaveRule.item(two), .failure(.notTheSaveSlot))
    }

    func testASaveIsTheControlChangingAndACountGoingUpByOneInAnyLanguage() {
        // English, Spanish, Japanese, Arabic digits: the words are never read, only the label differing and the count.
        for (off, on, was, now) in [("Bookmark", "Bookmarked", "20 replies, 10 reposts, 184 likes, 252 bookmarks, 24383 views",
                                     "20 replies, 10 reposts, 184 likes, 253 bookmarks, 24383 views"),
                                    ("Guardar", "Guardado", "2 respuestas, 1.204 Me gusta, 99 elementos guardados",
                                     "2 respuestas, 1.204 Me gusta, 100 elementos guardados"),
                                    ("ブックマーク", "ブックマーク済み", "返信20件、いいね184件、ブックマーク9件", "返信20件、いいね184件、ブックマーク10件"),
                                    ("حفظ", "تم الحفظ", "٢٠ ردًا، ١٨٤ إعجابًا، ٩ إشارات", "٢٠ ردًا، ١٨٤ إعجابًا، ١٠ إشارات")] {
            XCTAssertEqual(SiteSaveRule.outcome(before: timeline(save: off, counts: was),
                                                after: timeline(save: on, counts: now)), .saved, off)
            XCTAssertEqual(SiteSaveRule.outcome(before: timeline(save: on, counts: now),
                                                after: timeline(save: off, counts: was)), .unsaved, off)
        }
    }

    func testTheFirstSaveOfAPostAddsACountAndARoundedCountSaysNothing() {
        // A zero count is left out of the label, so the first save adds a "1".
        XCTAssertEqual(SiteSaveRule.outcome(before: timeline(save: "a", counts: "1 reply, 28 likes, 1266 views"),
                                            after: timeline(save: "b", counts: "1 reply, 28 likes, 1 bookmark, 1266 views")),
                       .saved)
        XCTAssertEqual(SiteSaveRule.step(before: [1, 28, 1, 1266], after: [1, 28, 1266]), -1)
        // The control changed and the counts did not move (rounded, or late): a change, direction unknown.
        XCTAssertEqual(SiteSaveRule.outcome(before: timeline(save: "a", counts: "11.4K"),
                                            after: timeline(save: "b", counts: "11.4K")), .changed)
        // Someone else's like landing in the same second is two counts moving: no direction read from it.
        XCTAssertNil(SiteSaveRule.step(before: [20, 184, 252], after: [20, 185, 253]))
        // The control did not change: not a save, whatever the counts did.
        XCTAssertEqual(SiteSaveRule.outcome(before: timeline(save: "a", counts: "1, 2, 3"),
                                            after: timeline(save: "a", counts: "1, 2, 4")), SiteSaveRule.Outcome.none)
    }

    func testNumbersAreReadWithTheirGroupSeparatorsAndNeverOverflow() {
        XCTAssertEqual(SiteSaveRule.numbers(in: "20 replies, 1,204 likes, 24383 views."), [20, 1204, 24383])
        XCTAssertEqual(SiteSaveRule.numbers(in: "1\u{202F}204 vues"), [1204])
        XCTAssertEqual(SiteSaveRule.numbers(in: "no counts"), [])
        XCTAssertEqual(SiteSaveRule.numbers(in: "id 190000000000000000199 and 7"), [7])
    }

    func testASitesOwnChannelIsItsOriginAndABrowsersLosesItsPlural() {
        XCTAssertEqual(SavedBookmarkLookup.origin(forChannel: "x-bookmarks"), "x-bookmarks")
        XCTAssertEqual(SavedBookmarkLookup.origin(forChannel: "chrome-bookmarks"), "chrome-bookmark")
        XCTAssertEqual(SavedBookmarkLookup.origin(forChannel: "safari-bookmarks"), "safari-bookmark")
    }

    /// The state before a click comes from where the pointer rested: a tap is over before a read at the click could
    /// finish, and the browser's first answer about a fresh point is often a neighbour.
    func testTheStateBeforeAClickIsTheOneReadWhenThePointerRested() throws {
        let rested = timeline(save: "off", counts: "3 a, 9 b")
        let item = try SiteSaveRule.item(rested).get()
        let hover = SiteSaveWatcher.Hover(item: item, reading: rested, point: CGPoint(x: 100, y: 100), at: 1000)
        // A click near the rest, soon after, leans on it; far away or much later it does not.
        XCTAssertNotNil(SiteSaveWatcher.usable(hover, at: CGPoint(x: 110, y: 104), now: 1005))
        XCTAssertNil(SiteSaveWatcher.usable(hover, at: CGPoint(x: 100, y: 160), now: 1005))
        XCTAssertNil(SiteSaveWatcher.usable(hover, at: CGPoint(x: 100, y: 100), now: 1100))
        // The read at the click already shows the new state (a tap), or names nothing: the rest's reading is "before".
        let flipped = timeline(save: "on", counts: "3 a, 10 b")
        XCTAssertEqual(SiteSaveWatcher.before(hover: hover, atClick: flipped)?.reading, rested)
        XCTAssertEqual(SiteSaveWatcher.before(hover: hover, atClick: nil)?.reading, rested)
        XCTAssertEqual(SiteSaveRule.outcome(before: rested, after: flipped), .saved)
        // A click on another post's control uses its own read; with no rest and no control, nothing.
        let other = timeline(save: "off", counts: "", user: "bob_example")
        XCTAssertEqual(SiteSaveWatcher.before(hover: hover, atClick: other)?.item.url,
                       "https://x.com/bob_example/status/1900000000000000001")
        XCTAssertNil(SiteSaveWatcher.before(hover: nil, atClick: nil))
        XCTAssertNil(SiteSaveWatcher.before(hover: nil, atClick: timeline(save: "x", counts: "", clicked: 2)))
    }

    /// A noticed save is stored under the site's own source first, then asked about like a confirmed bookmark; with
    /// the question switched off, or a backend that cannot take the save, nothing is asked.
    @MainActor
    func testANoticedSaveIsStoredThenAskedAboutUnderItsOwnSource() async {
        let item = SiteSaveItem(site: "x", origin: "x-bookmarks", url: "https://x.com/alpha_user/status/19",
                                title: "Post by @alpha_user")
        func center(enabled: Bool, api: SiteSaveFakeAPI) -> SaveWhyCenter {
            let defaults = UserDefaults(suiteName: "site-save-tests-\(UUID().uuidString)")!
            var prefs = SaveWhyPrefs(defaults: defaults)
            prefs.enabled = enabled
            return SaveWhyCenter(prefs: prefs, api: api)
        }
        let api = SiteSaveFakeAPI()
        let asked = center(enabled: true, api: api)
        await asked.siteSaved(item)
        XCTAssertEqual(asked.state?.item?.url, item.url)
        XCTAssertEqual(asked.state?.channel, "x-bookmarks")
        XCTAssertTrue(asked.confirmed)
        let saved = await api.saved
        XCTAssertEqual(saved, ["x https://x.com/alpha_user/status/19"])

        let offAPI = SiteSaveFakeAPI()
        let off = center(enabled: false, api: offAPI)
        await off.siteSaved(item)
        XCTAssertNil(off.state)
        let none = await offAPI.saved
        XCTAssertEqual(none, [])

        let refusing = SiteSaveFakeAPI()
        await refusing.refuse()
        let unasked = center(enabled: true, api: refusing)
        await unasked.siteSaved(item)
        XCTAssertNil(unasked.state)
    }

    func testTheObserveModeNeedsItsKeyAndADeveloperBuild() {
        let defaults = UserDefaults(suiteName: "site-save-tests-\(UUID().uuidString)")!
        XCTAssertFalse(SiteSaveObserve.isAvailable(defaults: defaults))
    }
}

private actor SiteSaveFakeAPI: SavedWhyAPI {
    var saved: [String] = []
    var refusing = false
    func refuse() { refusing = true }

    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        BookmarkSyncResult(new: 0, skipped: 0, sources: [])
    }
    func savedWhyOptions() async throws -> SavedWhyOptions { SavedWhyOptions() }
    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws {}
    func saveSiteItem(site: String, url: String) async throws -> SiteSaveReply {
        if refusing { throw APIError.httpError(409, "Sleep is updating your memory") }
        saved.append("\(site) \(url)")
        return SiteSaveReply(status: "created", url: url, title: "Post by @alpha_user", origin: "x-bookmarks",
                             episodeId: "ep_2027-01-15_001", addedAt: ISO8601DateFormatter().string(from: Date()))
    }
}
