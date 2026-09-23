import AppKit

/// R-IA25 — URLs from the Dock ("Open With", a drop on the icon) arrive through
/// the app delegate, and on a cold launch they arrive BEFORE `ContentView`'s
/// `.onAppear` has attached the router. They wait here, then flow straight through.
@MainActor
final class DockOpenQueue {
    private var pending: [URL] = []
    private var handler: (([URL]) -> Void)?

    func receive(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        if let handler { handler(urls) } else { pending += urls }
    }

    func attach(_ handler: @escaping ([URL]) -> Void) {
        self.handler = handler
        guard !pending.isEmpty else { return }
        let urls = pending
        pending = []
        handler(urls)
    }
}

/// The one AppKit hook SwiftUI's `App` lacks for a Dock open (F10).
@MainActor
final class CicadaAppDelegate: NSObject, NSApplicationDelegate {
    let opens = DockOpenQueue()

    func application(_ application: NSApplication, open urls: [URL]) {
        opens.receive(urls)
    }
}
