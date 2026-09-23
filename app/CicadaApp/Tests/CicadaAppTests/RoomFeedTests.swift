import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z Z9 (design §7.4, I12–I16; Z-B6 … Z-B11) — feeding is import, and
/// only import (R-Z10): the room is a door onto the one intake, its lines tell
/// the router's own outcome in words with no number (R-Z3), and every beat is
/// one the §6.4 matrix allows.
@MainActor
final class RoomFeedTests: XCTestCase {

    private let scene = deskSceneLayout(pointSize: 120, uiScale: 1.0)
    private var spots: [DeskHotspot: CGRect] { deskHotspots(scene) }
    /// Top-left points (what `DropInfo.location` reports) at 5 pt cells.
    private let overWorm = CGPoint(x: 200, y: 70)
    private let overLamp = CGPoint(x: 20, y: 100)

    private var everyPhase: [FeedPhase] {
        let refusals: [FeedPhase] = FeedRefusal.allCases.map(FeedPhase.refused)
        let rest: [FeedPhase] = [.busy, .unreachable, .reading, .preview, .importing,
                                 .landed(.added), .landed(.nothingNew), .landed(.elsewhere), .failed,
                                 .failedUnseen]
        return [.armed(overWorm: false), .armed(overWorm: true)] + refusals + rest
    }

    // MARK: The lines (R-Z13, R-Z3)

    func test_everyFeedLineFitsTheSlot_andCarriesNoNumber() {
        for phase in everyPhase {
            for asleep in [false, true] {
                let line = feedLine(phase, asleep: asleep)
                XCTAssertFalse(line.lead.isEmpty)
                XCTAssertLessThanOrEqual(line.lead.count, SentenceLine.maxLead, line.lead)
                XCTAssertLessThanOrEqual(line.tail?.count ?? 0, SentenceLine.maxTail, line.tail ?? "")
                XCTAssertFalse(line.spoken.contains("!"), line.spoken)
                XCTAssertFalse(line.spoken.contains("%"), line.spoken)
                XCTAssertFalse(line.spoken.contains("~"), line.spoken)
                // R-Z13's banned words, split the way `RoomSentenceTests` splits them.
                let words = line.spoken.lowercased().split { !$0.isLetter }.map(String.init)
                for word in ["est", "cluster", "insight"] { XCTAssertFalse(words.contains(word), line.spoken) }
                XCTAssertFalse(line.spoken.contains(where: \.isNumber), "R-Z3 — the panel has the counts: \(line.spoken)")
                XCTAssertNil(line.action, "a feed line never links: the next step is in the panel")
            }
        }
    }

    /// Z-B18 — "saved links", not the design's "notes": a note is not an
    /// export the intake reads, so the worm must never refuse one and then
    /// say notes work.
    func test_theArmedLines() {
        XCTAssertEqual(feedLine(.armed(overWorm: false), asleep: false),
                       SentenceLine(lead: "Is that for me?", tail: "Chat exports, bookmarks, feeds and saved links."))
        XCTAssertEqual(feedLine(.armed(overWorm: true), asleep: false).lead, "Drop it on me.")
        XCTAssertEqual(feedLine(.armed(overWorm: false), asleep: true).tail, "I'll read it next cycle.")
    }

    /// Z-B18 — the worm's voice, and a named service wears its mark (Z-P26).
    func test_theRefusalsSpeakInTheWormsVoice() {
        XCTAssertEqual(feedLine(.refused(.claudeSessions), asleep: false),
                       SentenceLine(lead: "I don't eat those.",
                                    tail: "Claude Code sessions come to me once it's connected.",
                                    mark: .origin("claude-code")))
        XCTAssertEqual(feedLine(.refused(.codexSessions), asleep: false).mark, .origin("codex"))
        XCTAssertEqual(feedLine(.refused(.cicadaHome), asleep: false).lead, "That's my own folder.")
        XCTAssertNil(feedLine(.refused(.cicadaHome), asleep: false).mark)
        XCTAssertEqual(feedLine(.refused(.unreadable), asleep: false),
                       SentenceLine(lead: "I can't read that yet.", tail: "Chat exports, bookmarks, feeds and saved links work."))
        XCTAssertEqual(feedLine(.busy, asleep: false).lead, "I'm still eating the last one.")
        XCTAssertEqual(feedLine(.unreachable, asleep: false).tail, "Nothing was sent. Try again in a moment.")
    }

