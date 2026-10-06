import AppKit
import XCTest
@testable import CicadaApp

/// G166 / G178 — the rest of reading's app half: a wall page in the Feed offers its site's switch, Home's one line
/// counts only sites not allowed yet, "How your agent reads" offers the right thing per skill (and "Install…" opens
/// the skill's own detail even when the Skills page does not list it), site icons are drawn like a browser tab's and
/// come only through Cicada's own API, and no reading copy names a provider as the one doing a job.
@MainActor
final class ReadingSurfacesTests: XCTestCase {
    private func fixtureData(_ name: String) throws -> Data {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        return try Data(contentsOf: root.appendingPathComponent("api/tests/fixtures/\(name)"))
    }

    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    // MARK: Feed → Read — wall states

    func testWallStatesInTheFeedSection() {
        let walled = MediaReadState(status: "none", host: "www.linkedin.com", wall: "walled", siteKey: "linkedin",
                                    siteLabel: "LinkedIn", askable: true)
        XCTAssertTrue(ReadWords.shows(walled))
        XCTAssertEqual(ReadWords.line(walled, day: nil),
                       "Cicada’s reader couldn’t open this page: it needs a signed-in browser.")
        XCTAssertEqual(ReadWords.actions(walled), [.ask, .allowSite(site: "linkedin", label: "LinkedIn")])

        let consent = MediaReadState(status: "none", wall: "consent", siteKey: "news.example", askable: false,
                                     reason: "Turn on reading with an agent first.")
        XCTAssertEqual(ReadWords.line(consent, day: nil),
                       "Cicada’s reader couldn’t open this page: it stopped at a consent page.")
        XCTAssertEqual(ReadWords.actions(consent),
                       [.unavailable(reason: "Turn on reading with an agent first."),
                        .allowSite(site: "news.example", label: "news.example")],
                       "with agent reading off the page still offers its site's switch, which raises the sheet")

        let refused = MediaReadState(status: "none", wall: "refused", siteKey: "paperfold.io", askable: true)
        XCTAssertEqual(ReadWords.line(refused, day: nil), "Cicada’s reader couldn’t open this page: the site refused it.")

        // A wall page shows even with nothing to ask (agent reading off, no reason sent).
        XCTAssertTrue(ReadWords.shows(MediaReadState(status: "none", wall: "login")))
    }

    func testAnAllowedSitesPageWaitsWithoutOfferingTheSwitchAgain() {
        let queued = MediaReadState(status: "waiting", wall: "walled", siteKey: "linkedin", siteLabel: "LinkedIn",
                                    siteAllowed: true, queuedBy: "site", askable: true)
        XCTAssertEqual(ReadWords.line(queued, day: nil), "Waiting for your agent · LinkedIn is allowed")
        XCTAssertEqual(ReadWords.actions(queued), [.copyForAgent])
        let allowedNotQueued = MediaReadState(status: "none", wall: "walled", siteKey: "linkedin", siteAllowed: true,
                                              askable: true)
        XCTAssertEqual(ReadWords.actions(allowedNotQueued), [.ask], "an allowed site's switch is never offered again")
        // An explicit ask on an allowed site still reads as the plain waiting line.
        let asked = MediaReadState(status: "waiting", siteKey: "linkedin", siteAllowed: true, askable: true)
        XCTAssertEqual(ReadWords.line(asked, day: nil), "Waiting for your agent")
    }

    func testAPageWithNoSiteKeyNeverOffersASwitch() {
        let wall = MediaReadState(status: "none", wall: "walled", askable: true)
        XCTAssertEqual(ReadWords.actions(wall), [.ask])
    }

    // MARK: Home — "N saved pages need your browser"

