import XCTest
import SwiftUI
import MapKit
@testable import CicadaApp

/// A location page's map sat inside the scrolling card and took every scroll-wheel event over it: the panel scrolled
/// only on the sliver below the map. Driven through AppKit offscreen (never the app): a real scroll-wheel event goes to
/// the view under the pointer, as the window would send it, and the card must scroll.
final class LocationMapScrollTests: XCTestCase {
    @MainActor
    private func scrolledOffset(overMap: Bool) throws -> CGFloat {
        let card = ScrollView {
            VStack(spacing: 0) {
                LocationMap(name: "Example Park", coordinate: CLLocationCoordinate2D(latitude: 48.85, longitude: 2.35))
                Color.gray.frame(height: 2_000)
            }
        }
        let host = NSHostingView(rootView: card.frame(width: 400, height: 500))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 500), styleMask: [.borderless],
                              backing: .buffered, defer: false)
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        let scroll = try XCTUnwrap(Self.find(NSScrollView.self, in: host), "the card is an NSScrollView")
        // The map is the top `HeroPreview.maxHeight` points of the card; the window's origin is bottom-left.
        let y = overMap ? 500 - HeroPreview.maxHeight / 2 : 500 - HeroPreview.maxHeight - 40
        let point = NSPoint(x: 200, y: y)
        let target = try XCTUnwrap(host.hitTest(point))
        let cg = try XCTUnwrap(CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: -120,
                                       wheel2: 0, wheel3: 0))
        cg.location = window.convertPoint(toScreen: point)
        let event = try XCTUnwrap(NSEvent(cgEvent: cg))
        target.scrollWheel(with: event)
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        return scroll.contentView.bounds.origin.y
    }

    private static func find<T: NSView>(_ type: T.Type, in view: NSView) -> T? {
        if let hit = view as? T { return hit }
        for sub in view.subviews { if let hit = find(type, in: sub) { return hit } }
        return nil
    }

    @MainActor
    func testTheCardScrollsWithThePointerOverTheMap() throws {
        XCTAssertGreaterThan(try scrolledOffset(overMap: false), 0, "control: below the map the card scrolls")
        XCTAssertGreaterThan(try scrolledOffset(overMap: true), 0, "over the map the card scrolls too")
    }
}
