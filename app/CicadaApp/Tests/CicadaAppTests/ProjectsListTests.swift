import XCTest
@testable import CicadaApp

/// R-PP6…R-PP9, R-PP24 — what the Projects list shows, pure, on the demo's real wire at T = 2026-09-23.
@MainActor
final class ProjectsListTests: XCTestCase {
    private let today = ProjectFixtures.today
    private let us = Locale(identifier: "en_US")
    private func rows() throws -> [ProjectRow] { try ProjectFixtures.load().projects.projects }

    func testTabsCountTheDemoAndDefaultToActive() throws {
        let rows = try rows()
        let tabs = ProjectsModel.tabs(rows, today: today)
        XCTAssertEqual(tabs.map(\.label), ["Active", "Quiet", "All"])
        XCTAssertEqual(tabs.map(\.count), [6, 0, 15])
        XCTAssertEqual(ProjectsModel.defaultTab(rows, today: today), .active)
        XCTAssertNil(ProjectsModel.defaultTab(rows, today: today.adding(400)), "nothing in motion opens on All")
    }

    /// §11.2 — a sub-project sits indented under its parent when the parent is shown, and flat when it is not.
    func testSubProjectsSitUnderAVisibleParent() throws {
        let lines = ProjectsModel.lines(try rows(), tab: .active, query: "", today: today)
        XCTAssertEqual(lines.map(\.id), ["rover-arm-project", "pick-and-place-demo", "alpha-project", "beta-project",
                                         "gamma-project", "garden-sensor-project"])
        XCTAssertEqual(lines.map(\.depth), [0, 1, 0, 1, 0, 0])
        let found = ProjectsModel.lines(try rows(), tab: nil, query: "Beta", today: today)
        XCTAssertEqual(found.map(\.id), ["beta-project"])
        XCTAssertEqual(found.first?.depth, 0, "a child whose parent is not shown sits flat")
        XCTAssertEqual(ProjectsModel.lines(try rows(), tab: .quiet, query: "", today: today), [])
        XCTAssertEqual(ProjectsModel.lines(try rows(), tab: nil, query: "", today: today).count, 15)
    }

    func testTheRowSaysWhereItStandsNow() throws {
        let lines = ProjectsModel.lines(try rows(), tab: nil, query: "", today: today)
        func line(_ id: String) throws -> ProjectLine { try XCTUnwrap(lines.first { $0.id == id }) }
        let rover = try line("rover-arm-project")
        XCTAssertEqual(ProjectsModel.nowLine(rover, today: today, locale: us),
                       "Bob is connecting to Lab Cluster Example to run the Pick And Place Demo",
                       "the live thread, never the quiet one")
        XCTAssertEqual(ProjectsModel.nextLine(rover, today: today, locale: us), "Next · First grasp, Oct 1")
        XCTAssertEqual(ProjectsModel.shortLine(rover, today: today, locale: us), "1 of 4 done · First grasp Oct 1")
        XCTAssertEqual(ProjectsModel.questions(rover.row), "1 question")
        XCTAssertEqual(ProjectsModel.age(rover.row, today: today, locale: us).text, "today")
        XCTAssertEqual(ProjectsModel.accessibilityLabel(rover), "Rover Arm Project — 1 of 4 milestones done")
        let garden = try line("garden-sensor-project")
        XCTAssertEqual(ProjectsModel.nowLine(garden, today: today, locale: us), "Soil sensors that report from the garden.")
        XCTAssertEqual(ProjectsModel.nextLine(garden, today: today, locale: us), "No plan yet")
        XCTAssertEqual(ProjectsModel.shortLine(garden, today: today, locale: us), "No plan yet · last Sep 14")
        XCTAssertEqual(ProjectsModel.age(garden.row, today: today, locale: us).text, "9d")
        XCTAssertEqual(ProjectsModel.age(garden.row, today: today, locale: us).help, "Last activity Monday, September 14, 2026")
        let delta = try line("delta-project")
        XCTAssertEqual(ProjectsModel.nowLine(delta, today: today, locale: us), "Nothing heard yet")
        XCTAssertEqual(ProjectsModel.age(delta.row, today: today, locale: us).text, "—")
        XCTAssertEqual(ProjectsModel.age(delta.row, today: today, locale: us).help, "No activity yet")
        XCTAssertNil(ProjectsModel.questions(delta.row))
        // A month on, both threads are quiet: the row leads with the quiet days, never a stale "is connecting".
        let later = today.adding(30)
        let quietRover = ProjectLine(row: rover.row, state: ProjectsModel.state(rover.row, today: later), depth: 0)
        XCTAssertEqual(ProjectsModel.nowLine(quietRover, today: later, locale: us),
                       "Quiet 30 days · Bob is connecting to Lab Cluster Example to run the Pick And Place Demo")
    }

    func testTheEyebrowSaysWhereYouAre() {
        XCTAssertEqual(ProjectsModel.eyebrow(visible: 6, tab: .active, position: nil, openPlanned: nil, partial: false),
                       "Projects · 6 active")
        XCTAssertEqual(ProjectsModel.eyebrow(visible: 15, tab: nil, position: nil, openPlanned: nil, partial: false),
                       "Projects · 15")
        XCTAssertEqual(ProjectsModel.eyebrow(visible: 6, tab: .active, position: 1, openPlanned: true, partial: false),
                       "Projects · 1 of 6 · Planned")
        XCTAssertEqual(ProjectsModel.eyebrow(visible: 6, tab: .active, position: 6, openPlanned: false, partial: true),
                       "Projects · 6 of 6 · No plan yet · still indexing")
    }

