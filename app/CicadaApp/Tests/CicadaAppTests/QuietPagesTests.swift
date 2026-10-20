import XCTest
@testable import CicadaApp

/// Owner rulings 2026-10-20 — imported-only pages are quiet until the person mentions them, and the address book's
/// "me" card belongs to the owner's page. The wire's `quiet` is decode-tolerant (an older backend and a cached snapshot
/// omit it), reaches graph.js only when true, and dims a Clusters row; `isMe` crosses the wire only on that one card.
/// Synthetic names only.
final class QuietPagesTests: XCTestCase {

    func testGraphNodeAndEntityDecodeQuietAndDefaultToLit() throws {
        let quiet = """
        {"id":"media-a-saved-video","name":"A Saved Video","type":"media","status":"active","confidence":0.7,
         "quiet":true}
        """
        XCTAssertTrue(try JSONDecoder().decode(GraphNode.self, from: Data(quiet.utf8)).quiet)
        let lit = """
        {"id":"alpha-project","name":"Alpha Project","type":"project","status":"active","confidence":0.5}
        """
        XCTAssertFalse(try JSONDecoder().decode(GraphNode.self, from: Data(lit.utf8)).quiet)
        let entity = """
        {"id":"media-a-saved-video","name":"A Saved Video","type":"media","status":"active","confidence":0.7,
         "created":"2026-10-01","lastReferenced":"2026-10-01","decayRate":0.0,"quiet":true}
        """
        XCTAssertTrue(try JSONDecoder().decode(Entity.self, from: Data(entity.utf8)).quiet)
    }

    func testGraphJsHearsQuietOnlyWhenTrue() {
        let quiet = GraphNode(id: "media-a", name: "A", type: .media, quiet: true)
        let lit = GraphNode(id: "alpha-project", name: "Alpha Project", type: .project)
        XCTAssertEqual(GraphViewModel.nodeDict(quiet)["quiet"] as? Bool, true)
        XCTAssertNil(GraphViewModel.nodeDict(lit)["quiet"], "a lit node's payload is unchanged")
    }

    @MainActor
    func testAGraphStubCarriesQuietToTheClustersRows() {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        store.graph.value = GraphResponse(nodes: [GraphNode(id: "media-a", name: "A", type: .media, quiet: true),
                                                  GraphNode(id: "alpha-project", name: "Alpha Project", type: .project)])
        store.graph.loadedAt = Date()
        let vm = GraphViewModel(store: store)
        XCTAssertEqual(vm.entities.first { $0.id == "media-a" }?.quiet, true)
        XCTAssertEqual(vm.entities.first { $0.id == "alpha-project" }?.quiet, false)
    }

    func testTheMeCardIsTheOnlyCardThatSaysIsMe() throws {
        let me = ContactMapper.record(id: "ME", given: "Pat", family: "Owner", organization: "", jobTitle: "",
                                      emails: 0, phones: 0, hasBirthday: false, thumbnail: nil, isMe: true)
        let other = ContactMapper.record(id: "C1", given: "Erin", family: "Example", organization: "", jobTitle: "",
                                         emails: 1, phones: 0, hasBirthday: false, thumbnail: nil)
        let meJSON = String(decoding: try JSONEncoder().encode(me), as: UTF8.self)
        let otherJSON = String(decoding: try JSONEncoder().encode(other), as: UTF8.self)
        XCTAssertTrue(meJSON.contains("\"isMe\":true"))
        XCTAssertFalse(otherJSON.contains("isMe"), "every other card crosses the wire exactly as before")
    }

    func testTheSyncResultCountsTheWaitingCards() throws {
        let json = #"{"contacts":3,"matched":1,"people":1,"unmatched":2,"waiting":2,"bank":"default"}"#
        XCTAssertEqual(try JSONDecoder().decode(ContactsSyncResult.self, from: Data(json.utf8)).waiting, 2)
    }

    func testAQuietNameStepsDownTheLadderNeverToTheAccent() {
        XCTAssertEqual(CicadaTheme.quietName, CicadaTheme.textTertiaryOnFill)
        XCTAssertNotEqual(CicadaTheme.quietName, CicadaTheme.accent)
        XCTAssertLessThan(CicadaTheme.quietPictureOpacity, 1)
    }
}

/// Review of #391: forgetting the kept LinkedIn export says what happened, in words, with counts only.
final class LinkedInForgetWordsTests: XCTestCase {
    func testForgetSaysHowManyAndNeverAName() {
        XCTAssertEqual(LinkedInConnectionsWords.forgotten(0), "No connections were kept for this memory.")
        XCTAssertTrue(LinkedInConnectionsWords.forgotten(1).hasPrefix("Forgot 1 kept connection."))
        XCTAssertTrue(LinkedInConnectionsWords.forgotten(3).hasPrefix("Forgot 3 kept connections."))
    }
}
