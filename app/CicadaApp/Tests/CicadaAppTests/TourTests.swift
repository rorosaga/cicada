import XCTest
@testable import CicadaApp

/// G152 — the guided tour's decisions, each a pure function or a small state machine with a table test: the stops and
/// their pages, the words for an empty bank, what is remembered per viewer, when the layer starts it, where the coach
/// mark sits, and that routing only ever navigates.
@MainActor
final class TourTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suite: String!

    override func setUp() {
        super.setUp()
        suite = "tour-tests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    // MARK: The plan

    func testSixStopsInTheBriefsOrder() {
        XCTAssertEqual(TourStop.allCases, [.search, .home, .inbox, .person, .projects, .sleep])
    }

    func testTheDemoOpensItsShowcaseAndARealBankOnlyThePages() {
        let demo = TourContext(isDemo: true, hasShowcasePerson: true, hasShowcaseProject: true, hasPeople: true,
                               hasProjects: true, hasQuestions: true)
        XCTAssertEqual(TourPlan.step(.person, context: demo).navigation, .clustersEntity(DemoShowcase.person))
        XCTAssertEqual(TourPlan.step(.person, context: demo).anchors, [.personCard, .clusters])
        XCTAssertEqual(TourPlan.step(.projects, context: demo).navigation, .project(DemoShowcase.project))

        // A real bank that happens to hold the same ids is still never picked for (R-DT7).
        var real = demo
        real.isDemo = false
        XCTAssertEqual(TourPlan.step(.person, context: real).navigation, .tab(.clusters))
        XCTAssertEqual(TourPlan.step(.person, context: real).anchors, [.clusters])
        XCTAssertEqual(TourPlan.step(.projects, context: real).navigation, .tab(.projects))

        XCTAssertEqual(TourPlan.step(.search, context: real).navigation, .stay)
        XCTAssertEqual(TourPlan.step(.search, context: real).anchors, [.commandBar])
        XCTAssertEqual(TourPlan.step(.home, context: real).navigation, .tab(.home))
        XCTAssertEqual(TourPlan.step(.inbox, context: real).navigation, .tab(.inbox))
        XCTAssertEqual(TourPlan.step(.sleep, context: real).navigation, .tab(.sleep))
        XCTAssertEqual(TourPlan.step(.sleep, context: real).anchors, [.consolidate])
    }

    func testAnEmptyBankSaysWhenYouHaveOne() {
        let empty = TourContext()
        XCTAssertEqual(TourPlan.step(.inbox, context: empty).body, Copy.Tour.inboxEmpty)
        XCTAssertEqual(TourPlan.step(.person, context: empty).body, Copy.Tour.personEmpty)
        XCTAssertEqual(TourPlan.step(.projects, context: empty).body, Copy.Tour.projectsEmpty)
        let full = TourContext(hasPeople: true, hasProjects: true, hasQuestions: true)
        XCTAssertEqual(TourPlan.step(.inbox, context: full).body, Copy.Tour.inboxBody)
        XCTAssertEqual(TourPlan.step(.person, context: full).body, Copy.Tour.personBody)
        XCTAssertEqual(TourPlan.step(.projects, context: full).body, Copy.Tour.projectsBody)
    }

    func testTheContextReadsTheRosterAndTheGraph() {
        let roster = BanksResponse(banks: [MemoryBank(name: "demo", active: true, entityCount: 1, episodeCount: 1,
                                                      createdAt: "", description: nil, demo: true)], active: "demo")
        let graph = GraphResponse(nodes: [GraphNode(id: DemoShowcase.person, name: "Leo Example", type: .person),
                                          GraphNode(id: "alpha-project", name: "Alpha Project", type: .project)],
                                  links: [])
        let context = TourContext.from(roster: roster, graph: graph, inboxCount: 0)
        XCTAssertEqual(context, TourContext(isDemo: true, hasShowcasePerson: true, hasShowcaseProject: false,
                                            hasPeople: true, hasProjects: true, hasQuestions: false))
        XCTAssertEqual(TourContext.from(roster: nil, graph: nil, inboxCount: 2), TourContext(hasQuestions: true))
    }

    // MARK: The controller

    func testNextBackAndDoneAreRememberedOnlyWhenThePersonEndsIt() {
        let tour = TourController(defaults: defaults)
        tour.start(bank: "default")
        XCTAssertEqual(tour.currentStop, .search)
        XCTAssertTrue(tour.spotlights(.commandBar))
        tour.back()
        XCTAssertEqual(tour.currentStop, .search, "Back stops at the first stop")
        for _ in 0..<5 { tour.next() }
        XCTAssertEqual(tour.currentStop, .sleep)
        XCTAssertTrue(tour.isLast)
        XCTAssertFalse(tour.spotlights(.commandBar))
        tour.back()
        XCTAssertEqual(tour.currentStop, .projects)
        tour.next(); tour.next()
        XCTAssertFalse(tour.isActive, "Done on the last stop ends it")
        XCTAssertTrue(TourMemory.isDone(defaults))
    }

    func testAnInterruptionRemembersNothing() {
        let tour = TourController(defaults: defaults)
        tour.requestStart()
        tour.start(bank: "demo")
        tour.interrupt()
        XCTAssertFalse(tour.isActive)
        XCTAssertFalse(tour.pendingStart)
        XCTAssertFalse(TourMemory.isDone(defaults))
    }

    func testEveryArrivalBumpsSoTheLayerRoutesOncePerStop() {
        let tour = TourController(defaults: defaults)
        tour.start(bank: "default")
        let first = tour.arrival
        tour.next()
        XCTAssertEqual(tour.arrival, first &+ 1)
        tour.back()
        XCTAssertEqual(tour.arrival, first &+ 2)
        tour.back()
        XCTAssertEqual(tour.arrival, first &+ 2, "a Back that goes nowhere routes nowhere")
    }

    /// Seam 3 — `TourOffer.consume()` answers once; the offer lives on the controller until answered, and a viewer who
    /// declined or finished is not asked again.
    func testTheOfferIsAdoptedOnceAndNeverRepeatedAfterANo() {
        let tour = TourController(defaults: defaults)
        tour.adoptOffer()
        XCTAssertFalse(tour.offerPending, "nothing asked")
        TourOffer.request(defaults: defaults)
        tour.adoptOffer()
        XCTAssertTrue(tour.offerPending)
        tour.adoptOffer()
        XCTAssertTrue(tour.offerPending, "a second Home keeps the unanswered offer")
        tour.declineOffer()
        XCTAssertFalse(tour.offerPending)
        TourOffer.request(defaults: defaults)
        tour.adoptOffer()
        XCTAssertFalse(tour.offerPending, "Not now is remembered per viewer")
    }

    func testTakingTheOfferIsARequest() {
        let tour = TourController(defaults: defaults)
        TourOffer.request(defaults: defaults)
        tour.adoptOffer()
        tour.requestStart()
        XCTAssertFalse(tour.offerPending)
        XCTAssertTrue(tour.pendingStart)
    }

    func testTheDemoStartsItOncePerViewer() {
        let tour = TourController(defaults: defaults)
        XCTAssertFalse(tour.demoStarted)
        tour.autoStart(bank: "demo")
        XCTAssertTrue(tour.demoStarted)
        XCTAssertEqual(tour.bank, "demo")
    }

    func testTheTriggerTable() {
        typealias T = TourTrigger
        XCTAssertEqual(T.decide(pendingStart: true, hidden: true, demoActive: true, demoStarted: false, tourActive: false),
                       .none, "nothing starts under the Welcome or Settings")
        XCTAssertEqual(T.decide(pendingStart: true, hidden: false, demoActive: false, demoStarted: true, tourActive: false),
                       .start)
        XCTAssertEqual(T.decide(pendingStart: true, hidden: false, demoActive: true, demoStarted: true, tourActive: true),
                       .start, "Restart tour starts over from the first stop")
        XCTAssertEqual(T.decide(pendingStart: false, hidden: false, demoActive: true, demoStarted: false, tourActive: false),
                       .autoStartDemo)
        XCTAssertEqual(T.decide(pendingStart: false, hidden: false, demoActive: true, demoStarted: true, tourActive: false),
                       .none)
        XCTAssertEqual(T.decide(pendingStart: false, hidden: false, demoActive: false, demoStarted: false, tourActive: false),
                       .none)
    }

    // MARK: Routing only navigates

    func testRoutingUsesTheRoutersHandOffsAndNothingElse() {
        let router = AppRouter()
        TourRouting.apply(.project(DemoShowcase.project), router: router)
        XCTAssertEqual(router.pendingTab, .projects)
        XCTAssertEqual(router.pendingProject, DemoShowcase.project)
        TourRouting.apply(.clustersEntity(DemoShowcase.person), router: router)
        XCTAssertEqual(router.pendingTab, .clusters)
        XCTAssertEqual(router.pendingClustersEntity, DemoShowcase.person)
        TourRouting.apply(.tab(.sleep), router: router)
        XCTAssertEqual(router.pendingTab, .sleep)
        TourRouting.apply(.stay, router: router)
        XCTAssertEqual(router.pendingTab, .sleep)
        XCTAssertFalse(router.pendingFirstRun)
        XCTAssertFalse(router.settingsOpen)
    }

    // MARK: Where the coach mark sits

    func testPlacementTable() {
        let page = CGSize(width: 1000, height: 800)
        let mark = CGSize(width: 320, height: 160)
        func place(_ t: CGRect?) -> CoachMarkLayout.Placement {
            CoachMarkLayout.place(target: t, container: page, callout: mark, scale: 1)
        }
        XCTAssertEqual(place(nil), .init(origin: CGPoint(x: 340, y: 320), edge: .center))
        XCTAssertEqual(place(CGRect(x: 100, y: 50, width: 200, height: 40)),
                       .init(origin: CGPoint(x: 40, y: 102), edge: .below))
        XCTAssertEqual(place(CGRect(x: 600, y: 700, width: 300, height: 60)),
                       .init(origin: CGPoint(x: 590, y: 528), edge: .above))
        XCTAssertEqual(place(CGRect(x: 0, y: 0, width: 300, height: 800)),
                       .init(origin: CGPoint(x: 312, y: 16), edge: .trailing))
        XCTAssertEqual(place(CGRect(x: 600, y: 0, width: 400, height: 800)),
                       .init(origin: CGPoint(x: 268, y: 16), edge: .leading))
        XCTAssertEqual(place(CGRect(x: 0, y: 0, width: 1000, height: 800)),
                       .init(origin: CGPoint(x: 340, y: 624), edge: .foot), "a full-page target keeps the foot")
        XCTAssertEqual(place(CGRect(x: 950, y: 50, width: 40, height: 40)).origin.x, 664, "clamped inside the margin")
    }

    func testTheCommandBarIsCentredOnTheWindowNotThePage() {
        let rect = CoachMarkLayout.commandBarRect(pageWidth: 1384, navWidth: 56, scale: 1)
        XCTAssertEqual(rect, CGRect(x: 404, y: 0, width: 520, height: 0))
        XCTAssertEqual(CoachMarkLayout.place(target: rect, container: CGSize(width: 1384, height: 848),
                                             callout: CGSize(width: 320, height: 160), scale: 1),
                       .init(origin: CGPoint(x: 504, y: 12), edge: .below))
    }
}
