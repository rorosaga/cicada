import XCTest
@testable import CicadaApp

/// G166 — the app half of reading with the person's own agent: the `read` block decodes leniently, the `reading`
/// sync component refreshes the Feed, the Read section's words and controls are pure functions of the block, and the
/// Settings model turns the switch on only with an acknowledgement.
final class ReadingAgentTests: XCTestCase {
    private func decode(_ json: String) throws -> MediaFeedItem {
        try JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
    }

    // MARK: The wire

    func testAnOlderBackendSendsNoReadBlockAndTheRowStillDecodes() throws {
        let item = try decode(#"{"mediaEntityId":"media-a","url":"https://example.com/a","title":"A","mediaType":"url"}"#)
        XCTAssertNil(item.read)
        XCTAssertFalse(ReadWords.shows(item.read))
    }

    func testTheReadBlockDecodesEveryField() throws {
        let item = try decode("""
        {"mediaEntityId":"media-a","url":"https://example.com/a","title":"A","mediaType":"url",
         "read":{"status":"needs_login","by":"agent","at":"2026-09-29T12:01:00Z","askedAt":"2026-09-29T12:00:00Z",
                 "via":"a browser skill","harness":"claude-code","host":"LinkedIn","wall":"walled","siteKey":"linkedin",
                 "siteLabel":"LinkedIn","siteAllowed":true,"queuedBy":"site","askable":true,"reason":null}}
        """)
        let read = try XCTUnwrap(item.read)
        XCTAssertEqual(read.status, "needs_login")
        XCTAssertEqual(read.harness, "claude-code")
        XCTAssertEqual(read.wall, "walled")
        XCTAssertEqual(read.siteKey, "linkedin")
        XCTAssertEqual(read.siteLabel, "LinkedIn")
        XCTAssertTrue(read.siteAllowed)
        XCTAssertEqual(read.queuedBy, "site")
        XCTAssertTrue(read.askable)
    }

    func testAMalformedReadBlockDropsTheBlockNotTheRow() throws {
        let item = try decode(#"{"mediaEntityId":"media-a","url":"https://example.com/a","title":"A","mediaType":"url","read":"nope"}"#)
        XCTAssertNil(item.read)
        XCTAssertEqual(item.title, "A")
    }

    func testAnUnknownFieldTypeInTheBlockIsDroppedAlone() throws {
        let block = try JSONDecoder().decode(MediaReadState.self, from: Data(#"{"status":"waiting","askable":"yes","host":7}"#.utf8))
        XCTAssertEqual(block.status, "waiting")
        XCTAssertFalse(block.askable)
        XCTAssertNil(block.host)
    }

    // MARK: The sync component

    func testTheReadingComponentRefreshesTheFeedAndNothingElse() {
        let old = VersionVector(version: "1", components: ["bank": "b", "reading": "0:0"])
        let new = VersionVector(version: "2", components: ["bank": "b", "reading": "1.5:0"])
        XCTAssertEqual(new.changedDomains(since: old), [.sources])
    }

    // MARK: Words and controls

    func testTheLineSaysOnlyTheKnownFacts() {
        XCTAssertEqual(ReadWords.line(MediaReadState(status: "waiting"), day: nil), "Waiting for your agent")
        XCTAssertEqual(ReadWords.line(MediaReadState(status: "ok", by: "agent", harness: "claude-code"), day: "Sep 29"),
                       "Read by Claude Code · Sep 29")
        XCTAssertEqual(ReadWords.line(MediaReadState(status: "ok", by: "agent"), day: nil), "Read by an agent")
        XCTAssertEqual(ReadWords.line(MediaReadState(status: "needs_login", host: "LinkedIn"), day: nil),
                       "Needs you to sign in to LinkedIn")
        XCTAssertEqual(ReadWords.line(MediaReadState(status: "blocked", host: "example.com"), day: nil),
                       "example.com blocked the read")
        XCTAssertEqual(ReadWords.line(MediaReadState(status: "none"), day: nil), "Not read by an agent")
    }

    func testNoLineSaysInYourBrowserOrPromisesWhatAnAgentDoes() {
        // Cicada cannot know an agent used a browser: the status lines never say so (spec §7.5).
        for status in ["waiting", "ok", "needs_login", "blocked", "not_found", "failed", "none"] {
            let line = ReadWords.line(MediaReadState(status: status, by: "agent", host: "example.com"), day: "Sep 29")
            XCTAssertFalse(line.lowercased().contains("browser"), line)
        }
        let all = [Copy.Reading.switchDetail, Copy.Reading.sheetHow, Copy.Reading.sheetOnlyAsks, Copy.Reading.sheetTerms,
                   Copy.Reading.sheetSaferExport, Copy.Reading.askedNote, Copy.Reading.sitesIntro, Copy.Reading.methodsDetail, Copy.Reading.watchMethodsDetail,
                   Copy.Reading.waiting, Copy.Reading.copyPromptHelp]
        for text in all {
            for banned in ["read-only", "never posts", "never post", "cannot post", "safe to"] {
                XCTAssertFalse(text.lowercased().contains(banned), text)
            }
        }
    }

    func testNeedsLoginOffersTheBrowserFirstAndAskAgainOnlyWhenAskable() {
        XCTAssertEqual(ReadWords.actions(MediaReadState(status: "needs_login", askable: true)), [.openInBrowser, .askAgain])
        XCTAssertEqual(ReadWords.actions(MediaReadState(status: "needs_login", askable: false)), [.openInBrowser])
    }

    func testAWaitingAskOffersTheHandOffAndAFirstAskIsOnlyOfferedWhenAskable() {
        XCTAssertEqual(ReadWords.actions(MediaReadState(status: "waiting", askable: true)), [.copyForAgent])
        XCTAssertEqual(ReadWords.actions(MediaReadState(status: "none", askable: true)), [.ask])
        XCTAssertEqual(ReadWords.actions(MediaReadState(status: "none", askable: false, reason: "X is not turned on.")),
                       [.unavailable(reason: "X is not turned on.")])
        XCTAssertEqual(ReadWords.actions(MediaReadState(status: "none", askable: false)), [])
    }

    func testTheSectionShowsOnlyWhenThereIsSomethingToSayOrDo() {
        XCTAssertFalse(ReadWords.shows(nil))
        // An ordinary page with agent reading off: nothing is offered, so nothing is drawn.
        XCTAssertFalse(ReadWords.shows(MediaReadState(status: "none", askable: false, reason: "Agent reading is off.")))
        XCTAssertTrue(ReadWords.shows(MediaReadState(status: "none", askable: true)))
        XCTAssertTrue(ReadWords.shows(MediaReadState(status: "none", wall: "refused", askable: false, reason: "Agent reading is off.")))
        XCTAssertTrue(ReadWords.shows(MediaReadState(status: "needs_login")))
    }

    // MARK: Ambient surfaces (a wall is not visible only inside the open item)

    private func feedItem(_ id: String, read: String? = nil) -> MediaFeedItem {
        let extra = read.map { #", "read": \#($0)"# } ?? ""
        let json = #"{"mediaEntityId": "\#(id)", "url": "https://example.com/\#(id)", "title": "T \#(id)", "mediaType": "url", "savedAt": "2026-09-13T10:00:00Z", "relevance": 0.5, "tags": []\#(extra)}"#
        return try! JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
    }

    func testTheFeedRowFlagsALoginWallAndNothingElse() {
        let wall = feedItem("a", read: #"{"status":"needs_login","by":"agent","host":"linkedin.com"}"#)
        let done = feedItem("b", read: #"{"status":"ok","by":"agent"}"#)
        let plain = feedItem("c")
        XCTAssertEqual(ReadWords.rowFlag(wall.read), "Needs sign-in")
        XCTAssertNil(ReadWords.rowFlag(done.read))
        XCTAssertNil(ReadWords.rowFlag(plain.read))
        let utc = TimeZone(identifier: "UTC")!
        let us = Locale(identifier: "en_US")
        let line = FeedRowText.detail(wall, locale: us, timeZone: utc)
        XCTAssertTrue(line.hasSuffix("Needs sign-in · saved Sep 13"), line)
        XCTAssertFalse(FeedRowText.detail(done, locale: us, timeZone: utc).contains("Needs sign-in"))
    }

    func testAWallIsAnnouncedOnceAndNeverOnTheFirstLook() {
        let wall = feedItem("a", read: #"{"status":"needs_login","by":"agent","host":"linkedin.com"}"#)
        let quiet = feedItem("b")
        let first = ReadWords.newlyWalled(previous: nil, items: [wall, quiet])
        XCTAssertEqual(first.current, [wall.id])
        XCTAssertTrue(first.fresh.isEmpty, "a wall from an earlier session never toasts at launch")
        XCTAssertNil(ReadWords.walledToast(first.fresh))
        let newWall = feedItem("b", read: #"{"status":"needs_login","by":"agent","host":"x.com"}"#)
        let second = ReadWords.newlyWalled(previous: first.current, items: [wall, newWall])
        XCTAssertEqual(second.fresh.map(\.id), [newWall.id])
        XCTAssertEqual(ReadWords.walledToast(second.fresh), "x.com needs you to sign in. It's marked in the Feed.")
        let again = ReadWords.newlyWalled(previous: second.current, items: [wall, newWall])
        XCTAssertTrue(again.fresh.isEmpty, "the same wall does not toast twice")
        let cleared = ReadWords.newlyWalled(previous: second.current, items: [wall, quiet])
        XCTAssertEqual(cleared.current, [wall.id])
        let two = ReadWords.newlyWalled(previous: [], items: [wall, newWall])
        XCTAssertEqual(ReadWords.walledToast(two.fresh), "2 pages need you to sign in. They're marked in the Feed.")
    }

    func testTheAgentsNoteIsShownAsItsOwnWords() {
        let noted = MediaReadState(status: "ok", by: "agent", harness: "claude-code", note: "  The page loaded fine.  ")
        XCTAssertEqual(ReadWords.agentNoteLine(noted), "Claude Code noted: The page loaded fine.")
        XCTAssertNil(ReadWords.agentNoteLine(MediaReadState(status: "ok", by: "agent", note: "  ")))
        XCTAssertNil(ReadWords.agentNoteLine(MediaReadState(status: "ok", by: "cicada", note: "x")), "only an agent's words")
        XCTAssertNil(ReadWords.agentNoteLine(MediaReadState(status: "ok", by: "agent")))
    }

    func testOnlyAWebLinkOpensInTheBrowser() {
        XCTAssertNotNil(ReadWords.browserURL("https://example.com/a"))
        XCTAssertNil(ReadWords.browserURL("file:///etc/hosts"))
        XCTAssertNil(ReadWords.browserURL("javascript:alert(1)"))
        XCTAssertNil(ReadWords.browserURL("not a url"))
    }

    func testDayFormatsAStampAndABareDate() {
        let utc = TimeZone(identifier: "UTC")!
        let locale = Locale(identifier: "en_US")
        XCTAssertEqual(ReadWords.day("2026-09-29T12:01:00Z", locale: locale, timeZone: utc), "Sep 29")
        XCTAssertEqual(ReadWords.day("2026-09-29", locale: locale, timeZone: utc), "Sep 29")
        XCTAssertNil(ReadWords.day(nil))
        XCTAssertNil(ReadWords.day("garbage"))
    }

    // MARK: Settings — the wire (the backend's own fixtures, read by `test_reading_sites_rest.py` / `test_agent_methods_rest.py`)

    private func fixtureData(_ name: String) throws -> Data {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        return try Data(contentsOf: root.appendingPathComponent("api/tests/fixtures/\(name)"))
    }

    func testTheSettingsResponseDecodesLeniently() throws {
        let json = """
        {"agentEnabled":true,"allowedSites":{"linkedin":"2026-09-30"},"ackedAt":"2026-09-29","ackCurrent":true,
         "ackVersion":2,"lastAgentRead":"2026-09-29","shape":"reading-2"}
        """
        let s = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(json.utf8))
        XCTAssertTrue(s.agentEnabled)
        XCTAssertEqual(s.allowedSites, ["linkedin": "2026-09-30"])
        XCTAssertEqual(s.lastAgentRead, "2026-09-29")
        XCTAssertEqual(try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data("{}".utf8)), ReadingSettingsResponse())
        // An older backend's shape (per-site `agentHosts`) decodes to nothing allowed, never a failure.
        let old = try JSONDecoder().decode(ReadingSettingsResponse.self,
                                           from: Data(#"{"agentEnabled":true,"agentHosts":["x"],"hostSwitches":[]}"#.utf8))
        XCTAssertTrue(old.agentEnabled)
        XCTAssertTrue(old.allowedSites.isEmpty)
    }

    func testTheSitesFixtureDecodesAndReadsInWords() throws {
        let list = try JSONDecoder().decode(ReadingSitesResponse.self, from: fixtureData("reading_sites.json"))
        XCTAssertEqual(list.sites.map(\.site), ["linkedin", "paperfold.io", "tiktok"])
        XCTAssertEqual(list.waitingTotal, 6)
        XCTAssertEqual(list.waitingNotAllowed, 5)
        XCTAssertTrue(list.enabled)
        let linkedin = try XCTUnwrap(list.sites.first { $0.site == "linkedin" })
        XCTAssertTrue(linkedin.allowed)
        XCTAssertEqual(linkedin.iconHost, "linkedin.com")
        XCTAssertTrue(linkedin.granted)
        XCTAssertEqual(ReadingSiteWords.countLine(linkedin), "1 page waits until you sign in",
                       "a paused site's pages wait for the person, never 'queued'")
        XCTAssertTrue(ReadingSiteWords.isPaused(linkedin), "an allowed site whose agent was signed out is paused")
        XCTAssertNil(ReadingSiteWords.grantNote(linkedin))
        XCTAssertEqual(ReadingSiteWords.countLine(ReadingSite(site: "x", allowed: true, waiting: 2)),
                       "2 pages are queued for your agent")
        let paperfold = try XCTUnwrap(list.sites.first { $0.site == "paperfold.io" })
        XCTAssertEqual(ReadingSiteWords.countLine(paperfold), "4 saved pages are waiting")
        XCTAssertEqual(ReadingSiteWords.detail(paperfold), "Refused Cicada’s reader")
        XCTAssertFalse(ReadingSiteWords.isPaused(paperfold))
        let tiktok = try XCTUnwrap(list.sites.first { $0.site == "tiktok" })
        XCTAssertEqual(ReadingSiteWords.detail(tiktok), tiktok.note, "the server's own caveat wins over the wall's name")
    }

    func testAGrantWhileAgentReadingIsOffIsNeverQueuedAndStillCountsOnHome() throws {
        // The server's wire with the master switch off: `allowed` false (it does not count now), `granted` true.
        let json = #"""
        {"sites":[{"site":"linkedin","label":"LinkedIn","wall":"walled","allowed":false,"granted":true,
        "since":"2026-09-30","waiting":2,"read":0,"needsLogin":1}],
        "waitingTotal":2,"waitingNotAllowed":2,"enabled":false}
        """#
        let list = try JSONDecoder().decode(ReadingSitesResponse.self, from: Data(json.utf8))
        let site = try XCTUnwrap(list.sites.first)
        XCTAssertFalse(ReadingSiteWords.countLine(site).contains("queued"))
        XCTAssertEqual(ReadingSiteWords.countLine(site), "2 saved pages are waiting")
        XCTAssertFalse(ReadingSiteWords.isPaused(site), "no Try again while agent reading is off")
        XCTAssertEqual(ReadingSiteWords.grantNote(site), "Allowed · agent reading is off")
        XCTAssertTrue(ReadingSiteWords.switchOn(site), "the grant is drawn so it can be turned off")
        XCTAssertEqual(ReadingSiteWords.line(site), "2 saved pages are waiting · Allowed · agent reading is off · "
                       + (ReadingSiteWords.detail(site) ?? ""))
        let figures = try XCTUnwrap(HomeReadingLine.figures(list), "Home still counts pages nobody will read")
        XCTAssertEqual(figures.count, 2)
        XCTAssertEqual(figures.sites.map(\.site), ["linkedin"])
        // An older server sends only `allowed`, which then stands for the grant too.
        let old = try JSONDecoder().decode(ReadingSite.self, from: Data(#"{"site":"x","allowed":true}"#.utf8))
        XCTAssertTrue(old.granted)
    }

    func testASiteThisBuildCannotReadIsDroppedAloneAndNoCountIsAnInvention() throws {
        let json = #"{"sites":[{"nope":1},{"site":"x","allowed":true,"waiting":0,"read":2}],"enabled":true}"#
        let list = try JSONDecoder().decode(ReadingSitesResponse.self, from: Data(json.utf8))
        XCTAssertEqual(list.sites.map(\.site), ["x"])
        XCTAssertEqual(ReadingSiteWords.countLine(list.sites[0]), "2 read by an agent")
        XCTAssertEqual(ReadingSiteWords.countLine(ReadingSite(site: "y")), "Nothing is waiting")
    }

    func testTheAgentMethodsFixtureDecodesWithSkillsTaggedAndTheChoiceKept() throws {
        let all = try JSONDecoder().decode(AgentMethodsResponse.self, from: fixtureData("agent_methods.json"))
        let job = try XCTUnwrap(all.job("reading"))
        XCTAssertEqual(job.question, "How your agent reads")
        XCTAssertEqual(job.chosen, "auto")
        XCTAssertEqual(job.options.map(\.kind).prefix(2), ["auto", "own"])
        let skills = job.options.filter(\.isSkill)
        XCTAssertFalse(skills.isEmpty)
        for skill in skills {
            XCTAssertFalse(skill.title.isEmpty)
            XCTAssertFalse(skill.installedAnywhere, "the fixture bank has none installed")
            XCTAssertNil(skill.page)
        }
        XCTAssertEqual(skills.first?.reach, "Uses your own Chrome, including sites where you're signed in.")
    }

    func testAMethodWriteAnswersTheJobAndWhatHappenedToTheSkillsPage() throws {
        let json = """
        {"job":"reading","question":"How your agent reads","chosen":"own","options":[
          {"id":"auto","kind":"auto","title":"Let my agent choose","detail":"x"},
          {"id":"own","kind":"own","title":"Its own tools","detail":"y"}],
         "write":{"page":"created"}}
        """
        let answer = try JSONDecoder().decode(AgentMethodWriteResponse.self, from: Data(json.utf8))
        XCTAssertEqual(answer.job.chosen, "own")
        XCTAssertEqual(answer.pageState, "created")
        XCTAssertEqual(Copy.Reading.pageNote("created"), "Added this skill to your graph.")
        XCTAssertNil(Copy.Reading.pageNote("none"))
    }

    // MARK: Settings — the model

    private func deps(
        settings: ReadingSettingsResponse = ReadingSettingsResponse(),
        sent: Box<[(Bool?, [String: Bool]?, Bool)]> = Box([]),
        write: (@MainActor (Bool?, [String: Bool]?, Bool) async throws -> ReadingSettingsResponse)? = nil
    ) -> ReadingAgentModel.Deps {
        .init(
            fetch: { settings },
            write: write ?? { on, sites, ack in
                sent.value.append((on, sites, ack))
                var next = settings
                next.agentEnabled = on ?? next.agentEnabled
                next.ackCurrent = ack || next.ackCurrent
                for (k, v) in sites ?? [:] { if v { next.allowedSites[k] = "2026-09-30" } else { next.allowedSites[k] = nil } }
                return next
            },
            prompt: { "prompt" },
            fetchSites: { ReadingSitesResponse(sites: [ReadingSite(site: "linkedin", waiting: 2)], enabled: true) },
            fetchMethods: {
                AgentMethodsResponse(jobs: [AgentMethodJob(job: "reading", question: "How your agent reads", chosen: "auto",
                    options: [AgentMethodOption(id: "auto", kind: "auto", title: "Let my agent choose"),
                              AgentMethodOption(id: "s", kind: "skill", title: "s", state: ["claude-code": "installed"])]),
                    AgentMethodJob(job: "watching", question: "How your agent watches", chosen: "auto",
                    options: [AgentMethodOption(id: "auto", kind: "auto", title: "Let my agent choose"),
                              AgentMethodOption(id: "w", kind: "skill", title: "w", state: ["claude-code": "installed"])])])
            },
            setMethod: { job, choice in
                AgentMethodWriteResponse(job: AgentMethodJob(job: job, question: "q", chosen: choice),
                                         pageState: choice == "s" ? "created" : "none")
            },
            addPage: { AgentMethodPage(id: "skill-\($0)", state: "created") })
    }

    final class Box<T> { var value: T; init(_ value: T) { self.value = value } }

    @MainActor
    func testTurningItOnSendsTheAcknowledgementAndTheSiteInOneCall() async {
        let sent = Box<[(Bool?, [String: Bool]?, Bool)]>([])
        let model = ReadingAgentModel(deps: deps(sent: sent))
        await model.load()
        XCTAssertFalse(model.enabled)
        XCTAssertTrue(model.needsFirstUseSheet)
        let ok = await model.setEnabled(true, acknowledge: true, site: "linkedin")
        XCTAssertTrue(ok)
        XCTAssertTrue(model.enabled)
        XCTAssertEqual(sent.value.count, 1)
        XCTAssertEqual(sent.value[0].0, true)
        XCTAssertEqual(sent.value[0].1, ["linkedin": true])
        XCTAssertTrue(sent.value[0].2)
        XCTAssertEqual(model.sites?.sites.map(\.site), ["linkedin"], "the list is read again after a write")
    }

    @MainActor
    func testASiteSwitchSendsOnlyThatSiteAndTurnsTheSwitchOnWhenItWasOffAndAcknowledged() async {
        let sent = Box<[(Bool?, [String: Bool]?, Bool)]>([])
        let model = ReadingAgentModel(deps: deps(settings: ReadingSettingsResponse(agentEnabled: false, ackCurrent: true),
                                                 sent: sent))
        await model.load()
        XCTAssertFalse(model.needsFirstUseSheet, "an acknowledged person is not re-asked")
        _ = await model.setSite("linkedin", allowed: true)
        XCTAssertEqual(sent.value[0].0, true, "allowing a site while the switch is off turns it on in the same call")
        XCTAssertEqual(sent.value[0].1, ["linkedin": true])
        _ = await model.setSite("linkedin", allowed: false)
        XCTAssertNil(sent.value[1].0, "taking a site back leaves the switch alone")
        XCTAssertEqual(sent.value[1].1, ["linkedin": false])
        XCTAssertFalse(sent.value[1].2)
    }

    @MainActor
    func testARefusedWriteKeepsItOffAndShowsTheServersSentence() async {
        let model = ReadingAgentModel(deps: deps(write: { _, _, _ in
            throw APIError.httpError(422, #"{"detail":"Read the sheet and tick I understand before turning this on."}"#)
        }))
        await model.load()
        let ok = await model.setEnabled(true)
        XCTAssertFalse(ok)
        XCTAssertFalse(model.enabled)
        XCTAssertEqual(model.note, "Read the sheet and tick I understand before turning this on.")
    }

    @MainActor
    func testChoosingHowTheAgentReadsSavesTheChoiceAndSaysWhatHappenedToTheSkillsPage() async {
        let model = ReadingAgentModel(deps: deps())
        await model.load()
        XCTAssertEqual(model.methods?.chosen, "auto")
        await model.choose("s")
        XCTAssertEqual(model.methods?.chosen, "s")
        XCTAssertEqual(model.methodNote, "Added this skill to your graph.")
        await model.choose("auto")
        XCTAssertNil(model.methodNote, "a choice with no page news says nothing")
    }

    @MainActor
    func testChoosingHowTheAgentWatchesIsItsOwnChoiceAndNeverMovesReadings() async {
        let model = ReadingAgentModel(deps: deps())
        await model.load()
        XCTAssertEqual(model.watchMethods?.job, "watching")
        XCTAssertEqual(model.watchMethods?.chosen, "auto")
        await model.choose("w", job: ReadingAgentModel.watchJob)
        XCTAssertEqual(model.watchMethods?.chosen, "w")
        XCTAssertEqual(model.methods?.chosen, "auto", "one choice per job")
        XCTAssertEqual(model.methodNoteJob, "watching")
        XCTAssertEqual(SettingsRowID.watchingMethod("w").rawValue, "watchingMethod:w")
        XCTAssertNotEqual(SettingsRowID.watchingMethod("w"), SettingsRowID.readingMethod("w"))
    }

    @MainActor
    func testAddingASkillsPageToTheGraphAnswersInWords() async {
        let model = ReadingAgentModel(deps: deps())
        await model.load()
        await model.addPage("s")
        XCTAssertEqual(model.methodNote, "Added this skill to your graph.")
    }

    // MARK: Settings — the section and its rows

    func testTheSectionSitsAfterIntegrationsAndItsRowsAreIndexed() {
        let all = SettingsSection.allCases
        XCTAssertEqual(all.firstIndex(of: .reading), all.firstIndex(of: .integrations).map { $0 + 1 })
        XCTAssertEqual(SettingsSection.reading.group, .customize)
        XCTAssertEqual(SettingsSection.reading.title, "Reading the web")
        XCTAssertEqual(SettingsSection(rawValue: "reading"), .reading, "the raw value is a machine key")
        for id in [SettingsRowID.readingAgent, .readingMethods, .watchingMethods, .readingSites] {
            XCTAssertTrue(SettingsIndex.staticIDs.contains(id))
            XCTAssertTrue(SettingsIndex.staticEntries.contains { $0.id == id && $0.section == .reading })
        }
    }

    func testNoReadingCopyNamesAProviderOrAPromise() {
        let lines = [Copy.Reading.switchDetail, Copy.Reading.methodsDetail, Copy.Reading.watchMethodsDetail, Copy.Reading.sitesIntro,
                     Copy.Reading.sitesEmpty, Copy.Reading.sitesIconNote, Copy.Reading.needsLoginNote,
                     Copy.Reading.sheetHow, Copy.Reading.sheetOnlyAsks, Copy.Reading.sheetTerms]
        let banned = ["claude", "chatgpt", "codex", "ollama", "openrouter", "gemini", "haiku", "opus", "sonnet"]
        for line in lines {
            for word in banned { XCTAssertFalse(line.lowercased().contains(word), "\(word) in: \(line)") }
            XCTAssertFalse(line.lowercased().contains("never posts"), line)
        }
    }
}
