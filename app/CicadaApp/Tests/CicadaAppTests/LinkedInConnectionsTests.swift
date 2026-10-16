import XCTest
@testable import CicadaApp

/// LinkedIn connections (2026-10-16): the LinkedIn tile offers Connections in one sentence, says what an import will
/// do in counts (never a name), and sends the export's own day with a lone CSV only.
final class LinkedInConnectionsTests: XCTestCase {
    func testOnlyTheLinkedInTileOffersConnectionsAndSaysSoBeforeItOpens() {
        XCTAssertTrue(AddSourceTile.linkedin.offersConnections)
        for tile in AddSourceTile.allCases where tile != .linkedin { XCTAssertFalse(tile.offersConnections, tile.rawValue) }
        XCTAssertEqual(AddSourceTile.linkedin.routeLines, ["Saved items export", "Connections"])
        XCTAssertTrue(AddSourceTile.linkedin.blurb.contains("connections"))
    }

    func testWhatItDoesIsOneSentenceThatPromisesNoNewPeople() {
        let what = LinkedInConnectionsWords.what
        XCTAssertEqual(what.filter { $0 == "." }.count, 1)
        XCTAssertTrue(what.contains("never adds anyone new"))
    }

    func testThePreviewIsCountsAndTheButtonSaysHowManyPeople() {
        let some = LinkedInConnectionsPreview(connections: 420, matched: 12, ambiguous: 2, unmatched: 406,
                                              exportedOn: "2026-10-01")
        XCTAssertEqual(LinkedInConnectionsWords.preview(some),
                       "12 of your 420 connections are people Cicada already knows. 2 share a name with more than one person and are left out. As of 2026-10-01.")
        XCTAssertEqual(LinkedInConnectionsWords.confirm(some), "Add to 12 people")
        let one = LinkedInConnectionsPreview(connections: 3, matched: 1, ambiguous: 0, unmatched: 2, exportedOn: "2026-10-01")
        XCTAssertEqual(LinkedInConnectionsWords.confirm(one), "Add to 1 person")
        let none = LinkedInConnectionsPreview(connections: 3, matched: 0, ambiguous: 0, unmatched: 3, exportedOn: "2026-10-01")
        XCTAssertTrue(LinkedInConnectionsWords.preview(none).contains("Nothing will be added"))
        XCTAssertEqual(LinkedInConnectionsWords.confirm(none), "Keep for later")
    }

    func testTheDoneLineSaysWhatChanged() {
        let nothing = LinkedInConnectionsImport(connections: 3, matched: 1, sourcesAdded: 0, claimsWritten: 0,
                                                claimsClosed: 0, older: 0)
        XCTAssertEqual(LinkedInConnectionsWords.done(nothing), "Nothing new: memory already has what this export says.")
        let newer = LinkedInConnectionsImport(connections: 3, matched: 2, sourcesAdded: 0, claimsWritten: 2,
                                              claimsClosed: 1, older: 0)
        XCTAssertEqual(LinkedInConnectionsWords.done(newer), "Updated 2 people, replacing 1 older LinkedIn detail.")
    }

    func testTheExportDayGoesWithALoneCSVOnly() {
        let day = ISO8601DateFormatter().date(from: "2026-09-30T12:00:00Z")
        XCTAssertEqual(LinkedInConnectionsWords.exportedOn(fileURL: URL(fileURLWithPath: "/tmp/Connections.csv"),
                                                           modified: day), "2026-09-30")
        XCTAssertNil(LinkedInConnectionsWords.exportedOn(fileURL: URL(fileURLWithPath: "/tmp/export.zip"), modified: day))
        XCTAssertEqual(APIClient.exportedOnQuery("2026-09-30"), "?exported_on=2026-09-30")
        XCTAssertEqual(APIClient.exportedOnQuery("not a day"), "")
        XCTAssertEqual(APIClient.exportedOnQuery(nil), "")
    }

    func testTheWireDecodesTheBackendsCamelCase() throws {
        let json = #"{"connections":7,"matched":3,"ambiguous":3,"unmatched":1,"skipped":0,"withCompany":7,"exportedOn":"2026-01-15","bank":"default"}"#
        let p = try JSONDecoder().decode(LinkedInConnectionsPreview.self, from: Data(json.utf8))
        XCTAssertEqual(p.matched, 3)
        let done = #"{"connections":7,"matched":3,"ambiguous":3,"unmatched":1,"sourcesAdded":3,"claimsWritten":9,"claimsClosed":0,"older":0,"removedKeptOut":0,"exportedOn":"2026-01-15","bank":"default"}"#
        XCTAssertEqual(try JSONDecoder().decode(LinkedInConnectionsImport.self, from: Data(done.utf8)).claimsWritten, 9)
    }

    func testTheLinkedInSkillIsListedWithCicadasOwn() {
        XCTAssertEqual(CicadaSkillBundle.linkedinPeople.rawValue, "linkedin-people")
        XCTAssertEqual(CicadaSkillBundle.linkedinPeople.title, "What people do now")
    }
}
