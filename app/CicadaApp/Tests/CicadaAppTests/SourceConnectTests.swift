import XCTest
@testable import CicadaApp

/// G245 (plan 7) — one connect plan for the page's switch, the card's Connect and the notch's Yes.
@MainActor
final class SourceConnectTests: XCTestCase {
    private let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!
    private let safari = BrowserInventory.catalog.first { $0.id == "safari" }!

    private func entry(_ id: String) throws -> SourceCatalogEntry {
        let all = SourceCatalog.entries(browsers: [chrome, safari], wisprPresent: false, hexPresent: true, overview: [],
                                        channels: [SourceChannel(id: "telegram", label: "t", connected: true)])
        return try XCTUnwrap(all.first { $0.id == id }, id)
    }

    private let ready = SourceConnect.State(status: .off, agentEnabled: true, ackCurrent: true)
    private let unacknowledged = SourceConnect.State(status: .off, agentEnabled: false, ackCurrent: false)

    private func plan(_ id: String, _ state: SourceConnect.State? = nil) throws -> SourceConnect.Plan {
        SourceConnect.plan(try entry(id), state ?? ready)
    }

    // MARK: A site

    func testASitesYesTurnsOnItsSavedListAndNoticingSavesWhenAgentReadingIsAcknowledged() throws {
        XCTAssertEqual(try plan("x"), .start([.list(setting: "savedLists", key: "x", on: true), .noticeSaves(site: "x")],
                                             thenOpen: false))
        XCTAssertEqual(try plan("reddit"), .start([.list(setting: "savedLists", key: "reddit", on: true),
                                                   .noticeSaves(site: "reddit")], thenOpen: false))
    }

    func testWithoutTheAcknowledgementItNoticesSavesAloneAndAsksForTheSheetOnThePage() throws {
        XCTAssertEqual(try plan("x", unacknowledged),
                       .needsConsent(ReadingConsent(entryId: "x", setting: "savedLists", key: "x"),
                                     now: [.noticeSaves(site: "x")]),
                       "nothing about the list is turned on silently")
        // Agent reading on but its wording changed since the last acknowledgement: asked again.
        let stale = SourceConnect.State(status: .off, agentEnabled: true, ackCurrent: false)
        if case .needsConsent = try plan("instagram", stale) {} else { XCTFail("an old acknowledgement does not count") }
        // Acknowledged but agent reading turned off: the sheet turns it back on.
        let off = SourceConnect.State(status: .off, agentEnabled: false, ackCurrent: true)
        if case .needsConsent = try plan("tiktok", off) {} else { XCTFail("reading is off") }
    }

    func testASiteWithNoSaveControlOffersTheSamePlan() throws {
        XCTAssertEqual(try plan("linkedin"), .start([.list(setting: "savedLists", key: "linkedin", on: true)], thenOpen: false))
        XCTAssertEqual(try plan("spotify", unacknowledged),
                       .needsConsent(ReadingConsent(entryId: "spotify", setting: "savedLists", key: "spotify"), now: []))
        // Pinterest has a save control since 2026-11-25: noticing its saves is done at once, beside the sheet.
        XCTAssertEqual(try plan("pinterest", unacknowledged),
                       .needsConsent(ReadingConsent(entryId: "pinterest", setting: "savedLists", key: "pinterest"),
                                     now: [.noticeSaves(site: "pinterest")]))
        XCTAssertEqual(try plan("goodreads").self, .start([.list(setting: "savedLists", key: "goodreads", on: true)],
                                                          thenOpen: false))
    }

    func testAYesNeverTurnsOnAStreamThatIsNew() throws {
        // YouTube's Watch later and Substack's Saved are the existing saved lists; history and the rest stay the person's.
        XCTAssertEqual(try plan("youtube"), .start([.list(setting: "youtubeLists", key: "watch_later", on: true),
                                                    .noticeSaves(site: "youtube")], thenOpen: false))
        XCTAssertEqual(try plan(SourceCatalog.substackId), .start([.list(setting: "substackLists", key: "saved", on: true)],
                                                                  thenOpen: false))
        for id in ["x", "instagram", "reddit", "linkedin"] {
            guard case .start(let steps, _) = try plan(id) else { return XCTFail(id) }
            let keys = steps.compactMap { step -> String? in if case .list(_, let key, _) = step { key } else { nil } }
            XCTAssertEqual(keys, [id], "\(id): its own list, never x-likes, x-reposts or linkedin-connections")
        }
    }

