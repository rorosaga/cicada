import XCTest
@testable import CicadaApp

/// R-PP10…R-PP12, R-PP16 — the band's marks and where each one's words come from, pure, on the demo's wire at
/// T = 2026-09-23 and a 600-unit band (the rover spans Jul 15 → Nov 2: 110 days, 60/11 units a day).
@MainActor
final class ProjectBandTests: XCTestCase {
    private let today = ProjectFixtures.today
    private let us = Locale(identifier: "en_US")

    private func rover() throws -> (ProjectTimeline, BandLayout) {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let state = ProjectState.state(ProjectState.Input(t), today: today)
        return (t, BandLayout.make(t, state: state, width: 600, today: today, locale: us))
    }

    private func item(_ t: ProjectTimeline, _ kind: String, _ day: String) throws -> ProjectItem {
        try XCTUnwrap(t.items.first { $0.kind == kind && $0.day == day })
    }

    func testTheGreenFillsToTodayAgainstThePlan() throws {
        let (_, band) = try rover()
        XCTAssertTrue(band.span.planned)
        XCTAssertEqual(band.todayX, 600 * 70 / 110, accuracy: 0.01)
        XCTAssertEqual(band.months.map(\.label), ["Jul", "Aug", "Sep", "Oct", "Nov"])
        XCTAssertEqual(band.months[1].x, 600 * 17 / 110, accuracy: 0.01, "Aug 1")
        XCTAssertEqual(band.words.map(\.label), ["2 weeks ago", "in 2 weeks"])
        XCTAssertEqual(band.since, "Since Jul 15")
        XCTAssertEqual(band.progressWords, "1 of 4 done")
        XCTAssertEqual(band.next?.label, "First grasp · in 8 days")
        XCTAssertEqual(band.accessibility,
                       "Progress of Rover Arm Project, 1 of 4 milestones done. You are here, today, September 23.")
    }

    /// §3.8 — done milestones filled inside the green, planned ones hollow past today, a moved one with a dashed ghost at
    /// its earlier date and a bracket to the new one.
    func testMilestonesOwnTheTrack() throws {
        let (_, band) = try rover()
        func mark(_ slug: String, _ kind: BandLayout.Mark) -> BandLayout.Node? {
            band.nodes.first { $0.key == .milestone(slug) && $0.mark == kind }
        }
        let arm = try XCTUnwrap(mark("arm-assembled", .milestoneDone))
        XCTAssertEqual(arm.x, 600 * 25 / 110, accuracy: 0.01, "placed at its done day, Aug 9")
        XCTAssertEqual(arm.lane, .track)
        XCTAssertEqual(arm.when, "done Aug 9")
        let grasp = try XCTUnwrap(mark("first-grasp", .milestonePlanned))
        XCTAssertEqual(grasp.x, 600 * 78 / 110, accuracy: 0.01)
        let ghost = try XCTUnwrap(mark("first-grasp", .ghost))
        XCTAssertEqual(ghost.x, 600 * 56 / 110, accuracy: 0.01, "Sep 9, its earlier date")
        XCTAssertEqual(ghost.when, "Sep 9, moved Sep 10")
        XCTAssertEqual(band.brackets.count, 1)
        XCTAssertEqual(band.brackets[0].x0, ghost.x, accuracy: 0.01)
        XCTAssertEqual(band.brackets[0].x1, grasp.x, accuracy: 0.01)
        XCTAssertNotNil(mark("due-2026-11-02", .milestonePlanned))
    }

