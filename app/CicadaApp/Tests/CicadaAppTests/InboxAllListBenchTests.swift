import XCTest
import SwiftUI
@testable import CicadaApp

/// Owner 2026-10-29: "In home when i click All 465 questions the app gets stuck for a bit." What an "All N" list costs
/// the main thread on the click, at ~2,000 rows: the Inbox page's derived lists (built once per change, not once per
/// read), each row's words, and laying the list out (lazy: the rows on screen, not every row). The budget tests always
/// run, with generous margins for a debug build on a loaded Mac; `CICADA_APP_BENCH=1` also prints the `BENCH` lines
/// (best of N, ms) the report quotes. Before this change, at 465 questions: page derivations 2,397 ms, one sort 478 ms,
/// laying the list out 1,510 ms; at 2,000: 14,379 / 2,858 / 8,265 ms (debug build).
@MainActor
final class InboxAllListBenchTests: XCTestCase {
    static let rows = 2_000

    @discardableResult
    private func ms(_ label: String, runs: Int = 3, _ body: () -> Void) -> Double {
        body()
        var best = Double.infinity
        for _ in 0..<runs {
            let start = DispatchTime.now().uptimeNanoseconds
            body()
            best = min(best, Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000)
        }
        print(String(format: "BENCH %-44@ %9.2f ms", label as NSString, best))
        return best
    }

    private func once(_ body: () -> Void) -> Double {
        let start = DispatchTime.now().uptimeNanoseconds
        body()
        return Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000
    }

