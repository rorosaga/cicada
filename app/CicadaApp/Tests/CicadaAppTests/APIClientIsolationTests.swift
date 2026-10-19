import XCTest
@testable import CicadaApp

/// No unit test reaches a live backend or reads the person's token (#346 follow-up, 2026-10-19).
///
/// Every view model's defaults call `APIClient.shared`, so a test that forgot to inject one closure used to reach the
/// backend running on this Mac with the token from `~/.cicada`. Under XCTest `shared` now points at a name that never
/// resolves, and a token is read only from a test's own temporary folder. These fail if either guard goes away.
final class APIClientIsolationTests: XCTestCase {
    func testSharedClientPointsAtNothingUnderTests() {
        XCTAssertTrue(AppPasteboard.isRunningTests)
        XCTAssertEqual(APIClient.shared.baseURL, ServerConnection.unreachableBase)
        XCTAssertFalse(APIClient.shared.baseURL.contains("127.0.0.1"))
        XCTAssertFalse(APIClient.shared.connection.isServer, "This Mac's shape: nothing behaves as a server's client")
    }

    func testASharedRequestFailsWithoutLeavingTheProcess() async {
        let started = Date()
        do {
            _ = try await APIClient.shared.fetchSleepStatus()
            XCTFail("APIClient.shared answered under XCTest")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .cannotConnectToHost)
        }
        XCTAssertLessThan(Date().timeIntervalSince(started), 2)
    }

    func testNoTestReadsTheRealHomesToken() {
        var homes = [FileManager.default.homeDirectoryForCurrentUser]
        if let own = NSHomeDirectoryForUser(NSUserName()) { homes.append(URL(fileURLWithPath: own)) }
        for home in homes where !APIClient.testMayReadToken(at: home) {   // a scratch HOME under $TMPDIR is a test's own
            let cicada = home.appendingPathComponent(".cicada")
            XCTAssertFalse(APIClient.testMayReadToken(at: cicada.appendingPathComponent("api_token")))
            APIClient.invalidateToken()
            XCTAssertNil(APIClient.loadToken(connection: ServerConnection(mode: .thisMac, source: .none),
                                             cicadaHome: cicada))
            XCTAssertNil(APIClient.loadToken(connection: ServerConnection(mode: .invalid(reason: "x"), source: .none),
                                             cicadaHome: cicada))
        }
        // A client built with the default runtime reads the runtime's home: refused unless it is a test's own.
        if !APIClient.testMayReadToken(at: CicadaRuntime.current.cicadaHome.appendingPathComponent("api_token")) {
            APIClient.invalidateToken()
            XCTAssertNil(APIClient.loadToken(connection: ServerConnection(mode: .thisMac, source: .none),
                                             cicadaHome: CicadaRuntime.current.cicadaHome))
        }
    }

    func testATestsOwnTemporaryHomeStillServesItsToken() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("isolation-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: home); APIClient.invalidateToken() }
        try "test-token\n".write(to: home.appendingPathComponent("api_token"), atomically: true, encoding: .utf8)
        APIClient.invalidateToken()
        XCTAssertEqual(APIClient.loadToken(connection: ServerConnection(mode: .thisMac, source: .none), cicadaHome: home),
                       "test-token")
    }

    func testThePredicateResolvesSymlinkedTemporaryPaths() {
        let temp = URL(fileURLWithPath: "/private/var/folders/xy/T")
        XCTAssertTrue(APIClient.testMayReadToken(at: URL(fileURLWithPath: "/private/var/folders/xy/T/h/api_token"),
                                                 temporaryDirectory: temp))
        XCTAssertFalse(APIClient.testMayReadToken(at: URL(fileURLWithPath: "/private/var/folders/xy/Tother/api_token"),
                                                  temporaryDirectory: temp))
        XCTAssertFalse(APIClient.testMayReadToken(at: URL(fileURLWithPath: "/Users/someone/.cicada/api_token"),
                                                  temporaryDirectory: temp))
    }
}
