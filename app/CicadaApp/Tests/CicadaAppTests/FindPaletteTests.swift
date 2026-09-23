import SwiftUI
import XCTest
@testable import CicadaApp

/// G136 S3/S4 — the palette's state machine, keys and hand-offs, without a
/// view. NEVER call `askNow()` or activate an Ask / re-ask row here:
/// `AskViewModel.ask()` posts `/ask` through `APIClient.shared` — on a dev
/// machine the owner's live backend — and `/ask` spends.
@MainActor
final class FindPaletteTests: XCTestCase {
    private func model(_ inputs: QuickIndexInputs = FindFixtures.inputs()) -> FindPaletteModel {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        // G136 S4 — a fake server tier and a clock that never waits: no test
        // builds a palette that could reach `APIClient.shared`.
        let model = FindPaletteModel(store: store, api: FakeFindSearch(), sleeper: { _ in try Task.checkCancellation() })
        model.install(QuickIndex.build(inputs))
        return model
    }

    func testTypingFillsTheGroupsAtOnceAndSelectsTheTopHit() {
        let m = model()
        m.setQuery("alpha")
        XCTAssertEqual(m.results.ask?.destination, .ask("alpha"))
        XCTAssertEqual(m.results.topHit?.key, FindRowKey(kind: .entity, id: "alpha-project"))
        XCTAssertEqual(m.selection, FindRowKey(kind: .entity, id: "alpha-project"))
        XCTAssertTrue(m.footerText.hasPrefix("3 results in 3 groups"))
    }

    func testArrowsMoveAndReturnOpensTheSelectedRow() {
        let m = model()
        m.setQuery("alpha")
        XCTAssertEqual(m.submit(), .entity(id: "alpha-project"))
        m.move(.previous)
        XCTAssertEqual(m.selection?.kind, .ask)
        m.move(.last)
        XCTAssertEqual(m.selection?.kind, .inbox)
    }

    func testEscapeGoesAskToFindThenClearsThenCloses() {
        let m = model()
        m.present(prefill: "alpha")
        XCTAssertTrue(m.isPresented)
        m.setMode(.ask)
        XCTAssertEqual(m.ask.question, "alpha", "the text travels into Ask")
        XCTAssertFalse(m.escape())
        XCTAssertEqual(m.mode, .find)
        XCTAssertEqual(m.query, "alpha", "Esc in Ask keeps the text")
        XCTAssertFalse(m.escape())
        XCTAssertEqual(m.query, "")
        XCTAssertTrue(m.escape(), "the third Esc closes")
        m.dismissed()
        XCTAssertFalse(m.isPresented)
    }

