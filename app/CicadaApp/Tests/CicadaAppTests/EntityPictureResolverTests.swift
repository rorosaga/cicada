import XCTest
@testable import CicadaApp

/// C11 (plan R-PE3, R-PE5, R-PE6) — `EntityPictureResolver` and `entity_picture.resolve` run ONE table,
/// `api/tests/fixtures/entity_picture.json`: add a rung on one side only and the other goes red.
final class EntityPictureResolverTests: XCTestCase {
    private struct Answer: Decodable, Equatable {
        let source: String?
        let url: String?
    }

    private struct Case: Decodable {
        let name: String
        let id: String
        let input: PictureInputs
        let expected: Answer
        let detected: Answer
    }

    private func cases() throws -> [Case] {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/entity_picture.json")
        let cases = try JSONDecoder().decode([Case].self, from: Data(contentsOf: file))
        XCTAssertGreaterThanOrEqual(cases.count, 12, "read \(cases.count) cases from \(file.path) — vacuous below 12")
        return cases
    }

    private func answer(_ ref: EntityPictureRef?) -> Answer { Answer(source: ref?.source.rawValue, url: ref?.url) }

    func testTheSharedFixture() throws {
        for c in try cases() {
            XCTAssertEqual(answer(EntityPictureResolver.resolve(id: c.id, c.input)), c.expected, c.name)
            XCTAssertEqual(answer(EntityPictureResolver.detected(id: c.id, c.input)), c.detected, c.name)
        }
    }

    /// R-PE5 — a malformed answer draws the fallback, never a broken image.
    func testTheWirePairNeverDrawsABrokenImage() {
        XCTAssertEqual(EntityPictureRef.wire(url: "/entities/acme-example/logo", source: "logo"),
                       EntityPictureRef(url: "/entities/acme-example/logo", source: .logo))
        XCTAssertEqual(EntityPictureRef.wire(url: "/stray", source: "initials"), EntityPictureRef(url: nil, source: .initials))
        XCTAssertNil(EntityPictureRef.wire(url: nil, source: "upload"))
        XCTAssertNil(EntityPictureRef.wire(url: "/entities/x/logo", source: nil))
        XCTAssertNil(EntityPictureRef.wire(url: "/entities/x/logo", source: "gravatar"))
    }

    /// R-PE6 — Cicada's bearer goes only to Cicada's own API.
    func testTheBearerGoesOnlyToCicadasOwnAPI() throws {
        XCTAssertEqual(PictureURL.parse("/entities/bob-example/picture?v=3f9a1c0b2d4e"),
                       .api(path: "/entities/bob-example/picture?v=3f9a1c0b2d4e"))
        let thumb = try XCTUnwrap(URL(string: "https://img.example.com/1.jpg"))
        XCTAssertEqual(PictureURL.parse("https://img.example.com/1.jpg"), .external(thumb))
        for refused in ["http://img.example.com/1.jpg", "file:///etc/hosts", "data:image/png;base64,AAAA", "/etc/hosts",
                        "entities/x/picture", "/entities/../banks/x", "//img.example.com/1.jpg", "",
                        " https://img.example.com/1.jpg"] {
            XCTAssertNil(PictureURL.parse(refused), refused)
        }
        XCTAssertNil(PictureStore.externalRequest(thumb).value(forHTTPHeaderField: "Authorization"))
        XCTAssertFalse(PictureStore.externalRequest(thumb).httpShouldHandleCookies)
    }

    /// Decode tolerance: a node and a page from an older backend decode with no picture.
    func testTheNodeAndThePageDecodeTheirPicturesAndTolerateAnOlderBackend() throws {
        let node = try JSONDecoder().decode(GraphNode.self, from: Data(#"""
        {"id":"bob-example","name":"Bob Example","type":"person","status":"active","confidence":0.9,
         "picture":"/entities/bob-example/picture?v=3f9a1c0b2d4e","pictureSource":"upload","lastReferenced":"2026-09-20"}
        """#.utf8))
        XCTAssertEqual(node.pictureRef, EntityPictureRef(url: "/entities/bob-example/picture?v=3f9a1c0b2d4e", source: .upload))
        XCTAssertEqual(node.lastReferenced, "2026-09-20")
        let old = try JSONDecoder().decode(GraphNode.self, from: Data(#"""
        {"id":"alpha-project","name":"Alpha Project","type":"project","status":"active","confidence":0.5}
        """#.utf8))
        XCTAssertNil(old.pictureRef)
        XCTAssertNil(old.lastReferenced)
        let page = try JSONDecoder().decode(Entity.self, from: Data(#"""
        {"id":"acme-example","name":"Acme Example","type":"company","status":"active","confidence":0.8,
         "created":"2026-01-05","lastReferenced":"2026-09-01","decayRate":0.05,
         "picture":"/entities/acme-example/logo","pictureSource":"logo","pictureInputs":{"type":"company","logo":true}}
        """#.utf8))
        XCTAssertEqual(page.pictureRef?.source, .logo)
        XCTAssertEqual(page.pictureInputs, PictureInputs(type: "company", logo: true))
    }
}
