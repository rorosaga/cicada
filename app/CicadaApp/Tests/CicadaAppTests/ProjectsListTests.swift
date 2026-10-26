import XCTest
@testable import CicadaApp

/// Projects v2 (owner 2026-10-19) — what the Projects list and a project's summary show, pure, on the demo's real wire
/// at T = 2026-09-23, plus synthetic rows for a Past the demo is too small to page.
@MainActor
final class ProjectsListTests: XCTestCase {
    private let today = ProjectFixtures.today
    private let us = Locale(identifier: "en_US")
    private func rows() throws -> [ProjectRow] { try ProjectFixtures.load().projects.projects }

    private func ids(_ entries: [ProjectsEntry]) -> [String] { entries.map(\.id) }

    /// `count` archived projects, last heard one per ten days back from `from`; synthetic only.
    private func pastRows(_ count: Int, from: ISODay) throws -> [ProjectRow] {
        let objects: [[String: Any]] = (0..<count).map { i in
            ["id": "past-\(i)", "name": "Past Example \(i)", "oneLiner": "A synthetic past project.",
             "status": "archived", "lastMomentDay": from.adding(-10 * i).description]
        }
        let data = try JSONSerialization.data(withJSONObject: ["projects": objects])
        return try JSONDecoder().decode(ProjectsResponse.self, from: data).projects
    }

    func testTwoTabsCurrentAndPast() throws {
        let rows = try rows()
        let tabs = ProjectsModel.tabs(ProjectsModel.counts(rows, today: today))
        XCTAssertEqual(tabs.map(\.label), ["Current", "Past"])
        XCTAssertEqual(tabs.map(\.count), [6, 9], "nine demo projects were never heard from: they are past")
        XCTAssertEqual(ProjectsModel.defaultTab(ProjectsModel.counts(rows, today: today)), .current)
        XCTAssertEqual(ProjectsModel.defaultTab(ProjectsModel.counts(rows, today: today.adding(400))), .past,
                       "nothing current: the page opens on Past")
        XCTAssertEqual(ProjectsGroup(.inMotion), .current)
        XCTAssertEqual(ProjectsGroup(.quiet).tab, .current, "fading sits under Current")
        XCTAssertEqual(ProjectsGroup(.resting).tab, .past)
    }

    /// The owner: "if the projects have subsections, then it should actually be a dropdown that moves if I press
    /// again" — parts are folded under their parent until unfolded.
    func testPartsFoldUnderTheirParent() throws {
        let rows = try rows()
        let folded = ProjectsModel.entries(rows, tab: .current, query: "", today: today)
        XCTAssertEqual(ids(folded), ["rover-arm-project", "alpha-project", "gamma-project", "garden-sensor-project"])
        XCTAssertEqual(folded.compactMap(\.line).map(\.children), [1, 1, 0, 0])
        XCTAssertEqual(folded.compactMap(\.line).map(\.expanded), [false, false, false, false])

        let open = ProjectsModel.entries(rows, tab: .current, query: "", today: today,
                                         options: ProjectsListOptions(expanded: ["rover-arm-project"]))
        XCTAssertEqual(ids(open), ["rover-arm-project", "pick-and-place-demo", "alpha-project", "gamma-project",
                                   "garden-sensor-project"])
        XCTAssertEqual(open.compactMap(\.line).map(\.depth), [0, 1, 0, 0, 0])
        XCTAssertEqual(open.first?.line?.expanded, true)

        let found = ProjectsModel.entries(rows, tab: .current, query: "Beta", today: today)
        XCTAssertEqual(ids(found), ["beta-project"])
        XCTAssertEqual(found.first?.line?.depth, 0, "a part whose parent is not shown sits flat")
    }