    func testHomeLineShowsOnlyWithUnallowedSitesAndNeverCountsInTheInbox() throws {
        XCTAssertNil(HomeReadingLine.figures(nil))
        XCTAssertNil(HomeReadingLine.figures(ReadingSitesResponse()), "hidden at zero")
        let allAllowed = ReadingSitesResponse(sites: [ReadingSite(site: "linkedin", allowed: true, waiting: 3)],
                                              waitingTotal: 3, waitingNotAllowed: 0, enabled: true)
        XCTAssertNil(HomeReadingLine.figures(allAllowed), "hidden once every listed site is allowed")

        let fixture = try JSONDecoder().decode(ReadingSitesResponse.self, from: fixtureData("reading_sites.json"))
        let figures = try XCTUnwrap(HomeReadingLine.figures(fixture))
        XCTAssertEqual(figures.count, fixture.waitingNotAllowed, "the server's own count, never a sum the app invents")
        XCTAssertEqual(figures.sites.map(\.site), ["paperfold.io", "tiktok"], "not-allowed sites, busiest first")
        XCTAssertEqual(Copy.Reading.homePagesNeedBrowser(figures.count), "5 saved pages need your browser to be read")
        XCTAssertEqual(Copy.Reading.homePagesNeedBrowser(1), "1 saved page needs your browser to be read")
    }

    func testHomeShowsAtMostThreeIcons() {
        let sites = (1...6).map { ReadingSite(site: "s\($0)", waiting: $0) }
        let figures = HomeReadingLine.figures(ReadingSitesResponse(sites: sites, waitingTotal: 21,
                                                                   waitingNotAllowed: 21, enabled: false))
        XCTAssertEqual(figures?.sites.map(\.site), ["s6", "s5", "s4"])
    }

    func testTheHomeBlockIsItsOwnAndLinksToReadingTheWeb() throws {
        let sections = try source("Views/Home/HomeSections.swift")
        XCTAssertTrue(sections.contains("ReadingSitesSection()"))
        XCTAssertTrue(sections.contains("router.openSettings(.reading, row: .readingSites)"))
        let needsYou = try XCTUnwrap(sections.range(of: "struct NeedsYouSection").map { sections[$0.lowerBound...] })
        let end = try XCTUnwrap(needsYou.range(of: "// MARK: - Needs your browser"))
        XCTAssertFalse(needsYou[..<end.lowerBound].contains("ReadingSitesCache"),
                       "Needs you keeps the Inbox's count alone (each number once)")
    }

    func testTheSitesCacheKeepsItsValueOnA304AndForgetsItOnABankSwitch() async {
        var calls: [String?] = []
        var answer = Conditional<ReadingSitesResponse>(
            value: ReadingSitesResponse(sites: [ReadingSite(site: "a", waiting: 2)], waitingTotal: 2,
                                        waitingNotAllowed: 2, enabled: false),
            etag: "\"one\"", notModified: false)
        let cache = ReadingSitesCache(fetch: { etag in calls.append(etag); return answer })
        await cache.refresh()
        XCTAssertEqual(cache.value?.waitingTotal, 2)
        answer = Conditional(value: nil, etag: "\"one\"", notModified: true)
        await cache.refresh()
        XCTAssertEqual(calls, [nil, "\"one\""], "the ETag rides only once something is held")
        XCTAssertEqual(cache.value?.waitingTotal, 2, "a 304 keeps the last value (never blank)")
        cache.reset()
        XCTAssertNil(cache.value)
        await cache.refresh()
        XCTAssertEqual(calls.last ?? "x", nil, "after a bank switch nothing is held, so no ETag is sent")
    }

    // MARK: How your agent reads

    private func methods() throws -> AgentMethodJob {
        try XCTUnwrap(JSONDecoder().decode(AgentMethodsResponse.self, from: fixtureData("agent_methods.json")).job("reading"))
    }

    func testSkillOptionsDecodeThroughRecommendedSkill() throws {
        let job = try methods()
        for option in job.options {
            if option.isSkill {
                let skill = try XCTUnwrap(option.skill, option.id)
                XCTAssertEqual(skill.id, option.id)
                XCTAssertFalse(skill.agents.isEmpty)
                XCTAssertNotNil(SkillPromptText.shared(skill), "an agent-prompt install carries its sentence")
            } else {
                XCTAssertNil(option.skill, "a built-in is not a skill")
            }
        }
    }

    func testTheInstallPromptIsShownNotRun() throws {
        let skill = try XCTUnwrap(try methods().options.first { $0.id == "browser-harness" }?.skill)
        for agent in skill.agents {
            let plan = try XCTUnwrap(skill.install[agent])
            XCTAssertFalse(plan.runnable)
            XCTAssertTrue(plan.steps.isEmpty, "nothing for the app to run")
            XCTAssertNotNil(plan.prompt)
        }
    }

