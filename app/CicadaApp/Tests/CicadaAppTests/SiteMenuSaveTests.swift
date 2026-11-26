import XCTest
@testable import CicadaApp

/// G221 — a save a site keeps in a menu (Reddit's post menu, YouTube's sheet of lists): the pure rule, on readings
/// shaped as measured on the live sites 2026-11-23. Labels are in several languages on purpose: none is matched.
final class SiteMenuSaveTests: XCTestCase {
    private let post = "https://www.reddit.com/r/alpha_sub/comments/1abc234/a_synthetic_post/"
    private let english = ["Follow post", "Award this post", "Save", "Hide", "Report"]
    private let spanish = ["Seguir publicación", "Guardar", "Ocultar", "Denunciar"]

    private func reddit(_ items: [String], clicked: Int, key: String = "1abc234", links: [String]? = nil,
                        page: String = "https://www.reddit.com/", fits: Bool = true, foreign: Bool = false,
                        firstMarked: Int? = nil)
    -> SiteMenuReading {
        SiteMenuReading(site: "reddit", items: items, clicked: clicked, page: page, fits: fits, foreign: foreign,
                        blockKey: key, links: links ?? [post], linkLabels: ["A synthetic post"],
                        firstMarked: firstMarked)
    }

    private func sheet(_ items: [String], clicked: Int, page: String = "https://www.youtube.com/watch?v=AbCdEfGhIjK")
    -> SiteMenuReading {
        SiteMenuReading(site: "youtube", items: items, clicked: clicked, page: page)
    }

    // MARK: - Which item, which post

    func testOnRedditTheSaveIsTheThirdItemFromTheEndInAnyLanguage() throws {
        let found = try SiteMenuRule.item(reddit(english, clicked: 2)).get()
        XCTAssertEqual(found.item, SiteSaveItem(site: "reddit", origin: "reddit-saved", url: post.dropLast() + "",
                                                title: "Post in r/alpha_sub"))
        XCTAssertEqual(found.text, "A synthetic post")
        XCTAssertNil(found.folder)
        // The four-item menu (no award), in another language.
        XCTAssertNoThrow(try SiteMenuRule.item(reddit(spanish, clicked: 1)).get())
        // Every other item, and a menu of a size this does not know (the person's own post, a comment's three).
        for other in [0, 1, 3, 4] {
            XCTAssertEqual(SiteMenuRule.item(reddit(english, clicked: other)).failure, .notTheSaveSlot)
        }
        XCTAssertEqual(SiteMenuRule.item(reddit(english + ["Delete", "Edit"], clicked: 4)).failure, .notTheSaveSlot)
        XCTAssertEqual(SiteMenuRule.item(reddit(["Follow comment", "Report", "Save"], clicked: 0)).failure, .notTheSaveSlot)
    }

    func testThePostIsTheOneWhoseLinkCarriesTheBlocksOwnId() throws {
        // A post that links another post inside its block: only the link with the block's id names it.
        let other = "https://www.reddit.com/r/beta_sub/comments/9zzz999/another_post/"
        let found = try SiteMenuRule.item(reddit(english, clicked: 2, links: [other, post])).get()
        XCTAssertTrue(found.item.url.contains("/comments/1abc234/"))
        // On the post's own page the block holds no link to itself: the page is the post.
        let own = try SiteMenuRule.item(reddit(english, clicked: 2, links: [other], page: post)).get()
        XCTAssertTrue(own.item.url.contains("/comments/1abc234/"))
        // No link and no page with the id: no answer, never the other post.
        XCTAssertEqual(SiteMenuRule.item(reddit(english, clicked: 2, links: [other])).failure, .noPostLink)
    }

    func testAMenuThatIsNotThePostsOwnIsRefused() {
        XCTAssertEqual(SiteMenuRule.item(reddit(english, clicked: 2, foreign: true)).failure, .notTheSaveSlot)
        XCTAssertEqual(SiteMenuRule.item(reddit(english, clicked: 2, fits: false)).failure, .notTheSaveSlot)
        // A site the person did not connect.
        XCTAssertEqual(SiteMenuRule.item(reddit(english, clicked: 2), sites: [.youtube]).failure, .unknownSite)
    }