    func testAClickOpensAndTheSecondFolds() throws {
        let lines = ProjectsModel.entries(try rows(), tab: .current, query: "", today: today,
                                          options: ProjectsListOptions(expanded: ["rover-arm-project"])).compactMap(\.line)
        let rover = try XCTUnwrap(lines.first { $0.id == "rover-arm-project" })
        let garden = try XCTUnwrap(lines.first { $0.id == "garden-sensor-project" })
        let closedRover = ProjectLine(row: rover.row, state: rover.state, depth: 0, children: 1, expanded: false)
        XCTAssertTrue(ProjectsModel.tap(closedRover, openId: nil) == (true, true), "a parent opens and unfolds")
        XCTAssertTrue(ProjectsModel.tap(rover, openId: "rover-arm-project") == (false, false), "pressed again, it folds")
        XCTAssertTrue(ProjectsModel.tap(closedRover, openId: "rover-arm-project") == (false, true), "and again, unfolds")
        XCTAssertTrue(ProjectsModel.tap(garden, openId: nil) == (true, nil), "a plain project only opens")
        XCTAssertTrue(ProjectsModel.tap(garden, openId: "garden-sensor-project") == (true, nil))
    }

    /// A month on, the quiet projects fold into one *Fading* group under Current, closed unless opened or found.
    func testFadingIsOneFoldedGroup() throws {
        let rows = try rows()
        let later = today.adding(30)
        let counts = ProjectsModel.counts(rows, today: later)
        let fading = try XCTUnwrap(counts[.fading])
        XCTAssertGreaterThan(fading, 0)
        let closed = ProjectsModel.entries(rows, tab: .current, query: "", today: later)
        XCTAssertEqual(closed.last, .fading(count: fading, open: false))
        XCTAssertEqual(closed.compactMap(\.line).count, counts[.current])
        let open = ProjectsModel.entries(rows, tab: .current, query: "", today: later,
                                         options: ProjectsListOptions(fadingOpen: true))
        XCTAssertTrue(open.contains(.fading(count: fading, open: true)))
        let after = open.drop { $0.id != "projects.fading" }.dropFirst().compactMap(\.line)
        XCTAssertFalse(after.isEmpty)
        XCTAssertTrue(after.allSatisfy { $0.group == .fading })
        XCTAssertEqual(ProjectsModel.standing(try XCTUnwrap(after.first { $0.id == "rover-arm-project" }), today: later),
                       "Quiet 30 days")
        let onlyFading = rows.filter { ProjectsModel.group($0, today: later) == .fading }
        XCTAssertEqual(ProjectsModel.entries(onlyFading, tab: .current, query: "", today: later).first,
                       .fading(count: fading, open: true), "nothing in motion: Fading shows itself")
    }

    /// "Never 600 rows at once": Past draws a page at a time, newest first, under year labels.
    func testPastIsPagedUnderYearLabels() throws {
        let rows = try pastRows(120, from: ISODay(year: 2026, month: 3, day: 1))
        let first = ProjectsModel.entries(rows, tab: .past, query: "", today: today)
        XCTAssertEqual(first.first, .year("2026"))
        XCTAssertEqual(first.compactMap(\.line).count, ProjectsModel.pageSize)
        XCTAssertEqual(first.last, .more(70))
        XCTAssertTrue(first.contains(.year("2025")))
        XCTAssertEqual(first.compactMap(\.line).first?.id, "past-0", "newest heard first")
        let more = ProjectsModel.entries(rows, tab: .past, query: "", today: today,
                                         options: ProjectsListOptions(pastLimit: 100))
        XCTAssertEqual(more.last, .more(20))
        let found = ProjectsModel.entries(rows, tab: .past, query: "Past Example 117", today: today)
        XCTAssertEqual(found.compactMap(\.line).map(\.id), ["past-117"], "find reaches past the page")
        XCTAssertEqual(Copy.Projects.showMore(50, left: 70), "Show 50 more · 70 not shown")

        let demo = ProjectsModel.entries(try self.rows(), tab: .past, query: "", today: today)
        XCTAssertEqual(demo.first, .year("Nothing heard yet"))
        XCTAssertEqual(demo.compactMap(\.line).count, 9)
        XCTAssertFalse(demo.contains { if case .more = $0 { true } else { false } })
    }

