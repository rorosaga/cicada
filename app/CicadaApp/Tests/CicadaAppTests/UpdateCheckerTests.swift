import XCTest
@testable import CicadaApp

/// G182 phase 5 — the check: the newest release's `latest.json`, a strict version comparison, and a refusal when the
/// release needs a newer macOS. The fetch is injected; no request leaves the test.
final class UpdateCheckerTests: XCTestCase {
    static let repo = "owner-example/cicada"
    static let manifestURL = URL(string: "https://github.com/owner-example/cicada/releases/download/v0.3.1/latest.json")!
    static let sonoma = OperatingSystemVersion(majorVersion: 14, minorVersion: 6, patchVersion: 0)

    /// Records every request and answers from a table keyed by URL.
    final class FakeServer: @unchecked Sendable {
        var routes: [URL: (Int, Data)] = [:]
        var requests: [URLRequest] = []
        let lock = NSLock()

        var fetch: UpdateChecker.Fetch {
            { [self] request in
                lock.lock()
                requests.append(request)
                let route = routes[request.url!]
                lock.unlock()
                guard let (status, body) = route else { throw URLError(.cannotFindHost) }
                return (body, HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
            }
        }
    }

    static func release(assets: [(String, String)]) -> Data {
        let list = assets.map { #"{"name":"\#($0.0)","browser_download_url":"\#($0.1)","size":10}"# }
        return Data(#"{"tag_name":"v0.3.1","assets":[\#(list.joined(separator: ","))]}"#.utf8)
    }

    static func manifest(version: String = "0.3.1", minimum: String? = "14.0",
                         url: String = "https://github.com/owner-example/cicada/releases/download/v0.3.1/Cicada-0.3.1.zip") -> Data {
        let min = minimum.map { #","minimum_macos":"\#($0)""# } ?? ""
        return Data(#"{"version":"\#(version)","build":1540,"url":"\#(url)","size":10,"sha256":"aa","signature":"bb"\#(min)}"#.utf8)
    }

    private func server(release: Data? = nil, manifest: Data = manifest()) -> FakeServer {
        let s = FakeServer()
        s.routes[UpdateChecker.releasesURL(repo: Self.repo)!] = (200, release ?? Self.release(assets: [
            ("Cicada-0.3.1.zip", "https://github.com/owner-example/cicada/releases/download/v0.3.1/Cicada-0.3.1.zip"),
            ("latest.json", Self.manifestURL.absoluteString),
            ("Cicada-0.3.1.zip.sig", "https://github.com/owner-example/cicada/releases/download/v0.3.1/Cicada-0.3.1.zip.sig"),
        ]))
        s.routes[Self.manifestURL] = (200, manifest)
        return s
    }

    private func checker(_ s: FakeServer, current: String? = "0.3.0", os: OperatingSystemVersion = sonoma,
                         repo: String? = repo) -> UpdateChecker {
        UpdateChecker(repo: repo, currentVersion: current, osVersion: os, fetch: s.fetch)
    }

    func testANewerVersionIsFoundThroughTheLatestJSONAsset() async throws {
        let s = server()
        let result = try await checker(s).check()
        guard case .available(let m) = result else { return XCTFail("\(result)") }
        XCTAssertEqual(m.version, "0.3.1")
        XCTAssertEqual(s.requests.map(\.url), [UpdateChecker.releasesURL(repo: Self.repo), Self.manifestURL])
        XCTAssertEqual(s.requests[0].url?.absoluteString, "https://api.github.com/repos/owner-example/cicada/releases/latest")
        XCTAssertEqual(s.requests[0].value(forHTTPHeaderField: "Accept"), "application/vnd.github+json")
        XCTAssertEqual(s.requests[0].value(forHTTPHeaderField: "User-Agent"), "Cicada/0.3.0")
        XCTAssertEqual(s.requests[1].value(forHTTPHeaderField: "User-Agent"), "Cicada/0.3.0")
        XCTAssertFalse(s.requests[0].httpShouldHandleCookies)
    }

    func testTheSameOrAnOlderVersionIsUpToDate() async throws {
        let same = try await checker(server(), current: "0.3.1").check()
        XCTAssertEqual(same, .upToDate)
        let newer = try await checker(server(), current: "0.4.0").check()
        XCTAssertEqual(newer, .upToDate, "a build ahead of the release never 'updates' backwards")
        let numeric = try await checker(server(manifest: Self.manifest(version: "0.10.0")), current: "0.9.0").check()
        guard case .available = numeric else { return XCTFail("0.10.0 is newer than 0.9.0") }
    }

    func testAReleaseThatNeedsANewerMacOSIsRefused() async throws {
        let result = try await checker(server(manifest: Self.manifest(minimum: "15.0"))).check()
        guard case .needsNewerMacOS(let m, let minimum) = result else { return XCTFail("\(result)") }
        XCTAssertEqual(m.version, "0.3.1")
        XCTAssertEqual(minimum, "15.0")
        let fine = try await checker(server(manifest: Self.manifest(minimum: "14.6"))).check()
        guard case .available = fine else { return XCTFail("14.6 runs on 14.6") }
        let none = try await checker(server(manifest: Self.manifest(minimum: nil))).check()
        guard case .available = none else { return XCTFail("no minimum means any") }
    }

    /// The zip must be one of the same release's assets: a manifest naming any other https address is refused
    /// before a byte is downloaded.
    func testAManifestPointingOutsideItsReleaseIsRefused() async {
        await assertFailure(checker(server(manifest: Self.manifest(url: "https://elsewhere.example/Cicada-0.3.1.zip"))),
                            .foreignURL)
        await assertFailure(checker(server(manifest: Self.manifest(
            url: "https://github.com/owner-example/cicada/releases/download/v0.3.0/Cicada-0.3.0.zip"))), .foreignURL)
        XCTAssertFalse(UpdateChecker.Failure.foreignURL.message.lowercased().contains("github"))
    }

    func testAReleaseWithoutLatestJSONSaysSo() async {
        let s = server(release: Self.release(assets: [("Cicada-0.3.1.zip", "https://example.com/z.zip")]))
        await assertFailure(checker(s), .noManifestAsset)
    }

    func testFailuresAreTyped() async {
        // No release published yet.
        let none = server()
        none.routes[UpdateChecker.releasesURL(repo: Self.repo)!] = (404, Data())
        await assertFailure(checker(none), .noRelease)
        // Rate-limited or broken.
        let limited = server()
        limited.routes[UpdateChecker.releasesURL(repo: Self.repo)!] = (403, Data())
        await assertFailure(checker(limited), .http(403))
        // A manifest that doesn't decode, or carries a version that isn't X.Y.Z.
        await assertFailure(checker(server(manifest: Data("{}".utf8))), .badManifest)
        await assertFailure(checker(server(manifest: Self.manifest(version: "0.4.0-beta"))), .badManifest)
        // A zip address that isn't https.
        await assertFailure(checker(server(manifest: Self.manifest(url: "http://example.com/C.zip"))), .insecureURL)
        // A manifest asset that isn't https.
        let plain = server(release: Self.release(assets: [("latest.json", "http://example.com/latest.json")]))
        await assertFailure(checker(plain), .insecureURL)
        // No repo, a repo that can't be pasted into a path, or an app that doesn't know its version.
        await assertFailure(checker(server(), repo: nil), .noRepo)
        await assertFailure(checker(server(), repo: "owner/../../etc"), .noRepo)
        await assertFailure(checker(server(), repo: "owner/repo/extra"), .noRepo)
        await assertFailure(checker(server(), current: nil), .badVersion)
        // Transport errors in words.
        let offline = FakeServer()
        await assertFailure(UpdateChecker(repo: Self.repo, currentVersion: "0.3.0", osVersion: Self.sonoma,
                                          fetch: { _ in throw URLError(.notConnectedToInternet) }), .offline)
        await assertFailure(checker(offline), .unreachable)
    }

    func testEveryFailureIsAPlainPhraseWithoutAProviderName() {
        let all: [UpdateChecker.Failure] = [.noRepo, .noRelease, .http(500), .noManifestAsset, .badManifest, .badVersion,
                                            .insecureURL, .foreignURL, .offline, .unreachable]
        for f in all {
            XCTAssertFalse(f.message.isEmpty)
            XCTAssertFalse(f.message.hasSuffix("."))
            XCTAssertFalse(f.message.lowercased().contains("github"), "provider-neutral: \(f.message)")
        }
    }

    private func assertFailure(_ checker: UpdateChecker, _ expected: UpdateChecker.Failure,
                               file: StaticString = #filePath, line: UInt = #line) async {
        do {
            let result = try await checker.check()
            XCTFail("expected \(expected), got \(result)", file: file, line: line)
        } catch {
            XCTAssertEqual(error as? UpdateChecker.Failure, expected, file: file, line: line)
        }
    }
}