    func testAListAlreadyOnIsNotTurnedOnAgain() throws {
        let waiting = SourceConnect.State(status: .waitingForAgent, agentEnabled: true, ackCurrent: true,
                                          savedListsOn: ["x"], siteSavesOn: ["x"])
        XCTAssertEqual(try plan("x", waiting), .openPage)
        let noticingMissing = SourceConnect.State(status: .waitingForAgent, agentEnabled: true, ackCurrent: true,
                                                  savedListsOn: ["x"])
        XCTAssertEqual(try plan("x", noticingMissing), .start([.noticeSaves(site: "x")], thenOpen: false),
                       "only what is missing")
    }

    func testAConnectedSourceOpensItsPage() throws {
        var state = ready
        state.status = .connected
        XCTAssertEqual(try plan("x", state), .openPage)
        XCTAssertEqual(try plan("notes", state), .openPage)
    }

    func testGitHubNoticesSavesAndOpensItsPageForTheCode() throws {
        XCTAssertEqual(try plan("github"), .start([.noticeSaves(site: "github")], thenOpen: true))
        let noticing = SourceConnect.State(status: .off, siteSavesOn: ["github"])
        XCTAssertEqual(try plan("github", noticing), .needsChoice(.signIn))
    }

    // MARK: A Mac app

    func testAMacAppsYesStartsItsReaderWhenOneClickCan() throws {
        for id in ["calendar-local", "contacts-local", "notes", "voice-memos", "apple-books", "browser:chrome"] {
            XCTAssertEqual(try plan(id), .start([.startReader(entry: id)], thenOpen: false), id)
        }
    }

    func testAReaderAlreadyOnOpensItsPageInsteadOfStartingAgain() throws {
        let on = SourceConnect.State(status: .off, readersOn: ["notes": true])
        XCTAssertEqual(try plan("notes", on), .openPage)
    }

    func testItOpensThePageOnlyWhenAChoiceIsNeeded() throws {
        XCTAssertEqual(try plan("imessage"), .needsChoice(.chats))
        XCTAssertEqual(try plan("whatsapp"), .needsChoice(.chats))
        XCTAssertEqual(try plan(TelegramChats.channel), .needsChoice(.chats))
        XCTAssertEqual(try plan("reminders-local"), .needsChoice(.lists))
        XCTAssertEqual(try plan("folders"), .needsChoice(.folder))
        XCTAssertEqual(try plan("hex"), .needsChoice(.folder))
        XCTAssertEqual(try plan("meeting-folders"), .needsChoice(.folder))
        XCTAssertEqual(try plan("linear"), .needsChoice(.signIn))
        XCTAssertEqual(try plan("notion"), .needsChoice(.signIn))
        XCTAssertEqual(try plan("rss"), .needsChoice(.feedAddress))
        XCTAssertEqual(try plan(GoogleBooksKeyModel.id), .needsChoice(.key))
        XCTAssertEqual(try plan(SourceCatalog.tracesId), .needsChoice(.consentSheet))
    }

    func testAMissingFullDiskAccessIsNamedBeforeAnythingStarts() throws {
        let denied = SourceConnect.State(status: .off, permissions: [.fullDiskAccess: false])
        XCTAssertEqual(try plan("browser:safari", denied), .needsChoice(.permission(.fullDiskAccess)))
        XCTAssertEqual(try plan("imessage", denied), .needsChoice(.permission(.fullDiskAccess)))
        XCTAssertEqual(try plan("whatsapp", denied), .needsChoice(.permission(.fullDiskAccess)))
        // Chrome needs none, and a permission nothing has checked counts as given.
        XCTAssertEqual(try plan("browser:chrome", denied), .start([.startReader(entry: "browser:chrome")], thenOpen: false))
        XCTAssertEqual(try plan("browser:safari"), .start([.startReader(entry: "browser:safari")], thenOpen: false))
    }

    func testSourcesWithNothingOneClickCanStartJustOpen() throws {
        XCTAssertEqual(try plan("book-scan"), .openPage)
        XCTAssertEqual(try plan("files"), .openPage)
        XCTAssertEqual(try plan("chat-exports"), .openPage)
    }

