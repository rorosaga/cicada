import Foundation
import Observation

/// G152 — the guided tour's stops, in order (the owner's round-4 brief): the command bar and search, Home, the Inbox,
/// a person card with its signed beliefs, Projects, Sleep.
enum TourStop: String, CaseIterable, Equatable {
    case search, home, inbox, person, projects, sleep
}

/// Where a coach mark points. `.commandBar` is a toolbar item, outside the page's coordinate space, so it draws its
/// own ring (`TourController.spotlights`) and the callout sits under it; every other target publishes its bounds
/// with `.tourAnchor(_:)`.
enum TourAnchorID: String, Hashable {
    case commandBar, home, inbox, personCard, clusters, projectDetail, projects, consolidate
}

/// Where a stop takes the person before it points: a page, or a page with one thing open. Navigation through
/// `AppRouter` and nothing else — no case can answer, start, connect or save anything, so the tour never acts for the
/// person (UX principle 3; G152's constraint; `TourLintTests` holds the tour's files to it).
enum TourNavigation: Equatable {
    case stay
    case tab(AppTab)
    case clustersEntity(String)
    case project(String)
}

/// What a stop needs to know about the bank it is shown in — read at the moment it shows, so a demo whose graph
/// lands a beat after the tour starts still opens its person card.
struct TourContext: Equatable {
    var isDemo = false
    var hasShowcasePerson = false
    var hasShowcaseProject = false
    var hasPeople = false
    var hasProjects = false
    var hasQuestions = false

    static func from(roster: BanksResponse?, graph: GraphResponse?, inboxCount: Int) -> TourContext {
        let nodes = graph?.nodes ?? []
        return TourContext(
            isDemo: DemoMode.isActive(roster),
            hasShowcasePerson: nodes.contains { $0.id == DemoShowcase.person && $0.type == .person },
            hasShowcaseProject: nodes.contains { $0.id == DemoShowcase.project && $0.type == .project },
            hasPeople: nodes.contains { $0.type == .person },
            hasProjects: nodes.contains { $0.type == .project },
            hasQuestions: inboxCount > 0)
    }
}

struct TourStep: Equatable {
    let stop: TourStop
    let title: String
    let body: String
    /// Candidates, first present wins; none present → the callout sits in the middle of the page, unanchored.
    let anchors: [TourAnchorID]
    let navigation: TourNavigation
}

/// Each stop's words, target and page (pure; `TourTests`). In the demo the person and project stops open the
/// showcase's own ids; in a real bank they show the page and say "when you have one" in words (G152: "in the real
/// bank it points at real rows or says 'when you have one'") — never a person or project picked for the person.
enum TourPlan {
    static func step(_ stop: TourStop, context: TourContext) -> TourStep {
        switch stop {
        case .search:
            return TourStep(stop: stop, title: Copy.Tour.searchTitle, body: Copy.Tour.searchBody,
                            anchors: [.commandBar], navigation: .stay)
        case .home:
            return TourStep(stop: stop, title: Copy.Tour.homeTitle, body: Copy.Tour.homeBody,
                            anchors: [.home], navigation: .tab(.home))
        case .inbox:
            return TourStep(stop: stop, title: Copy.Tour.inboxTitle,
                            body: context.hasQuestions ? Copy.Tour.inboxBody : Copy.Tour.inboxEmpty,
                            anchors: [.inbox], navigation: .tab(.inbox))
        case .person:
            let showcase = context.isDemo && context.hasShowcasePerson
            return TourStep(stop: stop, title: Copy.Tour.personTitle,
                            body: context.hasPeople ? Copy.Tour.personBody : Copy.Tour.personEmpty,
                            anchors: showcase ? [.personCard, .clusters] : [.clusters],
                            navigation: showcase ? .clustersEntity(DemoShowcase.person) : .tab(.clusters))
        case .projects:
            let showcase = context.isDemo && context.hasShowcaseProject
            return TourStep(stop: stop, title: Copy.Tour.projectsTitle,
                            body: context.hasProjects ? Copy.Tour.projectsBody : Copy.Tour.projectsEmpty,
                            anchors: showcase ? [.projectDetail, .projects] : [.projects],
                            navigation: showcase ? .project(DemoShowcase.project) : .tab(.projects))
        case .sleep:
            return TourStep(stop: stop, title: Copy.Tour.sleepTitle, body: Copy.Tour.sleepBody,
                            anchors: [.consolidate], navigation: .tab(.sleep))
        }
    }
}