    /// The owner: "one signal, not five" — a row is its name, what it is, and where it stands.
    func testARowSaysWhereItStandsOnce() throws {
        let lines = ProjectsModel.entries(try rows(), tab: .current, query: "", today: today).compactMap(\.line)
        let rover = try XCTUnwrap(lines.first { $0.id == "rover-arm-project" })
        XCTAssertEqual(ProjectsModel.standing(rover, today: today, locale: us), "Next · First grasp, Oct 1")
        XCTAssertEqual(ProjectsModel.oneLine(rover.row), "A small arm that picks parts off a tray.")
        XCTAssertEqual(ProjectsModel.accessibilityLabel(rover, today: today, locale: us),
                       "Rover Arm Project, Next · First grasp, Oct 1, 1 part, Collapsed")
        // VoiceOver hears the row in the same locale it shows: a Mac in Spain (here en_GB) reads "1 Oct".
        XCTAssertEqual(ProjectsModel.accessibilityLabel(rover, today: today, locale: Locale(identifier: "en_GB")),
                       "Rover Arm Project, Next · First grasp, 1 Oct, 1 part, Collapsed")
        let garden = try XCTUnwrap(lines.first { $0.id == "garden-sensor-project" })
        XCTAssertEqual(ProjectsModel.standing(garden, today: today, locale: us), "Heard 9 days ago")
        XCTAssertEqual(ProjectsModel.accessibilityLabel(garden, today: today, locale: us),
                       "Garden Sensor Project, Heard 9 days ago")

        let past = ProjectsModel.entries(try rows(), tab: .past, query: "", today: today).compactMap(\.line)
        XCTAssertEqual(ProjectsModel.standing(try XCTUnwrap(past.first), today: today, locale: us), "",
                       "under the Nothing heard yet label a row says nothing more")
        let old = try pastRows(1, from: ISODay(year: 2025, month: 3, day: 3))
        let oldLine = try XCTUnwrap(ProjectsModel.entries(old, tab: .past, query: "", today: today).compactMap(\.line).first)
        XCTAssertEqual(ProjectsModel.standing(oldLine, today: today, locale: us), "Mar 3",
                       "the date alone: its year is the label above it")
        // Overdue says so in words, never red (DR-7).
        let late = ProjectLine(row: rover.row, state: ProjectsModel.state(rover.row, today: today.adding(10)), depth: 0)
        XCTAssertEqual(ProjectsModel.standing(late, today: today.adding(10), locale: us),
                       "Next · First grasp, overdue since Oct 1")
    }

    /// A ⌘K landing on a project the list hides draws its row first: its tab, Fading, its parents, enough of Past.
    func testRevealDrawsAHiddenProject() throws {
        let rows = try rows()
        XCTAssertEqual(ProjectsModel.reveal("pick-and-place-demo", rows: rows, today: today, pastLimit: 50),
                       .init(tab: .current, openFading: false, expand: ["rover-arm-project"], pastLimit: nil))
        XCTAssertEqual(ProjectsModel.reveal("delta-project", rows: rows, today: today, pastLimit: 50),
                       .init(tab: .past, openFading: false, expand: [], pastLimit: nil))
        XCTAssertEqual(ProjectsModel.reveal("rover-arm-project", rows: rows, today: today.adding(30), pastLimit: 50)?.openFading,
                       true)
        XCTAssertNil(ProjectsModel.reveal("nope", rows: rows, today: today, pastLimit: 50))
        let past = try pastRows(120, from: ISODay(year: 2026, month: 3, day: 1))
        XCTAssertEqual(ProjectsModel.reveal("past-75", rows: past, today: today, pastLimit: 50)?.pastLimit, 100)
        XCTAssertNil(ProjectsModel.reveal("past-10", rows: past, today: today, pastLimit: 50)?.pastLimit)
    }

    /// The tabs carry the counts and the detail says where the open project stands: the eyebrow repeats neither.
    func testTheEyebrowSaysWhereYouAre() {
        XCTAssertEqual(ProjectsModel.eyebrow(partial: false), "Projects")
        XCTAssertEqual(ProjectsModel.eyebrow(partial: true), "Projects · still indexing")
    }

