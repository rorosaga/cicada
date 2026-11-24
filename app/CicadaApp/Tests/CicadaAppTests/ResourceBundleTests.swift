import XCTest
@testable import CicadaApp

/// The resource bundle must resolve without ever probing the build directory
/// under ~/Documents (which triggers a TCC prompt that blocks the main thread
/// on a LaunchServices launch — see `Bundle.cicadaResources`).
final class ResourceBundleTests: XCTestCase {
    func testResourceBundleServesTheGraphPage() {
        // Through the both-layouts finder the app itself loads the page by (`GraphView`): a path-style name
        // ("graph/index") matches nothing in the layout the Swift Build engine makes (`cicadaResource`'s third layout).
        let url = Bundle.cicadaResources.cicadaResource("index", ext: "html", in: "graph")
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
