import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The Sleep page's running block as one calm, centred group (2026-10-16). The owner's live capture during a run had
/// four widths and alignments stacked under the room: a centred sentence, the stage tiles starting at the column's
/// left, a left-aligned caption, and a bar a third width again, with the controls pushed off-centre by their whisper.
///
/// Two kinds of test: the stepper's state for every stage (pure), and the column's geometry, read from the pixels of
/// the real `SleepRoomColumn` laid out offscreen — every row's ink centred on the column's axis, and the stepper and the
/// bar spanning the same width, the column's. `CICADA_RUN_STRIP_SNAPSHOTS=<dir>` also writes every run state, dark and
/// light, at the 1440 and 1079 pt windows, for a person to compare against the live capture.
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

    // MARK: - The stepper's state, stage by stage

    /// While stage k runs: the ones before it are done, k is the one current step, the ones after are to come — so the
    /// three read differently at a glance (the live capture drew all five with the same underline).
    func test_eachRunningStageIsTheOneCurrentStep() {
        for running in 1...5 {
            let pips = stageStripState(stage: running - 1, isRunning: true, cancelled: false, error: false,
                                       read: 14, total: 25)
            let looks = pips.map(StepLook.init)
            XCTAssertEqual(looks.filter { $0 == .current }.count, 1, "stage \(running)")
            XCTAssertEqual(looks.firstIndex(of: .current), running - 1, "stage \(running)")
            XCTAssertEqual(Array(looks.prefix(running - 1)), Array(repeating: .done, count: running - 1))
            XCTAssertEqual(Array(looks.suffix(5 - running)), Array(repeating: .toCome, count: 5 - running))
        }
    }

    /// A cancel freezes the stepper where it stopped; a failure marks the stage it died in. Neither shows a current
    /// step, because nothing is running.
    func test_aStoppedRunHasNoCurrentStep() {
        let cancelled = stageStripState(stage: 2, isRunning: false, cancelled: true, error: false, read: 0, total: 0)
        XCTAssertEqual(cancelled.map(StepLook.init), [.done, .done, .toCome, .toCome, .toCome])
        let failed = stageStripState(stage: 1, isRunning: false, cancelled: false, error: true, read: 0, total: 0)
        XCTAssertEqual(failed.map(StepLook.init), [.done, .failed, .toCome, .toCome, .toCome])
        XCTAssertEqual(StepLook.failed.pip.accessibilityWord, "failed", "a failure is said in words (DR-7)")
    }

    /// The way to the next stage fills only from a counted fraction (P15): whole after a done stage, the fraction after
    /// a counted stage in flight, nothing after an uncounted one or one that never ran.
    func test_theConnectorFillsOnlyFromACountedFraction() {
        XCTAssertEqual(StepLook.connectorFill(after: .done), 1)
        XCTAssertEqual(StepLook.connectorFill(after: .active(fill: 0.56)), 0.56, accuracy: 1e-9)
        XCTAssertEqual(StepLook.connectorFill(after: .active(fill: nil)), 0, "Notice and File carry no fraction")
        XCTAssertEqual(StepLook.connectorFill(after: .active(fill: 1.7)), 1)
        for pip in [StagePip.pending, .skipped, .failed] { XCTAssertEqual(StepLook.connectorFill(after: pip), 0) }
    }

    /// "Filing" is said once in the words: the lead names it, the secondary line says what it does, and what a stop
    /// does now is the whisper under the controls — the stage caption that said it a third time is gone.
    func test_filingIsSaidOnceAndTheStopWhisperSaysWhatAStopDoes() throws {
        let page = try Self.page(Self.running(stage: 5))
        let line = roomSentence(page.roomContext(locale: Self.en))
        XCTAssertEqual(line.lead, Copy.SleepV5.filingLead)
        XCTAssertNotNil(line.tail)
        XCTAssertFalse(line.tail?.localizedCaseInsensitiveContains("filing") ?? true)
        XCTAssertEqual(controlCaption(isRunning: true, draining: true, filing: true), Copy.SleepV5.filingWhisper)
        XCTAssertNil(batchFailureNote(drain: page.drain, activeStage: page.runningStage))
        XCTAssertFalse(Copy.SleepV5.filingWhisper.contains("nothing is lost"), "G163: never promise what is not kept")
    }

    // MARK: - One centred column

    /// Laid out in a page wider than the column, every row of the running block is centred on the column's axis, and
    /// the stepper and the bar span exactly the column — one width, one alignment (DR-36).
    func test_everyRowSharesOneCentredColumn() async throws {
        for width in [CGFloat(900), SleepLayout.contentWidth] {
            for stage in [1, 3, 5] {
                let host = try await Self.host()
                let status = try Self.running(stage: stage)
                host.sleep.status = status
                let view = try Self.column(Self.page(status), host: host)
                let bands = try Self.bands(of: view, width: width)
                let column = (left: (width - SleepLayout.contentWidth) / 2, right: (width + SleepLayout.contentWidth) / 2)
                XCTAssertGreaterThanOrEqual(bands.count, 6, "\(stage) at \(width): sentence, controls, schedule, stepper, bar, counts")
                for band in bands {
                    XCTAssertEqual(band.center, width / 2, accuracy: 3,
                                   "stage \(stage) at \(width) pt: the row at y \(band.top)–\(band.bottom) is off-centre "
                                   + "(\(band.left)–\(band.right))")
                    XCTAssertGreaterThanOrEqual(band.left, column.left - 1, "nothing leaves the column")
                    XCTAssertLessThanOrEqual(band.right, column.right + 1, "nothing leaves the column")
                }
                let full = bands.filter { $0.left <= column.left + 4 && $0.right >= column.right - 4 }
                XCTAssertEqual(full.count, 2, "stage \(stage) at \(width): the stepper and the bar, and only they, span the column")
            }
        }
    }

    /// The controls stay centred when their whisper shows: it is a line of its own under them, not a third item
    /// beside them (the live capture's off-centre pair).
    func test_theControlGroupIsCentredWithItsWhisperUnderIt() async throws {
        let host = try await Self.host()
        let page = try Self.page(Self.running(stage: 5))
        host.sleep.status = try Self.running(stage: 5)
        let row = SleepControlRow(consolidateEnabled: page.consolidateEnabled, queuedCount: page.queuedCount, page: page)
        let bands = try Self.bands(of: Self.environment(row, host: host), width: SleepLayout.contentWidth)
        XCTAssertEqual(bands.count, 2, "the buttons, then the whisper on its own line")
        for band in bands { XCTAssertEqual(band.center, SleepLayout.contentWidth / 2, accuracy: 3) }
    }

    // MARK: - The snapshots (for the person comparing against the live capture)

    func test_writeTheRunStatesForComparison() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_RUN_STRIP_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_RUN_STRIP_SNAPSHOTS=<dir> to write the run states")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let states: [(String, SleepStatusResponse, Bool, Bool)] = try [
            ("reading-1-read", Self.running(stage: 1), false, false),
            ("reading-1-read-failures", Self.running(stage: 1, failed: 2), false, false),
            ("reading-2-sort", Self.running(stage: 2), false, false),
            ("reading-3-decide", Self.running(stage: 3), false, false),
            ("reading-4-notice", Self.running(stage: 4), false, false),
            ("reading-5-file", Self.running(stage: 5), false, false),
            ("paused-user", Self.paused("user"), false, false),
            ("paused-plan-window", Self.paused("plan_window"), false, false),
            ("paused-engine", Self.paused("engine"), false, false),
            ("paused-restart", Self.paused("restart"), false, false),
            ("failed", Self.failed(), false, false),
            ("just-finished", Self.finished(), true, false),
            ("cancelled", Self.cancelled(), false, false),
            ("offline-stale", Self.running(stage: 3), false, true),
        ]
        // The page's column at the two windows the brief names: the rail (`ShellMetrics`) and the page gutters leave
        // the room's column 760 pt at both, so the 1079 pt render is the live capture's geometry.
        for (window, pageWidth) in [(1440, CGFloat(1280)), (1079, CGFloat(930))] {
            for mode in [AppColorScheme.dark, .light] {
                CicadaTheme.mode = mode
                for (name, status, finished, stale) in states {
                    let host = try await Self.host()
                    host.sleep.status = status
                    let page = Self.page(status, justFinished: finished)
                    if finished { host.room.recentCycleCommit = "abc1234" }
                    let view = try Self.column(page, host: host)
                        .saturation(stale ? SleepLiveness.staleSaturation : 1)
                        .padding(.vertical, CicadaTheme.spacingXL)
                        .frame(width: pageWidth)
                        .background(CicadaTheme.bgBase)
                    try Self.write(view, width: pageWidth, to: dir,
                                   file: "\(name)-\(window)-\(mode == .dark ? "dark" : "light").png")
                }
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
    static func running(stage: Int, failed: Int = 0) throws -> SleepStatusResponse {
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
        drain["elapsedMs"] = 1_620_000; drain["firstRun"] = false
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

    static func paused(_ reason: String) throws -> SleepStatusResponse {
        try decode(scenario("sleep-status-paused.json", reason))
    }

    /// A cancel with no pause record left (a run that is not continued): the stepper frozen where it stopped.
    static func cancelled() throws -> SleepStatusResponse {
        var status = try scenario("sleep-status-drain.json", "cancelled")
        status["paused"] = NSNull()
        return try decode(status)
    }

    static func finished() throws -> SleepStatusResponse {
        try decode(scenario("sleep-status-drain.json", "finished"))
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
