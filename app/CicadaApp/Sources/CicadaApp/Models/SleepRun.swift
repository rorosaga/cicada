import Foundation

// Sleep page v5 (G163; TODO rulings 13, 15, 16): the wire mirrors of the run's own records —
// the paused run, the reading options, the per-conversation queue, a whole run's detail and the
// reserve line. Every field decodes leniently, the `SleepDrainSSE` pattern: an older backend, or
// one that adds a key, reads as no news and never fails the status it rides on. Ids, counts and
// enums only, plus the pause's plan or engine diagnosis.

/// The reserve line ("Leave room in my plan") and which plan windows it can hold. `enforced` is
/// `true` only for a window the engine reported, `false` for one it should have reported and did
/// not, `nil` before anything could tell — and the app says nothing rather than promise then.
struct SleepReserveWindow: Codable, Equatable, Hashable, Identifiable {
    var window: String
    var enforced: Bool?
    var reason: String?
    var id: String { window }

    init(window: String, enforced: Bool? = nil, reason: String? = nil) {
        self.window = window; self.enforced = enforced; self.reason = reason
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        window = (try? c.decode(String.self, forKey: .window)) ?? ""
        enforced = (try? c.decodeIfPresent(Bool.self, forKey: .enforced)) ?? nil
        reason = (try? c.decodeIfPresent(String.self, forKey: .reason)) ?? nil
    }
    enum CodingKeys: String, CodingKey { case window, enforced, reason }
}

/// The reserve on a run's `drain` block: the percentage the run snapshotted and its windows.
struct SleepReserveInfo: Codable, Equatable, Hashable {
    var pct: Int?
    var windows: [SleepReserveWindow]

    init(pct: Int? = nil, windows: [SleepReserveWindow] = []) { self.pct = pct; self.windows = windows }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        pct = (try? c.decodeIfPresent(Int.self, forKey: .pct)) ?? nil
        windows = ((try? c.decodeIfPresent([SleepReserveWindow].self, forKey: .windows)) ?? nil) ?? []
    }
    enum CodingKeys: String, CodingKey { case pct, windows }
}

/// `GET /sleep/engine`'s `reserve`: the line, its choices, whether it applies to the engine a run
/// you start would use (a plan), and which windows the last run could enforce.
struct SleepReserveStatus: Codable, Equatable, Hashable {
    var pct: Int?
    var choices: [Int]
    var applies: Bool
    var windows: [SleepReserveWindow]

    init(pct: Int? = nil, choices: [Int] = [], applies: Bool = false, windows: [SleepReserveWindow] = []) {
        self.pct = pct; self.choices = choices; self.applies = applies; self.windows = windows
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        pct = (try? c.decodeIfPresent(Int.self, forKey: .pct)) ?? nil
        choices = ((try? c.decodeIfPresent([Int].self, forKey: .choices)) ?? nil) ?? []
        applies = ((try? c.decodeIfPresent(Bool.self, forKey: .applies)) ?? nil) ?? false
        windows = ((try? c.decodeIfPresent([SleepReserveWindow].self, forKey: .windows)) ?? nil) ?? []
    }
    enum CodingKeys: String, CodingKey { case pct, choices, applies, windows }
}

/// A run that stopped with conversations still waiting and can be continued. Paused is a fact
/// about a run, never a state of Sleep: `status` stays `idle`, nothing is held, and only the Sleep
/// page's Continue resumes it (every other door routes there). `reason`:
/// `user | plan_window | plan_weekly | reserve | overage | engine | restart`.
struct SleepPausedRun: Codable, Equatable {
    struct AutoContinue: Codable, Equatable {
        var armed: Bool
        var at: Int?
        var left: Int?
        var blocked: String?

        init(armed: Bool = false, at: Int? = nil, left: Int? = nil, blocked: String? = nil) {
            self.armed = armed; self.at = at; self.left = left; self.blocked = blocked
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            armed = ((try? c.decodeIfPresent(Bool.self, forKey: .armed)) ?? nil) ?? false
            at = (try? c.decodeIfPresent(Int.self, forKey: .at)) ?? nil
            left = (try? c.decodeIfPresent(Int.self, forKey: .left)) ?? nil
            blocked = (try? c.decodeIfPresent(String.self, forKey: .blocked)) ?? nil
        }
        enum CodingKeys: String, CodingKey { case armed, at, left, blocked }
    }

