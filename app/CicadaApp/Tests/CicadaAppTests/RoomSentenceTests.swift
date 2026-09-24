import XCTest
@testable import CicadaApp

/// Track Z, Z2 — the sentence slot (R-Z5, R-Z13, design §5). Every row of the
/// lead table (L1–L11, plus this plan's L8b) and the tail table (T1–T14) is
/// a case, then the rules that cut across all of them.
final class RoomSentenceTests: XCTestCase {

    private let en = Locale(identifier: "en_US")

    private func debt(_ unprocessed: Int, hasRunBefore: Bool = true, hours: Double? = 2,
                      rested: Int? = 60) -> SleepDebtView {
        SleepDebtView(restedPct: rested, volumePct: 0, agePct: 0, unprocessedCount: unprocessed,
                      hasRunBefore: hasRunBefore, hoursSinceLastCycle: hours)
    }

    private func ctx(_ mood: BookwormState, debt: SleepDebtView? = nil,
                     _ edit: (inout RoomContext) -> Void = { _ in }) -> RoomContext {
        var c = RoomContext(mood: mood, debt: debt, scheduleMode: "daily", locale: en)
        edit(&c)
        return c
    }

    // MARK: The lead (§5, first matching row wins)

    func test_L1_theQueueCouldNotLoad() {
        let line = roomSentence(ctx(.happy) { $0.queueLoad = .failed("Couldn't load status") })
        XCTAssertEqual(line.lead, "I can't see the queue.")
        XCTAssertEqual(line.tone, .danger)
        XCTAssertEqual(line.tail, "Couldn't load status")
        XCTAssertEqual(line.action, .retry, "T1")
    }

    func test_L2_theQueueIsLoading() {
        let line = roomSentence(ctx(.happy) { $0.queueLoad = .loading })
        XCTAssertEqual(line.lead, "Checking what's waiting…")
        XCTAssertNil(line.tail)
    }

    func test_L3_L4_readingNamesItsTwoNumbersOnlyWhenItHasThem() {
        let counted = roomSentence(ctx(.sleeping(stage: 1)) { $0.activeStage = 1; $0.read = 138; $0.total = 203 })
        XCTAssertEqual(counted.lead, "Reading 138 of 203.")
        XCTAssertEqual(counted.numeral, "138 of 203")
        XCTAssertEqual(counted.tail, SleepStages.all[0].detail, "T2 — the stage's own detail (P16)")
        XCTAssertEqual(roomSentence(ctx(.sleeping(stage: 1)) { $0.activeStage = 1 }).lead, "Reading…")
    }

    func test_L5_laterStagesSayWhatTheyAreDoing() {
        for (stage, lead) in [(2, "Sorting…"), (3, "Deciding…"), (4, "Noticing…"), (5, "Filing…")] {
            let line = roomSentence(ctx(.sleeping(stage: stage)) { $0.activeStage = stage })
            XCTAssertEqual(line.lead, lead)
            XCTAssertEqual(line.tail, SleepStages.all[stage - 1].detail)
        }
        XCTAssertEqual(SleepStages.all.map(\.progressive), ["Reading", "Sorting", "Deciding", "Noticing", "Filing"])
    }

    func test_L6_T3_aFailureLeadsWithItsFirstClause() {
        let line = roomSentence(ctx(.error) { $0.cycleError = "claude exited 1: rate limited\nTraceback (most recent call last)" })
        XCTAssertEqual(line.lead, "The last cycle failed.")
        XCTAssertEqual(line.tone, .danger)
        XCTAssertEqual(line.tail, "claude exited 1: rate limited")
        XCTAssertEqual(line.tailTone, .danger)
        XCTAssertEqual(line.action, .openDetails(.lastCycle))
    }

    func test_L7_digesting() {
        XCTAssertEqual(roomSentence(ctx(.digesting)).lead, "Filed.")
    }

