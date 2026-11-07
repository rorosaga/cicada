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

    private func model(fetch: @escaping () async throws -> HomeOverview,
                       move: @escaping (String) async throws -> HomeMoveAnswer = { _ in HomeMoveAnswer() },
                       preview: @escaping () async throws -> TakeOverPreview = { TakeOverPreview(possible: false) },
                       confirm: @escaping (Int) async throws -> Void = { _ in },
                       tries: Int = 1) -> HomeStripModel {
        HomeStripModel(fetch: fetch, move: move, fetchPreview: preview, confirmTakeOver: confirm, followTries: tries,
                       followEvery: 0)
    }

    func testOneComputerThatSharesNothingDrawsNothing() async throws {
        let local = try overview(#"{"shared": false, "role": "local"}"#)
        XCTAssertFalse(local.shared)
        XCTAssertTrue(local.devices.isEmpty)
        let m = model(fetch: { local })
        await m.load()
        XCTAssertFalse(m.isShown)
    }

    func testADeviceWithNoNameStillDecodes() throws {
        let o = try overview(#"{"shared": true, "devices": [{"id": "dddddddd", "keepsCopy": true}]}"#)
        XCTAssertEqual(o.devices.first?.name, "")
        XCTAssertFalse(o.devices.first?.canBeHome ?? true)
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
        let m = model(fetch: { o }, move: { sent.append($0); return HomeMoveAnswer() })
        await m.load()
        XCTAssertTrue(m.isShown)
        await m.makeHome(o.devices[0])
        XCTAssertEqual(sent, ["bbbbbbbb"])
        XCTAssertNil(m.problem)

        let refusing = model(fetch: { o }, move: { _ in
            throw APIError.httpError(409, #"{"code": "target_away", "detail": "bravo-laptop does not answer right now."}"#)
        })
        await refusing.makeHome(o.devices[0])
        XCTAssertEqual(refusing.problem, "bravo-laptop does not answer right now.")
    }

    /// Review of #570: a move pressed on a copy runs at the home, so the copy's own poll may say nothing of it. The
    /// 202's words show, no second move is offered, and the strip keeps asking until the poll names the new home.
    func testAMoveFromACopyStaysMovingUntilThePollNamesTheNewHome() async throws {
        let before = try overview(sharedJSON)
        var after = before
        after.home = HomeOverview.Home(id: "bbbbbbbb", name: "bravo-laptop", me: false, online: true, sleep: nil)
        var polls = 0
        var seenWhileMoving: [Bool] = []
        var m: HomeStripModel!
        m = model(fetch: {
            polls += 1
            if polls > 1 { seenWhileMoving.append(m.isMoving && m.movingLine == "Your memory is moving to bravo-laptop.") }
            return polls < 4 ? before : after
        }, move: { _ in HomeMoveAnswer(moving: HomeOverview.Words(text: "Your memory is moving to bravo-laptop.",
                                                                    phase: "starting")) }, tries: 10)
        await m.load()
        await m.makeHome(before.devices[0])
        XCTAssertEqual(polls, 4)                                 // it kept asking until bravo-laptop was the home
        XCTAssertEqual(seenWhileMoving, [true, true, true])     // moving, with the home's words, the whole time
        XCTAssertFalse(m.isMoving)
        XCTAssertEqual(m.overview?.home?.id, "bbbbbbbb")
    }

    func testATakeOverIsShownFirstAndConfirmsTheNumberItShowed() async throws {
        let o = try overview(sharedJSON)
        var confirmed: [Int] = []
        let m = model(fetch: { o }, preview: {
            TakeOverPreview(possible: true, behind: 4, text: "This computer is 4 changes behind the last home it saw.")
        }, confirm: { confirmed.append($0) })
        await m.askTakeOver()
        XCTAssertEqual(m.preview?.behind, 4)
        XCTAssertTrue(confirmed.isEmpty)                       // nothing happens before the person confirms
        await m.takeOver(behind: 4)
        XCTAssertEqual(confirmed, [4])
        XCTAssertNil(m.preview)

        let reachable = model(fetch: { o }, preview: {
            TakeOverPreview(possible: false, text: "alpha-desk answers, so it is not lost.", code: "home_reachable")
        }, confirm: { _ in XCTFail("never confirmed") })
        await reachable.askTakeOver()
        XCTAssertNil(reachable.preview)
        XCTAssertEqual(reachable.problem, "alpha-desk answers, so it is not lost.")
    }

    /// Review of #570: the dialog's dismissal clears the preview before the confirm's Task runs; the confirm still
    /// sends the number that was shown.
    func testATakeOverConfirmedAfterThePreviewWasClearedStillRuns() async throws {
        let o = try overview(sharedJSON)
        var confirmed: [Int] = []
        let m = model(fetch: { o }, preview: { TakeOverPreview(possible: true, behind: 2, text: "2 behind.") },
                      confirm: { confirmed.append($0) })
        await m.askTakeOver()
        let shown = m.preview!.behind!
        m.cancelTakeOver()                                     // what the binding's setter does on dismissal
        await m.takeOver(behind: shown)
        XCTAssertEqual(confirmed, [2])
    }

    /// Review of #570: a refusal's sentence stays through a move's own follow and goes at the next slow poll.
    func testARefusalClearsAtTheNextSlowPollOnly() async throws {
        let o = try overview(sharedJSON)
        let m = model(fetch: { o }, move: { _ in
            throw APIError.httpError(409, #"{"detail": "bravo-laptop does not answer right now."}"#)
        })
        await m.makeHome(o.devices[0])
        await m.load()                                        // an ordinary ask keeps it
        XCTAssertEqual(m.problem, "bravo-laptop does not answer right now.")
        await m.load(clearingProblem: true)                   // the page's slow poll answered
        XCTAssertNil(m.problem)
    }

    func testAFailedPollKeepsTheLastAnswer() async throws {
        let o = try overview(sharedJSON)
        var fail = false
        let m = model(fetch: {
            if fail { throw APIError.serverUnreachable }
            return o
        })
        await m.load()
        fail = true
        await m.load(clearingProblem: true)
        XCTAssertEqual(m.overview, o)                          // never blank
    }
}
