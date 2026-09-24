import XCTest
@testable import CicadaApp

/// R-PP13…R-PP18, R-PP22, R-PP26 — the story's words, pure, on the demo's wire at T = 2026-09-23.
@MainActor
final class ProjectStoryTests: XCTestCase {
    private let today = ProjectFixtures.today
    private let us = Locale(identifier: "en_US")

    private func rover() throws -> (ProjectTimeline, ProjectState.Output) {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        return (t, ProjectState.state(ProjectState.Input(t), today: today))
    }

    private func item(_ t: ProjectTimeline, _ kind: String, _ day: String) throws -> ProjectItem {
        try XCTUnwrap(t.items.first { $0.kind == kind && $0.day == day })
    }

    /// R-PP15 — one sentence: the owner, then words, then every page the sentence names, where it names it.
    func testASentenceLinksEveryParticipantWhereItIsSaid() throws {
        let (t, _) = try rover()
        let guide = try item(t, "happening", "2026-09-22")
        let (tokens, extra) = ProjectStory.tokens(guide.text, participants: guide.participants)
        XCTAssertEqual(tokens.map(\.kind), [.owner, .word, .word, .page, .word, .page, .word, .word, .word, .word, .word, .page])
        XCTAssertEqual(tokens.filter { $0.kind != .word }.map(\.text),
                       ["Bob", "lab cluster onboarding guide", "Hana Example", "Lab Cluster Example"])
        XCTAssertEqual(tokens[5].trailing, ";", "punctuation rides with the chip before it")
        XCTAssertFalse(tokens[0].spaceBefore)
        XCTAssertTrue(tokens[1].spaceBefore)
        XCTAssertTrue(tokens[6].spaceBefore, "“it” follows the “; ” the chip carried")
        XCTAssertEqual(tokens[3].participant?.url, "https://example.com/guides/lab-cluster-onboarding.pdf")
        XCTAssertEqual(extra, [])
        // A moment's participants carry no surface: their names link where the phrase says them.
        let used = try item(t, "moment", "2026-09-09")
        let moment = ProjectStory.tokens(used.text, participants: used.participants)
        XCTAssertEqual(moment.tokens.map(\.kind), [.word, .word, .word, .word, .page])
        XCTAssertEqual(moment.tokens.last?.text, "Tool Example E")
        // A page the sentence never names follows it as a chip; an unlinked name stays words.
        let absent = ProjectParticipant(id: "tool-example-z", name: "Tool Example Z", type: "tool")
        let unlinked = ProjectParticipant(id: nil, name: "gripper camera")
        let more = ProjectStory.tokens("Bob started calibrating the gripper camera",
                                       participants: [unlinked, absent])
        XCTAssertEqual(more.extra, [absent])
        XCTAssertTrue(more.tokens.allSatisfy { $0.kind == .word })
    }

    /// R-PP14 — Today · Yesterday · This week · Earlier, in the server's order; `created` is the foot line.
    func testLatelyGroupsByTheViewersDay() throws {
        let (t, _) = try rover()
        let groups = ProjectStory.groups(t.items, today: today)
        XCTAssertEqual(groups.map(\.group), [.today, .yesterday, .earlier])
        XCTAssertEqual(groups[1].items.map(\.kind), ["happening", "moment"])
        XCTAssertEqual(groups.last?.items.count, 6)
        XCTAssertFalse(groups.flatMap(\.items).contains { $0.kind == "created" })
        XCTAssertEqual(ProjectStory.createdLine(t.items, today: today, locale: us), "Cicada started tracking this · Jul 15")
        XCTAssertEqual(ProjectStory.groups(t.items, today: today.adding(3)).map(\.group), [.thisWeek, .earlier],
                       "three days on, the same rows read as this week — derived at read, never stored")
    }

