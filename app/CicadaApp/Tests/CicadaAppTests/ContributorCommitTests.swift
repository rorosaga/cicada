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

    // H1 — the backend caps `entities`; the row must say "+N more", not lie.
    func testContributorCommitReportsTheEntitiesTheBackendWithheld() throws {
        let json = """
        {
            "commitHash": "abc1234",
            "date": "2026-08-31",
            "subject": "Sleep cycle 2026-08-31",
            "entities": ["alpha", "beta"],
            "entitiesTotal": 895,
            "filesChanged": 901
        }
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)

        XCTAssertEqual(commit.entities.count, 2)
        XCTAssertEqual(commit.entitiesTotal, 895)
        XCTAssertEqual(commit.hiddenEntityCount, 893)
    }

    func testAnUncappedCommitHidesNothing() throws {
        let json = """
        {"commitHash": "abc1234", "date": "2026-08-31", "subject": "Sleep cycle",
         "entities": ["alpha", "beta"], "entitiesTotal": 2, "filesChanged": 2}
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)

        XCTAssertEqual(commit.hiddenEntityCount, 0, "no '+N more' capsule")
    }

    func testAnOlderBackendWithoutEntitiesTotalNeverShowsAPhantomMore() throws {
        let json = """
        {"commitHash": "abc1234", "date": "2026-08-31", "subject": "Sleep cycle",
         "entities": ["alpha", "beta"]}
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)

        XCTAssertEqual(commit.entitiesTotal, 2, "falls back to the ids we were sent")
        XCTAssertEqual(commit.hiddenEntityCount, 0)
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

    // H3 — a failed fetch must NOT come back as "this author wrote nothing".
    func testFetchContributorCommitsThrowsOnAServerError() async {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 500,
                                            httpVersion: nil, headerFields: nil)!
            return (response, Data("boom".utf8))
        }

        do {
            _ = try await APIClient(session: MockURLProtocol.makeSession())
                .fetchContributorCommits(author: "gpt-5.4-mini")
            XCTFail("a 500 must throw, never decode to an empty commit list")
        } catch APIError.httpError(let code, _) {
            XCTAssertEqual(code, 500)
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testFetchContributorCommitsThrowsWhenTheBackendIsUnreachable() async {
        MockURLProtocol.handler = { _ in throw URLError(.cannotConnectToHost) }

        do {
            _ = try await APIClient(session: MockURLProtocol.makeSession())
                .fetchContributorCommits(author: "gpt-5.4-mini")
            XCTFail("an offline backend must throw, not read as 'no commits'")
        } catch {
            // Any thrown error is the contract; the view turns it into a retry.
        }
    }

    func testFetchContributorCommitsSurfacesACancellationAsAThrow() async {
        // The row collapsing mid-flight cancels the task; URLSession reports
        // that as URLError.cancelled. It must reach the caller so the view can
        // tell "cancelled" apart from "failed" and from "genuinely empty".
        MockURLProtocol.handler = { _ in throw URLError(.cancelled) }

        do {
            _ = try await APIClient(session: MockURLProtocol.makeSession())
                .fetchContributorCommits(author: "gpt-5.4-mini")
            XCTFail("a cancelled fetch must not decode to an empty commit list")
        } catch let error as URLError {
            XCTAssertEqual(error.code, .cancelled)
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }
}
