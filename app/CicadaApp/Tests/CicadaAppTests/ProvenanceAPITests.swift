import XCTest
@testable import CicadaApp

/// G118 slice 2 — the four read routes are asked for with exactly the query
/// the server takes (`api/routers/episodes.py`, `claims.py`), and an ETag
/// round-trips so a 304 keeps what the cache already holds.
final class ProvenanceAPITests: XCTestCase {

    func testSectionProvenanceDecodesServerIdentityRangesAndReasoning() throws {
        let json = #"""
        {"entityId":"alpha-project","pageBodyHash":"abcdef123456","sectionSchema":1,"sectionsPartial":false,
         "sections":[{"key":"key_facts","title":"Key Facts","status":"partial","itemCount":2,
          "recordedItems":1,"spanCount":0,"reasoningCount":1,"unmatchedRecords":1,"partial":false,
          "items":[{"identity":"server-owned-item","text":"Synthetic fact 🐝.","bodyRanges":[[14,31]],
            "ambiguous":false,"evidence":[{"evidence":{"episode":"ep_2026-10-07_001","start":-1,"end":-1,
            "kind":"reasoning","hash":"123456abcdef"},"sourceTitle":"Synthetic conversation",
            "conversationId":"session-example","sourceAvailable":true,"status":"not_checked","span":null}]}]}]}
        """#
        let value = try JSONDecoder().decode(EntityProvenance.self, from: Data(json.utf8))
        XCTAssertEqual(value.pageBodyHash, "abcdef123456")
        XCTAssertEqual(value.sectionSchema, 1)
        XCTAssertFalse(value.sectionsPartial)
        let section = try XCTUnwrap(value.sections.first)
        XCTAssertEqual(section.recordedItems, 1)
        XCTAssertEqual(section.unmatchedRecords, 1)
        let item = try XCTUnwrap(section.items.first)
        XCTAssertEqual(item.identity, "server-owned-item")
        XCTAssertEqual(item.bodyRanges, [[14, 31]])
        XCTAssertEqual(item.evidence.first?.evidence?.kind, .reasoning)
        XCTAssertNil(item.evidence.first?.span)
    }

    func testOlderBackendHasNoSectionTokenOrRows() throws {
        let value = try JSONDecoder().decode(EntityProvenance.self, from: Data(#"{"entityId":"alpha-project"}"#.utf8))
        XCTAssertNil(value.pageBodyHash)
        XCTAssertEqual(value.sectionSchema, 0)
        XCTAssertTrue(value.sections.isEmpty)
        XCTAssertFalse(value.sectionsPartial)
    }

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    private func respond(_ body: String, status: Int = 200, etag: String? = nil,
                         check: @escaping (URLRequest) -> Void) {
        MockURLProtocol.handler = { request in
            check(request)
            var headers: [String: String] = [:]
            if let etag { headers["ETag"] = etag }
            let response = HTTPURLResponse(url: request.url!, statusCode: status,
                                           httpVersion: nil, headerFields: headers)!
            return (response, Data(body.utf8))
        }
    }

    private var client: APIClient { APIClient(session: MockURLProtocol.makeSession()) }

    func testSpanAsksForStartEndAndHash() async throws {
        respond(#"{"episode": "ep_2026-09-03_004", "text": "x", "start": 1, "end": 2}"#) { request in
            XCTAssertEqual(request.url?.path, "/episodes/ep_2026-09-03_004/span")
            XCTAssertEqual(request.url?.query, "start=1&end=2&hash=a1b2c3d4e5f6")
        }
        let span = try await client.fetchEpisodeSpan(episode: "ep_2026-09-03_004", start: 1, end: 2,
                                                     hash: "a1b2c3d4e5f6")
        XCTAssertEqual(span.text, "x")
    }

    func testTextSpellsEachFocusTheWayTheRouterReadsIt() {
        XCTAssertEqual(APIClient.provenancePath("/episodes", "ep_1", "/text"), "/episodes/ep_1/text")
        XCTAssertEqual(
            APIClient.provenancePath("/episodes", "ep_1", "/text",
                                     query: ReaderFocusQuery.span(start: 3, end: 9, hash: nil).queryItems),
            "/episodes/ep_1/text?start=3&end=9",
            "no hash means no hash parameter — the inbox cause is current by construction (R-PB16)")
        XCTAssertEqual(
            APIClient.provenancePath("/episodes", "ep_1", "/text",
                                     query: ReaderFocusQuery.mention(entityId: "alpha-project").queryItems),
            "/episodes/ep_1/text?focus=alpha-project")
        XCTAssertEqual(APIClient.provenancePath("/episodes", "ep/../x", "/text"), "/episodes/ep%2F..%2Fx/text",
                       "a slash in an id never reshapes the path")
        XCTAssertEqual(
            APIClient.provenancePath("/episodes", "ep_1", "/text",
                                     query: ReaderFocusQuery.mention(entityId: "a+b").queryItems),
            "/episodes/ep_1/text?focus=a%2Bb", "a plus is never read back as a space")
    }

    func testTextSendsTheETagAndReportsA304AsNotModified() async throws {
        respond("", status: 304) { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "If-None-Match"), "\"v1\"")
        }
        let result = try await client.fetchEpisodeText(episode: "ep_1", focus: .none, etag: "\"v1\"")
        XCTAssertTrue(result.notModified)
        XCTAssertNil(result.value)
    }

    func testProvenanceAndCitationsHitTheirRoutes() async throws {
        respond(#"{"entityId": "alpha-project"}"#, etag: "\"p1\"") { request in
            XCTAssertEqual(request.url?.path, "/entities/alpha-project/provenance")
        }
        let provenance = try await client.fetchEntityProvenance(entityId: "alpha-project", etag: nil)
        XCTAssertEqual(provenance.value?.entityId, "alpha-project")
        XCTAssertEqual(provenance.etag, "\"p1\"")

        respond(#"{"episode": "ep_1", "citations": []}"#) { request in
            XCTAssertEqual(request.url?.path, "/episodes/ep_1/citations")
        }
        let citations = try await client.fetchEpisodeCitations(episode: "ep_1", etag: nil)
        XCTAssertEqual(citations.value?.episode, "ep_1")
    }

    func testA404IsAnHTTPErrorTheCacheCanNameAsGone() async {
        respond(#"{"detail": "No stored document"}"#, status: 404) { _ in }
        do {
            _ = try await client.fetchEpisodeText(episode: "ep_gone", focus: .none, etag: nil)
            XCTFail("a 404 must surface")
        } catch APIError.httpError(let code, _) {
            XCTAssertEqual(code, 404)
        } catch {
            XCTFail("unexpected \(error)")
        }
    }
}
