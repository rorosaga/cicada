import Observation
import XCTest
@testable import CicadaApp

/// G221, G245 (ruling 77, owner 2026-11-24: "i just bookmarked an x post and nothing happened with the notch or anything.
/// same with the rest of sources") — a site whose saved list is on is a connected site: the person's own save clicks there
/// are noticed unless THEY turned "Saves you make" off for it. Before, "set up" (the page's word) and "noticed" (a second,
/// per-Mac flag only the notch's Yes or a switch ever set) were two facts, and a list turned on from the Sources page left
/// a dead site: a click read nowhere, offered nowhere, asked about nowhere, said nowhere.
///
/// The sweep at the end walks every combination of what decides what a save click does and pins two things for each: what
/// the click does, and that the Sources page's "Saves you make" row never says the opposite.
@MainActor
final class SiteSaveNoticingTests: XCTestCase {
    private let t0 = Date(timeIntervalSince1970: 1_800_000_000)
    private let day: TimeInterval = 24 * 3600

    private func prefs(_ file: String = #function) -> SiteSavePrefs {
        SiteSavePrefs(defaults: TestDefaults.suite("SiteSaveNoticingTests.\(file).\(UUID().uuidString)")!)
    }

    // MARK: - Connected means noticed

    func testASiteWhoseListIsOnIsNoticedWithNoSwitchEverTouched() {
        let prefs = prefs()
        for site in SiteSaveSite.all {
            XCTAssertNil(prefs.explicit(site.key), "nothing was ever set for \(site.key)")
            for status in [SourceCatalogStatus.connected, .waitingForAgent, .needsSignIn] {
                XCTAssertTrue(prefs.noticing(site.key, status: status), "\(site.key) \(status)")
            }
            XCTAssertFalse(prefs.noticing(site.key, status: .off), "an Off site is the connect offer's, not noticed")
            XCTAssertFalse(prefs.noticing(site.key, status: nil), "a source not read yet is never assumed on")
        }
        XCTAssertEqual(prefs.noticed(status: { _ in .waitingForAgent }).map(\.key), SiteSaveSite.all.map(\.key))
        XCTAssertEqual(prefs.noticed(status: { $0 == "x" ? .connected : .off }).map(\.key), ["x"])
    }

    /// The install the owner has: lists turned on weeks ago, no `cicada.siteSaves.connected.*` key. The first launch of
    /// this build reads it as on and writes nothing — there is no migration for anyone to see or to fail.
    func testAnInstallWithListsOnAlreadyNoticesThemOnFirstRunAndWritesNothing() {
        let defaults = TestDefaults.suite("SiteSaveNoticingTests.install.\(UUID().uuidString)")!
        let before = Set(defaults.dictionaryRepresentation().keys)
        let prefs = SiteSavePrefs(defaults: defaults)
        XCTAssertEqual(prefs.noticed(status: { $0 == "x" ? .connected : .off }).map(\.key), ["x"])
        XCTAssertEqual(Set(defaults.dictionaryRepresentation().keys), before, "reading is not a migration")
    }

    func testTheOffThePersonSetStaysOffAcrossLaunchesAndTheListBeingToggled() {
        let defaults = TestDefaults.suite("SiteSaveNoticingTests.off.\(UUID().uuidString)")!
        SiteSavePrefs(defaults: defaults).setConnected("x", false)
        // A launch later (a new value over the same defaults), with the list turned on, off, and on again.
        for status in [SourceCatalogStatus.connected, .off, .waitingForAgent, .connected, .needsSignIn] {
            let launch = SiteSavePrefs(defaults: defaults)
            XCTAssertEqual(launch.explicit("x"), false, "\(status)")
            XCTAssertFalse(launch.noticing("x", status: status), "\(status)")
        }
        XCTAssertEqual(SiteSavePrefs(defaults: defaults).turnedOff, ["x"])
        // Never set is not the same as off: another site, never touched, still follows its source.
        XCTAssertNil(SiteSavePrefs(defaults: defaults).explicit("instagram"))
        XCTAssertTrue(SiteSavePrefs(defaults: defaults).noticing("instagram", status: .connected))
    }

