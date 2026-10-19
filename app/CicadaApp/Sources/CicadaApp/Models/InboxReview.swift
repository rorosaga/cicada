import Foundation

/// The quick review (owner 2026-10-19): one kind at a time — "Fading pages · 49" — then one card at a time with the
/// same answers in the same place and one key each. The pure half lives here so the queue, the answers, the keys,
/// undo and progress are testable without a view. Nothing here writes: an answer is the Inbox's own (`Store.hold`,
/// `POST /inbox/{id}/resolve` after the Undo window — the same resolvers, provenance the person's), and a skip writes
/// nothing at all. There is no "accept all": one decision per card.

/// The kinds the review goes through, in the order the entry points list them.
enum ReviewKind: String, CaseIterable, Identifiable {
    case decay, fold, conflict, question

    var id: String { rawValue }

    var inboxKind: InboxKind {
        switch self {
        case .decay: .decay
        case .fold: .normalization
        case .conflict: .conflict
        case .question: .clarification
        }
    }

    static func of(_ kind: InboxKind) -> ReviewKind? { allCases.first { $0.inboxKind == kind } }

    /// The words a person uses for the kind: "Fading pages", "Folds", "Conflicts", "Questions".
    var title: String { Copy.Inbox.Review.kindTitle(self) }
}

/// One answer on a review card: the key that gives it (1…9, also its place on the card), its words, and the
/// resolution the Inbox's own card would have sent for the same choice.
struct ReviewAnswer: Equatable, Identifiable {
    let number: Int
    let label: String
    var detail: String? = nil
    var recommended = false
    let resolution: QuestionResolution

    var id: Int { number }
}

/// What a card offers, by kind. `answers` is nil for an item the review cannot put in its fixed places (a legacy
/// shape, an informational conflict, a fold whose keys are not the two the resolver knows) — that item stays in the
/// Inbox, where its full card answers it.
enum ReviewCard {
    static let keepKey = "keep", archiveKey = "archive"
    static let sameKey = "0", differentKey = "1"
    static let bothKey = "both", neitherKey = "neither"

    static func answers(_ item: InboxItem, locale: Locale = .autoupdatingCurrent,
                        timeZone: TimeZone = .autoupdatingCurrent) -> [ReviewAnswer]? {
        switch item.kind {
        case .decay: return decay(item)
        case .normalization: return fold(item)
        case .conflict: return conflict(item, locale: locale, timeZone: timeZone)
        case .clarification: return clarification(item)
        default: return nil
        }
    }

    static func reviewable(_ item: InboxItem) -> Bool {
        guard ReviewKind.of(item.kind) != nil, let answers = answers(item) else { return false }
        return !answers.isEmpty || takesText(item)
    }

    /// A clarification is answered in words: a name for a person Cicada knows only by a relation, else what is
    /// actually true.
    static func takesText(_ item: InboxItem) -> Bool {
        guard item.kind == .clarification else { return false }
        return item.asks == NameAnswer.asks || item.allowOther || item.requiredInput == .freetext || item.question != nil
    }

    /// The resolution a typed answer sends — `NameAnswer` for a name, else `FreeTextSubmit`, as the Inbox's card.
    static func typed(_ item: InboxItem, text: String) -> QuestionResolution? {
        item.asks == NameAnswer.asks ? NameAnswer.resolution(name: text) : FreeTextSubmit.resolution(for: item, text: text)
    }

    // MARK: Per kind

    /// Keep / Let fade — in that order on every card, whatever order the server sent.
    private static func decay(_ item: InboxItem) -> [ReviewAnswer]? {
        guard let keep = item.options.first(where: { $0.key == keepKey }),
              let archive = item.options.first(where: { $0.key == archiveKey }) else { return nil }
        return [
            ReviewAnswer(number: 1, label: Copy.Inbox.Review.keep, detail: Copy.Inbox.Review.keepDetail,
                         recommended: keep.recommended, resolution: pick(keepKey)),
            ReviewAnswer(number: 2, label: Copy.Inbox.Review.letFade, detail: Copy.Inbox.Review.letFadeDetail,
                         recommended: archive.recommended, resolution: pick(archiveKey)),
        ]
    }

