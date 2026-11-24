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

    /// Found in the real app: "...by Another agent, about once a day, Noticed when you save" — the generic "Another agent"
    /// row is not a name, and a phrase after the first is part of one sentence.
    func testTheHeadLineNeverNamesTheGenericAgentAndIsOneSentence() throws {
        XCTAssertNil(SourceHeadLine.app(rows: [AgentLiveRow(id: "other", connected: true)]),
                     "the generic row names no app: the line says your AI app")
        for source in ["x", "youtube", "instagram", "reddit", "github", "notes"] {
            guard let line = SourceHeadLine.text(account: nil, streams: try streams(source), app: nil) else { continue }
            XCTAssertNil(line.range(of: ", [A-Z]", options: .regularExpression), "\(source): \(line)")
        }
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

    /// DR-38: the head says how a source is read, so a row says only what is specific to its stream.
    func testARowSaysOnlyWhatIsSpecificToItsStream() throws {
        func line(_ id: String, in source: String) throws -> String? {
            let one = try resolved(id, in: source)
            let siblings = try XCTUnwrap(SourceStreamsFixture.load().source(source)).streams
            return SourceStreamRow.line(one.stream, among: siblings)
        }
        // The head already says "In your browser, by your AI app": nothing repeats it, and a depth word appears only where a source's streams differ.
        XCTAssertEqual(try line("x.bookmarks", in: "x"), "3 folders", "its folders, nothing about the way it is read")
        XCTAssertNil(try line("x.likes", in: "x"), "nothing specific: no line at all")
        XCTAssertEqual(try line("x.saves", in: "x"), "When you save, on this Mac", "the click stream's own way")
        XCTAssertEqual(try line("notes.notes", in: "notes"), "6 folders", "a lone Mac reader: the head says it is read on this Mac")
        XCTAssertEqual(try line("imessage.chats", in: "imessage"), "Messages needs Full Disk Access.", "unavailable: why")
        XCTAssertEqual(try line("linkedin.connections", in: "linkedin"), "Matched to people you already have pages for",
                       "what a stream is for when its name does not say, never the depth word")
        XCTAssertFalse(try XCTUnwrap(try line("linkedin.connections", in: "linkedin")).contains("never read"))
        let help = try XCTUnwrap(SourceStreamRow.help(try resolved("x.bookmarks", in: "x").stream))
        XCTAssertTrue(help.contains("Older ones come with the site's export"))
        XCTAssertTrue(help.contains("Unsaving on the site does not remove one here"))
        XCTAssertNil(SourceStreamRow.help(try resolved("notes.notes", in: "notes").stream))
    }

    func testARowSaysHowItIsReadOnlyWhenTheHeadDoesNot() {
        let browser = SourceStream(id: "s.a", label: "A", kind: .saved, how: .browser, state: .on)
        let account = SourceStream(id: "s.b", label: "B", kind: .saved, how: .account, state: .on)
        let app = SourceStream(id: "s.c", label: "C", kind: .notes, how: .app, state: .off)
        // The head names the ways of the streams that are on (browser, account); a stream read another way says it.
        XCTAssertNil(SourceStreamRow.line(browser, among: [browser, account, app]))
        XCTAssertEqual(SourceStreamRow.line(app, among: [browser, account, app]), "On this Mac")
        // A source whose streams go to different depths says each row's own.
        var deep = browser
        deep.depth = .read
        XCTAssertEqual(SourceStreamRow.line(deep, among: [deep, account]), "read by Sleep")
        XCTAssertEqual(SourceStreamRow.line(account, among: [deep, account]), "kept, never read: you did not save it")
        XCTAssertEqual(SourceStreamRow.line(SourceStream(id: "s.d", label: "D", kind: .saved, state: .unavailable,
                                                        why: "Needs Full Disk Access."), among: []),
                       "Needs Full Disk Access.", "an unavailable stream says why instead")
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

    func testAnItemCardsFooterIsOneDateTheListsAndTheDepthWithNothingForKept() throws {
        let today = try XCTUnwrap(ISODay("2026-11-24"))
        let en = Locale(identifier: "en_US")
        var item = ChannelItem(kind: .media, id: "m1", title: "t", day: "2026-11-22", host: "x.com")
        item.lists = ["Bookmarks", "Likes"]
        item.depth = "read"
        item.posted = "2026-11-20"
        // On a source's own page every item is from that site: no host, ONE date (the post's own day), then lists, depth.
        let footer = SourceItemCardText.footer(item, today: today, locale: en)
        XCTAssertEqual(footer.count, 3, "one date, the lists, the depth word: \(footer)")
        XCTAssertTrue(try XCTUnwrap(footer.first).hasPrefix("posted "))
        XCTAssertFalse(footer.contains { $0.hasPrefix("kept") }, "never two dates")
        XCTAssertFalse(footer.contains("x.com"))
        XCTAssertEqual(Array(footer.suffix(2)), ["Bookmarks · Likes", "read"])
        // Without a post day, the day it was kept.
        item.posted = nil
        XCTAssertEqual(SourceItemCardText.footer(item, today: today, locale: en).first, "kept 2d")
        // Away from the source's own page the site leads (its real mark is drawn beside it).
        XCTAssertEqual(SourceItemCardText.footer(item, today: today, showsSite: true, locale: en).first, "x.com")
        // A list's own tab: every card is on it, so it is not said again.
        XCTAssertEqual(SourceItemCardText.footer(item, today: today, omitting: "Bookmarks", locale: en),
                       ["kept 2d", "Likes", "read"])
        // The author leads the footer when the row has one.
        item.author = "  Alpha Writer "
        XCTAssertEqual(SourceItemCardText.footer(item, today: today, locale: en).first, "Alpha Writer")
        item.depth = "kept"
        XCTAssertEqual(SourceItemCardText.depth(item), "not read yet")
        XCTAssertEqual(SourceItemCardText.footer(ChannelItem(kind: .media, id: "m2", title: "t"), today: today), [],
                       "an older backend's row says less, never a guess")
    }

    /// G245 B3, ruling 80 — where a saved item stands, said in the footer's own style: nothing for a value this build does
    /// not know, one short plain phrase for each state, no provider named.
    func testTheDepthWordIsOneShortPhraseForEveryStateAndNothingForAnUnknownOne() throws {
        let today = try XCTUnwrap(ISODay("2026-11-24"))
        let en = Locale(identifier: "en_US")
        func card(_ depth: String?) -> ChannelItem {
            var item = ChannelItem(kind: .media, id: "m", title: "t", day: "2026-11-22", host: "x.com")
            item.depth = depth
            item.lists = ["Bookmarks"]
            return item
        }
        XCTAssertEqual(SourceItemCardText.depth(card("kept")), "not read yet")
        XCTAssertEqual(SourceItemCardText.depth(card("empty")), "nothing to read yet")
        XCTAssertEqual(SourceItemCardText.depth(card("record")), "kept, never read")
        XCTAssertNil(SourceItemCardText.depth(card(nil)))
        XCTAssertNil(SourceItemCardText.depth(card("deeper-than-we-know")), "an unknown value draws nothing")
        XCTAssertEqual(SourceItemCardText.depth(card("asked")), "waiting for your AI app")
        XCTAssertEqual(SourceItemCardText.depth(card("read")), "read")
        XCTAssertEqual(SourceItemCardText.depth(card("watched")), "watched")
        let plain = SourceItemCardText.footer(card("deeper-than-we-know"), today: today, locale: en)
        for depth in ["kept", "empty", "record", "asked", "read", "watched"] {
            let footer = SourceItemCardText.footer(card(depth), today: today, locale: en)
            XCTAssertEqual(footer.count, plain.count + 1, "\(depth): one more word in the meta line, nothing else")
            XCTAssertEqual(footer.dropLast().map { $0 }, plain, "\(depth): the depth word comes last")
        }
        for word in [Copy.Streams.itemRead, Copy.Streams.itemNotRead, Copy.Streams.itemNothing, Copy.Streams.itemRecord,
                     Copy.Streams.itemAsked, Copy.Streams.itemWatched] {
            XCTAssertTrue(word.first?.isLowercase == true, "the footer's own lowercase style: \(word)")
            XCTAssertFalse(["claude", "chatgpt", "openai", "gemini", "anthropic"].contains { word.lowercased().contains($0) }, word)
        }
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

    /// G246 (ruling 81, Track 3) — "Saved another way" is a place posts go: a tab of the Items with its count, never a Reads
    /// row's worth of words about how the source is read, and no setup to ask for.
    func testSavedAnotherWayIsATabAndSaysNothingAboutHowTheSourceIsRead() throws {
        let another = SourceStream(id: "x.another-way", label: "Saved another way", kind: .saved, how: .app, owner: .backend,
                                   control: .setup, state: .on, health: .read, count: 4, depth: .read)
        XCTAssertTrue(another.isDerived)
        XCTAssertFalse(SourceStream(id: "x.bookmarks", label: "Bookmarks").isDerived)
        let derived = ResolvedStream(source: "x", stream: another, word: .read, fix: nil, reader: nil)
        let base = try streams("x")
        XCTAssertEqual(SourceHeadLine.text(account: nil, streams: base + [derived], app: nil),
                       SourceHeadLine.text(account: nil, streams: base, app: nil), "the head's line is the lists' alone")
        XCTAssertEqual(SourceHeadLine.ways(base + [derived]), SourceHeadLine.ways(base))
        // Off lists, one derived stream that is on: still the ways a source could read, not an empty line.
        let off = base.map { r -> ResolvedStream in
            var s = r.stream; s.state = .off
            return ResolvedStream(source: r.source, stream: s, word: .off, fix: nil, reader: nil)
        }
        XCTAssertEqual(SourceHeadLine.ways(off + [derived]), SourceHeadLine.ways(off))
        let tabs = SourceStreamItems.tabs(base.filter { $0.stream.kind.isList && ($0.stream.count ?? 0) > 0 } + [derived])
        XCTAssertEqual(tabs.last?.label, "Saved another way")
        XCTAssertEqual(tabs.last?.count, 4)
        XCTAssertTrue(try Self.source("Views/Sources/SourceCatalogViews.swift").contains("!$0.stream.isDerived"),
                      "the Reads block and the connect step leave it out")
    }

    func testNotionLeftTheFileGroupAndIsItsLiveConnection() {
        let notion = SourceCatalog.fixed.first { $0.id == "notion" }
        XCTAssertEqual(notion?.group, .accounts)
        XCTAssertNotEqual(notion?.verb, .importFile)
    }
}
