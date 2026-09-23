import XCTest

/// G137 R-M7 / plan R-M24 — the Info.plist `bundle.sh` writes promised macOS
/// 13 while `Package.swift` builds for 14, so the `#available` floor the glass
/// and symbol-effect gates assume was not the floor the app advertised. Held
/// equal here so the two cannot drift again.
final class PlatformFloorTests: XCTestCase {
    private var packageRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp
    }

    private func firstCapture(_ pattern: String, in text: String) throws -> String? {
        let regex = try NSRegularExpression(pattern: pattern)
        let ns = text as NSString
        guard let m = regex.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)) else { return nil }
        return ns.substring(with: m.range(at: 1))
    }

    func testTheInfoPlistPromisesTheFloorThePackageBuildsFor() throws {
        let package = try String(contentsOf: packageRoot.appendingPathComponent("Package.swift"), encoding: .utf8)
        let bundle = try String(contentsOf: packageRoot.appendingPathComponent("bundle.sh"), encoding: .utf8)
        let major = try XCTUnwrap(try firstCapture(#"\.macOS\(\.v(\d+)\)"#, in: package))
        let plist = try XCTUnwrap(try firstCapture(#"<key>LSMinimumSystemVersion</key><string>([0-9.]+)</string>"#, in: bundle))
        XCTAssertEqual(plist, "\(major).0")
    }
}
