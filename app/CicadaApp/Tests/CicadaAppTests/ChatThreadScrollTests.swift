import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Owner 2026-11-25 — "when i opened the <a chat> chat from the messages in the sleep queue it was all the way scrolled
/// to the top and without the button at least that lets you go down". The column is hosted offscreen (an `NSHostingView`
/// in a never-shown window, never the running app) over synthetic sittings, and the scroll view's real position is read:
/// it opens at its newest message, and the jump back to it ends there.
@MainActor
final class ChatThreadScrollTests: XCTestCase {
    private typealias Line = ReaderChatTests.Line

    private func sitting(_ episode: String, day: Int, count: Int) -> EpisodeText {
        let lines = (0..<count).map { n in
            Line(marker: n % 2 == 0 ? "speaker:bob" : "user", text: "\(episode) line \(n) with a few words in it",
                 ts: String(format: "2026-11-%02dT10:%02d:00+00:00", day, n))
        }
        return ReaderChatTests.conversation(lines, episode: episode, title: "Messages with bob-example",
                                            timestamp: lines.first?.ts, origin: "imessage",
                                            conversationId: "imessage:0123456789abcdef:k1", correspondent: "bob-example")
    }

    private func host(thread: ReaderTarget.Thread, texts: [String: EpisodeText]) -> (NSHostingView<AnyView>, NSWindow) {
        let api = FakeProvenanceAPI()
        api.texts = texts
        let root = ChatThreadColumn(thread: thread, title: "bob-example")
            .environment(ProvenanceRouter())
            .environment(ProvenanceCache(api: api))
            .environment(\.colorScheme, .light)
        let view = NSHostingView(rootView: AnyView(root))
        view.frame = CGRect(x: 0, y: 0, width: 520, height: 520)
        view.appearance = NSAppearance(named: .aqua)
        let window = NSWindow(contentRect: view.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = view.appearance
        window.contentView = view
        return (view, window)
    }

    private func settle(_ view: NSView, _ seconds: TimeInterval = 1.2) {
        view.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(seconds))
        view.layoutSubtreeIfNeeded()
    }

    private func scrollView(in view: NSView) -> NSScrollView? {
        if let found = view as? NSScrollView { return found }
        for sub in view.subviews { if let found = scrollView(in: sub) { return found } }
        return nil
    }

    /// A picture of the column, written only when `CHAT_THREAD_RENDER_DIR` names a folder (the PR's evidence).
    private func snapshot(_ view: NSView, named name: String) {
        guard let dir = ProcessInfo.processInfo.environment["CHAT_THREAD_RENDER_DIR"], !dir.isEmpty,
              let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: rep)
        try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: dir).appendingPathComponent(name))
    }

    private func distanceFromEnd(_ scroll: NSScrollView) -> CGFloat {
        let clip = scroll.contentView
        let document = scroll.documentView!
        return (document.isFlipped ? max(0, document.frame.height - clip.bounds.height) : 0) - clip.bounds.origin.y
    }

    func testAWaitingChatFromTheQueueOpensAtItsNewestMessageAndTheJumpGoesBackToIt() throws {
        let ids = ["s1", "s2", "s3"]
        var texts: [String: EpisodeText] = [:]
        for (n, id) in ids.enumerated() { texts[id] = sitting(id, day: 20 + n, count: 14) }
        texts["s0"] = sitting("s0", day: 18, count: 6)
        let thread = ReaderTarget.Thread(chat: "bob", sittings: ids, messages: 42, group: false, waiting: true, before: "s0")
        let (view, window) = host(thread: thread, texts: texts)
        window.orderBack(nil)
        defer { window.orderOut(nil) }
        settle(view)

        let scroll = try XCTUnwrap(scrollView(in: view), "the thread draws its own scroll view")
        let document = try XCTUnwrap(scroll.documentView)
        XCTAssertGreaterThan(document.frame.height, scroll.contentView.bounds.height * 2, "the thread is longer than the view")
        XCTAssertLessThan(abs(distanceFromEnd(scroll)), 4, "it opens at its newest message, not at the oldest")
        snapshot(view, named: "thread-opened.png")

        // Scrolled up to the oldest message — where the old column opened — the way back is the jump (the button
        // itself is drawn by `JumpToLatestModifier`, whose wiring `JumpToLatestLintTests` holds).
        let clip = scroll.contentView
        clip.setBoundsOrigin(NSPoint(x: 0, y: 0))
        scroll.reflectScrolledClipView(clip)
        settle(view, 0.6)
        snapshot(view, named: "thread-scrolled-up.png")
        XCTAssertGreaterThan(distanceFromEnd(scroll), 200)
        let scroller = JumpToLatestScroller()
        scroller.scrollView = scroll
        scroller.jumpToEnd()
        settle(view, 1.5)
        XCTAssertLessThan(abs(distanceFromEnd(scroll)), 4, "the jump ends at the newest message")
    }
}
