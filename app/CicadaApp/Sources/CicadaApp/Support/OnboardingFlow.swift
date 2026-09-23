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
            steps += [.recordGettingStarted(ticked), .close]
        }
        steps += ticked.map { StartStep.turnOn($0) }
        return steps
    }

    static func shouldContinue(after step: StartStep, succeeded: Bool) -> Bool {
        if case .saveOwner = step { return succeeded }
        return true
    }

    static let demoSteps: [StartStep] = [.createDemoBank, .markOnboarded]
}
