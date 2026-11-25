import XCTest
@testable import CicadaApp

/// G245 (plan section 7, 7.1; owner 2026-11-24: "make sure the notch message appears correctly and works to connect the
/// source correctly when I'm inside the app or website") — the notch's Yes goes through the one connect plan, says only
/// what is true, and the silent cases around a bookmark and a save are said or fixed.
@MainActor
final class NotchConnectTests: XCTestCase {
    private let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!
    private let safari = BrowserInventory.catalog.first { $0.id == "safari" }!

    private func entry(_ id: String) throws -> SourceCatalogEntry {
        let all = SourceCatalog.entries(browsers: [chrome, safari], wisprPresent: false, hexPresent: true, overview: [])
        return try XCTUnwrap(all.first { $0.id == id }, id)
    }

    /// A record of what a Yes did, with every closure faked.
    @MainActor
    private final class World {
        var lists: [String] = []
        var noticed: [String] = []
        var started: [String] = []
        var opened: [String] = []
        var consents: [ReadingConsent] = []
        var acknowledged: [String] = []
        var permissions: [MacPermission] = []
        var listWriteWorks = true
        var readerStarts = true
        var trusted = true
        var state = SourceConnect.State(status: .off, agentEnabled: true, ackCurrent: true)
    }

    private func connector(_ world: World) -> NotchConnector {
        NotchConnector(
            entry: { id in try? self.entry(id) },
            state: { _ in world.state },
            deps: SourceConnect.Deps(
                setList: { setting, key, on in
                    if world.listWriteWorks { world.lists.append("\(setting).\(key)=\(on)") }
                    return world.listWriteWorks
                },
                noticeSaves: { world.noticed.append($0) },
                startReader: { world.started.append($0); return world.readerStarts },
                openPage: { world.opened.append($0) },
                raiseConsent: { world.consents.append($0) },
                lastNote: { world.listWriteWorks ? nil : "Agent reading is not on." },
                acknowledgeList: { setting, key in
                    if world.listWriteWorks { world.acknowledged.append("\(setting).\(key)") }
                    return world.listWriteWorks
                }),
            accessibilityGranted: { world.trusted },
            noticing: { world.noticed.contains($0) },
            openPermission: { world.permissions.append($0) })
    }

    // MARK: - A site's Yes is the page's own plan

    func testASitesYesTurnsOnItsSavedListAndNoticingSavesThenSaysItWillAskWhy() async {
        let world = World()
        let result = await connector(world).connect("site-save:x")
        XCTAssertEqual(world.lists, ["savedLists.x=true"], "the site's existing saved list, never a new stream")
        XCTAssertEqual(world.noticed, ["x"])
        XCTAssertTrue(world.opened.isEmpty)
        XCTAssertEqual(result, .turnedOn(asksWhy: true, needsAccessibility: false))
    }

    /// Owner 2026-11-25 — "remove the opening the app after selecting connect to accept the terms. skip that part. once
    /// you connect the notch should show the checkmark animation for a bit and then disappear." The offer said what is
    /// read and the person pressed Yes, so the Yes is the acknowledgement: the list goes on with it in one write, no
    /// page opens, and the panel goes on to its ring and check.
    func testWithoutTheAcknowledgementTheYesIsTheAcknowledgementAndNoPageOpens() async {
        let world = World()
        world.state = SourceConnect.State(status: .off, agentEnabled: false, ackCurrent: false)
        let result = await connector(world).connect("site-save:instagram")
        XCTAssertEqual(world.acknowledged, ["savedLists.instagram"], "the list, turned on with the acknowledgement")
        XCTAssertTrue(world.lists.isEmpty, "never by the plain switch, which the backend would refuse")
        XCTAssertEqual(world.noticed, ["instagram"])
        XCTAssertTrue(world.consents.isEmpty, "no sheet")
        XCTAssertTrue(world.opened.isEmpty, "no page")
        XCTAssertEqual(result, .turnedOn(asksWhy: true, needsAccessibility: false))
    }

