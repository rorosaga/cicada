import AppKit // NSEvent.ModifierFlags — this file has no SwiftUI import to inherit it from

/// The one thing `CicadaApp`'s local key monitor can do that the View menu's
/// own `CommandGroup` cannot (G130 R5).
///
/// Named `ChromeZoomAction`, not `ZoomAction` — `GraphViewModel.swift`
/// already defines a `ZoomAction` for the graph canvas's OWN zoom (in/out/
/// reset/fit), which slice 1 leaves untouched. Reusing the bare name would
/// either collide or silently overload the graph's action with the chrome's,
/// two unrelated concerns (whole-app text scale vs. one WKWebView's pan/zoom)
/// that must never be confused for each other.
enum ChromeZoomAction {
    case zoomIn
    case zoomOut
    case reset
}

/// SwiftUI can give a `Button` exactly one `keyboardShortcut`, so the View
/// menu already claims bare ⌘= (Zoom In), ⌘− (Zoom Out) and ⌘0 (Actual Size)
/// directly — two "Zoom In" rows to cover both ⌘= and ⌘⇧= would read as a
/// bug, and the menu resolves its own equivalents without this router's
/// help. The ONE chord left over is ⌘⇧= — what a US keyboard actually sends
/// when someone types "⌘+" — because macOS reports `=`+shift and a literal
/// `+` character as distinct key events from bare `=`.
///
/// Pure function, no `NSEvent` construction needed to test it: `CicadaApp`
/// installs a single `NSEvent.addLocalMonitorForEvents(matching: .keyDown)`
/// (idempotent, guarded by `zoomMonitor == nil`, same pattern as
/// `enableFirstMouseAcceptance`) that calls this and returns the event
/// unhandled (`nil` result here) for everything else, so no other shortcut
/// in the app (⌘1–6, ⌘K, ⌘F, ⌘N, ⌘[) is ever intercepted.
enum ZoomKeyRouter {
    static func action(characters: String, modifiers: NSEvent.ModifierFlags) -> ChromeZoomAction? {
        // Strip caps-lock/function/etc. noise so only the modifiers that
        // matter to a shortcut are compared.
        let mods = modifiers.intersection(.deviceIndependentFlagsMask)
        // `NSEvent.characters` (not `charactersIgnoringModifiers`) already
        // applies Shift's effect on the key it's paired with — a real
        // Shift+Command+= keydown on a US keyboard reports "+", never "=".
        // Checking "=" here with `.shift` in mods matches an event macOS
        // never sends, which silently defeated this router's one job.
        let plusViaShift = characters == "+" && mods == [.command, .shift]
        let plusDirect = characters == "+" && mods == [.command]
        return (plusViaShift || plusDirect) ? .zoomIn : nil
    }
}
