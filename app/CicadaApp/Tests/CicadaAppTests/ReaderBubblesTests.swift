import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The Reader's chat, both sides bubbled, and a cited passage that does not look selected (owner, 2026-10-20;
/// DESIGN_RULES §9). Every conversation here is synthetic.
@MainActor
final class ReaderBubblesTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    private let gb = Locale(identifier: "en_GB")
    private let now = ISO8601DateFormatter().date(from: "2026-10-19T15:00:00Z")!

    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private func built(_ doc: EpisodeText, focus: Range<Int>? = nil, others: [Range<Int>] = [],
                       focusStyle: ReaderWash.Style = .focus) -> [ReaderChat.Row] {
        let blocks = ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: focus, focusStyle: focusStyle,
                                         others: others, locale: gb, timeZone: utc)
        var keepOpen = Set(blocks.filter(\.holdsFocus).map(\.index))
        if let focus, let key = ReaderLayout.blockID(containing: focus.lowerBound, in: blocks) { keepOpen.insert(key.turn) }
        return ReaderChat.rows(blocks: blocks, doc: doc, expanded: [], keepOpen: keepOpen, now: now, locale: gb,
                               timeZone: utc)
    }

    private func messages(_ rows: [ReaderChat.Row]) -> [ReaderChat.Message] {
        rows.compactMap { if case let .message(m) = $0.kind { m } else { nil } }
    }

    private func range(of needle: String, in doc: EpisodeText) throws -> Range<Int> {
        let hay = Array(doc.text.unicodeScalars)
        let n = Array(needle.unicodeScalars)
        for i in 0...(hay.count - n.count) where Array(hay[i..<(i + n.count)]) == n { return i..<(i + n.count) }
        throw XCTSkip("fixture lost \(needle)")
    }

    // MARK: The cited marker

    /// A message holding the landed span is marked "current", one holding another cited span "other", a name found by
    /// searching nothing — and VoiceOver says the marker before the words.
    func testACitedMessageCarriesAQuietMarkerSaidInWords() throws {
        let doc = ReaderChatTests.messagesSitting()
        let landed = try range(of: "pack the map and the water filter", in: doc)
        let other = try range(of: "Saturday morning works", in: doc)
        let out = messages(built(doc, focus: landed, others: [other]))
        let landedMessage = try XCTUnwrap(out.first { $0.block.text.contains("water filter") })
        let otherMessage = try XCTUnwrap(out.first { $0.block.text.contains("Saturday") })
        let plain = try XCTUnwrap(out.first { $0.block.text.contains("See you there") })
        XCTAssertEqual(ReaderChat.citedMark(landedMessage.block), .current)
        XCTAssertEqual(ReaderChat.citedMark(otherMessage.block), .other)
        XCTAssertNil(ReaderChat.citedMark(plain.block))
        XCTAssertTrue(ReaderChat.accessibilityLabel(landedMessage).hasPrefix(Copy.Provenance.citedHere + ". "))
        XCTAssertTrue(ReaderChat.accessibilityLabel(otherMessage).hasPrefix(Copy.Provenance.alsoCitedHere + ". "))
        XCTAssertFalse(ReaderChat.accessibilityLabel(plain).contains(Copy.Provenance.citedHere))

        // R-DI11 — a name found by searching is not a citation, so it is never marked "cited".
        let found = messages(built(doc, focus: landed, focusStyle: .mention))
        XCTAssertTrue(found.allSatisfy { ReaderChat.citedMark($0.block) == nil })
    }

    /// The marker fits the room every bubble leaves, at every zoom step, so a cited bubble is never narrower.
    func testTheMarkerFitsTheRoomABubbleLeaves() throws {
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            for side in [ReaderChat.Side.person, .other] {
                let renderer = ImageRenderer(content: ReaderCitedMarker(mark: .current, side: side))
                let width = try XCTUnwrap(renderer.nsImage).size.width
                let slot = CicadaTheme.scaled(ReaderChatMessageView.otherSideRoom - ReaderChatMessageView.markerGap)
                XCTAssertGreaterThan(width, 0)
                XCTAssertLessThanOrEqual(width, slot, "\(scale) \(side): \(width) > \(slot)")
            }
        }
    }

    // MARK: Never a selection token

    /// The tint on cited words is neutral ink, never the accent macOS draws a text selection in, and no selection or
    /// hover fill is reused for a citation or a bubble.
    func testACitationNeverUsesASelectionToken() throws {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for (name, tint) in [("wash", CicadaTheme.wash), ("washSoft", CicadaTheme.washSoft)] {
                let c = try XCTUnwrap(NSColor(tint).usingColorSpace(.sRGB))
                XCTAssertEqual(c.redComponent, c.blueComponent, accuracy: 0.001, "\(mode) \(name) carries a hue")
                XCTAssertEqual(c.greenComponent, c.blueComponent, accuracy: 0.001, "\(mode) \(name) carries a hue")
                XCTAssertLessThanOrEqual(c.alphaComponent, 0.1, "\(mode) \(name) is more than a faint tint")
            }
            let selectionLike = [CicadaTheme.bgSelected, CicadaTheme.bgHover, CicadaTheme.bgButtonHover]
            for (name, fill) in [("chatBubbleFill", CicadaTheme.chatBubbleFill),
                                 ("chatBubbleOtherFill", CicadaTheme.chatBubbleOtherFill)] {
                for other in selectionLike {
                    XCTAssertNotEqual(Self.hex(fill), Self.hex(other), "\(mode) \(name) is a selection or hover fill")
                }
            }
            XCTAssertNotEqual(Self.hex(CicadaTheme.chatBubbleFill), Self.hex(CicadaTheme.chatBubbleOtherFill),
                              "\(mode): the two sides share one fill")
        }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        for file in ["Views/Common/CitedSpan.swift", "Views/Provenance/ReaderChatView.swift"] {
            let source = try String(contentsOf: root.appendingPathComponent(file), encoding: .utf8)
            for needle in ["bgSelected", "rowHover", "selectedTextBackgroundColor", "backgroundColor = CicadaTheme.accent"] {
                XCTAssertFalse(source.contains(needle), "\(file) draws a citation or a bubble with \(needle)")
            }
        }
        let theme = try String(contentsOf: root.appendingPathComponent("Theme/CicadaTheme.swift"), encoding: .utf8)
        XCTAssertFalse(theme.contains("static var wash: Color { accent"), "the wash is the accent again")
        XCTAssertFalse(theme.contains("static var chatBubbleFill: Color { bgSelected }"), "the bubble is the selection")
    }

    /// Review of #383 — the document view has no "Cited" marker, so VoiceOver says the cited words there too, in the
    /// chat's words; a block with no cited span reads as it did.
    func testTheDocumentViewSaysWhichBlocksAreCited() throws {
        let doc = ReaderChatTests.conversation([
            .init(marker: "user", text: "Move the bench to the north lot on Friday.", ts: "2026-10-19T09:00:00+00:00"),
            .init(marker: "assistant", text: "Noted: the bench moves on Friday.", ts: "2026-10-19T09:01:00+00:00"),
            .init(marker: "user", text: "Thanks.", ts: "2026-10-19T09:02:00+00:00"),
        ], harness: "claude-code", origin: "claude-code")
        let focus = try range(of: "north lot", in: doc)
        let other = try range(of: "moves on Friday", in: doc)
        let blocks = ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: focus, focusStyle: .focus,
                                         others: [other], locale: gb, timeZone: utc)
        let said = blocks.map(ReaderTurnView.accessibilityWords)
        XCTAssertEqual(said.filter { $0.hasPrefix(Copy.Provenance.citedHere + ". ") }.count, 1, "\(said)")
        XCTAssertEqual(said.filter { $0.hasPrefix(Copy.Provenance.alsoCitedHere + ". ") }.count, 1, "\(said)")
        XCTAssertTrue(said.contains { $0.hasPrefix(Copy.Provenance.citedHere + ". ") && $0.contains("north lot") })
        XCTAssertTrue(said.contains { $0.hasPrefix(Copy.Provenance.alsoCitedHere + ". ") && $0.contains("moves on") })
        XCTAssertTrue(said.contains { !$0.hasPrefix("Cited") && !$0.hasPrefix("Also") && $0.contains("Thanks.") })
    }

    // MARK: Both sides bubbled

    /// The person's bubble on the right in `chatBubbleFill`, the other party's on the left in `chatBubbleOtherFill`.
    func testBothSidesSitInABubble() throws {
        let doc = ReaderChatTests.conversation([
            .init(marker: "user", text: "Can you check the trail map for the north lot?", ts: "2026-10-19T09:00:00+00:00"),
            .init(marker: "assistant", text: "Yes — the north lot is the second trailhead on the map.",
                  ts: "2026-10-19T09:01:00+00:00"),
        ], harness: "claude-code", origin: "claude-code")
        let store = ReaderChatTests.store()
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let width: CGFloat = 360
            let view = ReaderChatView(rows: built(doc), landingTurn: nil, revealed: true)
                .frame(width: width)
                .background(CicadaTheme.bgPane)
                .environment(store)
            let renderer = ImageRenderer(content: view)
            renderer.scale = 1
            let rep = NSBitmapImageRep(cgImage: try XCTUnwrap(renderer.cgImage))
            func count(_ x: Int, _ fill: Color) throws -> Int {
                // The expected pixel as this renderer draws the colour (its colour space is not the token's).
                let swatch = ImageRenderer(content: Rectangle().fill(fill).frame(width: 4, height: 4))
                swatch.scale = 1
                let want = try XCTUnwrap(NSBitmapImageRep(cgImage: try XCTUnwrap(swatch.cgImage)).colorAt(x: 2, y: 2))
                return (0..<rep.pixelsHigh).filter { y in
                    guard let c = rep.colorAt(x: x, y: y) else { return false }
                    return abs(c.redComponent - want.redComponent) < 0.006
                        && abs(c.greenComponent - want.greenComponent) < 0.006
                        && abs(c.blueComponent - want.blueComponent) < 0.006
                }.count
            }
            XCTAssertGreaterThan(try count(rep.pixelsWide - 5, CicadaTheme.chatBubbleFill), 20,
                                 "\(mode): the person's words are not in their bubble")
            XCTAssertGreaterThan(try count(5, CicadaTheme.chatBubbleOtherFill), 20,
                                 "\(mode): the other party's words are not in a bubble")
            XCTAssertEqual(try count(5, CicadaTheme.chatBubbleFill), 0, "\(mode): the person's bubble on the left")
        }
    }

    /// Code blocks, lists and an unbroken token stay inside the bubble's width on both sides, at every zoom step;
    /// a long agent reply still folds behind "Show more".
    func testCodeAndListsStayInsideTheBubbleAndLongRepliesStillFold() throws {
        let code = "```swift\nlet index = try VectorIndex.open(path: \"" + String(repeating: "x", count: 160) + "\")\n```"
        let list = "- move the index\n- re-run the bench\n1. first\n2. second"
        let doc = ReaderChatTests.conversation([
            .init(marker: "user", text: "\(code)\n\(list)", ts: "2026-10-19T09:00:00+00:00"),
            .init(marker: "assistant", text: "\(list)\n\(code)", ts: "2026-10-19T09:01:00+00:00"),
        ], harness: "claude-code", origin: "claude-code")
        let store = ReaderChatTests.store()
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            for column: CGFloat in [304, 364] {
                let width = column * CGFloat(scale)
                let renderer = ImageRenderer(content: ReaderChatView(rows: built(doc), landingTurn: nil, revealed: true)
                    .environment(store))
                renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                let size = try XCTUnwrap(renderer.nsImage).size
                XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(column) × \(scale): \(size.width)")
            }
        }
        CicadaTheme.uiScale = 1
        let long = messages(built(ReaderChatTests.exportWithLongReply()))
        let reply = try XCTUnwrap(long.first { $0.block.index == 2 })
        XCTAssertEqual(reply.side, .other)
        XCTAssertTrue(reply.folded, "a long agent reply still folds inside its bubble")
    }

    // MARK: Keyboard jumps never animate

    /// DR-60 — an in-place jump a key asked for lands in one frame with no ring; the pointer's fades the wash in and
    /// rings the landed message; opening the Reader keeps its fade and never rings.
    func testAKeyboardJumpNeverAnimates() {
        XCTAssertEqual(ReaderLandingMotion.choose(isJump: true, trigger: .keyboard, isChat: true, landed: true), .instant)
        XCTAssertEqual(ReaderLandingMotion.choose(isJump: true, trigger: .keyboard, isChat: false, landed: true), .instant)
        XCTAssertEqual(ReaderLandingMotion.choose(isJump: true, trigger: .pointer, isChat: true, landed: true),
                       .revealAndEmphasise)
        XCTAssertEqual(ReaderLandingMotion.choose(isJump: true, trigger: .pointer, isChat: false, landed: true), .reveal)
        XCTAssertEqual(ReaderLandingMotion.choose(isJump: false, trigger: .pointer, isChat: true, landed: true), .reveal)
        // The navigator's ⌥↑ / ⌥↓ arrive as a key event; a click does not.
        XCTAssertEqual(LooksZoom.trigger(for: .keyDown), .keyboard)
        XCTAssertEqual(LooksZoom.trigger(for: .leftMouseUp), .pointer)
    }

    /// The jump reads its trigger from the event that ran it, and the keyboard path goes through `Instant.run`.
    func testTheReaderReadsTheJumpsTriggerAndLandsAKeyInOneFrame() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        let source = try String(contentsOf: root.appendingPathComponent("Views/Provenance/ReaderColumn.swift"),
                                encoding: .utf8)
        XCTAssertTrue(source.contains("let trigger = ReaderJumpAsk.trigger(ask, eventType: NSApp.currentEvent?.type)"))
        XCTAssertTrue(source.contains("case .instant:\n                Instant.run { washVisible = true }"))
    }

    /// DR-60 — a VoiceOver press on the navigator's chevrons or a "Noted" row is never the pointer, whatever event came
    /// last (a click, often): it lands as a key does, in one frame with no ring. Every jump control routes it.
    func testAnAssistivePressLandsAsAKeyDoes() throws {
        for type: NSEvent.EventType? in [nil, .leftMouseUp, .leftMouseDown, .mouseMoved, .keyDown, .scrollWheel] {
            XCTAssertEqual(ReaderJumpAsk.trigger(.assistive, eventType: type), .keyboard, "\(String(describing: type))")
        }
        XCTAssertEqual(ReaderJumpAsk.trigger(.event, eventType: .leftMouseUp), .pointer)
        XCTAssertEqual(ReaderJumpAsk.trigger(.event, eventType: .keyDown), .keyboard)
        XCTAssertEqual(ReaderLandingMotion.choose(isJump: true, trigger: ReaderJumpAsk.trigger(.assistive,
                                                  eventType: .leftMouseUp), isChat: true, landed: true), .instant)

        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        let source = try String(contentsOf: root.appendingPathComponent("Views/Provenance/ReaderColumn.swift"),
                                encoding: .utf8)
        // Both chevrons, and the noted row's jump button.
        XCTAssertEqual(source.components(separatedBy: "position: position, ask: .assistive)").count - 1, 2)
        XCTAssertTrue(source.contains(".modifier(AssistivePress(action: { onJump(.assistive) }))"))
        let button = try String(contentsOf: root.appendingPathComponent("Views/Common/IconButton.swift"), encoding: .utf8)
        XCTAssertTrue(button.contains(".modifier(AssistivePress(action: accessibilityPress))"))
        XCTAssertTrue(button.contains("content.accessibilityAction(.default, action)"))
    }

    // MARK: Helpers

    static func rgb(_ color: Color) -> (CGFloat, CGFloat, CGFloat) {
        let c = NSColor(color).usingColorSpace(.sRGB) ?? .black
        return (c.redComponent, c.greenComponent, c.blueComponent)
    }

    static func hex(_ color: Color) -> String {
        let (r, g, b) = rgb(color)
        let a = NSColor(color).usingColorSpace(.sRGB)?.alphaComponent ?? 1
        return [r, g, b, a].map { String(format: "%02X", Int(($0 * 255).rounded())) }.joined()
    }
}
