import AppKit
import SwiftUI

/// Track I T7 — the `+` sheet's "On this Mac": what Cicada found, each with the
/// one action that turns it on. Agents run `AgentConnect` (D-1: after THIS click,
/// with the commands visible under the row's disclosure); browsers run
/// `BrowserWatcher.syncNow` (T1's consent); Cursor opens its own confirm via its
/// deep link; Claude Desktop is finished in Settings → Agents (slice 1).
struct OnThisMacStrip: View {
    @Environment(BrowserWatcher.self) private var watcher
    @State private var inventory: LocalInventory?
    @State private var states: [FoundItemID: FoundRowState] = [:]
    @State private var refused: [FoundItemID: [String]] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.foundOnThisMac).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            if let inventory {
                // "Never blank", but never a false reason either: the backend line
                // only when the probe really had no answer — an empty list with a
                // wiring answer just means nothing here needs turning on.
                if inventory.isChecking && inventory.items.isEmpty {
                    Text(Copy.foundCheckingApps)
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                } else if !inventory.isChecking && inventory.wiring == nil {
                    Text(Copy.foundBackendDown)
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                ForEach(inventory.items) { item in row(item, wiring: inventory.wiring) }
            }
        }
        .task {
            let model = LocalInventory(probes: LocalInventory.live(watcher: watcher))
            inventory = model
            await model.refresh()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task { await inventory?.refresh() }
        }
    }

    @ViewBuilder
    private func row(_ item: FoundItem, wiring: AgentWiringResponse?) -> some View {
        let agent = wiring?.agents.first { if case .agent(let id) = item.id { return $0.id == id }; return false }
        let base: FoundRowState = {
            switch item.readiness {
            case .alreadyOn: return .on
            case .needsPermission: return .needsAction(Copy.foundAllow)
            case .failed(let why): return .failed(why)
            case .checking: return .working(Copy.foundCheckingApps)
            default: return .off
            }
        }()
        let disclosure = (agent?.connect ?? []).flatMap { [$0.display] + $0.touches.map { "Changes \($0)" } }
            + (agent == nil ? [] : [Copy.foundPastStays])
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            FoundRow(mark: Self.mark(item.id), title: item.title, detail: Self.detail(item.id),
                     state: states[item.id] ?? base, disclosure: disclosure,
                     action: { Task { await turnOn(item, agent: agent, wiring: wiring) } },
                     settingsLink: item.id == .agent("claude-desktop") ? .agents : nil)
            if let lines = refused[item.id] {
                Text(Copy.foundRefused).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                // To inspect, not to run: no copy button (see `Copy.foundRefused`).
                ForEach(lines, id: \.self) {
                    Text($0).font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    static func mark(_ id: FoundItemID) -> FoundMark {
        switch id {
        case .agent("claude-code"): .logo("claude-code")
        case .agent("codex"): .logo("codex")
        case .agent("cursor"): .app(bundleId: LocalInventory.cursorBundleId, logo: "cursor", symbol: "cursorarrow")
        case .agent("claude-desktop"): .app(bundleId: LocalInventory.claudeDesktopBundleId, logo: "claude-desktop", symbol: "bubble.left")
        case .browser("chrome-bookmarks"): .app(bundleId: "com.google.Chrome", logo: "chrome", symbol: "globe")
        case .browser("safari-bookmarks"): .app(bundleId: "com.apple.Safari", logo: nil, symbol: "safari")
        default: .logo("")
        }
    }

    static func detail(_ id: FoundItemID) -> String {
        switch id {
        case .agent("cursor"): Copy.foundCursorDetail
        case .agent("claude-desktop"): Copy.foundClaudeDesktopDetail
        case .browser: Copy.foundBrowserDetail
        default: Copy.foundAgentDetail
        }
    }

    private func turnOn(_ item: FoundItem, agent: AgentWiring?, wiring: AgentWiringResponse?) async {
        switch item.id {
        case .agent("cursor"):
            // An empty `repo` (a trimmed payload decodes to "") must not build
            // a deep link against "/api/.venv/bin/python".
            let repo = wiring?.repo.isEmpty == false ? wiring!.repo : BackendProcess.installRoot().path
            let catalog = AgentSetupCatalog.all(home: repo, memoryRoot: wiring?.memory)
            if let url = catalog.first(where: { $0.id == "cursor" })?.deeplink?.url { NSWorkspace.shared.open(url) }
        case .agent:
            guard let agent, let wiring else { return }
            states[item.id] = .working(Copy.foundConnecting)
            let outcome = await AgentConnect.run(agent.connect, installRoot: BackendProcess.installRoot(),
                                                 binaries: Set(wiring.agents.compactMap(\.binary)))
            switch outcome {
            case .done: states[item.id] = nil
            case .refused(let lines): states[item.id] = nil; refused[item.id] = lines
            case .failed(let why): states[item.id] = .failed(why)
            }
            await inventory?.refresh()
        case .browser(let channel):
            if item.readiness == .needsPermission {
                NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL)
                return
            }
            states[item.id] = .working(Copy.foundSavingBookmarks)
            do {
                _ = try await watcher.syncNow(channel)
                states[item.id] = nil
            } catch {
                states[item.id] = .failed(AddSourceSheet.friendlyError(error))
            }
            await inventory?.refresh()
        default:
            return
        }
    }
}