    func testOnYouTubeEveryItemIsAListAndTheVideoIsWhereTheSheetWasOpenedFrom() throws {
        let items = ["Watch later, Private, Not selected", "Alpha, tutorials, Private, Not selected",
                     "Beta, Unlisted, Not selected"]
        let own = try SiteMenuRule.item(sheet(items, clicked: 0), opener: .page).get()
        XCTAssertEqual(own.item.url, "https://www.youtube.com/watch?v=AbCdEfGhIjK")
        XCTAssertNil(own.folder, "the first list is the site's own")
        let card = try SiteMenuRule.item(sheet(items, clicked: 1),
                                         opener: .card("https://www.youtube.com/watch?v=ZyXwVuTsRqP&pp=abc")).get()
        XCTAssertEqual(card.item.url, "https://www.youtube.com/watch?v=ZyXwVuTsRqP")
        XCTAssertEqual(card.folder, "Alpha, tutorials", "a list's own name may hold a comma")
        // Opened from somewhere this does not know, or from a page that is not a video: no answer.
        XCTAssertEqual(SiteMenuRule.item(sheet(items, clicked: 0), opener: .other).failure, .noPostLink)
        XCTAssertEqual(SiteMenuRule.item(sheet(items, clicked: 0), opener: nil).failure, .noPostLink)
        XCTAssertEqual(SiteMenuRule.item(sheet(items, clicked: 0, page: "https://www.youtube.com/"), opener: .page).failure,
                       .noPostLink)
    }

    /// Measured 2026-11-25: a Short's "more" menu holds the item that opens the same sheet, and the address is the
    /// Short's own. Opened from the Short's own controls, the sheet files that Short, under the video's one link.
    func testOnAShortTheSheetFilesTheShortItself() throws {
        let items = ["Watch later, Private, Not selected", "Alpha, Private, Not selected", "Beta, Unlisted, Not selected"]
        let short = sheet(items, clicked: 1, page: "https://www.youtube.com/shorts/AbCdEfGhIjK")
        let found = try SiteMenuRule.item(short, opener: .page).get()
        XCTAssertEqual(found.item.url, "https://www.youtube.com/watch?v=AbCdEfGhIjK")
        XCTAssertEqual(found.folder, "Alpha")
        XCTAssertTrue(SiteSaveSite.youtube.menu?.pageClasses.contains("ytdReelVideoRendererHost") == true,
                      "a Short's own controls are the page's")
    }

    // MARK: - Which way

    func testInASheetTheOtherListsSayWhichWayInAnyLanguage() {
        let site = SiteSaveSite.youtube
        let japanese = ["後で見る、非公開、未選択", "アルファ、非公開、未選択", "ベータ、限定公開、未選択", "ガンマ、非公開、選択済み"]
        let saving = SiteMenuRule.outcome(sheet(japanese, clicked: 0), site: site, post: "p")
        XCTAssertEqual(saving, .init(outcome: .saved, basis: "sheet", unsaved: "未選択"))
        let leaving = SiteMenuRule.outcome(sheet(japanese, clicked: 3), site: site, post: "p")
        XCTAssertEqual(leaving, .init(outcome: .unsaved, basis: "sheet", saved: "選択済み", unsaved: "未選択"))
        // One list only, nothing learned: no evidence, nothing asked.
        XCTAssertEqual(SiteMenuRule.outcome(sheet(["Watch later, Private, Not selected"], clicked: 0), site: site,
                                            post: "p").outcome, .changed)
        // What a sheet taught is enough the next time.
        var learned = SiteSaveRule.Labels()
        learned.unsaved.insert("Not selected")
        XCTAssertEqual(SiteMenuRule.outcome(sheet(["Watch later, Private, Not selected"], clicked: 0), site: site,
                                            post: "p", learned: learned), .init(outcome: .saved, basis: "learned"))
    }

    /// Measured 2026-11-25 on the home feed: a recommended post's menu is longer, and the save was read as nothing.
    func testOnRedditTheSaveIsTwoBeforeTheFirstMirroredIconWhateverTheMenusLength() throws {
        let recommended = ["Follow post", "Award this post", "Show fewer posts like this", "Save", "Hide",
                           "Why was I recommended this?", "Report"]
        // Without the mark the seven-item menu is a layout this does not know.
        XCTAssertEqual(SiteMenuRule.item(reddit(recommended, clicked: 3)).failure, .notTheSaveSlot)
        XCTAssertNoThrow(try SiteMenuRule.item(reddit(recommended, clicked: 3, firstMarked: 5)).get())
        for other in [0, 1, 2, 4, 5, 6] {
            XCTAssertEqual(SiteMenuRule.item(reddit(recommended, clicked: other, firstMarked: 5)).failure, .notTheSaveSlot)
        }
        // The same mark places it in the short menus, in any language, with or without the award item.
        XCTAssertNoThrow(try SiteMenuRule.item(reddit(english, clicked: 2, firstMarked: 4)).get())
        XCTAssertNoThrow(try SiteMenuRule.item(reddit(spanish, clicked: 1, firstMarked: 3)).get())
        XCTAssertEqual(SiteMenuRule.item(reddit(spanish, clicked: 2, firstMarked: 3)).failure, .notTheSaveSlot)
        // A mark too early to have a save two places before it, or a menu too long to trust, is nothing.
        XCTAssertEqual(SiteMenuRule.item(reddit(english, clicked: 0, firstMarked: 1)).failure, .notTheSaveSlot)
        let long = recommended + ["Extra a", "Extra b"]
        XCTAssertEqual(SiteMenuRule.item(reddit(long, clicked: 3, firstMarked: 5)).failure, .notTheSaveSlot)
    }