    func testEachRowSaysItsStatusDateAndHowItWasDated() throws {
        let (t, state) = try rover()
        let guide = try item(t, "happening", "2026-09-22")
        XCTAssertEqual(ProjectStory.status(guide, state: state, today: today, locale: us), "Done")
        XCTAssertEqual(ProjectStory.glyph(guide), .done)
        XCTAssertEqual(ProjectStory.rowDate(guide, today: today, locale: us).text, "Sep 22")
        XCTAssertEqual(ProjectStory.rowDate(guide, today: today, locale: us).help, "Tuesday, September 22, 2026")
        XCTAssertEqual(ProjectStory.basis(guide.dateBasis), "Dated from your words")
        let camera = try item(t, "happening", "2026-08-30")
        XCTAssertEqual(ProjectStory.status(camera, state: state, today: today, locale: us), "Quiet 24 days")
        XCTAssertEqual(ProjectStory.glyph(camera), .ongoing)
        let connecting = try item(t, "happening", "2026-09-23")
        XCTAssertEqual(ProjectStory.status(connecting, state: state, today: today, locale: us), "Ongoing")
        let specs = try item(t, "moment", "2026-09-22")
        XCTAssertEqual(ProjectStory.status(specs, state: state, today: today, locale: us), "Said here")
        XCTAssertEqual(ProjectStory.glyph(specs), .said)
        XCTAssertEqual(ProjectStory.factsLine(specs, names: EntityNames(byId: ["lab-cluster-example": "Lab Cluster Example"])),
                       "+1 fact · via Lab Cluster Example")
        XCTAssertNil(ProjectStory.factsLine(guide, names: .empty))
        XCTAssertEqual(ProjectStory.basis("person"), "Set by you")
        XCTAssertNil(ProjectStory.basis(nil))
    }

    /// Now: the live thread first, then the quiet one; a quiet thread's follow-up is found by its claim.
    func testNowListsLiveThreadsFirstAndFindsTheirFollowUp() throws {
        let (t, state) = try rover()
        let threads = ProjectStory.nowThreads(t, state: state)
        XCTAssertEqual(threads.map(\.since), ["2026-09-23", "2026-08-30"])
        XCTAssertEqual(ProjectStory.threadMeta(threads[0], state: state, today: today, locale: us), "Started today")
        XCTAssertEqual(ProjectStory.threadMeta(threads[1], state: state, today: today, locale: us), "Since Aug 30 · quiet 24 days")
        let wire = try ProjectFixtures.load()
        let followups = ProjectStory.followups([wire.followup])
        XCTAssertEqual(followups[threads[1].claimId]?.id, wire.followup.id)
        XCTAssertNil(followups[threads[0].claimId])
        XCTAssertEqual(ProjectStory.pendingLine(t.pending, today: today), "1 conversation is waiting for Sleep — the newest from today")
        let garden = try ProjectFixtures.timeline("garden-sensor-project")
        XCTAssertEqual(ProjectStory.nowEmpty(garden, today: today, locale: us),
                       "Nothing in motion right now · last heard Sep 14 (9 days ago)")
        XCTAssertNil(ProjectStory.pendingLine(garden.pending, today: today))
    }

