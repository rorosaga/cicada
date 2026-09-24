import XCTest
@testable import CicadaApp

/// G147 (plan R-FD9, R-FD10) — the entity card says the pace Sleep actually charges, in words.
final class FadeWordsTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func decay(_ cls: DecayClass, _ rate: Double, _ weeks: Int) -> EntityDecay {
        EntityDecay(decayClass: cls, effectiveRatePerWeek: rate, mentionWeeks: weeks)
    }

    func testPaceThresholdsAreAnchoredOnTheActiveRate() {
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0), .never)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.0125), .verySlowly, "the spacing floor on an active page")
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.0126), .slowly)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.03), .slowly)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.05), .usual)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.0799), .usual)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.08), .quickly)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.15), .quickly)
    }

    func testTheDetailsRowSaysThePaceAndTheWeeks() {
        XCTAssertEqual(FadeWords.detail(decay(.active, 0.020073, 12), fallback: .active, locale: us),
                       "Slowly — mentioned across 12 weeks")
        XCTAssertEqual(FadeWords.detail(decay(.active, 0.05, 1), fallback: .active, locale: us),
                       "At the usual pace — mentioned in a single week")
        XCTAssertEqual(FadeWords.detail(decay(.durable, 0.010918, 4), fallback: .durable, locale: us),
                       "Very slowly — mentioned across 4 weeks")
        XCTAssertEqual(FadeWords.detail(decay(.evergreen, 0, 30), fallback: .evergreen, locale: us), "Never")
        XCTAssertEqual(FadeWords.detail(decay(.volatile, 0.15, 0), fallback: .volatile, locale: us), "Quickly")
        XCTAssertEqual(FadeWords.detail(decay(.active, 0.0125, 1200), fallback: .active, locale: us),
                       "Very slowly — mentioned across 1,200 weeks")
    }

    func testAnOlderBackendKeepsTheClassWords() {
        XCTAssertEqual(FadeWords.detail(nil, fallback: .durable, locale: us), DetailsWords.fades(.durable))
        XCTAssertEqual(FadeWords.detail(nil, fallback: .active, locale: us), "If it stops coming up")
    }

    private func entityJSON(_ decay: String?) -> Data {
        let block = decay.map { #", "decay": \#($0)"# } ?? ""
        return """
        {"id": "mongodb", "name": "MongoDB", "type": "tool", "status": "active",
         "confidence": 0.8, "created": "2026-01-01", "lastReferenced": "2026-08-01",
         "decayRate": 0.05, "decayClass": "active", "version": 1,
         "markdownContent": "", "history": []\(block)}
        """.data(using: .utf8)!
    }

    func testTheEntityDecodesTheDecayBlock() throws {
        let entity = try JSONDecoder().decode(Entity.self, from: entityJSON(
            #"{"class": "active", "effectiveRatePerWeek": 0.020073, "mentionWeeks": 12}"#))
        XCTAssertEqual(entity.decay, EntityDecay(decayClass: .active, effectiveRatePerWeek: 0.020073, mentionWeeks: 12))
    }

    func testAMissingOrBrokenBlockIsNilAndAnUnknownClassIsActive() throws {
        XCTAssertNil(try JSONDecoder().decode(Entity.self, from: entityJSON(nil)).decay)
        XCTAssertNil(try JSONDecoder().decode(Entity.self, from: entityJSON(#"{"class": "active"}"#)).decay)
        let glacial = try JSONDecoder().decode(Entity.self, from: entityJSON(
            #"{"class": "glacial", "effectiveRatePerWeek": 0.05, "mentionWeeks": 2}"#))
        XCTAssertEqual(glacial.decay?.decayClass, .active)
    }

    func testTheCardsFadesRowReadsTheEffectivePace() throws {
        let card = try ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "EntityDetailCard.swift" }
        let text = try String(contentsOf: XCTUnwrap(card), encoding: .utf8)
        XCTAssertTrue(text.contains("FadeWords.detail(entity.decay, fallback: entity.decayClass)"))
    }
}
