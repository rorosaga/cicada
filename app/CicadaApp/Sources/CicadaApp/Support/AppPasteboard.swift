import AppKit

/// The one door to the clipboard. The app copies into the person's clipboard; the test suite never does.
///
/// Found 2026-09-24: `TerminalLauncher`'s clipboard fallback and `ConversationsViewModel.copyCommand` wrote
/// `NSPasteboard.general` from `swift test`, so every run of the suite replaced whatever the owner had copied
/// with a fixture's `claude --resume 0f8f1c2a-…`. Under XCTest this door is a private named pasteboard, so a
/// test can still read back what the app copied and the person's clipboard is never touched — not written, and
/// not read either (the menu bar's "save the copied link" reads through here too). `ClipboardLintTests` keeps
/// every other file from reaching `NSPasteboard.general` directly.
enum AppPasteboard {
    /// True inside the `swift test` process (XCTest is loaded), false in the shipped app.
    static var isRunningTests: Bool { NSClassFromString("XCTestCase") != nil }

    /// The pasteboard the app reads and writes: the system clipboard in the app, a private one under tests.
    static var board: NSPasteboard {
        isRunningTests ? NSPasteboard(name: NSPasteboard.Name("com.cicada.tests.pasteboard")) : .general
    }

    /// Replace the clipboard's contents with `text`.
    static func copy(_ text: String) {
        let pasteboard = board
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
    }
}
