import Foundation

/// One numbered step of an agent's setup (C8's `AgentSetupSteps`), decided purely so the view is a renderer.
struct AgentStep: Identifiable, Equatable {
    enum Action: Equatable {
        case connectForMe([AgentWiringStep])
        case copy(String)
        case openCursor
        case setUpClaude
        case openFromAnywhere
        case createLink(RemoteApp, enabled: Bool)
        /// R-OB12 — onboarding's own "Remembers automatically · Turn on" step, offered when Connect for me is not
        /// (the agent is already connected): the recall hooks' install argv, shown before the click.
        case autoRecall([AgentWiringStep])
    }

    let id: Int
    let title: String
    let detail: String
    var advanced = false
    var actions: [Action] = []
    /// The prompt, shown before it is copied (R-FA15).
    var snippet: String? = nil
    var isConfirm = false
    var done = false
    var trailing: String? = nil
}

enum AgentSteps {
    static func steps(for entry: AgentCatalogEntry, setups: [String: AgentSetupPrompt], wiring: AgentWiring?,
                      live: AgentLiveRow?, remoteReady: Bool, bundleAutoRecall: Bool = false, now: Date = .now,
                      locale: Locale = .autoupdatingCurrent) -> [AgentStep] {
        var out: [(String, String, Bool, [AgentStep.Action], String?, Bool)] = []   // title, detail, advanced, actions, snippet, done
        switch entry.kind {
        case .prompt(let runsItself):
            let setup = setups[entry.id]
            let text = setup?.kind == "prompt" ? setup?.prompt.flatMap { $0.isEmpty ? nil : $0 } : nil
            // R-OB12 — onboarding turns Remembers automatically on with the connection (G149: recall must not depend
            // on the model calling a tool); Settings passes false, so R-H11 (recall its own click) holds there, and
            // the wire's `connect` list and the Copy prompt are unchanged either way.
            let recall = bundleAutoRecall ? recallSteps(for: wiring) : []
            var actions: [AgentStep.Action] = []
            var bundled = false
            for quick in AgentQuickSetup.actions(catalogId: entry.id, setup: setup, wiring: wiring) {
                if case .connectForMe(let steps) = quick {
                    actions.append(.connectForMe(steps + recall))
                    bundled = !recall.isEmpty
                }
            }
            if let text { actions.append(.copy(text)) }
            var detail = text == nil ? Copy.agentStepPreparing
                : (runsItself ? Copy.agentStepSendRuns(entry.name) : Copy.agentStepSendConfig(entry.name))
            if bundled && text != nil { detail += " " + Copy.agentStepAlsoRecalls }
            out.append((Copy.agentStepSend(entry.name), detail, false, text == nil ? [] : actions, text, false))
            // Connect for me not offered (already connected, or no setup yet): recall gets its own step, so the person
            // can still turn it on here without a trip to Settings → Agents.
            if !recall.isEmpty && !bundled {
                out.append((Copy.autoRecallGroup, Copy.agentStepRecallHow, false, [.autoRecall(recall)], nil, false))
            }
        case .deeplink:
            out.append((Copy.agentStepOpenCursor, setups[entry.id]?.note ?? Copy.agentStepCursorHow, false,
                        [.openCursor], nil, false))
        case .claude:
            out.append((Copy.agentStepClaudeApp, Copy.agentStepClaudeAppHow, false, [.setUpClaude], nil, false))
            out.append((Copy.agentStepClaudeWeb, setups["claude"]?.display.last ?? Copy.agentNeedsReach, true,
                        remoteReady ? [.createLink(.claude, enabled: true)] : [.openFromAnywhere], nil, false))
        case .remote(let app):
            let display = setups[entry.id]?.display ?? []
            out.append((Copy.agentStepReach(entry.name), display.first ?? Copy.agentNeedsReach, true,
                        [.openFromAnywhere], nil, remoteReady))
            out.append((Copy.agentStepLink(entry.name), display.count > 1 ? display[1] : Copy.agentStepLink(entry.name),
                        false, [.createLink(app, enabled: remoteReady)], nil, false))
        }
        var steps = out.enumerated().map { index, s in
            AgentStep(id: index + 1, title: s.0, detail: s.1, advanced: s.2, actions: s.3, snippet: s.4, done: s.5)
        }
        steps.append(AgentStep(id: steps.count + 1, title: Copy.agentStepConfirm,
                               detail: Copy.agentStepConfirmHow(entry.name), isConfirm: true,
                               done: live?.connected == true,
                               trailing: confirmLine(live: live, name: entry.name, now: now, locale: locale)))
        return steps
    }

    /// The recall hooks' install argv when they are off or stale (`AutoRecall`'s one rule) — only Claude Code and
    /// Codex carry them; every other agent answers `n/a` and gets nothing (R-OB12).
    static func recallSteps(for wiring: AgentWiring?) -> [AgentWiringStep] {
        guard let wiring else { return [] }
        switch AutoRecall.state(of: wiring) {
        case .off, .needsUpdate: return wiring.autorecallOn
        case .on, .unreadable, .unavailable: return []
        }
    }

    static func confirmLine(live: AgentLiveRow?, name: String, now: Date, locale: Locale) -> String {
        guard let live, live.connected else { return Copy.agentWaiting(name) }
        guard let raw = live.lastSeenAt, let seen = ISO8601DateFormatter().date(from: raw) else {
            return Copy.agentConnectedPlain
        }
        if now.timeIntervalSince(seen) < 60 { return Copy.agentConnectedNow }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        formatter.locale = locale
        return Copy.agentConnectedAgo(formatter.localizedString(for: seen, relativeTo: now))
    }

    /// D1 / G105: only a harness with a capture hook saves on its own.
    static func honesty(for entry: AgentCatalogEntry) -> String? {
        ModelNames.capturingHarnesses.contains(entry.id) ? nil : Copy.agentNoAutosave
    }

    /// The line under the header: found on this Mac, not yet, or in the cloud.
    static func header(for entry: AgentCatalogEntry, wiring: AgentWiring?) -> String? {
        switch entry.kind {
        case .remote: Copy.agentRunsInCloud
        case .claude, .deeplink: nil
        case .prompt: wiring.map { $0.installed ? Copy.agentFoundOnMac : Copy.agentNotFoundOnMac }
        }
    }
}
