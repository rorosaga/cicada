import XCTest
@testable import CicadaApp

/// G245 (plan 2.1) — the streams contract decoded as the backend sends it, and leniently when it sends more or less.
final class SourceStreamsTests: XCTestCase {
    private func decode(_ json: String) throws -> SourceStreamsResponse {
        try JSONDecoder().decode(SourceStreamsResponse.self, from: Data(json.utf8))
    }

    func testTheContractFixtureDecodesEveryField() throws {
        let response = try SourceStreamsFixture.load()
        XCTAssertEqual(response.sources.map(\.id),
                       ["x", "youtube", "linkedin", "notes", "browser:chrome", "github", "imessage"])
        let x = try XCTUnwrap(response.source("x"))
        XCTAssertEqual(x.label, "X")
        XCTAssertEqual(x.account, StreamAccount(handle: "@alpha-account", profileUrl: "https://x.com/alpha-account"))
        XCTAssertEqual(x.streams.map(\.id), ["x.bookmarks", "x.likes", "x.saves"], "the site's own order")
        let bookmarks = x.streams[0]
        XCTAssertEqual(bookmarks.label, "Bookmarks")
        XCTAssertEqual(bookmarks.kind, .saved)
        XCTAssertEqual(bookmarks.how, .browser)
        XCTAssertEqual(bookmarks.owner, .backend)
        XCTAssertEqual(bookmarks.control, .switch)
        XCTAssertEqual(bookmarks.state, .on)
        XCTAssertEqual(bookmarks.health, .read)
        XCTAssertEqual(bookmarks.lastReadAt, ISODate.parse("2026-11-24T08:10:00Z"))
        XCTAssertNil(bookmarks.pausedUntil)
        XCTAssertNil(bookmarks.checkRequestedAt)
        XCTAssertEqual(bookmarks.count, 214)
        XCTAssertEqual(bookmarks.folderCount, 3)
        XCTAssertEqual(bookmarks.depth, .index)
        XCTAssertEqual(bookmarks.switchRef, StreamSwitch(setting: "savedLists", key: "x"))
        XCTAssertNil(bookmarks.why)
        XCTAssertEqual(bookmarks.tail, "bookmarks")
    }

