import XCTest
@testable import CicadaApp

/// G182 — Settings → General's Version row: the Info.plist pair `bundle.sh` writes, and the backend's version only
/// when the two differ.
final class AppVersionTests: XCTestCase {
    func testReadsTheBundlePair() {
        let v = AppVersion.current(info: ["CFBundleShortVersionString": "0.3.0", "CFBundleVersion": "412"])
        XCTAssertEqual(v, AppVersion(short: "0.3.0", build: "412"))
        XCTAssertEqual(Copy.versionLine(v), "Version 0.3.0 (412)")
    }

    func testABundlelessBinaryIsADevelopmentBuild() {
        let v = AppVersion.current(info: nil)
        XCTAssertNil(v.short)
        XCTAssertEqual(Copy.versionLine(v), "Development build")
        XCTAssertFalse(v.differs(fromBackend: "0.3.0"), "an unknown app version never warns")
    }

    func testOnlyAKnownDifferentBackendWarns() {
        let v = AppVersion(short: "0.3.0", build: "9")
        XCTAssertFalse(v.differs(fromBackend: nil), "a backend that hasn't answered is not a mismatch")
        XCTAssertFalse(v.differs(fromBackend: "0.3.0"))
        XCTAssertFalse(v.differs(fromBackend: " "))
        XCTAssertTrue(v.differs(fromBackend: "0.2.9"))
        XCTAssertTrue(Copy.versionMismatch(backend: "0.2.9").contains("0.2.9"))
    }

    func testTheRowIsIndexedOnGeneral() {
        XCTAssertTrue(SettingsIndex.staticIDs.contains(.appVersion))
        XCTAssertEqual(SettingsIndex.staticEntries.first { $0.id == .appVersion }?.section, .general)
    }

    func testBundleShReadsTheOneVersionFile() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
        let script = try String(contentsOf: root.appendingPathComponent("bundle.sh"), encoding: .utf8)
        XCTAssertTrue(script.contains("plutil -replace CFBundleShortVersionString -string \"$APP_VERSION\""))
        XCTAssertFalse(script.contains("<string>0.2</string>"))
    }
}