    /// DR-68 — every project is reachable by keyboard: ↓ past Current opens Fading, ↓ past Past's page draws the next,
    /// → / ← unfold and fold a parent's parts, ← on a part goes to its parent.
    func testEveryProjectIsReachableByKeyboard() throws {
        let rows = try rows()
        let later = today.adding(30)
        let current = ProjectsModel.entries(rows, tab: .current, query: "", today: later).compactMap(\.line)
        let lastCurrent = try XCTUnwrap(current.last?.id)
        let down = ProjectsModel.step(1, openId: lastCurrent, rows: rows, tab: .current, query: "", today: later,
                                      options: ProjectsListOptions())
        XCTAssertTrue(down.options.fadingOpen, "↓ past the last current row opens Fading")
        let landed = try XCTUnwrap(rows.first { $0.id == down.open })
        XCTAssertEqual(ProjectsModel.group(landed, today: later), .fading, "and lands on its first row")
        XCTAssertEqual(ProjectsModel.step(-1, openId: lastCurrent, rows: rows, tab: .current, query: "", today: later,
                                          options: ProjectsListOptions()).options.fadingOpen, false)
        XCTAssertEqual(ProjectsModel.step(1, openId: nil, rows: rows, tab: .current, query: "", today: today,
                                          options: ProjectsListOptions()).open, "rover-arm-project")

        let past = try pastRows(120, from: ISODay(year: 2026, month: 3, day: 1))
        let paged = ProjectsModel.step(1, openId: "past-49", rows: past, tab: .past, query: "", today: today,
                                       options: ProjectsListOptions())
        XCTAssertEqual(paged.options.pastLimit, 100, "↓ on the 50th row draws the next page")
        XCTAssertEqual(paged.open, "past-50")
        let end = ProjectsModel.step(1, openId: "past-119", rows: past, tab: .past, query: "", today: today,
                                     options: ProjectsListOptions(pastLimit: 150))
        XCTAssertEqual(end.open, "past-119", "the last project stays put")

        let lines = ProjectsModel.entries(rows, tab: .current, query: "", today: today,
                                          options: ProjectsListOptions(expanded: ["rover-arm-project"])).compactMap(\.line)
        let rover = try XCTUnwrap(lines.first { $0.id == "rover-arm-project" })
        let pick = try XCTUnwrap(lines.first { $0.id == "pick-and-place-demo" })
        let folded = ProjectLine(row: rover.row, state: rover.state, depth: 0, children: 1, expanded: false)
        XCTAssertEqual(ProjectsModel.side(1, line: folded), .expand(true))
        XCTAssertEqual(ProjectsModel.side(1, line: rover), .none)
        XCTAssertEqual(ProjectsModel.side(-1, line: rover), .expand(false))
        XCTAssertEqual(ProjectsModel.side(-1, line: pick), .open("rover-arm-project"))
        XCTAssertEqual(ProjectsModel.side(-1, line: nil), .none)
    }

