import Foundation

/// G141 §6.2 — a project's derived state on one day, the Swift twin of `api/services/project_state.py` (R-PP4,
/// R-PJB17). Both run ONE table, `api/tests/fixtures/timeline_state.json`, so the app and an agent (`cicada_project`)
/// never disagree about whether a thread is quiet or a milestone overdue. `today` is an argument: nothing here reads a
/// clock, and nothing here is stored (R-PJ7). Keep it line for line with the Python — a rule changed on one side
/// only fails `ProjectStateTests`.
enum ProjectState {
    static let quietFloorDays = 14        // R-PJ13
    static let quietMultiplier = 2.0      // R-PJ13: 2×, not derived-first's 3×
    static let followupFloorDays = 21     // R-PJ13
    static let overdueAskDays = 3         // §9: asked about once 3 days overdue
    static let gapWindowDays = 180        // R-PJB6: ending at the last moment day
    static let quietSectionDays = 90      // §6.2: Quiet ≤ 90 days, Resting beyond
    static let restingStatuses: Set<String> = ["decaying", "archived"]
    static let counted: Set<String> = ["planned", "done", "missed", "passed-no-word"]   // R-PJ11: dropped never counts

    enum Section: String, Decodable, Sendable { case inMotion, quiet, resting }

    /// A payload's absolute fields (`input_from_timeline`), or the fixture's hand-written ones.
    struct Input: Decodable, Sendable {
        var status: String
        var momentDays: [String]
        var lastMomentDay: String?
        var medianGapDays: Double?
        var openThreads: [ProjectOpenThread]
        var milestones: [ProjectMilestone]

        init(status: String = "active", momentDays: [String] = [], lastMomentDay: String? = nil,
             medianGapDays: Double? = nil, openThreads: [ProjectOpenThread] = [], milestones: [ProjectMilestone] = []) {
            self.status = status
            self.momentDays = momentDays
            self.lastMomentDay = lastMomentDay
            self.medianGapDays = medianGapDays
            self.openThreads = openThreads
            self.milestones = milestones
        }

        init(_ row: ProjectRow) {
            self.init(status: row.status, lastMomentDay: row.lastMomentDay, medianGapDays: row.medianGapDays,
                      openThreads: row.openThreads, milestones: row.milestones)
        }

        init(_ t: ProjectTimeline) {
            self.init(status: t.project.status, momentDays: t.momentDays, lastMomentDay: t.lastMomentDay,
                      medianGapDays: t.medianGapDays, openThreads: t.now.threads, milestones: t.milestones)
        }

