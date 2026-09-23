import AppKit
import WebKit
import XCTest
@testable import CicadaApp

/// D10 / R-IA24 — the graph canvas must not swallow a file drop meant for the router.
@MainActor
final class GraphDropTests: XCTestCase {
    func testTheGraphWebViewRegistersNoDragTypes() {
        let view = ClickableWebView(frame: NSRect(x: 0, y: 0, width: 100, height: 100),
                                    configuration: WKWebViewConfiguration())
        // In a window, so a registration WebKit defers to `viewDidMoveToWindow`
        // has happened too — without that the assertion could pass vacuously.
        let window = NSWindow(contentRect: view.frame, styleMask: [.titled], backing: .buffered, defer: true)
        window.contentView = view
        XCTAssertTrue(view.registeredDraggedTypes.isEmpty)
        window.contentView = nil
    }
}
