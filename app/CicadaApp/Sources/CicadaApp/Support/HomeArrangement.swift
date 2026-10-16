import Foundation

/// Owner ruling 2026-10-14, "Graduate + Needs you first" (amends Track I R-IB17/R-IB18 and Home's block order; the
/// welcome-home plan records it beside those rulings). Getting started retires itself once the person has chats in
/// memory, a returning person sees what is waiting on them first, and setup stays reachable from Settings → General's
/// *Show setup checklist*. Every rule here is pure and table-tested (`HomeFrontDoorTests`); the views only render it.
enum HomeSetup {
    /// "Chats in memory": a conversation source — an imported chat export or a connected agent, both `harness` rows of
    /// `GET /sources/overview` — has fed at least one page. That is the overview's existing per-source page credit
    /// (`entities`, counted from each page's `source_episodes`), so the signal is a fact of the bank, not app state, and
    /// a conversation captured but never read does not count: it is not in memory yet. Unknown (the overview has not
    /// loaded) is nil, never "no" and never "yes".
    static func hasChatsInMemory(_ overview: [SourceOverview]?) -> Bool? {
        guard let overview else { return nil }
        return overview.contains { $0.kind == .harness && $0.entities > 0 }
    }

    /// The export rows still worth offering: a vendor leaves once its export is in this bank (its `chat-export:<vendor>`
    /// row holds episodes). Unknown keeps every vendor — an offer is harmless, a missing one is not.
    static func vendorsToAsk(_ overview: [SourceOverview]?) -> [ChatVendor] {
        guard let overview else { return ChatVendor.allCases }
        let imported = Set(overview.filter { $0.episodes > 0 }.map(\.id))
        return ChatVendor.allCases.filter { !imported.contains($0.channelId) }
    }

    /// The things still left on a graduated card: rows that are not On. A row in progress (`.working`) is Cicada's to
    /// finish, not the person's, so it is not counted; neither is the schedule question (a person on *When I ask* may
    /// have chosen it, and that cannot be told apart from never answering) nor *Also on this Mac* (an offer, never a
    /// chore — the review's "Also found stops blocking").
    static func thingsLeft(_ rows: [GettingStartedRow]) -> Int {
        rows.filter {
            switch $0.state {
            case .on, .working: false
            case .off, .needsAction, .failed: true
            }
        }.count
    }
}

/// How Getting started shows itself on Home.
enum GettingStartedPresentation: Equatable {
    /// No record, hidden, or graduated with nothing left.
    case none
    /// The whole card: the first week, or a graduated card its viewer opened.
    case card
    /// Graduated with something left: one line, "Setup · 2 things left · Show ›" (DR-39: secondary detail starts
    /// collapsed, and each viewer's choice is remembered).
    case line(left: Int)

    static func of(visible: Bool, graduated: Bool, expanded: Bool, left: Int) -> GettingStartedPresentation {
        guard visible else { return .none }
        guard graduated, !expanded else { return .card }
        return left > 0 ? .line(left: left) : .none
    }
}

/// Home's blocks, in the order the person's state asks for (owner 2026-10-14).
enum HomeBlockID: Equatable, CaseIterable {
    case setup, today, needsYou, readingSites, lastRead, tour, tip
}

enum HomeArrangement: Equatable {
    /// The full Getting started card is up and the person has no chats in memory yet: setup leads.
    case firstWeek
    /// Everyone else: what is waiting on the person leads, and setup (if anything is left) is the last line.
    case returning

    static func of(setupVisible: Bool, graduated: Bool) -> HomeArrangement {
        setupVisible && !graduated ? .firstWeek : .returning
    }

    /// *Make it yours* never sits above Needs you (DR-38, P-a "the work leads"). The tour offer leads the first week:
    /// onboarding's last page asked for it, and below the tall setup card it would start off-screen; for a returning
    /// person it follows Needs you.
    var order: [HomeBlockID] {
        switch self {
        case .firstWeek: [.tour, .setup, .today, .needsYou, .readingSites, .lastRead, .tip]
        case .returning: [.needsYou, .readingSites, .today, .lastRead, .tour, .tip, .setup]
        }
    }
}

/// DR-37/DR-38 — empty Home says one true thing, not three "nothing"s. A value that is not known yet is never empty
/// (R-A14): only a loaded zero is.
struct HomeEmptiness: Equatable {
    var captured: Int?
    /// nil when Today does not show the waiting line (`HomeLayout.showsWaitingInToday`) — then it cannot make Today
    /// non-empty.
    var waiting: Int?
    var showsWaiting: Bool
    var needsYou: Int
    var inboxLoaded: Bool
    var lastReadNever: Bool

    var todayEmpty: Bool { captured == 0 && (!showsWaiting || waiting == 0) }
    var needsYouEmpty: Bool { inboxLoaded && needsYou == 0 }
    var allEmpty: Bool { todayEmpty && needsYouEmpty && lastReadNever }

    enum Mode: Equatable {
        /// Each block as usual; an empty one is only its label with a short note, no card.
        case blocks
        /// The three are empty and nothing else on Home says so: one block says it once.
        case one
        /// The three are empty and the Getting started card already says "Nothing to read yet…": say nothing more.
        case hidden
    }

    func mode(setupCardShown: Bool) -> Mode {
        guard allEmpty else { return .blocks }
        return setupCardShown ? .hidden : .one
    }
}

/// DR-69 / review #5 — Home's hit targets.
enum HomeTargets {
    /// `InlineLink`'s hit height and side slop: 28 pt, layout-neutral, so a link inside a sentence keeps its line.
    static let linkHeight: CGFloat = 28
    static let linkSlop: CGFloat = 6
    /// A `Tag` is 18 pt (DR-44); its button's hit frame is 24.
    static let tagHitHeight: CGFloat = 24
}
