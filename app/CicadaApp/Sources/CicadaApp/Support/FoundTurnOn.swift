import AppKit
import Foundation

enum FoundTurnOnResult: Equatable {
    /// On; the line is the row's new detail (a sync's own result), or nil for the default.
    case on(String?)
    /// Not run: these are the commands, to inspect (AgentConnectPolicy refused them).
    case refused([String])
    case failed(String)
    /// Full Disk Access opened; the row ticks itself when the grant lands (W5).
    case needsPermission
    /// Cursor asks the person itself; nothing more for Cicada to know.
    case openedApp
    case finishInSettings(SettingsSection)
}

/// Everything a turn-on touches, injected (FoundTurnOnTests), all main-actor
/// because the live ones read `LocalInventory`, `BrowserWatcher` and the router.
struct FoundTurnOnDeps {
    var wiring: @MainActor () -> AgentWiringResponse?
    var installRoot: URL
    var connect: @MainActor ([AgentWiringStep], URL, Set<String>) async -> AgentConnectOutcome
    var syncBrowser: @MainActor (String) async throws -> String
    var readiness: @MainActor (FoundItemID) -> FoundItem.Readiness?
    var open: @MainActor (URL) -> Void
    var commitDrop: @MainActor (String) async -> IntakeOutcome?
    var refresh: @MainActor () async -> Void

    @MainActor
    static func live(inventory: LocalInventory, watcher: BrowserWatcher, intake: IntakeRouter) -> FoundTurnOnDeps {
        FoundTurnOnDeps(
            wiring: { inventory.wiring },
            installRoot: BackendProcess.installRoot(),
            connect: { steps, root, binaries in await AgentConnect.run(steps, installRoot: root, binaries: binaries) },
            syncBrowser: { try await watcher.syncNow($0) },
            readiness: { id in inventory.items.first { $0.id == id }?.readiness },
            open: { NSWorkspace.shared.open($0) },
            commitDrop: { await intake.commitWelcomeDrop($0) },
            refresh: { await inventory.refresh() })
    }
}

/// Track I part b — the ONE turn-on (part a's `OnThisMacStrip.turnOn`, hoisted):
/// the `+` strip, the Welcome's Start and Getting started's Turn on / Retry all
/// run this, so an agent is wired, a browser consented and an export committed
/// the same way from every host (design §3.8: one component, many hosts).
@MainActor
enum FoundTurnOn {
    static func run(_ id: FoundItemID, deps: FoundTurnOnDeps) async -> FoundTurnOnResult {
        switch id {
        case .agent("cursor"):
            // An empty `repo` (a trimmed payload decodes to "") must not build a
            // deep link against "/api/.venv/bin/python" (part a final review).
            let wiring = deps.wiring()
            let repo = wiring.map(\.repo).flatMap { $0.isEmpty ? nil : $0 } ?? deps.installRoot.path
            guard let url = AgentSetupCatalog.all(home: repo, memoryRoot: wiring?.memory)
                .first(where: { $0.id == "cursor" })?.deeplink?.url else { return .failed(Copy.intakeFailed) }
            deps.open(url)
            return .openedApp
        case .agent("claude-desktop"):
            return .finishInSettings(.agents)
        case .agent(let agentId):
            guard let wiring = deps.wiring(), let agent = wiring.agents.first(where: { $0.id == agentId }) else {
                return .failed(Copy.foundBackendDown)
            }
            if agent.connect.isEmpty {
                return agent.recall == "on" && agent.autosave == "on" ? .on(nil) : .failed(Copy.foundCouldNotCheck)
            }
            let outcome = await deps.connect(agent.connect, deps.installRoot, Set(wiring.agents.compactMap(\.binary)))
            await deps.refresh()
            switch outcome {
            case .done: return .on(nil)
            case .refused(let lines): return .refused(lines)
            case .failed(let why): return .failed(why)
            }
        case .browser(let channel):
            if deps.readiness(id) == .needsPermission {
                deps.open(BrowserFileError.fullDiskAccessURL)
                return .needsPermission
            }
            do {
                let line = try await deps.syncBrowser(channel)
                await deps.refresh()
                return .on(line)
            } catch {
                return .failed(AddSourceSheet.friendlyError(error))
            }
        case .dropped(let dropId):
            guard let outcome = await deps.commitDrop(dropId) else { return .failed(Copy.intakeFailed) }
            if outcome.total == 0, let first = outcome.failures.first { return .failed(first) }
            return .on(IntakeSummary.headline(outcome))
        case .app:
            return .finishInSettings(.integrations)
        }
    }
}
