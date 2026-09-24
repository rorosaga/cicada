import XCTest
@testable import CicadaApp

/// G147 (plan R-FD6 … R-FD8) — Settings → Memory's pace rows. The wire decodes leniently,
/// the rows are a pure function of the response and the viewer's "Not now"s, and the copy
/// says each number once, in plain words.
final class DecayTuningTests: XCTestCase {
    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    private let us = Locale(identifier: "en_US")

    private func suggestion(type: String = "person", direction: DecaySuggestion.Direction = .slower,
                            kept: Int = 9, archived: Int = 1) -> DecaySuggestion {
        DecaySuggestion(type: type, direction: direction, multiplier: direction == .slower ? 0.5 : 1.5,
                        kept: kept, archived: archived, answers: kept + archived)
    }

    // MARK: Wire

    func testTheResponseDecodesAndDropsOnlyTheSuggestionItCannotRead() throws {
        let json = """
        {"bank": "memory", "windowDays": 180, "tuning": {"tool": 1.5},
         "suggestions": [
           {"type": "person", "direction": "slower", "multiplier": 0.5, "kept": 9, "archived": 1, "answers": 10},
           {"type": "person", "direction": "sideways", "multiplier": 0.5, "kept": 9, "archived": 1, "answers": 10}
         ]}
        """.data(using: .utf8)!
        let r = try JSONDecoder().decode(DecayTuningResponse.self, from: json)
        XCTAssertEqual(r.bank, "memory")
        XCTAssertEqual(r.tuning, ["tool": 1.5])
        XCTAssertEqual(r.suggestions, [suggestion()])
    }

    func testAnEmptyBodyStillDecodes() throws {
        let r = try JSONDecoder().decode(DecayTuningResponse.self, from: Data("{}".utf8))
        XCTAssertEqual(r.suggestions, [])
        XCTAssertEqual(r.tuning, [:])
        XCTAssertEqual(r.windowDays, 180)
    }

    // MARK: Rows

    func testSuggestionsComeFirstThenChosenPacesAndNeverATypeTwice() {
        let r = DecayTuningResponse(bank: "memory", tuning: ["person": 1.5, "tool": 0.5],
                                    suggestions: [suggestion()])
        let rows = DecayTuningModel.rows(r, notNow: [:])
        XCTAssertEqual(rows.map(\.type), ["person", "tool"])
        XCTAssertEqual(rows[0].kind, .suggestion(suggestion()))
        XCTAssertEqual(rows[0].current, 1.5)
        XCTAssertEqual(rows[1].kind, .tuned(0.5))
    }

    func testNotNowHidesASuggestionUntilFiveMoreAnswersPerBank() {
        let s = suggestion()
        let notNow = [DecayTuningModel.notNowID(bank: "memory", s): 10]
        XCTAssertTrue(DecayTuningModel.isHidden(s, bank: "memory", notNow: notNow))
        XCTAssertTrue(DecayTuningModel.isHidden(suggestion(kept: 13), bank: "memory", notNow: notNow))
        XCTAssertFalse(DecayTuningModel.isHidden(suggestion(kept: 14), bank: "memory", notNow: notNow))
        XCTAssertFalse(DecayTuningModel.isHidden(s, bank: "other", notNow: notNow), "a Not now is per bank")
        let r = DecayTuningResponse(bank: "memory", tuning: ["person": 1.5], suggestions: [s])
        XCTAssertEqual(DecayTuningModel.rows(r, notNow: notNow).map(\.kind), [.tuned(1.5)],
                       "a hidden suggestion leaves the chosen pace's own row")
    }

    func testNotNowRoundTripsAndToleratesJunk() {
        let map = ["memory|person|slower": 10]
        XCTAssertEqual(DecayTuningModel.decodeNotNow(DecayTuningModel.encodeNotNow(map)), map)
        XCTAssertEqual(DecayTuningModel.decodeNotNow("not json"), [:])
        XCTAssertEqual(DecayTuningModel.decodeNotNow(""), [:])
    }

    // MARK: Copy (DR-21, DR-59)

    func testCopySaysEachNumberOnceInPlainWords() {
        XCTAssertEqual(FadeWords.suggestionTitle(suggestion()), "Let people fade more slowly?")
        XCTAssertEqual(FadeWords.suggestionDetail(suggestion(), current: nil, locale: us),
                       "You kept 9 of the 10 people Cicada asked about.")
        XCTAssertEqual(FadeWords.suggestionDetail(suggestion(kept: 7, archived: 0), current: nil, locale: us),
                       "You kept all 7 people Cicada asked about.")
        let faster = suggestion(type: "concept", direction: .faster, kept: 1, archived: 1200)
        XCTAssertEqual(FadeWords.suggestionTitle(faster), "Let ideas fade more quickly?")
        XCTAssertEqual(FadeWords.suggestionDetail(faster, current: 0.5, locale: us),
                       "You archived 1,200 of the 1,201 ideas Cicada asked about. Right now they fade more slowly.")
        XCTAssertEqual(FadeWords.tunedTitle(type: "company", multiplier: 0.5), "Companies fade more slowly")
        XCTAssertEqual(FadeWords.tunedTitle(type: "mystery", multiplier: 1.5), "Pages fade more quickly")
    }

    func testEveryKindHasAPlainNoun() {
        for type in EntityType.allCases {
            XCTAssertFalse(FadeWords.noun(type.rawValue, count: 2).isEmpty, type.rawValue)
        }
        XCTAssertEqual(FadeWords.noun("person", count: 1), "person")
        XCTAssertEqual(FadeWords.noun("location", count: 2), "places")
    }

    func testNoCopyCarriesAPercentSign() {
        let texts = [FadeWords.suggestionTitle(suggestion()),
                     FadeWords.suggestionDetail(suggestion(), current: 0.5, locale: us),
                     FadeWords.tunedTitle(type: "person", multiplier: 0.5), FadeWords.tunedDetail,
                     Copy.fadePaceDetail, Copy.fadeHeader, Copy.fadePaceTitle]
        for text in texts { XCTAssertFalse(text.contains("%"), text) }
    }

    // MARK: APIClient

    private static func body(_ request: URLRequest) -> [String: Any] {
        let data = request.httpBodyStream.map { stream -> Data in
            stream.open()
            defer { stream.close() }
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable {
                let read = stream.read(&buffer, maxLength: 1024)
                if read <= 0 { break }
                data.append(buffer, count: read)
            }
            return data
        } ?? request.httpBody ?? Data()
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    private static let reply = """
    {"bank": "memory", "windowDays": 180, "tuning": {}, "suggestions": []}
    """.data(using: .utf8)!

    func testFetchReadsTheSuggestionsEndpoint() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/memory/decay-suggestions")
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Self.reply)
        }
        let r = try await APIClient(session: MockURLProtocol.makeSession()).fetchDecayTuning()
        XCTAssertEqual(r.bank, "memory")
    }

    func testSetSendsThePaceAndANullToClear() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.url?.path, "/memory/decay-tuning")
            let body = Self.body(request)
            XCTAssertEqual(body["person"] as? Double, 0.5)
            XCTAssertTrue(body["tool"] is NSNull, "nil clears a type")
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Self.reply)
        }
        _ = try await APIClient(session: MockURLProtocol.makeSession())
            .setDecayTuning(["person": 0.5, "tool": nil])
    }

    // MARK: The page

    func testMemoryHostsHowThingsFade() throws {
        let view = try ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "MemoryView.swift" }
        XCTAssertTrue(try String(contentsOf: XCTUnwrap(view), encoding: .utf8).contains("FadePaceCard()"))
    }
}
