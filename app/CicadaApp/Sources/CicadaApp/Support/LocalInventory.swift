import AppKit
import Foundation

enum BrowserPresence: Equatable { case absent, blocked, off, on }

struct InventorySnapshot: Equatable {
    var wiring: AgentWiringResponse?
    var installedBundles: Set<String>
    var browsers: [String: BrowserPresence]
    var claudeDesktopHasCicada: Bool?
}

/// Everything detection touches, injected (design §12 T7: "LocalInventory with
/// injected probes"). The live set reads only local state — bundle ids, file
/// presence, one JSON key — and one loopback call; no outbound network.
struct LocalInventoryProbes {
    var wiring: () async -> AgentWiringResponse?
    var isInstalled: (String) -> Bool
    var browserPresence: (String) -> BrowserPresence
    var claudeDesktopHasCicada: () -> Bool?
}

/// Track I T7 (design §4.1.3) — detect, don't ask. Detect by bundle id, never
/// by name; an absent app has no row; a backend-probed row appears once the
/// probe answers. Part b's Welcome and this track's `+` strip share it.
@MainActor
@Observable
final class LocalInventory {
    nonisolated static let cursorBundleId = "com.todesktop.230313mzl4w4u92"
    nonisolated static let claudeDesktopBundleId = "com.anthropic.claudefordesktop"

    private(set) var items: [FoundItem] = []
    private(set) var wiring: AgentWiringResponse?
    private(set) var isChecking = false
    /// A scan has finished at least once. `items == []` means "nothing here"
    /// only after this; before it, it means "not asked yet" — the inventory is
    /// app-level and refreshed only by the Welcome and Getting started, so on an
    /// established bank it is still empty when *Show setup checklist* first
    /// renders the card (I-b final re-review, finding 4).
    private(set) var hasChecked = false
    @ObservationIgnored var probes: LocalInventoryProbes

    init(probes: LocalInventoryProbes) { self.probes = probes }

    func refresh() async {
        isChecking = true
        let fetched = await probes.wiring()
        let installed = Set([Self.cursorBundleId, Self.claudeDesktopBundleId].filter(probes.isInstalled))
        let snapshot = InventorySnapshot(
            wiring: fetched,
            installedBundles: installed,
            browsers: Dictionary(uniqueKeysWithValues: BrowserWatchPolicy.watched.map { ($0.channel, probes.browserPresence($0.channel)) }),
            // R-IA29: Claude Desktop's config is read only when the app is here.
            claudeDesktopHasCicada: installed.contains(Self.claudeDesktopBundleId) ? probes.claudeDesktopHasCicada() : nil)
        wiring = fetched
        items = FoundPolicy.order(Self.items(from: snapshot))
        isChecking = false
        hasChecked = true
    }

    nonisolated static func items(from s: InventorySnapshot) -> [FoundItem] {
        var out: [FoundItem] = []
        for (id, title) in [("claude-code", "Claude Code"), ("codex", "Codex")] {
            guard let a = s.wiring?.agents.first(where: { $0.id == id }), a.installed else { continue }
            let readiness: FoundItem.Readiness
            if a.recall == "on" && a.autosave == "on" { readiness = .alreadyOn }
            else if a.autosave == "invalid" { readiness = .failed(Copy.foundInvalidSettings) }
            // Nothing to run and not on: the probe timed out (`recall: unknown`,
            // never offered an `mcp` step). A spinner here would never end — say
            // so, and the row's Retry re-probes.
            else if a.connect.isEmpty { readiness = .failed(Copy.foundCouldNotCheck) }
            else { readiness = .ready }
            out.append(FoundItem(id: .agent(id), group: .agents, title: title, isPresent: true,
                                 content: .ownIntentionalAct, readiness: readiness, opensAnotherApp: false))
        }
        if s.installedBundles.contains(cursorBundleId) {
            out.append(FoundItem(id: .agent("cursor"), group: .agents, title: "Cursor", isPresent: true,
                                 content: .ownIntentionalAct, readiness: .ready, opensAnotherApp: true))
        }
        if s.installedBundles.contains(claudeDesktopBundleId) {
            out.append(FoundItem(id: .agent("claude-desktop"), group: .agents, title: "Claude", isPresent: true,
                                 content: .ownIntentionalAct,
                                 readiness: s.claudeDesktopHasCicada == true ? .alreadyOn : .ready, opensAnotherApp: true))
        }
        for (channel, title) in [("chrome-bookmarks", "Chrome"), ("safari-bookmarks", "Safari")] {
            let readiness: FoundItem.Readiness
            switch s.browsers[channel] ?? .absent {
            case .absent: continue
            case .blocked: readiness = .needsPermission
            case .off: readiness = .ready
            case .on: readiness = .alreadyOn
            }
            out.append(FoundItem(id: .browser(channel), group: .browsers, title: title, isPresent: true,
                                 content: .ownIntentionalAct, readiness: readiness, opensAnotherApp: false))
        }
        return out
    }

    /// The live probes. The app reads `~/Library` (CLAUDE.md rail); the backend is
    /// asked only for what it alone can answer (the CLIs, via `/agents/wiring`).
    static func live(watcher: BrowserWatcher) -> LocalInventoryProbes {
        LocalInventoryProbes(
            wiring: { try? await APIClient.shared.fetchAgentWiring() },
            isInstalled: { NSWorkspace.shared.urlForApplication(withBundleIdentifier: $0) != nil },
            browserPresence: { channel in
                guard let file = BrowserWatchPolicy.file(for: channel) else { return .absent }
                // Open, never `fileExists` first: a stat TCC refuses answers "no
                // such file" (`BrowserFileReader.readIfPresent`'s L2 note), which
                // would turn a blocked Safari into an absent one and hide its
                // Allow… row; `isReadableFile` says yes to a Full-Disk-Access file
                // the app cannot read. Only the errno of an open tells the three
                // apart. Nothing is read — the descriptor closes at once.
                var blocked = false
                for url in file.candidatePaths {
                    let fd = open(url.path, O_RDONLY)
                    if fd >= 0 {
                        close(fd)
                        return watcher.isEnabled(channel) ? .on : .off
                    }
                    if errno != ENOENT && errno != ENOTDIR { blocked = true }
                }
                return blocked ? .blocked : .absent
            },
            claudeDesktopHasCicada: {
                let url = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Application Support/Claude/claude_desktop_config.json")
                guard let data = try? Data(contentsOf: url) else { return nil }
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                return (json?["mcpServers"] as? [String: Any])?["cicada"] != nil
            })
    }
}