    /// Same / Different: "Correct fold" is `0`, "Wrong fold — keep separate" is `1` (`_resolve_normalization`).
    private static func fold(_ item: InboxItem) -> [ReviewAnswer]? {
        guard let same = item.options.first(where: { $0.key == sameKey }),
              let different = item.options.first(where: { $0.key == differentKey }) else { return nil }
        let pair = item.fold.map { ($0.raw, $0.canonical) }
        return [
            ReviewAnswer(number: 1, label: Copy.Inbox.Review.same,
                         detail: pair.map { Copy.Inbox.Review.sameDetail($0.0, $0.1) } ?? same.label,
                         recommended: same.recommended, resolution: pick(sameKey)),
            ReviewAnswer(number: 2, label: Copy.Inbox.Review.different,
                         detail: pair.map { Copy.Inbox.Review.differentDetail($0.0) } ?? different.label,
                         recommended: different.recommended, resolution: pick(differentKey)),
        ]
    }

    /// A / B (/ C …) / Both: every side the question holds, in the server's order, each with the day it was said;
    /// "Both" last. A conflict on a multi-valued predicate is shown, never asked (G98) — not reviewable.
    private static func conflict(_ item: InboxItem, locale: Locale, timeZone: TimeZone) -> [ReviewAnswer]? {
        guard !item.informational else { return nil }
        let sides = item.options.filter { $0.key != bothKey && $0.key != neitherKey }
        guard sides.count >= 2, sides.count <= 8 else { return nil }
        var out = sides.enumerated().map { i, side in
            ReviewAnswer(number: i + 1, label: side.label,
                         detail: Copy.Inbox.Review.said(day: day(side.observedAt ?? side.lastReferenced,
                                                                 locale: locale, timeZone: timeZone),
                                                        age: side.ageDays.map { InboxAge.phrase(days: $0) }),
                         recommended: side.recommended, resolution: pick(side.key))
        }
        if let both = item.options.first(where: { $0.key == bothKey }) {
            out.append(ReviewAnswer(number: out.count + 1, label: Copy.Inbox.Review.both, detail: both.label,
                                    resolution: pick(bothKey)))
        }
        return out
    }

    /// A typed answer, plus the item's own options when it has any ("I'd rather not say" on a name question).
    private static func clarification(_ item: InboxItem) -> [ReviewAnswer]? {
        guard !item.informational else { return nil }
        let options = Array(item.options.prefix(9))
        return options.enumerated().map { i, option in
            ReviewAnswer(number: i + 1, label: option.label, detail: option.description,
                         recommended: option.recommended, resolution: pick(option.key))
        }
    }

    private static func pick(_ key: String) -> QuestionResolution { QuestionResolution(action: "resolve", optionKey: key) }

    /// "3 Mar 2026" for an ISO day or stamp; nil when there is none.
    static func day(_ iso: String?, locale: Locale = .autoupdatingCurrent,
                    timeZone: TimeZone = .autoupdatingCurrent) -> String? {
        guard let iso, !iso.isEmpty else { return nil }
        return ReaderTime.day(timestamp: iso, episode: "", locale: locale, timeZone: timeZone)
    }
}

/// One review: the kind's questions frozen at its start (like a drain, nothing new joins it), and what the person
/// did with each. The card on screen is the first one not yet decided, so Undo puts a card back exactly where it was.
struct InboxReview: Equatable {
    enum Step: Equatable {
        case answered(String), skipped(String)
        var id: String {
            switch self {
            case .answered(let id), .skipped(let id): id
            }
        }
    }

    let kind: ReviewKind
    private(set) var queue: [String]
    private(set) var history: [Step] = []

