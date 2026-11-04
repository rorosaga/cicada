import XCTest
@testable import CicadaApp

/// 2026-11-04 — the This Mac source pages (Apple Notes, Reminders, Contacts, Calendar, the meeting recorders): the one
/// accounts → collections → items browser, and the owner's bugs — Contacts Off until a sync, Wispr Flow's missing mark
/// and its removal unnoticed, Calendar's unexplained Google account, Hex's folder read in one click.
@MainActor
final class ThisMacSourcesTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func row(_ id: String, in rows: [SourceCatalogRow]) -> SourceCatalogRow? { rows.first { $0.id == id } }

    // MARK: - Contacts: Connected from the start

    /// The owner: "I just pressed sync contacts … it said syncing and then it turned off … now that it finished
    /// syncing, it says connected. But I don't get why it wasn't connected from the start." The catalogue required the
    /// backend's `connected` — a sync recorded in the bank — and a fresh bank, a first read still running or a read the
    /// bank refused leaves it false. A reader this Mac runs is Connected while it is allowed and turned on.
    func testAReaderThatIsOnReadsConnectedBeforeTheBankRecordedASync() {
        let notYet = [SourceChannel(id: ContactsReader.channel, label: "Contacts", connected: false),
                      SourceChannel(id: "calendar-local", label: "Calendar", connected: false),
                      SourceChannel(id: RemindersReader.channel, label: "Reminders", connected: false)]
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])
        let on = SourceCatalog.rows(entries: entries, channels: notYet, overview: [], readableSites: [],
                                    localReaders: [ContactsReader.channel: true, "calendar-local": true,
                                                   RemindersReader.channel: true])
        XCTAssertEqual(row("contacts-local", in: on)?.status, .connected)
        XCTAssertEqual(row("calendar-local", in: on)?.status, .connected)
        XCTAssertEqual(row(RemindersReader.channel, in: on)?.status, .connected)
        // Before the channels are even read (launch), the reader's own switch still answers.
        let launch = SourceCatalog.rows(entries: entries, channels: [], overview: [], readableSites: [],
                                        localReaders: [ContactsReader.channel: true])
        XCTAssertEqual(row("contacts-local", in: launch)?.status, .connected)
        // Off here is Off, whatever the bank holds.
        let off = SourceCatalog.rows(entries: entries, channels: notYet, overview: [], readableSites: [],
                                     localReaders: [ContactsReader.channel: false])
        XCTAssertEqual(row("contacts-local", in: off)?.status, .off)
    }

    func testContactsIsOnWhenAllowedAndTurnedOnIncludingBeforeItsFirstRead() {
        XCTAssertTrue(LocalReaders.contactsOn(enabled: true, status: .off), "before start() ran at launch")
        XCTAssertTrue(LocalReaders.contactsOn(enabled: true, status: .syncing))
        XCTAssertTrue(LocalReaders.contactsOn(enabled: true, status: .watching))
        XCTAssertTrue(LocalReaders.contactsOn(enabled: true, status: .failed("x")))
        XCTAssertFalse(LocalReaders.contactsOn(enabled: true, status: .denied), "access taken away")
        XCTAssertFalse(LocalReaders.contactsOn(enabled: false, status: .watching))
    }

    // MARK: - Wispr Flow: its mark, and its removal

    func testWisprFlowWearsItsOwnBundledMark() {
        XCTAssertEqual(OriginIconography.logoName(for: "wispr-flow"), "wispr")
        XCTAssertTrue(LogoImage.exists(name: "wispr"))
    }

    func testAnAppRemovedFromThisMacReadsOffNotInstalledInWords() {
        let channels = [SourceChannel(id: SourceCatalog.wisprChannel, label: "Wispr Flow", connected: true,
                                      lastSync: "2026-11-03T10:00:00Z")]
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: true, overview: [])
        let rows = SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                                      notInstalled: [SourceCatalog.wisprChannel])
        let wispr = row(SourceCatalog.wisprChannel, in: rows)
        XCTAssertEqual(wispr?.status, .off)
        XCTAssertEqual(wispr.flatMap { SourceCatalog.line($0, now: .now) }, "Not installed")
        let page = SourcePageStatus.of(row: .off, run: .idle, latest: "2026-11-03", notInstalled: true)
        XCTAssertEqual(page.line(today: ISODay(year: 2026, month: 11, day: 4)), "Off · not installed")
        XCTAssertEqual(page.tone, .off)
        // Installed, the same row is the bank's word again.
        let back = SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [])
        XCTAssertEqual(row(SourceCatalog.wisprChannel, in: back)?.status, .connected)
    }

    /// Owner 2026-11-04 ("remove wisprflow also from sources for now"): every surface that offers it follows the one
    /// flag, whichever way it is set, so bringing it back needs no other line and no change here.
    func testWisprFlowIsOfferedOnlyWhileItsOneFlagSaysSo() {
        let flag = SourceCatalog.wisprOffered
        XCTAssertEqual(ConnectSuggestApps.target(bundleId: LocalSourceWatcher.wisprBundleId) != nil, flag)
        XCTAssertEqual(ConnectSuggestApps.status(of: SourceCatalog.wisprChannel, channels: [], overview: [],
                                                 localReaders: [:]) != nil, flag)
        XCTAssertEqual(ConnectSuggestApps.offered(SourceCatalog.wisprChannel), flag, "Settings' list of Noes")
        XCTAssertTrue(ConnectSuggestApps.offered("whatsapp"))
        let defaults = UserDefaults(suiteName: "ThisMacSourcesTests.wispr.\(UUID().uuidString)")!
        let local = LocalSourceWatcher(lights: BrowserWatcher(defaults: defaults, channels: []), defaults: defaults)
        XCTAssertEqual(AppSourceDrivers.live(calendar: nil, local: local, store: nil)[AppSourceDrivers.wispr] != nil, flag)
        // A checklist that ticked it before keeps every other row, and cannot be held open by this one.
        let ticked = GettingStartedRecord(enabled: [.app(AppSourceDrivers.wispr), .app(AppSourceDrivers.notes)])
        let expected: [FoundItemID] = (flag ? [.app(AppSourceDrivers.wispr)] : []) + [.app(AppSourceDrivers.notes)]
        XCTAssertEqual(GettingStartedProgress.rows(GettingStartedInputs(record: ticked)).map(\.id), expected)
    }

    // MARK: - Accounts by their real provider

    /// EventKit's source types: local 0, exchange 1, calDAV 2, mobileMe 3, subscribed 4, birthdays 5.
    func testCalendarAccountsSplitByTheirRealProvider() {
        XCTAssertEqual(SourceAccountProvider.of(sourceType: 2, title: "iCloud"), .icloud)
        XCTAssertEqual(SourceAccountProvider.of(sourceType: 2, title: "bob@gmail.com"), .google)
        XCTAssertEqual(SourceAccountProvider.of(sourceType: 2, title: "Google"), .google)
        XCTAssertEqual(SourceAccountProvider.of(sourceType: 2, title: "Fastmail"), .other)
        XCTAssertEqual(SourceAccountProvider.of(sourceType: 1, title: "Work"), .exchange)
        XCTAssertEqual(SourceAccountProvider.of(sourceType: 0, title: "On My Mac"), .local)
        XCTAssertEqual(SourceAccountProvider.of(sourceType: 4, title: "Holidays"), .subscribed)
        XCTAssertEqual(SourceAccountProvider.of(sourceType: 3, title: "Me"), .icloud)
    }

    func testNotesAccountsAreReadFromTheirNamesAndAPostedKindWins() {
        XCTAssertEqual(SourceAccountProvider.of(posted: nil, name: "iCloud"), .icloud)
        XCTAssertEqual(SourceAccountProvider.of(posted: nil, name: "On My Mac"), .local)
        XCTAssertEqual(SourceAccountProvider.of(posted: nil, name: "Gmail"), .google)
        XCTAssertEqual(SourceAccountProvider.of(posted: nil, name: "Outlook"), .exchange)
        XCTAssertEqual(SourceAccountProvider.of(posted: nil, name: "bob-example"), .other)
        XCTAssertEqual(SourceAccountProvider.of(posted: "google", name: "Work"), .google)
        XCTAssertEqual(SourceAccountProvider.of(posted: "nonsense", name: "iCloud"), .icloud)
    }

    /// Only a licensed brand mark is drawn (Google's, bundled); Apple's are never committed, so iCloud and this Mac
    /// wear a system symbol.
    func testEachAccountWearsItsOwnMark() {
        XCTAssertEqual(SourceAccountProvider.google.logo(channel: "calendar-local"), "google-calendar")
        XCTAssertEqual(SourceAccountProvider.google.logo(channel: "notes"), "gmail")
        XCTAssertNil(SourceAccountProvider.icloud.logo(channel: "notes"))
        XCTAssertEqual(SourceAccountProvider.icloud.symbol, "icloud")
        for kind in SourceAccountProvider.allCases {
            if let logo = kind.logo(channel: "calendar-local") { XCTAssertTrue(LogoImage.exists(name: logo), logo) }
            XCTAssertFalse(kind.symbol.isEmpty)
        }
    }

    // MARK: - The browser

    private func tree(_ accounts: [SourceAccount]) -> ChannelCollections {
        ChannelCollections(channel: "notes", accounts: accounts)
    }

    func testTheBrowserOpensWhereThereIsSomethingToChoose() {
        let work = SourceCollection(id: "c1", name: "Work", count: 3)
        let home = SourceCollection(id: "c2", name: "Home", count: 1)
        XCTAssertEqual(SourceBrowserText.start(nil), .flat)
        XCTAssertEqual(SourceBrowserText.start(tree([])), .flat)
        let two = tree([SourceAccount(name: "iCloud", count: 3, collections: [work]),
                        SourceAccount(name: "On My Mac", count: 1, collections: [home])])
        XCTAssertEqual(SourceBrowserText.start(two), .accounts)
        let oneAccount = SourceAccount(name: "iCloud", count: 4, collections: [work, home])
        XCTAssertEqual(SourceBrowserText.start(tree([oneAccount])), .collections(oneAccount))
        XCTAssertEqual(SourceBrowserText.start(tree([SourceAccount(name: "iCloud", count: 3, collections: [work])])),
                       .items(work))
    }

    func testANamelessAccountIsNamedByItsKind() {
        XCTAssertEqual(SourceBrowserText.accountName(SourceAccount(name: nil, provider: "local", count: 0,
                                                                   collections: [])), "On My Mac")
        XCTAssertEqual(SourceBrowserText.accountName(SourceAccount(name: "  ", count: 0, collections: [])), "Other")
        XCTAssertEqual(SourceBrowserText.accountName(SourceAccount(name: "iCloud", count: 0, collections: [])),
                       "iCloud")
    }

    func testTheTreeDecodesLeniently() throws {
        let json = """
        {"channel": "calendar-local", "accounts": [
          {"name": "iCloud", "provider": "icloud", "count": 2,
           "collections": [{"id": "c1", "name": "Home", "count": 2, "latest": "2026-11-03"}]},
          {"name": null, "collections": [{"id": "c2", "count": 1}], "future": true}
        ]}
        """
        let tree = try JSONDecoder().decode(ChannelCollections.self, from: Data(json.utf8))
        XCTAssertEqual(tree.accounts.count, 2)
        XCTAssertEqual(tree.accounts[0].kind, .icloud)
        XCTAssertEqual(tree.accounts[0].collections[0].latest, "2026-11-03")
        XCTAssertNil(tree.accounts[1].name)
        XCTAssertEqual(tree.accounts[1].count, 1, "a missing count is its collections' sum")
        XCTAssertEqual(tree.accounts[1].collections[0].name, "")
    }

    func testOneCollectionsListIsItsOwnKeyAndRidesTheWireAsCollection() {
        let key = SourceListKey.make("calendar-local", collection: "cal/1 2")
        XCTAssertNotEqual(key, "calendar-local")
        XCTAssertEqual(SourceListKey.parts(key).channel, "calendar-local")
        XCTAssertEqual(SourceListKey.parts(key).collection, "cal/1 2")
        XCTAssertEqual(SourceListKey.make("notes", collection: nil), "notes")
        XCTAssertNil(SourceListKey.parts("notes").collection)
        let path = APIClient.channelItemsPath(key, offset: 0, limit: 20)
        XCTAssertTrue(path.hasPrefix("/sources/channels/calendar-local/items?offset=0&limit=20&collection=cal%2F1%202"),
                      path)
        // A search of that collection keeps both.
        XCTAssertTrue(APIClient.channelItemsPath(key, offset: 0, limit: 20, query: "dentist").hasSuffix("&q=dentist"))
        // The cache keeps the collection's list apart from the whole channel's, and its search apart again.
        XCTAssertNotEqual(ChannelItemsCache.key(key, query: ""), ChannelItemsCache.key("calendar-local", query: ""))
        XCTAssertNotEqual(ChannelItemsCache.key(key, query: "x"), ChannelItemsCache.key(key, query: ""))
    }

    func testTheCacheReadsTheTreeAndKeepsItOnAFailure() async {
        let api = TreeAPI()
        let cache = ChannelItemsCache(api: api)
        api.reply = .success(Conditional(value: tree([SourceAccount(name: "iCloud", count: 1, collections: [
            SourceCollection(id: "c1", name: "Work", count: 1)])]), etag: "\"t1\"", notModified: false))
        await cache.refreshCollections("notes")
        XCTAssertEqual(cache.collections("notes")?.accounts.first?.name, "iCloud")
        api.reply = .failure(APIError.serverUnreachable)
        await cache.refreshCollections("notes")
        XCTAssertEqual(cache.collections("notes")?.accounts.count, 1, "never blank (DR-43)")
        XCTAssertEqual(api.etags.last, "\"t1\"", "revalidated with the tag it holds")
        cache.reset()
        XCTAssertNil(cache.collections("notes"))
    }

    // MARK: - Notes' accounts

    /// The script ends each record with its account; the account travels beside the dump, so a backend that checks a
    /// record's field count still reads every note.
    func testNotesAccountsTravelBesideTheDump() {
        let fs = AppleNotesReader.fieldSeparator, rs = AppleNotesReader.recordSeparator
        let nine = ["id-1", "Plan", "body", "c", "m", "Work", "2026-11-01T10:00:00", "0", "iCloud"].joined(separator: fs)
        let eight = ["id-2", "List", "body", "c", "m", "Notes", "2026-11-01T10:00:00", "0"].joined(separator: fs)
        let parts = AppleNotesReader.split([nine, eight].joined(separator: rs))
        XCTAssertEqual(parts.accounts, ["id-1": "iCloud"])
        let records = parts.dump.components(separatedBy: rs)
        XCTAssertEqual(records.map { $0.components(separatedBy: fs).count }, [8, 8])
        XCTAssertEqual(records[1], eight)
        XCTAssertTrue(AppleNotesReader.script.contains("set accName to name of acc"))
    }

    // MARK: - Meetings

    func testAMeetingRowSaysItsDayAndHowLongItRan() {
        var item = ChannelItem(kind: .episode, id: "ep", title: "Alpha planning", day: "2026-11-03")
        item.durationS = 750
        var gregorian = Calendar(identifier: .gregorian)
        gregorian.timeZone = TimeZone(identifier: "UTC")!
        let meta = MeetingRowText.meta(item, locale: us, calendar: gregorian)
        XCTAssertEqual(meta.text, "Tue, Nov 3 · 12 min")
        XCTAssertTrue(meta.help.hasPrefix("Tuesday, November 3, 2026"), meta.help)
        item.durationS = nil
        XCTAssertEqual(MeetingRowText.meta(item, locale: us, calendar: gregorian).text, "Tue, Nov 3")
        XCTAssertEqual(SourceBrowserText.duration(30), nil)
        XCTAssertEqual(SourceBrowserText.duration(3_900), "1 h 05 min")
    }

    /// Hex's folder as the person knows it, on *Connect Hex*'s hover.
    func testHexsFolderReadsAsThePathThePersonKnows() {
        let home = URL(fileURLWithPath: "/Users/verify")
        XCTAssertEqual(HexConnectText.display(URL(fileURLWithPath: "/Users/verify/Documents/Hex Meetings"), home: home),
                       "~/Documents/Hex Meetings")
        XCTAssertEqual(HexConnectText.display(URL(fileURLWithPath: "/Volumes/Notes/Meetings"), home: home),
                       "/Volumes/Notes/Meetings")
        XCTAssertEqual(HexConnectText.display(URL(fileURLWithPath: "/Users/verifyx/a"), home: home),
                       "/Users/verifyx/a", "a sibling of the home folder is not under it")
    }

    /// Hex's default is under Documents: opening its page asks nothing of that folder. Only Connect's own read does.
    func testOpeningHexsPageNeverChecksItsFolder() throws {
        let slots = try String(contentsOfFile: Self.path("Views/Sources/SourcePageSlots.swift"), encoding: .utf8)
        XCTAssertFalse(slots.contains("hexFolderFound"))
        XCTAssertFalse(slots.contains("fileExists"))
    }

    /// Hex's own settings name the folder; with none, Hex's default under Documents.
    func testHexsFolderIsHexsOwnSettingElseItsDefault() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("hex-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: home) }
        XCTAssertEqual(LocalSourceWatcher.hexMeetingsFolder(home: home).path,
                       home.appendingPathComponent("Documents/Hex Meetings").path)
        let settings = home.appendingPathComponent("Library/Application Support/hex")
        try FileManager.default.createDirectory(at: settings, withIntermediateDirectories: true)
        try Data(#"{"meetings": {"output_folder": "/tmp/elsewhere"}}"#.utf8)
            .write(to: settings.appendingPathComponent("settings.json"))
        XCTAssertEqual(LocalSourceWatcher.hexMeetingsFolder(home: home).path, "/tmp/elsewhere")
    }

    func testTheMeetingRowsDurationDecodes() throws {
        let json = #"{"kind": "episode", "id": "ep", "title": "T", "day": "2026-11-03", "duration_s": 1920}"#
        XCTAssertEqual(try JSONDecoder().decode(ChannelItem.self, from: Data(json.utf8)).durationS, 1920)
        let bad = #"{"kind": "episode", "id": "ep", "title": "T", "duration_s": "long"}"#
        XCTAssertNil(try JSONDecoder().decode(ChannelItem.self, from: Data(bad.utf8)).durationS)
    }

    // MARK: - Words

    func testTheBrowsersWordsCountInTheSourcesOwnUnit() {
        XCTAssertEqual(Copy.SourceBrowser.count(1, channel: "notes", locale: us), "1 note")
        XCTAssertEqual(Copy.SourceBrowser.count(1_204, channel: "calendar-local", locale: us), "1,204 events")
        XCTAssertEqual(Copy.SourceBrowser.count(2, channel: "meetings:f1", locale: us), "2 meetings")
        XCTAssertEqual(Copy.SourceBrowser.search(12, channel: "notes", in: "Work", locale: us), "Search 12 notes in Work")
        XCTAssertEqual(Copy.SourceBrowser.search(nil, channel: "reminders-local", locale: us), "Search reminders")
    }

    /// Calendar's standing "Google calendars come in through macOS…" line and its *Add a Google account* button are
    /// what read as an unexplained Google account; the account list replaces both.
    func testTheGoogleExplanationIsTheAccountListNotAStandingLine() throws {
        for file in ["Views/Settings/CalendarRow.swift", "Views/Sources/SourceBrowser.swift",
                     "Views/Sources/SourceCatalogViews.swift"] {
            let source = try String(contentsOfFile: Self.path(file), encoding: .utf8)
            XCTAssertFalse(source.contains("Copy.calendarGoogleHow"), file)
            XCTAssertFalse(source.contains("Copy.calendarAddGoogle"), file)
        }
    }

    /// Esc steps back one level while one is open, and only then does it close the page.
    func testEscStepsBackALevelBeforeItClosesThePage() {
        let back = SourcePageBack()
        XCTAssertFalse(back.run())
        var steps = 0
        back.step = { steps += 1 }
        XCTAssertTrue(back.run())
        XCTAssertEqual(steps, 1)
    }

    static func path(_ rel: String) -> String {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/\(rel)").path
    }
}

/// Answers the tree from one reply and records the tags it was asked with.
@MainActor
private final class TreeAPI: ChannelItemsAPI {
    var reply: Result<Conditional<ChannelCollections>, any Error> = .failure(APIError.serverUnreachable)
    private(set) var etags: [String?] = []

    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        throw APIError.serverUnreachable
    }

    func fetchChannelCollections(channel: String, etag: String?) async throws -> Conditional<ChannelCollections> {
        etags.append(etag)
        return try reply.get()
    }
}
