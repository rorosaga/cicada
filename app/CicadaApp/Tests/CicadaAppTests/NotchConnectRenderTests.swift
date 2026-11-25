import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G245 (plan section 7) — the notch's connect panel in each state it says something, rendered offscreen (an
/// `NSHostingView` in a never-shown window, never the running app): the offer, "Turning on…", "Turned on" with and
/// without the promise of a question, the Accessibility line with its one button, a refusal, and a Mac app's offer.
///
/// Skipped unless `NOTCH_RENDER_DIR` names a folder; the PNGs land there as `notch-*.png`. Run:
///
///     NOTCH_RENDER_DIR=<folder> swift test --filter NotchConnectRenderTests
@MainActor
final class NotchConnectRenderTests: XCTestCase {
    private final class Presenter: ConnectSuggestPresenting {
        func show(_ center: ConnectSuggestCenter) {}
        func hide() {}
    }

    private func center(offering site: String, result: ConnectSuggestResult?) async throws -> ConnectSuggestCenter {
        var now = Date(timeIntervalSince1970: 1_800_000_000)
        let center = ConnectSuggestCenter(store: ConnectSuggestStore(defaults: TestDefaults.suite("NotchRender.\(UUID())")!),
                                          now: { now }, uptime: { now.timeIntervalSince1970 }, wait: { _ in },
                                          ticks: false)
        now = now.addingTimeInterval(3600)
        center.attach(presenter: Presenter())
        center.memoryKnown = { true }
        center.setUp = { true }
        center.isDemo = { false }
        center.status = { _ in .off }
        center.iconFor = { _ in nil }
        let target = try XCTUnwrap(SiteSaveSite.offered(site))
        center.offer(site: target, connected: false, pid: 7, bundleId: "com.google.Chrome")
        if let result {
            now = now.addingTimeInterval(1)
            center.connect = { _ in result }
            center.input(.yes)
            await center.settle()
        }
        return center
    }

    private func write(_ center: ConnectSuggestCenter, to url: URL, connecting: Bool = false) throws {
        let notch = SaveWhyNotchModel()
        notch.grown = true
        notch.band = 8
        let view = ConnectSuggestPanelView(center: center, notch: notch)
            .frame(width: ConnectSuggestPanelView.width + 2 * SaveWhyNotch.ear, height: 150, alignment: .top)
            .background(Color(white: 0.55))
            .environment(\.colorScheme, .dark)
        let host = NSHostingView(rootView: view)
        host.frame = CGRect(x: 0, y: 0, width: ConnectSuggestPanelView.width + 2 * SaveWhyNotch.ear, height: 150)
        host.appearance = NSAppearance(named: .darkAqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        // `NOTCH_RENDER_WAIT` (seconds) lets the offer's bar fill before the picture is taken, to look at it part-way.
        let wait = ProcessInfo.processInfo.environment["NOTCH_RENDER_WAIT"].flatMap(Double.init) ?? 0.4
        RunLoop.main.run(until: Date().addingTimeInterval(wait))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        try XCTUnwrap(rep.representation(using: .png, properties: [:])).write(to: url)
    }

    func testRenderEachWordTheNotchSays() async throws {
        guard let dir = ProcessInfo.processInfo.environment["NOTCH_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set NOTCH_RENDER_DIR to render the notch's screenshots")
        }
        let base = URL(fileURLWithPath: dir, isDirectory: true)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        try write(try await center(offering: "x", result: nil), to: base.appendingPathComponent("notch-offer-x.png"))
        try write(try await center(offering: "x", result: .turnedOn(asksWhy: true, needsAccessibility: false)),
                  to: base.appendingPathComponent("notch-turned-on-x.png"))
        try write(try await center(offering: "instagram", result: .turnedOn(asksWhy: false, needsAccessibility: true)),
                  to: base.appendingPathComponent("notch-needs-accessibility.png"))
        try write(try await center(offering: "linkedin", result: nil), to: base.appendingPathComponent("notch-offer-linkedin.png"))
        try write(try await center(offering: "linkedin", result: .turnedOn(asksWhy: false, needsAccessibility: false)),
                  to: base.appendingPathComponent("notch-turned-on-linkedin.png"))
        try write(try await center(offering: "reddit", result: .failed("Agent reading is not on.")),
                  to: base.appendingPathComponent("notch-refused.png"))
    }
}
