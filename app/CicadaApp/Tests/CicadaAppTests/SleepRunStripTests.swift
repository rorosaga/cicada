import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The Sleep page's running state as one quiet object (2026-11-26; it was a stack of seven or eight things under the
/// room: the chip, an explaining sentence, a five-step stepper, a bar, a legend of five counts, an elapsed caption and
/// the engine's note).
///
/// Four kinds of test: what the object says in every run state (pure, `RunLine`), that nothing is said twice, the
/// geometry of the real block laid out offscreen (the bar spans the block, the count sits on its trailing edge, the
/// block is the room's height and nothing hangs under the pair), and the snapshots of the page's real layout beside the
/// room — `CICADA_RUN_STRIP_SNAPSHOTS=<dir>` writes every run state, dark and light, at the 1440 and 1079 pt windows and
/// in the narrow layout, for a person to look at.
@MainActor
final class SleepRunStripTests: XCTestCase {
    override func setUp() {
        CicadaTheme.uiScale = 1
        CicadaTheme.mode = .dark
    }

    override func tearDown() {
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private static func line(_ status: SleepStatusResponse, finished: Bool = false, owner: Bool = false) -> RunLine? {
        RunLine.from(page(status, justFinished: finished), recentCycleCommit: finished ? "abc1234" : nil,
                     canOpenOwnerPage: owner, locale: en)
    }

    // MARK: - What the object says, state by state

    /// While stage k runs the word is that step's own, in one word, with the live mark; the run's one count is
    /// conversations filed of the ones frozen at its start and the time it has read, both from the drain — never the
    /// batch's own "14 of 25".
    func test_eachRunningStageIsOneWordTheRunsCountAndItsTime() throws {
        for stage in 1...5 {
            let run = try XCTUnwrap(Self.line(Self.running(stage: stage)), "stage \(stage)")
            XCTAssertEqual(run.kind, .running)
            XCTAssertEqual(run.word, SleepStages.all[stage - 1].progressive, "the step, in one word")
            XCTAssertTrue(run.live, "a quiet mark while a step runs")
            XCTAssertEqual(run.count, "74 of 287", "conversations filed of the ones frozen — not the batch's own count")
            XCTAssertEqual(run.elapsed, "27 min")
            XCTAssertEqual(run.trailing, ["74 of 287", "27 min"])
            XCTAssertEqual(run.progress?.frozen, 287)
            XCTAssertFalse(run.indeterminate)
            XCTAssertFalse((run.help ?? "").isEmpty, "the stage's purpose is the word's tooltip, not a line")
        }
    }

    /// Only a note that changes what the person should do or expect may sit under the bar, one at a time: the batch's
    /// unreadable conversations (a glyph beside words, DR-7), what a stop does while it files, the first run's link.
    func test_onlyANoteThatChangesWhatToExpectSitsUnderTheBar() throws {
        XCTAssertNil(try XCTUnwrap(Self.line(Self.running(stage: 3))).note, "no explaining sentence while it runs")
        XCTAssertNil(try XCTUnwrap(Self.line(Self.running(stage: 1))).note)
        let filing = try XCTUnwrap(Self.line(Self.running(stage: 5)))
        XCTAssertEqual(filing.note, RunLine.Note(text: Copy.SleepV5.filingWhisper))
        let failures = try XCTUnwrap(Self.line(Self.running(stage: 1, failed: 2)))
        XCTAssertEqual(failures.note?.style, .caution)
        XCTAssertEqual(failures.note?.text, "2 could not be read, it gets one more try")
        let first = try Self.running(stage: 3, firstRun: true)
        XCTAssertNil(Self.line(first)?.note, "the link needs the owner's page to open")
        XCTAssertEqual(Self.line(first, owner: true)?.note, RunLine.Note(text: Copy.SleepV5.seeYourPage, style: .ownerPage))
    }

    /// The old single-pass shape has no countable total: the word and an indeterminate bar, never a made-up fraction
    /// (P15).
    func test_aRunWithNothingCountableIsIndeterminateNeverAFraction() throws {
        let run = try XCTUnwrap(Self.line(Self.singlePass()))
        XCTAssertEqual(run.kind, .running)
        XCTAssertNil(run.progress, "no fill without a counted quantity")
        XCTAssertTrue(run.indeterminate)
        XCTAssertNil(run.count)
    }

    func test_pausingAndWaitingForTheNetworkAreTheSameObject() throws {
        var model = Self.page(try Self.running(stage: 2))
        model.pausing = true
        let pausing = try XCTUnwrap(RunLine.from(model, locale: Self.en))
        XCTAssertEqual(pausing.kind, .pausing)
        XCTAssertEqual(pausing.word, "Pausing…")
        XCTAssertEqual(pausing.count, "74 of 287")
        let network = try XCTUnwrap(Self.line(Self.running(stage: 1, waiting: "connection")))
        XCTAssertEqual(network.kind, .waiting)
        XCTAssertEqual(network.word, "Waiting for the network")
        XCTAssertFalse(network.live, "nothing is reading while it waits")
        XCTAssertEqual(network.help, Copy.SleepV5.waitingForNetworkTail("connection"))
    }

    /// Paused keeps the pause's own words (why, and what to do), with the bar held; the count is in those words, so it
    /// is not said again on the trailing edge.
    func test_pausedKeepsThePausesOwnWordsAndHoldsTheBar() throws {
        for reason in ["user", "plan_window", "engine", "restart"] {
            let status = try Self.paused(reason)
            let run = try XCTUnwrap(Self.line(status), reason)
            let sentence = roomSentence(Self.page(status).roomContext(locale: Self.en))
            XCTAssertEqual(run.kind, .paused)
            XCTAssertTrue(sentence.lead.hasPrefix(run.word), "\(reason): the lead, ending on its last word")
            XCTAssertFalse(run.live)
            XCTAssertNil(run.count, "the pause's tail already says how many are filed")
            XCTAssertEqual(run.note?.text, sentence.tail, "\(reason): what to do, in the pause's own words")
            XCTAssertNotNil(run.progress, "the bar is held where the run stopped")
        }
    }

    /// A finished run: what it filed, the bar full, the way to what changed. Nothing cheers; no count of its own.
    func test_justFinishedIsFiledNWithTheBarFullAndTheWayToWhatChanged() throws {
        let run = try XCTUnwrap(Self.line(Self.finished(), finished: true))
        XCTAssertEqual(run.kind, .finished)
        XCTAssertEqual(run.word, "Filed 7 conversations")
        XCTAssertFalse(run.live)
        XCTAssertNil(run.count, "the word is the count")
        XCTAssertEqual(try XCTUnwrap(run.progress).filedFraction, 1, accuracy: 1e-9)
        XCTAssertEqual(run.note, RunLine.Note(text: "See what changed ›", style: .link, action: .whatChanged))
        XCTAssertNil(Self.line(try Self.finished()), "the object goes once the window for its link has")
    }

    /// What the frozen stepper showed, said once: the step a stop reached, with the bar where it stopped.
    func test_aStoppedOrFailedRunSaysWhereItStopped() throws {
        let stopped = try XCTUnwrap(Self.line(Self.cancelled()))
        XCTAssertEqual(stopped.kind, .stopped)
        XCTAssertTrue(stopped.word.hasPrefix("Stopped while "), stopped.word)
        XCTAssertNotNil(stopped.count)
        XCTAssertNotNil(stopped.progress, "the bar stays where it stopped")
        XCTAssertEqual(stopped.note?.text, Copy.SleepV5.stoppedKeepsFiled)
        XCTAssertEqual(stopped.note?.style, .detail, "a whole sentence is never accent-blue")
        let failed = try XCTUnwrap(Self.line(Self.failed()))
        XCTAssertEqual(failed.kind, .failed)
        XCTAssertTrue(failed.word.hasPrefix("Stopped while "), failed.word)
        XCTAssertTrue(failed.warns, "a failed run wears a glyph beside its words, never colour alone (DR-7)")
        XCTAssertEqual(failed.note?.text, Copy.SleepV5.readingStoppedTail)
        XCTAssertEqual(failed.note?.action, .openDetails(.lastCycle))
    }

    /// A page at rest, a night the write window refused and an empty page have no run: the chip stays.
    func test_noRunNoObject() throws {
        XCTAssertNil(Self.line(try Self.empty()))
        XCTAssertNil(Self.line(try Self.refusedNight()))
        XCTAssertNil(Self.line(try Self.refusedNight(gaveUp: true)))
    }

    /// Say it once (DR-38): no fact is on screen twice in the object, and none of the old stack's words survive on it
    /// (the batch's position, "waiting", "calls made", "Running 27 m", a stage's explaining sentence).
    func test_noFactIsOnScreenTwiceAndTheOldStacksWordsAreGone() throws {
        let states: [(String, RunLine?)] = try [
            ("running-1", Self.line(Self.running(stage: 1))), ("running-2", Self.line(Self.running(stage: 2))),
            ("running-5", Self.line(Self.running(stage: 5))), ("paused", Self.line(Self.paused("user"))),
            ("paused-window", Self.line(Self.paused("plan_window"))), ("stopped", Self.line(Self.cancelled())),
            ("failed", Self.line(Self.failed())), ("finished", Self.line(Self.finished(), finished: true)),
        ]
        for (name, run) in states {
            let run = try XCTUnwrap(run, name)
            let said = [run.word, run.count, run.elapsed, run.note?.text].compactMap { $0 }
            XCTAssertEqual(Set(said).count, said.count, "\(name): nothing repeated — \(said)")
            let all = said.joined(separator: " ")
            for stale in ["Batch ", "calls made", "Running ", "read, waiting to file"] {
                XCTAssertFalse(all.contains(stale), "\(name): \"\(stale)\" left the screen — \(all)")
            }
            if let count = run.count, let note = run.note?.text {
                for number in count.split(separator: " ").filter({ Int($0) != nil }) {
                    XCTAssertFalse(note.contains(number), "\(name): the count \(count) is not said again in \"\(note)\"")
                }
            }
        }
        for stage in 1...5 {
            let run = try XCTUnwrap(Self.line(Self.running(stage: stage)))
            XCTAssertNotEqual(run.help, run.word)
        }
    }

    /// What the old legend and the stage caption printed is the bar's tooltip and VoiceOver's value, not a line: the batch's
    /// position, what waits, the calls made.
    func test_theLegendIsTheBarsTooltipAndItsVoiceOverValue() throws {
        let progress = try XCTUnwrap(try XCTUnwrap(Self.line(Self.running(stage: 2))).progress)
        let value = progress.accessibilityValue(locale: Self.en)
        for part in ["Batch 4 of 12", "74 filed", "222 calls made", "waiting"] {
            XCTAssertTrue(value.contains(part), "\(part) is in \"\(value)\"")
        }
    }

    /// "This run keeps the engine it started on" is the engine label's tooltip while a run reads, and the label's
    /// ordinary tooltip otherwise — said nowhere else on the page.
    func test_theEnginesRunNoteMovedIntoItsTooltip() {
        XCTAssertEqual(EngineLabelHelp.text(runKeepsEngine: true), Copy.EngineMenu.runKeepsEngine)
        XCTAssertEqual(EngineLabelHelp.text(runKeepsEngine: false), Copy.EngineMenu.moreInSettings)
    }

    /// The pause's armed automatic continue (ruling 15) is said once, in the note's own words; why it will is the note's
    /// tooltip, not a second line under the pair.
    func test_anArmedContinueIsOneNoteWhoseWhyIsItsTooltip() throws {
        var model = Self.page(try Self.paused("plan_window"))
        model.autoContinueWhen = "3:14 PM"
        let run = try XCTUnwrap(RunLine.from(model, locale: Self.en))
        XCTAssertEqual(run.note?.help, Copy.SleepV5.willContinueBySelf("3:14 PM"))
        XCTAssertTrue(run.note?.text.contains("Continues after") == true, run.note?.text ?? "")
    }

    // MARK: - Geometry, from the real block

    /// The pixels of the real pinned block (drawn through a hosting view, as the page is): the bar is the block's full
    /// width, on its left edge, a thin line; the run's count sits flush on the trailing edge; the run bar's card (the
    /// controls) is the same width — one column, one alignment.
    func test_theBarSpansTheBlockAndTheCountSitsOnItsTrailingEdge() async throws {
        let width = Self.wordsWidth(window: 1440)
        for (name, status, finished) in try Self.runStates() {
            let host = try await Self.host()
            host.sleep.status = status
            let view = Self.environment(Self.pinned(status, finished: finished, host: host, width: width, cell: 3),
                                        host: host)
            let bands = try Self.hostedBands(of: view, width: width)
            let bar = try XCTUnwrap(bands.first { $0.bottom - $0.top + 1 <= 6 && $0.right - $0.left >= width - 4 },
                                    "\(name): a thin bar across the block — \(bands)")
            XCTAssertLessThanOrEqual(bar.left, 1.5, "\(name): the bar starts on the block's edge")
            XCTAssertGreaterThanOrEqual(bar.right, width - 1.5, "\(name): and ends on the other")
            let card = try XCTUnwrap(bands.last, "\(name): the run bar")
            XCTAssertEqual(card.left, bar.left, accuracy: 1.5, "\(name): the run bar's card shares the bar's left edge")
            XCTAssertEqual(card.right, bar.right, accuracy: 1.5, "\(name): and its right edge")
            let above = try XCTUnwrap(bands.last { $0.bottom < bar.top }, "\(name): the line over the bar")
            XCTAssertLessThanOrEqual(above.left, 1.5, "\(name): the word keeps the block's left edge")
            if let run = RunLine.from(Self.page(status, justFinished: finished),
                                      recentCycleCommit: finished ? "abc1234" : nil, locale: Self.en), run.count != nil {
                XCTAssertGreaterThanOrEqual(above.right, width - 3, "\(name): the count is flush right — \(bands)")
            }
        }
    }

    /// The rows of ink in a hosted render, at 1 pt per row: each run of pixel rows that differ from the page ground, with
    /// its horizontal extent.
    static func hostedBands(of view: some View, width: CGFloat) throws -> [Band] {
        let hosting = NSHostingView(rootView: view.background(CicadaTheme.bgBase))
        hosting.appearance = NSAppearance(named: CicadaTheme.mode == .dark ? .darkAqua : .aqua)
        hosting.frame = NSRect(x: 0, y: 0, width: width, height: 10)
        let height = hosting.fittingSize.height
        hosting.frame = NSRect(x: 0, y: 0, width: width, height: height)
        let window = NSWindow(contentRect: hosting.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = hosting.appearance
        window.contentView = hosting
        hosting.layoutSubtreeIfNeeded(); hosting.display()
        let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(width), pixelsHigh: Int(height),
                                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        rep.size = NSSize(width: width, height: height)
        hosting.cacheDisplay(in: hosting.bounds, to: rep)
        let ground = NSColor(CicadaTheme.bgBase).usingColorSpace(.deviceRGB)!
        func ink(_ x: Int, _ y: Int) -> Bool {
            guard let c = rep.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) else { return false }
            return abs(c.redComponent - ground.redComponent) + abs(c.greenComponent - ground.greenComponent)
                + abs(c.blueComponent - ground.blueComponent) > 0.06
        }
        var bands: [Band] = []
        var start: Int?
        var left = rep.pixelsWide, right = -1
        for y in 0...rep.pixelsHigh {
            var rowLeft = rep.pixelsWide, rowRight = -1
            if y < rep.pixelsHigh { for x in 0..<rep.pixelsWide where ink(x, y) { rowLeft = min(rowLeft, x); rowRight = max(rowRight, x) } }
            if rowRight >= 0 {
                if start == nil { start = y; left = rep.pixelsWide; right = -1 }
                left = min(left, rowLeft); right = max(right, rowRight)
            } else if let top = start {
                bands.append(Band(top: top, bottom: y - 1, left: CGFloat(left), right: CGFloat(right + 1)))
                start = nil
            }
        }
        return bands
    }

    /// Nothing about a run hangs under the pair any more: while a run reads, is paused, stopped or failed, what the page
    /// draws under the room's row (the control captions and the notes) is no taller than at rest, so nothing below
    /// jumps when a run starts or ends.
    func test_nothingAboutARunHangsUnderTheRoom() async throws {
        let rest = try await Self.underTheRoomHeight(Self.finished(), finished: false)
        for (name, status, finished) in try Self.runStates() where name != "just-finished" {
            let height = try await Self.underTheRoomHeight(status, finished: finished)
            XCTAssertEqual(height, rest, accuracy: 0.5, "\(name): under the pair is as tall as at rest")
        }
    }

    private static func underTheRoomHeight(_ status: SleepStatusResponse, finished: Bool) async throws -> CGFloat {
        let host = try await Self.host()
        host.sleep.status = status
        let model = page(status, justFinished: finished)
        let context = model.roomContext(recentCycleCommit: host.room.recentCycleCommit, locale: en)
        let under = VStack(alignment: .leading, spacing: 0) {
            SleepControlRow(consolidateEnabled: model.consolidateEnabled, queuedCount: model.queuedCount, page: model,
                            leading: true, part: .captions)
            SleepRoomColumn(page: model, status: roomSentence(context), answers: [], room: host.room, leading: true,
                            notesOnly: true)
        }
        let hosting = NSHostingView(rootView: environment(under.frame(width: 440), host: host))
        hosting.frame = NSRect(x: 0, y: 0, width: 440, height: 10)
        return hosting.fittingSize.height
    }

    // MARK: - Rails

    /// DR-5: the run object has no accent but its links (`accentText`); the bar is ink. DR-60: no `TimelineView`. The
    /// page's one primary stays the control row's alone.
    func test_theObjectKeepsTheRails() throws {
        let file = try XCTUnwrap(SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "SleepRunObject.swift" })
        let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
        XCTAssertFalse(code.contains { $0.contains("CicadaTheme.accent)") || $0.contains("CicadaTheme.accent.") },
                       "the accent is DR-5's six uses; links read accentText")
        XCTAssertFalse(code.contains { $0.contains("TimelineView(") })
        XCTAssertFalse(code.contains { $0.contains("PrimaryActionButton") })
        XCTAssertFalse(code.contains { $0.contains(".shadow(") }, "depth is a ring")
    }