    /// The kind's reviewable questions in the Inbox's one order (priority, then newest — `InboxColumns.precedes`).
    init(kind: ReviewKind, items: [InboxItem]) {
        self.kind = kind
        queue = InboxColumns.visible(items, filter: kind.inboxKind).filter(ReviewCard.reviewable).map(\.id)
    }

    private var decided: Set<String> { Set(history.map(\.id)) }

    var currentId: String? {
        let decided = decided
        return queue.first { !decided.contains($0) }
    }

    var total: Int { queue.count }
    var answered: Int { history.filter { if case .answered = $0 { true } else { false } }.count }
    var skipped: Int { history.count - answered }
    var left: Int { total - history.count }
    var isFinished: Bool { currentId == nil }
    /// "3 of 49": the card on screen, counted from 1; the total once every card is decided.
    var position: Int { min(history.count + 1, total) }

    /// Record what happened to the card on screen. Anything else is ignored (the card moved under the caller).
    @discardableResult
    mutating func record(_ step: Step) -> Bool {
        guard step.id == currentId else { return false }
        history.append(step)
        return true
    }

    /// The step Undo would take back: a skip always (it wrote nothing), an answer only while the Store still holds
    /// it unsent (`heldId`, the Inbox's one Undo window — R-DI2). An answer already sent has nothing to undo.
    func undoable(heldId: String?) -> Step? {
        guard let last = history.last else { return nil }
        switch last {
        case .skipped: return last
        case .answered(let id): return id == heldId ? last : nil
        }
    }

    /// Take the last step back; its card is on screen again. The caller drops the held answer first.
    @discardableResult
    mutating func undo(heldId: String?) -> Step? {
        guard let step = undoable(heldId: heldId) else { return nil }
        history.removeLast()
        return step
    }

    /// The Inbox moved. `visible` is what the Inbox shows now (a held or sending answer is not in it):
    /// - a card not yet decided that is gone (Sleep settled it, another client answered it) leaves the queue;
    /// - an answer that came back (refused, rolled back with a toast) is undecided again, so its card returns.
    mutating func reconcile(visible: Set<String>) {
        history.removeAll { step in
            if case .answered(let id) = step { return visible.contains(id) }
            return false
        }
        let decided = decided
        queue.removeAll { !decided.contains($0) && !visible.contains($0) }
    }
}

/// The entry points: one per kind with something to review, in `ReviewKind` order.
enum ReviewEntries {
    struct Entry: Equatable, Identifiable {
        let kind: ReviewKind
        let count: Int
        var id: String { kind.id }
    }

    static func of(_ items: [InboxItem]) -> [Entry] {
        ReviewKind.allCases.compactMap { kind in
            let n = items.filter { $0.kind == kind.inboxKind && ReviewCard.reviewable($0) }.count
            return n > 0 ? Entry(kind: kind, count: n) : nil
        }
    }
}

/// The review's keys (DR-68's grammar, DR-60: none animates). 1–9 answer with the card's answer n; S skips; O or ⏎
/// moves into the answer field on a card that takes words; Esc ends the review (handled by the page — the field's own
/// Esc comes first). ⌘Z takes back the last answer or skip: it is the Undo button's shortcut, present only while there
/// is something to undo and never while the field has focus (R-DI4 — there ⌘Z is the field's). While the field has
/// focus every other key is the field's too.
enum ReviewKey: Equatable {
    case answer(Int), skip, type
}

enum ReviewKeys {
    static func action(_ characters: String, answers: Int, takesText: Bool, fieldFocused: Bool) -> ReviewKey? {
        guard !fieldFocused else { return nil }
        let key = characters.lowercased()
        if let n = Int(key), n >= 1, n <= min(answers, 9) { return .answer(n - 1) }
        switch key {
        case "s": return .skip
        case "o", "\r": return takesText ? .type : nil
        default: return nil
        }
    }

    static func undoShortcut(fieldFocused: Bool) -> Bool { !fieldFocused }
}