    func test_L8_theCountIsTheNumeral_andOverdueIsAWord() {
        let reading = roomSentence(ctx(.reading, debt: debt(47)))
        XCTAssertEqual(reading.lead, "47 to read.")
        XCTAssertEqual(reading.numeral, "47")
        XCTAssertNil(reading.qualifier)
        let hungry = roomSentence(ctx(.hungry, debt: debt(1234, rested: 10)))
        XCTAssertEqual(hungry.lead, "1,234 to read — overdue.")
        XCTAssertEqual(hungry.numeral, "1,234")
        XCTAssertEqual(hungry.qualifier, "overdue")
        XCTAssertEqual(hungry.tone, .warning)
        // P9: a bank that has never consolidated is not "overdue" — T8 says why.
        let firstNight = roomSentence(ctx(.hungry, debt: debt(12, hasRunBefore: false, rested: 10)))
        XCTAssertEqual(firstNight.lead, "12 to read.")
        XCTAssertEqual(firstNight.tail, "My first night — nothing's been filed yet.")
    }

    /// Z-P6 — the design's table has no row for `.reading` with nothing
    /// counted yet, which is exactly an import landing (`intakeInFlight`).
    func test_L8b_somethingJustArrived() {
        XCTAssertEqual(roomSentence(ctx(.reading, debt: debt(0))).lead, "Something new just arrived.")
    }

