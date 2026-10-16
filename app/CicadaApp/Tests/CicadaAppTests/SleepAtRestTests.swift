import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The owner's Sleep page at rest (2026-10-16): one headline, one row of controls (Consolidate · engine · Options),
/// one schedule sentence. No italic, no orange "overdue", the lamp-off fact said once, "Reading options…" in the row as
/// Options, and the engine button at Consolidate's height. #315's running column is untouched (`SleepRunStripTests`).
@MainActor
final class SleepAtRestTests: XCTestCase {
    override func setUp() {
        CicadaTheme.uiScale = 1
        CicadaTheme.mode = .dark
    }

    override func tearDown() {
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    /// 23 waiting, three days since the last read, the lamp off — the QA capture's page.
    static func overdue() throws -> SleepStatusResponse {
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("fixtures/sleep-status-drain.json")
        let all = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
        var status = try XCTUnwrap(all["finished"] as? [String: Any])
        status["drain"] = NSNull()
        status["lastFinishedCycle"] = NSNull()
        status["debt"] = ["agePct": 80, "hasRunBefore": true, "hoursSinceLastCycle": 72,
                          "oldestUnprocessedAgeHours": 70, "restedPct": 10, "unprocessedCount": 23,
                          "volumePct": 60, "readableCount": 23, "parkedCount": 0]
        status["queueByOrigin"] = ["claude-code": 23]
        status["readByOrigin"] = [:]
        return try JSONDecoder().decode(SleepStatusResponse.self, from: JSONSerialization.data(withJSONObject: status))
    }

    static func page(_ status: SleepStatusResponse) -> SleepPageModel {
        SleepPageModel.resolve(
            status: status, sse: nil, queued: [], schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
            enginePreview: nil, history: [], storeStatus: nil, queueLoad: .loaded(count: 23),
            justFinishedAt: nil, intakeInFlight: false, paused: nil, batchSize: 25,
            now: Date(timeIntervalSince1970: 1_790_000_000), locale: Locale(identifier: "en_US"),
            timeZone: TimeZone(identifier: "UTC")!)
    }

    /// The words: "overdue" in the lead's own colour, nothing ambient above the controls, and the lamp-off sentence
    /// said once — as the schedule line. T10 still says how long it has been: news about the pile, not a repeat.
    func test_theHeadlineIsPlainAndTheLampIsSaidOnce() throws {
        let page = Self.page(try Self.overdue())
        let line = roomSentence(page.roomContext(locale: Locale(identifier: "en_US")))
        XCTAssertEqual(line.lead, "23 to read — overdue.")
        XCTAssertEqual(line.tone, .plain, "no orange overdue (DR-7)")
        XCTAssertEqual(line.tail, "It's been 3 days.", "the one secondary line, in plain words")
        XCTAssertFalse(line.spoken.contains("lamp"), "the lamp is not said above the controls")
        let schedule = whisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText, lampLit: page.lampLit)
        XCTAssertEqual(schedule, Copy.lampOffSentence)
    }

    /// The pixels, drawn the way the app draws them (an `NSHostingView` in a window, so the glass Consolidate is
    /// there): the headline and its one line, ONE row of controls, the schedule sentence — four bands, all centred.
    /// Options is in the row, not a line of its own between the row and the schedule.
    func test_theColumnIsAHeadlineOneRowAndOneSentence() async throws {
        let host = try await SleepRunStripTests.host()
        let status = try Self.overdue()
        host.sleep.status = status
        let page = Self.page(status)
        XCTAssertGreaterThan(page.readable ?? 0, 0, "Options shows while something waits")
        let context = page.roomContext(recentCycleCommit: nil, locale: Locale(identifier: "en_US"))
        let column = SleepRunStripTests.environment(
            SleepRoomColumn(page: page, status: roomSentence(context), answers: [], room: host.room), host: host)
        if let dir = ProcessInfo.processInfo.environment["CICADA_AT_REST_SNAPSHOT"] {
            try SleepRunStripTests.write(column, width: SleepLayout.contentWidth, to: dir, file: "at-rest.png")
        }
        // A one-point sliver at the window's edge is the window, not a row.
        let bands = try Self.hostedBands(column, width: SleepLayout.contentWidth).filter { $0.bottom - $0.top >= 2 }
        XCTAssertEqual(bands.count, 4, "headline, its line, controls, schedule — got \(bands.map { "\($0.top)–\($0.bottom)" })")
        for (index, band) in bands.enumerated() {
            // Offscreen, the glass Consolidate draws its label but not its bezel, so the row's ink starts about 15 pt
            // inside the button's frame and its centre reads up to half that to the right. The words are exact.
            XCTAssertEqual(band.center, SleepLayout.contentWidth / 2, accuracy: index == 2 ? 9 : 3, "band \(index)")
        }
        XCTAssertGreaterThanOrEqual(bands[2].bottom - bands[2].top, 26, "the controls are one row of buttons")
    }

