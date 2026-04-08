import SwiftUI
import AppKit

enum CicadaStatus: String {
    case awake = "Awake"
    case sleeping = "Sleeping"
    case ingesting = "Ingesting"
    case confused = "Confused"

    var icon: String {
        switch self {
        case .awake: "eye"
        case .sleeping: "moon.fill"
        case .ingesting: "arrow.down.circle"
        case .confused: "exclamationmark.triangle"
        }
    }

    var description: String {
        switch self {
        case .awake: "Idle — listening for episodes"
        case .sleeping: "Running consolidation cycle..."
        case .ingesting: "Processing new episodes..."
        case .confused: "Multiple uncertainties accumulated"
        }
    }
}

@Observable
final class MenuBarManager: NSObject {
    var status: CicadaStatus = .awake

    private var statusItem: NSStatusItem?
    private var onOpenApp: (() -> Void)?

    func setup(onOpenApp: @escaping () -> Void) {
        self.onOpenApp = onOpenApp

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        updateIcon()
        buildMenu()
    }

    func updateStatus(_ newStatus: CicadaStatus) {
        status = newStatus
        updateIcon()
        buildMenu()
    }

    private func updateIcon() {
        guard let button = statusItem?.button else { return }
        let config = NSImage.SymbolConfiguration(pointSize: 14, weight: .medium)
        button.image = NSImage(systemSymbolName: status.icon, accessibilityDescription: status.rawValue)?
            .withSymbolConfiguration(config)
    }

    private func buildMenu() {
        let menu = NSMenu()

        // Status header
        let statusItem = NSMenuItem(title: "\(status.rawValue) — \(status.description)", action: nil, keyEquivalent: "")
        statusItem.isEnabled = false
        menu.addItem(statusItem)

        menu.addItem(NSMenuItem.separator())

        // Open App
        let openItem = NSMenuItem(title: "Open Cicada", action: #selector(openApp), keyEquivalent: "o")
        openItem.target = self
        menu.addItem(openItem)

        menu.addItem(NSMenuItem.separator())

        // Quit
        let quitItem = NSMenuItem(title: "Quit Cicada", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        self.statusItem?.menu = menu
    }

    @objc private func openApp() {
        onOpenApp?()
    }

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }
}