    func testEveryCatalogueEntryHasAPlanAndNeverAnUnexpectedStart() throws {
        let all = SourceCatalog.entries(browsers: [chrome, safari], wisprPresent: false, hexPresent: true, overview: [])
        for entry in all {
            switch SourceConnect.plan(entry, ready) {
            case .start(let steps, _):
                XCTAssertFalse(steps.isEmpty, entry.id)
                for case .list(_, let key, _) in steps {
                    XCTAssertNotNil(entry.savedListKey ?? (entry.id == "youtube" || entry.id == SourceCatalog.substackId ? key : nil),
                                    "\(entry.id) starts a list it owns")
                }
            default: break
            }
        }
    }

    // MARK: A stream's switch

    func testTurningAStreamOffIsAlwaysOneCall() {
        XCTAssertEqual(SourceConnect.planSwitch(entry: "x", setting: "savedLists", key: "x-likes", on: false, unacknowledged),
                       .start([.list(setting: "savedLists", key: "x-likes", on: false)], thenOpen: false))
    }

    func testTurningAStreamOnNeedsTheAcknowledgementFirst() {
        XCTAssertEqual(SourceConnect.planSwitch(entry: "x", setting: "savedLists", key: "x-likes", on: true, ready),
                       .start([.list(setting: "savedLists", key: "x-likes", on: true)], thenOpen: false),
                       "a key this build has no case for is still flipped, by the contract's own words")
        XCTAssertEqual(SourceConnect.planSwitch(entry: "x", setting: "savedLists", key: "x-likes", on: true, unacknowledged),
                       .needsConsent(ReadingConsent(entryId: "x", setting: "savedLists", key: "x-likes"), now: []))
        XCTAssertEqual(SourceConnect.planSwitch(entry: "youtube", setting: "youtubeLists", key: "playlists", on: true, ready),
                       .start([.list(setting: "youtubeLists", key: "playlists", on: true)], thenOpen: false))
        XCTAssertEqual(SourceConnect.planSwitch(entry: "x", setting: "somethingNew", key: "k", on: true, ready), .openPage,
                       "a setting this build does not know sends nothing")
    }

    func testAConsentSpeaksTheTypedFormsTheSheetStillTakes() {
        XCTAssertEqual(ReadingConsent(entryId: "youtube", setting: "youtubeLists", key: "watch_later").youtubeList, .watchLater)
        XCTAssertNil(ReadingConsent(entryId: "youtube", setting: "youtubeLists", key: "playlists").youtubeList,
                     "a list with no case yet: the sheet turns it on through the model's own setSwitch")
        XCTAssertEqual(ReadingConsent(entryId: "substack", setting: "substackLists", key: "saved").substackList, .saved)
        XCTAssertEqual(ReadingConsent(entryId: "x", setting: "savedLists", key: "x").savedListKey, "x")
        XCTAssertNil(ReadingConsent(entryId: "x", setting: "savedLists", key: "x").youtubeList)
    }

    // MARK: Running a plan

    private final class Recorder {
        var events: [String] = []
        var listOK = true
        var readerOK = true
    }

    private func deps(_ r: Recorder) -> SourceConnect.Deps {
        SourceConnect.Deps(
            setList: { setting, key, on in r.events.append("list \(setting).\(key)=\(on)"); return r.listOK },
            noticeSaves: { r.events.append("notice \($0)") },
            startReader: { r.events.append("start \($0)"); return r.readerOK },
            openPage: { r.events.append("open \($0)") },
            raiseConsent: { r.events.append("consent \($0.id)") },
            lastNote: { "refused" })
    }

    func testAStartRunsEveryStepInOrderAndSaysTurnedOnOnlyAfterTheyAllReturned() async throws {
        let r = Recorder()
        let outcome = await SourceConnect.run(try plan("x"), entry: "x", deps: deps(r))
        XCTAssertEqual(r.events, ["list savedLists.x=true", "notice x"])
        XCTAssertEqual(outcome, .turnedOn)
    }

    func testARefusedWriteStopsThePlanAndSaysWhy() async throws {
        let r = Recorder()
        r.listOK = false
        let outcome = await SourceConnect.run(try plan("x"), entry: "x", deps: deps(r))
        XCTAssertEqual(r.events, ["list savedLists.x=true"], "noticing saves never goes ahead of a refused list")
        XCTAssertEqual(outcome, .failed("refused"))
    }

    func testAConsentPlanNoticesSavesRaisesTheSheetAndTurnsNothingElseOn() async throws {
        let r = Recorder()
        let outcome = await SourceConnect.run(try plan("x", unacknowledged), entry: "x", deps: deps(r))
        XCTAssertEqual(r.events, ["notice x", "consent x|savedLists.x"])
        XCTAssertEqual(outcome, .openedPage(consent: ReadingConsent(entryId: "x", setting: "savedLists", key: "x")))
    }