        enum CodingKeys: String, CodingKey { case status, momentDays, lastMomentDay, medianGapDays, openThreads, milestones }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            status = c.lenient(.status, "active")
            momentDays = c.lenient(.momentDays, [])
            lastMomentDay = c.lenient(.lastMomentDay)
            medianGapDays = c.lenient(.medianGapDays)
            openThreads = c.lenient(.openThreads, [])
            milestones = c.lenient(.milestones, [])
        }
    }

    struct ThreadState: Decodable, Equatable, Sendable {
        let claimId: String
        let quietDays: Int?
        let followupEligible: Bool
    }

    struct MilestoneState: Decodable, Equatable, Sendable {
        let slug: String
        /// `upcoming | overdue | someday | done | missed | dropped | passed-no-word`.
        let state: String
        /// Days to the target (planned), or done − target (done: < 0 early, > 0 late).
        let days: Int?
        let moved: Bool
        let followupEligible: Bool
    }

    struct Output: Decodable, Equatable, Sendable {
        let medianGapDays: Double?
        let quietThreshold: Int
        let section: Section
        let threads: [ThreadState]
        let milestones: [MilestoneState]
        let progress: ProjectProgress
        let next: String?
        let planned: Bool

        func thread(_ claimId: String) -> ThreadState? { threads.first { $0.claimId == claimId } }
        func milestone(_ slug: String) -> MilestoneState? { milestones.first { $0.slug == slug } }

        /// R-PP4 — quiet past Q, the section's own rule (`idle <= q` is in motion).
        func isQuiet(_ claimId: String) -> Bool { (thread(claimId)?.quietDays ?? 0) > quietThreshold }
    }

    /// The median gap between distinct moment days in the 180 days ending at the LAST one — data-anchored, so the
    /// server can serve it without today (R-PJB6).
    static func medianGap(_ days: [String]) -> Double? {
        let ds = Array(Set(days.compactMap { ISODay($0) })).sorted()
        guard let last = ds.last, ds.count >= 2 else { return nil }
        let window = ds.filter { last - $0 <= gapWindowDays }
        let gaps = zip(window, window.dropFirst()).map { $1 - $0 }.sorted()
        guard !gaps.isEmpty else { return nil }
        let mid = gaps.count / 2
        return gaps.count % 2 == 1 ? Double(gaps[mid]) : Double(gaps[mid - 1] + gaps[mid]) / 2
    }

    /// Q = max(14, 2 × median gap), rounded half-up.
    static func quietThreshold(_ gap: Double?) -> Int {
        guard let gap else { return quietFloorDays }
        return max(quietFloorDays, Int((quietMultiplier * gap + 0.5).rounded(.down)))
    }

    static func milestoneState(_ m: ProjectMilestone, today: ISODay) -> MilestoneState {
        let target = ISODay(m.target)
        let doneOn = ISODay(m.doneOn)
        switch m.status {
        case "planned":
            guard let target else {
                return MilestoneState(slug: m.slug, state: "someday", days: nil, moved: m.moved, followupEligible: false)
            }
            return MilestoneState(slug: m.slug, state: target >= today ? "upcoming" : "overdue", days: target - today,
                                  moved: m.moved, followupEligible: today - target >= overdueAskDays)
        case "done":
            let days: Int? = if let target, let doneOn { doneOn - target } else { nil }
            return MilestoneState(slug: m.slug, state: "done", days: days, moved: m.moved, followupEligible: false)
        case "missed", "dropped", "passed-no-word":
            return MilestoneState(slug: m.slug, state: m.status, days: nil, moved: m.moved, followupEligible: false)
        default:
            return MilestoneState(slug: m.slug, state: "someday", days: nil, moved: m.moved, followupEligible: false)
        }
    }

    static func progress(_ milestones: [ProjectMilestone]) -> ProjectProgress {
        let goals = milestones.filter { $0.source != "expectedEnd" && counted.contains($0.status) }
        return ProjectProgress(done: goals.filter { $0.status == "done" }.count, total: goals.count)
    }

    /// The open planned milestone with the earliest target, undated last — upcoming OR overdue, found without today.
    static func nextSlug(_ milestones: [ProjectMilestone]) -> String? {
        milestones
            .filter { $0.status == "planned" && $0.source != "expectedEnd" }
            .sorted { a, b in
                let ka = (a.target == nil ? 1 : 0, a.target ?? "", a.slug)
                let kb = (b.target == nil ? 1 : 0, b.target ?? "", b.slug)
                return ka < kb
            }
            .first?.slug
    }

    static func state(_ input: Input, today: ISODay) -> Output {
        var gap = input.medianGapDays
        if gap == nil, !input.momentDays.isEmpty { gap = medianGap(input.momentDays) }
        let q = quietThreshold(gap)
        let last = ISODay(input.lastMomentDay) ?? input.momentDays.compactMap { ISODay($0) }.max()
        let idle = last.map { today - $0 }
        let section: Section
        if restingStatuses.contains(input.status) || idle == nil || (idle ?? 0) > quietSectionDays {
            section = .resting
        } else if let idle, idle <= q {
            section = .inMotion
        } else {
            section = .quiet
        }
        let threads = input.openThreads.map { t -> ThreadState in
            let heard = ISODay(t.lastHeard) ?? ISODay(t.since)
            let quietDays = heard.map { today - $0 }
            return ThreadState(claimId: t.claimId, quietDays: quietDays,
                               followupEligible: quietDays.map { $0 >= max(followupFloorDays, q) } ?? false)
        }
        return Output(
            medianGapDays: gap, quietThreshold: q, section: section, threads: threads,
            milestones: input.milestones.filter { $0.source != "expectedEnd" }.map { milestoneState($0, today: today) },
            progress: progress(input.milestones), next: nextSlug(input.milestones), planned: !input.milestones.isEmpty)
    }
}