    func testAnAcknowledgementTheBackendRefusesSaysSoAndOpensNothing() async {
        let world = World()
        world.state = SourceConnect.State(status: .off, agentEnabled: false, ackCurrent: false)
        world.listWriteWorks = false
        let result = await connector(world).connect("site-save:instagram")
        XCTAssertEqual(result, .failed("Agent reading is not on."))
        XCTAssertTrue(world.consents.isEmpty)
        XCTAssertTrue(world.opened.isEmpty)
    }

    /// The page's switch and the root card are not a question that said what is read: they still raise the sheet.
    func testADoorThatIsNotTheNotchStillRaisesTheSheet() async throws {
        let world = World()
        let state = SourceConnect.State(status: .off, agentEnabled: false, ackCurrent: false)
        let plan = SourceConnect.plan(try entry("instagram"), state)
        let outcome = await SourceConnect.run(plan, entry: "instagram", deps: connector(world).deps)
        let consent = ReadingConsent(entryId: "instagram", setting: "savedLists", key: "instagram")
        XCTAssertEqual(outcome, .openedPage(consent: consent))
        XCTAssertEqual(world.consents, [consent])
        XCTAssertTrue(world.acknowledged.isEmpty)
    }

    func testWithoutAccessibilityTheWordsSayItInsteadOfPromisingTheQuestion() async {
        let world = World()
        world.trusted = false
        let result = await connector(world).connect("site-save:reddit")
        XCTAssertEqual(world.noticed, ["reddit"])
        XCTAssertEqual(result, .turnedOn(asksWhy: false, needsAccessibility: true))
    }

    func testASiteWithNoSaveControlTurnsOnItsListAndPromisesNoQuestion() async {
        let world = World()
        let result = await connector(world).connect("site-save:linkedin")
        XCTAssertEqual(world.lists, ["savedLists.linkedin=true"])
        XCTAssertTrue(world.noticed.isEmpty, "there is no save control to notice")
        XCTAssertEqual(result, .turnedOn(asksWhy: false, needsAccessibility: false))
    }

    func testGitHubNoticesSavesAndOpensItsPageForTheSignIn() async {
        let world = World()
        let result = await connector(world).connect("site-save:github")
        XCTAssertEqual(world.noticed, ["github"])
        XCTAssertEqual(world.opened, ["github"])
        XCTAssertEqual(result, .openedPage)
    }

    func testARefusedWriteIsSaidAndNothingIsClaimed() async {
        let world = World()
        world.listWriteWorks = false
        let result = await connector(world).connect("site-save:x")
        XCTAssertEqual(result, .failed("Agent reading is not on."))
        XCTAssertTrue(world.noticed.isEmpty)
    }

    // MARK: - A Mac app's Yes

    func testAMacAppsYesStartsItsReaderWhenOneClickCan() async throws {
        let world = World()
        let result = await connector(world).connect("notes")
        XCTAssertEqual(world.started, ["notes"])
        XCTAssertTrue(world.opened.isEmpty, "no page: nothing needs choosing")
        XCTAssertEqual(result, .turnedOn(asksWhy: false, needsAccessibility: false))
        world.readerStarts = false
        let refused = await connector(world).connect("calendar-local")
        XCTAssertEqual(refused, .failed(nil))
        let chromeStart = await connector(world).connect("browser:chrome")
        XCTAssertEqual(chromeStart, .failed(nil))
        XCTAssertEqual(world.started, ["notes", "calendar-local", "browser:chrome"])
    }