    func testAnOnThePersonSetStandsWhenTheListGoesOff() {
        let prefs = prefs()
        prefs.setConnected("github", true)
        XCTAssertTrue(prefs.noticing("github", status: .off))
        XCTAssertTrue(prefs.noticing("github", status: .connected))
        XCTAssertTrue(prefs.turnedOff.isEmpty)
        // Turning it off and on again is the person's own word each time; off does not decay back to "never set".
        prefs.setConnected("github", false)
        XCTAssertEqual(prefs.explicit("github"), false)
    }

    func testTheKeysTheOverlayAndThePlanReadFollowTheCataloguesRows() {
        func row(_ id: String, _ status: SourceCatalogStatus) -> SourceCatalogRow {
            let entry = SourceCatalog.entries(browsers: [], wisprPresent: false, hexPresent: false, overview: [])
                .first { $0.id == id }!
            return SourceCatalogRow(entry: entry, status: status, lastSync: nil, notInstalled: false,
                                    countsAsConnected: true, waitingOn: nil, suggested: false, browser: nil)
        }
        let prefs = prefs()
        XCTAssertEqual(prefs.noticedKeys(rows: [row("x", .waitingForAgent), row("reddit", .off), row("github", .connected)]),
                       ["x", "github"])
        prefs.setConnected("github", false)
        XCTAssertEqual(prefs.noticedKeys(rows: [row("x", .waitingForAgent), row("github", .connected)]), ["x"])
    }

    func testEverySiteWithASaveControlHasACatalogueSourceOfTheSameKey() {
        let ids = Set(SourceCatalog.entries(browsers: [], wisprPresent: false, hexPresent: false, overview: []).map(\.id))
        for site in SiteSaveSite.all {
            XCTAssertTrue(ids.contains(site.key), "\(site.key) is a source, so its status can say whether it is set up")
            XCTAssertTrue(site.hasSaveControl, site.key)
        }
        // The sites that are sources only keep no save table and no "Saves you make" row: nothing to notice.
        for site in SiteSaveSite.offerOnly { XCTAssertFalse(site.hasSaveControl, site.key) }
        XCTAssertEqual(SiteSaveSite.all.map(\.key), ["x", "instagram", "github", "tiktok", "reddit", "youtube"])
    }

    // MARK: - The watcher follows the source

    @Observable
    @MainActor
    final class FakeCatalogue {
        var status: SourceCatalogStatus? = nil
    }

    func testTheWatcherIsToldWhenTheCataloguesWordMovesAndNotBefore() async {
        let catalogue = FakeCatalogue()
        let prefs = prefs()
        let watch = SiteSaveNoticingWatch()
        var told = 0
        watch.read = { Set(prefs.noticed(status: { $0 == "x" ? catalogue.status : nil }).map(\.key)) }
        watch.changed = { told += 1 }
        watch.start()
        XCTAssertEqual(watch.last, [], "launch: the catalogue is not read yet")
        XCTAssertEqual(told, 0, "the watcher starts from the same look; only a later move needs telling")

        catalogue.status = .waitingForAgent        // the list turned on from the Sources page
        await settle { told == 1 }
        XCTAssertEqual(watch.last, ["x"])
        catalogue.status = .connected              // the first read lands: still noticed, nothing to say
        await settle { false }
        XCTAssertEqual(told, 1)
        catalogue.status = .off                    // the list turned off
        await settle { told == 2 }
        XCTAssertEqual(watch.last, [])
    }

    func testSettleSaysNothingForTheSameSetTwice() {
        let watch = SiteSaveNoticingWatch()
        var told = 0
        watch.changed = { told += 1 }
        watch.settle([])
        watch.settle([])
        watch.settle(["x"])
        watch.settle(["x"])
        XCTAssertEqual(told, 1)
    }

