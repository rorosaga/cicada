import XCTest
@testable import CicadaApp

/// 2026-10-26 (owner) — saved lists asked once in onboarding, pre-ticked, the answer the consent; every "Import a file"
/// source says where its file comes from; the Calendar row names the accounts it includes and how Google's joins.
final class SourcesDefaultsCalendarTests: XCTestCase {
    // MARK: Saved lists step

    func testEveryListIsPreTickedUnlessThePersonTurnedItOff() {
        XCTAssertEqual(SavedListsStepModel.initialTicks(nil), Set(SavedListItem.allCases))
        var settings = ReadingSettingsResponse()
        settings.savedListsOff = ["instagram": true]
        settings.youtubeListsOff = YouTubeListSwitches(watchLater: false, history: true)
        XCTAssertEqual(SavedListsStepModel.initialTicks(settings),
                       [.youtubeWatchLater, .x, .linkedin], "an off the person chose is never re-ticked")
    }

    func testTheAnswerTurnsTickedOnWithConsentAndRecordsTheRestOff() {
        let write = SavedListsStepModel.write([.youtubeHistory, .x])
        XCTAssertTrue(write.consent)
        XCTAssertEqual(write.youtubeLists, ["watch_later": false, "history": true])
        XCTAssertEqual(write.savedLists, ["x": true, "instagram": false, "linkedin": false])
        let none = SavedListsStepModel.write([])
        XCTAssertFalse(none.consent, "nothing ticked is no consent: nothing turns on")
        XCTAssertEqual(none.savedLists.values.filter { $0 }.count, 0)
        XCTAssertEqual(SavedListsStepModel.primaryTitle([]), Copy.onboardingContinue)
        XCTAssertEqual(SavedListsStepModel.primaryTitle([.x]), Copy.savedListsKeep)
    }

    /// Review of #474 (blocker): Skip on *Saved lists* ran the consent button's PUT — everything pre-ticked, so agent
    /// reading, its acknowledgement and all five lists turned on. Skip moves on and sends nothing.
    func testSkipSendsNoWrite() throws {
        XCTAssertFalse(SavedListsStepModel.writes(on: .skip))
        XCTAssertTrue(SavedListsStepModel.writes(on: .primary))
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Onboarding/OnboardingView.swift") })
        let view = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(view.contains("TextButton(title: Copy.onboardingSkip) { skip() }"),
                      "the foot's Skip goes through skip(), never advance()")
        let start = try XCTUnwrap(view.range(of: "private func skip() {"))
        let body = String(view[start.upperBound...].prefix(400))
        let end = body.range(of: "\n    }")?.lowerBound ?? body.endIndex
        let skipBody = String(body[..<end])
        XCTAssertFalse(skipBody.contains("saveLists"), "Skip never sends the step's answer")
        XCTAssertFalse(skipBody.contains("advance("), "advance() sends Saved lists' answer")
        XCTAssertFalse(skipBody.contains("setReadingSettings"))
        XCTAssertTrue(skipBody.contains("go(next, .pointer)"))
        XCTAssertTrue(view.contains("case .savedLists where SavedListsStepModel.writes(on: .primary): saveLists(input)"))
    }

    func testTheWriteRidesOnePutWithNoSiteGrant() {
        let write = SavedListsStepModel.write(Set(SavedListItem.allCases))
        let body = APIClient.readingSettingsBody(agentEnabled: true, acknowledge: true,
                                                 youtubeLists: write.youtubeLists, savedLists: write.savedLists)
        XCTAssertNil(body["sites"], "a saved list is a standing ask for one page, never the site")
        XCTAssertEqual(body["acknowledge"] as? Bool, true)
    }