    /// R-PP10 — a happening prefers the track, a moment below; a neighbour within 12 units pushes to the next lane.
    func testLanesAreDecidedDeterministically() throws {
        let (t, band) = try rover()
        func node(_ item: ProjectItem) -> BandLayout.Node? { band.nodes.first { $0.key == .item(item.id) } }
        let started = try XCTUnwrap(node(try item(t, "happening", "2026-07-15")))
        XCTAssertEqual(started.lane, .track)
        XCTAssertEqual(started.mark, .done)
        let assembled = try XCTUnwrap(node(try item(t, "happening", "2026-08-09")))
        XCTAssertEqual(assembled.lane, .below, "the arm-assembled milestone holds the track on Aug 9")
        let guide = try XCTUnwrap(node(try item(t, "happening", "2026-09-22")))
        XCTAssertEqual(guide.lane, .track)
        XCTAssertEqual(guide.label, "Bob got the lab cluster onboarding…")
        XCTAssertEqual(guide.when, "Yesterday")
        let specs = try XCTUnwrap(node(try item(t, "moment", "2026-09-22")))
        XCTAssertEqual(specs.mark, .said)
        XCTAssertEqual(specs.lane, .below)
        XCTAssertNil(node(try item(t, "happening", "2026-09-23")), "an ongoing happening is a thread, never a dot")
    }

    /// Threads end in an open cap at today; a quiet one fades after its last-heard day.
    func testThreadsRunToTodayAndFadeWhenQuiet() throws {
        let (t, band) = try rover()
        let camera = try XCTUnwrap(t.now.threads.first { $0.since == "2026-08-30" })
        let connecting = try XCTUnwrap(t.now.threads.first { $0.since == "2026-09-23" })
        let quiet = try XCTUnwrap(band.threads.first { $0.key == .thread(camera.claimId) })
        XCTAssertEqual(quiet.x0, 600 * 46 / 110, accuracy: 0.01)
        XCTAssertEqual(quiet.x1, band.todayX, accuracy: 0.01)
        XCTAssertEqual(quiet.solid, 0, accuracy: 0.0001, "quiet since the day it started: all dashed")
        XCTAssertEqual(quiet.cap, .open)
        XCTAssertEqual(quiet.when, "since Aug 30 · quiet 24 days")
        let live = try XCTUnwrap(band.threads.first { $0.key == .thread(connecting.claimId) })
        XCTAssertEqual(live.solid, 1)
        XCTAssertEqual(live.when, "started today")
        XCTAssertLessThanOrEqual(band.threads.count, BandLayout.threadRows)
    }

    /// ←/→ walk every mark left to right; a ghost is no stop (it selects its milestone).
    func testTheKeysWalkTheBandInOrder() throws {
        let (t, band) = try rover()
        let order = band.order
        XCTAssertEqual(order.first, .item(try item(t, "happening", "2026-07-15").id))
        XCTAssertEqual(order.last, .milestone("due-2026-11-02"))
        XCTAssertEqual(order.filter { $0 == .milestone("first-grasp") }.count, 1)
        XCTAssertEqual(band.step(from: nil, delta: 1), order.first)
        XCTAssertEqual(band.step(from: nil, delta: -1), order.last)
        XCTAssertEqual(band.step(from: order.last, delta: 1), order.last, "clamped at the end")
        XCTAssertEqual(band.step(from: order[0], delta: 1), order[1])
    }

    /// No plan: the fill runs to today and the end stays open; nothing is invented to fill the right side.
    func testAnUnplannedProjectHasAnOpenEnd() throws {
        let t = try ProjectFixtures.timeline("garden-sensor-project")
        let band = BandLayout.make(t, state: ProjectState.state(ProjectState.Input(t), today: today), width: 590,
                                   today: today, locale: us)
        XCTAssertFalse(band.span.planned)
        XCTAssertNil(band.progressWords)
        XCTAssertNil(band.next)
        XCTAssertEqual(band.todayX, 590 * 52 / 59, accuracy: 0.01)
        XCTAssertTrue(band.nodes.allSatisfy { $0.mark == .said }, "three moments, no milestone")
        XCTAssertTrue(band.accessibility.contains("no plan yet"))
    }

