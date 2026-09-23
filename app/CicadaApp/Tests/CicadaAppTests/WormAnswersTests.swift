import XCTest
@testable import CicadaApp

/// Track Z §6.3 — the answer ladder. A click steps through true lines; a rung
/// whose facts are unknown is omitted; no rung repeats the status sentence's
/// numeral; nothing reads a clock (R8).
final class WormAnswersTests: XCTestCase {

    private let en = Locale(identifier: "en_US")
    private let last = LastCycleFacts(episodes: 12, created: 3, updated: 5, durationText: "4 m 12 s")

    private func ctx(_ mood: BookwormState, _ edit: (inout RoomContext) -> Void = { _ in }) -> RoomContext {
        var c = RoomContext(mood: mood,
                            debt: SleepDebtView(restedPct: 60, volumePct: 0, agePct: 0, unprocessedCount: 47,
                                                hasRunBefore: true, hoursSinceLastCycle: 30),
                            scheduleMode: "daily", locale: en)
        c.oldestWait = "3 days"; c.lampLit = true; c.nextRunWhen = "Sep 24, 3:00 AM"
        c.lastCycle = last; c.inboxTotal = 2
        edit(&c)
        return c
    }

    func test_readingAsksWhatWhenLastTimeAndYou() {
        let rungs = wormAnswers(ctx(.reading))
        XCTAssertEqual(rungs.map(\.lead), ["Waiting for a night.", "Next: Sep 24, 3:00 AM.",
                                           "Last time I read 12 episodes.", "2 questions wait for you."])
        XCTAssertEqual(rungs[0].tail, "The oldest has waited 3 days.")
        XCTAssertEqual(rungs[2].tail, "+3 new · 5 updated, in 4 m 12 s.")
        XCTAssertEqual(rungs[2].action, .openDetails(.pastNights))
        XCTAssertEqual(rungs[3].tail, "They're in the Inbox.")
        XCTAssertEqual(rungs[3].action, .openInbox, "spec decision 16 — the last rung may point to the Inbox")
    }

    func test_theWhenRung_namesTheScheduledEngineOnlyWhenItDiffers() {
        XCTAssertNil(wormAnswers(ctx(.happy))[1].tail)
        XCTAssertNil(wormAnswers(ctx(.happy))[1].mark)
        let differs = wormAnswers(ctx(.happy) { $0.scheduledEngine = "ollama" })
        XCTAssertEqual(differs[1].tail, "Scheduled runs use Ollama (on this Mac).")
        XCTAssertEqual(differs[1].mark, .engine("ollama"), "a named engine wears its mark (Z-P26)")
    }

    func test_theLampOffRungPointsAtTheLamp() {
        let rung = wormAnswers(ctx(.reading) { $0.lampLit = false; $0.nextRunWhen = nil })[1]
        XCTAssertEqual(rung.lead, "The lamp is off — I read when you ask.")
        XCTAssertEqual(rung.action, .openLamp)
    }

    func test_unknownFactsOmitTheirRung() {
        let sparse = wormAnswers(ctx(.happy) { $0.nextRunWhen = nil; $0.lastCycle = nil; $0.inboxTotal = 0 })
        XCTAssertEqual(sparse.map(\.lead), ["Nothing to read."])
        let noEpisodes = wormAnswers(ctx(.happy) {
            $0.lastCycle = LastCycleFacts(episodes: 0, created: 0, updated: 0, durationText: nil)
        })
        XCTAssertFalse(noEpisodes.contains { $0.lead.hasPrefix("Last time") }, "0 is an older backend's unknown")
        let noDuration = wormAnswers(ctx(.happy) { $0.lastCycle = LastCycleFacts(episodes: 1, created: 0, updated: 2, durationText: nil) })
        XCTAssertEqual(noDuration[2].lead, "Last time I read 1 episode.")
        XCTAssertEqual(noDuration[2].tail, "+0 new · 2 updated.")
        XCTAssertEqual(wormAnswers(ctx(.happy) { $0.inboxTotal = 1 }).last?.lead, "1 question waits for you.")
    }

