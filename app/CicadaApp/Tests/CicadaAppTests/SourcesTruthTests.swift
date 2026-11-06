import XCTest
@testable import CicadaApp

/// sources-truth (2026-11-06) — what every catalog entry says in each state, pinned for all of them at once: an empty
/// bank reads nothing connected, a connection reads only on its own entry, a sign-in failure is a refusal and nothing
/// else, and a list the person turned on waits for an agent until one is here.
final class SourcesTruthTests: XCTestCase {
    private let entries = SourceCatalog.entries(browsers: [], wisprPresent: true, hexPresent: true, overview: [])

    private func rows(channels: [SourceChannel] = [], on: Set<String> = [], agent: Bool = false) -> [SourceCatalogRow] {
        SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                           savedListsOn: on, localAgent: agent)
    }

    func testAnEmptyBankReadsNoSourceConnected() {
        for row in rows() {
            XCTAssertEqual(row.status, .off, "\(row.id) must not read \(row.status) with nothing in memory and nothing on")
            XCTAssertFalse(row.isConnectedHere, row.id)
        }
        XCTAssertEqual(SourceCatalog.connectedCount(rows()), 0)
    }

    func testAChannelConnectedConnectsItsOwnEntryAndNoOtherOne() throws {
        let owners = Dictionary(grouping: entries.flatMap { e in e.channels.map { ($0, e.id) } }, by: { $0.0 })
        for (channel, pairs) in owners where channel != "files" {
            let connected = SourceChannel(id: channel, label: channel, connected: true, count: 3)
            let result = rows(channels: [connected])
            let mine = Set(pairs.map(\.1))
            for row in result where row.status == .connected {
                XCTAssertTrue(mine.contains(row.id), "\(channel) connected made \(row.id) Connected")
            }
        }
    }

    func testASignInFailureOnASignInSourceIsNeedsSignInAndAnyOtherFailureIsNot() throws {
        for id in SourceCatalog.signInChannels {
            let refused = SourceChannel(id: id, label: id, connected: true, lastError: "HTTPStatusError: HTTP 401")
            XCTAssertTrue(rows(channels: [refused]).contains { $0.status == .needsSignIn }, id)
            let slow = SourceChannel(id: id, label: id, connected: true, lastError: "ReadTimeout: timed out")
            XCTAssertFalse(rows(channels: [slow]).contains { $0.status == .needsSignIn }, id)
            let count = SourceChannel(id: id, label: id, connected: true, lastError: "1403 item(s) failed to ingest")
            XCTAssertFalse(rows(channels: [count]).contains { $0.status == .needsSignIn }, id)
        }
    }

    func testEverySavedListOnWaitsForAnAgentAndNeverReadsConnectedWithoutOne() throws {
        for key in SourceCatalog.savedListSites {
            let waiting = rows(on: [key], agent: false)
            XCTAssertEqual(waiting.first { $0.entry.savedListKey == key }?.status, .waitingForAgent, key)
            XCTAssertEqual(SourceCatalog.connectedCount(waiting), 0, "\(key): waiting is not connected")
        }
    }
}