    /// A window past 540 days keeps the last 365 and folds the rest into one "N earlier" mark.
    func testALongWindowFoldsTheOldestIntoOneMark() throws {
        var t = try ProjectFixtures.timeline("garden-sensor-project")
        t.project.created = "2024-01-10"
        let first = try XCTUnwrap(t.items.firstIndex { $0.kind == "moment" && $0.day == "2026-08-02" })
        t.items[first].day = "2024-01-10"
        let band = BandLayout.make(t, state: ProjectState.state(ProjectState.Input(t), today: today), width: 600,
                                   today: today, locale: us)
        XCTAssertEqual(band.span.start, today.adding(-BandLayout.keptDays))
        let earlier = try XCTUnwrap(band.nodes.first { $0.mark == .earlier })
        XCTAssertEqual(earlier.x, 0)
        XCTAssertEqual(earlier.label, "1 earlier")
    }

    /// R-PP16 — a row's source line and the Reader's target, said once.
    func testSourcesAndReaderTargets() throws {
        let (t, _) = try rover()
        let guide = try item(t, "happening", "2026-09-22")
        XCTAssertEqual(ProjectSource.line(guide), .conversation(origin: "telegram", app: "Telegram", title: "Notes on the lab cluster"))
        let target = try XCTUnwrap(ProjectSource.target(guide, projectId: t.project.id))
        guard case let .span(start, end, hash, derived) = target.focus else { return XCTFail("\(target.focus)") }
        let own = try XCTUnwrap(guide.claim?.evidence.first { $0.isSpan })
        XCTAssertEqual([start, end], [own.start, own.end])
        XCTAssertEqual(hash, own.hash, "the claim's own span carries its hash, so the server can say grown or stale")
        XCTAssertFalse(derived)
        XCTAssertEqual(target.subjectId, "pick-and-place-demo")
        let specs = try item(t, "moment", "2026-09-22")
        guard case let .span(_, _, momentHash, _) = try XCTUnwrap(ProjectSource.target(specs, projectId: t.project.id)).focus else {
            return XCTFail("a moment's quote lands on its span")
        }
        XCTAssertNil(momentHash, "a moment's quote carries no hash (reported)")
        XCTAssertEqual(ProjectSource.line(specs), .conversation(origin: "claude-code", app: "Claude Code", title: "Lab cluster specs"))
        // Spelled out: a bare `.none` could be read as `Optional.none` once XCTAssertEqual promotes to `Line?`.
        XCTAssertEqual(ProjectSource.line(try XCTUnwrap(t.items.first { $0.kind == "created" })), ProjectSource.Line.none)
        let grasp = try XCTUnwrap(t.milestones.first { $0.slug == "first-grasp" })
        XCTAssertEqual(ProjectSource.line(grasp, conversations: t.conversations), .setByYou,
                       "the person moved it in the app: reasoning evidence, origin companion_app (§7)")
        XCTAssertNil(ProjectSource.target(for: .milestone("first-grasp"), in: t, projectId: t.project.id),
                     "nothing to open: no sentence says it")
        let camera = try XCTUnwrap(t.now.threads.first { $0.since == "2026-08-30" })
        XCTAssertEqual(ProjectSource.target(for: .thread(camera.claimId), in: t, projectId: t.project.id)?.episode,
                       "ep_2026-08-30_002")
        XCTAssertEqual(ProjectSource.docIndex(t).meta("ep_2026-09-22_003")?.harness, "claude-code")
    }

    /// R-PP12 / R-PJ22 — the band never says "Timeline": the card's Timeline tab can share the screen.
    func testNothingOnThePageSaysTimeline() throws {
        let literal = try NSRegularExpression(pattern: #""[^"\n]*Timeline[^"\n]*""#)
        var offenders: [String] = []
        var scanned = 0
        for file in try ThemeTokenTests.swiftSources()
        where file.path.contains("/Views/Projects/") || file.path.hasSuffix("/Theme/Copy+Projects.swift") {
            scanned += 1
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                let ns = line as NSString
                if literal.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) != nil {
                    offenders.append("\(file.lastPathComponent):\(i + 1)")
                }
            }
        }
        XCTAssertGreaterThan(scanned, 0)
        XCTAssertEqual(offenders, [], "R-PJ22: the band is 'Progress', the card's tab is 'Timeline'")
    }
}
