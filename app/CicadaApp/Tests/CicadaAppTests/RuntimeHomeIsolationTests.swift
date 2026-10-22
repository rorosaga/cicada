import XCTest
@testable import CicadaApp

/// No unit test reads or writes the person's real home through `CicadaRuntime.current` (the #348 follow-up,
/// 2026-10-19). `APIClientIsolationTests` holds `APIClient.shared`; this holds every other default that reads the
/// runtime — the updater's sleep probe, its token file and Trash, `ServerConnection`'s files. Fails if a guard goes away.
final class RuntimeHomeIsolationTests: XCTestCase {
    private var realHomes: [String] {
        var homes = [FileManager.default.homeDirectoryForCurrentUser.standardizedFileURL.path]
        if let own = NSHomeDirectoryForUser(NSUserName()) { homes.append(URL(fileURLWithPath: own).standardizedFileURL.path) }
        return homes
    }

    private func assertTemporary(_ url: URL, _ what: String, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(APIClient.testMayReadToken(at: url), "\(what) is outside the temporary directory: \(url.path)",
                      file: file, line: line)
        for home in realHomes where !APIClient.testMayReadToken(at: URL(fileURLWithPath: home)) {
            XCTAssertFalse(url.standardizedFileURL.path.hasPrefix(home + "/.cicada"), "\(what) is the real ~/.cicada",
                           file: file, line: line)
        }
    }

    func testTheRuntimeHomeIsATemporaryFolderUnderTests() {
        XCTAssertTrue(AppPasteboard.isRunningTests)
        assertTemporary(CicadaRuntime.current.cicadaHome, "CicadaRuntime.current.cicadaHome")
        assertTemporary(CicadaRuntime.current.binDir, "the launcher folder")
        assertTemporary(CicadaRuntime.current.logDir, "the log folder")
        assertTemporary(UpdateInstaller.defaultTrashDir, "the updater's Trash")
    }

    func testAShellsCicadaHomeIsIgnoredUnderTests() {
        let runtime = CicadaRuntime.underTests(environment: ["CICADA_HOME": "/Users/someone/.cicada"])
        XCTAssertEqual(runtime.cicadaHome.standardizedFileURL.path,
                       CicadaRuntime.testHome.appendingPathComponent(".cicada").standardizedFileURL.path)
        XCTAssertEqual(runtime.distribution, .developer, "an XCTest bundle is never a release")
    }

    func testTheUpdatersFilesLiveInTheTestHome() {
        let installer = UpdateInstaller(installedApp: URL(fileURLWithPath: "/nonexistent/Cicada.app"),
                                        bundleIdentifier: nil, publicKeyBase64: nil,
                                        cicadaHome: CicadaRuntime.current.cicadaHome)
        assertTemporary(installer.tokenFile, "the probe's token file")
        assertTemporary(installer.logFile, "the update log")
        assertTemporary(installer.trashDir, "the installer's Trash")
    }

    /// The probe `UpdateService.live` wires answers "nothing listening" at once, whatever runs on this Mac's port,
    /// and never reads a token outside a test's own folder.
    func testTheLiveSleepProbeReachesNothing() async {
        let started = Date()
        for home in realHomes {
            let probe = SleepProbe.live(port: CicadaRuntime.defaultPort,
                                        tokenFile: URL(fileURLWithPath: home).appendingPathComponent(".cicada/api_token"))
            let answer = await probe(.seconds(1))
            XCTAssertEqual(answer, .noAnswer)
        }
        XCTAssertLessThan(Date().timeIntervalSince(started), 2)
    }

    func testServerConnectionReadsTheTestHome() {
        var read: [URL] = []
        _ = ServerConnection.resolve(environment: [:], includingPending: true, readFile: { read.append($0); return nil })
        _ = ServerConnection.deviceToken(environment: [:], readFile: { read.append($0); return nil })
        XCTAssertEqual(read.count, 3)
        for url in read { assertTemporary(url, "ServerConnection's default file") }
    }
}