    /// Measured 2026-11-25 on the person's own post: ten items, the save third, none of the marks the other layouts
    /// have. What the ordinary menus taught this Mac names it there.
    func testInAMenuOfAnUnknownLayoutTheSaveIsTheItemThisMacLearned() throws {
        let own = ["Award this post", "Edit post body", "Save", "Pin Post To Profile", "Hide", "Delete",
                   "Add spoiler tag", "Add NSFW tag", "Mark as brand affiliate", "Turn off reply notifications"]
        // Nothing learned: an unknown layout is nothing, as before.
        XCTAssertEqual(SiteMenuRule.item(reddit(own, clicked: 2)).failure, .notTheSaveSlot)
        var learned = SiteSaveRule.Labels()
        learned.unsaved.insert("Save")
        learned.saved.insert("Remove from saved")
        XCTAssertNoThrow(try SiteMenuRule.item(reddit(own, clicked: 2), learned: learned).get())
        var saved = own
        saved[2] = "Remove from saved"
        XCTAssertNoThrow(try SiteMenuRule.item(reddit(saved, clicked: 2), learned: learned).get())
        // Every other item of that menu is still nothing, and so is the label in another language until learned.
        for other in [0, 1, 3, 4, 5, 9] {
            XCTAssertEqual(SiteMenuRule.item(reddit(own, clicked: other), learned: learned).failure, .notTheSaveSlot)
        }
        var spanishOwn = own
        spanishOwn[2] = "Guardar"
        XCTAssertEqual(SiteMenuRule.item(reddit(spanishOwn, clicked: 2), learned: learned).failure, .notTheSaveSlot)
        // A comment's menu and a menu outside a post stay out, whatever their items are called.
        XCTAssertEqual(SiteMenuRule.item(reddit(own, clicked: 2, foreign: true), learned: learned).failure,
                       .notTheSaveSlot)
        XCTAssertEqual(SiteMenuRule.item(reddit(own, clicked: 2, fits: false), learned: learned).failure, .notTheSaveSlot)
        // Its direction is the learned one too.
        let verdict = SiteMenuRule.outcome(reddit(own, clicked: 2), site: .reddit, post: "p", learned: learned)
        XCTAssertEqual(verdict, .init(outcome: .saved, basis: "learned"))
    }

    func testAMenusLabelIsLearnedFromThePostsItWasClickedOn() {
        let site = SiteSaveSite.reddit
        var seen = SiteMenuRule.Seen(), learned = SiteSaveRule.Labels()
        func click(_ label: String, on post: String, page: String = "https://www.reddit.com/") -> SiteMenuRule.Verdict {
            var items = spanish
            items[1] = label
            let reading = reddit(items, clicked: 1, page: page)
            let item = SiteSaveItem(site: "reddit", origin: "reddit-saved", url: post, title: "")
            let settled = SiteSaveWatcher.settle(reading, item: item, site: site, learned: learned, seen: seen)
            seen = settled.seen
            if let label = settled.verdict.saved { learned.saved.insert(label) }
            if let label = settled.verdict.unsaved { learned.unsaved.insert(label) }
            return settled.verdict
        }
        // The first click on a Mac that has seen nothing: no evidence, nothing asked.
        XCTAssertEqual(click("Guardar", on: "a").outcome, .changed)
        // The same label on a second post: most posts are not saved, so this is the "not saved" label.
        XCTAssertEqual(click("Guardar", on: "b"), .init(outcome: .saved, basis: "seen", unsaved: "Guardar"))
        XCTAssertEqual(click("Guardar", on: "c"), .init(outcome: .saved, basis: "learned"))
        // A post seen wearing that label wears another now: it was saved since, and this click takes it off.
        XCTAssertEqual(click("Quitar de guardados", on: "b"),
                       .init(outcome: .unsaved, basis: "flip", saved: "Quitar de guardados"))
        XCTAssertEqual(click("Quitar de guardados", on: "z"), .init(outcome: .unsaved, basis: "learned"))
        // On the person's own saved list a click is leaving it, whatever the label.
        XCTAssertEqual(click("Unknown", on: "q", page: "https://www.reddit.com/user/alpha_user/saved/").outcome, .unsaved)
    }

