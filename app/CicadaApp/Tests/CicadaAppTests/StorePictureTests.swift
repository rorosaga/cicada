import XCTest
@testable import CicadaApp

/// C11 / R-PE10 — what an avatar draws: a write in flight, else the graph snapshot, else what the surface holds; a
/// settled write yields only to a newer snapshot that DISAGREES.
@MainActor
final class StorePictureTests: XCTestCase {
    private func store() -> Store {
        let s = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        s.bank = "work"
        return s
    }

    private func node(_ source: String?, url: String? = nil) -> GraphNode {
        GraphNode(id: "acme-example", name: "Acme Example", type: .company, picture: url, pictureSource: source)
    }

    func testTheOverrideTheSnapshotAndWhatIsHeld() {
        let s = store()
        s.graph.value = GraphResponse(nodes: [node("logo", url: "/entities/acme-example/logo")])
        s.graph.loadedAt = Date(timeIntervalSince1970: 100)
        XCTAssertEqual(s.picture(for: "acme-example")?.source, .logo)
        let key = Store.pictureKey(bank: "work", id: "acme-example")
        s.pictureOverrides[key] = PictureOverride(picture: EntityPictureRef(url: nil, source: .initials),
                                                  inputs: PictureInputs(type: "company", choice: "initials", logo: true),
                                                  at: .distantFuture)
        XCTAssertEqual(s.picture(for: "acme-example")?.source, .initials, "in flight, the paint wins")
        s.pictureOverrides[key]?.at = Date(timeIntervalSince1970: 200)
        s.graph.loadedAt = Date(timeIntervalSince1970: 300)
        XCTAssertEqual(s.picture(for: "acme-example")?.source, .logo, "a newer snapshot that disagrees wins")
        s.graph.value = GraphResponse(nodes: [node("initials")])
        s.graph.loadedAt = Date(timeIntervalSince1970: 400)
        XCTAssertEqual(s.picture(for: "acme-example")?.source, .initials)
        XCTAssertEqual(s.pictureInputs(for: "acme-example", held: nil)?.choice, "initials",
                       "an agreeing snapshot keeps the override's fresher inputs")
        XCTAssertNil(s.picture(for: "no-node"), "no node and nothing held draws the fallback")
        let held = EntityPictureRef(url: "/entities/no-node/logo", source: .logo)
        XCTAssertEqual(s.picture(for: "no-node", held: held), held)
        s.bank = "demo"
        XCTAssertNil(s.pictureOverride(for: "acme-example"), "an override belongs to its bank")
    }
}