    func testAChoiceOrAPermissionOpensThePageOrSettingsAndStartsNothing() async {
        let world = World()
        let chats = await connector(world).connect("whatsapp")
        XCTAssertEqual(chats, .openedPage)
        XCTAssertEqual(world.opened, ["whatsapp"])
        world.state = SourceConnect.State(status: .off, agentEnabled: true, ackCurrent: true,
                                          permissions: [.fullDiskAccess: false])
        world.opened = []
        let safariYes = await connector(world).connect("browser:safari")
        XCTAssertEqual(safariYes, .openedPage)
        XCTAssertEqual(world.permissions, [.fullDiskAccess], "Safari's Yes lands on the permission's own row")
        XCTAssertTrue(world.started.isEmpty)
        XCTAssertTrue(world.opened.isEmpty)
    }

    func testASourceTheCataloguesAlreadyConnectedJustOpensItsPage() async {
        let world = World()
        world.state = SourceConnect.State(status: .connected, agentEnabled: true, ackCurrent: true)
        let result = await connector(world).connect("site-save:x")
        XCTAssertEqual(result, .openedPage)
        XCTAssertTrue(world.lists.isEmpty)
        XCTAssertTrue(world.noticed.isEmpty)
    }

    // MARK: - One truth: the catalogue's word decides, never a per-Mac flag alone

    func testASourceThePageShowsAsSetUpIsNeverOfferedAndNotListenedTo() throws {
        let center = ConnectSuggestCenter(store: ConnectSuggestStore(defaults: TestDefaults.suite("Notch.\(UUID())")!),
                                          wait: { _ in }, ticks: false)
        center.memoryKnown = { true }
        center.setUp = { true }
        center.isDemo = { false }
        center.iconFor = { _ in nil }
        let site = try XCTUnwrap(SiteSaveSite.named("x"))
        for status in [SourceCatalogStatus.connected, .waitingForAgent, .needsSignIn] {
            center.status = { _ in status }
            XCTAssertFalse(center.listens(site: "x"), "\(status): a save click is not even read")
            center.offer(site: site, connected: false, pid: 1, bundleId: "com.google.Chrome")
            XCTAssertNil(center.state, "\(status)")
            XCTAssertEqual(center.lastDecision, .skip(.setUp))
        }
        center.status = { _ in nil }
        XCTAssertTrue(center.offer(site: site, connected: false, pid: 1, bundleId: "com.google.Chrome") == false,
                      "the catalogue not loaded yet: the visit is not spent")
        XCTAssertEqual(center.lastDecision, .skip(.noEntry))
    }

    func testTheNotchReadsAListTheCatalogueReadsAsOnLikeThePage() throws {
        let overview: [SourceOverview] = []
        let on = ConnectSuggestApps.Reading(savedListsOn: ["x"])
        XCTAssertEqual(ConnectSuggestApps.status(of: "site-save:x", channels: [], overview: overview, localReaders: [:],
                                                 reading: on), .waitingForAgent,
                       "a list turned on is the source's state, never Off")
        XCTAssertEqual(ConnectSuggestApps.status(of: "x", channels: [], overview: overview, localReaders: [:]), .off)
        XCTAssertNil(ConnectSuggestApps.entry(of: "no-such", overview: overview))
        XCTAssertEqual(ConnectSuggestApps.entry(of: "site-save:linkedin", overview: overview)?.id, "linkedin")
    }

    // MARK: - A site that is only a source may be offered, by its address alone

    func testSitesWithNoSaveControlAreOfferedButNeverReadForASave() throws {
        let keys = SiteSaveSite.offerOnly.map(\.key)
        XCTAssertEqual(Set(keys), ["linkedin", "pinterest", SourceCatalog.substackId, "spotify", "goodreads"])
        for key in keys {
            XCTAssertNil(SiteSaveSite.named(key), "\(key) has no save table: no save click is read")
            XCTAssertFalse(try XCTUnwrap(SiteSaveSite.offered(key)).hasSaveControl)
            XCTAssertEqual(ConnectSuggestApps.site(key).kind, .savedList)
            XCTAssertNotNil(try? entry(key), "\(key) is a catalogue entry, so its Yes is the page's own plan")
        }
        XCTAssertEqual(SiteSaveSite.offered.first { $0.onHost("https://www.linkedin.com/feed/") }?.key, "linkedin")
        XCTAssertEqual(SiteSaveSite.offered.first { $0.onHost("https://open.spotify.com/playlist/1") }?.key, "spotify")
        XCTAssertNil(SiteSaveSite.offered.first { $0.onHost("https://notlinkedin.com/") })
        XCTAssertEqual(ConnectSuggestApps.site("x").kind, .saves)
        XCTAssertTrue(SiteSaveSite.all.allSatisfy(\.hasSaveControl) || SiteSaveSite.all.contains { $0.menu != nil })
    }