    func testAChoiceAndAnAlreadyOnSourceOpenThePage() async throws {
        let r = Recorder()
        let a = await SourceConnect.run(try plan("imessage"), entry: "imessage", deps: deps(r))
        XCTAssertEqual(a, .openedPage(consent: nil))
        XCTAssertEqual(r.events, ["open imessage"])
    }

    func testAMacAppStartsItsReaderAndAFailedStartIsSaid() async throws {
        let r = Recorder()
        let ok = await SourceConnect.run(try plan("notes"), entry: "notes", deps: deps(r))
        XCTAssertEqual(ok, .turnedOn)
        r.readerOK = false
        let failed = await SourceConnect.run(try plan("notes"), entry: "notes", deps: deps(r))
        XCTAssertEqual(failed, .failed("refused"))
        XCTAssertEqual(r.events, ["start notes", "start notes"])
    }

    func testGitHubNoticesSavesThenOpensItsPage() async throws {
        let r = Recorder()
        let outcome = await SourceConnect.run(try plan("github"), entry: "github", deps: deps(r))
        XCTAssertEqual(r.events, ["notice github", "open github"])
        XCTAssertEqual(outcome, .openedPage(consent: nil))
    }

    // MARK: Hoisted: the model's generic switch and the app-level hand-off

    private func model(saved: Box<[([String: Bool], Bool)]> = Box([]), youtube: Box<[[String: Bool]]> = Box([]),
                       settings: ReadingSettingsResponse = ReadingSettingsResponse(agentEnabled: true, ackCurrent: true))
        -> ReadingAgentModel {
        var d = ReadingAgentModel.Deps.live
        d.fetch = { settings }
        d.fetchSites = { ReadingSitesResponse(sites: [], enabled: true) }
        d.write = { on, _, _ in var next = settings; next.agentEnabled = on ?? next.agentEnabled; next.ackCurrent = true; return next }
        d.writeSaved = { lists, enable in
            saved.value.append((lists, enable))
            var next = settings
            next.savedLists = lists
            return next
        }
        d.writeYouTube = { patch in youtube.value.append(patch); return settings }
        return ReadingAgentModel(deps: d)
    }

    final class Box<T> { var value: T; init(_ value: T) { self.value = value } }

    func testSetSwitchWritesAKeyThisBuildHasNoCaseFor() async {
        let saved = Box<[([String: Bool], Bool)]>([])
        let youtube = Box<[[String: Bool]]>([])
        let m = model(saved: saved, youtube: youtube)
        let a = await m.setSwitch(setting: "savedLists", key: "x-likes", on: true)
        let b = await m.setSwitch(setting: "youtubeLists", key: "playlists", on: true)
        XCTAssertTrue(a && b)
        XCTAssertEqual(saved.value.first?.0, ["x-likes": true])
        XCTAssertEqual(saved.value.first?.1, false, "no acknowledgement unless the sheet's Turn on sent it")
        XCTAssertEqual(youtube.value, [["playlists": true]])
        let refused = await m.setSwitch(setting: "nope", key: "k", on: true)
        XCTAssertFalse(refused)
    }

    func testSetSwitchWithTheSheetsAcknowledgementTurnsReadingOnInTheSameCall() async {
        let saved = Box<[([String: Bool], Bool)]>([])
        let m = model(saved: saved, settings: ReadingSettingsResponse(agentEnabled: false, ackCurrent: false))
        await m.loadSettings()
        XCTAssertFalse(m.readyForLists)
        XCTAssertTrue(m.needsFirstUseSheet)
        let ok = await m.setSwitch(setting: "savedLists", key: "x", on: true, acknowledge: true)
        XCTAssertTrue(ok)
        XCTAssertEqual(saved.value.first?.1, true)
    }

    func testTheHandOffStagesTheEntryAndTheConsentAndIsReadOnce() {
        let router = AppRouter()
        let consent = ReadingConsent(entryId: "x", setting: "savedLists", key: "x")
        router.routeToConsent(consent)
        XCTAssertEqual(router.pendingCatalogEntry, "x", "the page opens on the source")
        XCTAssertEqual(router.pendingTab, .sources)
        XCTAssertEqual(router.consumeConsent(), consent)
        XCTAssertNil(router.consumeConsent(), "read once: the page's onAppear and onChange can both see it")
    }
}
