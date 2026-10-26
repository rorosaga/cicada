import Foundation

// Onboarding v3 (2026-10-24, after HeyClicky's onboarding) — the new decisions, pure, so the views stay renderers and
// the rules are tested without a window (`OnboardingV3Tests`).

// MARK: Agents — the one live check

enum AgentTryPrompt {
    /// The agent the chip names: the person's own — a product that already called, else the first one found on this
    /// Mac — never a vendor chosen for them (provider-neutral copy). Nil reads "your agent".
    static func agentName(_ rows: [AgentUmbrellaRow]) -> String? {
        let products = rows.flatMap(\.products)
        return (products.first(where: \.connected) ?? products.first)?.name
    }

    /// The first call's agent, by the name its row shows ("Claude Code"), else the catalog's, else the raw id.
    static func callerName(_ id: String, rows: [AgentUmbrellaRow]) -> String {
        rows.flatMap(\.products).first { $0.id == id }?.name ?? AgentCatalog.entry(for: id)?.name ?? id
    }
}

// MARK: Sources — what leads, what folds

enum SourceTileGroups {
    /// DR-39: the tiles this Mac has data for lead — Calendar, Contacts, each browser found here and chat history —
    /// and the ones that open a detail (Messages and the accounts read through the browser) fold under *More sources*.
    static func split(_ tiles: [SourceTile]) -> (lead: [SourceTile], more: [SourceTile]) {
        var lead: [SourceTile] = []
        var more: [SourceTile] = []
        for tile in tiles {
            if case .open = tile.kind { more.append(tile) } else { lead.append(tile) }
        }
        return (lead, more)
    }

    /// A fold that holds something the person turned on opens by itself: what they did is never hidden.
    static func moreStartsOpen(remembered: Bool, anyOnInside: Bool) -> Bool { remembered || anyOnInside }

    /// Calendar and Contacts keep macOS's own prompt (never the drag helper). Once it was refused, macOS never asks
    /// again, so the tile opens the exact list instead (HeyClicky: a denied alert "quietly switches to Open").
    static func deniedSettingsURL(_ id: FoundItemID) -> URL? {
        let anchor: String
        switch id {
        case .app(AppSourceDrivers.calendar): anchor = "Privacy_Calendars"
        case .app(AppSourceDrivers.contacts): anchor = "Privacy_Contacts"
        default: return nil
        }
        return URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)")
    }
}

// MARK: Done — end on the person's own memory

/// What Done reveals: the first pages and conversations already in this memory — the person's own, never an example —
/// plus how many more. A read that is running (the post-import read, or any other) adds its pages as they land: the
/// Store's graph is live (SSE), so a new page shows here on its own. Nothing here starts a read.
struct DoneReveal: Equatable {
    enum Kind: Equatable {
        case page
        case conversation(origin: String)
    }

    struct Item: Equatable, Identifiable {
        let id: String
        let title: String
        let kind: Kind
    }

    struct Page: Equatable {
        let id: String
        let name: String
    }

    struct Conversation: Equatable {
        let id: String
        let title: String?
        let origin: String
    }

    static let limit = 3

    let items: [Item]
    let more: Int
    let reading: Bool

    var isEmpty: Bool { items.isEmpty }

    /// Pages first (what memory already holds), then conversations waiting to be read; the owner's own page is never
    /// counted as something that came in.
    static func of(pages: [Page], waiting: [Conversation], reading: Bool, limit: Int = DoneReveal.limit) -> DoneReveal {
        let all = pages.map { Item(id: "page:" + $0.id, title: $0.name, kind: .page) }
            + waiting.map { conversation in
                let title = conversation.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                return Item(id: "ep:" + conversation.id, title: title.isEmpty ? Copy.doneUntitled : title,
                            kind: .conversation(origin: conversation.origin))
            }
        let shown = Array(all.prefix(max(0, limit)))
        return DoneReveal(items: shown, more: all.count - shown.count, reading: reading)
    }

