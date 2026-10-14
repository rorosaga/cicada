import Foundation

/// A found item's stable spelling for defaults (`cicada.gettingStarted.<bank>.enabled`).
extension FoundItemID {
    var key: String {
        switch self {
        case .agent(let id): "agent:\(id)"
        case .browser(let id): "browser:\(id)"
        case .app(let id): "app:\(id)"
        case .dropped(let id): "dropped:\(id)"
        }
    }

    init?(key: String) {
        let parts = key.split(separator: ":", maxSplits: 1).map(String.init)
        guard parts.count == 2, !parts[1].isEmpty else { return nil }
        switch parts[0] {
        case "agent": self = .agent(parts[1])
        case "browser": self = .browser(parts[1])
        case "app": self = .app(parts[1])
        case "dropped": self = .dropped(parts[1])
        default: return nil
        }
    }
}

struct GettingStartedRecord: Equatable {
    var enabled: [FoundItemID] = []
    var settled: Set<FoundItemID> = []
    var hidden = false
    var scheduleAsked = false
    /// Owner 2026-10-14 ("Graduate + Needs you first", DR-39) — a graduated card is one line until its viewer opens it;
    /// the choice is remembered per bank. Meaningless before graduation (the card is whole then).
    var expanded = false
}

/// Track I part b (R-IB17) — the Getting started card's memory, per bank, in
/// `UserDefaults` (the `OnboardingState` pattern: a dynamic key cannot be an
/// `@AppStorage`). Absent `enabled` means the Welcome never ran on this bank, so
/// an install onboarded before this track never sees a card it did not ask for.
/// A dropped file is never persisted — its row is this session's result, not a
/// standing connection.
enum GettingStartedState {
    static func key(_ bank: String, _ field: String) -> String { "cicada.gettingStarted.\(bank).\(field)" }

    static func load(bank: String, defaults: UserDefaults = .standard) -> GettingStartedRecord? {
        guard let keys = defaults.stringArray(forKey: key(bank, "enabled")) else { return nil }
        return GettingStartedRecord(
            enabled: keys.compactMap(FoundItemID.init(key:)),
            settled: Set((defaults.stringArray(forKey: key(bank, "settled")) ?? []).compactMap(FoundItemID.init(key:))),
            hidden: defaults.bool(forKey: key(bank, "hidden")),
            scheduleAsked: defaults.bool(forKey: key(bank, "scheduleAsked")),
            expanded: defaults.bool(forKey: key(bank, "expanded")))
    }

    /// Unions, keeps first-seen order, and un-hides: a rerun that turns more on
    /// must show the card again. It never opens a graduated card — only *Show setup checklist* does (`showChecklist`).
    static func record(bank: String, enabled: [FoundItemID], defaults: UserDefaults = .standard) {
        var keys = defaults.stringArray(forKey: key(bank, "enabled")) ?? []
        for id in enabled {
            if case .dropped = id { continue }
            if !keys.contains(id.key) { keys.append(id.key) }
        }
        defaults.set(keys, forKey: key(bank, "enabled"))
        defaults.set(false, forKey: key(bank, "hidden"))
    }

    /// Settings → General's *Show setup checklist* (R-IB17): records the bank and opens the card whole, even once it has
    /// graduated to its one line (owner 2026-10-14: setup stays reachable from Settings). The Welcome's Start and an
    /// Also-on-this-Mac turn-on record through `record` and never open it.
    static func showChecklist(bank: String, defaults: UserDefaults = .standard) {
        record(bank: bank, enabled: [], defaults: defaults)
        setExpanded(true, bank: bank, defaults: defaults)
    }

    /// R-OB8 — an untick in onboarding takes its row off the card rather than leaving it Off. A bank with no record
    /// keeps none: an absent `enabled` key means "no card" (R-IB17), and writing `[]` would raise one.
    static func remove(_ id: FoundItemID, bank: String, defaults: UserDefaults = .standard) {
        guard let keys = defaults.stringArray(forKey: key(bank, "enabled")) else { return }
        defaults.set(keys.filter { $0 != id.key }, forKey: key(bank, "enabled"))
    }

    /// A drop is this session's result, so its ✕ is `SetupRunner.forget`, never a record.
    static func settle(_ id: FoundItemID, bank: String, defaults: UserDefaults = .standard) {
        if case .dropped = id { return }
        var keys = defaults.stringArray(forKey: key(bank, "settled")) ?? []
        if !keys.contains(id.key) { keys.append(id.key) }
        defaults.set(keys, forKey: key(bank, "settled"))
    }

    static func setHidden(_ hidden: Bool, bank: String, defaults: UserDefaults = .standard) {
        defaults.set(hidden, forKey: key(bank, "hidden"))
    }

    static func setExpanded(_ expanded: Bool, bank: String, defaults: UserDefaults = .standard) {
        defaults.set(expanded, forKey: key(bank, "expanded"))
    }

    static func setScheduleAsked(bank: String, defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: key(bank, "scheduleAsked"))
    }
}