    var runId: String
    var startedBy: String
    var reason: String
    /// `transient | needs_fix`; older backends omit this and retain the fix guidance.
    var engineKind: String?
    /// The pause's diagnosis: a plan's own sentence, or an engine interruption/fix.
    var sentence: String?
    /// The vendor's unix reset time — `nil` when none was given, never guessed.
    var resetsAt: Int?
    var limit: String?
    var filed: Int
    var frozen: Int
    var calls: Int
    var committedBatches: Int
    var pausedAt: String?
    var canContinue: Bool
    var engineLabel: String?
    var autoContinue: AutoContinue?

    init(runId: String = "run", startedBy: String = "user", reason: String, sentence: String? = nil,
         resetsAt: Int? = nil, limit: String? = nil, filed: Int = 0, frozen: Int = 0, calls: Int = 0,
         committedBatches: Int = 0, pausedAt: String? = nil, canContinue: Bool = true,
         engineLabel: String? = nil, autoContinue: AutoContinue? = nil, engineKind: String? = nil) {
        self.runId = runId; self.startedBy = startedBy; self.reason = reason; self.sentence = sentence
        self.engineKind = engineKind
        self.resetsAt = resetsAt; self.limit = limit; self.filed = filed; self.frozen = frozen
        self.calls = calls; self.committedBatches = committedBatches; self.pausedAt = pausedAt
        self.canContinue = canContinue; self.engineLabel = engineLabel; self.autoContinue = autoContinue
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func int(_ key: CodingKeys) -> Int { ((try? c.decodeIfPresent(Int.self, forKey: key)) ?? nil) ?? 0 }
        func str(_ key: CodingKeys) -> String? { (try? c.decodeIfPresent(String.self, forKey: key)) ?? nil }
        runId = str(.runId) ?? ""
        startedBy = str(.startedBy) ?? "user"
        reason = str(.reason) ?? "user"
        engineKind = str(.engineKind)
        sentence = str(.sentence)
        resetsAt = (try? c.decodeIfPresent(Int.self, forKey: .resetsAt)) ?? nil
        limit = str(.limit)
        filed = int(.filed); frozen = int(.frozen); calls = int(.calls); committedBatches = int(.committedBatches)
        pausedAt = str(.pausedAt)
        canContinue = ((try? c.decodeIfPresent(Bool.self, forKey: .canContinue)) ?? nil) ?? true
        engineLabel = str(.engineLabel)
        autoContinue = (try? c.decodeIfPresent(AutoContinue.self, forKey: .autoContinue)) ?? nil
    }

    enum CodingKeys: String, CodingKey {
        case runId, startedBy, reason, engineKind, sentence, resetsAt, limit, filed, frozen, calls, committedBatches
        case pausedAt, canContinue, engineLabel, autoContinue
    }
}

/// The compact paused block on the `sleep` SSE event: enough to know a pause appeared, was armed
/// or was cleared (the page then refetches `GET /sleep/status` for the whole record).
struct SleepPausedSSE: Codable, Equatable {
    var runId: String?
    var reason: String?
    var engineKind: String?
    var autoArmed: Bool
    var autoLeft: Int?

    init(runId: String? = nil, reason: String? = nil, autoArmed: Bool = false, autoLeft: Int? = nil,
         engineKind: String? = nil) {
        self.runId = runId; self.reason = reason; self.autoArmed = autoArmed; self.autoLeft = autoLeft
        self.engineKind = engineKind
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        runId = (try? c.decodeIfPresent(String.self, forKey: .runId)) ?? nil
        reason = (try? c.decodeIfPresent(String.self, forKey: .reason)) ?? nil
        engineKind = (try? c.decodeIfPresent(String.self, forKey: .engineKind)) ?? nil
        autoArmed = ((try? c.decodeIfPresent(Bool.self, forKey: .autoArmed)) ?? nil) ?? false
        autoLeft = (try? c.decodeIfPresent(Int.self, forKey: .autoLeft)) ?? nil
    }
    enum CodingKeys: String, CodingKey { case runId, reason, engineKind, autoArmed, autoLeft }
}

/// `GET/PUT /sleep/run-options` — how often progress is saved, the opt-in continue-after-reset
/// (TODO ruling 15, off) and the reserve (off). A run snapshots them when it starts. Not a Store
/// domain: no ETag, fetched when the page or the sheet needs it.
struct SleepRunOptions: Codable, Equatable {
    var batchSize: Int
    var batchSizeChoices: [Int]
    var continueAfterReset: Bool
    var reservePct: Int?
    var reserveChoices: [Int]

