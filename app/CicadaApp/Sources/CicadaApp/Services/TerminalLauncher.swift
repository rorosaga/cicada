import AppKit
import Foundation

/// Launching a terminal for `claude --resume <uuid>` (G48 §5).
///
/// The backend validates and hands us a descriptor; this type only launches.
/// Ladder: Ghostty (when installed) -> Terminal.app -> clipboard, mirroring
/// `ConnectionsView.openInTerminal`'s shipped fallback shape.
///
/// SAFETY: a string reaches AppleScript source only after `isSafeCommand` /
/// `isSafeCwd`. Nothing else is ever interpolated, and `/bin/sh -c` is never
/// used. `terminalScript` composes `cd <cwd> && <command>` from two
/// independently validated pieces plus fixed literals.
///
/// The Ghostty invocation below was verified once (Task 6 of G48's plan,
/// 2026-08-31) against Ghostty 1.3.1's AppleScript dictionary
/// (`sdef /Applications/Ghostty.app`) with a harmless `echo cicada-test`
/// before being hard-wired here. `sdef` confirmed the `surface configuration`
/// record's property names verbatim — `command`, `initial working directory`,
/// `wait after command`, `environment variables` — and osascript variant A
/// (`new window with configuration {command:..., initial working
/// directory:...}`) exited 0 on the first try, opening a Ghostty window that
/// printed `cicada-test`. No fallback variant was needed.
enum TerminalLauncher {

    enum Outcome: Equatable {
        case ghostty
        case terminal
        case clipboard
    }

    static let ghosttyAppPath = "/Applications/Ghostty.app"

    /// Letters, digits, space, and the punctuation a `claude --resume <uuid>`
    /// line legitimately needs. Deliberately excludes `"` `\` `$` `` ` `` `;`
    /// `&` `|` and every newline.
    private static let commandPattern = "^[A-Za-z0-9 ._:/@=-]+$"
    /// Same conservative charset the backend uses for `cwd`.
    private static let cwdPattern = "^[A-Za-z0-9/_.~-]+$"

    static func isSafeCommand(_ value: String) -> Bool {
        matches(value, commandPattern)
    }

    static func isSafeCwd(_ value: String) -> Bool {
        (value.hasPrefix("/") || value.hasPrefix("~")) && matches(value, cwdPattern)
    }

    private static func matches(_ value: String, _ pattern: String) -> Bool {
        guard !value.isEmpty else { return false }
        return value.range(of: pattern, options: .regularExpression) != nil
    }

    // MARK: - Pure script builders

    /// `nil` when the command fails the gate. An unsafe `cwd` is DROPPED (the
    /// window opens in Ghostty's default directory) rather than sanitised.
    static func ghosttyScript(command: String, cwd: String?) -> String? {
        guard isSafeCommand(command) else { return nil }
        var configuration = "command:\"\(command)\""
        if let cwd, isSafeCwd(cwd) {
            configuration += ", initial working directory:\"\(cwd)\""
        }
        return """
        tell application "Ghostty"
        activate
        new window with configuration {\(configuration)}
        end tell
        """
    }

    static func terminalScript(command: String, cwd: String?) -> String? {
        guard isSafeCommand(command) else { return nil }
        var full = command
        if let cwd, isSafeCwd(cwd) {
            full = "cd \(cwd) && \(command)"
        }
        return "tell application \"Terminal\"\nactivate\ndo script \"\(full)\"\nend tell"
    }

    // MARK: - Ladder

    @discardableResult
    static func launch(
        command: String,
        cwd: String?,
        ghosttyInstalled: Bool = FileManager.default.fileExists(atPath: ghosttyAppPath),
        run: (String) -> Bool = runAppleScript
    ) -> Outcome {
        if ghosttyInstalled, let script = ghosttyScript(command: command, cwd: cwd), run(script) {
            return .ghostty
        }
        if let script = terminalScript(command: command, cwd: cwd), run(script) {
            return .terminal
        }
        copyToClipboard(command)
        return .clipboard
    }

    static func runAppleScript(_ source: String) -> Bool {
        guard let script = NSAppleScript(source: source) else { return false }
        var error: NSDictionary?
        script.executeAndReturnError(&error)
        return error == nil
    }

    private static func copyToClipboard(_ value: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
    }
}
