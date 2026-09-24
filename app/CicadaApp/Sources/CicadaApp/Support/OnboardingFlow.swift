import Foundation

enum OnboardingMode: Equatable { case firstRun, setUpLater, rerun }

enum StartStep: Equatable {
    case saveOwner(String)
    case saveEngine(String)
    case markOnboarded
    case recordGettingStarted([FoundItemID])
    case showHome
    case close
    case turnOn(FoundItemID)
    case createDemoBank
    /// Seam 3 — F-07's Open Cicada offers the tour through the runner, so the spy sees it.
    case offerTour
}

/// Track I T6 (design §4.1.7) — what Start does, in order, as data. Part b's
/// Welcome executes it. The owner save runs alone and first because it is the
/// observer every later write carries (G117 R1); if it fails, nothing after it
/// runs. Every other step's failure belongs to its own row (§4.1.7 item 6).
/// `markOnboarded` always targets the LIVE bank at execution time
/// (`FirstRunSheet.swift:176-187`'s lesson), which is why the plan names no bank.
enum OnboardingFlow {
    static func canStart(name: String) -> Bool { !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    /// Built step by step rather than as one `+` chain of implicit members: the
    /// chain is exactly the shape Swift's type checker gives up on.
    static func plan(name: String, pickedEngine: String?, ticked: [FoundItemID], mode: OnboardingMode) -> [StartStep] {
        var steps: [StartStep] = [.saveOwner(name.trimmingCharacters(in: .whitespacesAndNewlines))]
        if mode == .setUpLater {
            // "Set up later" still saves the name (G117 R1) and turns nothing on.
            steps += [.markOnboarded, .recordGettingStarted([]), .showHome]
            return steps
        }
        if let pickedEngine { steps.append(.saveEngine(pickedEngine)) }
        if mode == .firstRun {
            steps += [.markOnboarded, .recordGettingStarted(ticked), .showHome]
        } else {
            // Run setup again reset the bank's flag before raising the Welcome,
            // so a saved rerun marks it again — as `FirstRunSheet.finish()`
            // always did. Without it an empty bank re-raised the first-run
            // Welcome (demo link, no Esc) at the next launch or graph reload
            // (I-b final review, finding 2). Close with no changes keeps
            // "shows again next launch".
            steps += [.markOnboarded, .recordGettingStarted(ticked), .close]
        }
        steps += ticked.map { StartStep.turnOn($0) }
        return steps
    }

    static func shouldContinue(after step: StartStep, succeeded: Bool) -> Bool {
        if case .saveOwner = step { return succeeded }
        return true
    }

    static let demoSteps: [StartStep] = [.createDemoBank, .markOnboarded]

    // MARK: Round-4 phase B — the paged flow's steps (R-OB2, R-OB15, R-OB19)

    private static func trimmed(_ name: String) -> String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    /// R-OB2 — Get started (F-01): the owner PUT, alone and first. Its failure stops the flow on F-01.
    static func beginSteps(name: String) -> [StartStep] { [.saveOwner(trimmed(name))] }

    /// R-OB15 — Open Cicada (F-07): mark the LIVE bank (a rerun too — I-b final review, finding 2), record the agents
    /// Cicada saw connect (sources were recorded as they started), offer the tour (seam 3), land on Home.
    static func finishSteps(recorded: [FoundItemID]) -> [StartStep] {
        [.markOnboarded, .recordGettingStarted(recorded), .offerTour, .showHome]
    }

    /// Set up later. From Welcome it still saves the name (G117 R1); from a later page the name is saved and what
    /// the person started keeps running. Never the tour — it follows a finished setup, not a skip.
    static func laterSteps(name: String, ownerSaved: Bool) -> [StartStep] {
        (ownerSaved ? [] : [StartStep.saveOwner(trimmed(name))]) + [.markOnboarded, .recordGettingStarted([]), .showHome]
    }

    /// R-OB19 — Close on a rerun (the topbar, Welcome's Close, Esc). The rule `plan(mode: .rerun)` carried (I-b final
    /// review, finding 2): a rerun that changed something marks the live bank again; one that changed nothing does not.
    static func closeSteps(ownerSaved: Bool) -> [StartStep] {
        ownerSaved ? [.markOnboarded, .close] : [.close]
    }

    /// The agents Home's Getting started has a row for, in catalog order. The Claude pill spans the desktop app and
    /// the web, so it maps to no single row; a cloud agent has none.
    static func recordedAgents(connected: Set<String>) -> [FoundItemID] {
        ["claude-code", "codex", "cursor"].filter(connected.contains).map(FoundItemID.agent)
    }
}
