import XCTest
@testable import CicadaApp

/// G67 §2.3 — the Contributors drill-down's wire types and fetch.
final class ContributorCommitTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Decoding

    func testContributorCommitDecodesTheCamelCaseWirePayload() throws {
        let json = """
        {
            "commitHash": "abc1234def",
            "date": "2026-08-31",
            "subject": "Sleep cycle 2026-08-31",
            "entities": ["mongodb", "cicada"],
            "filesChanged": 4
        }
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)

        XCTAssertEqual(commit.commitHash, "abc1234def")
        XCTAssertEqual(commit.id, "abc1234def")
        XCTAssertEqual(commit.date, "2026-08-31")
        XCTAssertEqual(commit.subject, "Sleep cycle 2026-08-31")
        XCTAssertEqual(commit.entities, ["mongodb", "cicada"])
        XCTAssertEqual(commit.filesChanged, 4)
    }

    func testContributorCommitToleratesAnOlderBackendMissingTheOptionalFields() throws {
        let json = """
        {"commitHash": "abc1234", "date": "2026-08-31", "subject": "Sleep cycle"}
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)

        XCTAssertEqual(commit.entities, [])
        XCTAssertEqual(commit.filesChanged, 0)
    }

    func testContributorCommitsResponseDecodesTheEnvelope() throws {
        let json = """
        {"author": "gpt-5.4-mini", "commits": [
            {"commitHash": "a1b2c3d", "date": "2026-08-31", "subject": "Sleep cycle",
             "entities": ["mongodb"], "filesChanged": 1}
        ]}
        """.data(using: .utf8)!

        let payload = try JSONDecoder().decode(ContributorCommitsResponse.self, from: json)

        XCTAssertEqual(payload.author, "gpt-5.4-mini")
        XCTAssertEqual(payload.commits.count, 1)
        XCTAssertEqual(payload.commits[0].entities, ["mongodb"])
    }

    // MARK: - APIClient.fetchContributorCommits

    func testFetchContributorCommitsSendsTheAuthorAsAQueryParam() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/contributors/commits")
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("author=gpt-5.4-mini"), query)
            XCTAssertTrue(query.contains("limit=50"), query)

            let body = """
            {"author": "gpt-5.4-mini", "commits": [
                {"commitHash": "a1b2c3d", "date": "2026-08-31", "subject": "Sleep cycle",
                 "entities": ["mongodb"], "filesChanged": 1}
            ]}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let commits = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchContributorCommits(author: "gpt-5.4-mini")

        XCTAssertEqual(commits.map(\.commitHash), ["a1b2c3d"])
    }

    func testFetchContributorCommitsPercentEncodesASlashedModelId() async throws {
        MockURLProtocol.handler = { request in
            // The slash must survive as an ENCODED query value, never split the path.
            XCTAssertEqual(request.url?.path, "/contributors/commits")
            XCTAssertTrue(
                (request.url?.query ?? "").contains("author=anthropic%2Fclaude-opus-4"),
                request.url?.query ?? ""
            )
            let body = #"{"author": "anthropic/claude-opus-4", "commits": []}"#.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let commits = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchContributorCommits(author: "anthropic/claude-opus-4")

        XCTAssertTrue(commits.isEmpty)
    }

    func testFetchContributorCommitsReturnsEmptyAgainstABackendWithoutTheEndpoint() async throws {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 404,
                                            httpVersion: nil, headerFields: nil)!
            return (response, Data("Not Found".utf8))
        }

        let commits = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchContributorCommits(author: "user")

        XCTAssertTrue(commits.isEmpty, "a 404 means 'no drill-down yet', not an error")
    }
}