    /// §3.8 / R-PP9 — the mini bar and the band share one geometry: from the first moment, through today, to the plan.
    func testTheBarFillsToTodayAndEndsWhereThePlanDoes() throws {
        let rover = ProjectsModel.bar(try ProjectFixtures.row("rover-arm-project"), today: today)
        XCTAssertEqual(rover.start.description, "2026-07-15")
        XCTAssertEqual(rover.end.description, "2026-11-02")
        XCTAssertEqual(rover.fill, 70.0 / 110.0, accuracy: 0.0001)
        XCTAssertTrue(rover.planned)
        let garden = ProjectsModel.bar(try ProjectFixtures.row("garden-sensor-project"), today: today)
        XCTAssertEqual(garden.end, today.adding(7), "no plan: a week past today, and an open end")
        XCTAssertEqual(garden.fill, 52.0 / 59.0, accuracy: 0.0001)
        XCTAssertFalse(garden.planned)
        let allPast = ProgressSpan.of(created: today.adding(-30), days: [], targets: [today.adding(-3)], planned: true,
                                      today: today)
        XCTAssertEqual(allPast.end, today.adding(7), "every target behind today: the bar still reaches past today")
        XCTAssertEqual(ProjectsModel.span(try ProjectFixtures.timeline("rover-arm-project"), planned: true, today: today),
                       rover, "the detail's span is the row's")
    }

    /// R-PP7 — people come from the graph the app already holds: a project's `person` neighbours, never the owner.
    func testPeopleAreThePersonNeighboursButNeverTheOwner() {
        let graph = GraphResponse(nodes: [
            GraphNode(id: "rover-arm-project", name: "Rover Arm Project", type: .project),
            GraphNode(id: "hana-example", name: "Hana Example", type: .person, degree: 3),
            GraphNode(id: "bob-example", name: "Bob Example", type: .person, degree: 9, isOwner: true),
            GraphNode(id: "cara-example", name: "Cara Example", type: .person, degree: 1),
            GraphNode(id: "tool-example-a", name: "Tool Example A", type: .tool),
        ], links: [
            GraphEdge(source: "hana-example", target: "rover-arm-project", label: "works-on"),
            GraphEdge(source: "rover-arm-project", target: "bob-example", label: "with"),
            GraphEdge(source: "rover-arm-project", target: "cara-example", label: "with"),
            GraphEdge(source: "rover-arm-project", target: "tool-example-a", label: "uses"),
        ])
        let people = ProjectsModel.peopleIndex(graph)["rover-arm-project"] ?? []
        XCTAssertEqual(people.map(\.name), ["Hana Example", "Cara Example"])
        XCTAssertEqual(people.first?.initials, "HE")
        XCTAssertTrue(ProjectsModel.isProject("rover-arm-project", in: graph))
        XCTAssertFalse(ProjectsModel.isProject("hana-example", in: graph))
    }

    func testTheListSaysWhatItHasBeforeItHasRows() {
        XCTAssertEqual(ProjectsListState.of(phase: .loading, hasList: false, rows: 0, lines: 0, finding: false), .loading)
        XCTAssertEqual(ProjectsListState.of(phase: .failed("x"), hasList: false, rows: 0, lines: 0, finding: false), .failed("x"))
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 0, lines: 0, finding: false), .empty)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 0, finding: false), .tabEmpty)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 0, finding: true), .noMatch)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 2, finding: false), .list)
    }

    /// R-PP24 — ⌘8 and the palette's page row come from `AppTab`; a project row, and a follow-up, hand off.
    func testTheEighthPageAndItsHandOffs() {
        XCTAssertEqual(RailItem.shortcut(for: .projects), "⌘8")
        XCTAssertEqual(RailItem.tooltipTitle(.projects, busy: false), "Projects", "the tooltip reads \"Projects ⌘8\"")
        XCTAssertEqual(AppTab.projects.icon, "point.topleft.down.to.point.bottomright.curvepath")
        XCTAssertTrue(AppTab.projects.hostsOwnReader)
        XCTAssertEqual(AppTab.restored(from: "Projects"), .projects)
        let row = PaletteActions.docs(QuickIndexInputs()).first { $0.row.key.id == "tab.Projects" }?.row
        XCTAssertEqual(row?.title, "Go to Projects")
        XCTAssertEqual(row?.trailing, "⌘8")
        let router = AppRouter()
        router.routeToProject("rover-arm-project")
        XCTAssertEqual(router.pendingTab, .projects)
        XCTAssertEqual(router.consumeProject(), "rover-arm-project")
        XCTAssertNil(router.consumeProject(), "read-then-clear")
        router.routeToInboxItem("inbox-007")
        XCTAssertEqual(router.pendingTab, .inbox)
        XCTAssertEqual(router.consumeInboxItem(), "inbox-007")
    }
}