    func test_whileSleepingItNamesTheStageAndTheEngine() {
        let rungs = wormAnswers(ctx(.sleeping(stage: 2)) {
            $0.activeStage = 2; $0.lastEngine = "claude-cli"; $0.engineDetail = "your plan is connected"
        })
        XCTAssertEqual(rungs.map(\.lead), ["Stage 2 · Sort.", "Running on Claude Code (your plan)."])
        XCTAssertEqual(rungs[0].tail, SleepStages.all[1].detail)
        XCTAssertEqual(rungs[1].tail, "Your plan is connected.")
        XCTAssertEqual(rungs[1].mark, .engine("claude-cli"))
    }

    func test_digestingErrorAndAwake() {
        let digesting = wormAnswers(ctx(.digesting) { $0.cycleCreated = 4; $0.cycleUpdated = 9 })
        XCTAssertEqual(digesting.first?.lead, "Just filed that cycle.")
        XCTAssertEqual(digesting.first?.tail, "+4 new · 9 updated.")
        XCTAssertEqual(digesting.count, 2)
        let error = wormAnswers(ctx(.error) { $0.cycleError = "claude exited 1"; $0.lastEngine = "ollama" })
        XCTAssertEqual(error.map(\.lead), ["The last cycle failed.", "It ran on Ollama (on this Mac).",
                                           "Last time I read 12 episodes."])
        XCTAssertEqual(error[0].action, .openDetails(.lastCycle))
        XCTAssertEqual(wormAnswers(ctx(.awake)).map(\.lead), ["I haven't heard from Cicada yet."])
    }

    /// R-Z7 — answers never restate the figure the status sentence shows.
    func test_noRungRepeatsTheStatusNumeral() {
        let c = ctx(.reading)
        let numeral = roomSentence(c).numeral!
        for rung in wormAnswers(c) { XCTAssertFalse(rung.spoken.contains(numeral), rung.spoken) }
    }

    /// The ladder's own fit filter drops an over-budget rung silently, so a
    /// per-rung length check alone could never fail (review r1): the count
    /// per mood is pinned too, so a rung that vanishes fails here. The engine
    /// detail is 80 characters with no stop — the edge where a clause plus
    /// `sentenceCase`'s "." used to lose the whole engine rung.
    func test_everyRungFitsAndSaysNothingItMayNot() {
        let detail = String(repeating: "abcd ", count: 15) + "abcde"
        XCTAssertEqual(detail.count, SentenceLine.maxTail)
        let expected: [(BookwormState, Int)] = [(.awake, 1), (.happy, 4), (.reading, 4), (.hungry, 4),
                                                (.digesting, 2), (.error, 3), (.sleeping(stage: 4), 2)]
        for (mood, count) in expected {
            let rungs = wormAnswers(ctx(mood) {
                $0.activeStage = 4; $0.lastEngine = "litellm"; $0.cycleError = "boom"; $0.engineDetail = detail
            })
            XCTAssertEqual(rungs.count, count, "\(mood): \(rungs.map(\.lead))")
            for rung in rungs {
                XCTAssertLessThanOrEqual(rung.lead.count, SentenceLine.maxLead, rung.lead)
                XCTAssertLessThanOrEqual(rung.tail?.count ?? 0, SentenceLine.maxTail)
                XCTAssertFalse(rung.spoken.contains("!") || rung.spoken.contains("%") || rung.spoken.contains("~"))
            }
        }
    }

    /// R8 — clock-free, by construction and by grep.
    func test_isDeterministicAndClockFree() throws {
        XCTAssertEqual(wormAnswers(ctx(.reading)), wormAnswers(ctx(.reading)))
        let file = try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "WormAnswers.swift" }!
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("Date("))
        XCTAssertFalse(text.contains(".now"))
    }
}