    // MARK: - Layouts

    /// The words' width beside the room at a window: the 1440 pt window's page is 1040 wide with the room at 3 pt a cell
    /// (480 × 192); at 1079 pt the room is 2 pt a cell (320 × 128).
    static func wordsWidth(window: Int) -> CGFloat { window == 1440 ? 448 : 440 }

    static func runStates() throws -> [(String, SleepStatusResponse, Bool)] {
        try [
            ("reading-1-read", running(stage: 1), false),
            ("reading-1-read-failures", running(stage: 1, failed: 2), false),
            ("reading-2-sort", running(stage: 2), false),
            ("reading-3-decide", running(stage: 3), false),
            ("reading-4-notice", running(stage: 4), false),
            ("reading-5-file", running(stage: 5), false),
            ("reading-single-pass", singlePass(), false),
            ("paused-user", paused("user"), false),
            ("paused-plan-window", paused("plan_window"), false),
            ("paused-engine", paused("engine"), false),
            ("paused-restart", paused("restart"), false),
            ("failed", failed(), false),
            ("cancelled", cancelled(), false),
            ("just-finished", finished(), true),
        ]
    }

    /// The page's pinned block: the title, the status slot, the run bar, as tall as the room (`SleepView.roomBlock`).
    static func pinned(_ status: SleepStatusResponse, finished: Bool, host: Host, width: CGFloat,
                       cell: CGFloat) -> some View {
        let model = page(status, justFinished: finished)
        if finished { host.room.recentCycleCommit = "abc1234" }
        let context = model.roomContext(recentCycleCommit: host.room.recentCycleCommit, locale: en)
        return SleepRoomColumn(page: model, status: roomSentence(context), answers: [], room: host.room, leading: true,
                               title: AnyView(EyebrowRow(eyebrow: "Sleep", bare: true) { EmptyView() }),
                               fillHeight: CGFloat(RoomLattice.rows) * cell)
            .frame(width: width, alignment: .leading)
    }