    /// R-PP22 — the Plan's words: early/late, upcoming, "passed, no word", and a moved milestone's chain.
    func testThePlanSaysWhereEachMilestoneStands() throws {
        let (t, _) = try rover()
        let rows = ProjectPlan.rows(t.milestones, today: today)
        XCTAssertEqual(rows.map(\.id), ["arm-assembled", "first-grasp", "due-2026-10-05", "due-2026-11-02"])
        let names = EntityNames(byId: ["pick-and-place-demo": "Pick And Place Demo"])
        func meta(_ i: Int) -> String {
            ProjectPlan.meta(rows[i], onName: rows[i].milestone.on.flatMap { names.name(for: $0) }, today: today, locale: us)
        }
        XCTAssertEqual(meta(0), "Done Aug 9 — 3 days early")
        XCTAssertEqual(meta(1), "Oct 1 · in 8 days")
        XCTAssertEqual(meta(2), "Oct 5 · in 12 days", "no \"on Pick And Place Demo\" when the milestone bears its name")
        XCTAssertEqual(meta(3), "Nov 2 · in 40 days")
        XCTAssertEqual(ProjectPlan.chain(rows[1].milestone, today: today, locale: us),
                       ["Sep 9 — planned Jul 22", "Oct 1 — moved by you on Sep 10"])
        XCTAssertEqual(ProjectPlan.diamond(rows[0]), .filled)
        XCTAssertEqual(ProjectPlan.diamond(rows[1]), .hollow)
        XCTAssertFalse(ProjectPlan.canMarkDone(rows[0]))
        XCTAssertTrue(ProjectPlan.canMarkDone(rows[1]))
        // A due that expiry closed before anyone said how it went (R-PJ4).
        let passed = ProjectPlan.Row(milestone: ProjectMilestone(slug: "due-2026-09-09", name: "First grasp",
                                                                 status: "passed-no-word", target: "2026-09-09", source: "due"),
                                     state: ProjectState.milestoneState(ProjectMilestone(slug: "due-2026-09-09", name: "First grasp",
                                                                                         status: "passed-no-word", target: "2026-09-09"),
                                                                        today: today))
        XCTAssertEqual(ProjectPlan.meta(passed, onName: nil, today: today, locale: us),
                       "Sep 9 · passed, no word on how it went")
        XCTAssertEqual(ProjectPlan.diamond(passed), .slashed)
        XCTAssertTrue(ProjectPlan.canMarkDone(passed), "saying it happened is the answer the follow-up asks for")
        let overdue = ProjectMilestone(slug: "dry-run", name: "Dry run", status: "planned", target: "2026-09-20")
        XCTAssertEqual(ProjectPlan.meta(ProjectPlan.Row(milestone: overdue, state: ProjectState.milestoneState(overdue, today: today)),
                                        onName: nil, today: today, locale: us), "Overdue since Sep 20")
        let sub = ProjectMilestone(slug: "calibrated", name: "Camera calibrated", status: "planned", target: "2026-10-10",
                                   on: "pick-and-place-demo")
        XCTAssertEqual(ProjectPlan.meta(ProjectPlan.Row(milestone: sub, state: ProjectState.milestoneState(sub, today: today)),
                                        onName: "Pick And Place Demo", today: today, locale: us),
                       "Oct 10 · in 17 days · on Pick And Place Demo")
        XCTAssertTrue(ProjectPlan.isPending(ProjectMilestone(slug: "pending-1", name: "x", status: "planned")))
    }

    /// Around this project: the brief's labels, a tool that opens to its specs, a sub-project that opens itself.
    func testAroundUsesThePagesWords() throws {
        let (t, _) = try rover()
        XCTAssertEqual(t.cluster.groups.map { ProjectAround.label($0.label) },
                       ["People", "Tools & infrastructure", "Documents & links", "Parts of this project"])
        let tools = try XCTUnwrap(t.cluster.groups.first { $0.label == "Tools & infrastructure" })
        let cluster = try XCTUnwrap(tools.members.first { $0.memberId == "lab-cluster-example" })
        XCTAssertTrue(ProjectAround.expands(cluster))
        XCTAssertEqual(ProjectAround.last(cluster, today: today, locale: us)?.text, "last Sep 23")
        XCTAssertTrue(ProjectAround.opensProject(try XCTUnwrap(t.cluster.groups.last)))
        XCTAssertFalse(ProjectAround.expands(try XCTUnwrap(t.cluster.groups.first?.members.first)), "a person opens its card")
        let claims = try JSONDecoder().decode([Claim].self, from: Data("""
        [{"id":"c1","text":"Lab Cluster Example has 4 GPU nodes.","predicate":"spec","objectKind":"literal"},
         {"id":"c2","text":"Lab Cluster Example hosts the demo.","predicate":"hosts","objectKind":"node"},
         {"id":"c3","text":"old spec","predicate":"spec","objectKind":"literal","validTo":"2026-09-01"}]
        """.utf8))
        XCTAssertEqual(ProjectAround.specs(claims).map(\.id), ["c1"], "open spec claims first")
        XCTAssertEqual(ProjectAround.specs([claims[1]]).map(\.id), [], "no literal: nothing to list")
    }

    /// R-PP26 — one wording for Resume's outcome, the Reader's and this page's.
    func testResumeSaysWhatHappenedInWords() {
        XCTAssertEqual(ResumeOutcome.launched("Ghostty").toast, "Reopening in Ghostty…")
        XCTAssertEqual(ResumeOutcome.gone.toast, "That conversation's transcript is gone — nothing to resume")
        XCTAssertEqual(ResumeOutcome.failed("x").toast, "x")
    }
}
