import XCTest
@testable import CicadaApp

/// G245 (ruling 78, plan 3.2) — the source page's words and rules, pure: the head's quiet line, a Reads row's control
/// and trailing words, the tabs and folder menu, an item card's footer, the list key's stream suffix, and that no source
/// page carries an import action or the website-reading diagram.
@MainActor
final class SourcePageStreamsTests: XCTestCase {
    private let now = SourceStreamsFixture.now

    private func resolved(_ id: String, in source: String) throws -> ResolvedStream {
        let response = try SourceStreamsFixture.load()
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, hexPresent: false, overview: [], channels: [])
        let all = SourceStreamOverlay.resolve(response, app: StreamAppState(readers: ["notes": true]), entries: entries,
                                              now: now)
        return try XCTUnwrap(all.streams(source).first { $0.id == id }, id)
    }

    private func streams(_ source: String) throws -> [ResolvedStream] {
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, hexPresent: false, overview: [], channels: [])
        return SourceStreamOverlay.resolve(try SourceStreamsFixture.load(), app: StreamAppState(readers: ["notes": true]),
                                           entries: entries, now: now).streams(source)
    }

    // MARK: The head

    func testTheHeadsLineIsTheAccountAndHowItIsReadAndNeverAParagraph() throws {
        let line = SourceHeadLine.text(account: StreamAccount(handle: "alpha-account", profileUrl: nil),
                                       streams: try streams("x"), app: "Claude Code")
        XCTAssertEqual(line, "@alpha-account · Read in your browser by Claude Code, about once a day")
        XCTAssertEqual(SourceHeadLine.text(account: nil, streams: try streams("notes"), app: nil), "Read on this Mac")
        XCTAssertNil(SourceHeadLine.text(account: nil, streams: [], app: nil))
        XCTAssertTrue(try XCTUnwrap(SourceHeadLine.text(account: nil, streams: try streams("x"), app: nil))
            .contains("your AI app"), "no app connected here: the line names none")
    }

    func testTheBrowserFactsAreTheLinesHoverNotAStandingText() throws {
        let help = try XCTUnwrap(SourceHeadLine.help(entryId: "x", streams: try streams("x"), app: "Claude Code"))
        for fact in ["your own sign-in", "never sees your password", "Claude Code's company sees what it reads",
                     "Nothing is posted or changed", "To stop"] {
            XCTAssertTrue(help.contains(fact), fact)
        }
        XCTAssertNil(SourceHeadLine.help(entryId: "notes", streams: try streams("notes"), app: nil))
        XCTAssertEqual(SourceHeadLine.help(entryId: "github", streams: try streams("github"), app: nil), Copy.Honest.github)
    }

    // MARK: A Reads row

    func testAListStreamHasASwitchAndAStreamThatNeedsSetupHasNone() throws {
        XCTAssertEqual(SourceStreamRow.control(try resolved("x.bookmarks", in: "x")), .toggle(on: true))
        XCTAssertEqual(SourceStreamRow.control(try resolved("x.bookmarks", in: "x"), pending: false), .toggle(on: false),
                       "optimistic: the row shows the flip at once")
        XCTAssertEqual(SourceStreamRow.control(try resolved("x.saves", in: "x")), .toggle(on: false),
                       "Saves you make is flipped by the per-Mac flag")
        XCTAssertEqual(SourceStreamRow.control(try resolved("github.stars", in: "github")), .setup)
        XCTAssertEqual(SourceStreamRow.control(try resolved("notes.notes", in: "notes")), .setup,
                       "a Mac reader no PUT can flip shows its own connect step, never a switch that does nothing")
        XCTAssertEqual(SourceStreamRow.control(try resolved("imessage.chats", in: "imessage")), .setup)
    }

    func testARowSaysHowItIsReadAndHowDeepItGoes() throws {
        XCTAssertEqual(SourceStreamRow.line(try resolved("x.bookmarks", in: "x").stream),
                       "In your browser, by your AI app · kept and findable")
        XCTAssertEqual(SourceStreamRow.line(try resolved("notes.notes", in: "notes").stream),
                       "On this Mac · read by Sleep")
        XCTAssertEqual(SourceStreamRow.line(try resolved("imessage.chats", in: "imessage").stream),
                       "Messages needs Full Disk Access.", "an unavailable stream says why instead")
        let help = try XCTUnwrap(SourceStreamRow.help(try resolved("x.bookmarks", in: "x").stream))
        XCTAssertTrue(help.contains("Older ones come with the site's export"))
        XCTAssertTrue(help.contains("Unsaving on the site does not remove one here"))
        XCTAssertNil(SourceStreamRow.help(try resolved("notes.notes", in: "notes").stream))
    }

    func testTheTrailingWordsAreCountAndLastReadOrTheStateWord() throws {
        let read = SourceStreamRow.trailing(try resolved("x.bookmarks", in: "x"), result: nil, checking: false, now: now,
                                            locale: Locale(identifier: "en_US"))
        XCTAssertEqual(read.text, "214 · 3 hr. ago")
        XCTAssertNil(read.word)
        let signedOut = SourceStreamRow.trailing(try resolved("youtube.watch_later", in: "youtube"), result: nil,
                                                 checking: false, now: now, locale: Locale(identifier: "en_US"))
        XCTAssertEqual(signedOut.word, .signedOut)
        let off = SourceStreamRow.trailing(try resolved("youtube.history", in: "youtube"), result: nil, checking: false,
                                           now: now)
        XCTAssertNil(off.word, "an off stream's switch says it")
        XCTAssertEqual(SourceStreamRow.trailing(try resolved("x.bookmarks", in: "x"), result: nil, checking: true, now: now)
            .note, Copy.Streams.checking)
    }

    func testACheckAnswerStandsUntilTheStreamIsReadAgain() throws {
        let stream = try resolved("x.bookmarks", in: "x")
        let fresh = SourceStreamCheckModel.Result(streamId: stream.id, word: .yourAIAppReadsNext,
                                                  at: now, previous: .read)
        let shown = SourceStreamRow.trailing(stream, result: fresh, checking: false, now: now)
        XCTAssertEqual(shown.word, .yourAIAppReadsNext)
        XCTAssertEqual(shown.note, "last: read")
        let stale = SourceStreamCheckModel.Result(streamId: stream.id, word: .couldntRead,
                                                  at: now.addingTimeInterval(-86_400), previous: nil)
        XCTAssertNil(SourceStreamRow.trailing(stream, result: stale, checking: false, now: now).word,
                     "a read since the check is the fresher word")
    }

    // MARK: The items

    func testOnlyListStreamsThatHoldItemsAreTabbedAndHistoryKeepsItsOwnContent() throws {
        let x = try streams("x")
        XCTAssertEqual(SourceStreamItems.tabbed(x).map(\.id), ["x.bookmarks", "x.likes"])
        XCTAssertEqual(SourceStreamItems.tabs(x).map(\.label), [Copy.Streams.all, "Bookmarks", "Likes"])
        XCTAssertEqual(SourceStreamItems.tabbed(try streams("youtube")).map(\.id), ["youtube.watch_later"])
        XCTAssertTrue(SourceStreamItems.tabs(try streams("youtube")).isEmpty, "one list is the page's list: no tabs")
        XCTAssertFalse(SourceStreamItems.usesCards(try streams("notes")), "Notes keeps its own browser")
        XCTAssertFalse(SourceStreamItems.usesCards(try streams("github")))
        XCTAssertNil(SourceStreamItems.effective("x.unknown", streams: x))
    }

    func testTheFolderMenuIsOneStreamsAndOnlyWhenItKeepsFolders() throws {
        let x = try streams("x")
        XCTAssertNil(SourceStreamItems.folderStream(nil, streams: x), "All has no folder menu")
        XCTAssertEqual(SourceStreamItems.folderStream("x.bookmarks", streams: x)?.id, "x.bookmarks")
        XCTAssertNil(SourceStreamItems.folderStream("x.likes", streams: x), "Likes keeps no folder (folderCount 0)")
        var a = ChannelItem(kind: .media, id: "1", title: "a"); a.folders = ["Design", "Reading"]
        var b = ChannelItem(kind: .media, id: "2", title: "b"); b.folders = ["Reading"]
        XCTAssertEqual(SourceStreamItems.folderNames(collections: nil, items: [a, b]), ["Design", "Reading"])
    }

    func testTheListKeyCarriesTheStreamAndTheFolderAndTheRouteAsksForThem() {
        let key = SourceStreamItems.key(channel: "x", stream: "x.bookmarks", folder: "Design & Art")
        XCTAssertEqual(SourceListKey.parts(key).channel, "x", "every caller of the channel still sees the channel")
        XCTAssertEqual(SourceListKey.streamParts(key)?.stream, "x.bookmarks")
        XCTAssertEqual(SourceListKey.streamParts(key)?.folder, "Design & Art")
        XCTAssertEqual(APIClient.channelItemsPath(key, offset: 0, limit: 20),
                       "/sources/channels/x/items?offset=0&limit=20&stream=x.bookmarks&folder=Design%20%26%20Art")
        XCTAssertEqual(SourceStreamItems.key(channel: "x", stream: nil, folder: "Design"), "x", "All has no folder")
        XCTAssertNil(SourceListKey.streamParts("x"))
        let withSearch = ChannelItemsCache.key(key, query: "sync")
        XCTAssertTrue(withSearch.hasPrefix(key), "a search is its own list beside the stream's")
    }

    func testARowFromABackendThatSendsTheNewFieldsDecodesAndOneThatDoesNotStillDoes() throws {
        let new = try JSONDecoder().decode(ChannelItem.self, from: Data("""
            {"kind": "media", "id": "m1", "title": "t", "day": "2026-11-20", "lists": ["Bookmarks", " ", "Likes", "Likes"],
             "folders": ["Design"], "depth": "read", "posted": "2026-11-18"}
            """.utf8))
        XCTAssertEqual(new.lists, ["Bookmarks", "Likes"])
        XCTAssertEqual(new.folders, ["Design"])
        XCTAssertEqual(new.depth, "read")
        XCTAssertEqual(new.posted, "2026-11-18")
        let old = try JSONDecoder().decode(ChannelItem.self, from: Data(#"{"kind": "media", "id": "m1", "title": "t"}"#.utf8))
        XCTAssertNil(old.lists); XCTAssertNil(old.folders); XCTAssertNil(old.depth); XCTAssertNil(old.posted)
        let bad = try JSONDecoder().decode(ChannelItem.self, from: Data(#"{"kind": "media", "id": "m1", "title": "t", "lists": 3}"#.utf8))
        XCTAssertNil(bad.lists, "a malformed field drops the field, never the row")
    }

    func testAnItemCardsFooterIsSiteKeptAgeListsAndDepthWithNothingForKept() throws {
        let today = try XCTUnwrap(ISODay("2026-11-24"))
        var item = ChannelItem(kind: .media, id: "m1", title: "t", day: "2026-11-22", host: "x.com")
        item.lists = ["Bookmarks", "Likes"]
        item.depth = "read"
        item.posted = "2026-11-20"
        let footer = SourceItemCardText.footer(item, today: today, locale: Locale(identifier: "en_US"))
        XCTAssertEqual(footer.first, "x.com")
        XCTAssertTrue(footer.contains("kept 2d"))
        XCTAssertTrue(footer.contains("Bookmarks · Likes"))
        XCTAssertEqual(footer.last, "read")
        XCTAssertTrue(footer.contains { $0.hasPrefix("posted ") })
        item.depth = "kept"
        XCTAssertNil(SourceItemCardText.depth(item), "kept says nothing")
        XCTAssertEqual(SourceItemCardText.footer(ChannelItem(kind: .media, id: "m2", title: "t"), today: today), [],
                       "an older backend's row says less, never a guess")
    }

    // MARK: What is gone

    private static func source(_ path: String) throws -> String {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp").appendingPathComponent(path)
        return try String(contentsOf: url, encoding: .utf8)
    }

    func testNoSourcePageDrawsAnImportActionOrTheDiagram() throws {
        let page = try Self.source("Views/Sources/SourceCatalogViews.swift")
        for gone in ["IntakePanel(", "chooseExport", "WebReadingCard", "WebReadingScene", ".importFile(origin:",
                     "IntakeRouter", "Copy.Catalog.notionHow"] {
            XCTAssertFalse(page.contains(gone), "\(gone) is gone from a source page (ruling 78 (g))")
        }
        let books = try Self.source("Views/Sources/BooksSlots.swift")
        XCTAssertFalse(books.contains("fileImporter"), "no file chooser on Goodreads' page either")
        XCTAssertTrue(page.contains("SourceReadsBlock(") && page.contains("SourceStreamItemsSection("),
                      "every page draws the Reads block, and a list source its cards")
    }

    func testFileImportStaysReachableThroughTheWindowTheShortcutThePaletteHomeAgentsAndOnboarding() throws {
        XCTAssertTrue(try Self.source("ContentView.swift").contains("IntakeLayer"), "the window's drop")
        XCTAssertTrue(try Self.source("ContentView.swift").contains("case .importFile: intake.present(from: .fileMenu)"),
                      "the palette")
        XCTAssertTrue(try Self.source("CicadaApp.swift").contains("intake"), "⇧⌘I")
        XCTAssertTrue(try Self.source("Views/Home/HomeSections.swift").contains("intake"), "Home")
        XCTAssertTrue(try Self.source("Views/Onboarding/SourcesStep.swift").contains("IntakePicker.choose()"), "onboarding")
        let agents = try FileManager.default.contentsOfDirectory(
            atPath: URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
                .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Views/Agents").path)
        var found = false
        for file in agents where file.hasSuffix(".swift") {
            if try Self.source("Views/Agents/" + file).contains("intake") { found = true }
        }
        XCTAssertTrue(found, "the Agents page")
    }

    func testNotionLeftTheFileGroupAndIsItsLiveConnection() {
        let notion = SourceCatalog.fixed.first { $0.id == "notion" }
        XCTAssertEqual(notion?.group, .accounts)
        XCTAssertNotEqual(notion?.verb, .importFile)
    }
}