    // MARK: - The panel: Turning on, then what it came to

    private let site = ConnectSuggestApps.site("x")
    private let u0: TimeInterval = 5_000

    private func panel(_ target: ConnectSuggestApps.Target? = nil) -> ConnectSuggestPanelState {
        ConnectSuggestPanelState(target: target ?? site, appName: "X", bundleId: "com.google.Chrome", shownAt: u0)
    }

    func testYesIsNotAnAnswerUntilWhatItDidIsKnown() {
        var state = panel()
        XCTAssertNil(state.handle(.yes, at: u0 + 1))
        XCTAssertTrue(state.isConnecting)
        XCTAssertEqual(ConnectSuggestPanelView.title(state), Copy.ConnectSuggest.turningOn)
        XCTAssertNil(state.handle(.no, at: u0 + 2), "the buttons are gone once Yes is pressed")
        XCTAssertNil(state.handle(.tick, at: u0 + 1 + ConnectSuggestPolicy.confirmShow + 1), "still turning on")
        XCTAssertNil(state.finish(.turnedOn(asksWhy: true, needsAccessibility: false), at: u0 + 3))
        XCTAssertEqual(ConnectSuggestPanelView.title(state), "Turned on")
        XCTAssertEqual(ConnectSuggestPanelView.line(state), "Saving on X will ask why.")
        XCTAssertNil(state.handle(.tick, at: u0 + 3 + ConnectSuggestPolicy.confirmShow - 0.1))
        XCTAssertEqual(state.handle(.tick, at: u0 + 3 + ConnectSuggestPolicy.confirmShow), .yes)
    }

    func testAPageOpenedLeavesAtOnceAndARefusalStaysThenIsNotNow() {
        var opened = panel()
        _ = opened.handle(.yes, at: u0 + 1)
        XCTAssertEqual(opened.finish(.openedPage, at: u0 + 2), .yes, "the page is the answer")

        var refused = panel()
        _ = refused.handle(.yes, at: u0 + 1)
        XCTAssertNil(refused.finish(.failed(nil), at: u0 + 2))
        XCTAssertEqual(ConnectSuggestPanelView.title(refused), Copy.ConnectSuggest.couldntTurnOn)
        XCTAssertEqual(ConnectSuggestPanelView.line(refused), Copy.ConnectSuggest.tryOnSources)
        XCTAssertFalse(ConnectSuggestPanelView.turnedOn(refused), "no ring, no check")
        XCTAssertNil(refused.handle(.tick, at: u0 + 2 + ConnectSuggestPolicy.confirmShow + 0.1))
        let outcome = refused.handle(.tick, at: u0 + 2 + ConnectSuggestPolicy.noteShow)
        XCTAssertEqual(outcome, .notNow, "a Yes that did nothing is offered again, never counted as Yes")
        XCTAssertEqual(outcome?.answer, .notNow)
    }