    /// What it is, where it stands, what happened last, what's next — once each.
    func testTheSummarySaysEachThingOnce() throws {
        let rover = try ProjectFixtures.timeline("rover-arm-project")
        let state = ProjectState.state(ProjectState.Input(rover), today: today)
        let s = ProjectSummary.make(rover, state: state, today: today, locale: us)
        XCTAssertEqual(s.stands, "In motion · 1 of 4 milestones done")
        XCTAssertEqual(s.last?.text, "Today · Bob is connecting to Lab Cluster Example to run the Pick And Place Demo")
        XCTAssertEqual(s.last?.key, .item("clm_pick-and-place-demo_happened_7ab9b8cd_2026-09-23"))
        XCTAssertEqual(s.next, .init(text: "First grasp · Oct 1 (in 8 days)", key: .milestone("first-grasp")))

        let later = today.adding(30)
        let quiet = ProjectSummary.make(rover, state: ProjectState.state(ProjectState.Input(rover), today: later),
                                        today: later, locale: us)
        XCTAssertEqual(quiet.stands, "Quiet 30 days · 1 of 4 milestones done")
        XCTAssertEqual(quiet.next?.text, "First grasp · overdue since Oct 1")

        let garden = try ProjectFixtures.timeline("garden-sensor-project")
        let g = ProjectSummary.make(garden, state: ProjectState.state(ProjectState.Input(garden), today: today),
                                    today: today, locale: us)
        XCTAssertEqual(g.stands, "In motion · no plan yet")
        XCTAssertEqual(g.last?.text, "Sep 14 · Garden Sensor Project uses Tool Example G")
        XCTAssertNil(g.next, "no plan and nothing going: the page says Nothing planned and offers Add a milestone")

        // Across the screen, each fact once. The Plan section's folded words never restate the summary's plan.
        XCTAssertEqual(ProjectSummary.planMeta(state), "", "Where it stands already says 1 of 4 milestones done")
        XCTAssertEqual(ProjectSummary.planMeta(ProjectState.state(ProjectState.Input(garden), today: today)), "",
                       "Where it stands already says no plan yet")
        XCTAssertEqual(ProjectSummary.planMeta(ProjectState.state(ProjectState.Input(garden), today: today.adding(400))),
                       "No plan yet", "a resting project's summary does not say it, so the section does")
        // A milestone named after its own project says only its day — in the row and in the detail.
        let pick = try ProjectFixtures.timeline("pick-and-place-demo")
        let p = ProjectSummary.make(pick, state: ProjectState.state(ProjectState.Input(pick), today: today), today: today,
                                    locale: us)
        XCTAssertEqual(p.next?.text, "Oct 5 (in 12 days)")
        let late = today.adding(20)
        XCTAssertEqual(ProjectSummary.make(pick, state: ProjectState.state(ProjectState.Input(pick), today: late),
                                           today: late, locale: us).next?.text, "overdue since Oct 5")
        let pickRow = try ProjectFixtures.row("pick-and-place-demo")
        XCTAssertEqual(ProjectsModel.standing(ProjectLine(row: pickRow, state: ProjectsModel.state(pickRow, today: today),
                                                          depth: 1), today: today, locale: us), "Next · Oct 5")
        XCTAssertEqual(ProjectsModel.standing(ProjectLine(row: pickRow, state: ProjectsModel.state(pickRow, today: late),
                                                          depth: 1), today: late, locale: us),
                       "Next · overdue since Oct 5")
        XCTAssertNil(ProjectsModel.milestoneName("pick and place demo ", project: "Pick And Place Demo"))
        XCTAssertEqual(ProjectsModel.milestoneName("First grasp", project: "Rover Arm Project"), "First grasp")
        // The open row beside its detail is only its name; the others say where they stand; at rest, what they are.
        let roverRow = try ProjectFixtures.row("rover-arm-project")
        let roverLine = ProjectLine(row: roverRow, state: ProjectsModel.state(roverRow, today: today), depth: 0)
        XCTAssertNil(ProjectsModel.secondLine(roverLine, style: .triage, selected: true, today: today, locale: us))
        XCTAssertEqual(ProjectsModel.secondLine(roverLine, style: .triage, selected: false, today: today, locale: us),
                       "Next · First grasp, Oct 1")
        XCTAssertEqual(ProjectsModel.secondLine(roverLine, style: .wide, selected: false, today: today, locale: us),
                       "A small arm that picks parts off a tray.")
        XCTAssertNil(ProjectsModel.secondLine(roverLine, style: .titles, selected: false, today: today, locale: us))
    }

    /// The thread Last already says is never Next too.
    func testNextNeverRepeatsLast() throws {
        var rover = try ProjectFixtures.timeline("rover-arm-project")
        rover.milestones = []
        let state = ProjectState.state(ProjectState.Input(rover), today: today)
        let s = ProjectSummary.make(rover, state: state, today: today, locale: us)
        XCTAssertEqual(s.last?.key, .item("clm_pick-and-place-demo_happened_7ab9b8cd_2026-09-23"))
        XCTAssertNotEqual(s.next?.key, .thread("clm_pick-and-place-demo_happened_7ab9b8cd_2026-09-23"))
    }

