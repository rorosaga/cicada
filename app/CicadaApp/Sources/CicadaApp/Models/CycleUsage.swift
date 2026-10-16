import Foundation

// 2026-09-28 ruling (TODO ruling 12): the Sleep page's Details and its engine menu show what a
// cycle cost. Wire mirrors of `api/models/schemas.py`'s `CycleUsage*` and `SleepEngineUsage`. Every
// figure is optional: null is unknown, never zero, and an older backend omits the whole block.
// Fractions are 0.0–1.0 on the wire; `UsageFormat.percent(fraction:)` turns one into words.

/// One `(engine, model)` a cycle called. `basis`: `charged` (the provider's bill) | `list` (a
/// list-price estimate, never a charge) | `plan` (a plan call with no tokens or cost to show) |
/// `free` (a local model).
struct CycleUsageModel: Codable, Hashable, Identifiable {
    var model: String? = nil
    var engine: String? = nil
    var calls: Int = 0
    var failedCalls: Int = 0
    var inputTokens: Int = 0
    var outputTokens: Int = 0
    var costUsd: Double? = nil
    var equivCostUsd: Double? = nil
    var basis: String? = nil
    /// Sleep page v5 — the ledger's own stage names this model was called for: data, never copy that says which
    /// model "reads".
    var stages: [String] = []

    var id: String { "\(engine ?? "")|\(model ?? "")" }
}

extension CycleUsageModel {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        model = try? c.decodeIfPresent(String.self, forKey: .model)
        engine = try? c.decodeIfPresent(String.self, forKey: .engine)
        calls = ((try? c.decodeIfPresent(Int.self, forKey: .calls)) ?? nil) ?? 0
        failedCalls = ((try? c.decodeIfPresent(Int.self, forKey: .failedCalls)) ?? nil) ?? 0
        inputTokens = ((try? c.decodeIfPresent(Int.self, forKey: .inputTokens)) ?? nil) ?? 0
        outputTokens = ((try? c.decodeIfPresent(Int.self, forKey: .outputTokens)) ?? nil) ?? 0
        costUsd = (try? c.decodeIfPresent(Double.self, forKey: .costUsd)) ?? nil
        equivCostUsd = (try? c.decodeIfPresent(Double.self, forKey: .equivCostUsd)) ?? nil
        basis = (try? c.decodeIfPresent(String.self, forKey: .basis)) ?? nil
        stages = ((try? c.decodeIfPresent([String].self, forKey: .stages)) ?? nil) ?? []
    }
}

/// One plan window's share used across a cycle. `beforeIsFirstSeen`: Claude reports a window only
/// after a call, so its `before` is the value after the cycle's first call.
struct CycleUsagePlanWindow: Codable, Hashable, Identifiable {
    let window: String
    let before: Double
    let after: Double
    var resetsAt: Int? = nil
    var beforeIsFirstSeen: Bool = false

    var id: String { window }
}

extension CycleUsagePlanWindow {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        window = try c.decode(String.self, forKey: .window)
        before = try c.decode(Double.self, forKey: .before)
        after = try c.decode(Double.self, forKey: .after)
        resetsAt = (try? c.decodeIfPresent(Int.self, forKey: .resetsAt)) ?? nil
        beforeIsFirstSeen = ((try? c.decodeIfPresent(Bool.self, forKey: .beforeIsFirstSeen)) ?? nil) ?? false
    }
}

struct CycleUsagePlan: Codable, Hashable {
    var connection: String? = nil
    var windows: [CycleUsagePlanWindow] = []
}

extension CycleUsagePlan {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        connection = (try? c.decodeIfPresent(String.self, forKey: .connection)) ?? nil
        windows = try c.decodeIfPresent([CycleUsagePlanWindow].self, forKey: .windows) ?? []
    }
}

/// Owner 2026-10-16 — how much of one plan window a run used. `basis`: `measured` (the window's own
/// reading moved; `share` is the move) | `under` (it did not move at the reading's resolution; the share is
/// below `under`, and `share` is nil — never zero) | `estimated` (the run's list-price size against the rate
/// `samples` earlier cycles moved the window by; `under` set too when the reading itself did not move).
struct CycleUsagePlanShare: Codable, Hashable, Identifiable {
    let window: String
    let basis: String
    var share: Double? = nil
    var under: Double? = nil
    var samples: Int? = nil

    var id: String { window }
}

extension CycleUsagePlanShare {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        window = try c.decode(String.self, forKey: .window)
        basis = try c.decode(String.self, forKey: .basis)
        share = (try? c.decodeIfPresent(Double.self, forKey: .share)) ?? nil
        under = (try? c.decodeIfPresent(Double.self, forKey: .under)) ?? nil
        samples = (try? c.decodeIfPresent(Int.self, forKey: .samples)) ?? nil
    }
}