    /// The pages a graph holds that came in: not the owner's seeded page, not a facet or a hub.
    static func pages(_ nodes: [GraphNode]) -> [Page] {
        nodes.filter { !$0.isOwner && !$0.isFacet && !$0.isHub }.map { Page(id: $0.id, name: $0.name) }
    }

    /// The label over the list: "Reading now" while a read runs, else "In your memory"; nothing over an empty list,
    /// which says "Nothing yet." on its own.
    var label: String? {
        if reading { return Copy.doneReading }
        return isEmpty ? nil : Copy.doneAlready
    }
}

// MARK: The worm's ways out

/// Every way out of onboarding, and how the menu-bar worm arrives for each (owner 2026-10-23: the worm shows on every
/// exit). Since v3 the flight is Done's closing beat: Open Cicada by pointer flies it from Done; every other exit shows
/// it with no flight (a key never animates, DR-60), and Reduce Motion fades it (DR-66).
enum OnboardingExit: CaseIterable {
    case openCicadaByPointer, openCicadaByKey, setUpLater, closeRerun, tryDemo, quitMidway

    func reveal(from frame: CGRect?, reduceMotion: Bool) -> MenuBarReveal {
        switch self {
        case .openCicadaByPointer:
            return (frame.map { MenuBarReveal.fly(from: $0) } ?? .instant).resolved(reduceMotion: reduceMotion)
        case .openCicadaByKey, .setUpLater, .closeRerun, .tryDemo, .quitMidway:
            return .instant
        }
    }
}

// MARK: Words

/// The bar onboarding v3 holds every step to (HeyClicky: 4–7-word titles, 1–2 sentences): a title of at most seven
/// words and a body of at most twenty-five — the step's own sentences, not its buttons, its frame or a name the
/// person typed. Measured on each step's longest variant (`OnboardingV3Tests`).
enum OnboardingWords {
    static let titleCap = 7
    static let bodyCap = 25

    struct Step: Equatable {
        let name: String
        let title: String
        let body: [String]
    }

    /// A word has a letter: "—", "·" and "3:00" are not words.
    static func count(_ parts: [String]) -> Int {
        parts.joined(separator: " ").split { $0.isWhitespace }.filter { $0.contains { $0.isLetter } }.count
    }

    /// Each step's title and its longest body.
    static var steps: [Step] {
        let when = "tonight at 3:00 AM"
        return [
            Step(name: "welcome", title: Copy.welcomeHello("Verify"), body: [Copy.welcomeLine]),
            Step(name: "intelligence", title: Copy.intelTitle,
                 body: [Copy.intelSubline, Copy.intelUsing("ChatGPT plan"), Copy.intelRuns("Claude Code")]),
            Step(name: "agents", title: Copy.agentsTitle,
                 body: [Copy.agentsSubline, Copy.agentsTryLead, Copy.agentsTryAsk("Claude Desktop")]),
            Step(name: "agents, after the first call", title: Copy.agentsTitle,
                 body: [Copy.agentsSubline, Copy.agentsFirstCall("Claude Desktop")]),
            Step(name: "sources", title: Copy.importTitle, body: [Copy.sourcesSubline]),
            Step(name: "saved lists", title: Copy.savedListsTitle, body: [Copy.savedListsSubline]),
            Step(name: "meet your bookworm", title: Copy.MeetWorm.title,
                 body: [Copy.MeetWorm.sublineShown, Copy.MeetWorm.number, Copy.MeetWorm.goesDown]),
            Step(name: "done", title: Copy.doneTitle,
                 body: [Copy.doneAlready, Copy.doneLead, Copy.doneScheduledAndNowOnKey(when, "OpenRouter")]),
            Step(name: "done, nothing yet", title: Copy.doneTitle,
                 body: [Copy.doneEmpty, Copy.doneLead, Copy.doneScheduledAndNowOnKey(when, "OpenRouter")]),
        ]
    }
}
