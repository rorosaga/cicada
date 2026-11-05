import XCTest
@testable import CicadaApp

/// Proposed ruling 55: the same number, the same token as `phone_numbers.py`
/// (`test_the_app_and_the_backend_compute_one_token`); synthetic numbers only.
final class PhoneNumberKeysTests: XCTestCase {
    private let key = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="

    func testTheBackendsVector() {
        XCTAssertEqual(PhoneNumberKeys.matchDigits("+1 202 555 0143"), "025550143")
        XCTAssertEqual(PhoneNumberKeys.tokenId(keyBase64: key, number: "+1 202 555 0143"), "zgjpbdixkc")
    }

    func testWrittenDifferentlyIsOneKey() {
        let keys = PhoneNumberKeys.keys(keyBase64: key, numbers: ["+1 202 555 0143", "(202) 555-0143", "202.555.0143"])
        XCTAssertEqual(keys, ["zgjpbdixkc"])
    }

    func testNotANumberAndNoKeyPostNothing() {
        XCTAssertEqual(PhoneNumberKeys.keys(keyBase64: key, numbers: ["12", "12345678901234567"]), [])
        XCTAssertEqual(PhoneNumberKeys.keys(keyBase64: nil, numbers: ["+1 202 555 0143"]), [])
    }

    func testACardWithNoKeysCrossesTheWireExactlyAsBefore() throws {
        let record = ContactMapper.record(id: "C1", given: "Bob", family: "Example", organization: "", jobTitle: "",
                                          emails: 0, phones: 1, hasBirthday: false, thumbnail: nil)
        let wire = try XCTUnwrap(String(data: JSONEncoder().encode(record), encoding: .utf8))
        XCTAssertFalse(wire.contains("phoneKeys"))
    }

    func testAKeyedCardHoldsTheHashNeverTheNumber() throws {
        let record = ContactMapper.record(id: "C1", given: "Bob", family: "Example", organization: "", jobTitle: "",
                                          emails: 0, phones: 1, hasBirthday: false, thumbnail: nil,
                                          phoneKeys: PhoneNumberKeys.keys(keyBase64: key, numbers: ["+1 202 555 0143"]))
        let wire = try XCTUnwrap(String(data: JSONEncoder().encode(record), encoding: .utf8))
        XCTAssertTrue(wire.contains("zgjpbdixkc"))
        XCTAssertFalse(wire.contains("555"))
    }
}
