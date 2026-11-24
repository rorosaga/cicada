import XCTest
@testable import CicadaApp

/// G245 (arrival join, owner 2026-11-24: "yes ofc join ... and let him say no"): a first name Sleep joined to the person who
/// newly appeared the same week is said on the connection's row and in the page's History, each with "Not them"; the notes'
/// reader sends each note's creation moment beside the dump (a note's modification date is its last edit). Names invented.
final class ArrivalJoinTests: XCTestCase {
    // MARK: the row

    func testAConnectionRowDecodesWhatTheBackendSaysAboutAJoinAndAnOlderBackendsRowDoesNot() throws {
        let joined = Data(#"""
        {"rows":[{"id":"a1","name":"Alex Example","headline":"Founder","day":"2026-11-12","precision":"day","page":"alex",
                  "joined":{"page":"alex","name":"Alex","on":"2026-11-24","delta":2,"holderDay":"2026-11-10"}},
                 {"id":"b2","name":"Bo Example","day":"2026-11-02"}],"total":2,"kept":2}
        """#.utf8)
        let page = try JSONDecoder().decode(LinkedInConnectionsPage.self, from: joined)
        XCTAssertEqual(page.rows[0].joined, LinkedInConnection.Join(page: "alex", name: "Alex", on: "2026-11-24", delta: 2,
                                                                     holderDay: "2026-11-10"))
        XCTAssertNil(page.rows[1].joined)
    }

    func testAMalformedJoinDropsThatFieldAloneNeverTheRow() throws {
        let data = Data(#"{"rows":[{"id":"a1","name":"Alex Example","joined":{"delta":"two"}}],"total":1}"#.utf8)
        let page = try JSONDecoder().decode(LinkedInConnectionsPage.self, from: data)
        XCTAssertEqual(page.rows.count, 1)
        XCTAssertNil(page.rows[0].joined)
    }

    func testTheWordsNameTheFirstNameAndSayWhyAndNeverAProvider() {
        XCTAssertEqual(Copy.Arrivals.rowLine("Alex"), "Joined to Alex: the same first name, new the same week")
        XCTAssertEqual(Copy.Arrivals.notThem, "Not them")
        for words in [Copy.Arrivals.rowLine("Alex"), Copy.Arrivals.notThemHelp, Copy.Arrivals.historyJoined("Alex Example"),
                      Copy.Arrivals.historyJoined(nil)] {
            for provider in ["Claude", "GPT", "model", "OpenAI", "Anthropic"] {
                XCTAssertFalse(words.contains(provider), "\(provider) in \(words)")
            }
        }
    }

    // MARK: the page's History

    private func entry(join: String?, joinedAs: String? = nil) throws -> EntityHistoryEntry {
        var object: [String: Any] = ["date": "2026-11-24", "changeType": "updated", "description": "d", "author": "cicada",
                                     "commitHash": "abc", "trigger": "sleep/arrival-join", "via": "sleep", "undoable": true]
        if let join { object["join"] = join }
        if let joinedAs { object["joinedAs"] = joinedAs }
        return try JSONDecoder().decode(EntityHistoryEntry.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func testAnArrivalJoinsHistoryRowSaysWhomItJoinedAndOffersNotThem() throws {
        let row = try entry(join: "arrival", joinedAs: "Alex Example")
        XCTAssertEqual(row.joinedAs, "Alex Example")
        XCTAssertTrue(row.undoable)
        XCTAssertEqual(HistoryRowWords.sentence(row), "Cicada joined Alex Example to this page: the same first name, new the same week")
        let older = try entry(join: "arrival")
        XCTAssertTrue(HistoryRowWords.sentence(older).hasSuffix("joined a name to this page: the same first name, new the same week"))
    }

    func testAMergeStillSaysMergedAndNeverTheArrivalsWords() throws {
        let row = try entry(join: "merge")
        XCTAssertFalse(HistoryRowWords.sentence(row).contains("same first name"))
    }

    // MARK: the notes' reader

    private let fs = AppleNotesReader.fieldSeparator
    private let rs = AppleNotesReader.recordSeparator

    private func note(_ id: String, created: String? = nil) -> String {
        var fields = [id, "event", "body", "c", "m", "Notes", "2026-11-06T11:30:00", "3600", "iCloud"]
        if let created { fields.append(created) }
        return fields.joined(separator: fs)
    }

    func testTheScriptAsksForTheCreationMomentTheSameLocaleFreeWayAsTheModificationOne() {
        let script = AppleNotesReader.script
        XCTAssertTrue(script.contains("(item i of cDates) as «class isot» as string"))
        XCTAssertTrue(script.contains("(item i of mDates) as «class isot» as string"))
    }

    func testTheCreationMomentTravelsBesideTheDumpAndNeverInIt() {
        let parts = AppleNotesReader.split([note("id-1", created: "2026-11-02T09:00:00"), note("id-2")].joined(separator: rs))
        XCTAssertEqual(parts.created, ["id-1": "2026-11-02T09:00:00"])
        XCTAssertEqual(parts.accounts, ["id-1": "iCloud", "id-2": "iCloud"])
        XCTAssertEqual(parts.dump.components(separatedBy: rs).map { $0.components(separatedBy: fs).count }, [8, 8],
                       "an older backend counts a record's fields: the dump holds the same 8 as ever")
        XCTAssertFalse(parts.dump.contains("2026-11-02T09:00:00"))
    }

    func testAnEmptyCreationMomentIsNoneAndTheBodyCarriesTheKeyOnlyWhenThereIsOne() {
        XCTAssertTrue(AppleNotesReader.split(note("id-1", created: "  ")).created.isEmpty)
        let none = APIClient.notesSyncBody(dump: "d", accounts: [:], locked: [], lockedKeys: [], pinned: nil, folderPaths: [:], folders: [])
        XCTAssertNil(none["noteCreated"])
        let some = APIClient.notesSyncBody(dump: "d", accounts: [:], locked: [], lockedKeys: [], pinned: nil, folderPaths: [:],
                                           folders: [], created: ["id-1": "2026-11-02T09:00:00"])
        XCTAssertEqual(some["noteCreated"] as? [String: String], ["id-1": "2026-11-02T09:00:00"])
    }
}