    func testWithoutAccessibilityThePanelSaysSoKeepsItAndOffersTheSetting() {
        var state = panel()
        _ = state.handle(.yes, at: u0 + 1)
        _ = state.finish(.turnedOn(asksWhy: false, needsAccessibility: true), at: u0 + 2)
        XCTAssertEqual(ConnectSuggestPanelView.line(state), "Seeing saves on X needs Accessibility.")
        XCTAssertTrue(ConnectSuggestPanelView.hasButtons(state), "the one button: Open Settings")
        XCTAssertNil(state.handle(.hover(true), at: u0 + 3))
        XCTAssertNil(state.handle(.tick, at: u0 + 60), "the pointer on it holds it")
        XCTAssertEqual(state.handle(.openSetting, at: u0 + 61), .yes)
        var plain = panel()
        _ = plain.handle(.yes, at: u0 + 1)
        _ = plain.finish(.turnedOn(asksWhy: true, needsAccessibility: false), at: u0 + 2)
        XCTAssertNil(plain.handle(.openSetting, at: u0 + 3), "no setting is named, none is opened")
        XCTAssertFalse(ConnectSuggestPanelView.hasButtons(plain))
    }

    func testAYesThatNeverReturnsLeavesAfterTheBoundAndLeavingKeepsAYes() {
        var state = panel()
        _ = state.handle(.yes, at: u0 + 1)
        XCTAssertNil(state.handle(.tick, at: u0 + ConnectSuggestPolicy.connectBound - 1))
        XCTAssertEqual(state.handle(.tick, at: u0 + 1 + ConnectSuggestPolicy.connectBound), .timedOut)
        var left = panel()
        _ = left.handle(.yes, at: u0 + 1)
        XCTAssertEqual(left.handle(.superseded, at: u0 + 2), .yes, "what it started goes on")
        var refused = panel()
        _ = refused.handle(.yes, at: u0 + 1)
        _ = refused.finish(.failed("no"), at: u0 + 2)
        XCTAssertEqual(refused.handle(.superseded, at: u0 + 3), .notNow)
    }

    func testTheWordsPromiseOnlyWhatIsTrue() {
        let reads = Copy.ConnectSuggest.reads(site)
        XCTAssertTrue(reads.contains("saved list"), reads)
        XCTAssertLessThan(reads.count, 56, "one line in the notch")
        XCTAssertFalse(Copy.ConnectSuggest.reads(ConnectSuggestApps.site("github")).contains("saved list"),
                       "GitHub has no list to read")
        XCTAssertFalse(Copy.ConnectSuggest.turnedOn.localizedCaseInsensitiveContains("connected"))
        var state = panel(ConnectSuggestApps.site("linkedin"))
        _ = state.handle(.yes, at: u0 + 1)
        _ = state.finish(.turnedOn(asksWhy: false, needsAccessibility: false), at: u0 + 2)
        XCTAssertFalse(ConnectSuggestPanelView.line(state).contains("ask why"), "no save control: no question")
    }

    // MARK: - The center: the Yes runs, the saves follow it, a refusal keeps nothing

    private final class Presenter: ConnectSuggestPresenting {
        var shows = 0, hides = 0
        func show(_ center: ConnectSuggestCenter) { shows += 1 }
        func hide() { hides += 1 }
    }

    private func candidate(_ url: String) -> SiteSaveCandidate {
        SiteSaveCandidate(item: SiteSaveItem(site: "github", origin: "github-starred", url: url, title: "alpha/beta"),
                          outcome: .saved, text: "", folder: nil, lesson: nil)
    }

    private func readyCenter(_ clock: Date) -> (ConnectSuggestCenter, Presenter, () -> Void) {
        var now = clock
        let center = ConnectSuggestCenter(store: ConnectSuggestStore(defaults: TestDefaults.suite("Notch.\(UUID())")!),
                                          now: { now }, uptime: { now.timeIntervalSince1970 }, wait: { _ in },
                                          ticks: false)
        now = now.addingTimeInterval(3600)
        let presenter = Presenter()
        center.attach(presenter: presenter)
        center.memoryKnown = { true }
        center.setUp = { true }
        center.isDemo = { false }
        center.status = { _ in .off }
        center.iconFor = { _ in nil }
        return (center, presenter, { now = now.addingTimeInterval(1) })
    }