    /// A sleeping worm takes the drop and says when it will read it (I15).
    func test_asleep_theWormSaysWhenItWillRead() {
        for phase in [FeedPhase.reading, .importing, .landed(.added)] {
            XCTAssertEqual(feedLine(phase, asleep: true).tail, "I'll read it after this nap.", "\(phase)")
        }
        XCTAssertEqual(feedLine(.landed(.added), asleep: false), SentenceLine(lead: "Got it.", tail: "It's on the pile now."))
    }

    /// Z-B9 — the router's own phase drives the line.
    func test_theRoutersPhaseIsTheLine() {
        XCTAssertNil(FeedPhase(.idle))
        XCTAssertEqual(FeedPhase(.reading(["conversations.json"])), .reading)
        XCTAssertEqual(FeedPhase(.preview(IntakePreview())), .preview)
        XCTAssertEqual(FeedPhase(.importing(IntakeProgress(total: 3, staged: 1))), .importing)
        XCTAssertEqual(FeedPhase(.done(IntakeOutcome(created: 2))), .landed(.added))
        XCTAssertEqual(FeedPhase(.done(IntakeOutcome(unchanged: 4))), .landed(.nothingNew))
        XCTAssertEqual(FeedPhase(.done(IntakeOutcome(created: 2, bank: "alpha-project", bankIsActive: false))),
                       .landed(.elsewhere))
        XCTAssertEqual(FeedPhase(.failed("Nothing here is an export Cicada can read.")), .failed)
    }

    // MARK: The room (I12–I16)

    func test_aDragArmsTheWormTowardIt_andEagerOverIt() {
        let room = RoomModel()
        room.dragMoved(to: overLamp, scene: scene, spots: spots, state: .happy)
        XCTAssertEqual(room.drag, .overRoom(.left))
        XCTAssertEqual(WormStage.pose(drag: room.drag, pointerInRoom: false, gaze: .center), .expectant(.left))
        room.dragMoved(to: overWorm, scene: scene, spots: spots, state: .happy)
        XCTAssertEqual(room.drag, .overWorm)
        XCTAssertEqual(WormStage.pose(drag: room.drag, pointerInRoom: true, gaze: .right), .eager,
                       "a drag outranks the pointer")
        room.dragEnded()
        XCTAssertNil(room.drag)
        XCTAssertEqual(WormStage.pose(drag: nil, pointerInRoom: true, gaze: .right), .attentive(.right))
    }

    /// Z-B10 — a gulp for what the router took, a shake for anything it did not.
    func test_yesGulps_noShakes() {
        let took = RoomModel()
        XCTAssertTrue(took.fed(.handedOver, state: .happy, reduceMotion: false))
        XCTAssertEqual(took.reaction?.kind, .gulp)
        for no in [FeedResult.refused(.unreadable), .busy, .unreachable] {
            let room = RoomModel()
            room.fed(no, state: .reading, reduceMotion: false)
            XCTAssertEqual(room.reaction?.kind, .shake, "\(no)")
        }
        let still = RoomModel()
        still.fed(.handedOver, state: .happy, reduceMotion: true)
        XCTAssertNil(still.reaction, "Reduce Motion: the line, no beat")
        XCTAssertEqual(still.feedResult, .handedOver)
        let failed = RoomModel()
        failed.fed(.refused(.unreadable), state: .error, reduceMotion: false)
        XCTAssertNil(failed.reaction, "an erroring worm answers in words only (§6.4)")
    }