/// Per viewer, never per bank (`TourOffer`'s rule — the tour teaches the app, not a memory): whether the tour was
/// finished or skipped (then nothing offers it again; Settings and the `?` still replay it), and whether the demo has
/// already started it once.
enum TourMemory {
    static let doneKey = "cicada.tour.done"
    static let demoStartedKey = "cicada.tour.demoStarted"

    static func isDone(_ defaults: UserDefaults) -> Bool { defaults.bool(forKey: doneKey) }
    static func markDone(_ defaults: UserDefaults) { defaults.set(true, forKey: doneKey) }
    static func demoStarted(_ defaults: UserDefaults) -> Bool { defaults.bool(forKey: demoStartedKey) }
    static func markDemoStarted(_ defaults: UserDefaults) { defaults.set(true, forKey: demoStartedKey) }
}

/// What the layer does when its inputs move (pure; `TourTests`). Nothing starts under the Welcome or the Settings
/// panel; a door's request restarts a running tour from the first stop; the demo starts it by itself once per viewer.
enum TourTrigger {
    enum Decision: Equatable { case none, start, autoStartDemo }

    static func decide(pendingStart: Bool, hidden: Bool, demoActive: Bool, demoStarted: Bool,
                       tourActive: Bool) -> Decision {
        guard !hidden else { return .none }
        if pendingStart { return .start }
        if demoActive && !demoStarted && !tourActive { return .autoStartDemo }
        return .none
    }
}

/// The tour's state, app-lifetime (`CicadaApp` injects it beside `AppRouter`). Views ask; `TourLayer` — the one view
/// always mounted over the pages — decides when a request becomes a tour and routes each stop.
@Observable
@MainActor
final class TourController {
    private(set) var index: Int?
    private(set) var pendingStart = false
    /// Bumped each time a stop becomes current, so the layer routes to its page once per arrival.
    private(set) var arrival = 0
    /// The bank the tour started in: a switch mid-tour ends it, because its stops describe another memory.
    private(set) var bank: String?
    /// Seam 3's offer, held here because Home is rebuilt on every tab switch (R-IB3) and `TourOffer.consume()` answers
    /// once.
    var offerPending = false
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    var isActive: Bool { index != nil }
    var currentStop: TourStop? { index.map { TourStop.allCases[$0] } }
    var count: Int { TourStop.allCases.count }
    var isLast: Bool { index == count - 1 }
    var demoStarted: Bool { TourMemory.demoStarted(defaults) }

    /// The command bar lights its own ring on the first stop (it lives in the titlebar, out of the scrim's reach).
    func spotlights(_ anchor: TourAnchorID) -> Bool { anchor == .commandBar && currentStop == .search }

    /// Every door asks here — Home's offer, Settings → General, the `?`, the demo banner's *Restart tour*.
    func requestStart() {
        pendingStart = true
        offerPending = false
    }

    func start(bank: String) {
        pendingStart = false
        self.bank = bank
        index = 0
        arrival &+= 1
    }

    /// The demo's first visit (G152, "started automatically on the first demo visit") — once per viewer.
    func autoStart(bank: String) {
        TourMemory.markDemoStarted(defaults)
        start(bank: bank)
    }

    func next() {
        guard let i = index else { return }
        if i + 1 < count {
            index = i + 1
            arrival &+= 1
        } else {
            finish()
        }
    }

    func back() {
        guard let i = index, i > 0 else { return }
        index = i - 1
        arrival &+= 1
    }

    /// Done, Skip tour and Esc: remembered per viewer, so nothing offers the tour again.
    func finish() {
        index = nil
        bank = nil
        TourMemory.markDone(defaults)
    }

    /// Ended by something else — a bank switch, leaving the demo. Nothing is remembered: the person decided nothing.
    func interrupt() {
        index = nil
        bank = nil
        pendingStart = false
    }

    /// Seam 3: onboarding's *Open Cicada* called `TourOffer.request()`; Home adopts it once. A viewer who already
    /// finished or skipped the tour is not asked again.
    func adoptOffer() {
        if TourOffer.consume(defaults: defaults), !TourMemory.isDone(defaults) { offerPending = true }
    }

    /// *Not now* on Home's offer — remembered like a skip.
    func declineOffer() {
        offerPending = false
        TourMemory.markDone(defaults)
    }
}

/// A stop's page, through the router's own hand-offs (each closes the Settings panel and brings the window forward,
/// Track P R7) — the same doors a ⌘K row uses.
@MainActor
enum TourRouting {
    static func apply(_ navigation: TourNavigation, router: AppRouter) {
        switch navigation {
        case .stay: break
        case .tab(let tab): router.pendingTab = tab
        case .clustersEntity(let id): router.routeToClustersEntity(id)
        case .project(let id): router.routeToProject(id)
        }
    }
}