    /// The page's real layout beside the room, as `SleepView.roomBlock` draws it: the pinned block and the room's
    /// rectangle (a neutral stand-in), then what hangs under the pair (the control captions, the notes). The room is
    /// 160 cells wide, 64 tall.
    static func beside(_ status: SleepStatusResponse, finished: Bool, host: Host, window: Int) -> some View {
        let cell: CGFloat = window == 1440 ? 3 : 2
        let width = wordsWidth(window: window)
        let model = page(status, justFinished: finished)
        let context = model.roomContext(recentCycleCommit: host.room.recentCycleCommit, locale: en)
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
                pinned(status, finished: finished, host: host, width: width, cell: cell)
                Rectangle().fill(CicadaTheme.surfaceElevated)
                    .frame(width: 160 * cell, height: CGFloat(RoomLattice.rows) * cell)
                    .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
                    .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            }
            SleepControlRow(consolidateEnabled: model.consolidateEnabled, queuedCount: model.queuedCount, page: model,
                            leading: true, part: .captions)
            SleepRoomColumn(page: model, status: roomSentence(context), answers: [], room: host.room, leading: true,
                            notesOnly: true)
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: width + CicadaTheme.spacingXL + 160 * cell + CicadaTheme.spacingXL * 2, alignment: .leading)
        .background(CicadaTheme.bgBase)
    }

    /// The narrow layout (below 720 pt of column): the room above the words, the same object stacked.
    static func narrow(_ status: SleepStatusResponse, finished: Bool, host: Host) -> some View {
        let model = page(status, justFinished: finished)
        if finished { host.room.recentCycleCommit = "abc1234" }
        let context = model.roomContext(recentCycleCommit: host.room.recentCycleCommit, locale: en)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Rectangle().fill(CicadaTheme.surfaceElevated).frame(width: 320, height: 128)
                .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
                .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            SleepRoomColumn(page: model, status: roomSentence(context), answers: [], room: host.room, leading: true)
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: 600, alignment: .leading)
        .background(CicadaTheme.bgBase)
    }

    // MARK: - The snapshots (for the person looking at the page)

    func test_writeTheRunStatesForComparison() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_RUN_STRIP_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_RUN_STRIP_SNAPSHOTS=<dir> to write the run states")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        var states = try Self.runStates().map { ($0.0, $0.1, $0.2, false) }
        states.append(("offline-stale", try Self.running(stage: 3), false, true))
        states.append(("refused-night", try Self.refusedNight(), false, false))
        states.append(("refused-night-gave-up", try Self.refusedNight(gaveUp: true), false, false))
        states.append(("idle", try Self.finished(), false, false))
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let suffix = mode == .dark ? "dark" : "light"
            for window in [1440, 1079] {
                for (name, status, finished, stale) in states {
                    let host = try await Self.host()
                    host.sleep.status = status
                    if finished { host.room.recentCycleCommit = "abc1234" }
                    let view = Self.environment(Self.beside(status, finished: finished, host: host, window: window)
                        .saturation(stale ? SleepLiveness.staleSaturation : 1), host: host)
                    let width = Self.wordsWidth(window: window) + CicadaTheme.spacingXL + 160 * (window == 1440 ? 3 : 2)
                        + CicadaTheme.spacingXL * 2
                    try Self.write(view, width: width, to: dir, file: "\(name)-\(window)-\(suffix).png")
                }
            }
            for (name, status, finished, _) in states {
                let host = try await Self.host()
                host.sleep.status = status
                try Self.write(Self.environment(Self.narrow(status, finished: finished, host: host), host: host),
                               width: 600, to: dir, file: "\(name)-narrow-\(suffix).png")
            }
        }
    }

    // MARK: - Fixtures

    static let en = Locale(identifier: "en_US")
    static let now = Date(timeIntervalSince1970: 1_790_000_000)
    private static let fixtures = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("fixtures")

    private static func scenario(_ file: String, _ key: String) throws -> [String: Any] {
        let all = try JSONSerialization.jsonObject(with: Data(contentsOf: fixtures.appendingPathComponent(file)))
        return try XCTUnwrap((all as? [String: Any])?[key] as? [String: Any])
    }

    private static func decode(_ object: [String: Any]) throws -> SleepStatusResponse {
        try JSONDecoder().decode(SleepStatusResponse.self, from: JSONSerialization.data(withJSONObject: object))
    }

    /// A run of 287 conversations in batches of 25, on batch 4 of 12, with the stage `stage` (1…5) in flight.
    static func running(stage: Int, failed: Int = 0, firstRun: Bool = false, waiting: String? = nil) throws -> SleepStatusResponse {
        var status = try scenario("sleep-status-drain.json", "running")
        var drain = try XCTUnwrap(status["drain"] as? [String: Any])
        let ids = ["read", "sort", "decide", "notice", "file"]
        let totals: [String: (Int, Int?)] = ["read": (14, 25), "sort": (31, 86), "decide": (4, 12)]
        drain["stages"] = ids.enumerated().map { index, id -> [String: Any] in
            let state = index < stage - 1 ? "done" : index == stage - 1 ? "active" : "pending"
            let (done, total) = totals[id] ?? (0, nil)
            return ["id": id, "state": state, "done": index < stage - 1 ? (total ?? 0) : done,
                    "total": total as Any, "failed": 0, "unit": NSNull()]
        }
        drain["frozen"] = 287; drain["filed"] = 74; drain["batch"] = 4; drain["batches"] = 12
        drain["batchSize"] = 25; drain["committedBatches"] = 3; drain["calls"] = 222
        drain["elapsedMs"] = 1_620_000; drain["firstRun"] = firstRun
        if let waiting { drain["waiting"] = waiting }
        if firstRun { drain["committedBatches"] = 1; drain["ownerPage"] = ["beliefs": 31] }
        drain["batchState"] = ["index": 4, "of": 12, "total": 25, "read": stage == 1 ? 14 : 25, "reading": 0,
                               "failed": failed]
        drain["byOrigin"] = ["claude-code": ["frozen": 287, "filed": 74, "read": 0, "waiting": 213,
                                             "couldNotBeRead": 0, "parked": 0, "skipped": 0, "newSince": 0]]
        status["drain"] = drain
        status["stage"] = stage - 1
        status["queueByOrigin"] = ["claude-code": 287]
        status["readByOrigin"] = ["claude-code": 88]
        return try decode(status)
    }

    /// The old single-pass shape: running, no drain, nothing countable.
    static func singlePass() throws -> SleepStatusResponse {
        var status = try scenario("sleep-status-drain.json", "running")
        status["drain"] = NSNull()
        status["stage"] = 1
        return try decode(status)
    }

    static func paused(_ reason: String) throws -> SleepStatusResponse {
        try decode(scenario("sleep-status-paused.json", reason))
    }

    /// A cancel with no pause record left (a run that is not continued): the stepper frozen where it stopped.
    static func cancelled() throws -> SleepStatusResponse {
        var status = try scenario("sleep-status-drain.json", "cancelled")
        status["paused"] = NSNull()
        return try decode(status)
    }

    /// Nothing waiting and nothing running: no drain, no debt, an empty queue (the page's empty state).
    static func empty() throws -> SleepStatusResponse {
        var status = try scenario("sleep-status-drain.json", "finished")
        status["drain"] = NSNull(); status["debt"] = NSNull()
        status["queueByOrigin"] = [String: Int](); status["readByOrigin"] = [String: Int]()
        status["episodesQueued"] = 0; status["episodesTotal"] = 0; status["episodesProcessed"] = 0
        return try decode(status)
    }

    static func finished() throws -> SleepStatusResponse {
        try decode(scenario("sleep-status-drain.json", "finished"))
    }

    /// 2026-11-26 — a scheduled run the write window refused before it read: idle, a queue waiting, no error, and the
    /// backend's calm `notice` (synthetic times). `gaveUp` is the same night after every try was spent.
    static func refusedNight(gaveUp: Bool = false) throws -> SleepStatusResponse {
        var status = try scenario("sleep-status-drain.json", "finished")
        status["drain"] = NSNull(); status["paused"] = NSNull(); status["error"] = NSNull()
        status["notice"] = gaveUp
            ? ["kind": "scheduled_run_refused", "text": "Last night's 03:00 run didn't start. It runs again at 03:00.",
               "detail": "The scheduled run for Nov 24 at 03:00 did not start: something was still writing to your memory, so Sleep read nothing and used nothing. It tried 4 times and stopped; it will run at its next scheduled time, or you can start it yourself.",
               "retryAt": NSNull(), "tries": 4, "maxTries": 4, "gaveUp": true] as [String: Any]
            : ["kind": "scheduled_run_refused", "text": "Last night's 03:00 run hasn't started yet. Next try after 03:12.",
               "detail": "The scheduled run for Nov 24 at 03:00 did not start: something was still writing to your memory, so Sleep read nothing and used nothing. It will try again after 03:12 (try 2 of 4).",
               "retryAt": "2026-11-24T03:12:00+00:00", "tries": 1, "maxTries": 4, "gaveUp": false] as [String: Any]
        return try decode(status)
    }

    static func failed() throws -> SleepStatusResponse {
        var status = try scenario("sleep-status-drain.json", "cancelled")
        status["cancelled"] = false
        status["paused"] = NSNull()
        status["error"] = "The engine stopped answering."
        var drain = try XCTUnwrap(status["drain"] as? [String: Any])
        drain["stop"] = NSNull()
        status["drain"] = drain
        return try decode(status)
    }

    static func page(_ status: SleepStatusResponse, justFinished: Bool = false) -> SleepPageModel {
        SleepPageModel.resolve(
            status: status, sse: nil, queued: [], schedule: ScheduleConfig(mode: "daily", hour: 3, minute: 0),
            enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 0),
            justFinishedAt: justFinished ? now : nil, intakeInFlight: false, paused: status.paused, batchSize: 25,
            now: now, locale: en, timeZone: TimeZone(identifier: "UTC")!)
    }

    /// The environment the column's controls read: a Store over a fake API, the Sleep and engine view models (the
    /// engine menu names a plan the person chose, as it does live), the router, and the intake for the sentence.
    struct Host {
        let store: Store
        let sleep: SleepViewModel
        let engine: SleepEngineViewModel
        let intake: IntakeRouter
        let room: RoomModel
    }

    static func host() async throws -> Host {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let response = SleepEngineResponse(
            mode: "agent", model: "small", disambiguationModel: "", source: "prefs",
            candidates: [SleepEngineCandidate(id: "agent", label: "Example plan", available: true, connected: true,
                                              models: ["small"], detail: nil)],
            preview: SleepEnginePreviews(manual: SleepEnginePreview(engine: "litellm", model: "small", why: "chosen"),
                                         scheduled: SleepEnginePreview(engine: "litellm", model: "small", why: "chosen")))
        let engine = SleepEngineViewModel(fetch: { response }, update: { _, _, _, _ in response })
        await engine.load()
        return Host(store: store, sleep: SleepViewModel(store: store), engine: engine,
                    intake: IntakeRouter(api: FakeIntakeAPI()), room: RoomModel())
    }

    static func environment(_ view: some View, host: Host) -> some View {
        view
            .environment(host.store)
            .environment(host.sleep)
            .environment(host.engine)
            .environment(host.intake)
            .environment(AppRouter())
            .environment(\.spriteSnapshotDate, now)
            .environment(\.colorScheme, CicadaTheme.mode == .dark ? .dark : .light)
    }

    static func column(_ page: SleepPageModel, host: Host) throws -> some View {
        let context = page.roomContext(recentCycleCommit: host.room.recentCycleCommit, locale: en)
        return environment(SleepRoomColumn(page: page, status: roomSentence(context), answers: [], room: host.room),
                           host: host)
    }

    // MARK: - Pixels

    struct Band {
        let top: Int, bottom: Int
        let left: CGFloat, right: CGFloat
        var center: CGFloat { (left + right) / 2 }
    }

    /// The rows of ink in a render at 1 pt per pixel, top to bottom: each run of pixel rows that differ from the page
    /// ground, with its horizontal extent. Rows of words, the controls, the stepper and the bar each come out as one.
    static func bands(of view: some View, width: CGFloat) throws -> [Band] {
        let ground = NSColor(CicadaTheme.bgBase).usingColorSpace(.sRGB)!
        let renderer = ImageRenderer(content: view.frame(width: width).background(CicadaTheme.bgBase))
        renderer.proposedSize = ProposedViewSize(width: width, height: nil)
        renderer.scale = 1
        let image = try XCTUnwrap(renderer.cgImage)
        let w = image.width, h = image.height
        var pixels = [UInt8](repeating: 0, count: w * h * 4)
        let ctx = try XCTUnwrap(CGContext(data: &pixels, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                          space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        let g = [ground.redComponent, ground.greenComponent, ground.blueComponent].map { Int(($0 * 255).rounded()) }
        func ink(_ x: Int, _ y: Int) -> Bool {
            let i = ((h - 1 - y) * w + x) * 4
            return abs(Int(pixels[i]) - g[0]) + abs(Int(pixels[i + 1]) - g[1]) + abs(Int(pixels[i + 2]) - g[2]) > 6
        }
        var bands: [Band] = []
        var start: Int?
        var left = w, right = -1
        for y in 0...h {
            var rowLeft = w, rowRight = -1
            if y < h { for x in 0..<w where ink(x, y) { rowLeft = min(rowLeft, x); rowRight = max(rowRight, x) } }
            if rowRight >= 0 {
                if start == nil { start = y; left = w; right = -1 }
                left = min(left, rowLeft); right = max(right, rowRight)
            } else if let top = start {
                bands.append(Band(top: top, bottom: y - 1, left: CGFloat(left), right: CGFloat(right + 1)))
                start = nil
            }
        }
        return bands
    }

    /// Written through an `NSHostingView`, not `ImageRenderer`: the page's primary action is a system button
    /// (glass-prominent), which an `ImageRenderer` snapshot cannot draw — Continue would be missing from every paused
    /// render and the row would look off-centre for a reason the app does not have.
    static func write(_ view: some View, width: CGFloat, to dir: String, file: String) throws {
        let hosting = NSHostingView(rootView: view)
        hosting.appearance = NSAppearance(named: CicadaTheme.mode == .dark ? .darkAqua : .aqua)
        hosting.frame = NSRect(x: 0, y: 0, width: width, height: 10)
        let height = hosting.fittingSize.height
        hosting.frame = NSRect(x: 0, y: 0, width: width, height: height)
        // In a window (never shown): a system button draws its bezel only once it has one.
        let window = NSWindow(contentRect: hosting.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = hosting.appearance
        window.contentView = hosting
        hosting.layoutSubtreeIfNeeded()
        hosting.display()
        let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(width * 2),
                                                 pixelsHigh: Int(height * 2), bitsPerSample: 8, samplesPerPixel: 4,
                                                 hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                                 bytesPerRow: 0, bitsPerPixel: 0))
        rep.size = NSSize(width: width, height: height)
        hosting.cacheDisplay(in: hosting.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: URL(fileURLWithPath: dir).appendingPathComponent(file))
    }
}