    init(batchSize: Int = 25, batchSizeChoices: [Int] = [10, 25, 50], continueAfterReset: Bool = false,
         reservePct: Int? = nil, reserveChoices: [Int] = [5, 10, 20, 30]) {
        self.batchSize = batchSize; self.batchSizeChoices = batchSizeChoices
        self.continueAfterReset = continueAfterReset; self.reservePct = reservePct; self.reserveChoices = reserveChoices
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        batchSize = ((try? c.decodeIfPresent(Int.self, forKey: .batchSize)) ?? nil) ?? 25
        batchSizeChoices = ((try? c.decodeIfPresent([Int].self, forKey: .batchSizeChoices)) ?? nil) ?? [10, 25, 50]
        continueAfterReset = ((try? c.decodeIfPresent(Bool.self, forKey: .continueAfterReset)) ?? nil) ?? false
        reservePct = (try? c.decodeIfPresent(Int.self, forKey: .reservePct)) ?? nil
        reserveChoices = ((try? c.decodeIfPresent([Int].self, forKey: .reserveChoices)) ?? nil) ?? []
    }
    enum CodingKeys: String, CodingKey { case batchSize, batchSizeChoices, continueAfterReset, reservePct, reserveChoices }
}

/// A `PUT /sleep/run-options` change: only the fields set are sent (`reservePct` as JSON `null`
/// clears it, so "off" is a value of its own here, not an omission).
enum SleepRunOptionsChange: Equatable {
    case batchSize(Int)
    case continueAfterReset(Bool)
    case reservePct(Int?)

    var body: [String: Any] {
        switch self {
        case .batchSize(let n): ["batchSize": n]
        case .continueAfterReset(let on): ["continueAfterReset": on]
        case .reservePct(let pct): ["reservePct": pct.map { $0 as Any } ?? NSNull()]
        }
    }
}

/// `GET /sleep/queue` — one row per conversation still waiting (or filed by the running run), with
/// where it stands. Frontmatter only, bounded; the page refetches it when the run's counts move.
struct SleepQueueItem: Codable, Equatable, Identifiable {
    var id: String
    var timestamp: String
    var origin: String
    var title: String?
    /// `waiting | reading | read | filed | could_not_be_read | parked`.
    var state: String
    /// `empty_answer | timed_out | unparseable | refused | other` for a failure.
    var reason: String?
    var attempts: Int
    var batch: Int?

    init(id: String, timestamp: String = "", origin: String = "unknown", title: String? = nil,
         state: String = "waiting", reason: String? = nil, attempts: Int = 0, batch: Int? = nil) {
        self.id = id; self.timestamp = timestamp; self.origin = origin; self.title = title
        self.state = state; self.reason = reason; self.attempts = attempts; self.batch = batch
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        timestamp = ((try? c.decodeIfPresent(String.self, forKey: .timestamp)) ?? nil) ?? ""
        origin = ((try? c.decodeIfPresent(String.self, forKey: .origin)) ?? nil) ?? "unknown"
        title = (try? c.decodeIfPresent(String.self, forKey: .title)) ?? nil
        state = ((try? c.decodeIfPresent(String.self, forKey: .state)) ?? nil) ?? "waiting"
        reason = (try? c.decodeIfPresent(String.self, forKey: .reason)) ?? nil
        attempts = ((try? c.decodeIfPresent(Int.self, forKey: .attempts)) ?? nil) ?? 0
        batch = (try? c.decodeIfPresent(Int.self, forKey: .batch)) ?? nil
    }
    enum CodingKeys: String, CodingKey { case id, timestamp, origin, title, state, reason, attempts, batch }
}

struct SleepQueueResponse: Codable, Equatable {
    var total: Int
    var offset: Int
    var items: [SleepQueueItem]

    init(total: Int = 0, offset: Int = 0, items: [SleepQueueItem] = []) {
        self.total = total; self.offset = offset; self.items = items
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = ((try? c.decodeIfPresent(Int.self, forKey: .total)) ?? nil) ?? 0
        offset = ((try? c.decodeIfPresent(Int.self, forKey: .offset)) ?? nil) ?? 0
        items = ((try? c.decodeIfPresent([SleepQueueItem].self, forKey: .items)) ?? nil) ?? []
    }
    enum CodingKeys: String, CodingKey { case total, offset, items }
}

/// The owner page's beliefs, sampled at a run's start and after its first batch. `nil` on the wire
/// when the bank has no owner page (the run never creates one).
struct SleepOwnerPageCount: Codable, Equatable {
    var beliefs: Int
    var atStart: Int?
    var afterFirstBatch: Int?

