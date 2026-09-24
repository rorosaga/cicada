import Foundation

/// R-PP15 — one piece of a happening's sentence: a word, the owner, or a page the sentence names.
struct StoryToken: Identifiable, Equatable {
    enum Kind: Equatable { case word, owner, page }

    let id: Int
    let kind: Kind
    let text: String
    /// Punctuation right after a chip rides with it, so "." never wraps onto a line of its own (the mock).
    let trailing: String
    /// Whether a space came before it in the sentence; `SentenceFlowLayout` draws the gap.
    let spaceBefore: Bool
    let participant: ProjectParticipant?
}

/// G141 PJ-5 — the story's words, pure: a sentence cut into words and chips, Lately's groups, a row's status word, date
/// and how it was dated, a thread's line, the Now section's empty and pending lines. Every relative word comes from
/// `RelativeDay` (DR-58); nothing here is stored.
enum ProjectStory {
    /// R-PP15 / R-PJ15 — each participant's `surface` (else its name) links at its first occurrence no other link took.
    /// A page the sentence never names comes back in `extra`, to follow the sentence as a chip; an unlinked name (no
    /// page) stays words — there is nothing to open; the owner is found by its surface only (never by the name, which
    /// a third-person sentence does not use).
    static func tokens(_ text: String, participants: [ProjectParticipant])
        -> (tokens: [StoryToken], extra: [ProjectParticipant]) {
        var links: [(range: Range<String.Index>, participant: ProjectParticipant)] = []
        var extra: [ProjectParticipant] = []
        for p in participants {
            let surface = p.surface.flatMap { $0.isEmpty ? nil : $0 }
            let needle = surface ?? (p.isOwner ? nil : p.name)
            var found: Range<String.Index>?
            if let needle, !needle.isEmpty {
                var from = text.startIndex
                while from < text.endIndex, let r = text.range(of: needle, range: from..<text.endIndex) {
                    if !links.contains(where: { $0.range.overlaps(r) }) {
                        found = r
                        break
                    }
                    from = r.upperBound
                }
            }
            if let found, p.id != nil || p.isOwner {
                links.append((found, p))
            } else if found == nil, p.id != nil, !p.isOwner {
                extra.append(p)
            }
        }
        links.sort { $0.range.lowerBound < $1.range.lowerBound }

        var out: [StoryToken] = []
        var cursor = text.startIndex
        func spaced(_ i: String.Index) -> Bool { i > text.startIndex && text[text.index(before: i)].isWhitespace }
        func words(upTo end: String.Index) {
            var i = cursor
            while i < end {
                while i < end, text[i].isWhitespace { i = text.index(after: i) }
                guard i < end else { break }
                var j = i
                while j < end, !text[j].isWhitespace { j = text.index(after: j) }
                out.append(StoryToken(id: out.count, kind: .word, text: String(text[i..<j]), trailing: "",
                                      spaceBefore: spaced(i), participant: nil))
                i = j
            }
            cursor = end
        }
        for link in links {
            words(upTo: link.range.lowerBound)
            var end = link.range.upperBound
            while end < text.endIndex, ".,;:!?".contains(text[end]) { end = text.index(after: end) }
            out.append(StoryToken(id: out.count, kind: link.participant.isOwner ? .owner : .page,
                                  text: String(text[link.range]), trailing: String(text[link.range.upperBound..<end]),
                                  spaceBefore: spaced(link.range.lowerBound), participant: link.participant))
            cursor = end
        }
        words(upTo: text.endIndex)
        return (out, extra)
    }

    struct Group: Identifiable, Equatable {
        let group: RelativeDay.Group
        let items: [ProjectItem]
        var id: RelativeDay.Group { group }
    }

    /// R-PP14 — the story in the server's order (newest first), bucketed by the viewer's day; an undated history
    /// bullet reads under Earlier; `created` is the foot line, never a row.
    static func groups(_ items: [ProjectItem], today: ISODay) -> [Group] {
        var buckets: [RelativeDay.Group: [ProjectItem]] = [:]
        for item in items where item.kind != "created" {
            let group = ISODay(item.day).map { RelativeDay.group($0, today: today) } ?? .earlier
            buckets[group, default: []].append(item)
        }
        return RelativeDay.Group.allCases.compactMap { g in buckets[g].map { Group(group: g, items: $0) } }
    }

    static func createdLine(_ items: [ProjectItem], today: ISODay, locale: Locale = .autoupdatingCurrent) -> String? {
        guard let day = items.first(where: { $0.kind == "created" }).flatMap({ ISODay($0.day) }) else { return nil }
        return Copy.Projects.startedTracking(RelativeDay.absolute(day, today: today, locale: locale))
    }

    enum Glyph: Equatable { case done, ongoing, said, history, stopped }

    static func glyph(_ item: ProjectItem) -> Glyph {
        switch item.kind {
        case "history": .history
        case "moment": .said
        default:
            switch item.status {
            case "ongoing": .ongoing
            case "dropped": .stopped
            default: .done
            }
        }
    }