    func testRecentsKeepIdsOnly() throws {
        let m = model()
        m.setQuery("alpha")
        XCTAssertEqual(m.activate(FindRowKey(kind: .entity, id: "alpha-project")), .entity(id: "alpha-project"))
        XCTAssertEqual(m.recents, [FindRowKey(kind: .entity, id: "alpha-project")])
        m.setQuery("")
        XCTAssertEqual(m.results.groups[.recent]?.map(\.key.id), ["alpha-project"])
        let data = try JSONEncoder().encode(m.recents)
        let objects = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [[String: String]])
        XCTAssertEqual(Set(objects[0].keys), ["kind", "id"], "a recent is a key — never the query, never a title")
    }

    func testASettingsRowExplainsInsteadOfOpening() {
        let m = model()
        m.setQuery("integrations")
        XCTAssertNil(m.activate(FindRowKey(kind: .setting, id: SettingsSection.integrations.rawValue)))
        XCTAssertNotNil(m.hint)
        m.setQuery("integration")
        XCTAssertNil(m.hint, "the next keystroke clears it")
    }

    func testAnAskedBeforeRowShowsTheCachedAnswerInAskMode() throws {
        var inputs = FindFixtures.inputs()
        inputs.askHistory = [AskHistoryEntry(question: "where does alpha run", askedAt: Date(),
                                             answer: AskResponse(answer: "On the example host.", confidence: 0.8))]
        let m = model(inputs)
        m.ask.history = inputs.askHistory
        m.setQuery("where does")
        let key = try XCTUnwrap(m.results.groups[.askedBefore]?.first?.key)
        XCTAssertNil(m.activate(key))
        XCTAssertEqual(m.mode, .ask)
        XCTAssertEqual(m.ask.answer?.answer, "On the example host.")
        XCTAssertEqual(m.fieldText, "where does alpha run")
    }

    func testANewIndexNeverReordersWhatIsShown() {
        let m = model()
        m.setQuery("alpha")
        let before = m.results
        var more = FindFixtures.inputs()
        more.nodes.append(FindFixtures.node("alpha-2", "alpha", degree: 99))
        m.install(QuickIndex.build(more))
        XCTAssertEqual(m.results, before, "applies on the next keystroke (R-SU5)")
        m.setQuery("alpha ")
        XCTAssertEqual(m.results.topHit?.key.id, "alpha-2")
    }

    func testTheKeymap() {
        XCTAssertEqual(FindKeymap.action(key: .downArrow, modifiers: [], mode: .find), .move(.next))
        XCTAssertEqual(FindKeymap.action(key: .downArrow, modifiers: .command, mode: .find), .move(.last))
        XCTAssertEqual(FindKeymap.action(key: .upArrow, modifiers: .command, mode: .find), .move(.first))
        XCTAssertEqual(FindKeymap.action(key: .tab, modifiers: [], mode: .find), .move(.nextGroup))
        XCTAssertEqual(FindKeymap.action(key: .tab, modifiers: .shift, mode: .find), .move(.previousGroup))
        XCTAssertEqual(FindKeymap.action(key: KeyEquivalent("\u{19}"), modifiers: .shift, mode: .find), .move(.previousGroup))
        XCTAssertEqual(FindKeymap.action(key: .return, modifiers: .command, mode: .find), .askNow)
        XCTAssertEqual(FindKeymap.action(key: .return, modifiers: .option, mode: .find), .secondary)
        XCTAssertEqual(FindKeymap.action(key: .return, modifiers: [], mode: .find), .none, "plain ⏎ is onSubmit's")
        XCTAssertEqual(FindKeymap.action(key: .escape, modifiers: [], mode: .ask), .escape)
        XCTAssertEqual(FindKeymap.action(key: .downArrow, modifiers: [], mode: .ask), .none, "an answer has no list")
    }

    func testCommandKTogglesButARequestWithTextAlwaysOpens() {
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: false, firstRunShowing: false),
                       .open(prefill: "", mode: .find))
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: true, firstRunShowing: false), .close)
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(prefill: "alpha"), isOpen: true, firstRunShowing: false),
                       .open(prefill: "alpha", mode: .find), "a Search-all-of-memory row never closes what it asks for")
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: false, firstRunShowing: true), .ignore,
                       "never over the first-run sheet (§3.1)")
        XCTAssertNotEqual(PaletteRequest(), PaletteRequest(), "two ⌘K presses are two changes")
    }

    /// Track I part b (R-IB5) — on Home, ⌘K focuses Home's own field; the overlay never opens over it.
    func testCommandKOnHomeFocusesItsFieldInsteadOfTheOverlay() {
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: false, firstRunShowing: false, homeVisible: true),
                       .focusHome(prefill: "", mode: .find))
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(prefill: "alpha", mode: .ask), isOpen: false,
                                             firstRunShowing: false, homeVisible: true),
                       .focusHome(prefill: "alpha", mode: .ask))
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: true, firstRunShowing: false, homeVisible: true),
                       .close, "an overlay opened elsewhere, then ⌘1, still closes on ⌘K")
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: false, firstRunShowing: true, homeVisible: true),
                       .ignore)
    }

    func testAConversationFindsItsSourceCard() {
        let rows = [SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, harness: "claude-code"),
                    SourceOverview(id: "chat-export:chatgpt", label: "ChatGPT export", kind: .harness,
                                   origins: ["chatgpt-export"])]
        XCTAssertEqual(ConversationSource.sourceId(harness: "claude-code", origin: nil, rows: rows), "harness:claude-code")
        XCTAssertEqual(ConversationSource.sourceId(harness: nil, origin: "chatgpt-export", rows: rows), "chat-export:chatgpt")
        XCTAssertNil(ConversationSource.sourceId(harness: "cursor", origin: nil, rows: rows), "never a guessed neighbour")
    }
}