    func testEachSkillRowOffersWhatIsTrue() {
        let notInstalled = AgentMethodOption(id: "s", kind: "skill", title: "s", state: ["claude-code": "not_installed"],
                                             skill: nil)
        XCTAssertEqual(MethodRowWords.action(notInstalled), .none, "without the card shape there is nothing to open")
        XCTAssertEqual(MethodRowWords.action(AgentMethodOption(id: "auto", kind: "auto", title: "Let my agent choose")), .none)
        let installed = AgentMethodOption(id: "s", kind: "skill", title: "s", state: ["codex": "installed"])
        XCTAssertEqual(MethodRowWords.action(installed), .addToGraph)
        let withPage = AgentMethodOption(id: "s", kind: "skill", title: "s", state: ["codex": "installed"],
                                         page: AgentMethodPage(id: "s-page"))
        XCTAssertEqual(MethodRowWords.action(withPage), .openInGraph("s-page"), "open in graph only when a page exists")
    }

    func testSelectingAnUninstalledSkillKeepsTheRadioAndOffersInstall() throws {
        let option = try XCTUnwrap(try methods().options.first { $0.id == "macos-harness" })
        XCTAssertEqual(MethodRowWords.action(option), .install)
        XCTAssertTrue(MethodRowWords.detail(option).hasPrefix("Not installed yet · "))
        XCTAssertTrue(MethodRowWords.detail(option).contains("any app on your Mac"),
                      "the row says plainly it can control the whole Mac (D1)")
    }

    func testInstallFromThePickerOpensTheDetailForAHiddenRank() throws {
        let view = try source("Views/Settings/ReadingWebView.swift")
        XCTAssertTrue(view.contains("SkillDetailView(skill: skill, section: .reading)"),
                      "the picker hosts the skill's own detail; the Skills list shows only five")
        XCTAssertTrue(view.contains("openSkill = option.skill"))
        XCTAssertFalse(view.contains("findInSkills"))
        let option = try XCTUnwrap(try methods().options.first { $0.id == "browser-harness" })
        XCTAssertGreaterThan(option.skill?.rank ?? 0, 5, "a rank the Skills page's top five never shows")
    }

    func testSkillTagOnlyOnSkillRowsAndTheGroupIsDataDriven() throws {
        let view = try source("Views/Settings/ReadingWebView.swift")
        XCTAssertTrue(view.contains("if option.isSkill { Tag(text: Copy.Reading.skillTag) }"))
        XCTAssertTrue(view.contains("ForEach(job.options)"), "rows come from the server's list, never a table here")
        XCTAssertEqual(Copy.Reading.skillTag, "Skill")
    }