    /// Rows of ink (in points) in a render through `NSHostingView`, against the page ground.
    static func hostedBands(_ view: some View, width: CGFloat) throws -> [SleepRunStripTests.Band] {
        let hosting = NSHostingView(rootView: view.frame(width: width).background(CicadaTheme.bgBase))
        hosting.appearance = NSAppearance(named: .darkAqua)
        hosting.frame = NSRect(x: 0, y: 0, width: width, height: 10)
        let height = hosting.fittingSize.height
        hosting.frame = NSRect(x: 0, y: 0, width: width, height: height)
        let window = NSWindow(contentRect: hosting.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = hosting.appearance
        window.contentView = hosting
        hosting.layoutSubtreeIfNeeded()
        hosting.display()
        let rep = try XCTUnwrap(hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds))
        hosting.cacheDisplay(in: hosting.bounds, to: rep)
        // The ground as drawn (the window's colour management shifts the token a step), read from a corner.
        let ground = try XCTUnwrap(rep.colorAt(x: 1, y: 1)?.usingColorSpace(.sRGB))
        let scale = CGFloat(rep.pixelsWide) / width
        func ink(_ x: Int, _ y: Int) -> Bool {
            guard let c = rep.colorAt(x: x, y: y)?.usingColorSpace(.sRGB) else { return false }
            return abs(c.redComponent - ground.redComponent) + abs(c.greenComponent - ground.greenComponent)
                + abs(c.blueComponent - ground.blueComponent) > 0.04
        }
        var bands: [SleepRunStripTests.Band] = []
        var start: Int?
        var left = Int.max, right = -1
        for y in 0...rep.pixelsHigh {
            var rowLeft = Int.max, rowRight = -1
            if y < rep.pixelsHigh {
                for x in 0..<rep.pixelsWide where ink(x, y) { rowLeft = min(rowLeft, x); rowRight = max(rowRight, x) }
            }
            if rowRight >= 0 {
                if start == nil { start = y; left = Int.max; right = -1 }
                left = min(left, rowLeft); right = max(right, rowRight)
            } else if let top = start {
                bands.append(.init(top: Int(CGFloat(top) / scale), bottom: Int(CGFloat(y - 1) / scale),
                                   left: CGFloat(left) / scale, right: CGFloat(right + 1) / scale))
                start = nil
            }
        }
        return bands
    }

    /// Consolidate, the engine menu and Options stand at one height (the QA capture's engine button stood taller).
    func test_theThreeControlsShareOneHeight() throws {
        func height(_ view: some View) -> CGFloat {
            let hosting = NSHostingView(rootView: view)
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 100), styleMask: [.borderless],
                                  backing: .buffered, defer: false)
            window.contentView = hosting
            return hosting.fittingSize.height
        }
        // Consolidate as the row draws it (`SleepControlRow.consolidateButton`).
        let consolidate = height(PrimaryActionButton(title: Copy.consolidateNow, systemImage: "moon.fill") {}
            .font(CicadaTheme.font(size: 12, weight: .semibold)).controlSize(.large))
        let neutral = height(NeutralButton(title: Copy.SleepV5.options, size: .compact) {})
        XCTAssertEqual(consolidate, neutral, accuracy: 0.5)
        let source = try String(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Views/Sleep/SleepHero.swift"), encoding: .utf8)
        XCTAssertTrue(source.contains("EngineQuickMenuButton(size: .compact)"), "the engine menu at the row's height")
        XCTAssertTrue(source.contains("NeutralButton(title: Copy.SleepV5.options, size: .compact"), "Options in the row")
        XCTAssertFalse(source.contains("TextButton(title: Copy.SleepV5.readingOptions"), "no floating Reading options…")
    }
}