    func testTwoLabelsSeenEquallyOftenSayNothing() {
        var seen = SiteMenuRule.Seen()
        seen.note(label: "A", post: "1")
        seen.note(label: "A", post: "2")
        XCTAssertEqual(seen.common, "A")
        seen.note(label: "B", post: "3")
        seen.note(label: "B", post: "4")
        XCTAssertNil(seen.common)
        // The same post twice is one post; only a few posts are kept per label.
        seen.note(label: "A", post: "2")
        XCTAssertNil(seen.common)
        for post in 5...12 { seen.note(label: "A", post: String(post)) }
        XCTAssertEqual(seen.posts["A"]?.count, SiteMenuRule.Seen.perLabel)
        XCTAssertEqual(SiteMenuRule.postKey("https://example.com/a").count, 12)
    }

    func testARestsReadingOfAMenuIsUsedOnlyForAClickInTheSameRowWhileFresh() {
        var reading = sheet(["Watch later, Private, Not selected"], clicked: 0)
        reading.frame = CGRect(x: 1013, y: 617, width: 212, height: 34)
        let hover = SiteSaveWatcher.MenuHover(reading: reading, at: 100)
        XCTAssertNotNil(SiteSaveWatcher.usable(hover, at: CGPoint(x: 1100, y: 630), now: 101))
        // The row is wider than the item's own frame (measured on YouTube): a click on its icon still counts.
        XCTAssertNotNil(SiteSaveWatcher.usable(hover, at: CGPoint(x: 970, y: 630), now: 101))
        XCTAssertNil(SiteSaveWatcher.usable(hover, at: CGPoint(x: 1100, y: 660), now: 101), "the next row")
        XCTAssertNil(SiteSaveWatcher.usable(hover, at: CGPoint(x: 1100, y: 630), now: 100 + SiteSaveWatcher.menuFresh + 1))
    }

    func testThisMacRemembersWhatAMenuWore() {
        let prefs = SiteSavePrefs(defaults: TestDefaults.suite("SiteMenuSaveTests.\(UUID().uuidString)")!)
        var seen = SiteMenuRule.Seen()
        seen.note(label: "Save", post: "a")
        prefs.setSeen("reddit", seen)
        XCTAssertEqual(prefs.seen("reddit"), seen)
        XCTAssertEqual(prefs.seen("youtube"), SiteMenuRule.Seen())
        prefs.teach("reddit", saved: nil, unsaved: "Save")
        XCTAssertEqual(prefs.labels("reddit").unsaved, ["Save"])
        XCTAssertTrue(prefs.labels("youtube").unsaved.isEmpty)
    }

    // MARK: - LinkedIn: the first item of a post's menu, the post named by its words (ruling 77e)

    /// As measured on the feed 2026-11-26: seven or eight items, the save first; the block's id is a token of the page.
    private let feedMenu = ["Guardar", "Copiar enlace", "Insertar", "Dejar de seguir", "No me interesa", "Parece IA",
                            "Denunciar"]
    private let shown = """
        Carol Example likes this
        Alice Example
        Staff engineer at alpha-project
        We rebuilt the sync engine around an append-only log, and three things surprised us.
        """

    private func linkedin(_ items: [String], clicked: Int, key: String = "bvJhbBM_CurSfX8-zOJ", words: String? = nil,
                          page: String = "https://www.linkedin.com/feed/", fits: Bool = true) -> SiteMenuReading {
        SiteMenuReading(site: "linkedin", items: items, clicked: clicked, page: page, fits: fits, blockKey: key,
                        words: words ?? shown)
    }