    func testDefaultsToAutoWhenAnOlderBackendSendsNothing() throws {
        let job = try JSONDecoder().decode(AgentMethodJob.self, from: Data(#"{"job":"reading"}"#.utf8))
        XCTAssertEqual(job.chosen, "auto")
        XCTAssertTrue(job.options.isEmpty)
    }

    // MARK: Site icons

    func testFaviconIsDrawnUnclippedWithASmallRadius() {
        XCTAssertEqual(SiteIconLayout.Size.row.points, 20)
        XCTAssertEqual(SiteIconLayout.Size.inline.points, 16)
        XCTAssertEqual(SiteIconLayout.cornerRadius, 4, "a tab's corner, never a circle")
        XCTAssertTrue(SiteIconLayout.clips(.favicon), "a fetched favicon gets the tab's corner")
        XCTAssertFalse(SiteIconLayout.clips(.bundled("linkedin")), "a bundled brand mark stands bare (DR-52)")
        XCTAssertFalse(SiteIconLayout.clips(.monogram))
    }

    func testFamilyFallsBackToBundledMarkThenMonogram() {
        XCTAssertEqual(SiteIconLayout.rung(favicon: true, site: "linkedin"), .favicon, "the site's own icon wins")
        XCTAssertEqual(SiteIconLayout.rung(favicon: false, site: "linkedin", markExists: { _ in true }), .bundled("linkedin"))
        XCTAssertEqual(SiteIconLayout.rung(favicon: false, site: "instagram"), .bundled("instagram"),
                       "the icon service has no icon for this family's bare domain; the shipped mark stands in")
        XCTAssertEqual(SiteIconLayout.rung(favicon: false, site: "linkedin", markExists: { _ in false }), .monogram)
        XCTAssertEqual(SiteIconLayout.rung(favicon: false, site: "paperfold.io"), .monogram)
    }

    func testMonogramIsDeterministic() {
        XCTAssertEqual(SiteMonogram.letter("paperfold.io"), "P")
        XCTAssertEqual(SiteMonogram.letter("paperfold.io"), SiteMonogram.letter("paperfold.io"))
        XCTAssertEqual(SiteMonogram.letter("9gag.com"), "9")
        XCTAssertEqual(SiteMonogram.letter("…"), "?")
    }

    func testNegativeResultIsMemoryOnlyAndInFlightFetchIsShared() async {
        let counter = Counter()
        let store = SiteIconStore(fetch: { _ in
            await counter.bump()
            try await Task.sleep(for: .milliseconds(50))
            return nil
        })
        async let a = store.image(site: "paperfold.io", bank: "b1")
        async let b = store.image(site: "paperfold.io", bank: "b1")
        _ = await (a, b)
        let afterTwo = await counter.value
        XCTAssertEqual(afterTwo, 1, "two rows asking at once share one request")
        _ = await store.image(site: "paperfold.io", bank: "b1")
        let afterMiss = await counter.value
        XCTAssertEqual(afterMiss, 1, "a miss is remembered in memory for the bank")
        _ = await store.image(site: "paperfold.io", bank: "b2")
        let otherBank = await counter.value
        XCTAssertEqual(otherBank, 2, "another bank asks for itself")
        await store.clear(bank: "b1")
        _ = await store.image(site: "paperfold.io", bank: "b1")
        let afterClear = await counter.value
        XCTAssertEqual(afterClear, 3, "a bank switch forgets that bank's answers")
    }

    /// Under load a caller that joined a running request could resume after the first had cleared `inFlight`, find
    /// nothing there and ask again (the flaky "2 is not 1" in the test above, 2026-10-05). Many pairs at once make
    /// that interleaving likely; every pair must still cost exactly one request.
    func testEveryPairAskingAtOnceSharesOneRequestUnderLoad() async {
        let counter = Counter()
        let store = SiteIconStore(fetch: { _ in
            await counter.bump()
            try await Task.sleep(for: .microseconds(Int.random(in: 0...400)))
            return nil
        })
        let sites = (0..<400).map { "site-\($0).example" }
        await withTaskGroup(of: Void.self) { group in
            for site in sites {
                group.addTask { _ = await store.image(site: site, bank: "b1") }
                group.addTask { _ = await store.image(site: site, bank: "b1") }
            }
        }
        let asked = await counter.value
        XCTAssertEqual(asked, sites.count, "one request per site, however the pair interleaves")
    }

    func testANetworkBlipIsNotRememberedAsNoIcon() async {
        let counter = Counter()
        let store = SiteIconStore(fetch: { _ in
            await counter.bump()
            throw URLError(.timedOut)
        })
        _ = await store.image(site: "a.io", bank: "b")
        _ = await store.image(site: "a.io", bank: "b")
        let calls = await counter.value
        XCTAssertEqual(calls, 2)
    }

    func testNoRuntimeNetworkForIcons() throws {
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8).lowercased()
            XCTAssertFalse(text.contains("duckduckgo"), "\(file.lastPathComponent) names the icon service")
            XCTAssertFalse(text.contains("favicon.ico"), "\(file.lastPathComponent) requests a favicon itself")
            XCTAssertFalse(text.contains("apple-touch-icon"), "\(file.lastPathComponent) requests a site's icon itself")
        }
        let store = try source("Services/SiteIconStore.swift")
        XCTAssertTrue(store.contains("APIClient.shared.fetchSiteIcon"), "the one way in is Cicada's own API")
    }

    // MARK: Settings wiring

    func testAgentsPageLinksToReadingNotTheGroup() throws {
        let connect = try source("Views/Connect/ConnectView.swift")
        XCTAssertTrue(connect.contains("SettingsInlineLink(section: .reading"))
        XCTAssertFalse(connect.contains("ReadingAgentGroup"))
        XCTAssertTrue(SettingsIndex.staticEntries.contains { $0.id == .agentsReading && $0.section == .agents })
    }