    /// The merged backend's own answer (`api/services/source_streams.py`): a top-level `shape`, a `channel` on every stream,
    /// and, from the check route only, `checked` — one `{stream, result}` per stream asked about.
    func testTheBackendsOwnShapeAndTheCheckedResultsDecode() throws {
        let answer = try decode("""
            {"shape": "streams-1", "sources": [{"id": "x", "label": "X", "account": null, "streams": [
              {"id": "x.bookmarks", "label": "Bookmarks", "kind": "saved", "how": "browser", "owner": "backend",
               "control": "switch", "state": "on", "health": null, "lastReadAt": null, "pausedUntil": null,
               "checkRequestedAt": "2026-11-24T09:00:00Z", "count": 3, "folderCount": 0, "depth": "index",
               "switch": {"setting": "savedLists", "key": "x"}, "why": null, "channel": "x"}]}],
             "checked": [{"stream": "x.bookmarks", "result": "requested"}, {"stream": "x.saves-you-make", "result": "noted"},
                         {"bad": 1}]}
            """)
        XCTAssertEqual(answer.source("x")?.streams.first?.id, "x.bookmarks")
        XCTAssertEqual(answer.checked, ["x.bookmarks": "requested", "x.saves-you-make": "noted"],
                       "a malformed entry is dropped alone")
        XCTAssertEqual(try decode(#"{"sources": []}"#).checked, [:], "the GET carries none")
    }

    func testNullsAndTheClickStreamDecodeAsNothing() throws {
        let response = try SourceStreamsFixture.load()
        let saves = try XCTUnwrap(response.source("x")?.streams.last)
        XCTAssertEqual(saves.how, .click)
        XCTAssertEqual(saves.owner, .app)
        XCTAssertNil(saves.count, "a null count is unknown, never zero")
        XCTAssertNil(saves.health)
        XCTAssertNil(saves.switchRef)
        XCTAssertNil(response.source("youtube")?.account)
        XCTAssertEqual(response.source("youtube")?.streams[0].pausedUntil, ISODate.parse("2026-11-26T00:00:00Z"))
        XCTAssertEqual(response.source("imessage")?.streams[0].why, "Messages needs Full Disk Access.")
        XCTAssertEqual(response.source("imessage")?.streams[0].control, .setup)
    }

    func testEveryKindTheContractNamesIsKnownAndOnlyTheListKindsAreLists() {
        let names = ["saved", "liked", "reposted", "history", "later", "playlists", "connections", "notes", "pages",
                     "chats", "events", "tasks", "code", "books", "feed", "files"]
        for name in names {
            let kind = StreamKind(rawValue: name)
            XCTAssertEqual(kind.rawValue, name)
            if case .other = kind { XCTFail("\(name) is a contract kind") }
        }
        XCTAssertEqual(Set(names.filter { StreamKind(rawValue: $0).isList }),
                       ["saved", "liked", "reposted", "history", "later", "playlists"], "plan 3.2 item 3")
    }

    // MARK: Leniency

    func testAnUnknownKindWayHealthStateDepthAndFieldNeverFailThePage() throws {
        let response = try decode("""
        {"sources": [{"id": "x", "label": "X", "futureField": 1, "streams": [
          {"id": "x.polls", "label": "Polls", "kind": "polls", "how": "telepathy", "owner": "robot",
           "control": "dial", "state": "maybe", "health": "rate_limited", "depth": "frames", "count": 5,
           "newField": {"a": 1}}
        ]}]}
        """)
        let s = try XCTUnwrap(response.sources.first?.streams.first)
        XCTAssertEqual(s.kind, .other("polls"))
        XCTAssertFalse(s.kind.isList)
        XCTAssertEqual(s.how, .other("telepathy"))
        XCTAssertEqual(s.owner, .backend, "an unknown owner is the backend's, whose word is the wire's")
        XCTAssertEqual(s.control, .setup, "never a switch this build cannot drive")
        XCTAssertEqual(s.state, .off, "never claims on")
        XCTAssertNil(s.health, "a word this build does not know is no word")
        XCTAssertEqual(s.depth, .index, "the lighter claim")
        XCTAssertEqual(s.count, 5)
    }

    func testAMissingOptionalFieldTakesItsDefault() throws {
        let response = try decode(#"{"sources": [{"id": "x", "streams": [{"id": "x.bookmarks"}]}]}"#)
        let source = try XCTUnwrap(response.sources.first)
        XCTAssertEqual(source.label, "x")
        let s = try XCTUnwrap(source.streams.first)
        XCTAssertEqual(s.label, "bookmarks", "the id's tail when the stream sends no name")
        XCTAssertEqual(s.state, .off)
        XCTAssertEqual(s.folderCount, 0)
        XCTAssertNil(s.count)
    }

    func testABadStreamOrSourceIsDroppedAloneAndTheRestStay() throws {
        let response = try decode("""
        {"sources": [
          {"label": "no id"},
          {"id": "x", "streams": [{"label": "no id"}, {"id": "x.likes", "count": "many"}, 7, {"id": "x.bookmarks"}]},
          "nonsense",
          {"id": "y", "streams": "not a list"}
        ]}
        """)
        XCTAssertEqual(response.sources.map(\.id), ["x", "y"])
        XCTAssertEqual(response.source("x")?.streams.map(\.id), ["x.likes", "x.bookmarks"])
        XCTAssertNil(response.source("x")?.streams.first?.count, "a count that is not a number is unknown")
        XCTAssertEqual(response.source("y")?.streams, [])
    }

    func testAnEmptyOrWrongAnswerIsNoSources() throws {
        XCTAssertEqual(try decode("{}").sources, [])
        XCTAssertEqual(try decode(#"{"sources": 3}"#).sources, [])
        XCTAssertEqual(try decode(#"{"sources": []}"#).sources, [])
    }

    func testAnAccountWithNothingInItIsNoAccount() throws {
        let response = try decode(#"{"sources": [{"id": "x", "account": {"handle": null}, "streams": []}]}"#)
        XCTAssertNil(response.sources.first?.account)
    }

    func testASwitchNeedsBothItsWords() throws {
        let response = try decode("""
        {"sources": [{"id": "x", "streams": [
          {"id": "x.a", "switch": {"setting": "savedLists"}},
          {"id": "x.b", "switch": {"setting": "savedLists", "key": ""}},
          {"id": "x.c", "switch": {"setting": "savedLists", "key": "x"}}
        ]}]}
        """)
        XCTAssertEqual(response.sources[0].streams.map(\.switchRef), [nil, nil, StreamSwitch(setting: "savedLists", key: "x")])
    }

    // MARK: Words

    func testTheRestingWordFollowsTheWireInTheOrderThePlanSays() {
        let now = SourceStreamsFixture.now
        func word(_ health: StreamHealth?, state: StreamState = .on, how: StreamHow = .browser,
                  last: Date? = nil, paused: Date? = nil, checked: Date? = nil) -> StreamWord {
            .resting(SourceStream(id: "x.a", label: "A", how: how, state: state, health: health, lastReadAt: last,
                                  pausedUntil: paused, checkRequestedAt: checked), now: now)
        }
        XCTAssertEqual(word(.read), .read)
        XCTAssertEqual(word(nil), .notReadYet)
        XCTAssertEqual(word(nil, last: now), .read, "a dated read with no word said is a read")
        XCTAssertEqual(word(.notRead), .notReadYet)
        XCTAssertEqual(word(.couldntRead), .couldntRead)
        XCTAssertEqual(word(.signedOut), .signedOut)
        XCTAssertEqual(word(.read, state: .off), .off)
        XCTAssertEqual(word(.read, state: .unavailable), .unavailable)
        XCTAssertEqual(word(.paused), .paused)
        XCTAssertEqual(word(.read, paused: now.addingTimeInterval(60)), .paused, "paused while the pause runs")
        XCTAssertEqual(word(.read, paused: now.addingTimeInterval(-60)), .read, "and read once it has passed")
        XCTAssertEqual(word(.read, checked: now), .yourAIAppReadsNext, "a browser list asked to be read next")
        XCTAssertEqual(word(.read, how: .account, checked: now), .read, "only a browser list waits on the AI app")
    }

    func testACheckNeverLiftsAPause() {
        let now = SourceStreamsFixture.now
        let asked = SourceStream(id: "x.a", label: "A", how: .browser, state: .on, health: .signedOut,
                                 pausedUntil: now.addingTimeInterval(3600), checkRequestedAt: now)
        XCTAssertEqual(StreamWord.resting(asked, now: now), .signedOut)
    }

    func testTheToneIsBlueForABrowserReadGreenForAnyOtherAndAmberWhenThePersonHasSomethingToDo() {
        XCTAssertEqual(StreamWord.read.tone(how: .browser), .browser)
        XCTAssertEqual(StreamWord.read.tone(how: .app), .on)
        XCTAssertEqual(StreamWord.signedOut.tone(how: .browser), .attention)
        XCTAssertEqual(StreamWord.needsAccess.tone(how: .app), .attention)
        XCTAssertEqual(StreamWord.off.tone(how: .browser), .off)
    }

    func testTheSixCheckWordsAreExactlyThePlansAndEveryWordHasText() {
        let six: [StreamWord] = [.read, .signedOut, .couldntRead, .needsAccess, .yourAIAppReadsNext, .notInstalled]
        XCTAssertEqual(six.map(\.text),
                       ["Read", "Signed out", "Couldn't read", "Needs access", "Your AI app reads it next", "Not installed"])
        XCTAssertTrue(six.allSatisfy(\.isCheckWord))
        for rest in [StreamWord.notReadYet, .paused, .off, .unavailable] {
            XCTAssertFalse(rest.isCheckWord)
            XCTAssertFalse(rest.text.isEmpty)
        }
    }
}
