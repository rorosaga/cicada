import XCTest
@testable import CicadaApp

/// Track I part b (R-IB4, R-IB6) — Home's field is the palette's body with its
/// own model: the one Ask, no recents, the cards until the first keystroke.
@MainActor
final class HomeSearchTests: XCTestCase {
    private func store() -> Store {
        Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
              api: FakeSyncAPI())
    }

    func testHomeShowsResultsOnlyWhileSomethingIsTypedOrAsked() {
        XCTAssertTrue(FindPanelBody.showsBody(placement: .palette, query: "", mode: .find))
        XCTAssertFalse(FindPanelBody.showsBody(placement: .page, query: "  ", mode: .find),
                       "Home's cards stay until the first keystroke (H2)")
        XCTAssertTrue(FindPanelBody.showsBody(placement: .page, query: "alpha", mode: .find))
        XCTAssertTrue(FindPanelBody.showsBody(placement: .page, query: "", mode: .ask))
    }

    func testHomesFieldSharesTheOneAskButNeverWritesThePalettesRecents() async throws {
        let store = store()
        let palette = FindPaletteModel(store: store)
        let home = FindPaletteModel(store: store, ask: palette.ask, keepsRecents: false)
        XCTAssertTrue(home.ask === palette.ask, "one AskViewModel for the app (R-SU7)")
        home.install(QuickIndex.build(FindFixtures.inputs()))
        home.setQuery("alpha")
        let first = try XCTUnwrap(home.selection)
        // Activating the Ask row would call /ask and spend — the top hit here is the entity.
        XCTAssertNotEqual(first.kind, .ask)
        guard first.kind != .ask else { return }
        _ = home.activate(first)
        XCTAssertTrue(home.recents.isEmpty)
        let saved = await store.cache.load(.quickRecents, bank: store.bank, as: [FindRowKey].self)
        XCTAssertNil(saved, "two writers of .quickRecents would clobber each other's list")
    }

    func testFocusCarriesAPrefillAndAMode() {
        let search = HomeSearch(model: FindPaletteModel(store: store(), keepsRecents: false))
        search.focus(prefill: "bob-example", mode: .find)
        XCTAssertEqual(search.model.query, "bob-example")
        XCTAssertEqual(search.focusRequest, 1)
        search.focus(prefill: "", mode: .ask)
        XCTAssertEqual(search.model.mode, .ask)
        XCTAssertEqual(search.focusRequest, 2)
    }
}
