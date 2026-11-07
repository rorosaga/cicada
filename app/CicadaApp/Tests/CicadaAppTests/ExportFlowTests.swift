import XCTest
@testable import CicadaApp

/// ROR-126 — the pure halves: what a chosen start date and unticked chats leave to import, and when an agent may be
/// offered the request.
final class ExportFlowTests: XCTestCase {
    private func title(_ n: String, _ date: String, _ status: String = "new", deselected: Bool = false) -> IntakeTitle {
        IntakeTitle(title: n, date: date, key: "claude:\(n)", status: status, deselected: deselected)
    }

    private func preview(_ titles: [IntakeTitle]) -> IntakePreview {
        var p = IntakePreview()
        p.chatFiles = [URL(fileURLWithPath: "/tmp/x.zip")]
        p.titles = titles
        p.deselected = Set(titles.filter(\.deselected).compactMap(\.key))
        return p
    }

    func testStartDateAndUntickedChatsComeOffTheCount() {
        var p = preview([title("a", "2026-01-05"), title("b", "2026-03-01"), title("c", "2026-04-01", "grown"),
                         title("d", "2026-04-02", "unchanged")])
        XCTAssertEqual(p.chatImportCount, 3, "an unchanged chat is never counted")
        p.since = "2026-02-01"
        XCTAssertEqual(p.chatImportCount, 2)
        p.deselected.insert("claude:c")
        XCTAssertEqual(p.chatImportCount, 1)
        XCTAssertEqual(p.choice, ImportChoice(since: "2026-02-01", exclude: ["claude:c"]))
    }

    func testAChatLeftOutBeforeStartsUnticked() {
        let p = preview([title("a", "2026-01-05", deselected: true), title("b", "2026-03-01")])
        XCTAssertEqual(p.deselected, ["claude:a"])
        XCTAssertEqual(p.chatImportCount, 1)
    }

    func testWithoutKeysTheBackendDeltaStandsAndNoChoiceIsOffered() {
        var p = IntakePreview()
        p.chatFiles = [URL(fileURLWithPath: "/tmp/x.zip")]
        p.titles = [IntakeTitle(title: "a", date: "2026-01-01")]
        p.delta = IntakeDelta(new: 4, grown: 1)
        XCTAssertEqual(p.chatImportCount, 5)
        XCTAssertFalse(p.offersChoice)
    }

    func testTheWormWaitsOnlyForRequestsTheAgentActuallyMade() {
        let now = Date()
        let waits = ["claude", "chatgpt", "gemini"].map {
            ExportWait(vendor: $0, bank: "b", requestedAt: now, remindAt: now)
        }
        let requests = [ExportRequest(vendor: "claude", state: "asked"),
                        ExportRequest(vendor: "chatgpt", state: "requested"),
                        ExportRequest(vendor: "gemini", state: "manual")]
        XCTAssertEqual(ExportAgentRules.waitingVendors(waits: waits, requests: requests), ["chatgpt"])
        XCTAssertEqual(ExportAgentRules.waitingVendors(waits: waits, requests: []).count, 3, "a hand-started wait stays")
    }

    func testNoAgentNoOffer() {
        XCTAssertFalse(ExportAgentRules.canRequest(wiring: nil, methods: nil))
    }
}
