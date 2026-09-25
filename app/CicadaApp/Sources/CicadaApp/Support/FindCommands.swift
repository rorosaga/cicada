import SwiftUI

/// ⌘K and ⌘F as menu commands (G136; round-3 design §1.4, ruling A6; plan
/// R-SU9). Both used to be hidden zero-size buttons (`ContentView`), and the
/// ⌘F one lived on the graph's field — which stays mounted under every other
/// tab — so ⌘F on the Feed focused a field nobody could see. A menu item is
/// discoverable, reachable through the accessibility tree, and disabled when
/// no page offers a field. `HiddenShortcutLintTests` keeps both shortcuts in
/// this file.
struct FindCommands: Commands {
    let router: AppRouter
    @FocusedValue(\.pageFind) private var pageFind

    var body: some Commands {
        CommandGroup(after: .textEditing) {
            Button("Find in Memory…") { Task { @MainActor in router.requestPalette() } }
                .keyboardShortcut("k", modifiers: .command)
            Button("Find on This Page…") { pageFind?.focus() }
                .keyboardShortcut("f", modifiers: .command)
                .disabled(pageFind == nil)
        }
    }
}

/// What a page publishes to take ⌘F: focus its own search field.
struct PageFindAction {
    let focus: () -> Void
    func callAsFunction() { focus() }
}

struct PageFindKey: FocusedValueKey {
    typealias Value = PageFindAction
}

extension FocusedValues {
    /// The classic key form rather than `@Entry`, so a macOS 14 SDK still builds.
    var pageFind: PageFindAction? {
        get { self[PageFindKey.self] }
        set { self[PageFindKey.self] = newValue }
    }
}

private struct PageFindPublisher: ViewModifier {
    let enabled: Bool
    let focus: () -> Void
    /// R-DS25 — the page under the Settings panel stays quiet.
    @Environment(\.pageFindSuppressed) private var suppressed

    /// Only the visible page publishes (R-SU10): two publishers in one scene
    /// leave SwiftUI to pick either, and a hidden one could shadow the page
    /// you are looking at.
    @ViewBuilder
    func body(content: Content) -> some View {
        if enabled && !suppressed {
            content.focusedSceneValue(\.pageFind, PageFindAction(focus: focus))
        } else {
            content
        }
    }
}

/// R-DS25 — while the Settings panel covers the window, the page under it must not answer ⌘F:
/// two publishers in one scene leave SwiftUI to pick either (R-SU10). The shell sets this; the
/// panel, outside the shell, publishes its own field.
private struct PageFindSuppressedKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var pageFindSuppressed: Bool {
        get { self[PageFindSuppressedKey.self] }
        set { self[PageFindSuppressedKey.self] = newValue }
    }
}

extension View {
    func publishesPageFind(enabled: Bool = true, focus: @escaping () -> Void) -> some View {
        modifier(PageFindPublisher(enabled: enabled, focus: focus))
    }
}

/// A request to open the palette; the nonce makes every ⌘K a change `onChange` sees.
struct PaletteRequest: Equatable {
    var prefill: String = ""
    var mode: FindMode = .find
    var nonce = UUID()
}

/// Design §3.4: ⌘K opens the palette and, when it is open, closes it. A request
/// that carries text or asks for Ask always opens — a "Search all of memory
/// for …" row must never close what it asks for. Never over the first-run
/// sheet (§3.1), and never over the Settings panel (R-DS21).
///
/// Track I part b (R-IB5): on Home the page already IS the search field, so
/// ⌘K focuses it (carrying the request's prefill and mode) instead of opening
/// a second field over the first. An overlay opened elsewhere and still up
/// after ⌘1 closes on a plain ⌘K as before.
enum PaletteToggle {
    enum Outcome: Equatable {
        case open(prefill: String, mode: FindMode)
        case close
        case ignore
        case focusHome(prefill: String, mode: FindMode)
    }

    static func outcome(for request: PaletteRequest, isOpen: Bool, firstRunShowing: Bool,
                        homeVisible: Bool = false, settingsOpen: Bool = false) -> Outcome {
        if firstRunShowing || settingsOpen { return .ignore }
        let plain = request.prefill.isEmpty && request.mode == .find
        if isOpen && plain { return .close }
        if homeVisible && !isOpen { return .focusHome(prefill: request.prefill, mode: request.mode) }
        return .open(prefill: request.prefill, mode: request.mode)
    }
}
