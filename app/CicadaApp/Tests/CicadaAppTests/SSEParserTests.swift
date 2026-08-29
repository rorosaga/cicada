import XCTest
@testable import CicadaApp

final class SSEParserTests: XCTestCase {
    func testDispatchesOnBlankLine() {
        var p = SSEParser()
        XCTAssertNil(p.feed("event: version"))
        XCTAssertNil(p.feed("data: {\"version\":\"abc\"}"))
        XCTAssertEqual(p.feed(""), SSEEvent(name: "version", data: "{\"version\":\"abc\"}"))
        XCTAssertNil(p.feed(""))
    }
    func testMultiLineDataAndComments() {
        var p = SSEParser()
        _ = p.feed(": keepalive"); _ = p.feed("data: a"); _ = p.feed("data: b")
        XCTAssertEqual(p.feed(""), SSEEvent(name: "message", data: "a\nb"))
    }
}
