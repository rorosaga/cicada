import Foundation

/// Decision 9 (owner 2026-10-28) — a project's pulse: the last 4 weeks (conversations per week and what was done),
/// what it waits on, and what has gone quiet. Counted, no model, read at the viewer's today. The Swift twin of
/// `api/services/project_pulse.py`: both run ONE table, `api/tests/fixtures/project_pulse.json` (`ProjectPulseTests`),
/// the `ProjectState` precedent — a rule changed on one side only goes red. Nothing here reads a clock.
enum ProjectPulse {
    static let weeks = 4
    /// Waiting on and Gone quiet each name at most this many threads; In motion lists them all.
    static let shown = 2

    struct Input: Decodable, Sendable {
        var conversationDays: [ProjectActivityDay]
        var done: [String]
        var openThreads: [ProjectOpenThread]
        var medianGapDays: Double?
        var momentDays: [String]

        init(conversationDays: [ProjectActivityDay] = [], done: [String] = [], openThreads: [ProjectOpenThread] = [],
             medianGapDays: Double? = nil, momentDays: [String] = []) {
            self.conversationDays = conversationDays
            self.done = done
            self.openThreads = openThreads
            self.medianGapDays = medianGapDays
            self.momentDays = momentDays
        }

        /// `input_from_timeline`: a done happening on its day, a done milestone on its `doneOn`.
        init(_ t: ProjectTimeline) {
            let happenings = t.items.filter { $0.kind == "happening" && $0.state == "done" }.compactMap(\.day)
            let milestones = t.milestones.filter { $0.status == "done" && $0.source != "expectedEnd" }
                .compactMap(\.doneOn)
            self.init(conversationDays: t.conversationDays, done: happenings + milestones, openThreads: t.now.threads,
                      medianGapDays: t.medianGapDays, momentDays: t.momentDays)
        }

        enum CodingKeys: String, CodingKey { case conversationDays, done, openThreads, medianGapDays, momentDays }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            conversationDays = c.lenient(.conversationDays, [])
            done = c.lenient(.done, [])
            openThreads = c.lenient(.openThreads, [])
            medianGapDays = c.lenient(.medianGapDays)
            momentDays = c.lenient(.momentDays, [])
        }
    }

    struct Waiting: Decodable, Equatable, Sendable {
        let claimId: String
        let who: String
        let text: String
        let since: String
    }

    struct Quiet: Decodable, Equatable, Sendable {
        let claimId: String
        let text: String
        let since: String
        let quietDays: Int
    }

    struct Output: Decodable, Equatable, Sendable {
        let weeks: [Int]
        let conversations: Int
        let done: Int
        let quietThreshold: Int
        let waiting: [Waiting]
        let waitingTotal: Int
        let quiet: [Quiet]
        let quietTotal: Int
        let empty: Bool
    }

    static func pulse(_ input: Input, today: ISODay) -> Output {
        let first = today.adding(-(7 * weeks - 1))
        var buckets = Array(repeating: 0, count: weeks)
        for row in input.conversationDays {
            guard let day = ISODay(row.day), day >= first, day <= today else { continue }
            buckets[(day - first) / 7] += row.n
        }
        let done = input.done.compactMap { ISODay($0) }.filter { $0 >= first && $0 <= today }.count
        var gap = input.medianGapDays
        if gap == nil, !input.momentDays.isEmpty { gap = ProjectState.medianGap(input.momentDays) }
        let q = ProjectState.quietThreshold(gap)
        var waiting: [Waiting] = []
        var quiet: [Quiet] = []
        for t in input.openThreads {
            let who = (t.waitingOn ?? "").split(whereSeparator: \.isWhitespace).joined(separator: " ")
            if !who.isEmpty {
                waiting.append(Waiting(claimId: t.claimId, who: who, text: t.text, since: t.since))
                continue
            }
            guard let heard = ISODay(t.lastHeard) ?? ISODay(t.since) else { continue }
            let days = today - heard
            if days >= q { quiet.append(Quiet(claimId: t.claimId, text: t.text, since: t.since, quietDays: days)) }
        }
        waiting.sort { ($0.since, $0.claimId) < ($1.since, $1.claimId) }
        quiet.sort { ($0.quietDays, $1.claimId) > ($1.quietDays, $0.claimId) }
        let conversations = buckets.reduce(0, +)
        return Output(weeks: buckets, conversations: conversations, done: done, quietThreshold: q,
                      waiting: Array(waiting.prefix(shown)), waitingTotal: waiting.count,
                      quiet: Array(quiet.prefix(shown)), quietTotal: quiet.count,
                      empty: conversations == 0 && done == 0 && waiting.isEmpty && quiet.isEmpty)
    }
}
