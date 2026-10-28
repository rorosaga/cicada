import Foundation

/// Ruling 48 (1), (2), (8) — the questions where they belong (owner 2026-10-28: the Inbox leaves the rail; its
/// questions live on Home and on each page). Pure and table-tested (`HomeQuestionsTests`); the views only draw it.
///
/// The order is the server's: `GET /inbox` already serves the questions on the pages the person uses most first
/// (`page_use`, vision item 10 — bank facts, never view telemetry), so nothing here re-ranks.
enum HomeQuestions {
    /// Home shows at most this many pages with a question; *All N* opens the rest (never a fold — part 17).
    static let rowLimit = 4

    /// A question Cicada can put to the person in a sentence and answer with a tap or their words — the catch-up's
    /// queue, a page's strip and Home's rows. The rest (an agent's request, the grouped link review, a shown-never-asked
    /// conflict, a merge with no other side named) still live in the full list.
    static func askable(_ item: InboxItem) -> Bool {
        guard !item.isTopCard, !item.informational, item.status == "pending",
              spokenKinds.contains(item.kind) else { return false }
        switch FocusCardVariant.of(item) {
        case .options, .name, .freeText, .legacyDecay: return true
        case .merge: return !(item.mergeTargetHint ?? "").isEmpty
        case .informational, .dismissOnly: return false
        }
    }

    /// The kinds Cicada asks in plain words (`inbox_service._SPOKEN_KINDS`, the catch-up's set). A divergence, a
    /// predicate fold, a removal or a page edit is the person's housekeeping: it waits in the full list.
    static let spokenKinds: Set<InboxKind> = [.conflict, .decay, .clarification, .mergeSuggestion, .followup]

    struct Row: Identifiable, Equatable {
        let id: String
        let entityId: String
        let entityName: String
        let entityType: EntityType?
        let question: String
        let reason: String?
        /// The page's open questions, this one included.
        let onPage: Int
        /// The question's age, as the list's rows say it ("2d"), and the day on hover.
        let age: String
        let ageHelp: String
        let kind: InboxKind
    }

    struct Figures: Equatable {
        /// One row per page, its most-used-first question (`rowLimit` at most).
        var rows: [Row]
        /// Every question in the list ("All 41 questions").
        var total: Int
        /// The catch-up's questions, in order, and how many pages they are about.
        var catchUp: [String]
        var catchUpPages: Int
    }

    static func figures(_ items: [InboxItem], limit: Int = rowLimit, now: Date = .now) -> Figures {
        let asked = items.filter(askable)
        var perPage: [String: Int] = [:]
        for item in asked { perPage[pageKey(item), default: 0] += 1 }
        var seen = Set<String>()
        var rows: [Row] = []
        for item in asked where rows.count < limit {
            let key = pageKey(item)
            guard seen.insert(key).inserted else { continue }
            let age = InboxRowAge.of(item, now: now)
            rows.append(Row(id: item.id, entityId: item.entityId, entityName: item.displayName,
                            entityType: item.entityType.flatMap(EntityType.init(rawValue:)),
                            question: item.askText, reason: item.spokenReason, onPage: perPage[key] ?? 1,
                            age: age.text, ageHelp: age.help, kind: item.kind))
        }
        return Figures(rows: rows, total: items.count, catchUp: asked.map(\.id), catchUpPages: perPage.count)
    }

    /// A page's questions are one group whatever side of a pair they sit on; a question with no page is its own.
    static func pageKey(_ item: InboxItem) -> String {
        item.entityId.isEmpty ? "item:\(item.id)" : "page:\(item.entityId)"
    }

    /// Ruling 48 (1) — a page's own questions strip: the askable questions about `entityId` (either side of a pair),
    /// in the server's order. The strip shows one at a time, "1 of N".
    static func onPage(_ items: [InboxItem], entityId: String) -> [InboxItem] {
        guard !entityId.isEmpty else { return [] }
        return items.filter { askable($0) && ($0.entityId == entityId || $0.mergeTargetHint == entityId) }
    }
}

// MARK: - The catch-up chat (ruling 48 (8))

/// One line of the catch-up chat. Cicada's lines and the person's are the conversation (sent as history and kept as
/// the session's episode); a *noted* line is the app's own receipt for an answer (with Undo) and never leaves the app.
struct CatchupLine: Identifiable, Equatable {
    enum Kind: Equatable {
        /// Cicada speaking; `itemId` when the line asks a question.
        case cicada(String, itemId: String?)
        case you(String)
        /// "Noted: Org Gamma · Undo" — `heldId` is the answer held for its Undo window.
        case noted(String, heldId: String)
        /// A quiet line in Cicada's voice that is not part of the conversation ("I can only take taps right now").
        case aside(String)
    }

    let id = UUID()
    let at: Date
    let kind: Kind

    init(_ kind: Kind, at: Date = .now) {
        self.kind = kind
        self.at = at
    }

    /// What goes to the backend as the conversation: Cicada's words and the person's, nothing else.
    var wire: (who: String, text: String)? {
        switch kind {
        case .cicada(let text, _): ("cicada", text)
        case .you(let text): ("you", text)
        case .noted, .aside: nil
        }
    }

    static func == (a: CatchupLine, b: CatchupLine) -> Bool { a.id == b.id }
}

/// `POST /inbox/catchup/turn`'s answer.
struct CatchupTurnReply: Decodable, Equatable {
    struct Reading: Decodable, Equatable {
        var optionKey: String?
        var answer: String?
        var quote: String
        /// A question about who someone is: offered as a one-tap confirmation, never applied (ruling 41).
        var confirm: Bool
    }

    var reply: String?
    var reading: Reading?
    var move: String
    var nextId: String?
    var engine: Bool
    var why: String?
    var error: Bool?

