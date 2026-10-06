import XCTest
@testable import CicadaApp

/// G182 phase 5 — `latest.json` and the version rules the updater compares with. Pure.
final class UpdateManifestTests: XCTestCase {
    static let sample = """
    {"version":"0.3.1","build":1540,"url":"https://github.com/owner-example/cicada/releases/download/v0.3.1/Cicada-0.3.1.zip",
     "size":144000000,"sha256":"abc123","signature":"c2ln","notes_url":"https://github.com/owner-example/cicada/releases/tag/v0.3.1",
     "minimum_macos":"14.0","published_at":"2026-10-06T10:00:00Z"}
    """

    func testSemVerParsesXYZAndIgnoresALeadingV() {
        XCTAssertEqual(SemVer("0.3.1"), SemVer(major: 0, minor: 3, patch: 1))
        XCTAssertEqual(SemVer("v1.2.3"), SemVer(major: 1, minor: 2, patch: 3))
        XCTAssertEqual(SemVer(" 10.0.12 "), SemVer(major: 10, minor: 0, patch: 12))
        XCTAssertEqual(SemVer("v1.2.3")?.description, "1.2.3")
    }

    func testSemVerRefusesAnythingElse() {
        for bad in ["", "1.2", "1.2.3.4", "1.2.x", "1..3", "1.2.3-beta", "v", "vv1.2.3", "-1.2.3", "1.2.3\n4",
                    "１.2.3", "1.2.+3", "1.2.3; rm -rf /"] {
            XCTAssertNil(SemVer(bad), bad)
        }
    }

    func testSemVerOrdersNumericallyNotAsText() {
        XCTAssertLessThan(SemVer("0.3.0")!, SemVer("0.3.1")!)
        XCTAssertLessThan(SemVer("0.9.9")!, SemVer("0.10.0")!)
        XCTAssertLessThan(SemVer("1.9.0")!, SemVer("2.0.0")!)
        XCTAssertLessThan(SemVer("0.3.9")!, SemVer("0.3.10")!)
        XCTAssertFalse(SemVer("1.0.0")! < SemVer("v1.0.0")!)
        XCTAssertEqual(SemVer("1.0.0"), SemVer("v1.0.0"))
    }

    func testTheManifestDecodesEveryField() throws {
        let m = try UpdateManifest.decode(Data(Self.sample.utf8))
        XCTAssertEqual(m.version, "0.3.1")
        XCTAssertEqual(m.build, 1540)
        XCTAssertEqual(m.url.lastPathComponent, "Cicada-0.3.1.zip")
        XCTAssertEqual(m.size, 144_000_000)
        XCTAssertEqual(m.sha256, "abc123")
        XCTAssertEqual(m.signature, "c2ln")
        XCTAssertEqual(m.notesURL?.absoluteString, "https://github.com/owner-example/cicada/releases/tag/v0.3.1")
        XCTAssertEqual(m.minimumMacOS, "14.0")
        XCTAssertEqual(m.publishedAt, "2026-10-06T10:00:00Z")
    }

    func testTheOptionalFieldsMayBeAbsentButTheVerifiedOnesMayNot() throws {
        let minimal = #"{"version":"0.3.1","url":"https://example.com/C.zip","size":1,"sha256":"a","signature":"b"}"#
        let m = try UpdateManifest.decode(Data(minimal.utf8))
        XCTAssertNil(m.build)
        XCTAssertNil(m.minimumMacOS)
        XCTAssertNil(m.notesURL)
        let noSignature = #"{"version":"0.3.1","url":"https://example.com/C.zip","size":1,"sha256":"a"}"#
        XCTAssertThrowsError(try UpdateManifest.decode(Data(noSignature.utf8)))
    }

    func testMacOSVersionsParseAndCompare() {
        let v14 = MacOSVersion.parse("14.0")!
        XCTAssertEqual(v14.majorVersion, 14)
        XCTAssertEqual(MacOSVersion.parse("15")?.majorVersion, 15)
        XCTAssertEqual(MacOSVersion.parse("14.2.1")?.patchVersion, 1)
        XCTAssertNil(MacOSVersion.parse("fourteen"))
        XCTAssertNil(MacOSVersion.parse("14.0.0.1"))
        let running = OperatingSystemVersion(majorVersion: 14, minorVersion: 5, patchVersion: 0)
        XCTAssertTrue(MacOSVersion.satisfies(running, minimum: v14))
        XCTAssertFalse(MacOSVersion.satisfies(running, minimum: MacOSVersion.parse("15.0")!))
        XCTAssertFalse(MacOSVersion.satisfies(running, minimum: MacOSVersion.parse("14.5.1")!))
        XCTAssertEqual(MacOSVersion.display(MacOSVersion.parse("15")!), "15.0")
    }
}
