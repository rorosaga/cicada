import XCTest
@testable import CicadaApp

/// G66 §1.7 — the decay class on the app side: decode tolerance (old cached
/// snapshots must still load), the chip copy, and the override PUT.
final class DecayClassTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Copy

    func testEveryClassHasAHumanChipStringMatchingTheSpec() {
        XCTAssertEqual(DecayClass.evergreen.chipText, "evergreen · never fades")
        XCTAssertEqual(DecayClass.durable.chipText, "durable · fades slowly")
        XCTAssertEqual(DecayClass.active.chipText, "active")
        XCTAssertEqual(DecayClass.volatile.chipText, "volatile · expected to change")
    }

    func testAllFourClassesArePickable() {
        XCTAssertEqual(
            DecayClass.allCases.map(\.rawValue),
            ["evergreen", "durable", "active", "volatile"]
        )
    }

    // MARK: - Decode tolerance

    func testEntityDecodesTheDecayClassFromTheWire() throws {
        let json = """
        {"id": "mongodb", "name": "MongoDB", "type": "tool", "status": "active",
         "confidence": 0.8, "created": "2026-01-01", "lastReferenced": "2026-08-01",
         "decayRate": 0.15, "decayClass": "volatile", "version": 1,
         "markdownContent": "", "history": []}
        """.data(using: .utf8)!

        let entity = try JSONDecoder().decode(Entity.self, from: json)

        XCTAssertEqual(entity.decayClass, .volatile)
    }

    func testEntityFromAnOlderBackendDefaultsToActive() throws {
        let json = """
        {"id": "mongodb", "name": "MongoDB", "type": "tool", "status": "active",
         "confidence": 0.8, "created": "2026-01-01", "lastReferenced": "2026-08-01",
         "decayRate": 0.05, "version": 1, "markdownContent": "", "history": []}
        """.data(using: .utf8)!

        XCTAssertEqual(try JSONDecoder().decode(Entity.self, from: json).decayClass, .active)
    }

    func testAnUnknownFutureClassNeverFailsTheDecode() throws {
        let json = """
        {"id": "x", "name": "X", "type": "tool", "status": "active", "confidence": 0.5,
         "created": "2026-01-01", "lastReferenced": "2026-01-01", "decayRate": 0.05,
         "decayClass": "glacial", "version": 1, "markdownContent": "", "history": []}
        """.data(using: .utf8)!

        XCTAssertEqual(try JSONDecoder().decode(Entity.self, from: json).decayClass, .active)
    }

    func testGraphNodeDecodesTheClassAndToleratesAnOldCachedSnapshot() throws {
        let withClass = """
        {"id": "a", "name": "A", "type": "concept", "status": "active",
         "confidence": 0.5, "decayClass": "durable"}
        """.data(using: .utf8)!
        let without = """
        {"id": "a", "name": "A", "type": "concept", "status": "active", "confidence": 0.5}
        """.data(using: .utf8)!

        XCTAssertEqual(try JSONDecoder().decode(GraphNode.self, from: withClass).decayClass,
                       .durable)
        XCTAssertEqual(try JSONDecoder().decode(GraphNode.self, from: without).decayClass,
                       .active)
    }

    // MARK: - APIClient.setDecayClass

    func testSetDecayClassPUTsTheCamelCaseBodyAndReturnsTheUpdatedEntity() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.url?.path, "/entities/mongodb/decay")

            let bodyData = request.httpBodyStream.map { stream -> Data in
                stream.open()
                defer { stream.close() }
                var data = Data()
                var buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable {
                    let read = stream.read(&buffer, maxLength: 1024)
                    if read <= 0 { break }
                    data.append(buffer, count: read)
                }
                return data
            } ?? request.httpBody ?? Data()
            let payload = try? JSONSerialization.jsonObject(with: bodyData) as? [String: Any]
            XCTAssertEqual(payload?["decayClass"] as? String, "evergreen")

            let body = """
            {"id": "mongodb", "name": "MongoDB", "type": "tool", "status": "active",
             "confidence": 0.8, "created": "2026-01-01", "lastReferenced": "2026-08-01",
             "decayRate": 0.0, "decayClass": "evergreen", "version": 1,
             "markdownContent": "", "history": []}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let entity = try await APIClient(session: MockURLProtocol.makeSession())
            .setDecayClass(entityId: "mongodb", .evergreen)

        XCTAssertEqual(entity.decayClass, .evergreen)
        XCTAssertEqual(entity.decayRate, 0.0)
    }

    func testSetDecayClassPercentEncodesALegacyEntityId() async throws {
        MockURLProtocol.handler = { request in
            // Assert on absoluteString, NOT `url.path`: Foundation decodes
            // percent-escapes out of `.path`, so the encoding is invisible there.
            XCTAssertTrue(
                request.url?.absoluteString.hasSuffix("/entities/atle%CC%81tico/decay") == true,
                request.url?.absoluteString ?? "nil"
            )
            let body = """
            {"id": "atlético", "name": "Atletico", "type": "company", "status": "active",
             "confidence": 0.5, "created": "2026-01-01", "lastReferenced": "2026-01-01",
             "decayRate": 0.05, "decayClass": "active", "version": 1,
             "markdownContent": "", "history": []}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        _ = try await APIClient(session: MockURLProtocol.makeSession())
            .setDecayClass(entityId: "atle\u{0301}tico", .active)
    }

    func testSetDecayClassPropagatesAnHTTPFailure() async {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 404,
                                            httpVersion: nil, headerFields: nil)!
            return (response, Data("Entity nope not found".utf8))
        }

        do {
            _ = try await APIClient(session: MockURLProtocol.makeSession())
                .setDecayClass(entityId: "nope", .durable)
            XCTFail("a 404 must surface so the picker can revert")
        } catch {
            // expected — the caller reverts the optimistic chip
        }
    }
}