    func testTheStepsWordsStayInTheBudget() {
        let step = OnboardingWords.steps.first { $0.name == "saved lists" }
        XCTAssertNotNil(step)
        XCTAssertLessThanOrEqual(OnboardingWords.count([step!.title]), OnboardingWords.titleCap)
        XCTAssertLessThanOrEqual(OnboardingWords.count(step!.body), OnboardingWords.bodyCap)
        XCTAssertTrue(Copy.savedListsSubline.contains("terms"), "the sites' terms are said before the answer")
    }

    func testReadingSettingsDecodesTheRecordedOffs() throws {
        let json = #"{"agentEnabled":true,"allowedSites":{},"ackCurrent":true,"exploreSignedIn":true,"neverExplore":{},"#
            + #""youtubeLists":{"watchLater":true,"history":false},"savedLists":{"x":true},"#
            + #""youtubeListsOff":{"watchLater":false,"history":true},"savedListsOff":{"linkedin":true}}"#
        let settings = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(json.utf8))
        XCTAssertTrue(settings.youtubeListsOff.history)
        XCTAssertEqual(settings.savedListsOff, ["linkedin": true])
        let older = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(#"{"agentEnabled":false}"#.utf8))
        XCTAssertEqual(older.savedListsOff, [:], "an older backend sends no offs")
    }

    // MARK: Import a file says where the file comes from

    func testEveryImportAFileSourceSaysWhereItsFileComesFrom() {
        for entry in SourceCatalog.fixed where entry.verb == .importFile || entry.tile?.route == .importFile {
            if entry.id == "notion" { continue }   // `notionHow` says its own
            XCTAssertNotNil(SourceCatalog.exportHow(entry.id), "\(entry.id) offers Import a file with no where-from")
        }
        XCTAssertTrue(Copy.Catalog.howTikTok.contains("Download your data"))
        XCTAssertTrue(Copy.Catalog.howTikTok.contains("JSON"))
        XCTAssertNil(SourceCatalog.exportHow("pinterest"), "a connector imports no file")
    }

    func testAYouTubeListKeptCurrentReadsConnectedOnlyWithAnAgentHere() {
        let youtube = SourceCatalog.fixed.first { $0.id == "youtube" }!
        XCTAssertEqual(SourceCatalog.status(for: youtube, channels: [], overview: [], readableSites: []), .off)
        XCTAssertEqual(SourceCatalog.status(for: youtube, channels: [], overview: [], readableSites: [],
                                            savedListsOn: ["youtube"], localAgent: true), .connected)
        XCTAssertEqual(SourceCatalog.status(for: youtube, channels: [], overview: [], readableSites: [],
                                            savedListsOn: ["youtube"]), .waitingForAgent)
    }

    // MARK: Calendar accounts

    func testCalendarAccountsGroupByAccountMostFirst() {
        let calendars = [CalendarInfo(id: "1", title: "Home", account: "iCloud"),
                         CalendarInfo(id: "2", title: "Work", account: "person@example.com"),
                         CalendarInfo(id: "3", title: "Team", account: "person@example.com"),
                         CalendarInfo(id: "4", title: "Birthdays", account: nil)]
        XCTAssertEqual(CalendarAccountGroup.groups(calendars), [
            CalendarAccountGroup(name: "person@example.com", calendars: 2),
            CalendarAccountGroup(name: "iCloud", calendars: 1),
            CalendarAccountGroup(name: Copy.calendarOnMyMac, calendars: 1),
        ])
        XCTAssertEqual(Copy.calendarIncludes([CalendarAccountGroup(name: "iCloud", calendars: 1),
                                              CalendarAccountGroup(name: "Google", calendars: 3)],
                                             locale: Locale(identifier: "en_US")),
                       "Includes iCloud (1 calendar) · Google (3 calendars)")
    }

    func testAddAGoogleAccountOpensInternetAccountsNotAPermissionPrompt() {
        XCTAssertEqual(CalendarRow.internetAccountsURL.scheme, "x-apple.systempreferences")
        XCTAssertTrue(CalendarRow.internetAccountsURL.absoluteString.contains("Internet-Accounts"))
    }
}