    func testARefusedYesKeepsNoSaveAndIsOfferedAgain() async throws {
        let (center, _, advance) = readyCenter(Date(timeIntervalSince1970: 1_800_000_000))
        let site = try XCTUnwrap(SiteSaveSite.named("github"))
        var kept = 0
        center.onHeld = { kept += $0.count }
        center.connect = { _ in .failed("Agent reading is not on.") }
        center.offer(saved: candidate("https://github.com/alpha/beta"), site: site, pid: 7, bundleId: "com.google.Chrome")
        advance()
        center.input(.yes)
        await center.settle()
        XCTAssertEqual(kept, 0, "a Yes that turned nothing on keeps nothing")
        XCTAssertEqual(center.store.memory.sources["site-save:github"]?.answer, .notNow)
        XCTAssertEqual(ConnectSuggestPanelView.line(try XCTUnwrap(center.state)), "Agent reading is not on.")
    }

    func testASaveHeldWhenThePanelLeftBeforeTheYesReturnedIsKeptWhenItDoes() async throws {
        let (center, _, advance) = readyCenter(Date(timeIntervalSince1970: 1_800_000_000))
        let site = try XCTUnwrap(SiteSaveSite.named("github"))
        var kept: [SiteSaveCandidate] = []
        center.onHeld = { kept += $0 }
        let gate = AsyncGate()
        center.connect = { _ in await gate.wait(); return .turnedOn(asksWhy: true, needsAccessibility: false) }
        let first = candidate("https://github.com/alpha/beta")
        center.offer(saved: first, site: site, pid: 7, bundleId: "com.google.Chrome")
        advance()
        center.input(.yes)
        // A save made while the Yes is still turning things on is held too, then the ask-why question takes the notch.
        let second = candidate("https://github.com/alpha/gamma")
        center.offer(saved: second, site: site, pid: 7, bundleId: "com.google.Chrome")
        center.input(.superseded)
        XCTAssertNil(center.state)
        XCTAssertTrue(kept.isEmpty, "not before it is turned on")
        await gate.open()
        await center.settle()
        XCTAssertEqual(kept, [first, second])
        XCTAssertEqual(center.store.memory.sources["site-save:github"]?.answer, .yes)
    }

    func testTheSettingButtonOpensAccessibilityAndNothingElse() async {
        let (center, _, advance) = readyCenter(Date(timeIntervalSince1970: 1_800_000_000))
        var opened: [MacPermission] = []
        center.openSetting = { opened.append($0) }
        center.connect = { _ in .turnedOn(asksWhy: false, needsAccessibility: true) }
        center.offer(site: SiteSaveSite.x, connected: false, pid: 7, bundleId: "com.google.Chrome")
        advance()
        center.input(.yes)
        await center.settle()
        center.input(.openSetting)
        XCTAssertEqual(opened, [.accessibility])
        XCTAssertNil(center.state)
    }

    func testTheSavesYouMakeRowSaysItAsksWhyOnlyWhenItWill() {
        var stream = SourceStream(id: "x.saves", label: Copy.Streams.savesYouMake, kind: .other("saves"), how: .click,
                                  owner: .app, control: .switch, state: .on)
        XCTAssertEqual(SourceStreamRow.line(stream), Copy.Streams.lineClickAsks)
        stream.why = Copy.Streams.accessibilityWhy       // Accessibility missing: the row's own sentence leads
        XCTAssertEqual(SourceStreamRow.line(stream), Copy.Streams.lineClick)
        stream.why = nil
        stream.state = .off
        XCTAssertEqual(SourceStreamRow.line(stream), Copy.Streams.lineClick)
    }

    // MARK: - The silent cases around a bookmark

