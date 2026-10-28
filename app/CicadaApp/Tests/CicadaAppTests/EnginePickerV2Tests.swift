import SwiftUI
import XCTest
@testable import CicadaApp

/// Engine picker v2 (ruling 48 part 11, `10-engine-picker`): the filterable model list's every decision, from
/// synthetic catalogues; nothing reaches `APIClient.shared`.
@MainActor
final class EnginePickerV2Tests: XCTestCase {
    private func card(_ ids: [(String, String, String)], new: Set<String> = [], asOf: String? = "2026-10-28T10:00:00Z",
                      source: String = "agent models", drift: String? = nil, connected: Bool = true) -> SleepEngineCandidate {
        let models = ids.map { id, key, label in
            ModelCatalogue.Model(id: id, source: "harness", asOf: asOf, family: key, familyLabel: label,
                                 new: new.contains(id))
        }
        return SleepEngineCandidate(id: "cursor", label: "Cursor", available: true, connected: connected,
                                    models: ids.map(\.0), detail: nil, kind: "plan", engine: "cursor-cli",
                                    mark: "cursor",
                                    catalogue: ModelCatalogue(engine: "cursor-cli", asOf: asOf, source: source,
                                                              drift: drift, models: models))
    }

    private let roster: [(String, String, String)] = [
        ("opus-5.5", "claude", "Claude"), ("sonnet-5", "claude", "Claude"), ("sonnet-4.6", "claude", "Claude"),
        ("opus-4.5", "claude", "Claude"), ("haiku-4.5", "claude", "Claude"),
        ("gpt-6", "gpt", "GPT"), ("gpt-5.5", "gpt", "GPT"),
        ("composer-2", "own", "Cursor's own"),
    ]
    private let now = EngineModelListModel.date(iso: "2026-10-28T10:02:30Z")!

    func testFamiliesShowTheirNewestThreeAndTheRestWaitBehindShowOlder() {
        let list = EngineModelListModel.from(card: card(roster, new: ["gpt-6"]), selected: "sonnet-5", now: now)
        XCTAssertEqual(list.sections.map(\.label), ["Claude", "GPT", "Cursor's own"])
        XCTAssertEqual(list.sections[0].rows.map(\.id), ["opus-5.5", "sonnet-5", "sonnet-4.6"])
        XCTAssertEqual(list.sections[0].hidden, 2)
        XCTAssertEqual(list.sections[0].total, 5)
        XCTAssertTrue(list.sections[1].rows[0].isNew)
        XCTAssertTrue(list.sections[0].rows[1].isSelected)
        XCTAssertEqual(list.total, 8)
        let open = EngineModelListModel.from(card: card(roster), selected: "sonnet-5", expanded: ["claude"], now: now)
        XCTAssertEqual(open.sections[0].rows.count, 5)
        XCTAssertEqual(open.sections[0].hidden, 0)
    }

    func testAnOlderChosenModelIsAlwaysOnScreen() {
        let list = EngineModelListModel.from(card: card(roster), selected: "haiku-4.5", now: now)
        XCTAssertEqual(list.sections[0].rows.map(\.id), ["opus-5.5", "sonnet-5", "sonnet-4.6", "haiku-4.5"])
        XCTAssertEqual(list.sections[0].hidden, 1)
    }

    func testTheFilterShowsEveryMatchAndSaysWhenNothingMatches() {
        let list = EngineModelListModel.from(card: card(roster), selected: "", filter: "4.", now: now)
        XCTAssertEqual(list.flat.map(\.id), ["sonnet-4.6", "opus-4.5", "haiku-4.5"])
        XCTAssertTrue(EngineModelListModel.from(card: card(roster), selected: "", filter: "zzz", now: now).sections.isEmpty)
        // A family name finds its models.
        XCTAssertEqual(EngineModelListModel.from(card: card(roster), selected: "", filter: "gpt", now: now).flat.count, 2)
    }