    /// §3.8 / R-PP9 — the band's span: from the first moment, through today, to the plan.
    func testTheBandFillsToTodayAndEndsWhereThePlanDoes() throws {
        let rover = ProjectsModel.span(try ProjectFixtures.timeline("rover-arm-project"), planned: true, today: today)
        XCTAssertEqual(rover.start.description, "2026-07-15")
        XCTAssertEqual(rover.end.description, "2026-11-02")
        XCTAssertEqual(rover.fill, 70.0 / 110.0, accuracy: 0.0001)
        let allPast = ProgressSpan.of(created: today.adding(-30), days: [], targets: [today.adding(-3)], planned: true,
                                      today: today)
        XCTAssertEqual(allPast.end, today.adding(7), "every target behind today: the span still reaches past today")
    }

    func testTheListSaysWhatItHasBeforeItHasRows() {
        XCTAssertEqual(ProjectsListState.of(phase: .loading, hasList: false, rows: 0, lines: 0, finding: false), .loading)
        XCTAssertEqual(ProjectsListState.of(phase: .failed("x"), hasList: false, rows: 0, lines: 0, finding: false), .failed("x"))
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 0, lines: 0, finding: false), .empty)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 0, finding: false), .tabEmpty)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 0, finding: true), .noMatch)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 5, lines: 2, finding: false), .list)
    }

    /// R-PP24 — ⌘8 and the palette's page row come from `AppTab`; a project row, a follow-up, and the rail's second
    /// click hand off.
    func testTheEighthPageAndItsHandOffs() {
        XCTAssertEqual(RailItem.shortcut(for: .projects), "⌘8")
        XCTAssertEqual(RailItem.tooltipTitle(.projects, busy: false), "Projects", "the tooltip reads \"Projects ⌘8\"")
        XCTAssertEqual(AppTab.projects.icon, "point.topleft.down.to.point.bottomright.curvepath")
        XCTAssertTrue(AppTab.projects.hostsOwnReader)
        XCTAssertEqual(AppTab.restored(from: "Projects"), .projects)
        // Owner 2026-10-26: the page is hidden behind `PageSwitches.projectsPage` — no palette row, and a project opens
        // as its own page on the graph. The page, its digit and its reselect stay for when the switch returns it.
        let row = PaletteActions.docs(QuickIndexInputs()).first { $0.row.key.id == "tab.Projects" }?.row
        XCTAssertNil(row)
        let router = AppRouter()
        router.routeToProject("rover-arm-project")
        XCTAssertEqual(router.pendingTab, .graph)
        XCTAssertEqual(router.consumeRevealEntity(), "rover-arm-project")
        XCTAssertNil(router.consumeProject(), "nothing staged for a hidden page")
        router.routeToInboxItem("inbox-007")
        XCTAssertEqual(router.pendingTab, .inbox)
        XCTAssertEqual(router.consumeInboxItem(), "inbox-007")
        XCTAssertTrue(RailReselect.isReselect(current: .projects, tapped: .projects))
        router.reselect(.projects)
        XCTAssertEqual(router.reselections(of: .projects), 1, "Projects clicked again asks the page for its root")
        XCTAssertEqual(router.reselections(of: .sources), 0)
    }

    func testAProjectNodeLandsOnProjects() {
        let graph = GraphResponse(nodes: [
            GraphNode(id: "rover-arm-project", name: "Rover Arm Project", type: .project),
            GraphNode(id: "hana-example", name: "Hana Example", type: .person, degree: 3),
        ], links: [])
        XCTAssertTrue(ProjectsModel.isProject("rover-arm-project", in: graph))
        XCTAssertFalse(ProjectsModel.isProject("hana-example", in: graph))
    }
}