    init(beliefs: Int, atStart: Int? = nil, afterFirstBatch: Int? = nil) {
        self.beliefs = beliefs; self.atStart = atStart; self.afterFirstBatch = afterFirstBatch
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        beliefs = ((try? c.decodeIfPresent(Int.self, forKey: .beliefs)) ?? nil) ?? 0
        atStart = (try? c.decodeIfPresent(Int.self, forKey: .atStart)) ?? nil
        afterFirstBatch = (try? c.decodeIfPresent(Int.self, forKey: .afterFirstBatch)) ?? nil
    }
    enum CodingKeys: String, CodingKey { case beliefs, atStart, afterFirstBatch }
}

/// A history row's run (`SleepHistoryEntry.run`): the run's own numbers from its machine-local
/// summary — never summed from the visible page of history, which one long run can fill.
struct SleepRunRef: Codable, Equatable {
    var id: String
    var batches: Int
    var filed: Int
    var parked: Int
    var frozen: Int
    var pauses: Int
    var readMs: Int
    var pausedMs: Int
    var startedAt: String?
    var finishedAt: String?
    /// `running | paused | finished | failed | ended`.
    var state: String?
    var startedBy: String

    init(id: String, batches: Int = 0, filed: Int = 0, parked: Int = 0, frozen: Int = 0, pauses: Int = 0,
         readMs: Int = 0, pausedMs: Int = 0, startedAt: String? = nil, finishedAt: String? = nil,
         state: String? = nil, startedBy: String = "user") {
        self.id = id; self.batches = batches; self.filed = filed; self.parked = parked; self.frozen = frozen
        self.pauses = pauses; self.readMs = readMs; self.pausedMs = pausedMs; self.startedAt = startedAt
        self.finishedAt = finishedAt; self.state = state; self.startedBy = startedBy
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func int(_ key: CodingKeys) -> Int { ((try? c.decodeIfPresent(Int.self, forKey: key)) ?? nil) ?? 0 }
        id = try c.decode(String.self, forKey: .id)
        batches = int(.batches); filed = int(.filed); parked = int(.parked); frozen = int(.frozen)
        pauses = int(.pauses); readMs = int(.readMs); pausedMs = int(.pausedMs)
        startedAt = (try? c.decodeIfPresent(String.self, forKey: .startedAt)) ?? nil
        finishedAt = (try? c.decodeIfPresent(String.self, forKey: .finishedAt)) ?? nil
        state = (try? c.decodeIfPresent(String.self, forKey: .state)) ?? nil
        startedBy = ((try? c.decodeIfPresent(String.self, forKey: .startedBy)) ?? nil) ?? "user"
    }
    enum CodingKeys: String, CodingKey {
        case id, batches, filed, parked, frozen, pauses, readMs, pausedMs, startedAt, finishedAt, state, startedBy
    }
}

/// `GET /sleep/runs/{id}` — one whole run, engine-free: ids, counts and enums, never a title or a
/// line of text. Unknown is `nil`, never zero. Not a Store domain: the app keeps it in memory
/// (`SleepViewModel.runDetails`) and a bank switch starts a new view model.
struct SleepRunDetail: Codable, Equatable {
    struct Pause: Codable, Equatable {
        var startedAt: String
        var endedAt: String?
        var reason: String
        var resetsAt: Int?

        init(startedAt: String, endedAt: String? = nil, reason: String, resetsAt: Int? = nil) {
            self.startedAt = startedAt; self.endedAt = endedAt; self.reason = reason; self.resetsAt = resetsAt
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            startedAt = ((try? c.decodeIfPresent(String.self, forKey: .startedAt)) ?? nil) ?? ""
            endedAt = (try? c.decodeIfPresent(String.self, forKey: .endedAt)) ?? nil
            reason = ((try? c.decodeIfPresent(String.self, forKey: .reason)) ?? nil) ?? "user"
            resetsAt = (try? c.decodeIfPresent(Int.self, forKey: .resetsAt)) ?? nil
        }
        enum CodingKeys: String, CodingKey { case startedAt, endedAt, reason, resetsAt }
    }

    struct Batch: Codable, Equatable, Identifiable {
        var index: Int
        var commit: String?
        var ts: String?
        var filed: Int
        /// Read but not filed, or never started: failed, or stopped by the reserve line.
        var notFiled: Int
        var tookMs: Int?
        var calls: Int
        var windows: [CycleUsagePlanWindow]
        var id: Int { index }

