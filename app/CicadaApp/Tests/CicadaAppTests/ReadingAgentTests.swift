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
                 "via":"a browser skill","harness":"claude-code","host":"LinkedIn","hostKey":"linkedin",
                 "askable":true,"reason":null}}
        """)
        let read = try XCTUnwrap(item.read)
        XCTAssertEqual(read.status, "needs_login")
        XCTAssertEqual(read.harness, "claude-code")
        XCTAssertEqual(read.hostKey, "linkedin")
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
                   Copy.Reading.sheetSaferExport, Copy.Reading.askedNote, Copy.Reading.hostSwitchDetail,
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
        XCTAssertTrue(ReadWords.shows(MediaReadState(status: "none", hostKey: "x", askable: false, reason: "X is off.")))
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

    // MARK: Settings

    func testTheSettingsResponseDecodesLeniently() throws {
        let json = """
        {"agentEnabled":true,"agentHosts":["x"],"ackedAt":"2026-09-29","ackCurrent":true,
         "hostSwitches":[{"key":"linkedin","label":"LinkedIn","domains":["linkedin.com"]},{"nope":1},
                         {"key":"tiktok","label":"TikTok","note":"Profiles and pages only."}],
         "lastAgentRead":"2026-09-29"}
        """
        let s = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(json.utf8))
        XCTAssertTrue(s.agentEnabled)
        XCTAssertEqual(s.agentHosts, ["x"])
        XCTAssertEqual(s.hostSwitches.map(\.key), ["linkedin", "tiktok"], "a switch this build cannot read is dropped alone")
        XCTAssertEqual(try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data("{}".utf8)), ReadingSettingsResponse())
    }

    @MainActor
    func testTurningItOnSendsTheAcknowledgementAndTheSitesInOneCall() async {
        var sent: [(Bool?, [String]?, Bool)] = []
        let model = ReadingAgentModel(deps: .init(
            fetch: { ReadingSettingsResponse() },
            write: { on, hosts, ack in
                sent.append((on, hosts, ack))
                return ReadingSettingsResponse(agentEnabled: on ?? false, agentHosts: hosts ?? [], ackCurrent: ack)
            },
            prompt: { "prompt" }))
        await model.load()
        XCTAssertFalse(model.enabled)
        let ok = await model.setEnabled(true, acknowledge: true, hosts: ["x"])
        XCTAssertTrue(ok)
        XCTAssertTrue(model.enabled)
        XCTAssertEqual(sent.count, 1)
        XCTAssertEqual(sent[0].0, true)
        XCTAssertEqual(sent[0].1, ["x"])
        XCTAssertTrue(sent[0].2)
    }

    @MainActor
    func testARefusedTurnOnKeepsItOffAndShowsTheServersSentence() async {
        let model = ReadingAgentModel(deps: .init(
            fetch: { ReadingSettingsResponse() },
            write: { _, _, _ in
                throw APIError.httpError(422, #"{"detail":"Read the sheet and tick I understand before turning this on."}"#)
            },
            prompt: { "" }))
        await model.load()
        let ok = await model.setEnabled(true)
        XCTAssertFalse(ok)
        XCTAssertFalse(model.enabled)
        XCTAssertEqual(model.note, "Read the sheet and tick I understand before turning this on.")
    }

    @MainActor
    func testASiteSwitchSendsTheWholeList() async {
        var lists: [[String]] = []
        let model = ReadingAgentModel(deps: .init(
            fetch: { ReadingSettingsResponse(agentEnabled: true, agentHosts: ["x"], ackCurrent: true) },
            write: { _, hosts, _ in
                lists.append(hosts ?? [])
                return ReadingSettingsResponse(agentEnabled: true, agentHosts: hosts ?? [], ackCurrent: true)
            },
            prompt: { "" }))
        await model.load()
        await model.setHost("linkedin", allowed: true)
        await model.setHost("x", allowed: false)
        XCTAssertEqual(lists, [["x", "linkedin"], ["linkedin"]])
    }

    @MainActor
    func testOffThenOnKeepsTheSitesTheServerKept() async {
        // The fake mimics the server: `agentHosts` replaces the list when sent, and a turn-on with none sent keeps it.
        var held = ["linkedin", "x"]
        var sentHosts: [[String]?] = []
        let model = ReadingAgentModel(deps: .init(
            fetch: { ReadingSettingsResponse(agentEnabled: true, agentHosts: held, ackCurrent: true) },
            write: { on, hosts, _ in
                sentHosts.append(hosts)
                if let hosts { held = hosts }
                return ReadingSettingsResponse(agentEnabled: on ?? false, agentHosts: held, ackCurrent: true)
            },
            prompt: { "" }))
        await model.load()
        XCTAssertFalse(model.needsFirstUseSheet, "an acknowledged person is not re-asked")
        _ = await model.setEnabled(false)
        _ = await model.setEnabled(true)
        XCTAssertEqual(held, ["linkedin", "x"])
        XCTAssertEqual(model.settings?.agentHosts, ["linkedin", "x"])
        XCTAssertTrue(sentHosts.allSatisfy { $0 == nil })
    }

    @MainActor
    func testTheSheetOpensWithTheHeldSitesTickedAndAskedOnlyWithoutACurrentAck() async {
        let model = ReadingAgentModel(deps: .init(
            fetch: { ReadingSettingsResponse(agentEnabled: false, agentHosts: ["x"], ackCurrent: false) },
            write: { _, _, _ in ReadingSettingsResponse() }, prompt: { "" }))
        await model.load()
        XCTAssertTrue(model.needsFirstUseSheet)
        XCTAssertEqual(model.heldHosts, ["x"])
    }

    func testTheSettingsRowIsIndexedAndWordedWithoutPromises() {
        XCTAssertTrue(SettingsIndex.staticIDs.contains(.agentsReading))
        XCTAssertTrue(SettingsIndex.staticEntries.contains { $0.id == .agentsReading && $0.section == .agents })
    }
}
