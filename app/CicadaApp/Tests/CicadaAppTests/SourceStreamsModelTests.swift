import XCTest
@testable import CicadaApp

/// G245 — the in-memory streams model: ETag, never blank, a 404 as its own state, an answer across a bank switch dropped.
@MainActor
final class SourceStreamsModelTests: XCTestCase {
    private func response(_ n: Int = 1) -> SourceStreamsResponse {
        SourceStreamsResponse(sources: [SourceStreamsSource(id: "x", streams: [SourceStream(id: "x.bookmarks", label: "B", count: n)])])
    }

    func testAFirstReadHoldsTheAnswerAndItsTag() async {
        var seen: [String?] = []
        let model = SourceStreamsModel { etag in
            seen.append(etag)
            return Conditional(value: self.response(), etag: "\"v1\"", notModified: false)
        }
        XCTAssertEqual(model.phase, .idle)
        await model.refresh()
        XCTAssertEqual(model.phase, .loaded)
        XCTAssertEqual(model.source("x")?.streams.first?.count, 1)
        await model.refresh()
        XCTAssertEqual(seen, [nil, "\"v1\""], "an ETag only once something is held to keep")
    }

    func testA304KeepsWhatIsHeld() async {
        var calls = 0
        let model = SourceStreamsModel { _ in
            calls += 1
            return calls == 1 ? Conditional(value: self.response(), etag: "\"v1\"", notModified: false)
                              : Conditional(value: nil, etag: "\"v1\"", notModified: true)
        }
        await model.refresh()
        await model.refresh()
        XCTAssertEqual(model.source("x")?.streams.first?.count, 1)
        XCTAssertEqual(model.phase, .loaded)
    }

    func testAFailureKeepsWhatIsHeldAndNeverBlanks() async {
        var calls = 0
        let model = SourceStreamsModel { _ in
            calls += 1
            if calls == 1 { return Conditional(value: self.response(), etag: "t", notModified: false) }
            throw APIError.serverUnreachable
        }
        await model.refresh()
        await model.refresh()
        XCTAssertNotNil(model.value, "never blank (DR-43)")
        XCTAssertEqual(model.phase, .loaded)
    }

    func testAFailureWithNothingHeldIsFailedAndTheCatalogueRowStands() async {
        let model = SourceStreamsModel { _ in throw APIError.serverUnreachable }
        await model.refresh()
        XCTAssertEqual(model.phase, .failed)
        XCTAssertNil(model.value)
    }

    func testA404IsNoStreamsYetAndEmptiesWhatWasHeld() async {
        var calls = 0
        let model = SourceStreamsModel { _ in
            calls += 1
            if calls == 1 { return Conditional(value: self.response(), etag: "t", notModified: false) }
            throw APIError.httpError(404, "Not Found")
        }
        await model.refresh()
        XCTAssertNotNil(model.value)
        await model.refresh()
        XCTAssertEqual(model.phase, .absent)
        XCTAssertNil(model.value, "an endpoint that is gone has no stale streams to draw")
        XCTAssertNil(model.source("x"))
    }

    func testAnAnswerInFlightAcrossABankSwitchIsDropped() async {
        var model: SourceStreamsModel!
        model = SourceStreamsModel { _ in
            model.reset()   // the switch happens while the read is out
            return Conditional(value: self.response(9), etag: "t", notModified: false)
        }
        await model.refresh()
        XCTAssertNil(model.value, "another bank's counts never draw in this one")
        XCTAssertEqual(model.phase, .idle)
    }

    func testACheckAnswerReplacesWhatIsHeldAndDropsTheTag() async {
        var seen: [String?] = []
        let model = SourceStreamsModel { etag in
            seen.append(etag)
            return Conditional(value: self.response(1), etag: "t", notModified: false)
        }
        await model.refresh()
        model.apply(response(7))
        XCTAssertEqual(model.source("x")?.streams.first?.count, 7)
        await model.refresh()
        XCTAssertEqual(seen, [nil, nil], "the tag named a body that is no longer the one held")
    }

    func testAnOlderSlowerReadNeverReplacesANewerOne() async {
        var releaseFirst: CheckedContinuation<Void, Never>?
        var calls = 0
        let model = SourceStreamsModel { _ in
            calls += 1
            if calls == 1 { await withCheckedContinuation { releaseFirst = $0 } }
            return Conditional(value: self.response(calls == 1 ? 1 : 2), etag: "t\(calls)", notModified: false)
        }
        let first = Task { await model.refresh() }
        await Task.yield()
        await model.refresh()
        releaseFirst?.resume()
        await first.value
        XCTAssertEqual(model.source("x")?.streams.first?.count, 2)
    }
}