    /// The row's status word (the mock): a happening's state as of its day, a quiet thread's days, a moment's kind.
    static func status(_ item: ProjectItem, state: ProjectState.Output, today: ISODay,
                       locale: Locale = .autoupdatingCurrent) -> String {
        switch item.kind {
        case "history":
            return Copy.Projects.statusHistory
        case "moment":
            switch item.state {
            case "changed": return Copy.Projects.statusChanged
            case "ended": return Copy.Projects.statusEnded
            default: return Copy.Projects.statusSaid
            }
        default:
            switch item.status {
            case "ongoing":
                if let to = ISODay(item.claim?.validTo) {
                    return Copy.Projects.statusOngoingUntil(RelativeDay.absolute(to, today: today, locale: locale))
                }
                if state.isQuiet(item.id) { return Copy.Projects.statusQuiet(state.thread(item.id)?.quietDays ?? 0) }
                return Copy.Projects.statusOngoing
            case "dropped":
                return Copy.Projects.statusStopped
            default:
                return Copy.Projects.statusDone
            }
        }
    }

    /// R-PJ6 / spec §7 — the date is provenance too: how this one was decided, in words.
    static func basis(_ basis: String?) -> String? {
        switch basis {
        case "stated": Copy.Projects.basisStated
        case "turn": Copy.Projects.basisTurn
        case "episode": Copy.Projects.basisEpisode
        case "person": Copy.Projects.basisPerson
        case "written": Copy.Projects.basisWritten
        case "day": Copy.Projects.basisDay
        default: nil
        }
    }

    /// R-PP14 / DR-58 — a row's date is absolute; the full date is its `.help`.
    static func rowDate(_ item: ProjectItem, today: ISODay, locale: Locale = .autoupdatingCurrent) -> (text: String, help: String) {
        guard let day = ISODay(item.day) else { return ("", "") }
        return (RelativeDay.absolute(day, today: today, locale: locale), RelativeDay.full(day, locale: locale))
    }

    /// A moment's facts beyond its lead, and the member it came through (§11.3: "+N facts", "via X").
    static func factsLine(_ item: ProjectItem, names: EntityNames) -> String? {
        let more = item.moreFacts > 0 ? Copy.Projects.moreFacts(item.moreFacts) : ""
        let via = item.via.map { Copy.Projects.via(names.display($0)) } ?? ""
        let line = Eyebrow.text(more, via)
        return line.isEmpty ? nil : line
    }

    /// Now: the threads heard from first (newest first), then the quiet ones.
    static func nowThreads(_ t: ProjectTimeline, state: ProjectState.Output) -> [ProjectOpenThread] {
        t.now.threads.sorted { a, b in
            let qa = state.isQuiet(a.claimId)
            let qb = state.isQuiet(b.claimId)
            return qa != qb ? !qa : a.since > b.since
        }
    }

    static func threadMeta(_ t: ProjectOpenThread, state: ProjectState.Output, today: ISODay,
                           locale: Locale = .autoupdatingCurrent) -> String {
        guard let since = ISODay(t.since) else { return "" }
        let sinceWords = RelativeDay.absolute(since, today: today, locale: locale)
        if state.isQuiet(t.claimId) {
            return Copy.Projects.threadQuiet(since: sinceWords, days: state.thread(t.claimId)?.quietDays ?? 0)
        }
        if since == today { return Copy.Projects.threadStartedToday }
        let heard = ISODay(t.lastHeard) ?? since
        return heard == since ? Copy.Projects.threadSince(sinceWords)
            : Copy.Projects.threadHeard(since: sinceWords, heard: RelativeDay.distance(heard, today: today))
    }

    static func nowEmpty(_ t: ProjectTimeline, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let last = ISODay(t.lastMomentDay)
        return Copy.Projects.nothingInMotion(lastHeard: last.map { RelativeDay.absolute($0, today: today, locale: locale) },
                                             distance: last.map { RelativeDay.distance($0, today: today) })
    }

    /// §6.1 layer 7 — "me today" is honest about what the story does not hold yet.
    static func pendingLine(_ p: ProjectPending, today: ISODay) -> String? {
        guard p.unconsolidated > 0 else { return nil }
        return Copy.Projects.waiting(p.unconsolidated, newest: ISODay(p.newestDay).map { RelativeDay.distance($0, today: today) })
    }

    /// R-PP18 — each open follow-up, by the thread claim it asks about.
    static func followups(_ inbox: [InboxItem]) -> [String: InboxItem] {
        var out: [String: InboxItem] = [:]
        for item in inbox where item.kind == .followup {
            if let claim = item.claimId, out[claim] == nil { out[claim] = item }
        }
        return out
    }
}

/// R-PP22 — the Plan's rows and words (R-PJ4, R-PJ11).
enum ProjectPlan {
    struct Row: Identifiable, Equatable {
        let milestone: ProjectMilestone
        let state: ProjectState.MilestoneState
        var id: String { milestone.slug }
    }

    enum Diamond: Equatable { case filled, hollow, slashed }