    func test_L9_L10_L11() {
        XCTAssertEqual(roomSentence(ctx(.hungry, debt: debt(0, hours: 80))).lead, "Nothing new to read.")
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0))).lead, "All caught up.")
        XCTAssertEqual(roomSentence(ctx(.awake)).lead, "Listening.")
    }

    // MARK: The tail (§5, first matching row wins — news outranks everything)

    func test_T4_T5_T6_theNewsTails() {
        let cancelled = roomSentence(ctx(.happy, debt: debt(0)) { $0.cancelled = true })
        XCTAssertEqual(cancelled.tail, "Stopped early — nothing was lost.")
        XCTAssertEqual(cancelled.action, .openDetails(.lastCycle))
        let capped = roomSentence(ctx(.reading, debt: debt(40)) { $0.capped = true })
        XCTAssertEqual(capped.tail, "The rest wait for the next cycle.")
        let warned = roomSentence(ctx(.happy, debt: debt(0)) { $0.indexWarning = "index rebuild failed" })
        XCTAssertEqual(warned.tail, "Finished with a warning — it's in Details.")
        XCTAssertEqual(warned.tailTone, .warning)
    }

    func test_newsOutranksTheStateTails() {
        let failedAndCancelled = roomSentence(ctx(.error) { $0.cycleError = "boom"; $0.cancelled = true })
        XCTAssertEqual(failedAndCancelled.tail, "boom", "T3 before T4")
        let runningAndCancelled = roomSentence(ctx(.sleeping(stage: 2)) { $0.activeStage = 2; $0.cancelled = true })
        XCTAssertEqual(runningAndCancelled.tail, SleepStages.all[1].detail, "T2 before T4")
        let cancelledFirstNight = roomSentence(ctx(.reading, debt: debt(3, hasRunBefore: false)) { $0.cancelled = true })
        XCTAssertEqual(cancelledFirstNight.tail, "Stopped early — nothing was lost.", "T4 before T8")
    }

    /// T7 — below the news (T3–T6), above the first-night and state tails.
    func test_T7_seeWhatChanged() {
        let line = roomSentence(ctx(.digesting, debt: debt(0)) { $0.recentCycleCommit = "c0ffee" })
        XCTAssertEqual(line.tail, "See what changed ›")
        XCTAssertEqual(line.action, .whatChanged)
        let warned = roomSentence(ctx(.happy, debt: debt(0)) { $0.recentCycleCommit = "c0ffee"; $0.indexWarning = "w" })
        XCTAssertEqual(warned.tail, "Finished with a warning — it's in Details.", "T6 before T7")
        let firstNight = roomSentence(ctx(.happy, debt: debt(0, hasRunBefore: false)) { $0.recentCycleCommit = "c0ffee" })
        XCTAssertEqual(firstNight.tail, "See what changed ›", "T7 before T9")
    }

    func test_T8_T9_theFirstNight() {
        XCTAssertEqual(roomSentence(ctx(.reading, debt: debt(3, hasRunBefore: false))).tail,
                       "My first night — nothing's been filed yet.")
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0, hasRunBefore: false))).tail,
                       "Nothing's been filed in this memory yet.")
        XCTAssertNotEqual(roomSentence(ctx(.happy, debt: nil)).tail, "Nothing's been filed in this memory yet.",
                          "an unloaded debt is never reported as a first night")
    }

    func test_T10_theDaysOnlyWhenTheGapIsLong() {
        XCTAssertEqual(roomSentence(ctx(.hungry, debt: debt(9, hours: 72, rested: 10))).tail, "It's been 3 days.")
        XCTAssertNil(roomSentence(ctx(.hungry, debt: debt(9, hours: 47, rested: 10))).tail, "under two days, no day count")
    }

    func test_T11_theLampIsOffOnlyWhenSomethingWaits() {
        let off = roomSentence(ctx(.reading, debt: debt(5)) { $0.scheduleMode = "manual" })
        XCTAssertEqual(off.tail, "The lamp is off — I read when you ask.")
        XCTAssertEqual(off.action, .openLamp)
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0)) { $0.scheduleMode = "manual" }).tail,
                       "Drop a file on me to add it to the pile.",
                       "nothing waits, so no lamp line — T13 speaks instead")
    }

    func test_T12_theBigPile_orNothingWhenItWouldNotFit() {
        let line = roomSentence(ctx(.reading, debt: debt(5)) { $0.topOriginLabel = "Claude Code"; $0.topOrigin = "claude-code" })
        XCTAssertEqual(line.tail, "The Claude Code pile is the big one.")
        XCTAssertEqual(line.mark, .origin("claude-code"), "a named source wears its mark (Z-P26)")
        let long = String(repeating: "x", count: 70)
        XCTAssertNil(roomSentence(ctx(.reading, debt: debt(5)) { $0.topOriginLabel = long }).tail)
    }

    /// T13 (Z-B19) — feeding shipped, so a happy worm invites a file.
    func test_T13_aHappyWormInvitesAFile() {
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0))).tail, "Drop a file on me to add it to the pile.")
        XCTAssertNil(roomSentence(ctx(.happy, debt: debt(0))).mark)
        XCTAssertEqual(roomSentence(ctx(.happy, debt: debt(0, hasRunBefore: false))).tail,
                       "Nothing's been filed in this memory yet.", "T9 before T13")
        XCTAssertNil(roomSentence(ctx(.happy, debt: debt(0)) { $0.queueLoad = .loading }).tail,
                     "no invitation while the queue is still loading")
    }

    /// T14 — the no-tail case moved to `.digesting` once T13 claimed `.happy`'s (Z-B19).
    func test_T14_nothingToAdd() {
        XCTAssertNil(roomSentence(ctx(.digesting, debt: debt(0))).tail)
        XCTAssertNil(roomSentence(ctx(.digesting, debt: debt(0))).mark, "no service named, no mark")
    }

    // MARK: The rules across every row (R-Z13)

    private var matrix: [RoomContext] {
        var out: [RoomContext] = []
        let moods: [BookwormState] = [.awake, .happy, .reading, .hungry, .digesting, .error,
                                      .sleeping(stage: 1), .sleeping(stage: 3), .sleeping(stage: 5)]
        for mood in moods {
            for count in [0, 1, 47, 1_234_567] {
                for firstRun in [false, true] {
                    out.append(ctx(mood, debt: debt(count, hasRunBefore: !firstRun, hours: 96, rested: 5)) {
                        $0.activeStage = mood.stageNumber == 0 ? nil : mood.stageNumber
                        $0.read = count / 2; $0.total = count
                        $0.cycleError = mood == .error ? String(repeating: "error text ", count: 20) : nil
                        $0.scheduleMode = firstRun ? "manual" : "daily"
                        $0.topOriginLabel = "Safari bookmarks"
                    })
                }
            }
        }
        return out
    }

    func test_everyLineFitsItsBudget_andSaysNothingItMayNot() {
        let banned = ["est", "cluster", "insight"]
        for c in matrix {
            let line = roomSentence(c)
            XCTAssertFalse(line.lead.isEmpty, "\(c.mood.caseName) has no lead")
            XCTAssertLessThanOrEqual(line.lead.count, SentenceLine.maxLead, line.lead)
            XCTAssertLessThanOrEqual(line.tail?.count ?? 0, SentenceLine.maxTail, line.tail ?? "")
            for text in [line.lead, line.tail ?? ""] {
                XCTAssertFalse(text.contains("!"), text)
                XCTAssertFalse(text.contains("%"), text)
                XCTAssertFalse(text.contains("~"), text)
                let words = text.lowercased().split { !$0.isLetter }.map(String.init)
                for word in banned { XCTAssertFalse(words.contains(word), "'\(word)' in \(text)") }
            }
        }
    }

    /// The numeral is `heroCount`, formatted — the hero and the sentence can
    /// never disagree because the sentence asks the same function.
    func test_theNumeralIsHeroCount() {
        for mood in [BookwormState.reading, .hungry] {
            for count in [1, 47, 1234] {
                let d = debt(count, rested: 10)
                XCTAssertEqual(roomSentence(ctx(mood, debt: d)).numeral,
                               heroCount(mood, debt: d).map { UsageFormat.count($0, locale: en) })
            }
        }
    }

    func test_isDeterministic_R8() {
        for c in matrix { XCTAssertEqual(roomSentence(c), roomSentence(c)) }
    }

    // MARK: Rendering helpers

    func test_sentenceRuns_splitTheLeadIntoWhatTheViewDrawsDifferently() {
        let line = SentenceLine(lead: "47 to read — overdue.", numeral: "47", qualifier: "overdue", tone: .warning)
        XCTAssertEqual(sentenceRuns(line), [SentenceRun(text: "47", kind: .numeral),
                                            SentenceRun(text: " to read — ", kind: .plain),
                                            SentenceRun(text: "overdue", kind: .qualifier),
                                            SentenceRun(text: ".", kind: .plain)])
        XCTAssertEqual(sentenceRuns(line).map(\.text).joined(), line.lead)
        XCTAssertEqual(sentenceRuns(SentenceLine(lead: "Filed.")), [SentenceRun(text: "Filed.", kind: .plain)])
    }

    /// Z-P8 — the link is the words after the tail's last " — ", else the whole tail.
    func test_tailLink_isTheLastWords() {
        XCTAssertEqual(tailLink("Stopped early — nothing was lost."), "nothing was lost.")
        XCTAssertEqual(tailLink("See what changed ›"), "See what changed ›")
    }

    func test_sentenceClause_isOneLineCutOnAWord() {
        XCTAssertEqual(sentenceClause("a\nb"), "a")
        XCTAssertNil(sentenceClause("  \n"))
        let long = sentenceClause(String(repeating: "word ", count: 40))!
        XCTAssertLessThanOrEqual(long.count, SentenceLine.maxTail)
        XCTAssertTrue(long.hasSuffix("word…"), long)
    }

    func test_sentenceCase_capitalisesAndCloses() {
        XCTAssertEqual(sentenceCase("scheduled cycle — using the configured API model"),
                       "Scheduled cycle — using the configured API model.")
        XCTAssertEqual(sentenceCase("Already a sentence."), "Already a sentence.")
        XCTAssertNil(sentenceCase(" "))
    }

    // MARK: The control row and the whisper line

    func test_whisperLine_isTheLampsTwinInWords() {
        XCTAssertEqual(whisperLine(scheduleText: "Every day at 03:00", nextRunText: "Next run Sep 24, 3:00 AM", lampLit: true),
                       "Every day at 03:00 · Next run Sep 24, 3:00 AM")
        XCTAssertEqual(whisperLine(scheduleText: Copy.nextRunManual, nextRunText: Copy.nextRunManual, lampLit: false),
                       "Manual only — the lamp is off")
    }

    /// R-HS9 — the caption is what Cancel does while a cycle runs, and nothing otherwise: the
    /// engine menu beside the control names what a click would run.
    func test_controlCaption() {
        XCTAssertNil(controlCaption(isRunning: false), "R-HS9 — the engine menu names the engine")
        XCTAssertEqual(controlCaption(isRunning: true), Copy.cancelCaption)
    }

    /// R-Z5 — the bubble is retired from the page.
    func test_theSpeechBubbleIsGone() throws {
        for file in try SleepNumbersLintTests.sleepSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("SpeechBubbleView"), file.lastPathComponent)
        }
    }
}