    /// `n` synthetic questions shaped like an owner's inbox: a third possible duplicates, the rest conflicts, fading
    /// pages, questions and follow-ups, on ~n/2 pages, each with the conversation that raised it. Placeholders only.
    static func items(_ n: Int, prefix: String = "inbox") -> [InboxItem] {
        let kinds = ["merge_suggestion", "conflict", "decay", "clarification", "followup", "merge_suggestion"]
        let harnesses = ["claude-code", "codex", "", "cursor"]
        var json: [String] = []
        for i in 0..<n {
            let kind = kinds[i % kinds.count]
            let page = i % 7 == 0 ? "" : "page-\(i / 2)"
            let name = page.isEmpty ? "" : "Page \(i / 2)"
            let day = String(format: "2026-%02d-%02d", 1 + (i % 9), 1 + (i % 28))
            let episode = "ep_\(day.replacingOccurrences(of: "-", with: ""))_\(String(format: "%03d", i % 50))"
            json.append(#"""
            {"id":"\#(prefix)-\#(i)","kind":"\#(kind)","requiredInput":"choice","title":"Is Page \#(i / 2) still the same as Page \#(i / 2 + 1)?","priority":\#(Double(i % 10) / 10),"createdDate":"\#(day)","entityId":"\#(page)","entityName":"\#(name)","cause":{"episodeId":"\#(episode)","timestamp":"\#(day)T10:\#(String(format: "%02d", i % 60)):00Z","harness":"\#(harnesses[i % harnesses.count])","origin":"mcp","conversationTitle":"Conversation \#(i)","excerpt":"words"}}
            """#)
        }
        return try! JSONDecoder().decode([InboxItem].self, from: Data("[\(json.joined(separator: ","))]".utf8))
    }

    private func store(_ items: [InboxItem]) -> Store {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        store.inbox.value = items
        store.inbox.loadedAt = Date()
        return store
    }

    /// Everything `InboxPage.body` and the list read on the click that opens the full list.
    private func pageDerivations(_ vm: InboxViewModel) {
        vm.reconcile()
        vm.reconcileReview()
        _ = vm.items.map(\.id)
        _ = vm.eyebrow
        _ = vm.tabs
        _ = vm.agentRequests
        _ = vm.whereToCheckReviews
        _ = vm.reviewEntries
        _ = vm.rows
        _ = vm.lines
        _ = vm.openItem
        _ = vm.visible.count
    }

    private func rowWords(_ items: [InboxItem]) {
        let now = Date.now
        for item in items {
            _ = InboxRowAge.of(item, now: now)
            _ = InboxSourceLine.row(item)
            _ = InboxSourceLine.help(item)
            _ = InboxSourceLine.markOrigin(item)
            _ = InboxRowWords.namesItsPage(item)
        }
    }

    /// `view` in a never-shown window at `size`, laid out the way the app lays it out (the first frame).
    private func layOut<V: View>(_ view: V, size: CGSize = CGSize(width: 1_100, height: 800)) {
        let host = NSHostingView(rootView: view.frame(width: size.width, height: size.height, alignment: .topLeading))
        host.frame = CGRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        host.displayIfNeeded()
        window.contentView = nil
    }

    private func list(_ vm: InboxViewModel) -> some View {
        InboxQuestionList(entries: vm.rows, style: .wide, width: 1_100, openId: nil, undoShortcut: true,
                          landingToken: 0, open: { _ in }, undo: {}, move: { _ in }, focusQuestion: {},
                          escape: {}, lines: vm.lines)
    }

    // MARK: - Budgets

    /// The page's derived lists at ~2,000 questions: one build on the click, then every further read in that draw
    /// (and the next, until the inbox or the tab changes) is the kept value.
    func testThePagesDerivedListsAreBuiltOnceAndCheaplyAtTwoThousandQuestions() {
        let vm = InboxViewModel(store: store(Self.items(Self.rows)))
        let build = once { pageDerivations(vm) }
        let reread = ms("[\(Self.rows)] page derivations, kept") { pageDerivations(vm) }
        print(String(format: "BENCH %-44@ %9.2f ms", "[\(Self.rows)] page derivations, first build" as NSString, build))
        XCTAssertEqual(vm.visible.count, Self.rows)
        XCTAssertLessThan(build, 600, "the first build of the page's lists at \(Self.rows) questions (was ~14 s)")
        XCTAssertLessThan(reread, 15, "a further draw reads the kept lists")
    }

    /// The click's first frame: the grouped list laid out at full width with ~2,000 questions builds only the rows a
    /// window shows.
    func testTheFullListsFirstFrameAtTwoThousandQuestionsIsUnderBudget() {
        let vm = InboxViewModel(store: store(Self.items(Self.rows)))
        pageDerivations(vm)
        let first = once { layOut(list(vm)) }
        let again = ms("[\(Self.rows)] lay out the full list", runs: 2) { layOut(list(vm)) }
        print(String(format: "BENCH %-44@ %9.2f ms", "[\(Self.rows)] lay out the full list, first" as NSString, first))
        XCTAssertLessThan(again, 400, "the list's first frame at \(Self.rows) questions (was ~8 s, every row built)")
    }

    /// Every other "All N" opens in `FullListSheet`; its rows are lazy too.
    func testTheFullListSheetsFirstFrameAtTwoThousandRowsIsUnderBudget() {
        let rows = (0..<Self.rows).map { "Row \($0) — a placeholder line long enough to wrap at the sheet's width" }
        let sheet = FullListSheet(title: "All") {
            ForEach(rows, id: \.self) { Text($0).font(CicadaTheme.bodyFont).lineLimit(2) }
        }
        let time = ms("[\(Self.rows)] lay out FullListSheet", runs: 2) {
            layOut(sheet, size: CGSize(width: 640, height: 560))
        }
        XCTAssertLessThan(time, 300, "the sheet's first frame at \(Self.rows) rows")
    }

    // MARK: - The kept lists follow every change

    func testTheKeptListsFollowTheInboxTheTabAndTheHeldAnswer() {
        let store = store(Self.items(30))
        let vm = InboxViewModel(store: store)
        XCTAssertEqual(vm.visible.count, 30)
        XCTAssertEqual(vm.rows.count, 30)

        // A refresh brings new questions.
        store.inbox.value = Self.items(40)
        XCTAssertEqual(vm.visible.count, 40)
        XCTAssertEqual(vm.tabs.first?.count, 40)

        // A question's words change in place, same ids.
        var edited = Self.items(40)
        edited[0].title = "Placeholder question, reworded"
        store.inbox.value = edited
        XCTAssertTrue(vm.visible.contains { $0.title == "Placeholder question, reworded" })

        // An optimistic resolve hides one.
        store.hiddenInboxIds.insert("inbox-1")
        XCTAssertFalse(vm.visible.contains { $0.id == "inbox-1" })
        XCTAssertFalse(store.visibleInbox.contains { $0.id == "inbox-1" })
        store.hiddenInboxIds.remove("inbox-1")
        XCTAssertTrue(vm.visible.contains { $0.id == "inbox-1" })

        // The tab.
        vm.setFilter(.conflict)
        XCTAssertTrue(vm.visible.allSatisfy { $0.kind == .conflict })
        XCTAssertEqual(vm.visible.count, vm.tabs.first { $0.id == .conflict }?.count)
        vm.setFilter(nil)
        XCTAssertEqual(vm.visible.count, 40)

        // An answer held for its Undo window leaves the questions and puts its Undo row in their place.
        let target = vm.visible[3]
        XCTAssertTrue(vm.answer(target, QuestionResolution(action: "dismiss")))
        XCTAssertFalse(vm.visible.contains { $0.id == target.id })
        XCTAssertTrue(vm.rows.contains { if case .undo(_, let item) = $0 { item.id == target.id } else { false } })
        XCTAssertTrue(vm.lines.contains { if case .entry(.undo(_, let item), _) = $0 { item.id == target.id } else { false } })
        XCTAssertNotNil(vm.undo())
        XCTAssertTrue(vm.visible.contains { $0.id == target.id })
        XCTAssertFalse(vm.rows.contains { if case .undo = $0 { true } else { false } })

        // A bank switch's empty snapshot.
        store.inbox.value = []
        XCTAssertTrue(vm.visible.isEmpty)
        XCTAssertTrue(vm.lines.isEmpty)
    }

    /// The kept lists are exactly what the unkept derivation draws (same order, same lines).
    func testTheKeptListsMatchTheDerivation() {
        let items = Self.items(300)
        let vm = InboxViewModel(store: store(items))
        let questions = items.filter { !$0.isTopCard }
        let sections = InboxGroups.sections(InboxColumns.visible(questions, filter: nil), byKind: true)
        XCTAssertEqual(vm.visible.map(\.id), InboxGroups.ordered(InboxColumns.visible(questions, filter: nil),
                                                                  byKind: true).map(\.id))
        let lines = InboxListLine.lines(sections, byKind: true, held: nil, heldItem: nil,
                                        reviews: ReviewEntries.of(questions)) { _ in true }
        XCTAssertEqual(vm.lines.map(\.id), lines.map(\.id))
    }

    /// The G115 order with each day read once is the order `precedes` gives.
    func testTheOneSortKeepsTheG115Order() {
        let items = Self.items(500).shuffled()
        XCTAssertEqual(InboxColumns.ordered(items).map(\.id), items.sorted(by: InboxColumns.precedes).map(\.id))
    }

    // MARK: - The lazy list draws every line, once

    func testTheLazyListDrawsEachLineAsItsOwnChildWithTheExplainerUnderItsHeader() throws {
        let items = Self.items(24)
        let vm = InboxViewModel(store: store(items))
        let draw = InboxListDraw.items(vm.lines)
        let lineIds = draw.compactMap { if case .line(let line, _) = $0 { line.id } else { nil } }
        XCTAssertEqual(lineIds, vm.lines.map(\.id), "every line, in order, one child each")
        XCTAssertEqual(Set(draw.map(\.id)).count, draw.count, "no two children share an id")
        let kinds = vm.lines.filter { if case .kind = $0 { true } else { false } }.count
        XCTAssertEqual(draw.filter { if case .explainer = $0 { true } else { false } }.count, kinds,
                       "one explainer per group")
        guard case .line(.kind, let leads)? = draw.first else { return XCTFail("\(String(describing: draw.first))") }
        XCTAssertFalse(leads, "the first group has no gap above it")
        guard case .explainer? = draw.dropFirst().first else { return XCTFail("the explainer sits under its header") }
        XCTAssertEqual(draw.filter { if case .line(.kind, true) = $0 { true } else { false } }.count, kinds - 1)
    }

    /// R-DI4 — the lazy list's Undo row never owns ⌘Z (scrolled away, it is not built); the list's keeper does.
    func testTheHeldAnswersShortcutIsTheListsNotTheLazyRows() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        let list = try String(contentsOf: root.appendingPathComponent("Views/Inbox/InboxQuestionList.swift"),
                              encoding: .utf8)
        XCTAssertTrue(list.contains("LazyVStack("))
        XCTAssertTrue(list.contains("InboxUndoRow(held: held, item: item, style: style, shortcutEnabled: false"))
        XCTAssertTrue(list.contains("UndoShortcutKeeper(undo: undo)"))
        let sheet = try String(contentsOf: root.appendingPathComponent("Views/Common/FullListSheet.swift"),
                               encoding: .utf8)
        XCTAssertTrue(sheet.contains("LazyVStack("))
    }

    // MARK: - Numbers for the report

    func testPrintTheFullListsCostAtOwnerScale() throws {
        guard ProcessInfo.processInfo.environment["CICADA_APP_BENCH"] == "1" else {
            throw XCTSkip("set CICADA_APP_BENCH=1 to print the numbers")
        }
        for n in [465, 2_000] {
            let items = Self.items(n, prefix: "bench\(n)")
            let vm = InboxViewModel(store: store(items))
            let build = once { pageDerivations(vm) }
            print(String(format: "BENCH %-44@ %9.2f ms", "[\(n)] page derivations, first build" as NSString, build))
            ms("[\(n)] page derivations, kept") { pageDerivations(vm) }
            ms("[\(n)] one G115 sort") { _ = InboxColumns.visible(items, filter: nil) }
            ms("[\(n)] row words, every row") { rowWords(items) }
            ms("[\(n)] HomeQuestions.figures") { _ = HomeQuestions.figures(items, now: .now) }
            ms("[\(n)] lay out the full list", runs: 2) { layOut(list(vm)) }
        }
    }
}