    /// By target (a done one by its target too, so it keeps its place in the plan), undated last.
    static func rows(_ milestones: [ProjectMilestone], today: ISODay) -> [Row] {
        milestones
            .map { Row(milestone: $0, state: ProjectState.milestoneState($0, today: today)) }
            .sorted { a, b in
                (a.milestone.target ?? a.milestone.doneOn ?? "~", a.milestone.slug)
                    < (b.milestone.target ?? b.milestone.doneOn ?? "~", b.milestone.slug)
            }
    }

    static func meta(_ row: Row, onName: String?, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let m = row.milestone
        func day(_ d: ISODay) -> String { RelativeDay.absolute(d, today: today, locale: locale) }
        let target = ISODay(m.target)
        var words: String
        switch row.state.state {
        case "done":
            let head = Copy.Projects.doneOn(day(ISODay(m.doneOn) ?? today))
            if let days = row.state.days {
                let tail = days < 0 ? Copy.Projects.early(-days) : (days > 0 ? Copy.Projects.late(days) : Copy.Projects.onItsDate)
                words = "\(head) — \(tail)"
            } else {
                words = head
            }
        case "upcoming":
            words = target.map { Copy.Projects.upcoming(day($0), RelativeDay.distance($0, today: today)) } ?? Copy.Projects.someday
        case "overdue":
            words = target.map { Copy.Projects.overdueSince(day($0)) } ?? Copy.Projects.someday
        case "passed-no-word":
            words = target.map { Copy.Projects.passedNoWord(day($0)) } ?? Copy.Projects.someday
        case "missed":
            words = Copy.Projects.missed(target.map(day))
        case "dropped":
            words = Copy.Projects.dropped
        default:
            words = Copy.Projects.someday
        }
        if let onName, !onName.isEmpty, onName != m.name { words = Eyebrow.text(words, Copy.Projects.onProject(onName)) }
        return words
    }

    /// A moved milestone's history, oldest first (R-PJ4: the chain IS the history): "Sep 9 — planned Jul 22", then
    /// "Oct 1 — moved by you on Sep 10". Empty when it never moved.
    static func chain(_ m: ProjectMilestone, today: ISODay, locale: Locale = .autoupdatingCurrent) -> [String] {
        guard m.moved else { return [] }
        let ordered = Array(m.chain.reversed())
        return ordered.enumerated().compactMap { i, c in
            guard let target = ISODay(c.target) ?? (c.predicate == "due" ? ISODay(c.object) : nil),
                  let on = ISODay(c.validFrom) else { return nil }
            let t = RelativeDay.absolute(target, today: today, locale: locale)
            let o = RelativeDay.absolute(on, today: today, locale: locale)
            if i == 0 { return Copy.Projects.plannedOn(target: t, on: o) }
            return c.origin == "companion_app" ? Copy.Projects.movedByYou(target: t, on: o) : Copy.Projects.movedOnDay(target: t, on: o)
        }
    }

    /// Mark done answers a planned, overdue or undated milestone, and a closed `due` nobody said anything about.
    static func canMarkDone(_ row: Row) -> Bool {
        !isPending(row.milestone) && row.milestone.source != "expectedEnd"
            && ["upcoming", "overdue", "someday", "passed-no-word"].contains(row.state.state)
    }

    static func diamond(_ row: Row) -> Diamond {
        switch row.state.state {
        case "done": .filled
        case "passed-no-word", "missed": .slashed
        default: .hollow
        }
    }

    /// An optimistic row (Task 5) has no slot on the server yet: nothing may act on it until the answer lands.
    static func isPending(_ m: ProjectMilestone) -> Bool { m.slug.hasPrefix("pending-") }
}

/// R-PP13 / §6.4 — Around this project, in the brief's words.
enum ProjectAround {
    /// The brief names two groups differently from the server; the rest read as served.
    static func label(_ server: String) -> String {
        switch server {
        case "Documents": Copy.Projects.documentsAndLinks
        case "Sub-projects": Copy.Projects.partsOfThisProject
        default: server
        }
    }

    static func last(_ m: ProjectMember, today: ISODay, locale: Locale = .autoupdatingCurrent) -> (text: String, help: String)? {
        ISODay(m.lastSeen).map {
            (Copy.Projects.lastSeen(RelativeDay.absolute($0, today: today, locale: locale)),
             Copy.Projects.lastMentioned(RelativeDay.full($0, locale: locale)))
        }
    }

    /// The brief: "a tool row expands to its spec claims" — tools and the directories grouped with them.
    static func expands(_ m: ProjectMember) -> Bool {
        !m.pending && m.memberId != nil && (m.type == .tool || m.type == .directory)
    }

    /// Its open `spec` claims; with none, up to three open literal claims (§6.4's "one fact" rule, unfolded).
    static func specs(_ claims: [Claim]) -> [Claim] {
        let open = claims.filter(\.isValid)
        let spec = open.filter { $0.predicate == "spec" }
        return spec.isEmpty ? Array(open.filter { $0.objectKind == "literal" }.prefix(3)) : spec
    }

    /// R-PP17 — a part of this project opens as the project, not as a card.
    static func opensProject(_ group: ProjectMemberGroup) -> Bool { group.label == "Sub-projects" }
}
