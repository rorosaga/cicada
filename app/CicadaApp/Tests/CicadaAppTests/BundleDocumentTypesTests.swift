import XCTest
@testable import CicadaApp

/// R-IA25 — Cicada is offered in Open With, never made the default opener.
final class BundleDocumentTypesTests: XCTestCase {
    func testTheBundleDeclaresAnAlternateViewerForExports() throws {
        let script = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: script, encoding: .utf8)
        XCTAssertTrue(text.contains("<key>CFBundleDocumentTypes</key>"))
        XCTAssertTrue(text.contains("<key>LSHandlerRank</key><string>Alternate</string>"))
        XCTAssertTrue(text.contains("<key>CFBundleTypeRole</key><string>Viewer</string>"))
        for uti in ["public.zip-archive", "public.json", "public.html", "public.folder"] {
            XCTAssertTrue(text.contains("<string>\(uti)</string>"), uti)
        }
        XCTAssertFalse(text.contains("<string>Owner</string>") || text.contains("<string>Default</string>"))
    }
}
