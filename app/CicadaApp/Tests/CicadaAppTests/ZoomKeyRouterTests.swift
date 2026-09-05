import AppKit
import XCTest
@testable import CicadaApp

/// G130 R5: the View menu's `CommandGroup` owns ⌘= / ⌘− / ⌘0 directly — SwiftUI
/// resolves those key equivalents on its own, no monitor involved. The ONLY
/// chord a `Button.keyboardShortcut` cannot also claim is ⌘⇧= (what a US
/// keyboard actually sends for the "⌘+" people type), because macOS treats
/// `=`+shift and `+` as distinct events and the menu already claimed plain
/// `=`. `ZoomKeyRouter` is the pure function behind the local key monitor
/// that catches that one extra chord — pure so this file never has to spin
/// up a window or synthesize a real `NSEvent` to prove it works.
final class ZoomKeyRouterTests: XCTestCase {
    func test_shiftEquals_isZoomIn() {
        XCTAssertEqual(ZoomKeyRouter.action(characters: "=", modifiers: [.command, .shift]), .zoomIn)
    }

    func test_plusCharacter_withCommand_isZoomIn() {
        // Some layouts/keyboards send the "+" character directly rather than
        // "=" plus a shift flag — both must resolve to the same action.
        XCTAssertEqual(ZoomKeyRouter.action(characters: "+", modifiers: [.command]), .zoomIn)
    }

    func test_plainCommandEquals_isNil() {
        // The menu's "Zoom In" item already owns bare ⌘= — the monitor must
        // not double-fire it.
        XCTAssertNil(ZoomKeyRouter.action(characters: "=", modifiers: [.command]))
    }

    func test_commandMinus_isNil() {
        // ⌘− is the menu's "Zoom Out" equivalent, expressible on its own —
        // nothing for the monitor to do here.
        XCTAssertNil(ZoomKeyRouter.action(characters: "-", modifiers: [.command]))
    }

    func test_commandOptionPlus_isNil() {
        // A different chord entirely (e.g. a layout's own binding) — must not
        // be mistaken for the one chord this router owns.
        XCTAssertNil(ZoomKeyRouter.action(characters: "+", modifiers: [.command, .option]))
    }

    func test_unrelatedShortcut_isNil() {
        XCTAssertNil(ZoomKeyRouter.action(characters: "k", modifiers: [.command]))
    }
}
