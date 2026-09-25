import XCTest
@testable import CicadaApp

/// G117 R2 step 7b — decode-tolerance for `GraphNode.isOwner` / `Entity.isOwner`
/// (the wire's `isOwner`, mirroring the entity page's `owner: true`
/// frontmatter via `owner_identity.ensure_owner_entity`). Both fields are
/// additive/defaulted per the plan's decode-tolerance rail (CLAUDE.md: "every
/// new Swift/wire field is additive with a default; an older backend/client
/// payload must still decode") — a payload that omits the key must decode to
/// `false`, not throw, so an older API build (or a cached `SnapshotCache`
/// entry written before this field existed) keeps working.
final class EntityIsOwnerDecodeTests: XCTestCase {

    func testGraphNodeDecodesIsOwnerTrueWhenPresent() throws {
        let json = """
        {"id":"bob-example","name":"Bob Example","type":"person","status":"active",
         "confidence":0.9,"isOwner":true}
        """
        let node = try JSONDecoder().decode(GraphNode.self, from: Data(json.utf8))
        XCTAssertTrue(node.isOwner)
    }

    func testGraphNodeDefaultsIsOwnerFalseWhenAbsent() throws {
        let json = """
        {"id":"alpha-project","name":"Alpha Project","type":"project","status":"active",
         "confidence":0.5}
        """
        let node = try JSONDecoder().decode(GraphNode.self, from: Data(json.utf8))
        XCTAssertFalse(node.isOwner)
    }

    func testEntityDecodesIsOwnerTrueWhenPresent() throws {
        let json = """
        {"id":"bob-example","name":"Bob Example","type":"person","status":"active",
         "confidence":0.9,"created":"2026-09-01","lastReferenced":"2026-09-01",
         "decayRate":0.0,"isOwner":true}
        """
        let entity = try JSONDecoder().decode(Entity.self, from: Data(json.utf8))
        XCTAssertTrue(entity.isOwner)
    }

    func testEntityDefaultsIsOwnerFalseWhenAbsent() throws {
        let json = """
        {"id":"alpha-project","name":"Alpha Project","type":"project","status":"active",
         "confidence":0.5,"created":"2026-09-01","lastReferenced":"2026-09-01",
         "decayRate":0.05}
        """
        let entity = try JSONDecoder().decode(Entity.self, from: Data(json.utf8))
        XCTAssertFalse(entity.isOwner)
    }
}
