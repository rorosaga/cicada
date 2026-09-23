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

    /// Only the visible page publishes (R-SU10): two publishers in one scene
    /// leave SwiftUI to pick either, and a hidden one could shadow the page
    /// you are looking at.
    @ViewBuilder
    func body(content: Content) -> some View {
        if enabled {
            content.focusedSceneValue(\.pageFind, PageFindAction(focus: focus))
        } else {
            content
        }
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
/// sheet (§3.1).
enum PaletteToggle {
    enum Outcome: Equatable {
        case open(prefill: String, mode: FindMode)
        case close
        case ignore
    }

    static func outcome(for request: PaletteRequest, isOpen: Bool, firstRunShowing: Bool) -> Outcome {
        if firstRunShowing { return .ignore }
        let plain = request.prefill.isEmpty && request.mode == .find
        if isOpen && plain { return .close }
        return .open(prefill: request.prefill, mode: request.mode)
    }
}