        init(index: Int, commit: String? = nil, ts: String? = nil, filed: Int = 0, notFiled: Int = 0,
             tookMs: Int? = nil, calls: Int = 0, windows: [CycleUsagePlanWindow] = []) {
            self.index = index; self.commit = commit; self.ts = ts; self.filed = filed; self.notFiled = notFiled
            self.tookMs = tookMs; self.calls = calls; self.windows = windows
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            index = ((try? c.decodeIfPresent(Int.self, forKey: .index)) ?? nil) ?? 0
            commit = (try? c.decodeIfPresent(String.self, forKey: .commit)) ?? nil
            ts = (try? c.decodeIfPresent(String.self, forKey: .ts)) ?? nil
            filed = ((try? c.decodeIfPresent(Int.self, forKey: .filed)) ?? nil) ?? 0
            notFiled = ((try? c.decodeIfPresent(Int.self, forKey: .notFiled)) ?? nil) ?? 0
            tookMs = (try? c.decodeIfPresent(Int.self, forKey: .tookMs)) ?? nil
            calls = ((try? c.decodeIfPresent(Int.self, forKey: .calls)) ?? nil) ?? 0
            windows = ((try? c.decodeIfPresent([CycleUsagePlanWindow].self, forKey: .windows)) ?? nil) ?? []
        }
        enum CodingKeys: String, CodingKey { case index, commit, ts, filed, notFiled, tookMs, calls, windows }
    }

    struct Pages: Codable, Equatable {
        var created: Int
        var ownerTouched: Bool?
        var first: [String]

        init(created: Int = 0, ownerTouched: Bool? = nil, first: [String] = []) {
            self.created = created; self.ownerTouched = ownerTouched; self.first = first
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            created = ((try? c.decodeIfPresent(Int.self, forKey: .created)) ?? nil) ?? 0
            ownerTouched = (try? c.decodeIfPresent(Bool.self, forKey: .ownerTouched)) ?? nil
            first = ((try? c.decodeIfPresent([String].self, forKey: .first)) ?? nil) ?? []
        }
        enum CodingKeys: String, CodingKey { case created, ownerTouched, first }
    }

    var id: String
    var startedBy: String
    var startedAt: String?
    var finishedAt: String?
    var state: String?
    var filed: Int
    var frozen: Int
    var parked: Int
    var skipped: Int
    var calls: Int?
    var readMs: Int?
    var pausedMs: Int?
    var pauses: [Pause]
    var questionsRaised: Int?
    var owner: SleepOwnerPageCount?
    var batches: [Batch]
    var models: [CycleUsageModel]
    var usage: CycleUsage?
    var pages: Pages?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func int(_ key: CodingKeys) -> Int { ((try? c.decodeIfPresent(Int.self, forKey: key)) ?? nil) ?? 0 }
        func opt(_ key: CodingKeys) -> Int? { (try? c.decodeIfPresent(Int.self, forKey: key)) ?? nil }
        id = try c.decode(String.self, forKey: .id)
        startedBy = ((try? c.decodeIfPresent(String.self, forKey: .startedBy)) ?? nil) ?? "user"
        startedAt = (try? c.decodeIfPresent(String.self, forKey: .startedAt)) ?? nil
        finishedAt = (try? c.decodeIfPresent(String.self, forKey: .finishedAt)) ?? nil
        state = (try? c.decodeIfPresent(String.self, forKey: .state)) ?? nil
        filed = int(.filed); frozen = int(.frozen); parked = int(.parked); skipped = int(.skipped)
        calls = opt(.calls); readMs = opt(.readMs); pausedMs = opt(.pausedMs)
        pauses = ((try? c.decodeIfPresent([Pause].self, forKey: .pauses)) ?? nil) ?? []
        questionsRaised = opt(.questionsRaised)
        owner = (try? c.decodeIfPresent(SleepOwnerPageCount.self, forKey: .owner)) ?? nil
        batches = ((try? c.decodeIfPresent([Batch].self, forKey: .batches)) ?? nil) ?? []
        models = ((try? c.decodeIfPresent([CycleUsageModel].self, forKey: .models)) ?? nil) ?? []
        usage = (try? c.decodeIfPresent(CycleUsage.self, forKey: .usage)) ?? nil
        pages = (try? c.decodeIfPresent(Pages.self, forKey: .pages)) ?? nil
    }

    enum CodingKeys: String, CodingKey {
        case id, startedBy, startedAt, finishedAt, state, filed, frozen, parked, skipped, calls, readMs, pausedMs
        case pauses, questionsRaised, owner, batches, models, usage, pages
    }
}
