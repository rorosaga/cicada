import XCTest
@testable import CicadaApp

/// The resource bundle must resolve without ever probing the build directory
/// under ~/Documents (which triggers a TCC prompt that blocks the main thread
/// on a LaunchServices launch — see `Bundle.cicadaResources`).
final class ResourceBundleTests: XCTestCase {
    func testResourceBundleServesTheGraphPage() {
        let url = Bundle.cicadaResources.url(forResource: "graph/index", withExtension: "html")
        XCTAssertNotNil(url, "graph/index.html must be reachable through Bundle.cicadaResources")
    }

    func testNoCallSiteUsesBundleModuleDirectly() throws {
        // Source-level guard: only ResourceBundle.swift may name Bundle.module.
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp")
        let files = try FileManager.default.subpathsOfDirectory(atPath: root.path)
            .filter { $0.hasSuffix(".swift") && !$0.hasSuffix("ResourceBundle.swift") }
        let offenders = files.filter { path in
            (try? String(contentsOf: root.appendingPathComponent(path), encoding: .utf8))?.contains("Bundle.module") == true
        }
        XCTAssertEqual(offenders, [], "use Bundle.cicadaResources, not Bundle.module")
    }
}