/// `GET /sleep/history/{commit}` → `usage`. Null on the wire means "not recorded"; a cycle with a
/// `sleep_run` and no calls is `recorded: true` with no models ("No model calls").
struct CycleUsage: Codable, Hashable {
    var recorded: Bool = true
    var engine: String? = nil
    var connection: String? = nil
    var models: [CycleUsageModel] = []
    var totalCostUsd: Double? = nil
    var totalEquivUsd: Double? = nil
    /// `charged | list | plan | free | mixed`; null when no model was called.
    var basis: String? = nil
    var plan: CycleUsagePlan? = nil
    /// A plan run's share of each window, weekly first; empty for a metered run, an older backend, or unknown.
    var planShare: [CycleUsagePlanShare] = []
}

extension CycleUsage {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // A malformed structural field throws: the whole block is dropped and reads as not recorded,
        // never as a recorded cycle that made no calls.
        recorded = try c.decodeIfPresent(Bool.self, forKey: .recorded) ?? true
        engine = (try? c.decodeIfPresent(String.self, forKey: .engine)) ?? nil
        connection = (try? c.decodeIfPresent(String.self, forKey: .connection)) ?? nil
        models = try c.decodeIfPresent([CycleUsageModel].self, forKey: .models) ?? []
        totalCostUsd = (try? c.decodeIfPresent(Double.self, forKey: .totalCostUsd)) ?? nil
        totalEquivUsd = (try? c.decodeIfPresent(Double.self, forKey: .totalEquivUsd)) ?? nil
        basis = (try? c.decodeIfPresent(String.self, forKey: .basis)) ?? nil
        plan = try c.decodeIfPresent(CycleUsagePlan.self, forKey: .plan)
        planShare = ((try? c.decodeIfPresent([CycleUsagePlanShare].self, forKey: .planShare)) ?? nil) ?? []
    }
}

struct CycleUsageSummaryPlan: Codable, Hashable {
    let window: String
    let before: Double
    let after: Double
}

/// `SleepHistoryEntry.usageSummary` — flat and small; the app words it, the server never sends a
/// sentence.
struct CycleUsageSummary: Codable, Hashable {
    var basis: String? = nil
    var costUsd: Double? = nil
    var equivCostUsd: Double? = nil
    var engine: String? = nil
    var connection: String? = nil
    var plan: CycleUsageSummaryPlan? = nil
    var planShare: [CycleUsagePlanShare] = []
}

extension CycleUsageSummary {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        basis = (try? c.decodeIfPresent(String.self, forKey: .basis)) ?? nil
        costUsd = (try? c.decodeIfPresent(Double.self, forKey: .costUsd)) ?? nil
        equivCostUsd = (try? c.decodeIfPresent(Double.self, forKey: .equivCostUsd)) ?? nil
        engine = (try? c.decodeIfPresent(String.self, forKey: .engine)) ?? nil
        connection = (try? c.decodeIfPresent(String.self, forKey: .connection)) ?? nil
        plan = try c.decodeIfPresent(CycleUsageSummaryPlan.self, forKey: .plan)
        planShare = ((try? c.decodeIfPresent([CycleUsagePlanShare].self, forKey: .planShare)) ?? nil) ?? []
    }
}

/// A candidate's caption source on `GET /sleep/engine`. `kind`: `plan-window` (a window's used
/// fraction, `resetsAt` unix seconds, `asOf` the ISO time of the reading, `source` =
/// `codex-snapshot` | `last-cycle`) or `list-price` (a model's list price per million tokens and
/// the last cycle's charged cost).
struct SleepEngineUsage: Codable, Hashable {
    let kind: String
    var window: String? = nil
    var usedFraction: Double? = nil
    var resetsAt: Int? = nil
    var asOf: String? = nil
    var source: String? = nil
    var model: String? = nil
    var inputPerMillionUsd: Double? = nil
    var outputPerMillionUsd: Double? = nil
    var lastCycleCostUsd: Double? = nil
    /// A plan card: its newest run's share of each window, and that run's list-price equivalent (the secondary
    /// "would have cost" figure, never a charge). Nil from an older backend.
    var lastRunShare: [CycleUsagePlanShare]? = nil
    var lastRunEquivUsd: Double? = nil
}

/// One model's list price per million tokens, for the model picker.
struct SleepEngineModelPrice: Codable, Hashable {
    var inputPerMillionUsd: Double? = nil
    var outputPerMillionUsd: Double? = nil
}