    func testTheKeysWalkTheRowsAndStopAtTheEnds() {
        let list = EngineModelListModel.from(card: card(roster), selected: "", filter: "gpt", now: now)
        XCTAssertEqual(list.step(from: nil, by: 1), "gpt-6")
        XCTAssertEqual(list.step(from: "gpt-6", by: 1), "gpt-5.5")
        XCTAssertEqual(list.step(from: "gpt-5.5", by: 1), "gpt-5.5")
        XCTAssertEqual(list.step(from: "gpt-6", by: -1), "gpt-6")
    }

    func testFreshnessIsWhoseListAndHowOldInWords() {
        let list = EngineModelListModel.from(card: card(roster), selected: "", now: now)
        XCTAssertEqual(list.freshness, "Cursor's own list, as of 2 min ago")
        XCTAssertTrue(list.canRefresh)
        let builtIn = EngineModelListModel.from(card: card(roster, source: "default"), selected: "", now: now)
        XCTAssertEqual(builtIn.freshness, "Cicada's built-in list")
        XCTAssertFalse(builtIn.canRefresh)
        let signedOut = EngineModelListModel.from(card: card(roster, connected: false), selected: "", now: now)
        XCTAssertFalse(signedOut.canRefresh, "Refresh reads a signed-in tool only")
        let drifted = EngineModelListModel.from(card: card(roster, drift: "changed shape"), selected: "", now: now)
        XCTAssertEqual(drifted.drift, "changed shape")
    }

    func testAnOlderBackendIsOneUnnamedFamily() {
        let bare = SleepEngineCandidate(id: "agent", label: "Claude plan", available: true, connected: true,
                                        models: ["sonnet", "haiku", "opus"], detail: nil)
        let list = EngineModelListModel.from(card: bare, selected: "haiku", now: now)
        XCTAssertEqual(list.sections.count, 1)
        XCTAssertEqual(list.sections[0].label, "")
        XCTAssertEqual(list.flat.map(\.id), ["sonnet", "haiku", "opus"])
    }

    func testTheCatalogueDecodesAndAnOlderBodyStillDecodes() throws {
        let json = #"{"id":"cursor","label":"Cursor","available":true,"connected":true,"models":["auto"],"catalogue":{"engine":"cursor-cli","source":"agent models","asOf":"2026-10-28T10:00:00Z","models":[{"id":"auto","source":"harness","family":"own","familyLabel":"Cursor's own","new":true}]}}"#
        let c = try JSONDecoder().decode(SleepEngineCandidate.self, from: Data(json.utf8))
        XCTAssertEqual(c.catalogue?.models.first?.familyLabel, "Cursor's own")
        XCTAssertEqual(c.catalogue?.models.first?.new, true)
        let old = try JSONDecoder().decode(SleepEngineCandidate.self, from: Data(
            #"{"id":"agent","label":"Claude plan","available":true,"connected":true,"models":["sonnet"]}"#.utf8))
        XCTAssertNil(old.catalogue)
    }

    func testTheMenuListsModelsInItsSecondColumnAndNoNativePickerRemains() throws {
        let body = EnginePickerTimingTests.response()
        let menu = EngineQuickMenuModel.from(body)
        XCTAssertEqual(menu.listCard?.id, "cursor")
        XCTAssertEqual(EngineQuickMenu.width(for: menu), EngineQuickMenu.width + EngineQuickMenu.listWidth)
        let source = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Sleep/EngineQuickMenu.swift") })
        let text = try String(contentsOf: source, encoding: .utf8)
        XCTAssertEqual(text.components(separatedBy: "Picker(").count - 1, 1, "only the reserve's menu remains (DR-81)")
    }

    func testRefreshAsksOnceAndKeepsTheListOnAFailure() async {
        var asked: [String] = []
        let first = EnginePickerTimingTests.response()
        let vm = SleepEngineViewModel(fetch: { first }, update: { _, _, _, _ in first },
                                      refresh: { id in asked.append(id); throw URLError(.timedOut) })
        await vm.load()
        await vm.refreshModels("cursor")
        XCTAssertEqual(asked, ["cursor"])
        XCTAssertEqual(vm.refreshFailed, "cursor")
        XCTAssertEqual(vm.response?.candidates.map(\.id), first.candidates.map(\.id))
        XCTAssertNil(vm.refreshing)
    }
}
