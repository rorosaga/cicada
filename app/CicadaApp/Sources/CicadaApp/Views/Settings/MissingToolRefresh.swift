import SwiftUI
import AppKit

/// 2026-11-06 — a person installs Claude Code or Codex from the line a plan row gave them, in Terminal, and comes back.
/// Nothing in the app moved while they were away, so the row still said "Not installed" until they left the page and
/// returned. Coming back to the app asks again, fresh, once — only while a tool is still missing, so a Mac with
/// everything in place never probes on activation.
enum MissingTools {
    /// A plan row, or an engine card, still waiting on its tool.
    static func waiting(connections: [ConnectionStatus], candidates: [SleepEngineCandidate]) -> Bool {
        connections.contains(where: \.needsInstall)
            || candidates.contains { !$0.available && !($0.nextCommand ?? "").isEmpty && !$0.notReady }
    }
}

private struct RefreshesMissingTools: ViewModifier {
    @Environment(Store.self) private var store
    @Environment(ConnectionsViewModel.self) private var connectionsVM
    @Environment(SleepEngineViewModel.self) private var engineVM

    func body(content: Content) -> some View {
        content.onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            guard MissingTools.waiting(connections: store.connections.value ?? [],
                                       candidates: engineVM.response?.candidates ?? []) else { return }
            Task {
                // Connections first: the engine's answer reads the probe this one just refreshed.
                await connectionsVM.load(fresh: true)
                await engineVM.load()
            }
        }
    }
}

extension View {
    /// Re-probe the plans' tools when the app is brought back to the front while one is still missing.
    func refreshesMissingTools() -> some View { modifier(RefreshesMissingTools()) }
}