    func testOnLinkedInTheSaveIsTheMenusFirstItemAndTheFeedsPostIsNamedByItsWords() throws {
        let found = try SiteMenuRule.item(linkedin(feedMenu, clicked: 0)).get()
        XCTAssertTrue(found.item.byWords, "the feed gives the post no link")
        XCTAssertEqual(found.item, SiteSaveItem(site: "linkedin", origin: "linkedin-saved", url: "",
                                                title: "LinkedIn post"))
        XCTAssertEqual(found.text, shown)
        XCTAssertNoThrow(try SiteMenuRule.item(linkedin(feedMenu + ["Ocultar"], clicked: 0)).get(), "eight items")
        // Every other item, and a menu that is not a post's (a comment's three items, an ad's two).
        for other in 1..<feedMenu.count {
            XCTAssertEqual(SiteMenuRule.item(linkedin(feedMenu, clicked: other)).failure, .notTheSaveSlot)
        }
        XCTAssertEqual(SiteMenuRule.item(linkedin(["Copiar enlace", "Denunciar", "Eliminar"], clicked: 0)).failure,
                       .notTheSaveSlot)
        XCTAssertEqual(SiteMenuRule.item(linkedin(["Ocultar anuncio", "Por qué"], clicked: 0)).failure, .notTheSaveSlot)
        // A block that shows too little to tell the post from another, or no block at all: nothing is said.
        XCTAssertEqual(SiteMenuRule.item(linkedin(feedMenu, clicked: 0, words: "Alice Example\n3d")).failure, .noPostLink)
        XCTAssertEqual(SiteMenuRule.item(linkedin(feedMenu, clicked: 0, key: "")).failure, .noPostLink)
        XCTAssertEqual(SiteMenuRule.item(linkedin(feedMenu, clicked: 0, fits: false)).failure, .notTheSaveSlot)
    }

    func testOnALinkedInPostsOwnPageTheAddressIsThePost() throws {
        let page = "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/?utm=x"
        let found = try SiteMenuRule.item(linkedin(feedMenu, clicked: 0, words: "", page: page)).get()
        XCTAssertEqual(found.item.url, "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/")
        XCTAssertFalse(found.item.byWords)
        XCTAssertEqual(SiteSaveSite.linkedin.item("https://www.linkedin.com/posts/alice-example_sync-activity-7000000000000000001-AbCd")?.url,
                       "https://www.linkedin.com/posts/alice-example_sync-activity-7000000000000000001-AbCd/")
        XCTAssertNil(SiteSaveSite.linkedin.item("https://www.linkedin.com/in/alice-example/"))
        XCTAssertNil(SiteSaveSite.linkedin.item("https://www.linkedin.com/feed/"))
        XCTAssertTrue(SiteSaveSite.linkedin.isListPage("https://www.linkedin.com/my-items/saved-posts/"))
    }

    /// The item wears one of two labels and nothing else on the page says which way a click went: the record decides,
    /// and no label is learned from a click (a wrong lesson would silence every later save).
    func testOnLinkedInTheRecordDecidesTheDirectionAndNothingIsLearned() throws {
        let reading = linkedin(feedMenu, clicked: 0)
        let item = try SiteMenuRule.item(reading).get().item
        var seen = SiteMenuRule.Seen()
        for _ in 0..<4 {
            let settled = SiteSaveWatcher.settle(reading, item: item, site: .linkedin,
                                                 learned: .init(saved: ["Guardar"], unsaved: ["Guardar"]), seen: seen)
            XCTAssertEqual(settled.verdict, SiteMenuRule.Verdict(outcome: .changed, basis: "none"))
            seen = settled.seen
        }
        XCTAssertEqual(seen, SiteMenuRule.Seen())
        XCTAssertTrue(SiteMenuRule.names(shown))
        XCTAssertFalse(SiteMenuRule.names("Alice Example · 3d · 42"))
    }

    func testTheNewSitesAreOfferedAndStoredUnderTheirOwnSource() {
        XCTAssertEqual(SiteSaveSite.all.map(\.key), ["x", "instagram", "github", "tiktok", "reddit", "youtube",
                                                    "pinterest", "spotify", "linkedin"])
        XCTAssertNotNil(SiteSaveSite.youtube.item("https://www.youtube.com/shorts/AbCdEfGhIjK"))
        XCTAssertNil(SiteSaveSite.youtube.item("https://www.youtube.com/@alpha"))
        XCTAssertNil(SiteSaveSite.reddit.item("https://www.reddit.com/r/alpha_sub/comments/1abc234/a_post/k9x8y7z/"),
                     "a comment's own link is not a post")
        // Neither site has a save button in a row: a row of buttons there is never a save.
        let row = SiteSaveReading(row: (0..<5).map { _ in SiteSaveNode(role: "AXButton") }, clicked: 4,
                                  page: "https://www.youtube.com/watch?v=AbCdEfGhIjK")
        XCTAssertEqual(SiteSaveRule.item(row).failure, .notTheSaveSlot)
    }
}

private extension Result {
    var failure: Failure? { if case let .failure(why) = self { return why }; return nil }
}
