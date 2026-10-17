import SwiftUI
import XCTest
@testable import CicadaApp

/// The entity card's leftovers from the 2026-10-16 QA rounds: one row of tabs, no "Timeline 0", the day said once.
final class EntityCardPolishTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        super.tearDown()
    }

    private func claim(_ id: String, predicate: String = "uses", validFrom: String = "2026-10-16",
                       validTo: String? = nil, evidenceEpisode: String? = nil) throws -> Claim {
        let to = validTo.map { #","validTo":"\#($0)""# } ?? ""
        let ev = evidenceEpisode.map { #","evidence":[{"episode":"\#($0)","start":0,"end":4,"kind":"user"}]"# } ?? ""
        return try JSONDecoder().decode(Claim.self, from: Data(#"""
            {"id":"\#(id)","text":"t","predicate":"\#(predicate)","context":"work","observer":"user","object":"x",\#
            "validFrom":"\#(validFrom)"\#(to)\#(ev)}
            """#.utf8))
    }

    /// "Timeline 0" offered a tab with nothing in it (DR-38): once the claims are known and none is contested, the tab
    /// is not drawn. Unknown counts keep it (no jump while loading), and so does a belief's clock that has it open.
    func test_noTimelineTabWhenNothingIsContested() throws {
        let uncontested = [try claim("a"), try claim("b", predicate: "role")]
        XCTAssertEqual(EntityTabs.tabs(claims: uncontested, historyCount: 2).map(\.id),
                       [EntityCardTab.content, .perspectives, .history], "no Timeline 0")
        XCTAssertEqual(EntityTabs.tabs(claims: uncontested, historyCount: 2, selected: .timeline).map(\.id).last,
                       EntityCardTab.timeline, "a belief's clock still opens it")
        XCTAssertEqual(EntityTabs.tabs(claims: nil, historyCount: nil).map(\.id).last, EntityCardTab.timeline,
                       "not known yet: the row keeps its shape")
        let contested = [try claim("a", validTo: "2026-10-17"), try claim("b")]
        let tabs = EntityTabs.tabs(claims: contested, historyCount: 2)
        XCTAssertEqual(tabs.last?.id, EntityCardTab.timeline)
        XCTAssertEqual(tabs.last?.count, 1)
    }

    /// "Known since Oct 16 · 0 days" — a page first heard of today is its day alone.
    func test_knownSinceNeverSaysZeroDays() {
        XCTAssertEqual(Copy.People.knownSinceValue("Oct 16", days: 0), "Oct 16")
        XCTAssertEqual(Copy.People.knownSinceValue("Oct 15", days: 1), "Oct 15 · 1 day")
        XCTAssertEqual(Copy.People.knownSinceValue("Oct 1", days: 20), "Oct 1 · 2 weeks")
    }

    /// "You said · Oct 16" beside a "today" tag said the day twice: the age is drawn only when no chip names its day.
    func test_theAgeTagStepsAsideWhenAChipAlreadyNamesTheDay() throws {
        let sameDay = try claim("a", validFrom: "2026-10-16", evidenceEpisode: "ep_2026-10-16_001")
        XCTAssertTrue(BeliefWords.ageRepeatsChips(sameDay, chipEpisodes: ["ep_2026-10-16_001"]))
        let older = try claim("b", validFrom: "2026-09-01", evidenceEpisode: "ep_2026-10-16_001")
        XCTAssertFalse(BeliefWords.ageRepeatsChips(older, chipEpisodes: ["ep_2026-10-16_001"]),
                       "true since another day: the age says something the chip does not")
        XCTAssertFalse(BeliefWords.ageRepeatsChips(sameDay, chipEpisodes: ["media-example-com"]), "a page chip has no day")
        XCTAssertFalse(BeliefWords.ageRepeatsChips(sameDay, chipEpisodes: []))
        XCTAssertTrue(BeliefWords.ageRepeatsChips(try claim("c", validFrom: "2026-10-16T09:00:00Z"),
                                                  chipEpisodes: ["ep_2026-09-01_002", "ep_2026-10-16_003"]))
    }

    /// The Rendered/Source switch and Copy moved into the header's tab row: the card has one row of tabs. The header
    /// with the page tools is no taller than the header without them, at every zoom.
    @MainActor
    func test_thePageToolsSitInTheTabRow() throws {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let entity = Entity(id: "alpha-project", name: "Alpha project", type: .project, status: .active,
                            confidence: 0.9, created: "2026-01-05", lastReferenced: "2026-10-16", decayRate: 0.05,
                            sourceEpisodes: [], tags: [], related: [], version: 1,
                            markdownContent: "## Summary\nA synthetic project.", history: [])
        func height(tools: Bool, scale: Double) throws -> CGFloat {
            CicadaTheme.uiScale = scale
            let header = EntityCardHeader(
                entity: entity, summary: "A synthetic project.", isStub: false, canGoBack: false,
                backTargetName: nil, onBack: {}, showsClose: true, onClose: {},
                tabs: EntityTabs.tabs(claims: [], historyCount: 3), selection: .constant(.content),
                inset: EntityCardStyle.column.inset,
                showsSource: tools ? .constant(false) : nil, onCopy: tools ? {} : nil
            ).environment(store)
            let renderer = ImageRenderer(content: header)
            renderer.proposedSize = ProposedViewSize(width: GraphColumns.entityMin * CGFloat(scale), height: nil)
            return try XCTUnwrap(renderer.nsImage).size.height
        }
        for scale in [0.8, 1.0, 1.4] {
            let without = try height(tools: false, scale: scale)
            XCTAssertLessThanOrEqual(try height(tools: true, scale: scale), without + 2 * CGFloat(scale) + 0.5,
                                     "\(scale): the tools share the tab row, never a row of their own")
        }
    }

    /// The card draws no second tab row: its only `TextTabs` is the header's.
    func test_theCardHasNoSecondTabRow() throws {
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Views/Graph/EntityDetailCard.swift")
        let source = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(source.contains("TextTabs("), "Rendered/Source is the header's toggle, not a second tab row")
    }
}

/// DR-57 — the Reader called an RSS item's and a calendar entry's text "You". Nobody said it: it is labelled by its
/// source, with the source's mark, in the Reader's turns and on every evidence chip and Noted row.
final class ArrivedSpeakerTests: XCTestCase {
    private let us = Locale(identifier: "en_US")
    private let utc = TimeZone(identifier: "UTC")!

    func test_aFeedOrCalendarTurnIsLabelledByItsSource() {
        let turn = EpisodeTurn(index: 0, start: 0, contentStart: 0, end: 4, role: "user")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn, harness: nil, origin: "rss"), "From the feed")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn, harness: nil, origin: "calendar"), "On your calendar")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn, harness: nil, origin: "calendar-local"), "On your calendar")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn, harness: "claude-code", origin: "mcp"), "You",
                       "the person's own words are still theirs")
        let system = EpisodeTurn(index: 0, start: 0, contentStart: 0, end: 4, role: "user", marker: "system")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(system, harness: nil, origin: "rss"),
                       Copy.Provenance.setupMessage, "a marker's own label is unchanged")
    }

    func test_theReaderBlockWearsTheSourcesMark() {
        let text = "Alpha Example ships v2."
        let doc = EpisodeText(episode: "ep_2026-10-16_001", text: text, origin: "rss",
                              turns: [EpisodeTurn(index: 0, start: 0, contentStart: 0, end: text.unicodeScalars.count)])
        let blocks = ReaderLayout.blocks(doc: doc, scalars: ScalarText(text), focus: nil, focusStyle: .focus)
        XCTAssertEqual(blocks.first?.speaker, "From the feed")
        XCTAssertEqual(blocks.first?.mark, "rss")
        let own = EpisodeText(episode: "ep_2026-10-16_002", text: text, harness: "claude-code",
                              turns: [EpisodeTurn(index: 0, start: 0, contentStart: 0, end: text.unicodeScalars.count)])
        let ownBlocks = ReaderLayout.blocks(doc: own, scalars: ScalarText(text), focus: nil, focusStyle: .focus)
        XCTAssertEqual(ownBlocks.first?.speaker, "You")
        XCTAssertNil(ownBlocks.first?.mark)
    }

    func test_aChipFromAFeedIsNeverYouSaid() {
        let chip = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-10-16_001", start: 0, end: 4,
                                                              kind: .user)))
        XCTAssertEqual(EvidenceLabel.chipText(chip, meta: EvidenceDocMeta(title: nil, harness: nil, origin: "rss"),
                                              locale: us, timeZone: utc), "From the feed · Oct 16")
        XCTAssertEqual(EvidenceLabel.chipText(chip, meta: EvidenceDocMeta(title: nil, harness: nil, origin: "calendar"),
                                              locale: us, timeZone: utc), "On your calendar · Oct 16")
        XCTAssertEqual(EvidenceLabel.chipText(chip, meta: EvidenceDocMeta(title: nil, harness: "claude-code", origin: nil),
                                              locale: us, timeZone: utc), "You said · Oct 16")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .user, agent: nil, origin: "rss"), "From the feed")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .assistant, agent: "Claude Code", origin: "rss"), "Claude Code replied",
                       "only the person's side moves")
    }
}
