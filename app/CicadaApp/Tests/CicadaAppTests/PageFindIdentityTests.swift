import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// ⌘K on the Graph used to land nowhere: `publishesPageFind` put the page in an `if`/`else`, so every flip of `enabled`
/// (the palette opening or closing, find, the Settings panel, a tab change) gave the page a new identity and SwiftUI
/// built it again. On the Graph that is a new web view: a cold layout, the zoom lost, and the palette's reveal sent to a
/// page that had not loaded yet. Hosted offscreen (an `NSHostingView` in a never-shown window, never the running app).
@MainActor
final class PageFindIdentityTests: XCTestCase {
    @Observable final class Switch { var enabled = true }

    /// Counts how many times SwiftUI makes the view it stands for.
    final class Made { var count = 0 }

    struct Probe: NSViewRepresentable {
        let made: Made
        func makeNSView(context: Context) -> NSView { made.count += 1; return NSView() }
        func updateNSView(_ nsView: NSView, context: Context) {}
    }

    struct Page: View {
        let made: Made
        @Bindable var toggle: Switch
        var body: some View {
            Probe(made: made).publishesPageFind(enabled: toggle.enabled) {}
        }
    }

    func testFlippingThePageFindSwitchNeverRebuildsThePage() {
        let made = Made()
        let toggle = Switch()
        let view = NSHostingView(rootView: Page(made: made, toggle: toggle))
        view.frame = CGRect(x: 0, y: 0, width: 200, height: 200)
        let window = NSWindow(contentRect: view.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = view
        settle(view)
        XCTAssertEqual(made.count, 1)
        for _ in 0..<4 {
            toggle.enabled.toggle()
            settle(view)
        }
        XCTAssertEqual(made.count, 1, "the page under publishesPageFind was built again when its switch flipped")
        window.contentView = nil
    }

    private func settle(_ view: NSView) {
        view.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        view.layoutSubtreeIfNeeded()
    }
}