    private func settle(until done: () -> Bool) async {
        for _ in 0..<40 {
            if done() { return }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
    }

    // MARK: - Where the watcher looks

    func testABrowserCicadaReadsIsWatchedOnlyWithAccessibilityAndAReasonToLook() {
        typealias W = SiteSaveWatcher
        XCTAssertEqual(W.arming(bundle: "com.google.Chrome", wanted: true, trusted: true), .watches)
        XCTAssertEqual(W.arming(bundle: "com.google.Chrome", wanted: true, trusted: false), .noAccessibility,
                       "never prompted for: the page's row says it")
        XCTAssertEqual(W.arming(bundle: "com.google.Chrome", wanted: false, trusted: true), .notWatched)
        XCTAssertEqual(W.arming(bundle: nil, wanted: true, trusted: true), .notWatched)
        // A browser Cicada does not read (named on the Browsers page, never offered a switch) is not watched.
        for spec in BrowserInventory.catalog {
            XCTAssertEqual(W.arming(bundle: spec.bundleId, wanted: true, trusted: true),
                           spec.supported ? .watches : .notWatched, spec.id)
        }
        XCTAssertEqual(W.arming(bundle: "com.apple.finder", wanted: true, trusted: true), .notWatched)
    }

    // MARK: - What the row says

    private func row(_ site: String, noticed: Bool, off: Bool = false, accessibility: Bool = true) -> ResolvedStream {
        let stream = SourceStream(id: site + ".saves", label: Copy.Streams.savesYouMake, kind: .other("saves"),
                                  how: .click, owner: .app, control: .switch, state: .off)
        let app = StreamAppState(siteSavesOn: noticed ? [site] : [], siteSavesOff: off ? [site] : [],
                                 permissions: [.accessibility: accessibility])
        return SourceStreamOverlay.resolve(stream, of: site, entry: nil, app: app, readerKeys: [], now: t0)
    }

    func testAConnectedSitesRowShowsOnAndATurnedOffOneSaysThePersonDidIt() {
        XCTAssertEqual(row("x", noticed: true).word, .read)
        XCTAssertEqual(row("x", noticed: true).stream.state, .on)
        let off = row("x", noticed: false, off: true)
        XCTAssertEqual(off.word, .off)
        XCTAssertEqual(off.stream.why, Copy.Streams.savesTurnedOff)
        XCTAssertEqual(SourceStreamRow.line(off.stream), Copy.Streams.savesTurnedOff,
                       "off by the person's own word is said, not left as a bare off")
        // Off because the site is not set up is plain off: the connect offer, or the switch, is what turns it on.
        let notSetUp = row("x", noticed: false)
        XCTAssertEqual(notSetUp.word, .off)
        XCTAssertNil(notSetUp.stream.why)
        XCTAssertEqual(SourceStreamRow.line(notSetUp.stream), Copy.Streams.lineClick)
        XCTAssertEqual(SourceStreamRow.line(row("x", noticed: true).stream), Copy.Streams.lineClickAsks)
    }

    func testTheRowNamesTheBrowsersASaveIsSeenIn() {
        let help = SourceStreamRow.help(row("x", noticed: true).stream)
        XCTAssertEqual(help, Copy.Streams.savesSeenIn(SourceStreamRow.supportedBrowserNames))
        for spec in BrowserInventory.catalog where spec.supported {
            XCTAssertTrue(SourceStreamRow.supportedBrowserNames.contains(spec.name), spec.id)
        }
        for spec in BrowserInventory.catalog where !spec.supported {
            XCTAssertFalse(SourceStreamRow.supportedBrowserNames.contains(spec.name), spec.id)
        }
    }

    // MARK: - The sweep: what a save click does, for every combination

    /// What a person's own click on a site's save control comes to.
    enum Click: Equatable, CustomStringConvertible {
        case asksWhy
        case offersConnect
        case nothing(Why)
        var description: String {
            switch self {
            case .asksWhy: "asks why"
            case .offersConnect: "offers to connect"
            case .nothing(let why): "nothing (\(why))"
            }
        }
    }

    /// Why a click did nothing — each one is something the Sources page says, or is the site being Off.
    enum Why: Equatable {
        /// Noticing is on, Accessibility is not given: the row says so, with the button.
        case noAccessibility
        /// A browser Cicada does not read is in front: the row's hover and the Browsers page name the ones it reads.
        case browserNotRead
        /// The person turned "Saves you make" off for the site: the row says so.
        case turnedOff
        /// The site is Off and nothing can offer: Accessibility missing, the offer switch off, answered No or Yes, or
        /// shown its last time, or inside a wait. The row reads Off, with its switch.
        case siteOffNoOffer
    }

    struct Case {
        var site: String
        var status: SourceCatalogStatus?
        var explicit: Bool?
        var accessibility: Bool
        var memory: Memory
        var offerSwitch: Bool
        var browser: String
    }

    enum Memory: CaseIterable {
        case never, yes, no, notNowWaiting, notNowWaited, shownItsLastTime

        func apply(_ id: String, now: Date) -> ConnectSuggestMemory {
            let day: TimeInterval = 24 * 3600
            var memory = ConnectSuggestMemory()
            switch self {
            case .never: break
            case .yes:
                memory = ConnectSuggestPolicy.shown(id, at: now.addingTimeInterval(-3 * day), in: memory)
                memory = ConnectSuggestPolicy.answered(id, .yes, at: now.addingTimeInterval(-3 * day), in: memory)
            case .no:
                memory = ConnectSuggestPolicy.shown(id, at: now.addingTimeInterval(-3 * day), in: memory)
                memory = ConnectSuggestPolicy.answered(id, .no, at: now.addingTimeInterval(-3 * day), in: memory)
            case .notNowWaiting:
                memory = ConnectSuggestPolicy.shown(id, at: now.addingTimeInterval(-600), in: memory)
                memory = ConnectSuggestPolicy.answered(id, .notNow, at: now.addingTimeInterval(-600), in: memory)
            case .notNowWaited:
                memory = ConnectSuggestPolicy.shown(id, at: now.addingTimeInterval(-3 * day), in: memory)
                memory = ConnectSuggestPolicy.answered(id, .notNow, at: now.addingTimeInterval(-3 * day), in: memory)
            case .shownItsLastTime:
                for i in 0..<ConnectSuggestPolicy.maxShows {
                    memory = ConnectSuggestPolicy.shown(id, at: now.addingTimeInterval(-Double(40 - i) * day), in: memory)
                }
                memory = ConnectSuggestPolicy.answered(id, .notNow, at: now.addingTimeInterval(-30 * day), in: memory)
            }
            return memory
        }
    }

    /// What a click does, by asking the real parts in the order the app asks them: whether the browser is watched
    /// (`SiteSaveWatcher.arming`), whether the site is noticed (`SiteSavePrefs.noticing`), and whether the connect
    /// offer could show for a site that is not (`ConnectSuggestCenter.listens`, then the policy's save-click decision).
    private lazy var sweepPrefs = SiteSavePrefs(defaults: TestDefaults.suite("SiteSaveNoticingTests.sweepPrefs.\(UUID().uuidString)")!)
    private lazy var sweepStore = ConnectSuggestStore(defaults: TestDefaults.suite("SiteSaveNoticingTests.sweepStore.\(UUID().uuidString)")!)

    /// The same two scratch defaults for the whole sweep, cleared for each combination (a suite per row took seconds).
    private func fresh(_ c: Case) -> SiteSavePrefs {
        let key = "\(c.site)|\(String(describing: c.explicit))"
        guard key != sweepPrefsKey else { return sweepPrefs }
        sweepPrefsKey = key
        sweepPrefs.defaults.removeObject(forKey: SiteSavePrefs.connectedKey(c.site))
        if let explicit = c.explicit { sweepPrefs.setConnected(c.site, explicit) }
        return sweepPrefs
    }

    private var sweepMemoryKey = ""
    private var sweepPrefsKey = ""
    private lazy var sweepCenter: ConnectSuggestCenter = {
        let center = ConnectSuggestCenter(store: sweepStore, now: { [t0] in t0 }, ticks: false)
        center.memoryKnown = { true }
        center.setUp = { true }
        center.isDemo = { false }
        return center
    }()

    private func click(_ c: Case) -> Click {
        let prefs = fresh(c)
        let id = ConnectSuggestApps.site(c.site).entryId
        let store = sweepStore
        // The store is written only when the combination's memory changes (the defaults are the slow part).
        if sweepMemoryKey != "\(id)|\(c.memory)|\(c.offerSwitch)" {
            sweepMemoryKey = "\(id)|\(c.memory)|\(c.offerSwitch)"
            store.enabled = c.offerSwitch
            store.memory = c.memory.apply(id, now: t0)
        }
        let center = sweepCenter
        center.status = { [c] _ in c.status }

        let noticing = prefs.noticing(c.site, status: c.status)
        // The person's own word keeps a connected site quiet, whatever else is so.
        if !noticing, c.explicit == false, SiteSaveNoticing.setUp(c.status) { return .nothing(.turnedOff) }
        let wanted = noticing || c.offerSwitch      // `isWanted` for this one site
        switch SiteSaveWatcher.arming(bundle: c.browser, wanted: wanted, trusted: c.accessibility) {
        case .noAccessibility: return .nothing(.noAccessibility)
        case .notWatched:
            if BrowserInventory.catalog.first(where: { $0.bundleId == c.browser })?.supported == true {
                // A supported browser, and nothing to look for: the site is Off and the offer switch is off.
                return .nothing(.siteOffNoOffer)
            }
            return .nothing(.browserNotRead)
        case .watches: break
        }
        if noticing { return .asksWhy }
        guard center.listens(site: c.site) else { return .nothing(.siteOffNoOffer) }
        // A click on the control is read when the site is a candidate; the offer then decides at that moment.
        let context = ConnectSuggestPolicy.Context(
            now: t0, enabled: store.enabled, memoryKnown: true, setUp: true, isDemo: false,
            status: c.status, appLaunchedAt: nil, cicadaLaunchedAt: t0.addingTimeInterval(-3600), saveWhyOpen: false,
            showing: false)
        let decision = ConnectSuggestPolicy.decide(ConnectSuggestApps.site(c.site), memory: store.memory,
                                                   context: context, trigger: .saveClick)
        return decision == .suggest ? .offersConnect : .nothing(.siteOffNoOffer)
    }

    /// What the Sources page's "Saves you make" row shows for the same state.
    private func pageRow(_ c: Case) -> ResolvedStream {
        let prefs = fresh(c)
        let noticed = prefs.noticing(c.site, status: c.status)
        return row(c.site, noticed: noticed, off: prefs.explicit(c.site) == false, accessibility: c.accessibility)
    }

    private func case_(_ site: String = "x", _ status: SourceCatalogStatus? = .waitingForAgent, explicit: Bool? = nil,
                       accessibility: Bool = true, memory: Memory = .never, offerSwitch: Bool = true,
                       browser: String = "com.google.Chrome") -> Case {
        Case(site: site, status: status, explicit: explicit, accessibility: accessibility, memory: memory,
             offerSwitch: offerSwitch, browser: browser)
    }

    func testTheRowsThatMatterAreEachPinned() {
        // The owner's own state: list on from the Sources page, noticing never set, Accessibility given.
        XCTAssertEqual(click(case_("x", .connected)), .asksWhy)
        XCTAssertEqual(click(case_("x", .waitingForAgent)), .asksWhy)
        XCTAssertEqual(click(case_("x", .waitingForAgent, memory: .no)), .asksWhy, "a No to the offer is not a No to a list")
        XCTAssertEqual(click(case_("x", .waitingForAgent, offerSwitch: false)), .asksWhy,
                       "the offer switch is the offers', not the connected site's")
        // The person's word.
        XCTAssertEqual(click(case_("x", .connected, explicit: false)), .nothing(.turnedOff))
        XCTAssertEqual(pageRow(case_("x", .connected, explicit: false)).stream.why, Copy.Streams.savesTurnedOff)
        XCTAssertEqual(click(case_("x", .off, explicit: true)), .asksWhy, "on stays on while the list is off")
        // Accessibility: said by the row, with the button.
        XCTAssertEqual(click(case_("x", .connected, accessibility: false)), .nothing(.noAccessibility))
        let needs = pageRow(case_("x", .connected, accessibility: false))
        XCTAssertEqual(needs.word, .needsAccess)
        XCTAssertEqual(needs.fix, .accessibility)
        // A site that is Off: the offer at the save click (77b), by its own rules.
        XCTAssertEqual(click(case_("x", .off)), .offersConnect)
        XCTAssertEqual(click(case_("x", .off, memory: .notNowWaited)), .offersConnect)
        XCTAssertEqual(click(case_("x", .off, memory: .notNowWaiting)), .offersConnect,
                       "a save click passes a wait once (77b)")
        XCTAssertEqual(click(case_("x", .off, memory: .no)), .nothing(.siteOffNoOffer))
        XCTAssertEqual(click(case_("x", .off, memory: .yes)), .nothing(.siteOffNoOffer))
        XCTAssertEqual(click(case_("x", .off, memory: .shownItsLastTime)), .nothing(.siteOffNoOffer))
        XCTAssertEqual(click(case_("x", .off, offerSwitch: false)), .nothing(.siteOffNoOffer))
        XCTAssertEqual(click(case_("x", .off, accessibility: false)), .nothing(.noAccessibility))
        // The catalogue not read yet: nothing is assumed noticed and nothing is offered on a guess; the row reads Off, and
        // the visit is not spent (`Skip.passes`), so the first rest after the catalogue loads offers.
        XCTAssertEqual(click(case_("x", nil)), .nothing(.siteOffNoOffer))
        XCTAssertTrue(ConnectSuggestPolicy.Skip.noEntry.passes)
        // A browser Cicada does not read.
        XCTAssertEqual(click(case_("x", .connected, browser: "org.mozilla.firefox")), .nothing(.browserNotRead))
    }

    func testEveryCombinationForEverySiteIsAccountedFor() {
        var rows = 0
        for site in SiteSaveSite.all.map(\.key) {
            for explicit in [Bool?.none, true, false] {
                for memory in Memory.allCases {
                    for offerSwitch in [true, false] {
                        for status in [SourceCatalogStatus.off, .connected, .waitingForAgent, .needsSignIn, nil] {
                            for accessibility in [true, false] {
                                for browser in ["com.google.Chrome", "org.mozilla.firefox"] {
                                    check(case_(site, status, explicit: explicit, accessibility: accessibility,
                                                memory: memory, offerSwitch: offerSwitch, browser: browser))
                                    rows += 1
                                }
                            }
                        }
                    }
                }
            }
        }
        XCTAssertEqual(rows, 6 * 5 * 3 * 2 * 6 * 2 * 2)
    }

    /// The rule behind the table: the click and the row never disagree, and a click that does nothing is never left
    /// without a word on the page.
    private func check(_ c: Case) {
        let what = "\(c.site) status=\(String(describing: c.status)) explicit=\(String(describing: c.explicit)) " +
            "ax=\(c.accessibility) memory=\(c.memory) offers=\(c.offerSwitch) browser=\(c.browser)"
        let did = click(c)
        let row = pageRow(c)
        let setUp = SiteSaveNoticing.setUp(c.status)
        switch did {
        case .asksWhy:
            XCTAssertEqual(row.word, .read, "the page says on when a click asks: \(what)")
            XCTAssertTrue(c.accessibility && (c.explicit == true || (setUp && c.explicit != false)), what)
        case .offersConnect:
            XCTAssertEqual(row.word, .off, "an Off site reads Off, and its click brings the offer: \(what)")
            XCTAssertFalse(setUp, "a set-up site is never offered: \(what)")
        case .nothing(.noAccessibility):
            XCTAssertTrue(row.word == .needsAccess || row.word == .off, what)
            if row.word == .needsAccess {
                XCTAssertEqual(row.fix, .accessibility, what)
                XCTAssertEqual(row.stream.why, Copy.Streams.accessibilityWhy, what)
            }
        case .nothing(.browserNotRead):
            // Said by the row's hover and the Browsers page, whatever the row's word.
            XCTAssertNotNil(SourceStreamRow.help(row.stream), what)
        case .nothing(.turnedOff):
            XCTAssertEqual(row.word, .off, what)
            XCTAssertEqual(row.stream.why, Copy.Streams.savesTurnedOff, "the page says the person turned it off: \(what)")
        case .nothing(.siteOffNoOffer):
            XCTAssertNotEqual(row.word, .read, "the page says saves are noticed while a click does nothing: \(what)")
        }
        // A set-up site that the person did not turn off is never silent for any reason but Accessibility or the browser.
        if setUp, c.explicit != false, c.accessibility, c.browser == "com.google.Chrome" {
            XCTAssertEqual(did, .asksWhy, "a connected site asks why: \(what)")
        }
    }
}
