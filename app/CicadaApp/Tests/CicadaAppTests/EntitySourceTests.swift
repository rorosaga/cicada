import XCTest
@testable import CicadaApp

/// A fake-transport `URLProtocol` for `APIClient` tests. `APIClient.shared`
/// always talks to a real backend, so these tests never touch it — instead
/// each test builds its own `APIClient(session:)` (see the test-only init
/// added alongside G61) whose `URLSessionConfiguration` lists ONLY this
/// protocol class, guaranteeing every request is intercepted and none ever
/// reaches the network.
final class MockURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    static func makeSession() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        return URLSession(configuration: config)
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = MockURLProtocol.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class EntitySourceTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Decoding

    func testEntitySourceDecodesTheCamelCaseWirePayload() throws {
        let json = """
        {
            "ref": "https://example.com/docs",
            "kind": "url",
            "predicate": "pricing",
            "addedBy": "user",
            "addedAt": "2026-08-30"
        }
        """.data(using: .utf8)!

        let source = try JSONDecoder().decode(EntitySource.self, from: json)

        XCTAssertEqual(source.ref, "https://example.com/docs")
        XCTAssertEqual(source.kind, "url")
        XCTAssertEqual(source.predicate, "pricing")
        XCTAssertEqual(source.addedBy, "user")
        XCTAssertEqual(source.addedAt, "2026-08-30")
        XCTAssertEqual(source.url, URL(string: "https://example.com/docs"))
        XCTAssertEqual(source.icon, "link")
    }

    func testEntitySourceListDecodesTheEnvelope() throws {
        let json = """
        {
            "entityId": "recruiting-thread",
            "sources": [
                {"ref": "~/notes/recruiting.md", "kind": "path", "addedBy": "gpt-5.4-mini", "addedAt": "2026-08-01"}
            ]
        }
        """.data(using: .utf8)!

        let list = try JSONDecoder().decode(EntitySourceList.self, from: json)

        XCTAssertEqual(list.entityId, "recruiting-thread")
        XCTAssertEqual(list.sources.count, 1)
        XCTAssertEqual(list.sources[0].kind, "path")
        XCTAssertNil(list.sources[0].url)
        XCTAssertEqual(list.sources[0].icon, "folder")
    }

    func testEntitySourceNoteKindHasNoURLAndTheNoteIcon() throws {
        let json = """
        {"ref": "ask HR about equity refresh", "kind": "note", "addedBy": "user", "addedAt": "2026-08-30"}
        """.data(using: .utf8)!

        let source = try JSONDecoder().decode(EntitySource.self, from: json)

        XCTAssertNil(source.url)
        XCTAssertEqual(source.icon, "text.quote")
    }

    // MARK: - APIClient.fetchEntitySources

    func testFetchEntitySourcesGETsAndDecodesTheEnvelope() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/entities/recruiting-thread/sources")
            let body = """
            {"entityId": "recruiting-thread", "sources": [
                {"ref": "https://example.com", "kind": "url", "addedBy": "user", "addedAt": "2026-08-30"}
            ]}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let sources = try await APIClient(session: MockURLProtocol.makeSession()).fetchEntitySources(entityId: "recruiting-thread")

        XCTAssertEqual(sources.count, 1)
        XCTAssertEqual(sources[0].ref, "https://example.com")
    }

    // MARK: - APIClient.addEntitySource

    func testAddEntitySourcePOSTsTheRefAndReturnsTheUpdatedList() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/entities/recruiting-thread/sources")
            let bodyData = request.httpBodyStream.map { stream -> Data in
                stream.open()
                defer { stream.close() }
                var data = Data()
                let bufferSize = 1024
                var buffer = [UInt8](repeating: 0, count: bufferSize)
                while stream.hasBytesAvailable {
                    let read = stream.read(&buffer, maxLength: bufferSize)
                    if read <= 0 { break }
                    data.append(buffer, count: read)
                }
                return data
            } ?? request.httpBody ?? Data()
            let payload = try? JSONSerialization.jsonObject(with: bodyData) as? [String: Any]
            XCTAssertEqual(payload?["ref"] as? String, "https://example.com/pricing")

            let body = """
            {"entityId": "recruiting-thread", "sources": [
                {"ref": "https://example.com/pricing", "kind": "url", "addedBy": "user", "addedAt": "2026-08-30"}
            ]}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let sources = try await APIClient(session: MockURLProtocol.makeSession()).addEntitySource(
            entityId: "recruiting-thread", ref: "https://example.com/pricing"
        )

        XCTAssertEqual(sources.count, 1)
        XCTAssertEqual(sources[0].ref, "https://example.com/pricing")
    }

    // MARK: - APIClient.deleteEntitySource

    func testDeleteEntitySourceDELETEsByIndexAndReturnsTheUpdatedList() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/entities/recruiting-thread/sources/0")
            let body = """
            {"entityId": "recruiting-thread", "sources": []}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let sources = try await APIClient(session: MockURLProtocol.makeSession()).deleteEntitySource(entityId: "recruiting-thread", index: 0)

        XCTAssertTrue(sources.isEmpty)
    }
}