    /// I15 — a drop while asleep still goes through; the worm stays asleep.
    func test_aSleepingWormTakesTheDropAndStaysAsleep() throws {
        let room = RoomModel()
        room.dragMoved(to: overWorm, scene: scene, spots: spots, state: .sleeping(stage: 2))
        XCTAssertEqual(BookwormPose.eager.effective(for: .sleeping(stage: 2), reduceMotion: false), .idle,
                       "no open mouth under the nightcap")
        room.fed(.handedOver, state: .sleeping(stage: 2), reduceMotion: false)
        XCTAssertNil(room.reaction, "no gulp — the nightcap stays on")
        XCTAssertEqual(room.feedResult, .handedOver, "…but the drop went through")
        let running = try JSONDecoder().decode(SleepStatusResponse.self, from: Data(#"{"status":"running","stage":0}"#.utf8))
        XCTAssertEqual(deriveSleepPageMood(status: running, debt: nil, justFinishedAt: nil, intakeInFlight: true),
                       .sleeping(stage: 1), "an intake landing mid-cycle never wakes the page")
    }

    /// Z-B9 / Z-B11 — which line the slot shows, and when it ends.
    func test_theSlotsFeedLine_andWhatEndsIt() {
        XCTAssertEqual(RoomModel.feedPhase(drag: .overWorm, result: .refused(.unreadable), intakePhase: .idle),
                       .armed(overWorm: true), "a new drag outranks the last drop")
        XCTAssertNil(RoomModel.feedPhase(drag: nil, result: .handedOver, intakePhase: .idle))
        XCTAssertEqual(RoomModel.feedPhase(drag: nil, result: .handedOver, intakePhase: .reading(["a.json"])), .reading)
        let room = RoomModel()
        room.fed(.handedOver, state: .happy, reduceMotion: false)
        let outcome = IntakeOutcome(created: 3)
        XCTAssertNil(room.intakeChanged(from: .reading(["a.json"]), to: .preview(IntakePreview())))
        XCTAssertEqual(room.intakeChanged(from: .done(outcome), to: .idle), .landed(.added))
        XCTAssertEqual(room.feedResult, .landed(.added), "the landing outlives the done card")
        room.dismissSlot()
        XCTAssertNil(room.feedResult)
        let cancelled = RoomModel()
        cancelled.fed(.handedOver, state: .happy, reduceMotion: false)
        XCTAssertNil(cancelled.intakeChanged(from: .preview(IntakePreview()), to: .idle))
        XCTAssertNil(cancelled.feedResult, "a cancel goes back to the status")
        let live = RoomModel()
        live.fed(.handedOver, state: .happy, reduceMotion: false)
        live.dismissSlot()
        XCTAssertEqual(live.feedResult, .handedOver, "a live intake's line is still true")
        let poked = RoomModel()
        poked.fed(.busy, state: .happy, reduceMotion: false)
        poked.poke(answerCount: 2, state: .happy, reduceMotion: false)
        XCTAssertNil(poked.feedResult)
        XCTAssertEqual(poked.answerIndex, 0)
    }

    /// Final review, finding 1 (Task-3 review r1's M1) — the panel closed
    /// mid-import (`IntakeRouter.dismiss` keeps it running): the ending
    /// nobody sees ends the room's line too, so it dwells back to the status
    /// instead of covering it for good.
    func test_anImportThatEndsWithThePanelClosedEndsTheLine() {
        let outcome = IntakeOutcome(created: 3)
        let importing = IntakePhase.importing(IntakeProgress(total: 3, staged: nil))
        let unseen = RoomModel()
        unseen.fed(.handedOver, state: .happy, reduceMotion: false)
        XCTAssertNil(unseen.intakeChanged(from: .preview(IntakePreview()), to: importing, overlayPresented: false),
                     "an import still landing is still true")
        XCTAssertEqual(unseen.feedResult, .handedOver)
        XCTAssertEqual(unseen.intakeChanged(from: importing, to: .done(outcome), overlayPresented: false),
                       .landed(.added))
        XCTAssertEqual(unseen.feedResult, .landed(.added))
        unseen.dismissSlot()
        XCTAssertNil(unseen.feedResult, "Esc, the dwell and a mood change end it now")
        XCTAssertNil(unseen.intakeChanged(from: .done(outcome), to: .idle, overlayPresented: false),
                     "the later Done says nothing twice")

        let failed = RoomModel()
        failed.fed(.handedOver, state: .happy, reduceMotion: false)
        XCTAssertEqual(failed.intakeChanged(from: importing, to: .failed("x"), overlayPresented: false), .failedUnseen)
        XCTAssertTrue(failed.feedResult?.isTerminal == true)
        XCTAssertEqual(feedLine(.failedUnseen, asleep: false).tail, "Drop it again to open the panel.",
                       "never 'the panel says why' with no panel")

        let seen = RoomModel()
        seen.fed(.handedOver, state: .happy, reduceMotion: false)
        XCTAssertNil(seen.intakeChanged(from: importing, to: .done(outcome), overlayPresented: true),
                     "an open done card waits for Done")
        XCTAssertEqual(seen.feedResult, .handedOver)
    }

    /// Final review, finding 1 — the slot's ranking: a drag, then the answer
    /// the person asked for, then the feed line, then the status.
    func test_theSlotRanksDrag_thenAnswer_thenFeed_thenStatus() {
        let importing = IntakePhase.importing(IntakeProgress(total: 3, staged: nil))
        XCTAssertEqual(RoomModel.slot(drag: .overWorm, result: .handedOver, intakePhase: importing,
                                      answerIndex: 0, answerCount: 2), .feed(.armed(overWorm: true)))
        XCTAssertEqual(RoomModel.slot(drag: nil, result: .handedOver, intakePhase: importing,
                                      answerIndex: 1, answerCount: 2), .rung(1), "a poke shows what it announces")
        XCTAssertEqual(RoomModel.slot(drag: nil, result: .handedOver, intakePhase: importing,
                                      answerIndex: 2, answerCount: 2), .feed(.importing),
                       "an index that outlived its ladder is no rung")
        XCTAssertEqual(RoomModel.slot(drag: nil, result: nil, intakePhase: .idle,
                                      answerIndex: nil, answerCount: 2), .status)
        let room = RoomModel()
        room.poke(answerCount: 2, state: .happy, reduceMotion: false)
        room.fed(.handedOver, state: .happy, reduceMotion: false)
        XCTAssertEqual(RoomModel.slot(drag: room.drag, result: room.feedResult, intakePhase: importing,
                                      answerIndex: room.answerIndex, answerCount: 2), .feed(.importing),
                       "a new drop still wins: `fed` dismisses the answers")
    }

    /// I15 — a stale page never asks the router, so nothing is sent.
    func test_anOfflinePageSendsNothing() {
        XCTAssertEqual(roomFeedResult(reachable: false) { XCTFail("the router was asked"); return .accepted },
                       .unreachable)
        XCTAssertEqual(roomFeedResult(reachable: true) { .busy }, .busy)
        XCTAssertEqual(roomFeedResult(reachable: true) { .refused(.cicadaHome) }, .refused(.cicadaHome))
        XCTAssertEqual(roomFeedResult(reachable: true) { .accepted }, .handedOver)
    }

    // MARK: Lints — R-Z10: a door, never a second pipeline

    private func code(_ file: URL) throws -> [String] {
        try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.hasPrefix("//") }
    }

    func test_theRoomIsADoorOntoTheOneIntake() throws {
        var accepting: [String] = []
        var dropping: [String] = []
        for file in try SleepNumbersLintTests.sleepSources() {
            let lines = try code(file)
            for needle in ["sniffIntake(", "importIntake(", "uploadSaved(", "NSOpenPanel", "APIClient.shared"] {
                XCTAssertFalse(lines.contains { $0.contains(needle) }, "\(file.lastPathComponent) reaches past the router: \(needle)")
            }
            if lines.contains(where: { $0.contains(".accept(urls:") }) { accepting.append(file.lastPathComponent) }
            if lines.contains(where: { $0.contains(".onDrop(") }) { dropping.append(file.lastPathComponent) }
        }
        XCTAssertEqual(accepting, ["StudyRoom.swift"])
        XCTAssertEqual(dropping, ["StudyRoom.swift"])
        let room = try code(try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "StudyRoom.swift" }!)
        XCTAssertTrue(room.contains { $0.contains("from: .sleepRoom") })
        XCTAssertTrue(room.contains { $0.contains("RoomDropDelegate(") })
    }

    func test_theHintIsTrueNowThatFeedingShipped() {
        XCTAssertEqual(Copy.wormHint, "Click to ask what it's doing. Drop a file to import it.")
        XCTAssertEqual(Copy.feedAFile, "Feed a file…")
    }
}