    func testTheAskWhySwitchSaysWhetherThisBrowserIsWatched() {
        typealias Lines = BrowserAskWhyLine
        XCTAssertEqual(Lines.lines(name: "Chrome", askWhy: false, watched: true, otherProfile: false).map(\.text),
                       [Copy.SaveWhy.askWhyOff])
        let notWatched = Lines.lines(name: "Safari", askWhy: true, watched: false, otherProfile: false)
        XCTAssertEqual(notWatched.map(\.text), [Copy.SaveWhy.askWhyNotWatched("Safari")])
        XCTAssertTrue(notWatched[0].isAttention)
        let asking = Lines.lines(name: "Chrome", askWhy: true, watched: true, otherProfile: false)
        XCTAssertEqual(asking.map(\.text), [Copy.SaveWhy.askingHere("Chrome")])
        XCTAssertFalse(asking[0].isAttention)
        let profile = Lines.lines(name: "Chrome", askWhy: true, watched: true, otherProfile: true)
        XCTAssertEqual(profile.map(\.text), [Copy.SaveWhy.otherProfile("Chrome")])
    }

    func testTheChromeProfileInUseIsReadFromLocalState() throws {
        let state = Data(#"{"profile":{"last_used":"Profile 2","info_cache":{}}}"#.utf8)
        XCTAssertEqual(ChromeProfile.lastUsed(inLocalState: state), "Profile 2")
        XCTAssertFalse(ChromeProfile.isRead("Profile 2"))
        XCTAssertTrue(ChromeProfile.isRead("Default"))
        XCTAssertTrue(ChromeProfile.isRead(nil), "no Local State is Chrome with one profile")
        XCTAssertNil(ChromeProfile.lastUsed(inLocalState: Data("not json".utf8)))
        XCTAssertNil(ChromeProfile.lastUsed(inLocalState: Data("{}".utf8)))
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("chrome-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let file = dir.appendingPathComponent("Local State")
        try state.write(to: file)
        XCTAssertEqual(ChromeProfile.inUse(at: file), "Profile 2")
        XCTAssertNil(ChromeProfile.inUse(at: dir.appendingPathComponent("missing")))
    }

    func testABookmarkWithNoInstantIsAskedAboutOnlyWhenItsBrowserWasInFront() {
        func result(addedAt: String?) -> BookmarkSyncResult {
            var r = BookmarkSyncResult(new: 1, skipped: 0, sources: [])
            r.fresh = [FreshBookmark(url: "https://alpha.example/a", title: "A", origin: "safari-bookmark",
                                     channel: "safari-bookmarks", episodeId: "", addedAt: addedAt)]
            r.freshTotal = 1
            return r
        }
        func decide(_ r: BookmarkSyncResult, witnessed: Bool) -> SaveWhyPolicy.Decision {
            SaveWhyPolicy.decide(.init(enabled: true, live: true, result: r, now: Date(), lastAsked: nil,
                                       mutedHosts: [], writing: false, witnessed: witnessed))
        }
        XCTAssertEqual(decide(result(addedAt: nil), witnessed: false), .skip(.notRecent),
                       "a bookmark that synced in from another device: no instant, nobody there")
        if case .ask = decide(result(addedAt: nil), witnessed: true) {} else { XCTFail("the person was in Safari") }
        let now = ISO8601DateFormatter().string(from: Date())
        if case .ask = decide(result(addedAt: now), witnessed: false) {} else { XCTFail("an instant stands for itself") }
        XCTAssertTrue(SaveWhyCenter.browserInFront(channel: "safari-bookmarks", front: "com.apple.Safari"))
        XCTAssertFalse(SaveWhyCenter.browserInFront(channel: "safari-bookmarks", front: "com.google.Chrome"))
        XCTAssertTrue(SaveWhyCenter.browserInFront(channel: "chrome-bookmarks", front: nil), "Chrome dates its own")
        XCTAssertTrue(SaveWhyCenter.browserInFront(channel: "x-bookmarks", front: nil), "a site's own source has no browser")
    }
}

/// A gate a test opens by hand, so an async closure can be held while the test acts.
private actor AsyncGate {
    private var opened = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    func wait() async {
        if opened { return }
        await withCheckedContinuation { waiters.append($0) }
    }
    func open() {
        opened = true
        waiters.forEach { $0.resume() }
        waiters = []
    }
}
