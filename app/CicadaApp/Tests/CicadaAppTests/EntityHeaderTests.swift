import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// R-DG14 … R-DG16 — the entity column's header and tabs, pure, plus one fit test.
final class EntityHeaderTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        super.tearDown()
    }

    private func claim(_ id: String, predicate: String = "uses", context: String = "engineering",
                       observer: String = "agent", object: String = "sqlite-vec", validTo: String? = nil) throws -> Claim {
        let to = validTo.map { #","validTo":"\#($0)""# } ?? ""
        return try JSONDecoder().decode(Claim.self, from: Data(#"{"id":"\#(id)","text":"t","predicate":"\#(predicate)","context":"\#(context)","observer":"\#(observer)","object":"\#(object)","validFrom":"2026-04-01"\#(to)}"#.utf8))
    }

    /// R-DG14 — the mock's four steps, boundaries included.
    func testConfidenceIsWords() {
        let cases: [(Double, String)] = [(0.92, "very confident"), (0.85, "very confident"), (0.849, "fairly confident"),
                                         (0.6, "fairly confident"), (0.59, "unsure"), (0.4, "unsure"), (0.39, "doubtful")]
        for (value, words) in cases { XCTAssertEqual(EntityHeaderWords.confidence(value), words, "\(value)") }
    }

    func testTheStatusLineAndItsHelp() {
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .active, confidence: 0.92), "Active · very confident")
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .decaying, confidence: 0.5), "Fading · unsure")
        XCTAssertEqual(EntityHeaderWords.statusHelp(status: .active, confidence: 0.92), "Confidence 92 out of 100")
        let fading = EntityHeaderWords.statusHelp(status: .decaying, confidence: 0.5)
        XCTAssertTrue(fading.hasPrefix("Confidence 50 out of 100"))
        XCTAssertTrue(fading.contains("fading"))
        XCTAssertFalse(fading.contains("%"), "DR-59")
    }

    /// G194 A2 (owner D4) — a page whose newest source is older than 90 days says when it was last mentioned, in
    /// the place the confidence word was; confidence is not freshness, so the number moves to `.help` (DR-59).
    func testAnOldPageSaysWhenItWasLastMentionedInsteadOfHowSure() {
        let en = Locale(identifier: "en_US")
        let today = ISODay(year: 2026, month: 10, day: 7)
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .active, confidence: 0.99, lastReferenced: "2025-02-06",
                                                    today: today, locale: en), "Active · last mentioned Feb 2025")
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .decaying, confidence: 0.5, lastReferenced: "2025-02-06",
                                                    today: today, locale: en), "Fading · last mentioned Feb 2025")
        let help = EntityHeaderWords.statusHelp(status: .active, confidence: 0.99, lastReferenced: "2025-02-06",
                                                today: today, locale: en)
        XCTAssertEqual(help, "Confidence 99 out of 100 · last mentioned Feb 6, 2025")
        let fading = EntityHeaderWords.statusHelp(status: .decaying, confidence: 0.5, lastReferenced: "2025-02-06",
                                                  today: today, locale: en)
        XCTAssertTrue(fading.hasPrefix("Confidence 50 out of 100 · last mentioned Feb 6, 2025"))
        XCTAssertTrue(fading.hasSuffix(Copy.Graph.fadingReason), "the decaying reason stays")
        XCTAssertFalse(help.contains("%"), "DR-59")
    }

    /// The boundary is 90 whole days (the backend's `source_dates.OLD_AFTER_DAYS`); anything the header cannot read
    /// as a past day keeps the confidence words — a missing, invalid or future day is never called old.
    func testOnlyAReadablePastDayOlderThanNinetyDaysChangesTheHeader() {
        let en = Locale(identifier: "en_US")
        let today = ISODay(year: 2026, month: 10, day: 7)
        XCTAssertEqual(EntityHeaderWords.oldAfterDays, 90)
        func line(_ day: String?) -> String {
            EntityHeaderWords.statusLine(status: .active, confidence: 0.92, lastReferenced: day, today: today, locale: en)
        }
        XCTAssertEqual(line("2026-07-09"), "Active · very confident", "90 days: not old yet")
        XCTAssertEqual(line("2026-07-08"), "Active · last mentioned Jul 2026", "91 days")
        XCTAssertEqual(line("2026-07-08T23:30:00Z"), "Active · last mentioned Jul 2026", "an instant's day part")
        for day in [nil, "", "not-a-date", "2026-13-01", "2026-12-01", "2027-01-01"] {
            XCTAssertEqual(line(day), "Active · very confident", day ?? "nil")
            XCTAssertEqual(EntityHeaderWords.statusHelp(status: .active, confidence: 0.92, lastReferenced: day,
                                                        today: today, locale: en), "Confidence 92 out of 100")
        }
    }

    /// Fix round 1 (review finding 1): an impossible calendar day is not a day. `ISODay` normalizes Feb 30 into
    /// Mar 2; the header must not show a month the payload never named, so it keeps the confidence words.
    func testAnImpossibleCalendarDayIsNeverShownAsAnotherDay() {
        let en = Locale(identifier: "en_US")
        let today = ISODay(year: 2026, month: 10, day: 7)
        for day in ["2025-02-30", "2025-04-31", "2026-02-29", "2025-06-31", "2025-00-10", "2025-02-00",
                    "2025-2-6", "20250206", "2025-02-06x", "2025/02/06", " 2025-02-06"] {
            XCTAssertEqual(EntityHeaderWords.statusLine(status: .active, confidence: 0.92, lastReferenced: day,
                                                        today: today, locale: en), "Active · very confident", day)
            XCTAssertEqual(EntityHeaderWords.statusHelp(status: .active, confidence: 0.92, lastReferenced: day,
                                                        today: today, locale: en), "Confidence 92 out of 100", day)
        }
        // A real leap day, and an instant on a real day, are still read.
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .active, confidence: 0.92, lastReferenced: "2024-02-29",
                                                    today: today, locale: en), "Active · last mentioned Feb 2024")
        XCTAssertEqual(EntityHeaderWords.statusHelp(status: .active, confidence: 0.92, lastReferenced: "2024-02-29",
                                                    today: today, locale: en),
                       "Confidence 92 out of 100 · last mentioned Feb 29, 2024")
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .active, confidence: 0.92,
                                                    lastReferenced: "2025-02-06 10:00:00", today: today, locale: en),
                       "Active · last mentioned Feb 2025")
    }

    /// Today is the viewer's calendar day (DR-58: computed at read); the stored day is a calendar day with no zone.
    func testTodayIsTheViewersDayAtTheBoundary() {
        let now = ISO8601DateFormatter().date(from: "2026-05-07T09:00:00Z")!
        var west = Calendar(identifier: .gregorian)
        west.timeZone = TimeZone(secondsFromGMT: -10 * 3600)!
        var east = Calendar(identifier: .gregorian)
        east.timeZone = TimeZone(secondsFromGMT: 14 * 3600)!
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .active, confidence: 0.92, lastReferenced: "2026-02-05",
                                                    today: .today(now: now, calendar: west), locale: en),
                       "Active · very confident", "UTC−10: still May 6, 90 days")
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .active, confidence: 0.92, lastReferenced: "2026-02-05",
                                                    today: .today(now: now, calendar: east), locale: en),
                       "Active · last mentioned Feb 2026", "UTC+14: already May 7, 91 days")
    }

    /// The month is the viewer's language; the words around it are the app's copy.
    func testTheMonthFollowsTheLocale() {
        let today = ISODay(year: 2026, month: 10, day: 7)
        for id in ["es_ES", "de_DE", "ja_JP"] {
            let month = EntityHeaderWords.lastMentionedMonth("2025-02-06", today: today, locale: Locale(identifier: id))
            XCTAssertEqual(month, RelativeDay.monthYear(ISODay(year: 2025, month: 2, day: 6), locale: Locale(identifier: id)))
            XCTAssertTrue(month?.contains("2025") ?? false, id)
            XCTAssertNotEqual(month, "Feb 2025", id)
        }
    }

    /// R-DG15 — the Summary, never the agentic-write placeholder; a stub's preview until the page lands.
    func testTheHeaderSummary() {
        let page = "## Summary\nA [[FastAPI]] dashboard.\n\n## Notes\nMore."
        XCTAssertEqual(EntityHeaderWords.summary(markdown: page, isStub: false), "A [[FastAPI]] dashboard.")
        XCTAssertNil(EntityHeaderWords.summary(markdown: "## Summary\nAlpha project — created via agentic write.", isStub: false))
        XCTAssertNil(EntityHeaderWords.summary(markdown: "# Alpha project\nJust prose.", isStub: false))
        XCTAssertEqual(EntityHeaderWords.summary(markdown: "A short preview.", isStub: true), "A short preview.")
        XCTAssertNil(EntityHeaderWords.summary(markdown: "", isStub: true))
    }

    /// R-DG16 — the brief's order; a count only once it is known.
    func testTabsInOrderWithCountsOnlyWhenKnown() throws {
        let unknown = EntityTabs.tabs(claims: nil, historyCount: nil)
        XCTAssertEqual(unknown.map(\.label), ["Content", "Perspectives", "History", "Timeline"])
        XCTAssertEqual(unknown.map(\.id), [.content, .perspectives, .history, .timeline])
        XCTAssertEqual(unknown.map(\.count), [nil, nil, nil, nil])
        let claims = [try claim("c1", validTo: "2026-05-01"), try claim("c2"), try claim("c3", predicate: "role")]
        let known = EntityTabs.tabs(claims: claims, historyCount: 4)
        XCTAssertEqual(known.map(\.count), [nil, 2, 4, 1], "2 current beliefs, 4 commits, 1 contested (uses|engineering)")
    }

    func testTheHistoryCountIsWhatIsInHand() {
        let entry = EntityHistoryEntry(date: .now, changeType: .updated, description: "d")
        XCTAssertNil(EntityTabs.historyCount(embedded: [], fetched: nil), "not fetched yet")
        XCTAssertEqual(EntityTabs.historyCount(embedded: [entry, entry], fetched: nil), 2)
        XCTAssertEqual(EntityTabs.historyCount(embedded: [], fetched: []), 0)
    }

    func testContestedIsTwoOrMoreClaimsPerKey() throws {
        let claims = [try claim("a"), try claim("b", validTo: "2026-05-01"), try claim("c", predicate: "role"),
                      try claim("d", context: "career"), try claim("e", context: "career")]
        XCTAssertEqual(EntityTabs.contested(claims).map(\.id), ["uses|career", "uses|engineering"])
    }

    /// DR-31 / DR-70 — at the 440 floor, at every zoom, the header never wants more than its column: a long
    /// name wraps, a long Back target truncates, the tabs with a five-digit count still fit.
    @MainActor
    func testTheHeaderNeverWantsMoreThanItsColumn() throws {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let entity = Entity(id: "alpha-project", name: String(repeating: "Alpha project ", count: 8), type: .project,
                            status: .decaying, confidence: 0.42, created: "2026-01-05", lastReferenced: "2026-08-25",
                            decayRate: 0.05, sourceEpisodes: [], tags: [], related: [], version: 1,
                            markdownContent: "## Summary\n" + String(repeating: "A long summary sentence. ", count: 20),
                            history: [])
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let width = GraphColumns.entityMin * CGFloat(scale)
            let header = EntityCardHeader(
                entity: entity, summary: EntityHeaderWords.summary(markdown: entity.markdownContent, isStub: false),
                isStub: false, canGoBack: true, backTargetName: String(repeating: "Bob example ", count: 6),
                onBack: {}, showsClose: true, onClose: {},
                tabs: EntityTabs.tabs(claims: [], historyCount: 12345), selection: .constant(.content),
                inset: EntityCardStyle.column.inset
            ).environment(store)
            let renderer = ImageRenderer(content: header)
            renderer.proposedSize = ProposedViewSize(width: width, height: nil)
            let size = try XCTUnwrap(renderer.nsImage).size
            XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(scale): \(size.width)")
        }
    }

    /// G194 A2 — the old page's line ("last mentioned Feb 2025") fits the 440 floor at every zoom, one line (DR-59).
    @MainActor
    func testAnOldPagesHeaderNeverWantsMoreThanItsColumn() throws {
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let width = GraphColumns.entityMin * CGFloat(scale)
            let renderer = ImageRenderer(content: Self.oldPageHeader(width: width))
            renderer.proposedSize = ProposedViewSize(width: width, height: nil)
            let size = try XCTUnwrap(renderer.nsImage).size
            XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(scale): \(size.width)")
        }
    }

    /// Offscreen review renders (never the app): light and dark, the column floor and 1.4× text, written only when
    /// `G194_RENDER_DIR` names a folder — the orchestrator's live look is separate.
    @MainActor
    func testRenderTheOldPageHeaderForReview() throws {
        guard let dir = ProcessInfo.processInfo.environment["G194_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set G194_RENDER_DIR to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark }
        for mode in [AppColorScheme.light, .dark] {
            for (scale, tag) in [(1.0, "1x"), (1.4, "1.4x")] {
                CicadaTheme.mode = mode
                CicadaTheme.uiScale = scale
                let width = GraphColumns.entityMin * CGFloat(scale)
                for (name, last) in [("old", "2025-02-06"), ("recent", "2026-09-30")] {
                    let view = Self.oldPageHeader(width: width, lastReferenced: last)
                        .padding(.vertical, 12)
                        .background(CicadaTheme.bgBase)
                        .environment(\.colorScheme, mode == .dark ? .dark : .light)
                    let renderer = ImageRenderer(content: view)
                    renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                    renderer.scale = 2
                    let image = try XCTUnwrap(renderer.nsImage)
                    let tiff = try XCTUnwrap(image.tiffRepresentation)
                    let png = try XCTUnwrap(NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]))
                    let file = URL(fileURLWithPath: dir).appendingPathComponent("header-\(name)-\(mode == .dark ? "dark" : "light")-\(tag).png")
                    try png.write(to: file)
                }
            }
        }
    }

    @MainActor
    private static func oldPageHeader(width: CGFloat, lastReferenced: String = "2025-02-06") -> some View {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let entity = Entity(id: "alpha-co", name: "Alpha Co", type: .company, status: .active, confidence: 0.99,
                            created: "2025-02-04", lastReferenced: lastReferenced, decayRate: 0.05, sourceEpisodes: [],
                            tags: [], related: [], version: 1,
                            markdownContent: "## Summary\nAs of February 2025, a company running a summer programme.",
                            history: [])
        return EntityCardHeader(
            entity: entity, summary: EntityHeaderWords.summary(markdown: entity.markdownContent, isStub: false),
            isStub: false, canGoBack: false, backTargetName: nil, onBack: {}, showsClose: true, onClose: {},
            tabs: EntityTabs.tabs(claims: [], historyCount: 2), selection: .constant(.content),
            inset: EntityCardStyle.column.inset, today: ISODay(year: 2026, month: 10, day: 7)
        ).environment(store)
    }

    /// F-12 (R-PE16) — the person hero and a six-cell strip never want more than the column, at every zoom.
    @MainActor
    func testThePersonHeroNeverWantsMoreThanItsColumn() throws {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let entity = Entity(id: "leo-example", name: String(repeating: "Leo Example ", count: 6), type: .person,
                            status: .active, confidence: 0.92, created: "2026-03-12", lastReferenced: "2026-09-24",
                            decayRate: 0.05, sourceEpisodes: [], tags: [], related: [], version: 1,
                            markdownContent: "## Summary\n" + String(repeating: "Robotics engineer at Northwind. ", count: 8),
                            history: [])
        let facts = [PersonFact.Kind.worksAt, .role, .knownSince, .lastMentioned, .conversations, .contacts].map {
            PersonFact(kind: $0, label: "Last mentioned", value: String(repeating: "Northwind ", count: 5),
                       line: "Claude Code · 10:42", marks: ["claude-code", "codex"])
        }
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let width = GraphColumns.entityMin * CGFloat(scale)
            let header = EntityCardHeader(
                entity: entity, summary: EntityHeaderWords.summary(markdown: entity.markdownContent, isStub: false),
                isStub: false, canGoBack: false, backTargetName: nil, onBack: {}, showsClose: true, onClose: {},
                tabs: EntityTabs.tabs(claims: [], historyCount: 3), selection: .constant(.content),
                inset: EntityCardStyle.card.inset, facts: facts, onShowOnGraph: {}
            ).environment(store)
            let renderer = ImageRenderer(content: header)
            renderer.proposedSize = ProposedViewSize(width: width, height: nil)
            let size = try XCTUnwrap(renderer.nsImage).size
            XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(scale): \(size.width)")
        }
    }
}
