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

    // MARK: - The other sites: the same rule, another place in the row

    func testOnInstagramTheSaveControlIsTheLastButtonAndThePostIsTheBlocksOwnLink() throws {
        // like, its count, comment, its count, share, its count, save: every one a plain button.
        var feed = SiteSaveReading(row: (0..<7).map { button("b\($0)") }, clicked: 6, page: "https://www.instagram.com/",
                                   links: ["https://www.instagram.com/p/AbCdEfGhIjK/",
                                           "https://www.instagram.com/reels/AbCdEfGhIjK/"], linksBefore: 2)
        XCTAssertEqual(try SiteSaveRule.item(feed).get(),
                       SiteSaveItem(site: "instagram", origin: "instagram-saved",
                                    url: "https://www.instagram.com/p/AbCdEfGhIjK/", title: "Instagram post"))
        feed.clicked = 0                                    // the like
        XCTAssertEqual(SiteSaveRule.item(feed), .failure(.notTheSaveSlot))
        feed.clicked = 6
        // The nearest link before the row names the post, whatever follows it (the next post's head, a quoted post).
        feed.links = ["https://www.instagram.com/reel/ZyXwVuTsRqP/", "https://www.instagram.com/p/AbCdEfGhIjK/"]
        feed.linksBefore = 1
        XCTAssertEqual(try SiteSaveRule.item(feed).get().url, "https://www.instagram.com/p/ZyXwVuTsRqP/")
        // Links only after the row are another block's (the stories tray above the first post): no answer.
        feed.linksBefore = 0
        XCTAssertEqual(SiteSaveRule.item(feed), .failure(.twoPosts))
        // A post's own page names the post when the block holds no link.
        let own = SiteSaveReading(row: (0..<7).map { button("b\($0)") }, clicked: 6,
                                  page: "https://www.instagram.com/alpha_user/reel/ZyXwVuTsRqP/")
        XCTAssertEqual(try SiteSaveRule.item(own).get().url, "https://www.instagram.com/p/ZyXwVuTsRqP/")
    }

    func testOnGitHubTheStarIsTheButtonBeforeItsListsMenuOnAListAndOnARepositorysPage() throws {
        let list = SiteSaveReading(row: [link("https://github.com/sponsors/alpha"), button("s"), menu("lists"),
                                         link("https://github.com/alpha-org/alpha-project"),
                                         link("https://github.com/alpha-org/alpha-project/stargazers")],
                                   clicked: 1, page: "https://github.com/trending")
        XCTAssertEqual(try SiteSaveRule.item(list).get(),
                       SiteSaveItem(site: "github", origin: "github-starred",
                                    url: "https://github.com/alpha-org/alpha-project", title: "alpha-org/alpha-project"))
        let page = SiteSaveReading(row: [menu("watch"), link("https://github.com/alpha-org/alpha-project/fork"),
                                         menu("forks"), button("s"), menu("lists")],
                                   clicked: 3, page: "https://github.com/alpha-org/alpha-project/tree/main")
        XCTAssertEqual(SiteSaveRule.item(page), .failure(.noPostLink))   // a file view is not the repository's page
        var home = page
        home.page = "https://github.com/alpha-org/alpha-project"
        XCTAssertEqual(try SiteSaveRule.item(home).get().url, "https://github.com/alpha-org/alpha-project")
        // GitHub's own sections are never an account.
        XCTAssertNil(SiteSaveSite.github.item("https://github.com/sponsors/alpha"))
        XCTAssertNil(SiteSaveSite.github.item("https://github.com/stars/alpha"))
    }

    func testOnTikTokTheFavouriteIsTheButtonBeforeTheLast() throws {
        let video = SiteSaveReading(row: [button("like"), button("comments"), button("fav 4256"), button("share")],
                                    clicked: 2, page: "https://www.tiktok.com/@alpha.user/video/7300000000000000001")
        XCTAssertEqual(try SiteSaveRule.item(video).get().url,
                       "https://www.tiktok.com/@alpha.user/video/7300000000000000001")
        var share = video
        share.clicked = 3
        XCTAssertEqual(SiteSaveRule.item(share), .failure(.notTheSaveSlot))
    }

    /// Measured 2026-11-25 with real clicks and the reader: a video opened from a profile's grid shows its controls as
    /// comments, favourite, five share links, Share, Copy link (the like is a checkbox), each count alone as the label.
    /// The old place (before the last button) named Share as the save control and the favourite as nothing.
    func testInTheViewerAProfileOpensTheFavouriteIsTheCountedButtonBeforeTheShareLinks() throws {
        let page = "https://www.tiktok.com/@alpha.user/video/7300000000000000002"
        let shared = SiteSaveNode(role: "AXLink", label: "Repost", url: page)
        let elsewhere = SiteSaveNode(role: "AXLink", label: "Send", url: "https://wa.me/?text=x")
        let row = [button("31"), button("604"), shared, shared, shared, elsewhere, elsewhere, button("Share"),
                   button("Copy link")]
        let viewer = SiteSaveReading(row: row, clicked: 1, page: page)
        XCTAssertEqual(try SiteSaveRule.item(viewer).get().url, page)
        for other in [0, 7, 8] {
            var reading = viewer
            reading.clicked = other
            XCTAssertEqual(SiteSaveRule.item(reading), .failure(.notTheSaveSlot), "button \(other)")
        }
        // Its count moving by one says which way, as on the video's own page.
        var saved = viewer
        saved.row[1].label = "605"
        XCTAssertEqual(SiteSaveRule.outcome(before: viewer, after: saved, site: .tiktok), .saved)
        XCTAssertEqual(SiteSaveRule.outcome(before: saved, after: viewer, site: .tiktok), .unsaved)
        // The player's own row (two buttons, volume, full screen) holds no favourite: nothing in it counts anything.
        let player = SiteSaveReading(row: [button("Play"), button("Next"), button("Volume"), button("Full screen")],
                                     clicked: 2, page: page)
        XCTAssertEqual(SiteSaveRule.item(player), .failure(.notTheSaveSlot))
    }

    func testOnlyTheSitesHandedToTheRuleAreRead() {
        let feed = timeline(save: "b", counts: "")
        XCTAssertEqual(SiteSaveRule.item(feed, sites: [.instagram]), .failure(.unknownSite))
        XCTAssertNotNil(try? SiteSaveRule.item(feed, sites: [.x]).get())
    }

    // MARK: - Which way a change went

    func testOnThePersonsOwnSavedListAToggleIsLeavingIt() {
        var before = timeline(save: "on", counts: "")
        var after = timeline(save: "off", counts: "")
        before.page = "https://x.com/i/bookmarks"
        after.page = "https://x.com/i/history"
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after, site: .x), .unsaved)
        XCTAssertTrue(SiteSaveSite.instagram.isListPage("https://www.instagram.com/alpha_user/saved/all-posts/"))
        XCTAssertTrue(SiteSaveSite.github.isListPage("https://github.com/stars"))
        XCTAssertFalse(SiteSaveSite.x.isListPage("https://x.com/home"))
    }

    func testWithNoCountTheOtherPostsOnThePageSayWhichWay() {
        let before = timeline(save: "Guardar", counts: ""), after = timeline(save: "Quitar", counts: "")
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after), .changed)
        // Three other posts still wear the label it left, none the one it took: it joined the saved list.
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after, census: .init(was: 3, now: 0)), .saved)
        XCTAssertEqual(SiteSaveRule.outcome(before: after, after: before, census: .init(was: 0, now: 3)), .unsaved)
        // A page where both labels are worn, or too few posts, says nothing.
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after, census: .init(was: 3, now: 1)), .changed)
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after, census: .init(was: 1, now: 0)), .changed)
    }

    /// Found 2026-11-25 on a post's own page on X: the control names its count and the row's label names it again, so
    /// two counts moved and the click was read as "changed", with nobody asked.
    func testOnAPostsOwnPageTheControlsOwnCountSaysWhichWay() {
        let before = ownPage(save: "1,204 Bookmarks. Bookmark",
                             counts: "20 replies, 184 reposts, 3,512 likes, 1,204 bookmarks, 252,118 views")
        let after = ownPage(save: "1,205 Bookmarks. Bookmarked",
                            counts: "20 replies, 184 reposts, 3,512 likes, 1,205 bookmarks, 252,119 views")
        XCTAssertNil(SiteSaveRule.step(before: SiteSaveRule.counts(before), after: SiteSaveRule.counts(after)))
        XCTAssertEqual(SiteSaveRule.countStep(before: before, after: after), 1)
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after, site: .x), .saved)
        XCTAssertEqual(SiteSaveRule.outcome(before: after, after: before, site: .x), .unsaved)
        // A control with no count of its own still goes by the row's.
        XCTAssertEqual(SiteSaveRule.countStep(before: timeline(save: "a", counts: "5"),
                                              after: timeline(save: "b", counts: "6")), 1)
    }

    func testAControlThatNamesARoundedCountIsKnownByItsTail() {
        let before = ownPage(save: "11.4K Bookmarks. Bookmark", counts: "11.4K bookmarks")
        let after = ownPage(save: "11.4K Bookmarks. Bookmarked", counts: "11.4K bookmarks")
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after, site: .x), .changed)
        // What the timeline taught (the bare labels) settles it, both ways.
        var labels = SiteSaveRule.Labels()
        labels.learn(was: "Bookmark", now: "Bookmarked", outcome: .saved)
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after, site: .x, learned: labels), .saved)
        XCTAssertEqual(SiteSaveRule.outcome(before: after, after: before, site: .x, learned: labels), .unsaved)
        // The core is the two labels without the lead they share, in any language, and a moved count does not end it.
        XCTAssertEqual(SiteSaveRule.core(was: "11.4K Bookmarks. Bookmark", now: "11.4K Bookmarks. Bookmarked")?.now,
                       "Bookmarked")
        XCTAssertEqual(SiteSaveRule.core(was: "1,204 guardados. Guardar", now: "1,205 guardados. Quitar")?.was, "Guardar")
        XCTAssertEqual(SiteSaveRule.core(was: "1.2万件。保存", now: "1.2万件。削除")?.now, "削除")
        XCTAssertNil(SiteSaveRule.core(was: "Bookmark", now: "Bookmarked"))
        XCTAssertNil(SiteSaveRule.core(was: "Guardar", now: "Quitar"))
    }

    /// Measured 2026-11-25 (labels and structure, no click): GitHub's repository page calls its control by the
    /// repository ("Star <owner>/<repo>") with no count, and its lists call it "Star this repository"; TikTok's names a
    /// count after the words, rounded on a popular video. What differs is the same on every page of a site.
    func testAControlNamedByWhatItIsAboutIsKnownByItsCore() {
        let star = SiteSaveRule.core(was: "Star alpha-org/alpha-repo", now: "Unstar alpha-org/alpha-repo")
        XCTAssertEqual(star?.was, "Star")
        XCTAssertEqual(star?.now, "Unstar")
        let list = SiteSaveRule.core(was: "Star this repository", now: "Starred, click to unstar this repository")
        XCTAssertEqual(list?.was, "Star")
        XCTAssertEqual(list?.now, "Starred, click to unstar")
        let rounded = SiteSaveRule.core(was: "Add to Favorites. 12.3K added to Favorites",
                                        now: "Remove from Favorites. 12.3K added to Favorites")
        XCTAssertEqual(rounded?.was, "Add to")
        XCTAssertEqual(rounded?.now, "Remove from")
        // The trail never reaches back into the lead: each label keeps something of its own.
        XCTAssertEqual(SiteSaveRule.core(was: "a a", now: "a b a")?.was, "a")
        XCTAssertEqual(SiteSaveRule.core(was: "a a", now: "a b a")?.now, "b a")

        // What a list taught settles the repository's own page, both ways, for any repository.
        var labels = SiteSaveRule.Labels()
        let lesson = SiteSaveRule.lesson(was: "Star this repository", now: "Starred, click to unstar this repository")
        labels.learn(was: lesson?.was ?? "", now: lesson?.now ?? "", outcome: .saved)
        XCTAssertEqual(labels.saysAny(was: "Star beta-org/beta-repo", now: "Unstar beta-org/beta-repo"), .saved)
        XCTAssertEqual(labels.saysAny(was: "Unstar beta-org/beta-repo", now: "Star beta-org/beta-repo"), .unsaved)
        XCTAssertEqual(labels.saysAny(was: "Star this repository", now: "Starred, click to unstar this repository"), .saved)
        // A site nothing was learned on still says nothing.
        XCTAssertNil(SiteSaveRule.Labels().saysAny(was: "Star beta-org/beta-repo", now: "Unstar beta-org/beta-repo"))
    }

    func testALabelThatNamesACountTeachesItsCoreOrNothing() {
        XCTAssertEqual(SiteSaveRule.lesson(was: "Bookmark", now: "Bookmarked")?.was, "Bookmark")
        let counted = SiteSaveRule.lesson(was: "1,204 Bookmarks. Bookmark", now: "1,205 Bookmarks. Bookmarked")
        XCTAssertEqual(counted?.was, "Bookmark")
        XCTAssertEqual(counted?.now, "Bookmarked")
        XCTAssertNil(SiteSaveRule.lesson(was: "fav 4256", now: "fav 4257"))
    }

    func testWhatACertainChangeTaughtIsUsedOnAPageWithNoOtherEvidence() {
        var labels = SiteSaveRule.Labels()
        labels.learn(was: "Guardar", now: "Quitar", outcome: .saved)
        let before = timeline(save: "Guardar", counts: ""), after = timeline(save: "Quitar", counts: "")
        XCTAssertEqual(SiteSaveRule.outcome(before: before, after: after, learned: labels), .saved)
        XCTAssertEqual(SiteSaveRule.outcome(before: after, after: before, learned: labels), .unsaved)
        // Another language's labels are unknown until that language teaches them.
        XCTAssertEqual(SiteSaveRule.outcome(before: timeline(save: "保存", counts: ""),
                                            after: timeline(save: "削除", counts: ""), learned: labels), .changed)
        // A count still wins over what was learned.
        XCTAssertEqual(SiteSaveRule.outcome(before: timeline(save: "Quitar", counts: "5"),
                                            after: timeline(save: "Guardar", counts: "4"), learned: labels), .unsaved)
    }

    func testThisMacRemembersConnectionsAndLabelsPerSite() {
        let prefs = SiteSavePrefs(defaults: TestDefaults.suite("SiteSaveTests.\(UUID().uuidString)")!)
        XCTAssertTrue(prefs.noticed(status: { _ in .off }).isEmpty)
        prefs.setConnected("x", true)
        XCTAssertEqual(prefs.noticed(status: { _ in .off }).map(\.key), ["x"])
        prefs.setConnected("x", false)
        XCTAssertTrue(prefs.noticed(status: { _ in .off }).isEmpty)
        prefs.learn("x", was: "a", now: "b", outcome: .saved)
        XCTAssertEqual(prefs.labels("x").says(was: "a", now: "b"), .saved)
        XCTAssertNil(prefs.labels("instagram").says(was: "a", now: "b"))
    }

    // MARK: - The connect offer for a site

    func testASitesYesStaysAMomentToSayWhatItDidThenClosesAsYes() {
        var panel = ConnectSuggestPanelState(target: ConnectSuggestApps.site("x"), appName: "X",
                                             bundleId: "com.google.Chrome", shownAt: 100)
        XCTAssertNil(panel.handle(.yes, at: 100.1), "a press inside the arm delay is the hand on its way elsewhere")
        XCTAssertNil(panel.handle(.yes, at: 102))
        XCTAssertEqual(panel.confirmedAt, 102)
        XCTAssertNil(panel.handle(.no, at: 102.2), "nothing is undone by a stray press while it says so")
        // It says "Turned on" only once what the Yes turned on has returned (it is never "Connected").
        XCTAssertNil(panel.finish(.turnedOn(asksWhy: true, needsAccessibility: false), at: 102.3))
        XCTAssertNil(panel.handle(.tick, at: 102.5))
        XCTAssertEqual(panel.handle(.tick, at: 102.4 + ConnectSuggestPolicy.confirmShow), .yes)
        // Leaving the browser while it says so keeps the yes.
        var leaving = ConnectSuggestPanelState(target: ConnectSuggestApps.site("x"), appName: "X",
                                               bundleId: "com.google.Chrome", shownAt: 100)
        _ = leaving.handle(.yes, at: 102)
        XCTAssertEqual(leaving.handle(.appChanged, at: 102.3), .yes)
        // An app's yes is the same plan: it says what it did, and a page it opened is the answer.
        var app = ConnectSuggestPanelState(target: .init(entryId: "notes", kind: .notes), appName: "Notes",
                                           bundleId: "com.apple.Notes", shownAt: 100)
        XCTAssertNil(app.handle(.yes, at: 102))
        XCTAssertEqual(app.finish(.openedPage, at: 102.1), .yes)
        XCTAssertEqual(ConnectSuggestApps.siteKey(entryId: ConnectSuggestApps.site("github").entryId), "github")
        XCTAssertNil(ConnectSuggestApps.siteKey(entryId: "notes"))
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

    /// A noticed save is stored under the site's own source first, then asked about like a confirmed bookmark, with
    /// the bookmark question's switch on or off (the site's own connection is its switch); with a backend that cannot
    /// take the save, nothing is asked.
    @MainActor
    func testANoticedSaveIsStoredThenAskedAboutUnderItsOwnSource() async {
        let item = SiteSaveItem(site: "x", origin: "x-bookmarks", url: "https://x.com/alpha_user/status/19",
                                title: "Post by @alpha_user")
        func center(enabled: Bool, api: SiteSaveFakeAPI) -> SaveWhyCenter {
            let defaults = TestDefaults.suite("SiteSaveTests.\(UUID().uuidString)")!
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

        // The bookmark question's switch is not the site's: connecting the site turned its question on.
        let offAPI = SiteSaveFakeAPI()
        let off = center(enabled: false, api: offAPI)
        await off.siteSaved(item)
        XCTAssertEqual(off.state?.item?.url, item.url)
        let stored = await offAPI.saved
        XCTAssertEqual(stored.count, 1)

        let refusing = SiteSaveFakeAPI()
        await refusing.refuse()
        let unasked = center(enabled: true, api: refusing)
        await unasked.siteSaved(item)
        XCTAssertNil(unasked.state)
    }

    /// A save made while Sleep held the pages used to vanish (the refusal was swallowed). It is held, stored when the
    /// backend can take it, and asked about only while the moment is still near; a stale one is stored and not asked.
    @MainActor
    func testASaveMadeWhileSleepWritesIsHeldStoredLaterAndAskedOnlyWhileFresh() async {
        let item = SiteSaveItem(site: "x", origin: "x-bookmarks", url: "https://x.com/alpha_user/status/19",
                                title: "Post by @alpha_user")
        let defaults = TestDefaults.suite("SiteSaveTests.\(UUID().uuidString)")!
        let api = SiteSaveFakeAPI()
        await api.refuse()
        var clock = Date()
        let center = SaveWhyCenter(prefs: SaveWhyPrefs(defaults: defaults), api: api, now: { clock })
        await center.siteSaved(item, text: "an idea")
        XCTAssertNil(center.state, "nothing is asked while nothing is stored")
        XCTAssertEqual(center.siteOutbox.entries.map(\.url), [item.url])
        // Still refused: it stays held.
        await center.retryHeld()
        XCTAssertEqual(center.siteOutbox.entries.count, 1)
        // Sleep let go, a minute later: stored, and asked, since the moment is near.
        await api.refuse(false)
        clock = clock.addingTimeInterval(60)
        await center.retryHeld()
        XCTAssertTrue(center.siteOutbox.entries.isEmpty)
        XCTAssertEqual(center.state?.item?.url, item.url)
        let stored = await api.saved
        XCTAssertEqual(stored, ["x https://x.com/alpha_user/status/19"])

        // A save held for an hour is stored but never asked about: the question is about the moment of saving.
        let late = SaveWhyCenter(prefs: SaveWhyPrefs(defaults: TestDefaults.suite("SiteSaveTests.\(UUID().uuidString)")!),
                                 api: api, now: { clock })
        await api.refuse()
        await late.siteSaved(item)
        await api.refuse(false)
        clock = clock.addingTimeInterval(3600)
        await late.retryHeld()
        XCTAssertTrue(late.siteOutbox.entries.isEmpty)
        XCTAssertNil(late.state)
        let storedLater = await api.saved
        XCTAssertEqual(storedLater.count, 2)

        // Taken off again before it landed: never stored.
        let off = SaveWhyCenter(prefs: SaveWhyPrefs(defaults: TestDefaults.suite("SiteSaveTests.\(UUID().uuidString)")!),
                                api: api, now: { clock })
        await api.refuse()
        await off.siteSaved(item)
        await off.siteUnsaved(item)
        XCTAssertTrue(off.siteOutbox.entries.isEmpty)
    }

    func testThePostsOwnWordsAreCutFromItsBlockWithoutKnowingASingleWord() {
        var reading = timeline(save: "b", counts: "20 respuestas, 184 Me gusta")
        reading.context = "Alpha Person Cuenta verificada @alpha_user hace 5 horas una idea para sincronizar réplicas 20 respuestas, 184 Me gusta"
        reading.linkLabel = "hace 5 horas"
        let item = SiteSaveItem(site: "x", origin: "x-bookmarks", url: "https://x.com/alpha_user/status/19",
                                title: "Post by @alpha_user")
        XCTAssertEqual(SiteSaveRule.text(of: reading, item: item), "una idea para sincronizar réplicas")
        reading.context = "a block that does not name the handle"
        XCTAssertEqual(SiteSaveRule.text(of: reading, item: item), "")
    }

}

private actor SiteSaveFakeAPI: SavedWhyAPI {
    var saved: [String] = []
    var refusing = false
    func refuse(_ on: Bool = true) { refusing = on }

    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        BookmarkSyncResult(new: 0, skipped: 0, sources: [])
    }
    func savedWhyOptions() async throws -> SavedWhyOptions { SavedWhyOptions() }
    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws {}
    func saveSiteItem(site: String, url: String, text: String, folder: String?) async throws -> SiteSaveReply {
        if refusing { throw APIError.httpError(409, "Sleep is updating your memory") }
        saved.append("\(site) \(url)")
        return SiteSaveReply(status: "created", url: url, title: "Post by @alpha_user", origin: "x-bookmarks",
                             episodeId: "ep_2027-01-15_001", addedAt: ISO8601DateFormatter().string(from: Date()))
    }
}
