import XCTest
@testable import CicadaApp

/// G132 phase 2 — the Sleep page's strip of the memory's home: decoded from `GET /sync/home`, its words, when it
/// offers a move, and the model's acts (a move, a take-over shown before it is confirmed). Synthetic names only.
@MainActor
final class HomeStripTests: XCTestCase {
    private let sharedJSON = """
    {"shared": true, "role": "home", "bankId": "b", "term": 1,
     "home": {"id": "aaaaaaaa", "name": "alpha-desk", "me": true, "online": true, "seq": 40,
              "sleep": {"status": "running", "stage": 1, "totalStages": 5}},
     "devices": [{"id": "bbbbbbbb", "name": "bravo-laptop", "me": false, "online": true, "keepsCopy": true,
                  "behind": 3, "lastSeenAt": null, "canBeHome": true},
                 {"id": "cccccccc", "name": "charlie-phone", "me": false, "online": false, "keepsCopy": false,
                  "behind": null, "lastSeenAt": null, "canBeHome": false}],
     "moving": null, "takeOver": null,
     "setAside": {"text": "2 changes made on this computer after bravo-laptop took over are kept aside here."},
     "note": null}
    """

    private func overview(_ json: String) throws -> HomeOverview {
        try JSONDecoder().decode(HomeOverview.self, from: Data(json.utf8))
    }

    func testOneComputerThatSharesNothingDrawsNothing() async throws {
        let local = try overview(#"{"shared": false, "role": "local"}"#)
        XCTAssertFalse(local.shared)
        XCTAssertTrue(local.devices.isEmpty)
        let model = HomeStripModel(fetch: { local }, move: { _ in }, fetchPreview: { TakeOverPreview(possible: false) },
                                   confirmTakeOver: { _ in })
        await model.load()
        XCTAssertFalse(model.isShown)
    }

    func testTheStripNamesTheHomeAndEachDevicesLag() throws {
        let o = try overview(sharedJSON)
        XCTAssertEqual(HomeStrip.homeLine(o.home!), "Sleep runs on alpha-desk · this computer · consolidating, stage 2 of 5")
        XCTAssertEqual(HomeStrip.deviceLine(o.devices[0]), "bravo-laptop · online · 3 changes behind")
        XCTAssertEqual(HomeStrip.deviceLine(o.devices[1]), "charlie-phone · offline · keeps no copy")
        XCTAssertTrue(HomeStrip.offersMove(o.devices[0], in: o))
        XCTAssertFalse(HomeStrip.offersMove(o.devices[1], in: o))
        XCTAssertEqual(HomeStrip.notes(o).count, 1)
        var idle = o.home!
        idle.sleep = HomeOverview.SleepLine(status: "idle")
        idle.me = false
        idle.online = false
        XCTAssertEqual(HomeStrip.homeLine(idle), "Sleep runs on alpha-desk · not answering")
    }

    func testNoMoveIsOfferedWhileOneIsUnderWay() throws {
        var o = try overview(sharedJSON)
        o.moving = HomeOverview.Words(text: "Your memory is moving to bravo-laptop.", phase: "leaving")
        XCTAssertFalse(HomeStrip.offersMove(o.devices[0], in: o))
        o.moving = HomeOverview.Words(text: "Called off.", phase: "refused")
        XCTAssertTrue(HomeStrip.offersMove(o.devices[0], in: o))
    }

    func testAMoveSendsThePickedDeviceAndARefusalShowsItsSentence() async throws {
        let o = try overview(sharedJSON)
        var sent: [String] = []
        let model = HomeStripModel(fetch: { o }, move: { sent.append($0) }, fetchPreview: {
            TakeOverPreview(possible: false)
        }, confirmTakeOver: { _ in })
        await model.load()
        XCTAssertTrue(model.isShown)
        await model.makeHome(o.devices[0])
        XCTAssertEqual(sent, ["bbbbbbbb"])
        XCTAssertNil(model.problem)

        let refusing = HomeStripModel(fetch: { o }, move: { _ in
            throw APIError.httpError(409, #"{"code": "target_away", "detail": "bravo-laptop does not answer right now."}"#)
        }, fetchPreview: { TakeOverPreview(possible: false) }, confirmTakeOver: { _ in })
        await refusing.makeHome(o.devices[0])
        XCTAssertEqual(refusing.problem, "bravo-laptop does not answer right now.")
    }

    func testATakeOverIsShownFirstAndConfirmsTheNumberItShowed() async throws {
        let o = try overview(sharedJSON)
        var confirmed: [Int] = []
        let model = HomeStripModel(fetch: { o }, move: { _ in }, fetchPreview: {
            TakeOverPreview(possible: true, behind: 4, text: "This computer is 4 changes behind the last home it saw.")
        }, confirmTakeOver: { confirmed.append($0) })
        await model.askTakeOver()
        XCTAssertEqual(model.preview?.behind, 4)
        XCTAssertTrue(confirmed.isEmpty)                       // nothing happens before the person confirms
        await model.takeOver()
        XCTAssertEqual(confirmed, [4])
        XCTAssertNil(model.preview)

        let reachable = HomeStripModel(fetch: { o }, move: { _ in }, fetchPreview: {
            TakeOverPreview(possible: false, text: "alpha-desk answers, so it is not lost.", code: "home_reachable")
        }, confirmTakeOver: { _ in XCTFail("never confirmed") })
        await reachable.askTakeOver()
        XCTAssertNil(reachable.preview)
        XCTAssertEqual(reachable.problem, "alpha-desk answers, so it is not lost.")
    }

    func testAFailedPollKeepsTheLastAnswer() async throws {
        let o = try overview(sharedJSON)
        var fail = false
        let model = HomeStripModel(fetch: {
            if fail { throw APIError.serverUnreachable }
            return o
        }, move: { _ in }, fetchPreview: { TakeOverPreview(possible: false) }, confirmTakeOver: { _ in })
        await model.load()
        fail = true
        await model.load()
        XCTAssertEqual(model.overview, o)                      // never blank
    }
}