    func testSettingsSectionRawValuesDidNotMove() {
        let raw = ["general", "you", "privacy", "memory", "sleep", "integrations", "reading", "agents", "remote",
                   "skills", "engines", "plansAndKeys", "advanced"]
        XCTAssertEqual(SettingsSection.allCases.map(\.rawValue), raw)
        for value in raw { XCTAssertNotNil(SettingsSection(rawValue: value), value) }
    }

    func testTheFirstUseSheetHasNoSitePickerAndCarriesTheInstruction() throws {
        let view = try source("Views/Settings/ReadingWebView.swift")
        XCTAssertTrue(view.contains("Copy.Reading.sheetInstruction"))
        XCTAssertFalse(view.contains("sheetSites"))
        XCTAssertFalse(view.contains("heldHosts"))
        XCTAssertTrue(Copy.Reading.sheetInstruction.contains("can’t see or enforce"),
                      "an instruction with its honest limit, never a promise")
    }

    func testTheSwitchSaysWhyItReadsOffAfterAnOlderAcknowledgement() {
        XCTAssertEqual(ReadingSwitchHelp.text(nil), Copy.Reading.loadFailed)
        XCTAssertEqual(ReadingSwitchHelp.text(ReadingSettingsResponse(ackedAt: "2026-09-29", ackCurrent: false)),
                       Copy.Reading.reAskHelp)
        XCTAssertEqual(ReadingSwitchHelp.text(ReadingSettingsResponse(ackedAt: "2026-09-30", ackCurrent: true)), "")
        XCTAssertEqual(ReadingSwitchHelp.text(ReadingSettingsResponse()), "", "never asked: the sheet explains itself")
    }

    // MARK: Provider-neutral copy (owner 2026-09-30)

    func testReadingSearchKeywordsNameNoProductOrSkill() {
        let reading = SettingsIndex.staticEntries.filter { $0.section == .reading || $0.id == .agentsReading }
        XCTAssertEqual(reading.count, 5)
        let banned = ["harness", "claude", "codex", "chatgpt", "cursor", "gemini", "ollama", "openrouter", "chrome"]
        for entry in reading {
            for keyword in entry.keywords {
                for word in banned {
                    XCTAssertFalse(keyword.lowercased().contains(word), "\(entry.id.rawValue): \(keyword)")
                }
            }
        }
    }

    func testProviderNeutralCopyLint() throws {
        // Scanned: the copy file and every view that speaks about reading. Exempt by name: `ReadWords.harnessName`,
        // which names the connection that actually recorded a read (a fact, not a choice made for the person).
        let files = ["Theme/Copy+Reading.swift", "Views/Settings/ReadingWebView.swift", "Views/Feed/FeedReadSection.swift",
                     "Views/Common/SiteIcon.swift", "Services/SiteIconStore.swift", "Models/ReadingSitesCache.swift"]
        let banned = ["ollama", "claude plan", "chatgpt plan", "your claude", "haiku", "sonnet", "gemma",
                      "claude in chrome", "claude code", "codex", "chatgpt", "cursor", "gemini", "openrouter",
                      "goes to your", "summarized on this mac by", "browser-harness", "browser harness"]
        for file in files {
            let text = try source(file)
            // Only string literals are copy; doc comments may explain the rule they follow.
            let literals = Self.stringLiterals(text).map { $0.lowercased() }
            for literal in literals {
                for word in banned { XCTAssertFalse(literal.contains(word), "\(file): \(word) in \"\(literal)\"") }
                XCTAssertNil(literal.range(of: #"\bopus\b"#, options: .regularExpression), "\(file): \(literal)")
                XCTAssertNil(literal.range(of: #"\bgpt-"#, options: .regularExpression), "\(file): \(literal)")
            }
        }
    }

    /// Every `"…"` literal in a Swift source, skipping `//` comments.
    static func stringLiterals(_ text: String) -> [String] {
        var out: [String] = []
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let code = line.trimmingCharacters(in: .whitespaces)
            if code.hasPrefix("//") { continue }
            let pieces = line.split(separator: "\"", omittingEmptySubsequences: false)
            guard pieces.count >= 3 else { continue }
            for index in stride(from: 1, to: pieces.count - 1, by: 2) { out.append(String(pieces[index])) }
        }
        return out
    }
}

private actor Counter {
    private(set) var value = 0
    func bump() { value += 1 }
}
