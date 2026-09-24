import Foundation
import Observation

/// G149 — what one agent's "Remembers automatically" row says and does, as
/// pure functions over `GET /agents/wiring`'s `autorecall` fields, so the view
/// is a renderer.
enum AutoRecallState: Equatable {
    case on, off, needsUpdate, unreadable, unavailable

    init(wire: String) {
        switch wire {
        case "on": self = .on
        case "off": self = .off
        case "stale": self = .needsUpdate
        case "invalid": self = .unreadable
        default: self = .unavailable
        }
    }
}

struct AutoRecallAction: Equatable {
    let title: String
    let steps: [AgentWiringStep]

    /// The files the steps change, once each, for the disclosure (spec decision 14).
    var touches: [String] {
        var seen = Set<String>()
        return steps.flatMap(\.touches).filter { seen.insert($0).inserted }
    }
}

enum AutoRecall {
    /// The agents this group lists: installed, and with a state the page can act on or explain.
    static func rows(_ wiring: AgentWiringResponse?) -> [AgentWiring] {
        (wiring?.agents ?? []).filter { $0.installed && state(of: $0) != .unavailable }
    }

    static func state(of agent: AgentWiring) -> AutoRecallState { AutoRecallState(wire: agent.autorecall) }

    /// One button per state, and only with the backend's argv behind it: a
    /// state with no steps (an unreadable file) offers nothing (R-IA15's rule).
    static func action(for agent: AgentWiring) -> AutoRecallAction? {
        switch state(of: agent) {
        case .off where !agent.autorecallOn.isEmpty:
            AutoRecallAction(title: Copy.autoRecallTurnOn, steps: agent.autorecallOn)
        case .needsUpdate where !agent.autorecallOn.isEmpty:
            AutoRecallAction(title: Copy.autoRecallUpdate, steps: agent.autorecallOn)
        case .on where !agent.autorecallOff.isEmpty:
            AutoRecallAction(title: Copy.autoRecallTurnOff, steps: agent.autorecallOff)
        default:
            nil
        }
    }

    static func detail(_ state: AutoRecallState) -> String {
        switch state {
        case .on: Copy.autoRecallOn
        case .off: Copy.autoRecallOff
        case .needsUpdate: Copy.autoRecallStale
        case .unreadable, .unavailable: Copy.autoRecallUnreadable
        }
    }

    /// The group's one lead line (DR-38): still checking, the backend not
    /// answering, no agent that can, or what the group does. A fetch that never
    /// answered reads as the backend waiting, never as "no agent can".
    static func lead(loaded: Bool, wiring: AgentWiringResponse?) -> String {
        if !loaded { return Copy.autoRecallChecking }
        guard let wiring else { return Copy.foundBackendDown }
        return rows(wiring).isEmpty ? Copy.autoRecallNone : Copy.autoRecallDetail
    }

    static func name(_ id: String) -> String { OriginIconography.label(for: id) }

    /// Every sentence this group can show, for `AutoRecallTests`' copy lint.
    static let words: [String] = [
        Copy.autoRecallGroup, Copy.autoRecallTitle, Copy.autoRecallDetail, Copy.autoRecallChecking,
        Copy.autoRecallNone, Copy.autoRecallOn, Copy.autoRecallOff, Copy.autoRecallStale, Copy.autoRecallUnreadable,
        Copy.autoRecallTurnOn, Copy.autoRecallTurnOff, Copy.autoRecallUpdate, Copy.autoRecallWorking,
        Copy.autoRecallWorkingHelp, Copy.autoRecallCodexTrust, Copy.autoRecallChanges(["~/.claude/settings.json"]),
    ]
}

/// The group's state. Last-known-good: a fetch that fails keeps the previous
/// answer (the app-wide never-blank rule). Every collaborator is injected
/// (`AutoRecallTests`), like `FoundTurnOnDeps`.
@MainActor
@Observable
final class AutoRecallModel {
    struct Deps {
        var fetch: @MainActor () async -> AgentWiringResponse?
        var run: @MainActor ([AgentWiringStep], URL, Set<String>) async -> AgentConnectOutcome
        var installRoot: URL

        /// `@MainActor` like `FoundTurnOnDeps.live`: a nested type does not inherit the class's actor.
        @MainActor static var live: Deps {
            Deps(fetch: { try? await APIClient.shared.fetchAgentWiring() },
                 run: { steps, root, binaries in await AgentConnect.run(steps, installRoot: root, binaries: binaries) },
                 installRoot: BackendProcess.installRoot())
        }
    }

    private(set) var wiring: AgentWiringResponse?
    private(set) var loaded = false
    private(set) var working: Set<String> = []
    private(set) var failures: [String: String] = [:]
    private(set) var refused: [String: [String]] = [:]
    private let deps: Deps

    init(deps: Deps) { self.deps = deps }

    /// The live collaborators, for `@State private var model = AutoRecallModel()`.
    /// A convenience init rather than `deps: Deps = .live`: `Deps.live` is
    /// main-actor state, and whether a default argument is evaluated with the
    /// initializer's isolation depends on SE-0411, which Swift 5 language mode
    /// (swift-tools 5.10 here) does not turn on. The init body is isolated.
    convenience init() { self.init(deps: .live) }

    var rows: [AgentWiring] { AutoRecall.rows(wiring) }

    func load() async {
        if let fresh = await deps.fetch() { wiring = fresh }
        loaded = true
    }

    /// Runs the row's one action after the person's click, through the
    /// checkout-pinned allowlist with `CICADA_CAPTURE=off` (`AgentConnect`),
    /// then asks the backend again, so the row shows what is true, not what was hoped.
    func perform(_ agent: AgentWiring) async {
        guard let action = AutoRecall.action(for: agent), !working.contains(agent.id) else { return }
        working.insert(agent.id)
        failures[agent.id] = nil
        refused[agent.id] = nil
        let binaries = Set(wiring?.agents.compactMap(\.binary) ?? [])
        switch await deps.run(action.steps, deps.installRoot, binaries) {
        case .done: break
        case .refused(let lines): refused[agent.id] = lines
        case .failed(let why): failures[agent.id] = why
        }
        await load()
        working.remove(agent.id)
    }
}