    enum CodingKeys: String, CodingKey { case reply, reading, move, nextId, engine, why, error }

    init(reply: String?, reading: Reading? = nil, move: String = "stay", nextId: String? = nil, engine: Bool = true,
         why: String? = nil, error: Bool? = nil) {
        self.reply = reply; self.reading = reading; self.move = move; self.nextId = nextId; self.engine = engine
        self.why = why; self.error = error
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        reply = try c.decodeIfPresent(String.self, forKey: .reply)
        reading = (try? c.decodeIfPresent(Reading.self, forKey: .reading)) ?? nil
        move = try c.decodeIfPresent(String.self, forKey: .move) ?? "stay"
        nextId = try c.decodeIfPresent(String.self, forKey: .nextId)
        engine = try c.decodeIfPresent(Bool.self, forKey: .engine) ?? true
        why = try c.decodeIfPresent(String.self, forKey: .why)
        error = try c.decodeIfPresent(Bool.self, forKey: .error)
    }
}

/// The one-tap answers under the question being asked (DR-42), in the inbox's own resolutions — so a tap in the chat
/// is exactly the tap in the list, held for the same Undo window.
struct CatchupChip: Identifiable, Equatable {
    enum Role: Equatable { case answer, notNow, skip }
    let id: String
    let label: String
    let role: Role
    /// nil for Skip: nothing is sent, the question stays in the list.
    let resolution: QuestionResolution?
}

enum CatchupAnswers {
    static func chips(_ item: InboxItem) -> [CatchupChip] {
        var out: [CatchupChip] = []
        switch FocusCardVariant.of(item) {
        case .options:
            out = item.options.prefix(6).map {
                CatchupChip(id: "opt:\($0.key)", label: $0.label, role: .answer,
                            resolution: QuestionResolution(action: "resolve", optionKey: $0.key))
            }
        case .name:
            out = [CatchupChip(id: "decline", label: NameAnswer.declineLabel(item), role: .answer,
                               resolution: NameAnswer.decline)]
        case .merge:
            if let same = merge(item, same: true), let different = merge(item, same: false) {
                out = [CatchupChip(id: "same", label: Copy.Catchup.same, role: .answer, resolution: same),
                       CatchupChip(id: "different", label: Copy.Catchup.different, role: .answer, resolution: different)]
            }
        case .legacyDecay:
            out = [CatchupChip(id: "keep", label: Copy.Inbox.keepActive, role: .answer,
                               resolution: QuestionResolution(action: "keep_active")),
                   CatchupChip(id: "archive", label: Copy.Inbox.archive, role: .answer,
                               resolution: QuestionResolution(action: "archive"))]
        case .freeText, .informational, .dismissOnly:
            break
        }
        if item.allowDefer {
            out.append(CatchupChip(id: "later", label: Copy.Catchup.notNow, role: .notNow,
                                   resolution: QuestionResolution(action: "defer", remindDays: 7)))
        }
        out.append(CatchupChip(id: "skip", label: Copy.Catchup.skip, role: .skip, resolution: nil))
        return out
    }

    /// A same-person (or same-thing) pair answered: Merge keeps the page Sleep named; Different is the remembered
    /// verdict (`MergeReject`). nil when the pair has no other side.
    static func merge(_ item: InboxItem, same: Bool) -> QuestionResolution? {
        guard let hint = item.mergeTargetHint, !hint.isEmpty else { return nil }
        return same ? QuestionResolution(action: "merge", mergeTarget: hint, mergeSurvivor: hint)
            : MergeReject.resolution(existingName: hint)
    }

    /// The person's own words, answered as the list's free-text field would (when the question takes words).
    static func ownWords(_ item: InboxItem, _ text: String) -> QuestionResolution? {
        switch FocusCardVariant.of(item) {
        case .name: return NameAnswer.resolution(name: text)
        case .freeText: return FreeTextSubmit.resolution(for: item, text: text)
        case .options where item.allowOther: return FreeTextSubmit.resolution(for: item, text: text)
        default: return nil
        }
    }

    /// A reading the backend grounded in the person's words, as the inbox's own resolution. nil when it does not fit
    /// the question (an unknown key, a free answer to a closed question).
    static func resolution(_ item: InboxItem, _ reading: CatchupTurnReply.Reading) -> QuestionResolution? {
        if item.kind == .mergeSuggestion {
            switch reading.optionKey {
            case "same": return merge(item, same: true)
            case "different": return merge(item, same: false)
            default: return nil
            }
        }
        if let key = reading.optionKey {
            guard item.options.contains(where: { $0.key == key }) else { return nil }
            return QuestionResolution(action: "resolve", answer: reading.answer, optionKey: key)
        }
        guard let answer = reading.answer else { return nil }
        return ownWords(item, answer)
    }

    /// How the chat says what it noted, in a few words ("Noted: Org Gamma").
    static func noted(_ item: InboxItem, _ resolution: QuestionResolution) -> String {
        if let key = resolution.optionKey, let option = item.options.first(where: { $0.key == key }) {
            if let answer = resolution.answer, !answer.isEmpty { return Copy.Catchup.noted(answer) }
            return Copy.Catchup.noted(option.label)
        }
        switch resolution.action {
        case "merge": return Copy.Catchup.notedSame
        case "reject": return Copy.Catchup.notedDifferent
        case "defer": return Copy.Catchup.notedLater
        case "keep_active": return Copy.Catchup.noted(Copy.Inbox.keepActive)
        case "archive": return Copy.Catchup.noted(Copy.Inbox.archive)
        default: return Copy.Catchup.noted(resolution.answer ?? "")
        }
    }
}
